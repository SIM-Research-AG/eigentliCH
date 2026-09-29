// S-01 — the first conversation, one question at a time.
//
// **R-101 is the whole design of this file.** Each answer is PUT as it is given, before the next question
// is shown. There is no draft object accumulating in memory and no save button holding four answers
// hostage: a member who closes the tab between question two and three has lost nothing, because there was
// never anything unsaved.
//
// **What is deliberately absent.** No "question 2 of 4", no progress bar, no percentage (R-113, C-07).
// The server tells the client which question is next, not how far along it is — see
// `services/onboarding.py::progress`. A step counter is the smallest possible completion meter and it is
// still a completion meter.
//
// **Every question shows why it is asked.** That is carried from the original questionnaire, where each
// of the 78 questions had a `why:` line. It is the single most valuable thing in the estate's onboarding
// and it survives the rewrite intact.

import { button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getOnboarding, putAnswer, completeOnboarding } from '../app/api.js';

/**
 * The control for one question, and how to read it back.
 *
 * Returns `{ node, read, focus }` rather than a bare input, because one question is not one field any
 * more: the goal question is a template choice **and** a name, and its answer is an object. A single
 * `control.value` could not express that, and the shape it forced was the defect — see below.
 */
function controlFor(question, { language }) {
  if (question.type === 'goal_template') return goalControl(question, language);
  if (question.type === 'choice') return choiceControl(question, language);

  if (question.type === 'number') {
    const input = h('input', { type: 'number', step: 'any', name: question.key });
    if (question.min !== null && question.min !== undefined) input.setAttribute('min', String(question.min));
    if (question.max !== null && question.max !== undefined) input.setAttribute('max', String(question.max));
    if (question.answer !== null && question.answer !== undefined) input.value = String(question.answer);
    return {
      node: input,
      read: () => (input.value.trim() ? Number(input.value.trim()) : null),
      focus: () => input.focus(),
    };
  }

  const input = h('input', { type: 'text', maxlength: '300', name: question.key });
  if (question.answer) input.value = String(question.answer);
  return { node: input, read: () => input.value.trim() || null, focus: () => input.focus() };
}

/**
 * Any question that offers a closed list. **Nothing here knows what it is asking about.**
 *
 * That is the requirement A127 was built to satisfy: a key can be added to the instrument "without
 * touching the intake flow". The canton, the civil status and the resilience reading all render through
 * this one function, and a sixth choice key renders through it too, having been added to
 * `client/content/onboarding-questions.json` and nowhere else.
 *
 * **The stored answer is the option's `value`, never its label.** A label is a rendering — it changes with
 * the reader's language — and an answer that changed with the language would be a different answer. The
 * server compares against the same values in `services/member_fact.check`.
 *
 * Nothing is preselected, for the reason `goalControl` gives below: assigning the first option to everyone
 * who never opened the control records an answer nobody gave. Every one of these questions is skippable,
 * so "no answer" has to be reachable and it is the initial state.
 */
function choiceControl(question, language) {
  const options = question.options || [];
  const select = h('select', { name: question.key });
  select.appendChild(h('option', { value: '', text: t('containers.template_choose', language) }));

  // The index, not the value: `value` may be a number (the resilience readings are 0.6 … 1.0) and a
  // select's own value is always a string, so reading it back would turn 0.85 into "0.85" and the
  // server would refuse it as not one of the options — correctly, since it is not.
  options.forEach((option, index) => {
    const node = h('option', { value: String(index) }, [option.label]);
    if (question.answer === option.value) node.selected = true;
    select.appendChild(node);
  });

  return {
    node: select,
    read: () => (select.value === '' ? null : options[Number(select.value)].value),
    focus: () => select.focus(),
  };
}

/**
 * S-01's goal question: choose a goal, and it is filled out.
 *
 * **This is the owner's second sentence, built.** *"We have the potential goals already defined and when in
 * the onboarding the system ask for a goal, then we should immediately fill that goal out."* Before this,
 * the question took free text and the service stored the sentence as the goal's *name* with no template at
 * all — so "Frühpensionierung" became a goal eigentliCH could not recognise as one, and the two templates
 * that existed were never reached from here.
 *
 * The templates travel in the question's own payload (`GET /api/onboarding`), so this control needs no
 * second request and cannot render an empty list because one was forgotten.
 *
 * **Choosing a template fills the name in, and the name stays editable.** The template is a shape, not a
 * label the member has to accept: someone whose early retirement is "Praxis mit 58 abgeben" should be able
 * to say so and still have the goal carry `early_retirement`. Overwriting the name never changes the
 * template, and the hint says the name is theirs.
 *
 * Nothing is preselected. The first option carries no value, because the first real one is
 * Frühpensionierung and assigning that to everyone who never opened the control would be worse than the
 * defect being fixed.
 */
