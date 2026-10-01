# Engine changes the Docker deployment would like

State of 01.10.2026, for the two-container layout (`db` and `simtech`). Nothing here has been
changed in an engine: the deployment in this folder works today without any of it, through the
workarounds named below. Each item says which file, which setting, and the change proposed, so
the coordinator can apply them and then remove the workaround.

Every engine already takes its database host, port, name, user and password from the
environment (`<PREFIX>_DB_HOST`, `_DB_PORT`, `_DB_NAME`, `_DB_USER`, `_DB_PASSWORD`, or a full
`<PREFIX>_DATABASE_URL`) and its listening host from `<PREFIX>_HOST`. Inside the one `simtech`
container every engine reaches the others on `127.0.0.1:<port>`, the default in every
config.yaml, so no upstream address needs overriding any more.

## Needed for a clean deployment (a workaround is in place)

| # | Engine | File | Setting today | Proposed change | Workaround in `deploy/` |
|---|---|---|---|---|---|
| 1 | cockpit | `cockpit/src/cockpit/settings.py`, `_curator_db()` | `curator_db.host`, `port`, `dbname`, `user` in config.yaml only (the password already has `COCKPIT_CURATOR_DB_PASSWORD`) | `COCKPIT_CURATOR_DB_HOST`, `COCKPIT_CURATOR_DB_PORT`, `COCKPIT_CURATOR_DB_NAME`, `COCKPIT_CURATOR_DB_USER` | `docker/cockpit_docker_config.py` writes a `config.local.yaml` at image build with `curator_db.host: db` |
| 2 | cockpit | `cockpit/src/cockpit/settings.py` and `api.py` (`POST /api/launcher/{key}/start`), `launcher.py` (`start`, `start_autostart`) | none: the launcher starts any engine that has a `start` command | `COCKPIT_LAUNCHER=off`: the start route answers 409 with a plain sentence, `start-engines` and `desktop` start nothing, and the System page hides Start | the same generated `config.local.yaml` removes every `start`, `python` and `autostart`, so nothing is startable (tested 01.10.2026: 0 of 13 startable, the start route answers 409). In Docker supervisord starts the engines, and a second starter would only get in its way |
| 3 | lbsim | `eigentliCH_Engines/engines/lbsim/src/lbsim/store.py`, `Store.initialise()` | every process (the API and each worker) applies `schema.sql` at start-up; two at the same moment can deadlock in PostgreSQL (`DeadlockDetected ... while updating tuple in relation "pg_proc"`, seen 01.10.2026 when three workers started together). The process exits and is restarted, so it heals, but it is noise | take a transaction-level advisory lock first (`SELECT pg_advisory_xact_lock(hashtext('lbsim.schema'))`) in the same session as the DDL, or let only `serve` apply the schema and the workers wait for it | `docker/supervisord.conf` starts worker n 4 x (n - 1) seconds after the first (`RUN_STAGGER`) |

Items 1 and 2 together would let the cockpit run in Docker from its own config.yaml plus
environment, and `cockpit_docker_config.py` could be deleted.

## Advisable (the deployment works, but a person notices)

