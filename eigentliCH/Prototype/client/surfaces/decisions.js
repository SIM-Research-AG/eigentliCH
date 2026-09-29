// S-07 — the decisions, rendered. **The thing §7 calls "the thing that survives a change of adviser".**
//
// **Why this file exists.** R-160 was the only identifier in the whole specification with zero references
// anywhere in the code (A90). A92 gave it three routes. Then it had a server and no screen, which is the
// exact shape of the failure the owner reported twice as "there is still no output": work finished behind
// a route nobody could reach. `api/decisions.py` is complete, guarded and tested, and until this file
// existed no member could see a single one of their own decisions.
//
// ===========================================================================================================
// THE FIVE THINGS THIS FILE IS NOT ALLOWED TO DO, AND WHERE EACH IS ENFORCED
// ===========================================================================================================
//
// **R-162: the control says "record a correction", and never "edit".** That is not a wording preference.
// `POST /api/decisions/{id}/correction` writes a NEW Decision with `corrects_id` set; the prior row is
// refused an UPDATE by `db.py::before_flush` and again by the `trg_decisions_no_update` trigger. A button
// labelled "edit" would promise something the storage layer refuses, and the member would reasonably
// conclude their earlier record had been replaced — which is the one reading R-040 exists to prevent. The
// string is `decisions.correct` in both languages, `api.js` has no function named `editDecision`, and a
// test asserts no client file contains the word next to a decision.
//
// **The chain reads oldest first, and this file does not sort it.** The service orders by lineage depth —
// not by the clock, because three decisions written inside one microsecond tie on `created_at` and fall
// through to a random hex id, which made a member's correction history reshuffle between two page loads
// (A96). `chain.records` arrives in the right order and is iterated. A client that sorted by timestamp
// would put the defect back on the one screen it was found on.
//
// **A member's own words are quoted, never composed into a sentence.** `quoted` holds the question, the
// choice, the reasoning and C-06's weighed options, all typed by the member or by a curator; `sentence` is
// what eigentliCH says about the record and has passed C-01's outbound gate in `Fact.__post_init__`. The
// service keeps them in two fields precisely so that a renderer cannot join them, and the reason is not
// squeamishness: a member whose reasoning reads "ich sollte mehr sparen" would otherwise make their own
// record unrenderable, because the gate would refuse a sentence they wrote. So every quoted value is a
// `<blockquote>` with its own label, outside the sentence. `subject` only says which one goes in front.
//
// **C-07 / R-113: nothing is counted.** Not the decisions, not the corrections, not the chain's length.
// `is_part_of_a_chain` is a boolean for exactly this reason — so a client can say "there is a chain"
// without counting it. S-07 is the screen a completion figure would ruin most, because a record of what
// somebody decided is not a quantity.
//
// **C-04: a vault link is an id and nothing else.** A `VaultItem` is K3 entity-wide, so carrying even its
// `kind` here would raise this whole payload from K2 to K3 — the Befund makes the identical call. The
// screen says so in a sentence rather than rendering a bare hex string with no explanation, and points at
// the vault, which is classified and store-guarded for the document itself.
//
// **R-110 in the empty state, and no nudge in it.** The service distinguishes "nothing recorded" from "the
// filter matched nothing" and carries its own sentence only for the first. The second is worded here,
// beside the control that set the filter, and it states what is there rather than suggesting an action:
// A87 and A92 put advice about a member's own plan and their own decisions inside C-01, so
// "Sie sollten hier etwas festhalten" is a refused sentence and not a friendlier one.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { detailText, getDecision, getDecisions, recordCorrection } from '../app/api.js';

/**
 * A `31.08.2026` from a `2026-08-31`, without a Date object — `befund.js` carries the same helper and the
 * same reason: `new Date('2026-08-31')` parses as UTC midnight and renders as the 30th west of Greenwich.
 */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : iso;
}

/** The label for one key of `quoted`, falling back to the key so a new one appears rather than vanishing. */
function quotedLabel(key, language) {
  const label = t(`decisions.quoted_${key}`, language);
  return label === `decisions.quoted_${key}` ? key : label;
}

/**
 * One quoted value as a quotation. Member-authored text, so every branch ends in a text node.
 *
 * Three shapes arrive: a string (`question`, `choice`, `reasoning`), a list of `{label, consequence}` —
 * C-06's weighed options, which `read_decision` adds and the list route omits — and, for anything added
 * later, a plain object rendered as readable pairs rather than `[object Object]`. `dom.js::h` has no
 * `html` option, so nothing here can become markup whatever the member typed.
 */
