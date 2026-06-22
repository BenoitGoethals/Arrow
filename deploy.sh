#!/usr/bin/env bash
# Arrow deploy script
#
# Usage:
#   ./deploy.sh           # HTTP on port 6200
#   ./deploy.sh https     # HTTPS on port 6200 (self-signed cert)
#   ./deploy.sh down      # stop containers
#   ./deploy.sh restart   # restart without rebuilding
#   ./deploy.sh rebuild   # full no-cache rebuild
#   ./deploy.sh logs      # tail logs
#   ./deploy.sh status    # show container health
#   ./deploy.sh maps      # list MBTiles base-maps
#   ./deploy.sh db        # open psql shell on the PostgreSQL database
#   ./deploy.sh backup    # trigger an immediate pg_dump backup
#   ./deploy.sh wms       # print MapServer WMS GetCapabilities URL
#
# For HTTPS, set extra IPs in .env or export before running:
#   ARROW_WEB_EXTRA_IPS=78.21.255.210,192.168.0.240 ./deploy.sh https

set -euo pipefail
cd "$(dirname "$0")"

# Load .env
[ -f .env ] && export $(grep -v '^\s*#' .env | grep '=' | xargs) 2>/dev/null || true

PORT="${ARROW_HTTP_PORT:-6200}"

# ── PostgreSQL password ───────────────────────────────────────────────────────
# Generate a random password on first deploy and persist it in .env so every
# subsequent run (including docker compose up without deploy.sh) uses the same
# credentials. Never overwrite an already-set value.
ensure_pg_password() {
    if grep -q '^POSTGRES_PASSWORD=' .env 2>/dev/null; then
        export POSTGRES_PASSWORD
        POSTGRES_PASSWORD="$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
    else
        local pw
        pw="$(openssl rand -hex 24 2>/dev/null || LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 48)"
        echo "POSTGRES_PASSWORD=${pw}" >> .env
        export POSTGRES_PASSWORD="$pw"
        echo "==> generated POSTGRES_PASSWORD (saved to .env)"
    fi
}

# ── docker compose detection ─────────────────────────────────────────────────
require_compose() {
    if docker compose version >/dev/null 2>&1; then DC="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose"
    else echo "error: docker compose not installed" >&2; exit 1; fi
}

# ── Maps volume ───────────────────────────────────────────────────────────────
mkdir -p maps && chmod 0777 maps 2>/dev/null || true

