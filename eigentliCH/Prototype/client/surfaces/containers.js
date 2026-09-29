// S-04 — Containers. What each franc is for.
//
// **R-130 is the hardest thing on this screen to get right, and it is a wording problem.** Goals do not
// partition holdings: the same position may carry several goals and nothing is divided up. Every visual
// convention available — a card per goal, a figure under each name, a column of amounts — quietly says
// "account", so this file says the opposite out loud in three places: once as the surface's own lede, once
// on every funding position that also carries another goal, and once as an observation the server itself
// returns. A member who reads any one of the three has been told.
//
// **R-031 / A45: the observations are statements of fact.** They carry no severity, no colour, no icon and
// no dismiss control, because there is nothing to dismiss — a fact about a member's own plan is not an
// alert about it. They are rendered in the same ink as everything else, deliberately.
//
// **R-133 / C-02: there IS a projection now, and where there is not, the reason is named.** This comment
// used to read "`illustration` is null and `illustration_unavailable_reason` says why", and it had stopped
// being true: `services/illustration.py` returns a real illustration for any goal with an amount and active
// funding, and every reason it returns is derived. This file went on printing `illustration_none` plus a
// reason unconditionally, so two things were wrong at once — the projections that had been built were
// invisible where they existed, and where they genuinely did not exist, five of the six reasons had no
// string in the table and rendered as their own key.
//
// **What the illustration is allowed to say, and the two lines that keep it honest.** The published set
// estimates its rates for ONE year and nothing extends them; a goal's date is usually years further out.
// Both numbers are rendered, side by side, with `rates_extended_to_the_goal_horizon: false` said as a
// sentence — a screen that showed the goal's date above a one-year range would be C-02's violation dressed
// as a courtesy. And the scenario probabilities are printed **beside** the rates exactly as published:
// nothing here multiplies them together, because which probabilities weight which horizon is a decision
// with an owner (A69), and a weighted average on this screen would quietly take it.
//
// **R-131: all five parameters, always.** A parameter that is unanswered is shown as unanswered rather than
// omitted — a missing row and an unanswered question are different facts, and the payload keeps them apart
// on purpose.
//
// **R-113 / R-006: no total, no funded percentage, no "on track", no bar.** The payload carries none of the
// numbers one would be built from, and nothing here counts them up either.
//
// **A goal can be changed after it is named** — added 31 August 2026, because it could not be, and the
// owner found that by trying. `editForm` below is that screen and carries the reasoning that belongs on
// this side of the wire; `services/goals.revise_goal` carries the reasoning about what changing a goal does
// to the record, which is the part that had to be decided rather than built.

import { announce, clear, formatAmount, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getGoals, getRoleGrid, createGoal, reviseGoal, ApiError } from '../app/api.js';

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

/**
 * The template select, with a placeholder that carries no value.
 *
 * **Nothing is preselected, and that is the whole reason this is a function.** There were two templates
 * until 31 August 2026; there are nine, and whichever one is first in the list would otherwise be assigned
 * to every goal named by a member who never opened the control. `GOAL_TEMPLATES` puts Frühpensionierung
 * first at the owner's request, which makes the placeholder load-bearing rather than tidy.
 *
 * An empty value means no template, which is what `Goal.template` being nullable already meant and what
 * every goal named before the templates existed carries.
 */
function templateSelect(templates, language, { name = 'template', selected = null } = {}) {
  const control = h('select', { name }, [
    h('option', { value: '', text: t('containers.template_choose', language) }),
    ...templates.map((record) =>
      h('option', {
        value: record.key,
        selected: record.key === selected ? '' : null,
        text: (record[language] && record[language].name) || t('containers.template_unnamed', language),
      }),
    ),
  ]);
  if (!selected) control.value = '';
  return control;
}

/** The template's own sentence, shown under the select and rewritten as the choice changes. */
function templatePurpose(control, templates, language) {
  const purpose = h('p', { class: 'field-hint' });
  function show() {
    const record = templates.find((entry) => entry.key === control.value);
    purpose.textContent = record && record[language] ? record[language].purpose : '';
  }
  control.addEventListener('change', show);
  show();
  return purpose;
}

/** A liquidity band, or the fact that the member has not stated one. Never guessed — A45. */
function liquidityLabel(band, language) {
  return band ? t(`containers.liquidity_${band}`, language) : t('containers.liquidity_unstated', language);
}

/**
 * R-031. One observation, as a sentence.
 *
 * The `kind` is translated; the payload's own identifiers are the fallback, so an observation kind added
 * to the service later shows up as an untranslated line rather than disappearing from the screen.
 */
function observationNode(observation, language) {
  const text = t(`containers.obs_${observation.kind}`, language, {
    date: observation.target_date || '',
  });
  return h('li', {
    text: text === `containers.obs_${observation.kind}` ? observation.kind : text,
    style: 'margin-top:var(--sp-xs)',
  });
}

