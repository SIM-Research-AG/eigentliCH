"""R-003 acceptance: protection instruments under the default estimator, per type.

**Against the live store, read-only.** The question is about real history -- public
proxies, the andersCH recoveries and the exchange rates -- none of which a throwaway
schema built from the NAS sources holds. Nothing here writes: the profiles are computed
in memory, exactly as ``/v1/diagnostics/estimators`` computes them.

**The profile judged is the served default** since 29 September 2026: the 12 month
forward measurement with a light smoothing across neighbouring states
(``forward_12m_smoothed``, FMRE-22).

**Each protection instrument is judged by the rule of its type** (owner, 29 September
2026, FMRE-24), read from the register by what the instrument is, not by its name
(``service.protection_type``):

* **tail hedge** (price proxy a volatility index, VXTH or VIXY): did it pay when the shock
  hit, i.e. the mean log return of the months tagged crisis (states 1 to 5) is above zero;
* **cash** (asset class ``Cash``): never negative, in any of the 25 states;
* **everything else**: the 12 month forward rule of FMRE-19, positive in every crisis state
  in CHF, EUR and USD, and highest in the crisis states in the source currency.

Every rule is checked in CHF, EUR and USD. **Where it cannot hold, the instrument is named
with the reason** in :data:`CANNOT_HOLD`, rather than the check being loosened. The test
fails both ways: an instrument that fails without an entry, and an entry whose instrument
now passes (a stale excuse is as misleading as a missing one). Short MSCI US and CS Long
Vola are inactive since 29 September 2026 and are no longer measured here.
"""

from __future__ import annotations

import pytest

from engines.fund_map import service
from engines.fund_map.estimate import ProfileMethod
from engines.fund_map.service import ProtectionType

CURRENCIES = ("CHF", "EUR", "USD")
DEFAULT = service.DEFAULT_PROFILE_METHOD

_USD_CASH_FX = (
    "Dollar cash carries the dollar for a franc or euro investor, and the dollar fell "
    "after crisis months: in CHF about -8.4 % at the edge of the crisis band, in EUR about "
    "-5.5 %. The currency, not the asset (as it stands, owner 29 September 2026). In USD "
    "it is never negative (+0.9 % to +2.0 %)."
)
_CHF_CASH_IN_USD = (
    "Franc cash read in dollars carries the franc: the franc fell against the dollar in "
    "the year after most contraction months, about -3.1 % at the contraction knot. The "
    "currency, not the asset. In CHF and EUR it is never negative."
)
_BWX = (
    "Proxy BWX is unhedged international government bonds ex-US, quoted in USD; read in "
    "CHF or EUR its crisis year is dominated by the currency, not by duration (as it "
    "stands, owner 29 September 2026). In USD the requirement holds."
)

#: (instrument name, currency) -> why its type's rule cannot hold there.
CANNOT_HOLD: dict[tuple[str, str], str] = {
    ("USD Cash", "CHF"): _USD_CASH_FX,
    ("USD Cash", "EUR"): _USD_CASH_FX,
    ("CHF Cash", "USD"): _CHF_CASH_IN_USD,
    ("Global Governmental Bonds", "CHF"): _BWX,
    ("Global Governmental Bonds", "EUR"): _BWX,
}

_VXTH_FORWARD = (
    "A tail hedge is judged on the crisis months themselves (FMRE-24) and passes that "
    "rule. Its 12 month forward profile, which the ReturnSet publishes, dips below zero at "
    "the extrapolated edge of the crisis band in CHF (about -1.2 %) and EUR (about "
    "-0.04 %): VXTH is the S&P 500 with a small VIX call overlay, so the year after a "
    "crisis month is mostly the equity rebound, and the dollar fell after crisis months."
)

#: Protection instruments whose *served profile* is negative somewhere in states 1 to 5
#: although they pass their own type's rule, with the reason.
NEGATIVE_IN_CRISIS_PROFILE: dict[tuple[str, str], str] = {
    ("Long Volatility Index", "CHF"): _VXTH_FORWARD,
    ("Long Volatility Index", "EUR"): _VXTH_FORWARD,
}

