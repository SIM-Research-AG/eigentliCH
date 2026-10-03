// The client's home: what is open, the role grid from the lbs balance sheet, and what has been answered.
//
// No completion meter, no "n of m", no percentage (R-113): what is answered is listed, what comes next is
// named, and nothing measures one against the other.

import { api, detailText } from '../app/api.js';
import { amount, button, clear, h, notice, when, put } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { basisLabel, basisSwitch, currentBasis, pct } from '../app/basis.js';
import { chanceWords, planSentence } from './outlook.js';
import { balanceChart, capitalsChart } from '../app/charts.js';

export function showValue(value, L) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number') return Math.abs(value) >= 10000 ? amount(value, L) : String(value);
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v === 'string')) return value.join(', ');
    return t('value.entries', L, { n: value.length });
  }
  if (value.adults) return [...value.adults, ...(value.dependants || [])].join(', ');
  if (value.name) return value.name;
  return JSON.stringify(value);
}

const ROLE_ORDER = ['gain', 'income', 'stabilisation', 'protection'];

/** A role row's name: the house's names for both kinds of capital, once when they are the same (EIG-56). The
 *  server puts them into the cells in the reader's language, from reference/roles, never lbs's English. */
export function roleName(cells, fallback) {
  const names = [...new Set(cells.filter(Boolean).map((c) => c.display).filter(Boolean))];
  return names.length ? names.join(' · ') : fallback;
}

/** How old the sheet is, in words: "vor 3 Minuten", "vor 2 Tagen". */
export function age(seconds, L) {
  if (seconds === null || seconds === undefined) return '';
  const steps = [[60, 'seconds', 1], [3600, 'minutes', 60], [86400, 'hours', 3600], [Infinity, 'days', 86400]];
  const [, unit, div] = steps.find(([limit]) => seconds < limit);
  const n = Math.max(unit === 'seconds' ? 0 : 1, Math.floor(seconds / div));
  return unit === 'seconds' ? t('age.now', L) : t(`age.${unit}`, L, { n });
}

export function sheetGrid(sheet, L) {
  const grid = h('div', { class: 'grid' });
  put(grid, h('div', { class: 'grid-head' }, [h('span'), h('span', { text: t('capital.human', L) }),
    h('span', { text: t('capital.financial', L) })]));
  for (const role of ROLE_ORDER) {
    const cells = ['human', 'financial'].map((cap) => sheet.grid.find((c) => c.role === role && c.capital_type === cap));
    put(grid, h('div', { class: 'role-row' }, [
      h('div', { class: 'role-name', text: roleName(cells, '') }),
      ...cells.map((cell) => {
        if (!cell) return h('div', { class: 'cell' });
        const figures = [];
        if (cell.assets_chf !== null && cell.assets_chf !== undefined) figures.push([t('sheet.assets', L), `CHF ${amount(cell.assets_chf, L)}`]);
        if (cell.liabilities_chf !== null && cell.liabilities_chf !== undefined) figures.push([t('sheet.liabilities', L), `CHF ${amount(cell.liabilities_chf, L)}`]);
        if (cell.flows_chf_per_year !== null && cell.flows_chf_per_year !== undefined) figures.push([t('sheet.flows', L), `CHF ${amount(cell.flows_chf_per_year, L)} ${t('unit.per_year', L)}`]);
        return h('div', { class: 'cell', 'data-capital': cell.capital_type }, [
          h('span', { class: 'cell-capital', text: t(`capital.${cell.capital_type}`, L) }),
          figures.length
            ? h('div', {}, figures.map(([k, v]) => h('div', { class: 'position' }, [
              h('div', { class: 'position-meta', text: k }), h('div', { class: 'figure', text: v })])))
            : h('p', { class: 'cell-prompt', text: cell.positions.length ? t('sheet.no_amounts', L) : (cell.definition || t('sheet.empty', L)) }),
        ]);
      }),
    ]));
  }
  return grid;
}

