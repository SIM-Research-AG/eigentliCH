# sim-tech Optimizer engines

The Optimizer family of the engine roster (Engine Building Guide section 4). One folder per engine under
`engines/`, each a self-contained FastAPI service with its own README, configuration, tests and port. Engines
talk over HTTP through published contracts only.

| Engine | Folder | Port | Status |
|---|---|---|---|
| 07 Portfolio Creation Program | `engines/pcp` | 8007 | Built v1.0.0 (28.09.2026): the draft's curve fit, the client's regime blend, the 75-row block; runs live against fmre's ReturnSet stamped with the Regime's `regime_id` |

The virtual environment `.venv` in this folder is shared by the Optimizer engines:
`python -m venv .venv`, then `.venv\Scripts\pip install -e engines/<name>[dev]`.

Start order: PostgreSQL (`docker compose up -d` in `Projects\PostgreSQL`), `aggregation`
(`Macro\engines\aggregation\start.cmd`), `fmre` (`Instruments\start.cmd`), then `engines\pcp\start.cmd`.

Model-derived research output. Not investment advice.
