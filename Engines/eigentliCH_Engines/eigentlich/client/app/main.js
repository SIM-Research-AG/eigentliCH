// The shell: which client this browser session acts for, the language, the doors, and hash routing.
//
// No sign-in (owner decision, 9.1). Picking a client on the start page stores its id for this browser
// session only (sessionStorage); every request names it in its path. "Person wechseln" returns to the
// picker. There is no token, no password and nothing to log out of.

import { api, detailText } from './api.js';
import { button, clear, h, notice } from './dom.js';
import { t } from './i18n.js';
import * as picker from '../surfaces/picker.js';
import * as home from '../surfaces/home.js';
import * as questionnaire from '../surfaces/questionnaire.js';
import * as plan from '../surfaces/plan.js';
import * as threads from '../surfaces/threads.js';
import * as reports from '../surfaces/reports.js';

const KEY_CLIENT = 'eigentlich.client';
const KEY_LANG = 'eigentlich.language';

function read(storage, key) {
  try { return storage.getItem(key); } catch { return null; }
}
function write(storage, key, value) {
  try { if (value === null) storage.removeItem(key); else storage.setItem(key, value); } catch { /* private mode */ }
}

export const state = {
  language: read(localStorage, KEY_LANG) === 'en' ? 'en' : 'de',
  client: (() => { try { return JSON.parse(read(sessionStorage, KEY_CLIENT) || 'null'); } catch { return null; } })(),
};

export function chooseClient(client) {
  state.client = client ? { id: client.id, display_name: client.display_name } : null;
  write(sessionStorage, KEY_CLIENT, state.client ? JSON.stringify(state.client) : null);
  chrome();
}

function setLanguage(language) {
  state.language = language;
  write(localStorage, KEY_LANG, language);
  document.documentElement.lang = language;
  chrome();
  route();
}

const DOORS = [
  ['home', '#/home'], ['onboarding', '#/q/onboarding'], ['intake', '#/q/intake'], ['plan', '#/plan'],
  ['threads', '#/threads'], ['reports', '#/reports'],
];

function chrome() {
  const lang = state.language;
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n, lang); });
  const doors = clear(document.getElementById('doors'));
  const current = (location.hash || '#/').split('/')[1] || '';
  if (state.client) {
    for (const [key, href] of DOORS) {
      const active = href.split('/')[1] === current && (key !== 'onboarding' && key !== 'intake'
        || location.hash.startsWith(href));
      doors.append(h('a', { class: 'door', href, 'aria-current': active ? 'page' : null, text: t(`door.${key}`, lang) }));
    }
  }
  document.getElementById('who').textContent = state.client ? state.client.display_name : '';
  const sw = document.getElementById('switch');
  sw.hidden = !state.client;
  sw.onclick = () => { chooseClient(null); location.hash = '#/'; };
  const langs = clear(document.getElementById('lang'));
  for (const code of ['de', 'en']) {
    langs.append(button(code.toUpperCase(), {
      'aria-pressed': String(code === lang), 'aria-label': t(`lang.${code}`, lang), onClick: () => setLanguage(code),
    }));
  }
}

export function go(hash) {
  if (location.hash === hash) route(); else location.hash = hash;
}

async function route() {
  const main = document.getElementById('main');
  clear(main);
  chrome();
  const parts = (location.hash || '#/').replace(/^#\/?/, '').split('/');
  const ctx = { language: state.language, client: state.client, go, chooseClient };
  // A link that names the client (#/client/<id>/<page>): the same as picking it on the start page.
  if (parts[0] === 'client' && parts[1]) {
    try {
      chooseClient(await api.client(parts[1]));
      return go(`#/${parts.slice(2).join('/') || 'home'}`);
    } catch (e) {
      main.append(notice(detailText(e), 'error'));
      return picker.render(main, ctx);
    }
  }
  if (!state.client || parts[0] === '' || parts[0] === 'pick') {
    if (state.client && parts[0] === '') return go('#/home');
    return picker.render(main, ctx);
  }
  switch (parts[0]) {
    case 'home': return home.render(main, ctx);
    case 'q': return questionnaire.render(main, { ...ctx, name: parts[1] || 'onboarding', mode: parts[2] || null });
    case 'plan': return plan.render(main, ctx);
    case 'threads': return threads.render(main, { ...ctx, threadId: parts[1] || null });
    case 'reports': return reports.render(main, { ...ctx, reportId: parts[1] || null });
    default: return go('#/home');
  }
}

window.addEventListener('hashchange', () => { route(); document.getElementById('main').focus(); });
document.documentElement.lang = state.language;
route();
