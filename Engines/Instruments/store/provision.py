"""Provision the shared ``simtech`` database: one schema per engine, one role per engine.

**The decision this implements.** The server used to carry one database per repository,
which was never decided: two repositories were built weeks apart and each picked a name.
The cost showed up as two different schemas both called ``datafeed``, four table names
shared with incompatible definitions, and a catalogue that has to open two connections and
join in Python. One database with a schema per engine keeps the boundary and gets the
cross-engine query back.

**The boundary is grants, not geography.** A separate database inside one PostgreSQL
instance stops accidents but not intent, and it stopped neither when every schema was owned
by one superuser. So each engine gets a login role that owns its own schemas, may create
schemas of its own, and holds ``SELECT`` and nothing more on the shared feed. An engine
that tries to write outside its own schema is refused by the server rather than by a
convention somebody has to remember.

Everything here is idempotent: ``CREATE ... IF NOT EXISTS``, ``DO`` blocks that check
``pg_roles`` first, and grants that can be reapplied. Run it as often as you like.

    python -m store.provision                 # create or repair the layout
    python -m store.provision --show          # print what exists, change nothing

Passwords come from ``SIMTECH_<ENGINE>_PASSWORD``. Without one the role is created with the
development password and the script says so loudly, because a shared password across ten
roles is a development convenience and nothing else.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from store.config import DatabaseConfig, load

#: The one database. Named for the system, not for a repository, because which repository
#: an engine happens to live in is not a property of its data.
DATABASE = "simtech"

#: The shared feed. Engine 01 owns it; every other engine reads it and writes nothing.
FEED_SCHEMA = "datafeed"

#: The development password, used only when no per-engine variable is set.
DEV_PASSWORD = "mysecretpassword"

#: The one account that reads across engines. The catalogue has to see the whole server,
#: which is exactly what an engine role must not do, so it gets its own read-only login
#: rather than borrowing the superuser. It never writes anything, anywhere.
CATALOGUE_ROLE = "catalogue"

#: Databases the catalogue reads. One, since the Macro repository's schemas moved into
#: `simtech` on 27 September 2026 and `simtech_macro` was dropped. Kept as a tuple because
#: the catalogue's job is to cover the whole server, and a second database may reappear.
CATALOGUED = (DATABASE,)


@dataclass(frozen=True)
class Engine:
    """One engine's place in the store.

    ``schemas`` is usually one. Fund Map has two because it still keeps a private copy of
    the series it reads; that copy is interim and named so that nobody mistakes it for the
    shared feed. It goes away when Fund Map reads Engine 01's ``Panel`` instead.
    """

    name: str
    port: int
    schemas: tuple[str, ...]
    built: bool
    note: str = ""


#: The roster from the Engine Building Guide, section 4. Unbuilt engines are listed so the
#: name is reserved and the convention is visible, but nothing is created for them: an
#: empty schema is a promise, and promises do not belong in a data dictionary.
ROSTER: tuple[Engine, ...] = (
    Engine("datafeed", 8001, ("datafeed",), built=True,
           note="Owns all source data. Every other engine reads it."),
    Engine("honi", 8002, ("honi",), built=True),
    Engine("macrofield", 8003, ("macrofield",), built=True,
           note="Formerly threebody; renamed 27 September 2026."),
    Engine("aggregation", 8004, ("aggregation",), built=True,
           note="Aggregation layer (formerly listed as taa): combines mrs, cycle and macrofield "
                "into the Regime and issues the regime_id."),
    Engine("mrs", 8005, ("mrs",), built=True,
           note="Parked mid-rebuild; `python -m mrs init-db` recreates its tables."),
    Engine("fmre", 8006, ("fmre", "fmre_feed"), built=True,
           note="fmre_feed is an interim private copy of the series Fund Map reads, "
                "kept until it reads Engine 01's Panel. Not the shared feed."),
    Engine("pcp", 8007, ("pcp",), built=True,
           note="Portfolio Creation Program, Optimizer/engines/pcp; built 28.09.2026."),
    Engine("cycle", 8012, ("cycle",), built=True,
           note="Cycle model; role created by hand on 27 September 2026, registered here since."),
    Engine("lbs", 8013, ("lbs",), built=True,
           note="Life Balance Sheet, eigentliCH_Engines/engines/lbs; built 28.09.2026."),
    Engine("lbsim", 8014, ("lbsim",), built=False),
    Engine("report", 8015, ("report",), built=True,
           note="eigentliCH Report Engine, drafts on spark7; eigentliCH_Engines/engines/report."),
    Engine("chatbot", 8016, ("chatbot",), built=True,
           note="eigentliCH ChatBot, answers on spark7; eigentliCH_Engines/engines/chatbot."),
    Engine("eigentlich", 8017, ("eigentlich",), built=True,
           note="The consumer side's store: client records, answers, questionnaire content, "
                "threads, requests and approvals. Personal data; no engine reads it. "
                "eigentliCH_Engines/eigentlich; Build Instruction section 9."),
)

#: Engines whose store this script creates. Every built engine is now listed: the Macro
#: repository's three schemas were migrated into `simtech` on 27 September 2026 on the
#: owner's instruction, so their roles and grants are provisioned from here too.
#:
#: This is a deliberate exception to "each repository provisions its own". One script has
#: to create the shared `datafeed` schema and the grants that let every other engine read
#: it, and splitting that across repositories would mean no single place says what the
#: layout is. The Macro repository still owns its *code*; this owns the layout.
OWNED_HERE = ("fmre", "datafeed", "honi", "macrofield", "mrs", "aggregation", "cycle", "pcp",
              "lbs", "report", "chatbot", "eigentlich")

#: The cockpit's login for the curator workflow (Build Instruction section 9.1, owner
#: 28.09.2026). A stated exception to "a role writes only its own schema": it owns nothing,
#: and reads and writes the consumer schema `eigentlich` and nothing else. The grant covers
#: tables `eigentlich` creates later through default privileges.
CURATOR_ROLE = "curator"
CURATOR_SCHEMA = "eigentlich"


def _password(engine: str) -> tuple[str, bool]:
    """The role's password, and whether it came from the environment."""
    value = os.environ.get(f"SIMTECH_{engine.upper()}_PASSWORD")
    return (value, True) if value else (DEV_PASSWORD, False)