/** R-130. The sentence that keeps a funding position from reading as a balance in this goal's account. */
function fundingNode(position, language) {
  const shared = position.also_funds_goal_count;

  return h('div', { class: 'position' }, [
    h('div', { class: 'position-label', text: position.label }),
    h('div', { class: 'position-meta', text: liquidityLabel(position.liquidity, language) }),
    shared > 0
      ? h('div', {
          class: 'position-meta',
          text: shared === 1
            ? t('containers.also_carries_one', language)
            : t('containers.also_carries_many', language, { n: shared }),
        })
      : null,
  ]);
}

// ---------------------------------------------------------------- R-133 / C-02: the illustration

/** The Swiss locale tag for a language. One place, so the figures and the rates cannot disagree. */
function locale(language) {
  return language === 'de' ? 'de-CH' : 'en-CH';
}

/**
 * A rate as a percentage.
 *
 * `services/illustration.py` copies the rate out of the published set and deliberately does **not** round
 * it: "rounding is a transformation, and the client is the layer that formats". This is that layer. One
 * decimal place, because the difference between -35.8% and -35.9% is not a difference a member acts on and
 * the full 17 digits of a float are noise that reads as false precision.
 */
function formatRate(value, language) {
  if (typeof value !== 'number') return null;
  return new Intl.NumberFormat(locale(language), {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(value);
}

/** A franc change, with its sign stated. A gain that renders as `4'800` reads as a balance, not a change. */
function formatChange(value, language) {
  if (typeof value !== 'number') return null;
  const figure = formatAmount(value, locale(language));
  return value > 0 ? `+${figure}` : figure;
}

/** A scenario's own name, falling back to the payload's identifier so a new scenario appears rather than vanishing. */
function scenarioLabel(name, language) {
  const label = t(`containers.scenario_${name}`, language);
  return label === `containers.scenario_${name}` ? name : label;
}

/**
 * The two horizons, stated as two facts.
 *
 * **This is the C-02 line on this screen.** `horizon.published_years` is what the set estimated (one year)
 * and `horizon.goal_years` is how far away the member's own date is; `rates_extended_to_the_goal_horizon` is
 * `false` and never anything else. Rendering the goal's date beside a one-year range without saying so would
 * be showing a member a figure their date does not reach — which is the whole reason the payload carries
 * both numbers instead of one.
 */
function horizonNodes(horizon, language) {
  const published = horizon.published_years;
  const nodes = [
    h('p', {
      text: published === 1
        ? t('containers.illustration_horizon_one_year', language)
        : t('containers.illustration_horizon_years', language, {
            years: new Intl.NumberFormat(locale(language), { maximumFractionDigits: 1 })
              .format(published),
          }),
    }),
  ];
  if (typeof horizon.goal_years === 'number') {
    nodes.push(h('p', {
      text: t('containers.illustration_goal_horizon', language, {
        years: new Intl.NumberFormat(locale(language), { maximumFractionDigits: 1 })
          .format(horizon.goal_years),
      }),
    }));
    // Never true in the payload, and said as a sentence rather than left to the caveat list.
    if (!horizon.rates_extended_to_the_goal_horizon) {
      nodes.push(h('p', { text: t('containers.illustration_not_extended', language) }));
    }
  } else {
    nodes.push(h('p', { class: 'field-hint', text: t('containers.illustration_no_goal_date', language) }));
  }
  return nodes;
}

/**
 * One role's range of outcomes, as a table.
 *
 * A table rather than a list of sentences because these are five rows of four figures and a member is
 * comparing down the columns. `<th scope>` on both axes is what makes that readable to a screen reader
 * instead of twenty unlabelled numbers.
 *
 * **The published probability is a column, not a weight.** It sits beside the rate exactly as the set
 * publishes it, and no cell in this table is a product of the two — see the surface's own header comment
 * and A69. `name` is the role's member-facing name, resolved by `roleDisplayName` below from the grid
 * payload where the role definitions live (K0, D-03); the assumption set's own name for the same role is
 * stated beneath it, because the two vocabularies genuinely differ and a reader should be able to see that
 * a translation happened.
 */
function roleNode(entry, language, name) {
  const columns = [
    t('containers.illustration_scenario', language),
    t('containers.illustration_rate', language),
    t('containers.illustration_change', language),
    t('containers.illustration_after', language),
    t('containers.illustration_probability', language),
  ];

  return h('div', { class: 'illustration-role' }, [
    h('div', { class: 'position-label', text: `${t('containers.illustration_role', language)}: ${name}` }),
    h('div', {
      class: 'position-meta',
      text: t('containers.illustration_set_role', language, { name: entry.assumption_set_role }),
    }),
    h('div', {
      class: 'position-meta',
      text: entry.positions_naming_this_role === 1
        ? t('containers.illustration_one_position_names_role', language)
        : t('containers.illustration_n_positions_name_role', language, {
            n: entry.positions_naming_this_role,
          }),
    }),
    // WCAG 2.1.1: the box scrolls sideways on a narrow screen, and a region that can only be reached by
    // dragging cannot be reached by keyboard at all. `tabindex="0"` puts it in the tab order, the group
    // label says which role's figures are inside it, and `app.css` gives it a visible focus ring.
    h('div', {
      class: 'figures-scroll',
      tabindex: '0',
      role: 'group',
      'aria-label': `${t('containers.illustration_role', language)}: ${name}`,
    }, [
      h('table', { class: 'figures' }, [
        h('thead', {}, [
          h('tr', {}, columns.map((label) => h('th', { scope: 'col', text: label }))),
        ]),
        h('tbody', {}, entry.scenarios.map((row) =>
          h('tr', {}, [
            h('th', { scope: 'row', text: scenarioLabel(row.scenario, language) }),
            h('td', { text: formatRate(row.rate, language) }),
            h('td', { text: formatChange(row.change_chf, language) }),
            h('td', { text: formatAmount(row.amount_after_the_horizon_chf, locale(language)) }),
            h('td', {
              text: typeof row.probability_as_published === 'number'
                ? formatRate(row.probability_as_published, language)
                : t('containers.illustration_probability_unstated', language),
            }),
          ]))),
      ]),
    ]),
  ]);
}

/**
 * The member-facing name of a plan role, for this goal's funding.
 *
 * The grid names a role differently per kind of capital — the same `growth` is "Wertsteigerung" financially
 * and "Wachstum" for human capital — and the illustration groups by the plan role across both. So the name
 * is resolved from the kinds of capital that actually fund *this* goal in *this* role: one of them normally,
 * both where the member funds a goal from both, and the bare identifier if the grid could not be read.
 * Picking one of the two arbitrarily would rename half the member's plan on this screen.
 */
function roleDisplayName(goal, role, roles) {
  const kinds = [];
  for (const position of goal.funded_by || []) {
    if (position.role === role && !kinds.includes(position.capital_type)) {
      kinds.push(position.capital_type);
    }
  }
  const names = kinds.map((kind) => roles[`${role}|${kind}`]).filter(Boolean);
  return names.length ? names.join(' / ') : role;
}

/**
 * The whole illustration, or the true reason there is not one.
 *
 * The unavailable branch is what this file used to render unconditionally. It is still here, because an
 * absent illustration is a fact with a reason and silence would read as "nothing to show" — but it is now
 * reached only when `illustration` is actually null, and all six reasons have a sentence.
 */
/**
 * Principle 9. The positions a goal is funded by that no rate was applied to, named.
 *
 * **On every path, illustrated or not**, because `services/illustration.py` puts
 * `excluded_from_the_projection` on every return path for exactly that reason: a client that had to infer
 * "nothing was excluded" from a missing key would be inferring from an absence. Rendered beside the
 * figures rather than instead of them — a goal funded by both kinds of capital gets its illustration *and*
 * this list, and reading the figures without reading what they left out is the misunderstanding the key
 * exists to prevent.
 *
 * **Excluded, never zeroed, and the sentence says so.** A zero rate would be a published claim that a
 * salary is expected not to move, and nobody published one.
 */
function exclusionsNode(goal, language) {
  const excluded = goal.excluded_from_the_projection || [];
  if (!excluded.length) return null;

  // One line per distinct reason, not per position: the reason is the fact, and repeating one sentence
  // once per salary would read as a list of problems rather than as one statement about the arithmetic.
  const reasons = [...new Set(excluded.map((entry) => entry.reason))];

  return h('div', { class: 'field' }, [
    h('span', { class: 'lbl', text: t('containers.excluded_heading', language) }),
    h('ul', { style: 'margin:0; padding-left:1.2em' }, reasons.map((reason) => {
      const said = t(`containers.excluded_${reason}`, language);
      return h('li', { text: said === `containers.excluded_${reason}` ? reason : said });
    })),
  ]);
}

function illustrationNode(goal, language, roles) {
  const illustration = goal.illustration;
  if (!illustration) {
    const reason = t(`containers.illustration_${goal.illustration_unavailable_reason}`, language);
    return h('div', {}, [
      h('p', {
        class: 'field-hint',
        text: `${t('containers.illustration_none', language)} `
          + (reason === `containers.illustration_${goal.illustration_unavailable_reason}`
            ? goal.illustration_unavailable_reason
            : reason),
      }),
      exclusionsNode(goal, language),
    ]);
  }

  const basis = illustration.basis || {};
  const unit = t(`containers.illustration_unit_${illustration.values_unit}`, language);

  return h('div', { class: 'illustration' }, [
    h('span', { class: 'lbl', text: t('containers.illustration_heading', language) }),
    h('p', { class: 'field-hint', text: t('containers.illustration_lede', language) }),

    // C-02, first and not last: "every illustration response returns the assumption_set_id used", and a
    // member has to be able to see which published set a figure came from before they read the figure.
    h('p', {
      class: 'report-meta',
      text: `${t('containers.illustration_assumption_set', language)}: `
        + `${illustration.assumption_set_version} (${illustration.assumption_set_id})`,
    }),
    h('p', {
      class: 'report-meta',
      text: `${t('containers.illustration_effective_from', language)}: `
        + `${illustration.assumption_set_effective_from}`,
    }),
    illustration.published_by
      ? h('p', {
          class: 'report-meta',
          text: `${t('containers.illustration_published_by', language)}: ${illustration.published_by}`,
        })
      : null,

    h('div', { class: 'position-magnitude',
      text: `${t('containers.illustration_basis', language)}: `
        + `${formatAmount(basis.amount_chf, locale(language))} CHF` }),
    h('p', { class: 'field-hint', text: t('containers.illustration_basis_note', language) }),
    // Principle 9, stated positively where the figure is rather than only as an absence further down. The
    // service puts `capital_types_projected` inside the basis block for exactly this reason: a reader
    // looking at the number should be able to see which inputs produced it without scrolling to find out
    // which ones did not.
    (basis.capital_types_projected || []).length
      ? h('p', {
          class: 'report-meta',
          text: `${t('containers.illustration_projected_on', language)}: `
            + basis.capital_types_projected
              .map((kind) => t(`capital.${kind}`, language)).join(', '),
        })
      : null,

    h('div', { class: 'field' }, [
      h('span', { class: 'lbl', text: t('containers.illustration_horizon', language) }),
      ...horizonNodes(illustration.horizon || {}, language),
      unit === `containers.illustration_unit_${illustration.values_unit}`
        ? null
        : h('p', { class: 'field-hint', text: unit }),
    ]),

    ...(illustration.by_role || []).map((entry) =>
      roleNode(entry, language, roleDisplayName(goal, entry.role, roles))),

    // A69, in front of the member rather than only in the service's docstring.
    h('p', { class: 'field-hint', text: t('containers.illustration_probability_note', language) }),

    // Principle 9, beside the figures rather than instead of them.
    exclusionsNode(goal, language),

    h('div', { class: 'field' }, [
      h('span', { class: 'lbl', text: t('containers.illustration_caveats', language) }),
      h('ul', {}, (illustration.caveats || []).map((key) => {
        const said = t(`containers.caveat_${key}`, language);
        return h('li', { text: said === `containers.caveat_${key}` ? key : said });
      })),
    ]),

    // Why there is no line through the years. The gap list is the service's, verbatim: the reasons in
    // `services/engine_inputs.py` are the considered ones, and the member-facing sentence for each input is
    // in the string table beside every other string. An input nobody has written one for shows its own
    // declared name rather than disappearing — the reason `test_every_illustration_gap_has_a_client_string`
    // exists is that disappearing is the failure that looks like success.
    (illustration.no_trajectory_because || []).length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'lbl', text: t('containers.illustration_no_trajectory', language) }),
          h('p', { class: 'field-hint', text: t('containers.illustration_no_trajectory_lede', language) }),
          h('ul', {}, illustration.no_trajectory_because.map((gap) => {
            const said = t(`gap.input_${gap.input}`, language);
            const kind = t(`gap.kind_${gap.kind}`, language);
            return h('li', {}, [
              h('span', { text: said === `gap.input_${gap.input}` ? gap.input : said }),
              kind === `gap.kind_${gap.kind}`
                ? null
                : h('span', { class: 'position-meta', text: ` — ${kind}` }),
            ]);
          })),
        ])
      : null,
  ]);
}

