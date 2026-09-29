// A11: the login screen, the registration screen, and the forced password change.
//
// **Three states of one surface, not three screens**, because they are one moment for the member: getting
// in. The registration form is reached from the login form and returns to it — it does not log anybody in,
// because `POST /api/members` deliberately mints no token and `POST /api/session` is the only route that
// does. So a new member fills the form and then logs in with what they just chose, which also tells them
// immediately whether they typed the password they think they typed.
//
// **The refusal is the server's, shown as it was written.** A wrong address and a wrong password are one
// message on purpose (C-05: eigentliCH is sole controller of who is a member, and that is not given away at
// a login prompt). A client that translated the 401 into "we don't know that address" would rebuild the
// oracle the server refuses to be, so this surface never interprets it — it prints `detail`.
//
// **The forced change screen asks for the current password too.** That is the service's rule, and it is
// the rule that makes A53's demonstration passwords safe to write down: they are good for exactly one
// login, and the person choosing the new one is expected to know the old one. A screen that waived it
// would turn a stolen token into a password change.
//
// A51: no new colours and no new controls. `.position-form`, `.field`, `.primary`, `.add` and `.notice`
// are the ones every other surface uses.

import { button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import {
  ApiError,
  changePassword,
  createMember,
  detailText,
  getConsentStatement,
  openSession,
} from '../app/api.js';
import * as session from '../app/session.js';

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

/**
 * `role="alert"` so a refusal that appears after submit is announced. A70 recorded its absence on
 * `.notice.error` as a known gap; a login form is the place it matters most, because the member has no
 * other way to learn that nothing happened.
 */
function errorNotice() {
  return h('div', { class: 'notice error', role: 'alert', hidden: '' });
}

function show(node, message) {
  node.textContent = message;
  node.removeAttribute('hidden');
}

// ---------------------------------------------------------------- log in

export function render(container, { language, onSignedIn, onRegister }) {
  clear(container);

  const email = h('input', {
    type: 'email',
    name: 'email',
    required: '',
    maxlength: '320',
    autocomplete: 'username',
    // Addresses are lowercased and trimmed on the server (`_normalise_email`); switching off the
    // phone keyboard's capitalisation just means the field shows the member what will be sent.
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
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('login.submit', language)]);

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      submit.disabled = true;
      try {
        const payload = await openSession(email.value, password.value);
        // The password leaves this function here and is not kept: the field is cleared before anything
        // else happens, and nothing wrote it anywhere else.
        password.value = '';
        onSignedIn(session.begin(payload));
      } catch (failure) {
        show(error, failure instanceof ApiError ? failure.detail || failure.message : String(failure));
        password.value = '';
        password.focus();
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: t('login.eyebrow', language) }),
    h('h1', { text: t('login.title', language) }),
    h('p', { class: 'lede', text: t('login.lede', language) }),

    field(t('login.email', language), email),
    field(t('login.password', language), password),

    error,

    h('div', { class: 'actions' }, [submit]),
  ]);

  container.append(form);

  container.append(
    h('div', { class: 'known' }, [
      h('span', { class: 'lbl', text: t('login.no_account', language) }),
      button(t('login.register', language), { class: 'add', onClick: onRegister }),
      h('p', { class: 'field-hint', text: t('login.forgotten', language) }),
      // ---- A40: the curator's door, and why it is a link rather than a second form ----
      //
      // Five people in the world need this and everybody else needs to read past it, so it is one
      // sentence and one quiet link at the bottom of the screen — not a second pair of credential fields
      // beside the member's. A second form here would put a choice in front of every member on their way
      // in, and would invite exactly the confusion the two credential tables exist to prevent: a member
      // typing their own address into the curator half and being refused by a form that looked like it
      // was for them.
      //
      // `.definition-toggle` is the client's existing quiet text-button treatment — the same weight as
      // "Was gehört hierher?" in a grid cell — so this introduces no colour, no control and no new
      // interactive selector. Rendered as an anchor because it is navigation and a curator should be able
      // to open it in a tab; `main.js` routes `#/kurator` before it asks whether there is a member
      // session, because a curator has no member session and never will.
      h('p', { class: 'field-hint' }, [
        `${t('curator.door_hint', language)} `,
        h('a', {
          href: '#/kurator',
          class: 'definition-toggle',
          style: 'text-decoration:none',
          text: t('curator.door', language),
        }),
      ]),
    ]),
  );

  email.focus();
}

