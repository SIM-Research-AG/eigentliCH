"""Extract the offline intake form (``Prototype/client/intake.html``) into questionnaire content.

The form's schema is hardcoded twice: once as the ``FIELDS`` and ``REPEATS`` constants in its script
(what the form saves), and once as HTML (what a person reads: section titles and ledes, labels, the
why-texts, units, placeholders and the options of each select). This reads both and fails loudly unless
they agree field for field: a key in one and not the other, or a kind that does not match the control,
is an error, never a guess.

The output uses the onboarding questionnaire's question structure (``key``, ``order``, ``section``,
``type``, ``unit``, ``options`` as ``[{value, label: {de}}]``, ``question: {de}``, ``why: {de}``), so the
consumer app renders both with one component. Types map as: select -> ``choice``, number input ->
``number``, text input -> ``text``, textarea -> ``text`` with ``multiline: true``; the repeat group
(``properties``) is one question of type ``repeat`` whose ``fields`` use the same structure.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional


class IntakeError(ValueError):
    """The form's HTML and its FIELDS/REPEATS constants disagree, or the file is not the form."""


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self.fields: list[dict[str, Any]] = []
        self._section: Optional[dict[str, Any]] = None
        self._field: Optional[dict[str, Any]] = None
        self._capture: Optional[str] = None     # which text is being read
        self._buf: list[str] = []
        self._option: Optional[list[str]] = None
        self._div_depth = 0                     # depth inside the current div.f
        self._in_header = False

    # -- helpers -----------------------------------------------------------

    def _start_capture(self, what: str) -> None:
        self._capture = what
        self._buf = []

    def _end_capture(self) -> str:
        text = _clean("".join(self._buf))
        self._capture = None
        self._buf = []
        return text

    # -- parser callbacks --------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        classes = set(a.get("class", "").split())
        if tag == "section":
            self._section = {"number": None, "title": None, "lede": None, "repeat": None}
            self.sections.append(self._section)
            return
        if self._section is None:
            return
        if tag == "header":
            self._in_header = True
        elif tag == "span" and "n" in classes and self._in_header:
            self._start_capture("number")
        elif tag == "h2" and self._in_header:
            self._start_capture("title")
        elif tag == "p" and "seclede" in classes:
            self._start_capture("lede")
        elif tag == "div" and "rows" in classes and a.get("data-repeat"):
            self._section["repeat"] = a["data-repeat"]
        elif tag == "div" and "f" in classes and self._field is None:
            self._field = {"section": self._section, "label": None, "why": None, "control": None,
                           "name": None, "input_type": None, "options": [], "unit": None,
                           "placeholder": None, "attrs": {}}
            self.fields.append(self._field)
            self._div_depth = 1
        elif tag == "div" and self._field is not None:
            self._div_depth += 1
        elif self._field is not None:
            if tag == "label":
                self._start_capture("label")
            elif tag == "p" and "why" in classes:
                self._start_capture("why")
            elif tag in ("input", "select", "textarea"):
                self._field["control"] = tag
                self._field["name"] = a.get("name")
                self._field["input_type"] = a.get("type") if tag == "input" else None
                self._field["placeholder"] = a.get("placeholder") or None
                self._field["attrs"] = {k: a[k] for k in ("min", "max", "step") if k in a}
            elif tag == "option":
                self._option = []
            elif tag == "span" and "unit" in classes:
                self._start_capture("unit")

    def handle_endtag(self, tag: str) -> None:
        if tag == "header":
            self._in_header = False
        if self._capture == "number" and tag == "span":
            self._section["number"] = self._end_capture()
        elif self._capture == "title" and tag == "h2":
            self._section["title"] = self._end_capture()
        elif self._capture == "lede" and tag == "p":
            self._section["lede"] = self._end_capture()
        elif self._capture == "label" and tag == "label":
            self._field["label"] = self._end_capture()
        elif self._capture == "why" and tag == "p":
            self._field["why"] = self._end_capture()
        elif self._capture == "unit" and tag == "span":
            self._field["unit"] = self._end_capture()
        elif tag == "option" and self._option is not None:
            text = _clean("".join(self._option))
            if text:
                self._field["options"].append(text)
            self._option = None
        elif tag == "div" and self._field is not None:
            self._div_depth -= 1
            if self._div_depth == 0:
                self._field = None
        elif tag == "section":
            self._section = None

    def handle_data(self, data: str) -> None:
        if self._option is not None:
            self._option.append(data)
        elif self._capture:
            self._buf.append(data)


_CONST = re.compile(r"^const (FIELDS|REPEATS) = (\[.*\]);\s*$", re.MULTILINE)


