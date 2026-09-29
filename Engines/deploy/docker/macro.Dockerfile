# syntax=docker/dockerfile:1
#
# Macro family image. One image, six containers: datafeed (8001), honi (8002), macrofield (8003),
# aggregation (8004), mrs (8005), cycle (8012). compose.yaml gives each its folder and command.
#
# Build context: the Engines folder (compose.yaml sets `context: ..`). What enters the context is
# decided by macro.Dockerfile.dockerignore beside this file: engine code only, never a .venv,
# config.local.yaml, .env, tests, golden files or caches.
#
# The layout inside mirrors the repository (/srv/Engines/Macro/engines/<engine>), because every
# engine finds config.yaml, schema.sql and pyproject.toml relative to its own folder.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin engine

COPY deploy/docker/constraints.txt deploy/docker/deps.py deploy/docker/healthcheck.py /opt/deploy/

# 1. Third-party packages, from the engines' own pyproject.toml files. This layer is rebuilt only
#    when a pyproject.toml or constraints.txt changes, not on every code change.
COPY Macro/engines/datafeed/pyproject.toml    /tmp/pyproject/datafeed.toml
COPY Macro/engines/honi/pyproject.toml        /tmp/pyproject/honi.toml
COPY Macro/engines/macrofield/pyproject.toml  /tmp/pyproject/macrofield.toml
COPY Macro/engines/aggregation/pyproject.toml /tmp/pyproject/aggregation.toml
COPY Macro/engines/mrs/pyproject.toml         /tmp/pyproject/mrs.toml
COPY Macro/engines/cycle/pyproject.toml       /tmp/pyproject/cycle.toml
RUN python /opt/deploy/deps.py /tmp/requirements.txt /tmp/pyproject/*.toml \
    && pip install -r /tmp/requirements.txt -c /opt/deploy/constraints.txt \
    && rm -rf /tmp/pyproject /tmp/requirements.txt

# 2. The engine code, installed editable (as in the local virtual environment) so that each
#    engine's ROOT stays its own folder.
COPY Macro/engines /srv/Engines/Macro/engines
RUN for e in datafeed honi macrofield aggregation mrs cycle; do \
        pip install --no-deps -e "/srv/Engines/Macro/engines/$e" || exit 1; \
    done

USER engine
WORKDIR /srv/Engines/Macro/engines
