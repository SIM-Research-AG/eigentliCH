#!/bin/bash
# The simtech container's entrypoint and administration command (installed as /usr/local/bin/simtech).
#
#   simtech start              the container's command: clear the start-up marker, then supervisord
#   simtech provision [--show] the provisioning, once, with its exit status (scripts/restore.sh)
#   simtech eigentlich ARGS    a maintenance command of the app (python -m eigentlich ARGS), with
#                              its database login, as the user engine; reports go to
#                              EIGENTLICH_REPORT_DIR (README.md, "Everyday commands")
#   simtech health [--quiet]   every engine's health route (scripts/health.sh, the container health check)
#   simtech COMMAND ...        anything else is run as given (e.g. bash, supervisorctl status)
set -euo pipefail

INSTRUMENTS=/srv/Engines/Instruments
APP=/srv/Engines/eigentliCH_Engines/eigentlich

case "${1:-start}" in
    start)
        # A restarted container keeps its filesystem: forget the last start's provisioning, so
        # that every engine waits for this start's run of it.
        mkdir -p /run/simtech && chown engine:engine /run/simtech
        rm -f /run/simtech/provisioned
        case "${LBSIM_WORKERS:-3}" in
            ''|*[!0-9]*|0) echo "simtech: LBSIM_WORKERS must be a whole number of at least 1, not '${LBSIM_WORKERS:-}'" >&2; exit 2 ;;
        esac
        # cloudflared is a supervised program that starts only when a tunnel token is set.
        if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
            export SIMTECH_TUNNEL=true
            echo "simtech: tunnel token set, cloudflared will start"
        else
            export SIMTECH_TUNNEL=false
            echo "simtech: no CLOUDFLARE_TUNNEL_TOKEN, cloudflared stays off"
        fi
        echo "simtech: starting supervisord (${LBSIM_WORKERS:-3} lbsim workers)"
        exec supervisord -n -c /etc/supervisord.conf
        ;;
    provision)
        shift
        cd "$INSTRUMENTS"
        RUN_NAME=provision RUN_DB=INSTRUMENTS:- RUN_KEEP=all RUN_AFTER_PROVISION=0 \
            exec /opt/deploy/run.sh python -X utf8 -m store.provision "$@"
        ;;
    eigentlich)
        shift
        cd "$APP"
        status=0
        RUN_NAME=eigentlich RUN_DB=EIGENTLICH:eigentlich RUN_AFTER_PROVISION=0 /opt/deploy/run.sh \
            python -X utf8 -m eigentlich "$@" || status=$?
        sleep 1   # let the log prefixer flush
        exit "$status"
        ;;
    health)
        shift
        exec python /opt/deploy/healthcheck.py "$@"
        ;;
    *)
        exec "$@"
        ;;
esac
