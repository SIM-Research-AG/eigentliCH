"""The connective sentence, written by the local model, inside a page the code has already finished.

**What this layer may and may not do.** The dossier is complete and readable before this runs: every figure,
every table, every finding, the whole schedule. What is added here is the sentence that says why the reader is
looking at a section, in this household's own terms -- the thing a human writer adds and a rule cannot. It may
not add a figure, a section, an ordering or a conclusion, and it is structurally unable to change any of those,
because it is handed one section's facts and its output goes into one paragraph slot.

**Every draft is verified against that section's own facts, and only that section's.** `prose.write_prose`
verifies against the whole `ReportFacts`; this verifies per section, which is strictly tighter. A sentence about
the balance sheet that quotes the pension annuity is rejected here and would pass there. That is deliberate: the
failure mode observed in this repo is not invention out of nothing, it is a correct figure attached to the wrong
label -- 800 000 of debt called *das Eigenkapital* -- and a narrow allowed set is what catches it.

**A refusal costs nothing.** No slot is required. If the daemon is down, the model wanders, or a figure cannot
be traced, the section keeps the deterministic text it already had. That is why the model is allowed near this
at all: the worst outcome is the report as it was.

**K2 by construction, and gated accordingly.** This reads a household's computed position, so unlike the book
coach it is not K0 and must run inside the core perimeter. It reaches `127.0.0.1` only, like every other model
call here.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from coach import swiss_ss  # noqa: E402  one implementation of the house orthography, not three
from prose import MODEL, OLLAMA, _readings  # noqa: E402  the verifier is not reimplemented here

#: Shorter than `prose.TIMEOUT_S`. Each of these is two or three sentences rather than four paragraphs, and
#: several run in a row: a per-section budget that adds up to more than a reader will wait is not a budget.
TIMEOUT_S = 60

#: How many times a section is redrafted when a figure cannot be traced. **Hallucination here is occasional and
#: stochastic**, which `prose.py` measured: eight clean drafts and then a fabricated figure on the ninth. So the
#: response to a failed check is to redraft, not to publish nothing and not to publish the draft.
ATTEMPTS = 2

SYSTEM = """Du schreibst EINEN Absatz für einen Abschnitt eines Schweizer Finanzbefundes.

Der Abschnitt enthält bereits Tabellen und Zahlen. Deine Aufgabe ist der verbindende Satz: was der Leser hier
sieht und warum es zählt. Zwei bis drei Sätze, Fliesstext, Deutsch, sachlich.

REGELN ohne Ausnahme:
1. Nur die unten übergebenen Zahlen, und jede mit ihrer RICHTIGEN Bezeichnung. Schulden sind Schulden, nicht
   Eigenkapital. Vermietetes ist nicht selbst genutzt. Eine Rente ist kein Kapital.
2. Lieber ein Wort als eine Zahl: "gut die Hälfte", "die bindende Grösse", "knapp darunter". Der Leser hat die
   Tabelle vor sich.
3. KEINE Empfehlung. Kein "Sie sollten", kein "wir empfehlen", keine Anlage, kein Produkt.
4. Nur dieser Haushalt. Kein Vergleich mit anderen Fällen, Durchschnitten oder Klienten.
5. Behaupte nichts, was nicht dasteht: kein Beruf, keine Familie, keine Absicht, keine Nationalität.
6. Keine Aufzählung, keine Nummerierung, keine Überschrift. Nur der Absatz.
"""

#: Which sections may carry a model paragraph, what it is asked to say, and which part of the quantities it may
#: draw on. **A closed list, and a section absent from it silently gets no prose** -- which is the safe
#: direction: a new section added to the renderer does not automatically acquire a generated sentence.
#:
#: `plan` is deliberately NOT here. That section carries the M79 refusal and the achievable measurement, and
#: both are sentences whose exact wording is the compliance boundary between a Befund and a Recommendation.
#: Those are not paraphrased by a model.
SLOTS: dict[str, dict[str, str]] = {
    "balance": {
        "key": "balance",
        "ask": "Beschreibe, wie sich dieses Vermögen zusammensetzt und was davon tatsächlich verfügbar ist. "
               "Der Punkt ist der Unterschied zwischen Vermögen und entnahmefähigem Vermögen.",
    },
    "cash_flow": {
        "key": "cash_flow",
        "ask": "Beschreibe, was dieser Haushalt pro Jahr erzeugt und was davon nach allen genannten Kosten "
               "übrig bleibt. Wenn ein Betrag frei bleibt, ohne einer Verwendung zugeordnet zu sein, ist das "
               "der Kern des Abschnitts.",
    },
    "income_65": {
        "key": "income_65",
        "ask": "Beschreibe, welche Zuflüsse ab der Referenzaltersgrenze bestehen, ohne dass jemand etwas "
               "entscheidet, und woraus sie kommen.",
    },
    "gap": {
        "key": "gap",
        "ask": "Beschreibe das Verhältnis zwischen dem Ausgabenziel und diesen Zuflüssen, und was daraus für "
               "den Kapitalbedarf folgt. Wenn keine Lücke besteht, sage das.",
    },
    "health": {
        "key": "health",
        "ask": "Beschreibe, warum die Arbeitszeit in diesem Modell eine Finanzgrösse ist und was der Verlauf "
               "über den Horizont bedeutet.",
    },
    "bridge": {
        "key": "bridge",
        "ask": "Beschreibe die Jahre zwischen dem Ausstieg und der Referenzaltersgrenze: was sie kosten, "
               "woraus sie gedeckt werden, und was der frühere Ausstieg dauerhaft kostet.",
    },
    "levers": {
        "key": "levers",
        "ask": "Beschreibe, welche dieser Grössen am stärksten wirkt und warum die Einheiten nicht dieselben "
               "sind. Nenne keine Empfehlung, nur die Rangfolge und ihren Grund.",
    },
}


@dataclass
class Slot:
    """One section's generated paragraph, and everything a reader needs to judge it."""

    section: str
    text: str = ""
    model: str = ""
    refused: str = ""
    unverified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text) and not self.unverified and not self.refused


