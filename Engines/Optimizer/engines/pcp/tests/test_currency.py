"""The reporting currency (D-01, PCP-18, PCP-19): the mandate names CHF, EUR or USD, pcp asks fmre for the
ReturnSet measured in it, refuses a set in another currency or in none, and the Allocation states it."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcp.contracts import Mandate, ReturnSet
from pcp.service import served_currency

from .conftest import REGIME_ID, _client, read, run_body, stamped_return_set


def _rs(**kw) -> ReturnSet:
    return ReturnSet.model_validate_json(stamped_return_set(**kw))


def test_the_mandate_takes_chf_eur_or_usd_and_defaults_to_chf(mandate):
    body = mandate()
    del body["currency"]
    assert Mandate.model_validate(body).currency == "CHF"          # a pcp-mandate@1.0.0 body without one
    for ccy in ("CHF", "EUR", "USD"):
        assert Mandate.model_validate(mandate(currency=ccy)).currency == ccy
    for bad in ("GBP", "chf", "", None):
        with pytest.raises(ValidationError, match="not a reporting currency"):
            Mandate.model_validate(mandate(currency=bad))


def test_the_served_currency_is_read_from_the_field_first_then_from_fmres_note():
    assert served_currency(_rs(currency="EUR")) == "EUR"
    assert served_currency(_rs(currency=None, currency_field="USD")) == "USD"
    assert served_currency(_rs(currency="USD", currency_field="USD")) == "USD"
    assert served_currency(_rs(currency="CHF", currency_field="USD")) is None     # they disagree
    assert served_currency(_rs(currency=None)) is None                             # the unconverted default
    assert served_currency(_rs(currency="source")) == "source"


def test_the_return_set_is_requested_in_the_mandates_currency(settings, mandate):
    seen: list[dict] = []
    with _client(settings, None, seen) as c:
        for ccy in ("EUR", "CHF"):
            v = c.post("/validate", json=run_body(mandate(currency=ccy))).json()
            assert v["ok"] and v["currency"] == ccy, v["problems"]
            assert seen[-1]["currency"] == ccy and seen[-1]["regime_id"] == REGIME_ID
            assert seen[-1]["include_instruments"] == "true" and seen[-1]["include_blocks"] == "false"


@pytest.mark.parametrize("served, why", [("USD", "measured in USD, not the mandate's CHF"),
                                         (None, "has not stated a currency"),
                                         ("source", "unconverted source-currency")])
def test_a_return_set_in_another_currency_is_refused(settings, mandate, served, why):
    with _client(settings, stamped_return_set(currency=served)) as c:
        v = c.post("/validate", json=run_body(mandate(name=f"ccy-{served}"))).json()
        assert v["ok"] is False and why in v["problems"][0] and "PCP-18" in v["problems"][0]
        r = c.post("/run", json=run_body(mandate(name=f"ccy-{served}"))).json()
        assert r["status"] == "failed" and r["artefact_id"] is None
        assert why in c.get(f"/runs/{r['run_id']}").json()["error"]


def test_a_structured_currency_field_is_honoured(settings, mandate):
    with _client(settings, stamped_return_set(currency=None, currency_field="EUR")) as c:
        assert c.post("/validate", json=run_body(mandate(currency="EUR"))).json()["ok"]
        assert not c.post("/validate", json=run_body(mandate(currency="CHF"))).json()["ok"]


def test_the_allocation_names_its_currency_and_the_currency_enters_the_key(client, mandate):
    runs = {}
    for ccy in ("EUR", "CHF"):
        r = client.post("/run", json=run_body(mandate(name="ccy", currency=ccy))).json()
        assert r["status"] == "succeeded", client.get(f"/runs/{r['run_id']}").json()["error"]
        runs[ccy] = r
        a = client.get(f"/allocation/{r['artefact_id']}").json()
        assert a["currency"] == ccy and a["provenance"]["currency"] == ccy
        assert a["provenance"]["upstream"]["fmre:currency"] == ccy
    assert runs["EUR"]["idempotency_key"] != runs["CHF"]["idempotency_key"]
    assert runs["EUR"]["artefact_id"] != runs["CHF"]["artefact_id"]


def test_the_frozen_return_set_is_the_unconverted_default():
    """The frozen inputs are fmre's source-currency default of 28.09.2026; the double names them CHF
    (PCP-20). A refreeze (``dev/freeze_inputs.py``, now in CHF) turns this red on purpose: rebuild layer C,
    then update PCP-20 and this test."""
    rs = json.loads(read("return_set.json"))
    assert rs["provenance"]["regime_id"] is None and "currency" not in rs["provenance"]
    assert not any("currency=" in n for n in rs["provenance"]["notes"])
