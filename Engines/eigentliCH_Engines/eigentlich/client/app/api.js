// The only place this client talks to the server. Same origin, relative paths, no third party (C-05).
//
// No sign-in (owner decision, 9.1): the client picked on the start page is kept for this browser session
// (sessionStorage) and travels in the path of every request. There is no token and no password.

import { t } from './i18n.js';

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

const lang = () => (document.documentElement.lang === 'en' ? 'en' : 'de');

// The server words its refusals in English for the cockpit and the logs; the client reads them in the chosen
// language (owner, 29.09.2026). Each refusal a client can meet is recognised here and said in i18n's words;
// anything else gets a plain sentence for its status. The server's own text goes to the console, never the page.
const PATTERNS = [
  [/is not one of the options/, 'err.not_an_option'], [/^at least (.+)$/, 'err.at_least'], [/^at most (.+)$/, 'err.at_most'],
  [/a number is expected/, 'err.number'], [/a text is expected/, 'err.text'], [/a list of options is expected/, 'err.list'],
  [/empty answer|empty list/, 'err.empty'], [/household has at least one adult/, 'err.household_adult'],
  [/a goal needs a name/, 'err.goal_name'], [/a position needs/, 'err.position_needs'],
  [/reload and edit again/, 'err.stale_edit'], [/is not answered yet/, 'err.first_question'],
  [/already complete/, 'err.onboarding_done'], [/approval was already asked/, 'err.approval_twice'],
  [/only a waiting request can be withdrawn|decided in the meantime/, 'err.approval_state'],
  [/thread is (already )?closed|is closed; open a new thread/, 'err.thread_closed'],
  [/an update (states|needs)/, 'err.update_needs_report'], [/the report exists/, 'err.report_exists'],
  [/request was withdrawn|only an open request|already fulfilled/, 'err.request_state'],
  [/has at most 2000 characters/, 'err.too_long'], [/(question|message) is empty/, 'err.empty_text'],
  [/nothing to change/, 'err.nothing_to_change'], [/keeps its German wording/, 'err.edit_german'],
  [/every option has its own value|keeps at least one option/, 'err.edit_option_values'],
  [/is already (in|out of|active|inactive)/, 'err.already'], [/^no client /, 'err.no_client'],
  [/shares of the yearly saving would sum to (\d+) %/, 'err.shares_sum'], [/share of the yearly saving is between/, 'err.share_range'],
  [/belongs to the client or the partner/, 'err.owner'], [/a fact key is/, 'err.invalid'],
  [/is asked per goal/, 'err.per_goal'], [/amount is in today's francs/, 'err.amount_basis'], [/report's basis is/, 'err.basis'],
  [/has no balance sheet yet/, 'err.no_sheet_yet'],
];
const BY_STATUS = { 0: 'err.server_down', 403: 'err.forbidden', 404: 'err.not_found', 409: 'err.conflict', 422: 'err.invalid', 400: 'err.invalid' };

function engineSentence(engine, text, status, L) {
  const name = t(`engine.${engine}`, L, {}, t('engine.app', L));
  const key = status === 502 ? 'err.engine_refused' : /not reachable|did not answer|answered 5/.test(text || '') || status === 503
    ? 'err.engine_down' : 'err.engine_failed';
  const sentence = t(key, L, { engine: name });
  return sentence.charAt(0).toUpperCase() + sentence.slice(1);
}

/** A refusal as a sentence in the reader's language, whatever shape the server put it in. */
export function detailText(error) {
  const L = lang();
  if (!(error instanceof ApiError)) return t('err.generic', L);
  const d = error.detail;
  if (d !== null && d !== undefined) console.warn('server:', error.status, d);  // eslint-disable-line no-console
  if (d && typeof d === 'object' && !Array.isArray(d) && d.engine) return engineSentence(d.engine, d.error, error.status, L);
  if (error.status === 0) return t('err.server_down', L);
  if (typeof d === 'string') {
    for (const [re, key] of PATTERNS) {
      const m = d.match(re);
      if (m) return t(key, L, { n: m[1] || '' });
    }
  }
  if (error.status >= 500) return t('err.server', L);
  return t(BY_STATUS[error.status] || 'err.generic', L);
}

/** A failed job (a draft, a report) as a sentence: which engine, and that it can be tried again. */
export function jobText(job, L) {
  if (!job || !job.error) return '';
  return job.engine ? engineSentence(job.engine, job.error, 503, L) : t('err.generic', L);
}