#: The type each active protection instrument with history is judged as. Pinned so a
#: register change that moves an instrument to another rule is seen, not absorbed.
EXPECTED_TYPES = {
    "Long Volatility Index": ProtectionType.TAIL_HEDGE,
    "USD Cash": ProtectionType.CASH,
    "CHF Cash": ProtectionType.CASH,
    "Precious Metals": ProtectionType.FORWARD,
    "Global Governmental Bonds": ProtectionType.FORWARD,
    "US Treasury TR Index": ProtectionType.FORWARD,
    "Bloomberg Multiverse (H-CHF)": ProtectionType.FORWARD,
}

#: Inactive since 29 September 2026 (``store/etl/universe.py::DEACTIVATED``).
INACTIVE = ("Short MSCI US", "CS Long Vola")


@pytest.fixture(scope="module")
def live():
    """The configured store, opened directly so no test fixture's schema can intervene."""
    from store import db
    from store.config import load

    conn = db.connect(load())
    try:
        calibration_id = service.latest_calibration_id(conn)
        assert calibration_id, "the live store has no calibration; run the bootstrap"
        universe = service.load_universe(conn, calibration_id)
    finally:
        conn.close()
    assert universe.in_chf is not None, (
        "the live store has no exchange rates, so CHF/EUR/USD cannot be measured. "
        "Load them with: python -m store.etl.fx"
    )
    return universe


def _views(universe, currency, method=DEFAULT):
    cache: dict = {}
    for inst in universe.instruments:
        if inst["role"] != "protection" or not universe.returns.get(inst["instrument_id"]):
            continue
        yield inst, service.estimate_view(universe, inst, method, currency, cache)


def test_the_served_default_is_the_smoothed_forward_measurement():
    assert DEFAULT is ProfileMethod.FORWARD_12M_SMOOTHED


def test_each_protection_instrument_has_the_type_of_what_it_is(live):
    """Types come from the register (asset class, price proxy), not from a list of names."""
    found = {inst["name"]: service.protection_type(inst) for inst, _ in _views(live, None)}
    assert found == EXPECTED_TYPES


@pytest.mark.parametrize("currency", CURRENCIES)
def test_every_protection_instrument_holds_its_rule_or_is_named(live, currency):
    unexplained, stale = [], []
    for inst, view in _views(live, currency):
        check = service.protection_check(view, service.protection_type(inst))
        key = (inst["name"], currency)
        if check["passed"] and key in CANNOT_HOLD:
            stale.append(inst["name"])
        if not check["passed"] and key not in CANNOT_HOLD:
            unexplained.append(
                f"{inst['name']} ({check['type']}): crisis {check['crisis_knot']:+.2%} "
                f"(min {check['crisis_min']:+.2%}), profile min {check['profile_min']:+.2%}")
    assert not unexplained, (
        f"protection instruments failing in {currency} with no stated reason: {unexplained}")
    assert not stale, (
        f"listed as unable to hold in {currency} but now passing, remove the entry: {stale}")


@pytest.mark.parametrize("currency", CURRENCIES)
def test_no_protection_instrument_is_negative_in_crisis_unless_named(live, currency):
    """R-003 in its plainest form, on the served profile, whatever the type: no state from
    1 to 5 at or below zero, except where named with the reason (both lists)."""
    named = CANNOT_HOLD.keys() | NEGATIVE_IN_CRISIS_PROFILE.keys()
    negative, stale = [], []
    for inst, view in _views(live, currency):
        key = (inst["name"], currency)
        below = min(view["profile"][:5]) <= 0
        if below and key not in named:
            negative.append(f"{inst['name']}: {min(view['profile'][:5]):+.2%}")
        if not below and key in NEGATIVE_IN_CRISIS_PROFILE:
            stale.append(inst["name"])
    assert not negative, f"negative in crisis in {currency} with no stated reason: {negative}"
    assert not stale, f"listed as negative in crisis in {currency} but now positive: {stale}"


