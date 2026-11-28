"""`openguildkit task retro` on projects whose tasks were closed through the commands of the CLI (issue #423).

Project A holds four closed tasks that share some findings (a rule skipped for the same reason, a rule that failed, a pack
declared not applicable, a waived blocker, a committee that said nothing) and differ on others. Project C holds four tasks
too: three could not run the project's check command, and none of them touched the profile's board list. Every test reads
them; the proof that nothing is written is a fingerprint of the whole project before and after.
"""

import hashlib
import json
import shlex
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.decisions import export_digest
from openguildkit.retro import MAX_REASON
from openguildkit.storage import write_json
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "request-status"
# Names that must never reach what the retrospective prints; `task list` shows the first, third and fourth.
APPROVER, CLOSER, OWNER, WAIVER, DECLARER = (
    "Zorglub-Approver", "Yvonne-Closer", "Quentin-Owner", "Wilhelmina-Waiver", "Desmond-Declarer")
NAMES = (APPROVER, CLOSER, OWNER, WAIVER, DECLARER)
BOARDS = ["product", "engineering", "qa", "design", "marketing", "security", "legal"]
# Fails until ready.txt exists; no single quote, so that every shell prints and reads it back the same way.
READY_COMMAND = f'"{sys.executable}" -c "import os, sys; sys.exit(int(not os.path.exists(sys.argv[1])))" ready.txt'
SKIPPED = "Handled by the platform team."
FAILING = "rule:typescript/strict-type-checking"
SKIPPED_RULE = "react/reuse-ui-components"
OTHER_RULE = "python/follow-python-style"


def cli(root, *arguments, code=0, typed=None, **options):
    return run_cli(root, *arguments, expect=code, typed=typed, **options)


def days(count: int) -> str:
    return (clock.real_today() + timedelta(days=count)).isoformat()


def close_task(root: Path, spec: dict) -> None:
    """One task, from its brief to its closing, as a team does it; `spec` says what is not the default.

    Default: the example's review, every rule passed, nothing waived, the project's check command run.
    """
    task_id = spec["id"]
    cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
    cli(root, "task", "consult", task_id, "--answers", EXAMPLE / "answers.json")
    template = json.loads(cli(root, "task", "template", task_id).stdout)
    review = {"consultation_id": template["consultation_id"],
              **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
    for board in review["boards"]:
        if board["id"] in spec.get("boards", {}):
            board["challenge"].update(verdict=spec["boards"][board["id"]], blockers=[])
        if board["id"] == "security" and spec.get("waive"):
            board["challenge"].update(verdict="block", blockers=[
                {"finding": "No test proves a user cannot read another user's request.", "owner": OWNER,
                 "clears_when": "An automated test with two synthetic accounts passes."}])
    write_json(root / "review.json", review)
    cli(root, "task", "review", task_id, "--file", root / "review.json")
    if spec.get("waive"):
        cli(root, "task", "waive", task_id, "security:1", "--by", WAIVER, "--reason", "Pilot only", "--scope", "Pilot",
            "--until", days(spec["waive"]), typed=task_id)
    cli(root, "task", "decide", task_id, "--approve", "--by", APPROVER, "--reason", "Agreed", typed=task_id)
    if spec.get("cannot_run"):
        cli(root, "task", "verify", task_id, code=1)  # the command fails, and the rules' machine checks are recorded
        cli(root, "task", "verify", task_id, "--cannot-run", "command:1", "--by", DECLARER, "--reason",
            spec["cannot_run"], typed=task_id)
    else:
        cli(root, "task", "verify", task_id)
    write_json(root / "result.json", result_of(root, spec))
    cli(root, "task", "result", task_id, "--file", root / "result.json")
    cli(root, "task", "complete", task_id, "--by", CLOSER, typed=task_id)


def result_of(root: Path, spec: dict) -> dict:
    """The result file of a task: each rule passed unless the spec says otherwise."""
    task_id, packs = spec["id"], spec.get("packs", {})
    checks = json.loads(cli(root, "task", "checks", task_id, "--json").stdout)
    outcomes = []
    for check in (item["id"] for item in checks if item["kind"] == "rule"):
        name = check.removeprefix("rule:")
        if name.split("/")[0] in packs:
            continue  # the pack answer stands for it
        status, reason = spec.get("rules", {}).get(name, ("passed", ""))
        if status == "passed":
            # One evidence for each rule: the same one cited for rules of several packs is itself a warning.
            outcomes.append({"check": check, "status": "passed", "evidence": f"Reviewed {name} in the pull request."})
        elif status == "failed":
            outcomes.append({"check": check, "status": "failed", "evidence": reason})
        else:
            outcomes.append({"check": check, "status": status, "reason": reason, "owner": OWNER})
    return {"pull_request": "https://github.com/example/portal/pull/7", "checks": outcomes,
            "packs": [{"pack": pack, "status": "not-applicable", "reason": reason, "owner": OWNER}
                      for pack, reason in packs.items()],
            "criteria": [{"criterion": "Users only see their own requests.", "status": "met",
                          "evidence": "tests/test_access.py"}]}


def initialized(root: Path, **profile) -> None:
    base = json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))
    write_json(root / "profile.json", {
        **base, "checks": [], "boards": BOARDS, "waivers": {"allowed_by": [WAIVER], "max_days": 30}, **profile})
    cli(root, "init", "--answers", root / "profile.json")


