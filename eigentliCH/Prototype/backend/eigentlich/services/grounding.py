"""The impersonal ground The Know may answer from: the book corpus, and approved authored content.

`know.py` retrieves the member's own material. This module retrieves everything that is *not* theirs —
the five-source `bge-m3` index the estate already built (A34), and the German explainers a human has
reviewed and marked approved. Both are K0. Neither knows a member exists, and neither is passed one.

**Why this exists at all.** A34 recorded the book corpus as deliberately unwired, and the consequence was
that `retrieve()` searched a member's vault and the learning units, of which there are zero rows in the
database — so every educational question returned "Dazu finde ich … nichts" in four milliseconds without
ever reaching a model. The refusal was honest and it was also total.

**The score is two numbers and a rule, not a number.** A single blended similarity tells a caller a
passage won without telling it why, and the estate reached the same conclusion for its branch matcher and
for `know.retrieve`. So every result carries its `semantic` and its `lexical` component separately, the
terms that matched, and the gate that let it through. Everything is in **per mille as an integer**: an
exact sort key that cannot drift, and — since C-02's structural test forbids a float literal in this
layer, and it is right to — a threshold that is written down as the integer it is compared against.

**The relevance floor is conjunctive, and that is the measurement talking.** Calibrated on 95 member-shaped
probes run against the real index — 40 the corpus can genuinely answer, 55 it cannot — in two rounds, the
second of them held out and scored only after the floors had been fixed from the first:

    semantic alone,  ≥ 0.540                    37/40 kept    7/55 FALSE POSITIVES
    semantic alone,  ≥ 0.600 (tight enough
                     to admit none of the 55)   17/40 kept    0/55
    lexical alone,   ≥ 0.700                    16/40 kept    0/55
    both, sem ≥ 0.540 AND lex ≥ 0.100           31/40 kept    0/55

**Neither channel separates on its own; together they do.** The best either manages while admitting nothing
it should refuse is 17 of 40; the conjunction keeps 31.

The semantic channel cannot separate alone because **a multilingual embedding scores any German sentence
against a corpus that is 91 % English on language and register rather than on topic**: "Was kostet eine
Kinderkrippe in Zürich?" reaches 0.576 against the Methodik manual and "Wie funktioniert die
Pensionskasse?" reaches 0.586 against the book — both above every threshold that would still admit a real
question. What those two have in common is that the corpus contains **none of their words**: their lexical
score is exactly 0.000. Requiring a tenth of the question's own discriminative weight to be present in the
passage removes them and 19 others outright, whatever the similarity says. Below 0.100 nothing changes and
above 0.200 real questions start falling out, so 0.100 is the flat middle of a plateau rather than a knee —
what the lexical channel is really asserting is *presence*, that the corpus contains at least one of the
words the question was asked in.

The semantic floor is the midpoint of the observed bounds, which is the estate's own rule in
`desktop/coach.py`, rounded toward refusing. Among probes clearing the lexical requirement, the highest
score the corpus cannot answer is **0.537** ("Was ist die Amortisation einer Hypothek?" and "How do I apply
for a mortgage?", both landing on the Methodik manual) and the lowest it can and still keeps is **0.542**
("Was ist entnehmbares Vermögen?"). `SEMANTIC_FLOOR` is 0.540, between them.

**Five per mille is a thin separation and calling it a guarantee would be an overclaim.** Both boundary
probes came from the held-out round, which is to say the first round's numbers were optimistic and a third
round would probably find something at 0.541. This is a filter, and it is the first of three: the model is
then instructed to answer from the passages or say it cannot, and `boundary.check_answer` runs over what it
produced. `tests/test_grounding.py` pins both boundary probes, so moving either floor has to face them.

**The gate decides whether to answer, and cannot decide which passage is right.** "Was ist eine
Beitragslücke bei der AHV?" clears it at 0.568 and lands on the Methodik manual, which has nothing to say
about contribution gaps — the corpus has no passage on the subject and the gate has no way to know that.
That is what the two layers beneath it are for, and it is why every `Ground` carries its own numbers: a
citation a member can open is a citation a member can find empty.

**What this still cannot do, stated rather than tuned away.** Of the 1 280 passages, 1 160 are the English
*Capital Saturation* manuscript, and by a common-word count only **14 are written in German at all** — the
eleven AHV passages and three German bibliography entries. The AHV Merkblätter are the sole Swiss
regulatory ground in the whole corpus. So German questions about pillar 3a, ETFs, the Pensionskasse or
Vorsorge return nothing, correctly, and German questions about concepts the book *does* cover —
Kapitalsättigung, Humankapital, Lebensbilanz — also return nothing, because the German compound shares no
token with the English text and the similarity alone is not allowed to carry a passage. Lowering the floor
until something always comes back would buy a confidently wrong citation, which is worse than a refusal.

The gap that would close most of that is a second query: `desktop/bookindex.search_multi` translates the
question and keeps each passage's best score, which lifts "Was bedeutet Kapitalsättigung?" from 0.536 to
0.648. It costs a model call inside retrieval and was not taken here.
`tests/test_grounding.py::test_the_german_compounds_the_corpus_cannot_reach_are_recorded_as_open`
asserts the hole is open and instructs its own deletion on the day it closes.

**Nothing here logs, and nothing here writes.** The question is a member's own words: it is never logged,
never persisted, and never sent anywhere but the loopback embedding endpoint. The index is opened
read-only and lives in the estate, which §9 puts out of scope for writing.
"""