// ---------------------------------------------------------------- the occupancy question

/**
 * The property finding, and the one question that unblocks it.
 *
 * **This control exists because `services/property.py` could answer nothing without it.** The two tests
 * were built on 4 September, the route took `occupancy` the same day, and the client never rendered the
 * question — so five real property goals sat at `could_not_be_determined` for a reason no member could
 * see or fix. That is the shape A137 warned about: a capability with no way in is indistinguishable from
 * an absent one.
 *
 * **The options come from the content record, never from this file.** `occupancy_options` travels on the
 * goal payload with its own `de`/`en` labels, because the set of occupancies is a published convention
 * (`property-funding.json`) and a client that spelled them itself would be a second copy of a regulated
 * vocabulary — R-154's shape.
 *
 * **The record's `why` is deliberately NOT rendered.** It is English, written for a reader of the record
 * rather than for a member, and it explains a lending rule rather than answering the member's question.
 * What a member reads here is authored in the string table in their own language.
 *
 * **Clearing is offered as an option, not hidden.** `check_occupancy(None)` is a real answer that puts the
 * goal back to unanswered, and a member who chose wrongly needs that without deleting the goal.
 *
 * R-031 holds: no severity class, no icon, no dismiss. A verdict is a line of body text.
 */
function occupancyNode(goal, language, { onAnswered }) {
  const property = goal.property;
  if (!property) return null;

  const options = property.occupancy_options || [];
  const answered = property.occupancy;
  const label = (option) => (option.label && option.label[language]) || option.label?.en || option.value;
  const chosen = options.find((option) => option.value === answered);

  let busy = false;
  const error = h('p', { class: 'field-hint' });

  async function answer(value, choiceText) {
    if (busy) return;
    busy = true;
    error.textContent = '';
    try {
      // The same route the edit form uses. `occupancy: null` clears, which the server treats as an answer
      // rather than as a missing field -- see `goals.check_occupancy`.
      //
      // **`question` and `choice` are required, and composing them here is the right call rather than a
      // shortcut.** C-09 makes every plan mutation produce a Decision, and the route deliberately refuses
      // to write that sentence itself -- the edit form asks the member to type both. Asking someone to
      // type a decision sentence to answer a one-tap question would put the friction in the wrong place,
      // so the sentence is composed from **the exact words the member was shown and tapped**: the question
      // as it appears above the buttons, and the option's own label from the content record. That is a
      // faithful record of what they did, in words they actually read, which is what C-09 is protecting.
      await reviseGoal(goal.id, {
        occupancy: value,
        question: t('containers.property_question', language),
        choice: choiceText,
      });
      announce(t('containers.property_recorded', language));
      await onAnswered();
    } catch (failure) {
      busy = false;
      error.textContent = failure instanceof ApiError
        ? failure.message
        : t('containers.property_failed', language);
    }
  }

  const reasons = (property.undetermined_because || []).map((reason) => {
    const text = t(`containers.property_because_${reason}`, language);
    return h('li', { text: text === `containers.property_because_${reason}` ? reason : text,
                     style: 'margin-top:var(--sp-xs)' });
  });

  return h('div', { class: 'field' }, [
    h('span', { class: 'lbl', text: t('containers.property', language) }),

    h('p', {
      class: 'position-meta',
      text: t(`containers.property_verdict_${property.verdict}`, language),
    }),

    // What the member has answered, or the question. Never both.
    answered
      ? h('div', { class: 'position' }, [
          h('div', { class: 'position-label', text: t('containers.property_your_answer', language) }),
          h('div', { class: 'position-meta', text: chosen ? label(chosen) : answered }),
        ])
      : h('p', { class: 'cell-prompt', text: t('containers.property_question_hint', language) }),

    h('div', { class: 'actions' },
      options
        .filter((option) => option.value !== answered)
        .map((option) => h('button', {
          type: 'button',
          class: 'add',
          text: label(option),
          onClick: () => answer(option.value, label(option)),
        }))
        .concat(answered
          ? [h('button', {
              type: 'button',
              class: 'add',
              text: t('containers.property_clear', language),
              onClick: () => answer(null, t('containers.property_clear', language)),
            })]
          : [])),

    error,

    reasons.length
      ? h('ul', { style: 'margin:var(--sp-xs) 0 0; padding-left:1.2em; color:var(--ink-black)' }, reasons)
      : null,

    // The two tests, where the record permitted them to be computed. `binds_on` names which one decided.
    (property.binds_on || []).length
      ? h('p', {
          class: 'position-meta',
          text: `${t('containers.property_binds', language)}: `
            + property.binds_on
              .map((test) => t(`containers.property_test_${test}`, language))
              .join(', '),
        })
      : null,
  ]);
}

