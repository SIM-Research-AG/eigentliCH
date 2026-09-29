// The only place this client talks to the server.
//
// C-05: every request is same-origin and relative. There is no base URL, no configurable host, and no
// third-party endpoint — so there is nothing to point at an analytics service later without editing this
// file, which is the point. A test asserts the authenticated bundle makes no cross-origin request; this
// module is what makes that assertion cheap to keep true.
//
// **A11, wired 31 August 2026: the member is the token, and no function here takes a member id.** Every
// call used to carry `member_id` as a query parameter or a body field, which is exactly what the server
// used to believe. Both ends changed together: the parameter is gone from the routes and gone from these
// signatures, so a caller cannot supply one by accident and there is no argument to get wrong.
//
// `request` attaches `Authorization: Bearer <token>` when there is one, and throws `ApiError` with status
// 401 when the server refuses. `main.js` treats a 401 from anywhere as "the session is over" and returns
// to the login screen, which is the one place that decision is made.

import * as session from './session.js';

const JSON_HEADERS = { 'Content-Type': 'application/json', Accept: 'application/json' };

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `request failed with ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * A refusal as a sentence, whatever shape the server put it in.
 *
 * **Three shapes arrive on `detail` and only one of them is a string.** FastAPI's own hand-written
 * refusals are strings and every surface written before this one printed `error.detail` directly. Two
 * others are not:
 *
 *   * **Pydantic's validation errors are a list of objects** — `[{type, loc, msg, input}, ...]`. That is
 *     what `PATCH /api/positions/{id}` answers when a client sends `active`, which is the field the
 *     server refuses **by name** and therefore the one a client is most likely to send. Printed the old
 *     way it reads `[object Object]`, so the one refusal written to teach a client something taught it
 *     nothing.
 *   * **`services/runs.NotQueueable` is an object** with a `reason` and a gap list, and `surfaces/runs.js`
 *     already reads it as one rather than flattening it. That surface keeps its own reading; this helper
 *     is the fallback for everywhere else, and it names the reason rather than serialising the object.
 *
 * A28's rule about two lists applies to two *readings* as well: every surface added here calls this, so a
 * fourth shape is handled in one place rather than in seven.
 */
export function detailText(error) {
  if (!(error instanceof ApiError)) return String(error);
  const detail = error.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail)) {
    // `loc` is `["body", "active"]`. The field name is the useful half — a member does not need to be
    // told the word "body" — so the last element is what is named.
    const lines = detail.map((entry) => {
      if (!entry || typeof entry !== 'object') return String(entry);
      const where = Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : null;
      return where ? `${where}: ${entry.msg || ''}`.trim() : String(entry.msg || '');
    });
    const said = lines.filter(Boolean).join('; ');
    if (said) return said;
  }
  if (detail && typeof detail === 'object') {
    if (typeof detail.reason === 'string' && detail.reason) return detail.reason;
    if (typeof detail.detail === 'string' && detail.detail) return detail.detail;
  }
  return String(error.status);
}

async function request(path, options = {}) {
  if (!path.startsWith('/')) throw new Error(`refusing a non-relative request: ${path}`);
  const token = session.token();
  const headers = { ...(options.headers || {}) };
  // Only when there is one. An empty header is a shape the server has to parse, and every shape it has
  // to parse is a shape it can get wrong.
  //
  // **And only when the caller has not set one already.** A40's curator routes authenticate with HTTP
  // Basic against a different table, and a curator signing in on a machine where a member is also logged
  // in must not have the member's bearer token put over the top of their own header — the request would
  // then be made as the member, on a route that answers 401 to one, which reads as a wrong password. The
  // guard is on the caller's header rather than on the path, because a rule about which prefixes are
  // curator routes would be a second list to keep in step with `api/curator.py`.
  if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(path, { credentials: 'same-origin', ...options, headers });
  const text = await response.text();
  const body = text ? JSON.parse(text) : null;
  if (!response.ok) throw new ApiError(response.status, body && body.detail);
  return body;
}

function post(path, payload) {
  return request(path, { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) });
}

// ---------------------------------------------------------------- the session (A11)

/**
 * Log in. The raw token comes back exactly once, in this response, and is stored by `session.begin`.
 *
 * A refusal is a 401 with one message whichever half was wrong — the server will not say whether the
 * address is one it knows, and a client that guessed on its behalf ("no account with that address?")
 * would rebuild the oracle the server refuses to be. So the refusal is shown as it was written.
 */
export function openSession(email, password) {
  return post('/api/session', { email, password });
}

/** Who this token belongs to. The first call after a stored token is found, and its liveness check. */
export function readSession() {
  return request('/api/session');
}

export function endSession() {
  return request('/api/session', { method: 'DELETE' });
}

/**
 * A member changing their own password. The current one is required even when `must_change` is set —
 * that is the server's rule and the forced-change screen sends both fields for that reason.
 */
export function changePassword(current, next) {
  return post('/api/password', { current, new: next });
}

export function createMember(payload) {
  return post('/api/members', payload);
}

/**
 * A12 / A26. Change the language the member reads, and keep it.
 *
 * A `PUT` to a setting rather than a value held in this tab: A26 puts the language on `Member.locale`, so
 * the member chooses it once and finds it again on the next device. Returns the new locale as well as the
 * language, which is what `session.refresh` needs — `de` becomes `de-CH` on the server and this client is
 * deliberately not the thing that knows how.
 */
export function setLanguage(language) {
  return request('/api/settings/language', {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ language }),
  });
}

// ---------------------------------------------------------------- the plan

export function getRoleGrid(language) {
  return request(`/api/positions?${new URLSearchParams({ language })}`);
}

export function createPosition(payload) {
  return post('/api/positions', payload);
}

export function health() {
  return request('/api/health');
}

export function getOnboarding(language) {
  return request(`/api/onboarding?${new URLSearchParams({ language })}`);
}

export function putAnswer(questionKey, value) {
  return request(`/api/onboarding/answers/${encodeURIComponent(questionKey)}`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify({ value }),
  });
}

export function completeOnboarding() {
  return post('/api/onboarding/complete', {});
}

// ---------------------------------------------------------------- the know (S-08)

/**
 * S-08. C-01 is enforced on the far side of this call and nowhere on this one.
 *
 * The response may come back with `requires_curator: true` and that is a successful request, not an error
 * — `request` only throws on a non-2xx. A refusal arriving as an exception is how a boundary ends up being
 * rendered as a fault, which R-172 forbids.
 */
/**
 * Item 5's Regime pane. **The one call in this file that carries no token and names nobody.**
 *
 * `GET /api/regime` is in `OPEN_ROUTES`: the regime is population-level, computed once and shared by
 * everyone, and page 3 makes it the first regulatory boundary — everything on that side can be shown to
 * anyone before signup. So this is deliberately not routed through the authenticated helper.
 */
export function getFeed() {
  return request('/api/feed');
}

export function getRegime() {
  return request('/api/regime');
}

export function askKnow(question, language) {
  return post('/api/know/ask', { question, language });
}

/** R-174. The prepared decisions, fetched when the panel is opened — never polled (R-175). */
export function getActions() {
  return request('/api/actions');
}

/**
 * R-170 / R-173. The named people a member can ask for.
 *
 * Plural, and a different surface from `/api/curator/*`: that prefix is the curator's own workbench and
 * every route under it refuses without a curator login. This one is the staff list, and it is the one
 * member-reachable route that still needs no session — it says a name and a role label, nothing about any
 * member, and R-170 keeps the Curator button on screen at all times, including before login.
 *
 * An empty list is a normal answer, not an error.
 */
