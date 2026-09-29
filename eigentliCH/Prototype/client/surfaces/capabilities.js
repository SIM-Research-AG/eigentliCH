// S-10 — the capability statements, and the member's own record of which of them hold for them.
//
// **Why this file exists.** `POST /api/capabilities/assertions` was written the day D-01 was answered
// (A94), and nothing rendered it — so `POST /api/marketplace/applications` went on refusing **every real
// member** with a 403, because the gate reads capability evidence and no member could hold any. The most
// heavily guarded module in the build could not be entered by anybody. This is the screen that makes
// R-005's gate passable from the product rather than from a test.
//
// It also replaces the placeholder behind the `#/know` door. That door is §3's Knowledge and Community
// door — **not** S-08, which is the panel mounted on `document.body` and present on every screen. The
// distinction was the whole content of the placeholder, so it is kept as a sentence here rather than
// dropped: a member who went looking for the panel behind this door would be learning exactly the mistake
// R-002 exists to prevent.
//
// ===========================================================================================================
// D-01 AND R-194: WHAT THIS SCREEN IS NOT ALLOWED TO IMPLY
// ===========================================================================================================
//
// **A capability is the member's own self-assessment. eigentliCH does not test, grade or certify one.** A82
// answered D-01 as "it's their responsibility", and R-194 forbids eigentliCH any claim of accredited
// standing — so being in the business of examining people was never available to it. What this screen does
// is write down that the member said so, with the member named as the one who said it.
//
// So: **the control says "this holds for me"**, not "mark as achieved", not "complete", not "pass". The
// heading is "what you can do", not "your level". `assessed_by` is `member:<id>` and comes back from the
// server; it is rendered as the member's own statement and never as eigentliCH's finding.
//
// **C-07, and this is the screen where a rung would sneak in as a UI affordance rather than as a word.**
// There is no ordering of the statements, no count of how many are recorded, no "3 of 10", no bar and no
// tick-list totals. `capabilities_are_unordered` is true in the payload and this file iterates the list as
// it arrives. `rung` is null on every entry and `rung_scheme_reason` says there is **no scheme** rather
// than that one is pending — D-01 is answered, not open. The temptation here is not the word "level"; it
// is a filled circle beside each statement and a row of them across the top, which is a rung scheme drawn
// instead of written. There is neither, and `test_client_bundle.py`'s C-07 scan plus a test in
// `test_client_capabilities.py` hold the words and the shape.
//
// **`evidence_ref` may only name a learning unit whose content actually evidences that capability.** The
// selector against one statement is built from that statement's own `evidenced_by_units`, so a member
// cannot offer a reference the server would refuse — and the server refuses it anyway (422, R-190),
// because a reference that does not hold reads as corroboration and is not one. The two halves agree by
// construction: the list on screen comes from the same content record the check reads.
//
// **There is no removal, and that is a decision rather than an omission.** Neither the route nor this
// screen offers one. Following A86's reasoning about goals: nothing in the specification says what
// withdrawing an assertion means for a listing already published on the strength of it, and answering that
// question in a form is how a member loses something they cannot get back. The screen says so out loud
// instead of leaving a member to discover it.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { assertCapability, detailText, getCapabilities, getLearning } from '../app/api.js';

/** A `31.08.2026` from an ISO timestamp. Date only: an assertion is a day, not a moment. */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('T')[0].split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : parts.join('-');
}

/**
 * A11: no member id in either call. Both are the token's member's.
 *
 * The learning payload is fetched for the unit **titles** — see `api.js::getLearning`. A selector offering
 * `konten_die_liegen_bleiben` is a selector nobody can use, and a title table held in this client would be
 * a second copy of content the server owns.
 */
export async function load(language) {
  const [review, learning] = await Promise.all([getCapabilities(language), getLearning(language)]);
  return { review, learning };
}

/** `{unitKey: title}` from the learning payload, so a key never reaches the screen. */
function unitTitles(learning) {
  const titles = {};
  for (const unit of (learning && learning.units) || []) titles[unit.key] = unit.title;
  return titles;
}

/**
 * What the member has already recorded against one statement.
 *
 * `evidence_kind` and `assessed_by` are the server's constants and are rendered as what they are: the
 * member's own statement about themselves, with the date. **Not rendered as a finding**, and `assessed_by`
 * is deliberately not printed as a raw `member:<id>` string at somebody — the fact it carries is "you
 * said this", which is a sentence.
 */
function evidenceNodes(entry, language, titles) {
  return (entry.evidence || []).map((record) => h('div', { class: 'capability-evidence' }, [
    h('p', { class: 'report-meta', text: t('capabilities.asserted', language) }),
    h('p', {
      class: 'report-meta',
      text: `${t('capabilities.asserted_on', language)}: ${readableDate(record.assessed_at, language)}`,
    }),
    // R-190. The reference, by the unit's title where the content names one; the server stores it as
    // `learning.json#units.<key>`, so the key is recovered from the tail rather than parsed loosely.
    record.evidence_ref
      ? h('p', {
          class: 'report-meta',
          text: `${t('capabilities.evidence_unit', language)}: `
            + (titles[String(record.evidence_ref).split('.').pop()] || record.evidence_ref),
        })
      : h('p', { class: 'report-meta', text: t('capabilities.evidence_self', language) }),
  ]));
}

/**
 * The form for one statement. **A door, not a control standing open.**
 *
 * One statement, one deliberate press, one submit. There is no "record all", because a screen that let a
 * member assert ten things about themselves in one action is a screen that has stopped asking them
 * anything.
 */
