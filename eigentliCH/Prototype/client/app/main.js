// Entry point, session gate and router.
//
// R-001: the role grid is the default authenticated landing screen — not a dashboard of widgets and not
// the vault. So `#/plan` is the default route and it renders S-02.
//
// **A11 is the gate now, wired 31 August 2026.** This file used to read the member from `?member=<id>`
// and from a list of profile ids kept in `localStorage` — a development affordance whose own comment said
// it "authenticates nothing and must be deleted the moment real sessions exist". Both are gone. The
// opening question is `is there a live session`, answered by `GET /api/session` against a stored token,
// and every other screen sits behind that answer.
//
// **A 401 from anywhere ends the session, in one place.** `guard` wraps every surface load: any route
// answering 401 means the token has expired or been revoked (R-213 makes revocation immediate), so the
// client forgets it and shows the login form rather than rendering an error the member can do nothing
// with. A 403 carrying `password_change_required` is the other server-driven navigation — the member is
// authenticated and may not proceed until they choose a password, which the server enforces and this
// merely obeys.
//
// **The Know is mounted, not routed** (R-002 / R-170). `know.mount` appends its panel to `document.body`
// once, at startup. The router below clears `#main` and nothing else, so the panel survives every route
// change and renders alongside whatever screen is active. It is deliberately absent from `ROUTES` and from
// the `.door` list: a tab is a place you leave the current screen to visit, and "persistent across all
// authenticated screens" is the opposite of that. The `#/know` door in `index.html` is S-10's Knowledge and
// Community door, which is a different thing that happens to share a word.
//
// **S-04 and S-06 hang off the Plan door**, reached by the links `surfaceLinks` renders on each of the
// three screens. §3's information architecture has two doors and a shared third surface, so containers and
// the vault are rooms behind the Plan door rather than new doors.
//
// **The chrome is translated here** (A12, and A70 recorded its absence as a known gap with a precise
// location). The three door labels and the skip link are marked up in `index.html` with `data-i18n` keys
// and carry German as their served text; `applyChrome` rewrites them from the string table on load and on
// every language change, so an English member no longer keeps a German header.

import { ApiError, endSession, getActions, getOnboarding, readSession, setLanguage } from './api.js';
import { announce, clear, h } from './dom.js';
import { DEFAULT_LANGUAGE, languages, t } from './i18n.js';
import * as session from './session.js';
import * as curatorState from './curator.js';
import * as curatorSurface from '../surfaces/curator.js';
import * as ask from '../surfaces/ask.js';
import * as grid from '../surfaces/grid.js';
import * as positionForm from '../surfaces/position-form.js';
import * as login from '../surfaces/login.js';
import * as onboarding from '../surfaces/onboarding.js';
import * as know from '../surfaces/know.js';
import * as vault from '../surfaces/vault.js';
import * as containers from '../surfaces/containers.js';
import * as befund from '../surfaces/befund.js';
import * as runs from '../surfaces/runs.js';
import * as decisions from '../surfaces/decisions.js';
import * as settings from '../surfaces/settings.js';
import * as capabilities from '../surfaces/capabilities.js';
// The six surfaces added on 31 August 2026 for A90's remaining gaps: the member's side of S-12, S-11's
// screen over the placeholder, and the four payloads phase 8 composed that nothing rendered.
import * as grants from '../surfaces/grants.js';
import * as regime from '../surfaces/regime.js';
import * as network from '../surfaces/network.js';
import * as feed from '../surfaces/feed.js';
import * as market from '../surfaces/market.js';
import * as stages from '../surfaces/stages.js';
import * as lifeEvents from '../surfaces/life-events.js';
import * as community from '../surfaces/community.js';
import * as learning from '../surfaces/learning.js';

const main = document.getElementById('main');
const params = new URLSearchParams(location.search);

const state = {
  // `?lang=` still wins, because it is how someone demonstrating this shows the other language without a
  // login. Otherwise the language is the member's own locale as the server derived it (A26: the setting
  // lives on `Member.locale`), and falls back to de-CH before anybody has logged in (A12).
  languageOverride: params.get('lang'),
  language: params.get('lang') || DEFAULT_LANGUAGE,
  // C-10 wants an identified curator on every session. Read from the URL, so a session opened here
  // records a real person rather than a queue. Absent is absent: see `know.js::requestCurator`, which
  // says so instead of inventing one.
  curatorId: params.get('curator'),
};

function chooseLanguage() {
  state.language = state.languageOverride || session.language() || DEFAULT_LANGUAGE;
  return state.language;
}

// ---------------------------------------------------------------- the chrome (A12 / A70)

/**
 * Translate everything outside `#main`: the three doors and the skip link.
 *
 * The elements carry `data-i18n="<key>"` in `index.html` and their served text is the German string, so a
 * member whose JavaScript has not run yet still gets a readable header in the default language rather
 * than an empty one. This rewrites `textContent` — never markup — from the same table every surface uses.
 *
 * `document.documentElement.lang` moves with it, because a screen reader picks its voice from that
 * attribute and a German header announced in English is worse than a German header.
 */
function applyChrome(language) {
  document.documentElement.lang = language;
  for (const node of document.querySelectorAll('[data-i18n]')) {
    const key = node.dataset.i18n;
    const translated = t(key, language);
    // `t` returns the key itself when a string is missing, which would put `door.plan` on screen. Leaving
    // the served German in place is the better failure, and `test_i18n_parity` is what catches the cause.
    if (translated !== key) node.textContent = translated;
  }
  const label = document.querySelector('.doors');
  if (label) label.setAttribute('aria-label', t('chrome.nav_label', language));
  // Rebuilt here rather than beside it, so the switch itself cannot be the one thing in the header still
  // speaking the language the member just left.
  renderLanguageSwitch(language);
}

/**
 * The right-hand end of the header: the language switch and, once there is one, the member.
 *
 * One container for both, because `.chrome` is a wrapping flex row and two elements each claiming
 * `margin-left: auto` would split the free space between them and drift apart as the window widens.
 */
function chromeEnd() {
  const chrome = document.querySelector('.chrome');
  if (!chrome) return null;
  let end = chrome.querySelector('.chrome-end');
  if (!end) {
    end = h('div', { class: 'chrome-end' });
    chrome.append(end);
  }
  return end;
}

