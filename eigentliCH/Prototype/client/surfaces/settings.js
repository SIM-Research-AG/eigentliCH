// Settings — R-230's consent history, R-231's export, and R-231's erasure.
//
// **Three things that had a working server and no screen** (A90, A93). `GET /api/settings/consents` had
// returned an empty list for every real member since phase 0 because nothing ever wrote a `Consent` row;
// R-103's capture point exists now, so this is the first time it has anything to show. `erase_member` was
// complete, tested, and reachable only from tests. And the export the client actually called was the GET,
// which writes no Decision — so R-231's "both producing a Decision record" held only on the path nobody
// used.
//
// ===========================================================================================================
// THE FOUR DECISIONS IN THIS FILE
// ===========================================================================================================
//
// **The erasure is behind a door that has to be opened, and the door is not the destructive control.**
// Pressing `erasure.open` reveals the form; the form then needs the exact published sentence *and* the
// member's password. Nothing on the settings screen destroys anything in one press, and the sentence and
// the password are both checked in `services/erasure.py` rather than in the route — so this client is not
// the thing holding the line, it is the thing explaining it. What it must not do is make arriving there
// look ordinary.
//
// **The confirmation sentence is the server's, never composed here.** `confirmation_phrase` arrives from
// `GET /api/settings/erasure` in the language the server derived from `Member.locale`, and case is not
// folded. A client that built the sentence itself would be a client that could disagree with the thing
// doing the comparing, on the one route whose mistake cannot be corrected.
//
// **The erasure response is treated as a logout, because it is one.** The member's `sessions` rows are
// among those deleted, so the token is dead the moment the 200 arrives. The local session is ended
// *before* the receipt renders — otherwise the next click makes a request with a dead token and the member
// lands on the login screen with no explanation of what happened to the account they just deleted. The
// receipt is shown once and goes when they leave the page, which the copy says out loud.
//
// **Withdrawal marks, it does not delete.** `withdrawal_marks_rather_than_deletes` is true in the payload
// and the screen says so. There is deliberately no control that removes an entry from the history, and no
// "restore": R-230's question is "did they ever consent, and to what version", and an entry that could be
// taken out of the list would answer a different and easier one.
//
// **The withdraw control is gated on `withdrawable`, never on the absence of `withdrawn_at`.** Those came
// apart the day `entscheidprotokoll` became a **notice** rather than a consent. A member who registered
// before that has a standing `Consent` row for it, and the history now returns that row with
// `kind: "notice"`, `withdrawable: false`, `required_at_registration: false` — and `withdrawn_at: null`.
// A control derived from the timestamp would therefore appear beside it, offering to revoke a record R-040
// makes undeletable, next to a line saying the consent is not required. That reads as "optional, and you
// may take it back", which is false twice over. The route refuses it with a 422 either way; the button
// simply must not be there. Verified against a planted historical row on a throwaway database, because the
// development database holds none.
//
// **`consequence` is one field for two meanings, so the label follows `kind`.** It was `withdrawal` on the
// statement and `withdrawal_means` on the history, and both are now `consequence`. For a consent it says
// what withdrawing would mean; for a notice it says why there is nothing to withdraw. Reading it under one
// label would put "what withdrawing means" over a sentence explaining that nothing can be withdrawn.
//
// **The notices section is not a footnote, and it does not depend on a row.** `notices` arrives on the
// history payload as full records, so every member sees it whether or not they have ever consented to
// anything — which matters because the more surprising of the two facts is in there: a recorded decision
// cannot be altered or deleted by anyone, eigentliCH included, and survives an erasure emptied of name and
// text. It is rendered above the consent history for that reason.
//
// C-07: nothing here is counted. Not the consents, not what the export contains, not what the erasure
// removed — the receipt names tables and row figures because that is what an erasure *is*, and a count of
// deleted rows is a fact about an act rather than a tally of a member's progress. R-113 is about the
// latter.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import {
  detailText,
  getConsents,
  getDataClasses,
  getErasure,
  requestErasure,
  requestExport,
  withdrawConsent,
} from '../app/api.js';

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

