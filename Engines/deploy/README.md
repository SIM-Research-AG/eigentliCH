# sim-tech / eigentliCH on Docker

For the person who runs the team server (Linux x86_64). You need to know Docker and Compose;
you do not need to know the code. Written 29.09.2026.

**What runs:** 13 engines, the consumer app `eigentlich` and the cockpit, each in its own
container, built from five images (one per family), plus PostgreSQL 18, a one-shot provisioning
job, a nightly backup and a Cloudflare Tunnel. Only the app and the cockpit are reachable from
outside, through the tunnel and Cloudflare Access. Nothing publishes a host port.

**What does not change on the owner's machine:** this folder is new. No engine was modified; the
changes the engines would benefit from are listed in [ENGINE_CHANGES.md](ENGINE_CHANGES.md).

## Contents

- [The system at a glance](#the-system-at-a-glance)
- [What you need](#what-you-need)
- [First start (day one, from the owner's dump)](#first-start-day-one-from-the-owners-dump)
- [Start order](#start-order)
- [Health check](#health-check)
- [Cloudflare Tunnel and Access](#cloudflare-tunnel-and-access)
- [Backup and restore](#backup-and-restore)
- [Upgrade](#upgrade)
- [Everyday commands](#everyday-commands)
- [The cockpit in Docker](#the-cockpit-in-docker)
- [How configuration reaches the engines](#how-configuration-reaches-the-engines)
- [What is not in the repository](#what-is-not-in-the-repository)
- [Files in this folder](#files-in-this-folder)

## The system at a glance

| Service | Image | Port (internal) | Health | Waits for |
|---|---|---|---|---|
| `postgres` | `postgres:18` | 5432 | `pg_isready` | |
| `provision` (one-shot) | instruments | | exits 0 | postgres |
| `backup` | `postgres:18` | | | postgres |
| `datafeed` (01) | macro | 8001 | `/health` | provision |
| `honi` (02) | macro | 8002 | `/health` | datafeed |
| `macrofield` (03) | macro | 8003 | `/health` | datafeed |
| `mrs` (05) | macro | 8005 | `/health` | datafeed |
| `cycle` (12) | macro | 8012 | `/health` | datafeed, macrofield |
| `aggregation` (04) | macro | 8004 | `/health` | mrs, cycle, macrofield |
| `fmre` (06) | instruments | 8006 | `/v1/health` | aggregation |
| `pcp` (07) | optimizer | 8007 | `/health` | aggregation, fmre (started) |
| `lbs` (13) | eigentlich | 8013 | `/health` | provision |
| `lbsim` (14, API only) | eigentlich | 8014 | `/health` | lbs, pcp, aggregation, fmre (started) |
| `lbsim-worker` (x3) | eigentlich | none | | lbsim |
| `report` (15) | eigentlich | 8015 | `/health` | lbs, pcp, lbsim |
| `chatbot` (16) | eigentlich | 8016 | `/health` | lbsim |
| `eigentlich` (the app) | eigentlich | 8017 | `/health` | lbs, lbsim, report, chatbot |
| `cockpit` (11) | cockpit | 8000 | `/api/config` | provision |
| `cloudflared` | `cloudflare/cloudflared` | | | eigentlich, cockpit |

Every engine gets its own database login (role = engine name) and owns one schema of the one
database `simtech`; the provisioning creates them. Containers reach each other by service name:
`http://fmre:8006`, `postgres:5432`.

Engines 08, 09 and 10 are not built and are not in the roster.

## What you need

- A Linux x86_64 server with a current Docker Engine and the Compose plugin (tested with Docker
  29.5 and Compose 5.1). BuildKit, the default builder, is required because each image has its
  own `.dockerignore`. About 3 GB of disk
  for the images, plus the database and its backups.
- Sizing: idle, all containers together use about 1.3 GB of RAM (measured). Each lbsim worker is
  limited to 1 CPU and 2 GB while it solves a plan. 8 cores and 16 GB leave comfortable room.
- Outbound HTTPS from the server to Cloudflare (the tunnel) and to `spark7.minimind.ch` (the
  MiniMind model server that report and chatbot call).
- A clone of the repository: `git clone https://github.com/SIM-Research-AG/eigentliCH.git
  /opt/simtech` (branch `main`). The deployment lives in `/opt/simtech/Engines/deploy`, and the
  images are built from `/opt/simtech/Engines`. The images take nothing else from the machine.
- From the owner: the dump of today's `simtech` database, and the two MiniMind values
  `SPARK7_CLIENT_ID` and `SPARK7_CLIENT_SECRET`.
- From you: every password in `.env`, a Cloudflare account with Zero Trust, the two hostnames,
  and who may sign in.

## First start (day one, from the owner's dump)

All commands run in this folder (`Engines/deploy`) on the server unless said otherwise.

**1. Settings.**

```bash
cp .env.example .env && chmod 600 .env
chmod +x scripts/*.sh            # a copy from Windows may lose the executable bit
# edit .env: replace every CHANGE_ME (admin password, 15 role passwords, SPARK7_*, tunnel token)
```

**2. Build the images** (on the server, no registry). About 4 minutes the first time.

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

The script asks for `yes`, then: starts postgres, runs the provisioning (so that every engine
role exists before the dump refers to it), drops and recreates `simtech`, restores the dump with
its original owners, runs the provisioning again (database grants, new schemas) and starts all
services. It prints each schema with its owner and table count, and any pg_restore error. If one
reads `role "x" does not exist`, that role was made by hand on the owner's machine and is not in
the roster: tell the owner. If the provisioning then warns that an object "is owned by myuser, not
the engine role", the owner's database has that object owned by the administrator; the engine may
fail to start on it, and `store.provision.adopt()` hands it over (ask the owner first).

**5. Check.** `./scripts/health.sh` should show every endpoint `ok`.

**6. Open the way in:** [Cloudflare Tunnel and Access](#cloudflare-tunnel-and-access).

**Starting without a dump** (an empty system, e.g. to try it out): `docker compose up -d`, then
`./scripts/init-empty.sh`, which creates the tables of the two services that do not create their
own at start-up (fmre and the app). Everything is healthy, but empty: there is no source data,
no calibration and no questionnaire content.

## Start order

`docker compose up -d` starts everything in this order, each step waiting for the previous one:

1. `postgres` until `pg_isready` answers;
2. `provision` runs `python -m store.provision` and exits 0 (idempotent: it runs on every `up`,
   creates what is missing and changes nothing that exists; role passwords are set only when a
   role is created);
3. the engines in roster order: an engine waits until the engines it consumes are healthy
   (table above), so datafeed comes first and macrofield is up before cycle;
4. the app after lbs, lbsim, report and chatbot; the cockpit straight after provisioning, so that
   it can show an engine that is down;
5. `cloudflared` last.

`fmre` is waited for as *started*, not *healthy*, because its health reads its own tables and
answers 500 while they do not exist (ENGINE_CHANGES.md, item 6). Every service restarts by itself
(`unless-stopped`), including after a reboot of the server.

## Health check

```bash
./scripts/health.sh
```

Prints every container's state and health, then calls every engine's health endpoint from inside
the cockpit container (engines have no host ports) and prints the HTTP status and the engine's
own `status` field. Exit status 0 when all answered 200, so it can go into a monitoring job.

Expected values: `ok` for all; `fmre` says `uncalibrated` until a calibration is loaded; the app
says `degraded` when its database is unreachable. `docker compose ps` alone shows the health that
Docker itself checks every 30 seconds.

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
2. **Tunnel** (Zero Trust > Networks > Tunnels > Create a tunnel > Cloudflared > Docker). Copy the
   token from the command Cloudflare shows (the long value after `--token`) into
   `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. Do not run Cloudflare's command; compose runs cloudflared.
3. **Public hostnames** of that tunnel:
   - `app.<your-domain>`, service type HTTP, URL `eigentlich:8017`
   - `cockpit.<your-domain>`, service type HTTP, URL `cockpit:8000`

   Nothing else. The engines and Postgres are not exposed.
4. Start or restart the tunnel: `docker compose up -d cloudflared` (it runs when
   `COMPOSE_PROFILES=tunnel` is in `.env`; leave that empty to run without a tunnel).
5. Test from outside: both hostnames must first show the Cloudflare Access sign-in page.

Once it works, pin the cloudflared image to a release in `.env` (`CLOUDFLARED_VERSION`).

## Backup and restore

**Nightly.** The `backup` service writes, every day at `BACKUP_AT` (default 02:30, `TZ`
Europe/Zurich), into the named volume `backups`:

- `simtech-YYYY-MM-DD_HHMM.dump`, a `pg_dump -Fc` of `simtech`;
- `globals-YYYY-MM-DD_HHMM.sql`, the roles with their password hashes (`pg_dumpall --globals-only`);

and deletes files older than `BACKUP_KEEP_DAYS` (default 14). These files are on the same disk as
the database: copy them off the server as well (your usual backup tool, reading the volume's
folder `docker volume inspect simtech_backups --format '{{ .Mountpoint }}'`).

**On demand,** for example before an upgrade:

```bash
docker compose exec backup bash /scripts/backup.sh now
docker compose exec backup ls -l /backups
docker compose cp backup:/backups/simtech-2026-09-29_1430.dump .      # copy one out
```

**Restore** (replaces the whole `simtech` database on this server; asks for `yes`):

```bash
./scripts/restore.sh /path/to/simtech-YYYY-MM-DD_HHMM.dump
```

Same steps as on day one. A file already in the backup volume: copy it out first with
`docker compose cp` as above. The roles and their passwords are not in a `simtech-*.dump`; they
come from `.env` through the provisioning. `globals-*.sql` is only needed to bring back the *old*
role passwords on a rebuilt server: after the restore, `docker compose exec -T postgres psql -U
myuser -d postgres < globals-....sql` (its `CREATE ROLE` lines fail harmlessly because the roles
exist; its `ALTER ROLE ... PASSWORD` lines apply), and `.env` must then hold those old values.

Tested on 29.09.2026 on a separate test project: backup, then restore into the same server, then
provisioning; every schema came back with its engine as owner and every health check was `ok`.
The owner's real dump of 29.09.2026 (`simtech_for_server_2026-09-29.dump`, 24.6 MB) was restored
the same way on a fresh test project: no pg_restore errors, no object owned by anyone but its
engine, no role outside the roster, the curator's grants on `eigentlich` intact, and every engine
healthy straight away, without `init-empty.sh`.

## Upgrade

New engine code:

```bash
docker compose exec backup bash /scripts/backup.sh now     # 1. a backup first
git -C /opt/simtech pull                                    # 2. new code (deploy/.env is git-ignored and stays)
docker compose build                                        # 3. rebuild (cached layers: fast)
docker compose up -d                                        # 4. recreates only what changed
./scripts/health.sh
```

Engines apply their own schema changes at start-up (idempotent `schema.sql`); `provision` runs
again on `up` and adds roles and schemas for engines new to the roster. To keep a way back, tag
the running images before step 3 (`for i in macro instruments optimizer eigentlich cockpit; do
docker tag simtech/$i:local simtech/$i:prev; done`); to go back, set `IMAGE_TAG=prev` in `.env`
and `docker compose up -d`. A database change is not undone by that: restore the backup from
step 1 if needed.

Python packages: the versions are pinned in `docker/constraints.txt`; change a version there and
rebuild. The engines' own `pyproject.toml` files decide which packages are installed.

PostgreSQL within 18 (18.x): `docker compose pull postgres backup && docker compose up -d`. To a
new major version: take a dump, point both `postgres:18` lines in compose.yaml at the new version,
remove the `pgdata` volume (after the dump is safe) and restore.

## Everyday commands

```bash
docker compose ps                         # what runs
docker compose logs -f --tail 100 lbsim   # one service's log (json-file, 5 x 10 MB kept)
docker compose restart honi               # restart one engine
docker compose stop && docker compose up -d
docker compose up -d --scale lbsim-worker=5    # more plan workers for a while (or LBSIM_WORKERS)
docker compose -f compose.yaml -f compose.debug.yaml up -d   # publish ports on 127.0.0.1 for debugging
docker compose exec postgres psql -U myuser -d simtech       # a SQL prompt as administrator
```

**Changing a password.** The provisioning sets a role's password only when it creates the role.
To change one later: `docker compose exec postgres psql -U myuser -d postgres -c "ALTER ROLE honi
PASSWORD 'new-value'"`, put the same value in `.env` (`SIMTECH_HONI_PASSWORD`), then
`docker compose up -d honi`. For the curator: role `curator`, variable `SIMTECH_CURATOR_PASSWORD`,
service `cockpit`.

## The cockpit in Docker

On the owner's machine the cockpit's desktop app starts every engine (`autostart: true` and a
`start` command for each engine in `cockpit/config.yaml`); `python -m cockpit serve` does not
autostart, but its System page can still start an engine through `POST /api/launcher/{key}/start`.
There is no environment switch for that. In Docker it must only show status, so without changing
the cockpit:

- the container runs `python -m cockpit serve`, never `desktop` or `start-engines`;
- at image build, `docker/cockpit_docker_config.py` writes the cockpit's `config.local.yaml` from
  its own `config.yaml`: each engine's address becomes `http://<key>:<port>`, and every `start`,
  `python` and `autostart` entry is removed. The cockpit then has nothing it may start (tested:
  none of the 13 is startable, and the start route answers 409);
- the curator's database host becomes `postgres`; its password comes from
  `SIMTECH_CURATOR_PASSWORD`.

Known limit: the System page links each engine's own address, which is an internal name in
Docker; those links do not open from a browser (the test benches and the proxy work).
ENGINE_CHANGES.md items 2 to 5 describe the cockpit changes that would make the overlay
unnecessary.

`COCKPIT_MODE` in `.env`: `development` (today's behaviour on the owner's machine: everything,
including the test benches and every write through the proxy) or `cio` (the CIO workspace and
system status only). Which one the team server should use is the owner's decision.

## How configuration reaches the engines

Every engine reads `config.yaml < config.local.yaml < environment`. The images contain the
committed `config.yaml` files and never a developer's `config.local.yaml`, `.env` or
`config.toml`. compose.yaml sets, per engine:

- `<PREFIX>_HOST=0.0.0.0` (the prefix is the engine name in capitals; the app uses
  `EIGENTLICH_APP_HOST`), so it listens on the container network;
- `<PREFIX>_DB_HOST=postgres`, `<PREFIX>_DB_PORT=5432`, `<PREFIX>_DB_PASSWORD` from
  `SIMTECH_<ENGINE>_PASSWORD`; database, schema and user stay as in config.yaml (`simtech`, the
  engine's schema, the engine's role). fmre uses `INSTRUMENTS_DB_*` and `INSTRUMENTS_DB_USER=fmre`;
- the upstream addresses where the engine reads them from the environment (`HONI_DATAFEED_URL`,
  `AGGREGATION_MRS_URL`, `PCP_FMRE_URL`, `REPORT_LBSIM_URL`, `EIGENTLICH_LBS_URL`,
  `INSTRUMENTS_AGGREGATION_URL`, ...). lbsim does not yet; its addresses come from
  `config/lbsim.docker.yaml`, baked into the image as its `config.local.yaml`;
- report and chatbot: `SPARK7_CLIENT_ID` and `SPARK7_CLIENT_SECRET` (the Cloudflare Access
  service token of the model server). Locally they read these from `eigentliCH_Engines/.env`; the
  environment takes precedence, and that file is never in an image.

The lbsim API runs as `python -m lbsim serve --workers 0` (no workers in the API container); the
plan workers run as `python -m lbsim worker`, one per `lbsim-worker` container, each limited by
`LBSIM_WORKER_CPUS` and `LBSIM_WORKER_MEMORY`, with the maths libraries held to one thread.

## What is not in the repository

The builds need nothing outside the `Engines` folder. The images leave out, on purpose: every
`.venv`, `.env`, `config.local.yaml` and `config.toml`, `tests/`, `golden/`, `dev/`, caches,
`*.cmd`, `macrofield/data/archive` and the cockpit's `data/`. So the engines' test suites do not
run inside the images; run them on a development machine.

Some one-off loading commands read files that are not in the repository. None is needed after a
restore from the owner's dump:

| Command | Needs | Where it is on the owner's machine |
|---|---|---|
| `python -m datafeed bootstrap` | the MATLAB export `M_TS.mat` and the ticker workbooks (`DATAFEED_MATLAB_DIR`) | `SIM_NAS/SIM_Tech/Master_Controller` |
| `python -m store.etl.bootstrap` (fmre) | the feed CSV and the ECN folder (`INSTRUMENTS_FEED_CSV`, `INSTRUMENTS_ECN_DIR`) | outside `Engines` |
| `python -m eigentlich seed` / `migrate` | the questionnaire prototype and its SQLite file (`EIGENTLICH_PROTOTYPE_ROOT`, `EIGENTLICH_MIGRATE_FROM`) | `Projects/eigentliCH/Prototype` |

## Files in this folder

| File | What it is |
|---|---|
| `compose.yaml` | every service, its command, environment, health check and start order |
| `compose.debug.yaml` | optional: publishes all ports on 127.0.0.1 for debugging |
| `.env.example` | every setting and secret, with placeholders; copy to `.env` |
| `docker/<family>.Dockerfile` | the five images: macro, instruments, optimizer, eigentlich, cockpit |
| `docker/<family>.Dockerfile.dockerignore` | each image's allowlist of what enters the build |
| `docker/constraints.txt` | pinned package versions (from the owner's working environments) |
| `docker/deps.py` | reads the engines' dependencies from their `pyproject.toml` |
| `docker/healthcheck.py` | the containers' health check (standard library only) |
| `docker/cockpit_docker_config.py` | writes the cockpit's status-only overlay at build |
| `config/lbsim.docker.yaml` | lbsim's upstream addresses for Docker |
| `scripts/health.sh` | health of the whole deployment |
| `scripts/restore.sh` | restore a dump, in the right order (runs on the host) |
| `scripts/restore-db.sh` | the pg_restore step (runs in the backup container) |
| `scripts/backup.sh` | the nightly and on-demand backup (runs in the backup container) |
| `scripts/init-empty.sh` | tables for fmre and the app on an empty database |
| `ENGINE_CHANGES.md` | changes to engines that would remove the workarounds here |
