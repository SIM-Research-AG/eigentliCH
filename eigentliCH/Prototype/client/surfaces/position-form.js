// S-03 — add a position. Reached from any cell in one action (R-112).
//
// **What this form asks for and what it refuses to.**
//
//   R-120  role, capital type, label, magnitude with an EXPLICIT unit, and the five correlation tags
//   R-121  human-capital positions capture a time basis; financial ones do not
//   D-02   the tags are stored and never interpreted — free text, optional (A29)
//   R-020  a position with only a label is valid, so nothing but the label is required
//   C-09   the member states the decision; the server writes it in the same transaction
//
// **Magnitude is optional and its unit is never inferred** (A30). An MBA being taken is a Growth position
// in human capital with a time basis and no franc figure, and forcing one would mean either inventing a
// number or refusing a real position.
//
// **The unit selector used to appear only once an amount was typed, and that was the defect.** It read as
// keeping the two in step, and it hid the one thing the member needed while they were deciding what to
// type: whether a Betrag here means a year or a month. It is on screen from the start now, with nothing
// preselected, and an amount without a unit is refused rather than defaulted. See the block that builds it.

import { button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import {
  createPosition,
  deactivatePosition,
  detailText,
  reactivatePosition,
  revisePosition,
} from '../app/api.js';

//: D-02. Order matters only for the form; nothing downstream reads it.
const TAGS = ['client_type', 'skill', 'reputation_basis', 'sector', 'time_basis'];

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

export function render(container, { cell, language, onSaved, onCancel }) {
  clear(container);

  const isHuman = cell.capital_type === 'human';

  const label = h('input', { type: 'text', name: 'label', required: '', maxlength: '200' });
  const description = h('textarea', { name: 'description', rows: '2' });
  const magnitude = h('input', { type: 'number', name: 'magnitude', step: 'any', min: '0' });

  // **The unit is visible before anything is typed, and nothing is preselected.**
  //
  // The owner's report was "Wachstum menschliches Kapital -> Betrag in welcher Frequenz?" — they were
  // asked for a Betrag and the field did not say per what. It did not, for two reasons that were each
  // defensible and were wrong together: the selector was hidden until an amount existed (so the frequency
  // was invisible at exactly the moment it was being decided), and `chf_per_year` was the first option and
  // therefore preselected (so a member who never opened it had a unit chosen for them).
  //
  // R-120 says the unit is never inferred. A default IS an inference — the quietest kind, because nobody
  // sees it happen. So the placeholder is first and carries no value, the selector is on screen from the
  // start, and an amount without a unit is refused below rather than filled in. A member who typed a
  // monthly figure now reads "CHF pro Jahr" while they type it, and the hint says to convert.
  const unit = h('select', { name: 'magnitude_unit' }, [
    h('option', { value: '', text: t('form.unit_choose', language) }),
    h('option', { value: 'chf_per_year', text: t('unit.chf_per_year', language) }),
    h('option', { value: 'share_of_total', text: t('unit.share_of_total', language) }),
  ]);
  const unitField = field(t('form.unit', language), unit, t('form.unit_hint', language));

  const timeBasis = h('input', { type: 'text', name: 'time_basis', maxlength: '80' });

  const tagInputs = {};
  for (const name of TAGS) {
    // R-121: time_basis is asked as its own field for human capital, so it is not asked twice.
    if (name === 'time_basis' && isHuman) continue;
    tagInputs[name] = h('input', { type: 'text', name: `tag_${name}`, maxlength: '120' });
  }

  const question = h('input', { type: 'text', name: 'question', maxlength: '300' });
  const choice = h('input', { type: 'text', name: 'choice', maxlength: '300' });

  const error = h('div', { class: 'notice error', hidden: '' });

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      const amount = magnitude.value.trim();
      // R-120 at the point it would otherwise be broken. The model's CHECK constraint requires the pair to
      // be both-null or both-present, so the server refuses this too — but a member who has typed a figure
      // deserves to be asked here rather than shown a constraint name.
      if (amount && !unit.value) {
        error.textContent = t('form.unit_missing', language);
        error.removeAttribute('hidden');
        unit.focus();
        return;
      }
      const tags = {};
      for (const [name, input] of Object.entries(tagInputs)) {
        const value = input.value.trim();
        if (value) tags[name] = value;
      }
      if (isHuman && timeBasis.value.trim()) tags.time_basis = timeBasis.value.trim();

      const payload = {
        role: cell.role,
        capital_type: cell.capital_type,
        label: label.value.trim(),
        description: description.value.trim() || null,
        magnitude: amount ? Number(amount) : null,
        magnitude_unit: amount ? unit.value : null,
        time_basis: isHuman && timeBasis.value.trim() ? timeBasis.value.trim() : null,
        tags,
        // C-09. The member says what they decided; the server refuses the write without it.
        question: question.value.trim() || t('form.default_question', language, { role: cell.display }),
        choice: choice.value.trim() || label.value.trim(),
      };

      try {
        await createPosition(payload);
        onSaved();
      } catch (err) {
        // `detailText` rather than `err.detail`: a 422 from pydantic is a list of objects, not a sentence,
        // and rendering the field directly puts `[object Object]` in the notice.
        error.textContent = detailText(err);
        error.removeAttribute('hidden');
      }
    },
  }, [
    h('span', { class: 'lbl', text: `${cell.display} · ${t(`capital.${cell.capital_type}`, language)}` }),
    h('h1', { text: t('form.title', language) }),
    // The role's own definition, so the member is answering a question they can see the point of.
    cell.definition ? h('p', { class: 'lede', text: cell.definition }) : null,

    field(t('form.label', language), label, t('form.label_hint', language)),
    field(t('form.description', language), description),

    field(t('form.magnitude', language), magnitude, t('form.magnitude_hint', language)),
    unitField,

    isHuman ? field(t('form.time_basis', language), timeBasis, t('form.time_basis_hint', language)) : null,

    h('details', { class: 'tags' }, [
      h('summary', { text: t('form.tags', language) }),
      h('p', { class: 'field-hint', text: t('form.tags_hint', language) }),
      ...Object.entries(tagInputs).map(([name, input]) =>
        field(t(`tag.${name}`, language), input),
      ),
    ]),

    h('fieldset', { class: 'decision' }, [
      h('legend', { text: t('form.decision', language) }),
      h('p', { class: 'field-hint', text: t('form.decision_hint', language) }),
      field(t('form.question', language), question),
      field(t('form.choice', language), choice),
    ]),

    error,

    h('div', { class: 'actions' }, [
      h('button', { type: 'submit', class: 'primary' }, [t('form.save', language)]),
      button(t('form.cancel', language), { class: 'add', onClick: onCancel }),
    ]),
  ]);

  container.append(form);
  label.focus();
}

