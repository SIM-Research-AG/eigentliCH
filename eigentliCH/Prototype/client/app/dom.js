// Minimal DOM helpers. No framework, no build step (A2).
//
// Everything here builds nodes rather than strings. `innerHTML` appears nowhere in this client, which is
// the cheapest way to be sure a member's own label — which they typed — can never become markup.

/** Create an element. `attrs.text` sets textContent; `attrs.html` does not exist, deliberately. */
export function h(tag, attrs = {}, kids = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    if (key === 'text') el.textContent = String(value);
    else if (key === 'class') el.className = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else el.setAttribute(key, String(value));
  }
  for (const kid of [].concat(kids)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

export function button(label, attrs = {}) {
  return h('button', { type: 'button', ...attrs }, [label]);
}

/** Announce to assistive technology without stealing focus. */
export function announce(message) {
  const live = document.getElementById('live');
  if (live) live.textContent = message;
}

/**
 * Swiss number formatting: an apostrophe thousands separator, as CHF figures are written here.
 *
 * Returns null for null. A magnitude that is absent renders as absent — R-020 makes a position without a
 * magnitude a real position, and "0" would be a different and wrong claim.
 */
export function formatAmount(value, locale = 'de-CH') {
  if (value === null || value === undefined) return null;
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(value);
}
