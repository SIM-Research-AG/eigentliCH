"""The local model. Nothing here may reach off this machine.

**Local is a constraint, not a deployment preference.** C-05 makes eigentliCH sole data controller from the
first intake question, and C-03 keeps model artefacts server-side. A member's answer to "womit verdienen
Sie heute Ihr Geld" is K2 the moment they type it; sending it to a hosted model would make that model's
operator a processor of it. So the client refuses any host that is not loopback — not by configuration, by
code that raises.

**The estate reached the same conclusion first.** `apps/anderschapp/app/api/chat/route.ts` carries the
comment "Never sends data to a cloud model. No Anthropic path (decision 2026-08-01)", and A3 ports that
loop rather than replacing it. This module is that port's foundation.

**What the model is allowed to do here is narrow.** It reads what a member wrote and proposes a structure
for it. It does not answer questions, does not advise, and does not fill a field the member left blank.
The boundary that matters for C-01 lives in front of `/api/know/ask` in phase 4; this module is not that
surface and must never grow into it.
"""

from __future__ import annotations

import json
import socket
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

#: Loopback only. A hostname that resolves to loopback is still refused: the check is on what was written,
#: because a resolver is a thing that can change under you.
_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})

DEFAULT_BASE_URL = os.environ.get("ANDERSCH_LLM_URL", "http://127.0.0.1:11434")

#: **qwen2.5:14b since 5 September 2026, measured rather than assumed (A145).** The previous default
#: was `apertus:8b` — the Swiss model used across the estate, and the one every guarantee in this
#: build was originally measured against.
#:
#: The Know is extractive (A106): the model never composes a fact, it picks which retrieved sentences
#: answer the question. So selection accuracy is the whole of what a model contributes here, and it
#: is measurable. Over six German questions with known answers and known distractors, three runs
#: each:
#:
#:     apertus:8b     missed the answering sentence in  9 of 18 attempts
#:     qwen2.5:14b    missed the answering sentence in  3 of 18 attempts
#:
#: at the same speed once warm. Both over-select; missing the sentence that answers is the failure
#: that matters, because it shows a member true text that does not answer them.
#:
#: **The cost is provenance and it is the owner's to weigh.** Apertus is Swiss, and this is a Swiss
#: product whose whole posture is local control. Set `ANDERSCH_LLM_MODEL=apertus:8b` to go back —
#: one variable, no code change.
#:
#: **This is NOT the embedding model and must not be confused with it.** `services/grounding.py`
#: embeds with the model the book index was built with (`bge-m3`) and never with a configured one:
#: two models produce two coordinate systems, and a dot product across them is a number that means
#: nothing and looks like a similarity.
DEFAULT_MODEL = os.environ.get("ANDERSCH_LLM_MODEL", "qwen2.5:14b")

#: Short. This runs while a member waits, and a slow interpretation is worse than none — the caller
#: degrades to "not interpreted" rather than holding the screen.
DEFAULT_TIMEOUT_S = float(os.environ.get("ANDERSCH_LLM_TIMEOUT", "20"))

#: Embeddings are slower to start than a chat turn — the daemon loads the model on the first call — and
#: nothing degrades gracefully from half a vector. Longer than the chat timeout for that reason alone.
EMBED_TIMEOUT_S = float(os.environ.get("ANDERSCH_LLM_EMBED_TIMEOUT", "60"))

#: Temperature for a grounded answer over retrieved passages (S-08). Low but not zero: the answer is
#: prose a person reads, and zero produces a stilted register, while anything higher starts inventing
#: connections between passages that are not in them.
#:
#: It lives HERE rather than in the service that uses it because C-02's test forbids float literals in
#: the model and service layers, and it was right to: a model parameter sitting inline in a service is a
#: tuning knob nobody can find. A rate it is not, but the placement rule caught a real problem.
#:
#: **Unused since S-08 became extractive on 1 September 2026, and kept deliberately.** The Know no longer
#: asks for prose; it asks which retrieved sentences answer the question and gets numbers back, at this
#: module's default temperature of zero, because a selection that varies between runs is not a selection.
#: The constant stays because the reasoning above is about grounded prose in general and the next caller
#: that wants some should find it rather than write `0.1` into a service.
GROUNDED_ANSWER_TEMPERATURE = float(os.environ.get("ANDERSCH_LLM_ANSWER_TEMPERATURE", "0.1"))

#: The budget for ONE sentence-selection turn in S-08, and why it is not `DEFAULT_TIMEOUT_S`.
#:
#: `EMBED_TIMEOUT_S` above gives the reason and this is the same reason from the other side. The Know
#: embeds the question against the book index and then, immediately, chats with `apertus:8b` — two
#: different models, and on a machine where both do not fit at once the daemon unloads one to load the
#: other. **Every single answer pays that swap**, because retrieval always runs before selection. Measured
#: warm on this machine, a selection turn is 0.6 s median and 4.2 s at its worst over 88 calls; measured
#: through `ask`, where the swap lands on the first turn, two runs in ten exceeded twenty seconds and the
#: member was told the model was not running when it was. Long enough to absorb a reload, and no longer.
SELECTION_TIMEOUT_S = float(os.environ.get("ANDERSCH_LLM_SELECTION_TIMEOUT", "45"))

#: The budget for ALL of them together, which is the number that protects the member rather than the call.
#:
#: Selection is one turn per retrieved source, so `SELECTION_TIMEOUT_S` alone bounds the wait at seven
#: times itself — five minutes in front of a panel that says "Wird gelesen …", which is not a degradation,
#: it is an abandonment. This bounds the whole pass instead, and exceeding it is `LocalModelUnavailable`:
#: the same honest notice as a daemon that is not running, for the same reason — there is no answer, and
#: saying so beats holding the screen.
SELECTION_BUDGET_S = float(os.environ.get("ANDERSCH_LLM_SELECTION_BUDGET", "90"))