/**
 * A12 / A26 — the language switch, in the browser chrome where the owner asked for it.
 *
 * **Why it is here and not in a settings panel.** The report was "English vs German Version - where can I
 * switch" followed by "Make a switch in the browser". A26 had decided against a per-screen switcher on the
 * grounds that nobody changes language more than once a year — which is true, and is beside the point: the
 * once is the moment they need to find it, and a control nobody can find is the same as no control. A26's
 * substance survives intact, because what is stored is still `Member.locale` and there is still exactly
 * one setting; only the door to it moved.
 *
 * **Two buttons, not a select.** Both options are visible at once, which is what makes this findable at a
 * glance, and `aria-pressed` states which one is in force. The labels are endonyms — Deutsch, English —
 * and are deliberately not translated: a member looking for their own language looks for its own word.
 *
 * **`fr` and `it` are not offered.** `boundary.py` carries refusal texts in four languages; the string
 * table carries two. Offering a language in which only the refusals are written would hand a member a
 * screen of key names, so the list comes from `i18n.js::languages()` — the table itself — rather than from
 * a constant somebody would have to remember to keep in step.
 */
function renderLanguageSwitch(language) {
  const end = chromeEnd();
  if (!end) return;
  const existing = end.querySelector('.lang');
  if (existing) existing.remove();

  const group = h('div', { class: 'lang', role: 'group', 'aria-label': t('chrome.language', language) });
  for (const code of languages()) {
    const current = code === language;
    group.append(
      h('button', {
        type: 'button',
        class: 'add lang-choice',
        lang: code,
        // A statement about which language is in force, not about which button was clicked last: a
        // toggle-button pattern rather than a tab, because the page does not change place.
        'aria-pressed': String(current),
        text: ENDONYM[code] || code,
        onClick: () => changeLanguage(code),
      }),
    );
  }
  // First in the container, so the member's own name and the way out stay at the outside edge where they
  // were before this arrived.
  end.prepend(group);
}

//: What each language calls itself. Not in `i18n.js`, because these are the same two words in both tables
//: and a duplicated pair is a pair that gets edited on one side.
const ENDONYM = { de: 'Deutsch', en: 'English' };

/**
 * Change the language the member reads, and keep it (A26).
 *
 * **Signed in: it persists**, because it is the member's setting and not this tab's mood. `PUT
 * /api/settings/language` writes `Member.locale`, and the stored identity is refreshed from the response
 * rather than patched by hand — the server owns the locale that `de` becomes.
 *
 * **Not signed in: this window only, and it says so.** There is no member row for it to sit on, and
 * inventing somewhere to keep it would mean this client holding a preference for a person who does not
 * exist yet. The login form still has to be readable in both languages, which is the whole reason the
 * switch is rendered before the session exists.
 *
 * **`?lang=` is cleared on the way through.** It is a demonstration override and it wins over the member's
 * own setting by design; leaving it in place would make the switch appear to do nothing, which is a worse
 * bug than the one being fixed.
 *
 * A failure keeps the old language rather than showing the new one and forgetting it a reload later.
 */
async function changeLanguage(language) {
  if (language === state.language) return;
  state.languageOverride = null;

  if (session.token()) {
    try {
      const saved = await setLanguage(language);
      session.refresh({ ...session.identity(), locale: saved.locale, language: saved.language });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        session.end();
        return renderLogin();
      }
      // The member is still reading the language they were reading, and the header still says so.
      applyChrome(chooseLanguage());
      renderIdentity();
      return announce(t('language.not_saved', state.language));
    }
  } else {
    state.languageOverride = language;
  }

  applyChrome(chooseLanguage());
  renderIdentity();
  // The panel is mounted on `document.body` and outlives every route change, so it retranslates through
  // its own `sync` — which `route()` and `renderLogin()` both call. That is the join A70 recorded as
  // missing for the doors, one surface further out.
  //
  // **Awaited, and that is not tidiness.** Every screen announces itself to `#live` when it finishes
  // loading, and the announcement below was being overwritten by the one from the screen re-rendering
  // behind it — so a member using a screen reader heard the position count and never heard that the
  // language had changed. Found by running this path rather than by reading it.
  // A12: the curator screens follow the switch too, and they are outside the member session — so the
  // question is not only "is somebody logged in" but "is a screen showing that has to be redrawn".
  if (session.token() || isCuratorRoute()) await route();
  else renderLogin();
  announce(
    session.token()
      ? t('language.changed', state.language)
      : `${t('language.changed', state.language)} ${t('language.this_device_only', state.language)}`,
  );
}

/**
 * The member's name and the way out, in the header.
 *
 * Rebuilt rather than updated, because it is three nodes and the alternative is keeping references to
 * them alive across a logout. R-003 applies here as everywhere: no count, no dot, no badge.
 */
function renderIdentity() {
  const chrome = chromeEnd();
  if (!chrome) return;
  const existing = chrome.querySelector('.who');
  if (existing) existing.remove();

  const who = session.identity();
  if (!who) return;

  chrome.append(
    h('div', { class: 'who' }, [
      h('span', { class: 'who-name', text: who.display_name }),
      // **The settings door, in the chrome, and A86 is the argument for putting it there.** The consent
      // history, the export and the erasure are all settings, and A26's mistake was reasoning that a
      // control nobody uses more than once a year does not need to be findable — the once is exactly the
      // moment it does. A member looking for how to withdraw a consent or delete their account will not
      // find it by opening the Plan door. A link rather than a button, because it is navigation and should
      // open in a tab.
      h('a', {
        href: '#/settings',
        class: 'add',
        style: 'text-decoration:none',
        text: t('settings.nav', state.language),
      }),
      h('button', {
        type: 'button',
        class: 'add',
        text: t('session.sign_out', state.language),
        onClick: signOut,
      }),
    ]),
  );
}

// ---------------------------------------------------------------- notices

function notice(message, detail, kind = '') {
  return h('div', { class: `notice ${kind}`.trim(), role: kind === 'error' ? 'alert' : null }, [
    h('p', { text: message, style: 'margin:0' }),
    detail ? h('p', { class: 'lbl', text: detail, style: 'margin:8px 0 0' }) : null,
  ]);
}