function goalNode(goal, language, { parameters, templates, roles, onEdit, onAnswered }) {
  // The template the goal was named from, in the member's language. Rendered as a plain line rather than
  // as a chip: `.provisional` is the attention hue and means "not settled yet", and courage money is a
  // first-class template (R-132), not a caveat.
  const template = templates.find((entry) => entry.key === goal.template);
  const templateName = template && template[language] ? template[language].name : null;

  return h('div', { class: 'role-row', style: 'grid-template-columns:1fr' }, [
    h('div', { class: 'cell', style: 'border-left-width:0' }, [
      templateName
        ? h('span', { class: 'cell-capital', text: templateName })
        : null,
      h('div', { class: 'position-label', text: goal.name }),

      // The target, where there is one. A goal without an amount or without a date is a real goal — the
      // columns are nullable for the same reason a position without a magnitude is a position (R-020).
      h('div', {
        class: 'position-meta',
        text: goal.target_date
          ? `${t('containers.target_date', language)}: ${goal.target_date}`
          : t('containers.no_target_date', language),
      }),
      // The unit is stated, not implied. `Goal.target_amount` is one sum in francs and the label says so —
      // the same defect the owner reported on the position form ("Betrag in welcher Frequenz?") was here
      // too, in a line that read "Zielbetrag: 250000" and left the reader to assume both the currency and
      // that it was not a yearly figure. Formatted the Swiss way, like every other figure in the client.
      goal.target_amount !== null && goal.target_amount !== undefined
        ? h('div', {
            class: 'position-magnitude',
            text: `${t('containers.target_amount', language)}: `
              + `${formatAmount(goal.target_amount, language === 'de' ? 'de-CH' : 'en-CH')}`,
          })
        : null,

      // R-131. All five, in the payload's order, unanswered ones included.
      h('div', { class: 'field' }, [
        h('span', { class: 'lbl', text: t('containers.parameters', language) }),
        ...parameters.map((name) =>
          h('div', { class: 'position' }, [
            h('div', { class: 'position-label', text: t(`containers.param_${name}`, language) }),
            h('div', {
              class: 'position-meta',
              text: goal.parameters[name] || t('containers.param_unanswered', language),
            }),
          ]),
        ),
      ]),

      // R-130. The funding, with the overlap said plainly above it rather than implied by the layout.
      h('div', { class: 'field' }, [
        h('span', { class: 'lbl', text: t('containers.funding', language) }),
        goal.funded_by.length
          ? h('p', { class: 'field-hint', text: t('containers.overlap_note', language) })
          : null,
        ...goal.funded_by.map((position) => fundingNode(position, language)),
        goal.funded_by.length
          ? null
          : h('p', { class: 'cell-prompt', text: t('containers.unfunded', language) }),
      ]),

      // R-031. No severity class, no icon, no dismiss button. A plain list, in the body ink.
      goal.observations.length
        ? h('div', { class: 'field' }, [
            h('span', { class: 'lbl', text: t('containers.observations', language) }),
            h('ul', { style: 'margin:0; padding-left:1.2em; color:var(--ink-black)' },
              goal.observations.map((observation) => observationNode(observation, language))),
          ])
        : null,

      // The property finding and its one blocking question. Above the illustration because a goal whose
      // occupancy is unanswered has a verdict of `could_not_be_determined`, and a member should meet the
      // reason before meeting a projection that does not depend on it.
      occupancyNode(goal, language, { onAnswered }),

      // R-133 / C-02. The illustration where there is one, the derived reason where there is not.
      illustrationNode(goal, language, roles),

      // The owner's report: "If I have a Ziel, I can not change it afterwards." One action, on the goal
      // itself, in the client's one secondary treatment — a goal is an intention and an intention that
      // cannot be revised is a worse record of one, not a better one.
      h('div', { class: 'actions' }, [
        h('button', {
          type: 'button',
          class: 'add',
          text: t('containers.edit', language),
          onClick: () => onEdit(goal),
        }),
      ]),
    ]),
  ]);
}

