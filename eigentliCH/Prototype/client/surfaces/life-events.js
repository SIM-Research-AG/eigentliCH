// S-09 — the seven life-event modules. The frame, and the plain statement that the content is not written.
//
// **R-183 is the whole design of this file.** "Module content is authored, not generated; the framework
// ships empty rather than filled with generated text." So there are three things this screen must do at
// once, and they pull against each other until they are said out loud:
//
//   1. **Render the frame.** R-180's four fields — first steps, what not to sign, which documents are
//      relevant, what a curator does here — are named on every module whether or not anything has been
//      written into them. The framework existing is the deliverable; a member has to be able to see the
//      shape of what is coming.
//   2. **Say plainly that it is not written.** Not "no data", not an empty panel, not a spinner that
//      resolves to nothing. `authored: false` and `unauthored_reason` are on every module and on the file
//      itself, and this screen states them as a sentence.
//   3. **Invent nothing.** No placeholder first step, no example of a document not to sign, no generated
//      summary. R-183 exists because generated content in this position is advice with nobody's name on
//      it — which is C-01 as well as R-183.
//
// **And it does not hide a module because it is empty.** All seven are listed. `life_event_modules`'s own
// docstring gives the reason: a list that dropped the unauthored ones would be an empty screen with no
// explanation on it, and a member who has just been through a separation would be looking at nothing.
//
// **R-181's retrieval works, and the payload keeps two absences apart.** `vault_items` is empty here for a
// reason that is *not* "your vault is empty": an unauthored module names no document kinds, so there is
// nothing to select by. `retrieval_unavailable_reason` is set exactly when that is the case, and this file
// renders the two cases as two different sentences. Collapsing them would tell a member they hold no
// documents, which may well be false.
//
// **R-182: the key is the address.** `#/life-events?key=<key>` opens one module directly, so The Know can
// send a member into one without navigating a menu. The seven keys are stable and are the whole address —
// which is why the route carries the key rather than an index.
//
// **R-222: in this interface, "events" means LIFE events, and this is that surface.** The community screen
// never uses the word.
//
// **C-07 / R-003:** no count of modules, no "1 of 7", no marker of how many are authored. The list is a
// list.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getLifeEvent, getLifeEvents } from '../app/api.js';

/** A module's title, or its key. A key on screen is a translation gap; a blank card is a broken screen. */
function moduleTitle(record, language) {
  if (record.title) return record.title;
  const key = `life_events.module_${record.key}`;
  const word = t(key, language);
  return word === key ? record.key : word;
}

/** `31.08.2026` from an ISO date. Vault items carry an expiry and nothing else datelike. */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('T')[0].split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : parts.join('-');
}

/**
 * One of R-180's authored fields: the heading, and either its lines or the sentence saying it is unwritten.
 *
 * **The heading is rendered either way.** That is the frame R-183 asks to ship: a member can see that
 * "what not to sign" is a thing this module will hold, before anybody has written what goes in it.
 */
function authoredField(labelKey, lines, language) {
  const rows = lines || [];
  return h('div', { class: 'field' }, [
    h('span', { class: 'field-label', text: t(labelKey, language) }),
    rows.length
      ? h('ul', {}, rows.map((line) => h('li', { text: line })))
      : h('span', { class: 'field-hint', text: t('life_events.field_unwritten', language) }),
  ]);
}

/**
 * One module, in full.
 *
 * R-180's four fields in the specification's own order, then the retrieval, then the marker. The marker is
 * first on screen rather than last, so that nothing below it can be read as content — the same ordering
 * `module_payload` uses in the payload, and for the same reason.
 */
