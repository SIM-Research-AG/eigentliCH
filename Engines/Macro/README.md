# sim-tech Macro engines

> **Start with [HANDOVER.md](HANDOVER.md).** Open work is tracked on the Notion project
> "sim-tech Macro Engine".

The macro side of the engine roster (Engine Building Guide section 4). One folder per
engine under `engines/`, each a self-contained FastAPI service with its own README,
configuration, tests and port. Engines talk over HTTP through published contracts only.

Flow: `datafeed` feeds `mrs`, `cycle` and `macrofield`; `aggregation` combines them into the
Regime for the instrument engine and the optimiser. `honi` reads `datafeed`; its scores are
used by the CIO, outside the automated flow.

| Engine | Folder | Port | Status |
|---|---|---|---|
| Data Feed | `engines/datafeed` | 8001 | Built: Bloomberg snapshot in PostgreSQL, public-source fills |
| Health of Nations Index | `engines/honi` | 8002 | Built: port of `HoNI2.m`, reads datafeed |
| Macro Field (three-body) | `engines/macrofield` | 8003 | Built v0.4.0, parked |
| Market Risk Signal | `engines/mrs` | 8005 | Parked mid-port (see its HANDOVER.md) |
| Cycle Model | `engines/cycle` | 8012 | Built: port of the first draft's cycles, reads datafeed and macrofield |
| Aggregation layer | `engines/aggregation` | 8004 | Built 28.09.2026: combines mrs, cycle and macrofield into the Regime (issues `regime_id`, applies optimism); first draft reproduced exactly |

The virtual environment `.venv` in this folder is shared by the Macro engines;
`python -m venv .venv` then `pip install -e engines/<name>[dev]`.

Start order: PostgreSQL (`docker compose up -d` in `Projects\PostgreSQL`), then
`engines\datafeed\start.cmd`, then the engine you need (`honi`, `macrofield`, `mrs`, `cycle`, `aggregation`). First
time only: `python -m datafeed bootstrap --create-database`, then `python -m <engine> init-db`.

Model-derived research output. Not investment advice.
