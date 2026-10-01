#!/usr/bin/env bash
# Create the tables that do not create themselves, on an EMPTY database (not after a restore).
#
#   ./scripts/init-empty.sh
#
# Most engines apply their schema.sql when they start. Two do not:
#   - fmre (Instruments) builds its tables in `python -m store.etl.bootstrap`, which also loads
#     source files that are not in the repository; here only the schema is applied.
#   - the consumer app eigentlich, which has `python -m eigentlich init-db`.
# Without this, on an empty database fmre's /v1/health answers 500 (so the simtech container
# stays unhealthy) and the app has no tables. The questionnaire content (eigentlich seed) and
# fmre's data are NOT created: they come from the restored dump, or from source files outside
# the repository (see README.md, "What is not in the repository").
# Another compose project or env file: COMPOSE_PROJECT_NAME and COMPOSE_ENV_FILES, as for compose.
set -euo pipefail

cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1      # Git Bash on Windows only

docker compose exec -T simtech simtech init-empty
echo "done. fmre and the app answer healthy at their next health check."
