// Reports and updates. The client asks for one; the app runs lbs for the client, adds the curator's pcp
// allocation when there is one, and asks the report engine. While an engine is down the request stays
// open and can be tried again; nothing is made up in its place. Approval only on the client's request.

import { api, detailText, jobText } from '../app/api.js';
import { button, clear, field, h, notice, when, put } from '../app/dom.js';
import { t } from '../app/i18n.js';

const POLL_MS = 3000;

function badge(state, L) {
  const kind = state === 'fulfilled' || state === 'approved' ? 'ok' : state === 'open' || state === 'awaiting_curator' ? 'wait' : 'quiet';
  return h('span', { class: `badge ${kind}`, text: t(`state.${state}`, L) });
}

async function reader(main, { language: L, client, reportId, go }) {
  put(main, h('div', { class: 'actions' }, [button(t('report.back', L), { onClick: () => go('#/reports') })]));
  put(main, h('iframe', {
    class: 'report-frame', title: t('report.frame_title', L), src: api.reportHtmlUrl(client.id, reportId),
    // No scripts, no same-origin: the report's HTML is shown, never run (and CSP forbids it too).
    sandbox: '', referrerpolicy: 'no-referrer',
  }));
  put(main, h('p', { class: 'small muted', text: t('notice', L) }));
}

async function list(main, ctx) {
  const { language: L, client, go } = ctx;
  const root = h('div');
  put(main, 
    h('span', { class: 'lbl', text: t('report.eyebrow', L) }),
    h('h1', { text: t('report.title', L) }),
    h('p', { class: 'lede', text: t('report.lede', L) }),
    root,
  );
  let timer = null;

  async function load() {
    let rows;
    try { rows = await api.reports(client.id); } catch (e) { clear(root); put(root, notice(detailText(e), 'error')); return; }
    draw(rows);
    clearTimeout(timer);
    const busy = rows.some((r) => (r.job && r.job.state === 'running')
      || r.reports.some((x) => x.approval && x.approval.state === 'awaiting_curator'));
    if (busy) timer = setTimeout(() => { if (document.body.contains(root)) load(); }, POLL_MS);
  }

  function draw(rows) {
    clear(root);
    const err = h('div');
    const note = h('input', { type: 'text', maxlength: '1000', placeholder: t('report.note_hint', L) });
    const hasReport = rows.some((r) => r.reports.length);
    const ask = (kind) => async () => {
      clear(err);
      try { await api.requestReport(client.id, { kind, language: L, note: note.value.trim() || null }); load(); } catch (e) { put(err, notice(detailText(e), 'error')); }
    };
    put(root, h('div', { class: 'card' }, [
      field(t('report.note', L), note),
      h('div', { class: 'actions' }, [
        button(t('report.ask_report', L), { class: 'primary', onClick: ask('report') }),
        button(t('report.ask_update', L), { onClick: ask('update'), disabled: hasReport ? null : true, title: hasReport ? null : t('report.update_needs', L) }),
      ]),
      h('p', { class: 'field-hint', text: t('report.ask_hint', L) }),
      err,
    ]));

    const ul = h('ul', { class: 'list' });
    if (!rows.length) put(ul, h('li', { class: 'muted', text: t('report.none', L) }));
    for (const r of rows) {
      const itemErr = h('div');
      const li = h('li', {}, [
        h('div', { class: 'row' }, [
          h('strong', { class: 'grow', text: `${t(`report.kind_${r.kind}`, L)} · ${when(r.created_at, L)}` }),
          badge(r.state, L),
        ]),
        r.note ? h('p', { class: 'small muted', text: r.note }) : null,
      ]);
      if (r.state === 'open') {
        if (r.job && r.job.state === 'running') put(li, notice(t('report.producing', L), 'calm'));
        else {
          if (r.job && r.job.state === 'failed') put(li, h('div', { class: 'notice error', role: 'alert' }, [
            h('p', { text: t('report.failed', L) }), h('p', { class: 'small', text: jobText(r.job, L) })]));
          else put(li, h('p', { class: 'small muted', text: t('report.open_idle', L) }));
          put(li, h('div', { class: 'actions' }, [
            button(t('report.retry', L), { class: 'primary', onClick: async () => { clear(itemErr); try { await api.produce(client.id, r.id); load(); } catch (e) { put(itemErr, notice(detailText(e), 'error')); } } }),
            button(t('report.withdraw', L), { onClick: async () => { clear(itemErr); try { await api.withdrawReport(client.id, r.id); load(); } catch (e) { put(itemErr, notice(detailText(e), 'error')); } } }),
          ]));
        }
      }
      for (const rep of r.reports) {
        const a = rep.approval;
        const actions = [button(t('report.read', L), { class: 'primary', onClick: () => go(`#/reports/${rep.id}`) })];
        if (!a && !rep.revises) {
          actions.push(button(t('approval.ask', L), { onClick: async () => { clear(itemErr); try { await api.askApproval(client.id, { item: 'report', item_id: rep.id }); load(); } catch (e) { put(itemErr, notice(detailText(e), 'error')); } } }));
        } else if (a && a.state === 'awaiting_curator') {
          actions.push(button(t('approval.withdraw', L), { onClick: async () => { clear(itemErr); try { await api.withdrawApproval(client.id, a.id); load(); } catch (e) { put(itemErr, notice(detailText(e), 'error')); } } }));
        }
        put(li, h('div', { class: 'card' }, [
          h('div', { class: 'row' }, [
            h('span', { class: 'grow small', text: `${rep.revises ? t('approval.revision', L) + ' · ' : ''}${when(rep.created_at, L)}` }),
            a ? badge(a.state, L) : null,
          ]),
          a && a.event_note ? h('p', { class: 'small muted', text: `${t('approval.curator_note', L)}: ${a.event_note}` }) : null,
          h('p', { class: 'small muted', text: t(rep.allocation_artefact_id ? 'report.rests_on_both' : 'report.rests_on_sheet', L) }),
          h('div', { class: 'actions' }, actions),
        ]));
      }
      put(li, itemErr);
      put(ul, li);
    }
    put(root, ul);
  }
  load();
}

export function render(main, ctx) {
  return ctx.reportId ? reader(main, ctx) : list(main, ctx);
}
