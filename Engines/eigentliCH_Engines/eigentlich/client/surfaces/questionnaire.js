// The questionnaires, rendered from the database content (questionnaire/onboarding, questionnaire/intake).
//
// R-101: every answer is PUT the moment it is given, naming the content version it answered; there is no
// draft held in the page. Resumable: the server names the next unanswered question, never a count (R-113).
// Two ways through: one question at a time, or a section at a time. The edit mode lets the client change
// the shared wording (question, why, options) and saves a new content version as saved by this client
// (owner decision, 9.1); answers already given keep naming the version they answered.

import { api, detailText } from '../app/api.js';
import { button, clear, field, h, notice, tr, when, put } from '../app/dom.js';
import { t } from '../app/i18n.js';

// ---------------------------------------------------------------------------- controls

function textControl(q, answer, L) {
  const multiline = q.multiline;
  const input = multiline ? h('textarea', { rows: '4', maxlength: '4000' }) : h('input', { type: 'text', maxlength: '4000' });
  if (q.placeholder) input.setAttribute('placeholder', tr(q.placeholder, L));
  if (typeof answer === 'string') input.value = answer;
  return { node: input, read: () => input.value.trim() || null, focus: () => input.focus(), changeEvent: 'change' };
}

function numberControl(q, answer, L) {
  const input = h('input', { type: 'number', step: 'any', min: q.min, max: q.max, inputmode: 'decimal' });
  if (typeof answer === 'number') input.value = String(answer);
  const unit = q.unit ? h('span', { class: 'field-hint', text: t(`unit.${q.unit}`, L, {}, q.unit) }) : null;
  return {
    node: h('div', {}, [input, unit]),
    read: () => (input.value.trim() === '' ? null : Number(input.value)),
    focus: () => input.focus(), changeEvent: 'change',
  };
}

// An option marked `offered: false` stays a valid answer (earlier answers, the offline form's files) but is not
// offered for a new one; it is shown only while it is the answer given (EIG-44).
const shown = (o, chosen) => o.offered !== false || chosen;

function choiceControl(q, answer, L) {
  const options = q.options || [];
  const select = h('select', {}, [h('option', { value: '', text: t('q.choose', L) })]);
  // The index, not the value: a value may be a number and a select's value is always a string.
  options.forEach((o, i) => {
    if (!shown(o, answer === o.value)) return;
    put(select, h('option', { value: String(i), selected: answer === o.value ? true : null, text: tr(o.label, L) || String(o.value) }));
  });
  return {
    node: select, read: () => (select.value === '' ? null : options[Number(select.value)].value),
    focus: () => select.focus(), changeEvent: 'change',
  };
}

function multiChoiceControl(q, answer, L) {
  const chosen = Array.isArray(answer) ? answer : [];
  const boxes = [];
  const node = h('div', { class: 'checks', role: 'group' });
  (q.options || []).forEach((o) => {
    const on = chosen.includes(o.value);
    if (!shown(o, on)) return;
    const box = h('input', { type: 'checkbox', checked: on ? true : null });
    boxes.push([box, o.value]);
    put(node, h('label', { class: 'check' }, [box, ' ', tr(o.label, L) || String(o.value)]));
  });
  return {
    node,
    read: () => { const v = boxes.filter(([b]) => b.checked).map(([, value]) => value); return v.length ? v : null; },
    focus: () => { if (boxes.length) boxes[0][0].focus(); }, changeEvent: 'change',
  };
}

function listEditor(values, placeholder, L) {
  const box = h('div', { class: 'field' });
  const rows = [];
  function add(value = '') {
    const input = h('input', { type: 'text', maxlength: '200', value, placeholder });
    const row = h('div', { class: 'row' }, [h('div', { class: 'grow' }, [input]),
      button(t('q.remove', L), { onClick: () => { row.remove(); rows.splice(rows.indexOf(input), 1); } })]);
    rows.push(input);
    box.insertBefore(row, addBtn);
  }
  const addBtn = button(t('q.add_person', L), { onClick: () => add() });
  put(box, addBtn);
  for (const v of values) add(v);
  return { node: box, read: () => rows.map((r) => r.value.trim()).filter(Boolean), add };
}

