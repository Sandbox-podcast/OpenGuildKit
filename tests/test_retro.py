"""The retrospective reads the records of closed tasks and counts what comes back (issue #423).

Pure functions on dicts: what a closed task set aside, which committees brought nothing, what it left open and which
blockers were waived; then what comes back in several tasks, with the profile command a person could type for it.
"""

import copy
import itertools
import json
import random
import shlex
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.cli import command_parser
from openguildkit.consultation import consult
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.retro import (
    DEFAULT_MINIMUM, MAX_REASON, facts_of_record, facts_of_task, project_summary, proposals, recurrences,
    render_project, render_task, task_retro,
)
from openguildkit.tasks import NOT_RUN_GROUP, OTHER_RULES_GROUP, SENSITIVE_GROUP, VERDICTS_GROUP, record_review

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
# Names that must never reach what the retrospective prints: the fields that hold a person are not copied.
APPROVER, CLOSER, OWNER, WAIVER = "Zorglub-Approver", "Yvonne-Closer", "Quentin-Owner", "Wilhelmina-Waiver"
NAMES = (APPROVER, CLOSER, OWNER, WAIVER)

WAIVED = {"kind": "waived", "by": WAIVER, "at": "2026-11-20T10:00:00+00:00", "reason": "Pilot only.", "scope": "Pilot",
          "until": "2026-12-05"}
CLEARED = {"kind": "cleared", "by": WAIVER, "evidence": "tests/test_access.py", "supports": "Access is refused."}


def entry(board_id: str, verdict: str = "proceed", blockers: tuple = ()) -> dict:
    return {"id": board_id, "recommendation": f"{board_id} says go.", "evidence": [], "open_questions": [],
            "challenge": {"verdict": verdict, "blockers": list(blockers), "failure_mode": "It could fail."}}


def skipped(check: str, reason: str = "Handled by the platform team.", status: str = "skipped") -> dict:
    return {"check": check, "status": status, "reason": reason, "owner": OWNER}


def closed(task_id: str = "t1", *, boards: dict | None = None, blockers: dict | None = None, objections=None,
           checks=(), packs=(), groups=(), not_concerned=(), resolutions: dict | None = None,
           created: str = "2026-11-20T10:00:00+00:00", **extra) -> dict:
    """A task as `task complete` leaves it: a review, a decision, a result and its closing."""
    boards = boards or {"security": "revise"}  # a committee that asked for changes: it brought something
    task = {
        "schema_version": 1, "id": task_id, "created_at": created, "brief": "Show the status.", "rounds": [],
        "answers": {"kind": "feature"}, "status": "done-with-reservations" if groups else "done",
        "consultation": {"id": "c1", "boards": list(boards), "domains": {board: [board] for board in boards}},
        "review": {"consultation_id": "c1", "summary": "Fine.", "boards": [
            entry(board, verdict, (blockers or {}).get(board, ())) for board, verdict in boards.items()]},
        "decision": {"outcome": "approved", "by": APPROVER, "reason": "Agreed", "at": "2026-11-21T10:00:00+00:00"},
        "result": {"checks": list(checks), "packs": list(packs),
                   "closing": {"open_points": list(groups), "not_concerned": list(not_concerned), "by": CLOSER}},
        "deliberation": {"objections": list(objections or []), "responses": [], "agreed": [], "open": [],
                         "decision_needed": ""},
        **extra,
    }
    if resolutions:
        task["blocker_resolutions"] = resolutions
    return task


def group(title: str, *points: str) -> dict:
    return {"group": title, "points": list(points)}


