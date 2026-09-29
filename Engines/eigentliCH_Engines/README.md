# eigentliCH engines

The client and communication side of the engine roster (Engine Building Guide, section 4), and the consumer
app that clients use (Engine Build Instruction, section 9). One folder per engine under `engines/`, each a
self-contained FastAPI service with its own README, configuration, tests and port. Engines talk over HTTP
through published contracts only; no engine reads the consumer store.

| Part | Folder | Port | Status |
|---|---|---|---|
| eigentliCH consumer app and its store | `eigentlich` | 8017 | Store built (schema `eigentlich`, content seeded, prototype data migrated); the app is in build |
| 13 Life Balance Sheet | `engines/lbs` | 8013 | Built v1.0.0 (28.09.2026): the deterministic balance sheet from the prototype's services, reproduced exactly, with a Mandate proposal |
| 14 Scenario Generator, LifeBalance Simulator | `engines/lbsim` | 8014 | Scaffold (to be built on `personal_alm`) |
| 15 eigentliCH Report Engine | `engines/report` | 8015 | Built v1.0.0 (28.09.2026): figures from the pcp and lbs artefacts, prose on spark7 checked against them |
| 16 eigentliCH ChatBot | `engines/chatbot` | 8016 | Built v1.0.0 (28.09.2026): answers on spark7 from the grounding the caller sends, every number checked |

Flow: the consumer app stores what the client enters; `lbs` turns it into the balance sheet; the curator
finalises the parameters in the cockpit and runs `pcp`; `report` drafts reports and updates, `chatbot` drafts
answers; approval by the curator only when the client asks for it.

The virtual environment `.venv` in this folder is shared by all parts:
`py -3.12 -m venv .venv`, then `.venv\Scripts\pip install --no-deps -e <folder>` per part (the runtime
packages are listed in each `pyproject.toml`).

spark7 access: `.env` in this folder (git-ignored) holds `SPARK7_CLIENT_ID` and `SPARK7_CLIENT_SECRET`, the
house's Cloudflare Access service token. Never commit it, never print it.

Model-derived research output. Not investment advice.