// ---------------------------------------------------------------- naming a goal

function addForm({ language, templates, parameters, positions, onSaved }) {
  const name = h('input', { type: 'text', name: 'name', required: '', maxlength: '200' });

  // R-132. Courage money is an option in the list with its own name and its own purpose, offered at the
  // same weight as everything else — which is what "first-class template, not a footnote" means in a form.
  // It is one of nine now rather than one of two, and still at equal weight: the list is the owner's own
  // eight goal kinds with Frühpensionierung first, plus a member naming their own.
  const template = templateSelect(templates, language);
  const purpose = templatePurpose(template, templates, language);

  const amount = h('input', { type: 'number', name: 'target_amount', step: 'any', min: '0' });
  const date = h('input', { type: 'date', name: 'target_date' });

  // The five parameters are free text on the model — `String(40)` with no enumeration anywhere in the
  // schema or the content records. A select here would be this client inventing the vocabulary a member is
  // allowed to describe their own goal in, which is the mistake `GOAL_TEMPLATES` avoids by leaving courage
  // money's parameters unset. Free text, stored, not interpreted — the same treatment as the tags (A29).
  const parameterInputs = {};
  for (const key of parameters) {
    parameterInputs[key] = h('input', { type: 'text', name: key, maxlength: '40' });
  }

  // R-030 in the control itself: a multiple select, because a position may carry more than one goal and
  // choosing it here does not take it away from anything else.
  const funding = h('select', { name: 'funded_by', multiple: '', size: String(Math.min(6, Math.max(2, positions.length))) },
    positions.map((position) =>
      h('option', { value: position.id, text: `${position.label} · ${position.display}` }),
    ));

  const question = h('input', { type: 'text', name: 'question', maxlength: '300' });
  const choice = h('input', { type: 'text', name: 'choice', maxlength: '300' });

  const error = h('div', { class: 'notice error', hidden: '' });

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      const chosen = Array.from(funding.selectedOptions).map((option) => option.value);
      const payload = {
        name: name.value.trim(),
        template: template.value || null,
        target_amount: amount.value.trim() ? Number(amount.value) : null,
        target_date: date.value || null,
        funded_by_position_ids: chosen,
        // C-09. The member states the decision; the server writes it in the same transaction and refuses
        // the write without it.
        question: question.value.trim() || t('containers.default_question', language, { name: name.value.trim() }),
        choice: choice.value.trim() || name.value.trim(),
      };
      for (const [key, input] of Object.entries(parameterInputs)) {
        payload[key] = input.value.trim() || null;
      }

      try {
        await createGoal(payload);
        onSaved();
      } catch (err) {
        error.textContent = err instanceof ApiError ? err.detail || String(err.status) : String(err);
        error.removeAttribute('hidden');
      }
    },
  }, [
    h('h1', { text: t('containers.add_title', language), style: 'font-size:1.2rem' }),
    field(t('containers.name', language), name),
    field(t('containers.template', language), template),
    purpose,
    field(t('containers.target_amount', language), amount, t('containers.target_amount_hint', language)),
    field(t('containers.target_date', language), date),

    h('details', { class: 'tags' }, [
      h('summary', { text: t('containers.parameters', language) }),
      h('p', { class: 'field-hint', text: t('containers.param_hint', language) }),
      ...parameters.map((key) => field(t(`containers.param_${key}`, language), parameterInputs[key])),
    ]),

    positions.length
      ? field(t('containers.funding_select', language), funding, t('containers.funding_hint', language))
      : h('p', { class: 'cell-prompt', text: t('containers.no_positions', language) }),

    h('fieldset', { class: 'decision' }, [
      h('legend', { text: t('form.decision', language) }),
      h('p', { class: 'field-hint', text: t('form.decision_hint', language) }),
      field(t('form.question', language), question),
      field(t('form.choice', language), choice),
    ]),

    error,
    h('div', { class: 'actions' }, [
      h('button', { type: 'submit', class: 'primary' }, [t('containers.save', language)]),
    ]),
  ]);

  return form;
}

