// Question threads. The client asks; MiniMind (the chatbot engine, which runs on the spark7 server; the store
// keeps author_kind 'spark7', EIG-48) drafts an answer from approved knowledge notes; a curator may answer in
// the cockpit; both appear here. Approval only on the client's request: "ask the curator to approve" on a
// MiniMind answer, which then shows "awaiting curator" until the curator approves or sends a revision.

import { api, detailText, jobText } from '../app/api.js';
import { button, clear, field, h, notice, when, put } from '../app/dom.js';
import { t } from '../app/i18n.js';

const POLL_MS = 2500;

function stateBadge(state, L) {
  const kind = state === 'answered' ? 'ok' : state === 'closed' ? 'quiet' : 'wait';
  return h('span', { class: `badge ${kind}`, text: t(`thread.${state}`, L) });
}

function approvalBadge(a, L) {
  if (!a) return null;
  const kind = a.state === 'approved' ? 'ok' : a.state === 'awaiting_curator' ? 'wait' : 'quiet';
  return h('span', { class: `badge ${kind}`, text: t(`state.${a.state}`, L) });
}

function draftNote(draft, L, onRetry) {
  if (!draft) return null;
  if (draft.state === 'running') return notice(t('thread.drafting', L), 'calm');
  if (draft.state === 'failed') {
    return h('div', { class: 'notice error', role: 'alert' }, [
      h('p', { text: t('thread.draft_failed', L) }), h('p', { class: 'small', text: jobText(draft, L) }),
      h('div', { class: 'actions' }, [button(t('thread.retry', L), { onClick: onRetry })]),
    ]);
  }
  return null;
}

async function list(main, { language: L, client, go }) {
  put(main, 
    h('span', { class: 'lbl', text: t('thread.eyebrow', L) }),
    h('h1', { text: t('thread.title', L) }),
    h('p', { class: 'lede', text: t('thread.lede', L) }),
  );
  const question = h('textarea', { rows: '3', maxlength: '2000', placeholder: t('thread.placeholder', L), required: true });
  const err = h('div');
  const send = h('button', { type: 'submit', class: 'primary', text: t('thread.ask', L) });
  put(main, h('form', {
    class: 'form card',
    onSubmit: async (event) => {
      event.preventDefault();
      clear(err);
      send.disabled = true;
      try {
        const res = await api.ask(client.id, { question: question.value.trim(), language: L });
        go(`#/threads/${res.thread_id}`);
      } catch (e) { send.disabled = false; put(err, notice(detailText(e), 'error')); }
    },
  }, [field(t('thread.your_question', L), question, t('thread.question_hint', L)), err, h('div', { class: 'actions' }, [send])]));

  let rows = [];
  try { rows = await api.threads(client.id); } catch (e) { put(main, notice(detailText(e), 'error')); return; }
  put(main, h('h2', { text: t('thread.list', L) }));
  const ul = h('ul', { class: 'list' });
  if (!rows.length) put(ul, h('li', { class: 'muted', text: t('thread.none', L) }));
  for (const r of rows) {
    put(ul, h('li', { style: 'padding:0;border:0;background:none' }, [h('button', {
      type: 'button', class: 'picker-item', onClick: () => go(`#/threads/${r.id}`),
    }, [h('div', { class: 'row' }, [
      h('span', { class: 'grow picker-name', text: r.subject || '—' }),
      stateBadge(r.state, L),
      r.awaiting_curator ? h('span', { class: 'badge wait', text: t('state.awaiting_curator', L) }) : null,
      r.draft && r.draft.state === 'failed' ? h('span', { class: 'badge bad', text: t('thread.draft_failed_short', L) }) : null,
      h('span', { class: 'small muted', text: when(r.last_message_at || r.created_at, L) }),
    ])])]));
  }
  put(main, ul);
}