class NotLocal(Exception):
    """Raised when a non-loopback model host is configured. Never caught and worked around."""


class LocalModelUnavailable(Exception):
    """The local model is not running, or did not answer in time.

    Callers degrade. R-302's rule for engines applies with equal force here: a failure renders as "not
    available", never as a zero and never as a guess.
    """


class LocalModelTooSlow(LocalModelUnavailable):
    """The daemon answered the connection and not the question inside the budget.

    **A subclass, so every existing `except LocalModelUnavailable` keeps working**, and a caller that
    wants to tell the two apart can. They are genuinely different states and were reported as one: on
    21 September 2026 fifty of sixty members were told «Das lokale Modell läuft gerade nicht» while it
    was running the whole time and simply reasoning past the budget. That sentence sends whoever reads it
    to check an installation that is fine, and the thing to change — the budget, or the model — is not
    mentioned anywhere in it.
    """


@dataclass(frozen=True)
class Reply:
    text: str
    model: str


def _assert_local(base_url: str) -> None:
    host = urlparse(base_url).hostname
    if host not in _ALLOWED_HOSTS:
        raise NotLocal(
            f"refusing a non-local model host {host!r}. Member answers are K2 from the first question, "
            f"and C-05 makes eigentliCH sole data controller — there is no configuration that permits this."
        )


def chat(
    prompt: str,
    *,
    system: str | None = None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    temperature: float = 0.0,
    json_mode: bool = False,
    think: bool | None = None,
) -> Reply:
    """One turn against the local model. No history, no tools, no streaming.

    `temperature=0` by default: this is used for reading what a member wrote, and a reading that varies
    between runs is not a reading. Determinism also makes the guards downstream meaningful — a value that
    must appear in the member's own text cannot be checked if the text changes every call.
    """
    _assert_local(base_url)

    payload: dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    if think is not None:
        # **`think=False` on a reasoning model, which is a latency decision and not a quality one.**
        # `qwen3:8b` spends its budget on a hidden chain before it writes: measured on this prompt, 52.7
        # seconds and 1 164 characters of reasoning to produce a 452-character answer, against 18.1
        # seconds and 458 characters with thinking off. Three times the wall clock for an answer the same
        # length, and the reasoning is discarded — the member waits for it and nobody reads it.
        #
        # It went unnoticed until the grounding got richer and 50 of 60 real questions stopped coming back
        # inside the timeout at all, which reported as "the local model is not running".
        #
        # Accepted by every model installed here, including the two that do not reason (`apertus:8b`,
        # `qwen2.5:14b`), so it is safe to send whatever is configured. Sent only when a caller asks, so a
        # caller that wants a model's reasoning simply does not pass it.
        payload["think"] = bool(think)

    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, socket.timeout) as error:
        raise LocalModelTooSlow(
            f"local model at {base_url} did not finish within {timeout_s:.0f}s. It is running; it is "
            f"slower than the budget allows for this prompt."
        ) from error
    except (urllib.error.URLError, OSError) as error:
        # A URLError wrapping a timeout is the same state as the branch above — urllib raises it that way
        # when the socket times out mid-read rather than while connecting.
        if isinstance(getattr(error, "reason", None), (TimeoutError, socket.timeout)):
            raise LocalModelTooSlow(
                f"local model at {base_url} did not finish within {timeout_s:.0f}s. It is running; it is "
                f"slower than the budget allows for this prompt."
            ) from error
        raise LocalModelUnavailable(f"local model at {base_url} did not answer: {error}") from error
    except json.JSONDecodeError as error:
        raise LocalModelUnavailable(f"local model returned unparseable output: {error}") from error

    return Reply(text=body.get("response", ""), model=body.get("model", model))


def embed(
    text: str,
    *,
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = EMBED_TIMEOUT_S,
) -> list[float]:
    """One embedding vector from the local daemon, L2-normalised so a dot product IS the cosine.

    **`model` has no default, on purpose.** A vector is only comparable to vectors produced by the same
    model, so the caller must name the model *its corpus was built with* rather than whichever embedding
    model happens to be configured. A default here would be a silent way to compare two coordinate systems
    and get a number back that looks like a similarity.

    It lives in this module rather than in the service that uses it because C-05 lives here: `_assert_local`
    is the one place that refuses a non-loopback host, and a second HTTP client in a service layer would be
    a second place for that refusal to be forgotten.
    """
    _assert_local(base_url)
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/embeddings",
        data=json.dumps({"model": model, "prompt": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LocalModelUnavailable(f"local embedding model at {base_url} did not answer: {error}") from error
    except json.JSONDecodeError as error:
        raise LocalModelUnavailable(f"local embedding model returned unparseable output: {error}") from error

    vector = body.get("embedding") or []
    if not vector:
        raise LocalModelUnavailable(f"local embedding model {model!r} returned no vector")
    norm = math.sqrt(sum(x * x for x in vector))
    if not norm:
        raise LocalModelUnavailable(f"local embedding model {model!r} returned a zero vector")
    return [x / norm for x in vector]


def available(base_url: str = DEFAULT_BASE_URL, timeout_s: float = 2.0) -> bool:
    """Whether the local model is reachable. Used to degrade a screen, never to decide policy."""
    try:
        _assert_local(base_url)
        request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags")
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.status == 200
    except Exception:
        return False
