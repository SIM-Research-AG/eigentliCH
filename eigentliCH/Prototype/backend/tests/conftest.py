from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from eigentlich.db import create_all, make_engine, make_session_factory  # noqa: E402
from eigentlich.services import grounding  # noqa: E402
from eigentlich.services import register_member  # noqa: E402


@pytest.fixture(autouse=True)
def _no_corpus(tmp_path_factory, monkeypatch):
    """Every test starts with no book index and no authored content, unless it plants its own.

    A34's note about the model applies unchanged to the corpus: **the suite does not depend on Ollama, and
    it must not depend on this developer's machine either.** The index lives in the estate and exists here;
    it will not exist on a CI runner or in a friend's distribution ZIP, and a suite that is green only where
    the corpus happens to sit is a suite that proves nothing about the code a friend runs. Worse, leaving it
    in would put a real 1 024-dimension embedding call in front of every `ask()` in the suite.

    So the default is absent, which is the case that has to degrade cleanly anyway. `tests/test_grounding.py`
    points these back at a planted index, or at the real one behind an explicit availability check.
    """
    empty = tmp_path_factory.mktemp("no-corpus")
    monkeypatch.setenv("ANDERSCH_BOOKINDEX_DIR", str(empty / "bookindex"))
    monkeypatch.setenv("ANDERSCH_KNOWLEDGE_DIR", str(empty / "knowledge"))
    grounding.reset_caches()
    yield
    grounding.reset_caches()


@pytest.fixture()
def engine():
    """In-memory SQLite, one per test, with the append-only triggers installed.

    A shared cache URI rather than plain `:memory:` so the triggers and the session see one database.
    """
    engine = make_engine("sqlite:///:memory:")
    create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine) -> Session:
    factory = make_session_factory(engine)
    with factory() as session:
        yield session


@pytest.fixture()
def member(session):
    m = register_member(session, age_at_registration=41, display_name="Test Member")
    session.commit()
    return m


# ============================================================ the HTTP surface (A11)
#
# One fixture for every test that talks to the application over HTTP. It exists because A11 was wired on
# 31 August 2026 and standing a router up on its own app is no longer enough: a route resolves its member
# through `api.auth.get_session`, and a test that overrides only its own router's session dependency
# authenticates against the developer's real `backend/eigentlich.db` while the routes read the fixture.
# That is the A68 failure mode — a test that silently uses the wrong database — so the override list lives
# here, once, and is derived from the modules rather than typed out per test file.

#: Every module that defines a `get_session` FastAPI dependency. `api.auth` is not optional in this list:
#: it is the one the token is resolved through, whichever router is under test.
#:
#: **`api.erasure` is deliberately absent, and adding it would break the assertion below.** That module
#: imports `get_session` from `api.auth` instead of defining its own, so the two names are one object and
#: overriding `api.auth.get_session` already covers it — see `api/erasure.py`'s docstring. It is the one
#: router where forgetting a line in this list would not give a test that reads the wrong database but one
#: that erases it, so it was written not to need the line.
_SESSION_DEPENDENCY_MODULES = (
    "eigentlich.api.main",
    "eigentlich.api.auth",
    "eigentlich.api.befund",
    "eigentlich.api.curator",
    "eigentlich.api.curators",
    "eigentlich.api.decisions",
    "eigentlich.api.learning",
    "eigentlich.api.marketplace",
    # Not wired into `main.py` yet, and in this list anyway: what it is a list of is "every module that
    # defines a `get_session` dependency", and a test standing this router up on its own app needs the
    # override whether or not the application serves it. Leaving it out is the A68 failure mode — a test
    # that quietly reads the developer's real `backend/eigentlich.db`.
    "eigentlich.api.positions",
    "eigentlich.api.remainder",
    "eigentlich.api.runs",
)


def session_overrides(db_session):
    """`{dependency: provider}` for every `get_session` in the api package, all yielding `db_session`.

    Returned as a mapping rather than applied, so a caller can `app.dependency_overrides.update(...)` on
    an app it built itself.
    """
    import importlib

    overrides = {}
    for name in _SESSION_DEPENDENCY_MODULES:
        module = importlib.import_module(name)
        overrides[module.get_session] = lambda: db_session
    assert len(overrides) == len(_SESSION_DEPENDENCY_MODULES), (
        "two api modules share one get_session object; the override list has stopped being a list"
    )
    return overrides


@pytest.fixture()
def api_engine():
    """An engine an HTTP test can share with the request thread.

    `TestClient` serves on a worker thread and SQLAlchemy gives in-memory SQLite one connection per
    thread, so a plain `:memory:` would hand the request an empty schema. `StaticPool` pins the single
    connection that holds it.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def api_session(api_engine):
    factory = make_session_factory(api_engine)
    with factory() as db_session:
        yield db_session


@pytest.fixture()
def fast_kdf(monkeypatch):
    """600,000 PBKDF2 iterations is the right number in production and the wrong one in a test suite that
    creates a dozen credentials. Lowered here only, on the model's own constant, so the code under test is
    the code that ships."""
    monkeypatch.setattr("eigentlich.models.auth.PBKDF2_ITERATIONS", 1000)