async function request(method, path, body) {
  const init = { method, headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (err) {
    throw new ApiError(0, null);
  }
  const text = await response.text();
  let payload = null;
  try { payload = text ? JSON.parse(text) : null; } catch { payload = text; }
  if (!response.ok) throw new ApiError(response.status, payload && payload.detail !== undefined ? payload.detail : payload);
  return payload;
}

const enc = encodeURIComponent;
const C = (id) => `/api/clients/${enc(id)}`;

export const api = {
  health: () => request('GET', '/health'),
  clients: () => request('GET', '/api/clients'),
  createClient: (body) => request('POST', '/api/clients', body),
  client: (id) => request('GET', C(id)),
  patchClient: (id, body) => request('PATCH', C(id), body),
  home: (id, lang) => request('GET', `${C(id)}/home?language=${lang}`),

  questionnaire: (id, name, lang) => request('GET', `${C(id)}/questionnaires/${name}?language=${lang}`),
  putAnswer: (id, name, key, contentVersion, value) =>
    request('PUT', `${C(id)}/questionnaires/${name}/answers/${enc(key)}`, { content_version: contentVersion, value }),
  editQuestion: (id, name, body) => request('POST', `${C(id)}/questionnaires/${name}/edit`, body),
  history: (name) => request('GET', `/api/questionnaires/${name}/history`),
  completeOnboarding: (id) => request('POST', `${C(id)}/onboarding/complete`),

  plan: (id, lang) => request('GET', `${C(id)}/plan?language=${lang}`),
  decisions: (id, lang) => request('GET', `${C(id)}/decisions?language=${lang || 'de'}`),
  setHousehold: (id, body) => request('PUT', `${C(id)}/household`, body),
  createPosition: (id, body) => request('POST', `${C(id)}/positions`, body),
  patchPosition: (id, pid, body) => request('PATCH', `${C(id)}/positions/${enc(pid)}`, body),
  positionActive: (id, pid, active, reasoning) =>
    request('POST', `${C(id)}/positions/${enc(pid)}/${active ? 'reactivate' : 'deactivate'}`, { reasoning }),
  createGoal: (id, body) => request('POST', `${C(id)}/goals`, body),
  patchGoal: (id, gid, body) => request('PATCH', `${C(id)}/goals/${enc(gid)}`, body),
  goalActive: (id, gid, active, reasoning) =>
    request('POST', `${C(id)}/goals/${enc(gid)}/${active ? 'reactivate' : 'deactivate'}`, { reasoning }),

  balanceSheet: (id, lang) => request('GET', `${C(id)}/balance-sheet?language=${lang || 'de'}`),
  runBalanceSheet: (id, lang) => request('POST', `${C(id)}/balance-sheet?language=${lang || 'de'}`),
  restateFact: (id, key, value, reasoning) => request('PUT', `${C(id)}/facts/${enc(key)}`, { value, reasoning }),

  outlook: (id, lang, basis) => request('GET', `${C(id)}/outlook?language=${lang || 'de'}&basis=${basis || 'nominal'}`),
  runOutlook: (id, lang, basis) => request('POST', `${C(id)}/outlook?language=${lang || 'de'}&basis=${basis || 'nominal'}`),

  threads: (id) => request('GET', `${C(id)}/threads`),
  thread: (id, tid) => request('GET', `${C(id)}/threads/${enc(tid)}`),
  ask: (id, body) => request('POST', `${C(id)}/threads`, body),
  message: (id, tid, body) => request('POST', `${C(id)}/threads/${enc(tid)}/messages`, body),
  redraft: (id, tid) => request('POST', `${C(id)}/threads/${enc(tid)}/draft`),
  closeThread: (id, tid) => request('POST', `${C(id)}/threads/${enc(tid)}/close`),

  askApproval: (id, body) => request('POST', `${C(id)}/approvals`, body),
  withdrawApproval: (id, aid) => request('POST', `${C(id)}/approvals/${enc(aid)}/withdraw`),

  reports: (id) => request('GET', `${C(id)}/reports`),
  requestReport: (id, body) => request('POST', `${C(id)}/reports`, body),
  produce: (id, rid) => request('POST', `${C(id)}/reports/${enc(rid)}/produce`),
  withdrawReport: (id, rid) => request('POST', `${C(id)}/reports/${enc(rid)}/withdraw`),
  reportHtmlUrl: (id, reportId) => `${C(id)}/report/${enc(reportId)}/html`,
};