/** A `31.08.2026 ` from an ISO timestamp. Date only: a consent is a day, not a moment. */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('T')[0].split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : parts.join('-');
}

/**
 * The name of one purpose, in the member's language, falling back to the key the server sent.
 *
 * **Driven off the payload's `purpose`, and the fallback is load-bearing.** The registry is closed on the
 * server and one of its entries is under discussion — `entscheidprotokoll` may become a notice rather than
 * a consent. A purpose this table has no name for renders as its key, which is readable and obviously
 * unfinished, rather than as an empty label.
 */
function purposeName(purpose, language) {
  const label = t(`consents.purpose_${purpose}`, language);
  return label === `consents.purpose_${purpose}` ? purpose : label;
}

// ---------------------------------------------------------------- R-230: the consent history

function consentNode(entry, language, { onChanged }) {
  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });

  // A door, not a bare button. The consequence is on screen before the control that causes it rather than
  // in a dialog afterwards, and the words are the **server's** `consequence` — never a sentence this
  // screen wrote about what a withdrawal does.
  //
  // **This comment used to assert that withdrawing a required consent means the account cannot continue.**
  // It does not, and an audit on 1 September 2026 measured every route to establish that: a withdrawal
  // writes `withdrawn_at`, answers 200, and nothing anywhere reads that column to gate anything. The owner
  // decided to keep the behaviour and correct the words. `required_at_registration` gates **registration**
  // and nothing after it, which is what `consents.required` now says, and the honest account of what a
  // withdrawal does is the server's to write because the server is what does or does not act on it.
  const confirm = h('div', { class: 'actions', hidden: '' });
  const opener = button(t('consents.withdraw', language), {
    class: 'add',
    'aria-expanded': 'false',
    onClick: (event) => {
      const opening = confirm.hasAttribute('hidden');
      if (opening) confirm.removeAttribute('hidden');
      else confirm.setAttribute('hidden', '');
      event.currentTarget.setAttribute('aria-expanded', String(opening));
    },
  });

  confirm.append(
    h('button', {
      type: 'button',
      class: 'primary',
      text: t('consents.withdraw_confirm', language),
      onClick: async (event) => {
        const control = event.currentTarget;
        control.disabled = true;
        error.setAttribute('hidden', '');
        try {
          await withdrawConsent(entry.id);
          // **After the re-render, not before it.** `onChanged` re-reads the history and `render` announces
          // the screen when it finishes, so announcing first put "the withdrawal is recorded" into `#live`
          // and then overwrote it — a member using a screen reader would hear the screen name and never
          // hear that their withdrawal had gone through. A86's defect, in a second place; found by driving
          // this screen in a real DOM rather than by reading it.
          await onChanged();
          announce(t('consents.withdrawn_announced', language));
        } catch (failure) {
          error.textContent = detailText(failure);
          error.removeAttribute('hidden');
          control.disabled = false;
        }
      },
    }),
    button(t('consents.withdraw_cancel', language), {
      class: 'add',
      onClick: () => {
        confirm.setAttribute('hidden', '');
        opener.setAttribute('aria-expanded', 'false');
      },
    }),
  );

  const isNotice = entry.kind === 'notice';

  return h('div', { class: 'cell consent-entry', 'data-kind': entry.kind || 'consent' }, [
    h('div', { class: 'position-label', text: purposeName(entry.purpose, language) }),
    // R-103. Which wording was agreed to — the reason a boolean would have been useless in this table.
    h('div', {
      class: 'position-meta',
      text: `${t('consent.version', language)}: ${entry.document_version}`,
    }),
    h('div', {
      class: 'position-meta',
      text: `${t('consents.granted_at', language)}: ${readableDate(entry.granted_at, language)}`,
    }),
    // A withdrawn consent stays in the list and says when. `withdrawable` is the server's fact, so this
    // screen does not derive it from the timestamp.
    entry.withdrawn_at
      ? h('div', { class: 'position-meta consent-withdrawn' }, [
          h('span', { text: `${t('consents.withdrawn', language)} ` }),
          h('span', {
            text: `${t('consents.withdrawn_at', language)}: ${readableDate(entry.withdrawn_at, language)}`,
          }),
        ])
      : h('div', { class: 'position-meta', text: t('consents.standing', language) }),

    entry.required_at_registration
      ? h('p', { class: 'field-hint', text: t('consents.required', language) })
      : null,

    // A row from before this purpose became a notice. Said in words, because the only other thing marking
    // it would be the *absence* of the withdraw control — and an absence explains nothing.
    isNotice
      ? h('p', { class: 'field-hint', text: t('consents.notice_row', language) })
      : null,

    // R-230's second half made worth something: what follows a withdrawal — or, for a notice, why nothing
    // does. One field, `consequence`, and the label follows `kind`. `null` for a purpose no longer in the
    // registry at all: a retired purpose has no current consequence to state, and inventing one would be
    // worse than saying nothing.
    entry.consequence
      ? h('div', { class: 'field' }, [
          h('span', {
            class: 'field-label',
            text: t(isNotice ? 'consents.consequence_notice' : 'consents.consequence_consent', language),
          }),
          h('p', { class: 'cell-prompt', text: entry.consequence }),
        ])
      : h('p', { class: 'field-hint', text: t('consents.retired_purpose', language) }),

    // **`withdrawable`, not `!withdrawn_at`** — see the module header. The two came apart the day the
    // decision record became a notice, and the timestamp version would put a revoke button beside a record
    // that cannot be revoked.
    entry.withdrawable ? opener : null,
    entry.withdrawable ? confirm : null,
    error,
  ]);
}