from __future__ import annotations

import array
import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from .. import llm

# --------------------------------------------------------------------------- where things live

#: `backend/eigentlich/services/grounding.py` → prototype2 → the estate.
_PROTOTYPE_ROOT = Path(__file__).resolve().parents[3]
_ESTATE_ROOT = _PROTOTYPE_ROOT.parent

#: The index the estate already built (A34). **Read, never written**: §9 puts the estate out of scope for
#: this build, and a retrieval index that a member's application can modify is a retrieval index a member's
#: application can poison.
DEFAULT_INDEX_DIR = _ESTATE_ROOT / "desktop" / "bookindex"

#: German member-facing explainers, drafted here and gated on a human's approval. May not exist.
DEFAULT_KNOWLEDGE_DIR = _PROTOTYPE_ROOT / "content" / "knowledge"

#: Scores are integers in per mille. See the module docstring: an exact sort key, and a threshold that is
#: written as the integer it is compared against rather than as a float this layer may not contain.
#:
#: **Truncated, never rounded.** A number a floor is applied to should err toward refusing, so a perfect
#: lexical match scores 999 rather than 1000 and a cosine of 0.5399 scores 539 rather than 540. Rounding
#: would let a passage over the floor on the last bit of a float32.
PER_MILLE = 1000

#: The two floors, from the calibration in the module docstring. **Both must be cleared.** 0.540 is the
#: midpoint of the observed bounds (0.537 the highest unanswerable, 0.542 the lowest answerable kept);
#: 0.100 is the flat middle of the lexical plateau, and what it really requires is that the corpus contain
#: at least one of the words the question was asked in.
SEMANTIC_FLOOR = 540
LEXICAL_FLOOR = 100

#: The floor when there is no embedding model and only the lexical channel exists. Measured on the same 95
#: probes: word overlap alone keeps 16 of the 40 answerable at 0.700 and admits none of the 55 it should
#: refuse, where 0.600 admits one. It is deliberately punishing — a corpus searched by word overlap alone
#: cannot answer a German question about an English book at all, and should say so rather than guess.
LEXICAL_ONLY_FLOOR = 700

#: The floor an AUTHORED entry clears while an answer is being composed. Measured on the fifty real
#: questions of 20 September 2026.
#:
#: **`LEXICAL_ONLY_FLOOR` is the wrong floor for these, and it was calibrated against a different
#: corpus.** Its own note above says what it is for: word overlap alone "cannot answer a German question
#: about an English book at all, and should say so rather than guess." The authored entries are not an
#: English book. They are German, they are reviewed, there are tens of them rather than thousands, and
#: each one carries a section naming in the member's own words the questions it answers — so a weak
#: overlap against one of them means something quite different from a weak overlap against a translated
#: index.
#:
#: What the wrong floor cost: of the fifty questions, **two** reached an authored entry at 700. The best
#: score per question clusters between 400 and 700, so the reviewed material written for exactly these
#: people sat below the line while book passages about capital saturation came back in its place. At 400
#: it is sixteen of fifty; 300 admits enough that the noise is visible by hand.
#:
#: Composing only. Quoting is unchanged, because there a passage that comes back IS the answer put in
#: front of the member, and 700 is the number that was calibrated for that.
COMPOSE_ENTRY_FLOOR = 400

#: A long term is more specific than a short one — `nichterwerbstatige` says more than `jahr` — so length
#: lifts a term's weight by up to about a quarter. Twelve is `desktop/bookindex.py`'s own divisor, kept so
#: the two lexical stages in this house rank the same words the same way rather than nearly the same way.
_TERM_LENGTH_SCALE = 12

