# syntax=docker/dockerfile:1
#
# The simtech image: every engine, the lbsim workers, the consumer app eigentlich (8017), the
# cockpit (8000), the start-up provisioning and cloudflared, in one container under supervisord
# (docker/supervisord.conf). The database runs in the second container, `db` (postgres:18).
#
# One Python environment (/opt/venv) for all four families: their pinned dependency sets are the
# same versions (docker/constraints.txt), and no two engines share a top-level package name.
# supervisord has its own small environment (/opt/supervisor), so it adds nothing to the engines'.
#
# Build context: the Engines folder (compose.yaml sets `context: ..`). What enters it is decided
# by simtech.Dockerfile.dockerignore beside this file: engine code only, never a .venv, .env,
# config.local.yaml, config.toml, tests, golden files, dev material or caches. The layout inside
# mirrors the repository (/srv/Engines/...), because every engine finds its config.yaml and
# schema.sql relative to its own folder, and the cockpit finds the test benches at ../<family>.

ARG CLOUDFLARED_VERSION=2026.9.3
FROM cloudflare/cloudflared:${CLOUDFLARED_VERSION} AS cloudflared

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PATH=/opt/venv/bin:$PATH \
    SIMTECH_ENGINE_BIND=127.0.0.1 \
    LBSIM_WORKERS=3

RUN useradd --system --uid 10001 --user-group --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin engine \
    && mkdir -p /data /run/simtech && chown engine:engine /data /run/simtech

COPY deploy/docker/constraints.txt deploy/docker/deps.py /opt/deploy/

# 1. supervisord, in its own environment.
RUN python -m venv /opt/supervisor \
    && /opt/supervisor/bin/pip install supervisor -c /opt/deploy/constraints.txt \
    && ln -s /opt/supervisor/bin/supervisord /opt/supervisor/bin/supervisorctl /usr/local/bin/

# 2. cloudflared, the static binary from Cloudflare's own image (pinned by CLOUDFLARED_VERSION).
COPY --from=cloudflared /usr/local/bin/cloudflared /usr/local/bin/cloudflared

# 3. Third-party packages, from the engines' own pyproject.toml files and Instruments'
#    requirements.txt (plus openpyxl, which its offline ETL imports). Rebuilt only when one of
#    those files or constraints.txt changes, not on every code change.
COPY Macro/engines/datafeed/pyproject.toml          /tmp/pyproject/datafeed.toml
COPY Macro/engines/honi/pyproject.toml              /tmp/pyproject/honi.toml
COPY Macro/engines/macrofield/pyproject.toml        /tmp/pyproject/macrofield.toml
COPY Macro/engines/aggregation/pyproject.toml       /tmp/pyproject/aggregation.toml
COPY Macro/engines/mrs/pyproject.toml               /tmp/pyproject/mrs.toml
COPY Macro/engines/cycle/pyproject.toml             /tmp/pyproject/cycle.toml
COPY Optimizer/engines/pcp/pyproject.toml           /tmp/pyproject/pcp.toml
COPY eigentliCH_Engines/engines/lbs/pyproject.toml     /tmp/pyproject/lbs.toml
COPY eigentliCH_Engines/engines/lbsim/pyproject.toml   /tmp/pyproject/lbsim.toml
COPY eigentliCH_Engines/engines/report/pyproject.toml  /tmp/pyproject/report.toml
COPY eigentliCH_Engines/engines/chatbot/pyproject.toml /tmp/pyproject/chatbot.toml
COPY eigentliCH_Engines/eigentlich/pyproject.toml      /tmp/pyproject/eigentlich.toml
COPY cockpit/pyproject.toml                         /tmp/pyproject/cockpit.toml
COPY Instruments/requirements.txt                   /tmp/instruments-requirements.txt
RUN python -m venv /opt/venv \
    && python /opt/deploy/deps.py /tmp/requirements.txt /tmp/pyproject/*.toml --extra openpyxl \
    && pip install -r /tmp/requirements.txt -r /tmp/instruments-requirements.txt -c /opt/deploy/constraints.txt \
    && pip check \
    && rm -rf /tmp/pyproject /tmp/requirements.txt /tmp/instruments-requirements.txt

# 4. CasADi's IPOPT (with MUMPS) must solve in this image, or the lbsim workers cannot.
RUN python -c "import casadi as ca; x = ca.SX.sym('x'); s = ca.nlpsol('s', 'ipopt', {'x': x, 'f': (x - 2) ** 2}, {'print_time': 0, 'ipopt.print_level': 0}); r = s(x0=0); assert abs(float(r['x']) - 2) < 1e-6, r; print('casadi', ca.__version__, 'IPOPT ok')"

# 5. The engine code, installed editable (as in the local virtual environments) so that each
#    engine's ROOT stays its own folder. Instruments is not a package: fmre and the provisioning
#    run from its folder, as on the owner's machine.
COPY Macro/engines        /srv/Engines/Macro/engines
COPY Instruments          /srv/Engines/Instruments
COPY Optimizer/engines    /srv/Engines/Optimizer/engines
COPY eigentliCH_Engines   /srv/Engines/eigentliCH_Engines
COPY cockpit              /srv/Engines/cockpit
COPY deploy/docker/cockpit_docker_config.py /opt/deploy/
RUN for p in Macro/engines/datafeed Macro/engines/honi Macro/engines/macrofield Macro/engines/aggregation \
             Macro/engines/mrs Macro/engines/cycle Optimizer/engines/pcp \
             eigentliCH_Engines/engines/lbs eigentliCH_Engines/engines/lbsim eigentliCH_Engines/engines/report \
             eigentliCH_Engines/engines/chatbot eigentliCH_Engines/eigentlich cockpit; do \
        pip install --no-deps -e "/srv/Engines/$p" || exit 1; \
    done \
    && python /opt/deploy/cockpit_docker_config.py /srv/Engines/cockpit

# 6. The supervisor's configuration and the start-up scripts.
COPY deploy/docker/supervisord.conf /etc/supervisord.conf
COPY deploy/docker/run.sh deploy/docker/provision.sh deploy/docker/healthcheck.py /opt/deploy/
COPY deploy/docker/simtech.sh /usr/local/bin/simtech
RUN chmod 755 /opt/deploy/run.sh /opt/deploy/provision.sh /usr/local/bin/simtech

# supervisord runs as root and starts every program as the user `engine` (uid 10001).
WORKDIR /srv/Engines
ENTRYPOINT ["simtech"]
CMD ["start"]