function householdControl(q, answer, L) {
  const a = answer && typeof answer === 'object' ? answer : {};
  const adults = listEditor(a.adults || [], t('q.adult_label', L), L);
  if (!(a.adults || []).length) adults.add('');
  const dependants = listEditor(a.dependants || [], t('q.dependant_label', L), L);
  const asOf = h('input', { type: 'date', value: a.as_of || '' });
  return {
    node: h('div', { class: 'form wide', style: 'margin-top:0' }, [
      h('span', { class: 'field-label', text: t('q.adults', L) }), h('span', { class: 'field-hint', text: t('q.adults_hint', L) }),
      adults.node,
      h('span', { class: 'field-label', text: t('q.dependants', L) }), dependants.node,
      field(t('q.as_of', L), asOf, t('q.as_of_hint', L)),
    ]),
    read: () => {
      const ad = adults.read();
      if (!ad.length) return null;
      const out = { adults: ad, dependants: dependants.read() };
      if (asOf.value) out.as_of = asOf.value;
      return out;
    },
    focus: () => {}, changeEvent: null,
  };
}

function goalControl(q, answer, L, templates) {
  const a = answer && typeof answer === 'object' ? answer : (typeof answer === 'string' ? { name: answer } : {});
  const template = h('select', {}, [h('option', { value: '', text: t('q.choose', L) }),
    ...templates.map((tp) => h('option', { value: tp.key, selected: a.template === tp.key ? true : null,
      text: (tp[L] && tp[L].name) || (tp.de && tp.de.name) || tp.key }))]);
  const name = h('input', { type: 'text', maxlength: '200', value: a.name || '' });
  const purpose = h('p', { class: 'field-hint' });
  template.addEventListener('change', () => {
    const tp = templates.find((x) => x.key === template.value);
    purpose.textContent = tp ? ((tp[L] || tp.de).purpose || '') : '';
    if (tp && !name.value.trim()) name.value = (tp[L] || tp.de).name || '';
  });
  return {
    node: h('div', { class: 'form wide', style: 'margin-top:0' }, [
      field(t('q.goal_template', L), template), purpose,
      field(t('q.goal_name', L), name, t('q.goal_name_hint', L)),
    ]),
    read: () => (name.value.trim() ? { template: template.value || null, name: name.value.trim() } : null),
    focus: () => template.focus(), changeEvent: null,
  };
}

function repeatControl(q, answer, L) {
  const entries = Array.isArray(answer) ? answer : [];
  const box = h('div', { class: 'form wide', style: 'margin-top:0' });
  const items = [];
  const addBtn = button(t('q.add_entry', L), { onClick: () => add({}) });
  function add(values) {
    const controls = (q.fields || []).map((f) => [f, controlFor(f, values[f.key], L, [])]);
    const card = h('div', { class: 'card' }, [
      h('div', { class: 'two' }, controls.map(([f, c]) => field(tr(f.question, L), c.node))),
      h('div', { class: 'actions' }, [button(t('q.remove', L), { onClick: () => { card.remove(); items.splice(items.indexOf(controls), 1); } })]),
    ]);
    items.push(controls);
    box.insertBefore(card, addBtn);
  }
  put(box, addBtn);
  entries.forEach(add);
  if (!entries.length) add({});
  return {
    node: box,
    read: () => {
      const rows = items.map((controls) => Object.fromEntries(controls.map(([f, c]) => [f.key, c.read()]).filter(([, v]) => v !== null)))
        .filter((r) => Object.keys(r).length);
      return rows.length ? rows : null;
    },
    focus: () => {}, changeEvent: null,
  };
}

function controlFor(q, answer, L, templates) {
  switch (q.type) {
    case 'choice': return choiceControl(q, answer, L);
    case 'multi_choice': return multiChoiceControl(q, answer, L);
    case 'number': return numberControl(q, answer, L);
    case 'household': return householdControl(q, answer, L);
    case 'goal_template': return goalControl(q, answer, L, templates);
    case 'repeat': return repeatControl(q, answer, L);
    default: return textControl(q, answer, L);
  }
}

// ---------------------------------------------------------------------------- the edit mode