// ---------------------------------------------------------------- changing a goal after it is named

/**
 * The form for changing a goal that exists. **The screen that did not exist** — see the owner's report.
 *
 * **Only what actually changed is sent.** The server distinguishes "clear this field" from "leave this
 * field alone" by reading which keys are present in the request, so this compares every control against
 * the value it was prefilled with and sends the difference. Posting the whole form back would make an
 * untouched field indistinguishable from a cleared one.
 *
 * **It says what happens to the record, in `containers.edit_lede`, above the fields.** Changing a goal
 * writes a new Decision that references the one before it; the earlier Decision is untouched and cannot be
 * removed (R-040). A member should be able to see that they are leaving a trail before they leave it, not
 * afterwards — which is the same reason C-09's question and choice are a visible fieldset rather than
 * something the save button does quietly.
 *
 * There is no delete. Not an omission: R-122 keeps an inactive *position* rather than deleting it, nothing
 * in the specification says what removing a goal means for the Decisions that reference it, and inventing
 * an answer to that in a form is how a member loses the record of a decision they made.
 */
function editForm({ goal, language, templates, parameters, positions, onSaved, onCancel }) {
  const name = h('input', { type: 'text', name: 'name', required: '', maxlength: '200', value: goal.name });
  const template = templateSelect(templates, language, { selected: goal.template });
  const purpose = templatePurpose(template, templates, language);

  const amount = h('input', {
    type: 'number', name: 'target_amount', step: 'any', min: '0',
    value: goal.target_amount === null || goal.target_amount === undefined ? '' : String(goal.target_amount),
  });
  const date = h('input', { type: 'date', name: 'target_date', value: goal.target_date || '' });

  const parameterInputs = {};
  for (const key of parameters) {
    parameterInputs[key] = h('input', {
      type: 'text', name: key, maxlength: '40', value: goal.parameters[key] || '',
    });
  }

  const funded = new Set(goal.funded_by.map((position) => position.id));
  const funding = h('select', {
    name: 'funded_by',
    multiple: '',
    size: String(Math.min(6, Math.max(2, positions.length))),
  }, positions.map((position) =>
    h('option', {
      value: position.id,
      selected: funded.has(position.id) ? '' : null,
      text: `${position.label} · ${position.display}`,
    }),
  ));

  const question = h('input', { type: 'text', name: 'question', maxlength: '300' });
  const choice = h('input', { type: 'text', name: 'choice', maxlength: '300' });
  const error = h('div', { class: 'notice error', hidden: '' });

  function refuse(message) {
    error.textContent = message;
    error.removeAttribute('hidden');
  }

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      const changes = {};
      const nextName = name.value.trim();
      if (nextName !== goal.name) changes.name = nextName;
      if ((template.value || null) !== (goal.template || null)) changes.template = template.value || null;

      const nextAmount = amount.value.trim() ? Number(amount.value) : null;
      const wasAmount = goal.target_amount === undefined ? null : goal.target_amount;
      if (nextAmount !== wasAmount) changes.target_amount = nextAmount;

      const nextDate = date.value || null;
      if (nextDate !== (goal.target_date || null)) changes.target_date = nextDate;

      for (const [key, input] of Object.entries(parameterInputs)) {
        const next = input.value.trim() || null;
        if (next !== (goal.parameters[key] || null)) changes[key] = next;
      }

      const chosen = Array.from(funding.selectedOptions).map((option) => option.value);
      const fundingMoved = chosen.length !== funded.size || chosen.some((id) => !funded.has(id));

      // Refused here as well as on the server, and for a different reason: the server refuses because a
      // Decision recording a change that did not happen is permanent, and this refuses because the member
      // should hear it in their own language rather than read the service's German sentence.
      if (!Object.keys(changes).length && !fundingMoved) return refuse(t('containers.edit_unchanged', language));

      const payload = {
        ...changes,
        // C-09, exactly as when the goal was named. Only sent when the funding actually moved, because an
        // unchanged list still counts as "stated" on the wire.
        ...(fundingMoved ? { funded_by_position_ids: chosen } : {}),
        question: question.value.trim()
          || t('containers.edit_default_question', language, { name: nextName }),
        choice: choice.value.trim() || nextName,
      };

      try {
        await reviseGoal(goal.id, payload);
        announce(t('containers.edit_done', language));
        onSaved();
      } catch (err) {
        refuse(err instanceof ApiError ? err.detail || String(err.status) : String(err));
      }
    },
  }, [
    h('h1', { text: t('containers.edit_title', language), style: 'font-size:1.2rem' }),
    h('p', { class: 'lede', text: t('containers.edit_lede', language) }),

    field(t('containers.name', language), name),
    field(t('containers.template', language), template),
    purpose,
    field(
      t('containers.target_amount', language),
      amount,
      `${t('containers.target_amount_hint', language)} ${t('containers.edit_clear_hint', language)}`,
    ),
    field(t('containers.target_date', language), date),

    h('details', { class: 'tags' }, [
      h('summary', { text: t('containers.parameters', language) }),
      h('p', { class: 'field-hint', text: t('containers.param_hint', language) }),
      ...parameters.map((key) => field(t(`containers.param_${key}`, language), parameterInputs[key])),
    ]),

    positions.length
      ? field(t('containers.funding_select', language), funding, t('containers.funding_hint', language))
      : h('p', { class: 'cell-prompt', text: t('containers.no_positions', language) }),

    h('fieldset', { class: 'decision' }, [
      h('legend', { text: t('form.decision', language) }),
      h('p', { class: 'field-hint', text: t('form.decision_hint', language) }),
      field(t('form.question', language), question),
      field(t('form.choice', language), choice),
    ]),

    error,
    h('div', { class: 'actions' }, [
      h('button', { type: 'submit', class: 'primary' }, [t('containers.edit_save', language)]),
      h('button', {
        type: 'button',
        class: 'add',
        text: t('containers.edit_cancel', language),
        onClick: onCancel,
      }),
    ]),
  ]);

  return form;
}

