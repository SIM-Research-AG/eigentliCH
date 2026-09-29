# Engine 16: eigentliCH ChatBot (`chatbot`)

MiniMind, the house's AI, answers a client's question: from the approved knowledge notes the caller chose where
they cover it, cited, and from general knowledge where they do not, marked as a general assessment. MiniMind
runs on the house's AI server, spark7. The model composes words and does no arithmetic; every number in an
answer is checked against the grounding and the client facts. Refused are only a question without a word in
it, one that cannot be understood, and one outside the system's domain entirely (CHB-18, CHB-19, CHB-23). The
domain is wide: personal finances, work and income, pensions, insurance, taxes, housing, the law around family,
estate and incapacity, care arrangements and their costs, and health as it bears on work and money. Engine page: https://app.notion.com/p/3e80ba72543f81ab9706e18e563646f8

> Model-derived research output. An answer is composed by MiniMind, a language model, from the notes it was given
> and, marked, from general knowledge; its figures are checked, its wording is not a recommendation. **Not investment advice.**

| | |
|---|---|
| Family | Communication |
| Module | `chatbot` |
| Default port | 8016 (configurable) |
| Status | v1.2.0 (29.09.2026), calibration 1.1.0, prompt `chatbot-prompt@1.2.0`; 151 tests and one opt-in live test |
| Consumes | `ChatRequest` from the caller (the consumer app): question, grounding, client facts, history |
| Produces | `ChatAnswer` (`chat-answer@1.0.0`) |
| Model | MiniMind (display name), served by spark7 (`https://spark7.minimind.ch`, vLLM), `google/gemma-4-31B-it-qat-w4a16-ct` |

## Run it

```bat
cd Projects\PostgreSQL && docker compose up -d
cd Projects\Engines\eigentliCH_Engines\engines\chatbot
start.cmd                                    :: engine on 8016, test bench at http://127.0.0.1:8016/
```

First time: `..\..\.venv\Scripts\pip install --no-deps -e .`, the role and schema `chatbot` (provisioned by
`python -m store.provision` in `Projects\Engines\Instruments`), the database password in `config.local.yaml`
(`database: password: ...`, git-ignored) and the spark7 token in the family `.env`
(`eigentliCH_Engines\.env`, git-ignored: `SPARK7_CLIENT_ID`, `SPARK7_CLIENT_SECRET`). `python -m chatbot probe`
checks the model service without printing a header; `python -m chatbot init-db` creates the tables.

```bash
python -m pytest              # 151 tests, real PostgreSQL, spark7 stand-in on a real socket
python -m pytest -m live -s   # one test against the real spark7
```

## How an answer is made

1. **The key.** The idempotency key is the content hash of the whole request (question, language, grounding,
   client facts, history), the calibration's hash, the model's name and host, the prompt version and its hash,
   and the engine and contract versions. The model is not deterministic, so the key does not promise the same
   text from a second call; it promises the same **stored** answer. A key already answered is answered from the
   store and the model is not called (CHB-06).
2. **Only a question without a word is refused before the model** (CHB-19): no run of two letters ("???").
   A question without grounding goes to the model, which is told there are no notes.
3. **The route** (CHB-08). The client facts reach the prompt only when the question is about the client
   (first-person markers, after `boundary.asks_about_the_member`); for a question about the world they are
   withheld, and the answer says so in its warnings.
4. **The model** answers under guided decoding with `{status, from_notes, general, cited}`. A reply that is
   not that object, or that leaves the language, is redrafted (twice at most, with a language reminder); then
   the run fails with 502. `status` `out_of_domain` or `unintelligible` is a refusal (`not_covered`, the
   reason says which); the reader sees the calibration's fixed text, not the model's words. Out of domain is
   narrow (a recipe, a sports result, programming help, a medical diagnosis); notes that do not cover a
   question never make it out of domain (CHB-23).