// **`renderPlaceholder` is deleted, and its absence is the point.**
//
// It existed to render a screen that said a screen did not exist, and by 31 August 2026 it had exactly one
// caller left: `#/market`, whose body string was "Angebote werden nach den vier Rollen geordnet, nicht nach
// Beruf. Noch nicht gebaut." — in front of `services/marketplace.py`, the most heavily guarded module in
// the build. A94 removed the other caller when the capability screen replaced the `#/know` placeholder and
// kept the placeholder's one substantive sentence as copy on the real screen; S-11 does the same with the
// sentence about the four roles, which is R-200 and now sits on `surfaces/market.js` beside the filter that
// implements it.
//
// The function is gone rather than left unused because a placeholder renderer with no callers is an
// invitation: it makes "route it to a placeholder for now" a one-line change, and `ROUTES[name] ||
// ROUTES.plan` already means a route that is merely absent falls through to the grid rather than to a lie.

function renderError(error) {
  clear(main);
  main.append(
    notice(
      t('error.load', state.language),
      error instanceof ApiError
        ? `${t('error.detail', state.language)}: ${error.detail || error.status}`
        : String(error),
      'error',
    ),
  );
}

// ---------------------------------------------------------------- the session gate

function renderLogin() {
  chooseLanguage();
  applyChrome(state.language);
  renderIdentity();
  panel.sync();
  clear(main);
  login.render(main, {
    language: state.language,
    onSignedIn: afterSignIn,
    onRegister: renderRegistration,
  });
}

function renderRegistration() {
  clear(main);
  login.renderRegistration(main, {
    language: state.language,
    onRegistered: () => {
      // Back to the login form with what they just chose. Registration mints no token — see api.js.
      renderLogin();
      announceSignedOut(t('register.now_sign_in', state.language));
    },
    onCancel: renderLogin,
  });
}

function renderPasswordChange() {
  chooseLanguage();
  applyChrome(state.language);
  renderIdentity();
  panel.sync();
  clear(main);
  login.renderPasswordChange(main, {
    language: state.language,
    onChanged: async () => {
      // Ask the server rather than assuming: `must_change` is the server's fact and the token is the same
      // one, so re-reading it is both the confirmation and the refresh.
      try {
        session.refresh(await readSession());
      } catch {
        return renderLogin();
      }
      afterSignIn(session.identity());
    },
    onSignOut: signOut,
  });
}

// ---------------------------------------------------------------- the curator's door (A40)
//
// **A route outside the member session gate, and the only one.** `#/kurator` is reached from a link on the
// member login screen and is answered before `route()` asks whether there is a member token, because a
// curator has no member token and never will: A40 puts curators in their own table with their own login,
// and `POST /api/curator/login` mints nothing. The state is `app/curator.js` — in memory, for this window.
//
// **Three screens behind one route name**, the same arrangement `renderLogin` / `renderPasswordChange` /
// the authenticated surfaces have for a member, and for the same reason: which one is right is a fact
// about the server's answer rather than about where the curator clicked.
//
// **A 401 on any curator request forgets the credential and returns to the form.** Not `guard`, which
// belongs to the member session and would show the *member* login screen — the wrong door for someone who
// has just been refused at this one.

const CURATOR_ROUTE = 'kurator';

function isCuratorRoute() {
  return routeName() === CURATOR_ROUTE;
}

function curatorSignedOut(message) {
  curatorState.forget();
  renderCurator();
  if (message) announceSignedOut(message);
}

async function renderCurator() {
  chooseLanguage();
  applyChrome(state.language);
  renderIdentity();
  panel.sync();
  clear(main);

  if (!curatorState.signedIn()) {
    return curatorSurface.render(main, {
      language: state.language,
      onSignedIn: () => renderCurator(),
      // The link's own href already goes to `#/plan`; nothing more is needed, and a handler that also
      // re-rendered would race the hashchange.
      onCancel: null,
    });
  }

  // A43 / A53. The server refuses every other curator route while this is true, so the client does not
  // get to decide it is optional — it reads the flag the login returned and draws the one screen that works.
  if (curatorState.mustChange()) {
    return curatorSurface.renderPasswordChange(main, {
      language: state.language,
      onChanged: () => {
        announceSignedOut(t('curator.password_changed', state.language));
        renderCurator();
      },
      onSignOut: () => curatorSignedOut(t('curator.signed_out', state.language)),
    });
  }

  let payload;
  try {
    payload = await curatorSurface.load();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      // The password has been changed elsewhere, or the account deactivated. Forget it and ask again.
      return curatorSignedOut(null);
    }
    if (error instanceof ApiError && error.status === 403
        && String(error.detail || '').includes('curator_password_change_required')) {
      // The server's own direction, obeyed rather than second-guessed: the flag was set after this window
      // signed in, or the login's answer was stale.
      return curatorSurface.renderPasswordChange(main, {
        language: state.language,
        onChanged: () => renderCurator(),
        onSignOut: () => curatorSignedOut(t('curator.signed_out', state.language)),
      });
    }
    return renderError(error);
  }

  return curatorSurface.renderWorkbench(main, payload, {
    language: state.language,
    onSignOut: () => curatorSignedOut(t('curator.signed_out', state.language)),
    // R-213: re-read rather than re-render. Nothing was kept, so this is the only way to show the
    // current state of a grant — and it is what makes the screen honest a minute after it was drawn.
    onReload: async () => {
      await renderCurator();
      announceSignedOut(t('curator.reloaded', state.language));
    },
    onExpired: () => curatorSignedOut(null),
  });
}

function afterSignIn(who) {
  chooseLanguage();
  applyChrome(state.language);
  renderIdentity();
  if (who && who.must_change) return renderPasswordChange();
  panel.sync();
  route();
}

async function signOut() {
  try {
    await endSession();
  } catch {
    // A token the server no longer recognises is already the state we are asking for. Ending the local
    // session regardless is the behaviour a member expects from a button labelled "sign out".
  }
  session.end();
  // Item 1: after sign-in, the ask screen. It was `#/plan` — the role grid — which page 2 rules out:
  // "nobody meets the four roles before they have entered data".
  location.hash = '#/ask';
  renderLogin();
  announceSignedOut(t('session.signed_out', state.language));
}

function announceSignedOut(message) {
  const live = document.getElementById('live');
  if (live) live.textContent = message;
}