/**
 * Fetch what this surface needs.
 *
 * Two requests, because the funding control offers the member's positions and the goals payload only names
 * the ones already chosen. Same-origin and relative, through `api.js` — C-05.
 */
// A11: no member id is passed. The server reads it off the bearer token, and there is no
// parameter left by which this client could ask for anybody else's goals.
export async function load(language) {
  const [goals, grid] = await Promise.all([getGoals(), getRoleGrid(language)]);
  const positions = [];
  // The role's member-facing name, from the grid payload. The illustration keys its rates by `role`
  // (`growth`, `income`, ...) and those identifiers are not the words a member reads; the role definitions
  // are content records the server owns (R-111, D-03), so the name is taken from there rather than
  // duplicated into this client's string table where it would drift from the definition it names.
  // Keyed by role AND capital type, because the grid's `display` genuinely differs between them: the same
  // plan role is "Wertsteigerung" for financial capital and "Wachstum" for human capital, and `roles.json`
  // records that as the source manual's own distinction rather than a decision anybody here may collapse.
  const roles = {};
  for (const cell of grid.cells) {
    roles[`${cell.role}|${cell.capital_type}`] = cell.display;
    for (const position of cell.positions) {
      positions.push({ id: position.id, label: position.label, display: cell.display });
    }
  }
  return { goals, positions, roles };
}

