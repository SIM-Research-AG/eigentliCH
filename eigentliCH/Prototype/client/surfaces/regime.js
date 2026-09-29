// The Regime pane. Item 5, and the one screen in this product that needs no account.
//
// **Why it is reachable before sign-in.** Journey & Design page 3: the regime "is population-level and
// carries no member data at all: computed once, shared by everyone", and "everything on the population
// side can be shown to anyone, before signup, without member data and without regulatory exposure". Item 5
// adds the product argument and it is the sharper one: this "is the product's most distinctive output at
// zero data cost, and today nothing exposes it to someone who has not completed an intake."
//
// **What it does NOT do.** It states no figure about the member, because it has none — `GET /api/regime`
// takes no member id and this surface sends none. It draws no chart: the payload is a handful of scalar
// readings and a provenance block, and a chart over four numbers would be decoration standing in for
// substance. And it offers no interpretation of what the reading means for anybody's plan, which is the
// first boundary and is the whole reason this screen can exist without an account.

import { getRegime } from '../app/api.js';
import { clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';

export function load() {
  return getRegime();
}

/**
 * Whether a reading has been NAMED by somebody. Found by running the page: the engine publishes
 * `mean_bin`, `mode_margin`, `modal_state` and `state` beside `crisis_tail` and `bimodal`, and the first
 * version put all of them on a public screen as headline readings — "bimodal / true", "mean_bin /
 * 10.187683837907553". Those are model internals, and a member reading them learns nothing.
 *
 * **A reading is shown when somebody has named it.** Adding a label is therefore the editorial act that
 * makes a figure public, which is the right way round: the service admits every scalar because that is a
 * safe STRUCTURAL rule (C-03), and this decides what is worth saying, which is a judgement.
 *
 * Nothing is hidden — the unnamed ones are rendered verbatim inside the collapsed fold, with their engine
 * key, so the page shows the whole reading without leading with the parts of it nobody can read.
 */
function isNamed(key, language) {
  return t(`regime.reading_${key}`, language) !== `regime.reading_${key}`;
}

/** One reading. Booleans are rendered as words: a member reading "true" has been shown a variable. */
function reading(key, value, language) {
  const label = t(`regime.reading_${key}`, language);
  const shown = typeof value === 'boolean'
    ? t(value ? 'regime.yes' : 'regime.no', language)
    : String(value);
  return [
    h('dt', { text: label === `regime.reading_${key}` ? key : label }),
    h('dd', { text: shown }),
  ];
}

export function render(host, payload, { language }) {
  clear(host);

  const section = h('section', { class: 'regime' }, [
    h('h1', { text: t('regime.title', language) }),
    h('p', { class: 'field-hint', text: t('regime.lede', language) }),
  ]);

  if (!payload.available) {
    // R-302's shape on a public page: not available, never a guess. The server's own reason is shown
    // underneath, because "the regime is unavailable" is a different thing from "no assumption set has
    // been published" and whoever installed this needs the second one.
    section.append(
      h('div', { class: 'notice' }, [
        h('p', { text: t('regime.unavailable', language), style: 'margin:0' }),
        h('p', { class: 'lbl', text: payload.reason || '', style: 'margin:8px 0 0' }),
      ]),
    );
    host.append(section);
    return;
  }

  const readings = Object.entries(payload.regime || {});
  const named = readings.filter(([key]) => isNamed(key, language));
  const unnamed = readings.filter(([key]) => !isNamed(key, language));

  if (named.length) {
    section.append(
      h('dl', { class: 'regime-readings' },
        named.flatMap(([key, value]) => reading(key, value, language))),
    );
  }

  // R-171's rule applied to a page with no member on it: a figure carries where it came from. Here that
  // is the run it was read off, so a reader can trace a public number to something replayable.
  const source = payload.source || {};
  section.append(
    h('details', { class: 'ask-caveat' }, [
      h('summary', { text: t('regime.source', language) }),
      h('dl', { class: 'ask-caveat-rows' }, [
        h('dt', { text: t('regime.source_regime', language) }),
        h('dd', { text: source.regime_id || '—' }),
        h('dt', { text: t('regime.source_scope', language) }),
        h('dd', { text: source.scope || '—' }),
        h('dt', { text: t('regime.source_as_of', language) }),
        h('dd', { text: source.as_of || '—' }),
        h('dt', { text: t('regime.source_model', language) }),
        h('dd', { text: source.model_version || '—' }),
        h('dt', { text: t('regime.source_published_by', language) }),
        h('dd', { text: source.published_by || '—' }),
        // The readings nobody has named, verbatim and with the engine's own key. Present so the page
        // shows the whole reading, folded so it does not lead with the parts a member cannot read.
        ...unnamed.flatMap(([key, value]) => [
          h('dt', { text: key }),
          h('dd', { text: String(value) }),
        ]),
      ]),
    ]),
  );

  section.append(
    h('p', { class: 'field-hint', text: t('regime.nothing_personal', language) }),
  );
  host.append(section);
}