// ===========================================================================================================
// R-123's second half and R-122 — changing a position that already exists
// ===========================================================================================================
//
// **`Position.active` was honoured on six read paths and nothing anywhere could set it to `False`.**
// `services/grid.py` flags it, `services/befund.py` has a sentence for a cell holding only inactive
// material, `services/illustration.py` and `services/engine_inputs.py` skip it, `services/derive.py`
// filters on it, `services/goals.py` excludes it from a goal's funding — and this client rendered it.
// R-122 says a position may be marked inactive; no code could mark one, and §6's `PATCH
// /api/positions/:id` did not exist. A94 built all three routes and nothing rendered them.
//
// **Three controls, and the split between them is the argument.** The edit form corrects what a position
// *is*. Deactivating changes what the member's **live plan** is — the Befund stops counting the cell, the
// illustration stops projecting it, the derivations leave it out — which is a different statement, so it
// is a different act with its own Decision. `active` is refused **by name** on the PATCH
// (`extra="forbid"`), deliberately: a boolean in the middle of an edit form is how a member deactivates a
// position by accident. This client therefore has no checkbox for it anywhere, and the two status routes
// each say in words what changes before the control that causes it.
//
// **Only the fields the member actually changed are sent.** The server reads `model_fields_set` to tell
// "clear the description" from "leave the description alone", and posting the whole form back would make
// those indistinguishable and would wipe whatever was not retyped.
//
// **`liquidity` is shown, and A99 is what made that possible.** This comment used to say the opposite: it
// recorded that `GET /api/positions` did not carry the band, that the selector was therefore additive with
// nothing preselected, and that no value was sent unless a member picked one. A99 put `liquidity` into the
// grid payload — arguing the rule against `POSITION_REVISABLE_FIELDS` rather than against a list of names —
// and this form was left as it was. The consequence was that the band was **write-only**: a member could
// state one and could never afterwards see which one stood, and having stated one could never take it back,
// because "" meant "leave unchanged" and there was no way to say "not stated" at all.
//
// So the band is preselected from `position.liquidity`, and the empty option now *means* R-031's null —
// "nicht angegeben" — which is a value the member may choose again. That null is meaningful and not an
// absence: `services/goals.py` reports `liquidity_not_stated` about it under R-031, and a member who
// recorded a band by mistake has to be able to return to the state that report describes.

//: R-031's four bands, in the order `models/plan.py::LIQUIDITY` declares them. Never a number of years: a
//: threshold in years would be an assumption under C-02 and nobody has published one.
const LIQUIDITY = ['immediate', 'within_months', 'within_years', 'illiquid'];

