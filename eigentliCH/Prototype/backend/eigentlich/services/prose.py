"""Member-facing text is prose, and that is guaranteed here rather than requested in a prompt.

**Why this is code and not a seventh line in the system prompt.** It was a line in the system prompt.
`SYSTEM_DE` said, in German, at most 200 words, no headings, no tables, no emoji, no lists without need.
Asked "kann ich in vier Jahren aufhören, ohne den Lebensstandard zu ändern?", the model returned 645
words under six numbered headings, with two tables, sixteen emoji, horizontal rules, a closing "Fazit",
and an offer to run a simulation. Tightening the wording made it longer.

A prompt is a request. What a member reads has to be a guarantee, and the only place to put one is on
the string.

**The cause was ours, which is why the repair runs on both sides.** The authored corpus entries are
Markdown — they carry `##` headings, `**bold**` and bullet lists, because they are files a person reads.
Handing that to a model as grounding and then asking for plain prose is asking it to ignore the shape of
everything in front of it, and it does not. `for_prompt` strips the structure out of a passage before the
model sees it; `for_member` strips whatever came back anyway.

Neither is a rewrite. Both remove presentation and keep words: a heading becomes its own sentence, a
bullet loses its dash, a table row becomes its cells separated by en-dashes. Nothing is reordered and no
word is replaced, so a figure that was traceable before is traceable after and `unverifiable_figures`
reads the same text the member does.
"""

from __future__ import annotations

import re

#: Emoji and the pictographic blocks a financial answer has no use for. Deliberately not "everything
#: above U+2500": `«»`, `—`, `€` and the Swiss `’` all live up there and all belong in this prose.
_PICTOGRAPHIC = (
    (0x1F300, 0x1FAFF),   # emoji, pictographs, symbols
    (0x2600, 0x27BF),     # misc symbols and dingbats
    (0xFE00, 0xFE0F),     # variation selectors
    (0x2190, 0x21FF),     # arrows
)

_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$", re.MULTILINE)
_BULLET = re.compile(r"^\s{0,4}[-*+]\s+", re.MULTILINE)

#: **There is deliberately no rule for a numbered list, and this domain is why.** Stripping a leading
#: `1. ` would turn «1. Säule», «2. Säule» and «3. Säule» into «Säule» — the three pillars are the
#: subject of half this corpus, and their numbers are the whole of what distinguishes them. A stray
#: `1.` at the start of a line costs a member nothing; losing the pillar costs them the sentence.
#: Headings, rules, bullets, tables, bold and emoji are all removable without touching a word. This
#: one is not, so it stays.
_TABLE_DIVIDER = re.compile(r"\|?[\s:|-]*-[\s:|-]*\|?")
_TABLE_ROW = re.compile(r"\|(.+)\|")
_BLANKS = re.compile(r"\n{3,}")


def _depictograph(text: str) -> tuple[str, int]:
    out, removed = [], 0
    for char in text:
        if any(low <= ord(char) <= high for low, high in _PICTOGRAPHIC):
            removed += 1
            continue
        out.append(char)
    return "".join(out), removed


def _rows_to_sentences(text: str) -> str:
    """A table row becomes its cells, en-dash separated, one line each.

    Line by line rather than by substitution: a regex pass over the whole string ran two rows together
    into `Faktor — WarumUmwandlungssatz — bestimmt die Rente`, because removing the divider left the
    surrounding newlines to be collapsed by the blank-line pass afterwards. Walking the lines keeps each
    row a line, which is the only thing this has to get right.
    """
    out = []
    for line in text.splitlines():
        if _TABLE_DIVIDER.fullmatch(line.strip()) and "|" in line:
            continue
        row = _TABLE_ROW.fullmatch(line.strip())
        if row:
            cells = [cell.strip() for cell in row.group(1).split("|") if cell.strip()]
            if cells:
                out.append(" — ".join(cells))
            continue
        out.append(line)
    return "\n".join(out)


def flatten(text: str) -> tuple[str, dict]:
    """Presentation out, words kept. Returns the prose and what was removed.

    The counts are returned rather than logged so the caller can put them in an answer's audit: a rising
    number means the model has started formatting again, which is a fact about the model or the prompt
    and worth seeing before a member reports it.
    """
    if not text:
        return text, {}

    found: dict = {}
    if _HEADING.search(text):
        found["headings"] = len(_HEADING.findall(text))
    if _TABLE_ROW.search(text):
        found["table_rows"] = len(_TABLE_ROW.findall(text))

    text = _rows_to_sentences(text)
    text = _RULE.sub("", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    text = text.replace("**", "").replace("__", "")

    text, pictograms = _depictograph(text)
    if pictograms:
        found["pictograms"] = pictograms

    text = _BLANKS.sub("\n\n", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip(), found


def for_prompt(text: str) -> str:
    """A passage as the model should see it: the words, without a shape to imitate."""
    return flatten(text)[0]


def for_member(text: str) -> tuple[str, dict]:
    """An answer as the member should read it, and what had to be taken out of it."""
    return flatten(text)


__all__ = ["flatten", "for_member", "for_prompt"]
