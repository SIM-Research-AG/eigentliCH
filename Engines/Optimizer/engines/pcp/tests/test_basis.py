"""The nominal and real view (REAL_VIEW_INTERFACES.md, PCP-22): the mandate's optional ``basis`` is the basis
of its target curve, pcp asks fmre for the ReturnSet on it, refuses a set on another basis (a set that states
none is nominal), and the Allocation states it. A nominal mandate is byte for byte what it was before."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcp.contracts import Allocation, Mandate, ReturnSet
from pcp.service import mandate_id, served_basis

from .conftest import _client, real_return_set_id, run_body, stamped_return_set

#: Measured on pcp@1.2.0 before the basis existed (29.09.2026), on the ``mandate()`` fixture against the
#: stand-in: the ids a nominal mandate without ``basis`` must keep. The artefact id moves with the engine
#: version or the frozen inputs, deliberately; the other two only with the engine or contract versions.
BEFORE = {"mandate_id": "MAN-495131576599f3ef", "idempotency_key": "IDK-12c65e46ac6ebac6",
          "artefact_id": "PCP-3b5156f678fcb720"}


def _rs(**kw) -> ReturnSet:
    return ReturnSet.model_validate_json(stamped_return_set(**kw))


def test_the_mandate_takes_nominal_or_real_and_defaults_to_nominal(mandate):
    assert Mandate.model_validate(mandate()).basis == "nominal"
    assert Mandate.model_validate(mandate(basis="real")).basis == "real"
    for bad in ("Real", "", None, "hard"):
        with pytest.raises(ValidationError, match="not one of nominal, real"):
            Mandate.model_validate(mandate(basis=bad))


def test_a_nominal_mandate_keeps_its_bytes_and_its_id(mandate):
    plain, explicit = Mandate.model_validate(mandate()), Mandate.model_validate(mandate(basis="nominal"))
    assert "basis" not in plain.model_dump(mode="json") and "basis" not in plain.model_dump_json()
    assert mandate_id(plain) == mandate_id(explicit) == BEFORE["mandate_id"]
    real = Mandate.model_validate(mandate(basis="real"))
    assert real.model_dump(mode="json")["basis"] == "real" and mandate_id(real) != BEFORE["mandate_id"]


def test_the_served_basis_is_nominal_unless_the_set_states_real():
    assert served_basis(_rs()) == "nominal"                     # no provenance.basis: nominal
    assert served_basis(_rs(basis="nominal")) == "nominal"
    assert served_basis(_rs(basis="real")) == "real"


def test_a_nominal_run_gives_the_same_request_and_artefact_as_before(settings, mandate):
    seen: list[dict] = []
    with _client(settings, None, seen) as c:
        for body in (mandate(), mandate(basis="nominal")):
            r = c.post("/run", json=run_body(body)).json()
            assert r["status"] == "succeeded", c.get(f"/runs/{r['run_id']}").json()["error"]
            assert r["idempotency_key"] == BEFORE["idempotency_key"]
            assert r["artefact_id"] == BEFORE["artefact_id"]
        assert seen and all("basis" not in q for q in seen)         # the query fmre saw before the real view
        a = c.get(f"/allocation/{r['artefact_id']}").json()
        assert "basis" not in a and "basis" not in a["provenance"] and "fmre:basis" not in a["provenance"]["upstream"]
        assert Allocation.model_validate(a).basis == "nominal"      # a body without basis reads as nominal
        v = c.post("/validate", json=run_body(mandate())).json()
        assert v["ok"] and v["basis"] == "nominal" and "basis" not in seen[-1]


def test_the_return_set_is_requested_on_the_mandates_basis(settings, mandate):
    seen: list[dict] = []
    with _client(settings, None, seen) as c:
        v = c.post("/validate", json=run_body(mandate(basis="real"), return_set_id=real_return_set_id())).json()
        assert v["ok"] and v["basis"] == "real", v["problems"]
        assert seen[-1]["basis"] == "real" and seen[-1]["currency"] == "CHF"
        # the nominal id names the nominal set: a real mandate must send the real one
        v = c.post("/validate", json=run_body(mandate(basis="real"))).json()
        assert not v["ok"] and "fmre serves ReturnSet " + real_return_set_id() in v["problems"][0]


def test_the_allocation_states_real_and_the_basis_enters_the_key(client, mandate):
    nominal = client.post("/run", json=run_body(mandate(name="basis"))).json()
    real = client.post("/run", json=run_body(mandate(name="basis", basis="real"),
                                             return_set_id=real_return_set_id())).json()
    for r in (nominal, real):
        assert r["status"] == "succeeded", client.get(f"/runs/{r['run_id']}").json()["error"]
    a = client.get(f"/allocation/{real['artefact_id']}").json()
    assert a["basis"] == "real" and a["provenance"]["basis"] == "real"
    assert a["provenance"]["upstream"]["fmre:basis"] == "real"
    assert a["provenance"]["upstream"]["fmre:deflator"].startswith("CHF CPI")
    assert a["return_set_id"] == real_return_set_id() and a["curves"]["target"] == [0.02] * 25
    assert any("real basis" in w and "measured 22" in w for w in a["coverage"]["warnings"])
    assert Allocation.model_validate(a).basis == "real"
    assert real["idempotency_key"] != nominal["idempotency_key"]
    assert real["artefact_id"] != nominal["artefact_id"]
    n = client.get(f"/allocation/{nominal['artefact_id']}").json()
    assert "basis" not in n
    # deflating lowers every profile, so the same weights achieve less; the fit is on the real curve
    assert a["diagnostics"]["objective"] != n["diagnostics"]["objective"]


@pytest.mark.parametrize("mandate_basis, served, why", [
    ("real", None, "on the nominal basis, not the mandate's real; the target curve is real"),
    ("real", "nominal", "on the nominal basis, not the mandate's real"),
    ("nominal", "real", "on the real basis, not the mandate's nominal"),
])
def test_a_return_set_on_another_basis_is_refused(settings, mandate, mandate_basis, served, why):
    rs = stamped_return_set(basis=served)
    rs_id = real_return_set_id() if served == "real" else None
    body = run_body(mandate(name=f"basis-{served}", basis=mandate_basis),
                    **({"return_set_id": rs_id} if rs_id else {}))
    with _client(settings, rs) as c:
        v = c.post("/validate", json=body).json()
        assert v["ok"] is False and why in v["problems"][0] and "PCP-22" in v["problems"][0]
        if served is None:
            assert "states no basis on this set, which counts as nominal" in v["problems"][0]
        r = c.post("/run", json=body).json()
        assert r["status"] == "failed" and r["artefact_id"] is None
        assert why in c.get(f"/runs/{r['run_id']}").json()["error"]


def test_a_real_set_with_a_state_not_computable_is_refused(settings, mandate):
    deflator = {"currency": "CHF", "index": "CPI", "method": "m",
                "labels": ["measured"] * 24 + ["not_computable"], "hard_currency_fallback": None}
    with _client(settings, stamped_return_set(basis="real", deflator=deflator)) as c:
        v = c.post("/validate", json=run_body(mandate(basis="real"), return_set_id=real_return_set_id())).json()
        assert not v["ok"] and "not_computable" in v["problems"][0]


def test_a_hard_currency_fallback_is_reported_not_hidden(settings, mandate):
    """PCP-23 replaced PCP-22's interim "reported, not refused": a fallback from EUR is accepted, and reported,
    on an EUR mandate (``tests/test_fallback.py``); on this CHF mandate it does not match and is refused."""
    deflator = {"currency": "CHF", "index": "CPI", "method": "m", "labels": ["measured"] * 25,
                "hard_currency_fallback": {"from": "EUR", "to": "CHF", "states": [1, 2],
                                           "reason": "outside the band"},
                "scenario": None, "curves": []}
    with _client(settings, stamped_return_set(basis="real", deflator=deflator)) as c:
        v = c.post("/validate", json=run_body(mandate(basis="real"), return_set_id=real_return_set_id())).json()
        assert not v["ok"] and "from EUR, not from the mandate's CHF" in v["problems"][0]
        v = c.post("/validate", json=run_body(mandate(basis="real", currency="EUR"),
                                              return_set_id=real_return_set_id())).json()
        assert v["ok"], v["problems"]
        assert any("hard-currency fallback EUR to CHF, states [1, 2]: outside the band" in n for n in v["notes"])


def test_fmres_not_computable_answer_is_a_refusal_with_its_reason(settings, mandate):
    reason = "CHF and USD inflation both outside -20 % to +100 % in state 1"
    with _client(settings, None, not_computable=reason) as c:
        body = run_body(mandate(name="basis-nc", basis="real"), return_set_id=real_return_set_id())
        v = c.post("/validate", json=body).json()
        assert not v["ok"] and "not_computable" in v["problems"][0] and reason in v["problems"][0]
        r = c.post("/run", json=body).json()
        assert r["status"] == "failed" and reason in c.get(f"/runs/{r['run_id']}").json()["error"]
        assert c.post("/validate", json=run_body(mandate())).json()["ok"]     # nominal is untouched
