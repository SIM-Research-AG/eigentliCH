"""The hard-currency fallback (owner, 29.09.2026, PCP-23; fmre decision 5): when a real mandate's currency leaves
fmre's -20 % to +100 % inflation band, fmre measures the real set in CHF, then USD, and states it
(``provenance.currency`` the hard currency, ``provenance.deflator.hard_currency_fallback`` ``{from, to, states,
reason}``). pcp accepts such a set only on a real mandate whose currency is the fallback's ``from``, with the
served currency its ``to``, and the Allocation states it; every other currency mismatch stays refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcp.contracts import Allocation

from .conftest import (FALLBACK_STATES, _client, hard_currency_fallback, real_return_set_id, run_body,
                       stamped_return_set)

EUR_TO_CHF = {"EUR": "CHF"}


def _fallback_set(served: str = "CHF", fallback: dict | None = None, deflated_in: str | None = None) -> bytes:
    """A real set measured in ``served`` stating ``fallback`` (as fmre does), served whatever is asked."""
    body = stamped_return_set(currency=served, basis="real", fallback=fallback)
    if deflated_in is not None:
        body = body.replace(f'"currency": "{served}", "index"'.encode(), f'"currency": "{deflated_in}", "index"'.encode(), 1)
    return body


def test_a_real_eur_mandate_on_the_chf_fallback_is_accepted_and_says_so(settings, mandate):
    fb = hard_currency_fallback("EUR", "CHF")
    rs_id = real_return_set_id(fallback=fb)
    seen: list[dict] = []
    with _client(settings, None, seen, hard_currency=EUR_TO_CHF) as c:
        body = run_body(mandate(name="fallback", currency="EUR", basis="real"), return_set_id=rs_id)
        v = c.post("/validate", json=body).json()
        assert v["ok"], v["problems"]
        assert seen[-1]["currency"] == "EUR" and seen[-1]["basis"] == "real"     # asked in the mandate's
        assert v["currency"] == "EUR" and v["hard_currency_fallback"] == fb
        plain = f"real, measured in CHF because EUR inflation left the computable band"
        assert any(n.startswith(plain) and f"states {FALLBACK_STATES}" in n and "PCP-23" in n for n in v["notes"])

        r = c.post("/run", json=body).json()
        assert r["status"] == "succeeded", c.get(f"/runs/{r['run_id']}").json()["error"]
        a = c.get(f"/allocation/{r['artefact_id']}").json()
        assert a["currency"] == "CHF" and a["provenance"]["currency"] == "CHF"       # what the figures are in
        assert a["provenance"]["hard_currency_fallback"] == fb                        # from EUR, the mandate's
        assert a["basis"] == "real" and a["return_set_id"] == rs_id
        up = a["provenance"]["upstream"]
        assert up["fmre:currency"] == "CHF" and up["fmre:hard_currency_fallback"].startswith("EUR to CHF")
        assert any(w.startswith(plain) for w in a["coverage"]["warnings"])
        assert Allocation.model_validate(a).provenance.hard_currency_fallback == fb

        # the fallback enters the key: through fmre's return_set_id, which it moves
        chf = c.post("/run", json=run_body(mandate(name="fallback", currency="CHF", basis="real"),
                                           return_set_id=real_return_set_id())).json()
        assert chf["status"] == "succeeded"
        assert real_return_set_id() != rs_id
        assert chf["idempotency_key"] != r["idempotency_key"] and chf["artefact_id"] != r["artefact_id"]
        n = c.get(f"/allocation/{chf['artefact_id']}").json()
        assert "hard_currency_fallback" not in n["provenance"] and n["currency"] == "CHF"
        assert not any("computable band" in w for w in n["coverage"]["warnings"])


def test_without_the_fallback_a_real_set_in_another_currency_is_refused(settings, mandate):
    with _client(settings, _fallback_set("CHF", None)) as c:
        body = run_body(mandate(name="fb-none", currency="EUR", basis="real"), return_set_id=real_return_set_id())
        v = c.post("/validate", json=body).json()
        assert not v["ok"] and "measured in CHF, not the mandate's EUR" in v["problems"][0]
        assert "PCP-18" in v["problems"][0] and "states no hard-currency fallback" in v["problems"][0]
        r = c.post("/run", json=body).json()
        assert r["status"] == "failed" and r["artefact_id"] is None


@pytest.mark.parametrize("fb, why", [
    (hard_currency_fallback("USD", "CHF"), "from USD, not from the mandate's EUR"),
    (hard_currency_fallback("EUR", "USD"), "to USD, but the set is measured in CHF"),
    ({"from": "EUR", "to": "CHF"}, "lacks ['states', 'reason']"),
], ids=["from-mismatch", "to-mismatch", "incomplete"])
def test_a_fallback_that_does_not_match_is_refused(settings, mandate, fb, why):
    with _client(settings, _fallback_set("CHF", fb)) as c:
        body = run_body(mandate(name="fb-bad", currency="EUR", basis="real"),
                        return_set_id=real_return_set_id(fallback=fb))
        v = c.post("/validate", json=body).json()
        assert not v["ok"] and why in v["problems"][0] and "PCP-23" in v["problems"][0], v["problems"]
        r = c.post("/run", json=body).json()
        assert r["status"] == "failed" and why in c.get(f"/runs/{r['run_id']}").json()["error"]


def test_a_fallback_is_refused_on_a_nominal_mandate_and_when_deflated_elsewhere(settings, mandate):
    fb = hard_currency_fallback("EUR", "CHF")
    with _client(settings, _fallback_set("CHF", fb)) as c:
        v = c.post("/validate", json=run_body(mandate(name="fb-nom", currency="EUR"),
                                              return_set_id=real_return_set_id(fallback=fb))).json()
        assert not v["ok"] and "measured in CHF, not the mandate's EUR" in v["problems"][0]
        assert "real mandate and a real set only (PCP-23)" in v["problems"][0]
    with _client(settings, _fallback_set("CHF", fb, deflated_in="USD")) as c:
        v = c.post("/validate", json=run_body(mandate(name="fb-defl", currency="EUR", basis="real"),
                                              return_set_id=real_return_set_id(fallback=fb))).json()
        assert not v["ok"] and "measured in CHF but deflated in USD" in v["problems"][0]


def test_the_allocation_contract_holds_the_fallback_to_its_currency(client, mandate):
    fb = hard_currency_fallback("EUR", "CHF")
    r = client.post("/run", json=run_body(mandate(name="fb-contract", basis="real"),
                                          return_set_id=real_return_set_id())).json()
    a = client.get(f"/allocation/{r['artefact_id']}").json()
    assert "hard_currency_fallback" not in a["provenance"]
    a["provenance"]["hard_currency_fallback"] = fb
    assert Allocation.model_validate(a).provenance.hard_currency_fallback == fb      # real, to CHF: holds
    for bad, why in [({**fb, "to": "USD"}, "is the Allocation's currency"),
                     ({**fb, "from": "CHF"}, "to itself"),
                     ({**fb, "from": "GBP"}, "outside CHF, EUR, USD")]:
        a["provenance"]["hard_currency_fallback"] = bad
        with pytest.raises(ValidationError, match=why):
            Allocation.model_validate(a)
    a["provenance"]["hard_currency_fallback"] = fb
    a.pop("basis"), a["provenance"].pop("basis")                                     # a nominal body
    with pytest.raises(ValidationError, match="real only"):
        Allocation.model_validate(a)
