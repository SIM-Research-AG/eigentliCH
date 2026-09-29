"""C-04: the top data class never appears in a log line.

"A logging filter drops the top class by field name. A test asserts no top-class field appears in any log
line." Both halves are implemented here, and the filter reads the field names from the mappers rather than
from a list, so a new K3 column is protected by existing rather than by being remembered.

**What this catches.** Structured extras (`logger.info("...", extra={"title": ...})`), dict arguments, and
`key=value` / `"key": value` shapes inside a formatted message — in the record's `msg` and `args`, which is
everything the filter is handed.

**The exception form, which used to be a hole and is now closed.** This paragraph once said the forms
above were "the full range of ways a field name travels with its value". They were not: an exception's text
is rendered by the Formatter from `record.exc_info`, so `logger.exception(...)` inside an `except` block
whose exception message reads `could not parse title=<value>` emitted that value verbatim — and vault
extraction is exactly the code that raises with the document it was parsing in the message.

It is closed by rendering the traceback in the filter, scrubbing it, and assigning `record.exc_text`, which
the Formatter then uses instead of rendering it again. `stack_info` goes the same way. Only when something
was actually redacted, so a custom `formatException` survives in the ordinary case.

**What this cannot catch, stated rather than papered over.** A bare value logged without its field name —
`logger.info(item.title)` — is invisible to a name-based filter, because at that point there is no name to
match. Nothing short of tainting values at the ORM boundary would see it. The honest mitigation is that K3
fields are read through the vault service, which does not log their values, and that the test below fails
loudly on the named forms. A reviewer should treat `logger.*(some_k3_value)` as a defect on sight; the
filter will not save them.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Any

from .models import TOP_CLASS, top_class_field_names

REDACTION = f"[{TOP_CLASS} redacted]"

#: printf-style conversion specifiers, as the logging module interpolates them.
_SPECIFIER = re.compile(r"%(?:\([^)]*\))?[-+ #0]*\*?\d*(?:\.\*?\d+)?[hlL]?[diouxXeEfFgGcrsa%]")

#: A field name sitting immediately before a placeholder: `title=`, `"title": `, `title:`.
_TRAILING_KEY = re.compile(r"(?P<key>['\"]?[A-Za-z_][A-Za-z0-9_]*['\"]?)\s*[=:]\s*$")


class TopClassRedactingFilter(logging.Filter):
    """Drops top-class fields by name from the record, its args and its extras.

    Returns True always: the line is kept, its sensitive fields are not. Dropping whole lines would remove
    the diagnostic value that made someone log them, and would hide that a K3 field was nearly disclosed.
    """

    def __init__(self, name: str = "") -> None:
        super().__init__(name)
        self._names: frozenset[str] = frozenset()
        self._pattern: re.Pattern[str] | None = None

    def _refresh(self) -> None:
        names = top_class_field_names()
        if names == self._names and self._pattern is not None:
            return
        self._names = names
        if not names:
            self._pattern = None
            return
        alternation = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        # `field=value`, `field: value`, `'field': value`, `"field": value` — up to the next delimiter.
        self._pattern = re.compile(
            # The value is a quoted string, or a run that stops at a clause delimiter OR at the next
            # `key=` / `key:`. Without the lookahead an unquoted multi-word value either leaks its tail
            # (bounded at whitespace) or eats the fields after it (bounded at the delimiter alone).
            rf"""(?P<key>['"]?\b(?:{alternation})\b['"]?)\s*(?P<sep>[=:])\s*"""
            rf"""(?P<value>'[^']*'|"[^"]*"|(?:(?!\s+['"]?[A-Za-z_][A-Za-z0-9_]*['"]?\s*[=:])[^,;}}\)\]])+)""",
            re.VERBOSE,
        )

    def _scrub_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: (REDACTION if k in self._names else self._scrub_value(v)) for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            scrubbed = [self._scrub_value(v) for v in value]
            return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
        return value

    def _scrub_text(self, text: str) -> str:
        """Redact `key=value` in already-rendered text, and leave an already-redacted one alone.

        **Idempotence is load-bearing now.** The filter is attached to handlers as well as to loggers, so
        one record can pass through it more than once, and both `_scrub_placeholders` and this backstop
        run within a single pass. Without the guard below, `title=%s` came out of the real server as
        `title=[K3 redacted]]` — the value pattern stops at `]`, so it re-matched its own output and
        appended a bracket per pass. The value was never disclosed; the log line was just wrong, and a
        redaction marker that grows is one a reader stops trusting.
        """
        if self._pattern is None:
            return text

        already = (REDACTION, REDACTION.rstrip("]"))

        def replace(match: re.Match[str]) -> str:
            if match.group("value").strip() in already:
                return match.group(0)
            return f"{match.group('key')}{match.group('sep')}{REDACTION}"

        return self._pattern.sub(replace, text)

    def _scrub_placeholders(self, record: logging.LogRecord) -> None:
        """Redact `title=%s` in the format string AND drop the matching argument.

        This runs before the message is rendered, and it is the reason the filter does not have to guess
        where an unquoted value ends. Scrubbing the rendered text alone cannot tell
        `title=Pensionskassenausweis Helvetia 2026 for member` from the words that follow it, so it either
        leaks the tail or eats the sentence. Redacting the *placeholder* is exact: the argument that would
        have filled it is removed with it.
        """
        if not isinstance(record.msg, str) or not isinstance(record.args, tuple) or not record.args:
            return

        pieces: list[str] = []
        kept: list[object] = []
        last_end = 0
        arg_index = 0
        changed = False

        for match in _SPECIFIER.finditer(record.msg):
            if match.group(0) == "%%":
                continue
            preceding = record.msg[last_end : match.start()]
            pieces.append(preceding)
            if arg_index < len(record.args) and _TRAILING_KEY.search(preceding):
                key = _TRAILING_KEY.search(preceding).group("key").strip("'\"")  # type: ignore[union-attr]
                if key in self._names:
                    pieces.append(REDACTION)
                    changed = True
                else:
                    pieces.append(match.group(0))
                    kept.append(record.args[arg_index])
            else:
                pieces.append(match.group(0))
                if arg_index < len(record.args):
                    kept.append(record.args[arg_index])
            last_end = match.end()
            arg_index += 1

        if not changed:
            return
        pieces.append(record.msg[last_end:])
        kept.extend(record.args[arg_index:])
        record.msg = "".join(pieces)
        record.args = tuple(kept)

    def _scrub_exception_text(self, record: logging.LogRecord) -> None:
        """Render the traceback here, scrub it, and hand it back through `record.exc_text`.

        **Why this works when "a filter never sees the traceback" was true.** It does not see it, but it
        does not have to. `logging.Formatter.format` renders `record.exc_info` only when `record.exc_text`
        is empty, and uses `exc_text` verbatim when it is set. So the filter renders the exception itself,
        runs the same text scrubber the message goes through, and assigns the result — the Formatter then
        emits the redacted rendering because it believes someone already did the work.

        **Only when something was actually redacted.** Leaving `exc_text` unset in the common case matters:
        a JSON or otherwise custom Formatter overrides `formatException`, and pre-rendering every traceback
        with the stdlib's version would quietly flatten that. The cost of the exception is that a record
        needing redaction loses a custom exception rendering, which is the right way round.

        `stack_info` is scrubbed on the same reasoning — `logger.error(..., stack_info=True)` renders a
        frame list that can carry a local variable's value into the line.
        """
        if record.exc_text:
            scrubbed = self._scrub_text(record.exc_text)
            if scrubbed != record.exc_text:
                record.exc_text = scrubbed
        elif isinstance(record.exc_info, tuple) and record.exc_info[1] is not None:
            rendered = "".join(traceback.format_exception(*record.exc_info)).rstrip()
            scrubbed = self._scrub_text(rendered)
            if scrubbed != rendered:
                record.exc_text = scrubbed

        if record.stack_info:
            scrubbed = self._scrub_text(record.stack_info)
            if scrubbed != record.stack_info:
                record.stack_info = scrubbed

    def filter(self, record: logging.LogRecord) -> bool:
        self._refresh()
        if not self._names:
            return True

        # Extras land as plain attributes on the record.
        for name in list(vars(record)):
            if name in self._names:
                setattr(record, name, REDACTION)

        if isinstance(record.args, dict):
            record.args = self._scrub_value(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(self._scrub_value(a) for a in record.args)

        if isinstance(record.msg, (dict, list, tuple)):
            record.msg = self._scrub_value(record.msg)

        self._scrub_placeholders(record)
        self._scrub_exception_text(record)

        # Backstop for text that arrived already interpolated. Bounded at clause delimiters rather than at
        # whitespace, so an unquoted multi-word value is over-redacted rather than half-redacted — the safe
        # direction of the two.
        try:
            rendered = record.getMessage()
        except Exception:  # a broken format string is not this filter's problem
            return True
        scrubbed = self._scrub_text(rendered)
        if scrubbed != rendered:
            record.msg = scrubbed
            record.args = ()
        return True


# ================================================================ installation
#
# **This half was the defect, not the filter.** `api/main.py` calls `install()` at import time, on the root
# logger, which at that moment has no handlers. The old `install()` attached the filter to the logger and
# to `target.handlers` — an empty list — and uvicorn added its handlers afterwards. A filter attached at
# *logger* level does not run for records that arrive by propagation from an `eigentlich.*` child logger, so
# in the running server `logger.info("title=%s", value)` reached the handler unredacted. The filter was
# installed and inert: exactly the shape of A20, A63 and A66 — a guarantee that had stopped holding while
# nothing complained.
#
# Three things are needed for the filter to be effective, and all three are here:
#
#   1. it is attached to HANDLERS, not only to loggers. A handler filter runs for every record the handler
#      emits, including one that arrived by propagation from a child. That is the load-bearing change.
#   2. every handler that already exists when `install()` runs is swept — including `logging.lastResort`,
#      which is what actually emits `eigentlich.*` records under uvicorn, because uvicorn configures its own
#      loggers and leaves the root logger with no handlers at all.
#   3. handlers added AFTER `install()` are caught by a one-method patch of `logging.Logger.addHandler`.
#      That is the single funnel `dictConfig`, `basicConfig`, uvicorn and pytest's caplog all go through.
#      Without it the guard would be correct only for the handlers that happened to exist at import.
#
# Residual, stated rather than papered over: a handler attached by mutating `logger.handlers` directly
# rather than through `addHandler()` is not seen until the next `install()` call. `api/main.py` re-runs
# `install()` from its lifespan hook, after the server's own logging is fully configured, which closes the
# realistic version of that.

_installed: TopClassRedactingFilter | None = None


def _attach(filterer: logging.Filterer, instance: TopClassRedactingFilter) -> bool:
    if instance in filterer.filters:
        return False
    filterer.addFilter(instance)
    return True


def _known_loggers() -> list[logging.Logger]:
    manager = logging.Logger.manager
    loggers: list[logging.Logger] = [logging.root]
    for existing in list(manager.loggerDict.values()):
        if isinstance(existing, logging.Logger):  # skips PlaceHolder entries
            loggers.append(existing)
    return loggers


def _known_handlers() -> list[logging.Handler]:
    handlers: list[logging.Handler] = []
    for logger in _known_loggers():
        for handler in list(logger.handlers):
            if handler not in handlers:
                handlers.append(handler)
    # The handler that emits when nothing else is configured. Under uvicorn this is the one an
    # `eigentlich.*` warning actually goes through, so leaving it out would leave the real path uncovered.
    last_resort = getattr(logging, "lastResort", None)
    if isinstance(last_resort, logging.Handler) and last_resort not in handlers:
        handlers.append(last_resort)
    return handlers


def _patch_add_handler() -> None:
    """Make `Logger.addHandler` attach the filter to whatever is being added. Idempotent."""
    if getattr(logging.Logger.addHandler, "_eigentlich_c04", False):
        return
    original = logging.Logger.addHandler

    def addHandler(self: logging.Logger, hdlr: logging.Handler) -> None:  # noqa: N802 - stdlib's name
        original(self, hdlr)
        instance = _installed
        if instance is not None and instance not in hdlr.filters:
            hdlr.addFilter(instance)

    addHandler.__doc__ = original.__doc__
    addHandler._eigentlich_c04 = True  # type: ignore[attr-defined]
    addHandler._eigentlich_original = original  # type: ignore[attr-defined]
    logging.Logger.addHandler = addHandler  # type: ignore[method-assign]


def covered_handlers() -> list[logging.Handler]:
    """Every handler the filter is currently attached to. Diagnostic, and what the tests assert against."""
    instance = _installed
    if instance is None:
        return []
    return [handler for handler in _known_handlers() if instance in handler.filters]


def install(logger: logging.Logger | None = None) -> TopClassRedactingFilter:
    """Make the filter effective, now and for handlers that arrive later. Safe to call repeatedly.

    One filter instance for the process — calling this twice attaches the same object rather than stacking
    a second copy on every handler. Returns it, so a caller can assert on what was installed.
    """
    global _installed
    instance = _installed
    if instance is None:
        instance = _installed = TopClassRedactingFilter()

    # The logger too: it costs nothing and it covers a record logged directly on `logger` before any
    # handler sees it. It is NOT what makes this work — see the note above.
    target = logger if logger is not None else logging.root
    _attach(target, instance)
    for handler in list(target.handlers):
        _attach(handler, instance)

    for handler in _known_handlers():
        _attach(handler, instance)

    _patch_add_handler()
    return instance


def uninstall() -> None:
    """Detach the filter everywhere and restore `logging.Logger.addHandler`.

    For tests that have to plant the defect back and watch a guard fail. Not called by the application:
    C-04 has no off switch in the running server.
    """
    global _installed
    instance = _installed
    if instance is not None:
        for logger in _known_loggers():
            if instance in logger.filters:
                logger.removeFilter(instance)
        for handler in _known_handlers():
            if instance in handler.filters:
                handler.removeFilter(instance)
    _installed = None

    original = getattr(logging.Logger.addHandler, "_eigentlich_original", None)
    if original is not None:
        logging.Logger.addHandler = original  # type: ignore[method-assign]