/**
 * What a member is told rather than asked. Above the history, and independent of any recorded row.
 *
 * `notices` arrives as full records — purpose, kind, version, statement, consequence — so this section
 * renders the wording itself rather than a key. There is **no control anywhere in here**: no checkbox, no
 * acknowledgement, no withdraw. A notice is not a choice, and nothing records that it was displayed.
 */
function noticesSection(payload, language) {
  const notices = payload.notices || [];
  if (!notices.length) return null;

  return h('section', { class: 'known notices', 'aria-labelledby': 'notices-heading' }, [
    h('h2', { id: 'notices-heading', text: t('notices.heading', language) }),
    payload.notices_are_not_a_choice
      ? h('p', { class: 'lede', text: t('notices.lede', language) })
      : null,
    // **`notice-entry`, not `consent-entry`.** They looked interchangeable and are not: a notice in this
    // section is a published statement that belongs to every member, while a `consent-entry` is a row in
    // *this* member's history. Sharing the class made "does this member have a historical consent to the
    // decision record" unanswerable from the DOM — a harness check for it matched the notices section
    // instead and passed for the wrong reason.
    ...notices.map((notice) => h('div', {
      class: 'cell notice-entry',
      'data-kind': 'notice',
    }, [
      h('span', { class: 'lbl', text: t('notices.kind', language) }),
      h('div', { class: 'position-label', text: purposeName(notice.purpose, language) }),
      // The server's own wording, unchanged. K0 authored text.
      h('p', { class: 'consent-statement', text: notice.statement }),
      h('p', {
        class: 'position-meta',
        text: `${t('consent.version', language)}: ${notice.document_version}`,
      }),
      notice.consequence
        ? h('div', { class: 'field' }, [
            h('span', { class: 'field-label', text: t('notices.consequence', language) }),
            h('p', { class: 'cell-prompt', text: notice.consequence }),
          ])
        : null,
    ])),
  ]);
}

