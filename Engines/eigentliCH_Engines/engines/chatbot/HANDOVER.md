# eigentliCH ChatBot (chatbot): handover

Where the build stands, how to pick it up, and what is still open. The README is the reference; this file is the
resume point. Model-derived research output; not investment advice.

## State (03.10.2026, the deployment's engine changes)

- **`Engines/deploy/ENGINE_CHANGES.md` items 3 and 10** (CHB-24, CHB-25): `Store.initialise()` takes a transaction-level
  advisory lock before it applies `schema.sql`, so processes starting together queue instead of deadlocking on
  `pg_proc`; `serve` leaves `/health` out of uvicorn's access log. No contract, figure or key moves, so the
  engine version stays `chatbot@1.2.0`. 155 tests pass. **The running server on 8016 needs a restart** for the quieter
  access log; the lock matters only at the next start, so nothing is urgent.

## State (29.09.2026)

- **Engine 16, v1.2.0**, calibration 1.1.0, prompt `chatbot-prompt@1.2.0`. 151 tests pass
  (`python -m pytest`, about 20 s, needs the PostgreSQL container); the live test against spark7 passes
  (`python -m pytest -m live -s`: grounded answer 3.4 s, first byte 0.42 s; the growth-strategy question
  without grounding 11.1 s, answered as a general assessment; the app's incapacity request 18.9 s, answered).
- **29.09.2026, the wider domain** (CHB-23): care for a parent, incapacity and inheritance were refused as out
  of domain when the app's notes did not cover them; the prompt now names the whole domain and says that
  uncovered notes never make a question out of domain. Golden: thirteen cases, re-frozen from spark7.
  The running server on 8016 needs a restart to serve prompt 1.2.0 (the owner's session restarts it).
- **29.09.2026, owner's change**: no refusal for lack of grounding (CHB-18); refused only without a word, when
  unintelligible or outside the domain (CHB-19); `chat-answer@1.0.0` gained the optional fields `basis` and
  `model_display_name` (CHB-20); the AI is called MiniMind, spark7 is the server (CHB-21). Calibration 1.0.0
  stays in the store as history and is refused as a request (CHB-22).
- Store: database `simtech`, schema `chatbot`, role `chatbot` (provisioned outside this folder). Password in
  `config.local.yaml` (git-ignored). The tests build and drop throwaway schemas `t_<uuid>` as that role.
- spark7 token: `SPARK7_CLIENT_ID`, `SPARK7_CLIENT_SECRET` in `eigentliCH_Engines/.env` (git-ignored), the existing
  Cloudflare Access service token (the owner's decision).
- Golden: thirteen cases with spark7's real replies frozen on 29.09.2026 (prompt 1.2.0).

## Resume

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\eigentliCH_Engines\engines\chatbot && start.cmd      :: 8016, test bench at http://127.0.0.1:8016/
..\..\.venv\Scripts\python -m pytest
```

After a prompt or calibration change: `python dev/build_golden.py --live` (asks spark7 once per case), check the
diff of `golden/cases.json`, and give the prompt a new `PROMPT_VERSION`.

## Open points

1. **Unverified numbers are reported, not withheld** (CHB-07): the consumer app shows them flagged (the owner's
   decision). General answers make this more frequent in principle; the prompt forbids numbers from no source.
2. **The consumer app** should show `basis` (for example a style for the general part, which starts at the
   marking line) and read `model_display_name`; a strict mirror of `chat-answer@1.0.0` must add both optional
   fields. The app's retrieval is being fixed separately; answers with notes stay cited.
3. **Misattribution is not caught**: a true figure under the wrong label passes the number check. Closing it needs
   an entailment check, not arithmetic (prior art A76).
4. **Languages**: French and Italian (the prior art's four) are not built.
5. **Retrieval is the caller's**: the consumer app chooses the approved notes; the engine has no index of its own.
6. **The refusal text** of calibration 1.1.0 still lists the domain briefly ("Geld, Einkommen, Beruf, Vorsorge,
   Versicherungen, Steuern, Wohnen und Anlegen"); widening it is a calibration change (1.2.0) and was left out
   of CHB-23, since it is shown only on a refusal.
7. The family README (`eigentliCH_Engines/README.md`) still lists this engine as a scaffold; it was outside this
   build's folders.
8. Deploy folder when signed off: `python dev/make_deploy.py`.