export function totals(sheet, L) {
  const rows = [
    ['sheet.financial_assets', sheet.totals.financial_assets], ['sheet.human_assets', sheet.totals.human_assets],
    ['sheet.liabilities_total', sheet.totals.liabilities], ['sheet.net_worth', sheet.totals.net_worth],
  ];
  return h('table', { class: 'figures' }, rows.map(([k, v]) => h('tr', {}, [
    h('th', { text: t(k, L) }),
    h('td', { class: 'num', text: v === null || v === undefined ? t('sheet.open', L) : `CHF ${amount(v, L)}` }),
  ])));
}

/** A date (ISO) as 31.12.2040. */
function day(iso, L) {
  if (!iso) return '';
  return new Intl.DateTimeFormat(L === 'en' ? 'en-GB' : 'de-CH', { dateStyle: 'medium' }).format(new Date(`${iso}T12:00:00`));
}

/** The goals in the chosen basis, from lbs's real view (LBS-31), and the mandate's required return, each with
 *  its basis beside it. Real is today's francs; nominal is the francs of the goal's date. */
export function goalFigures(views, basis, L) {
  const box = h('div', { class: 'goal-figures', 'data-basis': basis });
  const shown = basisLabel(basis, L);
  if (basis === 'real' && !(views && views.available)) {
    put(box, notice(t('basis.not_available', L), 'calm'));
    return box;
  }
  const rows = [];
  for (const g of (views && views.goals) || []) {
    const v = g[basis] || {};
    const unit = g.unit === 'chf_per_year' ? ` ${t('unit.per_year', L)}` : '';
    const figure = v.amount === null || v.amount === undefined ? t('sheet.open', L) : `CHF ${amount(v.amount, L)}${unit}`;
    const where = basis === 'real' ? shown : (v.as_at ? t('basis.as_at', L, { date: day(v.as_at, L) }) : shown);
    rows.push(h('tr', {}, [h('th', { text: g.name || t('gap.this_goal', L) }),
      h('td', { class: 'num', text: figure }), h('td', { class: 'small muted', text: where })]));
  }
  const m = views && views.mandate;
  if (m && m[basis]) {
    const rr = m[basis].required_return;
    rows.push(h('tr', {}, [h('th', { text: t('home.required_return', L, { name: m.name || t('gap.this_goal', L) }) }),
      h('td', { class: 'num', text: rr === null || rr === undefined ? t('home.required_none', L) : `${pct(rr, L)} ${t('unit.per_year', L)}` }),
      h('td', { class: 'small muted', text: shown })]));
  }
  if (!rows.length) return box;
  put(box, h('h3', { text: t('home.goals_title', L) }), h('table', { class: 'figures' }, rows));
  if (basis === 'real' && views.inflation) {
    put(box, h('p', { class: 'small muted', text: t('basis.inflation', L, { rate: pct(views.inflation.annual_rate, L) }) }));
  }
  return box;
}

const ACTIONS = { plan: '#/plan', onboarding: '#/q/onboarding', intake: '#/q/intake' };
const PERSON_SECTIONS = ['human_capital', 'pensions'];

/** One gap as a sentence in the reader's language: never an id, never lbs's own key (EIG-49). */
export function gapText(g, L) {
  const section = g.key.split('.')[0];
  const name = g.name ? `«${g.name}»` : t(PERSON_SECTIONS.includes(section) ? 'gap.this_person' : 'gap.this_goal', L);
  const fallback = t(`gapkind.${g.kind || 'unknown'}`, L, {}, t('gapkind.unknown', L));
  return t(`gap.${g.key}`, L, { name }, fallback);
}

/** "Was noch fehlt": what the client can add, each with where to add it; then what is ours to prepare. */
export function missingList(missing, L, go) {
  const box = h('div', { class: 'missing' });
  const yours = missing.filter((g) => g.group === 'you');
  const ours = missing.filter((g) => g.group !== 'you');
  put(box, h('h3', { text: t('home.missing_you', L) }));
  if (!yours.length) put(box, h('p', { class: 'small muted', text: t('home.missing_none', L) }));
  else {
    put(box, h('ul', { class: 'list' }, yours.map((g) => h('li', {}, [h('div', { class: 'row' }, [
      h('span', { class: 'grow small', text: gapText(g, L) }),
      g.action && ACTIONS[g.action] ? button(`→ ${t(`gap.action.${g.action}`, L)}`, { onClick: () => go(ACTIONS[g.action]) }) : null,
    ])]))));
  }
  if (ours.length) {
    put(box, h('details', {}, [h('summary', { class: 'small', text: t('home.missing_us', L) }),
      h('ul', {}, ours.map((g) => h('li', { class: 'small muted', text: gapText(g, L) })))]));
  }
  return box;
}