5. **The answer is composed by the code** (CHB-18): the part from the notes, then the general part under the
   fixed line "Allgemeine Einschätzung von MiniMind, nicht aus den geprüften Unterlagen:" ("General assessment
   by MiniMind, not drawn from the approved notes:"). A part given as from the notes that cites no given note
   is shown as general. `basis` is `grounded`, `general` or `mixed`.
6. **The checks.** Presentation is removed, German is written the Swiss way (`ss`) with the polite form repaired
   where a word swap can repair it; citations are kept only for notes that were given; every number of two or
   more digits is looked up in the sources the answer was allowed to use (CHB-07). A number that matches none
   is listed in `unverified_numbers` and in the warnings.

**The number check** accepts a figure only as one of its enumerated renderings, never within a tolerance: the
value as written or rounded to 0, 1 or 2 decimals (half up, as prose rounds, and half even); in thousands or
millions only when the answer writes the scale word ("1,6 Millionen"); as a percentage only when the answer
writes a percent sign and the value is a share. Dates are matched as dates. Every Swiss, German and English
spelling of a number is read (`7'258`, `7 258`, `7.258`). It catches a figure that is in no source. It does
**not** catch a true figure under a wrong label, which is why the answer is model-derived output.

## Contracts

`ChatRequest` (`chat-request@1.0.0`): `question` (1 to 2000 characters), `language` (`de` or `en`),
`grounding` [{`id`, `title`, `text`, `source_label`}] chosen by the caller, `client_facts`
[{`key`, `label`, `value` (number or text), `source`}], `history` [{`role` user or assistant, `content`}],
`calibration_version`.

`ChatAnswer` (`chat-answer@1.0.0`): `artefact_id` (`CHB-...`), `question`, `language`, `answer`, `cited_ids`,
`numbers` [{`text`, `matched` (grounding ids, `fact:<key>`, `question`, `history`)}], `unverified_numbers`,
`refused`, `refusal_code` (`not_covered`; `no_grounding` only on answers stored before 1.1.0),
`refusal_reason` (`out_of_domain: ...` or `unintelligible: ...`), `route` (`population_fact` or
`client_situation`), `basis` (optional: `grounded`, `general`, `mixed`, `null` on a refusal), `warnings`,
`model` (technical name), `model_display_name` (optional: `MiniMind`), `prompt_version`, `latency_ms`, `provenance` (engine and contract
versions, calibration and its hash, idempotency key, request hash, grounding ids and hash, client fact keys,
whether they were used, history turns used, the model call: service, host, model, prompt version and hash,
finish reason, drafts, first byte, tokens), `notice` ("Composed by MiniMind. Model-derived research output. Not
investment advice."). `basis` and `model_display_name` were added as optional fields; the contract version is
unchanged (CHB-20).

## Endpoints

Standard (Guide 2.1): `GET /health`, `/meta`, `/contracts`, `POST /run` ({`run_id`, `status`, `artefact_id`,
`idempotency_key`, `cached`}), `GET /runs`, `/runs/{run_id}`, `/artefacts/{artefact_id}`, `GET` and
`PUT /calibration`. Engine specific:

| Method | Path | |
|---|---|---|
| POST | `/answer` | `POST /run` returning the `ChatAnswer` itself; 503 when spark7 cannot answer now, 502 when it answered with nothing usable |
| GET | `/model` | Live probe of the model service: reachable, serving the configured model |
| GET | `/calibration/versions` | Calibrations, the active one marked |

## spark7

MiniMind is the name readers see (`model.display_name`, CHB-21); spark7 is the server. One config block
(`config.yaml`, `model:`) names the display name, the service, the protocol (`openai`: vLLM speaks the
OpenAI-compatible routes only), the base URL, the model, the timeouts and the headers, the secret ones by
**variable name** only. The client (`src/chatbot/spark7.py`, this engine's own copy, httpx only):

* **streams every call** (SSE): the access proxy cuts a response that has not started within 125 s, so only the
  first byte has to beat it; `first_byte_s` (120) is also the longest silence tolerated between chunks, and
  `total_s` (300) bounds the whole call;
* sends `CF-Access-Client-Id` and `CF-Access-Client-Secret` from the environment (or the family `.env`) and
  `Cache-Control: no-cache, no-store, must-revalidate`; the values appear in no message, log, `/meta` or answer;
* refuses at start a known external generative-AI provider by name, and any host that is neither loopback nor
  `*.minimind.ch`, and plain http to a remote host (CHB-04);
* refuses an answer that names another model than the configured one;
* maps failures to two kinds: *unavailable* (unreachable, timeout, 401/403 with the missing variable named,
  429, 5xx, 524) and *unusable* (400/404/422, a broken stream);
* keeps the model loaded with a one-token **warm-up tick** every 240 s (`CHATBOT_WARMUP=0` turns it off).

**Live, 29.09.2026** (calibration 1.1.0): `/v1/models` 0.40 s; one grounded German answer in 3.6 s (first byte
0.43 s), citing the right note, both figures verified; the growth-strategy question without grounding answered in
10.7 s as a general assessment, five concrete steps, no figure. Nine golden cases frozen from spark7: 1.9 to
10.9 s each (general answers are longer); in the arithmetic case the model named the age and the reference age
and did not compute the difference. **Prompt 1.2.0** (CHB-23): thirteen golden cases re-frozen, 1.5 to 21.3 s;
the care, incapacity and inheritance requests the app had sent (refused under 1.1.0, reproduced live) answered as
general assessments, the medical diagnosis refused; the live test passes (grounded answer 3.4 s, first byte
0.42 s; the incapacity request answered in 18.9 s).

## Model quality

* **Golden** (`golden/requests.json`, `golden/cases.json`): spark7's real replies to thirteen cases (grounded,
  not in the notes, no grounding, the growth-strategy question with client facts, mixed, arithmetic, out of
  domain, without a word, a medical diagnosis, and the app's care, incapacity and inheritance requests with the
  notes it sent), frozen once by
  `dev/build_golden.py --live`, replayed through the stand-in; the engine's answer, citations, number check,
  refusal, route, basis, display name and warnings must be exactly the frozen ones.
* **Property tests** (hypothesis): every rendering of a figure verifies; a different integer never does.
* **Boundary**: the role cannot write outside its schema, owns it, no `REAL` column (swept over the built
  schema), every table commented, append-only triggers on answers and calibrations; a concurrent burst of six
  identical questions against a real socket calls the model once; two engine instances answering one key store
  one answer.
* **Regression tests verified by reverting**: each of these was broken once and its test turned red: date
  masking, the single-digit rule, the scale-word rule, the percent rule, client facts only for a client
  question, the per-key lock, the first stored answer wins, a failed run is not a cached answer, unknown
  citations dropped, the model-name check, the house host rule, the wider domain in the prompt (CHB-23).

## Layout

```
config.yaml            port, the model service, store, active calibration
src/chatbot/
  api.py               routing only
  contracts.py         ChatRequest, ChatAnswer, Calibration
  engine.py            prompt, reply parsing, routing, repairs, number check (pure)
  spark7.py            the model client and the warm-up tick
  calibration.py       seed calibration 1.0.0
  clients.py           (no upstream engine; see its docstring)
  store.py, schema.sql PostgreSQL, schema chatbot, append-only answers and calibrations
  service.py           orchestration
golden/                requests and the frozen live cases
dev/                   build_golden.py, make_deploy.py
testbench/index.html   development only
tests/                 stand-in spark7 (standin.py), engine, client, API, boundary, golden, live
```

Model-derived research output. Not investment advice.
