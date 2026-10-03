// "Aussichten" / "Outlook" (LBSIM_INTERFACES section 7, EIG-68): what lbsim says about the client's plan over
// time. Earning power per adult ("Ihre Angabe" or "Modellwert"), the income paths with the saving each goal needs
// at a return of zero, the findings with their next steps and a link to the question that answers them, the three
// charts with the nominal / real switch, the Regimes by the house's labels with the chances as numbers, and the
// plan calculation's figures for this period, framed as what the calculation assumes, never as a recommendation.
//
// One language per page; the server sends lbsim's words in this page's language and names instead of ids.

import { api, detailText } from '../app/api.js';
import { button, clear, h, notice, put, when } from '../app/dom.js';
import { amount, chance as chanceText, count, rate, share } from '../app/format.js';
import { t } from '../app/i18n.js';
import { basisLabel, basisSwitch, currentBasis } from '../app/basis.js';
import { capitalPathChart, fanChart, fitChart, weightsChart } from '../app/charts.js';

const chfText = (v, L) => (v === null || v === undefined ? t('sheet.open', L) : `CHF ${amount(v, L)}`);
const yearly = (v, L) => (v === null || v === undefined ? t('sheet.open', L) : `CHF ${amount(v, L)} ${t('unit.per_year', L)}`);

function day(iso, L) {
  if (!iso) return '';
  return new Intl.DateTimeFormat(L === 'en' ? 'en-GB' : 'de-CH', { dateStyle: 'medium' }).format(new Date(`${iso}T12:00:00`));
}

/** "In 68 % der simulierten Verläufe …": a chance in words, rounded as every chance is (ROUNDING.md). */
export function chanceWords(chance, L) {
  return t('outlook.in_share_of_paths', L, { p: chanceText(chance || 0, L) });
}

/** The plan calculation's state in a sentence (also the home card's). */
export function planSentence(plan, L) {
  if (!plan || !plan.state) return '';
  if (plan.state === 'calculating') {
    const minutes = count(Math.max(1, (plan.elapsed_s || 0) / 60), L);
    const hours = count(Math.max(1, (plan.budget_s || 7200) / 3600), L);
    return t('outlook.plan_calculating', L, { minutes, hours });
  }
  if (plan.state === 'ready') return t('outlook.plan_ready', L);
  return plan.reason || t(`outlook.plan_${plan.state}`, L);
}

function links(list, L) {
  if (!list || !list.length) return null;
  return h('div', { class: 'actions' }, list.map((l) => h('a', { class: 'link', href: l.href,
    text: l.question ? `→ ${l.question}` : `→ ${t('outlook.to_question', L)}` })));
}

function earningBlock(data, L) {
  const box = h('div');
  put(box, h('h2', { text: t('outlook.earning_title', L) }), h('p', { class: 'muted', text: t('outlook.earning_lede', L) }));
  for (const e of data.earning_power) {
    const rows = [];
    const used = e.level_basis === 'stated' ? t('outlook.level_stated', L) : t('outlook.level_modelled', L);
    rows.push([t('outlook.level_used', L), used]);
    if (e.stated_chf !== null && e.stated_chf !== undefined) rows.push([t('outlook.stated', L), yearly(e.stated_chf, L)]);
    if (e.modelled_full_time_chf !== null && e.modelled_full_time_chf !== undefined) rows.push([t('outlook.modelled', L), yearly(e.modelled_full_time_chf, L)]);
    if (e.current_income_chf !== null && e.current_income_chf !== undefined) {
      rows.push([t('outlook.current', L), `${yearly(e.current_income_chf, L)}${e.pensum ? ` · ${t('outlook.pensum', L)} ${share(e.pensum, L)}` : ''}`]);
    }
    if (e.responsibility) rows.push([t('outlook.responsibility', L), `${e.responsibility}${e.responsibility_stated ? '' : ` (${t('outlook.assumed', L)})`}`]);
    if (e.education && e.education.status && e.education.status !== 'none') {
      rows.push([t('outlook.education', L), `${t(`outlook.edu_${e.education.status}`, L)}${e.education.end_year ? ` · ${t('outlook.until', L)} ${e.education.end_year}` : ''}`]);
    }
    put(box, h('div', { class: 'card' }, [
      h('h3', { text: e.name || t('gap.this_person', L) }),
      e.available ? null : notice(e.reason || t('outlook.not_available', L), 'calm'),
      h('table', { class: 'figures' }, rows.map(([k, v]) => h('tr', {}, [h('th', { text: k }), h('td', { text: v })]))),
      e.caveats.length ? h('ul', { class: 'small muted' }, e.caveats.map((c) => h('li', { text: c }))) : null,
    ]));
  }
  return box;
}

