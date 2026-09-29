#!/bin/bash
# Replace the simtech database with a pg_dump custom-format file. Runs inside a one-off
# container of the `backup` service (postgres:18 image); scripts/restore.sh calls it after
# stopping every engine and running the provisioning once, so every engine role exists.
#
#   bash /scripts/restore-db.sh /restore/<file>.dump
#
# What it does: drops simtech (WITH (FORCE) ends any leftover session), creates it empty,
# and runs pg_restore as the administrator WITHOUT --no-owner, so every schema, table and
# function gets its original owner (the engine role of the same name), and the dump's grants
# and default privileges come back with it. The database-level grants (CONNECT, CREATE) are
# not in a pg_dump; the provisioning run after this puts them back.
set -euo pipefail

DUMP=${1:?usage: restore-db.sh /restore/<file>.dump}
DATABASE=${BACKUP_DATABASE:-simtech}
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 2; }

until pg_isready -q; do echo "waiting for the server"; sleep 2; done

echo "restore: dropping and recreating $DATABASE"
psql -v ON_ERROR_STOP=1 -d postgres \
     -c "DROP DATABASE IF EXISTS $DATABASE WITH (FORCE)" \
     -c "CREATE DATABASE $DATABASE"

echo "restore: pg_restore $DUMP"
set +e
pg_restore -d "$DATABASE" --jobs 4 --verbose "$DUMP" 2> /tmp/restore.log
status=$?
set -e
grep -E 'error|warning' /tmp/restore.log | grep -v 'processing item' || true
errors=$(grep -c 'pg_restore: error' /tmp/restore.log || true)
echo "restore: pg_restore exit status $status, $errors error lines (full log: /tmp/restore.log in this container)"
psql -d "$DATABASE" -At -c "SELECT n.nspname || ' ' || pg_get_userbyid(n.nspowner) || ' ' ||
    (SELECT count(*) FROM pg_class c WHERE c.relnamespace = n.oid AND c.relkind = 'r') || ' tables'
    FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg\_%' AND n.nspname <> 'information_schema'
    ORDER BY 1" | sed 's/^/  /'
exit 0