#: How the two channels are weighted for *ranking* (not for the gate, which is conjunctive). The semantic
#: channel leads because it is the one that crosses languages; the lexical one breaks its ties. Integers
#: out of 100, so the blend stays exact.
SEMANTIC_WEIGHT = 80
LEXICAL_WEIGHT = 100 - SEMANTIC_WEIGHT

#: Longest question accepted. Beyond this the term set stops discriminating and the embedding is a summary
#: of a paragraph rather than of a question.
MAX_QUESTION_CHARS = 1000

#: Approved authored content is cited from its own `sources:` list, which R-171 requires. An entry without
#: one is not retrievable — see `_entry_from_text`.
REQUIRED_FRONTMATTER = ("approved", "sources")


class CorpusNotLocal(llm.NotLocal):
    """The index was pointed somewhere that is not a file on this machine.

    C-05's rule, one layer over from the model host: the corpus is data this installation controls, and a
    path that reaches a server is a path by which somebody else decides what the member is told. Refused
    by code rather than validated by configuration, and never caught and worked around.

    **What this cannot see**: a mapped drive letter or a bind mount that resolves to a remote filesystem
    looks exactly like a local path to `pathlib`. The check is on what was written, as `llm._assert_local`
    is, and the honest statement is that it stops a URL and a UNC path and nothing subtler.
    """


# --------------------------------------------------------------------------- tokens

#: ASCII-folded, because the index's postings are: the key is `saule`, not `säule`. Digits kept — `2` in
#: "Säule 3a" and "AHV 2.03" carry as much as any word does.
_WORD = re.compile(r"[a-z0-9]+")

#: Shortest token the index kept when it was built (`len(t) > 2` in `desktop/bookindex.py`). Matching that
#: exactly matters: a two-letter query term can never match anything, so counting it in the denominator
#: would penalise the question for a word the corpus was never given the chance to carry.
MIN_TERM_CHARS = 3

#: Words too common in a German or English question to discriminate on. Written ASCII-folded, because that
#: is the form `_terms` produces. Longer than `know.py`'s list because that one filters a member's own
#: documents, where a rare word is rare in a dozen items; this one filters against 1 280 passages, where an
#: ordinary auxiliary matches hundreds and drags the denominator down without ever separating anything.
_STOP = frozenset("""
und der die das den dem des ein eine einen einem eines fur von vom mit ist sind war waren wie was wer wo
wann warum bei aus auf meine mein meinem meiner meines ich sie ihr ihre ihrem ihren man wird werden wurde
kann konnen muss mussen soll sollen sollte hat haben habe dass wenn oder aber auch noch nur nicht sich
als zum zur uber nach vor unter damit dann denn doch schon sehr viel mehr weniger etwas jemand welche
welcher welches gibt geben bin bist seid sein eigenen eigene diese dieser dieses jede jeder jedes
the and for with what how why does are were mine this that from have has had can could should would
you your yours will shall about into out much many any some there their they them his her its
who whom which when where such than then been being not but all one two
""".split())


def _fold(text: str) -> str:
    """Lowercase and strip accents, exactly as `desktop/bookindex.py` did when it wrote the postings."""
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _terms(text: str) -> list[str]:
    """The question's content terms, in order, deduplicated. A list rather than a set so it is reportable."""
    seen = dict.fromkeys(
        t for t in _WORD.findall(_fold(text)) if len(t) >= MIN_TERM_CHARS and t not in _STOP
    )
    return list(seen)


# --------------------------------------------------------------------------- the index on disk


@dataclass(frozen=True)
class BookIndex:
    """`desktop/bookindex/` as loaded. Immutable, and opened read-only."""

    passages: tuple[dict, ...]
    postings: dict[str, list[int]]
    dim: int
    model: str
    vectors: array.array | None

    def vector(self, i: int) -> array.array:
        return self.vectors[i * self.dim:(i + 1) * self.dim]


@dataclass(frozen=True)
class Loaded:
    """An index, or the reason there is not one. Never an exception at the call site: a friend who
    installed the distribution ZIP without the corpus gets today's behaviour and a sentence saying why."""

    index: BookIndex | None
    reason: str | None


def index_dir() -> Path:
    """Where the corpus is, resolved at call time so it is overridable in a test and not at import."""
    return _assert_local_path(os.environ.get("ANDERSCH_BOOKINDEX_DIR") or str(DEFAULT_INDEX_DIR))


