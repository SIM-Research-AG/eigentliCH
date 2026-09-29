"""The member application's model layer.

**This package is the scope of the C-07 grep** (A6 in DECISIONS.md). `test_no_gamification_identifiers_in_model_layer`
walks these files and fails on a points, score, streak, badge, level-number, leaderboard or daily-goal
identifier. It deliberately does NOT cover `eigentliCH/engines/score/` or the shared contracts layer, whose
`Score` is an analytical household-standing measure rather than a game mechanic — that narrowing is a
recorded decision, not an oversight, and the test says so itself.

Marketplace `Listing` is phase 7 and is not here yet. Its absence is scope, not omission.
"""

from .base import Base, Classified, DataClass, new_id, TOP_CLASS, top_class_field_names, utcnow
from .member import Consent, MINIMUM_AGE, Member
from .household import (
    ADULT,
    DEPENDANT,
    HOUSEHOLD_MEMBER_KINDS,
    STATED_BY,
    Household,
    HouseholdMember,
)
from .plan import (
    ASSET,
    CAPITAL_TYPES,
    CORRELATION_TAGS,
    FLOW_UNIT,
    Goal,
    LIABILITY,
    LIQUIDITY,
    MAGNITUDE_UNITS,
    PlanMutable,
    Position,
    ROLES,
    SHARE_UNIT,
    STOCK_KINDS,
    STOCK_UNIT,
    STOCK_UNITS,
    goal_funding,
    goal_owners,
)
from .decision import Decision, DecisionImmutable, decision_facts
from .member_fact import MemberFact
from .run import (
    DONE,
    EngineRun,
    FAILED,
    RUNNING,
    RUN_STATUSES,
    SUBMITTED,
    TERMINAL_STATUSES,
)
from .vault import VaultItem
from .action import ActionItem
from .assumptions import AssumptionSet, NoAssumptionSet
from .curator import AuditImmutable, CuratorSession, CuratorSessionEvent
from .knowledge import Capability, CapabilityAssertion, LearningUnit
from .auth import Credential, MINIMUM_PASSWORD_LENGTH, Session, WeakPassword
from .access import Attendance, AccessGrant, Curator, GATHERING_KINDS, GRANTABLE, Gathering
from .marketplace import (
    DOMAINS,
    Disclosure,
    LISTING_STATUS,
    Listing,
    MemberOffer,
    PIPELINES,
    Provider,
    UndisclosedListing,
)
from .onboarding import OnboardingAnswer
from .submission import Submission
from .version import (
    PROPOSED,
    STANDING,
    SUPERSEDED,
    VERSION_STATUSES,
    PlanVersion,
)

__all__ = [
    "ActionItem",
    "ADULT",
    "AssumptionSet",
    "AuditImmutable",
    "Base",
    "CAPITAL_TYPES",
    "CORRELATION_TAGS",
    "AccessGrant",
    "Attendance",
    "Capability",
    "Curator",
    "DOMAINS",
    "Disclosure",
    "GATHERING_KINDS",
    "GRANTABLE",
    "Gathering",
    "LISTING_STATUS",
    "Listing",
    "MemberOffer",
    "PIPELINES",
    "Provider",
    "CapabilityAssertion",
    "Classified",
    "Consent",
    "Credential",
    "CuratorSession",
    "CuratorSessionEvent",
    "DataClass",
    "DEPENDANT",
    "DONE",
    "Decision",
    "DecisionImmutable",
    "EngineRun",
    "FAILED",
    "RUNNING",
    "RUN_STATUSES",
    "SUBMITTED",
    "TERMINAL_STATUSES",
    "Goal",
    "HOUSEHOLD_MEMBER_KINDS",
    "Household",
    "HouseholdMember",
    "LIQUIDITY",
    "LearningUnit",
    "MAGNITUDE_UNITS",
    "ASSET",
    "FLOW_UNIT",
    "LIABILITY",
    "SHARE_UNIT",
    "STOCK_KINDS",
    "STOCK_UNIT",
    "STOCK_UNITS",
    "MINIMUM_AGE",
    "MINIMUM_PASSWORD_LENGTH",
    "Member",
    "MemberFact",
    "NoAssumptionSet",
    "OnboardingAnswer",
    "Submission",
    "PlanMutable",
    "Position",
    "STATED_BY",
    "decision_facts",
    "goal_owners",
    "PROPOSED",
    "STANDING",
    "SUPERSEDED",
    "VERSION_STATUSES",
    "PlanVersion",
    "ROLES",
    "Session",
    "WeakPassword",
    "TOP_CLASS",
    "UndisclosedListing",
    "VaultItem",
    "goal_funding",
    "new_id",
    "top_class_field_names",
    "utcnow",
]