/**
 * Every authenticated surface goes through here.
 *
 * 401 — the token is gone, expired or revoked. Forget it and show the login form; there is nothing the
 * member can do about it on the current screen and rendering a refusal there would only be a dead end.
 * 403 with `password_change_required` — the server is directing the member to the one screen they may
 * use. Both decisions live here rather than in seven surfaces.
 */
/**
 * The token is gone. One place, because two places is one place that forgets to forget the token.
 *
 * Reached from `guard` for a 401 on any surface load, and directly by `surfaces/runs.js`, whose polling
 * loop can meet a 401 long after its screen finished loading — a run may take half an hour and a session
 * can expire inside one.
 */
function sessionExpired() {
  session.end();
  renderLogin();
  return null;
}

async function guard(work) {
  try {
    return await work();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      return sessionExpired();
    }
    if (error instanceof ApiError && error.status === 403
        && String(error.detail || '').includes('password_change_required')) {
      renderPasswordChange();
      return null;
    }
    renderError(error);
    return null;
  }
}

// ---------------------------------------------------------------- the screens

/**
 * The three screens behind the Plan door: the grid (S-02), the containers (S-04) and the vault (S-06).
 *
 * Links rather than buttons, because they are navigation and a member should be able to open one in a new
 * tab. `.add` is the client's one secondary-button treatment and is reused here for the same reason the
 * other surfaces reuse it: it reads as available without competing with `.primary`.
 *
 * **R-003 applies here too.** These carry no count, no dot and no badge — not for action items, not for
 * vault items, not for goals. The current screen is marked with `aria-current`, which is a statement about
 * where you are and not about how much is waiting.
 */
/**
 * The rooms behind the Vault door (items 4 and 8).
 *
 * Renamed from `surfaceLinks` when the Plan door became the Vault door. The Vault "holds everything about
 * the client and everything they have to do — goals, action points, documents, decisions taken and the
 * reasoning behind them", so what used to be a row of rooms behind Plan is the Vault's own contents.
 *
 * `befund` is in this row and is no longer in the chrome. It stopped being a door on 4 September 2026 by
 * the owner's decision, on the condition that it stays one tap away: it is the report over what the Vault
 * holds, so it sits beside the material it reports on.
 */
function vaultLinks(active) {
  const entries = [
    // Item 4's four panes, in its own order: Plan, Actions, Documents, Decisions. `containers` is the
    // goal half of the Plan pane and sits beside it until the two are one screen; `befund` is the report
    // over what the Vault holds and came inside when it stopped being a door (A121).
    ['plan', 'nav.plan'],
    ['containers', 'nav.containers'],
    ['actions', 'nav.actions'],
    ['documents', 'nav.documents'],
    ['befund', 'nav.befund'],
    // R-301's queue. A room behind the Plan door rather than a door of its own: a run reads what the plan
    // records and writes nothing back to it, so it belongs beside the plan's other rooms. The Befund is a
    // door because it is the whole of what a member gets out; this is one thing they can ask for.
    ['runs', 'nav.runs'],
    // S-07. Reached from the nav with no filter, and from a position with one.
    ['decisions', 'decisions.nav'],
    // S-05 and S-09. They sat behind the Plan door because it was called "Plan & Lebensereignisse" and the
    // second half of that name led nowhere. The door's name changed and they have not moved: a life event
    // is something that happens to the household the Vault holds.
    ['stages', 'stages.nav'],
    ['life-events', 'life_events.nav'],
  ];
  return linkRow(entries, active);
}

/**
 * One row of room links. Extracted because there are two doors with rooms behind them now, and two copies
 * of this would be two places `aria-current` and the R-003 rule have to keep holding.
 */
function linkRow(entries, active) {
  return h('div', { class: 'actions', style: 'margin-top:var(--sp-2xl)' },
    entries.map(([route, key]) =>
      h('a', {
        href: `#/${route}`,
        class: 'add',
        style: 'text-decoration:none',
        'aria-current': route === active ? 'page' : null,
        text: t(key, state.language),
      }),
    ));
}

/**
 * The three rooms behind the Knowledge and Community door.
 *
 * **The door is called "Wissen & Gemeinschaft" and only the first word had anything behind it.** `#/know`
 * rendered the capability statements; `GET /api/learning` was called by one surface for unit titles alone,
 * and `GET /api/community/gatherings` by nothing at all. So half of S-10 and all of S-13 sat behind a name
 * that promised them.
 *
 * **The Know panel is not in this list and never will be.** It is mounted on `document.body` and present on
 * every screen (R-002 / R-170); a link to it from inside a door would teach exactly the mistake that
 * requirement exists to prevent. `capabilities.js` says the same thing on the screen itself.
 */
function knowLinks(active) {
  return linkRow([
    // Item 5's three panes: Feed, Learning, Regime. `know` is the capability statements, which sit with
    // the curriculum rather than forming a pane of their own.
    ['feed', 'feed.title'],
    ['know', 'capabilities.nav'],
    ['learning', 'learning.nav'],
    // Item 5: population-level, and the one room here a person can open without an account.
    ['regime', 'nav.regime'],
  ], active);
}

/**
 * The rooms behind the Market door (item 7).
 *
 * **`community` moved here from the Know door.** Item 7 names the Market's four panes — community,
 * services, ventures, build your own venture — and item 5 names the Know's three, which do not include it.
 * Page 1 agrees: a lecture attended and a café evening with a guide are the Market Place serving learners
 * "before they arrive at the planner", which is demand rather than curriculum.
 *
 * `ventures` and `build your own venture` do not exist yet and are deliberately not stubbed: a link to a
 * screen that says "not built" is the placeholder S-11 was criticised for, one level out.
 */
function marketLinks(active) {
  return linkRow([
    ['network', 'network.title'],
    ['community', 'community.nav'],
    ['market', 'nav.market'],
  ], active);
}

function renderOnboarding() {
  clear(main);
  onboarding.render(main, { language: state.language, onFinished: renderPlan });
}

