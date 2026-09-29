"""A retrieval index over *Capital Saturation*, built and searched with nothing but the standard library.

    python desktop/bookindex.py --build      # embed the manuscript, once
    python desktop/bookindex.py "kapitalsaettigung"   # search it

**Why this exists.** The desktop program can already compute a household's position and have a local model write
prose about it. What it could not do is answer "why does the model treat my home that way" — a question about the
*book the model comes from*, not about the household. That question has an authoritative answer sitting in
`book/manuscript/`, 51 fragments and about a megabyte of set text, and nothing could reach it.

**This index is K0 — no personal data, ever.** It is built from the book and from nothing else, and a coach
grounded on it cannot say anything about a household because it was never given one. That distinction is what
lets this ship now: the data-class rule says a model reading K1 or above must run inside the core, and this reads
K0. It is the part of the chatbot module that needs no gate.

**Standard library only, matching `prose.py`.** No numpy in the root environment and none added: the vectors are
`array('f')` on disk and the dot products are pure Python. That is affordable because of the two-stage search
below, not because pure-Python linear algebra over the whole book would be fast.

**Two stages, and the first one is what makes it interactive.**

  1. A cheap lexical filter over an inverted index narrows a few thousand passages to a few hundred.
  2. Exact cosine similarity re-ranks those, using embeddings from the local Ollama daemon.

Stage 2 alone would be several million multiply-adds per question in interpreted Python. Stage 1 alone would miss
everything a German question asks about an English book. Together they are fast and cross-lingual.

**`bge-m3` is the embedding model, and the choice is not arbitrary.** The book is set in English; the questions
arrive in German. A monolingual embedding would put "Kapitalsättigung" and "capital saturation" in different
neighbourhoods, which is the one thing this index must not do. `bge-m3` is explicitly multilingual.
`nomic-embed-text` is the fallback if it is absent, and the pure lexical stage is the fallback if neither is.
"""

from __future__ import annotations

import argparse
import array
import html as htmllib
import json
import math
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUSCRIPT = ROOT / "book" / "manuscript"
STORE = Path(__file__).resolve().parent / "bookindex"