def build_a(root: Path) -> None:
    initialized(root, packs=["agent-workflow", "python", "react", "secure-sdlc", "typescript", "container-images"])
    pack_reason, untouched = "Not used by this team.", ("not-applicable", "Schema untouched.")
    shared = {SKIPPED_RULE: ("skipped", SKIPPED), "postgresql/protect-data-invariants": untouched,
              "postgresql/stage-schema-migrations": untouched}
    failing = FAILING.removeprefix("rule:")
    for spec in (
        {"id": "a1", "waive": 5, "packs": {"fastapi": pack_reason},
         "rules": {**shared, OTHER_RULE: ("skipped", "Out of scope for the pilot."),
                   "python/type-public-interfaces": ("not-applicable", "No change in this area.")}},
        {"id": "a2", "waive": 9, "packs": {"fastapi": pack_reason},
         "rules": {**shared, OTHER_RULE: ("skipped", "Out of scope for the pilot."),
                   failing: ("failed", "tsc reports 2 errors.")}},
        {"id": "a3", "waive": 14, "packs": {"fastapi": pack_reason},
         # The same reason, written another way: the retrospective compares the words, not the case or the stop.
         "rules": {**shared, SKIPPED_RULE: ("skipped", "handled by the  platform team"),
                   failing: ("failed", "tsc reports 5 errors.")}},
        {"id": "a4", "packs": {"fastapi": "Another reason entirely."}, "boards": {"qa": "revise"},
         "rules": {SKIPPED_RULE: ("not-applicable", "No change in this area."),
                   failing: ("failed", "tsc reports 1 error.")}},
    ):
        close_task(root, spec)


def build_c(root: Path) -> None:
    initialized(root, checks=[READY_COMMAND])
    for task_id in ("c1", "c2", "c3"):
        close_task(root, {"id": task_id, "cannot_run": "The sandbox has no network for the tests."})
    (root / "ready.txt").write_text("ready\n", encoding="utf-8")
    close_task(root, {"id": "c4"})


def fingerprint(root: Path) -> list:
    """Every file and folder of the project with its mode, modification time and bytes."""
    entries = []
    for path in sorted(root.rglob("*")):
        stat = path.lstat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        entries.append((path.relative_to(root).as_posix(), stat.st_mode, stat.st_mtime_ns, digest))
    return entries


def streams(result) -> str:
    return result.stdout + "\n" + result.stderr


class RetroCase(unittest.TestCase):
    """A project built once for the class; each test gets a copy it may change."""

    builder = None
    source = None

    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory(prefix="ogk-retro-")
        cls.addClassCleanup(temporary.cleanup)
        cls.source = Path(temporary.name).resolve() / "built"
        cls.source.mkdir()
        cls.builder(cls.source)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ogk-retro-copy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "project"
        shutil.copytree(self.source, self.root)

    def retro(self, *arguments, code=0):
        return cli(self.root, "task", "retro", *arguments, code=code)

    def found(self, *arguments):
        return json.loads(self.retro("--all", "--json", *arguments).stdout)["recurrences"]

    def task(self, task_id):
        return json.loads(self.retro(task_id, "--json").stdout)


