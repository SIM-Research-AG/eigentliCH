// Render every surface this work touched, for real, against a running server.
//
// **Why this exists.** `tests/test_client_*.py` read the client's SOURCE — joins, strings, structure,
// vocabulary — and they are good at that. None of them executes a line of it. A typo in an import, a null
// dereference in a render, a `.map` on something the server returned as null: every one of those passes
// the whole Python suite and fails the moment a member opens the page.
//
// **jsdom cannot run the page as the browser does**, and that is worth stating rather than working around
// silently: jsdom does not execute `<script type="module">`, so loading `index.html` in it gives an empty
// `<main>` and proves nothing. The first version of this file did exactly that and reported every screen
// blank — which looked like a catastrophic bug and was an artefact of the harness.
//
// So this sets up a DOM, imports each surface module as Node ESM — the same files the browser loads — and
// calls its exported `render` with a payload fetched from the live API. That covers the render path, which
// is where this session's new code lives. It does NOT cover `main.js`'s routing, which self-boots; the
// chrome is checked by reading the served HTML instead.
//
// **It needs jsdom, which this repo deliberately does not vendor.** A2 keeps the client free of a build
// step and C-05 keeps the served page free of any external origin; neither of those is a reason to add a
// permanent node_modules for one diagnostic. Install it for the run and remove it after:
//
//     npm install --no-save jsdom
//     python -m uvicorn eigentlich.api.main:app --port 8891      # from backend/, in the venv
//     node tools/walk_screens.mjs http://127.0.0.1:8891 <email> <password>
//     rm -rf node_modules package-lock.json
//
// Usage:  node tools/walk_screens.mjs http://127.0.0.1:8891 [email] [password]

import { JSDOM, VirtualConsole } from 'jsdom';

const BASE = process.argv[2] || 'http://127.0.0.1:8891';
const EMAIL = process.argv[3] || null;
const PASSWORD = process.argv[4] || null;

const virtualConsole = new VirtualConsole();
const dom = new JSDOM('<!doctype html><html><body><main id="main"></main><div id="live"></div></body></html>', {
  url: BASE,
  pretendToBeVisual: true,
  virtualConsole,
});

// The globals the surfaces expect. `dom.js` uses `document`; `know.js` uses `window.matchMedia`.
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.Node = dom.window.Node;
globalThis.Event = dom.window.Event;
globalThis.localStorage = dom.window.localStorage;
globalThis.matchMedia = dom.window.matchMedia || (() => ({ matches: false, addEventListener() {} }));
// `app/api.js` calls bare `fetch('/api/...')`. Node's fetch needs an absolute URL.
const hostFetch = globalThis.fetch;
globalThis.fetch = (input, init) =>
  hostFetch(typeof input === 'string' && input.startsWith('/') ? `${BASE}${input}` : input, init);
dom.window.matchMedia = globalThis.matchMedia;

let token = null;

async function api(path) {
  const headers = token ? { authorization: `Bearer ${token}` } : {};
  const response = await fetch(`${BASE}${path}`, { headers });
  if (!response.ok) throw new Error(`${path} -> ${response.status} ${await response.text()}`);
  return response.json();
}

async function signIn(email, password) {
  const response = await fetch(`${BASE}/api/session`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) throw new Error(`sign-in ${response.status}: ${await response.text()}`);
  const body = await response.json();
  token = body.token;
  if (!token) throw new Error(`sign-in returned no token; keys: ${Object.keys(body)}`);
  // Where `app/session.js` looks, so a surface's own `load()` — which goes through `app/api.js` — can be
  // used instead of a hand-built payload. That distinction cost a false alarm: the first run called
  // `containers.render` with the raw `/api/goals` body and reported "Cannot read properties of undefined",
  // which looked like a regression and was the harness. `containers.load` composes from TWO endpoints.
  dom.window.localStorage.setItem('eigentlich.session.v1', JSON.stringify(body));
  return body;
}

const results = [];

async function draw(name, load, render) {
  const host = document.getElementById('main');
  while (host.firstChild) host.removeChild(host.firstChild);
  try {
    const payload = await load();
    // Awaited: a surface whose `render` is async — `onboarding.js` fetches its own state — would
    // otherwise be measured before it had drawn anything and reported BLANK, which is the harness
    // lying about the product for the second time in this file's short life.
    await render(host, payload);
    const text = (host.textContent || '').trim().replace(/\s+/g, ' ');
    const headings = [...host.querySelectorAll('h1,h2,h3')].map((n) => n.textContent.trim());
    const buttons = [...host.querySelectorAll('button')].map((n) => n.textContent.trim());
    const status = text.length ? 'ok' : 'BLANK';
    results.push([name, status]);
    console.log(`\n${status.padEnd(5)} ${name}`);
    if (headings.length) console.log(`      headings: ${headings.slice(0, 6).join(' | ')}`);
    if (buttons.length) console.log(`      buttons : ${buttons.slice(0, 5).join(' | ')}`);
    console.log(`      chars   : ${text.length}`);
    if (text.length) console.log(`      first   : ${text.slice(0, 130)}`);
  } catch (error) {
    results.push([name, 'ERROR']);
    console.log(`\nERROR ${name}\n      ${error.message.split('\n')[0]}`);
  }
}

// ---------------------------------------------------------------- signed out

console.log('=== signed out ===');
const regime = await import('../client/surfaces/regime.js');
await draw('regime', () => api('/api/regime'), (host, p) => regime.render(host, p, { language: 'de' }));

// ---------------------------------------------------------------- signed in

