// A40 / S-12: the curator's way in, the forced password change, and what a curator can honestly be shown.
//
// **Why this is a separate surface and not a second form on the member screen.** Curators and members are
// two populations with two credential tables, and the member screen is the one everybody lands on. A
// second set of email and password fields there would put a choice in front of every member on their way
// in — a choice five people in the world need to make and everybody else has to read past and decide is
// not for them. Worse, it invites the mistake it looks like it is preventing: a member typing their own
// address into the curator half and being refused, which is the exact confusion the two tables exist to
// avoid. So the member screen carries one sentence and one link, in `.definition-toggle` — the client's
// existing quiet text-button treatment, the same weight as "Was gehört hierher?" — and the whole of the
// curator's entry lives behind it at `#/kurator`.
//
// **The refusal is the server's, printed as written.** Same rule as `login.js`: a wrong address and a
// wrong password are one 401 with one message, and a client that translated it into "no curator with that
// address" would rebuild the oracle `services/curator.py` derives against a throwaway salt to avoid.
// Nothing here interprets a status code into copy of its own.
//
// **What a curator can do here is bounded by A40 issuing no token, and the screen says so.** There is no
// curator session table, so `POST /api/curator/login` returns an identity and nothing else, and every
// later request re-authenticates from the credential `app/curator.js` holds in memory for this window.
// `curator.no_token` states that plainly on the landing screen, because a curator who reloads and finds
// themselves signed out should have been told rather than surprised.
//
// **R-210 shapes the landing screen more than anything else does.** A curator cannot browse. Every read
// beneath the `/api/curator` prefix consults a live, scoped grant or raises, so this screen shows what the
// server will actually answer: the members who have granted something, the scopes they granted, when the
// grant lapses — and, when nobody has granted anything, a sentence saying that and why, rather than an
// empty table that would read as "no members exist" or as a search box that has not been typed into yet.
//
// **R-213: nothing is cached.** No grant, no worklist and no scope is held anywhere in this module — it
// declares no module-scope state at all. Every draw re-reads `GET /api/curator/members`, and the per-member
// detail re-reads the workbench. A grant remembered for the length of a screen is a grant that outlives
// its own revocation.
//
// **C-10: one control on this screen writes an audit row.** "Beratung eröffnen" posts to
// `/api/curator/workbench/sessions`, which appends an `opened` event to a table whose UPDATE and DELETE
// are refused by database trigger. That is said beside the button, before it is pressed, and not reported
// after the fact.
//
// A51: no new colours and no new controls. `.position-form`, `.field`, `.primary`, `.add`, `.notice`,
// `.report*` and `.definition-toggle` are the ones every other surface uses.

