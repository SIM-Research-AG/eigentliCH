// The plan: household, positions (the role grid) and goals. Every change goes through a decision written
// in the same transaction (C-09); the client may say why, and the decision list shows what was decided.
// Positions and goals are never deleted: they leave the running plan and can come back (R-122, EIG-07).

import { api, detailText } from '../app/api.js';
import { amount, button, clear, field, h, notice, when, put } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { roleName, showValue } from './home.js';
import { basisLabel, basisSwitch, currentBasis } from '../app/basis.js';

const UNITS = ['', 'chf', 'chf_per_year', 'share_of_total'];
const LIQUIDITY = ['', 'immediate', 'within_months', 'within_years', 'illiquid'];
const VESSELS = ['', 'free', 'pillar_2', 'pillar_3a', 'real_asset'];

function select(values, current, L, prefix) {
  return h('select', {}, values.map((v) => h('option', { value: v, selected: (current ?? '') === v ? true : null,
    text: v ? t(`${prefix}.${v}`, L, {}, v) : t('q.choose', L) })));
}

function magnitudeText(p, L) {
  if (p.magnitude === null || p.magnitude === undefined) return null;
  const unit = p.magnitude_unit === 'chf_per_year' ? t('unit.chf_per_year', L) : p.magnitude_unit === 'share_of_total' ? '%' : 'CHF';
  return p.magnitude_unit === 'share_of_total' ? `${p.magnitude} %` : `${amount(p.magnitude, L)} ${unit}`;
}

function positionForm(L, { position, role, capital, partner, onSave, onCancel }) {
  const p = position || { role, capital_type: capital, tags: {} };
  const label = h('input', { type: 'text', maxlength: '300', value: p.label || '', required: true });
  const description = h('input', { type: 'text', maxlength: '2000', value: p.description || '' });
  const magnitude = h('input', { type: 'number', step: 'any', value: p.magnitude ?? '' });
  const unit = select(UNITS, p.magnitude_unit, L, 'unitname');
  const stock = select(['', 'asset', 'liability'], p.stock_kind, L, 'stock');
  const liquidity = select(LIQUIDITY, p.liquidity, L, 'liquidity');
  const vessel = select(VESSELS, (p.tags || {}).vessel, L, 'vessel');
  const timeBasis = h('input', { type: 'text', maxlength: '200', value: p.time_basis || '' });
  // Whose position it is (EIG-53): offered once the household names a partner.
  const owner = h('select', {}, [h('option', { value: '', text: t('owner.client', L) }),
    h('option', { value: 'partner', selected: p.owner === 'partner' ? true : null, text: partner || t('owner.partner', L) })]);
  const reasoning = h('input', { type: 'text', maxlength: '2000', placeholder: t('plan.why_hint', L) });
  const err = h('div');
  return h('form', {
    class: 'form card',
    onSubmit: async (event) => {
      event.preventDefault();
      clear(err);
      const body = {
        label: label.value.trim(), description: description.value.trim() || null,
        magnitude: magnitude.value === '' ? null : Number(magnitude.value), magnitude_unit: unit.value || null,
        stock_kind: unit.value === 'chf' ? (stock.value || null) : null, liquidity: liquidity.value || null,
        time_basis: timeBasis.value.trim() || null, vessel: vessel.value || null, reasoning: reasoning.value.trim() || null,
      };
      if (partner || p.owner === 'partner') body.owner = owner.value || 'client';
      if (!position) { body.role = p.role; body.capital_type = p.capital_type; }
      try { await onSave(body); } catch (e) { put(err, notice(detailText(e), 'error')); }
    },
  }, [
    h('h3', { text: position ? t('plan.edit_position', L) : t('plan.new_position', L) }),
    field(t('plan.label', L), label), field(t('plan.description', L), description),
    h('div', { class: 'two' }, [field(t('plan.magnitude', L), magnitude, t('plan.magnitude_hint', L)), field(t('plan.unit', L), unit)]),
    h('div', { class: 'two' }, [field(t('plan.stock_kind', L), stock, t('plan.stock_kind_hint', L)), field(t('plan.liquidity', L), liquidity)]),
    h('div', { class: 'two' }, [field(t('plan.vessel', L), vessel, t('plan.vessel_hint', L)), field(t('plan.time_basis', L), timeBasis)]),
    partner || p.owner === 'partner' ? field(t('plan.owner', L), owner, t('plan.owner_hint', L)) : null,
    field(t('plan.why', L), reasoning),
    err,
    h('div', { class: 'actions' }, [h('button', { type: 'submit', class: 'primary', text: t('plan.save', L) }),
      button(t('plan.cancel', L), { onClick: onCancel })]),
  ]);
}

