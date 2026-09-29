#!/usr/bin/env bash
# Create the tables that do not create themselves, on an EMPTY database (not after a restore).
#
#   ./scripts/init-empty.sh [-p PROJECT]
#
# Most engines apply their schema.sql when they start. Two do not:
#   - fmre (Instruments) builds its tables in `python -m store.etl.bootstrap`, which also loads
#     source files that are not in the repository; here only the schema is applied.
#   - the consumer app eigentlich, which has `python -m eigentlich init-db`.
# Without this, on an empty database fmre's /v1/health answers 500 and the app has no tables.
# The questionnaire content (eigentlich seed) and fmre's data are NOT created: they come from the
# restored dump, or from source files outside the repository (see README.md, "What is not in
# the repository").
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose)
if [ "${1:-}" = "-p" ] && [ -n "${2:-}" ]; then COMPOSE=(docker compose -p "$2"); fi

echo "== fmre: schema only"
"${COMPOSE[@]}" run --rm --no-deps fmre python -X utf8 -c "from store import db; db.initialise(); print('fmre schema ready')"

echo "== eigentlich: init-db"
"${COMPOSE[@]}" run --rm --no-deps eigentlich python -X utf8 -m eigentlich init-db