function quotedBody(value) {
  if (value === null || value === undefined || value === '') return null;

  if (Array.isArray(value)) {
    if (!value.length) return null;
    return h('ul', {}, value.map((entry) => {
      if (entry && typeof entry === 'object') {
        // C-06: an option and what follows from it. The consequence is the half that makes it a decision
        // rather than a button, so it is rendered beside the label and never dropped.
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

function quotedNode(key, value, language) {
  const body = quotedBody(value);
  if (!body) return null;
  return h('blockquote', { class: 'report-quote' }, [
    h('span', { class: 'report-quote-label', text: quotedLabel(key, language) }),
    body,
  ]);
}

/**
 * R-161's first clause: who recorded this, and whether a curator was involved.
 *
 * **Two separate statements, because the payload distinguishes two situations and the Befund cannot.**
 * `author` is who wrote it; `curator_involved` is also true when the *member* wrote it while sitting in a
 * curator session, which is the case `services/befund.py` drops entirely. R-212 wants an attribution
 * rather than "a curator", so `author_ref` is rendered when there is one.
 */
function attributionNodes(record, language) {
  const key = { member: 'author_member', curator: 'author_curator' }[record.author] || 'author_system';
  return [
    h('p', { class: 'report-meta', text: t(`decisions.${key}`, language) }),
    record.curator_involved
      ? h('p', {
          class: 'report-meta',
          text: record.author_ref
            ? `${t('decisions.curator_involved', language)} ${t('decisions.curator_ref', language)}: ${record.author_ref}`
            : t('decisions.curator_involved', language),
        })
      : null,
  ];
}

/**
 * R-040's chain, stated on the record rather than left to a client to derive from two id lists.
 *
 * Both directions: this record corrects an earlier one, and/or a later one corrects this. Neither is a
 * count — `was_corrected` is a boolean and `corrected_by_ids` is used only to link, never to number.
 */
function lineageNodes(record, language) {
  return [
    record.is_correction
      ? h('p', { class: 'report-meta', text: t('decisions.is_correction', language) })
      : null,
    record.was_corrected
      ? h('p', { class: 'report-meta', text: t('decisions.was_corrected', language) })
      : null,
  ];
}

/**
 * One record: the member's own subject first, then the sentence eigentliCH composed, then the rest of their
 * words.
 *
 * The subject comes first because that is what `subject` is for — the service says which quoted key
 * belongs in front, and for a decision that is the question, so "Am 31.08.2026 haben Sie eine Entscheidung
 * festgehalten" has the question it answered above it instead of standing alone.
 */
function recordNode(record, language, { open = null, emphasise = false } = {}) {
  const quoted = record.quoted || {};
  const subject = record.subject && quoted[record.subject] !== undefined
    ? quotedNode(record.subject, quoted[record.subject], language)
    : null;
  const others = Object.keys(quoted)
    .filter((key) => key !== record.subject)
    .map((key) => quotedNode(key, quoted[key], language));

  return h('div', {
    class: 'report-fact decision-record',
    // A statement about which record was asked for, not a decoration: on the chain view it is how a member
    // finds the one they arrived from. Rendered as an attribute AND as a label below, because a border
    // alone would be a state visible only in colour (1.4.1).
    'data-asked-for': emphasise ? 'true' : null,
  }, [
    emphasise ? h('span', { class: 'lbl', text: t('decisions.chain_this_one', language) }) : null,
    subject,
    h('p', { class: 'report-sentence', text: record.sentence }),
    h('p', {
      class: 'report-meta',
      text: `${t('decisions.recorded_on', language)}: ${readableDate(record.recorded_on, language)}`,
    }),
    ...attributionNodes(record, language),
    ...lineageNodes(record, language),
    ...others,
    open
      ? h('div', { class: 'actions' }, [
          button(t('decisions.open', language), { class: 'add', onClick: () => open(record.id) }),
        ])
      : null,
  ]);
}

// ---------------------------------------------------------------- the list (R-160)

/**
 * A11: no member id. The decisions are the token's member's, and the filters name what they touched.
 *
 * A filter naming a position that is not this member's comes back as an empty list rather than a refusal,
 * because the query is scoped to the member before the filter is applied — so this surface never has to
 * distinguish "not yours" from "no such thing", and cannot be used to find out which.
 */
export function load(language, filters = {}) {
  return getDecisions({ language, ...filters });
}

export function loadOne(decisionId, language) {
  return getDecision(decisionId, language);
}

/**
 * The filters in force, and the way out of them.
 *
 * **Rendered from `payload.filters`, which is the server's echo of what it applied** — not from whatever
 * this client believes it asked for. Those can differ (a stale hash, a hand-typed URL), and a screen
 * showing a filter it is not actually under is worse than one showing none.
 */
function filterNode(payload, language, { onFilter }) {
  const filters = payload.filters || {};
  const active = Object.entries({
    position_id: 'filter_position',
    goal_id: 'filter_goal',
    vault_item_id: 'filter_vault_item',
  }).filter(([field]) => filters[field]);

  if (!active.length) return null;

  return h('div', { class: 'known' }, [
    h('span', { class: 'lbl', text: t('decisions.filter_heading', language) }),
    ...active.map(([field, key]) =>
      h('p', { class: 'report-meta', text: `${t(`decisions.${key}`, language)}: ${filters[field]}` })),
    h('div', { class: 'actions' }, [
      button(t('decisions.filter_clear', language), { class: 'add', onClick: () => onFilter({}) }),
    ]),
  ]);
}

export function render(container, payload, { language, onOpen, onFilter }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('decisions.eyebrow', language) }),
    h('h1', { text: t('decisions.title', language) }),
    h('p', { class: 'lede', text: t('decisions.lede', language) }),
    // The service states its own order in `order`, so this is read rather than assumed. The list is newest
    // first and the chain is oldest first, and both are deliberate — see `list_decisions`.
    h('p', {
      class: 'field-hint',
      text: payload.order === 'newest_first' ? t('decisions.newest_first', language) : '',
    }),
  );

  const filters = filterNode(payload, language, { onFilter });
  if (filters) container.append(filters);

  const records = payload.decisions || [];

  if (!records.length) {
    // Two empty states, and the distinction is the service's. Only the first has a server-authored
    // sentence: the Befund's "nothing has been recorded yet" is true of an empty record and false of a
    // filter that matched none of it, so the second is worded in this client's own table — beside the
    // control that set the filter, which is where it belongs.
    container.append(
      h('p', {
        class: 'cell-prompt',
        text: payload.empty_reason === 'no_decision_matched_the_filter'
          ? t('decisions.filtered_none', language)
          : payload.empty_sentence || '',
      }),
    );
    announce(t('decisions.announced', language));
    return;
  }

  // The payload's order, untouched.
  container.append(
    h('div', { class: 'report' },
      records.map((record) => recordNode(record, language, { open: onOpen }))),
  );

  announce(t('decisions.announced', language));
}

// ---------------------------------------------------------------- one decision and its chain (R-161)

/**
 * What this decision touched.
 *
 * Positions and goals carry their member-authored names, because they are K2 — the same class as the
 * decision. **Vault items are ids only**, and the screen says why rather than showing a hex string with
 * nothing beside it: the document is K3 as a whole and lives behind the vault route, which is classified
 * and store-guarded for it.
 *
 * Each position and goal is a filter, because arriving at S-07 from a position and then wanting only that
 * position's history is the question a member actually asks.
 */
function linkedNode(linked, language, { onFilter }) {
  const positions = linked.positions || [];
  const goals = linked.goals || [];
  const vaultIds = linked.vault_item_ids || [];
  if (!positions.length && !goals.length && !vaultIds.length) return null;

  return h('div', { class: 'known' }, [
    h('span', { class: 'lbl', text: t('decisions.linked_heading', language) }),

    positions.length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('decisions.linked_positions', language) }),
          ...positions.map((position) => h('div', { class: 'decision-link' }, [
            // The member's own label, quoted rather than folded into a sentence — the same rule as
            // everywhere else on this screen.
            h('blockquote', { class: 'report-quote' }, [
              h('p', { text: position.quoted.label, style: 'margin:0' }),
            ]),
            button(t('decisions.filter_position', language), {
              class: 'add',
              onClick: () => onFilter({ positionId: position.id }),
            }),
          ])),
        ])
      : null,

    goals.length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('decisions.linked_goals', language) }),
          ...goals.map((goal) => h('div', { class: 'decision-link' }, [
            h('blockquote', { class: 'report-quote' }, [
              h('p', { text: goal.quoted.name, style: 'margin:0' }),
            ]),
            button(t('decisions.filter_goal', language), {
              class: 'add',
              onClick: () => onFilter({ goalId: goal.id }),
            }),
          ])),
        ])
      : null,

    vaultIds.length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('decisions.linked_vault_items', language) }),
          // C-04, said to the member. The id is shown because it is what the payload carries and hiding it
          // would leave the link unusable; the sentence says why there is no title.
          h('p', { class: 'field-hint', text: t('decisions.vault_item_id_only', language) }),
          ...vaultIds.map((id) => h('div', { class: 'decision-link' }, [
            h('span', { class: 'report-meta', text: id }),
            button(t('decisions.filter_vault_item', language), {
              class: 'add',
              onClick: () => onFilter({ vaultItemId: id }),
            }),
          ])),
        ])
      : null,
  ]);
}

