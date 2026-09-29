"""The declarative base, and the data classification that C-04 makes a column rather than a convention.

**Why classification is a column and not a docstring.** The estate already had a K0-K3 scheme, written down
in `architecture/DECISIONS.md` and applied by hand. A scheme that lives in prose is checked by whoever
remembers it, which is a guarantee that decays. C-04 requires the class to be *on the model*, so that a
logging filter and a test can both read it without anyone being asked.

**Two levels, because C-04 says two things.** It says "every stored FIELD carries a data class", and it says
"classification is a COLUMN on the model". Both are implemented:

  * every table carries a `data_class` column, whose value defaults to the entity's `__data_class__`. That is
    the row's class, and it is what an export or a retention rule reads.
  * any individual column may declare `info={"data_class": ...}` to raise itself above its entity. A
    `VaultItem` is K3 as a whole, but a `Member.display_name` sitting at K1 inside a K1 entity does not need
    the override, while `Position.magnitude` inside a K2 entity does not either. The override exists for the
    case where one field is more sensitive than the row it sits in, which is the case the entity-level class
    silently gets wrong.

The class assignment itself is A5 in DECISIONS.md: the build spec's §4 assignment wins over the estate's,
and the two disagree. Anyone reading `architecture/DECISIONS.md` should read A5 before assuming otherwise.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime as SADateTime, Integer, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class DateTime(TypeDecorator):
    """A timezone-aware UTC datetime that stays aware through a round trip to SQLite.

    **This exists because of a real crash, not a theoretical one.** `DateTime(timezone=True)` is a promise
    the SQLite dialect cannot keep: it stores the instant and drops the offset, so a row written with an
    aware datetime comes back naive. Any `stored > utcnow()` comparison then raises

        TypeError: can't compare offset-naive and offset-aware datetimes

    and it raises only when the row is loaded from disk rather than served from the session's identity
    map. Within one session everything works; across two it crashes. That is why it survived a 450-test
    suite — the tests use one session, and `expire_on_commit=False` keeps objects aware in memory.

    It was found in `Session.active` and `AccessGrant.is_live()`, both on read paths where the failure
    reads as a bug rather than as a refusal — a member's session check crashing with a TypeError instead
    of returning False. Under FastAPI, which opens a session per request, it would have fired on the first
    real login.

    Fixed here rather than at each comparison. Coercing at the boundary means every datetime column in the
    application is aware everywhere, and no future comparison has to remember. A fix in `is_live()` would
    have left `Session.active` broken, which is exactly what had happened.
    """

    impl = SADateTime
    cache_ok = True

    def __init__(self, timezone: bool = True, **kwargs):
        # `timezone=True` is accepted and ignored: awareness is this type's whole job, and letting a caller
        # write `timezone=False` would reintroduce the bug under a name that looks deliberate.
        super().__init__(timezone=True, **kwargs)

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # A naive value arriving here is a caller who used `datetime.now()` instead of `utcnow()`.
            # Assume UTC rather than local: the alternative silently shifts an instant by the machine's
            # offset, which is worse than being wrong in one obvious direction.
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class DataClass(enum.IntEnum):
    """The estate's K0-K3 scheme, ordered so that "at or above" is a comparison rather than a lookup.

    K0  published, impersonal   — assumption sets, role definitions, learning content
    K1  identifying, low        — display name, locale, consents
    K2  personal, substantive   — positions, goals, decisions, action items
    K3  personal, documentary   — vault items and what was extracted from them
    """

    K0 = 0
    K1 = 1
    K2 = 2
    K3 = 3

    def __str__(self) -> str:  # so log lines and errors read "K3", not "DataClass.K3"
        return self.name


#: The class that never leaves the server and never appears in a log line (C-04). Named once, because a
#: literal `DataClass.K3` scattered through the filter and the tests is a rule with several copies.
TOP_CLASS = DataClass.K3


def new_id() -> str:
    """Opaque primary key. Not sequential: a member's row count is itself a small disclosure."""
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base carrying the classification contract.

    Every concrete model must set `__data_class__`. There is no default: a model whose author did not think
    about its class is exactly the model the logging filter will get wrong, so the omission is an error at
    import time rather than a silent K0.
    """

    #: The entity's class. Subclasses must override.
    __data_class__: DataClass

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Abstract intermediates (mixins, `__abstract__`) are exempt; concrete tables are not.
        if getattr(cls, "__abstract__", False) or not hasattr(cls, "__tablename__"):
            return
        if "__data_class__" not in cls.__dict__ and not hasattr(cls, "__data_class__"):
            raise TypeError(
                f"{cls.__name__} defines a table but no __data_class__. C-04 requires every stored row to "
                f"carry a data class; there is deliberately no default."
            )


class Classified:
    """Mixin giving a model its `data_class` column and the per-field lookup the filter needs.

    `declared_attr` rather than a plain `mapped_column`, for two reasons that only show up at runtime: a
    column object defined once on a mixin is *shared* by every subclass, and the default has to close over
    the subclass's own `__data_class__` rather than the mixin's. Declaring it per class gets both right and
    bakes the value in as a literal, so no callable is handed to the driver.
    """

    @declared_attr
    def data_class(cls) -> Mapped[int]:  # noqa: N805 - declared_attr receives the class
        return mapped_column(
            Integer,
            nullable=False,
            default=int(cls.__data_class__),
            doc="C-04. Defaults to the entity's __data_class__; stored per row so an export or a "
            "retention sweep reads the row rather than the code that wrote it.",
        )

    @classmethod
    def field_data_class(cls, field_name: str) -> DataClass:
        """The class of one field: its own override if it declares one, else its entity's."""
        column = cls.__table__.columns.get(field_name)
        if column is not None:
            override = column.info.get("data_class")
            if override is not None:
                return DataClass(override)
        return cls.__data_class__

    @classmethod
    def fields_at_or_above(cls, threshold: DataClass) -> frozenset[str]:
        return frozenset(
            name for name in cls.__table__.columns.keys() if cls.field_data_class(name) >= threshold
        )


class Timestamped:
    """`created_at` on everything that is written once and read for years."""

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


#: Columns that carry no content about a person even when they sit on a top-class row: the row's own key,
#: its links to other rows, its class, and when it was written.
#:
#: **Why this exclusion has to exist.** Entity-level classification is coarse by design — a `VaultItem` is
#: K3 as a whole. Without this, `member_id` would be a K3 field name, and since the filter drops by *name*
#: it would redact `member_id=` in every log line the application ever writes, including lines about
#: entities that are not K3 at all. A filter that removes the field every trace is followed by is not a
#: safer filter, it is an unused one, and an unused filter is how K3 values end up being logged deliberately.
#:
#: Note this is about the *name-based log filter* only. It does not lower any row's stored `data_class`, and
#: it says nothing about R-303's separate rule that engine logs have the member reference removed.
_STRUCTURAL_FIELDS = frozenset({"data_class", "created_at", "version"})


def top_class_field_names() -> frozenset[str]:
    """Every content field name in the model layer classified at TOP_CLASS or above.

    This is what the logging filter drops by name (C-04). Computed from the mappers rather than listed, so a
    new K3 column is protected by existing in the schema rather than by someone remembering this function.
    """
    names: set[str] = set()
    structural: set[str] = set(_STRUCTURAL_FIELDS)
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not issubclass(model, Classified):
            continue
        names |= model.fields_at_or_above(TOP_CLASS)
        for column in model.__table__.columns:
            if column.primary_key or column.foreign_keys:
                structural.add(column.key)
    return frozenset(names - structural)