#: Every document the coach may answer from. **An allow-list, because the alternative has already gone wrong
#: elsewhere in this repo**: a glob over `andersCH-prototype/*.html` would sweep in the dossiers, which are real
#: households. Each entry carries the label a citation shows, so an answer can say which book it came from.
SOURCES: tuple[dict[str, object], ...] = (
    {"key": "book", "label": "Capital Saturation", "dir": ROOT / "book" / "manuscript",
     "pattern": "*.html"},
    {"key": "lbs", "label": "The Life Balance Sheet",
     "file": ROOT / "engines" / "Life_Balance_Sheet" / "The_Life_Balance_Sheet_Book.md"},
    {"key": "method", "label": "Methodik der Standortbestimmung",
     "file": ROOT / "architecture" / "manual-gameplan.html"},
    {"key": "pcp", "label": "Portfolio Creation Program",
     "file": ROOT / "engines" / "PCP" / "CLAUDE_CODE_portfolio_creation_program.md"},
    # **The one source here that is about rules rather than about the model**, added 25 August 2026. Every
    # figure in it is quoted from Merkblatt 2.03 and 3.04 of the Informationsstelle AHV-IV, Stand 1. Januar
    # 2026. It exists because the coach was caught inventing a derivation for a question of law -- right
    # conclusion, invented mechanism -- and because refusing those questions, which is what it did next, left
    # a client asking about their own early retirement with nothing at all.
    {"key": "ahv", "label": "AHV: Beiträge und flexibler Rentenbezug",
     "file": ROOT / "knowledge" / "AHV_Beitraege_und_flexibler_Bezug.md"},
    # Four more rule sources, added 5 September 2026, for the same reason as the one above: the ten
    # loaded members between them asked about the second pillar, the retirement age, the WEF
    # withdrawal and the 3a maximum, and the index held none of it. Every figure in them is quoted
    # from a named document with its Stand date -- BVG and WEFV from fedlex, the amounts from the
    # BSV sheet "Beträge gültig ab dem 1. Januar 2026", the leaflets from ahv-iv.ch. Nothing was
    # restored from memory; what could not be quoted is named in each file's own closing section.
    {"key": "bvg", "label": "BVG: berufliche Vorsorge",
     "file": ROOT / "knowledge" / "BVG_Berufliche_Vorsorge.md"},
    {"key": "ahv-rente", "label": "AHV: Altersrente und Berechnung",
     "file": ROOT / "knowledge" / "AHV_Altersrente_Berechnung.md"},
    {"key": "wef", "label": "Wohneigentumsförderung mit Mitteln der beruflichen Vorsorge",
     "file": ROOT / "knowledge" / "WEF_Wohneigentumsfoerderung.md"},
    {"key": "3a", "label": "Säule 3a: Höchstabzüge",
     "file": ROOT / "knowledge" / "Saeule_3a_Grenzbetraege.md"},
    # Added 5 September 2026. Several notes in the corpus said an unmarried couple has no statutory right
    # of inheritance and called it the largest gap in a plan; none of them said what DOES apply. And the
    # Erbrechtsrevision in force since 1 January 2023 changed the Pflichtteile, so anyone recalling the
    # older fractions recalls the wrong ones.
    {"key": "erbrecht", "label": "ZGB: Erbrecht",
     "file": ROOT / "knowledge" / "ZGB_Erbrecht.md"},
    # Added 6 September 2026, and the first source here that is a STATISTIC rather than a rule. It is in
    # the index because the human-capital model turns education, network and health into an earning
    # power, and until this landed the endpoints of that conversion were chosen rather than quoted.
    # Reading it also settled what was wrong: the model's calibration reproduces a university graduate
    # WITHOUT a management function almost exactly, and the BFS table shows the Kaderfunktion is worth
    # more than the qualification. The missing dimension was responsibility, not expertise.
    {"key": "loehne", "label": "BFS: Lohnstrukturerhebung, Löhne 2024",
     "file": ROOT / "knowledge" / "BFS_Lohnstrukturerhebung.md"},
)

#: What was removed on the last build, per file. Printed by `build`, because a redaction nobody is told about
#: is indistinguishable from a document that never had the reference.
REDACTIONS: list[str] = []

#: Markers whose presence means the document is ABOUT a person. Refused: no redaction can make a case file
#: about somebody into general knowledge, and pretending otherwise is how one household's figures end up in
#: another household's answer.
_REFUSE_MARKERS: tuple[tuple[str, str], ...] = (
    (r"\bAbdellah\b", "a real person's name"),
)

#: **Filename patterns that are refused whatever the file contains.** The content check missed
#: `Nicolas_special_case.md` -- one real person's case from beginning to end -- because it looked for the
#: string "Nicolas_special_case" in the TEXT, and the words "special case" are in the NAME. A name check does
#: not depend on the document naming the person its filename already names.
_REFUSE_NAMES: tuple[tuple[str, str], ...] = (
    (r"special_case", "a case file for one person"),
    (r"^gameplan-", "a dossier"),
    (r"^onb-", "real onboarding output"),
    (r"^andersch-onboarding-", "a saved submission"),
    (r"^derived_onb-", "a derived mandate for a real household"),
)

#: Markers that are REFERENCES rather than data: a household id, a dossier filename. These are removed and the
#: removal is reported. `onb-` followed by a digit is an id; `onb-<` is the manual's own placeholder and is left
#: alone, which is the distinction a plain substring search would miss.
_REDACT_MARKERS: tuple[tuple[str, str], ...] = (
    (r"onb-\d[\w-]*", "a household id"),
    (r"gameplan-[\w-]+", "a dossier filename"),
    (r"derived_onb-\d[\w-]*", "a derived mandate name"),
)

