# syntax=docker/dockerfile:1
#
# eigentliCH family image. One image, six containers: lbs (8013), lbsim (8014, API only),
# lbsim-worker (the plan workers, no port), report (8015), chatbot (8016) and the consumer app
# eigentlich (8017). Includes casadi 3.7.2 (IPOPT with MUMPS), which only the lbsim workers load.
#
# Build context: the Engines folder; what enters it is decided by
# eigentlich.Dockerfile.dockerignore (never .env, which holds the spark7 token, and never a
# config.local.yaml). Layout mirrors the repository.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin engine

COPY deploy/docker/constraints.txt deploy/docker/deps.py deploy/docker/healthcheck.py /opt/deploy/

COPY eigentliCH_Engines/engines/lbs/pyproject.toml     /tmp/pyproject/lbs.toml
COPY eigentliCH_Engines/engines/lbsim/pyproject.toml   /tmp/pyproject/lbsim.toml
COPY eigentliCH_Engines/engines/report/pyproject.toml  /tmp/pyproject/report.toml
COPY eigentliCH_Engines/engines/chatbot/pyproject.toml /tmp/pyproject/chatbot.toml
COPY eigentliCH_Engines/eigentlich/pyproject.toml      /tmp/pyproject/eigentlich.toml
RUN python /opt/deploy/deps.py /tmp/requirements.txt /tmp/pyproject/*.toml \
    && pip install -r /tmp/requirements.txt -c /opt/deploy/constraints.txt \
    && rm -rf /tmp/pyproject /tmp/requirements.txt

COPY eigentliCH_Engines /srv/Engines/eigentliCH_Engines
RUN for p in engines/lbs engines/lbsim engines/report engines/chatbot eigentlich; do \
        pip install --no-deps -e "/srv/Engines/eigentliCH_Engines/$p" || exit 1; \
    done

# lbsim reads its upstream addresses from config.yaml only (no environment override yet, see
# ENGINE_CHANGES.md), so the Docker addresses come in as its config.local.yaml overlay.
COPY deploy/config/lbsim.docker.yaml /srv/Engines/eigentliCH_Engines/engines/lbsim/config.local.yaml

USER engine
WORKDIR /srv/Engines/eigentliCH_Engines