import { announce, button, clear, formatAmount, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import {
  ApiError,
  addCuratorNote,
  changeCuratorPassword,
  closeCuratorSession,
  curatorLogin,
  curatorMembers,
  curatorWorkbench,
  grantableScopes,
  openWorkbenchSession,
  readCuratorSession,
  recordCuratorRecommendation,
} from '../app/api.js';
import * as curator from '../app/curator.js';

//: R-173 / C-10. Which screen a consultation was opened from, recorded at the time. A constant rather than
//: a literal at the call site, so the audit row cannot come to disagree with the screen it names.
const OPENED_FROM = 'curator_landing';

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

/** `role="alert"`, so a refusal that appears after submit is announced. Same as `login.js`. */
function errorNotice() {
  return h('div', { class: 'notice error', role: 'alert', hidden: '' });
}

function show(node, message) {
  node.textContent = message;
  node.removeAttribute('hidden');
}

/** The server's own words, whatever the failure was. Never a sentence this client wrote about a status. */
function detailOf(failure) {
  return failure instanceof ApiError ? failure.detail || failure.message : String(failure);
}

/** `2026-09-01T14:12:57+00:00` as a local wall-clock time, or the string as it arrived. */
function clockTime(iso, language) {
  if (!iso) return '';
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleString(language === 'de' ? 'de-CH' : 'en-CH');
}

/**
 * The word for one of `GRANTABLE`'s scope names.
 *
 * Falls back to the server's own name when the string table has none, rather than to a blank: a scope this
 * client cannot name is still a scope the member granted, and hiding it would understate what the curator
 * can see. `test_curator_signin.py` walks `GRANTABLE` against the table so the fallback stays unused.
 */
function scopeLabel(name, language) {
  const label = t(`curator.scope_${name}`, language);
  return label === `curator.scope_${name}` ? name : label;
}

function scopeList(names, language) {
  return (names || []).map((name) => scopeLabel(name, language)).join(', ');
}

// ================================================================ S-12: what the member actually shared
//
// **`workbench.sections` was fetched and thrown away.** This screen called `curatorWorkbench`, appended
// `granted_scope` and `not_granted` as two comma-separated strings, and dropped the payload's third and
// largest field on the floor — the one carrying the positions, the goals, the vault index, the decisions
// and the open items that the grants are grants *of*. So a curator could read that a member had shared
// their goals and could not read the goals. R-210 was enforced perfectly over material no screen showed.
//
// **Each section is rendered from the same payload the member's own screen reads.** `curator_view_goals`
// returns `list_goals` unchanged and says why in its docstring: a curator sees what the member sees,
// including R-113's absence of any funded percentage. Nothing here adds a figure the member does not have,
// and nothing here counts rows.
//
// **A granted section that is empty says so.** An empty area and a withheld area are different facts and
// `not_granted` is the payload's own way of keeping them apart; a section that rendered as nothing would
// undo that distinction at the last step.

/** One line about one thing, in the client's existing report treatment. */
function line(label, value) {
  return h('p', { class: 'report-sentence' }, [
    h('span', { class: 'report-quote-label', text: label }),
    value === null || value === undefined ? '' : String(value),
  ]);
}

function amountLine(position, language) {
  const figure = formatAmount(position.magnitude, language === 'de' ? 'de-CH' : 'en-CH');
  if (figure === null) return null;
  const unit = position.magnitude_unit ? t(`unit.${position.magnitude_unit}`, language) : '';
  return h('p', { class: 'report-meta', text: unit ? `${figure} ${unit}` : figure });
}

function positionsSection(payload, language) {
  const rows = [];
  for (const cell of (payload && payload.cells) || []) {
    for (const position of cell.positions || []) {
      rows.push(h('div', { class: 'report-fact' }, [
        line(`${cell.display} · ${t(`capital.${cell.capital_type}`, language)}`, position.label),
        amountLine(position, language),
        position.active === false
          ? h('p', { class: 'report-meta', text: t('position.inactive', language) })
          : null,
      ]));
    }
  }
  return rows;
}

function goalsSection(payload, language) {
  return ((payload && payload.goals) || []).map((goal) => h('div', { class: 'report-fact' }, [
    line(t('curator.scope_goals', language), goal.name),
    goal.target_date ? h('p', { class: 'report-meta', text: goal.target_date }) : null,
  ]));
}

function vaultSection(payload, language) {
  const items = (payload && payload.items) || [];
  const rows = items.map((item) => h('div', { class: 'report-fact' }, [
    line(item.kind || '', item.title),
    item.expiry_date ? h('p', { class: 'report-meta', text: item.expiry_date }) : null,
    item.notes ? h('p', { class: 'report-meta', text: item.notes }) : null,
  ]));
  // Stated on the section rather than inferred from the absence of a download control: the payload's
  // `content_bytes_included` is false, and a curator should read why rather than wonder.
  rows.push(h('p', { class: 'field-hint', text: t('curator.vault_no_bytes', language) }));
  return rows;
}

function decisionsSection(payload, language) {
  return ((payload && payload.decisions) || []).map((decision) => h('div', { class: 'report-fact' }, [
    line(decision.question || '', decision.choice),
    // R-212. Which curator, or the member — never "a curator".
    h('p', {
      class: 'report-meta',
      text: decision.author_ref ? `${decision.author} · ${decision.author_ref}` : decision.author,
    }),
    decision.reasoning ? h('p', { class: 'report-meta', text: decision.reasoning }) : null,
  ]));
}

function actionItemsSection(payload, language) {
  return ((payload && payload.items) || []).map((item) => h('div', { class: 'report-fact' }, [
    // The same string table the member's own panel reads, so a curator and the member are looking at one
    // sentence rather than at a label and an identifier.
    line(t(`know.trigger_${item.trigger_kind}`, language), item.due_date || ''),
    ...(item.prepared_options || []).map((option) =>
      h('p', { class: 'report-meta', text: `${option.label} — ${option.consequence}` })),
  ]));
}

const SECTION_RENDERERS = {
  positions: positionsSection,
  goals: goalsSection,
  vault: vaultSection,
  decisions: decisionsSection,
  action_items: actionItemsSection,
};

/** Every granted section, in the order the server listed the grants. */
function sectionsNode(workbench, language) {
  const sections = (workbench && workbench.sections) || {};
  const names = Object.keys(sections);

  if (!names.length) {
    return h('div', { class: 'notice' }, [
      h('p', { text: t('curator.no_sections', language), style: 'margin:0' }),
    ]);
  }

  return h('div', { class: 'report' }, [
    h('p', { class: 'report-heading' }, [
      h('span', { class: 'report-status', text: t('curator.sections', language) }),
    ]),
    ...names.map((name) => {
      const build = SECTION_RENDERERS[name];
      // A scope the server grants and this client has no renderer for is named and left empty rather than
      // omitted: the same argument `scopeLabel` makes above, and a test walks `GRANTABLE` against this
      // table so the branch stays unused.
      const rows = build ? build(sections[name], language) : [];
      return h('div', { class: 'report-block' }, [
        h('p', { class: 'report-heading' }, [
          h('span', { class: 'report-status', text: scopeLabel(name, language) }),
        ]),
        h('div', { class: 'report-facts' }, rows.length
          ? rows
          : [h('p', { class: 'report-meta', text: t('curator.section_empty', language) })]),
      ]);
    }),
  ]);
}

// ================================================================ R-211 / R-212 / C-10: the consultation
//
// **Six sessions existed on the shipped database and `outcome` was NULL on every one.** Not because
// closing was unimplemented — `close_session`, `record_note` and `recommend` are complete, gated and
// tested — but because no client function called any of them and no screen offered them. R-211's sentence
// is "every session is recorded with entry point and outcome"; the product recorded the entry point and
// had no way to record the other half. So an opened consultation could only ever stay open, forever, in a
// table whose whole value is that it is a true account of what happened.
//
// **Three controls, in the order a consultation actually goes.** A note while reading; a recommendation
// when there is one to make; the close when it is over. Each says what it writes before it is pressed,
// because every one of them appends to a log that refuses UPDATE and DELETE at the database.
//
// **The outcome has no default and no placeholder.** `close_session` raises on an empty one in its own
// words — "a session that was had and not accounted for" — and this screen refuses it before the request
// rather than after, so the curator is asked rather than shown a constraint. Nothing here proposes an
// outcome: a suggested outcome is an outcome the audit did not get from a person.
//
// **R-213 again: nothing is held.** The log is re-read from the server after every append rather than
// patched locally, so what is on screen is what the append-only table actually contains.

/** One appended entry, by what it is rather than by its stored kind. */
function logEntry(entry, language) {
  const key = `curator.log_${entry.kind}`;
  const label = t(key, language);
  const detail = entry.detail || {};
  const words = detail.redacted
    ? detail.redacted
    : detail.text || detail.outcome || detail.question || '';

  return h('div', { class: 'report-fact' }, [
    line(label === key ? entry.kind : label, clockTime(entry.at, language)),
    words ? h('p', { class: 'report-meta', text: String(words) }) : null,
    detail.liability_flag ? h('p', { class: 'report-meta', text: t('curator.close_liability', language) }) : null,
  ]);
}

/**
 * The consultation: its log, and the three things that may be appended to it.
 *
 * `sessionId` is the row `openWorkbenchSession` just wrote. Everything below is addressed to it, so a
 * note or a close that arrived after the member revoked still lands on the right consultation — which is
 * exactly the case `close_session` is deliberately not grant-gated for.
 */
function consultationNode(sessionId, memberId, { language, onExpired }) {
  const logRegion = h('div', { class: 'report-facts' });
  const status = h('p', { class: 'report-meta', role: 'status' });
  const error = errorNotice();

  /** R-213. Read again rather than remembered — including whether this session is still open. */
  async function refreshLog() {
    clear(logRegion);
    try {
      const record = await readCuratorSession(curator.held(), memberId, sessionId);
      logRegion.append(
        line(t('curator.consultation_ref', language), record.id),
        line(
          t('curator.close_outcome', language),
          record.outcome || t('curator.still_open', language),
        ),
        ...(record.events || []).map((entry) => logEntry(entry, language)),
      );
      if (record.notes_readable === false) {
        logRegion.append(h('p', { class: 'field-hint', text: t('curator.notes_redacted', language) }));
      }
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) return onExpired();
      logRegion.append(h('p', { class: 'report-meta', text: detailOf(failure) }));
    }
    return null;
  }

  /** One submit path for all three forms: refuse locally, send, re-read, say what happened. */
  function submitter(send, { announceKey, validate }) {
    return async (event, control) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      const refusal = validate();
      if (refusal) {
        show(error, t(refusal, language));
        return;
      }
      control.disabled = true;
      try {
        await send();
        status.textContent = t(announceKey, language);
        announce(t(announceKey, language));
        await refreshLog();
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 401) {
          onExpired();
          return;
        }
        show(error, detailOf(failure));
      } finally {
        control.disabled = false;
      }
    };
  }

  // ---- the note (C-10, grant-gated on the server)
  const noteText = h('textarea', { name: 'note', rows: '3', maxlength: '4000' });
  const noteSubmit = h('button', { type: 'submit', class: 'add' }, [t('curator.note_add', language)]);
  const noteSend = submitter(
    () => addCuratorNote(curator.held(), memberId, sessionId, noteText.value.trim()),
    { announceKey: 'curator.note_added', validate: () => (noteText.value.trim() ? null : 'curator.note_missing') },
  );
  const noteForm = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      await noteSend(event, noteSubmit);
      if (noteText.value.trim() && !error.hasAttribute('hidden')) return;
      noteText.value = '';
    },
  }, [
    field(t('curator.note', language), noteText, t('curator.note_hint', language)),
    h('div', { class: 'actions' }, [noteSubmit]),
  ]);

  // ---- the recommendation (R-212 / C-01)
  const recQuestion = h('input', { type: 'text', name: 'question', maxlength: '1000' });
  const recChoice = h('input', { type: 'text', name: 'choice', maxlength: '2000' });
  const recReasoning = h('textarea', { name: 'reasoning', rows: '2' });
  const recSubmit = h('button', { type: 'submit', class: 'primary' }, [
    t('curator.recommend_submit', language),
  ]);
  const recSend = submitter(
    () => recordCuratorRecommendation(curator.held(), memberId, {
      session_id: sessionId,
      question: recQuestion.value.trim(),
      choice: recChoice.value.trim(),
      reasoning: recReasoning.value.trim() || null,
    }),
    {
      announceKey: 'curator.recommend_done',
      validate: () =>
        (recQuestion.value.trim() && recChoice.value.trim() ? null : 'curator.recommend_missing'),
    },
  );
  const recForm = h('form', {
    class: 'position-form',
    onSubmit: (event) => recSend(event, recSubmit),
  }, [
    h('span', { class: 'lbl', text: t('curator.recommend_heading', language) }),
    // Said before the control, not after: this writes a Decision into the member's permanent record with
    // this curator's id on it, and C-01 is the reason it may exist at all.
    h('p', { class: 'field-hint', text: t('curator.recommend_hint', language) }),
    field(t('curator.recommend_question', language), recQuestion),
    field(t('curator.recommend_choice', language), recChoice),
    field(t('curator.recommend_reasoning', language), recReasoning),
    h('div', { class: 'actions' }, [recSubmit]),
  ]);

  // ---- the close (R-211's other half)
  const outcome = h('input', { type: 'text', name: 'outcome', maxlength: '400' });
  const closingNote = h('textarea', { name: 'closing_note', rows: '2' });
  const liability = h('input', { type: 'checkbox', name: 'liability_flag', class: 'consent-box' });
  const closeSubmit = h('button', { type: 'submit', class: 'primary' }, [
    t('curator.close_submit', language),
  ]);
  const closeSend = submitter(
    () => closeCuratorSession(curator.held(), memberId, sessionId, {
      outcome: outcome.value.trim(),
      note: closingNote.value.trim() || null,
      liabilityFlag: liability.checked ? true : null,
    }),
    {
      announceKey: 'curator.closed',
      validate: () => (outcome.value.trim() ? null : 'curator.close_outcome_missing'),
    },
  );
  const closeForm = h('form', {
    class: 'position-form',
    onSubmit: (event) => closeSend(event, closeSubmit),
  }, [
    h('span', { class: 'lbl', text: t('curator.close_heading', language) }),
    h('p', { class: 'field-hint', text: t('curator.close_hint', language) }),
    field(t('curator.close_outcome', language), outcome),
    field(t('curator.close_note', language), closingNote),
    h('label', { class: 'field' }, [
      liability,
      h('span', { class: 'field-label', text: t('curator.close_liability', language) }),
    ]),
    h('div', { class: 'actions' }, [closeSubmit]),
  ]);

  refreshLog();

  return h('div', { class: 'report-block' }, [
    h('p', { class: 'report-heading' }, [
      h('span', { class: 'report-status', text: t('curator.consultation', language) }),
    ]),
    h('span', { class: 'lbl', text: t('curator.log', language) }),
    logRegion,
    noteForm,
    recForm,
    closeForm,
    error,
    status,
  ]);
}

