#!/usr/bin/env bash
# Health of the whole deployment, from the server.
#
#   ./scripts/health.sh
#
# Prints the two containers' states, every program supervisord runs in simtech (the engines,
# the lbsim workers, the app, the cockpit, cloudflared; `provision` is EXITED once it has done
# its work), every health route called from inside simtech, and the database. Exit status 0
# when every route answered 200, every program that should run runs, and the database answers.
# Another compose project or env file: COMPOSE_PROJECT_NAME and COMPOSE_ENV_FILES, as for compose.
set -uo pipefail

cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1      # Git Bash on Windows only
bad=0

echo "== containers"
docker compose ps -a --format 'table {{.Service}}\t{{.State}}\t{{.Status}}'

echo
echo "== programs in simtech (supervisorctl status)"
status=$(docker compose exec -T simtech supervisorctl status 2>&1)
echo "$status" | sed 's/^/  /'
# Anything not RUNNING is a fault, except the finished provisioning and a tunnel left off.
echo "$status" | grep -vE '^(provision +EXITED|cloudflared +STOPPED +Not started)' | grep -vq ' RUNNING ' && bad=1
echo "$status" | grep -q ' RUNNING ' || bad=1

echo
echo "== health routes (from inside simtech)"
docker compose exec -T simtech simtech health || bad=1

echo
echo "== database"
if docker compose exec -T db sh -c 'pg_isready -U "$POSTGRES_USER" -d simtech' | sed 's/^/  /'; then :; else bad=1; fi

echo
[ "$bad" = 0 ] && echo "all ok" || echo "NOT all ok"
exit "$bad"