def _numbers_in(node: Any, out: set[float], depth: int = 0) -> None:
    """Every number reachable in one section's facts, at every scale prose legitimately uses."""
    if depth > 6:
        return
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, (int, float)):
        f = abs(float(node))
        out |= {f, float(round(f)), round(f, 1), round(f, 2)}
        if f <= 1.0001:
            out |= {100 * f, float(round(100 * f)), round(100 * f, 1)}
        if f >= 1000:
            out |= {f / 1000, float(round(f / 1000)), round(f / 1000, 1),
                    f / 1_000_000, round(f / 1_000_000, 1), round(f / 1_000_000, 2)}
        return
    if isinstance(node, dict):
        for v in node.values():
            _numbers_in(v, out, depth + 1)
    elif isinstance(node, list):
        for v in node[:200]:
            _numbers_in(v, out, depth + 1)


def allowed_values(section_facts: Any) -> set[float]:
    """What this section's paragraph may quote. Narrower than `prose._allowed_values`, on purpose."""
    out: set[float] = set()
    _numbers_in(section_facts, out)
    # Counting and dates are ordinary prose, not claims about money. Ages and small counts live here too.
    out |= {float(i) for i in range(0, 101)}
    out |= {float(y) for y in range(1950, 2101)}
    return out


def unverified_numbers(text: str, section_facts: Any) -> list[str]:
    """Figures in `text` not traceable to this section. Reuses `prose`'s reading logic, not a second copy."""
    from prose import _NUMBER_RE  # noqa: PLC0415 - kept next to its use, it is a private detail there
    allowed = allowed_values(section_facts)
    bad: list[str] = []
    for tok in re.findall(_NUMBER_RE, text):
        readings = _readings(tok)
        if not readings:
            continue
        if any(abs(r - a) <= max(0.01 * max(abs(r), abs(a)), 1e-9)
               for r in readings for a in allowed):
            continue
        bad.append(tok.strip())
    return sorted(set(bad))


_BANNED = (
    # A Recommendation needs a named Curator and a Decision Record (G7). These phrases make one, whatever
    # the surrounding sentence says, so a draft containing them is discarded rather than edited.
    "sie sollten", "wir empfehlen", "ich empfehle", "empfehlenswert", "raten wir",
    "sie müssen", "am besten wäre", "ratsam",
)

#: **Currencies that are not this one.** The number verifier cannot catch a unit error: "130 000 EURO" quotes a
#: figure that IS in the facts, in a currency that is not, and passes every numeric check. The very first live
#: draft did exactly that. Every figure in this system is Swiss francs, so naming any other currency is a
#: factual error and the draft is discarded.
_WRONG_CURRENCY = ("euro", "€", "eur ", "dollar", "usd", "us-dollar", "pfund", "gbp", "yen")

#: Fragments of the prompt's own scaffolding. A draft that echoes them is a draft that treated the instructions
#: as content, and it reads as broken to any reader.
_ECHOES = ("abschnitt:", "aufgabe:", "fakten dieses abschnitts", "regeln ohne ausnahme", "json)")


