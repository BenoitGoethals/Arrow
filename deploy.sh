#!/usr/bin/env bash
# Arrow deploy script — builds and (re)starts the full stack via Docker Compose.
#
# Usage:
#   ./deploy.sh              # HTTP dev mode  (port 6200)
#   ./deploy.sh https        # HTTPS self-signed (port 443)  ← for bare IP servers
#   ./deploy.sh down         # stop and remove containers
#   ./deploy.sh logs         # tail all logs
#   ./deploy.sh restart      # restart without rebuilding
#   ./deploy.sh rebuild      # full no-cache rebuild
#   ./deploy.sh status       # show container health
#   ./deploy.sh maps         # list MBTiles base-maps
#
# HTTPS mode — one-time setup on new server:
#   1. ./deploy.sh https
#   2. Open https://<SERVER_IP> in browser
#   3. Click "Advanced → Proceed" to trust the self-signed cert (once per browser)
#   4. Microphone / PTT voice now works
#
# Environment variables (set in .env or export before running):
#   ARROW_DOMAIN          Caddy site address (default: :6200 for HTTP, :443 for HTTPS)
#   ARROW_HTTP_PORT       Host port for HTTP  (default: 6200)
#   ARROW_HTTPS_PORT      Host port for HTTPS (default: 443)
#   ARROW_ALLOWED_ORIGINS Comma-separated CORS origins seen by backend
#   CADDY_EMAIL           E-mail for Let's Encrypt (acme mode only)
#   BACKUP_KEEP_DAYS      Days to keep DB backups (default: 7)
#   BACKUP_INTERVAL_HOURS Backup interval in hours (default: 24)

set -euo pipefail
cd "$(dirname "$0")"

# ── Load .env if present ─────────────────────────────────────────────────────
if [ -f .env ]; then
    # shellcheck disable=SC2046
    export $(grep -v '^\s*#' .env | grep -v '^\s*$' | xargs)
fi

# ── Detect docker compose ────────────────────────────────────────────────────
require_compose() {
    if docker compose version >/dev/null 2>&1; then
        DC="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        DC="docker-compose"
    else
        echo "error: docker compose is not installed" >&2
        exit 1
    fi
}

# ── Maps volume setup ────────────────────────────────────────────────────────
mkdir -p maps
chmod 0777 maps 2>/dev/null || true

