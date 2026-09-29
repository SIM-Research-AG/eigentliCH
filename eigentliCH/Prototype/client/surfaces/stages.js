// S-05 — the stage map. Five situations, all of them open.
//
// **What was unrendered.** `GET /api/stages` composed the whole map and no client code called it. The map
// is the one payload in phase 8 that is *guarded*, and for a reason worth repeating on the screen it feeds:
// the member's own row buys exactly one field, `opens_at`, which is their `stage_hint` — content routing,
// and a fact about a named person. Everything else in the payload is the same for everybody.
//
// ===========================================================================================================
// R-140, R-141 AND R-006: WHAT A STAGE IS NOT
// ===========================================================================================================
//
// A stage **describes a situation**. It is not a grade, not a rung, not a place on a scale, and not a
// statement about the member reading it. So this screen:
//
//   * **opens every stage at once.** Nothing is locked, nothing is dimmed, nothing carries "available from
//     35". R-141 says a member may open any stage regardless of age, and `any_stage_may_be_opened` is in
//     the payload so a client author meets the rule before designing a locked row.
//   * **renders `age_marker` beside the sentence that denies it is a condition.** The payload carries
//     `age_marker_is_not_an_entry_condition` as a field of its own, because the number is exactly the thing
//     an interface turns into a gate without deciding to. It is the age at which a situation typically
//     arrives, and it is never compared to the member's own age — there is nothing here to compare it with.
//   * **marks where the map opens without saying the member is there.** `opens_at` names a stage and
//     `opens_at_is_not_a_position` denies the reading it invites. The marked stage is rendered exactly like
//     the other four — same card, same controls, no ordinal, no "you are here" — and the words carry the
//     distinction rather than a highlight, because a highlight cannot say *which* of the two things it
//     means.
//   * **carries no count and no share.** Not of stages, not of questions, not of anything. `stage_map`'s
//     own docstring lists what it refuses to compute; there is nothing here to filter out because nothing
//     upstream computes one.
//
// **NG-02 is stated rather than left as an absence.** `no_stage_after` is 50 and the payload names the
// non-goal. A member who reaches the last card and finds nothing after it should read why — drawdown is out
// of scope, which is a decision, not an omission — instead of concluding the screen failed to load.
//
// **The German is a draft and the payload says so.** `reviewed` is `stages_are_reviewed()`, false while the
// owner has not read the wording, and A42's precedent is that a draft is marked rather than passed off as
// reviewed. The marker reuses `.provisional`, which the grid already uses for the same kind of claim.
//
// **C-01:** the questions a situation raises are rendered with no answers attached. An answer to "where
// should this money go" is a recommendation and C-01 puts those behind a licensed human — the content
// record says so in its own `register` note, and this screen does not add one.

import { announce, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getDestination, getStages } from '../app/api.js';

/**
 * One stage. The same card whether or not it is the one the map opens at.
 *
 * `data-opens-at` records the distinction for anything that needs it; the *member* reads it as a sentence,
 * because "where the map opens" and "where you are" are one highlight and two completely different claims.
 */
function stageNode(record, { language, opensAt }) {
  const isOpening = record.key === opensAt;
  return h('div', { class: 'cell stage', 'data-opens-at': String(isOpening) }, [
    h('p', { class: 'position-label', text: record.title }),

    // The number, and immediately the sentence that stops it being a threshold.
    h('p', {
      class: 'position-meta',
      text: `${t('stages.age_marker', language)}: ${record.age_marker}`,
    }),
    record.age_marker_is_not_an_entry_condition
      ? h('p', { class: 'field-hint', text: t('stages.age_marker_not_a_condition', language) })
      : null,

    // R-140. A description of circumstances.
    record.situation ? h('p', { class: 'cell-prompt', text: record.situation }) : null,

    // R-006 / C-01. The questions the situation raises, with nothing attached to them.
    (record.questions || []).length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('stages.questions', language) }),
          h('ul', {}, record.questions.map((question) => h('li', { text: question }))),
        ])
      : null,

    isOpening
      ? h('p', { class: 'field-hint', text: t('stages.opens_here', language) })
      : null,

    // A42's precedent, on the wording rather than on the content.
    record.reviewed === false
      ? h('p', { class: 'provisional', text: t('stages.draft_wording', language) })
      : null,
  ]);
}

/**
 * A11: the member is the token's, and `opens_at` is the only thing that answer depends on.
 *
 * D-07's phrase is fetched alongside, and this is the screen it belongs on: the stage map is the surface
 * that says none of these five situations is a rung and that nothing follows the last one (NG-02). The
 * destination is the answer to what the map is *for*, and it is the same for every member — so it is stated
 * once, beside the five situations, rather than repeated on each of them.
 *
 * It fails soft. `GET /api/destination` raises rather than falling back on an unknown language, which is
 * right for the route; a stage map that refused to render because one phrase was unavailable would be the
 * wrong trade on this screen.
 */
export async function load(language) {
  const [stages, destination] = await Promise.all([
    getStages(language),
    getDestination(language).catch(() => null),
  ]);
  return { ...stages, destination: destination ? destination.destination : null };
}

export function render(container, payload, { language }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('stages.eyebrow', language) }),
    h('h1', { text: t('stages.title', language) }),
    h('p', { class: 'lede', text: t('stages.lede', language) }),
  );

  // D-07. One content key, said once, on the screen that explains what the five situations are for.
  // Rendered only when the route answered: a phrase this product will not state is better than a
  // placeholder standing in for it.
  if (payload.destination) {
    container.append(
      h('p', { class: 'destination' }, [
        h('span', { text: t('stages.destination_lead', language) }),
        h('strong', { text: payload.destination }),
      ]),
    );
  }

  // R-141 and R-140, from the payload's own flags rather than asserted by this client.
  container.append(
    h('div', { class: 'notice' }, [
      payload.any_stage_may_be_opened
        ? h('p', { text: t('stages.all_open', language), style: 'margin:0' })
        : null,
      payload.opens_at_is_not_a_position
        ? h('p', { text: t('stages.not_a_position', language), style: 'margin:8px 0 0' })
        : null,
    ]),
  );

  container.append(
    h('div', { class: 'grid stage-map' },
      (payload.stages || []).map((record) => stageNode(record, {
        language,
        opensAt: payload.opens_at,
      }))),
  );

  // NG-02, at the end of the list where the question arises, and only when the payload names the boundary.
  if (payload.no_stage_after) {
    container.append(h('div', { class: 'notice' }, [
      h('p', {
        text: t('stages.no_stage_after', language).replace('{age}', String(payload.no_stage_after)),
        style: 'margin:0',
      }),
      h('p', { class: 'field-hint', text: t('stages.no_stage_after_reason', language), style: 'margin:8px 0 0' }),
    ]));
  }

  announce(t('stages.announced', language));
}