async function renderPlan() {
  clear(main);
  const payload = await guard(() => grid.load(state.language));
  if (!payload) return;

  // A member who has registered but not yet answered anything goes to S-01 rather than to an empty grid.
  // The grid is useful at n=1 (R-110) but it is not the place to begin.
  const hasAnything = payload.cells.some((cell) => cell.positions.length > 0);
  if (!hasAnything) {
    try {
      const resume = await getOnboarding(state.language);
      if (resume.next_question_key) return renderOnboarding();
    } catch {
      // If onboarding state cannot be read, the grid is still a correct thing to show.
    }
  }

  grid.render(main, payload, {
    provisional: true, // D-03: the role definitions ship marked provisional until reviewed.
    // R-112: one action from the cell to the form, and the cell it came from is carried in, so the
    // member never re-states the role and capital type they already chose by tapping.
    onAdd: (cell) =>
      positionForm.render(main, {
        cell,
        language: state.language,
        onSaved: renderPlan,
        onCancel: renderPlan,
      }),
    // R-123's second half. Correcting what a position *is*.
    onEdit: (position, cell) =>
      positionForm.renderEdit(main, {
        position,
        cell,
        language: state.language,
        onSaved: async () => {
          await renderPlan();
          announce(t('position.changed_announced', state.language));
        },
        onCancel: renderPlan,
      }),
    // R-122. **Its own act, on its own route, and therefore its own screen.** Deactivating changes what
    // the live plan is rather than what the position is, and `active` is refused by name on the PATCH so
    // that this cannot be a checkbox on the edit form.
    onSetActive: (position, cell, active) =>
      positionForm.renderStatusChange(main, {
        position,
        cell,
        active,
        language: state.language,
        onSaved: async () => {
          await renderPlan();
          announce(t(
            active ? 'position.reactivated_announced' : 'position.deactivated_announced',
            state.language,
          ));
        },
        onCancel: renderPlan,
      }),
    // R-160, filtered to the position the member is standing in front of.
    onDecisions: (position) => { location.hash = decisionsHash({ positionId: position.id }); },
  });
  main.append(vaultLinks('plan'));
}

async function renderContainers() {
  clear(main);
  const payload = await guard(() => containers.load(state.language));
  if (!payload) return;
  containers.render(main, payload, { language: state.language, onChanged: renderContainers });
  main.append(vaultLinks('containers'));
}

/**
 * The Vault door itself. Item 4's container, opening on the Plan pane.
 *
 * **Not the Befund, deliberately.** The owner considered opening the Vault on the report — it is the
 * answer to "I put everything in and get nothing out" — and chose the role grid, which is what page 2
 * calls "the primary view inside the Vault". The Befund is one tap away in `vaultLinks`.
 */
function renderVaultHome() {
  return renderPlan();
}

/**
 * Item 4's Actions pane: "What the client has to do, with dates."
 *
 * **The same items the Know panel shows, rendered by the same function.** R-174 puts action items in the
 * panel, where they arrive with a prepared decision rather than as a notification; item 4 puts them in the
 * Vault, where a member goes to look at what they have to do. Those are two places to meet one list, not
 * two lists — `know.renderActionList` is the single implementation and a second copy would drift in the
 * worst possible place.
 *
 * **The derivations run on this read**, as they do on the panel's: `GET /api/actions` derives before it
 * answers, which is R-175 satisfied rather than violated — nothing is pushed and nothing is scheduled, the
 * list is computed because somebody asked for the list.
 */
async function renderActions() {
  clear(main);
  const payload = await guard(() => getActions());
  if (!payload) return;

  main.append(
    h('h1', { text: t('nav.actions', state.language) }),
    h('p', { class: 'field-hint', text: t('know.actions_hint', state.language) }),
  );
  const list = h('div', { class: 'field' });
  main.append(list);
  await know.renderActionList(list, payload, { language: state.language });
  main.append(vaultLinks('actions'));
  announce(t('nav.actions', state.language));
}

/**
 * Item 5's Regime pane. **The only screen in this application that renders without a session.**
 *
 * `route()` returns this before the token check, beside the curator door, because the whole point is that
 * a person who has not signed up can read it: "the product's most distinctive output at zero data cost".
 * The Know panel and the Curator button stay hidden — `panel.sync()` shows them only for a member — so an
 * anonymous reader gets the reading and nothing that implies an account.
 */
async function renderRegime() {
  clear(main);
  let payload;
  try {
    payload = await regime.load();
  } catch (error) {
    return renderError(error);
  }
  regime.render(main, payload, { language: state.language });
  if (session.token()) main.append(knowLinks('regime'));
  announce(t('regime.title', state.language));
}

/**
 * Item 7's community surface, recovered as a shape over the real directory (A124).
 *
 * `surfaces/network.js` carries the argument for what was recovered and what was not. The short version:
 * two rings and the privacy line survive; six hardcoded people and a radial canvas whose geometry was
 * six hardcoded percentages do not.
 */
/**
 * Item 5's Feed, in the Reading Room's three sections.
 *
 * **The tap is the content hook.** It opens the chat panel, which is where the intake lives (item 3) —
 * the hook says which inputs are still missing and the panel asks them one at a time. A member whose
 * Vault already holds them goes straight there, which is what `hook.ready` reports.
 */
async function renderFeed() {
  clear(main);
  const payload = await guard(() => feed.load());
  if (!payload) return;
  feed.render(main, payload, {
    language: state.language,
    // One panel, opened rather than a second chat. `panel.openCurator` is the same idea for the human
    // route (A115); this is the intake route.
    onTap: () => { location.hash = '#/plan'; },
  });
  main.append(knowLinks('feed'));
  announce(t('feed.title', state.language));
}

async function renderNetwork() {
  clear(main);
  const payload = await guard(() => network.load());
  if (!payload) return;
  network.render(main, payload, { language: state.language });
  main.append(marketLinks('network'));
  announce(t('network.title', state.language));
}

async function renderDocuments() {
  clear(main);
  const payload = await guard(() => vault.load());
  if (!payload) return;
  vault.render(main, payload, {
    memberId: session.memberId(),
    language: state.language,
    onChanged: renderDocuments,
  });
  main.append(vaultLinks('documents'));
}

/**
 * The Befund — the fourth door, and the answer to "there is still no output".
 *
 * A door rather than a room behind the Plan door, because it is not a view of one part of the plan: it is
 * the whole of what a member gets back out of everything they put in, which is what the owner asked for
 * twice. No `surfaceLinks` under it for the same reason — a door is where you arrive, not a corridor.
 */
