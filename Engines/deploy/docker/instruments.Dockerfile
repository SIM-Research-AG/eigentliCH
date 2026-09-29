# syntax=docker/dockerfile:1
#
# Instruments family image: the Fund Map and Return Estimation engine fmre (8006), and the
# one-shot `provision` service, which runs `python -m store.provision` from the same code.
#
# Instruments has no pyproject.toml and no virtual environment: locally it runs on the system
# Python 3.12. Its requirements.txt names the service's four packages; openpyxl is added
# because store/etl/long_record.py imports it for the offline ETL (never on the API path), so
# the ETL commands can also be run from this image.
#
# Build context: the Engines folder; what enters it is decided by
# instruments.Dockerfile.dockerignore (config.toml, which carries credentials, never does).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN useradd --system --uid 10001 --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin engine

COPY deploy/docker/constraints.txt deploy/docker/healthcheck.py /opt/deploy/

COPY Instruments/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt openpyxl -c /opt/deploy/constraints.txt \
    && rm /tmp/requirements.txt

COPY Instruments /srv/Engines/Instruments

USER engine
WORKDIR /srv/Engines/Instruments
