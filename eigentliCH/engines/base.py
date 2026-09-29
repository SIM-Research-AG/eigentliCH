r"""The one interface every engine is reachable through.

Phase 2's goal is "every model reachable through one interface, internals unchanged". This module is that
interface, and it invokes each engine **out of process, in its own environment**.

**Why out of process, which is forced rather than chosen.** The four engines have mutually incompatible
dependencies:

| Engine | Project | pandas | numpy | other |
|---|---|---|---|---|
| Market Signal | Macro_Model | 3.0.5 | 2.5.1 | |
| Return Estimation | Fund_Map | 2.2.3 (pinned <3) | 2.1.3 | |
| Portfolio Optimiser | PCP | 2.2.3 | 2.1.3 | scipy |
| Life Balance Sheet | Life_Balance_Sheet | | 2.5.1 | casadi |

Fund_Map is pinned below pandas 3 because its regime-timeline round-trip fails on the pandas 3 index dtype
change, and that assertion is what guarantees a published timeline reads back identically. Macro_Model runs
pandas 3. **No single interpreter can import both.** Reconciling them would mean changing an engine's pinned
dependencies, which is exactly the "do not refactor yet" the phase forbids.

So an adapter runs the engine's own CLI under the engine's own `python.exe` and reads the contract it wrote.
That also means copying the engines' source into `Master_Model\` would achieve nothing: a copy without its
environment is code that cannot run. See architecture/DECISIONS.md M6.

**What an adapter guarantees.** Typed inputs, a typed contract out, and nothing else: no hidden state, no
partial writes, no silent substitution. The exact command is recorded on the result so a run can be replayed
by hand, which is the crudest and most reliable form of reproducibility.
"""

from __future__ import annotations

import os
import subprocess
import sys
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from contracts.base import Provenance, Reliability, idempotency_key, trace_id_from

#: Where the wrapped engine projects live: this directory. They were relocated under `engines/` on
#: 2026-07-28, so a project sits beside the adapter that wraps it. Their own relative paths (PCP's
#: `../Macro_Model/output/regime`, for instance) still resolve, because all four remain siblings.
PROJECTS = Path(__file__).resolve().parent

#: Where each engine lives and which interpreter runs it. The only place these paths are written down.
ENGINE_HOMES: dict[str, str] = {
    "market_signal": "Macro_Model",
    "return_estimation": "Fund_Map",
    "portfolio_optimiser": "PCP",
    "life_balance_sheet": "Life_Balance_Sheet",
    # Native engines, built in the master model itself. `Master_Model` rather than a sibling project, so
    # `health()` reports where they live without a special case.
    "s_curve_trajectory": "Master_Model",
    "scenario_generator": "Master_Model",
    "score_engine": "Master_Model",
}


class EngineUnavailable(RuntimeError):
    """Raised when an engine's project or interpreter is missing.

    A missing engine fails loudly and says what is absent, per the ground rules. It never falls back to a
    stub, because a stubbed engine that returns plausible numbers is worse than one that refuses.
    """


class EngineFailed(RuntimeError):
    """Raised when an engine ran but did not produce a usable contract.

    Carries the command and the captured output, because an engine failure three projects away is
    undiagnosable without them.
    """

    def __init__(self, message: str, command: Sequence[str], stdout: str = "", stderr: str = "") -> None:
        super().__init__(message)
        self.command = list(command)
        self.stdout = stdout
        self.stderr = stderr

    def detail(self) -> str:
        return (
            f"{self}\n  command: {' '.join(self.command)}\n"
            f"  stdout: {self.stdout.strip()[-800:]}\n  stderr: {self.stderr.strip()[-800:]}"
        )


@dataclass(frozen=True)
class EngineCall:
    """One invocation, recorded so it can be replayed by hand."""

    engine: str
    command: tuple[str, ...]
    cwd: str
    returncode: int
    #: Set when the engine reported a handled failure rather than crashing. The engines use exit code 1 for
    #: an infeasible mandate or a missing input, which is a result rather than a bug.
    handled_failure: bool = False

    def replay(self) -> str:
        return f"cd {self.cwd} && {' '.join(self.command)}"


@dataclass(frozen=True)
class EngineResult:
    """What an adapter returns: the contract, its provenance, and how it was produced."""

    engine: str
    contract: Any
    provenance: Provenance
    call: EngineCall
    idempotency_key: str
    trace_id: str
    notes: tuple[str, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)


