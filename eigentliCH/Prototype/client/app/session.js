// The member's session, in this browser. A11, client side.
//
// **This replaces `store.js`, which is deleted.** That module remembered a list of member *ids* and said
// in its own comment that it "authenticates nothing and must be deleted the moment real sessions exist".
// They exist. What is kept here is one token and the identity the server returned with it — not a list of
// people, because a list of who has used this machine is a fact about members that nothing needs.
//
// **The token is the only credential held.** The password is never stored, never kept in memory past the
// submit handler that sent it, and never written anywhere. If the token is lost the member logs in again,
// which costs one form and is the correct trade against keeping a password on a laptop.
//
// **Why localStorage and not sessionStorage or a cookie.**
//   * a cookie would be sent automatically on every request to this origin, which is how CSRF becomes
//     possible; a header the client attaches deliberately is not sent by a form on another page.
//   * `sessionStorage` would log the member out when they close the tab, and this is a product someone
//     opens next to their tax papers over several evenings.
//   * `localStorage` throws rather than returning null in a private window, when site data is blocked and
//     in some preview contexts, so every access here is wrapped. A first screen that white-screens
//     because storage was unavailable is a worse failure than one that asks for a password again.
//
// C-05: this is the member's own browser, not a third party. Nothing here leaves the machine except the
// token, which goes back to the origin it came from.

const KEY = 'eigentlich.session.v1';

let current = null;

function read() {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed.token === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

function write(value) {
  try {
    if (value) window.localStorage.setItem(KEY, JSON.stringify(value));
    else window.localStorage.removeItem(KEY);
  } catch {
    // Storage unavailable. The session still works for as long as this page is open; it simply will not
    // survive a reload, and the member meets the login form again rather than an error.
  }
}

/** The token to send, or null. Read by `api.js` on every request and by nothing else. */
export function token() {
  if (current === null) current = read();
  return current ? current.token : null;
}

/** Who the server said this token belongs to: `{ member_id, display_name, locale, language, must_change }`. */
export function identity() {
  if (current === null) current = read();
  return current ? current.identity : null;
}

export function memberId() {
  const who = identity();
  return who ? who.member_id : null;
}

/** The member's language, or null when nobody is logged in — A12, and the server derives it from locale. */
export function language() {
  const who = identity();
  return who ? who.language : null;
}

export function mustChange() {
  const who = identity();
  return Boolean(who && who.must_change);
}

/** Called with what `POST /api/session` returned. The token is separated from the identity here. */
export function begin(payload) {
  const { token: raw, ...identityFields } = payload;
  current = { token: raw, identity: identityFields };
  write(current);
  return current.identity;
}

/** Called with what `GET /api/session` returned, to refresh the identity without a new token. */
export function refresh(identityFields) {
  if (!current) current = read();
  if (!current) return null;
  current = { token: current.token, identity: identityFields };
  write(current);
  return current.identity;
}

/** Forget everything. Called after `DELETE /api/session` and after any 401 from any route. */
export function end() {
  current = null;
  write(null);
}
