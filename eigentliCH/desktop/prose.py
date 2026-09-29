"""Task P5: a local model writes the report's prose. Nothing leaves the machine.

    from prose import write_prose
    result = write_prose(facts)      # facts is a ReportFacts dict from the engine

**The model runs locally, on this machine, through Ollama's HTTP API on 127.0.0.1.** `apertus:8b` is the local
answer model across these projects. Standard library only — `urllib` — so the root environment gains no dependency
and the "nothing leaves this device" promise the onboarding page makes stays literally true.

**M74 is structural here, not editorial.** The prompt is built from the `ReportFacts` dict and from nothing else.
`ReportFacts` has no field able to hold a second household, so a cross-household reference is not merely
forbidden, it is **absent from the context** — and a model cannot leak what it was never given. That is a far
stronger guarantee than instructing a model not to compare, which is the guarantee a human writer had and broke.

**And the model is not trusted with arithmetic.** Every number in the generated text is checked against the facts
it was given: any figure that does not appear there is reported in `unverified_numbers`. This is the part worth
having. A language model asked to describe a financial position will produce plausible figures whether or not it
was given them, and "plausible" is exactly the failure mode that survives review. The schema already draws this
line — *"an LLM that rephrases a question is fine; an LLM that decides what `W_res` means is not"* — and this makes
the line checkable rather than aspirational.

**A Befund is education, not a Recommendation** (G7: a Recommendation needs a named Curator and a Decision
Record). The system prompt says so, and `write_prose` refuses to return text for facts the engine marked
unpublishable — prose over withheld figures would be the report layer arguing with the engine.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OLLAMA = "http://127.0.0.1:11434"
MODEL = "apertus:8b"
#: Generation is slower than a solve is fast. Long enough for a few hundred tokens on CPU, short enough that a
#: hung daemon does not hold the request open indefinitely.
TIMEOUT_S = 240

SYSTEM = """Du bist ein Schweizer Finanz-Analyst und schreibst einen BEFUND — eine Standortbestimmung.

REGELN, die ohne Ausnahme gelten:
1. Verwende AUSSCHLIESSLICH die Zahlen aus den übergebenen Fakten, und verwende sie mit der RICHTIGEN
   Bezeichnung. Schulden sind Schulden, nicht Eigenkapital. Vermietetes ist nicht selbst genutzt. Erfinde
   keine Zahlen und rechne keine neuen aus. Bevorzuge Worte, wo Worte genügen: "knapp verfehlt", "etwa zwei
   Drittel", "die bindende Grösse".
2. Schreibe KEINE Empfehlung. Kein "Sie sollten", kein "wir empfehlen", kein Produkt, keine Allokation als
   Anweisung. Beschreibe die Lage und ihre Mechanik.
3. Sprich nur über DIESEN Haushalt. Vergleiche nicht mit anderen Fällen, Durchschnitten oder Klienten.
4. Behaupte nichts, was nicht in den Fakten steht — keine Nationalität, kein Beruf, keine Familie, keine
   Absichten. Was nicht dasteht, weisst du nicht.
5. Nenne die Warnungen ausdrücklich, wenn es welche gibt. Eine Einschränkung, die wie eine Fussnote klingt,
   wird überlesen.
6. Deutsch, sachlich, ganze Sätze, Fliesstext. Keine Aufzählungszeichen, keine Nummerierung. Höchstens vier
   kurze Abschnitte.
