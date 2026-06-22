#!/bin/sh
# Substitute ${POSTGRES_PASSWORD} from env into the mapfile at runtime,
# writing the resolved file to /tmp/arrow.map so the read-only volume is
# not modified. MS_MAPFILE is overridden in the environment accordingly.
set -e
PW="${POSTGRES_PASSWORD:-arrow_dev}"
sed "s/\${POSTGRES_PASSWORD}/${PW}/g" /mapserver/arrow.map.tpl > /tmp/arrow.map
export MS_MAPFILE=/tmp/arrow.map
exec "$@"