/**
 * R-162's form. **A correction, and there is no version of this that edits anything.**
 *
 * No question field: R-040 makes the question that stood part of what stood, and `record_correction`
 * copies it. A correction answers the same question differently rather than quietly becoming a record of
 * a different question having been asked — so the question is shown, as the member's own words, and is not
 * editable.
 */
function correctionForm(decisionId, priorQuoted, language, { onCorrected }) {
  const choice = h('input', { type: 'text', name: 'choice', maxlength: '300', required: '' });
  const reasoning = h('textarea', { name: 'reasoning', rows: '3' });
  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('decisions.correct_save', language)]);

  const form = h('form', {
    class: 'position-form',
    hidden: '',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      const stated = choice.value.trim();
      if (!stated) {
        // The server refuses a blank choice too, in R-040's own terms. Asked here first because a member
        // who has typed nothing deserves the question rather than a constraint's sentence.
        error.textContent = t('decisions.correct_choice_missing', language);
        error.removeAttribute('hidden');
        choice.focus();
        return;
      }
      submit.disabled = true;
      try {
        await recordCorrection(
          decisionId,
          { choice: stated, reasoning: reasoning.value.trim() || null },
          language,
        );
        onCorrected();
      } catch (failure) {
        // The server's refusal as it was written — including the one that says a correction stating the
        // same choice and the same reasoning is not written, which is a sentence worth reading.
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('h2', { text: t('decisions.correct_heading', language) }),
    h('p', { class: 'field-hint', text: t('decisions.correct_hint', language) }),
    // The question that stood, quoted and not editable. It is part of the permanent record.
    priorQuoted && priorQuoted.question
      ? quotedNode('question', priorQuoted.question, language)
      : null,
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('decisions.correct_choice', language) }),
      choice,
    ]),
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('decisions.correct_reasoning', language) }),
      reasoning,
    ]),
    error,
    h('div', { class: 'actions' }, [submit]),
  ]);

  // A door rather than a form standing open. R-040 makes what this writes permanent, so it is one
  // deliberate press away rather than a text field sitting under every record.
  const opener = button(t('decisions.correct', language), {
    class: 'add',
    'aria-expanded': 'false',
    onClick: (event) => {
      const opening = form.hasAttribute('hidden');
      if (opening) form.removeAttribute('hidden');
      else form.setAttribute('hidden', '');
      event.currentTarget.setAttribute('aria-expanded', String(opening));
      if (opening) choice.focus();
    },
  });

  return h('div', { class: 'known' }, [opener, form]);
}

