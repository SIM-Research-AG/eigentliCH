# syntax=docker/dockerfile:1
#
# Optimizer family image: pcp (8007). Build context: the Engines folder; what enters it is
# decided by optimizer.Dockerfile.dockerignore. Layout mirrors the repository.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin engine

COPY deploy/docker/constraints.txt deploy/docker/deps.py deploy/docker/healthcheck.py /opt/deploy/

COPY Optimizer/engines/pcp/pyproject.toml /tmp/pyproject/pcp.toml
RUN python /opt/deploy/deps.py /tmp/requirements.txt /tmp/pyproject/*.toml \
    && pip install -r /tmp/requirements.txt -c /opt/deploy/constraints.txt \
    && rm -rf /tmp/pyproject /tmp/requirements.txt

COPY Optimizer/engines /srv/Engines/Optimizer/engines
RUN pip install --no-deps -e /srv/Engines/Optimizer/engines/pcp

USER engine
WORKDIR /srv/Engines/Optimizer/engines/pcp