def knowledge_dir() -> Path:
    return _assert_local_path(os.environ.get("ANDERSCH_KNOWLEDGE_DIR") or str(DEFAULT_KNOWLEDGE_DIR))


def _assert_local_path(raw: str) -> Path:
    """C-05 for the corpus. A URL or a UNC path raises; there is no configuration that permits it."""
    scheme = urlparse(raw.replace("\\", "/")).scheme
    # A Windows drive letter parses as a one-character scheme. `file:` is a local path spelled oddly.
    if len(scheme) > 1 and scheme != "file":
        raise CorpusNotLocal(
            f"refusing a non-local corpus location {raw!r}: {scheme!r} is a network scheme. The index is a "
            f"file on this machine, and whoever serves it decides what a member is told."
        )
    if raw.startswith("\\\\") or raw.startswith("//"):
        raise CorpusNotLocal(
            f"refusing a non-local corpus location {raw!r}: a UNC path is another machine's filesystem."
        )
    return Path(raw)


@lru_cache(maxsize=4)
def _load_index(path: str) -> Loaded:
    """Read `meta.json` and `vecs.bin`, or say why not. Cached: 5 MB of vectors per process, not per query.

    **Every failure here degrades rather than raises.** The distribution ZIP may ship without the corpus,
    and a half-written index is not distinguishable from a missing one to a member — both mean the same
    thing, which is that there is nothing impersonal to ground on.
    """
    directory = Path(path)
    meta_path, vecs_path = directory / "meta.json", directory / "vecs.bin"
    if not meta_path.exists():
        return Loaded(None, f"no book index at {directory}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as error:
        return Loaded(None, f"the book index at {directory} is unreadable: {error}")
    if not isinstance(meta, dict):
        return Loaded(None, f"the book index at {directory} is not a mapping")

    raw_passages = meta.get("passages")
    if not isinstance(raw_passages, list) or not raw_passages:
        return Loaded(None, f"the book index at {directory} carries no passages")
    passages = tuple(p for p in raw_passages if isinstance(p, dict) and p.get("text"))
    if len(passages) != len(raw_passages):
        return Loaded(None, f"the book index at {directory} carries passages without text")

    postings = meta.get("postings")
    if not isinstance(postings, dict):
        postings = {}

    dim = meta.get("dim") or 0
    model = meta.get("model") or ""
    vectors: array.array | None = None
    if dim and model and vecs_path.exists():
        try:
            vectors = array.array("f")
            vectors.frombytes(vecs_path.read_bytes())
        except (OSError, ValueError) as error:
            return Loaded(None, f"the book index vectors at {directory} are unreadable: {error}")
        if len(vectors) != len(passages) * dim:
            # **The one malformation that must not degrade quietly into "lexical only".** A vector file
            # that is the wrong length is a file whose rows no longer line up with the passages, so every
            # similarity would be computed against the wrong text and would still look like a number.
            return Loaded(
                None,
                f"the book index at {directory} is inconsistent: {len(vectors)} floats for "
                f"{len(passages)} passages of {dim} dimensions. It has to be rebuilt.",
            )
    return Loaded(
        BookIndex(passages=passages, postings=postings, dim=dim, model=model, vectors=vectors), None
    )


# --------------------------------------------------------------------------- authored content


@dataclass(frozen=True)
class KnowledgeEntry:
    """One authored explainer that a human has marked approved, with the sources it cites."""

    entry_id: str
    title: str
    text: str
    sources: tuple[str, ...]
    language: str


#: `key: value` at the start of a line, once the indentation has been measured off it.
_PAIR = re.compile(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$")


def _split_frontmatter(raw: str) -> tuple[dict[str, object], str] | None:
    """The `---`-delimited block at the top of the file, or None if there is not one.

    Deliberately a small parser rather than a YAML dependency: PyYAML is not in this project's declared
    dependencies (it is present only transitively, through uvicorn's extras), and a safety gate that stops
    working when a transitive dependency moves is not a safety gate.

    It reads the three shapes the drafting convention actually uses — `key: value`, `key:` with indented
    `- item` scalars, and `key:` with indented `- label: …` items carrying further indented keys of their
    own. **Anything outside those is recorded as unreadable and the file is not approved.**

    That last rule cuts both ways and both of them matter. A file the parser half-understands must not be
    published on the strength of the half it read — but a gate that refuses everything is a wall, not a
    gate, so `test_the_real_drafts_would_be_readable_if_they_were_approved` reads the actual drafting
    directory and fails if this parser has fallen behind the convention. A silent "nothing is ever
    approved" is the failure this build has paid for four times (A20, A63, A66, A68): a guarantee that
    stopped holding while everything stayed green.
    """
    lines = raw.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None

    data: dict[str, object] = {}
    key: str | None = None
    item: dict[str, str] | None = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line[:1].isspace():                                    # a top-level key
            pair = _PAIR.match(stripped)
            if pair is None:
                data["__unparsed__"] = True
                continue
            key, rest = pair.group(1), _unquote(pair.group(2))
            data[key] = rest if rest else []
            item = None
            continue

        if key is None:                                               # indented, under nothing
            data["__unparsed__"] = True
            continue

        if stripped.startswith("-"):                                  # a list item
            body = _unquote(stripped[1:])
            if not isinstance(data.get(key), list):
                data[key] = []
            pair = _PAIR.match(body)
            if pair is not None:
                item = {pair.group(1): _unquote(pair.group(2))}
                data[key].append(item)                                # type: ignore[union-attr]
            elif body:
                item = None
                data[key].append(body)                                # type: ignore[union-attr]
            else:
                item = None
            continue

        pair = _PAIR.match(stripped)                                  # an indented key
        if pair is None:
            data["__unparsed__"] = True
        elif item is not None:
            item[pair.group(1)] = _unquote(pair.group(2))
        else:
            # An indented key under a top-level key that is not a list. A real shape in YAML, not one this
            # convention uses, and guessing at it is how a gate reads a file it does not understand.
            data["__unparsed__"] = True
    return data, "\n".join(lines[end + 1:])


def _render_source(source: object) -> str:
    """One `sources:` entry as the line a member reads. R-171 is satisfied by this string or by nothing.

    A scalar is itself. A mapping is its `label`, followed by `where` when it carries one — which is how
    the drafts name a legal source and then say where to find it ("BVV 3, Art. 1, 3 und 7 — SR 831.461.3,
    fedlex.admin.ch"). A mapping with neither is rendered from whatever keys it does have rather than
    dropped, because a citation that silently disappears is the one failure R-171 cannot tolerate.
    """
    if isinstance(source, str):
        return source.strip()
    if isinstance(source, dict):
        label = str(source.get("label") or "").strip()
        where = str(source.get("where") or "").strip()
        if label and where:
            return f"{label} — {where}"
        if label or where:
            return label or where
        return " — ".join(f"{k}: {v}" for k, v in source.items() if v)
    return str(source).strip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def is_approved(frontmatter: dict[str, object]) -> bool:
    """**The gate.** True only for a frontmatter that says, in as many words, `approved: true`.

    Fail-closed in every direction, and the directions matter because each of them is a way a draft
    reaches a member:

      * no frontmatter, no `approved` key, an empty value        → not approved
      * `false`, `no`, `pending`, `review`, `TRUE-ish` typos     → not approved
      * a list (`approved:` with items under it)                 → not approved
      * a file the frontmatter parser could not fully read       → not approved

    Only the exact scalar `true`, in any case, passes. There is no second spelling, because every second
    spelling is a way for a draft to be published by a typo.
    """
    if frontmatter.get("__unparsed__"):
        return False
    value = frontmatter.get("approved")
    return isinstance(value, str) and value.strip().lower() == "true"


def _entry_from_text(entry_id: str, raw: str) -> tuple[KnowledgeEntry | None, str]:
    """One file into an entry, or None and the reason it is not retrievable.

    R-171 is the second gate here and it is as hard as the first: an approved entry with no `sources:` is
    an answer a member cannot check, so it is not returned at all. That is stricter than "cite what you
    can", on the same principle as the relevance floor — a claim nobody can trace is worse than a refusal.
    """
    split = _split_frontmatter(raw)
    if split is None:
        return None, "no frontmatter"
    frontmatter, body = split
    if not is_approved(frontmatter):
        return None, "not approved"
    declared = frontmatter.get("sources")
    if isinstance(declared, str) and declared:
        declared = [declared]
    sources = tuple(s for s in (_render_source(x) for x in declared or ()) if s) \
        if isinstance(declared, list) else ()
    if not sources:
        return None, "approved but carries no sources, so R-171 cannot cite it"
    if not body.strip():
        return None, "approved but empty"
    # `title_de` is what the drafting convention writes; `title` is the plain form. Neither is required —
    # a citation falls back to the filename, which is a real place a member can be pointed at.
    title = next(
        (frontmatter[k] for k in ("title", "title_de", "title_en")
         if isinstance(frontmatter.get(k), str) and frontmatter[k]),
        entry_id,
    )
    return (
        KnowledgeEntry(
            entry_id=entry_id,
            title=str(title),
            text=body.strip(),
            sources=sources,
            language=str(frontmatter.get("language") or ""),
        ),
        "",
    )


def approved_entries(directory: Path | None = None) -> tuple[tuple[KnowledgeEntry, ...], dict[str, str]]:
    """Every approved entry, and why each of the others was left out.

    The second half is returned rather than logged, because C-04 and A36 forbid this layer writing a
    retrieved passage anywhere and a skipped draft is still authored text. A caller that wants to know why
    its entry is not appearing asks; nothing writes it down.
    """
    directory = directory if directory is not None else knowledge_dir()
    entries: list[KnowledgeEntry] = []
    skipped: dict[str, str] = {}
    if not directory.is_dir():
        # Absent is "no approved content", which is the same thing as an empty directory. A34's deferral
        # and a friend's distribution ZIP both land here, and neither is an error.
        return (), skipped
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".md", ".markdown"):
            continue
        entry_id = path.relative_to(directory).as_posix()
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            skipped[entry_id] = f"unreadable: {error}"
            continue
        entry, reason = _entry_from_text(entry_id, raw)
        if entry is None:
            skipped[entry_id] = reason
        else:
            entries.append(entry)
    return tuple(entries), skipped


# --------------------------------------------------------------------------- scoring


def _term_weights(terms: list[str], postings: dict[str, list[int]], n_passages: int) -> dict[str, float]:
    """How much of the question each term is worth: rarer is worth more, longer is worth more.

    **Every term counts toward the denominator, including one the corpus has never seen.** That is the
    correction that made the lexical channel a discriminator instead of noise. Normalising over only the
    terms the index happens to know gave a perfect 1.000 to any passage carrying the single in-vocabulary
    word of a question — "Welche Impfungen brauche ich für eine Reise nach Brasilien?" scored 1.000 on a
    passage that shared the word *Reise*. A term the index does not know is weight the passage cannot earn.
    """
    weights: dict[str, float] = {}
    for term in terms:
        df = len(postings.get(term, ()))
        weights[term] = math.log(1 + n_passages / (1 + df)) * (1 + len(term) / _TERM_LENGTH_SCALE)
    return weights


def _alias_groups() -> dict[str, tuple[tuple[str, ...], ...]]:
    """Alternative surface forms per term, from `client/content/search-aliases.json`.

    **Reach only.** A group is one term slot: it carries the weight of the word the member actually typed,
    and a passage earns that weight once by carrying any form in the group. The denominator `_term_weights`
    builds is untouched, so nothing is diluted and no passage can accrue weight it was not already eligible
    for -- the record's own `how_it_is_applied` argues why the obvious implementation (appending synonyms
    to the term list) is wrong here and measurably so.

    **Absent or malformed means today's behaviour**, deliberately. This decides which paragraph is shown
    beside a citation the member can open, not what a lender would say, so failing open fails toward
    showing a real source rather than toward inventing one -- the opposite call from `property.conventions`
    and for the opposite reason.

    Returns `{term: (form, ...)}` where a form is a tuple of tokens; a multi-word form matches a passage
    only when ALL its tokens do, which is the conservative reading.
    """
    try:
        from ..content import _load

        record = _load("search-aliases")
    except Exception:  # noqa: BLE001 - a missing or broken record must not stop retrieval
        return {}
    out: dict[str, tuple[tuple[str, ...], ...]] = {}
    for group in record.get("groups") or ():
        forms = []
        for form in group.get("forms") or ():
            tokens = tuple(_WORD.findall(_fold(str(form))))
            if tokens:
                forms.append(tokens)
        for form in forms:
            # Only a single-token form can be something a member typed as one term, so only those become
            # keys. A multi-word form is reachable as a target, never as a trigger.
            if len(form) == 1:
                out.setdefault(form[0], tuple(f for f in forms if f != form))
    return out


def _passages_for(term: str, postings: dict[str, list[int]],
                  aliases: dict[str, tuple[tuple[str, ...], ...]]) -> set[int]:
    """Every passage this term can earn its weight from, itself or through an alias."""
    hit = set(postings.get(term, ()))
    for form in aliases.get(term, ()):
        if len(form) == 1:
            hit |= set(postings.get(form[0], ()))
        else:
            sets = [set(postings.get(token, ())) for token in form]
            if sets and all(sets):
                hit |= set.intersection(*sets)
    return hit


def _lexical(
    terms: list[str], weights: dict[str, float], postings: dict[str, list[int]]
) -> dict[int, tuple[int, tuple[str, ...]]]:
    """Per-mille share of the question's own weight each passage carries, and which terms earned it."""
    total = sum(weights.values())
    if not total:
        return {}
    accrued: dict[int, float] = {}
    matched: dict[int, list[str]] = {}
    aliases = _alias_groups()
    for term in terms:
        # The term's own postings, plus every passage an alias of it reaches. Accrued ONCE per term, so a
        # group is one slot and a passage carrying three forms of the same word earns no more than one.
        for i in _passages_for(term, postings, aliases):
            # `0` and not `0.0`: C-02's structural test forbids a float literal in this layer, and it is
            # right to — a bare decimal in a service is exactly how a rate gets hardcoded. Nothing here is
            # a rate, and nothing here needs a decimal point to say "start from nothing".
            accrued[i] = accrued.get(i, 0) + weights[term]
            matched.setdefault(i, []).append(term)
    return {
        i: (int(share * PER_MILLE / total), tuple(matched[i]))
        for i, share in accrued.items()
    }


def _lexical_over_text(terms: list[str], weights: dict[str, float], text: str) -> tuple[int, tuple[str, ...]]:
    """The same measure against one loose document, for an authored entry that is in no postings list."""
    total = sum(weights.values())
    if not total:
        return 0, ()
    present = set(_WORD.findall(_fold(text)))
    matched = tuple(t for t in terms if t in present)
    earned = sum(weights[t] for t in matched)
    return int(earned * PER_MILLE / total), matched


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class Ground:
    """One retrieved piece of impersonal ground, with every number that decided it.

    `semantic` is -1 when there was no embedding model, which is not the same as 0 and must not round to
    it: 0 is "the model looked and found nothing alike", -1 is "nobody looked".
    """

    kind: str                       # "book_passage" | "knowledge_entry"
    source_id: str
    title: str
    text: str
    score: int                      # per mille, the blend that ranked it
    semantic: int                   # per mille cosine, or -1
    lexical: int                    # per mille share of the question's weight
    matched: tuple[str, ...]
    where: str                      # the human-readable provenance R-171 shows
    sources: tuple[str, ...] = ()   # an authored entry's own citations

    def explain(self) -> dict:
        """Why this passage was chosen, for a caller that wants to see rather than trust."""
        return {
            "kind": self.kind,
            "id": self.source_id,
            "score": self.score,
            "semantic": self.semantic,
            "lexical": self.lexical,
            "matched_terms": list(self.matched),
        }


@dataclass(frozen=True)
class Grounding:
    """What a search found, in what mode, and — when it found nothing — why."""

    results: tuple[Ground, ...] = ()
    #: "vector" both channels ran · "lexical" no embedding model · "none" nothing was searched at all.
    mode: str = "none"
    reason: str | None = None
    considered: int = 0
    #: The floors this search actually applied, so a caller can report the gate it was refused by.
    floors: dict[str, int] = field(default_factory=dict)


def _cite(passage: dict) -> str:
    """Document first, then the place inside it — the estate's own rule, and for its own reason.

    With five sources a section heading alone is not provenance: "07 The gap and the capital" names a place
    in a document nobody identified, and an answer citing the wrong source is worse than one citing none,
    because it can be checked, found absent, and the reader concludes the citations are invented.
    """
    parts, seen = [], set()
    for part in (passage.get("work"), passage.get("chapter"), passage.get("section")):
        part = (part or "").strip()
        if part and part not in seen:
            seen.add(part)
            parts.append(part)
    return " · ".join(parts) or str(passage.get("source") or "")


def search(question: str, *, limit: int = 4, index_path: Path | None = None,
           relief: int = 0) -> Grounding:
    """Everything impersonal that clears the floor for this question, best first.

    Makes exactly one call to the local daemon — the question's embedding — and nothing else leaves this
    process. The question is not logged, not written and not kept.

    **`relief` lowers the floors, in per mille, and the caller states why.** The floors here were
    calibrated for a quoted answer, where a passage that comes back IS the answer put in front of the
    member — so a weak passage is a wrong answer and refusing it is correctness. A composed answer reads
    its passages as context and is able to say what they do not cover, which makes a weak passage weak
    context rather than a false claim, and the same setting that is right for quoting produced nothing at
    all for thirty-six of fifty real questions on 20 September 2026.

    The conjunctive shape does not move and neither does `LEXICAL_FLOOR`: relief applies to the two
    floors that express "close enough to be the answer" and not to the one that expresses "the corpus
    contains at least one word of the question", which is a different claim and is still required.
    """
    text = (question or "").strip()[:MAX_QUESTION_CHARS]
    terms = _terms(text)
    if not terms:
        return Grounding(reason="the question carries no term the corpus could be searched by")

    loaded = _load_index(str(index_path if index_path is not None else index_dir()))
    entries, _ = approved_entries()
    if loaded.index is None and not entries:
        return Grounding(reason=loaded.reason)

    book = loaded.index
    passages = book.passages if book else ()
    postings = book.postings if book else {}
    weights = _term_weights(terms, postings, len(passages) or len(entries) or 1)
    lexical = _lexical(terms, weights, postings) if book else {}

    semantic: list[float] | None = None
    mode, reason = "lexical", loaded.reason
    if book is not None and book.vectors is not None:
        try:
            # Embedded with the model the INDEX was built with, never with a configured one: two models
            # produce two coordinate systems, and a dot product across them is a number that means nothing
            # and looks like a similarity.
            query = llm.embed(text, model=book.model)
        except llm.LocalModelUnavailable as error:
            reason = f"no embedding model, so only word overlap was searched ({error})"
        else:
            if len(query) != book.dim:
                reason = (
                    f"the embedding model returned {len(query)} dimensions and the index has {book.dim}: "
                    f"{book.model!r} is not the model this index was built with"
                )
            else:
                semantic = [
                    sum(a * b for a, b in zip(query, book.vector(i))) for i in range(len(passages))
                ]
                mode, reason = "vector", None

    relief = max(0, int(relief))
    semantic_floor = max(0, SEMANTIC_FLOOR - relief)
    lexical_only_floor = max(0, LEXICAL_ONLY_FLOOR - relief)
    floor = semantic_floor if mode == "vector" else lexical_only_floor
    floors = ({"semantic": semantic_floor, "lexical": LEXICAL_FLOOR} if mode == "vector"
              else {"lexical_only": lexical_only_floor})
    if relief:
        floors["relief"] = relief
        floors["authored_entry"] = COMPOSE_ENTRY_FLOOR

    found: list[Ground] = []
    for i, passage in enumerate(passages):
        lex, matched = lexical.get(i, (0, ()))
        sem = max(0, int(semantic[i] * PER_MILLE)) if semantic is not None else -1
        if mode == "vector":
            if sem < semantic_floor or lex < LEXICAL_FLOOR:
                continue
            score = (SEMANTIC_WEIGHT * sem + LEXICAL_WEIGHT * lex) // 100
        else:
            if lex < lexical_only_floor:
                continue
            score = lex
        found.append(Ground(
            kind="book_passage", source_id=f"{passage.get('source', '')}#{i}", title=_cite(passage),
            text=str(passage.get("text", "")), score=score, semantic=sem, lexical=lex,
            matched=matched, where=_cite(passage),
        ))

    for entry in entries:
        # **Authored entries are scored on word overlap alone, and that is a decision.** They are written
        # in the member's language for the member's questions, so overlap is a direct measure rather than
        # a proxy for one; there are tens of them, not thousands, so there is no precision problem for an
        # embedding to solve; and it is the one channel that still works when the daemon is down, which
        # is the wrong moment for reviewed content to disappear. The floor is `LEXICAL_ONLY_FLOOR` while
        # quoting and `COMPOSE_ENTRY_FLOOR` while composing — see that constant for why the same number
        # cannot be right for both, and what the wrong one cost.
        lex, matched = _lexical_over_text(terms, weights, f"{entry.title}\n{entry.text}")
        if lex < (COMPOSE_ENTRY_FLOOR if relief else LEXICAL_ONLY_FLOOR):
            continue
        found.append(Ground(
            kind="knowledge_entry", source_id=entry.entry_id, title=entry.title, text=entry.text,
            score=lex, semantic=-1, lexical=lex, matched=matched,
            where=entry.title, sources=entry.sources,
        ))

    found.sort(key=lambda g: (-g.score, g.kind, g.source_id))
    if not found and reason is None:
        reason = (
            f"nothing in the corpus reached the relevance floor for this question "
            f"(floor {floor} per mille, mode {mode})"
        )
    return Grounding(results=tuple(found[:limit]), mode=mode, reason=reason,
                     considered=len(passages) + len(entries), floors=floors)


def reset_caches() -> None:
    """Drop the loaded index. For a test that plants one, and for nothing else."""
    _load_index.cache_clear()