export function getCurators() {
  return request('/api/curators');
}

/**
 * R-173 / C-10. `opened_from` is which screen the button was pressed on, recorded at the time.
 *
 * **Deliberately `/api/curators/sessions` and not `/api/curator/sessions`.** The older route was written
 * before anything could check a curator id; this one resolves it against the `curators` table before a row
 * is written. C-10's column says "the identified curator, never a role, never a queue", and the difference
 * between the two routes is whether that is enforced or hoped for.
 *
 * Which *member* opened it is no longer part of the payload: it is the token's member (A11).
 */
export function openCuratorSession(payload) {
  return post('/api/curators/sessions', payload);
}

// ---------------------------------------------------------------- the curator's door (A40 / S-12)
//
// **A different table, a different scheme, and no token.** `POST /api/curator/login` verifies a curator
// and returns their identity; it mints nothing, deliberately (A40 — there is no curator session table).
// So every call here carries HTTP Basic, and every one of them takes the credentials as an argument
// rather than reading them from a module: `app/curator.js` is the one place they are held, for the length
// of one window, and this module stays a set of functions with no memory.
//
// **Nothing here is cached and there is no function that returns a stored answer.** R-213 makes a member's
// revocation immediate, so a grant read once and kept would be a grant that outlives its withdrawal. Every
// screen that shows what a curator may see calls `curatorMembers` or `curatorWorkbench` again.

/**
 * RFC 7617's `Basic` header for one curator.
 *
 * `btoa` takes a latin1 string and throws a `InvalidCharacterError` on any code point above U+00FF, and
 * a curator password containing an umlaut is not hypothetical — `tools/seed_demo_accounts.py` writes
 * German passphrases and the five real curators all have one. So the pair is encoded to UTF-8 bytes and
 * those bytes are handed to `btoa` one at a time, which is the encoding the server decodes in
 * `api/curator.py::authenticating_curator`.
 */
function basic({ email, password }) {
  const bytes = new TextEncoder().encode(`${email}:${password}`);
  let raw = '';
  for (const byte of bytes) raw += String.fromCharCode(byte);
  return `Basic ${btoa(raw)}`;
}

function curatorRequest(credentials, path, options = {}) {
  return request(path, {
    ...options,
    // Set explicitly, which is also what stops `request` attaching a member's bearer token over it.
    headers: { ...(options.headers || {}), Authorization: basic(credentials) },
  });
}

/**
 * A40. Verify a curator and get their identity back. **There is no token in the response.**
 *
 * The payload carries `session_token: null` and `must_change`. A true `must_change` means this credential
 * opens this route and `POST /api/curator/password` and nothing else — the server enforces that, and
 * `surfaces/curator.js` reads the flag only to decide which screen to draw.
 */