function moduleNode(payload, { language }) {
  const authored = Boolean(payload.authored);
  return h('div', { class: 'cell life-event' }, [
    // R-183, first.
    authored
      ? null
      : h('div', { class: 'notice' }, [
          h('p', { text: t('life_events.not_written', language), style: 'margin:0' }),
          h('p', { class: 'field-hint', text: t('life_events.not_written_why', language), style: 'margin:8px 0 0' }),
        ]),

    authoredField('life_events.first_steps', payload.first_steps, language),
    authoredField('life_events.do_not_sign', payload.do_not_sign, language),

    // R-181. The document kinds this module names, and the member's own items of those kinds.
    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('life_events.vault_kinds', language) }),
      (payload.vault_kinds || []).length
        ? h('ul', {}, payload.vault_kinds.map((kind) => h('li', { text: kind })))
        : h('span', { class: 'field-hint', text: t('life_events.vault_kinds_unwritten', language) }),
    ]),

    // The distinction the payload was careful to keep, kept here too. `retrieval_unavailable_reason` is set
    // exactly when no kinds are named, so these are three separate sentences and never one.
    payload.retrieval_unavailable_reason
      ? h('p', { class: 'field-hint', text: t('life_events.retrieval_unavailable', language) })
      : h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('life_events.your_documents', language) }),
          (payload.vault_items || []).length
            ? h('div', {}, payload.vault_items.map((item) => h('div', { class: 'position' }, [
                h('div', { class: 'position-label', text: item.title }),
                h('div', { class: 'position-meta', text: item.kind }),
                item.expiry_date
                  ? h('div', {
                      class: 'position-meta',
                      text: `${t('life_events.expires', language)}: ${readableDate(item.expiry_date, language)}`,
                    })
                  : null,
              ])))
            : h('span', { class: 'field-hint', text: t('life_events.no_documents', language) }),
        ]),

    // R-180's fourth field. A sentence about what a curator does in this situation, when somebody writes one.
    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('life_events.curator_role', language) }),
      payload.curator_role
        ? h('p', { class: 'cell-prompt', text: payload.curator_role })
        : h('span', { class: 'field-hint', text: t('life_events.field_unwritten', language) }),
    ]),

    payload.authored_by
      ? h('p', { class: 'position-meta', text: `${t('life_events.authored_by', language)}: ${payload.authored_by}` })
      : null,
  ]);
}

export function load(language) {
  return getLifeEvents(language);
}

/** R-182. One module by its key, with the member's own relevant documents already retrieved. */
export function loadOne(key, language) {
  return getLifeEvent(key, language);
}

export function render(container, payload, { language, onOpen }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('life_events.eyebrow', language) }),
    h('h1', { text: t('life_events.title', language) }),
    h('p', { class: 'lede', text: t('life_events.lede', language) }),
  );

  // R-183 at the file level, where `life_event_modules` puts it: the rule before the records.
  if (payload.authored === false) {
    container.append(h('div', { class: 'notice' }, [
      h('p', { text: t('life_events.none_written', language), style: 'margin:0' }),
      h('p', { class: 'field-hint', text: t('life_events.not_written_why', language), style: 'margin:8px 0 0' }),
    ]));
  }

  // R-180. The shape all seven share, named so a member reads what a module will hold before opening one.
  if ((payload.module_fields || []).length) {
    container.append(h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('life_events.frame_heading', language) }),
      h('ul', {}, payload.module_fields.map((name) => h('li', {
        text: t(`life_events.${name}`, language),
      }))),
    ]));
  }

  // All seven, unauthored ones included. Every card is openable: the frame and the member's own documents
  // are behind it, and neither depends on anybody having written the prose.
  container.append(
    h('div', { class: 'grid life-event-list' }, (payload.modules || []).map((record) =>
      h('div', { class: 'cell life-event-entry' }, [
        h('p', { class: 'position-label', text: moduleTitle(record, language) }),
        record.authored
          ? null
          : h('p', { class: 'field-hint', text: t('life_events.not_written', language) }),
        h('div', { class: 'actions' }, [
          button(t('life_events.open', language), { class: 'add', onClick: () => onOpen(record.key) }),
        ]),
      ]))),
  );

  announce(t('life_events.announced', language));
}

export function renderOne(container, payload, { language, onBack }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('life_events.eyebrow', language) }),
    h('h1', { text: payload.title || moduleTitle(payload, language) }),
    h('div', { class: 'actions' }, [
      button(t('life_events.back', language), { class: 'add', onClick: onBack }),
    ]),
    h('div', { class: 'grid' }, [moduleNode(payload, { language })]),
  );

  announce(t('life_events.announced_one', language));
}