function consentsSection(payload, language, { onChanged }) {
  const entries = payload.consents || [];
  return h('div', { class: 'known' }, [
    h('h2', { text: t('consents.heading', language) }),
    h('p', { class: 'lede', text: t('consents.lede', language) }),
    // Said out loud so no client author reaches for "remove from list". The payload asserts it too.
    payload.withdrawal_marks_rather_than_deletes
      ? h('p', { class: 'field-hint', text: t('consents.marks_not_deletes', language) })
      : null,
    ...entries.map((entry) => consentNode(entry, language, { onChanged })),
  ]);
}

// ---------------------------------------------------------------- R-231: the export, as a POST

/**
 * The export control. **A POST, and the whole point is the method** — see `api.js::requestExport`.
 *
 * The file is `payload.export` and the Decision that records the request is `payload.decision_id`, shown
 * beside it: the member asked for their data and that is now in their own record, which is the half the
 * GET could not do without turning a prefetch into a permanent row.
 */
function exportSection(language) {
  const region = h('div', { class: 'field' });

  const trigger = button(t('settings.export', language), {
    class: 'add',
    onClick: async (event) => {
      const control = event.currentTarget;
      control.disabled = true;
      clear(region);
      region.append(h('p', { class: 'field-hint', text: t('settings.export_working', language) }));
      try {
        const payload = await requestExport();
        clear(region);
        // Handed to the browser as a file the member keeps. No mail step, no share link, no third party —
        // C-05 means the bytes never leave this machine on their way to their owner.
        const blob = new Blob([JSON.stringify(payload.export, null, 2)], { type: 'application/json' });
        const href = URL.createObjectURL(blob);
        const link = h('a', {
          href,
          download: `eigentlich-export-${payload.member_id}.json`,
          class: 'add',
          style: 'text-decoration:none',
          text: `eigentlich-export-${payload.member_id}.json`,
        });
        region.append(
          h('p', { class: 'field-hint', text: t('settings.export_ready', language) }),
          link,
          // R-231's record, named. The member can go and read it on S-07.
          h('p', {
            class: 'report-meta',
            text: `${t('settings.export_decision', language)}: ${payload.decision_id}`,
          }),
        );
        // Offered as a click and taken as one: the link stays visible, so a browser that blocks the
        // programmatic download leaves the member something to press rather than nothing.
        link.click();
      } catch (failure) {
        clear(region);
        region.append(
          h('div', { class: 'notice error', role: 'alert' }, [
            h('p', { text: detailText(failure), style: 'margin:0' }),
          ]),
        );
      } finally {
        control.disabled = false;
      }
    },
  });

  return h('div', { class: 'known' }, [
    h('h2', { text: t('settings.export_heading', language) }),
    h('p', { class: 'field-hint', text: t('settings.export_hint', language) }),
    trigger,
    region,
  ]);
}

// ---------------------------------------------------------------- R-231: the erasure

/**
 * The receipt. Rendered after the local session has already been ended.
 *
 * `ErasureReport.as_dict()` names what was deleted and what was redacted, per table. The member is handed
 * the act rather than a reassurance — which is what that report was written for — and this screen does not
 * summarise it into one sentence, because "your data has been deleted" is the sentence that would let the
 * two surviving tables go unmentioned.
 */
function erasureReceipt(container, report, language) {
  clear(container);

  const rows = (group) => Object.entries(group || {}).map(([table, count]) =>
    h('li', { text: `${table}: ${count} ${t('erasure.rows', language)}` }));

  container.append(
    h('span', { class: 'lbl', text: t('settings.eyebrow', language) }),
    h('h1', { text: t('erasure.done_heading', language) }),
    h('p', { class: 'lede', text: t('erasure.done_lede', language) }),
    h('div', { class: 'known' }, [
      h('h2', { text: t('erasure.done_deleted', language) }),
      h('ul', {}, rows(report.deleted)),
      h('h2', { text: t('erasure.done_redacted', language) }),
      // R-231's honest half: these rows remain, emptied of name and text, and cannot be removed at the
      // storage layer by anybody.
      h('p', { class: 'field-hint', text: t('erasure.what_stays', language) }),
      h('ul', {}, rows(report.redacted)),
      report.decision_id
        ? h('p', {
            class: 'report-meta',
            text: `${t('erasure.done_decision', language)}: ${report.decision_id}`,
          })
        : null,
    ]),
  );

  announce(t('erasure.done_announced', language));
}

