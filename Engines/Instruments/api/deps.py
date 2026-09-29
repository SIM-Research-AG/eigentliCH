"""Shared FastAPI dependencies.

Split out of ``main`` so the data-tester router can use the same connection handling
without importing the module that includes it.
"""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, HTTPException

from engines.fund_map import service
from store import db


def get_conn() -> Iterator[db.Connection]:
    """One connection per request, committed on success and always closed.

    Note what this does *not* do: it takes no lock and changes no server-side setting
    beyond ``SET search_path``. An earlier version set a pragma here and the result was a
    500 the first time a browser issued two requests at once.
    """
    conn = db.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def require_calibration(conn: db.Connection = Depends(get_conn)) -> str:
    calibration_id = service.latest_calibration_id(conn)
    if calibration_id is None:
        raise HTTPException(
            status_code=503,
            detail="no calibration in the store. Run: python -m store.etl.bootstrap",
        )
    return calibration_id