const LEVEL_WORDS = (L) => ({ low: t('capitals.level_low', L), mid: t('capitals.level_mid', L), high: t('capitals.level_high', L) });

/** "Ihre Lebensbilanz" (EIG-70): the balance sheet as a graph from the newest lbs sheet. Today's assets and debts
 *  are the same in both bases (lbs states today's stocks); the goals' amounts follow the nominal / real switch. */
export function pictureBlock(pic, basis, L) {
  if (!pic) return null;
  const box = h('div', { class: 'picture', 'data-basis': basis });
  put(box, h('h3', { text: t('picture.title', L) }), h('p', { class: 'small muted', text: t('picture.lede', L) }));
  const assets = pic.assets.map((a) => ({ label: t(`picture.part.${a.part}`, L), chf: a.chf, cls: a.part }));
  if (!assets.length) {
    put(box, h('p', { class: 'small muted', text: t('picture.nothing', L) }));
    return box;
  }
  const open = t('picture.open', L);
  const net = pic.net_worth;
  const middle = [{ label: t('picture.debts', L), chf: pic.liabilities, cls: 'debts', open }];
  middle.push({ label: t('picture.net_worth', L), chf: typeof net === 'number' ? net : null, cls: 'net', open });
  const claims = pic.claims.map((c, i) => ({ label: `${c.name || t('picture.this_goal', L)}${c.date ? ` · ${c.date.slice(0, 4)}` : ''}`,
    chf: c[basis], cls: i % 2 ? 'claim alt' : 'claim', open }));
  const columns = [{ title: t('picture.assets', L), parts: assets },
    { title: t('picture.debts_and_net', L), parts: middle },
    { title: t('picture.claims', L), parts: claims, note: claims.length ? null : t(pic.claims_available ? 'picture.nothing' : 'picture.no_claims', L) }];
  put(box, balanceChart(columns, { title: t('picture.title', L), desc: t('picture.desc', L) }, L),
    h('p', { class: 'small muted', text: t('picture.claims_basis', L, { basis: basisLabel(basis, L) }) }));
  if (typeof net === 'number' && net < 0) put(box, notice(t('picture.negative', L, { amount: amount(-net, L) }), 'calm'));
  const yearly = pic.yearly_goals || [];
  if (yearly.length) put(box, h('p', { class: 'small muted', text: t('picture.yearly', L, { names: yearly.map((n) => n || t('picture.this_goal', L)).join(', ') }) }));
  return box;
}

/** "Ihre vier Kapitale" today (EIG-71): wealth in francs as words, expertise, network and health as levels on
 *  lbs's scale, per adult. A withheld health (K3) is not drawn: the server sends no figure, the page says why. */
export function capitalsBlock(caps, L) {
  if (!caps || !caps.adults || !caps.adults.length) return null;
  const box = h('div', { class: 'capitals' });
  put(box, h('h3', { text: t('capitals.title', L) }), h('p', { class: 'small muted', text: t('capitals.lede', L) }));
  const w = caps.wealth || {};
  const wealthText = typeof w.net_worth === 'number' ? t('capitals.wealth_household', L, { amount: amount(w.net_worth, L) })
    : typeof w.financial_assets === 'number' ? t('capitals.wealth_financial', L, { amount: amount(w.financial_assets, L) })
      : t('capitals.unknown', L);
  for (const row of caps.adults) {
    const name = row.name || t('capitals.this_person', L);
    put(box, h('h4', { text: name }), capitalsChart(row, caps.scale || {}, {
      title: `${t('capitals.title', L)}: ${name}`, desc: t('capitals.desc', L), wealth: t('capitals.wealth', L), wealthText,
      expertise: t('capitals.expertise', L), network: t('capitals.network', L), health: t('capitals.health', L),
      ...LEVEL_WORDS(L), of: t('capitals.of', L), unknown: t('capitals.unknown', L), withheld: t('capitals.withheld', L) }, L));
  }
  return box;
}

