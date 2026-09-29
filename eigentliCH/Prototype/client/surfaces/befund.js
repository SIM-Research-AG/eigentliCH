// The Befund — the standing report, rendered. The surface the report did not have.
//
// **Why this file exists, in the owner's words.** *"I can put all the information in but I don't get
// anything out of it, like an action plan, like a status update, report or whatever."* `services/befund.py`
// was written to answer that and `GET /api/befund` returns a complete six-section report. Then the owner
// opened the application again and said **"there is still no output"** — and they were right, because the
// chrome had three doors and none of them led here. The report existed and no member could reach it. This
// is the surface, and `chrome.door_befund` is the door.
//
// ===========================================================================================================
// THE FOUR THINGS THIS FILE IS NOT ALLOWED TO DO, AND WHERE EACH IS ENFORCED
// ===========================================================================================================
//
// **The section order is the payload's, and it is editorial.** `SECTIONS` in the service reads: what the
// plan holds, then what it is for, then what was decided, then what carries a date, then what is prepared,
// then what is not known. This file iterates `report.sections` and never sorts, filters or regroups it — a
// client that sorted by "most facts first" would silently republish the report in an order nobody chose.
//
// **A member's own words are quoted, never spliced.** `Fact.sentence` is what eigentliCH says and passes
// C-01's outbound gate in the service's constructor; `Fact.quoted` is what the member typed and has passed
// no gate, because it is not eigentliCH speaking. The service keeps them in separate fields precisely so a
// renderer cannot concatenate them, and the reason is not squeamishness: a member who names a goal
// "Ich sollte mehr sparen" would otherwise make their own report unrenderable — the gate would refuse a
// sentence they wrote. So every quoted value is rendered as a `<blockquote>` with its own label, outside
// the sentence, and `Fact.subject` only says which one belongs *in front*.
//
// **C-02: nothing here shows a figure from an assumption without the id of the set it came from.** The
// Befund projects nothing, so `assumptions.any_figure_derived_from_an_assumption` is `false` and no fact
// carries a `source` of `assumption` today. The branch is written anyway and is checked by a test that
// plants such a fact: the day a section starts reporting a derived figure, the id renders with it rather
// than the constraint being noticed afterwards.
//
// **C-07 / R-113: nothing is counted.** Not the sections, not the facts, not how much of the report is
// filled in. The service counts nothing and says why: naming three empty cells is a list, telling a member
// "3 of 8" is a score. There is no count in this file, no total, and no key in the string table for one.
//
// **R-175: opening the screen is the whole of the trigger.** One GET, no polling, no refresh timer, and
// nothing written back. The report says so about itself in `delivered_on_request_only`, and
// `befund.on_request` says it to the member.

import { announce, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getBefund } from '../app/api.js';

/**
 * A `31.08.2026` from a `2026-08-31`, without a Date object.
 *
 * The service's own `_swiss_date` avoids `strftime('%d.%m.%Y')` because it is platform-dependent for the
 * day; the same trap on this side is `new Date('2026-08-31')`, which parses as UTC midnight and renders as
 * the 30th for anybody west of Greenwich. The string is already the right three numbers in the right
 * order; only the separators change, and English keeps the ISO form it reads natively.
 */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : iso;
}

/** The label for one key of `Fact.quoted`, falling back to the key so a new one appears rather than vanishing. */
function quotedLabel(key, language) {
  const label = t(`befund.quoted_${key}`, language);
  return label === `befund.quoted_${key}` ? key : label;
}

/**
 * One quoted value, by its shape. Member-authored text, so every branch ends in a text node.
 *
 * The four shapes the payload actually carries: a string (`goal_name`, `question`, `choice`, `reasoning`,
 * `title`), a list of strings (`position_labels`), a list of `{label, consequence}` (C-06's prepared
 * options, which is the member-facing half of an action item), and — for anything added later — a plain
 * object. The last branch exists so that a fifth shape renders as readable pairs instead of
 * `[object Object]`; `dom.js::h` has no `html` option and this file builds nodes, so nothing here can
 * become markup whatever a member typed.
 */
function quotedBody(value) {
  if (value === null || value === undefined || value === '') return null;

  if (Array.isArray(value)) {
    if (!value.length) return null;
    return h('ul', {}, value.map((entry) => {
      if (entry && typeof entry === 'object') {
        // C-06's shape: an option and what follows from it. The consequence is the half that makes the
        // option a decision rather than a button, so it is rendered beside the label, never dropped.
        return h('li', {}, [
          h('span', { class: 'report-option', text: String(entry.label ?? '') }),
          entry.consequence ? h('span', { text: ` — ${entry.consequence}` }) : null,
        ]);
      }
      return h('li', { text: String(entry) });
    }));
  }

  if (typeof value === 'object') {
    return h('ul', {}, Object.entries(value).map(([key, inner]) =>
      h('li', {}, [
        h('span', { class: 'report-option', text: `${key}: ` }),
        h('span', { text: String(inner) }),
      ])));
  }

  return h('p', { text: String(value), style: 'margin:0' });
}

/** One quoted entry: its label and the member's own words, as a quotation. */
function quotedNode(key, value, language) {
  const body = quotedBody(value);
  if (!body) return null;
  return h('blockquote', { class: 'report-quote' }, [
    h('span', { class: 'report-quote-label', text: quotedLabel(key, language) }),
    body,
  ]);
}