function editBox(qn, q, L, { client, name, onSaved }) {
  const qde = h('textarea', { rows: '2', value: tr(q.question, 'de') });
  const qen = h('textarea', { rows: '2', value: (q.question && q.question.en) || '' });
  const wde = h('textarea', { rows: '3', value: (q.why && q.why.de) || '' });
  const wen = h('textarea', { rows: '3', value: (q.why && q.why.en) || '' });
  const note = h('input', { type: 'text', maxlength: '500', placeholder: t('edit.note_hint', L) });
  const err = h('div');
  const optionRows = [];
  const optionsBox = h('div', { class: 'field' });
  function addOption(o = { value: '', label: {} }) {
    const v = h('input', { type: 'text', value: String(o.value ?? ''), 'aria-label': t('edit.option_value', L) });
    const de = h('input', { type: 'text', value: (o.label && o.label.de) || '', 'aria-label': 'de' });
    const en = h('input', { type: 'text', value: (o.label && o.label.en) || '', 'aria-label': 'en' });
    const original = o.value;
    const row = h('div', { class: 'option-row' }, [v, de, en,
      button(t('q.remove', L), { onClick: () => { row.remove(); optionRows.splice(optionRows.indexOf(entry), 1); } })]);
    const entry = { v, de, en, original };
    optionRows.push(entry);
    optionsBox.insertBefore(row, addOpt);
  }
  const addOpt = button(t('edit.add_option', L), { onClick: () => addOption() });
  const hasOptions = q.type === 'choice' || q.type === 'multi_choice';
  if (hasOptions) {
    put(optionsBox, h('div', { class: 'option-row small muted' }, [h('span', { text: t('edit.option_value', L) }),
      h('span', { text: 'Deutsch' }), h('span', { text: 'English' }), h('span')]), addOpt);
    (q.options || []).forEach(addOption);
  }
  const save = h('button', { type: 'submit', class: 'primary', text: t('edit.save', L) });
  return h('form', {
    class: 'edit-box form wide',
    onSubmit: async (event) => {
      event.preventDefault();
      clear(err);
      const body = {
        base_version: qn.version, question_key: q.key, note: note.value.trim() || null,
        question: { de: qde.value, en: qen.value }, why: { de: wde.value, en: wen.value },
      };
      if (hasOptions) {
        body.options = optionRows.map((r) => ({
          // A number stays a number: a stored answer is compared with the option value as it was.
          value: typeof r.original === 'number' && String(r.original) === r.v.value.trim() ? r.original : r.v.value.trim(),
          label: { de: r.de.value.trim(), en: r.en.value.trim() },
        }));
      }
      save.disabled = true;
      try {
        const res = await api.editQuestion(client.id, name, body);
        onSaved(res);
      } catch (e) {
        save.disabled = false;
        put(err, notice(detailText(e), 'error'));
      }
    },
  }, [
    h('span', { class: 'lbl', text: t('edit.eyebrow', L, { key: q.key }) }),
    h('div', { class: 'two' }, [field(t('edit.question_de', L), qde), field(t('edit.question_en', L), qen)]),
    h('div', { class: 'two' }, [field(t('edit.why_de', L), wde), field(t('edit.why_en', L), wen)]),
    hasOptions ? h('div', {}, [h('span', { class: 'field-label', text: t('edit.options', L) }),
      h('p', { class: 'field-hint', text: t('edit.options_hint', L) }), optionsBox]) : null,
    field(t('edit.note', L), note),
    h('p', { class: 'field-hint', text: t('edit.shared_hint', L) }),
    err, h('div', { class: 'actions' }, [save]),
  ]);
}

// ---------------------------------------------------------------------------- the surface

