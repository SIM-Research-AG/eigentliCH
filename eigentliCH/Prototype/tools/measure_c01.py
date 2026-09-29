"""Run every C-01 probe through the gate and record the verdict. A164's appendix.

**Why this exists for exactly one day.** C-01 is being deleted. The probe corpus in
`tests/test_boundary_c01.py` is the only measurement anyone has of what the gate was actually catching,
and once `boundary.py`'s pattern half is gone the question "what did we stop doing" has no answer at all
— the corpus asserts *that* each probe is refused, never records *which rule* refused it or how many
probes there were. T2.2 of the cull task asks for that record before the deletion, not after.

It is deliberately not a test. It asserts nothing and cannot fail; it reports. A test that measured this
would have to be deleted with everything else it depends on, and the number would go with it.

Run before the deletion:

    python tools/measure_c01.py > reports/c01-final-measurement.txt

The output is copied into A164 as an appendix. After the deletion, `tools/measure_cull.py` runs the same
member and intake questions through the Know surface and records what now comes back (T2.7).
"""

from __future__ import annotations

import io
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend" / "tests"))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")

from eigentlich.boundary import (  # noqa: E402
    SUPPORTED_LANGUAGES,
    asks_about_the_member,
    check_answer,
    classify_question,
    refusal_text,
    states_statutory_duty,
)

import test_boundary_c01 as corpus  # noqa: E402

#: Every named corpus in the probe suite, and which direction it is scanned in. Outbound corpora are
#: model output the gate must refuse or pass; inbound corpora are member questions.
OUTBOUND = (
    "AUDITED_ESCAPES",
    "UNAUDITED_REGISTERS_DE_EN",
    "UNAUDITED_REGISTERS_FR_IT",
    "DU_REGISTER",
    "VERB_FRONTED",
    "SUITABILITY_VERDICTS",
    "INTERROGATIVE_ADVICE",
    "CLOSED_FROM_THE_HONESTY_LIST",
    "ADVICE_WEARING_DUTY",
    "DETACHED_ADVICE",
)
OUTBOUND_MUST_PASS = ("EDUCATION_ANSWERS", "STATUTORY_DUTY")
INBOUND = (
    "ADVICE_QUESTIONS_FR",
    "ADVICE_QUESTIONS_IT",
    "ADVICE_QUESTIONS_DU",
    "RANKING_REQUESTS",
)
INBOUND_MUST_PASS = ("EDUCATION_QUESTIONS_FR", "EDUCATION_QUESTIONS_IT", "SUBSTRING_TRAPS")


def _items(name: str) -> list:
    raw = getattr(corpus, name, None)
    if raw is None:
        return []
    out = []
    for entry in raw:
        # Some corpora are bare strings, some are (text, note) or (text, expected_reason) pairs.
        out.append(entry[0] if isinstance(entry, (tuple, list)) else entry)
    return [x for x in out if isinstance(x, str)]


def main() -> int:
    print("C-01 — final measurement before deletion")
    print("=" * 78)
    print()
    print("Every probe in tests/test_boundary_c01.py, run through the gate it was written for,")
    print("with the rule that fired. Taken 20 September 2026, immediately before C-01 was removed.")
    print()

    grand = Counter()
    reasons = Counter()

    print("OUTBOUND — model output the gate refuses")
    print("-" * 78)
    for name in OUTBOUND:
        items = _items(name)
        if not items:
            continue
        caught = 0
        for text in items:
            verdict = check_answer(text)
            if verdict.requires_curator:
                caught += 1
                reasons[verdict.reason] += 1
        grand["outbound_probes"] += len(items)
        grand["outbound_caught"] += caught
        print(f"  {name:<34}{caught:>4} / {len(items):<4} refused")

    print()
    print("OUTBOUND — education and statements of duty the gate must NOT refuse")
    print("-" * 78)
    for name in OUTBOUND_MUST_PASS:
        items = _items(name)
        if not items:
            continue
        passed = sum(1 for t in items if not check_answer(t).requires_curator)
        grand["outbound_allowed_probes"] += len(items)
        grand["outbound_allowed_ok"] += passed
        print(f"  {name:<34}{passed:>4} / {len(items):<4} allowed through")

    print()
    print("INBOUND — member questions the gate refuses to answer")
    print("-" * 78)
    for name in INBOUND:
        items = _items(name)
        if not items:
            continue
        caught = 0
        for text in items:
            verdict = classify_question(text)
            if verdict.requires_curator:
                caught += 1
                reasons[verdict.reason] += 1
        grand["inbound_probes"] += len(items)
        grand["inbound_caught"] += caught
        print(f"  {name:<34}{caught:>4} / {len(items):<4} refused")

    print()
    print("INBOUND — questions and substring traps the gate must NOT refuse")
    print("-" * 78)
    for name in INBOUND_MUST_PASS:
        items = _items(name)
        if not items:
            continue
        passed = sum(1 for t in items if not classify_question(t).requires_curator)
        grand["inbound_allowed_probes"] += len(items)
        grand["inbound_allowed_ok"] += passed
        print(f"  {name:<34}{passed:>4} / {len(items):<4} allowed through")

    print()
    print("WHICH RULE FIRED, across every refused probe")
    print("-" * 78)
    for reason, count in reasons.most_common():
        print(f"  {str(reason):<44}{count:>5}")

    print()
    print("THE REFUSAL TEXTS, which go with the patterns")
    print("-" * 78)
    for reason in corpus.REASONS:
        for language in SUPPORTED_LANGUAGES:
            body = refusal_text(reason, language)
            print(f"  {reason:<34}{language}  {body[:90]}")
        print()

    print("THE MEMBER-QUESTION SCAN, which is NOT being deleted")
    print("-" * 78)
    print("  `asks_about_the_member` governs whether the vault may be read. T2.3 keeps it: it is a")
    print("  data-protection rule, not a compliance one. Sampled here so the record shows it separately.")
    for probe in ("Wie viel habe ich gespart?", "Wie viele Menschen in der Schweiz sparen?"):
        print(f"    {probe:<46}{asks_about_the_member(probe)}")

    print()
    print("TOTALS")
    print("-" * 78)
    print(f"  outbound probes                         {grand['outbound_probes']:>5}")
    print(f"    refused                               {grand['outbound_caught']:>5}")
    print(f"  outbound probes that must pass          {grand['outbound_allowed_probes']:>5}")
    print(f"    allowed                               {grand['outbound_allowed_ok']:>5}")
    print(f"  inbound probes                          {grand['inbound_probes']:>5}")
    print(f"    refused                               {grand['inbound_caught']:>5}")
    print(f"  inbound probes that must pass           {grand['inbound_allowed_probes']:>5}")
    print(f"    allowed                               {grand['inbound_allowed_ok']:>5}")
    total = (
        grand["outbound_probes"]
        + grand["outbound_allowed_probes"]
        + grand["inbound_probes"]
        + grand["inbound_allowed_probes"]
    )
    print(f"  ------------------------------------------------")
    print(f"  probes in the corpus                    {total:>5}")
    print()
    print("After the deletion, every number in the 'refused' rows becomes zero: the text is returned")
    print("unexamined. That is the measurement, and it is the thing the trade was made to buy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