async function renderBefund() {
  clear(main);
  const report = await guard(() => befund.load(state.language));
  if (!report) return;
  befund.render(main, report, { language: state.language });
}

/**
 * R-301's queue, behind the Plan door.
 *
 * `onExpired` rather than `guard` for the surface's own later requests: its polling loop outlives the load,
 * and a 401 arriving thirty minutes in has to end the session the same way a 401 on load does.
 */
async function renderRuns() {
  clear(main);
  const payload = await guard(() => runs.load());
  if (!payload) return;
  runs.render(main, payload, { language: state.language, onExpired: sessionExpired });
  main.append(vaultLinks('runs'));
}

/**
 * S-07 — the decisions, and the one screen in this client with two states behind one route.
 *
 * `#/decisions` is the list; `#/decisions?id=<decision>` is one record with its correction chain. Both are
 * the same route because which one is right is a fact about the URL rather than about where the member
 * clicked — the same arrangement `renderLogin` / `renderPasswordChange` have, and it means a member can
 * link to, bookmark, and go back to one decision.
 *
 * The three filters travel in the hash for the reason `hashQuery` gives.
 */
async function renderDecisions() {
  clear(main);
  const query = hashQuery();
  const decisionId = query.get('id');

  if (decisionId) {
    const payload = await guard(() => decisions.loadOne(decisionId, state.language));
    if (!payload) return;
    decisions.renderOne(main, payload, {
      language: state.language,
      onBack: () => { location.hash = '#/decisions'; },
      // Re-read rather than re-render. A correction is a new row and the chain is composed on the server;
      // patching the screen by hand would be this client deciding what the lineage now looks like.
      onCorrected: async () => {
        await renderDecisions();
        announce(t('decisions.corrected', state.language));
      },
      onFilter: (filters) => { location.hash = decisionsHash(filters); },
    });
    return;
  }

  const payload = await guard(() => decisions.load(state.language, {
    positionId: query.get('position'),
    goalId: query.get('goal'),
    vaultItemId: query.get('vault_item'),
  }));
  if (!payload) return;

  decisions.render(main, payload, {
    language: state.language,
    onOpen: (id) => { location.hash = `#/decisions?id=${encodeURIComponent(id)}`; },
    onFilter: (filters) => { location.hash = decisionsHash(filters); },
  });
  main.append(vaultLinks('decisions'));
}

/** One place that builds S-07's hash, so the three filter names are spelled once. */
function decisionsHash({ positionId = null, goalId = null, vaultItemId = null } = {}) {
  const query = new URLSearchParams();
  if (positionId) query.set('position', positionId);
  if (goalId) query.set('goal', goalId);
  if (vaultItemId) query.set('vault_item', vaultItemId);
  const tail = query.toString();
  return tail ? `#/decisions?${tail}` : '#/decisions';
}

/**
 * Settings — R-230's consent history and withdrawal, R-231's export, and R-231's erasure.
 *
 * **`onErased` ends the local session before the receipt renders**, because the token is already dead: the
 * member's `sessions` rows are among those the erasure deleted, so the next request with it is a 401. The
 * surface then draws the receipt over the top. `renderLogin` is deliberately NOT called here — a member who
 * has just deleted their account should read what happened, not meet a login form.
 */
async function renderSettings() {
  clear(main);
  const payload = await guard(() => settings.load());
  if (!payload) return;
  settings.render(main, payload, {
    language: state.language,
    // R-213's habit, applied to consent: re-read rather than re-render. Nothing is kept, so this is the
    // only way to show the current state of a withdrawal.
    onChanged: renderSettings,
    onErased: () => {
      session.end();
      // The header must stop naming a member who no longer exists. The language switch stays — it is
      // rendered before any session exists, which is the whole reason it works on the login screen.
      renderIdentity();
    },
  });
}

/**
 * S-10 — the capability statements, behind §3's Knowledge and Community door.
 *
 * **This replaced a placeholder**, and the placeholder's content is kept as a sentence on the screen: this
 * door is not S-08. The Know is the panel mounted on `document.body`, present on every screen, and a member
 * sent looking for it behind a door would be learning exactly the mistake R-002 exists to prevent.
 */
async function renderCapabilities() {
  clear(main);
  const payload = await guard(() => capabilities.load(state.language));
  if (!payload) return;
  capabilities.render(main, payload, {
    language: state.language,
    onAsserted: renderCapabilities,
  });
  main.append(knowLinks('know'));
}

/**
 * R-210 / R-213 — the member granting a curator access, and taking it away.
 *
 * **A90's fourth finding, and the one that made a whole role unusable.** There was no client function for
 * grants at all, so a member could neither open a window nor close one, and a curator who signed in
 * correctly saw nothing because every read under `/api/curator` refuses without a live grant. The server
 * was complete; the product could not reach it in either direction.
 *
 * **`onChanged` re-reads rather than re-rendering, and here that is R-213 rather than tidiness.** Nothing
 * in the client keeps a grant — see `surfaces/grants.js` — so a re-read is the only way to show the current
 * state of one. It is also what makes the screen honest a minute after it was drawn: a grant that lapsed
 * while the member was reading disappears on the next read instead of sitting there looking live.
 */
async function renderGrants() {
  clear(main);
  const payload = await guard(() => grants.load());
  if (!payload) return;
  grants.render(main, payload, { language: state.language, onChanged: renderGrants });
}

/**
 * S-11 — the Market Place, over the placeholder that said "Noch nicht gebaut."
 *
 * **Two states behind one route, the same arrangement S-07 has**: `#/market` is the list and
 * `#/market?listing=<id>` is one listing. Which is right is a fact about the URL rather than about where
 * the member clicked, so a listing can be linked to and gone back to.
 *
 * **The role filter travels in the hash** (R-201), for the reason `hashQuery` gives about S-07's filters: a
 * filter held in a module variable survives a route change invisibly, and a member who left the screen and
 * came back would be looking at a subset of the market place with nothing on the page to say so.
 */
