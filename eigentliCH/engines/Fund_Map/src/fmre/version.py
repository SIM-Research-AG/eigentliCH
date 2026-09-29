__version__ = "0.2.0"

#: The building-block register. Bumped to 0.2.0 on 2026-07-28: a geographic `Region` column was added
#: for all blocks (54 at the time; 8 since the 2026-08-02 cut), distinct from the existing `Risk Signal`
#: scope. See decisions.md D11 and
#: docs/region_assignments.md.
UNIVERSE_VERSION = "fm@0.2.0"

#: The estimator and the ReturnSet payload it emits. Bumped to 0.2.0 on 2026-07-28: each building block
#: now publishes its register classification (name, region_geo, region_scope, home_scenario, currency,
#: asset_class, economic_phase, capital_type, liquidity, esg) alongside its profile, and the ambiguous
#: `region` field is gone. A consumer pinned to re@0.1.0 will not find `region` and must migrate.
ESTIMATOR_VERSION = "re@0.2.0"

STATE_TO_SCENARIO_VERSION = "sts@0.1.0"
