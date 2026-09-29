"""Give the four anonymous submissions a name, in the file's own provenance block. Idempotent.

    python tools/name_archived_submissions.py

**This script is in git and the files it edits are not.**  is ignored — those are
real people's answers about their own money and they do not belong in a repository. So the names would
be lost on a fresh clone, and this file is how they come back: run it once and the four archived
submissions carry their labels again. The registry below is the record.

**Why here and not in the loader.** A name invented at load time is a name nobody can find afterwards: it
would live in one function, differ between runs of different versions, and appear in the database with
nothing beside it saying where it came from. `meta` is where these files already record `source` and
`collected`, so it is where a label belongs — it travels with the data, it is visible to anyone who opens
the file, and it says in the file itself that the name is not the person's.

**The names are regionally plausible and nothing more.** The submissions state a canton and no name and no
gender; German formal address is genderless, so nothing downstream needs to know. The surnames are ordinary
for the canton the member stated. That is the whole of the intention: a label a person can say out loud
instead of `2026-08-06 (2)`.

Two of the five files are byte-identical. The duplicate is marked as one rather than given a second name,
because two names for one person is exactly the confusion this is meant to prevent.
"""
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
#: Both directories. The four named files were moved into `client/submissions/` on 4 September when
#: A8 was reversed and they became ordinary members (A141); the byte-identical duplicate stayed
#: behind. Scanning only the archive left this script finding one orphan it could not group and
#: reporting a skip that read like a failure.
DIRECTORIES = (ROOT / "client/submissions", ROOT / "client/submissions/archive")

NOTE = (
    "Invented on 4 September 2026 to give an anonymous submission a label. THIS IS NOT THE NAME OF THE "
    "PERSON WHO ANSWERED — the submission was collected without one. It carries no claim about them "
    "beyond the canton they stated, and it exists so a record can be referred to as a person rather than "
    "as a filename. Six of this build's members are real people under their own names; these four are "
    "not, and this field is the only thing that says so."
)

PSEUDONYMS = {
    # file stem                          first     surname       why this surname
    "eigentlich-onboarding-2026-08-05":   ("Ueli",   "Wyss",     "ordinary in Bern, the canton stated"),
    "eigentlich-onboarding-2026-08-06 (1)": ("Sandra", "Iten",   "ordinary in Zug, the canton stated"),
    "eigentlich-onboarding-2026-08-06 (2)": ("Nadine", "Chassot", "ordinary in Freiburg, the canton stated"),
    "eigentlich-onboarding-2026-08-18":   ("Reto",   "Kälin",    "ordinary in Schwyz, the canton stated"),
}

def _content_digest(path: Path) -> str:
    """A digest of the ANSWERS, not of the file.

    Hashing the bytes worked exactly once. The first run writes `pseudonym` into one copy and
    `duplicate_of` into the other, after which the two files differ and the second run no longer sees
    them as the same submission — so it re-labelled the keeper and silently skipped the duplicate. The
    digest therefore covers what the member actually answered and ignores `meta`, which is where this
    script writes.
    """
    document = json.loads(io.open(path, encoding="utf-8").read())
    answers = {key: value for key, value in document.items() if key != "meta"}
    return hashlib.sha256(
        json.dumps(answers, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


digests = {}
#: Only the files this registry knows a name for, and their duplicates. The six real members under
#: their own names live in the same directory and are not touched.
candidates = sorted(
    path
    for directory in DIRECTORIES
    for path in directory.glob("*.json")
    if path.stem in PSEUDONYMS or "duplicate_of" in io.open(path, encoding="utf-8").read()
       or any(path.stem.startswith(known[:24]) for known in PSEUDONYMS)
)
for path in candidates:
    digests.setdefault(_content_digest(path), []).append(path)

for digest, paths in digests.items():
    # The keeper is the copy this registry knows a name for, not whichever sorted first — `(3)` sorts
    # ahead of the plain filename and would otherwise take the group with it.
    keeper = next((one for one in paths if one.stem in PSEUDONYMS), paths[0])
    stem = keeper.stem
    entry = PSEUDONYMS.get(stem)
    if entry is None:
        print(f"  {keeper.name}: no pseudonym registered, skipped")
        continue
    first, surname, why = entry

    for path in paths:
        document = json.loads(io.open(path, encoding="utf-8").read())
        meta = document.setdefault("meta", {})
        if path is keeper:
            meta["pseudonym"] = f"{first} {surname}"
            meta["pseudonym_display"] = f"{first} {surname[0]}."
            meta["pseudonym_note"] = NOTE
            meta["pseudonym_surname_why"] = why
            meta["pseudonym_assigned_on"] = "2026-09-04"
        else:
            meta["duplicate_of"] = keeper.name
            meta["duplicate_note"] = (
                f"Byte-identical to {keeper.name} (sha256 matches). The same submission saved twice, not "
                f"a second person. Deliberately NOT given a pseudonym of its own: two names for one "
                f"person is the confusion the pseudonyms exist to prevent."
            )
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )
        mark = "named" if path is keeper else "marked duplicate"
        print(f"  {path.name:42} {mark}"
              + (f" -> {first} {surname[0]}." if path is keeper else ""))