async function renderMarket() {
  clear(main);
  const query = hashQuery();
  const listingId = query.get('listing');

  if (listingId) {
    const payload = await guard(() => market.loadOne(listingId, state.language));
    if (!payload) return;
    market.renderOne(main, payload, {
      language: state.language,
      onBack: () => { location.hash = '#/market'; },
    });
    return;
  }

  // R-201's three ways in, carried as one parameter: absent pre-filters by the member's own role grid, a
  // list chooses, and the single value the payload names removes it. This client never spells that value —
  // it comes back from `filter.remove_by` and goes out again as it arrived.
  const roles = query.get('roles');
  const payload = await guard(() => market.load(state.language, {
    roles: roles ? roles.split(',').filter(Boolean) : null,
    domain: query.get('domain'),
  }));
  if (!payload) return;

  market.render(main, payload, {
    language: state.language,
    onFilter: (chosen) => { location.hash = marketHash({ roles: chosen }); },
    onOpen: (id) => { location.hash = marketHash({ listingId: id }); },
  });
  main.append(marketLinks('market'));
}

/** One place that builds S-11's hash, so the two parameter names are spelled once. */
function marketHash({ roles = null, domain = null, listingId = null } = {}) {
  const query = new URLSearchParams();
  if (listingId) query.set('listing', listingId);
  if (roles && roles.length) query.set('roles', roles.join(','));
  if (domain) query.set('domain', domain);
  const tail = query.toString();
  return tail ? `#/market?${tail}` : '#/market';
}

/** S-05 — the stage map. Five situations, all open, and nothing that says where the member is. */
async function renderStages() {
  clear(main);
  const payload = await guard(() => stages.load(state.language));
  if (!payload) return;
  stages.render(main, payload, { language: state.language });
  main.append(vaultLinks('stages'));
}

/**
 * S-09 — the seven life-event modules. The index, and one module by its key.
 *
 * `#/life-events?key=<key>` is R-182's address: the seven keys are stable and are the whole of it, which is
 * what lets The Know open a module directly rather than through a menu.
 */
async function renderLifeEvents() {
  clear(main);
  const key = hashQuery().get('key');

  if (key) {
    const payload = await guard(() => lifeEvents.loadOne(key, state.language));
    if (!payload) return;
    lifeEvents.renderOne(main, payload, {
      language: state.language,
      onBack: () => { location.hash = '#/life-events'; },
    });
    return;
  }

  const payload = await guard(() => lifeEvents.load(state.language));
  if (!payload) return;
  lifeEvents.render(main, payload, {
    language: state.language,
    onOpen: (chosen) => { location.hash = `#/life-events?key=${encodeURIComponent(chosen)}`; },
  });
  main.append(vaultLinks('life-events'));
}

/** S-13 — the community programme. R-222: nothing behind this route is called an event. */
async function renderCommunity() {
  clear(main);
  const payload = await guard(() => community.load());
  if (!payload) return;
  community.render(main, payload, { language: state.language, onChanged: renderCommunity });
  main.append(marketLinks('community'));
}

/** S-10's other half — the learning path, its prerequisites-as-facts and R-193's three exits. */
async function renderLearning() {
  clear(main);
  const payload = await guard(() => learning.load(state.language));
  if (!payload) return;
  learning.render(main, payload, { language: state.language });
  main.append(knowLinks('learning'));
}

const ROUTES = {
  // Item 1's entry surface, and the landing route. A question field and nothing else above the fold —
  // Journey & Design page 1: "It carries no member data, needs no intake, works in the first second, and
  // does not assume which journey the person is on." The role grid moved behind the Vault door for the
  // same reason page 2 gives: nobody meets the four roles before they have entered data.
  ask: renderAsk,
  // Item 8's Vault door. It opens on the Plan pane; `vaultLinks` is what makes the rest reachable from
  // every one of the Vault's rooms.
  vault: renderVaultHome,
  plan: renderPlan,
  containers: renderContainers,
  // Item 4's Actions pane. A room in the Vault rather than a door, and the same list the panel shows.
  actions: renderActions,
  // The document table. Named `documents` since 4 September 2026: item 4 makes "Vault" the whole screen
  // and documents ONE pane inside it, so the route that meant the document store could not go on being
  // called the thing that now means the container.
  documents: renderDocuments,
  runs: renderRuns,
  befund: renderBefund,
  // R-160. A room behind the Plan door rather than a door of its own: the three things S-07 filters by —
  // a position, a goal, a vault item — are all reached through that door, so the record of what was
  // decided about them belongs beside them. The Befund is a door because it is the whole of what a member
  // gets out; this is one part of the plan looked at along a different axis.
  decisions: renderDecisions,
  settings: renderSettings,
  // §3's Knowledge and Community door, and S-10 is what is behind it. Still not S-08 — see
  // `renderCapabilities`, which says so on the screen rather than only here.
  // Item 5's Feed pane, in the Reading Room's shape.
  feed: renderFeed,
  know: renderCapabilities,
  // Item 5. Open before sign-in — see `route()`, which returns it before the token check.
  regime: renderRegime,
  // S-10's other half and S-13, behind the same door as the capability statements — see `knowLinks` for
  // why the door's name promised both and only the first arrived.
  learning: renderLearning,
  community: renderCommunity,
  // S-11. **This entry replaced `renderPlaceholder`**, whose string was literally "Noch nicht gebaut."
  // behind the most rigorously guarded module in the build.
  market: renderMarket,
  // Item 7's community surface. A room behind the Market door, beside the gatherings.
  network: renderNetwork,
  // S-05 and S-09. Rooms behind the Plan door rather than doors of their own: the door is already called
  // "Plan & Lebensereignisse", and a fifth door for the half of a name that already exists would be a
  // second answer to the same question.
  stages: renderStages,
  'life-events': renderLifeEvents,
  // R-210 / R-213. Reached from the settings screen and from the Know panel's own confirmation that a
  // curator session was opened — which is the moment a member finds out that opening one shares nothing.
  grants: renderGrants,
};

/**
 * S-08's entry surface. Item 1.
 *
 * **The surface holds its own last answer and this does not re-ask.** Arriving back at `#/ask` from the
 * Vault renders what is already there; item 1 forbids the silent recompute, because "a second run can
 * produce a different figure than the one the person already acted on".
 */