class EngineAdapter(ABC):
    """A pure, deterministic wrapper around one engine.

    Subclasses implement `run`, which must be a function of its arguments alone. `internals_unchanged` is a
    class attribute rather than a comment because Phase 2's promise is exactly that, and a subclass that
    starts editing the engine it wraps should have to say so.
    """

    #: Registry key, and the name used in provenance.
    name: str = ""
    #: The engine version, read from the engine where it publishes one.
    model_version: str = "unknown"
    #: Which contract this adapter produces.
    produces: str = ""
    internals_unchanged: bool = True

    # -- environment ------------------------------------------------------

    @property
    def home(self) -> Path:
        if self.name not in ENGINE_HOMES:
            raise EngineUnavailable(f"no home registered for engine {self.name!r}")
        return PROJECTS / ENGINE_HOMES[self.name]

    @property
    def interpreter(self) -> Path:
        """The engine's own interpreter. Never this process's."""
        candidate = self.home / ".venv" / "Scripts" / "python.exe"
        if candidate.exists():
            return candidate
        posix = self.home / ".venv" / "bin" / "python"
        if posix.exists():
            return posix
        raise EngineUnavailable(
            f"engine {self.name!r} has no virtual environment at {self.home / '.venv'}. Each engine runs "
            f"under its own interpreter because their dependencies conflict: create it with\n"
            f"  cd {self.home} && python -m venv .venv && .venv/Scripts/python.exe -m pip install -r "
            f"requirements.txt"
        )

    def available(self) -> bool:
        """Whether this engine can be invoked at all. Used by the health board and to skip smoke tests."""
        try:
            return self.home.exists() and self.interpreter.exists()
        except EngineUnavailable:
            return False

    # -- invocation -------------------------------------------------------

    def invoke(
        self,
        arguments: Sequence[str],
        timeout: int = 900,
        extra_env: Mapping[str, str] | None = None,
        allow_handled_failure: bool = False,
    ) -> tuple[EngineCall, str, str]:
        """Run the engine's CLI and return the call record with its output.

        `allow_handled_failure` permits exit code 1, which the engines use for a handled failure such as an
        infeasible mandate. That is a result to report, not a crash to hide, so the caller decides.

        **Guarded, and guarded here rather than only at `result()`.** This is where a wrapped engine actually
        starts work and where data crosses a process boundary. A check that ran only on the way back would let the
        whole computation happen unmediated and then decline to hand it over, which is an audit trail of a
        computation nobody authorised. See DECISIONS.md M18 for what this does and does not cover.
        """
        from orchestration.control_plane import require_mediation

        require_mediation(self.name)

        command = (str(self.interpreter), *arguments)
        environment = dict(os.environ)
        if extra_env:
            environment.update(extra_env)
        # Deterministic hashing inside the engine, so a run is reproducible rather than dependent on the
        # interpreter's per-process salt.
        environment.setdefault("PYTHONHASHSEED", "0")

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.home),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as error:
            raise EngineUnavailable(f"could not launch engine {self.name!r}: {error}") from error
        except subprocess.TimeoutExpired as error:
            raise EngineFailed(
                f"engine {self.name!r} did not finish within {timeout}s", command, "", str(error)
            ) from error

        handled = completed.returncode == 1 and allow_handled_failure
        if completed.returncode != 0 and not handled:
            raise EngineFailed(
                f"engine {self.name!r} exited {completed.returncode}",
                command,
                completed.stdout,
                completed.stderr,
            )

        call = EngineCall(
            engine=self.name,
            command=command,
            cwd=str(self.home),
            returncode=completed.returncode,
            handled_failure=handled,
        )
        return call, completed.stdout, completed.stderr

    # -- results ----------------------------------------------------------

    def provenance_for(
        self,
        as_of: str,
        reliability: Reliability = Reliability.DERIVED,
        note: str | None = None,
    ) -> Provenance:
        return Provenance(
            source=f"{self.name} ({ENGINE_HOMES.get(self.name, 'unknown')})",
            as_of=as_of,
            model_version=self.model_version,
            reliability=reliability,
            note=note,
        )

    def result(
        self,
        contract: Any,
        call: EngineCall,
        inputs: Any,
        as_of: str,
        notes: Sequence[str] = (),
        raw: Mapping[str, Any] | None = None,
        reliability: Reliability = Reliability.DERIVED,
    ) -> EngineResult:
        """Assemble the result, stamping determinism from the inputs.

        The key is computed from the adapter's inputs rather than from the engine's output, so two calls with
        the same inputs share a key even before either has run. That is what makes it usable as a cache key.

        **This method is the control plane's chokepoint.** Every adapter, wrapped or native, builds its result
        here, so requiring mediation at this one point makes Phase 5's gate structurally true: an engine call
        outside a mediated context raises rather than silently succeeding. Putting the guard on each adapter
        instead would mean a new engine could forget it. See `orchestration.control_plane`.
        """
        # Imported here rather than at module scope: `engines` must remain importable without pulling in
        # orchestration, or the two packages would import each other in a cycle.
        from orchestration.control_plane import record, require_mediation

        require_mediation(self.name)

        key = idempotency_key(inputs, self.model_version)
        result = EngineResult(
            engine=self.name,
            contract=contract,
            provenance=self.provenance_for(as_of, reliability=reliability),
            call=call,
            idempotency_key=key,
            trace_id=trace_id_from(key),
            notes=tuple(notes),
            raw=dict(raw or {}),
        )
        record(
            engine=self.name,
            inputs=inputs,
            produced=contract,
            idempotency_key=key,
            as_of=as_of,
            notes=tuple(notes),
        )
        return result

    @abstractmethod
    def run(self, **kwargs: Any) -> EngineResult:
        """Produce a typed contract. Must be a pure function of its arguments."""

    @abstractmethod
    def smoke(self) -> EngineResult:
        """The Phase 2 gate: run on real sample data and return a schema-valid contract.

        Implemented per engine rather than generically, because "real sample data" means something different
        for a macro model and for a household.
        """


