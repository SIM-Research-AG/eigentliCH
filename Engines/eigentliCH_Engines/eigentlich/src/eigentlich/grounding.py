"""Choosing the knowledge notes a question is answered from (EIG-33, widened on 29.09.2026: EIG-51).

Only approved notes (``front_matter.approved`` true, the prototype's retrieval gate) are candidates. The
score is keyword overlap, deterministic and explainable, made German-aware:

* **Words.** The question and every note are lower-cased, umlauts folded (ä->a, ö->o, ü->u, ß->ss), split
  into words of three letters or more, and German and English stop words removed, with their inflected forms
  (``unseren``, ``müssen``, ``gehört``: EIG-55). Numbers never score (``000``, ``2030``, ``180``): a year or an
  amount says nothing about which note answers, and ``180 000`` matched every note with a figure in it. Nor do
  number words and the words every note uses (``Franken``, ``zwei``). Each word is reduced to a simple stem (a
  German inflection ending taken off: ``einkommens`` and ``einkommen`` meet), and a word also matches a note
  word it is a prefix of when both have five letters or more (``saeule`` and ``saeulen``); a note word that is
  a prefix of the question's word matches only when what is left is an ending (three letters at most), so
  ``vorsorgeauftrag`` no longer matches every note that says ``vorsorge``.
* **Compounds.** A long question word that matches nothing whole is split where one part is a word of the
  notes (``wachstumsstrategie``: ``wachstum`` + ``strategie``, the linking ``s`` dropped); its parts then count
  as one term, scored by the best of them.
* **Synonyms.** The groups of ``reference/search-aliases`` (the prototype's record: surface forms of the same
  thing, «Pensionskasse», «berufliche Vorsorge», «BVG», ...): when the question uses one form, a note that
  carries any form of the group matches that term. A group is one term, as the record says, never several.
* **Where it matches.** Each term scores 3 in the note's title or id, 2 in its topic tag or in its «Fragen,
  die dieser Text beantwortet» list, 1 in its body.
* **Always something, when anything matches.** Notes at or above ``min_score`` are sent, the best
  ``max_notes`` of them; when none reaches it, the best ``fallback_notes`` at or above ``floor`` are sent
  rather than none (the chatbot says when its answer is a general assessment). A question that matches
  nothing at all gets no note. Ties are broken by key.

The note is sent whole up to ``max_chars_per_note`` (the chatbot refuses longer notes), cut at a paragraph
boundary. Its grounding id is ``<note id>.v<version>`` (the chatbot's ids admit no slash), so a stored
answer names exactly which version it drew on.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from . import contracts as c

_STOP = set("""
aber alle allem allen aller alles als also am an andere anderen auch auf aus bei beim bin bis bist da damit
dann das dass dein deine dem den denn der des dessen die dies diese diesem diesen dieser dieses doch dort du
durch ein eine einem einen einer eines er es etwas euer fur gegen gibt hab habe haben hat hatte ich ihr ihre
ihrem ihren ihrer im in ist ja jede jedem jeden jeder jedes kann kein keine konnen man mehr mein meine meinem
meinen meiner mich mir mit muss musste nach nicht nichts noch nun nur ob oder ohne sehr sein seine sich sie
sind so soll sollte sondern uber um und uns unser unter vom von vor war waren was weil welche welchem welchen
welcher welches wenn wer werde werden wie wieviel viel viele wir wird wo wollen zu zum zur zwischen
machen mache macht tun kann konnte dass damit also bitte gerne etwa
the and for are but not you your yours with from that this what which when where who how can could should
would will have has had does did was were been being into about than then them they their there here its
""".split()) | set("""
unsere unserem unseren unserer unseres eure eurem euren eurer eures deinem deinen deiner deines seinem seinen
seiner seines ihres meines jene jenem jenen jener jenes solche solchem solchen solcher solches manche manchem
manchen mancher einige einigem einigen einiger beide beiden beider beides jemand niemand jeder jemandem
bist ist sind seid sei seien war warst waren wart gewesen wird wirst werdet wurde wurden wurdest wurde wurden
worden geworden hast hatte hatten hattest hatte habt gehabt kannst konnen konnt konnten konntest musst mussen
musst musste mussten sollst sollen sollt sollten darf darfst durfen durft durfte durften will willst wollt
wollte wollten mag magst mochte mochten mochtest lasst lassen gibt geben gegeben gilt gelten galt
gehort gehoren gehorte bekomme bekommen kommt kommen kam geht gehen ging steht stehen stand sagen sagt
beachten beachte wissen weiss sehen sieht finden findet brauche brauchen braucht
schon immer wieder dann denn doch noch nun jetzt heute hier dort dabei dafur dazu davon darauf daruber daran
darin damit dagegen daher darum deshalb deswegen trotzdem obwohl sowie bzw usw beim zum zur ins ans vom
wann warum wieso weshalb wofur womit wovon worauf wozu wohin woher welches wessen wem wen
ganz gar sehr mehr weniger wenig viel viele vielen vieles etwas nichts alles eigentlich wirklich genau
eigene eigenen eigener eigenes eigenem sinn sinne fall falls falle weise art
null eins zwei drei vier funf sechs sieben acht neun zehn elf zwolf zwanzig dreissig hundert tausend
million millionen milliarde prozent franken chf fr jahr jahre jahren jahres monat monate monaten
seit seitdem wegen bevor nachdem wahrend bis
""".split())

#: Words that make a question one about the asker's own situation (the chatbot's ``client_situation``).
FIRST_PERSON = frozenset("ich mich mir mein meine meinen meinem meiner meines wir uns unser unsere unserem unseren "
                         "unserer my me mine myself we us our ours".split())

#: German inflection endings, longest first; a stem keeps at least four letters.
_ENDINGS = ("ungen", "innen", "ern", "en", "er", "es", "em", "e", "n", "s")

_QUESTIONS_HEADING = re.compile(r"^#+\s*fragen, die dieser text beantwortet\s*$", re.I)


def fold(text: str) -> str:
    text = text.lower().replace("ß", "ss").replace("ä", "a").replace("ö", "o").replace("ü", "u")
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", fold(text))


def stem(word: str) -> str:
    for end in _ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 4:
            return word[: -len(end)]
    return word


def words(text: str) -> set[str]:
    """The distinct stems of a text's content words: no stop word, no number (EIG-55)."""
    return {stem(w) for w in tokens(text) if len(w) >= 3 and w not in _STOP and not w.isdigit()}


