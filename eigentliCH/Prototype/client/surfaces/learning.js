// S-10 — the learning path. The units, what each one evidences, and the three exits.
//
// **What was unrendered.** `GET /api/learning` was called by exactly one caller, and only for unit
// *titles*: `surfaces/capabilities.js` fetches it so a selector can offer "Konten, die liegen bleiben"
// instead of a key. The units themselves, their prerequisites, the sentences each one evidences and R-193's
// three exits reached no screen at all — half of S-10 built and invisible.
//
// ===========================================================================================================
// R-190, R-192 AND C-07: A PATH THAT IS NOT A LADDER
// ===========================================================================================================
//
// **Nothing is gated and nothing is ordered.** `units_are_not_gated` is in the payload and
// `capabilities_are_unordered` beside it, and the file order is authoring convenience — the service says
// so, because "a client that reads it as a sequence is reading a ladder nobody designed". So this screen
// renders the list as it arrives, with no numbers, no first/next, no locks and no arrows between cards.
//
// **A prerequisite is rendered as a fact, never as a gate.** R-190's first half: a unit names what came
// before it, and `capabilities_without_evidence` says which of that unit's sentences the member has not yet
// asserted. That is information, not a door. Whether evidence of a prerequisite's capabilities means the
// prerequisite is *met* is the assessment question D-01 owns, and D-01's answer (A82) is that the member
// says so about themselves — so there is nobody here to open a door.
//
// **`rung` is null and `rung_scheme_reason` says there is no scheme rather than that one is pending.** D-01
// is answered, not open. Nothing on this screen may imply a level: no number beside a unit, no filled
// circles, no bar. C-07's temptation on this surface is not the word "level" — it is a row of dots across
// the top, which is a rung scheme drawn instead of written. There is neither, and there is no count of how
// many units exist or how many sentences the member has asserted.
//
// **R-194 / NG-04: eigentliCH awards nothing and examines nothing.** `qualification_claim` is null in the
// payload and the screen states it, on the surface where a member would most naturally read a completed
// unit as a credential.
//
// **The lesson prose does not exist and the payload says which absence that is.** `body_ref` names where a
// unit's material would live and `body_unavailable_reason` is `not_authored` — the same rule R-183 states
// for the life-event modules. So the frame is rendered and nothing is generated to fill it.
//
// **R-193's three exits, and only two of them touch the Market Place.** `touches_market_place` is a field
// per exit and is rendered as one, because "this is what the learning is for" is the answer to a question a
// member asks before working through anything, and two of the three answers have nothing to do with being
// listed as supply.
//
// **C-01:** no unit is recommended, no order is suggested, and nothing here says what the member should
// learn next. Which unit to work through is their decision (A92).

import { announce, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getLearning } from '../app/api.js';

/**
 * R-190, second half. The capability sentences one unit evidences.
 *
 * `evidenced` is rendered in words, never as a tick and never as a share of the list. The sentence itself is
 * the progression (R-191), so it is printed in full rather than summarised into a label.
 */
function evidencesNode(entry, language) {
  return h('div', { class: 'field' }, [
    h('span', { class: 'field-label', text: t('learning.evidences', language) }),
    h('div', {}, (entry.evidences || []).map((record) => h('div', { class: 'position' }, [
      h('div', { class: 'position-label', text: record.statement }),
      // The member's own recorded statement, said as one. `capabilities.js` is where it is recorded; this
      // is where it is read back beside the unit that evidences it.
      record.evidenced
        ? h('div', { class: 'position-meta', text: t('learning.you_asserted', language) })
        : h('div', { class: 'position-meta', text: t('learning.not_asserted', language) }),
    ]))),
    // D-01, per unit rather than only once at the top: this is the field a reader would use to decide what
    // a unit is worth.
    h('span', { class: 'field-hint', text: t('learning.no_scheme', language) }),
  ]);
}

/**
 * R-190, first half. What came before this unit — as a statement, not as a lock.
 *
 * The wording is deliberate: "this unit follows" rather than "requires". Nothing here disables anything,
 * and `capabilities_without_evidence` is named as what the member has not said about themselves yet, which
 * is a fact about their own record rather than a condition of entry.
 */