list_maps() {
    echo "==> maps (./maps/)"
    compgen -G "maps/*.mbtiles" >/dev/null 2>&1 \
        && ls -lh maps/*.mbtiles 2>/dev/null | awk '{print "    "$NF" ("$(NF-4)")"}'  \
        || echo "    (none)"
}

# ── Self-signed cert generation ───────────────────────────────────────────────
# Writes data/ssl/web-cert.pem + web-key.pem via openssl.
# Covers 127.0.0.1, all local interfaces, and ARROW_WEB_EXTRA_IPS.
generate_cert() {
    local ssl_dir="./data/ssl"
    mkdir -p "$ssl_dir"

    # Collect all IPs
    local ips="127.0.0.1"
    for ip in $(hostname -I 2>/dev/null || true); do ips="$ips $ip"; done
    for ip in $(echo "${ARROW_WEB_EXTRA_IPS:-}" | tr ',' ' '); do
        [ -n "$ip" ] && ips="$ips $ip"
    done
    ips=$(echo "$ips" | tr ' ' '\n' | sort -u | grep -v '^$' | tr '\n' ' ')

    # Check if existing cert already covers all IPs
    if [ -f "$ssl_dir/web-cert.pem" ] && [ -f "$ssl_dir/web-key.pem" ]; then
        local ok=1
        for ip in $ips; do
            openssl x509 -in "$ssl_dir/web-cert.pem" -noout -text 2>/dev/null \
                | grep -q "IP Address:$ip" || ok=0
        done
        if [ "$ok" = "1" ]; then
            echo "==> TLS cert OK (reusing existing)"
            return
        fi
        echo "==> TLS cert missing IPs — regenerating"
        rm -f "$ssl_dir/web-cert.pem" "$ssl_dir/web-key.pem"
    fi

    # Build SAN
    local san="DNS:localhost"
    for ip in $ips; do san="$san,IP:$ip"; done

    # Write openssl config (works on LibreSSL/macOS and OpenSSL/Linux)
    local cfg; cfg="$(mktemp /tmp/arrow-ssl-XXXXXX.conf)"
    cat > "$cfg" << SSLCONF
[req]
distinguished_name = dn
x509_extensions    = san
prompt             = no
[dn]
CN = arrow
O  = Arrow
[san]
subjectAltName   = ${san}
basicConstraints = CA:TRUE
SSLCONF

    echo "==> Generating TLS cert (SANs: $san)"
    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$ssl_dir/web-key.pem" \
        -out    "$ssl_dir/web-cert.pem" \
        -days 3650 -config "$cfg" 2>/dev/null \
        || { echo "error: openssl failed"; exit 1; }
    rm -f "$cfg"
    echo "==> Cert written to $ssl_dir/"
}

# ── nginx.conf generation ─────────────────────────────────────────────────────
write_nginx_http() {
    local port="$1"
    cat > nginx.conf << EOF
server {
    listen ${port};
    server_name _;

    add_header X-Content-Type-Options  nosniff;
    add_header X-Frame-Options         SAMEORIGIN;
    add_header Permissions-Policy      "microphone=*, geolocation=*";

    # Backend REST
    location /api/ {
        proxy_pass         http://backend:6001/;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 120s;
    }

    # Stream WebSocket (Android camera producer: /api/streams/{id}/produce)
    location ~ ^/api/streams/ {
        rewrite ^/api/(.*)$ /\$1 break;
        proxy_pass         http://backend:6001;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 86400s;
    }

    # WebSocket endpoints (with or without /api prefix)
    location ~ ^/(api/)?(ws|mumble/voice) {
        rewrite ^/api/(.*)$ /\$1 break;
        proxy_pass         http://backend:6001;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 86400s;
    }

    # MapServer OGC WMS/WFS
    location /mapserver/ {
        proxy_pass         http://mapserver/cgi-bin/mapserv?;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 30s;
    }

    # Web dashboard
    location / {
        proxy_pass         http://web:6002;
        proxy_set_header   Host       \$host;
        proxy_set_header   X-Real-IP  \$remote_addr;
        proxy_read_timeout 120s;
    }
}
EOF
    echo "==> nginx.conf written (HTTP port $port)"
}

write_nginx_https() {
    local port="$1"
    cat > nginx.conf << EOF
# ── Shared TLS settings ────────────────────────────────────────────────────
ssl_certificate     /etc/nginx/ssl/web-cert.pem;
ssl_certificate_key /etc/nginx/ssl/web-key.pem;
ssl_protocols       TLSv1.2 TLSv1.3;
ssl_ciphers         HIGH:!aNULL:!MD5;
ssl_session_cache   shared:SSL:10m;
ssl_session_timeout 10m;

# ── Port ${port} — web dashboard (browser) ─────────────────────────────────
server {
    listen ${port} ssl;
    server_name _;

    add_header X-Content-Type-Options  nosniff;
    add_header X-Frame-Options         SAMEORIGIN;
    add_header Permissions-Policy      "microphone=*, geolocation=*";
    add_header Strict-Transport-Security "max-age=63072000";

    # Backend REST (browser uses /api prefix)
    location /api/ {
        proxy_pass         http://backend:6001/;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }

    # Stream WebSocket (Android camera producer: /api/streams/{id}/produce)
    location ~ ^/api/streams/ {
        rewrite ^/api/(.*)$ /\$1 break;
        proxy_pass         http://backend:6001;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 86400s;
    }

    # WebSocket — matches /ws, /api/ws, /mumble/voice, /api/mumble/voice
    # rewrite strips the /api prefix so backend always sees /ws or /mumble/voice
    location ~ ^/(api/)?(ws|mumble/voice) {
        rewrite ^/api/(.*)$ /\$1 break;
        proxy_pass         http://backend:6001;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 86400s;
    }

    # MapServer OGC WMS/WFS
    location /mapserver/ {
        proxy_pass         http://mapserver/cgi-bin/mapserv?;
        proxy_set_header   Host \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 30s;
    }

    # Web dashboard (Flask)
    location / {
        proxy_pass         http://web:6002;
        proxy_set_header   Host              \$host;
        proxy_set_header   X-Real-IP         \$remote_addr;
        proxy_set_header   X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}

# ── Port 6001 — FastAPI direct (Arrow Front desktop app) ───────────────────
# Arrow Front calls /auth/login, /missions, /ws etc. without /api prefix.
# This block exposes FastAPI directly over HTTPS so the desktop app can use
# https://SERVER:6001 as its server URL.
server {
    listen 6001 ssl;
    server_name _;

    add_header X-Content-Type-Options nosniff;

    # Stream WebSocket (Android / desktop camera producer)
    location ~ ^/streams/ {
        proxy_pass         http://backend:6001;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 86400s;
    }

    # WebSocket
    location ~ ^/(ws|mumble/voice) {
        proxy_pass         http://backend:6001;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    \$http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       \$host;
        proxy_read_timeout 86400s;
    }

    # All other FastAPI routes
    location / {
        proxy_pass         http://backend:6001;
        proxy_set_header   Host      \$host;
        proxy_set_header   X-Real-IP \$remote_addr;
        proxy_read_timeout 120s;
    }
}
EOF
    echo "==> nginx.conf written (HTTPS — web :${port}, API :6001)"
}

# ── Container cleanup ─────────────────────────────────────────────────────────
remove_existing() {
    for name in arrow-backend arrow-web arrow-proxy arrow-mapserver; do
        if [ -n "$(docker ps -aq --filter "name=^${name}$" 2>/dev/null)" ]; then
            echo "==> removing $name"
            docker rm -f "$name" >/dev/null
        fi
    done
}

# ── Wait for backend health ───────────────────────────────────────────────────
wait_healthy() {
    echo "==> waiting for backend health…"
    for _ in $(seq 1 30); do
        status=$($DC ps --format '{{.Service}} {{.Health}}' 2>/dev/null \
                 | awk '$1=="backend"{print $2}')
        [ "$status" = "healthy" ] && echo "    backend healthy ✓" && return
        sleep 2
    done
    echo "    warning: health check timed out" >&2
}

# ── Commands ──────────────────────────────────────────────────────────────────
cmd="${1:-up}"

case "$cmd" in

    up)
        require_compose
        ensure_pg_password
        write_nginx_http "$PORT"
        remove_existing
        list_maps
        $DC build
        $DC up -d
        wait_healthy
        $DC ps
        host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || host_ip=localhost
        echo ""
        echo "  Arrow      →  http://${host_ip}:${PORT}"
        echo "  MapServer  →  http://${host_ip}:${PORT}/mapserver/?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities"
        echo ""
        ;;

    https)
        require_compose
        ensure_pg_password
        generate_cert
        write_nginx_https "$PORT"
        # Persist mode so plain `docker compose up` also works
        grep -v '^ARROW_TLS=' .env 2>/dev/null > .env.tmp || true
        echo "ARROW_TLS=internal" >> .env.tmp && mv .env.tmp .env
        remove_existing
        list_maps
        $DC build
        $DC up -d
        wait_healthy
        $DC ps
        host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || host_ip=localhost
        pub_ip="${SERVER_IP:-$host_ip}"
        echo ""
        echo "══════════════════════════════════════════════════════"
        echo "  Arrow      →  https://${pub_ip}:${PORT}"
        echo "  MapServer  →  https://${pub_ip}:${PORT}/mapserver/?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities"
        echo ""
        echo "  Browser setup (one-time):"
        echo "    1. Open  https://${pub_ip}:${PORT}"
        echo "    2. Click 'Advanced → Proceed to ${pub_ip} (unsafe)'"
        echo "    3. Mic / PTT voice now works"
        echo "══════════════════════════════════════════════════════"
        echo ""
        ;;

    down)
        require_compose; $DC down ;;

    restart)
        require_compose; $DC restart ;;

    rebuild)
        require_compose
        ensure_pg_password
        remove_existing
        $DC build --no-cache
        $DC up -d --force-recreate
        wait_healthy
        ;;

    logs)
        require_compose; $DC logs -f --tail=200 ;;

    status|ps)
        require_compose; $DC ps ;;

    maps)
        list_maps ;;

    db)
        require_compose
        [ -f .env ] && export $(grep -v '^\s*#' .env | grep '=' | xargs) 2>/dev/null || true
        echo "==> connecting to arrow PostgreSQL (\\q to exit)"
        $DC exec postgres psql -U arrow arrow
        ;;

    backup)
        require_compose
        [ -f .env ] && export $(grep -v '^\s*#' .env | grep '=' | xargs) 2>/dev/null || true
        DATE="$(date -u +%Y-%m-%dT%H%M%SZ)"
        OUTFILE="arrow-db-manual-${DATE}.sql.gz"
        echo "==> pg_dump → ${OUTFILE}"
        $DC exec -T postgres sh -c \
            "PGPASSWORD=\$POSTGRES_PASSWORD pg_dump -U arrow arrow" \
            | gzip > "$OUTFILE"
        echo "==> saved: $OUTFILE ($(du -h "$OUTFILE" | cut -f1))"
        ;;

    wms)
        require_compose
        host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || host_ip=localhost
        PORT_WMS="${ARROW_HTTP_PORT:-6200}"
        echo ""
        echo "  WMS GetCapabilities:"
        echo "    http://${host_ip}:${PORT_WMS}/mapserver/?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetCapabilities"
        echo ""
        echo "  Available layers:  operators  tactical_objects  cot_tracks"
        echo "                     alerts     fire_missions     supply_points"
        echo ""
        ;;

    *)
        echo "usage: $0 [up|https|down|restart|rebuild|logs|status|maps|db|backup|wms]" >&2
        exit 1 ;;
esac
