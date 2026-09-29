"""Show that each regression test guards something: revert its fix, watch it fail, restore, watch it pass.

``CASES``: fixes that live in the database (schema.sql); a revert is SQL run in the test's throwaway schema
right after schema.sql (conftest's EIGENTLICH_TEST_REVERT hook). The real schema is never touched.

``CODE_CASES`` (29.09.2026): fixes that live in the package's Python; a revert replaces the fix's text in its
source file for the one test run, and the file's bytes are put back afterwards whatever happens.

    ..\\.venv\\Scripts\\python dev\\verify_regressions.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
SCHEMA = (ROOT / "src" / "eigentlich" / "schema.sql").read_text(encoding="utf-8")


def _function(name: str) -> str:
    m = re.search(rf"CREATE OR REPLACE FUNCTION {name}\(.*?\n\$\$;", SCHEMA, re.S)
    assert m, name
    return m.group(0)


NO_LOCK = _function("content_record_version").replace(
    "    PERFORM pg_advisory_xact_lock(hashtextextended(TG_TABLE_SCHEMA || '.content_record:' || NEW.key, 0));\n", "")
assert "pg_advisory_xact_lock" not in NO_LOCK

NO_OWNER_CHECK = """CREATE OR REPLACE FUNCTION erasure_allowed(p_schema text, p_client text) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('eigentlich.erasure_client', true), '') <> ''
       AND (p_client IS NULL OR current_setting('eigentlich.erasure_client', true) = p_client) $$;"""

NO_CLIENT_SCOPE = """CREATE OR REPLACE FUNCTION erasure_allowed(p_schema text, p_client text) RETURNS boolean
    LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('eigentlich.erasure_client', true), '') <> '' $$;"""

NO_ACTOR_CHECK = "CREATE OR REPLACE FUNCTION check_actor() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$;"

NO_CLASS_RAISE = _function("answer_check").replace(
    "        NEW.data_class := greatest(NEW.data_class, substr(declared, 2)::smallint);\n", "        NULL;\n")

NULL_HOLE = ("ALTER TABLE content_record DROP CONSTRAINT content_body_shape, ADD CONSTRAINT content_body_shape "
             "CHECK (CASE kind WHEN 'questionnaire' THEN jsonb_typeof(body -> 'questions') = 'array' "
             "WHEN 'scoring_map' THEN jsonb_typeof(body -> 'binds') = 'array' AND body ? 'map' "
             "WHEN 'knowledge' THEN jsonb_typeof(body -> 'markdown') = 'string' "
             "AND jsonb_typeof(body -> 'front_matter') = 'object' ELSE jsonb_typeof(body) IN ('object', 'array') END);")

PLAN_GUARD_MOVABLE = _function("plan_guard").replace(
    "NEW.id <> OLD.id OR NEW.created_at <> OLD.created_at\n"
    "        OR (client_col IS NOT NULL AND (to_jsonb(NEW) ->> client_col) IS DISTINCT FROM (to_jsonb(OLD) ->> client_col))",
    "NEW.id <> OLD.id")
assert "NEW.created_at" not in PLAN_GUARD_MOVABLE

GRANT_DELETE = ("DO $$ BEGIN EXECUTE format('GRANT DELETE ON ALL TABLES IN SCHEMA %I TO curator', current_schema()); "
                "END $$;")

AO = "tests/test_append_only.py"
PG = "tests/test_plan_guard.py"
CASES: list[tuple[str, str, str]] = [
    ("decision append-only", f"{AO}::test_update_is_refused[decision]", "DROP TRIGGER decision_append_only ON decision"),
    ("decision never deleted", f"{AO}::test_delete_is_refused[decision]", "DROP TRIGGER decision_append_only ON decision"),
    ("content_record append-only", f"{AO}::test_update_is_refused[content_record]",
     "DROP TRIGGER content_record_append_only ON content_record"),
    ("thread_message append-only", f"{AO}::test_update_is_refused[thread_message]",
     "DROP TRIGGER thread_message_append_only ON thread_message"),
    ("approval_event append-only", f"{AO}::test_update_is_refused[approval_event]",
     "DROP TRIGGER approval_event_append_only ON approval_event"),
    ("curator_session_event append-only", f"{AO}::test_update_is_refused[curator_session_event]",
     "DROP TRIGGER curator_session_event_append_only ON curator_session_event"),
    ("parameter_set append-only", f"{AO}::test_update_is_refused[parameter_set]",
     "DROP TRIGGER parameter_set_append_only ON parameter_set"),
    ("report append-only", f"{AO}::test_update_is_refused[report]", "DROP TRIGGER report_append_only ON report"),
    # Two layers refuse a stale decision: plan_guard, and decision_link_guard on the automatic link row.
    ("C-09 stale decision, both layers", f"{PG}::test_a_plan_insert_with_a_decision_from_another_transaction_is_refused",
     "DROP TRIGGER position_c09 ON position; DROP TRIGGER decision_position_guard ON decision_position"),
    ("C-09 plan rows never deleted", f"{PG}::test_plan_rows_are_never_deleted[position]",
     "DROP TRIGGER position_c09 ON position"),
    ("C-09 forged txid", f"{PG}::test_a_caller_cannot_forge_the_transaction_id", "DROP TRIGGER decision_stamp ON decision"),
    ("C-09 goal funding", f"{PG}::test_goal_funding_needs_a_decision_linked_to_the_goal",
     "DROP TRIGGER goal_funding_c09 ON goal_funding"),
    ("C-09 late link", f"{PG}::test_a_decision_cannot_be_linked_after_its_transaction",
     "DROP TRIGGER decision_position_guard ON decision_position"),
    ("C-09 same client", f"{PG}::test_the_decision_must_belong_to_the_same_client",
     "DROP TRIGGER position_c09 ON position"),
    ("plan row stays with its client", f"{PG}::test_a_plan_row_cannot_move_to_another_client",
     PLAN_GUARD_MOVABLE),
    ("one current answer", "tests/test_answers.py::test_two_current_answers_to_one_question_are_refused",
     "DROP INDEX answer_one_current"),
    ("answer names a real question", "tests/test_answers.py::test_an_answer_names_a_question_of_that_version",
     "DROP TRIGGER answer_check ON answer"),
    ("question class raises row class", "tests/test_answers.py::test_the_question_class_raises_the_row_class",
     NO_CLASS_RAISE),
    ("content versions under concurrency", "tests/test_content.py::test_concurrent_saves_queue_and_number_without_gaps",
     NO_LOCK),
    ("content body NULL hole", "tests/test_content.py::test_body_shape_and_key_are_checked[questionnaire/x-questionnaire-body0]",
     NULL_HOLE),
    ("pinned search_path", "tests/test_answers.py::test_the_curator_answers_on_the_clients_behalf",
     "ALTER FUNCTION answer_check() RESET search_path"),
    ("revoked curator cannot act", "tests/test_workflow.py::test_a_revoked_curator_cannot_act_and_stays", NO_ACTOR_CHECK),
    ("fulfilled request not withdrawn", "tests/test_workflow.py::test_report_request_states",
     "DROP TRIGGER report_request_check ON report_request"),
    ("approval events terminal", "tests/test_workflow.py::test_every_event_is_terminal",
     "ALTER TABLE approval_event DROP CONSTRAINT approval_event_one_per_request"),
    ("revision is a new report", "tests/test_workflow.py::test_a_revision_is_a_new_report_for_the_same_request",
     "DROP TRIGGER approval_event_check ON approval_event"),
    ("engine run forward only", "tests/test_workflow.py::test_engine_runs_move_forward_only",
     "DROP TRIGGER engine_run_guard ON engine_run"),
    ("curator cannot erase", "tests/test_boundary.py::test_the_curator_cannot_stand_the_guards_down", NO_OWNER_CHECK),
    ("erasure bounded to one client", "tests/test_erasure.py::test_the_erasure_setting_covers_only_the_named_client",
     NO_CLIENT_SCOPE),
    ("curator has no DELETE", "tests/test_boundary.py::test_the_curator_cannot_delete[client-id-client]", GRANT_DELETE),
]


S = "src/eigentlich/"
T = "tests/"
#: (name, test node, file, the fix as it stands, the fix reverted)
CODE_CASES: list[tuple[str, str, str, str, str]] = [
    ("code page: a plausible letter only", f"{T}test_encoding.py::test_the_pattern_is_found_and_reversed", f"{S}encoding.py",
     "if len(decoded) == 1 and _plausible(decoded):", "if len(decoded) == 1 and ord(decoded) >= 0x80:"),
    ("encoding decision without garble", f"{T}test_encoding.py::test_the_fix_follows_each_tables_rule", f"{S}encoding.py",
     'choice = "Korrigiert: " + "; ".join(f"{t} {repair(_label(r))!r}" for t, r in rows)',
     'choice = "; ".join(f"{t}: {_label(r)!r} -> {repair(_label(r))!r}" for t, r in rows)'),
    ("aligned content: 0 mismatches",
     f"{T}test_alignment.py::test_the_seeded_content_had_19_mismatches_and_the_aligned_has_none", f"{S}alignment.py",
     '    _set_options(new, "rest_hours", REST_HOURS_OPTIONS)\n', ""),
    ("an edit keeps offered: false", f"{T}test_alignment.py::test_an_edit_keeps_an_option_not_offered",
     f"{S}questionnaires.py", 'offered = o.get("offered", was_offered.get(value, True))', 'offered = o.get("offered", True)'),
    ("contribution reaches the mandate", f"{T}test_app_inputs.py::test_the_yearly_contribution_reaches_the_mandate",
     f"{S}inputs.py", "annual_contribution=contribution, name=None", "annual_contribution=None, name=None"),
    ("gaps name no ids", f"{T}test_app_language.py::test_a_gap_is_named_by_what_the_client_called_it", f"{S}gaps.py",
     "    if rest and first in ids:", "    if False:"),
    ("lbs auto: a burst is one run", f"{T}test_app_auto.py::test_a_burst_of_changes_makes_one_run", f"{S}service.py",
     '                    state["timer"].cancel()\n', ""),
    ("lbs auto: one run at a time",
     f"{T}test_app_auto.py::test_one_run_at_a_time_and_a_change_during_a_run_runs_once_more", f"{S}service.py",
     '            if state["running"]:\n                state["again"] = True                  '
     '# one more run once the current one is done\n                return\n', ""),
    ("lbs auto: a change the app did not see",
     f"{T}test_app_auto.py::test_a_change_the_app_did_not_see_runs_when_the_home_opens", f"{S}service.py",
     "        if schedule_if_stale and changed", "        if False and changed"),
    ("cockpit run: curator in service (403)", f"{T}test_app_auto.py::test_the_cockpits_run_names_its_curator",
     f"{S}service.py", "            self.curator_in_service(curator_id)\n", ""),
]

HH = f"{T}test_app_household.py"
#: The fix round after the use cases (29.09.2026, EIG-53 to EIG-59).
CODE_CASES += [
    ("partner: the person reaches lbs", f"{HH}::test_the_partner_reaches_lbs_with_age_income_and_human_capital",
     f"{S}inputs.py", 'persons.append(_partner(pid, answer, num) if answer("partner_in_plan") != "nein"\n'
     '                               else c.LbsPerson(person_id=pid, kind="adult"))',
     'persons.append(c.LbsPerson(person_id=pid, kind="adult"))'),
    ("partner: a position's owner", f"{HH}::test_the_partner_reaches_lbs_with_age_income_and_human_capital",
     f"{S}inputs.py", "                owner = partner_id\n", '                owner = "p1"\n'),
    ("re-answer restates the fact",
     f"{HH}::test_answering_again_restates_the_fact_so_lbs_reads_the_new_answer", f"{S}service.py",
     "            restated = self._restate_from_answer(conn, client_id, q, stored)\n", "            restated = None\n"),
    ("grounding: numbers do not score",
     f"{T}test_app_api.py::test_numbers_and_inflected_stop_words_do_not_choose_the_notes", f"{S}grounding.py",
     "w not in _STOP and not w.isdigit()}", "w not in _STOP}"),
    ("grounding: inflected stop words",
     f"{T}test_app_api.py::test_numbers_and_inflected_stop_words_do_not_choose_the_notes", f"{S}grounding.py",
     '""".split()) | set("""', '""".split()) or set("""'),
    ("grounding: a prefix is an ending",
     f"{T}test_app_api.py::test_numbers_and_inflected_stop_words_do_not_choose_the_notes", f"{S}grounding.py",
     "(word.startswith(b) and len(word) - len(b) <= 3)", "word.startswith(b)"),
    ("role names are the house's", f"{HH}::test_no_english_role_text_reaches_a_german_page", f"{S}service.py",
     '        sheet = {**sheet, "grid": grid}\n', ""),
    ("shares sum to at most 100 %", f"{HH}::test_each_goals_share_of_the_saving_is_stored_checked_and_sent",
     f"{S}service.py", '            if old["active"] and "contribution_share" in row:\n'
     '                self._check_shares(conn, client_id, goal_id, row["contribution_share"])\n', ""),
    ("a revision is not the cached copy", f"{T}test_app_api.py::test_a_revision_is_sent_as_one_and_is_not_the_cached_copy",
     f"{S}service.py", "                                  revision_of=revision_of, revision_note=revision_note)", "                                  )"),
    ("hours_learning left the intake", f"{HH}::test_the_intake_gains_the_partner_section_and_drops_hours_learning",
     f"{S}alignment.py", '    new["questions"] = [q for q in new["questions"] if q.get("key") != "hours_learning"]\n', ""),
]

CASES += [
    ("basis only on AI answers", "tests/test_app_inputs.py::test_only_an_ai_answer_carries_a_basis",
     "ALTER TABLE thread_message DROP CONSTRAINT thread_message_basis"),
]


def run_code(node: str, path: str, fix: str, reverted: str) -> int:
    target = ROOT / path
    original = target.read_bytes()
    text = original.decode("utf-8").replace("\r\n", "\n")
    assert text.count(fix) == 1, f"{path}: the fix is not in the source as recorded: {fix[:60]!r}"
    try:
        target.write_bytes(text.replace(fix, reverted).encode("utf-8"))
        return run(node, None)
    finally:
        target.write_bytes(original)


def run(node: str, revert: str | None) -> int:
    env = dict(os.environ)
    env.pop("EIGENTLICH_TEST_REVERT", None)
    if revert:
        env["EIGENTLICH_TEST_REVERT"] = revert
    return subprocess.run([PY, "-m", "pytest", node, "-q", "-p", "no:cacheprovider", "-x"], cwd=ROOT, env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def main(argv: list[str] | None = None) -> int:
    """``verify_regressions.py [text]``: only the guards whose name contains ``text``."""
    only = (argv if argv is not None else sys.argv[1:])[:1]
    cases = [c for c in CASES if not only or only[0] in c[0]]
    code_cases = [c for c in CODE_CASES if not only or only[0] in c[0]]
    bad = 0
    print(f"{'guard':<36} {'reverted':<10} {'restored':<10}")
    for name, node, revert in cases:
        reverted = run(node, revert)
        restored = run(node, None)
        ok = reverted != 0 and restored == 0
        bad += not ok
        print(f"{name:<36} {'FAILS' if reverted else 'passes!':<10} {'passes' if restored == 0 else 'FAILS!':<10}"
              f"{'' if ok else '  <-- not guarding'}")
    for name, node, path, fix, reverted_text in code_cases:
        reverted = run_code(node, path, fix, reverted_text)
        restored = run(node, None)
        ok = reverted != 0 and restored == 0
        bad += not ok
        print(f"{name:<36} {'FAILS' if reverted else 'passes!':<10} {'passes' if restored == 0 else 'FAILS!':<10}"
              f"{'' if ok else '  <-- not guarding'}")
    total = len(cases) + len(code_cases)
    print(f"\n{total - bad} of {total} regression tests fail when their fix is reverted and pass when restored")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
