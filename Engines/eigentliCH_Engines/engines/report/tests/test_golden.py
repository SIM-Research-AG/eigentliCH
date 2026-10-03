"""Golden layer: frozen reports over frozen artefacts, reproduced exactly; and the report's promise tested on
them: every figure traces to an artefact id, and the page prints no figure that is not a fact.

The prose case replays spark7's real replies, frozen once from the live server (``dev/build_golden.py --live``),
through the stand-in; the engine must reach the same checked report from them.
"""

from __future__ import annotations

import html as htmllib
import json
import re

import httpx
import pytest

from report import engine

from . import golden_cases as gc
from .conftest import drop, settings_for
from .standin import Reply

CASES = gc.cases()
NAMES = [c["name"] for c in CASES]


def _transports() -> dict[str, httpx.BaseTransport]:
    files = gc.upstream_files()

    def make(name: str) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            f = files[name].get(request.url.path)
            return httpx.Response(200, content=(gc.INPUTS / f).read_bytes()) if f else httpx.Response(404)
        return httpx.MockTransport(handler)

    return {"pcp": make("pcp"), "lbs": make("lbs"), "lbsim": make("lbsim")}


@pytest.fixture(scope="module")
def produced(standin):
    """Every case run once, in order, on a fresh store: the reports this build produces."""
    from fastapi.testclient import TestClient

    from report.api import create_app
    from report.settings import load

    settings = settings_for(standin.url)
    from dataclasses import replace
    settings = replace(settings, model=replace(settings.model, model=load().model.model))
    out: dict[str, dict] = {}
    try:
        with TestClient(create_app(settings, _transports())) as client:
            for case in CASES:
                body = dict(case["request"])
                if case.get("previous"):
                    body["previous_report_id"] = out[case["previous"]]["artefact_id"]
                if case.get("revision_of"):
                    body["revision_of"] = out[case["revision_of"]]["artefact_id"]
                standin.reset()
                if case.get("live"):
                    standin.queue(*(Reply(content=t, model=settings.model.model)
                                    for t in gc.frozen(case["name"])["model_replies"]))
                r = client.post("/report", json=body)
                assert r.status_code == 200, r.text
                out[case["name"]] = r.json()
    finally:
        drop(settings)
    return out


def _served_elsewhere(report: dict) -> dict:
    """The fields that name the server that wrote the prose (spark7 when frozen, the stand-in in the replay):
    its host, and the key and id that include it. Everything else must match."""
    out = json.loads(json.dumps(report))
    out["artefact_id"] = "*"
    out["provenance"]["idempotency_key"] = "*"
    if out["provenance"]["model"]:
        out["provenance"]["model"]["host"] = "*"
    return out


@pytest.mark.parametrize("name", NAMES)
def test_the_frozen_report_is_reproduced_exactly(name, produced):
    frozen = gc.frozen(name)["report"]
    if next(c for c in CASES if c["name"] == name).get("live"):
        assert _served_elsewhere(produced[name]) == _served_elsewhere(frozen)
        assert frozen["provenance"]["model"]["host"] == "spark7.minimind.ch"
    else:
        assert produced[name] == frozen
    assert (gc.REPORTS / f"{name}.html").read_text(encoding="utf-8") == frozen["html"]


def _resolve(node, pointer: str):
    for part in pointer.lstrip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