export async function render(main, { language, client, go }) {
  const L = language;
  let data;
  try {
    data = await api.home(client.id, L);
  } catch (e) {
    put(main, notice(detailText(e), 'error'));
    return;
  }
  const c = data.client;
  put(main, 
    h('span', { class: 'lbl', text: t('home.eyebrow', L) }),
    h('h1', { text: t('home.title', L, { name: c.display_name }) }),
    h('p', { class: 'lede', text: t('home.lede', L) }),
  );

  // -- open items
  const o = data.open;
  const items = h('ul', { class: 'list' });
  if (o.onboarding_open) {
    put(items, h('li', {}, [h('div', { class: 'row' }, [
      h('span', { class: 'grow', text: t('home.open_onboarding', L) }), button(t('home.continue', L), { onClick: () => go('#/q/onboarding') })])]));
  }
  for (const th of o.threads_awaiting_answer) {
    put(items, h('li', {}, [h('div', { class: 'row' }, [
      h('span', { class: 'grow', text: `${t('home.open_thread', L)}: ${th.subject || ''}` }),
      button(t('home.open', L), { onClick: () => go(`#/threads/${th.id}`) })])]));
  }
  for (const th of o.drafts_failed) {
    put(items, h('li', {}, [h('span', { class: 'badge bad', text: t('home.draft_failed', L) }), ' ', th.subject || '']));
  }
  for (const a of o.approvals_awaiting_curator) {
    put(items, h('li', {}, [h('span', { class: 'badge wait', text: t('state.awaiting_curator', L) }), ' ',
      t(`approval.item_${a.item_kind}`, L), ' · ', when(a.created_at, L)]));
  }
  for (const r of o.report_requests_open) {
    put(items, h('li', {}, [h('div', { class: 'row' }, [
      h('span', { class: 'grow', text: `${t(`report.kind_${r.kind}`, L)} · ${t('report.state_open', L)} · ${when(r.created_at, L)}` }),
      button(t('home.open', L), { onClick: () => go('#/reports') })])]));
  }
  put(main, h('h2', { text: t('home.open_title', L) }));
  if (!items.children.length) put(main, h('p', { class: 'muted', text: t('home.nothing_open', L) }));
  else put(main, items);

  // -- the role grid from the lbs sheet
  const sheetBox = h('div');
  const switchSlot = h('div');
  put(main, h('h2', { text: t('home.grid_title', L) }), h('p', { class: 'muted', text: t('home.grid_lede', L) }), switchSlot, sheetBox);
  let poll = null;
  let last = null;
  function drawSheet(bs) {
    last = bs;
    clear(sheetBox);
    clear(switchSlot);
    put(switchSlot, basisSwitch(L, () => drawSheet(last)));
    const basis = currentBasis();
    if (poll) { clearTimeout(poll); poll = null; }
    // An automatic run is on its way (EIG-47): say so, and fetch the sheet again when it is done.
    if (bs.pending) {
      put(sheetBox, notice(t(`home.sheet_${bs.pending}`, L), 'calm'));
      poll = setTimeout(async () => {
        if (!sheetBox.isConnected) return;
        try { drawSheet(await api.balanceSheet(client.id, L)); } catch (e) { /* the next visit shows it */ }
      }, 2500);
    }
    const run = button(t('home.run_sheet', L), { class: 'primary' });
    run.addEventListener('click', async () => {
      run.disabled = true;
      run.textContent = t('home.running_sheet', L);
      try { drawSheet(await api.runBalanceSheet(client.id, L)); } catch (e) {
        run.disabled = false; run.textContent = t('home.run_sheet', L);
        put(sheetBox, notice(detailText(e), 'error'));
      }
    });
    if (bs.available) {
      const s = bs.sheet;
      put(sheetBox, 
        h('p', { class: 'small muted', text: t('home.sheet_as_of', L, { date: s.as_of, when: when(bs.made_at, L), id: s.artefact_id }) }),
        h('p', { class: 'small', text: t('home.sheet_age', L, { age: age(bs.age_s, L) }) }),
        bs.plan_changed_since && !bs.pending ? notice(t('home.sheet_stale', L), 'calm') : null,
        basis === 'real' ? h('p', { class: 'small muted', text: t('basis.today_same', L) }) : null,
        sheetGrid(s, L), totals(s, L),
        pictureBlock(bs.picture, basis, L),
        capitalsBlock(bs.capitals, L),
        goalFigures(bs.views, basis, L),
        missingList(bs.missing || [], L, go),
        h('p', { class: 'small muted', text: t('notice', L) }),
      );
    } else if (bs.reason === 'engine') {
      put(sheetBox, notice(t('home.lbs_down', L) + ' ' + (bs.error || ''), 'error'));
    } else {
      put(sheetBox, h('p', { class: 'muted', text: t('home.no_sheet', L) }));
      if (bs.last_failure) put(sheetBox, notice(`${t('home.last_failure', L)}: ${bs.last_failure.error}`, 'error'));
    }
    put(sheetBox, h('div', { class: 'actions' }, [run]));
  }
  drawSheet(data.balance_sheet);

  // -- the outlook (lbsim, EIG-68): the designated goal's chance in words, the top three actions, the plan's state
  const card = data.outlook || {};
  const outlookBox = h('div', { class: 'card' }, [h('div', { class: 'row' }, [
    h('h2', { class: 'grow', text: t('home.outlook_title', L) }), button(t('home.open', L), { onClick: () => go('#/outlook') })])]);
  if (card.available) {
    if (card.goal) {
      put(outlookBox, h('p', { class: 'outlook-chance', text: `${chanceWords(card.goal.chance, L)} ${t('home.outlook_goal', L, { goal: card.goal.name || t('gap.this_goal', L) })}` }),
        h('p', { class: 'small muted', text: t(card.goal.chance_basis === 'real' ? 'outlook.judged_real' : 'outlook.judged_nominal', L) }));
    }
    if (card.actions && card.actions.length) {
      put(outlookBox, h('h3', { text: t('home.outlook_actions', L) }),
        h('ol', {}, card.actions.map((a) => h('li', {}, [h('strong', { text: a.title }), h('span', { class: 'small', text: ` ${a.action}` })]))));
    }
    put(outlookBox, h('p', { class: 'small', text: planSentence(card.plan, L) }));
  } else {
    put(outlookBox, h('p', { class: 'muted', text: t(`outlook.reason_${card.reason || 'not_run'}`, L) }));
  }
  put(main, outlookBox);

  // -- what is answered
  put(main, h('h2', { text: t('home.answered_title', L) }));
  for (const name of ['onboarding', 'intake']) {
    const q = data.questionnaires[name];
    const box = h('div', { class: 'card' }, [
      h('div', { class: 'row' }, [
        h('h3', { class: 'grow', text: t(`q.title_${name}`, L) }),
        button(q.next_question_key ? t('home.continue', L) : t('home.review', L), { onClick: () => go(`#/q/${name}`) }),
      ]),
      q.next_question ? h('p', { class: 'small' }, [h('span', { class: 'muted', text: `${t('home.next_question', L)}: ` }), q.next_question]) : null,
    ]);
    if (q.answered.length) {
      put(box, h('details', {}, [
        h('summary', { class: 'small', text: t('home.show_answers', L) }),
        h('table', { class: 'figures' }, q.answered.map((a) => h('tr', {}, [
          h('td', { class: 'small', text: a.question }), h('td', { class: 'small', text: showValue(a.value, L) })]))),
      ]));
    } else {
      put(box, h('p', { class: 'small muted', text: t('home.nothing_answered', L) }));
    }
    put(main, box);
  }
  put(main, h('p', { class: 'small muted', style: 'margin-top:2rem', text: t('notice', L) }));
}