class TaskFactsTests(unittest.TestCase):
    def test_a_rule_set_aside_or_failed_comes_with_its_recorded_reason(self):
        facts = facts_of_task(closed(checks=[
            skipped("rule:react/reuse-ui-components"),
            skipped("rule:python/type-public-interfaces", "No change in this area.", "not-applicable"),
            {"check": "rule:typescript/strict-type-checking", "status": "failed", "evidence": "tsc reports 3 errors."},
            {"check": "evidence:gdpr/ropa/record", "status": "not-applicable", "reason": "Existing processing.",
             "owner": OWNER},
        ], packs=[{"pack": "fastapi", "status": "not-applicable", "reason": "Not used here.", "owner": OWNER}]))
        self.assertEqual(facts["rules"], [
            {"check": "evidence:gdpr/ropa/record", "status": "not-applicable", "reason": "Existing processing."},
            {"check": "pack:fastapi", "status": "not-applicable", "reason": "Not used here."},
            {"check": "rule:python/type-public-interfaces", "status": "not-applicable",
             "reason": "No change in this area."},
            {"check": "rule:react/reuse-ui-components", "status": "skipped", "reason": "Handled by the platform team."},
            {"check": "rule:typescript/strict-type-checking", "status": "failed", "reason": "tsc reports 3 errors."},
        ])

    def test_a_task_that_applied_every_rule_has_none_to_report(self):
        facts = facts_of_task(closed(checks=[
            {"check": "rule:react/reuse-ui-components", "status": "passed", "evidence": "src/Button.tsx"},
            {"check": "command:1", "status": "failed", "message": "exit 1"},
            {"check": "chaosfolk:login", "status": "failed"},
        ], packs=[{"pack": "react", "status": "passed", "evidence": "tests/test_ui.py"}]))
        self.assertEqual(facts["rules"], [])
        self.assertEqual(facts["not_concerned"], [])
        self.assertEqual(facts["waivers"], [])
        self.assertEqual(facts["reservations"], [])

    def test_what_the_task_was_not_asked_comes_from_its_closing_with_the_reason(self):
        concerned = [{"pack": "gdpr", "reason": "The task's data is none.", "checks": 6},
                     {"check": "evidence:dora/x/y", "reason": "It applies to regulated data.", "checks": 1}]
        self.assertEqual(facts_of_task(closed(not_concerned=concerned))["not_concerned"], concerned)

    def test_a_committee_without_a_blocker_or_an_objection_that_proceeds_brought_nothing(self):
        facts = facts_of_task(closed(boards={"product": "proceed", "qa": "proceed", "security": "revise"},
                                     objections=[{"id": "security-to-product", "from": "security", "to": "product"}]))
        self.assertEqual(facts["committees"], {"convened": ["product", "qa", "security"], "without": ["qa"]})

    def test_a_committee_that_asked_for_changes_blocked_or_was_objected_to_brought_something(self):
        for name, verdict, blockers, objections in (
                ("revise", "revise", (), []),
                ("insufficient-evidence", "insufficient-evidence", (), []),
                ("block with a blocker", "block", ({"finding": "No access test.", "owner": "Lead", "clears_when": "x"},), []),
                ("objected to", "proceed", (), [{"id": "x", "from": "security", "to": "qa"}]),
                ("objecting", "proceed", (), [{"id": "x", "from": "qa", "to": "security"}])):
            with self.subTest(name):
                task = closed(boards={"qa": verdict, "security": "proceed"}, blockers={"qa": blockers},
                              objections=objections)
                self.assertNotIn("qa", facts_of_task(task)["committees"]["without"])

    def test_a_proceed_that_carries_a_blocker_is_not_a_silent_committee(self):
        blocker = {"finding": "Retention is not decided.", "owner": "DPO", "clears_when": "It is recorded."}
        task = closed(boards={"legal": "proceed"}, blockers={"legal": (blocker,)})
        self.assertEqual(facts_of_task(task)["committees"]["without"], [])

    def test_the_objections_recorded_by_the_deliberation_stand_and_the_review_gives_them_otherwise(self):
        catalog = load_catalog()
        profile = validate_profile(json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), catalog)
        task = {"id": "request-status", "brief": "Show request status.", "answers": json.loads(
            (EXAMPLE / "answers.json").read_text(encoding="utf-8")), "status": "consulting", "rounds": [],
                "profile_fingerprint": "0" * 64}
        consultation = consult(resolved_profile(profile, catalog), catalog, task)
        review = {"consultation_id": consultation["id"], **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        reviewed = record_review({**task, "consultation": consultation}, review)
        closed_task = {**reviewed, "status": "done", "created_at": "2026-11-20T10:00:00+00:00",
                       "result": {"checks": [], "closing": {"open_points": [], "not_concerned": []}}}
        # The example's review: marketing objects to product and security to legal; qa is left out of both.
        silent = facts_of_task(closed_task)["committees"]["without"]
        self.assertEqual(silent, ["qa"])
        recorded = {**closed_task, "deliberation": {"objections": [], "responses": [], "agreed": [], "open": [],
                                                    "decision_needed": ""}}
        self.assertEqual(facts_of_task(recorded)["committees"]["without"], ["product", "qa", "legal"])

    def test_the_open_reservations_keep_the_order_of_the_closing_without_the_people(self):
        points = [
            group(SENSITIVE_GROUP, f"rule:gdpr/dpia is skipped: Existing processing. ({OWNER}) [data protection]"),
            group("Board blocks not lifted", "security said block; blocker security:1 is waived until 2026-12-05, "
                                             "not cleared"),
            group(NOT_RUN_GROUP, f"command:1 could not run: No network. (recorded by {OWNER})"),
            group("Named evidence handed to a follow-up task",
                  f"evidence:gdpr/ropa/record is handed to task follow, provided by the DPO (recorded by {CLOSER})"),
        ]
        facts = facts_of_task(closed(groups=points, checks=[skipped("rule:gdpr/dpia")]))
        self.assertEqual([item["group"] for item in facts["reservations"]], [item["group"] for item in points])
        self.assertEqual(facts["reservations"][0]["points"], ["rule:gdpr/dpia is skipped: Existing processing. "
                                                              "[data protection]"])
        self.assertEqual(facts["reservations"][2]["points"], ["command:1 could not run: No network."])
        self.assertEqual(facts["reservations"][3]["points"],
                         ["evidence:gdpr/ropa/record is handed to task follow, provided by the DPO"])

    def test_a_blocker_waived_names_its_end_date_and_one_cleared_is_not_reported(self):
        blockers = {"security": ({"finding": "No access test.", "owner": "Security lead", "clears_when": "A test passes."},
                                 {"finding": "Retention is not decided.", "owner": "DPO", "clears_when": "Recorded."})}
        task = closed(boards={"security": "block"}, blockers=blockers,
                      resolutions={"security:1": WAIVED, "security:2": CLEARED})
        self.assertEqual(facts_of_task(task)["waivers"], [{
            "blocker": "security:1", "board": "security", "phase": "approval", "finding": "No access test.",
            "until": "2026-12-05", "reason": "Pilot only.", "scope": "Pilot"}])
        self.assertEqual(facts_of_task(closed())["waivers"], [])

    def test_no_field_that_holds_a_person_reaches_the_facts(self):
        blockers = {"security": ({"finding": "No access test.", "owner": OWNER, "clears_when": "A test passes."},)}
        task = closed(
            boards={"security": "block"}, blockers=blockers, resolutions={"security:1": WAIVED},
            checks=[skipped("rule:react/reuse-ui-components")],
            packs=[{"pack": "fastapi", "status": "not-applicable", "reason": "Not used.", "owner": OWNER}],
            groups=[group(SENSITIVE_GROUP, f"rule:a/b is skipped: Why. ({OWNER}) [security]"),
                    group(NOT_RUN_GROUP, f"command:1 could not run: Why. (recorded by {WAIVER})")])
        task["result"]["deferred"] = [{"check": "evidence:a/b/c", "task": "f", "owner": "the DPO", "by": CLOSER}]
        facts = facts_of_task(task)
        retro = task_retro(facts)
        printed = json.dumps([facts, retro]) + "\n".join(render_task(retro))
        for name in NAMES:
            self.assertNotIn(name, printed)

    def test_a_task_that_is_not_closed_has_no_retrospective(self):
        for status in ("draft", "reviewed", "approved", "changes-requested"):
            with self.subTest(status), self.assertRaisesRegex(ValueError, "closed"):
                facts_of_task({**closed(), "status": status})

    def test_a_task_closed_by_an_earlier_release_is_read_with_what_it_has(self):
        old = {"id": "old", "status": "done", "created_at": "2026-10-01T00:00:00+00:00", "brief": "Old.", "rounds": [],
               "result": {"checks": [skipped("rule:python/follow-python-style", "Old reason.")],
                          "closing": {"open_points": []}}}
        facts = facts_of_task(old)
        self.assertEqual((facts["not_concerned"], facts["waivers"], facts["reservations"], facts["commands"]),
                         ([], [], [], {}))
        self.assertEqual([item["reason"] for item in facts["rules"]], ["Old reason."])
        # No review to read: the committees are said to be unread, and the rest is still told.
        self.assertIsNone(facts["committees"])
        retro = task_retro(facts)
        self.assertEqual(len(retro["not_recorded"]), 1)
        self.assertIn("cannot be read", retro["not_recorded"][0])
        self.assertIn("Committees: not read", "\n".join(render_task(retro)))
        bare = {key: value for key, value in old.items() if key != "result"}
        self.assertEqual(facts_of_task(bare)["rules"], [])

    def test_the_closing_groups_the_retrospective_names_are_those_the_task_writes(self):
        # The titles of tasks.py are the ones the recurrences leave out or read; a renamed group fails here.
        self.assertEqual({SENSITIVE_GROUP, OTHER_RULES_GROUP, NOT_RUN_GROUP, VERDICTS_GROUP},
                         {"Data protection, security or AI rules skipped, failed or declared not applicable as a pack",
                          "Other rules skipped or failed", "Project checks that could not run in this environment",
                          "Board verdicts at approval that asked for changes"})


def record_of(task: dict) -> dict:
    """The exported record of a closed task, as `task export` writes it (guard.export_decision)."""
    result, checks = task["result"], task["result"]["checks"]
    record = {
        "schema_version": 2, "task": task["id"], "brief": task["brief"], "status": task["status"],
        "task_created_at": task["created_at"], "summary": "Fine.", "completed": True,
        "boards": [{"id": item["id"], "verdict": item["challenge"]["verdict"], "recommendation": item["recommendation"]}
                   for item in task["review"]["boards"]],
        "decision": {"by": APPROVER, "reason": "Agreed", "at": "2026-11-21T10:00:00+00:00"},
        "result": {"checks": {item["check"]: item["status"] for item in checks},
                   "check_exceptions": [{key: item[key] for key in ("check", "status", "reason", "owner") if key in item}
                                        for item in checks if item["status"] in ("skipped", "not-applicable")],
                   "closing": result["closing"]},
    }
    if result.get("packs"):
        record["result"]["packs"] = result["packs"]
    record["blockers"] = [{"id": "security:1", "board": "security", "phase": "approval", "finding": "No access test.",
                           "owner": OWNER, "clears_when": "A test passes.", "resolution": WAIVED}] if (
        task.get("blocker_resolutions")) else []
    return record


class ExportedRecordFactsTests(unittest.TestCase):
    def test_an_exported_record_gives_the_rules_the_reservations_and_the_waivers(self):
        task = closed(
            boards={"security": "block"}, resolutions={"security:1": WAIVED},
            checks=[skipped("rule:react/reuse-ui-components"),
                    {"check": "rule:typescript/strict-type-checking", "status": "failed", "evidence": "tsc fails."}],
            groups=[group("Blockers waived rather than cleared", "blocker security:1 is waived until 2026-12-05")],
            not_concerned=[{"pack": "gdpr", "reason": "The task's data is none.", "checks": 6}])
        task["review"]["boards"][0]["challenge"]["blockers"] = [
            {"finding": "No access test.", "owner": OWNER, "clears_when": "A test passes."}]
        from_task, from_record = facts_of_task(task), facts_of_record(record_of(task))
        self.assertEqual((from_record["id"], from_record["status"], from_record["source"]),
                         ("t1", "done-with-reservations", "record"))
        for key in ("reservations", "waivers", "not_concerned"):
            self.assertEqual(from_record[key], from_task[key], key)
        # A failed rule has only its status in a record: the evidence stays in the task record.
        self.assertEqual([(item["check"], item["status"]) for item in from_record["rules"]],
                         [(item["check"], item["status"]) for item in from_task["rules"]])
        self.assertEqual(next(item for item in from_record["rules"] if item["status"] == "failed")["reason"], "")

    def test_the_committees_are_not_in_an_exported_record_and_the_retrospective_says_so(self):
        facts = facts_of_record(record_of(closed()))
        self.assertIsNone(facts["committees"])
        retro = task_retro(facts)
        self.assertEqual(retro["source"], "exported record")
        self.assertTrue(any("committees" in note and "objection" in note for note in retro["not_recorded"]))
        self.assertEqual(task_retro(facts_of_task(closed()))["not_recorded"], [])
        self.assertIn("not in the exported record", " ".join(render_task(retro)))

    def test_an_exported_record_that_was_not_completed_has_no_retrospective(self):
        record = {**record_of(closed()), "completed": False, "status": "approved"}
        with self.assertRaisesRegex(ValueError, "closed"):
            facts_of_record(record)

    def test_no_name_of_an_exported_record_reaches_the_facts(self):
        task = closed(checks=[skipped("rule:react/reuse-ui-components")],
                      groups=[group(NOT_RUN_GROUP, f"command:1 could not run: Why. (recorded by {OWNER})")])
        printed = json.dumps(task_retro(facts_of_record(record_of(task))))
        for name in NAMES:
            self.assertNotIn(name, printed)


GARBAGE = (None, 0, 7, True, "text", "", [], {}, [None], [1, "a"], {"a": 1}, ["x"], {"group": 1, "points": "no"},
           [{"group": "g", "points": [1, None]}], {"pack": 3, "status": ["failed"]})


def damaged(value, path=()):
    """Every copy of a record with the value at one path replaced by something that is not what the shape asks, or
    removed, down to the third level: what a record edited by hand or written by another release could hold."""
    if len(path) < 3 and isinstance(value, (dict, list)):
        for key in (value if isinstance(value, dict) else range(len(value))):
            for bad in GARBAGE:
                copy_ = copy.deepcopy(value)
                copy_[key] = bad
                yield (*path, key), copy_
            if isinstance(value, dict):
                copy_ = copy.deepcopy(value)
                del copy_[key]
                yield (*path, key), copy_
            for sub_path, sub in damaged(value[key], (*path, key)):
                copy_ = copy.deepcopy(value)
                copy_[key] = sub
                yield sub_path, copy_


class DamagedRecordTests(unittest.TestCase):
    """A record of the project can be wrong in any field: the retrospective says it cannot read it, never a trace."""

    def rich_task(self) -> dict:
        task = closed(boards={"security": "block"}, resolutions={"security:1": WAIVED},
                      checks=[skipped("rule:react/reuse-ui-components"),
                              {"check": "rule:python/follow-python-style", "status": "failed", "evidence": "e"}],
                      packs=[{"pack": "fastapi", "status": "not-applicable", "reason": "Not used.", "owner": OWNER}],
                      groups=[group(NOT_RUN_GROUP, f"command:1 could not run: Why. (recorded by {OWNER})")],
                      not_concerned=[{"pack": "gdpr", "reason": "No data.", "checks": 2}])
        task["review"]["boards"][0]["challenge"]["blockers"] = [
            {"finding": "No access test.", "owner": OWNER, "clears_when": "A test passes."}]
        return task

    def test_a_result_that_is_not_what_a_task_record_keeps_gives_facts_or_a_refusal(self):
        task, tried = self.rich_task(), 0
        for path, result in damaged(task["result"]):
            tried += 1
            with self.subTest(path=path):
                facts = facts_of_task({**task, "result": result})
                render_task(task_retro(facts))
                recurrences([facts], 1)
        self.assertGreater(tried, 300)

    def test_an_exported_record_that_is_not_what_one_keeps_gives_facts_or_a_refusal(self):
        record, tried = record_of(self.rich_task()), 0
        for path, damaged_record in damaged(record):
            tried += 1
            with self.subTest(path=path):
                try:
                    facts = facts_of_record(damaged_record)
                except ValueError:
                    continue  # a record that does not say it is completed has no retrospective
                render_task(task_retro(facts))
                recurrences([facts], 1)
        self.assertGreater(tried, 500)


def set_aside(task_id: str, check: str = "rule:react/reuse-ui-components", reason: str = "Handled by the platform.",
              status: str = "skipped") -> dict:
    return closed(task_id, checks=[skipped(check, reason, status)])


class RecurrenceTests(unittest.TestCase):
    def found(self, tasks, minimum=DEFAULT_MINIMUM):
        return recurrences([facts_of_task(task) for task in tasks], minimum)

    def test_the_default_is_three_tasks(self):
        self.assertEqual(DEFAULT_MINIMUM, 3)

    def test_a_rule_set_aside_for_the_same_reason_counts_from_the_task_that_makes_it_the_minimum(self):
        two = [set_aside(f"t{number}") for number in (1, 2)]
        self.assertEqual(self.found(two), [])
        found = self.found([*two, set_aside("t3")])
        self.assertEqual([(item["kind"], item["check"], item["status"], item["count"], item["tasks"]) for item in found],
                         [("rule", "rule:react/reuse-ui-components", "skipped", 3, ["t1", "t2", "t3"])])
        self.assertEqual(found[0]["reason"], "Handled by the platform.")
        self.assertEqual([item["count"] for item in self.found(two, minimum=2)], [2])

    def test_the_same_rule_with_another_reason_or_another_status_is_another_finding(self):
        tasks = [set_aside("t1"), set_aside("t2"), set_aside("t3", reason="Out of scope."),
                 set_aside("t4", status="not-applicable")]
        self.assertEqual(self.found(tasks), [])
        self.assertEqual(len(self.found(tasks, minimum=1)), 3)

    def test_the_wording_of_a_reason_is_compared_without_case_spacing_or_final_stop(self):
        tasks = [set_aside("t1", reason="Handled by the platform."), set_aside("t2", reason="handled by  the PLATFORM"),
                 set_aside("t3", reason="  Handled by the platform.. ")]
        self.assertEqual([item["count"] for item in self.found(tasks)], [3])

    def test_a_task_counts_once_however_many_times_it_says_the_same_thing(self):
        twice = closed("t1", checks=[skipped("rule:react/reuse-ui-components")] * 2)
        found = self.found([twice, set_aside("t2", reason="Handled by the platform team.")], minimum=1)
        self.assertEqual([item["tasks"] for item in found], [["t1", "t2"]])

    def test_a_failed_rule_counts_by_rule_whatever_the_evidence_says(self):
        tasks = [closed(f"t{number}", checks=[{"check": "rule:python/follow-python-style", "status": "failed",
                                               "evidence": f"{number} errors."}]) for number in (1, 2, 3)]
        found = self.found(tasks)
        self.assertEqual([(item["check"], item["status"], item["count"]) for item in found],
                         [("rule:python/follow-python-style", "failed", 3)])

    def test_a_pack_declared_not_applicable_as_a_whole_counts_by_pack(self):
        tasks = [closed(f"t{number}", packs=[{"pack": "fastapi", "status": "not-applicable", "reason": "Not used.",
                                              "owner": OWNER}]) for number in (1, 2, 3)]
        self.assertEqual([item["check"] for item in self.found(tasks)], ["pack:fastapi"])

    def test_a_committee_counts_in_the_tasks_where_it_brought_nothing_and_says_where_it_was_convened(self):
        silent = {"qa": "proceed", "product": "revise"}
        tasks = [closed(f"t{number}", boards=silent, objections=[]) for number in (1, 2, 3)]
        tasks.append(closed("t4", boards={"qa": "revise", "product": "revise"}))
        found = self.found(tasks)
        self.assertEqual([(item["kind"], item["board"], item["count"], item["convened_in"]) for item in found],
                         [("committee", "qa", 3, 4)])
        self.assertEqual(self.found(tasks[1:]), [])

    def test_the_tasks_known_only_by_a_record_do_not_count_for_committees(self):
        tasks = [facts_of_task(closed(f"t{number}", boards={"qa": "proceed"})) for number in (1, 2)]
        tasks.append(facts_of_record(record_of(closed("t3", boards={"qa": "proceed"}))))
        self.assertEqual(recurrences(tasks, 3), [])
        self.assertEqual([(item["count"], item["convened_in"]) for item in recurrences(tasks, 2)], [(2, 2)])

    def test_a_reservation_counts_by_its_wording_without_dates_blocker_numbers_or_follow_up_tasks(self):
        def waived(number, until):
            return closed(f"t{number}", groups=[
                group("Blockers waived rather than cleared", f"blocker security:{number} is waived until {until}"),
                group("Named evidence handed to a follow-up task",
                      f"evidence:gdpr/ropa/record is handed to task follow-{number}, provided by the DPO "
                      f"(recorded by {CLOSER})")])
        found = self.found([waived(1, "2026-12-01"), waived(2, "2026-12-09"), waived(3, "2027-01-03")])
        self.assertEqual({item["point"] for item in found},
                         {"blocker security is waived until <date>",
                          "evidence:gdpr/ropa/record is handed to a follow-up task, provided by the DPO"})
        self.assertEqual({item["count"] for item in found}, {3})
        self.assertEqual({item["kind"] for item in found}, {"reservation"})

    def test_the_closing_lines_that_restate_a_rule_or_a_verdict_are_not_counted_as_reservations(self):
        def with_groups(number):
            return closed(f"t{number}", checks=[skipped("rule:react/reuse-ui-components")], groups=[
                group(OTHER_RULES_GROUP, "rule:react/reuse-ui-components is skipped: Handled by the platform."),
                group(SENSITIVE_GROUP, "rule:gdpr/dpia is skipped: Why. [data protection]"),
                group(VERDICTS_GROUP, "engineering said revise")])
        found = self.found([with_groups(number) for number in (1, 2, 3)])
        self.assertEqual([item["kind"] for item in found], ["rule"])

    def test_a_command_that_could_not_run_is_named_by_the_command_not_by_its_number(self):
        def stuck(number, command):
            declared = {"check": "command:1", "status": "failed", "cannot_run": True, "reason": "No network.",
                        "owner": OWNER}
            return closed(f"t{number}", checks=[declared],
                          groups=[group(NOT_RUN_GROUP, f"command:1 could not run: No network. (recorded by {OWNER})")],
                          consultation={"id": "c1", "boards": ["qa"], "scope": {"checks": [command]}})
        found = self.found([stuck(1, "npm ci"), stuck(2, "npm ci"), stuck(3, "npm ci")])
        self.assertEqual([(item["point"], item["check_command"]) for item in found],
                         [("`npm ci` could not run: No network", "npm ci")])
        changed = self.found([stuck(1, "npm ci"), stuck(2, "npm ci"), stuck(3, "make test")])
        self.assertEqual(changed, [])

    def test_the_result_is_the_same_whatever_the_order_the_records_were_read_in(self):
        tasks = [set_aside(f"t{number}") for number in range(1, 4)]
        tasks.append(closed("t4", boards={"qa": "proceed", "product": "revise"}, groups=[
            group("Warnings on the result", "The same file is cited for 3 different named evidences: a, b, c.")]))
        tasks.append(closed("t5", boards={"qa": "proceed", "product": "revise"}, groups=[
            group("Warnings on the result", "The same file is cited for 3 different named evidences: a, b, c.")]))
        facts = [facts_of_task(task) for task in tasks]
        expected = json.dumps(recurrences(facts, 2))
        for order in itertools.permutations(facts):
            self.assertEqual(json.dumps(recurrences(list(order), 2)), expected)
        shuffled = list(facts)
        random.Random(423).shuffle(shuffled)
        self.assertEqual(json.dumps(recurrences(shuffled, 2)), expected)

    def test_the_findings_come_rules_first_then_committees_then_reservations_most_frequent_first(self):
        tasks = [closed(f"t{number}", checks=[skipped("rule:react/reuse-ui-components")],
                        boards={"qa": "proceed"},
                        groups=[group("Warnings on the result", "A warning.")]) for number in (1, 2, 3)]
        tasks.append(closed("t4", checks=[skipped("rule:react/reuse-ui-components")], boards={"qa": "proceed"}))
        self.assertEqual([(item["kind"], item["count"]) for item in self.found(tasks, 2)],
                         [("rule", 4), ("committee", 4), ("reservation", 3)])

    def test_a_minimum_below_one_is_refused(self):
        with self.assertRaisesRegex(ValueError, "--min"):
            recurrences([], 0)


def profile_and_catalog(**changes):
    catalog = load_catalog()
    base = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    return validate_profile({**base, **changes}, catalog), catalog


def finding(kind: str, **fields) -> dict:
    return {"kind": kind, "count": 3, "tasks": ["a", "b", "c"], "label": "x", **fields}


class ProposalTests(unittest.TestCase):
    def propose(self, found, **changes):
        profile, catalog = profile_and_catalog(**changes)
        return proposals([found], profile, catalog)[0]

    def parses(self, command: str) -> None:
        words = shlex.split(command)
        self.assertEqual(words[0], "openguildkit")
        command_parser().parse_args(words[1:])

    def test_a_rule_that_failed_in_several_tasks_can_be_made_a_required_rule(self):
        item = self.propose(finding("rule", check="rule:python/follow-python-style", status="failed", reason=""))
        self.assertEqual(item["command"],
                         "openguildkit profile add required-rule python/follow-python-style --by NAME --reason "
                         "'task retro: rule:python/follow-python-style failed in 3 tasks (a, b, c)'")
        self.assertFalse(item["needs_terminal"])
        self.parses(item["command"])

    def test_a_pack_that_failed_as_a_whole_is_required_as_a_whole(self):
        item = self.propose(finding("rule", check="pack:python", status="failed", reason=""))
        self.assertEqual(item["command"], "openguildkit profile add required-rule python --by NAME --reason "
                                          "'task retro: pack:python failed in 3 tasks (a, b, c)'")

    def test_a_rule_already_required_gets_no_command(self):
        item = self.propose(finding("rule", check="rule:python/follow-python-style", status="failed", reason=""),
                            required_rules=["python/follow-python-style"])
        self.assertIsNone(item["command"])

    def test_one_rule_set_aside_has_no_profile_command_since_none_declines_a_single_rule(self):
        for status in ("skipped", "not-applicable"):
            item = self.propose(finding("rule", check="rule:react/reuse-ui-components", status=status, reason="Why."))
            self.assertIsNone(item["command"], status)
        self.assertIsNone(self.propose(finding("rule", check="evidence:gdpr/ropa/record", status="not-applicable",
                                               reason="Why."))["command"])

    def test_a_pack_that_only_a_pattern_brings_leaves_with_that_pattern_and_the_others_it_drops_are_named(self):
        item = self.propose(finding("rule", check="pack:fastapi", status="not-applicable", reason="Not used."))
        self.assertEqual(item["command"],
                         "openguildkit profile decline python-fastapi-postgresql --by NAME --reason "
                         "'task retro: pack:fastapi not-applicable in 3 tasks (a, b, c): Not used.'")
        self.assertIn("api-design", item["also_drops"])
        self.assertNotIn("fastapi", item["also_drops"])
        self.parses(item["command"])

    def test_a_pack_the_profile_lists_and_no_pattern_brings_leaves_with_remove_pack(self):
        item = self.propose(finding("rule", check="pack:nist-ai-risk", status="skipped", reason="Why."),
                            packs=["agent-workflow", "python", "react", "secure-sdlc", "typescript", "nist-ai-risk"])
        self.assertEqual(item["command"], "openguildkit profile remove pack nist-ai-risk --by NAME --reason "
                                          "'task retro: pack:nist-ai-risk skipped in 3 tasks (a, b, c): Why.'")
        self.assertTrue(item["needs_terminal"])
        self.parses(item["command"])

    def test_a_pack_that_a_pack_list_and_a_pattern_both_bring_has_no_single_command(self):
        # react is in packs and brought by react-web: removing either leaves it active.
        item = self.propose(finding("rule", check="pack:react", status="not-applicable", reason="Not used."))
        self.assertIsNone(item["command"])

    def test_a_committee_that_never_brought_anything_can_leave_the_boards_the_profile_lists(self):
        boards = ["product", "engineering", "qa", "design", "marketing", "security", "legal"]
        item = self.propose(finding("committee", board="qa", convened_in=3), boards=boards)
        self.assertEqual(item["command"], "openguildkit profile remove board qa --by NAME --reason "
                                          "'task retro: qa brought no blocker or objection in 3 tasks (a, b, c)'")
        self.assertFalse(item["needs_terminal"])
        self.parses(item["command"])
        protective = self.propose(finding("committee", board="security", convened_in=3), boards=boards)
        self.assertTrue(protective["needs_terminal"])

    def test_a_committee_that_brought_something_elsewhere_or_that_the_profile_does_not_list_has_no_command(self):
        boards = ["product", "engineering", "qa", "design", "marketing", "security", "legal"]
        self.assertIsNone(self.propose(finding("committee", board="qa", convened_in=4), boards=boards)["command"])
        self.assertIsNone(self.propose(finding("committee", board="qa", convened_in=3))["command"])

    def test_a_command_that_could_not_run_can_be_removed_from_the_checks_with_its_text_quoted(self):
        command = "python -m pytest"
        item = self.propose(finding("reservation", group=NOT_RUN_GROUP, point="x", check_command=command),
                            checks=[command, "npm test"])
        self.assertEqual(item["command"], "openguildkit profile remove check 'python -m pytest' --by NAME --reason "
                                          "'task retro: x in 3 tasks (a, b, c)'")
        self.assertTrue(item["needs_terminal"])
        self.parses(item["command"])
        self.assertIsNone(self.propose(finding("reservation", group=NOT_RUN_GROUP, point="x", check_command="make"))["command"])

    def test_the_other_reservations_have_no_profile_command(self):
        item = self.propose(finding("reservation", group="Warnings on the result", point="A warning."))
        self.assertIsNone(item["command"])
        self.assertIsNone(item["proposed_reason"])
        self.assertFalse(item["needs_terminal"])

    def test_the_reason_names_the_tasks_behind_the_finding_and_the_json_keeps_it_with_them(self):
        item = self.propose(finding("rule", check="rule:python/follow-python-style", status="failed", reason=""))
        self.assertEqual(item["proposed_reason"], "task retro: rule:python/follow-python-style failed in 3 tasks (a, b, c)")
        self.assertEqual(item["tasks"], ["a", "b", "c"])
        self.assertEqual(shlex.split(item["command"])[-3:], ["NAME", "--reason", item["proposed_reason"]])

    def test_the_reason_is_quoted_for_posix_and_powershell_and_reads_back_as_written(self):
        profile, catalog = profile_and_catalog(packs=["agent-workflow", "python", "react", "secure-sdlc", "typescript",
                                                      "nist-ai-risk"])
        found = finding("rule", check="pack:nist-ai-risk", status="skipped", reason="Team's call: no `$HOME` use.")
        posix = proposals([found], profile, catalog, powershell=False)[0]
        powershell = proposals([found], profile, catalog, powershell=True)[0]
        reason = "task retro: pack:nist-ai-risk skipped in 3 tasks (a, b, c): Team's call: no `$HOME` use."
        self.assertEqual(posix["proposed_reason"], reason)
        self.assertEqual(shlex.split(posix["command"])[-1], reason)
        self.assertTrue(powershell["command"].endswith(" --reason 'task retro: pack:nist-ai-risk skipped in 3 tasks "
                                                       "(a, b, c): Team''s call: no `$HOME` use.'"))

    def test_the_reason_is_one_line_and_bounded_however_many_tasks_and_long_the_finding(self):
        tasks = [f"task-number-{index}" for index in range(40)]
        command = "python -m pytest " + " ".join(["tests/very/long/path"] * 30)
        item = self.propose(finding("reservation", group=NOT_RUN_GROUP, point=f"`{command}`\ncould not run: no net.",
                                    check_command=command, count=40, tasks=tasks), checks=[command])
        reason = item["proposed_reason"]
        self.assertLessEqual(len(reason), MAX_REASON)
        self.assertNotIn("\n", reason)
        self.assertIn("in 40 tasks (task-number-0, task-number-1, task-number-2, task-number-3, task-number-4, 35 more)",
                      reason)
        self.assertTrue(reason.startswith("task retro: `python -m pytest"))
        self.parses(item["command"])

    def test_the_profile_is_not_changed_by_asking(self):
        profile, catalog = profile_and_catalog()
        before = copy.deepcopy(profile)
        proposals([finding("rule", check="pack:fastapi", status="skipped", reason="Why.")], profile, catalog)
        self.assertEqual(profile, before)


class RenderTests(unittest.TestCase):
    def test_a_task_is_told_in_a_few_lines_and_names_the_command_for_the_detail(self):
        task = closed(
            boards={"product": "proceed", "qa": "proceed", "security": "block"},
            blockers={"security": ({"finding": "No access test.", "owner": "Lead", "clears_when": "x"},)},
            resolutions={"security:1": WAIVED},
            objections=[{"id": "security-to-product", "from": "security", "to": "product"}],
            checks=[skipped(f"rule:react/rule-{number}", "No change in this area.", "not-applicable")
                    for number in range(30)],
            groups=[group("Board blocks not lifted", "security said block; blocker security:1 is waived until "
                                                     "2026-12-05, not cleared")],
            not_concerned=[{"pack": f"pack-{number}", "reason": "The task's surface is service.", "checks": 2}
                           for number in range(12)])
        lines = render_task(task_retro(facts_of_task(task)))
        text = "\n".join(lines)
        self.assertLess(len(lines), 16)
        self.assertIn("30 rules not-applicable: No change in this area.", text)
        self.assertIn("12 packs not concerned: The task's surface is service.", text)
        self.assertIn("without a blocker or an objection", text)
        self.assertIn("qa", text)
        self.assertIn("security:1 until 2026-12-05: Pilot only. (scope: Pilot)", text)
        self.assertIn("openguildkit task retro t1 --json", text)
        self.assertIn("openguildkit task retro --all", text)

    def test_a_task_with_nothing_to_report_says_so(self):
        text = "\n".join(render_task(task_retro(facts_of_task(closed(boards={"security": "revise"}, objections=[
            {"id": "x", "from": "security", "to": "qa"}])))))
        self.assertIn("no rule set aside", text)

    def test_a_long_list_is_cut_with_the_command_that_shows_all_of_it(self):
        task = closed(checks=[skipped(f"rule:react/rule-{number}", f"Reason {number}.") for number in range(40)])
        lines = render_task(task_retro(facts_of_task(task)))
        self.assertLess(len(lines), 20)
        self.assertTrue(any("more" in line and "--json" in line for line in lines))

    def test_the_project_names_each_finding_in_a_line_with_its_command_and_the_terminal_rule(self):
        profile, catalog = profile_and_catalog()
        tasks = [closed(f"t{number}", checks=[{"check": "rule:python/follow-python-style", "status": "failed",
                                               "evidence": "e"}]) for number in (1, 2, 3)]
        summary = project_summary([facts_of_task(task) for task in tasks], 3, profile, catalog, {})
        text = "\n".join(render_project(summary))
        self.assertIn("rule:python/follow-python-style failed in 3 tasks (t1, t2, t3)", text)
        self.assertIn("openguildkit profile add required-rule python/follow-python-style --by NAME --reason "
                      "'task retro: rule:python/follow-python-style failed in 3 tasks (t1, t2, t3)'", text)
        self.assertIn("terminal", text)
        self.assertIn("--by is theirs to fill in", text)
        for name in NAMES:
            self.assertNotIn(name, text)
        self.assertEqual(summary["tasks"], {"read": 3, "from_task_records": 3, "from_exported_records": 0})

    def test_rules_set_aside_the_same_way_in_the_same_tasks_share_one_line_while_the_json_keeps_each(self):
        profile, catalog = profile_and_catalog()
        tasks = [closed(f"t{number}", checks=[
            skipped("rule:postgresql/protect-data-invariants", "Schema untouched.", "not-applicable"),
            skipped("rule:postgresql/stage-schema-migrations", "Schema untouched.", "not-applicable"),
            skipped("rule:react/reuse-ui-components", "Handled by the platform team.")]) for number in (1, 2, 3)]
        summary = project_summary([facts_of_task(task) for task in tasks], 3, profile, catalog, {})
        self.assertEqual(len(summary["recurrences"]), 3)
        lines = render_project(summary)
        self.assertIn("2 rules not-applicable in 3 tasks (t1, t2, t3): Schema untouched. "
                      "(rule:postgresql/protect-data-invariants, rule:postgresql/stage-schema-migrations)", "\n".join(lines))
        self.assertLess(len(lines), 12)

    def test_nothing_that_comes_back_is_said_with_the_way_to_lower_the_minimum(self):
        profile, catalog = profile_and_catalog()
        summary = project_summary([facts_of_task(closed("t1")), facts_of_task(closed("t2"))], 3, profile, catalog, {})
        self.assertEqual(summary["recurrences"], [])
        self.assertIn("--min 2", "\n".join(render_project(summary)))

    def test_a_minimum_of_one_with_nothing_set_aside_says_there_is_nothing_to_count(self):
        profile, catalog = profile_and_catalog()
        text = "\n".join(render_project(project_summary([facts_of_task(closed("t1"))], 1, profile, catalog, {})))
        self.assertIn("Nothing to count", text)
        self.assertNotIn("lower minimum", text)

    def test_no_closed_task_is_said_with_the_command_that_lists_the_tasks(self):
        profile, catalog = profile_and_catalog()
        text = "\n".join(render_project(project_summary([], 3, profile, catalog, {})))
        self.assertIn("No closed task to count", text)
        self.assertIn("openguildkit task list", text)

    def test_the_records_left_aside_are_counted_in_the_text(self):
        profile, catalog = profile_and_catalog()
        summary = project_summary([facts_of_task(closed("t1"))], 3, profile, catalog,
                                  {"unreadable_task_records": 1, "exported_records_not_holding": 2})
        text = "\n".join(render_project(summary))
        self.assertIn("1 task record unreadable", text)
        self.assertIn("2 exported records do not match their digest", text)


if __name__ == "__main__":
    unittest.main()