export function curatorLogin(credentials) {
  return curatorRequest(credentials, '/api/curator/login', { method: 'POST' });
}

/**
 * A43 / A53. A curator choosing their own password, and the route that makes the seeded ones good for one
 * login rather than forever. The current password is required, exactly as on the member's `/api/password`.
 */
export function changeCuratorPassword(credentials, current, next) {
  return curatorRequest(credentials, '/api/curator/password', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ current, new: next }),
  });
}

/**
 * The worklist: the members who have granted this curator something, and what.
 *
 * Composed on the server from live grants only, so a member who has revoked drops out of it on the same
 * read that would refuse the underlying material. Nothing here is stored between calls.
 */
export function curatorMembers(credentials) {
  return curatorRequest(credentials, '/api/curator/members');
}

/**
 * S-12 / R-210. One member's workbench: `granted_scope`, and `not_granted` named rather than left empty.
 *
 * A 403 is the expected answer for a member who has granted nothing, and it is a real answer — see
 * `services/curator.py` on why a refusal raises instead of returning an emptier payload.
 */
export function curatorWorkbench(credentials, memberId) {
  return curatorRequest(credentials, `/api/curator/members/${encodeURIComponent(memberId)}`);
}

/**
 * R-211 / C-10. Open a recorded consultation. This writes an `opened` event into a table whose UPDATE and
 * DELETE are refused by database trigger, so it is the one action on the curator's landing screen that
 * leaves a permanent mark — which is why the screen says so beside the button rather than afterwards.
 *
 * The member is named in the body here, and that is not A11 leaking back: A11 says *which member is
 * asking* is the token's, and this request is not a member asking. A curator is addressed by member id
 * throughout `/api/curator/*`, and `services/curator.py` refuses without a live scoped grant.
 */
export function openWorkbenchSession(credentials, memberId, openedFrom) {
  return curatorRequest(credentials, '/api/curator/workbench/sessions', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ member_id: memberId, opened_from: openedFrom }),
  });
}

// ---------------------------------------------------------------- R-211 / R-212: holding a consultation
//
// **These four functions did not exist, and their absence had a measurable consequence.** Every route
// behind them was built, tested and reachable only from a test: `POST .../notes`, `POST .../close`,
// `POST .../recommendations` and `GET .../sessions/{id}`. On the shipped database all six
// `curator_sessions` rows carried one `opened` event and `outcome` was NULL on every one — while R-211's
// own sentence is that a session is recorded *with entry point and outcome*. Half of that requirement was
// unreachable from any screen, so no session in the product's history has ever been accounted for.
//
// **The member is in the path, never in a body.** `/api/curator/members/{id}/sessions/{id}/...` — the same
// arrangement `curatorWorkbench` uses, and the reason A11's one permitted `member_id` on the wire stays
// exactly one: `openWorkbenchSession` is still the only function here that names a member in a payload.

/** R-211. The curator's own consultations, so an open one can be found and closed. No member material. */
export function curatorSessions(credentials) {
  return curatorRequest(credentials, '/api/curator/sessions');
}

/**
 * R-211 / C-10. One session: entry point, every appended event, and the outcome.
 *
 * `notes_readable` on the payload says which of two things is being looked at — the note bodies, or an
 * explicit `redacted` marker where a grant has lapsed. The audit stays legible after a revocation; the
 * member's words do not, and a missing note and a withheld note must not look the same.
 */
export function readCuratorSession(credentials, memberId, sessionId) {
  return curatorRequest(
    credentials,
    `/api/curator/members/${encodeURIComponent(memberId)}/sessions/${encodeURIComponent(sessionId)}`,
  );
}

/**
 * C-10. A note, appended to a table whose UPDATE and DELETE are refused by database trigger.
 *
 * Grant-gated on the server: a note written while reading a member's vault is the member's material. A 409
 * means the session is already closed, which is the append-only log refusing to grow a past consultation.
 */
export function addCuratorNote(credentials, memberId, sessionId, text) {
  return curatorRequest(
    credentials,
    `/api/curator/members/${encodeURIComponent(memberId)}/sessions/${encodeURIComponent(sessionId)}/notes`,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ text }) },
  );
}

/**
 * R-211. Closing appends an event carrying the outcome. Nothing on the session row is updated.
 *
 * **`outcome` has no default and this client supplies none.** The server's field is `min_length=1` and the
 * screen refuses an empty one before the request, because an outcome invented by the client would be the
 * one part of the audit that nobody wrote.
 *
 * Deliberately not grant-gated on the server: a member revoking mid-consultation must not be able to leave
 * the audit trail open.
 */
export function closeCuratorSession(credentials, memberId, sessionId, { outcome, note = null, liabilityFlag = null }) {
  return curatorRequest(
    credentials,
    `/api/curator/members/${encodeURIComponent(memberId)}/sessions/${encodeURIComponent(sessionId)}/close`,
    {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ outcome, note, liability_flag: liabilityFlag }),
    },
  );
}

