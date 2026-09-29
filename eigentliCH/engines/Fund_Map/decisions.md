# Decisions log — Fund Map and Return Estimation

Every entry corresponds to an item in section 12 of the spec, or to a spec-vs-seed inconsistency discovered while bootstrapping. Every `PROVISIONAL` entry is set for v0.1.0 to unblock the build and is expected to be revisited by the sponsor.

## D1 — State ordering and state-to-scenario map (spec 12.1)

- **State ordering (CONFIRMED).** Index 0 is the worst / crisis-like state. Index 24 is the best / boom-like state.
- **Evidence in the seed.** Growth blocks ascend into index 24 (row 5 US Equities: -40 to +16). Protection hedges descend from index 0 (row 33 Gold: 50 to 0; row 37 Long Volatility: 40 to -3; row 53 Short MSCI: 16 to -40). Both directions agree with crisis-at-0, boom-at-24.
- **State-to-scenario partition (PROVISIONAL).** Equal 5-per-scenario partition. See `src/fmre/registers/seed/state_to_scenario.json`. Not derived from data; a defensible default that respects the ordering. To be replaced with a partition informed by the macro field-model's state properties once available.

## D2 — Economic phase reconciliation (spec 12.2)

- Seed uses `Foundation, Maturing, Optimizing, Saturation` (with US spellings).
- Macro Regime uses `Foundation, Build-up, Optimisation, Saturation`.
- **Decision (PROVISIONAL).** `economic_phase` is descriptive metadata only in v0.1.0, not an estimator input. `Maturing` is retained as a fifth label rather than silently collapsed. A reconciliation map (`Maturing ~ Build-up`, `Optimizing ~ Optimisation`) is exposed for cross-programme joins.

## D3 — home_scenario has no Boom (spec 12.3)

- Seed uses four home_scenarios: `Expansion, Stagnation, Contraction, Crisis`. No `Boom`.
- **Decision (PROVISIONAL).** Left as authored. `home_scenario` is descriptive; it is not used in estimation. The five-scenario ReturnSet dimension is unchanged.

## D4 — Return horizon (spec 12.4)

- **Decision (PROVISIONAL).** The `ret_distribution` values are treated as annualised percent returns. The ReturnSet stamps `horizon_years = 1` unless overridden.

## D5 — House view ownership (spec 12.5)

- **Decision (PROVISIONAL).** Investment-Committee input, versioned, defaulted to the seed weighting to be defined once D1's partition is confirmed. Not required for the seed-load milestone.

## D6 — Low-frequency and illiquid blocks (spec 12.6)

- **Decision (PROVISIONAL).** Blocks with liquidity `Quarterly`, `Yearly`, `Decade` are estimated at native frequency in a separate estimation path. Never silently interpolated into the monthly grid. Deferred until the estimator is built.

## D7 — Covariance retention (spec 12.7)

- **Decision (CONFIRMED).** Regime-conditional per-state covariance IS computed and retained internally for diagnostics and downstream use, but IS NOT emitted on the ReturnSet, consistent with the no-moments rule.

## D8 — Enum spelling: seed vs spec

- Seed uses US spellings: `Stabilization`, `Optimizing`.
- Spec mandates British throughout code and docs.
- **Decision.** External data (the seed) is preserved verbatim. A canonical enum layer with British spelling (`Stabilisation`, `Optimisation`) exists in the register and is used for all emitted contracts and generated prose.

## D9 — Role monotonicity for Cash blocks (spec 4.1 vs seed)

- Spec 4.1: "monotonicity direction consistent with the role (ascending for Growth, descending for Protection blocks; Income and Stabilisation flat-to-mild)".
- Seed: rows 32 (CHF Cash), 35 (USD Cash), 51 (EUR Cash) are role `Protection` with slightly *ascending* shapes (1 -> 2, 0 -> 2). They protect capital by holding value, not by hedging.
- **Decision.** The Protection invariant admits two sub-shapes: (a) descending hedge, tested by `mean(first 5) >= mean(last 5)`; or (b) low-volatility floor, tested by `max(|value|) <= 5`. Row 30 Asia Pacific Arbitrage is `Stabilization` but has a Crisis home_scenario and a defensive shape peaking at index 0-5 then flat; the Stabilisation invariant is a bounded-magnitude check only.

## D10 — Role rename: Growth -> Gain

- Seed uses `Growth`. The framework's four roles per spec 3.1 are `Gain, Income, Stabilisation, Protection`.
- **Decision.** Loader exposes `role` (seed authored) and `canonical_role` (framework's `Gain`). Emitted ReturnSet contracts use canonical roles.

## D12 — Synthetic ingestion & role differentiation (resolved)

Original observation: under plain `SyntheticSource` (uniform GBM with
drift 5%, vol 10% for every ticker), all data-driven per-state estimates
converged to the same annualised drift. Tail states, rarely visited under
the synthetic Markov timeline, fell through to `borrow_from_peers`, which
averaged the FIRST peer's whole profile — including that peer's own seed
fallbacks — into the target. Gold ended up borrowing CHF Cash's cash-flat
profile and losing its hedge signature.

Two fixes were applied in v0.1.0:

**(1) State-conditional synthetic source.** `SyntheticSource` now accepts
an optional `(timeline, state_hints)` pair. When both are supplied, each
month's return is drawn with the mean set by the seed's ret_distribution
for the active state, so the estimator's per-state sample mean recovers
the seed value exactly. Available via `--source seed-aware-synthetic` on
the CLI. See `seed_state_conditional_hints()` in `ingest/sources.py`.

**(2) Stricter peer borrow.** `borrow_from_peers` now fills each missing
state INDEPENDENTLY, averaging only over peers whose method for that
specific state is `data-driven`, `data-driven-trimmed`, or `interpolated`.
Peers' own borrow or seed values are no longer propagated laterally. If no
peer has non-fallback data for state s, the target falls to its own seed
for state s — never inherits a stale peer fallback.

Consequences:
- Role differentiation IS preserved under state-conditional synthetic:
  aggregated `protection.crisis > protection.boom`, `gain.boom > gain.crisis`
  (verified in `test_full_seed_integration.py`).
- Under uniform-drift synthetic (still the default `--source synthetic`),
  role profiles remain flat by construction — no way to differentiate when
  the drift is the same for every ticker. Tests that need role shape use
  the state-conditional path.
- Under real market data (Bloomberg / CSV), the state-conditional path is
  irrelevant: each block's own history fills its states, and the stricter
  peer borrow only fires for genuinely under-observed states with
  qualifying peers.

## D11 — Proxy tickers (informational)

The following tickers appear on multiple building blocks in the seed and are therefore proxies for those blocks:

- `MXWO Index` -> rows 16, 45, 47
- `MXEU Index` -> rows 3, 46
- `SWIIT Index` -> rows 39, 48 (different roles: Alternative-Income vs Real Estate-Income)
- `VXTH Index` -> rows 37, 49

Any block estimated from a proxy will be labelled `proxy` on the estimation block of the ReturnSet per spec 4.3.
