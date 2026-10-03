// The nominal / real switch (REAL_VIEW_INTERFACES.md, owner decision 6 of 29.09.2026): nominal by default
// everywhere, the basis always shown next to the figures, and the choice remembered for this browser
// (localStorage; a private window starts nominal again). Real is "in heutigen Franken": what an amount buys today.

import { button, h } from './dom.js';
import { t } from './i18n.js';

const KEY = 'eigentlich.basis';
export const BASES = ['nominal', 'real'];

export function currentBasis() {
  try { return localStorage.getItem(KEY) === 'real' ? 'real' : 'nominal'; } catch { return 'nominal'; }
}

export function setBasis(basis) {
  try { localStorage.setItem(KEY, basis === 'real' ? 'real' : 'nominal'); } catch { /* private mode: not remembered */ }
}

/** "nominal" / "in heutigen Franken": the words shown next to a figure. */
export function basisLabel(basis, L) {
  return t(basis === 'real' ? 'basis.real_short' : 'basis.nominal_short', L);
}

/** The switch: two buttons, the current one pressed, and the basis in words beside them. */
export function basisSwitch(L, onChange) {
  const basis = currentBasis();
  return h('div', { class: 'basis-switch row', role: 'group', 'aria-label': t('basis.switch', L), 'data-basis': basis }, [
    h('span', { class: 'small muted', text: `${t('basis.switch', L)}:` }),
    ...BASES.map((b) => button(t(`basis.${b}`, L), {
      'aria-pressed': String(b === basis), class: b === basis ? 'add primary' : 'add',
      onClick: () => { if (b !== currentBasis()) { setBasis(b); onChange(b); } },
    })),
    h('span', { class: 'badge quiet basis-shown', text: t(basis === 'real' ? 'basis.shown_real' : 'basis.shown_nominal', L) }),
  ]);
}
