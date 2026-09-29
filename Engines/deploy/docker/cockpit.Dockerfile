# syntax=docker/dockerfile:1
#
# Cockpit image (8000). Locally the cockpit runs on the Macro virtual environment; here it gets
# its own image from its own pyproject.toml. It also carries every engine's test bench page,
# at the same relative paths as in the repository, because config.yaml names them as
# ../Macro/engines/honi/testbench/index.html and so on.
#
# In Docker the cockpit shows status only: cockpit_docker_config.py writes a config.local.yaml
# at build time that points every engine at its compose service and removes every start
# command. See that script, and README.md "The cockpit in Docker".

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin engine \
    && mkdir -p /data && chown engine /data

COPY deploy/docker/constraints.txt deploy/docker/deps.py deploy/docker/healthcheck.py deploy/docker/cockpit_docker_config.py /opt/deploy/

COPY cockpit/pyproject.toml /tmp/pyproject/cockpit.toml
RUN python /opt/deploy/deps.py /tmp/requirements.txt /tmp/pyproject/*.toml \
    && pip install -r /tmp/requirements.txt -c /opt/deploy/constraints.txt \
    && rm -rf /tmp/pyproject /tmp/requirements.txt

# The test benches (static HTML) the cockpit serves under /bench/<engine>/.
COPY Macro/engines          /srv/Engines/Macro/engines
COPY Instruments/testbench  /srv/Engines/Instruments/testbench
COPY Optimizer/engines      /srv/Engines/Optimizer/engines
COPY eigentliCH_Engines     /srv/Engines/eigentliCH_Engines

COPY cockpit /srv/Engines/cockpit
RUN pip install --no-deps -e /srv/Engines/cockpit \
    && python /opt/deploy/cockpit_docker_config.py /srv/Engines/cockpit

USER engine
WORKDIR /srv/Engines/cockpit