if (EMAIL && PASSWORD) {
  console.log(`\n=== signed in as ${EMAIL} ===`);
  try {
    await signIn(EMAIL, PASSWORD);
  } catch (error) {
    console.log(`  !! ${error.message}`);
  }

  if (token) {
    const feed = await import('../client/surfaces/feed.js');
    const network = await import('../client/surfaces/network.js');
    const ask = await import('../client/surfaces/ask.js');
    const befund = await import('../client/surfaces/befund.js');
    const grid = await import('../client/surfaces/grid.js');
    const containers = await import('../client/surfaces/containers.js');
    const vault = await import('../client/surfaces/vault.js');

    await draw('feed', () => api('/api/feed'), (h, p) => feed.render(h, p, { language: 'de', onTap: () => {} }));
    await draw('network', () => api('/api/curators'), (h, p) => network.render(h, p, { language: 'de' }));
    await draw('regime (signed in)', () => api('/api/regime'), (h, p) => regime.render(h, p, { language: 'de' }));
    await draw('befund', () => api('/api/befund?language=de'), (h, p) => befund.render(h, p, { language: 'de' }));
    await draw('plan (role grid)', () => grid.load('de'), (h, p) => grid.render(h, p, { language: 'de', onAdd: () => {}, onOpen: () => {} }));
    await draw('containers', () => containers.load('de'), (h, p) => containers.render(h, p, { language: 'de', onChanged: () => {} }));
    await draw('documents', () => api('/api/vault'), (h, p) => vault.render(h, p, { language: 'de', memberId: 'x', onChanged: () => {} }));

    // The ask surface renders its own empty state; it takes no payload.
    await draw('ask', async () => null, (h) => ask.render(h, { language: 'de', onCurator: () => {}, onStart: () => {} }));

    // S-01, added 4 September 2026 with A127's five keys. The `choice` control is new client code and
    // the Python suite reads it without executing a line of it, which is this file's whole reason.
    // **Takes options, not a payload**: `render(container, { language, onFinished })` fetches its own
    // state through `app/api.js`, which is why the sign-in above puts the session where `session.js`
    // looks. Passing a payload as the second argument left `language` undefined and drew nothing.
    const onboarding = await import('../client/surfaces/onboarding.js');
    await draw('onboarding', async () => null, (h) =>
      onboarding.render(h, { language: 'de', onFinished: () => {} }));

    // **Every question drawn, not merely the one this member happens to be on.** Rendering the screen
    // once proves nothing about the `choice` control A127 added, because a loaded member is on question
    // one. This draws each question in turn and reports the control it actually produced — a type with no
    // branch in `controlFor` falls through to the text input, which looks perfectly fine on screen and
    // silently discards a canton.
    //
    // Done by intercepting the surface's OWN fetch rather than by clicking through, because clicking
    // writes answers, and a diagnostic that mutates a real member's record to check a control is a worse
    // trade than a stubbed `next_question_key`. Everything below the fetch is the real client path.
    console.log('\n=== every question, as the member sees it ===');
    const intake = await api('/api/onboarding?language=de');
    const realFetch = globalThis.fetch;

    for (const question of intake.questions) {
      globalThis.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.includes('/api/onboarding') && (!init || !init.method || init.method === 'GET')) {
          return new Response(
            JSON.stringify({ ...intake, next_question_key: question.key }),
            { status: 200, headers: { 'content-type': 'application/json' } },
          );
        }
        return realFetch(input, init);
      };

      const host = document.getElementById('main');
      try {
        await onboarding.render(host, { language: 'de', onFinished: () => {} });
        const control = host.querySelector('.onboarding select, .onboarding input, .onboarding textarea');
        const tag = control ? control.tagName.toLowerCase() + (control.type ? `[${control.type}]` : '') : 'NONE';
        const options = control && control.tagName === 'SELECT' ? control.options.length : null;
        const ok = Boolean(control);
        console.log(`  ${ok ? 'ok   ' : 'NONE '} ${question.key.padEnd(22)} ${question.type.padEnd(14)} <${tag}>` + (options === null ? '' : ` ${options} options`));
        if (!ok) {
          results.push([`intake:${question.key}`, 'NO CONTROL']);
          // Printed, because a render that quietly drew its own error notice is exactly what this
          // reported as 'no control' the first time it ran, and the notice says why.
          console.log(`        drew: ${(host.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120)}`);
        }
        // A choice must offer its own options plus the empty first one. A `choice` falling through to
        // the text branch would render an <input> and be caught above; one rendering a <select> with
        // the wrong list would not, and that is the quieter failure.
        if (question.type === 'choice' && options !== (question.options.length + 1)) {
          console.log(`        expected ${question.options.length + 1} options, got ${options}`);
          results.push([`intake:${question.key} options`, 'WRONG COUNT']);
        }
      } catch (error) {
        results.push([`intake:${question.key}`, 'ERROR']);
        console.log(`  ERROR ${question.key.padEnd(22)} ${error.message.split('\n')[0]}`);
      }
    }
    globalThis.fetch = realFetch;
  }
}

// ---------------------------------------------------------------- the chrome, from the served HTML

const shell = new JSDOM(await (await fetch(`${BASE}/`)).text());
const chrome = shell.window.document.querySelector('header.chrome');
console.log('\n=== chrome (served markup) ===');
console.log('  doors        :', [...chrome.querySelectorAll('.door')].map((a) => a.getAttribute('href')).join(' '));
console.log('  wordmark href:', chrome.querySelector('.wordmark')?.getAttribute('href'));

const bad = results.filter(([, status]) => status !== 'ok');
console.log(`\n=== ${bad.length ? `${bad.length} not ok: ${bad.map(([n]) => n).join(', ')}` : `all ${results.length} surfaces rendered`} ===`);
