"""The Master agent and the six agents.

    Master
      ├─ Client Profile      per-user, owns the twin and its events
      ├─ Knowledge           per-user, education and the RAG index
      ├─ Investment          per-user, THE ONLY ENGINE CALLER
      ├─ Product             per-user, product and entitlement questions
      ├─ Support             per-user, support and the Curator handoff
      └─ Data / Integrations global, feeds and their provenance

**Only the Investment Agent calls engines.** That is an architectural boundary, not a convention, so it is
enforced: every other agent's `may_call_engines` is False, and the control plane's guard refuses a call from an
agent that lacks the permission. A Knowledge Agent that could quietly call the Optimiser would be a second,
unaudited route to a regulated output.

**The Master agent routes; it does not compute.** It chooses which agent handles a request and opens the
mediated context. Keeping the routing separate from the work means the trace log always names an agent that is
accountable for the call, rather than "the system".

**Why the agents are thin here.** Their real content is the reasoning each will eventually do. What Phase 5
needs is the *boundary*: who may call what, under what mediation, leaving what trace. Building elaborate agent
behaviour before that boundary exists would mean retrofitting the boundary afterwards, which is how a wall ends
up with a hole in it.
"""

from __future__ import annotations

import functools
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from orchestration.control_plane import (
    CallContext,
    PreCheckFailed,
    TraceStore,
    mediate,
)


class AgentError(RuntimeError):
    """Raised when a request cannot be routed or an agent is asked to do what it may not."""


@dataclass(frozen=True)
class Agent:
    """One agent: a name, a scope, and whether it may reach the engine room."""

    name: str
    scope: str
    #: The architectural boundary. Only the Investment Agent has this.
    may_call_engines: bool
    #: Whether its outputs can cross the regulated wall. Only the Investment Agent's can, and only via a Curator.
    may_produce_regulated: bool
    description: str
    run_owner: str

    def handle(
        self,
        purpose: str,
        work: Callable[[CallContext], Any],
        household_id: str | None = None,
        regulated: bool = False,
        inputs: Any = None,
        store: TraceStore | None = None,
        strict: bool = True,
    ) -> Any:
        """Do a piece of work inside a mediated context attributed to this agent.

        Every engine call made inside `work` passes the pre-check and leaves a trace, because the control plane's
        guard finds the context this opens.

        Raises:
            AgentError: If this agent may not produce a regulated output but the caller asked for one.
            PreCheckFailed: If the pre-check refuses and `strict` is set.
        """
        if regulated and not self.may_produce_regulated:
            raise AgentError(
                f"the {self.name!r} agent may not produce a regulated output. Only the Investment Agent can, "
                f"and only as analysis that a Curator must then confirm."
            )
        with mediate(
            agent=self.name,
            purpose=purpose,
            household_id=household_id,
            regulated=regulated,
            may_call_engines=self.may_call_engines,
            inputs=inputs,
            store=store,
            strict=strict,
        ) as context:
            return work(context)


#: The six agents plus the Master. Owners are role labels; real names are a later overlay (manual section 6).
MASTER = Agent(
    name="master",
    scope="global",
    may_call_engines=False,
    may_produce_regulated=False,
    description="routes a request to the agent that owns it, and opens the mediated context",
    run_owner="CTO",
)

CLIENT_PROFILE = Agent(
    name="client_profile",
    scope="per-user",
    may_call_engines=False,
    may_produce_regulated=False,
    description="owns the Financial Digital Twin: capture, corrections, and the event stream",
    run_owner="CTO",
)

KNOWLEDGE = Agent(
    name="knowledge",
    scope="per-user",
    may_call_engines=False,
    may_produce_regulated=False,
    description="education, the proprietary wiki and the RAG index; explains, never recommends",
    run_owner="CKL",
)

INVESTMENT = Agent(
    name="investment",
    scope="per-user",
    may_call_engines=True,
    may_produce_regulated=True,
    description="the only engine caller: runs the shared and per-user paths and produces the Recommendation",
    run_owner="CIO",
)

PRODUCT = Agent(
    name="product",
    scope="per-user",
    may_call_engines=False,
    may_produce_regulated=False,
    description="product, entitlement and journey-state questions",
    run_owner="CTO",
)

SUPPORT = Agent(
    name="support",
    scope="per-user",
    may_call_engines=False,
    may_produce_regulated=False,
    description="support, and the handoff into the Curator Workbench",
    run_owner="CTO",
)

DATA_INTEGRATIONS = Agent(
    name="data_integrations",
    scope="global",
    may_call_engines=False,
    may_produce_regulated=False,
    description="feeds, connectors and their provenance; publishes the shared inputs the engines read",
    run_owner="CTO",
)

AGENTS: dict[str, Agent] = {
    a.name: a
    for a in (MASTER, CLIENT_PROFILE, KNOWLEDGE, INVESTMENT, PRODUCT, SUPPORT, DATA_INTEGRATIONS)
}

