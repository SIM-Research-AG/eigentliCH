// R-301 — asking for an engine run, and waiting for it honestly.
//
// **`POST /api/runs` and `GET /api/runs/{id}` were a queue-and-poll surface with no client at all.** The
// routes existed, the worker existed, the refusals were written, and nothing rendered any of it. This is
// that client.
//
// ===========================================================================================================
// WHAT THIS SCREEN IS FOR, GIVEN THAT MOST OF WHAT IT OFFERS IS REFUSED
// ===========================================================================================================
//
// `services/runs.py` says it plainly: of the seven engines, one is genuinely runnable from a member's plan.
// The others each want something the plan does not hold — a wealth stock in francs, a mandate, an event
// stream, a numbered baseline — and A69 recorded every one of those as absent rather than defaulted. So the
// common answer to this screen is a **refusal, and the refusal is the product**: it names which of the
// member's own inputs is missing, in the words `services/engine_inputs.py` uses, which is a different and
// far more useful thing than "engine unavailable".
//
// That is why the gap list is rendered as prominently as a result would be, and why the models that cannot
// run are still offered rather than hidden. A screen that showed only the one engine that works would be
// telling the member that their plan answers everything eigentliCH can ask of it.
//
// **`portfolio_optimiser` and `score_engine` are not offered.** Not hidden failures — decisions, and the
// same two the Befund withholds:
//
//   * `portfolio_optimiser` ranks instruments. C-01, and the server refuses it before it consults the plan
//     so that the refusal cannot quietly stop happening the day its `mandate` gap is filled.
//   * `score_engine` produces a Score. A6 kept the name because the estate's measure is analytical and
//     scoped C-07's grep to the member layer accordingly — which is not a licence to render it. Listing
//     the inputs a Score lacks invites exactly one question, "so what would my score be", and that
//     question is the primitive C-07 forbids.
//
// ===========================================================================================================
// POLLING, AND WHY IT SAYS SO OUT LOUD
// ===========================================================================================================
//
// `market_signal` declares a **1800-second** budget in its manifest. A screen that submits and then sits
// silent for half an hour is indistinguishable from a screen that has hung, and a member who reloads it or
// presses the button again has been taught that the product does not work. So:
//
//   * the declared budget is stated before anything is submitted (`runs.lede_wait`) and again on the run;
//   * every poll writes when it last asked, so the screen is visibly alive rather than merely unchanged;
//   * a poll that fails says the check did not get through and keeps trying, because one dropped request
//     is not a failed run and turning it into one would report a result that does not exist;
//   * the interval widens from two seconds toward fifteen. Two seconds forever is 900 requests for one
//     run of the long engine; fifteen seconds from the start makes the short ones feel broken.
//
// **The budget and the elapsed time are deliberately not shown as a pair.** Together they are one division
// away from a completion meter, and C-07 leaves no room for one. The budget is a sentence about the model;
// the clock is a duration with no denominator.
//
// **The poll stops when the screen is gone.** This surface mounts a root node of its own and every tick
// asks whether that node is still in the document — `main.js` clears `#main` on each route change, so a
// detached root is exactly the signal that the member has navigated away or switched language. Without it
// the timer would keep polling forever against a screen nobody is looking at, and after two language
// switches there would be three of them.
//
// **R-113 / C-07: nothing is counted.** Not the runs, not how many were refused, not how many finished. The
// listing endpoint carries no aggregate for the same reason.
//
// **R-302: a failed run renders no number.** The payload for a failed run carries no numeric field at any
// depth — not the timeout, not a duration, not a zero — and every field this file reads is read behind a
// presence check, so absence renders as absence rather than as a zero.

