"""Seed the versioned content store from the prototype (read only).

What goes in, each as content version 1 on first run:

* ``questionnaire/onboarding``: ``client/content/onboarding-questions.json``, verbatim (21 questions,
  ``onb2@0.1.0``);
* ``questionnaire/intake``: the offline intake form ``client/intake.html``, extracted into the same
  question structure (``intake.py``);
* ``scoring/<name>``: ``intake-scales.json``, ``risk-profile.json``, ``human-capital.json`` as
  ``{"map": <file verbatim>, "binds": [...], "source": ...}``. Each bind ties one literal German string
  of the map to a questionnaire question and the option value it stands for. The binds are declared
  below (``BINDS``), resolved against the map, and checked by the database view ``scoring_bind_check``;
  the seed report lists every mismatch and every string-like map key no bind covers;
* ``reference/<name>``: every other ``client/content/*.json``, verbatim;
* ``knowledge/<id>``: the 35 notes ``content/knowledge/*.md`` as ``{"front_matter", "markdown", "source"}``
  (``README.md`` explains the format and is not a note).

Idempotent. Per key: unchanged source and an existing seed version with the same body -> nothing written;
a changed source while the latest version is still the seed's own -> a new seed version; a changed source
after a client or curator saved a newer version -> a conflict, reported and not written (the seed never
overwrites an edit), and the run exits non-zero.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import psycopg
import yaml
from psycopg.types.json import Jsonb

from . import store
from .intake import extract

SEED_REF = "eigentlich.seed@1.0.0"

ONB = "questionnaire/onboarding"
INTAKE = "questionnaire/intake"

SCORING_FILES = ("intake-scales.json", "risk-profile.json", "human-capital.json")
QUESTIONNAIRE_FILE = "onboarding-questions.json"

QUALIFICATION = ((ONB, "qualification_highest"), (INTAKE, "qualification_highest"))
KADER = ((ONB, "kader"), (INTAKE, "kader"))
SECTOR = ((ONB, "sector"), (INTAKE, "sector"))
REACH = ((ONB, "network_reach"), (INTAKE, "network_reach"))
CIVIL = ((ONB, "civil_status"), (INTAKE, "civil_status"))


@dataclass(frozen=True)
class BindSpec:
    """Where literal answer strings sit in a map, and which questions they answer.

    ``path`` is a list of keys; ``*`` matches every key of a mapping or every element of a list. ``mode``:
    ``keys`` (the keys of the mapping at the path are the strings), ``values`` (the list at the path holds
    the strings), ``value`` (the path ends at one string), ``keys_label`` (the keys are the map's own names
    and each entry's ``label.de`` is the option value it binds to).
    """

    path: tuple[str, ...]
    mode: str
    targets: tuple[tuple[str, str], ...]
    #: Keys at the path that are the map's own notes, not answer strings.
    exclude: tuple[str, ...] = ()


#: The binds, per scoring map. Question keys are the ones the prototype's services read each map with
#: (services/identities.py, risk_profile.py, human_capital.py, profile_inputs.py).
BINDS: dict[str, tuple[BindSpec, ...]] = {
    "intake-scales": (
        BindSpec(("confidence", "options"), "keys", ((INTAKE, "goal_confidence"),)),
        BindSpec(("civil_status", "partnered"), "values", CIVIL),
        BindSpec(("civil_status", "married"), "values", CIVIL),
        # services/identities.learning_commitment_scale reads `education_hours`; neither questionnaire
        # asks it. Declared anyway so the report shows the gap instead of hiding it.
        BindSpec(("learning_commitment", "hours"), "keys", ((INTAKE, "education_hours"),)),
    ),
    "risk-profile": (
        BindSpec(("willingness", "crisis_behaviour", "caps"), "keys", ((INTAKE, "crisis_behaviour"),)),
        BindSpec(("willingness", "crisis_behaviour", "floors"), "keys", ((INTAKE, "crisis_behaviour"),)),
        BindSpec(("capacity", "components", "income_stability", "base"), "keys", ((INTAKE, "employment"),)),
        BindSpec(("sustainability", "exclusions", "offered"), "values", ((INTAKE, "esg_exclusions"),)),
        BindSpec(("sustainability", "minimum", "levels", "*", "label"), "value", ((INTAKE, "esg_minimum"),)),
    ),
    "human-capital": (
        BindSpec(("expertise", "anchors", "by_qualification"), "keys", QUALIFICATION),
        BindSpec(("expertise", "anchors", "bfs_monthly_median_ohne_kader"), "keys", QUALIFICATION),
        BindSpec(("expertise", "intake_question", "options"), "values", QUALIFICATION),
        BindSpec(("network", "reach", "multipliers"), "keys", REACH),
        BindSpec(("network", "reach", "intake_question", "options"), "values", REACH),
        BindSpec(("health", "levels"), "keys", ((INTAKE, "health"),)),
        BindSpec(("rest_hours_bands",), "keys", ((INTAKE, "rest_hours"),), exclude=("midpoint_warning",)),
        BindSpec(("responsibility", "tiers"), "keys_label", KADER),
        BindSpec(("responsibility", "tiers", "oberes und mittleres Kader", "multiplier_by_qualification"), "keys",
                 QUALIFICATION),
        BindSpec(("responsibility", "tiers", "topmanagement", "multiplier_by_sector"), "keys", SECTOR),
        BindSpec(("responsibility", "tiers", "topmanagement", "bfs_monthly_by_sector"), "keys", SECTOR),
        BindSpec(("responsibility", "intake_question", "options"), "values", KADER),
        BindSpec(("responsibility", "sector_question", "options"), "values", SECTOR),
    ),
}


class SeedError(ValueError):
    """A source is missing or malformed, or a bind declaration does not match its map."""


# ---------------------------------------------------------------------------
# Reading the sources
# ---------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SeedError(f"{path}: {exc}") from exc


def _walk(node: Any, path: Sequence[str], at: tuple[Any, ...] = ()) -> Iterable[tuple[tuple[Any, ...], Any]]:
    if not path:
        yield at, node
        return
    head, rest = path[0], path[1:]
    if head == "*":
        items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else None
        if items is None:
            raise SeedError(f"bind path {'/'.join(map(str, at))}/*: not a mapping or list")
        for k, v in items:
            if isinstance(k, str) and k.startswith("_"):
                continue
            yield from _walk(v, rest, at + (k,))
        return
    if not isinstance(node, dict) or head not in node:
        raise SeedError(f"bind path {'/'.join(map(str, at + (head,)))}: not in the map")
    yield from _walk(node[head], rest, at + (head,))


def resolve_binds(name: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    """The explicit binds of one map: every bound string, per target question."""
    binds: list[dict[str, Any]] = []
    for spec in BINDS[name]:
        for at, node in _walk(body, spec.path):
            pairs: list[tuple[tuple[Any, ...], str, str]] = []   # (path, string, option value)
            if spec.mode == "keys":
                if not isinstance(node, dict):
                    raise SeedError(f"{name}: {'/'.join(map(str, at))} is not a mapping")
                pairs = [(at + (k,), k, k) for k in node if not k.startswith("_") and k not in spec.exclude]
            elif spec.mode == "keys_label":
                if not isinstance(node, dict):
                    raise SeedError(f"{name}: {'/'.join(map(str, at))} is not a mapping")
                for k, v in node.items():
                    if k.startswith("_"):
                        continue
                    label = (v.get("label") or {}).get("de") if isinstance(v, dict) else None
                    if not isinstance(label, str):
                        raise SeedError(f"{name}: {'/'.join(map(str, at + (k,)))} has no label.de to bind")
                    pairs.append((at + (k,), k, label))
            elif spec.mode == "values":
                if not isinstance(node, list) or not all(isinstance(v, str) for v in node):
                    raise SeedError(f"{name}: {'/'.join(map(str, at))} is not a list of strings")
                pairs = [(at + (i,), v, v) for i, v in enumerate(node)]
            elif spec.mode == "value":
                if not isinstance(node, str):
                    raise SeedError(f"{name}: {'/'.join(map(str, at))} is not a string")
                pairs = [(at, node, node)]
            else:  # pragma: no cover - a programming error in BINDS
                raise SeedError(f"unknown bind mode {spec.mode}")
            for p, string, option in pairs:
                for questionnaire, question in spec.targets:
                    binds.append({"path": list(p), "string": string, "option_value": option,
                                  "questionnaire": questionnaire, "question": question})
    return binds


def unbound_candidates(name: str, body: Any, binds: Sequence[dict[str, Any]]) -> list[str]:
    """Leaf keys that look like answer strings (a space, a non-ASCII letter, a per cent sign or a leading
    digit) and are covered by no bind. Identifiers such as ``max_tau_Y`` are the map's own names."""
    bound = {tuple(b["path"]) for b in binds}
    out: list[str] = []

    def visit(node: Any, at: tuple[Any, ...]) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k.startswith("_"):
                    continue
                here = at + (k,)
                looks = (" " in k or "%" in k or not k.isascii() or k[:1].isdigit())
                if looks and here not in bound and not isinstance(v, (dict, list)):
                    out.append("/".join(map(str, here)))
                visit(v, here)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                visit(v, at + (i,))

    visit(body, ())
    return out


def _json_safe(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def read_knowledge(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SeedError(f"{path.name}: no front matter")
    try:
        _, fm_text, markdown = text.split("---", 2)
        front = yaml.safe_load(fm_text)
    except ValueError as exc:
        raise SeedError(f"{path.name}: front matter is not closed") from exc
    if not isinstance(front, dict):
        raise SeedError(f"{path.name}: front matter is not a mapping")
    if front.get("id") != path.stem:
        raise SeedError(f"{path.name}: front matter id {front.get('id')!r} does not match the file name")
    return {"front_matter": _json_safe(front), "markdown": markdown.lstrip("\n")}


@dataclass(frozen=True)
class Item:
    key: str
    kind: str
    body: Any
    source: str          # relative to the prototype root
    sha256: str


def collect(root: Path) -> list[Item]:
    """Everything the seed writes, read and checked, before anything touches the database."""
    content = root / "client" / "content"
    knowledge = root / "content" / "knowledge"
    intake_html = root / "client" / "intake.html"
    for p in (content, knowledge, intake_html):
        if not p.exists():
            raise SeedError(f"source missing: {p}")
    items: list[Item] = []

    onb_path = content / QUESTIONNAIRE_FILE
    onb = _json(onb_path)
    if not isinstance(onb.get("questions"), list):
        raise SeedError(f"{onb_path.name}: no questions list")
    items.append(Item(ONB, "questionnaire", onb, f"client/content/{onb_path.name}", _sha256(onb_path)))
    items.append(Item(INTAKE, "questionnaire", extract(intake_html), "client/intake.html", _sha256(intake_html)))

    for path in sorted(content.glob("*.json")):
        if path.name == QUESTIONNAIRE_FILE:
            continue
        rel = f"client/content/{path.name}"
        body = _json(path)
        if path.name in SCORING_FILES:
            binds = resolve_binds(path.stem, body)
            items.append(Item(f"scoring/{path.stem}", "scoring_map",
                              {"map": body, "binds": binds, "source": rel}, rel, _sha256(path)))
        else:
            items.append(Item(f"reference/{path.stem}", "reference", body, rel, _sha256(path)))

    for path in sorted(knowledge.glob("*.md")):
        if path.name == "README.md":
            continue
        rel = f"content/knowledge/{path.name}"
        items.append(Item(f"knowledge/{path.stem}", "knowledge", {**read_knowledge(path), "source": rel},
                          rel, _sha256(path)))
    return items


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def seed(conn: psycopg.Connection, root: Path) -> dict[str, Any]:
    """Seed in one transaction. Returns the report; ``report["ok"]`` is False on any conflict."""
    items = collect(root)
    outcome: dict[str, list[str]] = {"created": [], "updated": [], "unchanged": [], "conflict": []}
    details: list[dict[str, Any]] = []
    with conn.transaction():
        for item in items:
            history = store.content_history(conn, item.key)
            seeds = [h for h in history if h["saved_by_kind"] == "seed"]
            same = False
            if seeds:
                same = conn.execute("SELECT body = %s AS same FROM content_record WHERE key = %s AND version = %s",
                                    (Jsonb(item.body), item.key, seeds[-1]["version"])).fetchone()["same"]
            if same:
                status, version = "unchanged", seeds[-1]["version"]
            elif not history or history[-1]["saved_by_kind"] == "seed":
                status = "created" if not history else "updated"
                version = store.save_content(conn, key=item.key, kind=item.kind, body=item.body,
                                             saved_by_kind="seed", saved_by_ref=SEED_REF,
                                             note=f"seeded from Prototype/{item.source} sha256:{item.sha256}")
            else:
                status, version = "conflict", history[-1]["version"]
            outcome[status].append(item.key)
            details.append({"key": item.key, "kind": item.kind, "status": status, "version": version,
                            "source": item.source, "sha256": item.sha256})

    kinds: dict[str, int] = {}
    for item in items:
        kinds[item.kind] = kinds.get(item.kind, 0) + 1
    checks = conn.execute("SELECT scoring_key, string, option_value, questionnaire_key, question_key, path, status "
                          "FROM scoring_bind_check ORDER BY scoring_key, bind_index").fetchall()
    mismatches = [dict(c) for c in checks if c["status"] != "ok"]
    unbound = {f"scoring/{name}": unbound_candidates(name, it.body["map"], it.body["binds"])
               for it in items if it.kind == "scoring_map" for name in [it.key.split("/", 1)[1]]}
    questionnaires = {it.key: {"version": it.body.get("version"), "questions": len(it.body["questions"])}
                      for it in items if it.kind == "questionnaire"}
    return {
        "ok": not outcome["conflict"],
        "counts": {k: len(v) for k, v in outcome.items()},
        "by_kind": kinds,
        "questionnaires": questionnaires,
        "conflicts": outcome["conflict"],
        "binds": {"total": len(checks), "ok": len(checks) - len(mismatches), "mismatches": mismatches},
        "unbound_candidates": {k: v for k, v in unbound.items() if v},
        "items": details,
    }


def format_report(report: dict[str, Any]) -> str:
    lines = ["Seed report", "==========="]
    c = report["counts"]
    lines.append(f"content keys: {sum(c.values())}  created {c['created']}  updated {c['updated']}  "
                 f"unchanged {c['unchanged']}  conflict {c['conflict']}")
    lines.append("by kind: " + ", ".join(f"{k} {v}" for k, v in sorted(report["by_kind"].items())))
    for key, q in report["questionnaires"].items():
        lines.append(f"{key}: {q['version']}, {q['questions']} questions")
    b = report["binds"]
    lines.append(f"binds: {b['total']} checked, {b['ok']} ok, {len(b['mismatches'])} mismatches")
    for m in b["mismatches"]:
        lines.append(f"  MISMATCH {m['scoring_key']} {'/'.join(map(str, m['path']))}: {m['option_value']!r} -> "
                     f"{m['questionnaire_key']}#{m['question_key']}: {m['status']}")
    for key, paths in report["unbound_candidates"].items():
        for p in paths:
            lines.append(f"  UNBOUND {key} {p}: looks like an answer string, no bind declared")
    for key in report["conflicts"]:
        lines.append(f"  CONFLICT {key}: the source changed and a client or curator saved a newer version; not written")
    return "\n".join(lines)
