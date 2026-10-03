// Minimal DOM helpers (after the prototype's app/dom.js). Nodes, never strings: `innerHTML` appears nowhere
// in this client, so a label a person typed can never become markup.

export const SVG_NS = 'http://www.w3.org/2000/svg';

/** An element with its attributes and children. Namespace-aware: `ns` (or the tag `svg`) builds it in the SVG
 *  namespace, so the charts are drawn with the same helper (EIG-68). */
export function h(tag, attrs = {}, kids = [], ns = tag === 'svg' ? SVG_NS : null) {
  const el = ns ? document.createElementNS(ns, tag) : document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'text') el.textContent = String(value);
    else if (key === 'class') { if (ns) el.setAttribute('class', value); else el.className = value; }
    else if (key === 'value' && !ns) el.value = value;
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const kid of [].concat(kids)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

/** An SVG element: `h` in the SVG namespace. */
export function svg(tag, attrs = {}, kids = []) {
  return h(tag, attrs, kids, SVG_NS);
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function button(label, attrs = {}) {
  return h('button', { type: 'button', class: 'add', ...attrs }, [label]);
}

export function field(label, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: label }), control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

export function announce(message) {
  const live = document.getElementById('live');
  if (live) live.textContent = message;
}

export function when(iso, language = 'de') {
  if (!iso) return '';
  const d = new Date(iso);
  return new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'de-CH', { dateStyle: 'medium', timeStyle: 'short' }).format(d);
}

export function notice(text, kind = '') {
  return h('div', { class: `notice ${kind}`.trim(), role: kind === 'error' ? 'alert' : null, text });
}

/** A text in the reader's language, falling back to German, then to whatever there is. */
export function tr(value, language) {
  if (value === null || value === undefined) return '';
  if (typeof value !== 'object') return String(value);
  return value[language] || value.de || Object.values(value).find((v) => typeof v === 'string') || '';
}

/** Append, skipping null, undefined and false (Element.append would print them). */
export function put(node, ...kids) {
  for (const kid of kids) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
  return node;
}
