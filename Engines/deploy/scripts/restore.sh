#!/usr/bin/env bash
# Restore the simtech database from a dump, on the server, in the right order.
#
#   ./scripts/restore.sh /path/to/simtech-2026-09-29.dump [--yes]      a file on this machine
#   ./scripts/restore.sh --backup simtech-2026-10-01_0230.dump [--yes]  a file in the backup volume
#
# Run from anywhere; it works in the deploy folder. Steps:
#   1. stop the simtech container (nothing may hold a connection or recreate tables)
#   2. start db and wait until it is healthy
#   3. run the provisioning once, so every engine role exists before the dump refers to it
#   4. copy the dump into the db container, drop simtech, recreate it, pg_restore the dump with
#      its original owners (scripts/restore-db.sh), delete the copy
#   5. run the provisioning again: database grants, new schemas, the curator and catalogue grants
#   6. start everything
#
# THIS REPLACES THE WHOLE simtech DATABASE on this server. It asks first unless --yes is given.
# Another compose project or env file: COMPOSE_PROJECT_NAME and COMPOSE_ENV_FILES, as for compose.
set -euo pipefail

cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1      # Git Bash on Windows only: leave container paths alone

usage() { echo "usage: scripts/restore.sh /path/to/simtech.dump [--yes] | --backup NAME.dump [--yes]" >&2; exit 2; }

FROM_VOLUME=0
if [ "${1:-}" = "--backup" ]; then
    FROM_VOLUME=1
    shift
fi
DUMP=${1:-}
[ -n "$DUMP" ] || usage
ANSWER=${2:-}
DUMP_NAME=$(basename "$DUMP")

if [ "$FROM_VOLUME" = "0" ]; then
    [ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 2; }
    # Docker Desktop under Git Bash wants a Windows path for `docker compose cp`.
    command -v cygpath >/dev/null 2>&1 && DUMP=$(cygpath -w "$DUMP")
fi

if [ "$ANSWER" != "--yes" ]; then
    read -r -p "Replace the simtech database of compose project '${COMPOSE_PROJECT_NAME:-simtech}' with $DUMP_NAME? Type yes: " answer
    [ "$answer" = "yes" ] || { echo "nothing changed"; exit 1; }
fi

echo "== 1. stopping the simtech container"
docker compose stop simtech

echo "== 2. starting db"
docker compose up -d --wait db

if [ "$FROM_VOLUME" = "1" ]; then
    TARGET="/backups/$DUMP_NAME"
    docker compose exec -T db test -f "$TARGET" || { echo "no such file in the backup volume: $DUMP_NAME" >&2; exit 2; }
else
    TARGET="/backups/incoming/$DUMP_NAME"
    trap 'docker compose exec -T db rm -f "$TARGET" >/dev/null 2>&1 || true' EXIT
fi

echo "== 3. provisioning (roles first)"
docker compose run --rm --no-deps simtech provision

echo "== 4. restoring $DUMP_NAME"
if [ "$FROM_VOLUME" = "0" ]; then
    docker compose exec -T db mkdir -p /backups/incoming
    docker compose cp "$DUMP" "db:$TARGET"
fi
docker compose exec -T db bash /scripts/restore-db.sh "$TARGET"

echo "== 5. provisioning again (grants)"
docker compose run --rm --no-deps simtech provision

echo "== 6. starting everything"
docker compose up -d
echo "done. The engines need a minute or two; then check with: ./scripts/health.sh"