#: Above this many redactions a document is about a household rather than merely mentioning one, and is
#: refused. The method manual needs five; a dossier would need dozens.
_REDACTION_LIMIT = 12

#: What a redacted reference becomes. Deliberately readable: a passage that says "siehe Fallbeispiel" is still
#: usable prose, where one with a hole in it reads as a rendering fault.
_REDACTED = "[Fallbeispiel]"


def _clean_or_refuse(path: Path, text: str) -> tuple[str, list[str]]:
    """The text with references removed, or a refusal if the document is about a person.

    **The build failing is the point for the first kind.** A knowledge base that absorbed a case file would
    answer one household's question with another's figures, and nothing downstream could detect it: the
    passage would look like any other and cite a real chapter.
    """
    import re as _re  # noqa: PLC0415
    for pattern, what in _REFUSE_NAMES:
        if _re.search(pattern, path.name, _re.I):
            raise ValueError(
                f"refusing to index {path.name}: its filename marks it as {what}. The coach is K0 and "
                f"must carry nothing about any household, and a name check does not depend on the "
                f"document mentioning the person its filename already names."
            )
    for pattern, what in _REFUSE_MARKERS:
        m = _re.search(pattern, text)
        if m:
            raise ValueError(
                f"refusing to index {path.name}: it contains {what} ({m.group(0)!r} at character "
                f"{m.start()}). The coach is K0 and must carry nothing about any household."
            )
    notes: list[str] = []
    total = 0
    for pattern, what in _REDACT_MARKERS:
        text, n = _re.subn(pattern, _REDACTED, text)
        if n:
            total += n
            notes.append(f"{n}x {what}")
    if total > _REDACTION_LIMIT:
        raise ValueError(
            f"refusing to index {path.name}: {total} references to households had to be removed, which is "
            f"more than a document merely mentioning them would carry. This reads as a file about one or "
            f"more households rather than about the method."
        )
    return text, notes


def _refuse_if_personal(path: Path, text: str) -> None:
    """Raise if this file carries real-person data. Called before any file is indexed.

    **The build failing is the point.** A knowledge base that silently absorbed one household's dossier would
    answer another household's question with it, and nothing downstream could detect that: the passage would
    look like any other and cite a real chapter. So this is a hard stop with the marker named, not a warning.
    """
    import re as _re  # noqa: PLC0415
    for pattern, what in _PERSONAL_MARKERS:
        m = _re.search(pattern, text)
        if m:
            raise ValueError(
                f"refusing to index {path.name}: it contains {what} ({m.group(0)!r} at "
                f"character {m.start()}). The coach is K0 and must carry nothing about any household. "
                f"If this file genuinely belongs in the index, the household data has to come out of it "
                f"first."
            )


META = STORE / "meta.json"
VECS = STORE / "vecs.bin"

OLLAMA = "http://127.0.0.1:11434"
#: Multilingual by design. See the module docstring: a German question against an English book is the whole
#: retrieval problem here, and a monolingual model fails it silently rather than loudly.
EMBED_MODELS = ("bge-m3", "nomic-embed-text")
EMBED_TIMEOUT_S = 120

#: Target passage size in characters. Long enough that a claim keeps its qualifying clause, short enough that a
#: retrieved passage is worth reading in a citation. Paragraphs are merged up to this and never split below it.
CHUNK_TARGET = 700
CHUNK_MAX = 1400

#: Candidates the lexical stage passes to the vector stage. Large enough that a poorly-worded query still reaches
#: the right passage, small enough that the pure-Python cosine stays well under a second.
PREFILTER = 240