/** C-09's fieldset, shared by the edit form and the two status forms. */
function decisionFieldset(language, question, choice, reasoning) {
  return h('fieldset', { class: 'decision' }, [
    h('legend', { text: t('position.decision_heading', language) }),
    h('p', { class: 'field-hint', text: t('position.decision_hint', language) }),
    field(t('form.question', language), question),
    field(t('form.choice', language), choice),
    field(t('decisions.correct_reasoning', language), reasoning),
  ]);
}

/**
 * R-123. Change a position that already exists.
 *
 * `position` is the record from the grid payload. Every field starts at its current value so a member can
 * see what stands, and **only what actually differs is sent** — compared against the value that was
 * rendered, not against an empty form.
 */
export function renderEdit(container, { position, cell, language, onSaved, onCancel }) {
  clear(container);

  const isHuman = cell.capital_type === 'human';

  const label = h('input', {
    type: 'text', name: 'label', required: '', maxlength: '200', value: position.label || '',
  });
  const description = h('textarea', { name: 'description', rows: '2' });
  description.value = position.description || '';
  const magnitude = h('input', {
    type: 'number', name: 'magnitude', step: 'any', min: '0',
    value: position.magnitude === null || position.magnitude === undefined ? '' : String(position.magnitude),
  });
  // **The current unit is marked with the `selected` attribute rather than by assigning `select.value`.**
  // Both work in a browser; only one works without one. Found by driving this form in a real DOM: the
  // property assignment threw outright there, and a property assignment is in any case a second statement
  // that can fall out of step with the options it refers to — a `magnitude_unit` the list does not offer
  // would silently select nothing rather than being visibly absent.
  const unitOption = (value, label) => h('option', {
    value,
    text: label,
    selected: (position.magnitude_unit || '') === value ? '' : null,
  });
  const unit = h('select', { name: 'magnitude_unit' }, [
    unitOption('', t('form.unit_choose', language)),
    unitOption('chf_per_year', t('unit.chf_per_year', language)),
    unitOption('share_of_total', t('unit.share_of_total', language)),
  ]);
  const timeBasis = h('input', {
    type: 'text', name: 'time_basis', maxlength: '80', value: position.time_basis || '',
  });
  // The band that stands, marked with the `selected` attribute rather than by assigning `select.value` —
  // the same lesson the unit selector above records, learned in a real DOM. The empty option is R-031's
  // null and is preselected when the member has not stated a band.
  const bandOption = (value, text) => h('option', {
    value,
    text,
    selected: (position.liquidity || '') === value ? '' : null,
  });
  const liquidity = h('select', { name: 'liquidity' }, [
    bandOption('', t('position.liquidity_choose', language)),
    ...LIQUIDITY.map((band) => bandOption(band, t(`position.liquidity_${band}`, language))),
  ]);

  const question = h('input', {
    type: 'text', name: 'question', maxlength: '300',
    value: t('position.edit_title', language),
  });
  const choice = h('input', { type: 'text', name: 'choice', maxlength: '300' });
  const reasoning = h('textarea', { name: 'reasoning', rows: '2' });

  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const submit = h('button', { type: 'submit', class: 'primary' }, [
    t('position.edit_save', language),
  ]);

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      const amount = magnitude.value.trim();
      // R-120, at the point it would otherwise be broken. The service refuses the pair too; asking here
      // means a member who has typed a figure is asked rather than shown a constraint name.
      if (amount && !unit.value) {
        error.textContent = t('form.unit_missing', language);
        error.removeAttribute('hidden');
        unit.focus();
        return;
      }

      // **Only what differs.** `null` is a value and not an absence on this route, so a field the member
      // emptied is sent as `null` — that is how "clear the description" reaches the server at all — while a
      // field they did not touch is absent from the body entirely.
      const changes = {};
      const stateIfChanged = (name, next, before) => {
        if (next !== before) changes[name] = next;
      };
      stateIfChanged('label', label.value.trim(), position.label || '');
      stateIfChanged('description', description.value.trim() || null, position.description ?? null);
      stateIfChanged(
        'magnitude',
        amount ? Number(amount) : null,
        position.magnitude === undefined ? null : position.magnitude,
      );
      stateIfChanged('magnitude_unit', amount ? unit.value : null, position.magnitude_unit ?? null);
      if (isHuman) {
        stateIfChanged('time_basis', timeBasis.value.trim() || null, position.time_basis ?? null);
      }
      // Through the same comparison as every other field now that the current band is on screen. It was
      // the one exception — `test_client_s07_settings_capabilities.py` named it and permitted it — and the
      // exception went with the defect: an additive field cannot express "clear this", and R-031's null is
      // a state a member has to be able to return to.
      stateIfChanged('liquidity', liquidity.value || null, position.liquidity ?? null);

      if (!Object.keys(changes).length) {
        // The server answers 422 for this in R-040's own terms and the sentence is worth reading, but a
        // member who changed nothing should not need a round trip to hear it.
        error.textContent = t('position.edit_unchanged', language);
        error.removeAttribute('hidden');
        return;
      }

      submit.disabled = true;
      try {
        await revisePosition(position.id, {
          ...changes,
          // C-09. The member states what they decided; the server refuses the write without it.
          question: question.value.trim() || t('position.edit_title', language),
          choice: choice.value.trim() || label.value.trim(),
          reasoning: reasoning.value.trim() || null,
        });
        onSaved();
      } catch (failure) {
        // A 422 refusing `active` arrives as pydantic's list of objects, not a sentence — `detailText`
        // is what stops it rendering as `[object Object]` on the one refusal written to teach a client
        // something.
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: `${cell.display} · ${t(`capital.${cell.capital_type}`, language)}` }),
    h('h1', { text: t('position.edit_title', language) }),
    h('p', { class: 'lede', text: t('position.edit_hint', language) }),

    field(t('form.label', language), label, t('form.label_hint', language)),
    field(t('form.description', language), description),
    field(t('form.magnitude', language), magnitude, t('form.magnitude_hint', language)),
    field(t('form.unit', language), unit, t('form.unit_hint', language)),
    isHuman ? field(t('form.time_basis', language), timeBasis, t('form.time_basis_hint', language)) : null,
    // R-031. The route that made this answerable at all: `POST /api/positions` cannot set it, so a member
    // told `liquidity_not_stated` about their own goal had no way to answer until the PATCH existed.
    field(t('position.edit_liquidity', language), liquidity, t('position.edit_liquidity_hint', language)),

    decisionFieldset(language, question, choice, reasoning),

    error,

    h('div', { class: 'actions' }, [
      submit,
      button(t('form.cancel', language), { class: 'add', onClick: onCancel }),
    ]),
  ]);

  container.append(form);
  label.focus();
}

