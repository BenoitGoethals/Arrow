#!/usr/bin/env bash
set -euo pipefail

# Arrow deploy script — builds and (re)starts the backend + web stack via docker compose.
#
# Usage:
#   ./deploy.sh              # build + up -d
#   ./deploy.sh down         # stop and remove containers
#   ./deploy.sh logs         # tail logs
#   ./deploy.sh restart      # restart services without rebuilding
#   ./deploy.sh rebuild      # force a no-cache rebuild
#   ./deploy.sh status       # show container + healthcheck status
#   ./deploy.sh maps         # list MBTiles base maps available to the backend

cd "$(dirname "$0")"

# ── Maps volume ─────────────────────────────────────────────────────────────
# Backend serves base-map tiles from MBTiles files in ./maps/, mounted into the
# container at /app/maps. Drop new *.mbtiles in here, then ./deploy.sh restart
# (no rebuild needed) and they appear in GET /map/sources for both web + Android.
#
# Uploads from the admin UI also write here. The backend container runs as the
# `arrow` system user whose UID won't match the host directory owner, so the
# dir needs to be world-writable for the upload endpoint to succeed. (`:ro`
# mount mode prevented writes too — that flag has been removed in compose.)
mkdir -p maps
chmod 0777 maps 2>/dev/null || true

list_maps() {
    echo "==> base-map sources (./maps/)"
    if compgen -G "maps/*.mbtiles" >/dev/null; then
        # `-h` works on macOS BSD `ls`; falls back gracefully elsewhere.
        ls -lh maps/*.mbtiles 2>/dev/null | awk '{print "    " $9 "  (" $5 ")"}'
    else
        echo "    (none — drop *.mbtiles files in ./maps/ to serve them)"
    fi
}

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

CONTAINERS=("arrow-backend" "arrow-web" "arrow-proxy")

remove_existing() {
    for name in "${CONTAINERS[@]}"; do
        if [ -n "$(docker ps -aq --filter "name=^${name}$")" ]; then
            echo "==> removing existing container ${name}"
            docker rm -f "$name" >/dev/null
        fi
    done
}

cmd="${1:-up}"

case "$cmd" in
    up)
        require_compose
        remove_existing
        list_maps
        echo "==> building images"
        $DC build
        echo "==> starting stack"
        $DC up -d
        echo "==> waiting for backend health"
        for _ in $(seq 1 30); do
            status=$($DC ps --format '{{.Service}} {{.Health}}' | awk '$1=="backend"{print $2}')
            if [ "$status" = "healthy" ]; then
                echo "    backend healthy"
                break
            fi
            sleep 2
        done
        $DC ps
        echo
        echo "backend : http://localhost:6001/docs"
        echo "web     : http://localhost:6002"
        ;;
    maps)
        list_maps
        ;;
    down)
        require_compose
        $DC down
        ;;
    restart)
        require_compose
        $DC restart
        ;;
    rebuild)
        require_compose
        remove_existing
        $DC build --no-cache
        $DC up -d --force-recreate
        ;;
    logs)
        require_compose
        $DC logs -f --tail=200
        ;;
    status|ps)
        require_compose
        $DC ps
        ;;
    *)
        echo "usage: $0 [up|down|restart|rebuild|logs|status|maps]" >&2
        exit 1
        ;;
esac