| # | Engine | File | What happens today | Proposed change |
|---|---|---|---|---|
| 4 | cockpit | `cockpit/src/cockpit/static/index.html` (uses `e.url`, `e.docs`, `n.url`), `settings.py` `Engine.public()` | The System page links each engine's own address and its `/docs`: `http://127.0.0.1:80NN`. Opened through the tunnel, that address points at the viewer's own computer, not at the server; the app link is not the public app address either. The proxy and the test benches work, because they go through the cockpit. | A separate browser-facing address per engine, optional: `public_url` in config.yaml, env `COCKPIT_ENGINE_<KEY>_PUBLIC_URL`; the page shows the link only when one is set. For the app: `COCKPIT_ENGINE_EIGENTLICH_PUBLIC_URL=https://app.<domain>`. |
| 5 | fmre (Instruments) | `Instruments/api/main.py`, `health()` | On a database without fmre's tables, `/v1/health` answers 500 (UndefinedTable) instead of a status, so the `simtech` container stays unhealthy on an empty database. fmre also does not apply its schema at start-up, unlike every other engine. | Apply `store.db.initialise()` in a start-up hook (idempotent), or let `health()` answer 200 with `"status": "uninitialised"` when the tables are missing. Until then: `scripts/init-empty.sh` on an empty database (not needed after a restore). |
| 6 | eigentlich (app) | `eigentliCH_Engines/eigentlich/src/eigentlich/api.py`, `lifespan` | The app does not create its tables at start-up (`python -m eigentlich init-db` is separate); on an empty database `/health` says `degraded`. | Call the store's `initialise()` in the lifespan, as the engines do. Until then: `scripts/init-empty.sh`. |
| 7 | cockpit | `cockpit/src/cockpit/api.py` | No `GET /health`; the health check uses `GET /api/config`. | A standard `/health` like the engines'. |
| 8 | eigentlich (app) | `eigentliCH_Engines/eigentlich/src/eigentlich/__main__.py`, `_report_path()` | Maintenance commands (`seed`, `migrate`, `align-content`, ...) write their report to `ROOT/dev/reports/`. The image leaves out `dev/` and runs every program as the unprivileged user `engine`, so these commands fail in the container. The server itself never needs them. | `EIGENTLICH_REPORT_DIR`, defaulting to `ROOT/dev/reports`. |
| 9 | fmre (Instruments) | `Instruments/` | No `pyproject.toml`; the image installs `requirements.txt` plus `openpyxl` (imported by `store/etl/long_record.py` for the offline ETL), and runs fmre from its folder rather than as an installed package. | A `pyproject.toml` with the service dependencies and an `etl` extra, like the other engines. |
| 10 | every engine with uvicorn | each engine's `serve` command (`uvicorn.run(...)`) | uvicorn's access log records every health probe. The container's health check calls 14 routes every 30 seconds, so `docker compose logs simtech` carries about 40,000 `GET /health` lines a day between the lines that matter. | Leave `/health` (and the cockpit's `/api/config` probe) out of the access log, for example with a logging filter, or an `<PREFIX>_ACCESS_LOG=false` switch. |

## No longer needed (dropped on 01.10.2026)

- **lbsim upstream addresses from the environment** (was item 1). lbsim reads, since commit 5e9340d,
  `LBSIM_LBS_URL`, `LBSIM_PCP_URL`, `LBSIM_AGGREGATION_URL` and `LBSIM_FMRE_URL`, and in the one
  container its config.yaml defaults are right anyway. `config/lbsim.docker.yaml` is gone.
- **cockpit engine addresses from the environment** (was item 2, `COCKPIT_ENGINE_<KEY>_URL`).
  The roster's `http://127.0.0.1:80NN` is the right address inside the container.
- The per-engine upstream overrides compose used to pass (`HONI_DATAFEED_URL`,
  `AGGREGATION_MRS_URL`, `PCP_FMRE_URL`, `REPORT_LBSIM_URL`, `EIGENTLICH_LBS_URL`,
  `INSTRUMENTS_AGGREGATION_URL`, ...) are no longer set. The engines keep them; they are useful
  wherever engines run apart.

## Watch points for the agents at work now

- **lbsim**: the container runs `python -m lbsim serve --workers 0` for the API and
  `python -m lbsim worker` once per worker (`LBSIM_WORKERS`). If either command or the
  `--workers` flag changes shape, `docker/supervisord.conf` must follow.
- **Any new engine or roster change**: add a `[program:...]` to `docker/supervisord.conf` (its
  folder, command, `RUN_DB`, the ports it consumes in `RUN_WAIT`, its `<PREFIX>_HOST`), its
  health route to `docker/healthcheck.py`, its `pyproject.toml` to `docker/simtech.Dockerfile`
  (the dependency layer and the editable installs), its port to `compose.debug-engines.yaml`,
  and a `SIMTECH_<ENGINE>_PASSWORD` to `.env.example` and the `simtech` service in
  `compose.yaml`. The cockpit picks the engine up from its config.yaml at the next
  `docker compose build`.
- **A new dependency**: the four families share one environment in the image. A package one
  family pins at a version another cannot use would need a second environment; `pip check` in
  the build stops on such a conflict.