@pytest.mark.parametrize("currency", CURRENCIES)
def test_precious_metals_is_measured_and_strong_in_crisis(live, currency):
    """The R-003 instrument, under the served default. Positive in every crisis state and
    no longer seeded, in every currency; highest in the crisis states in its source
    currency (GLD, USD). In CHF and EUR its crisis estimate sits below contraction because
    the dollar fell after most crisis months: the currency effect the owner accepted."""
    inst = next(i for i in live.instruments if i["name"] == "Precious Metals")
    view = service.estimate_view(live, inst, DEFAULT, currency)
    check = service.protection_check(view, service.protection_type(inst))
    assert view["coverage"] != "seed"
    assert view["methods"][2] == "forward-12m-smoothed"
    assert view["phases"][0]["method"] == "data-driven", "the crisis phase must be measured"
    assert check["positive_in_crisis"]
    assert check["passed"]
    if currency == view["series_currency"]:
        assert check["in_source_currency"] and check["highest_in_crisis"]


def test_the_tail_hedge_is_judged_on_the_crisis_months_themselves(live):
    """Long Volatility Index (VXTH): the rule reads the months tagged crisis, not the
    twelve months after them (which are mostly the equity rebound)."""
    inst = next(i for i in live.instruments if i["name"] == "Long Volatility Index")
    view = service.estimate_view(live, inst, DEFAULT, None)
    assert view["series"] == "cboe:VXTH:close"
    check = service.protection_check(view, ProtectionType.TAIL_HEDGE)
    assert check["crisis_months"] >= 24, "the crisis months since 2006 are all covered"
    assert all(1 <= m["state"] <= 5 for m in view["crisis_months"])
    assert check["passed"] and check["crisis_month_mean_log"] > 0


def test_the_deactivated_instruments_are_not_measured(live):
    """Short MSCI US and CS Long Vola stay in the register but leave the universe."""
    names = {i["name"] for i in live.instruments}
    assert not names & set(INACTIVE)
    assert not {name for name, _ in CANNOT_HOLD} & set(INACTIVE)


def test_long_volatility_reads_the_vxth_index_not_vixy(live):
    """The price proxy chosen on 29 September 2026 (FMRE-18) is what the measurement reads."""
    inst = next(i for i in live.instruments if i["name"] == "Long Volatility Index")
    assert (inst["proxy_symbol"], inst["proxy_grade"]) == ("VXTH", "close")
    view = service.estimate_view(live, inst, DEFAULT, None)
    assert view["series"] == "cboe:VXTH:close"
    assert service.protection_check(view)["positive_in_crisis"]


def test_the_cascade_still_reads_gold_negative_in_crisis_and_is_no_longer_served(live):
    """The fault R-003 describes is still in the stored cascade profiles, which stay
    selectable with ``profile_method=cascade``; the served default does not carry it."""
    inst = next(i for i in live.instruments if i["name"] == "Precious Metals")
    cascade = service.estimate_view(live, inst, ProfileMethod.CASCADE, None)
    assert cascade["stored"] is True
    assert cascade["profile"][2] < 0 and cascade["coverage"] == "seed"
    served = service.estimate_view(live, inst, DEFAULT, None)
    assert served["stored"] is False and served["profile"][2] > 0


@pytest.mark.parametrize("currency", (None, *CURRENCIES))
def test_the_served_default_is_smooth_and_labelled(live, currency):
    """R-002 acceptance on every instrument with history: mean jump between neighbouring
    states below 2 %, every state labelled, nothing seeded, no phase value moved by more
    than the smoother's tolerance, and no sign the unsmoothed measurement did not have."""
    from engines.fund_map.forward import SMOOTHING_TOLERANCE

    cache: dict = {}
    jumps = []
    for inst in live.instruments:
        if not live.returns.get(inst["instrument_id"]):
            continue
        view = service.estimate_view(live, inst, DEFAULT, currency, cache)
        p = view["profile"]
        jumps.append(sum(abs(b - a) for a, b in zip(p, p[1:])) / 24)
        assert len(view["methods"]) == 25 and all(view["methods"])
        assert view["coverage"] != "seed", inst["name"]
        before = view["unsmoothed"]["profile"]
        for k in (2, 7, 12, 17, 22):
            assert abs(p[k] - before[k]) <= SMOOTHING_TOLERANCE + 1e-12, inst["name"]
        assert all((a > 0) == (b > 0) and (a < 0) == (b < 0) for a, b in zip(p, before))
    assert sum(jumps) / len(jumps) < 0.02
