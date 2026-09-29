"""What now reaches a member that C-01 would have refused. A169's appendix, and T2.7's measurement.

**The question this answers.** `tools/measure_c01.py` measured the gate against the probes written to
attack it — 223 of them, and it caught 176. Probes are the adversary's questions. This runs the
questions **real people actually asked**: the `main_question` from every real submission in
`client/submissions/`, and the 78 onboarding questions of `onb@0.1.3` extracted in A23.

That is the difference between "what could the gate catch" and "what was it doing to the people using
it", and only the second one tells you whether the trade was worth making.

**It reconstructs C-01 from git rather than depending on it.** The module is deleted; importing it is not
an option, and re-implementing it from memory would measure a reconstruction rather than the thing. So
the classifier is loaded out of the commit before the deletion, by `git show`, into a module that is
never installed. If that commit is unreachable the tool says so and refuses to guess — a measurement
nobody can reproduce is worse than no measurement.

Run:

    python tools/measure_cull.py > reports/cull-measurement.txt
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n")

#: The last commit that still had C-01. Its parent is the deletion, so this is the tree to read from.
BEFORE_THE_DELETION = "a734b70^"
#: The path as it stood IN THAT COMMIT, which is not the path anything has today: the package was
#: `andersch` until 21 September 2026 and the directory was `andersCH-prototype2` until the same day.
#: A global rename walked through this line and pointed it at a file the old tree does not contain,
#: and the tool refused rather than guessing — which is the behaviour the docstring asks for. It is a
#: git revision argument, not a path on disk, so it must keep the old spelling.
BOUNDARY_PATH = "andersCH-prototype2/backend/andersch/boundary.py"


def load_the_deleted_boundary() -> types.ModuleType:
    """`boundary.py` as it stood the moment before it was deleted, as an importable module."""
    result = subprocess.run(
        ["git", "show", f"{BEFORE_THE_DELETION}:{BOUNDARY_PATH}"],
        cwd=str(REPO),
        capture_output=True,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"cannot read {BOUNDARY_PATH} at {BEFORE_THE_DELETION}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}\n"
            f"This tool measures the deleted gate against the questions people asked. Without the "
            f"original module it would be measuring a reconstruction, which answers a different "
            f"question. Fix the revision rather than approximating it."
        )
    module = types.ModuleType("c01_as_deleted")
    # Registered before exec because `@dataclass` resolves `cls.__module__` through `sys.modules`, and a
    # module that is not there yet makes `Verdict` fail to build.
    sys.modules["c01_as_deleted"] = module
    exec(compile(result.stdout.decode("utf-8"), "boundary.py@deleted", "exec"), module.__dict__)
    return module


def member_questions() -> list[tuple[str, str]]:
    """Every real submission's `main_question`. These are the six A135 and A139 measure against."""
    out = []
    for path in sorted((ROOT / "client" / "submissions").glob("eigentlich-onboarding-*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        raw = document.get("raw") or document
        question = raw.get("main_question") or document.get("main_question")
        if isinstance(question, str) and question.strip():
            out.append((path.stem.replace("eigentlich-onboarding-", ""), question.strip()))
    return out


def intake_questions() -> list[tuple[str, str]]:
    """A23's 78, extracted from `onb@0.1.3` before any rewriting."""
    path = ROOT / "client" / "reference" / "questions-onb-0.1.3.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for entry in document.get("questions", []):
        if isinstance(entry, str):
            out.append(("", entry))
            continue
        key = entry.get("key") or entry.get("id") or ""
        for field in ("question", "text", "label", "prompt", "de"):
            value = entry.get(field)
            if isinstance(value, str) and value.strip():
                out.append((str(key), value.strip()))
                break
            if isinstance(value, dict) and isinstance(value.get("de"), str):
                out.append((str(key), value["de"].strip()))
                break
    return out


def main() -> int:
    c01 = load_the_deleted_boundary()

    print("What the cull let through")
    print("=" * 78)
    print()
    print("Every question below is asked by the product today and answered. Each one was run through")
    print("C-01's inbound gate as it stood immediately before deletion, to say which of them the gate")
    print("would have refused. 20 September 2026.")
    print()

    for title, rows in (
        ("THE REAL MEMBERS' OWN QUESTIONS", member_questions()),
        ("THE 78 INTAKE QUESTIONS (A23, onb@0.1.3)", intake_questions()),
    ):
        refused = []
        for who, question in rows:
            verdict = c01.classify_question(question)
            if verdict.requires_curator:
                refused.append((who, question, verdict.reason))

        print(title)
        print("-" * 78)
        print(f"  asked           {len(rows):>4}")
        print(f"  C-01 refused    {len(refused):>4}")
        print(f"  now answered    {len(refused):>4}   <- what the cull bought here")
        print()
        for who, question, reason in refused:
            label = f"{who}: " if who else ""
            print(f"    [{reason}]")
            print(f"      {label}{question}")
        print()

    print("HOW TO READ THIS")
    print("-" * 78)
    print("  A refusal was not a wrong answer. It was the product declining to answer, and offering a")
    print("  curator instead. Every line above is a question a member asked that the product now")
    print("  answers from the corpus, with C-11 holding every sentence to a retrieved passage.")
    print()
    print("  A count of zero is also a result, and the honest one to report: it would mean C-01 was")
    print("  refusing the adversary's probes and almost nothing that the people using the product")
    print("  actually typed — which is worth knowing about a layer that cost 1,340 lines to maintain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
