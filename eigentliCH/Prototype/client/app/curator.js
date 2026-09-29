// The curator's sign-in, in this window. A40, client side — and the honest consequence of a decision.
//
// **There is no curator token, so there is nothing to store.** `POST /api/curator/login` verifies a
// curator and returns their identity; it mints no session, because there is no curator session table
// (A40, and `services/curator.py` states the trade). Every subsequent request therefore has to carry the
// credential again, which means a client that wants to make more than one request has to keep it.
//
// So this module keeps it, and the whole of its design is about how narrowly:
//
//   * **In memory only.** Nothing here touches `localStorage` or `sessionStorage`. A curator's credential
//     opens other people's K3 material, and a laptop that has been used once by a curator must not be a
//     laptop that can be used again by whoever picks it up. `session.js` says the member's password is
//     never stored; the same sentence is true here, one step further — the curator's password is not
//     stored *and* not kept past this window.
//   * **Cleared on sign-out and on any refusal.** `forget()` is called from the sign-out button and from
//     every 401 the curator surface meets, so a password that has stopped working stops being held.
//   * **A reload ends it.** That is a real cost and the surface says so in `curator.no_token`, rather than
//     leaving a curator to discover it. It is also the one benefit of A40's interim, stated in
//     `services/curator.py`: there is no bearer token for a curator to leave behind in a browser.
//
// **Nothing about any member is held here.** Not the worklist, not a grant, not a scope, not an expiry.
// R-213 makes a member's revocation immediate, and a grant this module remembered would be a grant that
// outlived its withdrawal — so the surface re-reads `GET /api/curator/members` every time it draws, and
// there is deliberately no function here that could hand it a stored answer. What is kept is a name, an
// email, a role label and the must-change flag: facts about the curator, and only for as long as they are
// looking at the screen.

//: `{ email, password }`, or null. Passed to `api.js` on every call and read by nothing else.
let credentials = null;

//: What `POST /api/curator/login` returned, minus nothing — it returns no secret. `{ id, display_name,
//: email, role_label, fictional, must_change, session_token: null }`.
let who = null;

/** The credentials to send, or null. Read by `surfaces/curator.js` and handed straight to `api.js`. */
export function held() {
  return credentials;
}

/** Who the server said this credential belongs to, or null. */
export function identity() {
  return who;
}

export function signedIn() {
  return credentials !== null && who !== null;
}

/** A43 / A53. True while the seeded password is still in force and only two routes will answer. */
export function mustChange() {
  return Boolean(who && who.must_change);
}

/**
 * Called with the address, the password and what `POST /api/curator/login` returned.
 *
 * The identity is stored as given rather than picked apart: it has no secret in it, `session_token` is
 * null by design, and a client that copied three of its fields would be the client that misses the fourth
 * when the payload grows one.
 */
export function begin(email, password, payload) {
  credentials = { email, password };
  who = payload;
  return who;
}

/**
 * After a password change: the credential in hand is the new one, and the flag the server just cleared.
 *
 * Written here rather than by re-running the login, because the login would be a second request whose
 * only purpose is to learn something this client already knows — and it would need the new password held
 * somewhere while it ran.
 */
export function passwordChanged(password) {
  if (!credentials) return null;
  credentials = { email: credentials.email, password };
  who = { ...who, must_change: false };
  return who;
}

/** Forget everything. Called from sign-out and from any 401 on any curator route. */
export function forget() {
  credentials = null;
  who = null;
}