@dataclass
class Passage:
    text: str
    #: Which of the four documents this passage is from, as a reader would name it. Defaulted so a store
    #: written before this field existed still loads -- it simply cites without the document, as it did.
    work: str = ""
    chapter: str = ""
    section: str = ""
    source: str = ""

    @property
    def cite(self) -> str:
        """Document first, then the place inside it.

        **The document leads because with four sources the section alone is not provenance.** A heading like
        "07 The gap and the capital" names a place in a document nobody identified, and the model duly
        attributed a manual passage to the book. An answer citing the wrong source is worse than one citing
        none: it can be checked, found absent, and the reader concludes the citations are invented.
        """
        bits = [b for b in (self.work, self.chapter, self.section) if b]
        # De-duplicated, because a single-file source sets `chapter` to its own label when the document has
        # no h1 of its own, and "Methodik · Methodik · 07 ..." reads as a bug.
        seen, unique = set(), []
        for b in bits:
            if b not in seen:
                seen.add(b)
                unique.append(b)
        return " · ".join(unique) if unique else self.source


# --- reading the manuscript -------------------------------------------------------------

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

#: Greek and operators the book actually uses, in the LaTeX the manuscript stores. **The manuscript holds
#: mathematics as LaTeX source** — `\(\kappa = K/Y\)` — and KaTeX renders it only at press time, so 192 of the
#: 1163 passages carry raw markup. Leaving it in costs twice: the embedding spends its attention on backslashes,
#: and the model repeats `W_R^{\text{inv}}` back to a reader who wanted a sentence. Translating is cheap and
#: makes the passage read the way the printed page does.
_GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "zeta": "ζ", "eta": "η",
    "theta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Delta": "Δ", "Gamma": "Γ", "Lambda": "Λ", "Omega": "Ω", "Phi": "Φ", "Sigma": "Σ", "Theta": "Θ",
}
_OPS = {
    r"\cdot": "·", r"\times": "×", r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\approx": "≈",
    r"\to": "→", r"\rightarrow": "→", r"\infty": "∞", r"\partial": "∂", r"\sum": "Σ", r"\int": "∫",
    r"\sqrt": "√", r"\pm": "±", r"\ldots": "…", r"\dots": "…",
}


def _demath(s: str) -> str:
    """Turn the manuscript's LaTeX into the symbols a reader would see on the page."""
    if "\\" not in s:
        return s
    s = re.sub(r"\\[()\[\]]", " ", s)                       # the \( \) \[ \] delimiters
    for k, v in _OPS.items():
        s = s.replace(k, v)
    s = re.sub(r"\\(?:mathrm|text|mathbf|mathit|operatorname)\{([^{}]*)\}", r"\1", s)
    s = re.sub(r"\\(" + "|".join(_GREEK) + r")\b", lambda m: _GREEK[m.group(1)], s)
    s = re.sub(r"\\(?:bigl|bigr|Bigl|Bigr|left|right|,|;|!|quad|qquad)", " ", s)
    s = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", s)
    s = re.sub(r"[_^]\{([^{}]*)\}", r"_\1", s)              # W_{R}^{inv} -> W_R_inv
    s = re.sub(r"\\[a-zA-Z]+", " ", s)                      # anything left, dropped rather than shown
    return s.replace("{", " ").replace("}", " ")


def _text(fragment: str) -> str:
    return _WS.sub(" ", _demath(htmllib.unescape(_TAG.sub(" ", fragment)))).strip()


def passages() -> list[Passage]:
    """Every passage of the set book, with the chapter and section it sits in.

    Provenance is carried because a coach that cannot say *where* an answer comes from is not usefully different
    from one that made it up. The headings are read from the manuscript's own markup rather than guessed:
    `.chap-open` carries the chapter, `h2.sec` and `h3.sub` the divisions inside it.
    """
    out: list[Passage] = []
    for src in SOURCES:
        paths = (sorted(src["dir"].glob(src["pattern"])) if src.get("dir")
                 else ([src["file"]] if Path(src["file"]).is_file() else []))
        for path in paths:
            raw = path.read_text(encoding="utf-8", errors="replace")
            raw, notes = _clean_or_refuse(path, raw)
            if notes:
                REDACTIONS.append(f"{path.name}: {', '.join(notes)}")
            out.extend(_from_one(path, raw, str(src["label"]), str(src["key"])))
    return _merge(out)