// ---------------------------------------------------------------- sign in

/**
 * The curator sign-in form.
 *
 * `onSignedIn` is called with what the server returned, including `must_change` — the caller decides which
 * screen comes next, because that decision is the router's and is the same one `main.js` already makes for
 * a member.
 */
export function render(container, { language, onSignedIn, onCancel }) {
  clear(container);

  const email = h('input', {
    type: 'email',
    name: 'email',
    required: '',
    maxlength: '320',
    autocomplete: 'username',
    // Normalised on the server (`_normalise_email`); switching off the phone keyboard's capitalisation
    // only means the field shows the curator what will be sent.
    autocapitalize: 'none',
    spellcheck: 'false',
  });
  const password = h('input', {
    type: 'password',
    name: 'password',
    required: '',
    maxlength: '1024',
    autocomplete: 'current-password',
  });
  const error = errorNotice();
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('curator.submit', language)]);

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      submit.disabled = true;
      const address = email.value;
      const secret = password.value;
      try {
        const payload = await curatorLogin({ email: address, password: secret });
        // Cleared before anything else happens. The credential goes to `app/curator.js`, which holds it
        // in memory for this window and writes it nowhere.
        password.value = '';
        onSignedIn(curator.begin(address, secret, payload));
      } catch (failure) {
        show(error, detailOf(failure));
        password.value = '';
        password.focus();
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: t('curator.eyebrow', language) }),
    h('h1', { text: t('curator.title', language) }),
    h('p', { class: 'lede', text: t('curator.lede', language) }),

    field(t('curator.email', language), email, t('curator.email_hint', language)),
    field(t('curator.password', language), password),

    error,

    h('div', { class: 'actions' }, [submit]),
  ]);

  container.append(form);
  container.append(
    h('div', { class: 'known' }, [
      h('a', {
        href: '#/plan',
        class: 'definition-toggle',
        style: 'text-decoration:none',
        text: t('curator.back', language),
        onClick: onCancel || null,
      }),
    ]),
  );

  email.focus();
}

