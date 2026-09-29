// The entry surface: one question field, and nothing else above the fold. Update script item 1.
//
// **Why the field and not the grid.** Journey & Design page 1: "The first thing a person meets is a
// question field, not an onboarding sequence. It carries no member data, needs no intake, works in the
// first second, and does not assume which journey the person is on." Page 2 says the same thing from the
// other side — "nobody meets the four roles before they have entered data" — which is why the role grid
// moved behind the Vault and this took the landing route.
//
// **Principle 3, applied to the first screen a member ever sees.** A person who has entered nothing gets a
// working screen. There is deliberately no metric, no card, no hero number and no onboarding prompt here:
// item 1 lists those four by name, and each of them is a way of telling somebody who has just arrived that
// they are behind.
//
// ==========================================================================================================
// THE FIELD BEHAVIOUR IS COPIED, NOT INVENTED
// ==========================================================================================================
//
// Item 1: "Field behaviour, taken from the LU OGD portal which solved this already." Four things, and the
// reasoning for each is the portal's rather than ours:
//
//   * **Multiline, growing to a cap, then scrolling.** "A question about someone's finances is usually a
//     sentence with a subordinate clause; in a single-line field people write blind."
//   * **Enter submits, Shift+Enter breaks the line.** The common act is the cheap one.
//   * **The submitted question stays above the answer.** It is the only thing on the screen that came from
//     the person.
//   * **A completed answer stays until a new question is started, and is never recomputed on return.**
//     "A second run can produce a different figure than the one the person already acted on. Same rule as
//     a re-solve never silently replacing the standing plan."
//
// That last one is why `state` lives at module scope. `main.js` calls `render()` on every arrival at
// `#/ask`, and a surface that re-asked on each arrival would be exactly the silent recompute the script
// forbids — the member would leave for the Vault, come back, and read a different number with no act of
// theirs in between.

