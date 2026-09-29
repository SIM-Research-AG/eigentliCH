// S-08 — The Know. A panel, and deliberately not a tab.
//
// **R-002 / R-170 are the whole architecture of this file.** The Know is "persistent across all
// authenticated screens, carrying a Curator button at all times". The obvious way to build that is a
// fourth navigation item, and it is the wrong one: a tab is a place you leave the current screen to visit,
// and a member who has to leave the goal they are looking at in order to ask about it has not been given a
// persistent panel. So this surface mounts **once, onto `document.body`, outside the router**. `main.js`
// clears `#main` on every route change; this node is not inside `#main` and is never cleared. It is
// alongside whatever route is active, which is what the requirement asks for.
//
// The information architecture says the same thing in one line: "Two doors and a shared third surface. The
// Know is reachable from everywhere, not from a tab." The `#/know` door in `index.html` is *Knowledge &
// Community* (S-10, S-12) — a door. This is the shared third surface.
//
// **A24 as JavaScript rather than as CSS.** `client/style/app.css` is not this agent's file, so the
// responsive rule is read from `matchMedia` and applied as inline style: docked to the right edge on a wide
// window, a drawer behind a launcher on a narrow one. The breakpoint is not the grid's 700px — see
// DOCK_QUERY below for the arithmetic.
//
// **R-173 / C-10: the Curator button names a person.** It opens a chooser built from `GET /api/curators`
// — real, active curators, by name and role label — and the id of the one the member picks is what the
// session records. There is no default, no placeholder and no "next available": C-10's column reads
// "never a role, never a queue", and a chooser that could be satisfied without a choice would be exactly
// that. When the directory is empty, or cannot be reached, the button stays where it is and the panel
// says so — R-170 carries it at all times, which includes the times there is nobody to hand a member to.
//
// **R-175: nothing here is proactive.** Action items are fetched when the panel is opened and rendered as a
// list. There is no polling, no toast, no auto-open, and no sound. Nothing in this file runs on a timer.
//
// **R-003: there is no count anywhere.** Not on a door, not on the launcher, not on the section heading.
// `index.html` has no badge element on purpose; nothing here adds one, and the section heading is a noun
// rather than a noun with a number after it.
//
// **R-113 / C-07:** no meter, no percentage, no "n of m", no points. The payloads carry none and this
// renders none.