function pathsBlock(data, basis, L) {
  const box = h('div');
  put(box, h('h2', { text: t('outlook.paths_title', L) }));
  if (data.zero_return_note) put(box, h('p', { class: 'muted', text: data.zero_return_note }));
  for (const p of data.income_paths) {
    const head = h('tr', {}, [t('outlook.goal', L), t('outlook.target', L), t('outlook.saving_zero', L),
      t('outlook.free', L), t('outlook.holds', L)].map((x) => h('th', { text: x })));
    const rows = p.goals.map((g) => {
      const v = g[basis] || {};
      return h('tr', {}, [
        h('td', { text: `${g.goal || t('gap.this_goal', L)}${g.date ? ` · ${day(g.date, L)}` : ''}` }),
        h('td', { class: 'num', text: chfText(v.target_chf, L) }),
        h('td', { class: 'num', text: yearly(v.saving_chf_per_year, L) }),
        h('td', { class: 'num', text: yearly(v.free_chf_per_year, L) }),
        h('td', { text: g.holds ? t('outlook.yes', L) : t('outlook.no', L) }),
      ]);
    });
    put(box, h('div', { class: 'card' }, [
      h('h3', { text: `${p.name || ''}${p.person ? ` · ${p.person}` : ''}` }),
      p.note ? h('p', { class: 'small muted', text: p.note }) : null,
      h('table', { class: 'figures' }, [head, ...rows]),
      h('p', { class: 'small muted', text: `${t('basis.switch', L)}: ${basisLabel(basis, L)}` }),
    ]));
  }
  return box;
}

function findingsBlock(data, L) {
  const box = h('div');
  put(box, h('h2', { text: t('outlook.findings_title', L) }));
  if (!data.findings.length) put(box, h('p', { class: 'muted', text: t('outlook.no_findings', L) }));
  for (const f of data.findings) {
    put(box, h('div', { class: 'card' }, [
      h('div', { class: 'row' }, [h('h3', { class: 'grow', text: f.title }),
        h('span', { class: 'badge wait', text: t(`severity.${f.severity}`, L) }),
        h('span', { class: 'badge quiet', text: t(`urgency.${f.urgency}`, L) })]),
      h('p', { text: f.trigger }), h('p', { class: 'why', text: f.why }),
      h('p', {}, [h('strong', { text: `${t(`action.${f.action_kind}`, L)}: ` }), f.action]),
      links(f.links, L),
    ]));
  }
  if (data.schedule.length) {
    put(box, h('h3', { text: t('outlook.schedule', L) }), h('ul', { class: 'list' }, data.schedule.map((s) =>
      h('li', {}, [h('strong', { text: s.label }), h('span', { class: 'small', text: ` ${s.titles.join(' · ')}` })]))));
  }
  if (data.unchecked.length) {
    put(box, h('details', {}, [h('summary', { class: 'small', text: t('outlook.unchecked', L) }),
      h('ul', {}, data.unchecked.map((u) => h('li', { class: 'small' }, [u.reason || '', links(u.links, L)])))]));
  }
  if (data.assumptions.length) {
    put(box, h('h3', { text: t('outlook.assumptions', L) }), h('table', { class: 'figures' }, data.assumptions.map((a) =>
      h('tr', {}, [h('th', { text: a.text || '' }),
        h('td', { class: 'num', text: a.unit === 'rate' ? rate(a.value, L) : a.unit === 'share' ? share(a.value, L) : (amount(a.value, L) ?? '') })]))));
  }
  return box;
}

function planBlock(plan, L) {
  const box = h('div', { class: 'card' });
  put(box, h('h2', { text: t('outlook.plan_title', L) }), h('p', { text: planSentence(plan, L) }));
  const r = plan.ready;
  if (plan.state === 'ready' && r) {
    const a = r.action_now || {};
    const hours = (v) => `${count(v, L)} ${t('outlook.hours_week', L)}`;
    const rows = [
      ['work_share', share(a.work_share, L)], ['learning_hours_per_week', hours(a.learning_hours_per_week)],
      ['network_hours_per_week', hours(a.network_hours_per_week)], ['rest_hours_per_week', hours(a.rest_hours_per_week)],
      ['consumption_chf_per_year', yearly(a.consumption_chf_per_year, L)], ['saving_chf_per_year', yearly(a.saving_chf_per_year, L)],
      ['education_spend_chf_per_year', yearly(a.education_spend_chf_per_year, L)],
      ['network_spend_chf_per_year', yearly(a.network_spend_chf_per_year, L)],
      ['amortisation_chf_per_year', yearly(a.amortisation_chf_per_year, L)],
    ];
    put(box, h('h3', { text: t('outlook.assumes', L) }), r.framing ? h('p', { class: 'small muted', text: r.framing }) : null,
      h('table', { class: 'figures' }, rows.map(([k, v]) => h('tr', {}, [h('th', { text: t(`plan_now.${k}`, L) }), h('td', { class: 'num', text: v })]))),
      h('p', { class: 'small' }, [t(`outcome.${r.outcome}`, L),
        r.goal ? ` · ${r.goal}` : '', r.confidence ? ` · ${t('outlook.confidence', L, { p: chanceText(r.confidence, L) })}` : '',
        typeof r.chance_out_of_sample === 'number' ? ` · ${chanceWords(r.chance_out_of_sample, L)}` : '']),
      r.reachable_chf ? h('p', { class: 'small', text: t('outlook.reachable', L, { amount: chfText(r.reachable_chf, L) }) }) : null);
  }
  return box;
}