/**
 * The destructive form, behind a door.
 *
 * Both required inputs are on screen with what they are for. The sentence is compared on the server, case
 * not folded, so this form does not pre-check it against a copy: the only client-side check is that the
 * fields are not empty, which is a typing check rather than a rule.
 */
function erasureSection(container, erasure, language, { onErased }) {
  const phrase = h('input', {
    type: 'text',
    name: 'confirmation',
    maxlength: '200',
    autocomplete: 'off',
    autocapitalize: 'none',
    spellcheck: 'false',
    // No `required` and no `pattern`: the comparison is the server's, and a browser-side pattern built
    // from the same sentence would be a second copy of the one string that must not have two.
  });
  const password = h('input', {
    type: 'password', name: 'password', maxlength: '1024', autocomplete: 'current-password',
  });
  const reason = h('textarea', { name: 'reason', rows: '2', maxlength: '2000' });
  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const submit = h('button', { type: 'submit', class: 'primary erasure-submit' }, [
    t('erasure.submit', language),
  ]);

  const form = h('form', {
    class: 'position-form erasure-form',
    hidden: '',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      if (!phrase.value.trim()) {
        error.textContent = t('erasure.phrase_missing', language);
        error.removeAttribute('hidden');
        phrase.focus();
        return;
      }
      if (!password.value) {
        error.textContent = t('erasure.password_missing', language);
        error.removeAttribute('hidden');
        password.focus();
        return;
      }
      submit.disabled = true;
      try {
        // **Sent exactly as typed.** Not trimmed, not upper-cased, not normalised: the server compares the
        // published sentence character for character and case is not folded, and a client that tidied the
        // input would be deciding on the member's behalf that they meant to type the sentence.
        const report = await requestErasure({
          confirmation: phrase.value,
          password: password.value,
          reason: reason.value.trim() || null,
        });
        password.value = '';
        // **The token is dead. Ended locally before anything renders**, so the next interaction cannot make
        // a request with it and land the member on a login screen with no account and no explanation.
        onErased();
        erasureReceipt(container, report, language);
      } catch (failure) {
        // 422 for a sentence that is not the published one, 403 for a wrong password — and the record is
        // intact either way. The server's own sentence says which, and it names the published phrases.
        password.value = '';
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        submit.disabled = false;
      }
    },
  }, [
    h('h3', { text: t('erasure.title', language) }),
    h('p', { class: 'erasure-irreversible', text: t('erasure.irreversible', language) }),
    h('p', { class: 'cell-prompt', text: t('erasure.what_goes', language) }),

    // What survives, said plainly and before the fields rather than in the receipt afterwards. The payload
    // asserts it too, so the sentence is rendered from the server's own flag.
    erasure.append_only_rows_are_emptied_not_removed
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('erasure.what_stays_heading', language) }),
          h('p', { class: 'cell-prompt', text: t('erasure.what_stays', language) }),
        ])
      : null,

    field(
      t('erasure.phrase_label', language),
      phrase,
      t('erasure.phrase_hint', language),
    ),
    // The sentence itself, rendered from the payload so there is exactly one place it is written down.
    h('p', { class: 'erasure-phrase', text: erasure.confirmation_phrase }),

    erasure.requires_password
      ? field(t('erasure.password_label', language), password, t('erasure.password_hint', language))
      : null,
    field(t('erasure.reason_label', language), reason, t('erasure.reason_hint', language)),

    error,
    h('div', { class: 'actions' }, [submit]),
  ]);

  const opener = button(t('erasure.open', language), {
    class: 'add erasure-open',
    'aria-expanded': 'false',
    onClick: (event) => {
      const opening = form.hasAttribute('hidden');
      if (opening) form.removeAttribute('hidden');
      else form.setAttribute('hidden', '');
      event.currentTarget.textContent = opening
        ? t('erasure.close', language)
        : t('erasure.open', language);
      event.currentTarget.setAttribute('aria-expanded', String(opening));
      if (opening) phrase.focus();
    },
  });

  // Last on the screen, in its own region, with a heading that says what it is before the control appears.
  // Nobody should arrive here on the way to something else.
  return h('section', { class: 'known erasure', 'aria-labelledby': 'erasure-heading' }, [
    h('h2', { id: 'erasure-heading', text: t('erasure.heading', language) }),
    h('p', { class: 'field-hint', text: t('erasure.hint', language) }),
    opener,
    form,
  ]);
}