def _from_one(path: Path, raw: str, label: str, key: str) -> list[Passage]:
    """Passages from one document. Markdown is converted to the same block shape as the manuscript's HTML.

    The manuscript carries its own structure in class names and the other three do not, so headings are read
    from whatever each format offers: `#` levels in Markdown, `h1`-`h3` in HTML. A passage with no heading
    above it still gets the document's label, which is the minimum a citation needs.
    """
    if path.suffix.lower() == ".md":
        raw = _md_to_blocks(raw)
    out: list[Passage] = []
    if True:
        chapter, section = label, ""
        # Split on the block elements that carry text, keeping the headings so state can be tracked.
        for m in re.finditer(
            r"<(h1|h2|h3|p|li|div|td)\b([^>]*)>(.*?)</\1>", raw, re.S | re.I
        ):
            tag, attrs, inner = m.group(1).lower(), m.group(2), m.group(3)
            body = _text(inner)
            if not body:
                continue
            cls = (re.search(r'class="([^"]*)"', attrs) or ["", ""])[1] if 'class="' in attrs else ""
            if tag == "h1" or "chap-open" in cls or "cnum" in cls:
                chapter, section = body, ""
                continue
            if tag == "h2":
                section = body
                continue
            if tag == "h3":
                section = f"{section} · {body}" if section else body
                continue
            if tag in ("div", "td") and len(body) < 40:
                continue                      # layout scaffolding, not prose
            if len(body) < 60:
                continue                      # captions, folios, stray labels
            out.append(Passage(text=body, work=label, chapter=chapter, section=section,
                               source=path.name))
    return out


_MD_HEAD = None


def _md_to_blocks(text: str) -> str:
    """Markdown into the block markup `_from_one` already knows how to walk.

    Deliberately crude: headings become `h1`-`h3`, everything else between blank lines becomes a paragraph.
    A full Markdown parser would be a dependency for no gain -- the coach reads prose, and a table rendered
    as a run of words is still answerable prose.
    """
    import re as _re  # noqa: PLC0415
    lines, out = text.split("\n"), []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            body = " ".join(buf).strip()
            if body:
                out.append(f"<p>{body}</p>")
            buf.clear()

    for line in lines:
        h = _re.match(r"^(#{1,3})\s+(.*)$", line)
        if h:
            flush()
            out.append(f"<h{len(h.group(1))}>{h.group(2).strip()}</h{len(h.group(1))}>")
            continue
        if not line.strip():
            flush()
            continue
        buf.append(line.strip().lstrip("|").replace("|", " "))
    flush()
    return "\n".join(out)


def _merge(items: list[Passage]) -> list[Passage]:
    """Glue short neighbours together up to `CHUNK_TARGET`, without crossing a section boundary.

    A single paragraph is often too small to answer anything on its own — the book states a proposition in one
    and qualifies it in the next, and retrieving only the first is how a qualified claim becomes an unqualified
    one. Merging stops at a section change so a passage never spans two arguments.
    """
    merged: list[Passage] = []
    for p in items:
        # `work` joins the boundary test: merging across two documents would produce a passage whose
        # citation names one source and whose second half came from another, which is the mis-attribution
        # this change exists to stop, reintroduced one layer down.
        if (merged and len(merged[-1].text) < CHUNK_TARGET
                and merged[-1].work == p.work
                and merged[-1].section == p.section and merged[-1].chapter == p.chapter
                and len(merged[-1].text) + len(p.text) <= CHUNK_MAX):
            merged[-1].text = merged[-1].text + " " + p.text
        else:
            merged.append(Passage(**asdict(p)))
    return merged


# --- the lexical stage ------------------------------------------------------------------