@pytest.mark.parametrize("name", NAMES)
def test_every_figure_traces_to_an_artefact_id(name):
    report = gc.frozen(name)["report"]
    prov = report["provenance"]
    upstream = {s["artefact_id"]: s for s in prov["sources"]}
    files = {aid: json.loads((gc.INPUTS / f).read_bytes())
             for paths in gc.upstream_files().values() for f in paths.values()
             for aid in [json.loads((gc.INPUTS / f).read_bytes())["artefact_id"]]}
    previous = None
    if report["previous_report_id"]:
        previous = next(gc.frozen(c["name"])["report"] for c in CASES
                        if gc.frozen(c["name"])["report"]["artefact_id"] == report["previous_report_id"])
    request = next(c["request"] for c in CASES if c["name"] == name)
    for fact in report["facts"]:
        assert fact["sources"], fact["fact_id"]
        for src in fact["sources"]:
            aid = src["artefact_id"]
            if src["engine"] in ("pcp", "lbs", "lbsim"):
                assert aid in upstream and upstream[aid]["engine"] == src["engine"], fact["fact_id"]
                node = _resolve(files[aid], src["path"])
                v = fact["value"]
                if fact["derivation"] == "the newest as-of date among the sources":
                    assert node == v
                elif fact["derivation"] or src["engine"] == "report":
                    assert node is not None
                elif isinstance(v, (int, float)) and not isinstance(v, bool) and not isinstance(node, (list, dict)):
                    assert float(node) == v, fact["fact_id"]
                elif fact["fact_id"].startswith("lbs.gap."):
                    assert v.endswith(node)
                elif isinstance(v, str) and v.startswith("not available"):
                    assert node.lower().startswith("not available") or v == f"not available: {node}"
                else:
                    assert node == v, fact["fact_id"]
            elif src["engine"] == "report":
                assert previous is not None and aid == previous["artefact_id"]
                node = _resolve(previous, src["path"])
                if src["path"].endswith("/value"):
                    assert node == fact["previous"], fact["fact_id"]
            elif src["engine"] == "caller":
                assert aid == prov["request_id"]
                assert _resolve(request, src["path"]) == fact["value"]
            else:
                pytest.fail(f"{fact['fact_id']} cites unknown engine {src['engine']!r}")


_EXEMPT = [
    re.compile(r"<style>.*?</style>", re.S),
    re.compile(r"<head>.*?</head>", re.S),
    re.compile(r"<code>[^<]*</code>"),
    # A fact's value, in the text or in a chart (REP-34: every printed value in an SVG is a <tspan data-fact>).
    re.compile(r'<(span|b|tspan) data-fact="[^"]*">[^<]*</\1>'),
    re.compile(r'<span class="ix">\d+</span>'),
    re.compile(r'<div class="box warn" data-meta="warnings">.*?</div>', re.S),
]


@pytest.mark.parametrize("name", NAMES)
def test_the_page_prints_no_figure_that_is_not_a_fact(name):
    """Outside fact elements, identifiers, the section index and engine notes, the page carries no number of two
    or more digits; verified prose is checked against its section's facts, and flagged prose is not printed."""
    report = gc.frozen(name)["report"]
    page = report["html"]
    by_section = {s["key"]: s for s in report["sections"]}
    for m in re.finditer(r'<p class="prose" data-prose="([^"]+)">([^<]*)</p>', page):
        s = by_section[m.group(1)]
        assert s["prose_status"] == "verified" and s["unverified_numbers"] == []
    stripped = re.sub(r'<p class="prose" data-prose="[^"]+">[^<]*</p>', " ", page)
    for pattern in _EXEMPT:
        stripped = pattern.sub(" ", stripped)
    text = htmllib.unescape(re.sub(r"<[^>]+>", " ", stripped))
    stray = [t.text for t in engine.tokens(text) if t.digits >= 2]
    assert stray == [], stray
    facts = {f["fact_id"] for f in report["facts"]}
    assert set(re.findall(r'data-fact="([^"]+)"', page)) <= facts


def test_the_update_states_its_changes_first_and_cites_both_reports():
    upd = gc.frozen("de_update")["report"]
    first = gc.frozen("de_full")["report"]
    assert upd["sections"][0]["key"] == "changes" and upd["previous_report_id"] == first["artefact_id"]
    moved = [f for f in upd["facts"] if f["fact_id"].startswith("change.")]
    assert moved and all(f["sources"][0]["artefact_id"] == first["artefact_id"] for f in moved)
    assert {f["fact_id"] for f in moved} >= {"change.pcp.role.Gain", "change.pcp.role.Protection"}


def test_the_live_prose_is_all_verified():
    """spark7's frozen drafts: every prose section verified, every figure in them one of the section's facts."""
    report = gc.frozen("de_full_prose")["report"]
    slotted = [s for s in report["sections"] if s["prose_status"] != "no_slot"]
    assert slotted and all(s["prose_status"] == "verified" and s["unverified_numbers"] == [] for s in slotted)
    assert report["provenance"]["model"]["model"] == slotted[0]["prose_model"]


def test_a_prose_free_report_is_the_same_on_a_fresh_store(produced):
    """Determinism: the prose-free cases were produced on a store that had never seen them, and match the
    frozen ids (the content hash of the whole report)."""
    for c in CASES:
        if not c["request"]["prose"]:
            assert produced[c["name"]]["artefact_id"] == gc.frozen(c["name"])["report"]["artefact_id"]