def about_the_asker(question: str) -> bool:
    return any(w in FIRST_PERSON for w in tokens(question))


def _hits(word: str, bag: set[str]) -> bool:
    """The word is in the bag, or a longer inflection of it is, or it is an inflection of a bag word (at most
    three letters longer). A bag word that is merely the first part of a compound does not match (EIG-55)."""
    if word in bag:
        return True
    if len(word) >= 5:
        return any(len(b) >= 5 and (b.startswith(word) or (word.startswith(b) and len(word) - len(b) <= 3))
                   for b in bag)
    return False


def _phrase_in(form: str, folded: str) -> bool:
    return re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])", folded) is not None


def _questions_section(markdown: str) -> str:
    """The note's «Fragen, die dieser Text beantwortet» list: what the note says it answers."""
    out, inside = [], False
    for line in markdown.splitlines():
        if _QUESTIONS_HEADING.match(line.strip()):
            inside = True
            continue
        if inside and line.lstrip().startswith("#"):
            break
        if inside:
            out.append(line)
    return "\n".join(out)


@dataclass(frozen=True)
class Chosen:
    key: str
    version: int
    score: int
    note: c.GroundingNote

    def source(self) -> dict[str, Any]:
        return {"id": self.note.id, "key": self.key, "version": self.version, "title": self.note.title,
                "source_label": self.note.source_label, "score": self.score}


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[:limit]
    cut = head.rfind("\n\n")
    return (head[:cut] if cut > limit // 2 else head).rstrip() + "\n\n[…]"


def alias_groups(body: Any) -> list[tuple[str, ...]]:
    """The groups of a ``reference/search-aliases`` body, each a tuple of folded surface forms."""
    groups = (body or {}).get("groups") if isinstance(body, dict) else None
    out = []
    for g in groups or []:
        forms = tuple(fold(f).strip() for f in (g.get("forms") or []) if isinstance(f, str) and f.strip())
        if forms:
            out.append(forms)
    return out


@dataclass
class _Field:
    folded: str
    bag: set[str]
    weight: int


def _fields(row: dict[str, Any], language: str) -> tuple[str, str, list[_Field]]:
    body = row["body"] or {}
    fm = body.get("front_matter") or {}
    note_id = str(fm.get("id") or row["key"].split("/", 1)[1])
    title = str(fm.get(f"title_{language}") or fm.get("title_de") or fm.get("title") or note_id)
    markdown = body.get("markdown") or ""
    head = f"{title} {note_id.replace('-', ' ')}"
    tags = " ".join(str(t) for t in ([fm.get("topic")] + list(fm.get("tags") or [])) if t)
    topic = f"{tags} {_questions_section(markdown)}"
    return note_id, title, [_Field(fold(head), words(head), 3), _Field(fold(topic), words(topic), 2),
                            _Field(fold(markdown), words(markdown), 1)]


def _terms(question: str, vocabulary: set[str], groups: Sequence[tuple[str, ...]]) -> list[tuple[str, tuple]]:
    """The question's terms: ("group", forms), ("word", (stem,)) or ("compound", parts)."""
    folded = fold(question)
    terms: list[tuple[str, tuple]] = []
    covered: set[str] = set()
    for forms in groups:
        if any(_phrase_in(f, folded) for f in forms):
            terms.append(("group", forms))
            for f in forms:
                if _phrase_in(f, folded):
                    covered.update(words(f))
    for w in sorted(words(question) - covered):
        if _hits(w, vocabulary) or len(w) < 9:
            terms.append(("word", (w,)))
            continue
        parts = set()
        for i in range(4, len(w) - 3):
            left, right = w[:i], w[i:]
            for piece in (left, left[:-1] if left.endswith("s") else None, right):
                if piece and len(piece) >= 4 and stem(piece) in vocabulary:
                    parts.add(stem(piece))
        terms.append(("compound", tuple(sorted(parts))) if parts else ("word", (w,)))
    return terms


def _score(terms: list[tuple[str, tuple]], fields: list[_Field]) -> int:
    total = 0
    for kind, what in terms:
        best = 0
        for f in fields:
            if kind == "group":
                hit = any(_phrase_in(form, f.folded) for form in what)
            else:
                hit = any(_hits(part, f.bag) for part in what)
            if hit:
                best = max(best, f.weight)
        total += best
    return total


def choose(question: str, notes: Iterable[dict[str, Any]], *, max_notes: int, max_chars_per_note: int,
           min_score: int, language: str = "de", aliases: Optional[Sequence[tuple[str, ...]]] = None,
           floor: int = 1, fallback_notes: int = 2) -> list[Chosen]:
    """``notes`` are ``content_current`` rows of kind knowledge; ``aliases`` from ``alias_groups``."""
    candidates = []
    for row in notes:
        fm = (row["body"] or {}).get("front_matter") or {}
        if fm.get("approved") is not True:
            continue
        note_id, title, fields = _fields(row, language)
        candidates.append((row, note_id, title, fields))
    vocabulary: set[str] = set()
    for _, _, _, fields in candidates:
        for f in fields:
            vocabulary |= f.bag
    terms = _terms(question, vocabulary, aliases or ())
    scored = sorted(((_score(terms, fields), row["key"], row, note_id, title)
                     for row, note_id, title, fields in candidates), key=lambda s: (-s[0], s[1]))
    picked = [s for s in scored if s[0] >= min_score][:max_notes]
    if not picked:
        picked = [s for s in scored if s[0] >= max(floor, 1)][:fallback_notes]
    chosen = []
    for score, key, row, note_id, title in picked:
        fm = row["body"]["front_matter"]
        reviewed = fm.get("reviewed_on")
        label = f"eigentliCH Wissen: {title}" + (f" (geprüft {reviewed})" if reviewed else "")
        chosen.append(Chosen(key=key, version=row["version"], score=score, note=c.GroundingNote(
            id=f"{note_id}.v{row['version']}", title=title[:300], text=_cut(row["body"]["markdown"], max_chars_per_note),
            source_label=label[:300])))
    return chosen
