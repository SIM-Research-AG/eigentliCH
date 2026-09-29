// The client picker (owner decision, 9.1): every client record from the view `client_overview`, and
// "new client". Picking one sets the client for this browser session. No sign-in.

import { api, detailText } from '../app/api.js';
import { button, clear, field, h, notice, put } from '../app/dom.js';
import { t } from '../app/i18n.js';

export async function render(main, { language, chooseClient, go }) {
  const L = language;
  put(main, 
    h('span', { class: 'lbl', text: t('picker.eyebrow', L) }),
    h('h1', { text: t('picker.title', L) }),
    h('p', { class: 'lede', text: t('picker.lede', L) }),
  );

  const search = h('input', { type: 'search', placeholder: t('picker.search', L), 'aria-label': t('picker.search', L) });
  const list = h('ul', { class: 'list' });
  const newBox = h('div');
  put(main, h('div', { class: 'row' }, [
    h('div', { class: 'search grow' }, [search]),
    button(t('picker.new', L), { class: 'primary', onClick: () => { newBox.hidden = !newBox.hidden; } }),
  ]), newBox, list);

  // -- new client
  newBox.hidden = true;
  const name = h('input', { type: 'text', maxlength: '200', required: true });
  const age = h('input', { type: 'number', min: '18', max: '120', step: '1', required: true });
  const err = h('div');
  put(newBox, h('form', {
    class: 'form card',
    onSubmit: async (event) => {
      event.preventDefault();
      clear(err);
      try {
        const c = await api.createClient({ display_name: name.value.trim(), age_at_registration: Number(age.value),
          locale: L === 'en' ? 'en-CH' : 'de-CH' });
        chooseClient(c);
        go('#/q/onboarding');
      } catch (e) { put(err, notice(detailText(e), 'error')); }
    },
  }, [
    h('h3', { text: t('picker.new_title', L) }),
    field(t('picker.name', L), name, t('picker.name_hint', L)),
    field(t('picker.age', L), age, t('picker.age_hint', L)),
    err,
    h('div', { class: 'actions' }, [h('button', { type: 'submit', class: 'primary', text: t('picker.create', L) })]),
  ]));

  let clients = [];
  try {
    clients = await api.clients();
  } catch (e) {
    put(main, notice(detailText(e), 'error'));
    return;
  }

  function draw() {
    clear(list);
    const q = search.value.trim().toLowerCase();
    const shown = clients.filter((c) => !q || c.display_name.toLowerCase().includes(q));
    if (!shown.length) put(list, h('li', { class: 'muted', text: t('picker.none', L) }));
    for (const c of shown) {
      const flags = [];
      if (c.threads_awaiting_answer > 0) flags.push(h('span', { class: 'badge wait', text: t('picker.flag_threads', L) }));
      if (c.approvals_awaiting_curator > 0) flags.push(h('span', { class: 'badge wait', text: t('picker.flag_approvals', L) }));
      if (c.report_requests_open > 0) flags.push(h('span', { class: 'badge wait', text: t('picker.flag_reports', L) }));
      if (!c.onboarding_completed_at) flags.push(h('span', { class: 'badge quiet', text: t('picker.flag_onboarding', L) }));
      put(list, h('li', { style: 'padding:0;border:0;background:none' }, [
        h('button', {
          type: 'button', class: 'picker-item',
          onClick: () => { chooseClient(c); go('#/home'); },
        }, [
          h('div', { class: 'row' }, [
            h('span', { class: 'picker-name grow', text: c.display_name }),
            h('span', { class: 'muted', text: t('picker.age_short', L, { n: c.age_at_registration }) }),
            ...flags,
          ]),
        ]),
      ]));
    }
  }
  search.addEventListener('input', draw);
  draw();
}