def key(item: dict) -> tuple:
    return item["kind"], item.get("check") or item.get("board") or item["point"]


class RulesAndReservationsTests(RetroCase):
    builder = build_a

    def test_a_task_lists_the_rules_it_set_aside_with_the_reason_it_recorded(self):
        rules = {(item["check"], item["status"]): item["reason"] for item in self.task("a1")["rules"]}
        self.assertEqual(rules[(f"rule:{SKIPPED_RULE}", "skipped")], SKIPPED)
        self.assertEqual(rules[(f"rule:{OTHER_RULE}", "skipped")], "Out of scope for the pilot.")
        self.assertEqual(rules[("pack:fastapi", "not-applicable")], "Not used by this team.")
        self.assertEqual(rules[("rule:python/type-public-interfaces", "not-applicable")], "No change in this area.")
        # What passed is not reported: nothing was set aside there.
        self.assertEqual({status for _, status in rules}, {"skipped", "not-applicable"})
        self.assertEqual(len(rules), 6)
        self.assertNotIn((FAILING, "failed"), rules)

    def test_a_failed_rule_comes_with_the_evidence_the_report_gave(self):
        failed = [item for item in self.task("a2")["rules"] if item["status"] == "failed"]
        self.assertEqual([(item["check"], item["reason"]) for item in failed], [(FAILING, "tsc reports 2 errors.")])

    def test_the_packs_the_task_was_not_asked_come_with_the_reason(self):
        concerned = self.task("a1")["not_concerned"]
        self.assertEqual([item["pack"] for item in concerned], ["container-images"])
        self.assertTrue(concerned[0]["reason"])

    def test_a_task_with_no_waiver_has_no_waived_blocker_to_report(self):
        waived = self.task("a1")["waivers"]
        self.assertEqual([(item["blocker"], item["board"], item["until"], item["reason"], item["scope"])
                          for item in waived], [("security:1", "security", days(5), "Pilot only", "Pilot")])
        self.assertEqual(self.task("a4")["waivers"], [])

    def test_the_open_reservations_come_as_the_closing_wrote_them_most_serious_first(self):
        groups = [item["group"] for item in self.task("a1")["reservations"]]
        self.assertEqual(groups[:2], ["Board blocks not lifted", "Blockers waived rather than cleared"])
        self.assertIn("Other rules skipped or failed", groups)
        self.assertLess(groups.index("Board blocks not lifted"), groups.index("Other rules skipped or failed"))
        self.assertEqual(self.task("a4")["reservations"][0]["group"], "Other rules skipped or failed")

    def test_a_committee_that_brought_nothing_is_named_and_one_that_asked_for_changes_is_not(self):
        self.assertEqual(self.task("a1")["committees"],
                         {"convened": sorted(BOARDS, key=BOARDS.index), "without": ["qa"]})
        self.assertEqual(self.task("a4")["committees"]["without"], [])

    def test_the_text_of_a_task_is_short_and_names_the_command_for_the_detail(self):
        result = self.retro("a1")
        self.assertLess(len(result.stdout.splitlines()), 26)
        for words in (f"1 rule skipped: {SKIPPED}", "pack:fastapi", "container-images", "qa",
                      f"security:1 until {days(5)}: Pilot only (scope: Pilot)", "openguildkit task retro a1 --json",
                      "openguildkit task retro --all"):
            self.assertIn(words, result.stdout)

    def test_a_finding_that_comes_back_in_three_tasks_is_counted_and_one_in_two_is_not(self):
        found = {key(item): item for item in self.found()}
        skipped = found[("rule", f"rule:{SKIPPED_RULE}")]
        self.assertEqual((skipped["status"], skipped["count"], skipped["tasks"]), ("skipped", 3, ["a1", "a2", "a3"]))
        self.assertEqual(skipped["reason"], SKIPPED)
        failed = found[("rule", FAILING)]
        self.assertEqual((failed["status"], failed["count"], failed["tasks"]), ("failed", 3, ["a2", "a3", "a4"]))
        pack = found[("rule", "pack:fastapi")]
        self.assertEqual((pack["count"], pack["tasks"], pack["reason"]), (3, ["a1", "a2", "a3"], "Not used by this team."))
        self.assertNotIn(("rule", f"rule:{OTHER_RULE}"), found)
        self.assertEqual({len(item["tasks"]) for item in found.values()}, {3})

    def test_a_finding_in_two_tasks_appears_only_when_the_minimum_goes_down_to_two(self):
        self.assertEqual(self.found("--min", "4"), [])
        two = {key(item): item for item in self.found("--min", "2")}
        self.assertEqual(two[("rule", f"rule:{OTHER_RULE}")]["tasks"], ["a1", "a2"])
        self.assertIn(("rule", f"rule:{SKIPPED_RULE}"), two)

    def test_a_committee_is_counted_where_it_brought_nothing_among_the_tasks_where_it_was_convened(self):
        committee = next(item for item in self.found() if item["kind"] == "committee")
        self.assertEqual((committee["board"], committee["count"], committee["convened_in"], committee["tasks"]),
                         ("qa", 3, 4, ["a1", "a2", "a3"]))

    def test_a_reservation_that_comes_back_is_counted_by_its_wording_whatever_the_dates(self):
        points = {item["point"]: item for item in self.found() if item["kind"] == "reservation"}
        self.assertEqual(set(points), {"blocker security is waived until <date>",
                                       "security said block; blocker security is waived until <date>, not cleared"})
        self.assertEqual({item["count"] for item in points.values()}, {3})
        # Skipped and failed rules are counted by rule; the verdicts are only a record: neither is a reservation.
        self.assertFalse([point for point in points if " is skipped" in point or "said revise" in point])

    def test_the_recurrences_come_rules_first_then_committees_then_reservations(self):
        kinds = [item["kind"] for item in self.found()]
        self.assertEqual(kinds, sorted(kinds, key=("rule", "committee", "reservation").index))

    def test_the_text_of_the_project_gives_one_line_per_finding_with_its_command_and_the_terminal_rule(self):
        text = self.retro("--all").stdout
        self.assertLess(len(text.splitlines()), 40)
        for words in ("4 closed tasks", "at least 3", "--min", f"rule:{SKIPPED_RULE} skipped in 3 tasks (a1, a2, a3)",
                      "rule:postgresql/protect-data-invariants not-applicable in 3 tasks (a1, a2, a3): Schema untouched.",
                      f"openguildkit profile decline rule {SKIPPED_RULE} --by INITIALS --reason",
                      f"{FAILING} failed in 3 tasks (a2, a3, a4)", "qa: no blocker or objection in 3 of the 4 tasks",
                      "terminal", "None of these commands was run", "--by is theirs to fill in",
                      "--reason 'task retro: rule:typescript/strict-type-checking failed in 3 tasks (a2, a3, a4)'"):
            self.assertIn(words, text)

    def test_the_commands_proposed_are_those_a_profile_command_accepts_and_run_as_written(self):
        found = {key(item): item for item in self.found()}
        required = found[("rule", FAILING)]
        decline = found[("rule", "pack:fastapi")]
        self.assertEqual(required["command"], "openguildkit profile add required-rule typescript/strict-type-checking "
                                              "--by INITIALS --reason 'task retro: rule:typescript/strict-type-checking "
                                              "failed in 3 tasks (a2, a3, a4)'")
        self.assertEqual(decline["command"], "openguildkit profile decline python-fastapi-postgresql --by INITIALS --reason "
                                             f"'task retro: pack:fastapi not-applicable in 3 tasks (a1, a2, a3): "
                                             f"{decline['reason']}'")
        self.assertIn("api-design", decline["also_drops"])
        for item in (required, decline):
            self.assertFalse(item["needs_terminal"])
        # One rule set aside in three tasks is declined alone, at a terminal (RFC #447).
        single = found[("rule", f"rule:{SKIPPED_RULE}")]
        self.assertEqual(single["command"], f"openguildkit profile decline rule {SKIPPED_RULE} --by INITIALS --reason "
                                            f"'task retro: rule:{SKIPPED_RULE} skipped in 3 tasks (a1, a2, a3): "
                                            f"{SKIPPED}'")
        self.assertTrue(single["needs_terminal"])
        # No profile command adds a committee's silence to the profile or settles a reservation.
        self.assertIsNone(next(item for item in found.values() if item["kind"] == "committee")["command"])
        self.assertTrue(all(item["command"] is None for item in found.values() if item["kind"] == "reservation"))
        for item in (required, decline, single):
            with self.subTest(item["command"]):
                copy_root = self.root.parent / f"copy-{item['check'].replace(':', '-').replace('/', '-')}"
                shutil.copytree(self.root, copy_root)
                words = [{"NAME": "CM"}.get(word, word) for word in shlex.split(item["command"])]
                self.assertEqual(words[0], "openguildkit")
                typed = SKIPPED_RULE if item is single else None
                result = cli(copy_root, *words[1:], typed=typed)
                self.assertIn("Profile changed", result.stdout)
                # The profile history keeps the reason, so the change stays linked to the tasks behind it.
                history = json.loads((copy_root / ".openguildkit" / "project.json").read_text())["changes"]
                self.assertEqual(history[-1]["reason"], item["proposed_reason"])

    def test_a_task_known_only_by_its_exported_record_gives_the_same_rules_waivers_and_reservations(self):
        before = self.task("a1")
        cli(self.root, "task", "export", "a1")
        (self.root / ".openguildkit" / "tasks" / "a1.json").unlink()
        after = self.task("a1")
        self.assertEqual(after["source"], "exported record")
        for field in ("not_concerned", "waivers", "reservations"):
            self.assertEqual(after[field], before[field], field)
        as_pairs = lambda task: [(item["check"], item["status"]) for item in task["rules"]]
        self.assertEqual(as_pairs(after), as_pairs(before))
        self.assertIsNone(after["committees"])
        self.assertTrue(after["not_recorded"])
        self.assertIn("not in the exported record", self.retro("a1").stdout)

    def test_the_project_counts_a_task_known_only_by_its_record_for_what_the_record_holds(self):
        cli(self.root, "task", "export", "a1")
        (self.root / ".openguildkit" / "tasks" / "a1.json").unlink()
        summary = json.loads(self.retro("--all", "--json", "--min", "2").stdout)
        self.assertEqual(summary["tasks"], {"read": 4, "from_task_records": 3, "from_exported_records": 1})
        rules = {key(item): item for item in summary["recurrences"]}
        self.assertEqual(rules[("rule", f"rule:{SKIPPED_RULE}")]["tasks"], ["a1", "a2", "a3"])
        committee = rules[("committee", "qa")]
        self.assertEqual((committee["count"], committee["convened_in"], committee["tasks"]), (2, 3, ["a2", "a3"]))

    def test_an_exported_record_that_no_longer_matches_its_digest_is_left_out_and_counted(self):
        cli(self.root, "task", "export", "a1")
        (self.root / ".openguildkit" / "tasks" / "a1.json").unlink()
        path = self.root / ".openguildkit" / "decisions" / "a1.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["brief"] = "Edited by hand."
        path.write_text(json.dumps(record), encoding="utf-8")
        summary = json.loads(self.retro("--all", "--json").stdout)
        self.assertEqual(summary["tasks"]["read"], 3)
        self.assertEqual(summary["ignored"]["exported_records_not_holding"], 1)
        self.assertIn("1 exported record does not match its digest", self.retro("--all").stdout)

    def test_a_task_record_that_cannot_be_read_is_left_out_and_counted(self):
        (self.root / ".openguildkit" / "tasks" / "a4.json").write_text("{not json", encoding="utf-8")
        summary = json.loads(self.retro("--all", "--json").stdout)
        self.assertEqual((summary["tasks"]["read"], summary["ignored"]["unreadable_task_records"]), (3, 1))
        self.assertIn("1 task record unreadable", self.retro("--all").stdout)