function assertForm(entry, language, titles, { onAsserted }) {
  const offered = entry.evidenced_by_units || [];

  // R-190. Only the units this statement's own content evidences — so the selector cannot offer a
  // reference the server would refuse, and the refusal path stays a genuine second line of defence rather
  // than the only one.
  const unit = offered.length
    ? h('select', { name: 'learning_unit' }, [
        h('option', { value: '', text: t('capabilities.evidence_unit_none', language) }),
        ...offered.map((key) => h('option', { value: key, text: titles[key] || key })),
      ])
    : null;

  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const submit = h('button', { type: 'submit', class: 'primary' }, [
    t('capabilities.assert_save', language),
  ]);

  const form = h('form', {
    class: 'position-form',
    hidden: '',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      submit.disabled = true;
      try {
        await assertCapability({
          capabilityId: entry.key,
          learningUnit: unit && unit.value ? unit.value : null,
        });
        // **Announced AFTER the screen behind it has settled, and that ordering is the whole of it.**
        // `onAsserted` re-reads and re-renders, and `render` announces "the capabilities are loaded" when
        // it finishes. Announcing first therefore put "recorded" into `#live` and then overwrote it a few
        // milliseconds later, so a member using a screen reader heard that the screen had loaded and never
        // heard that their statement had been recorded. Exactly the defect A86 found on the language switch,
        // in a second place, and found the same way: by running the client rather than by reading it. The
        // code reads correctly either way and the symptom is audible only.
        await onAsserted();
        announce(t('capabilities.asserted_announced', language));
      } catch (failure) {
        // 409 for a statement already recorded — which is "already true" rather than "malformed", and the
        // server says so; 422 for a unit that does not evidence this statement, naming the ones that do.
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        submit.disabled = false;
      }
    },
  }, [
    h('h3', { text: t('capabilities.assert_heading', language) }),
    h('p', { class: 'field-hint', text: t('capabilities.assert_hint', language) }),
    unit
      ? h('label', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('capabilities.evidence_unit_label', language) }),
          unit,
          h('span', { class: 'field-hint', text: t('capabilities.evidence_unit_hint', language) }),
        ])
      : null,
    error,
    h('div', { class: 'actions' }, [submit]),
  ]);

  const opener = button(t('capabilities.assert', language), {
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
 * One capability statement.
 *
 * **No marker of position in a sequence and no marker of standing.** `data-evidenced` records whether the
 * member has said this holds for them, and it is stated in words as well — `capabilities.asserted` — so
 * that it is not a state visible only in colour (1.4.1) and cannot be read as a mark out of a total.
 */
function capabilityNode(entry, language, titles, { onAsserted }) {
  return h('div', {
    class: 'cell capability',
    'data-evidenced': String(Boolean(entry.evidenced)),
  }, [
    // The statement is the content's own sentence, in the member's language, and is not paraphrased here.
    h('p', { class: 'capability-statement', text: entry.statement }),
    ...evidenceNodes(entry, language, titles),
    // Already recorded: the screen says so and offers nothing further. No removal — see the module
    // docstring, and the sentence is on screen rather than only in this comment.
    entry.evidenced
      ? h('p', { class: 'field-hint', text: t('capabilities.no_removal', language) })
      : assertForm(entry, language, titles, { onAsserted }),
    // R-190's list, shown whether or not anything is recorded: what a member would work through for this.
    (entry.evidenced_by_units || []).length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('capabilities.units_heading', language) }),
          h('ul', {}, entry.evidenced_by_units.map((key) =>
            h('li', { text: titles[key] || key }))),
        ])
      : null,
  ]);
}

export function render(container, payload, { language, onAsserted }) {
  clear(container);
  const review = payload.review || {};
  const titles = unitTitles(payload.learning);

  container.append(
    h('span', { class: 'lbl', text: t('capabilities.eyebrow', language) }),
    h('h1', { text: t('capabilities.title', language) }),
    h('p', { class: 'lede', text: t('capabilities.lede', language) }),

    // D-01 / R-194, rendered from the payload's own flags rather than asserted by this client. The server
    // says `capabilities_are_self_asserted`, `eigentlich_assesses_capabilities: false` and
    // `capabilities_are_unordered`; the screen states all three in one sentence, because a member reading
    // this needs to know it is their claim and not a mark.
    review.capabilities_are_self_asserted && review.eigentlich_assesses_capabilities === false
      ? h('p', { class: 'field-hint', text: t('capabilities.self_assessed', language) })
      : null,
    // R-194 / NG-04, on the one screen a 201 might otherwise be read as a pass.
    review.qualification_claim === null
      ? h('p', { class: 'field-hint', text: t('capabilities.no_qualification', language) })
      : null,
    review.fictional
      ? h('p', { class: 'field-hint', text: t('capabilities.fictional', language) })
      : null,
    // R-002. The panel is a different thing and lives on every screen — the placeholder this replaced said
    // exactly that, and it is worth more here beside a real screen than it was standing alone.
    h('p', { class: 'field-hint', text: t('capabilities.know_panel_note', language) }),
  );

  // The payload's order, untouched. `capabilities_are_unordered` is the server's own statement about it:
  // there is no progression, so there is nothing for a client to sort by.
  container.append(
    h('div', { class: 'grid capability-list' },
      (review.capabilities || []).map((entry) =>
        capabilityNode(entry, language, titles, { onAsserted }))),
  );

  announce(t('capabilities.announced', language));
}