def _reject(text: str, facts: Any) -> str:
    """Why this draft cannot be used, or an empty string. Checks the verifier cannot express.

    **Each of these was earned by an observed draft, not anticipated.** The first live run produced a paragraph
    that was in EUR, in capitals, and opened by repeating its own section header -- three faults, none of them
    a number the verifier could question. A generated sentence is only safe when the ways it can be wrong
    without being numerically wrong are enumerated too.
    """
    low = text.lower()
    hit = next((b for b in _BANNED if b in low), None)
    if hit:
        return f"der Entwurf enthielt eine Empfehlung ({hit!r})"
    cur = next((c for c in _WRONG_CURRENCY if c in low), None)
    if cur:
        return f"der Entwurf nannte eine falsche Währung ({cur.strip()!r}); gerechnet wird in Franken"
    echo = next((e for e in _ECHOES if e in low), None)
    if echo:
        return f"der Entwurf hat die Anweisung wiederholt ({echo!r})"
    letters = [c for c in text if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.5:
        return "der Entwurf war in Grossbuchstaben"
    words = len(text.split())
    if words < 12:
        return f"der Entwurf war zu kurz ({words} Wörter)"
    if words > 140:
        return f"der Entwurf war zu lang ({words} Wörter); verlangt sind zwei bis drei Sätze"
    return ""


def _ask_model(section: str, ask: str, facts: Any, *, model: str, base: str,
               timeout: float) -> tuple[str, str]:
    """One draft. Returns (text, refusal). Never raises: a model failure is not a report failure."""
    # **Written as one instruction rather than as labelled fields.** The first version used headed blocks --
    # ABSCHNITT, AUFGABE, FAKTEN -- and the model opened its reply by repeating them, because a form invites a
    # form back. The currency is stated because the model cannot read it off a bare number, and its first
    # draft guessed euros.
    prompt = (
        f"{ask}\n\n"
        f"Alle Beträge sind Schweizer Franken. Schreibe zwei bis drei Sätze Fliesstext, beginne direkt mit "
        f"dem ersten Satz, ohne Überschrift und ohne diese Anweisung zu wiederholen.\n\n"
        f"Die Zahlen:\n"
        f"{json.dumps(facts, ensure_ascii=False, indent=1, default=str)[:6000]}\n"
    )
    body = json.dumps({"model": model, "system": SYSTEM, "prompt": prompt, "stream": False,
                       "options": {"temperature": 0.2, "num_predict": 220}}).encode("utf-8")
    req = urllib.request.Request(f"{base}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return "", f"das lokale Modell ist nicht erreichbar: {exc}"
    except json.JSONDecodeError as exc:
        return "", f"die Antwort des Modells war nicht lesbar: {exc}"
    text = (payload.get("response") or "").strip()
    # Models like to open with a heading or a bullet even when told not to. Stripping is cheaper than
    # redrafting and changes no claim.
    text = re.sub(r"^\s*(#+|[-*•])\s*", "", text, flags=re.M).strip()
    if not text:
        return "", "das Modell hat nichts geschrieben"
    # Swiss orthography, applied here rather than hoped for from the prompt. The model writes reichsdeutsch
    # German because that is its training data: a live draft produced "fliesst" as "fließt", inside a report
    # whose every other line is Swiss.
    return swiss_ss(text), ""


def write_slot(section: str, facts: Any, *, model: str = MODEL, base: str = OLLAMA,
               timeout: float = TIMEOUT_S, attempts: int = ATTEMPTS) -> Slot:
    """One section's paragraph, verified. A `Slot` whose `ok` is False must not be rendered."""
    spec = SLOTS.get(section)
    if spec is None:
        return Slot(section, refused="dieser Abschnitt hat keinen Prosa-Platz")
    if not facts:
        return Slot(section, refused="dieser Abschnitt hat keine Fakten")

    last = Slot(section, refused="kein Versuch gelaufen")
    for _ in range(max(1, attempts)):
        text, refusal = _ask_model(section, spec["ask"], facts,
                                   model=model, base=base, timeout=timeout)
        if refusal:
            return Slot(section, refused=refusal, model=model)
        why = _reject(text, facts)
        if why:
            last = Slot(section, refused=why, model=model)
            continue
        bad = unverified_numbers(text, facts)
        last = Slot(section, text=text, model=model, unverified=bad)
        if not bad:
            return last
    return last


def write_all(quantities: dict, *, model: str = MODEL, base: str = OLLAMA,
              timeout: float = TIMEOUT_S) -> dict[str, Slot]:
    """A paragraph per eligible section. Sections whose slot is not `ok` are simply absent from the result.

    Sequential rather than concurrent: one local model on one machine, and eight parallel requests to it are
    slower than eight in a row plus a queue nobody can see.
    """
    out: dict[str, Slot] = {}
    for section, spec in SLOTS.items():
        facts = quantities.get(spec["key"])
        if not facts:
            continue
        slot = write_slot(section, facts, model=model, base=base, timeout=timeout)
        if slot.ok:
            out[section] = slot
        # A daemon that is unreachable will be unreachable for every remaining section too, and eight
        # timeouts in a row is eight minutes of a reader waiting for nothing.
        elif "nicht erreichbar" in slot.refused:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    """`python desktop/sectionprose.py --in quantities.json` prints each slot and its verdict."""
    import argparse
    ap = argparse.ArgumentParser(description="Draft the connective prose for one household's sections.")
    ap.add_argument("--in", dest="infile", required=True)
    ap.add_argument("--section", help="just this one")
    args = ap.parse_args(argv)
    q = json.loads(Path(args.infile).read_text(encoding="utf-8-sig"))
    names = [args.section] if args.section else list(SLOTS)
    for name in names:
        spec = SLOTS.get(name)
        slot = write_slot(name, q.get(spec["key"]) if spec else None)
        print(f"--- {name}: {'OK' if slot.ok else 'ABGELEHNT'}")
        if slot.refused:
            print(f"    {slot.refused}")
        if slot.unverified:
            print(f"    nicht belegte Zahlen: {slot.unverified}")
        if slot.text:
            print(f"    {slot.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