class DraftRulesTests(RetroCase):
    """task retro --all --draft-rules FOLDER writes a project pack in draft and nothing else (RFC #447)."""

    builder = build_a

    def test_the_draft_is_written_only_in_the_folder_given_and_is_not_active(self):
        before = fingerprint(self.root)
        result = self.retro("--all", "--draft-rules", "drafts")
        files = list((self.root / "drafts").glob("retro-draft-*.json"))
        self.assertEqual(len(files), 1)
        written = files[0].relative_to(self.root).as_posix()
        self.assertIn(f"Draft rule pack written: {written}", result.stdout)
        self.assertIn("not active", result.stdout)
        self.assertIn("It writes only the draft named below.", result.stdout)
        self.assertNotIn("It writes nothing", result.stdout)
        self.assertIn(".openguildkit/catalog/packs/", result.stdout)
        self.assertEqual([entry for entry in fingerprint(self.root) if not entry[0].startswith("drafts")], before)
        pack = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(len(pack["rules"]), 2)
        self.assertNotIn(pack["id"], json.loads((self.root / ".openguildkit" / "project.json").read_text())["packs"])
        for name in NAMES:
            self.assertNotIn(name, files[0].read_text(encoding="utf-8"))
        again = cli(self.root, "task", "retro", "--all", "--draft-rules", "drafts", code=1).stderr
        self.assertIn("already exists", again)

    def test_the_json_names_the_draft_and_the_catalog_reads_it_but_no_profile_uses_it_unreviewed(self):
        # OGK-PROJECT-023
        summary = json.loads(self.retro("--all", "--json", "--draft-rules", "drafts").stdout)
        draft = summary["draft"]
        self.assertEqual((draft["rules"], draft["path"]), (2, f"drafts/{draft['pack']}.json"))
        packs = self.root / ".openguildkit" / "catalog" / "packs"
        packs.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.root / draft["path"], packs)
        self.assertIn(draft["pack"], json.loads(cli(self.root, "catalog", "--json").stdout)["packs"])
        error = cli(self.root, "profile", "add", "pack", draft["pack"], "--by", "CM", "--reason", "x", code=1).stderr
        self.assertIn("draft written by task retro", error)

    def test_the_draft_goes_outside_the_state_folder_and_only_with_all(self):
        # OGK-TASK-077
        error = cli(self.root, "task", "retro", "--all", "--draft-rules", ".openguildkit/catalog/packs", code=1).stderr
        self.assertIn(".openguildkit/", error)
        error = cli(self.root, "task", "retro", "a1", "--draft-rules", "drafts", code=1).stderr
        self.assertIn("--all", error)
        self.assertFalse((self.root / "drafts").exists())

    def test_nothing_that_comes_back_as_a_reservation_writes_no_draft(self):
        result = self.retro("--all", "--min", "4", "--draft-rules", "drafts")
        self.assertIn("No draft written", result.stdout)
        self.assertFalse((self.root / "drafts").exists())


