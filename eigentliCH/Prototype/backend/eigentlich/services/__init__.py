"""Service layer: the convenient paths. Enforcement lives in `db.py` and on the tables."""

from .auth import (
    AuthenticationFailed,
    EmailAlreadyRegistered,
    change_password,
    login,
    logout,
    member_for_token,
    operator_reset,
    register_with_credentials,
    revoke_all_sessions,
)
from .befund import BefundWouldAdvise, render_befund
from .derive import causes_by_item_id, derive_action_items
from .export import export_member, to_json, verify_round_trip
from .goals import list_goals
from .know import action_items, ask, open_curator_session
from .vault import (
    IntakeNotImplemented,
    VaultStore,
    action_item_for_expiry,
    current_items,
    expiring_items,
    merge_extraction,
    store_item,
)
from .illustration import goal_illustration
from .runs import (
    NotQueueable,
    UnknownEngine,
    describe_run,
    list_runs,
    read_run,
    submit as submit_run,
)
from .grid import role_grid
from .onboarding import (
    OnboardingAlreadyComplete,
    OnboardingIncomplete,
    UnknownQuestion,
    answers,
    complete,
    resume_point,
    record_answer,
)
from .plan import mutate_plan, record_correction, validate_position_state
from .registration import BelowAgeFloor, register_member, withdraw_consent

__all__ = [
    "AuthenticationFailed",
    "BefundWouldAdvise",
    "render_befund",
    "BelowAgeFloor",
    "EmailAlreadyRegistered",
    "change_password",
    "IntakeNotImplemented",
    "VaultStore",
    "action_item_for_expiry",
    "causes_by_item_id",
    "current_items",
    "derive_action_items",
    "export_member",
    "expiring_items",
    "action_items",
    "ask",
    "list_goals",
    "open_curator_session",
    "merge_extraction",
    "store_item",
    "to_json",
    "verify_round_trip",
    "login",
    "logout",
    "member_for_token",
    "operator_reset",
    "register_with_credentials",
    "revoke_all_sessions",
    "OnboardingAlreadyComplete",
    "OnboardingIncomplete",
    "UnknownQuestion",
    "answers",
    "complete",
    "resume_point",
    "record_answer",
    "mutate_plan",
    "validate_position_state",
    "role_grid",
    "NotQueueable",
    "UnknownEngine",
    "describe_run",
    "goal_illustration",
    "list_runs",
    "read_run",
    "submit_run",
    "record_correction",
    "register_member",
    "withdraw_consent",
]
