// The Feed. Item 5, in the Reading Room's shape — pinned groups, pinned follows, pinned vaults.
//
// The reference page at https://stk.sim-tech.ch/ was read on 4 September 2026 and carries exactly those
// three section labels. Two of them have no object behind them in this build, and they say so rather than
// being omitted or filled: a missing section looks like a build error, a section of placeholders is a lie,
// and a section that says what it is waiting for is the truth. That is the treatment the owner chose for
// the community recovery on the same day (A124).
//
// **"Vault" means two different things and this surface is careful about it.** The Reading Room's "pinned
// vaults" are collections of reading; this application's Vault is the member's own plan. The section key
// stays `vaults` so the two pages can be compared, and the member-facing label does not use the word —
// see `feed.section_vaults`.
//
// **The tap is the content hook** (item 5): it asks only for the inputs the member has not already given,
// one at a time. An item that declares nothing gets no tap at all, and is rendered as reading rather than
// as a disabled control — a greyed-out tap is a promise the product is not keeping.

import { getFeed } from '../app/api.js';
import { clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';

export function load() {
  return getFeed();
}

/** The label on the tap: what it will ask for, or that it is ready to answer straight away. */
function tap(item, language, { onTap }) {
  const hook = item.hook || {};
  if (!hook.tappable) return null;

  const label = hook.ready ? t('feed.tap_ready', language) : t('feed.tap_asks', language);
  return h('button', {
    type: 'button',
    class: 'add',
    text: label,
    onClick: () => onTap(item),
  });
}

function entry(item, language, handlers) {
  const title = (item.title || {})[language] || item.key;
  const summary = (item.summary || {})[language] || '';
  return h('li', { class: 'feed-item' }, [
    h('h3', { class: 'feed-title', text: title }),
    summary ? h('p', { class: 'feed-summary', text: summary }) : null,
    tap(item, language, handlers),
  ]);
}

function section(block, language, handlers) {
  const items = block.items || [];
  return h('section', { class: 'feed-section' }, [
    h('h2', { text: t(`feed.section_${block.key}`, language) }),
    items.length
      ? h('ul', { class: 'feed-items' }, items.map((item) => entry(item, language, handlers)))
      // A structural reason ("nothing can fill this yet") reads differently from "you have none", and the
      // server distinguishes them: `empty_reason` is null for the second.
      : h('p', {
        class: 'cell-prompt',
        text: block.empty_reason
          ? t(`feed.empty_${block.empty_reason}`, language)
          : t('feed.empty_for_you', language),
      }),
  ]);
}

export function render(host, payload, { language, onTap }) {
  clear(host);
  host.append(
    h('section', { class: 'feed' }, [
      h('h1', { text: t('feed.title', language) }),
      h('p', { class: 'field-hint', text: t('feed.lede', language) }),
      ...(payload.sections || []).map((block) => section(block, language, { onTap })),
      // Item 5's ordering is not implemented and is not faked, and the screen says so rather than letting
      // the order read as relevance.
      h('p', { class: 'lbl', text: t('feed.ordering_note', language) }),
    ]),
  );
}