function goalControl(question, language) {
  const templates = question.templates || [];
  const answered = question.answer && typeof question.answer === 'object' ? question.answer : null;

  const template = h('select', { name: `${question.key}_template` }, [
    h('option', { value: '', text: t('containers.template_choose', language) }),
    ...templates.map((record) =>
      h('option', {
        value: record.key,
        selected: answered && answered.template === record.key ? '' : null,
        text: (record[language] && record[language].name) || t('containers.template_unnamed', language),
      }),
    ),
  ]);

  const name = h('input', { type: 'text', maxlength: '200', name: question.key });
  if (answered && answered.name) name.value = String(answered.name);
  else if (typeof question.answer === 'string') name.value = question.answer;

  const purpose = h('p', { class: 'field-hint' });

  template.addEventListener('change', () => {
    const record = templates.find((entry) => entry.key === template.value);
    purpose.textContent = record && record[language] ? record[language].purpose : '';
    // Filled in, never overwritten: a member who has typed their own words keeps them. R-151's rule about
    // extraction not overwriting a member-entered value, applied to a template.
    if (record && !name.value.trim()) {
      name.value = (record[language] && record[language].name) || '';
    }
  });

  const node = h('div', { class: 'goal-choice' }, [
    field(t('onboarding.goal_template', language), template),
    purpose,
    field(t('onboarding.goal_name', language), name, t('onboarding.goal_name_hint', language)),
  ]);

  return {
    node,
    read: () => {
      const stated = name.value.trim();
      // No name is no goal, whichever control was touched — R-102 writes the goal only "if stated", and a
      // template with nothing named is not a stated goal.
      if (!stated) return null;
      return { template: template.value || null, name: stated };
    },
    focus: () => template.focus(),
  };
}

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

// A11: `memberId` is no longer a parameter of any call this surface makes. It is not taken at all.
export async function render(container, { language, onFinished }) {
  clear(container);

  let state;
  try {
    state = await getOnboarding(language);
  } catch (error) {
    container.append(h('div', { class: 'notice error', text: error.detail || String(error) }));
    return;
  }

  // Resume where the member stopped. `next_question_key` is the server's answer to "where were they",
  // and it is a key rather than an index precisely so nothing here can render it as a position on a scale.
  const ordered = state.questions;
  const startIndex = Math.max(
    0,
    ordered.findIndex((q) => q.key === state.next_question_key),
  );
  let index = state.next_question_key ? startIndex : ordered.length - 1;

  const stage = h('div', { class: 'onboarding' });
  container.append(
    h('span', { class: 'lbl', text: t('onboarding.eyebrow', language) }),
    h('h1', { text: t('onboarding.title', language) }),
    h('p', { class: 'lede', text: t('onboarding.lede', language) }),
    stage,
  );

  async function step() {
    clear(stage);

    if (index >= ordered.length) {
      const finish = h('button', { type: 'button', class: 'primary' }, [t('onboarding.finish', language)]);
      const error = h('div', { class: 'notice error', hidden: '' });
      finish.addEventListener('click', async () => {
        try {
          await completeOnboarding();
          onFinished();
        } catch (err) {
          error.textContent = err.detail || String(err);
          error.removeAttribute('hidden');
        }
      });
      stage.append(h('div', { class: 'actions' }, [finish]), error);
      finish.focus();
      return;
    }

    const question = ordered[index];
    const control = controlFor(question, { language });
    const error = h('div', { class: 'notice error', hidden: '' });

    async function save(andThen) {
      error.setAttribute('hidden', '');
      try {
        // R-101: written now, per question. Not on navigate, not on submit.
        await putAnswer(question.key, control.read());
        andThen();
      } catch (err) {
        error.textContent = err.detail || String(err);
        error.removeAttribute('hidden');
      }
    }

    const next = h('button', { type: 'submit', class: 'primary' }, [
      index === ordered.length - 1 ? t('onboarding.next', language) : t('onboarding.next', language),
    ]);

    const form = h('form', {
      class: 'position-form',
      onSubmit: (event) => {
        event.preventDefault();
        if (question.required && !control.read()) {
          control.focus();
          return;
        }
        save(() => { index += 1; step(); });
      },
    }, [
      h('p', { class: 'question-text', text: question.question }),
      control.node,
      // The `why` line, carried from the original questionnaire. Not hidden behind a toggle: it is the
      // reason the question is tolerable, and a member should not have to ask for it.
      question.why ? h('p', { class: 'field-hint', text: question.why }) : null,
      error,
      h('div', { class: 'actions' }, [
        next,
        // R-102: only the first question is required. Skipping is offered plainly rather than being an
        // empty submit, because a member should be able to tell that leaving it blank is allowed.
        !question.required
          ? button(t('onboarding.skip', language), {
              class: 'add',
              onClick: () => { index += 1; step(); },
            })
          : null,
      ]),
    ]);

    stage.append(form);
    control.focus();
  }

  step();
}
