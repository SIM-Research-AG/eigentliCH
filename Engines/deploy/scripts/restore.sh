#!/usr/bin/env bash
# Restore the simtech database from a dump, on the server, in the right order.
#
#   ./scripts/restore.sh /path/to/simtech-2026-09-29.dump [--yes]
#
# Run from anywhere; it works in the deploy folder. Steps:
#   1. stop every engine, the app and the cockpit (nothing may hold a connection or recreate tables)
#   2. start postgres and wait until it is healthy
#   3. run the provisioning once, so every engine role exists before the dump refers to it
#   4. drop simtech, recreate it, pg_restore the dump with its original owners (scripts/restore-db.sh)
#   5. run the provisioning again: database grants, new schemas, the curator and catalogue grants
#   6. start everything
#
# THIS REPLACES THE WHOLE simtech DATABASE on this server. It asks first unless --yes is given.
set -euo pipefail

cd "$(dirname "$0")/.."

DUMP=${1:?usage: scripts/restore.sh /path/to/simtech.dump [--yes]}
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 2; }
# `pwd -W` gives a Windows path under Git Bash (Docker Desktop); on Linux it fails and pwd is used.
DUMP_DIR=$(cd "$(dirname "$DUMP")" && { pwd -W 2>/dev/null || pwd; })
DUMP_NAME=$(basename "$DUMP")

APPS="cockpit eigentlich chatbot report lbsim-worker lbsim lbs pcp fmre aggregation cycle mrs macrofield honi datafeed backup"

if [ "${2:-}" != "--yes" ]; then
    read -r -p "Replace the simtech database of project '$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' 2>/dev/null || echo "?")' with $DUMP_NAME? Type yes: " answer
    [ "$answer" = "yes" ] || { echo "nothing changed"; exit 1; }
fi

echo "== 1. stopping engines, app and cockpit"
docker compose stop $APPS

echo "== 2. starting postgres"
docker compose up -d --wait postgres

echo "== 3. provisioning (roles first)"
docker compose run --rm --no-deps provision

echo "== 4. restoring $DUMP_NAME"
docker compose run --rm --no-deps -v "$DUMP_DIR:/restore:ro" backup bash /scripts/restore-db.sh "/restore/$DUMP_NAME"

echo "== 5. provisioning again (grants)"
docker compose run --rm --no-deps provision

echo "== 6. starting everything"
docker compose up -d
echo "done. Check with: ./scripts/health.sh"
