#!/bin/bash
# The start-up provisioning: supervisord's first program, one-shot. Runs `python -m
# store.provision` (idempotent: creates database simtech, every engine role and schema, the
# curator and catalogue roles and every grant; changes nothing that exists) until it succeeds,
# then writes the marker every other program waits for (docker/run.sh) and exits 0.
set -uo pipefail

until python -X utf8 -m store.provision; do
    echo "provision: failed; trying again in 15 s"
    sleep 15
done
touch /run/simtech/provisioned
echo "provision: done, the engines start now"
