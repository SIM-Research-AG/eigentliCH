#!/bin/bash
# Nightly backup of the simtech database. Runs inside the `db` container (postgres:18 image, so
# pg_dump is the server's own version), over the local socket as the administrator.
#
#   bash /scripts/backup.sh          wait for BACKUP_AT every day, dump, prune (started by db-entrypoint.sh)
#   bash /scripts/backup.sh now      dump once, prune, exit (docker compose exec db bash /scripts/backup.sh now)
#
# Writes to /backups (the named volume `backups`):
#   simtech-YYYY-MM-DD_HHMM.dump      pg_dump custom format of the simtech database
#   globals-YYYY-MM-DD_HHMM.sql       roles and their password hashes (pg_dumpall --globals-only)
# Files older than BACKUP_KEEP_DAYS days are deleted after each successful dump.
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
BACKUP_AT=${BACKUP_AT:-02:30}
BACKUP_KEEP_DAYS=${BACKUP_KEEP_DAYS:-14}
DATABASE=${BACKUP_DATABASE:-simtech}
export PGUSER=${PGUSER:-${POSTGRES_USER:-postgres}}
export PGPASSWORD=${PGPASSWORD:-${POSTGRES_PASSWORD:-}}

log() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') backup: $*"; }

dump_once() {
    local stamp tmp
    stamp=$(date '+%Y-%m-%d_%H%M')
    mkdir -p "$BACKUP_DIR"
    until pg_isready -q -d postgres; do log "waiting for the server"; sleep 5; done
    tmp="$BACKUP_DIR/.simtech-$stamp.dump.partial"
    pg_dump -d "$DATABASE" -Fc -f "$tmp" || { rm -f "$tmp"; return 1; }
    mv "$tmp" "$BACKUP_DIR/simtech-$stamp.dump"
    pg_dumpall --globals-only -f "$BACKUP_DIR/globals-$stamp.sql" || return 1
    chmod 600 "$BACKUP_DIR/simtech-$stamp.dump" "$BACKUP_DIR/globals-$stamp.sql"
    log "wrote simtech-$stamp.dump ($(du -h "$BACKUP_DIR/simtech-$stamp.dump" | cut -f1)) and globals-$stamp.sql"
    find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'simtech-*.dump' -o -name 'globals-*.sql' \) \
        -mtime +"$BACKUP_KEEP_DAYS" -print -delete | sed 's/^/  pruned /'
}

if [ "${1:-}" = "now" ]; then
    dump_once
    exit 0
fi

log "daily at $BACKUP_AT, keeping $BACKUP_KEEP_DAYS days, into $BACKUP_DIR"
while true; do
    now=$(date +%s)
    next=$(date -d "today $BACKUP_AT" +%s)
    [ "$next" -le "$now" ] && next=$(date -d "tomorrow $BACKUP_AT" +%s)
    log "next dump at $(date -d "@$next" '+%Y-%m-%d %H:%M %Z')"
    sleep $((next - now))
    dump_once || log "FAILED; will try again at the next BACKUP_AT"
done