function prerequisitesNode(entry, language) {
  const rows = entry.prerequisites || [];
  if (!rows.length) return null;
  return h('div', { class: 'field' }, [
    h('span', { class: 'field-label', text: t('learning.follows', language) }),
    h('ul', {}, rows.map((row) => h('li', {}, [
      h('span', { text: row.title || row.key }),
      (row.capabilities_without_evidence || []).length
        ? h('span', { class: 'field-hint', text: t('learning.follows_open', language) })
        : null,
    ]))),
    h('span', { class: 'field-hint', text: t('learning.not_gated', language) }),
  ]);
}

/** One unit. The same card for every unit, in the order the payload arrived in. */
function unitNode(entry, language, exitNames) {
  return h('div', { class: 'cell learning-unit' }, [
    h('p', { class: 'position-label', text: entry.title || entry.key }),
    entry.summary ? h('p', { class: 'cell-prompt', text: entry.summary }) : null,

    prerequisitesNode(entry, language),
    evidencesNode(entry, language),

    // R-193, where a unit genuinely leads to one.
    (entry.exits || []).length
      ? h('p', {
          class: 'position-meta',
          // The exit's name comes from the payload's own `exits` block, not from this client's string
          // table: R-193's three exits are authored content and a second copy of their names here would be
          // two lists to keep in step — the A73 shape. A key with no name in the payload renders as itself.
          text: `${t('learning.leads_to', language)}: `
            + entry.exits.map((key) => exitNames[key] || key).join(', '),
        })
      : null,

    // The lesson material, and which absence it is. `not_authored` rather than "coming soon".
    entry.body_unavailable_reason
      ? h('p', { class: 'field-hint', text: t('learning.body_not_written', language) })
      : null,
    entry.fictional ? h('p', { class: 'field-hint', text: t('learning.fictional', language) }) : null,
  ]);
}

/** R-193. The three exits — what the learning is for — with the two that touch the Market Place named. */
function exitsSection(payload, language) {
  const rows = payload.exits || [];
  if (!rows.length) return null;
  return h('section', { class: 'learning-exits' }, [
    h('h2', { text: t('learning.exits_heading', language) }),
    h('p', { class: 'field-hint', text: t('learning.exits_lede', language) }),
    h('div', { class: 'grid' }, rows.map((record) => h('div', { class: 'cell learning-exit' }, [
      h('p', { class: 'position-label', text: record.name || record.key }),
      record.description ? h('p', { class: 'cell-prompt', text: record.description }) : null,
      h('p', {
        class: 'position-meta',
        text: record.touches_market_place
          ? t('learning.exit_touches_market', language)
          : t('learning.exit_no_market', language),
      }),
    ]))),
  ]);
}

/** A11: the member is the token's, and what their row buys is which sentences they have asserted. */
export function load(language) {
  return getLearning(language);
}

export function render(container, payload, { language }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('learning.eyebrow', language) }),
    h('h1', { text: t('learning.title', language) }),
    h('p', { class: 'lede', text: t('learning.lede', language) }),
  );

  // The four denials, each read off the payload's own flag rather than asserted here. Together they are the
  // whole of what this screen is not: no scheme, no gate, no order, no qualification.
  container.append(
    h('div', { class: 'notice' }, [
      payload.rung_scheme === null
        ? h('p', { text: t('learning.no_scheme', language), style: 'margin:0' })
        : null,
      payload.units_are_not_gated
        ? h('p', { text: t('learning.not_gated', language), style: 'margin:8px 0 0' })
        : null,
      payload.capabilities_are_unordered
        ? h('p', { text: t('learning.unordered', language), style: 'margin:8px 0 0' })
        : null,
      payload.capabilities_are_self_asserted && payload.eigentlich_assesses_capabilities === false
        ? h('p', { text: t('learning.self_asserted', language), style: 'margin:8px 0 0' })
        : null,
      payload.qualification_claim === null
        ? h('p', { class: 'field-hint', text: t('learning.no_qualification', language), style: 'margin:8px 0 0' })
        : null,
    ]),
  );

  container.append(exitsSection(payload, language));

  // The payload's order, untouched.
  const exitNames = {};
  for (const record of payload.exits || []) exitNames[record.key] = record.name;
  container.append(
    h('div', { class: 'grid learning-units' },
      (payload.units || []).map((entry) => unitNode(entry, language, exitNames))),
  );

  announce(t('learning.announced', language));
}