#: Provisioning creates roles and schemas, which an engine role deliberately cannot do.
#: It therefore connects as an administrator, taken from the environment so that the
#: engine's own credentials in config never carry that power.
ADMIN_USER_VAR = "SIMTECH_ADMIN_USER"
ADMIN_PASSWORD_VAR = "SIMTECH_ADMIN_PASSWORD"
DEFAULT_ADMIN = "myuser"


def admin(config: DatabaseConfig) -> DatabaseConfig:
    """The same server, as an account that may create roles and schemas."""
    from dataclasses import replace

    return replace(
        config,
        user=os.environ.get(ADMIN_USER_VAR, DEFAULT_ADMIN),
        password=os.environ.get(ADMIN_PASSWORD_VAR, DEV_PASSWORD),
    )


def _connect(config: DatabaseConfig, dbname: str) -> psycopg.Connection:
    conn = psycopg.connect(config.conninfo(dbname=dbname), row_factory=dict_row)
    conn.autocommit = True
    return conn


def create_database(config: DatabaseConfig) -> bool:
    """Create ``simtech`` if it is not there. Returns True if it was created."""
    with _connect(config, config.maintenance_dbname) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DATABASE,)
        ).fetchone()
        if exists:
            return False
        conn.execute(f"CREATE DATABASE {DATABASE}")
        return True


def _ensure_role(conn: psycopg.Connection, engine: str) -> tuple[bool, bool]:
    """Create the engine's login role if absent. Returns (created, password_from_env)."""
    password, from_env = _password(engine)
    existing = conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname = %s", (engine,)
    ).fetchone()
    if existing:
        return False, from_env
    # CREATE ROLE is a utility statement and takes no bind parameters, so the password
    # has to be composed in. `sql.Literal` quotes and escapes it; an f-string would not.
    conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
        sql.Identifier(engine), sql.Literal(password)))
    return True, from_env


