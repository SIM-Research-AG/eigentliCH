// R-210 and R-213 — the member granting a curator access, and taking it away.
//
// **This is the screen A90 found missing in both directions.** `POST`, `GET` and `DELETE
// /api/curator/grants` have been complete and guarded since phase 5: scoped, time-limited, appended to an
// audit, revocable with immediate effect. There was no client function for grants at all, so a member could
// neither open a window nor close one — and a curator who signed in correctly saw nothing, because every
// read under the curator prefix refuses without a live grant. The server kept a promise the product could
// not keep.
//
// ===========================================================================================================
// THE THREE THINGS THIS SCREEN HAS TO MAKE PLAIN
// ===========================================================================================================
//
// It is the member's data and the member's decision, so the screen is built around three facts rather than
// around a form:
//
//   1. **What a curator would be able to see.** The scopes, by name, each as a sentence about what it
//      covers — never a single "share my data" switch. R-210's scope is an explicit list and there is no
//      "everything" value on the route; a screen offering one would be inventing the thing the model
//      refuses to store.
//   2. **For how long.** Every grant ends. The window is chosen, stated on the card afterwards, and there
//      is no control here that means "until I say otherwise" — `AccessGrant.expires_at` is not nullable
//      precisely so that a member who forgets is still protected.
//   3. **That withdrawing takes effect immediately.** R-213's word is *immediate*. It is said before the
//      button is pressed, not in a confirmation afterwards.
//
// **Nothing on this screen caches a grant, and that is the load-bearing consequence of point 3.** There is
// no module-level state in this file: `load()` re-reads all three payloads every time, a revocation
// re-reads rather than patching the DOM, and a grant that has lapsed since the screen was drawn disappears
// on the next read instead of sitting there looking live. `app/curator.js` describes the same discipline
// from the curator's side and gives the same reason.
//
// **There is no pending state, so nothing here may suggest one.** The route commits on the request:
// `grant_access` flushes and the route commits, `revoke_grant` sets the timestamp and `is_live` consults
// it before `expires_at`, so the curator's very next read is refused. A screen that said "withdrawal
// requested" or greyed a card out "while it takes effect" would be describing machinery that does not
// exist, and it would teach a member to distrust the one control on this page that is instant. So the copy
// says *is withdrawn*, not *will be*, and the only asynchronous thing on screen is the button's own
// disabled state while its request is in flight.
//
// **A withdrawn grant stays on the screen, as withdrawn.** Revocation is a timestamp and the route says
// `deleted: false`; hiding the row would tell a member the record went with the access, which is the
// opposite of what happened and the opposite of what the audit is for.
//
// **The scope vocabulary is read from `GET /api/curator/grantable`, never written here.** A scope name this
// client invented would be a name nothing checks, and the service says in as many words that a scope
// nothing checks is indistinguishable from full access. The names come from the route; the *words* for
// them come from `i18n.js`, and a name with no string renders as itself rather than vanishing — a scope
// added on the server must show up here as something unlabelled rather than as nothing at all.
//
// **C-07:** there is no count of grants, no count of scopes, no "3 of 5 areas shared", and no meter of how
// much of a member's material is open. R-003 applies to the link that leads here, too.
//
// **C-01:** this screen does not advise. It states what a scope covers, what a window is, and what
// withdrawing does. It does not say which curator to choose, which scopes to open, or how long for — those
// are the member's own decisions, and A92 is the record of C-01 being widened to cover exactly that.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { detailText, getCurators, getGrants, grantAccess, grantableScopes, revokeGrant } from '../app/api.js';

//: Windows offered for a new grant, in hours. R-210 is "time-limited", so every one of these ends and
//: there is deliberately no entry meaning "no expiry" — the route would refuse it and the column could not
//: hold it.
//:
//: **A client list, and the one thing on this screen that is.** The route publishes
//: `default_lifetime_hours` and nothing else about time, so the alternative to a list here is a free-text
//: number field, which is a worse question: a member asked "how many hours" with no anchor invents one.
//: The published default is folded into this list by `windows()` below, so the server's own number is
//: always among the choices and this list can never contradict it.
const OFFERED_WINDOWS = [1, 4, 24, 72, 168];

/**
 * The windows to offer, with the server's published default guaranteed to be one of them.
 *
 * Sorted numerically, because a list of durations that is not in order is a list a member has to read
 * twice. That is the only ordering decision on this screen, and it is about a client-side constant rather
 * than about anything the server ranked.
 */
function windows(grantable) {
  const published = Number(grantable && grantable.default_lifetime_hours);
  const hours = new Set(OFFERED_WINDOWS);
  if (Number.isFinite(published) && published > 0) hours.add(published);
  return [...hours].sort((a, b) => a - b);
}

