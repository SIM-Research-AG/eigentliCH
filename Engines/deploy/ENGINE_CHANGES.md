# Engine changes the Docker deployment would like

State of 29.09.2026. Nothing here has been changed in an engine: the deployment in this folder
works today without any of it, through the workarounds named below. Each item says which file,
which setting, and the environment variable proposed for it, so the coordinator can apply them
and then remove the workaround.

Every engine already takes its database host, port, name, user and password from the
environment (`<PREFIX>_DB_HOST`, `_DB_PORT`, `_DB_NAME`, `_DB_USER`, `_DB_PASSWORD`, or a full
`<PREFIX>_DATABASE_URL`) and its listening host from `<PREFIX>_HOST`. The gaps are upstream
addresses in two places, the cockpit's roster and curator connection, and three start-up
behaviours.

## Needed for a clean deployment (a workaround is in place)

| # | Engine | File | Setting today | Proposed environment variable | Workaround in `deploy/` |
|---|---|---|---|---|---|
| 1 | lbsim | `eigentliCH_Engines/engines/lbsim/src/lbsim/settings.py`, `load()` | `upstream.lbs.url`, `upstream.pcp.url`, `upstream.aggregation.url`, `upstream.fmre.url` in config.yaml only | `LBSIM_LBS_URL`, `LBSIM_PCP_URL`, `LBSIM_AGGREGATION_URL`, `LBSIM_FMRE_URL`, each written to `tree["upstream"][<name>]["url"]` after the config.local.yaml merge, as report does for `REPORT_*_URL` | `config/lbsim.docker.yaml`, copied into the image as lbsim's `config.local.yaml` |
| 2 | cockpit | `cockpit/src/cockpit/settings.py`, `_engines()` / `load()` | every engine's `url` in config.yaml only (`http://127.0.0.1:80NN`) | `COCKPIT_ENGINE_<KEY>_URL`, e.g. `COCKPIT_ENGINE_HONI_URL=http://honi:8002` | `docker/cockpit_docker_config.py` writes a `config.local.yaml` at image build with `http://<key>:<port>` for every engine |
| 3 | cockpit | `cockpit/src/cockpit/settings.py`, `_curator_db()` | `curator_db.host`, `port`, `dbname`, `user` in config.yaml only (the password already has `COCKPIT_CURATOR_DB_PASSWORD`) | `COCKPIT_CURATOR_DB_HOST`, `COCKPIT_CURATOR_DB_PORT`, `COCKPIT_CURATOR_DB_NAME`, `COCKPIT_CURATOR_DB_USER` | the same generated `config.local.yaml` sets `curator_db.host: postgres` |
| 4 | cockpit | `cockpit/src/cockpit/settings.py` and `api.py` (`POST /api/launcher/{key}/start`), `launcher.py` (`start`, `start_autostart`) | none: the launcher starts any engine that has a `start` command | `COCKPIT_LAUNCHER=off`: the start route answers 409 with a plain sentence, `start-engines` and `desktop` start nothing, and the System page hides Start | the generated `config.local.yaml` removes every `start`, `python` and `autostart`, so nothing is startable (tested: 0 of 13 startable, the start route answers 409) |

Items 2 to 4 together would let the cockpit run in Docker from its own config.yaml plus
environment, and `cockpit_docker_config.py` could be deleted.

## Advisable (the deployment works, but a person notices)

| # | Engine | File | What happens today | Proposed change |
|---|---|---|---|---|
| 5 | cockpit | `cockpit/src/cockpit/static/index.html` (uses `e.url`, `e.docs`, `n.url`), `settings.py` `Engine.public()` | The System page links each engine's own address and its `/docs`. In Docker these are internal names (`http://honi:8002/docs`) that a browser outside cannot open; the app link (`http://eigentlich:8017`) is not the public app address either. The proxy and the test benches work, because they go through the cockpit. | A separate browser-facing address per engine, optional: `public_url` in config.yaml, env `COCKPIT_ENGINE_<KEY>_PUBLIC_URL`; the page shows the link only when one is set. For the app: `COCKPIT_ENGINE_EIGENTLICH_PUBLIC_URL=https://app.<domain>`. |
| 6 | fmre (Instruments) | `Instruments/api/main.py`, `health()` | On a database without fmre's tables, `/v1/health` answers 500 (UndefinedTable) instead of a status. fmre also does not apply its schema at start-up, unlike every other engine. | Apply `store.db.initialise()` in a start-up hook (idempotent), or let `health()` answer 200 with `"status": "uninitialised"` when the tables are missing. Until then: `scripts/init-empty.sh` on an empty database, and compose waits for fmre as `service_started`, not `service_healthy`. |
| 7 | eigentlich (app) | `eigentliCH_Engines/eigentlich/src/eigentlich/api.py`, `lifespan` | The app does not create its tables at start-up (`python -m eigentlich init-db` is separate); on an empty database `/health` says `degraded`. | Call the store's `initialise()` in the lifespan, as the engines do. Until then: `scripts/init-empty.sh`. |
| 8 | cockpit | `cockpit/src/cockpit/api.py` | No `GET /health`; the container health check uses `GET /api/config`. | A standard `/health` like the engines'. |
| 9 | eigentlich (app) | `eigentliCH_Engines/eigentlich/src/eigentlich/__main__.py`, `_report_path()` | Maintenance commands (`seed`, `migrate`, `align-content`, ...) write their report to `ROOT/dev/reports/`. The image leaves out `dev/` and runs as a non-root user, so these commands fail in the container. The server itself never needs them. | `EIGENTLICH_REPORT_DIR`, defaulting to `ROOT/dev/reports`. |
| 10 | fmre (Instruments) | `Instruments/` | No `pyproject.toml`; the image installs `requirements.txt` plus `openpyxl` (imported by `store/etl/long_record.py` for the offline ETL). | A `pyproject.toml` with the service dependencies and an `etl` extra, like the other engines. |

## Watch points for the agents at work now

- **lbsim** (being finished): the Docker image runs `python -m lbsim serve --workers 0` for the
  API and `python -m lbsim worker` in separate containers. If either command, the `--workers`
  flag or the `upstream` block of config.yaml changes shape, `compose.yaml` and
  `config/lbsim.docker.yaml` must follow. Item 1 above removes the second dependency.
- **eigentlich** (next): the cockpit roster says the app consumes lbsim, but the app's config has
  no `lbsim_url` yet. If one is added, please give it an environment variable from the start
  (`EIGENTLICH_LBSIM_URL`, beside `EIGENTLICH_LBS_URL` in `appsettings.py` `_ENV`), and tell the
  coordinator so compose.yaml passes `http://lbsim:8014`.
- **Any new engine or roster change**: add a service to `compose.yaml` (and a port line to
  `compose.debug.yaml`), a `SIMTECH_<ENGINE>_PASSWORD` to `.env.example` and compose's
  `provision` service. The cockpit picks the engine up from its config.yaml at the next
  `docker compose build cockpit`.