class CheckCommandTests(RetroCase):
    builder = build_c

    def test_a_check_command_that_could_not_run_in_three_tasks_comes_with_the_command_to_remove_it(self):
        found = {key(item): item for item in self.found()}
        stuck = next(item for item in found.values() if item["kind"] == "reservation")
        self.assertEqual((stuck["count"], stuck["tasks"], stuck["check_command"]), (3, ["c1", "c2", "c3"], READY_COMMAND))
        self.assertEqual(stuck["point"], f"`{READY_COMMAND}` could not run: The sandbox has no network for the tests")
        self.assertEqual(shlex.split(stuck["command"]), ["openguildkit", "profile", "remove", "check", READY_COMMAND,
                                                         "--by", "INITIALS", "--reason", stuck["proposed_reason"]])
        # The reason is cut to MAX_REASON characters, and READY_COMMAND holds the interpreter's path, which a virtual
        # environment (as under coverage) makes long: compare what fits before the tasks.
        expected = f"task retro: `{READY_COMMAND}` could not run"
        room = MAX_REASON - len(" in 3 tasks (c1, c2, c3)")
        self.assertTrue(stuck["proposed_reason"].startswith(expected[:room - 3]), stuck["proposed_reason"])
        self.assertIn("in 3 tasks (c1, c2, c3)", stuck["proposed_reason"])
        self.assertTrue(stuck["needs_terminal"])
        self.assertEqual([item for item in self.found("--min", "4") if item["kind"] == "reservation"], [])
        printed = streams(self.retro("--all")) + streams(self.retro("c1"))
        self.assertNotIn(DECLARER, printed)

    def test_the_command_to_remove_a_check_is_the_persons_decision_at_a_terminal(self):
        stuck = next(item for item in self.found() if item["kind"] == "reservation")
        words = [{"NAME": "CM"}.get(word, word) for word in shlex.split(stuck["command"])]
        refused = cli(self.root, *words[1:], code=1)
        self.assertIn("weakens a protection", refused.stderr)
        self.assertIn(READY_COMMAND, json.loads((self.root / ".openguildkit" / "project.json").read_text())["checks"])
        done = cli(self.root, *words[1:], typed=READY_COMMAND)
        self.assertIn("Profile changed", done.stdout)
        self.assertEqual(json.loads((self.root / ".openguildkit" / "project.json").read_text())["checks"], [])

    def test_a_committee_that_brought_nothing_in_every_task_can_leave_the_boards_the_profile_lists(self):
        qa = next(item for item in self.found("--min", "4") if item["kind"] == "committee")
        self.assertEqual((qa["board"], qa["count"], qa["convened_in"]), ("qa", 4, 4))
        self.assertEqual(qa["command"], "openguildkit profile remove board qa --by INITIALS --reason "
                                        "'task retro: qa brought no blocker or objection in 4 tasks (c1, c2, c3, c4)'")
        self.assertFalse(qa["needs_terminal"])
        result = cli(self.root, "profile", "remove", "board", "qa", "--by", "CM", "--reason", "Retrospective")
        self.assertIn("Profile changed", result.stdout)

    def test_a_task_that_ran_every_check_and_applied_every_rule_has_nothing_to_report(self):
        task = self.task("c4")
        self.assertEqual((task["rules"], task["waivers"], task["reservations"], task["not_concerned"]), ([], [], [], []))
        self.assertIn("no rule set aside", self.retro("c4").stdout)