function renderAsk() {
  ask.render(clear(document.querySelector('main')), {
    language: state.language,
    // One chooser, the same one the chrome button and the panel use (A115). A refusal offering its own
    // curator route would be a third copy.
    onCurator: () => panel.openCurator(),
    // Item 1: "offers to start there". The intake is the onboarding screen; the named input decides
    // nothing here beyond where the member lands.
    onStart: () => { location.hash = '#/plan'; },
  });
  announce(t('ask.label', state.language));
}

function routeName() {
  return (location.hash.replace(/^#\/?/, '') || 'plan').split('?')[0];
}

/**
 * The query half of the hash: `#/decisions?position=abc` gives `{position: 'abc'}`.
 *
 * **Why the state lives in the hash rather than in a module variable.** S-07 is filterable (R-160), and a
 * member arrives at it from a position, from a goal, or from the navigation with no filter at all. A filter
 * held in a variable would survive a route change invisibly — the member would leave the screen, come back
 * from the nav, and still be looking at one position's history with nothing to say so. In the hash it is
 * visible, it is what `hashchange` already re-reads, and a link can carry it. `routeName` splits on the
 * same `?`, so the two halves cannot disagree about where the name ends.
 */
function hashQuery() {
  const hash = location.hash.replace(/^#\/?/, '');
  const index = hash.indexOf('?');
  return new URLSearchParams(index === -1 ? '' : hash.slice(index + 1));
}

const panel = know.mount(document.body, {
  getMemberId: () => session.memberId(),
  getLanguage: () => state.language,
  // R-173: the screen the Curator button was pressed on, read at the moment it is pressed rather than
  // captured at mount — the panel outlives every route change, so a captured value would go stale.
  getRoute: routeName,
  curatorId: state.curatorId,
});

// ---------------------------------------------------------------- the Curator button (item 2)
//
// **A product-wide constraint, not a feature of a screen.** The update script is explicit: "reachable in
// one tap from every screen ... It is never inside a menu, and its treatment is identical everywhere."
// Journey & Design page 3 gives the reason it earns header space: the Curator button "is what prevents the
// app from becoming a closed AI loop, and it is what makes the regulatory position defensible — the line
// between education and advice is maintained not by restricting what MiniMind can say but by ensuring a
// human is always one tap away."
//
// **Why in the chrome and not in the panel, where R-170 already put one.** R-170's button is in the
// panel's header and is genuinely always visible *while the panel is docked*. Below `know.DOCK_QUERY` the
// panel is a drawer behind a launcher, so on a phone the route to a human was: tap the launcher, wait for
// the drawer, then tap Curator. Two taps, and inside something that can be closed.
//
// **It is not a fifth door.** A door is a place you go; this opens a chooser over wherever you already
// are, and the session records the screen underneath it (R-173). It sits in `.chrome-end` with the
// language switch — the container that already exists for chrome that is not navigation — rather than in
// `.doors`, which `aria-current` and the print sheet both treat as the set of pages.
const curatorButton = h('button', {
  type: 'button',
  // `add` is the panel button's own class, so the two are the same control wherever a member meets it,
  // which is what "its treatment is identical everywhere" asks for. `curator-button` is a hook for the
  // print rule and for the client scanner, and carries no appearance of its own.
  class: 'add curator-button',
  'data-i18n': 'know.curator',
  text: t('know.curator', DEFAULT_LANGUAGE),
  onClick: () => panel.openCurator(),
});

/**
 * Shown exactly when the panel would be. Before sign-in there is no member for a curator to be opened for,
 * and a button that opened nothing would be worse than an absent one.
 *
 * Called from `route()` immediately after `panel.sync()`, so it reads a state that has just been
 * recomputed rather than one from the previous screen.
 */
function syncCuratorButton() {
  if (panel.available()) curatorButton.removeAttribute('hidden');
  else curatorButton.setAttribute('hidden', '');
}

{
  // Appended once, at module load, so it is in the document before `applyChrome` runs and is translated
  // with the rest of the chrome. First in `.chrome-end`, ahead of the language switch: the route to a
  // human is not the last thing in the row.
  const end = chromeEnd();
  if (end) end.prepend(curatorButton);
  curatorButton.setAttribute('hidden', '');
}

function route() {
  // A40, and before the member gate rather than inside it: a curator has no member token, so a route that
  // asked for one first could never reach this screen. Also before the must-change redirect, because a
  // member whose own password needs changing is not a reason to close the curators' door.
  if (isCuratorRoute()) return renderCurator();
  // Item 5's Regime pane, before the token check and for the same reason the curator door is: a person
  // without a session has somewhere to be. It carries no member data by construction — `GET /api/regime`
  // takes no member id — so there is nothing here for a session to protect.
  if (routeName() === 'regime') return renderRegime();
  if (!session.token()) return renderLogin();
  if (session.mustChange()) return renderPasswordChange();

  const name = routeName();
  const handler = ROUTES[name] || ROUTES.plan;
  for (const link of document.querySelectorAll('.door')) {
    if (link.dataset.route === name) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  }
  // Before the screen renders, so the panel is present alongside it rather than after it.
  panel.sync();
  syncCuratorButton();
  // Returned rather than dropped. Four of the five handlers are async and every one of them announces its
  // own screen to `#live` when it finishes; a caller that needs to say something after the screen has
  // settled — `changeLanguage` — would otherwise be overwritten by an announcement still in flight.
  return handler();
}

window.addEventListener('hashchange', route);

/**
 * The opening move: if a token is stored, ask the server who it belongs to.
 *
 * A stored token is a claim, not a session — it may have expired, or been revoked from another device
 * (R-213), or belong to a database that has since been reset. `GET /api/session` is the cheapest possible
 * question and its answer also carries the display name and the locale, so the first screen can be right
 * about the language rather than defaulting and then correcting itself.
 */
async function boot() {
  applyChrome(chooseLanguage());
  // A40. Someone who has bookmarked the curator door, or reloaded on it, lands on it — and does not have
  // a stored member token read on their behalf first. There is nothing stored for a curator to restore:
  // `app/curator.js` holds the credential in memory only, so this is the sign-in form.
  if (isCuratorRoute()) return renderCurator();
  if (!session.token()) return renderLogin();
  try {
    const who = session.refresh(await readSession());
    afterSignIn(who);
  } catch (error) {
    session.end();
    renderLogin();
    if (!(error instanceof ApiError)) renderError(error);
  }
}

boot();