list_maps() {
    echo "==> base-map sources (./maps/)"
    if compgen -G "maps/*.mbtiles" >/dev/null 2>&1; then
        ls -lh maps/*.mbtiles 2>/dev/null | awk '{print "    " $NF "  (" $(NF-4) ")"}'
    else
        echo "    (none — drop *.mbtiles files in ./maps/ to serve them)"
    fi
}

# ── Container cleanup ────────────────────────────────────────────────────────
CONTAINERS=("arrow-backend" "arrow-web" "arrow-proxy")
remove_existing() {
    for name in "${CONTAINERS[@]}"; do
        if [ -n "$(docker ps -aq --filter "name=^${name}$" 2>/dev/null)" ]; then
            echo "==> removing existing container: ${name}"
            docker rm -f "$name" >/dev/null
        fi
    done
}

# ── Self-signed TLS cert generation ─────────────────────────────────────────
# Generates data/ssl/web-cert.pem + web-key.pem using openssl (available on
# every Linux server).  The cert SAN covers:
#   - 127.0.0.1 / localhost
#   - all local interface IPs (from hostname -I)
#   - any extra IPs passed as arguments or in ARROW_WEB_EXTRA_IPS
# Call:  _generate_cert [extra_ip1] [extra_ip2] …
_generate_cert() {
    local ssl_dir="./data/ssl"
    mkdir -p "$ssl_dir"

    # Collect all IPs: loopback + all local interfaces + arguments + env var
    local all_ips="127.0.0.1"
    local local_ips
    local_ips="$(hostname -I 2>/dev/null)" || local_ips=""
    for ip in $local_ips "$@"; do
        [ -n "$ip" ] && all_ips="${all_ips} ${ip}"
    done
    # Extra IPs from env (comma or space separated)
    for ip in $(echo "${ARROW_WEB_EXTRA_IPS:-}" | tr ',' ' '); do
        [ -n "$ip" ] && all_ips="${all_ips} ${ip}"
    done

    # Deduplicate
    all_ips=$(echo "$all_ips" | tr ' ' '\n' | sort -u | tr '\n' ' ')

    # Check if existing cert already covers all IPs
    if [ -f "$ssl_dir/web-cert.pem" ] && [ -f "$ssl_dir/web-key.pem" ]; then
        local missing=""
        for ip in $all_ips; do
            if ! openssl x509 -in "$ssl_dir/web-cert.pem" -noout -text 2>/dev/null \
                 | grep -q "IP Address:${ip}"; then
                missing="${missing} ${ip}"
            fi
        done
        if [ -z "$missing" ]; then
            echo "==> TLS cert OK (covers all IPs)"
            return
        fi
        echo "==> TLS cert missing IPs:${missing} — regenerating"
        rm -f "$ssl_dir/web-cert.pem" "$ssl_dir/web-key.pem"
    fi

    echo "==> Generating self-signed TLS cert"

    # Build SAN string:  IP:x.x.x.x,IP:y.y.y.y,DNS:localhost,...
    local san="DNS:localhost"
    for ip in $all_ips; do
        san="${san},IP:${ip}"
    done

    # Write openssl config (works on both LibreSSL/macOS and OpenSSL/Linux)
    local cfg
    cfg="$(mktemp /tmp/arrow-ssl-XXXXXX.conf)"
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

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$ssl_dir/web-key.pem" \
        -out    "$ssl_dir/web-cert.pem" \
        -days 3650 \
        -config "$cfg" \
        2>/dev/null && echo "==> Cert covers: ${san}" || {
            echo "error: openssl failed — is openssl installed?" >&2
            exit 1
        }
    rm -f "$cfg"
}

# ── TLS / Caddyfile selection ────────────────────────────────────────────────
# ARROW_TLS:  off (default) | internal (self-signed) | acme (Let's Encrypt)
setup_tls() {
    local mode="${ARROW_TLS:-off}"

    case "$mode" in
        internal)
            export ARROW_CADDYFILE="./Caddyfile.https"
            export ARROW_DOMAIN="${ARROW_DOMAIN:-:6200}"

            local port="${ARROW_HTTP_PORT:-6200}"
            local host_ip
            host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || host_ip="localhost"
            local pub_ip="${SERVER_IP:-$host_ip}"

            # Generate self-signed cert covering ALL server IPs
            _generate_cert "${pub_ip}"

            local origins="https://${pub_ip}:${port},http://localhost:${port}"
            export ARROW_ALLOWED_ORIGINS="${ARROW_ALLOWED_ORIGINS:-$origins}"

            echo "==> TLS mode  : self-signed (openssl)"
            echo "==> Listening : https://${pub_ip}:${port}"
            echo ""
            echo "    ┌───────────────────────────────────────────────────────────┐"
            echo "    │  BROWSER SETUP (one-time per browser / per IP):           │"
            echo "    │  1. Open  https://${pub_ip}:${port}                     "
            echo "    │  2. Click 'Advanced → Proceed to ${pub_ip} (unsafe)'     │"
            echo "    │  3. Done — mic / PTT voice now works                      │"
            echo "    └───────────────────────────────────────────────────────────┘"
            ;;

        acme)
            # Let's Encrypt — requires a real domain and ports 80+443
            export ARROW_CADDYFILE="./Caddyfile"
            export ARROW_DOMAIN="${ARROW_DOMAIN:?ARROW_DOMAIN must be set (e.g. my.domain.com) for acme mode}"
            echo "==> TLS mode  : acme (Let's Encrypt)"
            echo "==> Domain    : ${ARROW_DOMAIN}"
            ;;

        off|*)
            export ARROW_CADDYFILE="./Caddyfile"
            export ARROW_DOMAIN="${ARROW_DOMAIN:-:6200}"
            local http_port="${ARROW_HTTP_PORT:-6200}"
            local host_ip
            host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || host_ip="localhost"
            export ARROW_ALLOWED_ORIGINS="${ARROW_ALLOWED_ORIGINS:-http://localhost:${http_port}}"
            echo "==> TLS mode  : off (plain HTTP)"
            echo "==> Listening : http://${host_ip}:${http_port}"
            ;;
    esac
}

# ── Wait for backend health ───────────────────────────────────────────────────
wait_healthy() {
    echo "==> waiting for backend health"
    for _ in $(seq 1 30); do
        status=$($DC ps --format '{{.Service}} {{.Health}}' 2>/dev/null \
                 | awk '$1=="backend"{print $2}')
        if [ "$status" = "healthy" ]; then
            echo "    backend healthy ✓"
            return
        fi
        sleep 2
    done
    echo "    warning: backend health check timed out" >&2
}

# ── Print final URLs ──────────────────────────────────────────────────────────
print_urls() {
    local mode="${ARROW_TLS:-off}"
    local http_port="${ARROW_HTTP_PORT:-6200}"
    local https_port="${ARROW_HTTPS_PORT:-443}"
    local host_ip
    host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')" || host_ip="localhost"
    local pub_ip="${SERVER_IP:-$host_ip}"

    echo ""
    echo "═══════════════════════════════════════════════════"
    if [ "$mode" = "internal" ] || [ "$mode" = "acme" ]; then
        local domain="${ARROW_DOMAIN:-$pub_ip}"
        [ "$domain" = ":6200" ] && domain="${pub_ip}:${http_port}"
        [ "$domain" = ":443"  ] && domain="${pub_ip}:${https_port}"
        echo "  Arrow Web     https://${domain}"
        echo "  Arrow API     https://${domain}/api/docs"
    else
        echo "  Arrow Web     http://${pub_ip}:${http_port}"
        echo "  Arrow API     http://localhost:6001/docs"
    fi
    echo "═══════════════════════════════════════════════════"
    echo ""
}

# ── Commands ─────────────────────────────────────────────────────────────────
cmd="${1:-up}"

case "$cmd" in
    up)
        require_compose
        setup_tls
        remove_existing
        list_maps
        echo "==> building images"
        $DC build
        echo "==> starting stack"
        $DC up -d
        wait_healthy
        $DC ps
        print_urls
        ;;

    https)
        # Shortcut: ARROW_TLS=internal ./deploy.sh up
        export ARROW_TLS=internal
        export SERVER_IP="${SERVER_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
        require_compose
        setup_tls
        remove_existing
        list_maps
        echo "==> building images"
        $DC build
        echo "==> starting stack (HTTPS)"
        $DC up -d
        wait_healthy
        $DC ps
        print_urls
        ;;

    down)
        require_compose
        $DC down
        ;;

    restart)
        require_compose
        setup_tls
        $DC restart
        print_urls
        ;;

    rebuild)
        require_compose
        setup_tls
        remove_existing
        $DC build --no-cache
        $DC up -d --force-recreate
        wait_healthy
        print_urls
        ;;

    logs)
        require_compose
        $DC logs -f --tail=200
        ;;

    status|ps)
        require_compose
        $DC ps
        ;;

    maps)
        list_maps
        ;;

    *)
        echo "usage: $0 [up|https|down|restart|rebuild|logs|status|maps]" >&2
        exit 1
        ;;
esac
