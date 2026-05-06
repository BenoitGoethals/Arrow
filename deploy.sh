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

cd "$(dirname "$0")"

if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    echo "error: docker compose is not installed" >&2
    exit 1
fi

CONTAINERS=("arrow-backend" "arrow-web")

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
        remove_existing
        echo "==> building images"
        $DC build
        echo "==> starting stack"
        $DC up -d
        echo "==> waiting for backend health"
        for i in $(seq 1 30); do
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
    down)
        $DC down
        ;;
    restart)
        $DC restart
        ;;
    rebuild)
        remove_existing
        $DC build --no-cache
        $DC up -d --force-recreate
        ;;
    logs)
        $DC logs -f --tail=200
        ;;
    status|ps)
        $DC ps
        ;;
    *)
        echo "usage: $0 [up|down|restart|rebuild|logs|status]" >&2
        exit 1
        ;;
esac