export function render(container, { goals, positions, roles }, { language, onChanged }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('containers.eyebrow', language) }),
    h('h1', { text: t('containers.title', language) }),
    // R-130, stated before a member reads a single goal. `funding_may_overlap` is in the payload precisely
    // so a client author meets this sentence before designing a screen that implies separate pots.
    h('p', { class: 'lede', text: t('containers.lede', language) }),
  );

  const list = h('div', { class: 'grid' });
  if (goals.goals.length) {
    for (const goal of goals.goals) {
      list.append(
        goalNode(goal, language, {
          parameters: goals.five_parameters,
          templates: goals.templates,
          roles,
          onEdit: openEditor,
          onAnswered: onChanged,
        }),
      );
    }
  } else {
    list.append(h('p', { class: 'cell-prompt', text: t('containers.empty', language) }));
  }
  container.append(list);

  const forms = h('div');
  container.append(forms);

  /**
   * Swap the naming form for the changing form, in place.
   *
   * One region rather than a form per card: two open forms on one screen is two sets of decision fields,
   * and a member could submit the one they were not looking at. Cancelling puts the naming form back.
   */
  function openEditor(goal) {
    clear(forms);
    const form = editForm({
      goal,
      language,
      templates: goals.templates,
      parameters: goals.five_parameters,
      positions,
      onSaved: onChanged,
      onCancel: () => showAddForm(),
    });
    forms.append(form);
    form.scrollIntoView({ block: 'nearest' });
    form.querySelector('input').focus();
  }

  function showAddForm() {
    clear(forms);
    forms.append(
      addForm({
        language,
        templates: goals.templates,
        parameters: goals.five_parameters,
        positions,
        onSaved: onChanged,
      }),
    );
  }

  showAddForm();
}