async function view(main, ctx) {
  const { language: L, client, threadId, go } = ctx;
  const root = h('div');
  put(main, h('div', { class: 'actions' }, [button(t('thread.back', L), { onClick: () => go('#/threads') })]), root);

  let timer = null;
  const schedule = (thread) => {
    clearTimeout(timer);
    const waiting = (thread.draft && thread.draft.state === 'running') || thread.messages.some((m) => m.approval && m.approval.state === 'awaiting_curator')
      || thread.state === 'awaiting_answer';
    if (waiting) timer = setTimeout(() => { if (document.body.contains(root)) load(); }, POLL_MS);
  };

  async function load() {
    let thread;
    try { thread = await api.thread(client.id, threadId); } catch (e) { clear(root); put(root, notice(detailText(e), 'error')); return; }
    draw(thread);
    schedule(thread);
  }

  function draw(thread) {
    clear(root);
    put(root, 
      h('span', { class: 'lbl', text: t('thread.eyebrow', L) }),
      h('h1', { text: thread.subject || '—' }),
      h('div', { class: 'row', style: 'margin-top:.5rem' }, [stateBadge(thread.state, L)]),
    );
    const box = h('div', { class: 'messages' });
    for (const m of thread.messages) {
      const who = m.author_kind === 'client' ? t('thread.you', L)
        : m.author_kind === 'spark7' ? t('thread.spark7', L) : `${t('thread.curator', L)}${m.author_name ? ' ' + m.author_name : ''}`;
      const err = h('div');
      const approvalActions = [];
      if (m.author_kind === 'spark7') {
        if (!m.approval) {
          approvalActions.push(button(t('approval.ask', L), {
            onClick: async () => { try { await api.askApproval(client.id, { item: 'answer', item_id: m.id }); load(); } catch (e) { put(err, notice(detailText(e), 'error')); } },
          }));
        } else if (m.approval.state === 'awaiting_curator') {
          approvalActions.push(button(t('approval.withdraw', L), {
            onClick: async () => { try { await api.withdrawApproval(client.id, m.approval.id); load(); } catch (e) { put(err, notice(detailText(e), 'error')); } },
          }));
        }
      }
      put(box, h('div', { class: 'message', 'data-author': m.author_kind }, [
        h('div', { class: 'message-head' }, [h('strong', { text: who }), when(m.created_at, L),
          approvalBadge(m.approval, L),
          m.revises ? h('span', { class: 'badge ok', text: t('approval.revision', L) }) : null]),
        h('div', { class: 'message-body', text: m.body }),
        // Whether the answer rests on reviewed notes or is a general assessment (chat-answer basis, EIG-50).
        m.author_kind === 'spark7' && m.basis ? h('p', { class: `small basis basis-${m.basis}`, text: t(`thread.basis_${m.basis}`, L, {}, '') }) : null,
        m.author_kind === 'spark7' && m.unverified_numbers && m.unverified_numbers.length
          ? notice(t('thread.unverified', L, { numbers: m.unverified_numbers.join(', ') }), 'error') : null,
        m.sources && m.sources.length ? h('div', { class: 'sources' }, [
          h('span', { text: t('thread.sources', L) }),
          h('ul', {}, m.sources.map((s) => h('li', { text: s.source_label || s.title || s.key }))),
        ]) : null,
        m.approval && m.approval.event_note ? h('p', { class: 'small muted', text: `${t('approval.curator_note', L)}: ${m.approval.event_note}` }) : null,
        m.author_kind === 'spark7' ? h('p', { class: 'small muted', text: t('notice', L) }) : null,
        approvalActions.length ? h('div', { class: 'actions' }, approvalActions) : null, err,
      ]));
    }
    put(root, box);
    const dn = draftNote(thread.draft, L, async () => { try { await api.redraft(client.id, threadId); load(); } catch (e) { put(root, notice(detailText(e), 'error')); } });
    if (dn) put(root, dn);
    else if (thread.state === 'awaiting_answer' && thread.messages.length) put(root, notice(t('thread.waiting', L), 'calm'));

    formSlot.hidden = thread.state === 'closed';
  }

  // The follow-up form is built once, outside the redrawn part, so polling never wipes what is typed.
  const formSlot = h('div');
  const followUp = h('textarea', { rows: '3', maxlength: '2000', required: true });
  const formErr = h('div');
  put(formSlot, h('form', {
    class: 'form',
    onSubmit: async (event) => {
      event.preventDefault();
      clear(formErr);
      try {
        await api.message(client.id, threadId, { body: followUp.value.trim(), language: L });
        followUp.value = '';
        load();
      } catch (e) { put(formErr, notice(detailText(e), 'error')); }
    },
  }, [field(t('thread.follow_up', L), followUp), formErr, h('div', { class: 'actions' }, [
    h('button', { type: 'submit', class: 'primary', text: t('thread.send', L) }),
    button(t('thread.close', L), { onClick: async () => { try { await api.closeThread(client.id, threadId); load(); } catch (e) { put(formErr, notice(detailText(e), 'error')); } } }),
  ])]));
  formSlot.hidden = true;
  put(main, formSlot);
  load();
}

export function render(main, ctx) {
  return ctx.threadId ? view(main, ctx) : list(main, ctx);
}
