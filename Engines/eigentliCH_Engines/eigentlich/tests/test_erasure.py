"""Erasure (R-231): the one path that deletes, bounded to one client and to the owning role."""

from __future__ import annotations

import psycopg
import pytest

from eigentlich import store
from eigentlich.store import TABLES

from . import world


def _references(conn, client_id: str) -> dict[str, int]:
    """Rows in any table with any column holding the client's id."""
    out = {}
    for t in TABLES:
        n = conn.execute(f"SELECT count(*) AS n FROM {t} x WHERE to_jsonb(x)::text LIKE %s",
                         (f'%"{client_id}"%',)).fetchone()["n"]
        if n:
            out[t] = n
    return out


def test_erasure_removes_the_client_everywhere(st):
    w = world.build(st, tag="erase")
    with st.session() as conn:
        assert _references(conn, w["client"])
        removed = store.erase_client(conn, w["client"])
    with st.session() as conn:
        assert _references(conn, w["client"]) == {}
        # The curator's audit stays, without the client.
        s = conn.execute("SELECT client_id FROM curator_session WHERE id = %s", (w["session"],)).fetchone()
        assert s == {"client_id": None}
        assert conn.execute("SELECT count(*) AS n FROM curator_session_event WHERE id = %s",
                            (w["session_event"],)).fetchone()["n"] == 1
        # The shared household stays with the partner, the client's row redacted, C-09 intact.
        members = conn.execute("SELECT client_id, label, decision_id FROM household_member WHERE household_id = %s "
                               "ORDER BY label", (w["household"],)).fetchall()
        assert [(m["client_id"], m["label"]) for m in members] == [(None, store.REDACTED), (w["partner"], "Partner")]
        d = conn.execute("SELECT client_id, author FROM decision WHERE id = %s", (members[0]["decision_id"],)).fetchone()
        assert d == {"client_id": w["partner"], "author": "system"}
    assert removed["client"] == 1 and removed["decision"] == 1 and removed["position"] == 1


def test_a_client_in_no_shared_household_leaves_no_household(st):
    w = world.build(st, tag="erase2")
    with st.session() as conn:
        store.erase_client(conn, w["partner"])      # the partner leaves first: the household stays with the client
        store.erase_client(conn, w["client"])
    with st.session() as conn:
        assert conn.execute("SELECT count(*) AS n FROM household WHERE id = %s", (w["household"],)).fetchone()["n"] == 0


def test_the_erasure_setting_covers_only_the_named_client(st):
    a = world.build(st, tag="erase3a")
    b = world.build(st, tag="erase3b")
    with pytest.raises(psycopg.errors.RaiseException, match="never deleted"):
        with st.session() as conn:
            conn.execute("SELECT set_config('eigentlich.erasure_client', %s, true)", (a["client"],))
            conn.execute("DELETE FROM consent WHERE id = %s", (b["consent"],))


def test_without_the_setting_nothing_is_deleted(st):
    w = world.build(st, tag="erase4")
    with pytest.raises(psycopg.errors.RaiseException):
        with st.session() as conn:
            conn.execute("DELETE FROM answer WHERE client_id = %s", (w["client"],))
    with st.session() as conn:
        assert conn.execute("SELECT count(*) AS n FROM answer WHERE client_id = %s", (w["client"],)).fetchone()["n"] == 1


def test_the_setting_does_not_outlive_the_erasure(st):
    w = world.build(st, tag="erase5")
    with st.session() as conn:
        store.erase_client(conn, w["partner"])
        with pytest.raises(psycopg.errors.RaiseException):
            with conn.transaction():
                conn.execute("DELETE FROM consent WHERE id = %s", (w["consent"],))