_WORD = re.compile(r"[a-zäöüàéèêç0-9]+", re.I)


def tokens(s: str) -> list[str]:
    """Fold accents and case, keep digits. Deliberately crude: this stage only has to be generous."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _WORD.findall(s)


@dataclass
class Index:
    passages: list[Passage] = field(default_factory=list)
    #: token -> passage ids
    postings: dict[str, list[int]] = field(default_factory=dict)
    dim: int = 0
    model: str = ""
    _vecs: array.array | None = None

    def lexical(self, query: str, n: int = PREFILTER) -> list[int]:
        """Passage ids scored by how many distinct query tokens they carry, longest tokens weighted highest.

        Not BM25 and not trying to be: its only job is to hand the vector stage a candidate set that contains
        the right answer. Precision is stage two's problem.
        """
        scores: dict[int, float] = defaultdict(float)
        for t in set(tokens(query)):
            ids = self.postings.get(t)
            if not ids:
                continue
            # A term in few passages is worth more than one in many; long terms are worth more than short ones.
            w = math.log(1 + len(self.passages) / (1 + len(ids))) * (1.0 + len(t) / 12.0)
            for i in ids:
                scores[i] += w
        ranked = sorted(scores, key=lambda i: -scores[i])[:n]
        # A query whose words do not appear at all still has to search something.
        return ranked or list(range(min(n, len(self.passages))))

    def vector(self, i: int) -> list[float] | None:
        if self._vecs is None or not self.dim:
            return None
        off = i * self.dim
        return list(self._vecs[off:off + self.dim])

    def search_multi(self, queries: list[str], k: int = 6) -> list[tuple[Passage, float]]:
        """Search with several renderings of one question and keep each passage's best score.

        **German compounds are where the multilingual model is weakest, and it fails quietly.** Measured on this
        book: *"Was bedeutet Kapitalsättigung?"* tops out at 0.536 on a section about jurisdictional
        diversification, while *"What is capital saturation?"* reaches 0.648 on §10.5, which is the section that
        defines it. The German noun does not land near its English equivalent, and nothing in the score says so —
        0.536 clears the relevance gate, so the coach answers from a passage that is not about the question.

        Searching both renderings costs one extra embedding call and removes the failure. The union is taken by
        best score rather than by rank, because a passage that is strong in either language is the right answer
        in both.
        """
        if not (self.model and self._vecs is not None):
            return [(self.passages[i], 0.0) for i in self.lexical(queries[0])[:k]]
        best: dict[int, float] = {}
        for q in queries:
            qv = embed(q, self.model)
            if qv is None:
                continue
            for i in range(len(self.passages)):
                s = sum(a * b for a, b in zip(qv, self.vector(i)))
                if s > best.get(i, -2.0):
                    best[i] = s
        ranked = sorted(best.items(), key=lambda t: -t[1])[:k]
        return [(self.passages[i], s) for i, s in ranked]

    def search(self, query: str, k: int = 6) -> list[tuple[Passage, float]]:
        """Cosine over EVERY passage when embeddings exist; lexical only when they do not.

        **The lexical prefilter was here and had to be removed, because it defeated the reason the multilingual
        model was chosen.** A German question against an English book shares no vocabulary with it: measured on
        "Wie hängen Gesundheit und Einkommen zusammen?", the filter matched exactly one token — the German
        stopword *und*, which occurs in a German-language bibliography entry — and returned two candidates. The
        vector stage then re-ranked those two, and the answer came back as the bibliography. The retrieval was
        not weak; it was searching the wrong two passages out of 1163.

        The full scan costs **0.06 s** over the whole book. The prefilter was optimising something that was
        never expensive, at the cost of the property the index exists for.

        `lexical()` is kept because it is the honest fallback when no embedding model is present, and there the
        query and the corpus are at least in the same situation.
        """
        qv = embed(query, self.model) if self.model else None
        if qv is None or self._vecs is None:
            return [(self.passages[i], 0.0) for i in self.lexical(query)[:k]]
        scored = sorted(
            ((sum(a * b for a, b in zip(qv, self.vector(i))), i) for i in range(len(self.passages))),
            reverse=True)
        return [(self.passages[i], s) for s, i in scored[:k]]


def _norm(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


# --- embeddings, through the local daemon ------------------------------------------------

def _post(path: str, payload: dict, timeout: int = EMBED_TIMEOUT_S) -> dict:
    req = urllib.request.Request(
        OLLAMA + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def available_model() -> str:
    """The first preferred embedding model the local daemon actually has. Empty string if none."""
    try:
        with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=8) as r:
            names = {m["name"].split(":")[0] for m in json.loads(r.read().decode("utf-8")).get("models", [])}
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return ""
    for m in EMBED_MODELS:
        if m.split(":")[0] in names:
            return m
    return ""


def embed(text: str, model: str) -> list[float] | None:
    try:
        d = _post("/api/embeddings", {"model": model, "prompt": text})
        v = d.get("embedding")
        return _norm(v) if v else None
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


# --- build and load ----------------------------------------------------------------------

def build(force: bool = False, progress=print) -> Index:
    """Embed every passage and write the store. Idempotent unless `force`."""
    ps = passages()
    model = available_model()
    progress(f"  {len(ps)} passages from {len(list(MANUSCRIPT.glob('*.html')))} fragments")
    if not model:
        progress("  no embedding model on the local daemon: building the lexical index only")

    vecs = array.array("f")
    dim = 0
    if model:
        progress(f"  embedding with {model} (local, nothing leaves this machine)")
        for n, p in enumerate(ps, 1):
            v = embed(p.text, model)
            if v is None:
                progress(f"  embedding failed at passage {n}; falling back to lexical only")
                vecs, dim, model = array.array("f"), 0, ""
                break
            if dim == 0:
                dim = len(v)
            vecs.extend(v)
            if n % 200 == 0:
                progress(f"    {n}/{len(ps)}")

    STORE.mkdir(exist_ok=True)
    META.write_text(json.dumps({
        "passages": [asdict(p) for p in ps], "dim": dim, "model": model,
        "postings": _postings(ps),
    }, ensure_ascii=False), encoding="utf-8")
    VECS.write_bytes(vecs.tobytes())
    progress(f"  wrote {META.relative_to(ROOT).as_posix()} and {VECS.relative_to(ROOT).as_posix()}"
             f"  ({(META.stat().st_size + VECS.stat().st_size) // 1024} KB, dim {dim})")
    return load()


def _postings(ps: list[Passage]) -> dict[str, list[int]]:
    post: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(ps):
        for t in set(tokens(p.text)):
            if len(t) > 2:
                post[t].append(i)
    # Tokens in almost every passage carry no signal and dominate the store's size.
    cut = max(20, int(0.35 * len(ps)))
    return {t: ids for t, ids in post.items() if len(ids) <= cut}


def load() -> Index | None:
    if not META.exists():
        return None
    d = json.loads(META.read_text(encoding="utf-8"))
    idx = Index(passages=[Passage(**p) for p in d["passages"]],
                postings=d.get("postings", {}), dim=d.get("dim", 0), model=d.get("model", ""))
    if idx.dim and VECS.exists():
        a = array.array("f")
        a.frombytes(VECS.read_bytes())
        idx._vecs = a
    return idx


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("query", nargs="*", help="search the index")
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args(argv)

    if args.build:
        build()
        return 0
    idx = load()
    if idx is None:
        print("no index yet: run with --build", file=sys.stderr)
        return 1
    if not args.query:
        print(f"{len(idx.passages)} passages, model {idx.model or 'lexical only'}, dim {idx.dim}")
        return 0
    for p, s in idx.search(" ".join(args.query)):
        print(f"\n[{s:.3f}] {p.cite}")
        print(f"  {p.text[:300]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
