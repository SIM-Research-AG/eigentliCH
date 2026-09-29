// S-13 — the community programme. Lectures, café evenings and meet-ups, and whether the member was there.
//
// **R-222 is the first rule this file obeys, and it is a rule about words.** In this interface the word
// "events" means LIFE events, and that surface is `surfaces/life-events.js`. So nothing here is called an
// event — not in English, not in German, not in a class name, not in a string key. `models/access.py` names
// the table `Gathering` for the same reason and says "the name is the enforcement";
// `services/community.py` refuses a gathering whose own title calls itself one. This file is the third
// place that rule has to hold, because it is the only place a member reads the word.
//
// **R-221: attendance is a fact per gathering and never a standing.** The payload carries `attended` on each
// row and `attendance_is_not_scored` on the whole, and there is no aggregate anywhere in it. That is not a
// courtesy: attendance is one of R-203's three ordering inputs on the Market Place, so a number here would
// be a member's own ranking input shown back to them — which is the exact shape C-07 exists to prevent, and
// the payload's docstring says so before this screen gets the chance to draw one.
//
// So this file renders **no count, no total, no streak, no share, no "you have been to n"**, and there is
// nothing upstream to compute one from. What it does render is each gathering and, on the ones the member
// was at, that they were.
//
// **`POST /api/community/gatherings` is deliberately not rendered.** The route exists and takes a session,
// and its own docstring is explicit about what that session does and does not mean: "a session is required,
// which is the weakest honest lock ... it stops it being world-writable", and who may schedule a gathering
// is "the same open question as every other write route in this prototype". Putting a "schedule a lecture"
// form on a member's screen would answer that question in an interface — which is precisely how a
// permission gets granted without anybody deciding to. Attendance is different and is offered: the route
// writes it against the token's member and nobody else's, so it is a member recording their own fact.
//
// **C-01:** nothing here suggests attending anything. It lists what is scheduled and what the member was
// at. Which gathering to go to is their decision, and A92 records C-01 being widened to cover advice about
// a member's own decisions.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { detailText, getGatherings, recordAttendance } from '../app/api.js';

/**
 * The word for one kind, or the key.
 *
 * `services/community.py` states the division this relies on: "R-222. The key, not a word. The words live
 * in the client's string table." So the three kinds arrive as keys and are named here — and a fourth kind
 * added on the server shows up as its key rather than as a blank line.
 */
function kindLabel(kind, language) {
  const key = `community.kind_${kind}`;
  const word = t(key, language);
  return word === key ? kind : word;
}

/** `31.08.2026` from an ISO date. */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('T')[0].split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : parts.join('-');
}

/**
 * One gathering.
 *
 * `attended` is three-valued in the payload — true, false, or null when nobody is named — and the three are
 * kept apart: "you were there", the control to say so, and nothing at all. Collapsing null into false would
 * offer a member an attendance control on a screen that does not know who they are.
 */
function gatheringNode(row, { language, onChanged }) {
  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });

  const wasThere = button(t('community.was_there', language), {
    class: 'add',
    onClick: async (event) => {
      const pressed = event.currentTarget;
      pressed.disabled = true;
      error.setAttribute('hidden', '');
      try {
        await recordAttendance({ gatheringId: row.id });
        // Re-read, then announce. The screen's own announcement would otherwise overwrite this one — the
        // defect A86 found on the language switch and A94 found again on the capability form.
        await onChanged();
        announce(t('community.recorded_announced', language));
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        pressed.disabled = false;
      }
    },
  });

  return h('div', { class: 'cell gathering', 'data-attended': String(row.attended === true) }, [
    h('p', { class: 'cell-capital', text: kindLabel(row.kind, language) }),
    h('p', { class: 'position-label', text: row.title }),
    row.description ? h('p', { class: 'cell-prompt', text: row.description }) : null,
    h('p', {
      class: 'position-meta',
      text: `${t('community.held_on', language)}: ${readableDate(row.held_on, language)}`,
    }),
    row.location
      ? h('p', { class: 'position-meta', text: `${t('community.location', language)}: ${row.location}` })
      : null,
    // A41. The seed programme is invented and says so.
    row.fictional ? h('p', { class: 'field-hint', text: t('community.fictional', language) }) : null,

    // The fact, in words — not a tick, not a colour, not a filled shape. 1.4.1, and it is also what keeps
    // it from reading as one mark in a row of marks.
    row.attended === true
      ? h('p', { class: 'field-label', text: t('community.you_were_there', language) })
      : null,
    error,
    row.attended === true || row.attended === null
      ? null
      : h('div', { class: 'actions' }, [wasThere]),
  ]);
}

/** A11: whose attendance this is, is the token's member's. There is no parameter for it. */
export function load() {
  return getGatherings();
}

export function render(container, payload, { language, onChanged }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('community.eyebrow', language) }),
    h('h1', { text: t('community.title', language) }),
    h('p', { class: 'lede', text: t('community.lede', language) }),
  );

  // R-221, from the payload's own flag. Said out loud because a member who has just recorded an attendance
  // is entitled to know where it goes — it is an input to the Market Place ordering, and it is not a mark
  // against their name.
  if (payload.attendance_is_not_scored) {
    container.append(h('p', { class: 'field-hint', text: t('community.not_a_standing', language) }));
  }

  const rows = payload.gatherings || [];
  container.append(
    rows.length
      ? h('div', { class: 'grid gathering-list' },
        rows.map((row) => gatheringNode(row, { language, onChanged })))
      // R-110's shape: what is here, and what would be here. Not an instruction.
      : h('p', { class: 'field-hint', text: t('community.none_scheduled', language) }),
  );

  // Who schedules one, said rather than left as a missing button — see the module docstring. A member
  // looking for a way to add a gathering should read why there is none instead of hunting for it.
  container.append(h('p', { class: 'field-hint', text: t('community.who_schedules', language) }));

  announce(t('community.announced', language));
}
