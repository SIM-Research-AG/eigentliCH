"""Extract the 78 onboarding questions from `onboarding-chat.html` into a reference file.

    python tools/extract_reference_questions.py

**Why this exists.** A13 rewrites the onboarding questions against `Position` and `Goal` rather than
mapping the existing ones. The existing wording was refined across five schema versions and three real
interviews, and each question carries a `why:` line explaining to a member what the answer is for. That is
the expensive part and it should be readable during the rewrite even where it is not reused.

**Extraction is not adoption.** Nothing loads this file at runtime. It is `client/reference/`, not
`client/content/`, and the distinction is the point: content is what the product says, reference is what
the product's authors can consult.

**Verbatim, and how that is guaranteed.** Each question is stored with its `raw` JavaScript source
alongside the parsed fields. Parsing a JS object literal with regular expressions is unreliable at the
edges — nested braces in an `onlyIf` arrow function, apostrophes inside German strings — so the raw text is
the record and the parsed fields are the convenience. If the two ever disagree, the raw text is right.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent.parent / "andersCH-prototype" / "onboarding-chat.html"
OUT = HERE.parent / "client" / "reference" / "questions-onb-0.1.3.json"


def _find_array(src: str, marker: str = "const Q = [") -> str:
    """The Q array's source, by brace matching rather than by a greedy regex."""
    start = src.index(marker) + len(marker) - 1
    depth = 0
    in_string: str | None = None
    escaped = False
    for i in range(start, len(src)):
        ch = src[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in "\"'`":
            in_string = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise ValueError("unterminated Q array")


def _split_objects(array_src: str) -> list[str]:
    """Top-level `{...}` literals inside the array, string- and nesting-aware."""
    objects: list[str] = []
    depth = 0
    in_string: str | None = None
    escaped = False
    begin = None
    for i, ch in enumerate(array_src):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in "\"'`":
            in_string = ch
            continue
        if ch == "{":
            if depth == 0:
                begin = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and begin is not None:
                objects.append(array_src[begin : i + 1])
                begin = None
    return objects


def _string_field(obj: str, key: str) -> str | None:
    match = re.search(rf"\b{key}\s*:\s*(\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)')", obj)
    if not match:
        return None
    raw = match.group(2) if match.group(2) is not None else match.group(3)
    return raw.replace("\\'", "'").replace('\\"', '"')


def _number_field(obj: str, key: str) -> float | int | None:
    match = re.search(rf"\b{key}\s*:\s*(-?\d+(?:\.\d+)?)", obj)
    if not match:
        return None
    text = match.group(1)
    return float(text) if "." in text else int(text)


def _opts(obj: str) -> list[str] | None:
    match = re.search(r"\bopts\s*:\s*\[", obj)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    in_string: str | None = None
    for i in range(start, len(obj)):
        ch = obj[i]
        if in_string:
            if ch == in_string:
                in_string = None
            continue
        if ch in "\"'":
            in_string = ch
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                body = obj[start + 1 : i]
                return [m.group(1) or m.group(2) for m in re.finditer(r'"([^"]*)"|\'([^\']*)\'', body)]
    return None


def main() -> int:
    if not SOURCE.exists():
        print(f"source not found: {SOURCE}", file=sys.stderr)
        return 1

    src = SOURCE.read_text(encoding="utf-8")
    schema_version = _string_field(src, "schema_version") or "unknown"
    objects = _split_objects(_find_array(src))

    questions = []
    for index, obj in enumerate(objects):
        key = _string_field(obj, "k")
        if not key:
            continue
        questions.append(
            {
                "order": index,
                "key": key,
                "section": _string_field(obj, "s"),
                "group": _string_field(obj, "g"),
                "label": _string_field(obj, "l"),
                "type": _string_field(obj, "t"),
                "question_de": _string_field(obj, "q"),
                "why_de": _string_field(obj, "why"),
                "unit": _string_field(obj, "unit"),
                "min": _number_field(obj, "min"),
                "max": _number_field(obj, "max"),
                "options_de": _opts(obj),
                "core": bool(re.search(r"\bcore\s*:\s*1", obj)),
                "required": bool(re.search(r"\breq\s*:\s*1", obj)),
                "optional": bool(re.search(r"\bopt\s*:\s*1", obj)),
                "conditional": bool(re.search(r"\bonlyIf\s*:", obj)),
                "depends_on": _string_field(obj, "dep"),
                "raw": obj,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_about": {
                    "purpose": "Reference only. Nothing loads this at runtime — see A13 in DECISIONS.md.",
                    "extracted_from": str(SOURCE.relative_to(SOURCE.parents[2])),
                    "extracted_on": "2026-08-30",
                    "schema_version": schema_version,
                    "regenerate": "python tools/extract_reference_questions.py",
                    "verbatim": "Each entry keeps its original JavaScript source in `raw`. Where `raw` and "
                    "the parsed fields disagree, `raw` is authoritative.",
                    "language": "German, as authored. No translation has been applied.",
                },
                "count": len(questions),
                "questions": questions,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"extracted {len(questions)} questions at {schema_version} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