#: What each kind of request is routed to. The Master consults this rather than deciding ad hoc, so routing is
#: inspectable and a new request type has to declare its owner.
ROUTES: dict[str, str] = {
    "onboard": "client_profile",
    "record_event": "client_profile",
    "correct_event": "client_profile",
    "explain": "knowledge",
    "learn": "knowledge",
    "score": "investment",
    "trajectory": "investment",
    "scenario": "investment",
    "snapshot": "investment",
    "recommend": "investment",
    "shared_path": "investment",
    "per_user_path": "investment",
    # Publishing the Regime is an engine call, so it belongs to the one agent permitted to make one. Routing it
    # to Data / Integrations, where it first sat, was a route to an agent that could not execute it: the boundary
    # would have refused the call it had just been handed. Data / Integrations owns the *inputs* the engines read.
    "publish_regime": "investment",
    "entitlement": "product",
    "support": "support",
    "escalate": "support",
    "refresh_feeds": "data_integrations",
    "ingest_feed": "data_integrations",
}


#: Routes that necessarily make an engine call. Each must be owned by an agent that has engine access, or the
#: boundary would refuse the very request it was just handed.
ENGINE_ROUTES: frozenset[str] = frozenset(
    {
        "score",
        "trajectory",
        "scenario",
        "snapshot",
        "recommend",
        "shared_path",
        "per_user_path",
        "publish_regime",
    }
)


def check_routes() -> None:
    """Prove the route table and the permission table agree.

    Run at import, because a route pointing at an agent that may not do what the route requires is a wiring
    error, not a runtime condition — and it is the kind that stays invisible until the one request that uses it.
    """
    unknown_route = sorted(ENGINE_ROUTES - set(ROUTES))
    if unknown_route:
        raise AgentError(
            f"ENGINE_ROUTES names {unknown_route} which are not in ROUTES. Either route them or stop claiming "
            f"they need an engine."
        )
    unknown_owner = sorted({o for o in ROUTES.values() if o not in AGENTS})
    if unknown_owner:
        raise AgentError(f"ROUTES points at unknown agent(s) {unknown_owner}. Known: {sorted(AGENTS)}.")
    contradictory = sorted(r for r in ENGINE_ROUTES if not AGENTS[ROUTES[r]].may_call_engines)
    if contradictory:
        raise AgentError(
            f"route(s) {contradictory} require an engine call but are owned by an agent without engine access. "
            f"Move the route to the Investment Agent, or split the request so the engine call is a separate one. "
            f"Do not widen the agent's permission: that is the boundary, not a setting."
        )


def agent(name: str) -> Agent:
    if name not in AGENTS:
        raise AgentError(f"unknown agent {name!r}. Known: {sorted(AGENTS)}.")
    return AGENTS[name]


def route(request: str) -> Agent:
    """Which agent owns a kind of request.

    Raises:
        AgentError: On an unrouted request. Deliberately not defaulted to the Investment Agent: defaulting to
            the one agent that may call engines would turn every unrecognised request into a potential engine
            call.
    """
    if request not in ROUTES:
        raise AgentError(
            f"no route for request {request!r}. Known: {sorted(ROUTES)}. Add a route rather than letting it "
            f"fall through: the default would otherwise be the only agent permitted to call engines."
        )
    return agent(ROUTES[request])


def handle(
    request: str,
    purpose: str,
    work: Callable[[CallContext], Any],
    household_id: str | None = None,
    regulated: bool = False,
    inputs: Any = None,
    store: TraceStore | None = None,
    strict: bool = True,
) -> Any:
    """The Master agent's entry point: route the request, then let the owning agent handle it.

    This is the front door. Everything downstream of it is mediated, traced and attributed.
    """
    owner = route(request)
    return owner.handle(
        purpose=purpose,
        work=work,
        household_id=household_id,
        regulated=regulated,
        inputs=inputs,
        store=store,
        strict=strict,
    )


def mediated(
    owner: Agent,
    purpose: str | Callable[[dict[str, Any]], str],
    household_id: str | Callable[[dict[str, Any]], str | None] | None = None,
    regulated: bool | Callable[[dict[str, Any]], bool] = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Declare at the definition that a function runs inside a mediated context owned by `owner`.

    `purpose`, `household_id` and `regulated` may each be a fixed value or a callable taking the function's bound
    arguments, so they can name the household the call is about.

    Declaring mediation here rather than wrapping the body in a second function means the argument list exists
    once. A hand-written wrapper that restates twenty parameters is a wrapper whose defaults will drift from the
    body's, and a drifted default in this path is a run that silently used a different epsilon.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            given = dict(bound.arguments)

            def resolve(value: Any) -> Any:
                return value(given) if callable(value) else value

            return owner.handle(
                purpose=resolve(purpose),
                household_id=resolve(household_id),
                regulated=resolve(regulated),
                work=lambda _context: fn(*args, **kwargs),
            )

        #: The unmediated body, for tests that need to prove the wrapper is what supplies the mediation.
        wrapper.__wrapped_unmediated__ = fn  # type: ignore[attr-defined]
        wrapper.__mediating_agent__ = owner  # type: ignore[attr-defined]
        return wrapper

    return decorate


def boundary_report() -> list[dict[str, Any]]:
    """Who may call what. The data behind the health board's agent panel, and a reviewable statement of the
    engine-room boundary."""
    return [
        {
            "agent": a.name,
            "scope": a.scope,
            "may_call_engines": a.may_call_engines,
            "may_produce_regulated": a.may_produce_regulated,
            "run_owner": a.run_owner,
            "routes": sorted(r for r, owner in ROUTES.items() if owner == a.name),
            "description": a.description,
        }
        for a in AGENTS.values()
    ]


check_routes()