/** The per-goal question "Ist der Betrag in heutigen Franken?" (EIG-60), worded by the onboarding's content. */
function basisQuestion(questions) {
  return (questions || []).find((q) => q.field === 'amount_basis') || null;
}

function goalForm(L, { goal, positions, sharesAsked, onSave, onCancel, templates, questions }) {
  const g = goal || {};
  const bq = basisQuestion(questions);
  const amountBasis = bq ? h('select', {}, bq.options.map((o) => h('option', {
    value: o.value, text: o.label, selected: (g.amount_basis || bq.default) === o.value ? true : null }))) : null;
  const name = h('input', { type: 'text', maxlength: '300', value: g.name || '', required: true });
  const target = h('input', { type: 'number', min: '0', step: 'any', value: g.target_amount ?? '' });
  const date = h('input', { type: 'date', value: g.target_date || '' });
  const occupancy = select(['', 'owner_occupied_primary', 'second_or_holiday_home', 'let_to_someone_else'], g.occupancy, L, 'occupancy');
  // Its share of the one yearly saving, 0 to 100 % here, 0 to 1 in the store (EIG-59): asked when more than one
  // goal has an amount and a date, or when this goal already states one.
  const askShare = sharesAsked || (g.contribution_share !== null && g.contribution_share !== undefined);
  const share = h('input', { type: 'number', min: '0', max: '100', step: 'any',
    value: g.contribution_share === null || g.contribution_share === undefined ? '' : String(Math.round(g.contribution_share * 1000) / 10) });
  const reasoning = h('input', { type: 'text', maxlength: '2000', placeholder: t('plan.why_hint', L) });
  const funded = new Set(g.funded_by || []);
  const boxes = positions.filter((p) => p.active).map((p) => {
    const cb = h('input', { type: 'checkbox', checked: funded.has(p.id) ? true : null, value: p.id });
    return [cb, h('label', { class: 'row small' }, [cb, `${p.label}${magnitudeText(p, L) ? ' · ' + magnitudeText(p, L) : ''}`])];
  });
  const err = h('div');
  return h('form', {
    class: 'form card',
    onSubmit: async (event) => {
      event.preventDefault();
      clear(err);
      const body = { name: name.value.trim(), target_amount: target.value === '' ? null : Number(target.value),
        target_date: date.value || null, occupancy: occupancy.value || null,
        funded_by: boxes.filter(([cb]) => cb.checked).map(([cb]) => cb.value), reasoning: reasoning.value.trim() || null };
      // stated only when the client gives an amount or changes an earlier answer: unstated reads as today's francs
      if (amountBasis && (body.target_amount !== null || g.amount_basis)) body.amount_basis = amountBasis.value;
      if (askShare) {
        const pct = share.value === '' ? null : Number(share.value);
        if (pct !== null && !(pct >= 0 && pct <= 100)) { put(err, notice(t('err.share_range', L), 'error')); return; }
        body.contribution_share = pct === null ? null : pct / 100;
      }
      try { await onSave(body); } catch (e) { put(err, notice(detailText(e), 'error')); }
    },
  }, [
    h('h3', { text: goal ? t('plan.edit_goal', L) : t('plan.new_goal', L) }),
    field(t('plan.goal_name', L), name),
    h('div', { class: 'two' }, [field(t('plan.target_amount', L), target, t('plan.target_amount_hint', L)), field(t('plan.target_date', L), date)]),
    amountBasis ? field(bq.question, amountBasis, bq.why) : null,
    field(t('plan.occupancy', L), occupancy, t('plan.occupancy_hint', L)),
    askShare ? field(t('plan.share', L), share, t('plan.share_hint', L)) : null,
    boxes.length ? h('fieldset', { class: 'field' }, [h('legend', { class: 'field-label', text: t('plan.funded_by', L) }),
      h('span', { class: 'field-hint', text: t('plan.funded_by_hint', L) }), ...boxes.map(([, l]) => l)]) : null,
    field(t('plan.why', L), reasoning),
    err,
    h('div', { class: 'actions' }, [h('button', { type: 'submit', class: 'primary', text: t('plan.save', L) }),
      button(t('plan.cancel', L), { onClick: onCancel })]),
  ]);
}

