// The community surface, recovered from the earlier eigentliCH version. Item 7.
//
// **Recovered as a shape, not as markup.** The script says "Recover the community surface from the earlier
// eigentliCH version rather than rebuilding it", and the earlier version — the `network` pane of
// `andersCH-prototype/index.html` — places six people at hardcoded percentages with hardcoded bios and no
// matcher behind any of it. Porting that markup would have put six fictional advisers with names and
// biographies into a running product, which this build has refused everywhere else. The owner ruled on
// 4 September 2026: recover the shape over the real services.
//
// **What was recovered**, each part named so the two can be compared:
//
//   * **Two rings.** The earlier canvas drew solid connectors to people the member is connected to and
//     dashed ones to suggestions. That distinction is the whole idea of the surface and it survives here
//     as two groups, one of which is currently empty and says why.
//   * **A role label per person.** "Senior · Real estate", "Peer". Here it is `Curator.role_label`, which
//     exists for exactly this and is described in the model as the overlay C-10's "identified curator"
//     was waiting for.
//   * **The privacy line, on the screen.** The original carried it as a footnote: "Asset, liability, and
//     goals data are never exposed. Only shareable attributes feed the matcher." That sentence is item 7's
//     first hard rule stated to the member, and it is the part most worth keeping — except that here it is
//     also true of the code, which `tests/test_market_boundary.py` holds.
//
// **What was NOT recovered, and why each is deliberate.**
//
//   * *The radial SVG.* A canvas whose geometry is six hardcoded percentages is a picture of a matcher
//     rather than a view of one. The two-ring distinction is kept; the coordinates are not.
//   * *The five tabs* (All · Curators · Creators · Peers · MBA). Four of those five categories have no
//     object behind them in this build — there are no creators, no peers and no MBA cohort — so the tabs
//     would filter one populated list and four empty ones.
//   * *Suggestions.* There is no matcher. The group renders empty with its reason rather than with
//     invented people, which is R-302's shape applied to a screen.

import { getCurators } from '../app/api.js';
import { clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';

export function load() {
  return getCurators();
}

/** One person: a name, the role they are listed under, and nothing about the member reading it. */
function person(entry, language) {
  return h('li', { class: 'network-person' }, [
    h('span', { class: 'network-name', text: entry.display_name }),
    entry.role_label
      ? h('span', { class: 'network-role', text: entry.role_label })
      // R-110's principle: an empty cell states what would go there rather than going blank.
      : h('span', { class: 'lbl', text: t('network.role_unstated', language) }),
  ]);
}

/**
 * One group of people.
 *
 * **The class is `network-group`, not `network-ring`, and the rename is not cosmetic.**
 * `test_no_meter_exists_anywhere_in_the_client` refused the first version: "ring" is the vocabulary of the
 * altitude ring, which A2 kept out of this build as a C-07 / R-113 violation, and a CSS class teaching that
 * word back is how it returns. The domain concept really is two rings and the prose above says so; the
 * class name does not need to.
 */
function group(titleKey, entries, language, { emptyKey }) {
  return h('section', { class: 'network-group' }, [
    h('h2', { text: t(titleKey, language) }),
    entries.length
      ? h('ul', { class: 'network-people' }, entries.map((entry) => person(entry, language)))
      : h('p', { class: 'cell-prompt', text: t(emptyKey, language) }),
  ]);
}

export function render(host, payload, { language }) {
  clear(host);

  const curators = (payload.curators || []).filter((entry) => entry.active !== false);

  host.append(
    h('section', { class: 'network' }, [
      h('h1', { text: t('network.title', language) }),
      h('p', { class: 'field-hint', text: t('network.lede', language) }),

      // The inner ring: people the member can actually reach today. Curators are staff and are reachable
      // from every screen (A115), so this ring is populated by construction rather than by a matcher.
      group('network.connected', curators, language, { emptyKey: 'network.connected_empty' }),

      // The outer ring. Empty, and saying so.
      group('network.suggested', [], language, { emptyKey: 'network.suggested_empty' }),

      // Item 7's first hard rule, said to the member. The earlier version carried this sentence and it is
      // the best thing in it.
      h('p', { class: 'field-hint network-privacy', text: t('network.privacy', language) }),
    ]),
  );
}