def provision(config: DatabaseConfig, *, apply: bool = True) -> dict:
    """Create the database, the roles, the schemas and the grants. Idempotent."""
    report: dict = {"database_created": False, "roles": [], "schemas": [],
                    "insecure_passwords": []}

    if apply:
        report["database_created"] = create_database(config)

    with _connect(config, DATABASE if apply else config.maintenance_dbname) as conn:
        if not apply:
            return report

        # Nothing lives in public, and nothing may be created there. Every table has an
        # owner, and an unowned table in a shared database is how projects collide.
        conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        conn.execute(f"REVOKE ALL ON DATABASE {DATABASE} FROM PUBLIC")

        for engine in ROSTER:
            if not engine.built or engine.name not in OWNED_HERE:
                continue
            created, from_env = _ensure_role(conn, engine.name)
            if created:
                report["roles"].append(engine.name)
            if not from_env:
                report["insecure_passwords"].append(engine.name)

            # An engine may create schemas (its tests need throwaway ones) but it owns
            # only its own. CREATE on the database does not grant anything inside a
            # schema somebody else owns.
            conn.execute(f"GRANT CONNECT, CREATE ON DATABASE {DATABASE} TO {engine.name}")

            for schema in engine.schemas:
                conn.execute(
                    f"CREATE SCHEMA IF NOT EXISTS {schema} AUTHORIZATION {engine.name}")
                conn.execute(f"ALTER SCHEMA {schema} OWNER TO {engine.name}")
                report["schemas"].append(schema)

        created, from_env = _ensure_role(conn, CURATOR_ROLE)
        if created:
            report["roles"].append(CURATOR_ROLE)
        if not from_env:
            report["insecure_passwords"].append(CURATOR_ROLE)
        conn.execute(f"GRANT CONNECT ON DATABASE {DATABASE} TO {CURATOR_ROLE}")
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s",
                        (CURATOR_SCHEMA,)).fetchone():
            conn.execute(f"GRANT USAGE ON SCHEMA {CURATOR_SCHEMA} TO {CURATOR_ROLE}")
            conn.execute(f"GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "
                         f"{CURATOR_SCHEMA} TO {CURATOR_ROLE}")
            conn.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "
                         f"{CURATOR_SCHEMA} TO {CURATOR_ROLE}")
            conn.execute(f"ALTER DEFAULT PRIVILEGES FOR ROLE {CURATOR_SCHEMA} IN SCHEMA "
                         f"{CURATOR_SCHEMA} GRANT SELECT, INSERT, UPDATE ON TABLES "
                         f"TO {CURATOR_ROLE}")
            conn.execute(f"ALTER DEFAULT PRIVILEGES FOR ROLE {CURATOR_SCHEMA} IN SCHEMA "
                         f"{CURATOR_SCHEMA} GRANT USAGE, SELECT ON SEQUENCES "
                         f"TO {CURATOR_ROLE}")

        created, from_env = _ensure_role(conn, CATALOGUE_ROLE)
        if created:
            report["roles"].append(CATALOGUE_ROLE)
        if not from_env:
            report["insecure_passwords"].append(CATALOGUE_ROLE)

        # Read access to the shared feed, for every engine role that exists. Written as a
        # loop over roles actually present so it can be reapplied after Engine 01 arrives.
        feed_there = conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s", (FEED_SCHEMA,)
        ).fetchone()
        if feed_there:
            for engine in ROSTER:
                present = conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname = %s", (engine.name,)
                ).fetchone()
                if not present or engine.name == "datafeed":
                    continue
                conn.execute(f"GRANT USAGE ON SCHEMA {FEED_SCHEMA} TO {engine.name}")
                conn.execute(
                    f"GRANT SELECT ON ALL TABLES IN SCHEMA {FEED_SCHEMA} TO {engine.name}")
                conn.execute(
                    f"ALTER DEFAULT PRIVILEGES IN SCHEMA {FEED_SCHEMA} "
                    f"GRANT SELECT ON TABLES TO {engine.name}")
    return report