class ReadOnlyTests(RetroCase):
    builder = build_a

    COMMANDS = (("a1",), ("a1", "--json"), ("a4",), ("--all",), ("--all", "--json"), ("--all", "--min", "2"),
                ("--all", "--min", "9", "--json"))

    def test_the_project_is_the_same_after_every_form_of_the_command(self):
        before = fingerprint(self.root)
        for arguments in self.COMMANDS:
            with self.subTest(arguments):
                self.retro(*arguments)
                self.assertEqual(fingerprint(self.root), before)
        self.retro("missing", code=1)
        self.retro("--min", "0", "--all", code=1)
        self.assertEqual(fingerprint(self.root), before)

    def test_no_process_is_started_and_no_connection_is_made_not_even_to_refuse(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("the retrospective started a process or opened a connection")

        cli(self.root, "task", "new", "Work not started", "--id", "draft")
        with patch("subprocess.run", forbidden), patch("subprocess.Popen", forbidden), patch("os.system", forbidden), \
                patch("socket.socket.connect", forbidden), patch("socket.create_connection", forbidden):
            for arguments in self.COMMANDS:
                with self.subTest(arguments):
                    self.retro(*arguments)
            for arguments in (("missing",), ("draft",), ("--all", "--min", "0")):
                with self.subTest(arguments):
                    self.retro(*arguments, code=1)

    def test_no_name_of_a_person_is_printed_though_task_list_prints_the_approver_and_the_closer(self):
        listing = cli(self.root, "task", "list").stdout
        self.assertIn(APPROVER, listing)
        self.assertIn(CLOSER, listing)
        for arguments in self.COMMANDS:
            printed = streams(self.retro(*arguments))
            for name in NAMES:
                with self.subTest(arguments=arguments, name=name):
                    self.assertNotIn(name, printed)
        cli(self.root, "task", "export", "a2")
        (self.root / ".openguildkit" / "tasks" / "a2.json").unlink()
        for arguments in self.COMMANDS:
            printed = streams(self.retro(*arguments))
            for name in NAMES:
                with self.subTest(msg="record", arguments=arguments, name=name):
                    self.assertNotIn(name, printed)

    def test_two_runs_print_the_same_bytes_and_the_order_of_the_files_changes_nothing(self):
        for arguments in self.COMMANDS:
            with self.subTest(arguments):
                first, second = self.retro(*arguments), self.retro(*arguments)
                self.assertEqual((first.stdout, first.stderr), (second.stdout, second.stderr))
        original = Path.glob

        def reversed_glob(path, pattern, *args, **kwargs):
            return iter(sorted(original(path, pattern, *args, **kwargs), reverse=True))

        for arguments in (("--all",), ("--all", "--json"), ("--all", "--min", "2", "--json")):
            expected = self.retro(*arguments)
            with self.subTest(msg="reversed", arguments=arguments), patch.object(Path, "glob", reversed_glob):
                again = self.retro(*arguments)
            self.assertEqual((again.stdout, again.stderr), (expected.stdout, expected.stderr))

    def test_two_processes_with_other_hash_seeds_print_the_same_bytes(self):
        printed = []
        for seed in ("1", "2", "3"):
            result = run_cli(self.root, "task", "retro", "--all", "--json", subprocess_mode=True,
                             env={"PYTHONHASHSEED": seed})
            printed.append(result.stdout)
        self.assertEqual(len(set(printed)), 1)
        self.assertTrue(json.loads(printed[0])["recurrences"])


class RefusalTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ogk-retro-refusal-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        initialized(self.root)

    def test_an_unknown_task_is_refused_with_the_command_that_lists_the_tasks(self):
        cli(self.root, "task", "new", "Show the status", "--id", "status")
        error = cli(self.root, "task", "retro", "statuz", code=1).stderr
        self.assertTrue(error.startswith("OpenGuildKit [OGK-TASK-021]: Unknown task: statuz."))
        self.assertIn("Did you mean status?", error)
        self.assertIn("openguildkit task list", error)

    def test_a_task_not_closed_yet_is_refused_with_its_status_and_the_command_to_type(self):
        # OGK-TASK-079
        cli(self.root, "task", "new", "Show the status", "--id", "status")
        error = cli(self.root, "task", "retro", "status", code=1).stderr
        self.assertIn("only a closed task has a retrospective", error.lower())
        self.assertIn("Task status is a draft, not consulted yet", error)
        self.assertIn("openguildkit task consult status --answers FILE", error)
        cli(self.root, "task", "new", "More work", "--id", "second")
        cli(self.root, "task", "consult", "second", "--answers", EXAMPLE / "answers.json")
        error = cli(self.root, "task", "retro", "second", code=1).stderr
        self.assertIn("openguildkit task review second --summary TEXT", error)

    def test_an_exported_record_written_before_the_task_was_completed_is_refused_with_the_command(self):
        # OGK-TASK-074
        close_task(self.root, {"id": "done-one"})
        cli(self.root, "task", "export", "done-one")
        path = self.root / ".openguildkit" / "decisions" / "done-one.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update(completed=False, status="approved")
        record.pop("completed_at", None)
        record["record_sha256"] = export_digest(record)
        write_json(path, record)
        (self.root / ".openguildkit" / "tasks" / "done-one.json").unlink()
        error = cli(self.root, "task", "retro", "done-one", code=1).stderr
        self.assertIn("exported", error)
        self.assertIn("openguildkit task list --decisions", error)

    def test_a_project_with_no_closed_task_says_there_is_nothing_to_count(self):
        cli(self.root, "task", "new", "Show the status", "--id", "status")
        result = cli(self.root, "task", "retro", "--all")
        self.assertIn("No closed task to count", result.stdout)
        self.assertIn("openguildkit task list", result.stdout)
        self.assertEqual(json.loads(cli(self.root, "task", "retro", "--all", "--json").stdout)["tasks"]["read"], 0)

    def test_the_command_needs_a_task_or_all_and_a_minimum_of_one(self):
        for arguments, words in ((("--json",), "task retro ID"), (("a", "--all"), "--all"),
                                 (("--all", "--min", "0"), "--min"), (("a", "--min", "2"), "--min")):
            with self.subTest(arguments):
                error = cli(self.root, "task", "retro", *arguments, code=1).stderr
                self.assertRegex(error, r"^OpenGuildKit \[OGK-TASK-07[568]\]: ")  # OGK-TASK-075, OGK-TASK-076, OGK-TASK-078
                self.assertIn(words, error)

    def test_a_project_written_by_an_earlier_release_has_no_closed_task_and_is_left_as_it_was(self):
        bundle = json.loads((REPO / "tests" / "fixtures" / "upgrade" / "v0.16.1.json").read_text(encoding="utf-8"))
        old = self.root.parent / "old"
        for name, content in bundle["files"].items():
            (old / name).parent.mkdir(parents=True, exist_ok=True)
            (old / name).write_bytes(content.encode("utf-8"))
        before = fingerprint(old)
        self.assertIn("No closed task to count", cli(old, "task", "retro", "--all").stdout)
        error = cli(old, "task", "retro", bundle["approved_task"], code=1).stderr
        self.assertIn("only a closed task has a retrospective", error.lower())
        self.assertEqual(fingerprint(old), before)


if __name__ == "__main__":
    unittest.main()