import { announce, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { ApiError, getGoals, getRun, getRuns, startRun } from '../app/api.js';

//: The engines a member may ask for, in the order they are offered. `market_signal` first because it is the
//: one that runs: it republishes the Regime the AssumptionSet is read from, which is what every goal
//: illustration is stamped with (C-02).
//:
//: **A list here rather than a route**, because `known_engines()` is the manifest directory and a route that
//: served it would be the API package reaching toward the engine façade, which `test_constraints.py`
//: forbids in its strong form. The cost is that this list can drift from the manifests, so a test holds it
//: against `known_engines()` minus the two withheld above — see the module docstring for why those two.
const OFFERED_ENGINES = [
  'market_signal',
  'return_estimation',
  's_curve_trajectory',
  'life_balance_sheet',
  'scenario_generator',
];

//: Poll intervals in whole milliseconds. Widening additively rather than by a factor: doubling from two
//: seconds reaches two minutes in six steps, which for a 30-second engine is most of its runtime spent
//: waiting on the client rather than on the engine.
const FIRST_POLL_MS = 2000;
const POLL_STEP_MS = 2000;
const MAX_POLL_MS = 15000;

const SECONDS_PER_MINUTE = 60;
const MS_PER_SECOND = 1000;

/** Statuses that are still going somewhere. `done` and `failed` are the two that are not. */
const IN_FLIGHT = ['submitted', 'running'];

function engineLabel(name, language) {
  const label = t(`runs.engine_${name}`, language);
  // The raw manifest name rather than a key on screen, for an engine added to the directory before anybody
  // writes it a name. It is at least the name the refusal will also use.
  return label === `runs.engine_${name}` ? name : label;
}

function statusLabel(status, language) {
  const label = t(`runs.status_${status}`, language);
  return label === `runs.status_${status}` ? status : label;
}

/** `2026-08-31T14:12:57+00:00` as a local wall-clock time, or nothing at all. */
function clockTime(iso, language) {
  if (!iso) return '';
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return when.toLocaleString(language === 'de' ? 'de-CH' : 'en-CH');
}

/** `mm:ss` since a timestamp. A duration, with no denominator — see the module docstring. */
function elapsedClock(iso) {
  if (!iso) return null;
  const from = new Date(iso).getTime();
  if (Number.isNaN(from)) return null;
  const seconds = Math.max(0, Math.floor((Date.now() - from) / MS_PER_SECOND));
  const minutes = Math.floor(seconds / SECONDS_PER_MINUTE);
  const rest = seconds % SECONDS_PER_MINUTE;
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`;
}

/**
 * The model's declared budget, as a sentence.
 *
 * Read off the run rather than from a table in this file: it is the manifest's `timeout_s` and the manifests
 * are the authority. A failed run carries no `timeout_s` at all (R-302) and this returns nothing for it.
 */
function budgetNode(run, language) {
  if (typeof run.timeout_s !== 'number') return null;
  const text = run.timeout_s >= SECONDS_PER_MINUTE
    ? t('runs.budget_minutes', language, { minutes: Math.round(run.timeout_s / SECONDS_PER_MINUTE) })
    : t('runs.budget_seconds', language, { seconds: run.timeout_s });
  return h('p', { class: 'report-meta', text });
}

/**
 * One value of an engine result, at any depth.
 *
 * The keys are the engine's own field names and are rendered as they are. Translating them would be this
 * client deciding what an estate contract's fields mean, which §9's "wrap the engine, do not reinterpret
 * it" rules out — and inventing a German label for `contract_type` is exactly that in miniature.
 *
 * Depth-limited, because the result is an arbitrary JSON document from another process and a cycle or a
 * thousand-deep nesting would take the screen with it. What the limit reaches is rendered as text, so
 * nothing is silently dropped.
 */
function resultValue(value, depth = 0) {
  if (value === null || value === undefined) return null;
  if (depth >= 4 || typeof value !== 'object') {
    return h('span', { class: 'report-value', text: String(value) });
  }
  const entries = Array.isArray(value)
    ? value.map((entry, index) => [String(index), entry])
    : Object.entries(value);
  if (!entries.length) return null;
  return h('ul', { class: 'report-tree' }, entries.map(([key, inner]) => {
    const body = resultValue(inner, depth + 1);
    if (!body) return null;
    return h('li', {}, [h('span', { class: 'report-option', text: `${key}: ` }), body]);
  }));
}

/**
 * One gap, in the member's own vocabulary.
 *
 * **`AbsentInput.reason` is deliberately not rendered.** It is the considered sentence in
 * `services/engine_inputs.py` and it exists in English only — a note to whoever reads the mapping layer,
 * not member copy. Putting an English paragraph on a German screen is the half-translated product A12
 * exists to prevent, and the first version of this file did exactly that: a DOM run showed a German member
 * four paragraphs of English about `Position.magnitude`. So the input is named by the same subject the
 * Befund gives it (`services/befund.py::GAP_SUBJECTS`, mirrored in the `gap.input_*` strings) and the kind
 * is stated beside it.
 *
 * The engine's own declared name is shown as a fallback, so an input nobody has written a subject for
 * appears rather than disappearing — which is the failure that looks like success, and the reason the
 * Befund's own lookup raises instead of skipping.
 */
function gapNode(gap, language) {
  const subject = t(`gap.input_${gap.input}`, language);
  const kind = t(`gap.kind_${gap.kind}`, language);
  return h('li', {}, [
    h('span', {
      class: 'report-option',
      text: subject === `gap.input_${gap.input}` ? gap.input : subject,
    }),
    kind === `gap.kind_${gap.kind}` ? null : h('span', { text: ` — ${kind}` }),
  ]);
}

/**
 * A refusal from `POST /api/runs`, rendered from the object it actually is.
 *
 * `NotQueueable.as_dict()` travels in the 422's `detail` as `{queued, engine, reason, absent: [...]}`. A
 * client that printed `error.detail` would show `[object Object]`; the gap list is the half of the answer
 * worth having, so it is walked. An unrecognised reason falls back to its own identifier rather than to a
 * generic sentence, because the identifier is at least true.
 */
function refusalNode(detail, language) {
  const reason = t(`runs.refused_${detail.reason}`, language);
  const gaps = Array.isArray(detail.absent) ? detail.absent : [];
  return h('div', { class: 'notice error' }, [
    h('p', { class: 'report-sentence', text: t('runs.refused_heading', language) }),
    h('p', { class: 'report-meta', text: engineLabel(detail.engine, language) }),
    h('p', { text: reason === `runs.refused_${detail.reason}` ? detail.reason : reason }),
    gaps.length
      ? h('div', {}, [
          h('span', { class: 'lbl', text: t('runs.gaps_heading', language) }),
          h('ul', { class: 'report-tree' }, gaps.map((gap) => gapNode(gap, language))),
        ])
      : null,
  ]);
}

/** One run, as a card. Rebuilt on every poll rather than patched — three nodes and no state to keep alive. */
function runNode(run, language, live) {
  const failed = run.status === 'failed';
  const inFlight = IN_FLIGHT.includes(run.status);

  return h('section', { class: 'report-block' }, [
    h('h2', { class: 'report-heading' }, [
      engineLabel(run.engine, language),
      h('span', { class: 'report-status', text: statusLabel(run.status, language) }),
    ]),

    h('p', {
      class: 'report-meta',
      text: `${t('runs.submitted_at', language)}: ${clockTime(run.submitted_at, language)}`,
    }),
    run.started_at
      ? h('p', {
          class: 'report-meta',
          text: `${t('runs.started_at', language)}: ${clockTime(run.started_at, language)}`,
        })
      : null,
    run.finished_at
      ? h('p', {
          class: 'report-meta',
          text: `${t('runs.finished_at', language)}: ${clockTime(run.finished_at, language)}`,
        })
      : null,

    // A statement about the model, on its own. Never beside the clock — see the module docstring.
    budgetNode(run, language),

    // Still going. The live region is the caller's node so that a poll can rewrite this one line without
    // rebuilding the card underneath the member's cursor.
    inFlight
      ? h('div', { class: 'report-waiting' }, [
          h('p', { class: 'report-sentence', text: t('runs.still_working', language) }),
          live || null,
        ])
      : null,

    // R-302. `available: false` and a reason, and there is no number in the payload to render even by
    // accident: every numeric field above is behind a presence check.
    failed
      ? h('div', {}, [
          h('p', { text: t('runs.unavailable_lede', language) }),
          run.reason
            ? h('p', { class: 'report-meta', text: `${t('runs.reason', language)}: ${run.reason}` })
            : null,
        ])
      : null,

    run.status === 'done'
      ? h('div', {}, [
          typeof run.duration_ms === 'number'
            ? h('p', {
                class: 'report-meta',
                text: t('runs.took', language, {
                  seconds: Math.round(run.duration_ms / MS_PER_SECOND),
                }),
              })
            : null,
          h('span', { class: 'lbl', text: t('runs.result_heading', language) }),
          // Nothing invented for an empty result: the allowlist in `services/runs.py` can legitimately
          // leave nothing behind, and a placeholder sentence here would claim the run said something.
          resultValue(run.result),
        ])
      : null,
  ]);
}

/**
 * Fetch what this surface needs: the member's runs and their goals.
 *
 * The goals are for the optional `goal_id` — a run may be asked *about* one of the member's own goals, and
 * `s_curve_trajectory`'s horizon is read from it. A11: no member id on either call.
 */
export async function load() {
  const [runs, goals] = await Promise.all([getRuns(), getGoals()]);
  return { runs: runs.runs || [], goals: goals.goals || [] };
}

export function render(container, { runs, goals }, { language, onExpired }) {
  clear(container);

  // This surface's own root. Every poll checks whether it is still in the document: `main.js` clears
  // `#main` on each route change and on every language change, so a detached root means the member has
  // left and the timer must not fire again. Checking `container` would not work — `container` IS `#main`,
  // which stays connected while its children are replaced.
  const root = h('div', { class: 'runs' });

  root.append(
    h('span', { class: 'lbl', text: t('runs.eyebrow', language) }),
    h('h1', { text: t('runs.title', language) }),
    h('p', { class: 'lede', text: t('runs.lede', language) }),
    h('p', { class: 'field-hint', text: t('runs.lede_wait', language) }),
  );

  const refusal = h('div');
  const list = h('div', { class: 'report' });
  const notice = h('div', { class: 'notice error', hidden: '' });

  /**
   * Poll one run until it stops moving.
   *
   * The card is rebuilt in place on every answer, so a run that starts, then finishes, then reports its
   * result walks through all three renderings without the member doing anything. Only a *change of status*
   * is announced: a live region rewritten every two seconds is a screen reader talking over itself.
   */
  function watch(runId, card, initialStatus) {
    let interval = FIRST_POLL_MS;
    let status = initialStatus;
    let timer = null;

    const live = h('p', { class: 'report-meta' });
    let current = card;

    function replace(run) {
      const next = runNode(run, language, live);
      current.replaceWith(next);
      current = next;
      return current;
    }

    function schedule() {
      interval = Math.min(MAX_POLL_MS, interval + POLL_STEP_MS);
      timer = window.setTimeout(tick, interval);
    }

    async function tick() {
      // The one condition that ends the loop other than the run itself: this screen is no longer on screen.
      if (!root.isConnected) {
        if (timer) window.clearTimeout(timer);
        return;
      }
      let run;
      try {
        run = await getRun(runId);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return onExpired();
        // One dropped request is not a failed run. Say the check did not get through and keep asking —
        // turning a network blip into `status: failed` would report a result that does not exist (R-302).
        live.textContent = t('runs.check_failed', language);
        return schedule();
      }
      if (!root.isConnected) return;

      replace(run);
      const clock = elapsedClock(run.started_at || run.submitted_at);
      live.textContent = [
        clock ? t('runs.elapsed', language, { clock }) : '',
        t('runs.last_checked', language, { time: new Date().toLocaleTimeString() }),
      ].filter(Boolean).join(' ');

      if (run.status !== status) {
        status = run.status;
        const key = `runs.announced_${status}`;
        const said = t(key, language);
        if (said !== key) announce(said);
      }
      if (IN_FLIGHT.includes(run.status)) schedule();
    }

    timer = window.setTimeout(tick, FIRST_POLL_MS);
  }

  // ---- the form -------------------------------------------------------------------------------

  const engine = h('select', { name: 'engine', required: '' }, [
    // Nothing preselected, for R-120's reason one surface along: a default is an inference, and the member
    // has not chosen the first entry in a list by failing to open it.
    h('option', { value: '', text: t('runs.engine_choose', language) }),
    ...OFFERED_ENGINES.map((name) =>
      h('option', { value: name, text: engineLabel(name, language) })),
  ]);
  engine.value = '';

  const goal = h('select', { name: 'goal_id' }, [
    h('option', { value: '', text: t('runs.goal_none', language) }),
    ...goals.map((one) => h('option', { value: one.id, text: one.name })),
  ]);
  goal.value = '';

  const form = h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      notice.setAttribute('hidden', '');
      clear(refusal);
      if (!engine.value) return;

      let queued;
      try {
        queued = await startRun(engine.value, goal.value || null);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return onExpired();
        if (error instanceof ApiError && error.status === 422 && error.detail
            && typeof error.detail === 'object') {
          // The refusal, as the object it is. This is the branch that would otherwise read
          // `[object Object]`, and it is the one the member most often gets.
          refusal.append(refusalNode(error.detail, language));
          return announce(t('runs.announced_refused', language));
        }
        notice.textContent = error instanceof ApiError
          ? String(error.detail || error.status)
          : String(error);
        notice.removeAttribute('hidden');
        return undefined;
      }

      const card = runNode(queued, language, null);
      list.prepend(card);
      announce(t('runs.announced_queued', language));
      watch(queued.run_id, card, queued.status);
      return undefined;
    },
  }, [
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('runs.engine', language) }),
      engine,
    ]),
    goals.length
      ? h('label', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('runs.goal', language) }),
          goal,
        ])
      : null,
    notice,
    h('div', { class: 'actions' }, [
      h('button', { type: 'submit', class: 'primary' }, [t('runs.submit', language)]),
    ]),
  ]);

  root.append(form, refusal);

  // ---- what has been asked for already -------------------------------------------------------
  //
  // Newest first, in the order the server returned. No count and no grouping — R-113.

  root.append(h('span', { class: 'lbl', text: t('runs.list_heading', language) }));
  if (runs.length) {
    for (const run of runs) {
      const card = runNode(run, language, null);
      list.append(card);
      // A run left in flight by an earlier visit is picked up where it was, which is the whole point of a
      // queue that survives the screen. `api/runs.py` wakes the worker from the listing route for the same
      // reason.
      if (IN_FLIGHT.includes(run.status)) watch(run.run_id, card, run.status);
    }
  } else {
    // R-110: state what would stand here, and nothing about what the member ought to do about it.
    list.append(h('p', { class: 'cell-prompt', text: t('runs.none_yet', language) }));
  }
  root.append(list);

  container.append(root);
  announce(t('runs.announced', language));
}

export { OFFERED_ENGINES };
