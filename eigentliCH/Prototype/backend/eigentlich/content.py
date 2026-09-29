"""Content records loaded from files, never string literals in templates.

Three requirements land here and they are the same requirement wearing three hats:

  R-111  role definitions are content records, shown on demand
  D-03   those definitions come from a published model and ship marked provisional
  D-07   all destination copy comes from ONE content key, not scattered through templates

A string literal in a template is a decision nobody can find later. A key in a file is one
someone can change, translate, review, or mark provisional — which is what all three of
those ask for.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CONTENT = Path(__file__).resolve().parent.parent.parent / "client" / "content"

#: A12 — bilingual, de-CH default.
LANGUAGES = ("de", "en")
DEFAULT_LANGUAGE = "de"


class ContentMissing(Exception):
    """A content file or key that does not exist. Never falls back to a literal."""


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    path = CONTENT / f"{name}.json"
    if not path.exists():
        raise ContentMissing(
            f"content record {name!r} not found at {path}. R-111 and D-07 require these to be files; "
            f"there is deliberately no literal to fall back to."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def roles() -> list[dict]:
    return _load("roles")["roles"]


def role(key: str) -> dict:
    for record in roles():
        if record["key"] == key:
            return record
    raise ContentMissing(f"no role definition for {key!r}")


def roles_are_provisional() -> bool:
    """D-03. True until someone reviews them and clears the flag in the file."""
    return bool(_load("roles").get("provisional", True))


def role_definition(key: str, capital_type: str, language: str = DEFAULT_LANGUAGE) -> str | None:
    """The definition of one role for one kind of capital, in one language.

    Returns None rather than a placeholder when the string is absent. R-110 says an empty cell states what
    would go there; a definition that is genuinely missing should read as missing, not as an empty quote.
    """
    record = role(key)
    block = record["definition"].get(capital_type)
    if not block:
        return None
    return block.get(language) or None


def onboarding_questions() -> list[dict]:
    """S-01's question set, ordered by the file rather than by insertion."""
    return _load("onboarding-questions")["questions"]


def question_set_version() -> str:
    """Stamped on every answer, so a set that changes cannot silently re-point an old answer."""
    return _load("onboarding-questions")["version"]


def question(key: str) -> dict:
    for record in onboarding_questions():
        if record["key"] == key:
            return record
    raise ContentMissing(f"no onboarding question {key!r}")


def destination(language: str = DEFAULT_LANGUAGE) -> str:
    """D-07. The one key all destination copy comes from.

    A function rather than a constant, so that the only way to render the phrase is to ask for it in a
    language — which is what stops it being inlined into a template as a literal.
    """
    value = _load("destination")["destination"].get(language)
    if not value:
        raise ContentMissing(
            f"no destination phrase for language {language!r}. D-07 requires one key; there is no literal "
            f"to fall back to, because a fallback is how the phrase gets scattered."
        )
    return value


def role_display(key: str, capital_type: str, language: str = DEFAULT_LANGUAGE) -> str:
    """The display name. Differs by capital type: `Gain` financially, `Growth` for human capital.

    That is the source manual's own distinction, not a decision taken here — see `_about.naming` in
    `roles.json`.
    """
    record = role(key)
    return record["display"][capital_type][language]


# ---------------------------------------------------------------------------
# Currency horizons (update script item 6)
# ---------------------------------------------------------------------------


class HorizonNotPublished(ContentMissing):
    """An input class with no published validity horizon.

    A subclass rather than a bare `ContentMissing`, because the correct response differs: a missing role
    definition renders as absent (R-110), whereas a missing horizon means the currency of a finding
    **cannot be judged** and the caller must say so rather than treat the input as never expiring. Failing
    open here would present a stale figure as certified, which is the whole defect item 6 exists to close.
    """


def currency_horizons() -> dict:
    """Every published input-class horizon, keyed by input class."""
    return _load("currency-horizons")["horizons"]


def horizon_months(input_class: str) -> int:
    """How long a stated value of `input_class` stays valid, in months.

    Raises:
        HorizonNotPublished: When nobody has published one. There is deliberately no default: a horizon
            is a C-02 value, and the one thing worse than not knowing whether a figure is still true is
            assuming it is.
    """
    published = currency_horizons()
    if input_class not in published:
        raise HorizonNotPublished(
            f"no validity horizon is published for input class {input_class!r}. C-02 forbids a default "
            f"here — publishing one is an editorial act with an owner, in "
            f"client/content/currency-horizons.json. Until it is published, a finding resting on this "
            f"input cannot be presented as standing and must report that it could not be "
            f"determined."
        )
    return int(published[input_class]["months"])