/**
 * R-212 / C-01. The licensed human's recommendation, written as a Decision attributed to that curator.
 *
 * **This is the one place in the product where a recommendation may be produced at all**, and C-01 is what
 * makes it so: the constraint forbids *the application* selecting or weighting for an identified member,
 * and a curator doing so is what the handoff in `boundary.py` exists for. `author_ref` is taken from the
 * authenticated curator on the server and never from anything sent here, so there is no way for this
 * client to write a curator-attributed Decision on somebody else's behalf.
 *
 * A 422 means there is no open session for this member belonging to this curator — R-211 refusing a
 * recommendation made outside a recorded consultation.
 */
export function recordCuratorRecommendation(credentials, memberId, payload) {
  return curatorRequest(
    credentials,
    `/api/curator/members/${encodeURIComponent(memberId)}/recommendations`,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify(payload) },
  );
}

/**
 * R-210's scope vocabulary, so the landing screen names the areas the server knows rather than a list
 * this client invented. Unauthenticated on the server and sent without a credential here.
 */
export function grantableScopes() {
  return request('/api/curator/grantable');
}

// ---------------------------------------------------------------- vault (S-06)

export function getVault() {
  return request('/api/vault');
}

export function createVaultItem(payload) {
  return post('/api/vault', payload);
}

// R-154 / R-231 — **there is deliberately no client function for `GET /api/export`.**
//
// There was one, named `getExport`, and `surfaces/vault.js` called it. That was the outstanding half of
// A93: the GET is R-154's plain read and **writes no Decision**, so R-231's "both producing a Decision
// record" held only on the path nobody called, and the member's own record of having asked for their data
// was never written.
//
// The function is gone rather than merely unused, because an exported function that calls the GET is the
// thing the next author reaches for. What replaced it is `requestExport` below, which is a POST, and the
// method is the argument: a GET must be safe, and each repetition of one — a prefetch, a retry after a
// dropped connection, a proxy revalidation, a double-click — would append a row to a table R-040 makes
// append-only. S-07's screen would fill with export requests the member never made, permanently.
//
// The document is the same either way; `GET /api/export` remains served, for R-154 and for
// `test_export_asymmetry.py`, which pins that the two bodies agree. Nothing in this client asks for it.

// ---------------------------------------------------------------- containers (S-04)

export function getGoals() {
  return request('/api/goals');
}

export function createGoal(payload) {
  return post('/api/goals', payload);
}

/**
 * Change a goal that already exists.
 *
 * **Only the fields the member actually changed are sent**, because the server reads `model_fields_set` to
 * tell "clear the target date" from "leave the target date alone". Sending the whole form back would make
 * those two indistinguishable and would wipe whatever was not retyped — see `GoalRevisionRequest`.
 *
 * The decision fields are not optional: C-09 is enforced on the far side, and a revision without them is
 * refused there rather than being written silently.
 */
