"""The local model, and the guards that stop it inventing.

**These tests never touch Ollama.** The model is stubbed, so the suite runs on a machine with nothing
installed and stays fast. What is being tested is not whether apertus can read German — it can, and that
was checked by hand against real sentences — but whether the code around it refuses what it must refuse.
That is the part a model upgrade could silently break.
"""

from __future__ import annotations

import pytest

from eigentlich import interpret, llm


class _Stub:
    """Stands in for the local model, returning a fixed body."""

    def __init__(self, body: str, model: str = "stub"):
        self.body = body
        self.model = model
        self.calls: list[dict] = []

    def __call__(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        return llm.Reply(text=self.body, model=self.model)


@pytest.fixture()
def stub(monkeypatch):
    def install(body: str):
        s = _Stub(body)
        monkeypatch.setattr(interpret.llm, "chat", s)
        return s

    return install


# ============================================================ local only


def test_a_non_local_model_host_is_refused():
    """C-05. Member answers are K2 from the first question; there is no configuration that permits this."""
    with pytest.raises(llm.NotLocal):
        llm.chat("anything", base_url="https://api.openai.com")
    with pytest.raises(llm.NotLocal):
        llm.chat("anything", base_url="http://192.168.1.50:11434")


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434"])
def test_loopback_hosts_are_allowed(url):
    llm._assert_local(url)  # does not raise


# ============================================================ extraction is verified


def test_a_year_the_member_did_not_write_is_discarded(stub):
    """The single most important guard here.

    The model is asked to segment a sentence, not to compute. "mit 60 aufhören" plus today's date gives a
    retirement year, and a model that helpfully returns it has invented a fact the member never stated.
    """
    stub('{"name": "aufhören zu arbeiten", "target_year": 2044, "target_amount": null}')
    reading = interpret.interpret_goal("Ich möchte mit 60 aufhören zu arbeiten")
    assert [s.field_name for s in reading.suggestions] == ["name"]
    assert all(s.field_name != "target_year" for s in reading.suggestions)


def test_an_amount_the_member_did_not_write_is_discarded(stub):
    stub('{"name": "Wohneigentum", "target_year": null, "target_amount": 250000}')
    reading = interpret.interpret_goal("Wohneigentum irgendwann")
    assert [s.field_name for s in reading.suggestions] == ["name"]


def test_a_name_not_present_in_the_text_is_discarded(stub):
    """A model that paraphrases has editorialised. Only the member's own words come back."""
    stub('{"name": "Immobilienerwerb", "target_year": null, "target_amount": null}')
    reading = interpret.interpret_goal("Wohneigentum 2031")
    assert not any(s.field_name == "name" for s in reading.suggestions)


def test_swiss_apostrophe_amounts_verify(stub):
    """250'000 and 250000 are one figure written two ways; the guard must see that."""
    stub('{"name": "Wohneigentum", "target_year": 2031, "target_amount": 250000}')
    reading = interpret.interpret_goal("Wohneigentum 2031, etwa 250'000 Eigenkapital")
    values = {s.field_name: s.value for s in reading.suggestions}
    assert values["target_amount"] == 250000
    assert values["target_year"] == 2031


def test_spaced_amounts_verify(stub):
    stub('{"name": "Ferienhaus", "target_year": null, "target_amount": 1000000}')
    reading = interpret.interpret_goal("Ferienhaus, etwa 1 000 000")
    assert any(s.field_name == "target_amount" for s in reading.suggestions)


def test_an_implausible_year_is_discarded(stub):
    stub('{"name": "Ziel", "target_year": 12, "target_amount": null}')
    reading = interpret.interpret_goal("Ziel 12")
    assert not any(s.field_name == "target_year" for s in reading.suggestions)


# ============================================================ degradation and refusal


def test_an_unreachable_model_degrades_rather_than_failing(monkeypatch):
    """R-302's shape: not available, never a zero and never a guess."""
    def boom(*args, **kwargs):
        raise llm.LocalModelUnavailable("nothing listening")

    monkeypatch.setattr(interpret.llm, "chat", boom)
    reading = interpret.interpret_goal("Wohneigentum 2031")
    assert reading.unavailable is True
    assert reading.suggestions == []
    assert reading.as_dict()["interpreted"] is False


def test_non_json_output_yields_nothing(stub):
    """A model that answered in prose has not read anything. Nothing is scraped out of it."""
    stub("Das klingt nach einem guten Ziel! Ich würde vorschlagen...")
    reading = interpret.interpret_goal("Wohneigentum 2031")
    assert reading.suggestions == []


def test_empty_input_does_not_call_the_model(monkeypatch):
    called = []
    monkeypatch.setattr(interpret.llm, "chat", lambda *a, **k: called.append(1))
    assert interpret.interpret_goal("   ").suggestions == []
    assert not called


# ============================================================ never authoritative


def test_every_suggestion_requires_confirmation(stub):
    """R-151's rule: extraction never overwrites what a member entered."""
    stub('{"name": "Wohneigentum", "target_year": 2031, "target_amount": null}')
    payload = interpret.interpret_goal("Wohneigentum 2031").as_dict()
    assert payload["suggestions"]
    assert all(s["requires_confirmation"] is True for s in payload["suggestions"])
    assert all(s["source_span"] for s in payload["suggestions"])


def test_suggestions_carry_the_model_that_made_them(stub):
    """Provenance. 'Which model read this' is answerable a year later or it is not reproducible."""
    stub('{"name": "Wohneigentum", "target_year": null, "target_amount": null}')
    reading = interpret.interpret_goal("Wohneigentum")
    assert reading.suggestions[0].model == "stub"


def test_unknown_questions_get_no_interpretation(stub):
    stub('{"name": "x"}')
    payload = interpret.suggestions_for("employment_magnitude", 92000)
    assert payload["suggestions"] == []


def test_the_model_is_never_asked_a_question(stub):
    """C-01 by construction: this surface segments a sentence, it does not answer one.

    The prompt must contain the member's text and the examples, and must not contain an instruction that
    invites advice. Phase 4's /api/know/ask is where the boundary check lives; this is not that surface
    and must not grow into it.
    """
    s = stub('{"name": "Wohneigentum", "target_year": null, "target_amount": null}')
    interpret.interpret_goal("Wohneigentum")
    system = s.calls[0]["system"].lower()
    assert "erfinde nichts" in system
    assert "keine empfehlung" in system
    assert "rat" in system