/** A duration as words. Days above 24 hours, because "168 Stunden" is a number nobody converts. */
function windowLabel(hours, language) {
  if (hours === 1) return t('grants.window_one_hour', language);
  if (hours % 24 === 0) {
    const days = hours / 24;
    return days === 1
      ? t('grants.window_one_day', language)
      : t('grants.window_days', language).replace('{n}', String(days));
  }
  return t('grants.window_hours', language).replace('{n}', String(hours));
}

/** `31.08.2026, 14:05` from an ISO timestamp. A grant is a window, so the time of day is part of it. */
function readableMoment(iso, language) {
  if (typeof iso !== 'string') return '';
  const [day, rest] = iso.split('T');
  const parts = day.split('-');
  if (parts.length !== 3) return iso;
  const clock = (rest || '').slice(0, 5);
  const date = language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : parts.join('-');
  return clock ? `${date}, ${clock}` : date;
}

/**
 * The word for one scope, or the scope's own name.
 *
 * **Falling back to the name is deliberate.** `GRANTABLE` is the server's tuple and this client's string
 * table is a second file; if a sixth scope is added there and not here, a member must see that there is a
 * sixth area rather than see five where the server knows six. An unlabelled scope is a translation gap; a
 * silently dropped one is a member consenting to something invisible.
 */
function scopeLabel(name, language) {
  const key = `grants.scope_${name}`;
  const word = t(key, language);
  return word === key ? name : word;
}

/** What one scope covers, in a sentence, or nothing where this client has no sentence for it. */
function scopeMeaning(name, language) {
  const key = `grants.scope_${name}_covers`;
  const sentence = t(key, language);
  return sentence === key ? null : sentence;
}

/**
 * The curator a grant names, by name where the directory has one and by id where it does not.
 *
 * **The directory is not the complete list of curators.** `list_curators` omits inactive and fictional
 * rows (A62), and a grant may perfectly well name one of them — the demonstration curator is a real row a
 * real grant can point at. So this never invents a name and never hides the grant: an unnameable curator
 * is rendered as the id the grant carries, with a sentence saying the directory does not list them.
 */
function curatorName(curatorId, directory) {
  const found = (directory || []).find((person) => person.id === curatorId);
  return found ? found.display_name : null;
}

/**
 * One grant, live or ended.
 *
 * The state is the server's `live`, never this client comparing `expires_at` to a clock: two clocks
 * disagree, and the one that decides is the one the curator's next read consults. Where it ended, the
 * screen says *how* — withdrawn or lapsed — because a member who withdrew should read that they did.
 */
function grantNode(grant, { language, directory, onChanged }) {
  const name = curatorName(grant.curator_id, directory);
  const scopes = grant.scope || [];

  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });

  const revoke = button(t('grants.revoke', language), {
    class: 'add',
    onClick: async (event) => {
      const pressed = event.currentTarget;
      pressed.disabled = true;
      error.setAttribute('hidden', '');
      try {
        await revokeGrant(grant.id);
        // **Re-read, then announce, and the order is the whole of it.** `onChanged` re-reads and
        // re-renders, and `render` announces the screen when it finishes; announcing first put the outcome
        // into `#live` and had it overwritten milliseconds later by the screen's own announcement, so a
        // member using a screen reader heard the screen name and never heard that the access was gone.
        // A86 found this on the language switch and A94 found it again on the capability form; this is the
        // third place it would have happened, and it was found the same way — by running the client.
        await onChanged();
        announce(t('grants.revoked_announced', language));
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        pressed.disabled = false;
      }
    },
  });

  return h('div', { class: 'cell grant', 'data-live': String(Boolean(grant.live)) }, [
    h('p', { class: 'position-label', text: name || t('grants.curator_unnamed', language) }),
    name
      ? null
      : h('p', { class: 'field-hint', text: t('grants.curator_not_in_directory', language) }),

    // R-210's scope, as words rather than as a summary. Every name the grant carries, one per line, so
    // there is nothing to read as "and some other things".
    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('grants.scopes_label', language) }),
      h('ul', {}, scopes.map((name_) => h('li', { text: scopeLabel(name_, language) }))),
    ]),

    h('p', {
      class: 'position-meta',
      text: `${t('grants.granted_at', language)}: ${readableMoment(grant.granted_at, language)}`,
    }),
    h('p', {
      class: 'position-meta',
      text: `${t('grants.expires_at', language)}: ${readableMoment(grant.expires_at, language)}`,
    }),

    // Withdrawn, lapsed, or open — the three states a member can actually be in, each named.
    grant.revoked_at
      ? h('p', {
          class: 'position-meta',
          text: `${t('grants.revoked_at', language)}: ${readableMoment(grant.revoked_at, language)}`,
        })
      : null,
    grant.live
      ? null
      : h('p', {
          class: 'field-hint',
          text: grant.revoked_at
            ? t('grants.ended_withdrawn', language)
            : t('grants.ended_lapsed', language),
        }),
    // Revocation is a timestamp, and the route says `deleted: false`. Said on the ended card, because
    // "the access is gone and the record is not" is the part a member would otherwise have to be told
    // twice.
    grant.revoked_at
      ? h('p', { class: 'field-hint', text: t('grants.record_kept', language) })
      : null,

    error,
    grant.live
      ? h('div', {}, [
          h('p', { class: 'field-hint', text: t('grants.revoke_hint', language) }),
          h('div', { class: 'actions' }, [revoke]),
        ])
      : null,
  ]);
}

