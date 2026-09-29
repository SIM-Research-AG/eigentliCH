"""Readers see neither ids nor keys, and one language (REP-19, REP-20).

* Every key and reason lbs and pcp can emit has a sentence here in German and in English: the lbs and pcp
  sources are read (they sit beside this engine in the family and the Optimizer) and each gap input, gap kind,
  finding reason, not-available reason, absent reason, binding and coverage warning they write is looked up.
  A new one upstream turns this red until it has its sentences.
* No rendered report, frozen or constructed with UUID-like ids, carries a 32-hex id, a UUID or a snake_case key
  in what a reader sees; a German page carries none of the upstream English.
* Persons and goals are named by the caller's display facts on the page, generically otherwise, and the model
  sees only the generic names.
"""

from __future__ import annotations

import html as htmllib
import json
import re
from pathlib import Path

import pytest

from report import vocabulary as voc

from . import golden_cases as gc
from .conftest import INPUTS, request_body

ROOT = Path(__file__).resolve().parent.parent
LBS_SRC = ROOT.parent / "lbs" / "src" / "lbs"
PCP_SRC = ROOT.parents[2] / "Optimizer" / "engines" / "pcp" / "src" / "pcp"


def visible(page: str) -> str:
    """What a reader sees: the title and the text between the tags, entities decoded."""
    title = re.search(r"<title>(.*?)</title>", page, re.S)
    body = re.sub(r"<head>.*?</head>", " ", page, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    return htmllib.unescape((title.group(1) if title else "") + " " + text)


def internal(text: str) -> list[str]:
    return [m.group(0) for p in (voc.HEX32, voc.UUID, voc.SNAKE, voc.PREFIXED, voc.HEX16) for m in p.finditer(text)]


def test_the_id_patterns_catch_every_prefixed_id():
    for sample in ("LBS-87187d7cbb0454b5", "PCP-e213eab0625c0b86", "REP-4f73e96d7b7b2907", "RUN-0123456789abcdef",
                   "IDK-0123456789abcdef", "RRQ-cf68ec90594ccb16", "RGM-0123456789abcdef", "RS-0123456789abcdef",
                   "ef793a1ef16f849a"):
        assert internal(f"Quelle {sample}."), sample


# -- every entry in both languages ---------------------------------------------------------------------------

def _tables():
    for e in voc.REASONS + voc.GAP_INPUTS:
        yield e.key, e.text
    for w in voc.PCP_WARNINGS:
        yield w.key, w.text
    for table in (voc.GAP_KINDS, voc.FINDING_REASONS, voc.BINDS, voc.TOPIC, voc.GOAL, voc.PAGE_NOTES,
                  voc.BASIS_WORDS, voc.JUDGEMENT):
        yield from table.items()
    for key, texts in (("fallback_reason", voc.FALLBACK_REASON), ("fallback_gap", voc.FALLBACK_GAP),
                       ("fallback_finding", voc.FALLBACK_FINDING), ("fallback_pcp", voc.FALLBACK_PCP),
                       ("unnamed", voc.UNNAMED), ("person", voc.PERSON),
                       ("basis_nominal_kept", voc.BASIS_NOMINAL_KEPT), ("basis_label", voc.BASIS_ALLOCATION_LABEL)):
        yield key, texts
    for name, table in (("basis_header", voc.BASIS_HEADER), ("basis_mark", voc.BASIS_MARK),
                        ("basis_allocation", voc.BASIS_ALLOCATION), ("basis_prompt", voc.BASIS_PROMPT)):
        assert set(table) == {"nominal", "real"}, name
        for basis, texts in table.items():
            yield f"{name}.{basis}", texts


@pytest.mark.parametrize("key,texts", list(_tables()), ids=[k for k, _ in _tables()])
def test_every_entry_has_a_german_and_an_english_text(key, texts):
    assert set(texts) >= {"de", "en"}, key
    for lang in ("de", "en"):
        assert texts[lang].strip() and not internal(texts[lang].replace("{capital}", "").replace("{why}", "")), key
    assert "ß" not in texts["de"], key


# -- every key lbs and pcp can emit ---------------------------------------------------------------------------

def _source(folder: Path) -> str:
    if not folder.is_dir():
        pytest.skip(f"{folder} is not beside this engine; the upstream sources cannot be read")
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.py")))


def _sample(fstring: str) -> list[str]:
    """An f-string input as the values it takes: ``{cap.key}`` is E, N or H; any other placeholder an id."""
    if "{cap.key}" in fstring:
        return [re.sub(r"\{[^}]+\}", "p1", fstring.replace("{cap.key}", k)) for k in "ENH"]
    return [re.sub(r"\{[^}]+\}", "x1", fstring)]


def lbs_emits() -> dict[str, set[str]]:
    src = _source(LBS_SRC)
    inputs, kinds = set(), set()
    for m in re.finditer(r'ctx\.gap\(\s*[^,]+,\s*(f?)"([^"]+)"\s*,\s*"([^"]+)"', src):
        inputs.update(_sample(m.group(2)) if m.group(1) else [m.group(2)])
        kinds.add(m.group(3))
    kinds.update(re.findall(r'"(record_not_approved|past_its_validity_horizon|not_in_the_request)"', src))
    finding = set(re.findall(r'(?:undetermined_because"\]|\bwhy)\.append\("([^"]+)"\)', src))
    finding.update(re.findall(r'undetermined_because=\("([^"]+)",?\)', src))
    reasons = set(re.findall(r'NotAvailable\(reason=\(?\s*f?"([^"]+)"', src))
    reasons.update(re.findall(r'basis = \(?"(not available[^"]*)"', src))
    reasons.update(v for _, v in re.findall(r'^(NOT_ASKED|NOT_ANSWERED|WITHHELD) = "([^"]+)"', src, re.M))
    liquidity = set(re.findall(r'LiquidityFinding\([^)]*?reason="([^"]+)"', src, re.S))
    liquidity.update(re.findall(r'"reason": "([a-z_]+)"', src))
    binds = set(re.findall(r'\bbinds = "([^"]+)"', src)) | set(re.findall(r'binds_on"\]\.append\("([^"]+)"\)', src))
    return {"inputs": inputs, "kinds": kinds, "finding": finding, "reasons": reasons, "liquidity": liquidity,
            "binds": binds}


def test_the_lbs_source_is_read():
    """The scan finds what it must, so an empty scan cannot pass for a covered vocabulary."""
    found = lbs_emits()
    assert len(found["inputs"]) >= 30 and len(found["reasons"]) >= 10 and found["liquidity"] and found["binds"]
    assert "the_goal_does_not_say_whether_the_member_will_live_in_it" in found["finding"]


@pytest.mark.parametrize("kind", ["inputs", "finding"])
def test_every_lbs_gap_input_and_finding_reason_has_its_sentence(kind):
    missing = sorted(i for i in lbs_emits()[kind] if voc.gap_entry(i) is None)
    assert missing == [], missing


def test_every_lbs_gap_kind_has_its_sentence():
    missing = sorted(k for k in lbs_emits()["kinds"] if k not in voc.GAP_KINDS)
    assert missing == [], missing


def test_every_lbs_not_available_and_absent_reason_has_its_sentence():
    missing = sorted(r for r in lbs_emits()["reasons"] if voc.reason_entry(r) is None)
    assert missing == [], missing


def test_every_lbs_liquidity_reason_and_binding_has_its_text():
    found = lbs_emits()
    assert sorted(r for r in found["liquidity"] if r not in voc.FINDING_REASONS) == []
    assert sorted(b for b in found["binds"] if b not in voc.BINDS) == []


def test_every_pcp_coverage_warning_has_its_sentence():
    src = _source(PCP_SRC)
    sites = re.findall(r'(?:warnings|notes)\.append\(f?"([^"]*)"', src)
    assert len(sites) >= 5, sites
    for literal in sites:
        sample = re.sub(r"\{[^}]*\}", "X", literal)
        assert any(w.pattern.search(sample) for w in voc.PCP_WARNINGS), literal
        assert any(w.source_prefix in literal or literal.startswith(w.source_prefix) for w in voc.PCP_WARNINGS
                   if w.pattern.search(sample)), literal


# -- no id and no key on any page -----------------------------------------------------------------------------

@pytest.mark.parametrize("name", [c["name"] for c in gc.cases()])
def test_no_frozen_report_shows_an_id_or_a_key(name):
    report = gc.frozen(name)["report"]
    text = visible(report["html"])
    assert internal(text) == []
    for s in report["provenance"]["sources"]:
        assert s["artefact_id"] not in report["html"] and s["sha256"][:16] not in report["html"]
    assert report["provenance"]["request_id"] not in report["html"]
    upstream = [f["value"] for f in report["facts"] if f["unit"] == "text"
                and (f["fact_id"].startswith(("lbs.gap.", "pcp.warning.")) or str(f["value"]).startswith("not available"))]
    for raw in upstream:
        assert raw not in text, raw
    if report["language"] == "de":
        assert not re.search(r"\b(?:the|is|not available)\b", text), re.findall(r".{30}\bthe\b.{30}", text)


HEX_GOAL = "76658f42c1e04b5e9a3d2b1c0f9e8d7a"
HEX_PERSON = "0a1b2c3d4e5f60718293a4b5c6d7e8f9"


def constructed_with_ids() -> bytes:
    """The property sheet with ids as the consumer app makes them, and a gap for every input lbs can emit."""
    raw = (INPUTS / "lbs_sheet_property.json").read_text(encoding="utf-8")
    raw = re.sub(r"\bg1\b", HEX_GOAL, raw)
    raw = re.sub(r"\bp1\b", HEX_PERSON, raw)
    sheet = json.loads(raw)
    gaps = []
    for entry in voc.GAP_INPUTS:
        sample = entry.key.replace("capital", f"{HEX_PERSON}.E").replace("position_vessel", "pos_42.vessel")
        section = {"capital": "human_capital", "age": f"pensions.{HEX_PERSON}"}.get(entry.key, f"property.{HEX_GOAL}")
        gaps.append({"section": section, "input": sample, "kind": "not_in_the_request",
                     "reason": "E is absent: the intake does not ask a question this could be derived from"})
    gaps.append({"section": "totals", "input": "some_new_input", "kind": "some_new_kind", "reason": "new"})
    sheet["gaps"] = gaps
    sheet["liquidity"] = [{"goal_id": HEX_GOAL, "gap_chf": 12000.0, "due_date": "2030-01-01",
                           "reason": "funding_is_illiquid", "prepared": None}]
    sheet["artefact_id"] = "LBS-00000000c0ffee01"
    return json.dumps(sheet).encode("utf-8")


@pytest.fixture(scope="module")
def id_pages(client, upstream):
    upstream.extra["lbs"]["/artefacts/LBS-00000000c0ffee01"] = constructed_with_ids()
    client_ref = json.loads(constructed_with_ids())["client_ref"]
    sources = [{"engine": "lbs", "artefact_id": "LBS-00000000c0ffee01"}]
    out = {}
    for lang in ("de", "en"):
        named = client.post("/report", json=request_body(
            client_ref=client_ref, language=lang, sources=sources, prose=False,
            display_facts=[{"key": "name", "label": "Kundin", "value": "Muster", "source": "app"},
                           {"key": f"goal.{HEX_GOAL}", "label": "Ziel", "value": "Wohnung in Bern", "source": "app"}]))
        plain = client.post("/report", json=request_body(client_ref=client_ref, language=lang, sources=sources,
                                                         prose=False, display_facts=[]))
        assert named.status_code == 200 and plain.status_code == 200, (named.text, plain.text)
        out[lang] = (named.json(), plain.json())
    return out


@pytest.mark.parametrize("lang", ["de", "en"])
def test_a_report_on_uuid_like_ids_shows_none_of_them(id_pages, lang):
    for report in id_pages[lang]:
        text = visible(report["html"])
        assert internal(text) == [], internal(text)
        assert HEX_GOAL not in text and HEX_PERSON not in text and "pos_42" not in text
        assert report["client_ref"] not in text
        assert report["artefact_id"] not in report["html"] and report["provenance"]["request_id"] not in report["html"]
        assert all(s["artefact_id"] not in report["html"] for s in report["provenance"]["sources"])


def test_goals_are_named_by_the_callers_display_fact_or_generically(id_pages):
    (named_de, plain_de), (named_en, plain_en) = id_pages["de"], id_pages["en"]
    assert "Wohnung in Bern" in visible(named_de["html"]) and "Ihr Wohneigentumsziel" not in visible(named_de["html"])
    assert "Ihr Wohneigentumsziel" in visible(plain_de["html"]) and "Person 1" in visible(plain_de["html"])
    assert "Your home ownership goal" in visible(plain_en["html"])
    # The naming display fact is not a header chip, and the artefact keeps the generic label.
    assert 'class="chip">Ziel' not in named_de["html"]
    assert all("Wohnung in Bern" not in f["label"] for f in named_de["facts"])
    assert named_de["title"] == "Bericht · Muster" and plain_de["title"] == "Bericht"


def test_unknown_upstream_keys_fall_back_to_a_plain_sentence(id_pages):
    text = visible(id_pages["de"][1]["html"])
    assert voc.GAP_KINDS.get("some_new_kind") is None and voc.FALLBACK_GAP["de"] in text
    assert "some_new_input" not in text


def test_the_model_sees_the_generic_names_only(client, upstream, spark):
    upstream.extra["lbs"]["/artefacts/LBS-00000000c0ffee01"] = constructed_with_ids()
    client_ref = json.loads(constructed_with_ids())["client_ref"]
    r = client.post("/report", json=request_body(
        client_ref=client_ref, sources=[{"engine": "lbs", "artefact_id": "LBS-00000000c0ffee01"}], prose=True,
        display_facts=[{"key": f"goal.{HEX_GOAL}", "label": "Ziel", "value": "Wohnung in Bern", "source": "app"}]))
    assert r.status_code == 200, r.text
    prompts = " ".join(m["content"] for q in spark.chat_requests() for m in q["body"]["messages"])
    assert prompts and "Wohnung in Bern" not in prompts and HEX_GOAL not in prompts
    assert "MiniMind" in visible(r.json()["html"])


# -- the four roles by the house's names (REP-24) -----------------------------------------------------------------

ROLES_RECORD = ROOT.parents[3] / "eigentliCH" / "Prototype" / "client" / "content" / "roles.json"


def test_the_role_names_are_the_houses():
    """The names fixed in the content record reference/roles: "Einkommen" and "Absicherung", never "Ertrag" and
    "Schutz"; the gain role "Wertsteigerung" / "Gain" on the financial side and "Wachstum" / "Growth" on the
    human side."""
    expected = {("gain", "financial", "de"): "Wertsteigerung", ("gain", "financial", "en"): "Gain",
                ("gain", "human", "de"): "Wachstum", ("gain", "human", "en"): "Growth",
                ("income", "financial", "de"): "Einkommen", ("income", "human", "de"): "Einkommen",
                ("income", "financial", "en"): "Income", ("income", "human", "en"): "Income",
                ("stabilisation", "financial", "de"): "Stabilisierung",
                ("stabilisation", "human", "de"): "Stabilisierung",
                ("stabilisation", "financial", "en"): "Stabilisation",
                ("stabilisation", "human", "en"): "Stabilisation",
                ("protection", "financial", "de"): "Absicherung", ("protection", "human", "de"): "Absicherung",
                ("protection", "financial", "en"): "Protection", ("protection", "human", "en"): "Protection"}
    for (role, capital, lang), name in expected.items():
        assert voc.role_name(role, lang, capital) == name, (role, capital, lang)
        assert voc.role_name(role.capitalize(), lang, capital) == name, "pcp writes the roles capitalised"
    assert voc.role_name("Gain", "de") == "Wertsteigerung" and voc.role_name("growth", "de", "human") == "Wachstum"


def test_the_role_names_match_the_content_record():
    if not ROLES_RECORD.is_file():
        pytest.skip(f"{ROLES_RECORD} is not beside this engine")
    record = json.loads(ROLES_RECORD.read_text(encoding="utf-8"))
    for entry in record["roles"]:
        key = voc.ROLE_ALIASES.get(entry["key"], entry["key"])
        for capital, names in entry["display"].items():
            for lang in ("de", "en"):
                assert voc.ROLE_NAMES[key][capital][lang] == names[lang], (key, capital, lang)
    assert len(record["roles"]) == len(voc.ROLE_NAMES) == 4


@pytest.mark.parametrize("name", [c["name"] for c in gc.cases()])
def test_no_frozen_report_uses_the_draft_role_names(name):
    report = gc.frozen(name)["report"]
    page = visible(report["html"])
    assert not re.search(r"\b(Ertrag|Schutz)\b", page), name
    if report["language"] == "de" and "Gewicht nach Rolle" in page:
        assert "Absicherung" in page and "Einkommen" in page