// ---------------------------------------------------------------- the forced change (A40 / A43 / A53)

/**
 * The curator's forced password change.
 *
 * **The whole reason this exists.** All five real curators are seeded with `must_change` set and their
 * documented password described as good for exactly one login. Until this screen and the route behind it
 * landed, no service, no route and no surface could clear that flag — so the documented password never
 * stopped working and `Curator.must_change` was a field nothing read.
 *
 * **The current password is asked for**, exactly as on the member's screen. That is the server's rule and
 * it is the rule that makes a written-down first password safe: the person choosing the second one is
 * expected to know the first. Reusing the member's `password.*` strings rather than writing a second set,
 * because it is the same moment and the same three fields.
 */
export function renderPasswordChange(container, { language, onChanged, onSignOut }) {
  clear(container);

  const currentPassword = h('input', {
    type: 'password', name: 'current', required: '', maxlength: '1024',
    autocomplete: 'current-password',
  });
  const chosen = h('input', {
    type: 'password', name: 'new', required: '', minlength: '12', maxlength: '1024',
    autocomplete: 'new-password',
  });
  const repeated = h('input', {
    type: 'password', name: 'repeat', required: '', minlength: '12', maxlength: '1024',
    autocomplete: 'new-password',
  });
  const error = errorNotice();
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('password.submit', language)]);

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      if (chosen.value !== repeated.value) {
        // The only rule checked in the browser, and it is not a password rule: it is a typing check the
        // server cannot make, because it is only ever sent one of the two.
        show(error, t('password.mismatch', language));
        repeated.focus();
        return;
      }
      submit.disabled = true;
      const next = chosen.value;
      try {
        await changeCuratorPassword(curator.held(), currentPassword.value, next);
        currentPassword.value = '';
        chosen.value = '';
        repeated.value = '';
        // The credential in hand is now the new one. Held, because the very next request has to carry it
        // and there is no token to carry instead.
        curator.passwordChanged(next);
        onChanged();
      } catch (failure) {
        show(error, detailOf(failure));
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: t('curator.eyebrow', language) }),
    h('h1', { text: t('password.title', language) }),
    h('p', { class: 'lede', text: t('password.lede', language) }),

    field(t('password.current', language), currentPassword, t('password.current_hint', language)),
    field(t('password.new', language), chosen, t('password.new_hint', language)),
    field(t('password.repeat', language), repeated),

    error,

    h('div', { class: 'actions' }, [
      submit,
      button(t('password.sign_out', language), { class: 'add', onClick: onSignOut }),
    ]),
  ]);

  container.append(form);
  currentPassword.focus();
}