import { ApiError, askKnow } from '../app/api.js';
import { announce, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';

//: The tallest the field grows before it scrolls, in pixels. Not a row count: rows are a font-relative
//: unit and the cap here is about how much of the screen the field may take, which is a screen fact.
const MAX_FIELD_HEIGHT = 240;

//: What survives a route change. **Deliberately module-level and deliberately not persisted.** Surviving
//: a route change is required (see the header); surviving a reload is not, and an answer restored from
//: storage would be a figure whose provenance a member cannot see — it would look like it had just been
//: computed. A reload is a fresh screen, which is honest.
let state = {
  //: The question as submitted, kept verbatim. Rendered above the answer and never re-sent on its own.
  asked: null,
  //: The payload from `POST /api/know/ask`, or null.
  answer: null,
  //: True while a request is in flight. Renders as a waiting line rather than a spinner over the answer,
  //: so the previous answer stays readable until the new one replaces it.
  pending: false,
  //: An ApiError or Error from the last attempt, or null.
  failure: null,
};

/** Called by `main.js` when the member signs out. An answer is the member's, and it goes with them. */
export function forget() {
  state = { asked: null, answer: null, pending: false, failure: null };
}

// ---------------------------------------------------------------- the answer, and where it came from

/**
 * R-171. Every answer carries its sources, and a figure with no provenance does not render.
 *
 * The sources are a list under the answer rather than footnote markers in it, because the markers are
 * already in the text — `render` on the server emits `[1]`, `[2]` in the quotes' own order, and
 * `citations[i - 1]` is what each names.
 */
function sourceBar(payload, language) {
  const citations = payload.citations || [];
  if (!citations.length) return null;

  return h('div', { class: 'ask-sources' }, [
    h('span', { class: 'lbl', text: t('ask.sources', language) }),
    h(
      'ol',
      { class: 'ask-source-list' },
      citations.map((citation, index) =>
        h('li', {}, [
          h('span', { class: 'ask-source-index', text: `[${index + 1}]` }),
          h('span', { text: citation.title || citation.kind || t('ask.source_unnamed', language) }),
        ]),
      ),
    ),
  ]);
}

/**
 * One collapsed fold, and one only. Item 1's visual instruction, and Principle 4's shape applied to
 * caveats: several disclosures in a row are read as none.
 *
 * What goes in it is what a member would need to *check* the answer rather than to read it — which
 * branch it took, which boundary it sits below, and whether the corpus behaved. None of that belongs in
 * front of somebody who just wants the answer, and all of it belongs somewhere.
 */
function caveatFold(payload, language) {
  const route = payload.route || {};
  const rows = [
    [t('ask.caveat_branch', language), t(`ask.branch_${route.branch}`, language)],
    [t('ask.caveat_boundary', language), t(`ask.boundary_${route.boundary}`, language)],
  ];
  if (payload.model) rows.push([t('ask.caveat_model', language), payload.model]);

  return h('details', { class: 'ask-caveat' }, [
    h('summary', { text: t('ask.caveat', language) }),
    h(
      'dl',
      { class: 'ask-caveat-rows' },
      rows.flatMap(([term, value]) => [h('dt', { text: term }), h('dd', { text: value })]),
    ),
  ]);
}

/**
 * Branch 2 with an empty Vault. Item 1: the answer "names the single input that would make it personal,
 * and offers to start there".
 *
 * The sentence is the server's — a fixed phrase from the four-language table, composed by code — and this
 * renders it beside a way in. It is NOT dressed as a warning: nothing has gone wrong, and a member who has
 * not done an intake has not failed at anything.
 */
function personalisation(payload, language, { onStart }) {
  const named = payload.personalisation;
  if (!named) return null;

  return h('div', { class: 'ask-personal notice' }, [
    h('p', { text: named.sentence, style: 'margin:0' }),
    h('div', { class: 'actions', style: 'margin-top:8px' }, [
      h('button', {
        type: 'button',
        class: 'add',
        text: t('ask.start_there', language),
        onClick: () => onStart(named),
      }),
    ]),
  ]);
}

function answerBlock(payload, language, handlers) {
  // R-172. A handoff is the boundary being explained, and it is not dressed as an error — the same rule
  // the Know panel already follows. Nothing here rewords the server's text.
  //
  // **Unreachable from the ask route since 20 September 2026 (A164, A165).** This branch rendered C-01's
  // refusal; C-01 was withdrawn, and `services/router.py` now returns `requires_curator: false` on every
  // route. It is kept rather than deleted because the flag is still set elsewhere in the build — A122's
  // undecidable liquidity lever routes a computation nobody can make to a human — and because a client
  // that stops handling a key the server still sends fails silently the day something sets it again.
  const refused = Boolean(payload.requires_curator);

  return h('div', { class: refused ? 'ask-answer refused' : 'ask-answer' }, [
    h('p', { class: 'ask-answer-text', text: payload.answer }),
    refused
      ? h('div', { class: 'actions' }, [
          h('button', {
            type: 'button',
            class: 'primary',
            text: t('ask.to_curator', language),
            onClick: handlers.onCurator,
          }),
        ])
      : null,
    personalisation(payload, language, handlers),
    sourceBar(payload, language),
    caveatFold(payload, language),
  ]);
}

// ---------------------------------------------------------------- the screen

export function render(host, { language, onCurator, onStart }) {
  clear(host);

  const field = h('textarea', {
    id: 'ask-field',
    class: 'ask-field',
    rows: '1',
    maxlength: '1000',
    name: 'ask_question',
    'aria-label': t('ask.label', language),
    placeholder: t('ask.placeholder', language),
  });

  /** Grow with the content to a cap, then scroll. Reset first, or the field can only ever get taller. */
  function grow() {
    field.style.height = 'auto';
    const wanted = Math.min(field.scrollHeight, MAX_FIELD_HEIGHT);
    field.style.height = `${wanted}px`;
    field.style.overflowY = field.scrollHeight > MAX_FIELD_HEIGHT ? 'auto' : 'hidden';
  }

  const form = h('form', {
    class: 'ask-form',
    onSubmit: (event) => {
      event.preventDefault();
      submit();
    },
  });

  field.addEventListener('input', grow);
  field.addEventListener('keydown', (event) => {
    // Enter submits; Shift+Enter is a newline. `isComposing` is checked because an IME uses Enter to
    // accept a candidate, and submitting there would eat the word the member was still spelling.
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      submit();
    }
  });

  const submitButton = h('button', {
    type: 'submit',
    class: 'primary',
    text: t('ask.submit', language),
  });

  form.append(field, h('div', { class: 'actions' }, [submitButton]));

  // Everything below the field. The field is appended first and this after it, so that on a phone the
  // fold sits under the field rather than the field being pushed down by whatever was answered last.
  const below = h('div', { class: 'ask-below' });

  async function submit() {
    const question = field.value.trim();
    if (!question) return;

    // The new question replaces the old answer at the moment of asking, not when the reply arrives: the
    // member has moved on, and leaving the previous answer under a new question would pair the two.
    state = { asked: question, answer: null, pending: true, failure: null };
    field.value = '';
    grow();
    draw();
    announce(t('ask.asking', language));

    try {
      const payload = await askKnow(question, language);
      state = { asked: question, answer: payload, pending: false, failure: null };
      announce(t('ask.answered', language));
    } catch (error) {
      state = { asked: question, answer: null, pending: false, failure: error };
      announce(t('ask.failed', language));
    }
    draw();
  }

  function draw() {
    clear(below);
    if (!state.asked) return;

    // The question, above the answer and prominent. Item 1: "It is the only thing on the screen that came
    // from the person." Rendered as text through `h`, never as markup — see `dom.js`.
    below.append(h('p', { class: 'ask-asked', text: state.asked }));

    if (state.pending) {
      below.append(h('p', { class: 'field-hint', text: t('ask.asking', language) }));
      return;
    }
    if (state.failure) {
      const error = state.failure;
      below.append(
        h('div', { class: 'notice error' }, [
          h('p', { text: t('ask.failed', language), style: 'margin:0' }),
          h('p', {
            class: 'lbl',
            style: 'margin:8px 0 0',
            text: error instanceof ApiError ? error.detail || String(error.status) : String(error),
          }),
        ]),
      );
      return;
    }
    if (state.answer) {
      below.append(answerBlock(state.answer, language, { onCurator, onStart }));
    }
  }

  host.append(
    h('section', { class: 'ask' }, [
      // No heading above the field. A title would be the first of the "no metrics, no cards" list to
      // creep back — and the field's own label is read by assistive technology from `aria-label`.
      form,
      below,
    ]),
  );

  grow();
  draw();
  // Focus is NOT taken here. A member arriving back at this screen with an answer on it is reading, and a
  // field that grabs the caret would scroll the answer off a phone.
}