export function reviseGoal(goalId, payload) {
  return request(`/api/goals/${encodeURIComponent(goalId)}`, {
    method: 'PUT',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------- the Befund (the standing report)

/**
 * The member's standing report over what they have recorded.
 *
 * **A GET, and the language is a parameter rather than a header.** R-175: the report exists because the
 * member asked for it, and `api/befund.py` answers 422 for a language the report is not written in rather
 * than falling back to German — so the value sent here has to be one the string table also speaks, which
 * is what `i18n.js::languages()` guarantees about `state.language`.
 *
 * `prose` is deliberately not sent. It lets the local model rephrase each computed sentence, defaults to
 * false on the server, and the deterministic report is the product — a client that asked for prose by
 * default would make every screen depend on whether Ollama happened to be running.
 */
export function getBefund(language) {
  return request(`/api/befund?${new URLSearchParams({ language })}`);
}

// ---------------------------------------------------------------- engine runs (R-301)

/** This member's runs, newest first. No counts and no aggregate — R-113, on both ends. */
export function getRuns() {
  return request('/api/runs');
}

/**
 * R-301. Queue one run and get back its id and its poll URL.
 *
 * **A 422 here carries an object, not a sentence.** `services/runs.NotQueueable.as_dict()` travels in
 * `detail` as `{queued, engine, reason, absent: [...]}`, and that gap list is the useful half of the
 * answer: it names which of the member's own inputs is missing. A caller that renders `error.detail` as a
 * string gets `[object Object]` — `surfaces/runs.js` reads the object instead, which is the whole reason
 * the refusal is worth showing rather than flattening to "engine unavailable".
 *
 * No payload field, deliberately: there is nowhere for a caller to put an engine input. The payload is
 * built server-side from rows the plan already holds.
 */
export function startRun(engine, goalId = null) {
  return post('/api/runs', { engine, goal_id: goalId });
}

/** R-301's poll. 404 for a run that is not this member's, which is also a run that never existed. */
export function getRun(runId) {
  return request(`/api/runs/${encodeURIComponent(runId)}`);
}

// ---------------------------------------------------------------- S-07 decisions (R-160 – R-162)

/**
 * R-160. The member's decisions, newest first, filterable by what they touched.
 *
 * The three filters are AND on the server and are sent only when set — an empty string in the query would
 * be a filter for a position whose id is the empty string, which matches nothing, and a screen showing
 * nothing because of a parameter it did not mean to send is the worst kind of empty state.
 *
 * A11: no member id. The decisions are the token's member's, and a filter naming somebody else's position
 * comes back empty rather than refused, because the query is scoped to the member first.
 */
export function getDecisions({ language, positionId = null, goalId = null, vaultItemId = null } = {}) {
  const query = new URLSearchParams({ language });
  if (positionId) query.set('position_id', positionId);
  if (goalId) query.set('goal_id', goalId);
  if (vaultItemId) query.set('vault_item_id', vaultItemId);
  return request(`/api/decisions?${query}`);
}

/** R-161. One decision, what it linked to, and the correction chain it sits in — oldest first. */
export function getDecision(decisionId, language) {
  return request(
    `/api/decisions/${encodeURIComponent(decisionId)}?${new URLSearchParams({ language })}`,
  );
}

/**
 * R-162. **Records a correction. Never an edit**, and the route cannot be one.
 *
 * `POST /api/decisions/{id}/correction` writes a NEW Decision with `corrects_id` set; the prior record is
 * refused an UPDATE by `db.py::before_flush` and again by the `trg_decisions_no_update` trigger. So the
 * control that calls this says "record a correction" and there is no client function named `editDecision`
 * for somebody to reach for — R-162 in the shape of an absent function rather than a comment asking for
 * restraint.
 *
 * No `question`: R-040 makes the question that stood part of what stood, and `record_correction` copies
 * it. A correction answers the same question differently.
 */
export function recordCorrection(decisionId, { choice, reasoning }, language) {
  return request(
    `/api/decisions/${encodeURIComponent(decisionId)}/correction?${new URLSearchParams({ language })}`,
    { method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ choice, reasoning }) },
  );
}

// ---------------------------------------------------------------- R-103 consent, at registration

/**
 * R-103 / C-05. What is being agreed to, before an account exists.
 *
 * **Open, and called without a session** — which is the only reason it can be on the registration form at
 * all. `request` attaches a bearer token when there is one and there is none here, which is correct rather
 * than merely harmless: the statement names no member and reads no member table.
 *
 * **The payload is kept by the caller and echoed back at submit.** `echo_at_registration` is verbatim what
 * `POST /api/members` expects, and the version travels with it so the acceptance is an acceptance of the
 * words that were on the screen. A form left open across a wording change is refused rather than stamped.
 * That is the whole reason this is a separate call rather than a list the client holds: a list in the
 * client is a list that says the wording is whatever the client last shipped with.
 */
export function getConsentStatement(language) {
  return request(`/api/consent-statement?${new URLSearchParams({ language })}`);
}

// ---------------------------------------------------------------- R-230 consent history

/** R-230. Every consent ever given, withdrawn ones included, each with what a withdrawal would mean. */
export function getConsents() {
  return request('/api/settings/consents');
}

/**
 * R-230's second half. Withdraw one consent, by the member, without asking anyone.
 *
 * The body is empty on purpose: it used to carry `member_id`, which was the whole of what "by the member"
 * was failing to mean. Withdrawal marks the row rather than removing it, so there is no `unwithdraw` here
 * and nothing that offers to take an entry out of the history.
 */
export function withdrawConsent(consentId) {
  return request(`/api/settings/consents/${encodeURIComponent(consentId)}/withdraw`, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({}),
  });
}

// ---------------------------------------------------------------- R-231 erasure

/**
 * What the confirmation step requires, in the member's own language. Reads nothing and writes nothing.
 *
 * The sentence is **not** built in this client. It is `confirmation_phrase` from the server, in the
 * language the server derived from `Member.locale`, and it is compared there rather than here — a client
 * that composed it would be a client that could disagree with the thing doing the checking, on the one
 * route whose mistake cannot be corrected.
 */
export function getErasure() {
  return request('/api/settings/erasure');
}

/**
 * R-231. **This destroys the member's record and cannot be undone.**
 *
 * The typed sentence AND the password, both checked in `services/erasure.py` rather than in the route, so
 * a second caller cannot skip them. There is no boolean anywhere in this shape: pydantic's lax mode reads
 * `1`, `"y"` and `"on"` as true, which would make a field meant to express deliberate agreement the most
 * permissive input on the request.
 *
 * **The token dies with this call.** The member's `sessions` rows are among those deleted, so the next
 * request with the same token is a 401. The caller treats the response as a logout — see
 * `surfaces/settings.js`, which ends the local session before it renders the receipt.
 */
export function requestErasure({ confirmation, password, reason = null }) {
  return post('/api/settings/erasure', { confirmation, password, reason });
}

// ---------------------------------------------------------------- R-231 export, as a POST

/**
 * R-231. The export, **and the Decision recording that it was asked for**.
 *
 * **This replaced `getExport`'s use on the export control, and the method is the point.** A GET must be
 * safe. A prefetch, a retry after a dropped connection, a proxy revalidation or a double-click each repeat
 * one, and each repetition would append to `decisions` — a table R-040 makes append-only, where nothing
 * can be tidied away afterwards. S-07's screen would fill with export requests the member never made and
 * there would be no removing them. So the *request* is a POST, and `GET /api/export` stays R-154's plain
 * read that writes nothing.
 *
 * The document is the same either way — both call `services/export.py::export_member`, and
 * `tests/test_export_asymmetry.py` pins that the two bodies agree. What differs is that this one comes
 * wrapped: the file is `payload.export`, with `decision_id` beside it.
 */