/**
 * R-122. Marking a position inactive, or active again. **Its own act, on its own screen.**
 *
 * There is no `active` field in the body and none in this form: the act is the route, so there is no flag
 * to get the wrong way round and no request that means "leave it as it is".
 *
 * **The screen says what changes and what does not.** "Deactivate" is the word people read as "delete", so
 * the two sentences the payload asserts — `remains_in_history`, `remains_linked_to_decisions` — are on
 * screen *before* the control rather than in a confirmation afterwards.
 */
export function renderStatusChange(container, { position, cell, language, active, onSaved, onCancel }) {
  clear(container);

  const heading = active ? 'position.reactivate_heading' : 'position.deactivate_heading';
  const hint = active ? 'position.reactivate_hint' : 'position.deactivate_hint';
  const save = active ? 'position.reactivate_save' : 'position.deactivate_save';

  const question = h('input', {
    type: 'text', name: 'question', maxlength: '300', value: t(heading, language),
  });
  const choice = h('input', { type: 'text', name: 'choice', maxlength: '300' });
  const reasoning = h('textarea', { name: 'reasoning', rows: '2' });

  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const submit = h('button', { type: 'submit', class: 'primary' }, [t(save, language)]);

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      submit.disabled = true;
      const decision = {
        question: question.value.trim() || t(heading, language),
        choice: choice.value.trim() || t(save, language),
        reasoning: reasoning.value.trim() || null,
      };
      try {
        const result = active
          ? await reactivatePosition(position.id, decision)
          : await deactivatePosition(position.id, decision);
        onSaved(result);
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        submit.disabled = false;
      }
    },
  }, [
    h('span', { class: 'lbl', text: `${cell.display} · ${t(`capital.${cell.capital_type}`, language)}` }),
    h('h1', { text: t(heading, language) }),
    // The member's own label, quoted rather than folded into a sentence.
    h('blockquote', { class: 'report-quote' }, [
      h('p', { text: position.label, style: 'margin:0' }),
    ]),
    h('p', { class: 'lede', text: t(hint, language) }),
    // R-122's own word is *inactive*: "inactive positions remain in history and in decisions". Said here,
    // in front of the control, because this is the screen where a member decides whether to press it.
    active ? null : h('p', { class: 'cell-prompt', text: t('position.deactivate_stays', language) }),

    decisionFieldset(language, question, choice, reasoning),

    error,

    h('div', { class: 'actions' }, [
      submit,
      button(t('position.status_cancel', language), { class: 'add', onClick: onCancel }),
    ]),
  ]);

  container.append(form);
  choice.focus();
}