// ---------------------------------------------------------------- register
//
// R-100 / NG-05 is stated before it is typed into, rather than accepted and refused afterwards. The
// server refuses regardless — that is what makes the floor real — but a form that lets someone enter a
// number it will reject, without saying so, wastes their time to prove a point.
//
// ===========================================================================================================
// R-103 / C-05: THE CONSENT CAPTURE POINT IS THIS FORM, AND FIVE THINGS ABOUT IT
// ===========================================================================================================
//
// **Until 31 August 2026 no consent had ever been captured.** `Consent` rows existed only in tests, so
// R-230's "history visible and withdrawable" returned an empty list for every real member and C-05's
// "sole data controller from the first intake question" had no artefact behind it (A90, A93).
// `POST /api/members` now **requires** `consents` with no default, and a registration without it is a 422
// with **no account created** — `verify_acceptance` runs while the transaction is still empty, which is
// what stops an incomplete acceptance leaving a member row and a credential behind.
//
// **The wording is the server's and is not re-authored here.** `GET /api/consent-statement` is open — it
// has to be, because the person reading it has no session and asking for one would put the consent form
// behind the thing the consent form makes possible. Every sentence a member reads in this section comes
// from that payload; this file contributes the heading, the boxes and the refusal.
//
// **The client echoes back the `document_version` it actually DISPLAYED, and that is the whole of R-103's
// versioning.** `echo_at_registration` is kept from the response that was rendered and sent back
// unchanged. A form left open across a wording change is therefore **refused** rather than silently
// stamped with the current version: `StaleConsentDocument` names both versions and says the acceptance is
// not an acceptance of the text that is published now. Stamping it server-side would have made the field
// decorative. Building the list at submit time from a *fresh* fetch would be the same defect wearing a
// client's clothes, so the payload is captured once, on load, and never re-read before submit.
//
// **Which purposes need a tick is read from the payload, never hard-coded — and that became load-bearing
// the same day.** `entscheidprotokoll` is now published as a **notice** rather than a consent: keeping the
// decision record belongs to the service, cannot be declined, and the entry cannot be removed afterwards,
// so a member is *told* instead of asked. `required_at_registration` is `["datenbearbeitung"]` alone, each
// purpose carries `kind`, and sending the notice in `POST /api/members` is a **422** rather than a silent
// drop. A form that had rendered two checkboxes and echoed two purposes would now refuse every
// registration. This one renders every purpose the statement carries, gives a checkbox only to the
// purposes named in `echo_at_registration`, and shows the rest as notices. The number two appears nowhere
// in this file.
//
// **The set of checkboxes is keyed off `echo_at_registration` rather than `required_at_registration`, and
// deliberately.** The two lists agree today, and `echo_at_registration` is the one that *is* the request
// body: a purpose gets a box exactly when its acceptance will be sent. Keying off the other list would be
// keying off a list that describes the request rather than one that constitutes it, which is the shape a
// divergence hides in.
//
// **A notice gets no control at all — not even an acknowledgement.** No checkbox, no "I have read this".
// Nothing records that a notice was displayed and that was decided rather than overlooked: an
// acknowledgement that writes no row would look like a choice the member does not have. The consequence
// text the server supplies says why it is not a choice, and that sentence is what the screen shows.
//
// **The form does not submit without the statement.** If the fetch failed there is nothing displayed to
// have agreed to, so the submit is refused with a sentence saying exactly that — agreement to text that
// was never shown would not be agreement — and a retry is offered.

/**
 * R-103. The consent section: the server's wording, a box for each required purpose, notices for the rest.
 *
 * Returns the node plus two functions the form uses: `accepted()` gives back the list to echo, or `null`
 * when something required is unticked; `ready()` says whether a statement was displayed at all.
 */