// ---------------------------------------------------------------- the screen

/**
 * A11: no member id in either call. Both are the token's member's.
 *
 * Two requests, and the erasure one is a plain read that writes nothing — `GET /api/settings/erasure` says
 * what the second step requires and is guarded like every other member route, because an unauthenticated
 * route handing anybody the exact sentence that destroys an account is a route that exists to be pasted
 * into a phishing page.
 */
// ---------------------------------------------------------------- R-232: which class each category is in

/**
 * R-210 / R-213, as a door rather than as a section.
 *
 * **Why the link is here.** The consent history, the export and the erasure are all the member deciding
 * what happens to their own material, and so is a curator grant — A86's argument for putting the settings
 * door in the chrome applies to this the same way: a member looking for how to take a curator's access
 * away will not find it by opening the Plan door. It is a link rather than a section because the grant
 * screen is a screen — three payloads and two forms — and folding it in here would bury the one control on
 * it that has to be immediate.
 *
 * R-003: no count of open grants on the link. A door is a name.
 */
function grantsSection(language) {
  return h('section', { class: 'field' }, [
    h('h2', { text: t('settings.grants_heading', language) }),
    h('p', { class: 'field-hint', text: t('settings.grants_lede', language) }),
    h('div', { class: 'actions' }, [
      h('a', {
        href: '#/grants',
        class: 'add',
        style: 'text-decoration:none',
        text: t('grants.nav', language),
      }),
    ]),
  ]);
}

/**
 * R-232 — "a plain statement of which data class each stored category falls into".
 *
 * **This payload was shown to nobody.** `GET /api/settings/data-classes` derives the whole statement from
 * the model layer's own `__data_class__` and column overrides, so it cannot go stale, and no client code
 * called it — which made C-04's scheme a thing the code knew and the member could not read.
 *
 * **Plain, so it is not behind a disclosure.** R-232's word is *plain statement*; a `<details>` would make
 * it available rather than stated, and this is the one screen where a member is deciding what to export
 * and what to delete. It is long — one line per stored category — and that is what a complete answer looks
 * like.
 *
 * **The words for what K0 to K3 mean come from `i18n.js` and the assignment comes from the server.** The
 * service says so in its own docstring: "the sentence explaining what K2 means to a member is interface
 * copy". So a class the server names and this table has no sentence for renders as its name — visible and
 * obviously unfinished — rather than as a blank.
 *
 * **C-04's headline is rendered from the payload's flag**, not asserted here: the top class never leaves
 * the server, which is why an export of a K3 category is the member's own copy and nobody else's.
 */