/**
 * The list of grants, in two groups the payload itself decides.
 *
 * **Grouping by `live` is rendering a field, not sorting a list.** The server puts `live` on every row;
 * splitting on it shows a member what is open now, which is the question R-213 exists to answer. Inside
 * each group the payload's own order is kept — there is nothing here that re-ranks anything.
 */
function grantsSection(grants, { language, directory, onChanged }) {
  const rows = grants || [];
  const live = rows.filter((grant) => grant.live);
  const ended = rows.filter((grant) => !grant.live);

  const section = h('section', { class: 'grants' }, [
    h('h2', { text: t('grants.open_heading', language) }),
  ]);

  // R-110. An empty state says what is there and what would go there. It does not tell the member to do
  // something about it: whether to open a window is their decision, and C-01 refuses advice about those
  // (A92). So this sentence describes the screen, and the form below is the answer to "how".
  section.append(
    live.length
      ? h('div', { class: 'grid' }, live.map((grant) => grantNode(grant, { language, directory, onChanged })))
      : h('p', { class: 'field-hint', text: t('grants.none_open', language) }),
  );

  if (ended.length) {
    section.append(
      h('h2', { text: t('grants.ended_heading', language) }),
      h('p', { class: 'field-hint', text: t('grants.ended_hint', language) }),
      h('div', { class: 'grid' }, ended.map((grant) => grantNode(grant, { language, directory, onChanged }))),
    );
  }

  return section;
}

/**
 * The form that opens a window. **A door, not a control standing open** — the same shape the capability
 * form uses, and for the same reason: this is a decision, so it takes a deliberate press to reach it.
 *
 * **Nothing is preselected. Not the curator, not a scope, not a window.** A86's fourth defect is the
 * argument: a default is an inference, and the quietest kind, because nobody sees it happen. Here the
 * inference would be eigentliCH choosing which of a member's material a named person may read, which is the
 * one decision on this screen that is not ours to make even by accident. The placeholder options carry no
 * value and the submit refuses without a choice.
 */