function consentSection(language, { onRetry }) {
  const region = h('div', { class: 'consent' });
  //: The payload that was DISPLAYED. Read at submit and never re-fetched — see the header above.
  let statement = null;
  //: `{purpose: checkbox}` for the required purposes only.
  const boxes = {};

  /**
   * One purpose. A checkbox when its acceptance is going to be sent, and otherwise nothing to press.
   *
   * `asked` is membership in `echo_at_registration` — see the header. `kind` decides the wording only: it
   * is what makes the consequence paragraph read "what withdrawing would mean" for a consent and "why this
   * is not a choice" for a notice, over the same payload field.
   */
  function purposeNode(purpose, asked) {
    const isNotice = purpose.kind === 'notice';
    const box = asked
      ? h('input', { type: 'checkbox', name: `consent_${purpose.purpose}`, class: 'consent-box' })
      : null;
    if (box) boxes[purpose.purpose] = box;

    return h('div', {
      class: 'cell consent-purpose',
      'data-kind': purpose.kind || 'consent',
      'data-asked': String(asked),
    }, [
      // Stated in words as well as in the attribute, so "this one is not asking you anything" is not a
      // fact carried only by the absence of a control (1.4.1, and plain readability).
      isNotice ? h('span', { class: 'lbl', text: t('consent.notice_kind', language) }) : null,
      // The server's own text, rendered as it was written. K0 authored wording, not a member's words, so
      // it is a paragraph rather than a quotation.
      h('p', { class: 'consent-statement', text: purpose.statement }),
      h('p', {
        class: 'report-meta',
        text: `${t('consent.version', language)}: ${purpose.document_version}`,
      }),
      // **`consequence`, and it used to be `withdrawal`.** One field for both kinds, so the label is
      // chosen by `kind` rather than the field being read twice. R-230's second half comes *before* the
      // agreement rather than after it: a member is entitled to know what withdrawing would mean before
      // they agree, not only once they go looking for the control.
      purpose.consequence
        ? h('div', { class: 'field' }, [
            h('span', {
              class: 'field-label',
              text: t(isNotice ? 'consent.consequence_notice' : 'consent.consequence_consent', language),
            }),
            h('p', { class: 'cell-prompt', text: purpose.consequence }),
          ])
        : null,
      asked
        ? h('label', { class: 'field consent-agree' }, [
            box,
            h('span', { class: 'field-label', text: t('consent.agree', language) }),
            h('span', { class: 'field-hint', text: t('consent.required', language) }),
          ])
        : // A notice: nothing to tick, and **no acknowledgement either**. Nothing records that a notice was
          // displayed, deliberately — a control that writes no row would look like a choice the member does
          // not have. The sentence says what it is instead of offering something to press.
          h('p', { class: 'field-hint', text: t('consent.notice_only', language) }),
    ]);
  }

  async function fetchStatement() {
    clear(region);
    for (const key of Object.keys(boxes)) delete boxes[key];
    try {
      statement = await getConsentStatement(language);
    } catch (failure) {
      statement = null;
      region.append(
        h('div', { class: 'notice error', role: 'alert' }, [
          h('p', { text: t('consent.unavailable', language), style: 'margin:0' }),
          h('p', { class: 'lbl', text: detailText(failure), style: 'margin:8px 0 0' }),
        ]),
        h('div', { class: 'actions' }, [
          button(t('consent.retry', language), { class: 'add', onClick: () => onRetry() }),
        ]),
      );
      return;
    }

    // The exact set whose acceptance will be sent. A `Set` of keys rather than a repeated `.some()`, so the
     // membership test and the body built at submit read the same list.
    const asked = new Set((statement.echo_at_registration || []).map((entry) => entry.purpose));

    region.append(
      h('h2', { text: t('consent.heading', language) }),
      h('p', { class: 'field-hint', text: t('consent.lede', language) }),
      // D-03's arrangement applied to wording nobody qualified has reviewed. Rendered rather than hidden,
      // from the payload's own flag: these are honest descriptions of what eigentliCH does and they are not
      // a data-protection notice.
      statement.wording_is_provisional
        ? h('p', { class: 'provisional', text: t('consent.provisional', language) })
        : null,
      // Said once at the top as well as on each notice, and only when there is one: a member reading a
      // list of boxes should be told before they start that not every item is asking them something.
      statement.notices_are_not_a_choice && (statement.notices || []).length
        ? h('p', { class: 'field-hint', text: t('consent.notices_are_not_a_choice', language) })
        : null,
      ...(statement.purposes || []).map((purpose) => purposeNode(purpose, asked.has(purpose.purpose))),
    );
  }

  return {
    node: region,
    load: fetchStatement,
    ready: () => statement !== null,
    /**
     * The list `POST /api/members` expects, or `null` when a box is unticked.
     *
     * **`echo_at_registration` verbatim**, and nothing else — not the purposes that were rendered, and not
     * anything this client assembled. That is what keeps a *notice* out of the body: sending
     * `entscheidprotokoll` is a 422 naming it as published-as-a-notice, and the only defence that does not
     * depend on remembering is that the list sent is the list the server handed over.
     *
     * The versions are the ones that came back with the wording that was rendered — not a fresh read, and
     * not this client's idea of what the current version is.
     */
    accepted: () => {
      if (!statement) return null;
      const echo = statement.echo_at_registration || [];
      for (const entry of echo) {
        const box = boxes[entry.purpose];
        if (!box || !box.checked) return null;
      }
      return echo;
    },
  };
}