"""


@dataclass
class ProseResult:
    text: str = ""
    model: str = ""
    #: Numbers in the generated text that do not appear in the facts. Non-empty means do not publish the text.
    unverified_numbers: list[str] = field(default_factory=list)
    #: Why no text was produced, when there is none.
    refused: str = ""

    @property
    def ok(self) -> bool:
        """Every figure in the text is traceable to the facts. NOT the same as fit to send to a client."""
        return bool(self.text) and not self.unverified_numbers and not self.refused

    @property
    def client_ready(self) -> bool:
        """Always False, and deliberately so — a property rather than a comment so callers must confront it.

        The number check catches fabricated figures. It cannot catch MISATTRIBUTION, and the local model was
        measured doing exactly that: calling 800 000 of debt "das Eigenkapital in Immobilien". Removing figures
        from the prose would remove the opportunity, and both apertus:8b and qwen2.5:14b ignored that instruction
        in every draft. So this text is a draft for a human who knows what the numbers mean, and the human is
        required anyway: a Recommendation needs a named Curator and a Decision Record (G7).
        """
        return False


def _facts_for_prompt(facts: dict) -> dict:
    """The subset handed to the model. An allow-list, so a field added to `ReportFacts` later cannot silently
    reach the prompt — including one that should not."""
    keys = (
        "age", "net_worth", "total_wealth", "drawable", "liquid", "real_assets", "residence",
        "let_property", "debt", "pillar2", "pillar3a",
        "goal_kind", "goal_horizon_years", "deadline_age", "required_confidence",
        "p_goal", "meets_target", "binding_constraint", "exchange_rate_winner",
        "work_hours_per_week", "saving_rate", "fi_requirement",
    )
    out = {k: facts.get(k) for k in keys if facts.get(k) is not None}
    out["warnings"] = [w.get("message", "") for w in (facts.get("warnings") or [])]
    return out


#: How a number is recognised in prose. Two alternatives, and the order matters.
#:
#: 1. Space-separated thousands, where each separator MUST be followed by exactly three digits.
#: 2. Everything else: apostrophe thousands, and a dot or comma as either separator.
#:
#: Whitespace is deliberately NOT a general member of the character class. It was, and "400.000, 83 %" then
#: matched as a single token -- which passed verification only because 400 000.83 is within one per cent of
#: 400 000. A tokeniser that merges across a list separator can let an invented figure through by the same
#: coincidence that made this one look correct.
_NUMBER_RE = (
    r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?"
    r"|\d+(?:[.,'\u2019]\d+)*"
)


def _readings(tok: str) -> set[float]:
    """Every plausible numeric reading of one token. **German and Swiss formatting are genuinely ambiguous.**

    `400.000` means four hundred thousand in German and four-tenths in English. `1,6` means one-point-six in
    German. `1’600’000` is Swiss thousands. A verifier that picks one convention rejects correct prose, and
    the first live run of the real model proved it: the model wrote a faithful "CHF 1,6 Millionen" for 1 600 000
    and the check called it invented.

    So every reading is generated and a figure is accepted if ANY of them matches. Deliberately permissive: a
    false positive blocks a correct report, while a genuinely invented figure matches no reading of any fact.
    """
    t = tok.strip()
    for ch in ("'", "’", " ", " ", " "):
        t = t.replace(ch, "")
    t = t.strip(".,")
    if not t:
        return set()
    out: set[float] = set()
    for variant in (
        t,                                     # as written
        t.replace(",", "."),                   # comma as decimal separator
        t.replace(".", "").replace(",", "."),  # dot as thousands, comma as decimal
        t.replace(",", "").replace(".", ""),   # both as thousands separators
        t.replace(",", ""),                    # comma as thousands
    ):
        try:
            out.add(float(variant))
        except ValueError:
            continue
    return out


def _allowed_values(facts: dict) -> set[float]:
    """Every value the model may legitimately write, as floats in all the scales prose uses.

    "1.6 Millionen" for 1 600 000 is prose, not a hallucination, so thousands and millions are allowed; a share
    may appear as its percentage, because the report will say "83 %" for a `p_goal` of 0.83.
    """
    allowed: set[float] = set()
    for v in _facts_for_prompt(facts).values():
        if isinstance(v, (list, dict, str, bool)) or v is None:
            continue
        try:
            f = abs(float(v))
        except (TypeError, ValueError):
            continue
        allowed |= {f, float(round(f)), round(f, 1), round(f, 2)}
        if f <= 1.0001:
            allowed |= {100 * f, float(round(100 * f)), round(100 * f, 1)}
        if f >= 1000:
            allowed |= {f / 1000, float(round(f / 1000)), round(f / 1000, 1),
                        f / 1_000_000, round(f / 1_000_000, 1), round(f / 1_000_000, 2)}
    # Ordinary prose counts things and cites years. Neither is a claim about this household's money.
    allowed |= {float(i) for i in range(0, 101)}
    allowed |= {float(y) for y in range(1950, 2101)}
    return allowed


def verify_numbers(text: str, facts: dict) -> list[str]:
    """Numbers in `text` that are not traceable to `facts`. Empty means every figure came from the engine.

    Compared NUMERICALLY rather than as strings, with a 1% relative tolerance, so a rounded figure passes and a
    different one does not: 1.6 against 1 600 000 matches at some scale, 1.75 is nine per cent away and does not.
    """
    allowed = _allowed_values(facts)
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

def write_prose(facts: dict, *, model: str = MODEL, timeout: float = TIMEOUT_S,
                base: str = OLLAMA, attempts: int = 3) -> ProseResult:
    """Ask the local model to describe this household, retrying while a draft contains an untraceable figure.

    **`attempts` exists because hallucination here is occasional and stochastic, which is measurable rather than
    assumed.** Over eight drafts of the same facts, eight were clean; a ninth run in the test suite fabricated a
    "35'200" that appears nowhere in the facts. So the right response to a failed check is to regenerate, not to
    publish nothing — and not to publish the draft either.

    Returns the first clean draft. If every attempt contains an untraceable figure, returns the LAST one with
    `unverified_numbers` populated, so `ok` is False and the caller can show the reason rather than the prose.
    """
    if not facts.get("publishable", False):
        # The engine withheld its figures. Prose over withheld figures would be the report layer arguing with
        # the engine about what it stands behind.
        return ProseResult(refused="the engine marked these figures unpublishable, so there is nothing to "
                                   "describe: a blocking warning means the solve did not finish")

    last = ProseResult(refused="no attempt was made")
    for _ in range(max(1, attempts)):
        last = _one_draft(facts, model=model, timeout=timeout, base=base)
        if last.refused or not last.unverified_numbers:
            return last
    return last


def _one_draft(facts: dict, *, model: str, timeout: float, base: str) -> ProseResult:
    """A single generation, verified. `write_prose` decides whether to accept it."""
    prompt = ("Fakten zu diesem Haushalt (JSON):\n"
              + json.dumps(_facts_for_prompt(facts), ensure_ascii=False, indent=2)
              + "\n\nSchreibe den Befund.")
    body = json.dumps({
        "model": model,
        "system": SYSTEM,
        "prompt": prompt,
        "stream": False,
        # Low temperature: this is description, not composition, and a creative model invents figures.
        "options": {"temperature": 0.2, "num_predict": 700},
    }).encode("utf-8")

    req = urllib.request.Request(f"{base}/api/generate", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read())
    except urllib.error.URLError as exc:
        return ProseResult(refused=f"the local model is not reachable at {base} ({exc.reason}). "
                                   f"Ollama must be running and '{model}' pulled.")
    except (TimeoutError, OSError) as exc:
        return ProseResult(refused=f"the local model did not answer within {timeout:.0f}s ({exc})")
    except json.JSONDecodeError as exc:
        return ProseResult(refused=f"the local model returned unreadable output ({exc})")

    text = (payload.get("response") or "").strip()
    if not text:
        return ProseResult(refused="the local model returned no text")
    # **What this check does and does not catch, measured rather than assumed.**
    #
    # It catches FABRICATION: a figure with no relation to the facts. apertus:8b does this occasionally — eight
    # drafts clean, a ninth inventing a "35'200" — so the check is load-bearing and `attempts` exists to
    # regenerate rather than publish nothing.
    #
    # It does NOT catch MISATTRIBUTION, and the live model demonstrated the difference immediately: it wrote
    # "das Eigenkapital in Immobilien (CHF 800,000)" where 800 000 is the DEBT. Every figure verified, because
    # every figure came from the facts. Only the labels were wrong — which is the failure that looks checked.
    #
    # Forbidding figures outright would remove the opportunity, and that was tried: **both apertus:8b and
    # qwen2.5:14b ignored "schreibe keine Ziffern" in every draft** (5 of 5 and 2 of 2, six to nine numerals
    # each). So it is not a prompt to be tuned; a local model of this size cannot be held to it.
    #
    # Therefore this prose is an ADVISER DRAFT, not client-facing output — see `ProseResult.client_ready`.
    #
    # Swiss orthography last, and verified AFTER it: the eszett substitution cannot change a digit, so the
    # check reads the same text the reader will. `coach.swiss_ss` is imported rather than repeated, because
    # three copies of one substitution is three places for one of them to be forgotten.
    from coach import swiss_ss  # noqa: PLC0415 - local, to keep this module importable without the index
    text = swiss_ss(text)
    return ProseResult(text=text, model=model, unverified_numbers=verify_numbers(text, facts))