def _constants(html: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    found = {m.group(1): json.loads(m.group(2)) for m in _CONST.finditer(html)}
    if set(found) != {"FIELDS", "REPEATS"}:
        raise IntakeError(f"intake.html: expected const FIELDS and const REPEATS, found {sorted(found)}")
    return found["FIELDS"], found["REPEATS"]


_SCHEMA_VERSION = re.compile(r"schema_version:\s*'([^']+)'")


def _type_of(field: dict[str, Any]) -> tuple[str, bool]:
    if field["control"] == "select":
        return "choice", False
    if field["control"] == "textarea":
        return "text", True
    if field["control"] == "input" and field["input_type"] == "number":
        return "number", False
    if field["control"] == "input" and field["input_type"] == "text":
        return "text", False
    raise IntakeError(f"intake.html: field {field['name']!r} has an unrecognised control "
                      f"{field['control']}/{field['input_type']}")


_KIND = {("choice", False): "choice", ("text", True): "textarea", ("number", False): "number", ("text", False): "text"}


def _options(values: list[str]) -> list[dict[str, Any]]:
    return [{"value": v, "label": {"de": v}} for v in values]


def extract(path: Path) -> dict[str, Any]:
    """The intake questionnaire as content: ``{version, source, sections, questions}``."""
    html = path.read_text(encoding="utf-8")
    fields_const, repeats_const = _constants(html)
    m = _SCHEMA_VERSION.search(html)
    if not m:
        raise IntakeError("intake.html: no schema_version in the download payload")
    parser = _Parser()
    parser.feed(html)
    parser.close()

    sections = []
    for i, s in enumerate(parser.sections, start=1):
        if not s["number"] or not s["title"]:
            raise IntakeError(f"intake.html: section {i} has no number or title")
        sections.append({"key": s["number"], "order": i, "title": {"de": s["title"]},
                         "lede": {"de": s["lede"]} if s["lede"] else None})

    by_name = {}
    for f in parser.fields:
        if not f["name"]:
            raise IntakeError(f"intake.html: a field labelled {f['label']!r} has no control name")
        if f["name"] in by_name:
            raise IntakeError(f"intake.html: field {f['name']!r} appears twice")
        by_name[f["name"]] = f

    const_keys = [f["key"] for f in fields_const]
    html_keys = [f["name"] for f in parser.fields]
    if const_keys != html_keys:
        missing = sorted(set(const_keys) - set(html_keys))
        extra = sorted(set(html_keys) - set(const_keys))
        raise IntakeError(f"intake.html: FIELDS and the HTML disagree (only in FIELDS: {missing}; only in the "
                          f"HTML: {extra}; or the order differs)")

    repeat_sections = {s["repeat"]: s for s in parser.sections if s["repeat"]}
    if set(repeat_sections) != {r["key"] for r in repeats_const}:
        raise IntakeError(f"intake.html: REPEATS {[r['key'] for r in repeats_const]} and the HTML repeat groups "
                          f"{sorted(repeat_sections)} disagree")

    questions: list[dict[str, Any]] = []
    order = 0
    const_kind = {f["key"]: f["kind"] for f in fields_const}
    # Walk sections in document order so repeats land where they stand in the form.
    for s in parser.sections:
        for f in (x for x in parser.fields if x["section"] is s):
            qtype, multiline = _type_of(f)
            if _KIND[(qtype, multiline)] != const_kind[f["name"]]:
                raise IntakeError(f"intake.html: field {f['name']!r} is {const_kind[f['name']]} in FIELDS but "
                                  f"a {f['control']} in the HTML")
            if not f["label"]:
                raise IntakeError(f"intake.html: field {f['name']!r} has no label")
            if qtype == "choice" and not f["options"]:
                raise IntakeError(f"intake.html: choice {f['name']!r} has no options")
            order += 1
            q: dict[str, Any] = {"key": f["name"], "order": order, "section": s["number"], "type": qtype,
                                 "required": False, "question": {"de": f["label"]}}
            if multiline:
                q["multiline"] = True
            if f["unit"]:
                q["unit"] = f["unit"]
            for bound in ("min", "max"):
                if bound in f["attrs"]:
                    q[bound] = float(f["attrs"][bound])
            if f["options"]:
                q["options"] = _options(f["options"])
            if f["placeholder"]:
                q["placeholder"] = {"de": f["placeholder"]}
            if f["why"]:
                q["why"] = {"de": f["why"]}
            questions.append(q)
        if s["repeat"]:
            spec = next(r for r in repeats_const if r["key"] == s["repeat"])
            order += 1
            sub = []
            for j, fd in enumerate(spec["fields"], start=1):
                if fd["kind"] not in ("choice", "text", "number"):
                    raise IntakeError(f"intake.html: repeat field {fd['key']!r} has kind {fd['kind']!r}")
                if fd["kind"] == "choice" and not fd["options"]:
                    raise IntakeError(f"intake.html: repeat choice {fd['key']!r} has no options")
                item: dict[str, Any] = {"key": fd["key"], "order": j, "type": fd["kind"], "required": False,
                                        "question": {"de": fd["label"]}}
                if fd.get("unit"):
                    item["unit"] = fd["unit"]
                if fd.get("options"):
                    item["options"] = _options(fd["options"])
                sub.append(item)
            q = {"key": spec["key"], "order": order, "section": s["number"], "type": "repeat", "required": False,
                 "question": {"de": s["title"]}, "item_label": {"de": spec["label"]}, "fields": sub}
            if s["lede"]:
                q["why"] = {"de": s["lede"]}
            questions.append(q)

    return {
        "version": m.group(1),
        "source": "Prototype/client/intake.html (FIELDS, REPEATS and the HTML labels, why-texts, units, options)",
        "language": "de",
        "sections": sections,
        "questions": questions,
    }