export function renderRegistration(container, { language, onRegistered, onCancel }) {
  clear(container);

  const name = h('input', { type: 'text', name: 'display_name', required: '', maxlength: '200' });
  const age = h('input', { type: 'number', name: 'age', required: '', min: '18', max: '120', step: '1' });
  const email = h('input', {
    type: 'email', name: 'email', required: '', maxlength: '320',
    autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false',
  });
  const password = h('input', {
    type: 'password', name: 'password', required: '', minlength: '12', maxlength: '1024',
    autocomplete: 'new-password',
  });
  const error = errorNotice();
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('register.submit', language)]);

  // R-103. Reloaded through the same entry point the form was rendered by, so a retry after a failed fetch
  // is the ordinary path rather than a second one.
  const consent = consentSection(language, {
    onRetry: () => renderRegistration(container, { language, onRegistered, onCancel }),
  });

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      // Nothing was displayed, so there is nothing to have agreed to. Refused here rather than sent with
      // an empty list, which the server would refuse anyway — the difference is that this says why.
      if (!consent.ready()) {
        show(error, t('consent.unavailable', language));
        return;
      }
      const consents = consent.accepted();
      if (consents === null) {
        show(error, t('consent.missing', language));
        return;
      }

      submit.disabled = true;
      const address = email.value;
      const chosen = password.value;
      try {
        await createMember({
          email: address,
          password: chosen,
          display_name: name.value.trim(),
          age_at_registration: Number(age.value),
          // R-103 / C-05. Every required purpose, each with the `document_version` this form DISPLAYED.
          // A form left open across a wording change is refused rather than stamped.
          consents,
        });
        password.value = '';
        // Deliberately not logged in here. `POST /api/members` returns no token and this surface does not
        // ask for one: the member goes to the login form with the address prefilled and uses what they
        // just chose, which is also the moment a mistyped password becomes visible.
        onRegistered(address);
      } catch (failure) {
        // The server's refusal is shown as it was written: R-100's message names the floor and the stated
        // age, R-103's names the purposes still missing or the version that has moved on, and the password
        // rule names its length. All three are more use than "invalid input". `detailText` rather than
        // `detail` because pydantic's own 422 arrives as a list of objects, not a sentence.
        show(error, detailText(failure));
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: t('register.eyebrow', language) }),
    h('h1', { text: t('register.title', language) }),
    h('p', { class: 'lede', text: t('register.lede', language) }),

    field(t('register.name', language), name, t('register.name_hint', language)),
    field(t('register.age', language), age, t('register.age_hint', language)),
    field(t('register.email', language), email, t('register.email_hint', language)),
    field(t('register.password', language), password, t('register.password_hint', language)),

    // R-103's capture point, above the submit and below the account fields: it is the last thing read
    // before the account is asked for, which is the order the agreement actually happens in.
    consent.node,

    error,

    h('div', { class: 'actions' }, [
      submit,
      button(t('register.cancel', language), { class: 'add', onClick: onCancel }),
    ]),
  ]);

  container.append(form);
  name.focus();

  // Fetched after the form is on screen rather than before it, so a slow or failed statement leaves a
  // usable form with a refusal in it instead of a blank screen. The submit refuses while it is absent.
  return consent.load();
}

// ---------------------------------------------------------------- the forced change (A43, A53)

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
      try {
        await changePassword(currentPassword.value, chosen.value);
        currentPassword.value = '';
        chosen.value = '';
        repeated.value = '';
        onChanged();
      } catch (failure) {
        show(error, failure instanceof ApiError ? failure.detail || failure.message : String(failure));
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: t('password.eyebrow', language) }),
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
