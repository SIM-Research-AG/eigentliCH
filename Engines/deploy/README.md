# sim-tech / eigentliCH on Docker

For the person who runs the team server (Linux x86_64). You need to know Docker and Compose;
you do not need to know the code. Written 29.09.2026, restructured to two containers on
01.10.2026.

**What runs:** two containers.

- `db`: PostgreSQL 18 (the official image) with the one database `simtech`. It also runs the
  nightly backup.
- `simtech`: one image with everything else, under supervisord: the start-up provisioning, the
  13 engines, the lbsim plan workers, the consumer app `eigentlich` (8017), the cockpit (8000)
  and, when a tunnel token is set, the Cloudflare Tunnel (`cloudflared`).

Only the app and the cockpit are reachable from outside, through the tunnel and Cloudflare
Access. The host publishes no port.

**What does not change on the owner's machine:** this folder is all there is. The engine
changes this deployment asked for ([ENGINE_CHANGES.md](ENGINE_CHANGES.md)) are in the engines
since 03.10.2026, so every engine, the app and the cockpit run from their own committed
config.yaml plus environment, with no overlay and no workaround.

## Contents

- [The system at a glance](#the-system-at-a-glance)
- [What you need](#what-you-need)
- [Sizing](#sizing)
- [First start (day one, from the owner's dump)](#first-start-day-one-from-the-owners-dump)
- [Start order](#start-order)
- [Health check](#health-check)
- [Cloudflare Tunnel and Access](#cloudflare-tunnel-and-access)
- [Backup and restore](#backup-and-restore)
- [Upgrade](#upgrade)
- [Everyday commands](#everyday-commands)
- [Changing a password](#changing-a-password)
- [The cockpit in Docker](#the-cockpit-in-docker)
- [How configuration reaches the engines](#how-configuration-reaches-the-engines)
- [What is not in the repository](#what-is-not-in-the-repository)
- [Files in this folder](#files-in-this-folder)

## The system at a glance

| Container | Image | Volumes | Health |
|---|---|---|---|
| `db` | `postgres:18` | `pgdata` (the database), `backups` (the nightly dumps) | `pg_isready` |
| `simtech` | `simtech/simtech:local`, built on the server | `cockpit-data` (the CIO's decision log) | every route below answers 200 |

The programs supervisord runs in `simtech`, in start order:

| Program | Port (127.0.0.1) | Health route | Waits for |
|---|---|---|---|
| `provision` (one-shot) | | exits 0 | `db` healthy |
| `datafeed` (01) | 8001 | `/health` | provision |
| `honi` (02), `macrofield` (03), `mrs` (05) | 8002, 8003, 8005 | `/health` | datafeed |
| `lbs` (13) | 8013 | `/health` | provision |
| `cycle` (12) | 8012 | `/health` | datafeed, macrofield |
| `aggregation` (04) | 8004 | `/health` | mrs, cycle, macrofield |
| `fmre` (06) | 8006 | `/v1/health` | aggregation |
| `pcp` (07) | 8007 | `/health` | aggregation, fmre |
| `lbsim` (14, API only) | 8014 | `/health` | lbs, pcp, aggregation, fmre |
| `lbsim-worker-1` ... `-N` | none | `supervisorctl status` | lbsim |
| `report` (15) | 8015 | `/health` | lbs, pcp, lbsim |
| `chatbot` (16) | 8016 | `/health` | lbsim |
| `eigentlich` (the app) | 8017 (0.0.0.0) | `/health` | lbs, lbsim, report, chatbot |
| `cockpit` (11) | 8000 (0.0.0.0) | `/health` | the app |
| `cloudflared` (only with a token) | | | the app, the cockpit |

Inside `simtech` the engines reach each other on `http://127.0.0.1:<port>`, which is what every
engine's config.yaml says, and the database as `db:5432`. Every engine has its own database login
(role = engine name) and owns one schema of the database `simtech`; the provisioning creates them.
Engines 08, 09 and 10 are not built and are not in the roster.

## What you need

- A Linux x86_64 server with a current Docker Engine and the Compose plugin (tested with Docker
  29.5 and Compose 5.1). BuildKit, the default builder, is required (the image has its own
  `.dockerignore` beside its Dockerfile). About 1 GB of disk for the image, plus the database
  and its backups.
- Outbound HTTPS from the server to Cloudflare (the tunnel) and to `spark7.minimind.ch` (the
  MiniMind model server that report and chatbot call).
- A clone of the repository: `git clone https://github.com/SIM-Research-AG/eigentliCH.git
  /opt/simtech` (branch `main`). The deployment lives in `/opt/simtech/Engines/deploy`, and the
  image is built from `/opt/simtech/Engines`. The image takes nothing else from the machine.
- From the owner: the dump of today's `simtech` database, and the two MiniMind values
  `SPARK7_CLIENT_ID` and `SPARK7_CLIENT_SECRET`.
- From you: every password in `.env`, a Cloudflare account with Zero Trust, the two hostnames,
  and who may sign in.

## Sizing

Everything except the database shares one container, so its limits are set once, in `.env`:

| Setting | Default | What it does |
|---|---|---|
| `LBSIM_WORKERS` | 3 | lbsim plan workers. Each solve (CasADi/IPOPT with MUMPS) keeps **one core** busy for its whole run; the maths libraries are held to one thread per worker. More workers: more plans at the same time, not a faster single plan. |
| `SIMTECH_CPUS` | 6 | compose `cpus` of `simtech`: the cores all its programs together may use. |
| `SIMTECH_MEMORY` | 10g | compose `mem_limit` of `simtech`. If it is reached, the kernel ends the largest process (usually a solving worker); supervisord starts it again, and lbsim puts the plan run back in the queue once its heartbeat has gone stale. |

Rule of thumb: `SIMTECH_CPUS` = `LBSIM_WORKERS` + 3 (the engines, the app and the cockpit need
little CPU, but leave them room while all workers solve), and `SIMTECH_MEMORY` = 2 GB + 2 GB per
worker. Measured on 01.10.2026 with the owner's data: idle, `simtech` uses about 1.1 GB and `db`
about 150 MB. A server with 8 cores and 16 GB runs the defaults comfortably; for 6 workers give
`simtech` 9 cores and 14 GB. The `db` container has no limit; give it one in compose.yaml if the
server runs other things.

## First start (day one, from the owner's dump)

All commands run in this folder (`/opt/simtech/Engines/deploy`) on the server unless said
otherwise.

**1. Settings.**

```bash
cp .env.example .env && chmod 600 .env
chmod +x scripts/*.sh            # a copy from Windows may lose the executable bit
# edit .env: replace every CHANGE_ME (admin password, 15 role passwords, SPARK7_*, tunnel token)
```

Leave `CLOUDFLARE_TUNNEL_TOKEN` empty until Cloudflare Access is set up (step 6).

**2. Build the image** (on the server, no registry). About 2 to 4 minutes the first time.

```bash
docker compose build
```

**3. The dump.** On the owner's machine, where the live server is the container `postgres_server`:

```bash
docker exec postgres_server pg_dump -U myuser -d simtech -Fc -f /tmp/simtech-2026-09-29.dump
docker cp postgres_server:/tmp/simtech-2026-09-29.dump .
docker exec postgres_server rm /tmp/simtech-2026-09-29.dump
```

`pg_dump` only reads; the live database is not changed. Copy the file to the server (for example
with `scp`); it contains client records, so keep it off shared drives and delete it when done.

**4. Restore and start everything.**

```bash
./scripts/restore.sh ~/simtech-2026-09-29.dump
```

The script asks for `yes`, then: stops `simtech` (if it runs), starts `db`, runs the provisioning
(so that every engine role exists before the dump refers to it), copies the dump into the `db`
container, drops and recreates `simtech`, restores the dump with its original owners, deletes the
copy, runs the provisioning again (database grants, new schemas) and starts both containers. It
prints each schema with its owner and table count, and any pg_restore error. If one reads
`role "x" does not exist`, that role was made by hand on the owner's machine and is not in the
roster: tell the owner. If the provisioning then warns that an object "is owned by myuser, not
the engine role", the owner's database has that object owned by the administrator; the engine may
fail to start on it, and `store.provision.adopt()` hands it over (ask the owner first).

**5. Check.** After a minute, `./scripts/health.sh` should end with `all ok`.

**6. Open the way in:** [Cloudflare Tunnel and Access](#cloudflare-tunnel-and-access).

**Starting without a dump** (an empty system, e.g. to try it out): `docker compose up -d`. Every
engine and the app create their tables at start-up, so `simtech` goes healthy by itself, but
empty: there is no source data, no calibration (fmre says `uncalibrated`) and no questionnaire
content.

## Start order

`docker compose up -d` starts `db` and waits until it is healthy; then `simtech`, where
supervisord starts every program at once and each one waits for its turn (`docker/run.sh`):

1. `provision` runs `python -m store.provision` (idempotent: it runs on every start of the
   container, creates what is missing and changes nothing that exists; role passwords are set
   only when a role is created). It retries every 15 seconds until it succeeds, then exits 0;
2. every other program waits for that, then for the ports of the engines it consumes (table
   above), so datafeed comes first and macrofield is up before cycle. If an upstream still does
   not answer after 5 minutes, the program starts anyway and says so in the log: the engines call
   each other per request, not at start-up;
3. the app after lbs, lbsim, report and chatbot; the cockpit after the app; cloudflared last.

With the owner's data, `simtech` is healthy about 30 seconds after it starts. Every program is
restarted by supervisord when it exits (one that keeps failing at once is retried with a growing
pause); both containers restart by themselves (`unless-stopped`), including after a reboot of the
server. `docker compose stop` stops the programs in reverse order, within a few seconds.

## Health check

```bash
./scripts/health.sh
```

Prints both containers' state and health, every program in `simtech` with its supervisord state
(`provision` is `EXITED` once it has done its work, `cloudflared` is `STOPPED` without a token),
every health route called from inside `simtech` with the HTTP status and the engine's own
`status` field, and whether the database answers. Ends with `all ok` and exit status 0 when
everything is as it should be, so it can go into a monitoring job.

Expected values: `ok` for all; `fmre` says `uncalibrated` until a calibration is loaded (on an
empty database), and `uninitialised` if it could not create its tables at start-up (its log says
why; `supervisorctl restart fmre` tries again); the app says `degraded` when its database is
unreachable. `docker compose ps` alone shows the health that
Docker itself checks every 30 seconds (`simtech health --quiet`: every route must answer 200).

## Cloudflare Tunnel and Access

The app has **no sign-in in its code** (the owner's decision); neither has the cockpit. Cloudflare
Access is the only thing between the internet and client data, so set up Access **before** the
public hostnames.

1. **Access applications** (Zero Trust > Access > Applications > Add an application >
   Self-hosted), one per hostname, for example:
   - `app.<your-domain>` (the consumer app)
   - `cockpit.<your-domain>` (the cockpit)

   For each: a policy with action *Allow* for exactly the people who may use it (emails, an email
   domain, or an identity provider group); session duration as you see fit (for example 24 hours);
   identity provider as your organisation uses. Keep the cockpit's group smaller than the app's:
   in `development` mode the cockpit lets its users write to every engine.
2. **Tunnel** (Zero Trust > Networks > Tunnels > Create a tunnel > Cloudflared). Copy the token
   from the install command Cloudflare shows (the long value after `--token`) into
   `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. Do not run Cloudflare's command: cloudflared is built into
   the `simtech` image and supervisord runs it.
3. **Public hostnames** of that tunnel:
   - `app.<your-domain>`, service type HTTP, URL `127.0.0.1:8017`
   - `cockpit.<your-domain>`, service type HTTP, URL `127.0.0.1:8000`

   Nothing else. cloudflared runs inside `simtech`, where every engine also listens on
   127.0.0.1, so a further hostname would expose an engine without the cockpit in front of it:
   keep the right to edit this tunnel to the people who run the server.
4. Start the tunnel: `docker compose up -d` (the container is recreated with the token, and
   cloudflared starts once the app and the cockpit answer). Its log lines start with
   `[cloudflared]`.
5. Test from outside: both hostnames must first show the Cloudflare Access sign-in page.
6. Optional: set `COCKPIT_ENGINE_EIGENTLICH_PUBLIC_URL=https://app.<your-domain>` in `.env` and
   `docker compose up -d`, so that the cockpit's System page links the app at its public
   address. Without it, the System page links an engine only when the cockpit itself is opened
   on 127.0.0.1 or localhost (the debug files, [Everyday commands](#everyday-commands)), because
   through the tunnel `http://127.0.0.1:80NN` would point at the viewer's own computer. The cockpit reads
   `COCKPIT_ENGINE_<KEY>_PUBLIC_URL` for every engine in its roster, but the engines have no
   public hostname here (step 3), so leave the others unset.

To run without the tunnel, empty `CLOUDFLARE_TUNNEL_TOKEN` and `docker compose up -d`. A new
cloudflared release: set `CLOUDFLARED_VERSION` in `.env`, then `docker compose build` and
`docker compose up -d`.

## Backup and restore

**Nightly.** The `db` container runs `scripts/backup.sh` beside PostgreSQL (started by
`scripts/db-entrypoint.sh` before the image's own entrypoint; the official image and two small
scripts, nothing installed). Every day at `BACKUP_AT` (default 02:30, `TZ` Europe/Zurich) it
writes into the named volume `backups`:

- `simtech-YYYY-MM-DD_HHMM.dump`, a `pg_dump -Fc` of `simtech`;
- `globals-YYYY-MM-DD_HHMM.sql`, the roles with their password hashes (`pg_dumpall --globals-only`);

and deletes files older than `BACKUP_KEEP_DAYS` (default 14). Its log lines in
`docker compose logs db` contain `backup:`. These files are on the same disk as the database:
copy them off the server as well (your usual backup tool, reading the volume's folder
`docker volume inspect simtech_backups --format '{{ .Mountpoint }}'`).

Why in `db`: `pg_dump` must match the server's major version, and the `postgres:18` image has
exactly that one; in `simtech` it would need the PostgreSQL apt repository and a client package
kept in step with the server.

**On demand,** for example before an upgrade:

```bash
docker compose exec db bash /scripts/backup.sh now
docker compose exec db ls -l /backups
docker compose cp db:/backups/simtech-2026-10-01_1430.dump .      # copy one out
```

**Restore** (replaces the whole `simtech` database on this server; asks for `yes`):

```bash
./scripts/restore.sh /path/to/simtech-YYYY-MM-DD_HHMM.dump          # a file on the server
./scripts/restore.sh --backup simtech-YYYY-MM-DD_HHMM.dump          # a file in the backup volume
```

Same steps as on day one. The roles and their passwords are not in a `simtech-*.dump`; they
come from `.env` through the provisioning. `globals-*.sql` is only needed to bring back the *old*
role passwords on a rebuilt server: after the restore,
`docker compose exec -T db psql -U myuser -d postgres < globals-....sql` (its `CREATE ROLE` lines
fail harmlessly because the roles exist; its `ALTER ROLE ... PASSWORD` lines apply), and `.env`
must then hold those old values.

Tested on 01.10.2026 on a separate compose project with empty volumes: the owner's dump of
29.09.2026 (`simtech_for_server_2026-09-29.dump`, 24.6 MB) restored with this script in 14
seconds, no pg_restore errors, every schema owned by its engine, every health route `ok`; then
`backup.sh now`, and `restore.sh --backup` of that backup, with the same result.

Tested again on 03.10.2026 with the engines' changes (ENGINE_CHANGES.md): on an empty database
`simtech` went healthy by itself in about 35 seconds (fmre `uncalibrated`, everything else `ok`);
the same dump restored in 13 seconds with no pg_restore errors, healthy 30 seconds later, with
the Default Regime, 20 clients, their lbs sheets and stored reports readable through the
engines and the app, the cockpit's curator store reachable on `db` and no engine startable
through the cockpit; the 3 lbsim workers started together (and with the lbsim API, 5 times)
without one exiting; and 2 minutes of `docker compose logs simtech` held no health-probe line.

## Upgrade

New engine code:

```bash
docker compose exec db bash /scripts/backup.sh now         # 1. a backup first
docker tag simtech/simtech:local simtech/simtech:prev       # 2. keep a way back
git -C /opt/simtech pull                                    # 3. new code (deploy/.env is git-ignored and stays)
docker compose build                                        # 4. rebuild (cached layers: fast)
docker compose up -d                                        # 5. recreates simtech; db keeps running
./scripts/health.sh
```

Engines apply their own schema changes at start-up (idempotent `schema.sql`); the provisioning
runs at every start of `simtech` and adds roles and schemas for engines new to the roster. To go
back: set `IMAGE_TAG=prev` in `.env` and `docker compose up -d`. A database change is not undone
by that: restore the backup from step 1 if needed.

Python packages: the versions are pinned in `docker/constraints.txt`; change a version there and
rebuild. The engines' own `pyproject.toml` files decide which packages are installed.

PostgreSQL within 18 (18.x): `docker compose pull db && docker compose up -d db`. To a new major
version: take a dump, point the `postgres:18` line in compose.yaml at the new version, remove the
`pgdata` volume (after the dump is safe) and restore.

## Everyday commands

```bash
docker compose ps                                          # both containers and their health
docker compose exec simtech supervisorctl status           # every program inside simtech
docker compose logs -f --tail 200 simtech                  # all programs, each line "[name] ..."
docker compose logs -f --no-log-prefix simtech | grep '^\[lbsim'     # lbsim and its workers only
docker compose exec simtech supervisorctl restart honi     # restart one engine
docker compose exec simtech supervisorctl restart 'lbsim-worker:*'   # every plan worker
docker compose restart simtech                             # every program, provisioning first
docker compose exec simtech simtech health                 # the health routes alone
docker compose exec simtech simtech eigentlich show        # an app maintenance command (python -m eigentlich ...)
docker compose exec db psql -U myuser -d simtech           # a SQL prompt as administrator
docker compose -f compose.yaml -f compose.debug.yaml up -d # app and cockpit on 127.0.0.1:8017 / :8000
```

More plan workers: set `LBSIM_WORKERS` (and `SIMTECH_CPUS`, `SIMTECH_MEMORY`, see
[Sizing](#sizing)) in `.env`, then `docker compose up -d`. For debugging every engine from the
server, add `-f compose.debug-engines.yaml` as a third file: it publishes every engine port and
the database on 127.0.0.1 (move the database with `DEBUG_PG_PORT` if 5432 is taken).

The container logs use Docker's json-file driver, 5 files of 20 MB kept for each container.

## Changing a password

The provisioning sets a role's password only when it creates the role. To change one later:

```bash
docker compose exec db psql -U myuser -d postgres -c "ALTER ROLE honi PASSWORD 'new-value'"
# put the same value in .env (SIMTECH_HONI_PASSWORD), then:
docker compose up -d
```

`up -d` recreates the `simtech` container with the new environment (all programs restart, about
30 seconds). For the curator: role `curator`, variable `SIMTECH_CURATOR_PASSWORD`. For the
administrator: `ALTER ROLE myuser ...`, then `POSTGRES_ADMIN_PASSWORD` in `.env` (the server keeps
the password it was created with; `POSTGRES_PASSWORD` only matters on an empty volume).

## The cockpit in Docker

On the owner's machine the cockpit's desktop app starts every engine (`autostart: true` and a
`start` command for each engine in `cockpit/config.yaml`). In Docker supervisord starts the
engines, and the cockpit only shows status. It runs from its committed `config.yaml` (the
engine addresses `http://127.0.0.1:80NN` are right inside `simtech`) plus environment, set in
`docker/supervisord.conf`:

- `python -m cockpit serve`, never `desktop` or `start-engines`;
- `COCKPIT_LAUNCHER=off`: no engine is startable, the System page shows no Start, and
  `POST /api/launcher/{key}/start` answers 409 with a sentence saying why;
- `COCKPIT_CURATOR_DB_HOST` and `_PORT` from `SIMTECH_DB_HOST` and `SIMTECH_DB_PORT` (`db:5432`),
  the password from `SIMTECH_CURATOR_PASSWORD`; database `simtech` and user `curator` are the
  config.yaml defaults;
- `COCKPIT_DATA_DIR=/data` (the `cockpit-data` volume) and, when set in `.env`,
  `COCKPIT_ENGINE_EIGENTLICH_PUBLIC_URL` ([Cloudflare Tunnel and Access](#cloudflare-tunnel-and-access), step 6).

Its health route is `GET /health`. Opened through the tunnel, the System page leaves out the
links to the engines' own addresses (they would point at the viewer's computer); the test
benches and the proxy work, because they go through the cockpit.

`COCKPIT_MODE` in `.env`: `development` (the default, the owner's decision: everything, including
the test benches and every write through the proxy) or `cio` (the CIO workspace and system status
only).

## How configuration reaches the engines

Every engine reads `config.yaml < config.local.yaml < environment`. The image contains the
committed `config.yaml` files and never a developer's `config.local.yaml`, `.env` or
`config.toml`. Inside `simtech`:

- the engines listen on 127.0.0.1 and call each other there, exactly as their config.yaml says;
  only the app and the cockpit listen on 0.0.0.0, so that `compose.debug.yaml` can publish them;
- `docker/run.sh` gives each program, from the container's environment, `<PREFIX>_DB_HOST=db`,
  `<PREFIX>_DB_PORT=5432`, `<PREFIX>_DB_USER` (the engine's role) and `<PREFIX>_DB_PASSWORD` (its
  `SIMTECH_<ENGINE>_PASSWORD`). The prefix is the engine name in capitals; fmre uses
  `INSTRUMENTS_DB_*` with role `fmre`. Database and schema stay as in config.yaml;
- `run.sh` then removes every secret the program does not need from its environment: an engine
  sees its own password and no other, only report and chatbot see `SPARK7_CLIENT_ID` and
  `SPARK7_CLIENT_SECRET`, only cloudflared the tunnel token (as `TUNNEL_TOKEN`), only the
  provisioning the administrator password. Every program runs as the unprivileged user `engine`
  (uid 10001). This keeps a secret out of an engine's error pages and logs; it is not a wall
  between engines, which share the user and the container;
- the lbsim API runs as `python -m lbsim serve --workers 0`; the plan workers run as
  `python -m lbsim worker`, `LBSIM_WORKERS` of them, with the maths libraries held to one thread.
  They all start at once: every eigentliCH store applies its schema under an advisory lock, so
  processes starting together queue for it;
- the app's maintenance commands (`simtech eigentlich seed`, `migrate`, `align-content`, ...)
  write their reports to `EIGENTLICH_REPORT_DIR=/var/lib/simtech/reports`, a folder in the
  container owned by `engine` (not a volume: `docker compose cp simtech:/var/lib/simtech/reports .`
  to keep one);
- successful health probes are left out of every engine's, the app's and the cockpit's access
  log, so `docker compose logs simtech` shows real requests only.

## What is not in the repository

The build needs nothing outside the `Engines` folder. The image leaves out, on purpose: every
`.venv`, `.env`, `config.local.yaml` and `config.toml`, `tests/`, `golden/`, `dev/`, caches,
`*.cmd`, `macrofield/data/archive` and the cockpit's `data/`. So the engines' test suites do not
run inside the image; run them on a development machine.

Some one-off loading commands read files that are not in the repository. None is needed after a
restore from the owner's dump:

| Command | Needs | Where it is on the owner's machine |
|---|---|---|
| `python -m datafeed bootstrap` | the MATLAB export `M_TS.mat` and the ticker workbooks (`DATAFEED_MATLAB_DIR`) | `SIM_NAS/SIM_Tech/Master_Controller` |
| `python -m store.etl.bootstrap` (fmre) | the feed CSV and the ECN folder (`INSTRUMENTS_FEED_CSV`, `INSTRUMENTS_ECN_DIR`) | outside `Engines` |
| `simtech eigentlich seed` / `migrate` | the questionnaire prototype and its SQLite file (`EIGENTLICH_PROTOTYPE_ROOT`, `EIGENTLICH_MIGRATE_FROM`) | `Projects/eigentliCH/Prototype` |

## Files in this folder

| File | What it is |
|---|---|
| `compose.yaml` | the two containers, their environment, volumes, limits and health checks |
| `compose.debug.yaml` | optional: publishes the app and the cockpit on 127.0.0.1 |
| `compose.debug-engines.yaml` | optional, with the one above: every engine and the database on 127.0.0.1 |
| `.env.example` | every setting and secret, with placeholders; copy to `.env` |
| `docker/simtech.Dockerfile` | the one image: a Python environment for all engines, supervisord, cloudflared |
| `docker/simtech.Dockerfile.dockerignore` | the allowlist of what enters the build |
| `docker/supervisord.conf` | every program in `simtech`: folder, command, database role, start order |
| `docker/run.sh` | starts one program: its database login, secrets removed, waits, log prefix |
| `docker/simtech.sh` | the container's entrypoint and the `simtech` command (start, provision, eigentlich, health) |
| `docker/provision.sh` | the start-up provisioning (supervisord's one-shot program) |
| `docker/healthcheck.py` | every health route (standard library only) |
| `docker/constraints.txt` | pinned package versions (from the owner's working environments) |
| `docker/deps.py` | reads the engines' dependencies from their `pyproject.toml` |
| `scripts/health.sh` | health of the whole deployment |
| `scripts/restore.sh` | restore a dump, in the right order (runs on the host) |
| `scripts/restore-db.sh` | the pg_restore step (runs in `db`) |
| `scripts/backup.sh` | the nightly and on-demand backup (runs in `db`) |
| `scripts/db-entrypoint.sh` | starts the backup loop in `db`, then PostgreSQL |
| `ENGINE_CHANGES.md` | the engine changes this deployment asked for, done and open |

Every script on the host takes the compose project and env file from the usual
`COMPOSE_PROJECT_NAME` and `COMPOSE_ENV_FILES` variables, so a second copy (for example a test
project) can be checked and restored the same way.
