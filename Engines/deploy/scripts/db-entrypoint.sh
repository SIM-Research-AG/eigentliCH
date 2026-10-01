#!/bin/bash
# Entrypoint of the `db` container (official postgres:18 image): start the nightly backup loop
# (scripts/backup.sh) in the background, then hand over to the image's own entrypoint, which
# runs postgres exactly as without this script.
#
# The backup loop is started in a subshell that exits at once, so the loop belongs to the
# container's init (tini, `init: true` in compose.yaml), never to postgres; postgres stays the
# main process and receives `docker stop` as usual.
set -euo pipefail

( bash /scripts/backup.sh & )
exec docker-entrypoint.sh "$@"