function dataClassesSection(statement, language) {
  if (!statement) return null;
  const scheme = statement.scheme || [];

  const meaning = (name) => {
    const key = `settings.class_${name.toLowerCase()}`;
    const sentence = t(key, language);
    return sentence === key ? null : sentence;
  };

  return h('section', { class: 'data-classes' }, [
    h('h2', { text: t('settings.classes_heading', language) }),
    h('p', { class: 'field-hint', text: t('settings.classes_lede', language) }),

    // The scheme itself, in the order the server lists it — K0 to K3 is an ordered scale on the server
    // (`DataClass` is an IntEnum so that "at or above" is a comparison), and reordering it here would
    // break the one thing about it that is a fact rather than a label.
    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('settings.classes_scheme', language) }),
      h('ul', {}, scheme.map((name) => h('li', {}, [
        h('span', { class: 'field-label', text: name }),
        meaning(name) ? h('span', { class: 'field-hint', text: meaning(name) }) : null,
      ]))),
    ]),

    statement.top_class_never_leaves_the_server
      ? h('p', {
          class: 'field-hint',
          text: t('settings.classes_top_stays', language).replace('{class}', String(statement.top_class)),
        })
      : null,

    // One line per stored category. `holds_member_material` and `leaves_the_server` are the two facts a
    // member is actually asking about, so they are words rather than flags.
    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('settings.classes_categories', language) }),
      h('ul', {}, (statement.categories || []).map((entry) => h('li', {}, [
        h('span', { class: 'field-label', text: `${entry.category} — ${entry.data_class}` }),
        h('span', {
          class: 'field-hint',
          text: [
            entry.holds_member_material
              ? t('settings.classes_yours', language)
              : t('settings.classes_not_yours', language),
            entry.leaves_the_server
              ? t('settings.classes_can_leave', language)
              : t('settings.classes_stays', language),
          ].join(' '),
        }),
        // C-04's second level: a column may classify itself above the row it sits in, and the payload
        // reports it because "which class does this category fall into" has a second answer where one does.
        Object.keys(entry.fields_classified_above_the_row || {}).length
          ? h('span', {
              class: 'field-hint',
              text: `${t('settings.classes_field_above', language)}: `
                + Object.entries(entry.fields_classified_above_the_row)
                  .map(([name, klass]) => `${name} (${klass})`).join(', '),
            })
          : null,
      ]))),
    ]),

    // Said because it is the question a reader asks of a list of tables that has no join tables in it.
    statement.link_tables_carry_no_class_of_their_own
      ? h('p', { class: 'field-hint', text: t('settings.classes_link_tables', language) })
      : null,
    h('p', { class: 'field-hint', text: t('settings.classes_derived', language) }),
  ]);
}

export async function load() {
  const [consents, erasure, dataClasses] = await Promise.all([
    getConsents(),
    getErasure(),
    // Open on the server: a statement about the schema, not about a member. Fetched with the rest so the
    // screen is one snapshot, and allowed to fail on its own — a member who came here to withdraw a consent
    // must not lose that screen because a statement about table names could not be read.
    getDataClasses().catch(() => null),
  ]);
  return { consents, erasure, dataClasses };
}

export function render(container, payload, { language, onChanged, onErased }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('settings.eyebrow', language) }),
    h('h1', { text: t('settings.title', language) }),
    h('p', { class: 'lede', text: t('settings.lede', language) }),
  );

  // Notices first: every member has them, they depend on no recorded row, and the fact that a decision
  // record cannot be deleted even by eigentliCH is not a footnote.
  const notices = noticesSection(payload.consents, language);
  if (notices) container.append(notices);

  container.append(consentsSection(payload.consents, language, { onChanged }));
  // R-210 / R-213's door, above the export and the erasure: taking a curator's access away is the
  // reversible one of the three, and the one a member is most likely to have come here for.
  container.append(grantsSection(language));
  container.append(exportSection(language));
  container.append(erasureSection(container, payload.erasure, language, { onErased }));
  // R-232, last: it is the reference the three sections above are about, and it is the longest thing on
  // the screen. A member who came to withdraw a consent should not have to scroll past a table of every
  // stored category to reach the control.
  const classes = dataClassesSection(payload.dataClasses, language);
  if (classes) container.append(classes);

  announce(t('settings.title', language));
}