/** The goal's line on the fan: solid in the goal's own basis, dashed and marked converted in the other (LBSIM-09). */
function goalLine(goal, basis, L) {
  if (!goal || !goal.target) return null;
  const own = goal.target.amount_basis === 'today' ? 'real' : 'nominal';
  const value = basis === 'real' ? goal.target.real_chf : goal.target.nominal_chf;
  const converted = own !== basis;
  return { value, dashed: converted,
    label: `${goal.name || t('gap.this_goal', L)}: CHF ${amount(value, L)}${converted ? ` (${t('outlook.converted', L)})` : ''}` };
}

/** "Ihre vier Kapitale" over time (EIG-71): the principal's expertise, network and health from lbsim, each on its
 *  own scale with words, never on a money axis; wealth over time is the fan. A withheld health (K3) never arrives
 *  from the server, and the page says so instead of drawing it. */
export function capitalsOverTime(caps, startYear, L) {
  const box = h('div', { class: 'capitals-time' });
  put(box, h('h3', { text: t('capitals.time_title', L) }));
  if (!caps || !caps.series) {
    put(box, notice(t('capitals.not_yet', L), 'calm'));
    return box;
  }
  put(box, h('p', { class: 'small muted', text: t('capitals.time_lede', L, { name: caps.name || t('capitals.this_person', L) }) }));
  for (const key of ['expertise', 'network', 'health']) {
    const s = caps.series[key];
    if (key === 'health' && caps.health_withheld) {
      put(box, h('h4', { text: t('capitals.health', L) }), notice(t('capitals.time_withheld', L), 'calm'));
      continue;
    }
    if (!s) continue;
    const title = s.label || t(`capitals.${key}`, L);
    put(box, h('h4', { text: title }), capitalPathChart(s, startYear, {
      title, desc: t('capitals.time_desc', L), outer: t('capitals.band_outer', L), median: t('capitals.band_median', L),
      today: t('outlook.today', L), min: t('capitals.min', L), max: t('capitals.max', L),
      low: t('capitals.level_low', L), mid: t('capitals.level_mid', L), high: t('capitals.level_high', L) }, L));
  }
  return box;
}