/** lbs's figure for a goal in the chosen basis (LBS-31): "Laut Bilanz: CHF 540’000 in heutigen Franken". */
function goalInView(view, basis, L) {
  if (!view) return null;
  const v = view[basis] || {};
  if (v.amount === null || v.amount === undefined) return null;
  const unit = view.unit === 'chf_per_year' ? ` ${t('unit.per_year', L)}` : '';
  const where = basis === 'nominal' && v.as_at
    ? t('basis.as_at', L, { date: new Intl.DateTimeFormat(L === 'en' ? 'en-GB' : 'de-CH', { dateStyle: 'medium' }).format(new Date(`${v.as_at}T12:00:00`)) })
    : basisLabel(basis, L);
  return h('div', { class: 'small', 'data-basis': basis, text: t('plan.in_view', L, { amount: `CHF ${amount(v.amount, L)}${unit}`, basis: where }) });
}

export async function render(main, ctx) {
  const { language: L, client } = ctx;
  let plan;
  let decisions;
  try {
    [plan, decisions] = await Promise.all([api.plan(client.id, L), api.decisions(client.id, L)]);
  } catch (e) {
    put(main, notice(detailText(e), 'error'));
    return;
  }
  const reload = () => render(clear(main), ctx);
  const flash = h('div');
  put(main, 
    h('span', { class: 'lbl', text: t('plan.eyebrow', L) }),
    h('h1', { text: t('plan.title', L) }),
    h('p', { class: 'lede', text: t('plan.lede', L) }),
    flash,
  );

  // -- household
  put(main, h('h2', { text: t('plan.household', L) }));
  const hhBox = h('div', { class: 'card' });
  put(main, hhBox);
  const drawHousehold = (editing) => {
    clear(hhBox);
    const members = plan.members || [];
    if (!editing) {
      if (plan.household) {
        put(hhBox, 
          h('p', {}, members.map((m, i) => h('span', {}, [i ? ', ' : '', m.label, h('span', { class: 'muted small', text: ` (${t(`plan.kind_${m.kind}`, L)})` })]))),
          h('p', { class: 'small muted', text: t('plan.household_as_of', L, { date: plan.household.composition_as_of }) }));
      } else {
        put(hhBox, h('p', { class: 'muted', text: t('plan.no_household', L) }));
      }
      put(hhBox, h('div', { class: 'actions' }, [button(t('plan.change_household', L), { onClick: () => drawHousehold(true) })]));
      return;
    }
    const adults = h('textarea', { rows: '3', value: members.filter((m) => m.kind === 'adult').map((m) => m.label).join('\n') || t('plan.me', L) });
    const deps = h('textarea', { rows: '2', value: members.filter((m) => m.kind === 'dependant').map((m) => m.label).join('\n') });
    const asOf = h('input', { type: 'date', value: new Date().toISOString().slice(0, 10) });
    const reasoning = h('input', { type: 'text', maxlength: '2000', placeholder: t('plan.why_hint', L) });
    const err = h('div');
    put(hhBox, h('form', {
      class: 'form wide', style: 'margin-top:0',
      onSubmit: async (event) => {
        event.preventDefault();
        clear(err);
        const lines = (el) => el.value.split('\n').map((s) => s.trim()).filter(Boolean);
        try {
          await api.setHousehold(client.id, { adults: lines(adults), dependants: lines(deps), as_of: asOf.value || null, reasoning: reasoning.value.trim() || null });
          reload();
        } catch (e) { put(err, notice(detailText(e), 'error')); }
      },
    }, [
      h('div', { class: 'two' }, [field(t('q.adults', L), adults, t('plan.adults_hint', L)), field(t('q.dependants', L), deps, t('plan.one_per_line', L))]),
      field(t('q.as_of', L), asOf, t('q.as_of_hint', L)), field(t('plan.why', L), reasoning), err,
      h('div', { class: 'actions' }, [h('button', { type: 'submit', class: 'primary', text: t('plan.save', L) }),
        button(t('plan.cancel', L), { onClick: () => drawHousehold(false) })]),
    ]));
  };
  drawHousehold(false);

  // -- positions: the role grid
  put(main, h('h2', { text: t('plan.positions', L) }), h('p', { class: 'muted', text: t('plan.positions_lede', L) }));
  const formSlot = h('div');
  const grid = h('div', { class: 'grid' });
  put(main, formSlot, grid);
  put(grid, h('div', { class: 'grid-head' }, [h('span'), h('span', { text: t('capital.human', L) }), h('span', { text: t('capital.financial', L) })]));
  const openForm = (node) => { clear(formSlot); put(formSlot, node); formSlot.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
  for (const role of plan.roles) {
    const cells = plan.cells.filter((c) => c.role === role);
    put(grid, h('div', { class: 'role-row' }, [
      h('div', { class: 'role-name', text: roleName(cells, '') }),
      ...cells.map((cell) => h('div', { class: 'cell', 'data-capital': cell.capital_type }, [
        h('span', { class: 'cell-capital', text: t(`capital.${cell.capital_type}`, L) }),
        h('span', { class: 'small muted', text: cell.display }),
        ...cell.positions.map((p) => h('div', { class: 'position', 'data-active': String(p.active) }, [
          h('div', { class: 'position-label', text: p.label }),
          magnitudeText(p, L) ? h('div', { class: 'position-magnitude', text: magnitudeText(p, L) }) : null,
          p.time_basis ? h('div', { class: 'position-meta', text: p.time_basis }) : null,
          p.owner === 'partner' ? h('div', { class: 'position-meta', text: t('plan.belongs_to', L, { name: plan.partner || t('owner.partner', L) }) }) : null,
          p.liquidity ? h('div', { class: 'position-meta', text: t(`liquidity.${p.liquidity}`, L, {}, p.liquidity) }) : null,
          !p.active ? h('div', { class: 'position-meta', text: t('plan.inactive', L) }) : null,
          h('div', { class: 'actions' }, [
            p.active ? button(t('plan.edit', L), {
              onClick: () => openForm(positionForm(L, { position: p, partner: plan.partner, onCancel: () => clear(formSlot),
                onSave: async (body) => { await api.patchPosition(client.id, p.id, body); reload(); } })),
            }) : null,
            button(p.active ? t('plan.deactivate', L) : t('plan.reactivate', L), {
              onClick: async () => {
                try { await api.positionActive(client.id, p.id, !p.active, null); reload(); } catch (e) { put(flash, notice(detailText(e), 'error')); }
              },
            }),
          ]),
        ])),
        !cell.positions.length ? h('p', { class: 'cell-prompt', text: cell.definition || '' }) : null,
        button(t('plan.add_position', L), {
          onClick: () => openForm(positionForm(L, { role: cell.role, capital: cell.capital_type, partner: plan.partner, onCancel: () => clear(formSlot),
            onSave: async (body) => { await api.createPosition(client.id, body); reload(); } })),
        }),
      ])),
    ]));
  }

  // -- goals, with the nominal / real switch: the stated amount and its basis, and lbs's figure in the chosen basis
  const basis = currentBasis();
  put(main, h('h2', { text: t('plan.goals', L) }), basisSwitch(L, () => reload()));
  const goalSlot = h('div');
  const goals = h('ul', { class: 'list' });
  put(main, h('div', { class: 'actions' }, [button(t('plan.add_goal', L), {
    class: 'primary',
    onClick: () => { clear(goalSlot); put(goalSlot, goalForm(L, { positions: plan.positions, sharesAsked: plan.shares_asked, questions: plan.goal_questions, onCancel: () => clear(goalSlot),
      onSave: async (body) => { await api.createGoal(client.id, body); reload(); } })); },
  })]), goalSlot, goals);
  if (!plan.goals.length) put(goals, h('li', { class: 'muted', text: t('plan.no_goals', L) }));
  if (plan.shares_asked) {
    put(main, h('p', { class: 'small muted', text: t('plan.shares_total', L, { n: String(Math.round((plan.shares_total || 0) * 1000) / 10) }) }));
  }
  for (const g of plan.goals) {
    const funders = plan.positions.filter((p) => g.funded_by.includes(p.id)).map((p) => p.label);
    put(goals, h('li', { 'data-active': String(g.active) }, [
      h('div', { class: 'row' }, [
        h('strong', { class: 'grow', text: g.name + (g.active ? '' : ` (${t('plan.inactive', L)})`) }),
        h('span', { class: 'badge quiet', text: t(`goalkind.${g.kind}`, L) }),
      ]),
      h('div', { class: 'small muted' }, [
        g.target_amount !== null ? `CHF ${amount(g.target_amount, L)} ${t(`plan.stated_${g.amount_basis || 'today'}`, L)}` : t('plan.no_amount', L),
        ' · ', g.target_date || t('plan.no_date', L),
        funders.length ? ` · ${t('plan.funded_by', L)}: ${funders.join(', ')}` : '',
        g.contribution_share !== null && g.contribution_share !== undefined
          ? ` · ${t('plan.share_of_saving', L, { n: String(Math.round(g.contribution_share * 1000) / 10) })}` : '',
      ]),
      goalInView(plan.goal_views && plan.goal_views[g.id], basis, L),
      h('div', { class: 'actions' }, [
        g.active ? button(t('plan.edit', L), {
          onClick: () => { clear(goalSlot); put(goalSlot, goalForm(L, { goal: g, positions: plan.positions, sharesAsked: plan.shares_asked, questions: plan.goal_questions, onCancel: () => clear(goalSlot),
            onSave: async (body) => { await api.patchGoal(client.id, g.id, body); reload(); } })); goalSlot.scrollIntoView({ behavior: 'smooth' }); },
        }) : null,
        button(g.active ? t('plan.goal_deactivate', L) : t('plan.goal_reactivate', L), {
          onClick: async () => { try { await api.goalActive(client.id, g.id, !g.active, null); reload(); } catch (e) { put(flash, notice(detailText(e), 'error')); } },
        }),
      ]),
    ]));
  }

  // -- stated facts: they win over an answer, so a change is stated here (or by answering again)
  if ((plan.facts || []).length) {
    put(main, h('h2', { text: t('plan.facts', L) }), h('p', { class: 'muted', text: t('plan.facts_lede', L) }));
    const fl = h('ul', { class: 'list' });
    for (const f of plan.facts) {
      const li = h('li');
      const label = (plan.fact_labels || {})[f.stated_key] || f.stated_key;
      const draw = (editing) => {
        clear(li);
        if (!editing) {
          put(li, h('div', { class: 'row' }, [h('span', { class: 'grow small', text: label }),
            h('strong', { class: 'small', text: showValue(f.stated_value, L) }),
            button(t('plan.edit', L), { onClick: () => draw(true) })]));
          return;
        }
        const isNumber = typeof f.stated_value === 'number';
        const input = h('input', { type: isNumber ? 'number' : 'text', step: 'any', value: String(f.stated_value ?? '') });
        const err = h('div');
        put(li, h('form', { class: 'form', style: 'margin-top:0', onSubmit: async (event) => {
          event.preventDefault();
          clear(err);
          try {
            await api.restateFact(client.id, f.stated_key, isNumber ? Number(input.value) : input.value.trim(), null);
            reload();
          } catch (e) { put(err, notice(detailText(e), 'error')); }
        } }, [field(label, input), err, h('div', { class: 'actions' }, [
          h('button', { type: 'submit', class: 'primary', text: t('plan.save', L) }), button(t('plan.cancel', L), { onClick: () => draw(false) })])]));
      };
      draw(false);
      put(fl, li);
    }
    put(main, fl);
  }

  // -- decisions
  put(main, h('h2', { text: t('plan.decisions', L) }), h('p', { class: 'muted', text: t('plan.decisions_lede', L) }));
  const dl = h('ul', { class: 'list' });
  for (const d of decisions.slice(0, 40)) {
    put(dl, h('li', {}, [
      h('div', { class: 'row' }, [h('strong', { class: 'grow', text: d.question_text || d.question }),
        h('span', { class: 'small muted', text: `${t(`author.${d.author}`, L)} · ${when(d.created_at, L)}` })]),
      h('div', { class: 'small', text: d.choice_text || d.choice }),
      d.reasoning ? h('div', { class: 'small muted', text: d.reasoning }) : null,
    ]));
  }
  if (!decisions.length) put(dl, h('li', { class: 'muted', text: t('plan.no_decisions', L) }));
  put(main, dl);
}