export function requestExport(reason = null) {
  return post('/api/settings/export', { reason });
}

// ---------------------------------------------------------------- editing a position (R-122, R-123)

/**
 * R-123's second half. Change a position that already exists, with the Decision that records it.
 *
 * **Only the fields the member actually changed are sent.** The server reads `model_fields_set` to tell
 * "clear the description" from "leave the description alone", and sending the whole form back would make
 * those two indistinguishable — the same reasoning `reviseGoal` carries, and the defect that route exists
 * to fix wearing a different coat.
 *
 * **`active` is not a field here and must never become one.** The request model is `extra="forbid"` and
 * refuses it **by name**: R-122's mark is its own act on its own route, because a boolean in the middle of
 * an edit form is how a member deactivates a position by accident. A client that sends one is told, and
 * the 422 that says so arrives as pydantic's list — see `detailText`.
 */
export function revisePosition(positionId, payload) {
  return request(`/api/positions/${encodeURIComponent(positionId)}`, {
    method: 'PATCH',
    headers: JSON_HEADERS,
    body: JSON.stringify(payload),
  });
}

/**
 * R-122. Mark a position inactive. **Nothing is removed.**
 *
 * The act is the route, so there is no flag to get the wrong way round and no request that means "leave it
 * as it is". The response says `remains_in_history` and `remains_linked_to_decisions` out loud, because
 * "deactivate" is the word people read as "delete" and the screen has to be able to say what did not
 * happen.
 */
export function deactivatePosition(positionId, decision) {
  return post(`/api/positions/${encodeURIComponent(positionId)}/deactivate`, decision);
}

/** R-122, the other direction. The mark is not one-way, so a mis-click is not permanent. */
export function reactivatePosition(positionId, decision) {
  return post(`/api/positions/${encodeURIComponent(positionId)}/reactivate`, decision);
}

// ---------------------------------------------------------------- S-10 capabilities (D-01 / R-194)

/**
 * S-10. Every capability statement, and what evidence this member has for it.
 *
 * `rung` is null on every one of them and the payload carries no tally of how many are evidenced — R-191
 * makes the statements themselves the progression. D-01 was answered: there is no scheme, and
 * `rung_scheme_reason` says there is none rather than that one is pending.
 */
export function getCapabilities(language) {
  return request(`/api/capabilities?${new URLSearchParams({ language })}`);
}

/**
 * R-190. The learning units, with the capability statements each one's content evidences.
 *
 * **Fetched so a unit can be offered by its title rather than by its key.** `GET /api/capabilities` carries
 * `evidenced_by_units` as a list of keys, and a selector reading `konten_die_liegen_bleiben` at a member is
 * a selector nobody can use. It is also what makes the offered list correct rather than hopeful: the units
 * shown against one capability are exactly the ones the content says evidence it, so a member cannot pick
 * a reference the server would then refuse.
 *
 * `units_are_not_gated` and `rung_scheme: null` travel in this payload as well, and say the same thing the
 * capability payload says: there is no scheme, not a scheme pending.
 */
export function getLearning(language) {
  return request(`/api/learning?${new URLSearchParams({ language })}`);
}

/**
 * D-01, as a call. **The member records that they can do one of the things S-10 names.**
 *
 * `evidence_kind` and `assessed_by` are **not** in this shape and there is nowhere to put them: they are
 * server constants, because `capability_review` renders both straight back and a free-text kind is where
 * "level 3" would get stored *and displayed*. `assessed_by` is `member:<id>` — naming eigentliCH would be
 * eigentliCH vouching for a statement it never examined, which is R-194's forbidden claim of standing made
 * in a column rather than in copy.
 *
 * `learning_unit` is optional and **corroborated, not trusted**: the content has to agree that the named
 * unit evidences the named capability, or the server answers 422. A reference that does not hold reads as
 * corroboration and is not one. Omitted, the assertion stands on its own — which is what a self-assertion
 * is.
 *
 * There is no delete and no withdraw, here or on the server.
 */
export function assertCapability({ capabilityId, learningUnit = null }) {
  const body = { capability_id: capabilityId };
  // Sent only when chosen. `null` is a value pydantic accepts for the optional field, and it would be
  // indistinguishable in the payload from a member who picked a unit and then unpicked it — which is
  // fine, and this keeps the wire shape the same as the one the route's own docstring describes.
  if (learningUnit) body.learning_unit = learningUnit;
  return post('/api/capabilities/assertions', body);
}

// ---------------------------------------------------------------- R-210 / R-213: the member's own grants
//
// **The other half of the curator's door, and the half that was missing.** Everything in the S-12 section
// above authenticates as a curator; these three authenticate as the **member**, with the member's own
// bearer token, because R-213 makes a grant revocable *by the member* — and a withdrawal a curator could
// perform on their behalf is not the member's control. `api/curator.py` draws the same line in its own
// module docstring and puts the two sets of routes behind two different doors for it.
//
// **Nothing here is cached and there is no function that could hand back a stored answer.** R-213's word
// is *immediate*: a grant read once and kept is a grant that outlives its withdrawal. So `revokeGrant`
// returns what the server said and the screen re-reads the whole list rather than patching itself — the
// same habit `app/curator.js` describes for the curator's worklist, arrived at from the other side.