def grant_catalogue_read(config: DatabaseConfig, dbname: str) -> list[str]:
    """Give the catalogue role read access to every schema of one database.

    Read only, and re-runnable. `information_schema` hides what a role cannot see, so a
    missing grant here does not raise, it silently shrinks the catalogue: the export
    checks for that and refuses rather than publishing a short list.
    """
    granted = []
    with _connect(config, dbname) as conn:
        conn.execute(f"GRANT CONNECT ON DATABASE {dbname} TO {CATALOGUE_ROLE}")
        rows = conn.execute(
            "SELECT nspname FROM pg_namespace "
            r"WHERE nspname NOT LIKE 'pg\_%' AND nspname NOT IN "
            "      ('information_schema', 'public')"
        ).fetchall()
        for row in rows:
            schema = row["nspname"]
            conn.execute(f"GRANT USAGE ON SCHEMA {schema} TO {CATALOGUE_ROLE}")
            conn.execute(
                f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {CATALOGUE_ROLE}")

            # Default privileges apply only to objects created by the role that set
            # them, so setting them as the admin covers nothing an engine creates.
            # Without the FOR ROLE clause a table the engine adds later is invisible to
            # the catalogue, and `information_schema` hides it rather than refusing --
            # the export then silently reports a shorter list. Set it for the admin and
            # for every role that owns a schema here.
            owners = {r["owner"] for r in conn.execute(
                "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace "
                "WHERE nspname = %s", (schema,)).fetchall()}
            owners.add(os.environ.get(ADMIN_USER_VAR, DEFAULT_ADMIN))
            for owner in owners:
                conn.execute(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {schema} "
                    f"GRANT SELECT ON TABLES TO {CATALOGUE_ROLE}")
            granted.append(f"{dbname}.{schema}")
    return granted


def adopt(config: DatabaseConfig, schema: str, owner: str) -> int:
    """Hand every object in a schema to the engine that owns it.

    Needed after a restore, which recreates tables under whoever ran it. A table owned by
    the superuser in a schema owned by an engine is the half-state this whole exercise is
    meant to remove.
    """
    moved = 0
    with _connect(config, DATABASE) as conn:
        conn.execute(f"ALTER SCHEMA {schema} OWNER TO {owner}")

        rows = conn.execute(
            "SELECT c.relname, c.relkind FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'm', 'S')",
            (schema,),
        ).fetchall()
        for row in rows:
            what = {"r": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW",
                    "S": "SEQUENCE"}[row["relkind"]]
            conn.execute(f'ALTER {what} {schema}."{row["relname"]}" OWNER TO {owner}')
            moved += 1

        # **Functions too, and this was missed the first time.** Sweeping `pg_class`
        # alone leaves functions owned by whoever ran the restore. The engines here
        # define a `refuse_change()` trigger and re-run their schema on every start, so
        # a superuser-owned function made `CREATE OR REPLACE FUNCTION` fail with
        # "must be owner of function" on a real start -- while the suites stayed green,
        # because their fixtures build throwaway schemas the role owns outright.
        # A partial ownership sweep is the same shape of bug as a partial drop.
        rows = conn.execute(
            "SELECT p.oid::regprocedure AS signature FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = %s",
            (schema,),
        ).fetchall()
        for row in rows:
            conn.execute(f'ALTER FUNCTION {row["signature"]} OWNER TO {owner}')
            moved += 1
    return moved


def unowned(config: DatabaseConfig) -> list[tuple[str, str, str, str]]:
    """Every object in an engine schema that the engine role does not own.

    The check that would have caught the function above. Covers relations, functions and
    user-defined types rather than the one catalogue that happened to come to mind.
    """
    out = []
    with _connect(config, DATABASE) as conn:
        schemas = [s for e in ROSTER if e.built and e.name in OWNED_HERE
                   for s in e.schemas]
        for schema in schemas:
            owner = next(e.name for e in ROSTER if schema in e.schemas)
            for kind, sql_text in (
                ("relation",
                 "SELECT c.relname AS name, pg_get_userbyid(c.relowner) AS owner "
                 "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                 "WHERE n.nspname = %s AND c.relkind IN ('r','v','m','S')"),
                ("function",
                 "SELECT p.proname AS name, pg_get_userbyid(p.proowner) AS owner "
                 "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                 "WHERE n.nspname = %s"),
                ("type",
                 "SELECT t.typname AS name, pg_get_userbyid(t.typowner) AS owner "
                 "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                 "WHERE n.nspname = %s AND t.typtype <> 'b'"),
            ):
                for row in conn.execute(sql_text, (schema,)).fetchall():
                    if row["owner"] != owner:
                        out.append((schema, kind, row["name"], row["owner"]))
    return out


def describe(config: DatabaseConfig) -> list[dict]:
    """What is actually there, for `--show` and for the acceptance test."""
    with _connect(config, config.maintenance_dbname) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                            (DATABASE,)).fetchone():
            return []
    with _connect(config, DATABASE) as conn:
        return conn.execute(
            "SELECT n.nspname AS schema, pg_get_userbyid(n.nspowner) AS owner, "
            "  (SELECT count(*) FROM pg_class c WHERE c.relnamespace = n.oid "
            "     AND c.relkind = 'r') AS tables "
            "FROM pg_namespace n "
            "WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' "
            "ORDER BY n.nspname"
        ).fetchall()


def main(argv: list[str]) -> int:
    config = admin(load())
    if "--show" in argv:
        rows = describe(config)
        if not rows:
            print(f"database {DATABASE} does not exist")
            return 0
        print(f"{DATABASE}:")
        for row in rows:
            print(f"  {row['schema']:<14} owner {row['owner']:<12} "
                  f"{row['tables']:>3} tables")
        return 0

    report = provision(config)
    for dbname in CATALOGUED:
        try:
            granted = grant_catalogue_read(config, dbname)
            print(f"catalogue can read {len(granted)} schemas in {dbname}")
        except Exception as exc:  # noqa: BLE001
            print(f"could not grant catalogue read on {dbname}: {exc}", file=sys.stderr)
    if report["database_created"]:
        print(f"created database {DATABASE}")
    for role in report["roles"]:
        print(f"created role {role}")
    for schema in report["schemas"]:
        print(f"schema {schema} ready")
    for role in report["insecure_passwords"]:
        print(f"WARNING: role {role} uses the development password. "
              f"Set SIMTECH_{role.upper()}_PASSWORD for anything else.", file=sys.stderr)
    print()
    for row in describe(config):
        print(f"  {row['schema']:<14} owner {row['owner']:<12} {row['tables']:>3} tables")

    stray = unowned(config)
    if stray:
        print(file=sys.stderr)
        for schema, kind, name, owner in stray:
            print(f"WARNING: {schema}.{name} ({kind}) is owned by {owner}, not "
                  f"the engine role. Run adopt().", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