def horizon_is_load_bearing(input_class: str) -> bool:
    """Whether a finding resting on this input degrades when the horizon passes.

    Load-bearing is a property of the input, published beside its horizon rather than inferred from how
    many findings happen to read it: "how much does this matter" is an editorial judgement, and deriving
    it from usage would make it change whenever a section was added.
    """
    published = currency_horizons()
    if input_class not in published:
        raise HorizonNotPublished(
            f"no validity horizon is published for input class {input_class!r}, so whether it is "
            f"load-bearing is not published either."
        )
    return bool(published[input_class].get("load_bearing", False))


def horizon_provenance() -> dict:
    """Who published the horizons and when. Carried into a payload beside any figure that used one.

    A content record has no `assumption_set_id` to travel, so this is what a reader traces a horizon
    through — the same job `rates["source"]` does for an AssumptionSet.
    """
    about = _load("currency-horizons")["_about"]
    return {
        "published_by": about["published_by"],
        "effective_from": about["effective_from"],
        "provisional": bool(about.get("provisional", True)),
    }


# ---------------------------------------------------------------------------
# The annual review's household confirmation (update script item 6)
# ---------------------------------------------------------------------------


def household_confirmation_items() -> list[dict]:
    """The five or six closed items the annual review opens with. Content, never literals in a template."""
    return _load("household-confirmation")["items"]


def household_confirmation_keys() -> tuple[str, ...]:
    """The item keys, in the order the file gives them.

    A tuple so a service can check that an answer set covers exactly these — a confirmation missing an
    item is a question the member was not asked, and one carrying an extra is an answer to a question
    nobody published.
    """
    return tuple(item["key"] for item in household_confirmation_items())


def household_confirmation_prompt(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    for item in household_confirmation_items():
        text = item.get(language)
        if item["key"] == key and text:
            return text
    raise ContentMissing(
        f"no household confirmation item {key!r} in language {language!r}. There is no literal to fall "
        f"back to: an item the member is shown has to be one somebody published."
    )


def household_change_signals() -> list[dict]:
    """Item 6's inferred half: the closed set of visible events that may raise a confirmation flag.

    Each entry says whether it can be observed in this build. A flag raised by a signal nobody named is a
    flag nobody can explain to the member, which is why the set is closed rather than open to a caller's
    string.
    """
    return _load("household-confirmation")["_signals"]["signals"]


def observable_household_signals() -> tuple[str, ...]:
    """The signals this build can actually see. The rest are published with the reason they cannot."""
    return tuple(
        one["key"] for one in household_change_signals() if one.get("observable_now")
    )


# ---------------------------------------------------------------------------
# The intake scales (update script item 3)
# ---------------------------------------------------------------------------


def intake_scales() -> dict:
    """The numbers the reimplemented intake identities turn on.

    In a content record rather than in `services/identities.py` because C-02's guard forbids a float
    literal in application code and enforces the shape rather than the intent. See the file's `_about`:
    they are **provisional and uncalibrated**, carried verbatim from the prototype, and publishing them is
    not a claim that they are right.
    """
    return _load("intake-scales")


def intake_scales_are_provisional() -> bool:
    """True until somebody calibrates them and clears the flag in the file. Nobody has."""
    return bool(_load("intake-scales")["_about"].get("provisional", True))


# ---------------------------------------------------------------------------
# What the intake unlocks (update script item 3)
# ---------------------------------------------------------------------------


def intake_findings() -> list[dict]:
    """The findings the intake makes possible, each naming the questions it needs.

    Content rather than derived from the questions' own `fills`: which findings are worth naming is an
    editorial judgement, and deriving them would make the list whatever the question set happened to
    contain. The join runs the other way, and a test asserts every key named here exists in the set.
    """
    return _load("intake-findings")["findings"]


def intake_finding_sentence(key: str, language: str = DEFAULT_LANGUAGE) -> str:
    for finding in intake_findings():
        text = finding.get(language)
        if finding["key"] == key and text:
            return text
    raise ContentMissing(
        f"no intake finding {key!r} in language {language!r}. There is no literal to fall back to: a "
        f"sentence a member reads has to be one somebody published."
    )


# ---------------------------------------------------------------------------
# The liquidity lever precedence (update script item 4)
# ---------------------------------------------------------------------------


def liquidity_levers() -> list[dict]:
    """The fixed precedence a blocking liquidity finding prepares from, in publication order.

    Config rather than code because item 4 says so: "Keep the order in config so it can be changed without
    a rewrite." The order runs from what costs the member nothing they would notice to what costs them
    part of the goal, and that ranking is an editorial judgement about people rather than a fact about
    money.
    """
    return sorted(_load("liquidity-levers")["levers"], key=lambda lever: lever["order"])