import { button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import {
  askKnow,
  getActions,
  getCurators,
  getGoals,
  getOnboarding,
  getRoleGrid,
  openCuratorSession,
  ApiError,
} from '../app/api.js';

//: The width the docked panel takes out of the window.
const DOCK_WIDTH = 380;

//: Dock above this, drawer below it.
//
//: Not 700px (the grid's breakpoint, A24). `main` is held to `--measure` plus its padding — about 1145px —
//: and the docked panel takes DOCK_WIDTH out of the window before `main` sees any of it. Docking at 1100
//: would leave the role grid about 720px, which is close enough to the 700px card breakpoint that a member
//: could dock the panel and watch the grid collapse. 1240 leaves the grid about 860px, comfortably clear.
const DOCK_QUERY = `(min-width: ${DOCK_WIDTH + 860}px)`;

/**
 * A label for a citation's source kind.
 *
 * **This used to name two of the four kinds and print the other two as identifiers.** Every
 * corpus-grounded answer carries `book_passage` or `knowledge_entry`, so the literal strings
 * `book_passage` and `knowledge_entry` were what a member read under „Gestützt auf", in both languages —
 * on the requirement whose whole point is that an answer says where it came from.
 *
 * The raw kind is still the fallback rather than a blank, for `scopeLabel`'s reason in `curator.js`: a
 * kind this client cannot name is still a source the answer drew on, and hiding it would understate the
 * provenance. `test_client_surfaces.py` walks the kinds `services/know.py` and `services/grounding.py`
 * actually construct against the string table, so the fallback stays unused.
 */
function citationKindLabel(kind, language) {
  const label = t(`know.citation_${kind}`, language);
  return label === `know.citation_${kind}` ? kind : label;
}

/**
 * R-171: every answer says what it drew on, and — for an authored entry — what *that* was drawn from.
 *
 * **`where` and `sources` are the two fields that were in the payload and on no screen.** `where` is the
 * place inside a work a book passage sits ("Work · Chapter · Section"); `sources` is an approved
 * explainer's own `sources:` list, which `services/grounding.py` refuses to serve an entry without —
 * precisely so R-171 can cite it. Rendering the title alone made that refusal protect nothing: the member
 * saw that a Merkblatt was used and could not see what the Merkblatt itself stands on, which for the AHV
 * material is a legal reference and its `Stand`.
 */
function citationsNode(citations, language) {
  if (!citations || !citations.length) {
    return h('p', { class: 'field-hint', text: t('know.no_citations', language) });
  }
  return h('div', { class: 'field' }, [
    h('span', { class: 'lbl', text: t('know.citations', language) }),
    ...citations.map((citation) =>
      h('div', { class: 'position' }, [
        h('div', { class: 'position-label', text: citation.title }),
        h('div', {
          class: 'position-meta',
          text: citationKindLabel(citation.kind, language),
        }),
        citation.where
          ? h('div', {
              class: 'position-meta',
              text: `${t('know.citation_where', language)}: ${citation.where}`,
            })
          : null,
        // Listed rather than joined into one line: each entry is a separate reference with its own
        // `Stand`, and a comma-separated run of them reads as one citation with a long title.
        citation.sources && citation.sources.length
          ? h('div', { class: 'field' }, [
              h('span', { class: 'lbl', text: t('know.citation_sources', language) }),
              h('ul', { style: 'margin:0; padding-left:1.2em' },
                citation.sources.map((source) => h('li', { text: source }))),
            ])
          : null,
      ]),
    ),
  ]);
}

// ---------------------------------------------------------------- what an item is about (R-174)
//
// **The trigger kinds are the store's, and the store's names were reaching the screen.** `vault_expiry`
// was translated and everything else fell through to `item.trigger_kind` verbatim, so the five kinds
// `services/derive.py` emits — `plan_goal_unfunded`, `plan_goal_target_date_passed`,
// `plan_position_unrevised`, `plan_capital_type_empty`, `plan_onboarding_answer_skipped` — were read as
// identifiers by every member, in both languages.
//
// **And `derived_from` was in the payload and on no screen.** `api/main.py` joins it onto every item and
// says in its own words why: *"an item expandable to its options is not expandable to anything if it does
// not say WHICH goal, position, column or question it is about."* It said which in the JSON and not on the
// screen, which is the same defect one layer further out.

//: The cause column holds a different kind of identifier per trigger kind, so resolving it needs a
//: different lookup per kind. Keyed by the constants `services/derive.py` declares — a test walks
//: `DERIVED_TRIGGER_KINDS` against this table so a kind added there cannot quietly go unresolved here.
const GOAL_TRIGGERS = [
  'plan_goal_unfunded',
  'plan_goal_target_date_passed',
  // A112. Its cause is a goal id like the other two, so it needs no resolver of its own — the
  // member reads the name they gave the goal rather than a key.
  'plan_goal_frozen_for_division',
];
const POSITION_TRIGGER = 'plan_position_unrevised';
const CAPITAL_TRIGGER = 'plan_capital_type_empty';
const QUESTION_TRIGGER = 'plan_onboarding_answer_skipped';
//: Item 6's two. Neither needs a fetch: the confirmation's cause is the household's own id, and there is
//: exactly one household, so naming it by id would tell the member nothing they do not already know —
//: "your household" is the whole of the which. The inferred flag's cause is a published signal key, so it
//: is a translation like `CAPITAL_TRIGGER`'s rather than a lookup.
const HOUSEHOLD_TRIGGER = 'plan_household_confirmation_due';
const SIGNAL_TRIGGER = 'plan_household_change_inferred';

/**
 * The names behind the causes, fetched only for the kinds actually in the list.
 *
 * **Three requests at most, and usually none.** A member with no derived items pays nothing; one with an
 * unfunded goal pays a single `GET /api/goals`. Fetched alongside the items rather than kept, because the
 * panel outlives every route change and a name cached here would go stale the moment the member renames
 * the goal on the screen behind it.
 *
 * **A lookup that fails leaves an item unnamed rather than removing it.** The items are the point of the
 * list and a failed join is not a reason to withhold them; `know.about_unnamed` says on the item itself
 * that the reference could not be resolved, which is a true statement and an identifier is not.
 */
/**
 * The action-item list, as its own renderable. Item 4 puts an Actions pane inside the Vault — "what the
 * client has to do, with dates" — and R-174 keeps the same items in the Know panel, where they arrive as
 * items with prepared decisions rather than as notifications.
 *
 * **Two surfaces, one implementation.** The alternative was a second copy of `actionNode`, `causeNames`
 * and the "which goal" join, which is the two-implementations defect this build keeps recording — and it
 * would drift in the worst possible place, since the panel's copy and the pane's copy would then disagree
 * about what a member has to do.
 *
 * Exported rather than duplicated, and it takes a host so the caller decides where it lands.
 */
export async function renderActionList(host, payload, { language }) {
  if (!payload.items.length) {
    host.append(h('p', { class: 'cell-prompt', text: t('know.actions_empty', language) }));
    return;
  }
  // R-174's "which goal". Awaited before the first item is drawn, so the list appears once and complete
  // rather than as identifiers that are replaced a moment later by names.
  const names = await causeNames(payload.items, language);
  for (const item of payload.items) host.append(actionNode(item, language, names));
}


async function causeNames(items, language) {
  const kinds = new Set(items.map((item) => item.trigger_kind));
  const names = { goal: new Map(), position: new Map(), question: new Map() };
  const jobs = [];

  if (GOAL_TRIGGERS.some((kind) => kinds.has(kind))) {
    jobs.push(getGoals().then((payload) => {
      for (const goal of payload.goals || []) names.goal.set(goal.id, goal.name);
    }));
  }
  if (kinds.has(POSITION_TRIGGER)) {
    jobs.push(getRoleGrid(language).then((payload) => {
      for (const cell of payload.cells || []) {
        for (const position of cell.positions || []) names.position.set(position.id, position.label);
      }
    }));
  }
  if (kinds.has(QUESTION_TRIGGER)) {
    jobs.push(getOnboarding(language).then((payload) => {
      for (const question of payload.questions || []) names.question.set(question.key, question.question);
    }));
  }

  await Promise.all(jobs.map((job) => job.catch(() => null)));
  return names;
}

/** The one thing in the member's own record that caused this item, by the name they gave it. */
function causeOf(item, language, names) {
  const cause = item.derived_from;
  if (!cause) return null;
  const kind = item.trigger_kind;

  if (GOAL_TRIGGERS.includes(kind)) {
    return { label: t('know.about_goal', language), value: names.goal.get(cause) };
  }
  if (kind === POSITION_TRIGGER) {
    return { label: t('know.about_position', language), value: names.position.get(cause) };
  }
  if (kind === CAPITAL_TRIGGER) {
    // The cause IS the vocabulary here — `human` or `financial` — so this is a translation rather than a
    // lookup, and it uses the same `capital.*` keys the role grid's own column headings use.
    const word = t(`capital.${cause}`, language);
    return { label: t('know.about_capital', language), value: word === `capital.${cause}` ? undefined : word };
  }
  if (kind === QUESTION_TRIGGER) {
    return { label: t('know.about_question', language), value: names.question.get(cause) };
  }
  if (kind === HOUSEHOLD_TRIGGER) {
    // The cause is the household id and is deliberately not shown. A member has one household; naming it
    // by its opaque key would be the identifier-on-the-screen defect this table exists to close.
    return { label: t('know.about_household', language), value: undefined };
  }
  if (kind === SIGNAL_TRIGGER) {
    const word = t(`know.signal_${cause}`, language);
    return {
      label: t('know.about_signal', language),
      value: word === `know.signal_${cause}` ? undefined : word,
    };
  }
  return null;
}

/** A label for a trigger kind. Raw kind as the fallback; a test keeps the fallback unused. */
function triggerLabel(kind, language) {
  const label = t(`know.trigger_${kind}`, language);
  return label === `know.trigger_${kind}` ? kind : label;
}

/**
 * R-174. One action item, expandable to its prepared options and their consequences.
 *
 * Built as `<details class="tags">` — the same disclosure the position form uses for its correlation tags,
 * so the gesture is one the member has already met. Collapsed by default: R-175 says an item appears in a
 * list, and a list that has already unfolded itself is closer to an interruption than to a list.
 *
 * **What it is about is in the summary, not behind the disclosure.** A list of five items that all read
 * "Einem Ziel ist keine Position zugeordnet" is not a list a member can act on, and making them tell
 * themselves apart only once opened is the same failure R-174 names.
 */
function actionNode(item, language, names) {
  const trigger = triggerLabel(item.trigger_kind, language);
  const about = causeOf(item, language, names);

  const due = item.due_date
    ? `${t('know.action_due', language)}: ${item.due_date}`
    : t('know.action_no_due', language);

  return h('details', { class: 'tags' }, [
    h('summary', {}, [
      h('span', { text: trigger }),
      about && about.value
        ? h('span', {
            class: 'position-meta',
            style: 'display:block',
            text: `${about.label}: ${about.value}`,
          })
        : null,
    ]),
    about && !about.value
      ? h('p', { class: 'field-hint', text: t('know.about_unnamed', language) })
      : null,
    h('p', { class: 'field-hint', text: due }),
    h('p', { class: 'field-hint', text: t('know.action_options', language) }),
    // C-06: `prepared_options` is never empty and never has fewer than two entries — the server refuses to
    // persist an item without them. So there is no empty state to write here, and writing one would
    // suggest a notification without a prepared decision is a thing that can exist.
    ...item.prepared_options.map((option) =>
      h('div', { class: 'position' }, [
        h('div', { class: 'position-label', text: option.label }),
        h('div', { class: 'position-meta', text: option.consequence }),
        option.cost_or_benefit
          ? h('div', { class: 'position-meta', text: option.cost_or_benefit })
          : null,
      ]),
    ),
    item.source_vault_item_id
      ? h('p', { class: 'field-hint', text: t('know.action_source', language) })
      : null,
  ]);
}

export function mount(host, { getMemberId, getLanguage, getRoute, curatorId }) {
  const media = window.matchMedia(DOCK_QUERY);

  // The three regions that change independently: the answer, the curator handoff, and the item list.
  const answerRegion = h('div', { class: 'field', tabindex: '-1' });
  const curatorRegion = h('div', { class: 'field' });
  const actionsRegion = h('div', { class: 'field' });

  const question = h('textarea', { rows: '2', name: 'know_question', maxlength: '1000' });
  const askButton = h('button', { type: 'submit', class: 'primary' }, [t('know.ask_submit', 'de')]);

  let visible = false;      // is there an authenticated member to show it for
  let open = false;         // narrow only: is the drawer open
  let loadedFor = null;     // which member's items are currently rendered

  // ---------------------------------------------------------------- the curator button (R-170, R-173)

  //: The directory, once it has answered. Cached only on success, so a failed fetch is retried the next
  //: time the button is pressed rather than remembered as "nobody is there".
  let directory = null;

  /** The reason a request failed, said in the member's language with the server's own words beneath it. */
  function failureNode(message, error) {
    return h('div', { class: 'notice error' }, [
      h('p', { text: message, style: 'margin:0' }),
      h('p', {
        class: 'lbl',
        text: error instanceof ApiError ? error.detail || String(error.status) : String(error),
        style: 'margin:8px 0 0',
      }),
    ]);
  }

  /**
   * R-173 / C-10. The chosen curator's id goes onto the session, together with the screen it came from.
   *
   * `opened_from` carries both halves of the answer to "where were they when they needed a human": the
   * entry point (this panel) and the screen underneath it. The server resolves `curator_id` against the
   * `curators` table before writing anything, so a stale id from a bookmarked URL is refused there rather
   * than recorded here.
   */
  async function openWith(person, pressed) {
    const language = getLanguage();
    pressed.disabled = true;
    try {
      const record = await openCuratorSession({
        curator_id: person.id,
        opened_from: `know_panel:${getRoute()}`,
      });
      clear(curatorRegion);
      curatorRegion.append(
        h('div', { class: 'notice' }, [
          h('p', { text: t('know.curator_opened', language), style: 'margin:0' }),
          h('p', {
            class: 'lbl',
            text: `${t('know.curator_person', language)}: ${person.display_name}`,
            style: 'margin:8px 0 0',
          }),
          h('p', {
            class: 'lbl',
            text: `${t('know.curator_from', language)}: ${record.opened_from}`,
            style: 'margin:4px 0 0',
          }),
          // **R-210, said at the one moment a member would otherwise assume the opposite.** Opening a
          // session records that they asked for a human; it grants nothing. Every read under
          // `/api/curator` refuses without a live scoped grant, so the curator on the other end of this
          // session sees nothing at all until the member decides what they may see — and A90's finding was
          // that a member had no way to decide it. This is the join: the sentence, and the door to the
          // screen where the decision is made.
          h('p', {
            class: 'field-hint',
            text: t('know.curator_sees_nothing', language),
            style: 'margin:8px 0 0',
          }),
          h('div', { class: 'actions', style: 'margin-top:8px' }, [
            h('a', {
              href: '#/grants',
              class: 'add',
              style: 'text-decoration:none',
              text: t('grants.nav', language),
            }),
          ]),
        ]),
      );
    } catch (error) {
      curatorRegion.append(failureNode(t('know.error', language), error));
    } finally {
      pressed.disabled = false;
    }
  }

  /**
   * The chooser: real people, by name, each one a button that opens a session with them.
   *
   * **An empty directory is rendered, not hidden.** R-170 says the Curator button is carried at all times,
   * and "at all times" includes the times there is nobody to hand the member to. So the panel says so
   * plainly and sends nothing — writing an unidentified party into an append-only audit table would put a
   * falsehood in the one record that exists because it is true.
   *
   * R-113 / C-07: names and role labels. Nothing here counts the people, ranks them, or says how busy one
   * is — a member choosing who to talk to is not choosing from a scoreboard.
   */
  function renderChooser(people) {
    const language = getLanguage();
    clear(curatorRegion);

    if (!people.length) {
      curatorRegion.append(
        h('div', { class: 'notice' }, [
          h('p', { text: t('know.curator_unnamed', language), style: 'margin:0' }),
        ]),
      );
      return;
    }

    // `?curator=<id>` used to open a session on its own, back when nothing else could name anyone. It now
    // only puts that person first: C-10 records who the member asked for, and a query parameter they never
    // saw is not a choice they made. The URL may point at a person; it may not press the button for them.
    const ordered = curatorId
      ? [...people].sort((a, b) => Number(b.id === curatorId) - Number(a.id === curatorId))
      : people;

    const choices = ordered.map((person) =>
      h('button', {
        type: 'button',
        class: 'add',
        style: 'display:flex; flex-direction:column; align-items:flex-start; gap:2px; text-align:left;',
        onClick: (event) => openWith(person, event.currentTarget),
      }, [
        h('span', { class: 'position-label', text: person.display_name }),
        // A40's role label is an overlay on an identified person, never a substitute for one — so it is
        // rendered under the name and never instead of it.
        person.role_label ? h('span', { class: 'position-meta', text: person.role_label }) : null,
      ]),
    );

    curatorRegion.append(
      h('div', { class: 'notice' }, [
        h('p', { text: t('know.curator_choose', language), style: 'margin:0 0 8px' }),
        h('div', { class: 'actions' }, choices),
      ]),
    );
    // The member pressed a button and a chooser appeared; moving focus into it is where they already are.
    choices[0].focus();
  }

  /**
   * R-170 / R-173. Pressing the Curator button asks who is there, and then offers them by name.
   *
   * **The standing button is never disabled here.** A directory that fails to load is a reason to say so,
   * not a reason to take away the route to a human — R-170 says the panel carries a Curator button at all
   * times, and "at all times" is not conditional on a request having succeeded. Only the individual
   * person's button is disabled, and only while their session is being opened.
   */
  async function requestCurator() {
    const language = getLanguage();
    clear(curatorRegion);
    curatorRegion.append(h('p', { class: 'field-hint', text: t('know.curator_loading', language) }));

    if (directory === null) {
      try {
        directory = (await getCurators()).curators;
      } catch (error) {
        clear(curatorRegion);
        curatorRegion.append(failureNode(t('know.curator_directory_error', language), error));
        return;
      }
    }
    renderChooser(directory);
  }

  const curatorButton = button(t('know.curator', 'de'), {
    class: 'add',
    onClick: () => requestCurator(),
  });

  // ---------------------------------------------------------------- asking (R-171, R-172)

  function renderAnswer(payload) {
    const language = getLanguage();
    clear(answerRegion);

    if (payload.requires_curator) {
      // R-172. The boundary is explained and the handoff offered, and it is NOT dressed as an error: the
      // `.notice` wash rather than `.notice.error`, because nothing has gone wrong. A member who reads a
      // handoff as a fault will try to work around it, which is the opposite of what a boundary is for.
      //
      // **Unreachable from this route since 20 September 2026 (A164, A165).** This rendered C-01's
      // refusal. Kept for the same reason as `ask.js`'s copy: the flag is still set by A122's
      // undecidable liquidity lever, and a client that drops a key the server still sends fails
      // silently the day something sets it again.
      answerRegion.append(
        h('span', { class: 'lbl', text: t('know.boundary', language) }),
        h('div', { class: 'notice' }, [
          h('p', { text: payload.answer, style: 'margin:0' }),
          h('p', {
            class: 'field-hint',
            text: t('know.boundary_hint', language),
            style: 'margin:8px 0 0',
          }),
        ]),
        // The route out is offered with the refusal rather than left to be found. `curator_handoff` on the
        // payload names the same endpoint the standing button uses, so this is that button again — one
        // action, not a second mechanism to keep in step with the first.
        payload.curator_handoff
          ? h('div', { class: 'actions' }, [
              button(t('know.curator', language), {
                class: 'primary',
                onClick: () => requestCurator(),
              }),
            ])
          : null,
      );
      answerRegion.focus();
      return;
    }

    answerRegion.append(
      h('span', {
        class: 'lbl',
        // `answered: false` means the local model was not reachable. Said plainly, because the alternative
        // is a spinner that never resolves or an answer nothing produced.
        text: payload.answered ? t('know.answer', language) : t('know.unavailable', language),
      }),
      h('p', { class: 'cell-prompt', text: payload.answer }),
      // R-171: under every answer, including the one that says nothing was found.
      citationsNode(payload.citations, language),
      payload.model
        ? h('p', { class: 'field-hint', text: `${t('know.model', language)}: ${payload.model}` })
        : null,
    );
    answerRegion.focus();
  }

  const askForm = h('form', {
    class: 'position-form',
    style: 'margin-top:0; gap:var(--sp-sm)',
    onSubmit: async (event) => {
      event.preventDefault();
      const language = getLanguage();
      const asked = question.value.trim();
      if (!asked) {
        question.focus();
        return;
      }

      askButton.disabled = true;
      clear(answerRegion);
      answerRegion.append(h('p', { class: 'field-hint', text: t('know.asking', language) }));

      try {
        renderAnswer(await askKnow(asked, language));
      } catch (error) {
        clear(answerRegion);
        answerRegion.append(
          h('div', { class: 'notice error' }, [
            h('p', { text: t('know.error', language), style: 'margin:0' }),
            h('p', {
              class: 'lbl',
              text: error instanceof ApiError ? error.detail || String(error.status) : String(error),
              style: 'margin:8px 0 0',
            }),
          ]),
        );
      } finally {
        askButton.disabled = false;
      }
    },
  }, [
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('know.ask', 'de') }),
      question,
    ]),
    h('div', { class: 'actions' }, [askButton]),
  ]);

  // ---------------------------------------------------------------- action items (R-174, R-175)

  async function loadActions() {
    const memberId = getMemberId();
    const language = getLanguage();
    if (!memberId) return;

    clear(actionsRegion);
    actionsRegion.append(
      h('span', { class: 'lbl', text: t('know.actions', language) }),
      h('p', { class: 'field-hint', text: t('know.actions_hint', language) }),
    );

    let payload;
    try {
      payload = await getActions();
    } catch (error) {
      actionsRegion.append(
        h('div', { class: 'notice error' }, [
          h('p', {
            text: error instanceof ApiError ? error.detail || String(error.status) : String(error),
            style: 'margin:0',
          }),
        ]),
      );
      return;
    }

    loadedFor = memberId;
    await renderActionList(actionsRegion, payload, { language });
  }

  // ---------------------------------------------------------------- the panel itself

  const closeButton = button(t('know.close', 'de'), {
    class: 'add',
    onClick: () => setOpen(false),
  });

  const heading = h('span', { class: 'lbl', text: t('know.panel', 'de') });
  const lede = h('p', { class: 'field-hint', text: t('know.lede', 'de') });

  const panel = h('aside', {
    id: 'know',
    'aria-label': t('know.panel', 'de'),
    onKeyDown: (event) => {
      // Escape closes the drawer. Docked, there is nothing to close — the panel is part of the screen.
      if (event.key === 'Escape' && !media.matches) setOpen(false);
    },
  }, [
    h('div', { class: 'actions', style: 'justify-content:space-between' }, [heading, closeButton]),
    // R-170: the Curator button is in the header, above the fold of a scrolling panel, so it is present
    // whatever else the panel is showing. It is never behind an answer and never behind a question.
    h('div', { class: 'actions' }, [curatorButton]),
    curatorRegion,
    lede,
    askForm,
    answerRegion,
    actionsRegion,
  ]);

  //: Narrow only. A scrim rather than a shadow, because a shadow does not catch a tap outside the drawer.
  const scrim = h('div', {
    hidden: '',
    onClick: () => setOpen(false),
    style: 'position:fixed; inset:0; z-index:4; background:rgba(26, 23, 64, 0.28);',
  });

  const launcher = button(t('know.open', 'de'), {
    class: 'primary',
    'aria-controls': 'know',
    'aria-expanded': 'false',
    style: 'position:fixed; right:var(--sp-md); bottom:var(--sp-md); z-index:3;',
    onClick: () => setOpen(true),
  });

  function applyLayout() {
    const docked = media.matches;
    const shown = visible && (docked || open);

    const base = 'position:fixed; top:0; right:0; bottom:0; z-index:5; overflow-y:auto;'
      + ' display:flex; flex-direction:column; gap:var(--sp-md);'
      + ' background:var(--surface); border-left:1px solid var(--line);'
      + ' padding:var(--sp-lg) var(--sp-md);';
    panel.setAttribute(
      'style',
      docked ? `${base} width:${DOCK_WIDTH}px;` : `${base} width:min(420px, 100%);`,
    );

    if (shown) panel.removeAttribute('hidden');
    else panel.setAttribute('hidden', '');

    // Docked, the panel is furniture: the close button and the launcher would both be lying about what
    // they do, so neither is rendered.
    if (docked) {
      closeButton.setAttribute('hidden', '');
      launcher.setAttribute('hidden', '');
      scrim.setAttribute('hidden', '');
    } else {
      closeButton.removeAttribute('hidden');
      if (visible) launcher.removeAttribute('hidden');
      else launcher.setAttribute('hidden', '');
      if (visible && open) scrim.removeAttribute('hidden');
      else scrim.setAttribute('hidden', '');
    }
    launcher.setAttribute('aria-expanded', String(!docked && open));

    // The docked panel takes its width out of the page rather than sitting on top of it. `main` is a
    // max-width centred block, so it simply narrows; the chrome bar narrows with it.
    document.body.style.paddingRight = docked && shown ? `${DOCK_WIDTH}px` : '';
  }

  function setOpen(next) {
    open = next;
    applyLayout();
    if (next) {
      // R-175 in one line: the items are fetched because the member opened the panel. Nothing fetched them
      // before that, and nothing will fetch them again on its own.
      if (loadedFor !== getMemberId()) loadActions();
      question.focus();
    } else {
      launcher.focus();
    }
  }

  function retranslate() {
    const language = getLanguage();
    heading.textContent = t('know.panel', language);
    lede.textContent = t('know.lede', language);
    panel.setAttribute('aria-label', t('know.panel', language));
    closeButton.textContent = t('know.close', language);
    launcher.textContent = t('know.open', language);
    curatorButton.textContent = t('know.curator', language);
    askButton.textContent = t('know.ask_submit', language);
    askForm.querySelector('.field-label').textContent = t('know.ask', language);
  }

  host.append(scrim, panel, launcher);
  media.addEventListener('change', () => {
    applyLayout();
    // Turning a phone sideways, or dragging a window wider, docks the panel — which is an opening.
    if (visible && media.matches && loadedFor !== getMemberId()) loadActions();
  });
  applyLayout();

  return {
    /**
     * Called by the router after every route change.
     *
     * The panel is shown once there is a member — the welcome screen and a stale profile id have nobody to
     * answer for, and a panel offering to ask about "your documents" before a profile exists is offering
     * something that cannot be true. Everything from registration onwards is an authenticated screen and
     * gets it (R-002).
     */
    /**
     * Open the curator chooser from outside the panel. Update script item 2.
     *
     * **Why this exists.** R-170 put the Curator button in the panel's own header, "above the fold of a
     * scrolling panel, so it is present whatever else the panel is showing" — and that is true while the
     * panel is DOCKED. Below `DOCK_QUERY` the panel is a drawer behind a launcher, so the button was two
     * taps away and was a feature of the chat. Item 2 makes it a product-wide constraint: "reachable in
     * one tap from every screen ... never inside a menu, and its treatment is identical everywhere".
     *
     * So the chrome grows a button and calls this. **One chooser, two entry points** — the alternative was
     * a second copy of the directory fetch, the ordering and the session write, which is the
     * two-implementations defect this build keeps recording. R-173's `opened_from` still reads the live
     * route through `getRoute`, so a session opened from the chrome records the screen the member was
     * looking at rather than the word "chrome".
     *
     * On a narrow viewport the drawer is opened first, because a chooser rendered into a hidden panel is
     * a chooser nobody can see. Docked, the panel is already furniture and only the chooser is drawn.
     */
    openCurator() {
      if (!visible) return;
      if (!media.matches && !open) setOpen(true);
      requestCurator();
    },

    /** Whether there is a member for the Curator button to act for. The chrome mirrors it. */
    available() {
      return visible;
    },

    sync() {
      const memberId = getMemberId();
      visible = Boolean(memberId);
      retranslate();

      if (!visible) {
        loadedFor = null;
        clear(actionsRegion);
        clear(answerRegion);
        clear(curatorRegion);
      }
      applyLayout();

      // Docked, "opened" is the moment the panel first appears for this member. Narrow, it is the tap on
      // the launcher, handled in setOpen. Either way it is an opening, never a schedule.
      //
      // Nothing is announced to assistive technology here, and that is R-175 rather than an oversight: an
      // arriving item may not speak over the screen the member is on. `#live` belongs to the surface they
      // asked for.
      if (visible && media.matches && loadedFor !== memberId) loadActions();
    },
  };
}
