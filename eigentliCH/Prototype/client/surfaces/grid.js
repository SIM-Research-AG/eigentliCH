// S-02 — the role grid. The default authenticated landing screen (R-001).
//
// Four role rows x two capital columns. Below the breakpoint each role becomes one card holding both
// kinds of capital stacked (A24), because R-114 says both are shown together and a column scrolled
// off-screen is not together.
//
// **What this file must never grow.** No completion meter, no "n of 8", no progress ring, no percentage
// (R-113, R-006). The payload does not carry the numbers to build one, and that is deliberate rather than
// incidental — see `services/grid.py`. If a future change needs a count here, the constraint is the thing
// to revisit, not the payload.
//
// **Plain language only** (R-143, principle 10). No mountain, hut, tour, summit or climb vocabulary, in
// either language. The metaphor belongs in the marketing surfaces.

import { announce, button, clear, formatAmount, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getRoleGrid } from '../app/api.js';

const CAPITAL_ORDER = ['human', 'financial'];

/**
 * One position, and the three things a member may now do to it (R-122, R-123, R-160).
 *
 * **The controls are three, not one with a checkbox, and that is R-122.** Editing corrects what the
 * position *is*; deactivating changes what the live plan is. `active` is refused **by name** on the PATCH
 * route because a boolean in an edit form is how a member deactivates a position by accident — so there is
 * no checkbox here, and never should be. Whichever of deactivate/reactivate applies is the one shown: the
 * act is the control, so there is no toggle to get the wrong way round.
 *
 * The fourth link is to S-07 filtered to this position, which is the question a member asks standing in
 * front of one: what did I decide about this, and why.
 */
function positionNode(position, cell, language, { onEdit, onSetActive, onDecisions }) {
  const amount = formatAmount(position.magnitude, language === 'de' ? 'de-CH' : 'en-CH');
  const unit = position.magnitude_unit === 'chf_per_year' ? t('unit.chf_per_year', language)
    : position.magnitude_unit === 'share_of_total' ? t('unit.share_of_total', language)
    : null;

  return h('div', { class: 'position', 'data-active': String(position.active) }, [
    h('div', { class: 'position-label', text: position.label }),
    // A magnitude that is absent renders as absent. R-020: a position without one is still a position,
    // and showing "0" would be a different claim than the member made.
    amount !== null
      ? h('div', { class: 'position-magnitude', text: unit ? `${amount} ${unit}` : amount })
      : null,
    position.time_basis ? h('div', { class: 'position-meta', text: position.time_basis }) : null,
    position.active === false
      ? h('div', { class: 'position-meta', text: t('position.inactive', language) })
      : null,

    h('div', { class: 'actions position-actions' }, [
      onEdit
        ? button(t('position.edit', language), {
            class: 'add',
            onClick: () => onEdit(position, cell),
          })
        : null,
      // R-122, both directions. Reactivation exists because the mark is not one-way and making it one-way
      // would make a mis-click permanent.
      onSetActive
        ? button(
            t(position.active === false ? 'position.reactivate' : 'position.deactivate', language),
            {
              class: 'add',
              onClick: () => onSetActive(position, cell, position.active === false),
            },
          )
        : null,
      onDecisions
        ? button(t('position.see_decisions', language), {
            class: 'add',
            onClick: () => onDecisions(position),
          })
        : null,
    ]),
  ]);
}

function cellNode(cell, language, { onAdd, onEdit, onSetActive, onDecisions }) {
  const hasPositions = cell.positions.length > 0;

  const definition = h('p', {
    class: 'cell-prompt',
    text: cell.prompt || '',
    hidden: hasPositions ? '' : null,
  });

  const toggle = hasPositions
    ? button(t('cell.what_is_this', language), {
        class: 'definition-toggle',
        'aria-expanded': 'false',
        onClick: (event) => {
          const shown = definition.hasAttribute('hidden');
          if (shown) definition.removeAttribute('hidden');
          else definition.setAttribute('hidden', '');
          event.currentTarget.setAttribute('aria-expanded', String(shown));
        },
      })
    : null;

  return h('div', { class: 'cell', 'data-capital': cell.capital_type }, [
    h('span', { class: 'cell-capital', text: t(`capital.${cell.capital_type}`, language) }),
    ...cell.positions.map((p) => positionNode(p, cell, language, { onEdit, onSetActive, onDecisions })),
    // R-110: an empty cell states what would go there. The role's own definition is the honest sentence.
    definition,
    toggle,
    // R-112: adding a position is reachable from any cell in one action.
    button(t('cell.add', language), {
      class: 'add',
      onClick: () => onAdd(cell),
    }),
  ]);
}

/** Fetch the payload. Kept here so the surface owns its own data shape. */
// A11: the grid is the token's member's. There is no id to pass and none to get wrong.
export function load(language) {
  return getRoleGrid(language);
}

export function render(container, grid, { onAdd, onEdit, onSetActive, onDecisions, provisional }) {
  const language = grid.language;
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('grid.eyebrow', language) }),
    h('h1', {}, [
      t('grid.title', language),
      provisional
        ? h('span', { class: 'provisional', text: t('grid.provisional', language) })
        : null,
    ]),
    h('p', { class: 'lede', text: t('grid.lede', language) }),
  );

  const gridEl = h('div', { class: 'grid' });

  gridEl.append(
    h('div', { class: 'grid-head' }, [
      h('span', { text: '' }),
      ...CAPITAL_ORDER.map((c) => h('span', { text: t(`capital.${c}`, language) })),
    ]),
  );

  for (const roleKey of grid.roles) {
    const cells = CAPITAL_ORDER.map((capital) =>
      grid.cells.find((c) => c.role === roleKey && c.capital_type === capital),
    ).filter(Boolean);

    // The role's name differs by capital type — Wachstum vs Wertsteigerung, the manual's own Growth/Gain
    // distinction. The row label uses the human-capital name and each cell carries its own.
    const rowLabel = cells[0] ? cells[0].display : roleKey;

    gridEl.append(
      h('div', { class: 'role-row' }, [
        h('div', { class: 'role-name', text: rowLabel }),
        ...cells.map((cell) => cellNode(cell, language, { onAdd, onEdit, onSetActive, onDecisions })),
      ]),
    );
  }

  container.append(gridEl);

  const filled = grid.cells.filter((c) => c.positions.length > 0).length;
  // Announced for screen readers only, and phrased as a statement of what is there — never as progress
  // toward eight. "Eine Position erfasst", not "1 von 8".
  announce(filled === 1 ? t('grid.one_position', language) : t('grid.n_positions', language, { n: filled }));
}
