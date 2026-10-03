# Engine changes the Docker deployment asked for

State of 03.10.2026, for the two-container layout (`db` and `simtech`). Written on 01.10.2026 as a
list of engine changes, each with the workaround `deploy/` used until then. All ten are now in
the engines (commits 4d6350c, 91d1859 and 810fd9f, 03.10.2026), and `deploy/` uses them: the
workarounds are gone. Tested on 03.10.2026 on a separate compose project (README.md, "Backup and
restore").

Every engine takes its database host, port, name, user and password from the environment
(`<PREFIX>_DB_HOST`, `_DB_PORT`, `_DB_NAME`, `_DB_USER`, `_DB_PASSWORD`, or a full
`<PREFIX>_DATABASE_URL`) and its listening host from `<PREFIX>_HOST`. Inside the one `simtech`
container every engine reaches the others on `127.0.0.1:<port>`, the default in every
config.yaml, so no upstream address needs overriding.

## Open

| # | What | Who |
|---|---|---|
| 4 | The engine side is done (see below). What remains is configuration: `COCKPIT_ENGINE_EIGENTLICH_PUBLIC_URL=https://app.<domain>` in `.env` once the tunnel hostname exists (README.md, "Cloudflare Tunnel and Access", step 6). Optional; without it the System page simply does not link the app through the tunnel. | whoever runs the server |

No engine change is open.

## Done (03.10.2026)

| # | Engine | Change | Commit | What `deploy/` does now (and the workaround removed) |
|---|---|---|---|---|
| 1 | cockpit | `COCKPIT_CURATOR_DB_HOST`, `_PORT`, `_NAME`, `_USER` (C-38) | 4d6350c | `supervisord.conf` maps `COCKPIT_CURATOR_DB_HOST` and `_PORT` from `SIMTECH_DB_HOST` and `SIMTECH_DB_PORT` (`db:5432`); name and user are the config.yaml defaults. Removed: `docker/cockpit_docker_config.py`, which wrote a `config.local.yaml` at image build. |
| 2 | cockpit | `COCKPIT_LAUNCHER=off`: the start route answers 409, `start-engines` and `desktop` start nothing, the System page hides Start (C-39) | 4d6350c | `supervisord.conf` sets `COCKPIT_LAUNCHER=off`. Tested: 0 of 13 startable, the start route answers 409 with the cockpit's sentence. Removed: the same generated overlay, which stripped every `start`, `python` and `autostart`. |
| 3 | lbsim, lbs, report, chatbot, the app | `initialise()` takes `pg_advisory_xact_lock(hashtext('<engine>.schema'))` before the DDL | 91d1859 | The lbsim workers all start at once. Tested: on an empty database the API and 3 workers created the schema together, and 5 restarts of the API with its workers, without a deadlock or an exit. Removed: `RUN_STAGGER` in `supervisord.conf` and `run.sh` (worker n started 4 x (n - 1) seconds late). |
| 4 | cockpit | An optional browser-facing address per engine, `public_url` or `COCKPIT_ENGINE_<KEY>_PUBLIC_URL`; without one the System page links an engine only when the cockpit is opened on 127.0.0.1 or localhost (C-40) | 4d6350c | `compose.yaml` passes `COCKPIT_ENGINE_EIGENTLICH_PUBLIC_URL` from `.env` (empty by default); `.env.example` and the README describe it. The README's "known limit" (links to `http://127.0.0.1:80NN` through the tunnel) is gone: those links are no longer shown there. |
| 5 | fmre (Instruments) | Applies its schema at start-up (idempotent); `/v1/health` answers 200 `uninitialised` with the missing tables instead of a 500 (FMRE-42) | 810fd9f | Nothing to do on an empty database: fmre comes up `uncalibrated` and `simtech` goes healthy by itself. Removed: `scripts/init-empty.sh`, `simtech init-empty` and the README step. |
| 6 | eigentlich (app) | Applies its schema in the lifespan (app 1.5.2) | 91d1859 | As item 5: the app is `ok` on an empty database. |
| 7 | cockpit | `GET /health`, the standard answer (C-41) | 4d6350c | `docker/healthcheck.py` probes the cockpit at `/health` instead of `/api/config`. |
| 8 | eigentlich (app) | `EIGENTLICH_REPORT_DIR`, default `ROOT/dev/reports` (EIG-76) | 91d1859 | The image sets `EIGENTLICH_REPORT_DIR=/var/lib/simtech/reports`, a folder owned by `engine`; `simtech eigentlich ARGS` runs a maintenance command with the app's login, as `engine`. |
| 9 | fmre (Instruments) | `pyproject.toml` with the service dependencies, an `etl` extra, `packages = []` (runs from its folder) | 810fd9f | The image reads fmre's dependencies from its `pyproject.toml` with the `etl` extra (`deps.py` now takes `file.toml[extra]`), like every other engine. Removed: the install from `Instruments/requirements.txt` and the `--extra openpyxl` special case. |
| 10 | every engine with uvicorn, the app, the cockpit | Successful health probes (`/health`, fmre's `/v1/health`, the cockpit's `/health` and `/api/config`) are left out of the access log | 4d6350c (cockpit, C-42), 91d1859 (eigentliCH engines and the app), 810fd9f (fmre, Macro engines, pcp) | Nothing to configure. Tested: over 2 minutes (4 container health checks, 56 probes) `docker compose logs simtech` gained no line; other requests are still logged. |

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
- **Schema at start-up**: every engine, fmre and the app apply their own schema when they
  start, and the container relies on it (there is no separate initialisation step any more). An
  engine run as several processes at once (lbsim and its workers) must keep the advisory lock.
- **Health probes**: a new engine should leave its health route out of the access log as the
  others do, or `docker compose logs simtech` fills with probe lines again.
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