export function renderOne(container, payload, { language, onBack, onCorrected, onFilter }) {
  clear(container);
  const record = payload.decision;
  const chain = payload.chain || { records: [] };

  container.append(
    h('span', { class: 'lbl', text: t('decisions.eyebrow', language) }),
    h('h1', { text: t('decisions.title', language) }),
    h('div', { class: 'actions' }, [
      button(t('decisions.back', language), { class: 'add', onClick: onBack }),
    ]),
  );

  container.append(h('div', { class: 'report' }, [recordNode(record, language)]));

  const linked = linkedNode(payload.linked || {}, language, { onFilter });
  if (linked) container.append(linked);

  // R-040's lineage. **Oldest first, in the order the service returned**, which is by depth through
  // `corrects_id` rather than by the clock — see the module docstring and A96.
  container.append(
    h('div', { class: 'known' }, [
      h('h2', { text: t('decisions.chain_heading', language) }),
      chain.is_part_of_a_chain
        ? h('p', { class: 'field-hint', text: t('decisions.chain_oldest_first', language) })
        : h('p', { class: 'cell-prompt', text: t('decisions.chain_single', language) }),
      chain.is_part_of_a_chain
        ? h('div', { class: 'report decision-chain' },
            (chain.records || []).map((entry) =>
              recordNode(entry, language, { emphasise: entry.is_the_one_asked_for })))
        : null,
    ]),
  );

  container.append(correctionForm(record.id, record.quoted, language, { onCorrected }));

  announce(t('decisions.announced_one', language));
}