function grantForm(payload, { language, onChanged }) {
  const directory = (payload.curators && payload.curators.curators) || [];
  const grantable = payload.grantable || {};
  const scopes = grantable.grantable || [];

  const curatorSelect = h('select', { name: 'curator', required: '' }, [
    h('option', { value: '', text: t('grants.choose_curator_none', language) }),
    ...directory.map((person) => h('option', {
      value: person.id,
      text: person.role_label ? `${person.display_name} — ${person.role_label}` : person.display_name,
    })),
  ]);

  // R-210's scope, one checkbox per name the server knows. Checkboxes rather than a multi-select because
  // each one has a sentence under it saying what it covers, and a member choosing what a person may read
  // should be reading that sentence at the moment they choose.
  const boxes = scopes.map((name) => {
    const box = h('input', { type: 'checkbox', class: 'consent-box', value: name });
    const meaning = scopeMeaning(name, language);
    return {
      name,
      box,
      // The same shape R-103's agreement box uses on the registration form, and deliberately the same
      // classes: `.consent-agree` already carries the 44px target and `.consent-box` its own focus ring,
      // so a second checkbox treatment would be a second thing to keep accessible.
      node: h('label', { class: 'field consent-agree' }, [
        box,
        h('span', { class: 'field-label', text: scopeLabel(name, language) }),
        meaning ? h('span', { class: 'field-hint', text: meaning }) : null,
      ]),
    };
  });

  const windowSelect = h('select', { name: 'window', required: '' }, [
    h('option', { value: '', text: t('grants.choose_window_none', language) }),
    ...windows(grantable).map((hours) => h('option', {
      value: String(hours),
      text: hours === Number(grantable.default_lifetime_hours)
        ? `${windowLabel(hours, language)} — ${t('grants.window_usual', language)}`
        : windowLabel(hours, language),
    })),
  ]);

  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('grants.submit', language)]);

  const form = h('form', {
    class: 'position-form',
    hidden: '',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      const chosen = boxes.filter((entry) => entry.box.checked).map((entry) => entry.name);
      // Refused here as well as on the route, and the two refusals say different things. The server's is
      // "a grant covering nothing is not a grant"; this one is the question being asked again, before a
      // member reads a sentence about grants wearing clothes.
      if (!curatorSelect.value) {
        error.textContent = t('grants.no_curator_chosen', language);
        error.removeAttribute('hidden');
        curatorSelect.focus();
        return;
      }
      if (!chosen.length) {
        error.textContent = t('grants.no_scope_chosen', language);
        error.removeAttribute('hidden');
        boxes[0].box.focus();
        return;
      }
      if (!windowSelect.value) {
        error.textContent = t('grants.no_window_chosen', language);
        error.removeAttribute('hidden');
        windowSelect.focus();
        return;
      }

      submit.disabled = true;
      try {
        await grantAccess({
          curatorId: curatorSelect.value,
          scope: chosen,
          hours: Number(windowSelect.value),
        });
        // Re-read first, announce after. See `grantNode`'s revoke handler for why the order matters.
        await onChanged();
        announce(t('grants.granted_announced', language));
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        submit.disabled = false;
      }
    },
  }, [
    h('h3', { text: t('grants.new_heading', language) }),
    h('p', { class: 'field-hint', text: t('grants.new_hint', language) }),

    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('grants.choose_curator', language) }),
      curatorSelect,
      h('span', { class: 'field-hint', text: t('grants.choose_curator_hint', language) }),
    ]),

    directory.length
      ? null
      : h('p', { class: 'field-hint', text: t('grants.no_curators', language) }),

    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('grants.choose_scopes', language) }),
      h('span', { class: 'field-hint', text: t('grants.choose_scopes_hint', language) }),
      ...boxes.map((entry) => entry.node),
    ]),

    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('grants.choose_window', language) }),
      windowSelect,
      h('span', { class: 'field-hint', text: t('grants.choose_window_hint', language) }),
    ]),

    error,
    h('div', { class: 'actions' }, [submit]),
  ]);

  const opener = button(t('grants.new_open', language), {
    class: 'add',
    'aria-expanded': 'false',
    onClick: (event) => {
      const opening = form.hasAttribute('hidden');
      if (opening) form.removeAttribute('hidden');
      else form.setAttribute('hidden', '');
      event.currentTarget.setAttribute('aria-expanded', String(opening));
    },
  });

  return h('div', {}, [opener, form]);
}

/**
 * A11: no member id in any of the three calls. All of them are the token's member's.
 *
 * Three requests every time this screen is drawn, and none of the answers is kept between draws. The
 * directory could in principle be cached — it is a staff list and it does not change while a member reads
 * — but it is fetched with the grants so that the whole screen is one snapshot rather than a fresh list of
 * grants labelled from a stale list of people.
 */
export async function load() {
  const [grants, grantable, curators] = await Promise.all([
    getGrants(),
    grantableScopes(),
    getCurators(),
  ]);
  return { grants, grantable, curators };
}

export function render(container, payload, { language, onChanged }) {
  clear(container);

  const grantable = payload.grantable || {};
  const directory = (payload.curators && payload.curators.curators) || [];

  container.append(
    h('span', { class: 'lbl', text: t('grants.eyebrow', language) }),
    h('h1', { text: t('grants.title', language) }),
    h('p', { class: 'lede', text: t('grants.lede', language) }),
  );

  // The three facts, before any control. R-210's two properties and R-213's one, stated as sentences
  // rather than implied by the shape of the form — a member reading this page has to be able to learn what
  // a grant is without pressing anything.
  container.append(
    h('div', { class: 'notice' }, [
      h('p', { text: t('grants.scoped', language), style: 'margin:0' }),
      h('p', { text: t('grants.time_limited', language), style: 'margin:8px 0 0' }),
      h('p', { text: t('grants.immediate', language), style: 'margin:8px 0 0' }),
      // Said out loud because the absence is the surprising part: there is no waiting period, no approval
      // step and nothing to confirm afterwards. A member who expects one would keep the screen open
      // looking for it.
      h('p', { class: 'field-hint', text: t('grants.no_pending', language), style: 'margin:8px 0 0' }),
    ]),
  );

  // R-210 said as an absence, from the route's own note rather than from a sentence this client wrote:
  // there is no "all" and no "until revoked". Rendered only when the payload actually says so, so the
  // claim on screen is the server's.
  if (typeof grantable.note === 'string' && grantable.note) {
    container.append(h('p', { class: 'field-hint', text: t('grants.no_blanket_access', language) }));
  }

  container.append(grantsSection(payload.grants && payload.grants.grants, {
    language,
    directory,
    onChanged,
  }));

  container.append(grantForm(payload, { language, onChanged }));

  announce(t('grants.announced', language));
}