export async function render(main, ctx) {
  const { language: L, client, name, go } = ctx;
  if (!['onboarding', 'intake'].includes(name)) return go('#/home');
  let qn;
  try {
    qn = await api.questionnaire(client.id, name, L);
  } catch (e) {
    put(main, notice(detailText(e), 'error'));
    return;
  }
  const answers = Object.fromEntries(Object.entries(qn.answers).map(([k, a]) => [k, a.value]));
  const byKey = Object.fromEntries(qn.questions.map((q) => [q.key, q]));
  // asked_when: {key, equals}, {key, in: [...]} (EIG-65), or a list of conditions that must all hold
  const conds = (q) => (!q.asked_when ? [] : [].concat(q.asked_when));
  const asked = (q) => conds(q).every((c) => (Array.isArray(c.in) ? c.in.includes(answers[c.key]) : answers[c.key] === c.equals));
  const modeDefault = name === 'intake' ? 'sections' : 'one';
  const mode = ctx.mode === 'sections' || ctx.mode === 'one' || ctx.mode === 'edit' ? ctx.mode : modeDefault;
  const editing = mode === 'edit';

  const saver = qn.saved_by_name ? `${t(`saved_by.${qn.saved_by_kind}`, L)} ${qn.saved_by_name}` : t(`saved_by.${qn.saved_by_kind}`, L);
  put(main, 
    h('span', { class: 'lbl', text: t(`q.eyebrow_${name}`, L) }),
    h('h1', { text: t(`q.title_${name}`, L) }),
    h('p', { class: 'lede', text: t(`q.lede_${name}`, L) }),
    h('p', { class: 'small muted', text: t('q.version_line', L, { v: qn.version, who: saver, when: when(qn.saved_at, L) }) }),
    h('div', { class: 'tabs', role: 'group', 'aria-label': t('q.mode', L) }, [
      ['one', t('q.mode_one', L)], ['sections', t('q.mode_sections', L)], ['edit', t('q.mode_edit', L)],
    ].map(([m, label]) => h('button', { type: 'button', 'aria-pressed': String(mode === m), onClick: () => go(`#/q/${name}/${m}`), text: label }))),
  );
  if (qn.onboarding_completed_at && name === 'onboarding') {
    put(main, notice(t('q.onboarding_done', L, { when: when(qn.onboarding_completed_at, L) }), 'calm'));
  }
  const stage = h('div');
  put(main, stage);

  function header(q) {
    return [
      h('p', { class: 'question-text', text: tr(q.question, L) }),
      q.why ? h('p', { class: 'why', text: tr(q.why, L) }) : null,
      L === 'en' && q.question && !q.question.en ? h('p', { class: 'small muted', text: t('q.german_only', L) }) : null,
    ];
  }

  async function save(q, control, statusNode) {
    const value = control.read();
    if (value === null) return false;
    try {
      const res = await api.putAnswer(client.id, name, q.key, qn.version, value);
      answers[q.key] = res.value;
      if (statusNode) { clear(statusNode); put(statusNode, h('span', { class: 'saved', text: t('q.saved', L, { v: res.content_version }) })); }
      return true;
    } catch (e) {
      if (statusNode) { clear(statusNode); put(statusNode, notice(detailText(e), 'error')); }
      return false;
    }
  }

  // -- the edit mode: every question with its editable wording
  if (editing) {
    put(stage, notice(t('edit.lede', L), 'calm'));
    for (const q of qn.questions) {
      const box = h('div', { class: 'card' });
      put(box, h('p', { class: 'small muted', text: `${q.key} · ${q.type}${q.section ? ' · ' + t('q.section', L) + ' ' + q.section : ''}` }),
        h('p', { class: 'question-text', text: tr(q.question, L) }));
      const open = button(t('edit.open', L), {
        onClick: () => {
          open.remove();
          put(box, editBox(qn, q, L, { client, name, onSaved: () => render(clear(main), ctx) }));
        },
      });
      put(box, open);
      put(stage, box);
    }
    return;
  }

  // -- one question at a time
  if (mode === 'one') {
    const order = qn.questions;
    let index = qn.next_question_key ? order.findIndex((q) => q.key === qn.next_question_key) : order.length;
    if (index < 0) index = 0;
    const step = () => {
      clear(stage);
      while (index < order.length && !asked(order[index])) index += 1;
      if (index >= order.length) {
        put(stage, h('div', { class: 'card' }, [h('p', { text: t('q.all_seen', L) })]));
        if (name === 'onboarding' && !qn.onboarding_completed_at) {
          const err = h('div');
          const done = button(t('q.complete', L), { class: 'primary' });
          done.addEventListener('click', async () => {
            clear(err);
            try { await api.completeOnboarding(client.id); go('#/plan'); } catch (e) { put(err, notice(detailText(e), 'error')); }
          });
          put(stage, h('p', { class: 'field-hint', text: t('q.complete_hint', L) }), h('div', { class: 'actions' }, [done]), err);
        }
        put(stage, h('div', { class: 'actions' }, [
          button(t('q.back', L), { onClick: () => { index = Math.max(0, order.length - 1); while (index > 0 && !asked(order[index])) index -= 1; step(); } }),
          button(t('q.to_home', L), { onClick: () => go('#/home') })]));
        return;
      }
      const q = order[index];
      const control = controlFor(q, answers[q.key], L, qn.goal_templates);
      const status = h('div');
      const back = index > 0 ? button(t('q.back', L), { onClick: () => { index -= 1; while (index > 0 && !asked(order[index])) index -= 1; step(); } }) : null;
      const form = h('form', {
        class: 'form',
        onSubmit: async (event) => {
          event.preventDefault();
          if (control.read() === null) {
            if (q.required) { control.focus(); return; }
            index += 1; step(); return;
          }
          if (await save(q, control, status)) { index += 1; step(); }
        },
      }, [
        q.section && qn.sections.length ? h('span', { class: 'lbl', text: tr((qn.sections.find((s) => s.key === q.section) || {}).title, L) }) : null,
        ...header(q), control.node, status,
        h('div', { class: 'actions' }, [
          h('button', { type: 'submit', class: 'primary', text: t('q.next', L) }),
          !q.required ? button(t('q.skip', L), { onClick: () => { index += 1; step(); } }) : null,
          back,
        ]),
      ]);
      put(stage, form);
      control.focus();
    };
    step();
    return;
  }

  // -- a section at a time
  const sections = qn.sections.length ? qn.sections : [{ key: null, title: { de: t('q.all_questions', 'de'), en: t('q.all_questions', 'en') } }];
  // A link to one question (#/q/intake/sections/<key>, from the outlook's findings) opens its section.
  const aimed = ctx.focus && byKey[ctx.focus] ? ctx.focus : qn.next_question_key;
  const nextSection = aimed && byKey[aimed] ? byKey[aimed].section : null;
  let current = sections.findIndex((s) => s.key === nextSection);
  if (current < 0) current = 0;
  const nav = h('div', { class: 'tabs' });
  const body = h('div');
  put(stage, nav, body);
  const drawSection = () => {
    clear(nav);
    sections.forEach((s, i) => put(nav, h('button', {
      type: 'button', 'aria-pressed': String(i === current), onClick: () => { current = i; drawSection(); },
      text: `${s.key ? s.key + ' ' : ''}${tr(s.title, L)}`,
    })));
    clear(body);
    const s = sections[current];
    if (s.lede) put(body, h('p', { class: 'lede', text: tr(s.lede, L) }));
    const qs = qn.questions.filter((q) => (s.key === null ? true : q.section === s.key));
    for (const q of qs) {
      const wrap = h('div', { class: 'card' });
      const drawQ = () => {
        clear(wrap);
        if (!asked(q)) { wrap.hidden = true; return; }
        wrap.hidden = false;
        const control = controlFor(q, answers[q.key], L, qn.goal_templates);
        const status = h('div');
        if (qn.answers[q.key] && answers[q.key] !== undefined) {
          put(status, h('span', { class: 'saved', text: t('q.saved', L, { v: qn.answers[q.key].content_version }) }));
        }
        put(wrap, ...header(q), control.node, status);
        if (control.changeEvent) {
          control.node.addEventListener(control.changeEvent, async () => {
            if (await save(q, control, status)) redrawDependants(q.key);
          });
        } else {
          put(wrap, h('div', { class: 'actions' }, [button(t('q.save', L), { onClick: () => save(q, control, status) })]));
        }
      };
      wrap.redraw = drawQ;
      wrap.dataset.key = q.key;
      drawQ();
      put(body, wrap);
    }
    const nav2 = h('div', { class: 'actions' }, [
      current > 0 ? button(t('q.prev_section', L), { onClick: () => { current -= 1; drawSection(); window.scrollTo(0, 0); } }) : null,
      current < sections.length - 1 ? button(t('q.next_section', L), { class: 'primary', onClick: () => { current += 1; drawSection(); window.scrollTo(0, 0); } }) : null,
    ]);
    put(body, nav2);
    const target = ctx.focus && body.querySelector(`[data-key="${ctx.focus}"]`);
    if (target) target.scrollIntoView({ block: 'center' });
    if (name === 'onboarding' && !qn.onboarding_completed_at) {
      const err = h('div');
      put(body, h('div', { class: 'actions' }, [button(t('q.complete', L), {
        class: 'primary',
        onClick: async () => { clear(err); try { await api.completeOnboarding(client.id); go('#/plan'); } catch (e) { put(err, notice(detailText(e), 'error')); } },
      })]), err);
    }
  };
  function redrawDependants(key) {
    body.querySelectorAll('.card').forEach((card) => {
      const q = byKey[card.dataset.key];
      if (q && conds(q).some((c) => c.key === key) && card.redraw) card.redraw();
    });
  }
  drawSection();
}