class NativeEngineAdapter(EngineAdapter):
    """An engine that lives in the master model and runs in this process.

    The four engines wrapped from sibling projects must run out of process, because their dependencies are
    mutually incompatible. The engines built *here* have no such problem: they are pure Python over the
    contracts, so a subprocess would buy nothing and cost a process start per call.

    So this subclass overrides the environment machinery: `home` is the master model, there is no separate
    interpreter, and `invoke` is not used. Everything else, the provenance and the determinism stamps, is
    inherited unchanged, so a caller cannot tell from the interface which kind of engine it is holding.
    """

    #: Native engines are written here, so there is nothing to leave unchanged.
    internals_unchanged = True

    @property
    def home(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def interpreter(self) -> Path:
        return Path(sys.executable)

    def available(self) -> bool:
        """Always. A native engine is present whenever the master model is."""
        return True

    def native_call(self) -> EngineCall:
        """A call record for an in-process run, so the result shape is uniform.

        `replay` names the module rather than a shell command, because there is no subprocess to repeat. The
        determinism stamps are what make a native run reproducible.
        """
        return EngineCall(
            engine=self.name,
            command=("<in-process>", f"engines.{self.name}"),
            cwd=str(self.home),
            returncode=0,
        )

    def invoke(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        raise NotImplementedError(
            f"{self.name} is a native engine and runs in this process. Call run() directly rather than "
            f"invoking a subprocess."
        )


# ---------------------------------------------------------------------------
# The registry: the single interface
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, EngineAdapter] = {}


def register(adapter: EngineAdapter) -> EngineAdapter:
    """Register an adapter under its name. Called at import of `engines`."""
    if not adapter.name:
        raise ValueError(f"{type(adapter).__name__} has no name")
    if adapter.name in _REGISTRY:
        raise ValueError(f"engine {adapter.name!r} is already registered")
    _REGISTRY[adapter.name] = adapter
    return adapter


def get(name: str) -> EngineAdapter:
    if name not in _REGISTRY:
        raise EngineUnavailable(
            f"unknown engine {name!r}. Registered: {sorted(_REGISTRY)}."
        )
    return _REGISTRY[name]


def registry() -> dict[str, EngineAdapter]:
    return dict(_REGISTRY)


def health() -> list[dict[str, Any]]:
    """One row per engine: what it is, whether it can run, and what it produces.

    The data behind Phase 6's submodel health board, available now so the board has something real to render
    rather than being invented later.
    """
    rows: list[dict[str, Any]] = []
    for name, adapter in sorted(_REGISTRY.items()):
        rows.append(
            {
                "engine": name,
                "project": ENGINE_HOMES.get(name),
                "produces": adapter.produces,
                "model_version": adapter.model_version,
                "available": adapter.available(),
                "internals_unchanged": adapter.internals_unchanged,
            }
        )
    return rows