/**
 * R-210. The member opens a window onto their own material: scoped, and time-limited.
 *
 * `scope` is a list of names drawn from `GET /api/curator/grantable` and never a list this client wrote.
 * A scope name the server does not check is indistinguishable from full access, which is why the service
 * refuses an unrecognised one with a 422 instead of ignoring it — and why the screen builds its choices
 * from that route rather than from a constant somebody would have to keep in step.
 *
 * `hours` is sent rather than omitted. Omitting it is legal and means the server's own default lifetime,
 * which is a real answer — but a window the member did not choose is a window they were not asked about,
 * and R-210's "time-limited" is theirs to set. There is no value meaning "no expiry", here or on the route.
 */
export function grantAccess({ curatorId, scope, hours }) {
  return post('/api/curator/grants', { curator_id: curatorId, scope, hours });
}

/**
 * R-213's first half: a member cannot withdraw what they cannot see.
 *
 * Every grant they have ever made, with `live` decided by the server rather than by this client comparing
 * `expires_at` to a clock. Two clocks disagree, and the one that matters is the one the curator's next
 * read consults.
 */
export function getGrants() {
  return request('/api/curator/grants');
}

/**
 * R-213. Withdraw one grant, with effect on the curator's next read rather than at expiry.
 *
 * `DELETE` by HTTP and a timestamp in the database: the verb is the member's intent, and the row is the
 * evidence that access existed — which is not the member's to destroy or ours to lose. The response says
 * `deleted: false` in as many words, so the screen can state which of the two happened instead of letting
 * a member assume the record went with the access.
 */
export function revokeGrant(grantId) {
  return request(`/api/curator/grants/${encodeURIComponent(grantId)}`, { method: 'DELETE' });
}

// ---------------------------------------------------------------- S-11 Market Place (C-08, R-201, R-202)
//
// **What is absent from these signatures is the whole point.** `getListings` takes the role filter, the
// domain and the language. There is no placement, boost, sponsor or priority argument, and no options bag
// for one to arrive through unnoticed — C-08, held on this side of the wire the same way
// `services.marketplace.browse` holds it on the other. A parameter the server ignores today is a parameter
// somebody wires up the day the route grows it.
//
// **Nothing here sorts and nothing here counts.** The order arrives decided by `ordering_key`, whose
// inputs are three integers and an opaque tiebreak. `surfaces/market.js` says the same thing where the
// temptation actually lives.

/**
 * R-201 / R-004. The market place: provider listings and member offers as peers, in one decided order.
 *
 * `roles` omitted pre-filters by the member's own role grid; a list chooses; and the value that *removes*
 * the filter is deliberately not spelled here — the payload's own `filter.remove_by` carries it, so the
 * name this client sends and the name the screen prints back are one name rather than two that agree
 * until somebody edits one.
 *
 * Never gated on learning: nothing in this call carries a capability, a unit or an assertion, which is
 * what R-004 has to mean if it is to survive a redesign.
 */
export function getListings({ roles = null, domain = null, language } = {}) {
  const query = new URLSearchParams({ language });
  for (const role of roles || []) query.append('roles', role);
  if (domain) query.set('domain', domain);
  return request(`/api/marketplace/listings?${query}`);
}

/** One listing, with its disclosures always present (R-202). A draft answers 404, not a thinner listing. */
export function getListing(listingId, language) {
  return request(
    `/api/marketplace/listings/${encodeURIComponent(listingId)}?${new URLSearchParams({ language })}`,
  );
}

/**
 * R-004. How to reach a supplier — and there is no gate to pass, not a gate this member happens to clear.
 *
 * Who asked is the token's member and is not a parameter of this call. It used to be one, which meant the
 * record of who asked was whatever the caller typed.
 */
export function getListingContact(listingId) {
  return request(`/api/marketplace/listings/${encodeURIComponent(listingId)}/contact`);
}

/** R-205 / R-004. A member offer is contacted the same way a provider listing is, on its own route. */
export function getOfferContact(offerId) {
  return request(`/api/marketplace/offers/${encodeURIComponent(offerId)}/contact`);
}

/**
 * R-005. Apply to be listed as supply. **The one gated act on this surface**, and the gate is now passable.
 *
 * Until `POST /api/capabilities/assertions` shipped (A94) this route refused every real member with a 403,
 * because the capability pipeline reads recorded evidence and no member could hold any. The gate is
 * unchanged; what changed is that satisfying it is a thing a member can do.
 *
 * `qualification_pipeline` is declared rather than derived, and R-204 is why: a server that worked it out
 * from the domain would make a mismatch unrepresentable, and an unrepresentable mismatch is a rule nobody
 * can show is enforced. This client does not work it out either — see `surfaces/market.js`, which reads
 * which pipeline a domain goes through off the listings the market place is already serving.
 *
 * Returns a **draft**. It is not in the market place until it has been through the disclosure gate.
 */