export async function render(main, { language, client }) {
  const L = language;
  let data;
  const load = async () => { data = await api.outlook(client.id, L, currentBasis()); };
  try {
    await load();
  } catch (e) {
    put(main, notice(detailText(e), 'error'));
    return;
  }
  put(main, h('span', { class: 'lbl', text: t('outlook.eyebrow', L) }), h('h1', { text: t('outlook.title', L) }),
    h('p', { class: 'lede', text: t('outlook.lede', L) }));
  const page = h('div');
  put(main, page);
  let regime = 'base';
  let poll = null;

  const charts = h('div');
  function drawCharts(basis) {
    clear(charts);
    const p = data.paths;
    if (!p) return;
    const reg = p.regimes.find((r) => r.key === regime) || p.regimes[0];
    const a = p.allocation;
    put(charts, h('h3', { text: t('outlook.weights_title', L, { name: a.mandate_name || '' }) }),
      h('p', { class: 'small muted', text: t('outlook.weights_basis', L, { basis: basisLabel(a.allocation_basis, L) }) }),
      weightsChart(a.by_role.map((r) => ({ label: r.role, weight: r.weight })),
        { title: t('outlook.by_role', L), desc: t('outlook.by_role_desc', L) }, L),
      weightsChart(a.instruments.map((i) => ({ label: i.name, weight: i.weight })),
        { title: t('outlook.by_instrument', L), desc: t('outlook.by_instrument_desc', L) }, L));
    const curves = a.curves[basis];
    put(charts, h('h3', { text: `${t('outlook.fit_title', L)}${curves.derived ? ` (${t('outlook.converted', L)})` : ''}` }),
      fitChart(curves, { title: t('outlook.fit_title', L), desc: t('outlook.fit_desc', L), target: t('outlook.fit_target', L),
        achieved: t('outlook.fit_achieved', L), zero: t('outlook.fit_zero', L), crisis: t('outlook.crisis', L), boom: t('outlook.boom', L) }));
    const goal = reg.goals.find((g) => g.goal_id === p.designated_goal_id) || reg.goals[0];
    const series = goal && reg.bands[goal.measure] ? goal.measure : 'net_worth';
    const bands = (reg.bands[series] || {})[basis];
    if (bands) {
      const until = goal && goal.target && goal.target.date ? Number(goal.target.date.slice(0, 4)) - p.start_year : null;
      put(charts, h('h3', { text: t('outlook.fan_title', L, { regime: reg.label || '' }) }),
        h('p', { class: 'small muted', text: `${t(`series.${series}`, L)} · ${basisLabel(basis, L)}` }),
        fanChart(bands, p.start_year, until, goalLine(goal, basis, L), { title: t('outlook.fan_title', L, { regime: reg.label || '' }),
          desc: t('outlook.fan_desc', L), outer: t('outlook.fan_outer', L), inner: t('outlook.fan_inner', L),
          median: t('outlook.fan_median', L), today: t('outlook.today', L) }, L));
    }
    put(charts, capitalsOverTime(reg.capitals, p.start_year, L));
  }

  function chances(basis) {
    const p = data.paths;
    const box = h('div');
    if (!p) return box;
    put(box, h('h2', { text: t('outlook.chances_title', L) }), h('div', { class: 'tabs', role: 'group' }, p.regimes.map((r) =>
      h('button', { type: 'button', 'aria-pressed': String(r.key === regime), text: r.label || '',
        onClick: () => { regime = r.key; redrawAll(); } }))));
    const reg = p.regimes.find((r) => r.key === regime) || p.regimes[0];
    put(box, h('table', { class: 'figures chances' }, reg.goals.map((g) => h('tr', {}, [
      h('th', { text: g.name || t('gap.this_goal', L) }),
      h('td', { class: 'num', text: chanceText(g.chance || 0, L) }),
      h('td', { class: 'small muted', text: t(g.chance_basis === 'real' ? 'outlook.judged_real' : 'outlook.judged_nominal', L) }),
      h('td', { class: 'num small', text: `${chfText(basis === 'real' ? g.target.real_chf : g.target.nominal_chf, L)} · ${day(g.target.date, L)}` }),
    ]))));
    return box;
  }

  function redrawAll() {
    clear(page);
    if (poll) { clearTimeout(poll); poll = null; }
    const basis = currentBasis();
    if (!data.available) {
      put(page, notice(t(`outlook.reason_${data.reason || 'not_run'}`, L), data.reason === 'engine' ? 'error' : 'calm'));
      if (data.pending) put(page, notice(t('outlook.pending', L), 'calm'));
    } else {
      if (data.made_at) put(page, h('p', { class: 'small muted', text: t('outlook.made', L, { date: day(data.as_of, L), when: when(data.made_at, L) }) }));
      put(page, h('div', {}, [basisSwitch(L, onBasis)]));
      if (!data.paths) put(page, notice(t(`outlook.no_paths_${data.no_allocation || 'no_run'}`, L, {}, t('outlook.no_paths', L)), 'calm'));
      put(page, earningBlock(data, L), pathsBlock(data, basis, L), findingsBlock(data, L));
      if (data.paths) {
        put(page, chances(basis), charts);
        drawCharts(basis);
      }
      put(page, planBlock(data.plan, L));
      if (data.plan && data.plan.state === 'calculating') {
        poll = setTimeout(async () => {
          if (!page.isConnected) return;
          try { await load(); redrawAll(); } catch (e) { /* the next visit shows it */ }
        }, 60000);
      }
    }
    const run = button(t('outlook.run', L), { class: 'primary' });
    run.addEventListener('click', async () => {
      run.disabled = true;
      run.textContent = t('outlook.running', L);
      try { data = await api.runOutlook(client.id, L, currentBasis()); redrawAll(); } catch (e) {
        run.disabled = false; run.textContent = t('outlook.run', L);
        put(page, notice(detailText(e), 'error'));
      }
    });
    put(page, h('div', { class: 'actions' }, [run]), h('p', { class: 'small muted', text: t('notice', L) }));
  }

  async function onBasis() {
    try { await load(); } catch (e) { /* keep what is shown */ }
    redrawAll();
  }

  redrawAll();
}