// ---------------------------------------------------------------- the landing surface (S-12 / R-210)

/**
 * Everything the landing screen needs, read fresh.
 *
 * Two requests, both re-read on every draw: the worklist, and R-210's scope vocabulary. Neither is stored
 * — R-213 makes revocation immediate, and a worklist kept between draws would show a grant that has been
 * withdrawn. The vocabulary is not member data and is fetched with the worklist only so the screen has one
 * loading state rather than two.
 */
export async function load() {
  const [worklist, vocabulary] = await Promise.all([
    curatorMembers(curator.held()),
    grantableScopes(),
  ]);
  return { worklist, vocabulary };
}

/**
 * One member on the worklist.
 *
 * What is shown is exactly what the server composed from live grants: the member, the scopes granted, and
 * when the grant lapses. There is no link into the member's material from here and no id to type into one
 * — a curator reaches a member's positions through the grant, and the grant is the row above.
 */
function memberBlock(entry, { language, onExpired }) {
  const detail = h('div');
  const status = h('p', { class: 'report-meta' });

  const open = button(t('curator.open_consultation', language), {
    class: 'add',
    onClick: async () => {
      open.disabled = true;
      status.textContent = '';
      try {
        const record = await openWorkbenchSession(curator.held(), entry.member_id, OPENED_FROM);
        status.textContent = `${t('curator.consultation_opened', language)} ${record.id}`;
        announce(t('curator.consultation_opened', language));
        // Then the workbench itself, which is where R-210 becomes visible: what the member shared, and
        // what they did not, named rather than absent.
        clear(detail);
        const workbench = await curatorWorkbench(curator.held(), entry.member_id);
        detail.append(
          h('p', { class: 'report-sentence' }, [
            h('span', { class: 'report-quote-label', text: t('curator.granted', language) }),
            scopeList(workbench.granted_scope, language),
          ]),
          h('p', { class: 'report-sentence' }, [
            h('span', { class: 'report-quote-label', text: t('curator.withheld', language) }),
            scopeList(workbench.not_granted, language),
          ]),
          // The material itself. `sections` was in this payload from the day the route existed and was
          // read by nothing — see the block above `sectionsNode`.
          sectionsNode(workbench, language),
          // R-211's other half, and the reason `outcome` was NULL on every session ever opened.
          consultationNode(record.id, entry.member_id, { language, onExpired }),
        );
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 401) return onExpired();
        clear(detail);
        // A 403 here is R-210 working, not a fault: the member revoked between the worklist and this
        // request. Shown as the server wrote it, with the reason, for the same purpose the 403 has —
        // the curator, the member and the log all see the same "no".
        detail.append(
          h('div', { class: 'notice error', role: 'alert' }, [
            h('p', { text: t('curator.refused', language), style: 'margin:0' }),
            h('p', { class: 'lbl', text: detailOf(failure), style: 'margin:8px 0 0' }),
          ]),
        );
      } finally {
        open.disabled = false;
      }
      return null;
    },
  });

  return h('div', { class: 'report-block' }, [
    h('p', { class: 'report-heading' }, [
      h('span', { class: 'report-status', text: t('curator.member', language) }),
      entry.member_id,
    ]),
    h('div', { class: 'report-facts' }, [
      h('div', { class: 'report-fact' }, [
        h('p', { class: 'report-sentence' }, [
          h('span', { class: 'report-quote-label', text: t('curator.scope', language) }),
          scopeList(entry.scope, language),
        ]),
        h('p', {
          class: 'report-meta',
          text: `${t('curator.expires', language)} ${clockTime(entry.expires_at, language)}`,
        }),
      ]),
      detail,
    ]),
    h('div', { class: 'actions', style: 'margin-top:var(--sp-md)' }, [open]),
    // C-10, stated before the button is pressed rather than reported after it.
    h('p', { class: 'field-hint', text: t('curator.audit_note', language) }),
    status,
  ]);
}