/**
 * One fact: the member's own subject, then the sentence eigentliCH composed, then everything else they wrote.
 *
 * The subject comes first because that is what `Fact.subject` is for — it names which quoted key a renderer
 * should put in front of the sentence, so that "Dieses Ziel nennt 80'000 Franken und den 30.06.2034." has
 * the goal's own name above it instead of leaving "this goal" pointing at nothing.
 */
function factNode(fact, language) {
  const quoted = fact.quoted || {};
  const subject = fact.subject && quoted[fact.subject] !== undefined
    ? quotedNode(fact.subject, quoted[fact.subject], language)
    : null;

  const others = Object.keys(quoted)
    .filter((key) => key !== fact.subject)
    .map((key) => quotedNode(key, quoted[key], language));

  return h('div', { class: 'report-fact' }, [
    subject,
    h('p', { class: 'report-sentence', text: fact.sentence }),

    // C-02. A figure derived from an assumption carries the id of the set that produced it, and the
    // service makes that a biconditional: nothing else carries one. So the stamp is rendered from
    // `source`, not from the presence of the field — a fact claiming assumption provenance with no id
    // cannot exist, and one with an id and another provenance cannot either.
    fact.source === 'assumption'
      ? h('p', {
          class: 'report-meta',
          text: `${t('befund.assumption_set', language)}: ${fact.assumption_set_id}`,
        })
      : null,

    // The model rephrased this sentence and the deterministic one travels with it. Shown, because "code
    // owns the figures and the structure, the model only writes sentences" is a claim a member should be
    // able to check rather than take. With `prose` off — the default, and this client never asks for it —
    // neither line is ever reached.
    fact.sentence_origin === 'model'
      ? h('div', {}, [
          h('p', { class: 'report-meta', text: t('befund.model_wrote', language) }),
          fact.computed_sentence
            ? h('p', {
                class: 'report-meta',
                text: `${t('befund.computed_sentence', language)}: ${fact.computed_sentence}`,
              })
            : null,
        ])
      : null,

    ...others,
  ]);
}

/**
 * One section: its server-composed title and its facts, in the order they arrived.
 *
 * The heading is `section.title` and not a string from `i18n.js`, deliberately. The six titles are written
 * in both languages inside `services/befund.py`, beside the sentences they head — the module's argument is
 * that the ordering and the wording of the report are editorial decisions belonging to the report, and a
 * second copy of them in the client's chrome table is a copy that gets edited on one side.
 */
function sectionNode(section, language) {
  const facts = section.facts || [];
  return h('section', { class: 'report-block', 'aria-labelledby': `report-${section.key}` }, [
    h('h2', { class: 'report-heading', id: `report-${section.key}`, text: section.title }),
    // The service guarantees at least one fact per section — an empty plan still gets a sentence saying
    // what would stand there (R-110). This is the honest fallback rather than a nudge to go and fill
    // something in: A87 put advice about a member's own plan inside C-01, so "Sie sollten hier etwas
    // erfassen" is a refused sentence, not a friendlier one.
    facts.length
      ? h('div', { class: 'report-facts' }, facts.map((fact) => factNode(fact, language)))
      : h('p', { class: 'cell-prompt', text: t('befund.empty_section', language) }),
  ]);
}

/**
 * A11: no member id. The report is the token's member's, and the language is a real parameter — the route
 * answers 422 for a language the report is not written in rather than falling back to German.
 */
export async function load(language) {
  return getBefund(language);
}

export function render(container, report, { language }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('befund.eyebrow', language) }),
    h('h1', { text: t('befund.title', language) }),
    h('p', { class: 'lede', text: t('befund.lede', language) }),
    // R-175, stated to the member and not only in the payload.
    h('p', { class: 'field-hint', text: t('befund.on_request', language) }),
    h('p', {
      class: 'report-meta',
      text: `${t('befund.as_of', language)}: ${readableDate(report.as_of, language)}`,
    }),
    // A member prints the plan and takes it to somebody — the print stylesheet was written for exactly
    // this, and until now nothing on screen said so. The button is removed from the printed sheet by the
    // same `button { display: none }` rule that removes every other control.
    h('div', { class: 'actions' }, [
      h('button', {
        type: 'button',
        class: 'add',
        text: t('befund.print', language),
        onClick: () => window.print(),
      }),
    ]),
  );

  const document_ = h('div', { class: 'report' });
  // The payload's order, untouched. See the module docstring: the order is the report's, not this file's.
  for (const section of report.sections || []) {
    document_.append(sectionNode(section, language));
  }
  container.append(document_);

  // C-02 at the foot of the document. The Befund derives no figure from an assumption and says so in a
  // sentence the service wrote in the member's language; if that ever becomes true, the id of the set is
  // stated here rather than being left implicit in the facts.
  const assumptions = report.assumptions || {};
  container.append(
    h('div', { class: 'known' }, [
      h('span', { class: 'lbl', text: t('befund.assumptions', language) }),
      assumptions.note ? h('p', { class: 'field-hint', text: assumptions.note }) : null,
      assumptions.any_figure_derived_from_an_assumption && assumptions.assumption_set_id
        ? h('p', {
            class: 'report-meta',
            text: `${t('befund.assumption_set', language)}: ${assumptions.assumption_set_id}`,
          })
        : null,
    ]),
  );

  announce(t('befund.announced', language));
}
