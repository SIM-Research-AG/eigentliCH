#!/bin/bash
# Start one program of the simtech container: its environment, its place in the start order,
# its log prefix. supervisord.conf runs every program through this script; `simtech provision`
# and `simtech init-empty` use it too.
#
#   run.sh COMMAND [ARGS ...]
#
# Read from the program's environment (set per program in supervisord.conf):
#   RUN_NAME   the log prefix; default: supervisord's process name (datafeed, lbsim-worker-2, ...)
#   RUN_DB     PREFIX:ROLE. Sets PREFIX_DB_HOST, PREFIX_DB_PORT, PREFIX_DB_USER and PREFIX_DB_PASSWORD,
#              the last from SIMTECH_<ROLE>_PASSWORD. ROLE "-" sets host and port only.
#   RUN_MAP    "DEST=SRC ...": export DEST with the value of SRC (the curator password, the tunnel token)
#   RUN_KEEP   the secrets this program keeps, by name, or "all". Every other secret (each
#              SIMTECH_*_PASSWORD, SPARK7_*, the tunnel token, the datafeed admin token) is removed
#              from its environment, so an engine sees its own password and nothing else.
#   RUN_WAIT   ports on 127.0.0.1 that must accept a connection first, e.g. "8001 8003": the
#              engines this one consumes. After RUN_WAIT_TIMEOUT seconds (default 300) it starts
#              anyway and says so; the engines call each other per request, not at start-up.
#   RUN_AFTER_PROVISION  1 (default): wait until the provisioning has finished (marker file).
#   RUN_STAGGER  n: start 4 x (n - 1) seconds after the waits (the lbsim workers, by number).
#
# Every line the program writes to stdout or stderr goes to the container log as "[name] line".
# The script ends with exec, so supervisord's signals reach the program itself.
set -euo pipefail

name=${RUN_NAME:-${SUPERVISOR_PROCESS_NAME:-${1##*/}}}
exec > >(exec sed -u "s|^|[$name] |") 2>&1

say() { echo "run: $*"; }

# 1. The database login: host and port of the db container, this engine's role and password.
if [ -n "${RUN_DB:-}" ]; then
    prefix=${RUN_DB%%:*}
    role=${RUN_DB#*:}
    export "${prefix}_DB_HOST=${SIMTECH_DB_HOST:-db}" "${prefix}_DB_PORT=${SIMTECH_DB_PORT:-5432}"
    if [ "$role" != "-" ]; then
        var="SIMTECH_${role^^}_PASSWORD"
        if [ -z "${!var:-}" ]; then
            say "$var is not set; not starting (set it in .env)"
            sleep 30
            exit 1
        fi
        export "${prefix}_DB_USER=$role" "${prefix}_DB_PASSWORD=${!var}"
    fi
fi

# 2. Secrets copied under the name the program reads.
for pair in ${RUN_MAP:-}; do
    src=${pair#*=}
    export "${pair%%=*}=${!src:-}"
done

# 3. Every secret this program does not need leaves its environment.
if [ "${RUN_KEEP:-}" != "all" ]; then
    for var in $(compgen -e); do
        case "$var" in
            SIMTECH_*_PASSWORD|SPARK7_CLIENT_ID|SPARK7_CLIENT_SECRET|CLOUDFLARE_TUNNEL_TOKEN|DATAFEED_ADMIN_TOKEN) ;;
            *) continue ;;
        esac
        case " ${RUN_KEEP:-} " in *" $var "*) continue ;; esac
        unset "$var"
    done
fi

# 4. Start order: the provisioning first, then the engines this one consumes.
if [ "${RUN_AFTER_PROVISION:-1}" = "1" ]; then
    waited=0
    until [ -e /run/simtech/provisioned ]; do
        [ $((waited % 60)) -eq 0 ] && say "waiting for the provisioning"
        sleep 2
        waited=$((waited + 2))
    done
fi
timeout=${RUN_WAIT_TIMEOUT:-300}
for port in ${RUN_WAIT:-}; do
    waited=0
    until (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; do
        if [ "$waited" -ge "$timeout" ]; then
            say "port $port still not answering after ${timeout} s; starting anyway"
            break
        fi
        [ $((waited % 30)) -eq 0 ] && say "waiting for port $port"
        sleep 2
        waited=$((waited + 2))
    done
done

if [ -n "${RUN_STAGGER:-}" ] && [ "$RUN_STAGGER" -gt 1 ] 2>/dev/null; then
    sleep $(( (RUN_STAGGER - 1) * 4 ))
fi

# 5. Run it, as the unprivileged user `engine` (supervisord already sets it; `docker compose
#    run` and `exec` start as root).
if [ "$(id -u)" = "0" ]; then
    exec setpriv --reuid=engine --regid=engine --init-groups "$@"
fi
exec "$@"