/**
 * The landing screen. Who is signed in, what A40 costs them, how a grant works, and the worklist.
 *
 * The order is deliberate. The two sentences about the token and about the grant model come **before** the
 * list, because both of them are the reason the list is usually short: a curator arriving here for the
 * first time will find nobody on it, and the two explanations are what turn that from a broken screen into
 * a correct one.
 */
export function renderWorkbench(container, payload, { language, onSignOut, onReload, onExpired }) {
  clear(container);

  const who = curator.identity();
  const entries = (payload.worklist && payload.worklist.members) || [];

  container.append(
    h('span', { class: 'lbl', text: t('curator.workbench_eyebrow', language) }),
    h('h1', { text: t('curator.workbench_title', language) }),
    h('p', { class: 'lede', text: t('curator.workbench_lede', language) }),

    h('div', { class: 'report' }, [
      h('div', { class: 'report-block' }, [
        h('p', { class: 'report-heading' }, [
          h('span', { class: 'report-status', text: t('curator.identity', language) }),
          who ? who.display_name : '',
        ]),
        h('p', {
          class: 'report-meta',
          text: `${t('curator.role', language)}: ${
            (who && who.role_label) || t('curator.no_role', language)
          }`,
        }),
        // A40's interim, told to the person who pays for it.
        h('p', { class: 'field-hint', text: t('curator.no_token', language) }),
      ]),

      // R-210 and R-213 in one paragraph, before the list rather than as a footnote under it.
      h('div', { class: 'notice' }, [
        h('p', { text: t('curator.grant_model', language), style: 'margin:0' }),
        h('p', {
          class: 'lbl',
          text: (payload.vocabulary && scopeList(payload.vocabulary.grantable, language)) || '',
          style: 'margin:8px 0 0',
        }),
      ]),
    ]),
  );

  const list = h('div', { class: 'report' });
  if (entries.length === 0) {
    // Not an empty table and not a search box. The sentence says nobody has granted anything and that
    // there is no way past that from here, which is R-210 stated rather than implied by an absence.
    list.append(h('div', { class: 'notice' }, [
      h('p', { text: t('curator.nothing_granted', language), style: 'margin:0' }),
    ]));
  } else {
    for (const entry of entries) {
      list.append(memberBlock(entry, { language, onExpired }));
    }
  }
  container.append(list);

  container.append(
    h('div', { class: 'known' }, [
      h('div', { class: 'actions' }, [
        button(t('curator.reload', language), { class: 'add', onClick: onReload }),
        button(t('curator.sign_out', language), { class: 'add', onClick: onSignOut }),
      ]),
    ]),
  );

  announce(
    entries.length === 0
      ? t('curator.nothing_granted', language)
      : t('curator.workbench_lede', language),
  );
}