export function applyToBeListed(payload) {
  return post('/api/marketplace/applications', payload);
}

/**
 * R-202. What a supplier declares about its economic relationships.
 *
 * `kind` may be the server's `none_declared`, which is a positive statement and not an empty field — the
 * difference R-202 exists to make. `declared_by` names who said it and has no default: an unattributed
 * disclosure is the shape of thing nobody can be held to.
 */
export function declareDisclosure(listingId, { kind, statement, declaredBy }) {
  return post(
    `/api/marketplace/applications/${encodeURIComponent(listingId)}/disclosures`,
    { kind, statement, declared_by: declaredBy },
  );
}

/**
 * R-202's gate, over HTTP. It refuses; it does not warn.
 *
 * A listing with no disclosure answers 422 and stays a draft. That refusal is the requirement working, so
 * the screen shows it as what happened rather than as an error the member should route around.
 */
export function publishApplication(listingId) {
  return request(
    `/api/marketplace/applications/${encodeURIComponent(listingId)}/publish`,
    { method: 'POST' },
  );
}

// ---------------------------------------------------------------- S-05, S-09, S-13, R-232
//
// The four payloads phase 8 composed and nothing rendered. They share one property, which is why they are
// grouped here as they are grouped in `api/remainder.py`: **none of them returns a number about a member.**
// No current stage, no share of stages opened, no count of gatherings attended. There is nothing here for
// a client to filter out, because nothing above computes one.

/**
 * S-05. Five situations, all open (R-141), none of them a position on a scale (R-140, R-006).
 *
 * There is no parameter by which a client could ask "which stage am I on", because that question has no
 * answer here. What the member's own row buys is `opens_at` — where the map opens — and the payload
 * carries `opens_at_is_not_a_position` beside it, because that is the reading an interface would invite.
 */
export function getStages(language) {
  return request(`/api/stages?${new URLSearchParams({ language })}`);
}

// `GET /api/stages/{key}` has deliberately **no function here.** R-141's promise is that any stage may be
// opened by anybody at any age, and `stage_map` already returns all five in full — it calls the identical
// `stage_payload` for each one. A per-stage call would fetch content the screen is already holding and put
// it behind a click, which keeps R-141 less well than five stages open on one page. The route stays useful
// to anything outside this client (it needs no session at all), and if a stage ever grows material the map
// does not carry, this is the line to delete.

/**
 * S-09. The seven life-event modules. All seven come back unauthored and the payload says so — R-183.
 *
 * R-222: *this* is what the word "events" means in this interface. The community call below never uses it.
 */
export function getLifeEvents(language) {
  return request(`/api/life-events?${new URLSearchParams({ language })}`);
}

/**
 * D-07's destination phrase. **The only place the client asks for it.**
 *
 * A22 resolved D-07 by promoting the specification's own §1 phrasing into one content record, and a test
 * scanned the backend to be sure nothing inlined it. That test passed because **nothing said the phrase at
 * all** — `content.destination()` had no caller and appeared in no payload, so the one key D-07 asked for
 * was a key nothing read. A content record no surface can reach is not resolved, it is filed.
 *
 * It is fetched rather than added to `i18n.js` deliberately. Putting the phrase in the string table would
 * make it the forty-first copy of a phrase whose whole requirement is that there be one, and the German and
 * English forms would then drift independently of the record that owns them.
 */
export function getDestination(language) {
  return request(`/api/destination?${new URLSearchParams({ language })}`);
}

/**
 * One module, with the member's own relevant vault items already retrieved (R-181).
 *
 * Guarded where the index is not, because this one reaches into the vault. The four authored fields come
 * back empty with `unauthored_reason` set, and `retrieval_unavailable_reason` is what keeps "no document
 * kinds are named" apart from "you hold no documents" — two different facts that look identical on screen
 * unless a client keeps them apart.
 */
export function getLifeEvent(key, language) {
  return request(`/api/life-events/${encodeURIComponent(key)}?${new URLSearchParams({ language })}`);
}

/**
 * S-13. The scheduled lectures, café evenings and meet-ups, and whether this member was at each one.
 *
 * **`attended` per gathering is a fact; a count of them would be a standing.** R-221 forbids the second
 * and not the first, and this payload carries no aggregate of any kind — nothing to leave out, because
 * nothing computes one.
 */
export function getGatherings() {
  return request('/api/community/gatherings');
}

/**
 * R-220 / R-221. The member records that they were at one.
 *
 * No member field: attendance is one of R-203's three ordering inputs, so a route that let a caller name
 * somebody else would let anyone inflate any supplier's community presence. It is the token's member, and
 * `services/marketplace.py` reads the same rows on the ranking side.
 */
export function recordAttendance({ gatheringId, attended = true }) {
  return post('/api/community/attendance', { gathering_id: gatheringId, attended });
}

/**
 * R-232. Which data class each stored category falls into, derived from the model layer itself.
 *
 * No session and no member: this is a statement about the schema, and asking for either would imply the
 * answer differs per person. The words for what K0 to K3 *mean* are not in this payload — they are
 * interface copy and live in `i18n.js`, which is the one place they may be written.
 */
export function getDataClasses() {
  return request('/api/settings/data-classes');
}
