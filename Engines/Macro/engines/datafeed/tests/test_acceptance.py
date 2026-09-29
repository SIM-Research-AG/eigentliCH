"""Model quality, numbered as the datafeed engine page (section 5) states it.

1. The frozen snapshot is the golden reference; its checksum must match the manifest.
2. Panel alignment never invents a value.
3. Every carried cell is flagged.
4. Snapshots cannot be overwritten.
5. ``/coverage`` is the gate downstream engines call before running.
"""

from __future__ import annotations

import psycopg
import pytest

from datafeed.contracts import Panel, PanelRequest
from datafeed.engine import cell_sources, checksum
from datafeed.etl.bootstrap import FROZEN_RAW, read_frozen
from datafeed.store import get_cells

from .conftest import RAW_ID


def test_1_the_frozen_snapshot_matches_its_manifest(frozen_manifest):
    panel = Panel.model_validate_json((FROZEN_RAW / "panel.json").read_text(encoding="utf-8"))
    assert checksum(panel) == frozen_manifest["checksum"]


def test_1_the_store_serves_the_frozen_snapshot_exactly(service, frozen_manifest):
    assert checksum(service.panel(PanelRequest(snapshot_id=RAW_ID))) == frozen_manifest["checksum"]


def test_2_alignment_never_invents_a_value(service, filled_id):
    panel = service.panel(PanelRequest(snapshot_id=filled_id))
    with service.store.session() as conn:
        stored = {(c, s, d): (v, f, src) for c, s, d, v, f, src in get_cells(conn, filled_id)}
    present = 0
    for s in panel.series:
        for d, v, f, src in zip(panel.dates, s.values, s.flags, cell_sources(panel, s)):
            key = (s.country, s.series_id, d)
            if v is None:
                assert key not in stored
            else:
                assert stored[key] == (v, f, src)
                present += 1
    assert present == len(stored)


def test_3_every_carried_cell_is_flagged_and_sourced(service, filled_id):
    panel = service.panel(PanelRequest(snapshot_id=filled_id))
    carried = 0
    for s in panel.series:
        for f, src in zip(s.flags, cell_sources(panel, s)):
            if f == "carried":
                carried += 1
                assert src != panel.primary_source, "only fills are carried by datafeed"
    assert carried > 0


def test_4_a_snapshot_cannot_be_overwritten(service):
    raw = read_frozen(FROZEN_RAW)
    altered = raw.model_copy(update={"note": raw.note, "series": raw.series[1:]})
    from datafeed.service import Conflict
    with pytest.raises(Conflict, match="immutable"):
        service.ingest(altered)
    assert service.ingest(raw)[1] is False, "the identical snapshot again is a no-op"


@pytest.mark.parametrize("sql", ["UPDATE observation SET value = 0", "DELETE FROM snapshot",
                                 "UPDATE snapshot SET checksum = 'x'"])
def test_4_the_database_refuses_edits(service, sql):
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        with service.store.session() as conn:
            conn.execute(sql)


def test_5_coverage_reports_gaps_fills_and_implausible_units(service, filled_id):
    raw = service.coverage(RAW_ID)
    assert {"BR", "DE", "EU", "GB", "IN", "TH"} == {p.country for p in raw.plausibility}
    report = service.coverage(filled_id)
    assert len(report.rows) == 16 * 44
    assert sum(r.from_public_sources for r in report.rows) > 0
    assert report.plausibility == (), "the DF-16 replacements clear every unit finding"
