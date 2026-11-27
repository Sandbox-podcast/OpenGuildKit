import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.results import validate_result
from openguildkit.storage import write_json

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


class ResultCase(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout.strip()

    def reviewed(self, exit_code=0, answers=None, git_project=False, verdict=None, **extra):
        """The example task with its review recorded, before the person decides; verdict gives every board one."""
        command = f'"{sys.executable}" -c "import sys; print(\'checked\'); sys.exit({exit_code})"'
        profile = {"personal_data": "no", "name": "Portal", "stack": ["Python"], "packs": ["python"], "checks": [command], **extra}
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        if git_project:
            (self.root / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
            self.git("init", "-q", "-b", "main")
            self.git("add", ".")
            self.git("commit", "-qm", "Initial project")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        if answers:
            write_json(self.root / "answers.json", {**json.loads((EXAMPLE / "answers.json").read_text()), **answers})
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json" if answers else EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        for entry in review["boards"] if verdict else []:
            entry["challenge"].update(verdict=verdict, blockers=[])
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")

    def approved(self, exit_code=0, answers=None, git_project=False, **extra):
        self.reviewed(exit_code, answers, git_project, **extra)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")

    def rule_outcomes(self):
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        return [
            {"check": check["id"], "status": "not-applicable", "reason": "No change in this area.", "owner": "Camille"}
            for check in checks if check["kind"] == "rule"
        ]

    def record(self):
        return json.loads(self.run_cli("task", "show", TASK)[0])

    def report(self, *checks, criteria=(), code=0):
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": list(criteria), "checks": list(checks)})
        return self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=code)


class ResultCredentialTests(ResultCase):
    """What a result cites is recorded and published without the credentials in it (issue #390)."""

    PASSWORD = "hunter" + "2pass"
    TOKEN = "abcdef1234567890" + "SECRET"
    KEY = "AK" + "IA" + "IOSFODNN7EXAMPLE"
    SECRETS = (PASSWORD, TOKEN, KEY)

    def result(self, **fields):
        return {"pull_request": f"https://user:{self.PASSWORD}@github.com/example/portal/pull/7",
                "criteria": [{"criterion": f"Calls https://api.example.org/v1?token={self.TOKEN} ok with {self.KEY}",
                              "status": "met", "evidence": "tests/test_access.py"}],
                "checks": self.rule_outcomes(), **fields}

    def assertNoSecret(self, folder):
        for path in sorted(item for item in folder.rglob("*") if item.is_file()):
            for secret in self.SECRETS:
                self.assertNotIn(secret, path.read_text(encoding="utf-8"), path.name)

    def test_a_result_is_recorded_exported_and_published_without_the_credentials_it_cites(self):
        self.approved()
        self.run_cli("task", "verify", TASK)
        write_json(self.root / "result.json", self.result())
        _, warning = self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertIn("replaced a possible credential in the task result with a placeholder", warning)
        for secret in self.SECRETS:
            self.assertNotIn(secret, warning)
        self.run_cli("task", "complete", TASK)
        record = self.record()["result"]
        self.assertEqual(record["pull_request"], "https://user:[password]@github.com/example/portal/pull/7")
        self.assertEqual(record["criteria"][0]["criterion"], "Calls https://api.example.org/v1?token=[credential] ok with [credential]")
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.0.0")
        self.run_cli("task", "export", TASK)
        self.assertNoSecret(self.root / "docs-site")
        self.assertNoSecret(self.root / ".openguildkit" / "decisions")

    def test_the_evidence_and_the_reasons_of_a_result_lose_their_credentials_too(self):
        self.approved()
        rules = self.rule_outcomes()
        rules[0].update(reason=f"Out of scope, see password={self.PASSWORD}", owner="Camille")
        self.run_cli("task", "verify", TASK)
        write_json(self.root / "result.json", self.result(checks=rules, revision=f"abc1234 {self.KEY}"))
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        record = json.dumps(self.record())
        for secret in self.SECRETS:
            self.assertNotIn(secret, record)
        self.assertIn("password=[password]", record)

    def test_personal_data_in_a_result_is_recorded_with_a_warning_that_does_not_repeat_it(self):
        self.approved()
        self.run_cli("task", "verify", TASK)
        criterion = "Mails ops@example.test, +33 6 12 34 56 78 and FR76 3000 6000 0112 3456 7890 189 are masked."
        write_json(self.root / "result.json", self.result(criteria=[
            {"criterion": criterion, "status": "met", "evidence": "tests/test_access.py"}]))
        _, warning = self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertIn("the task result contains an email address and a phone number and a bank account number", warning)
        for value in ("ops@example.test", "56 78", "3000 6000"):
            self.assertNotIn(value, warning)
        self.assertEqual(self.record()["result"]["criteria"][0]["criterion"], criterion)


class ResultTests(ResultCase):
    def test_a_passing_mandatory_check_with_evidence_lets_the_task_finish(self):
        self.approved()
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertIn("command:1: passed", output)
        record = json.loads(self.run_cli("task", "show", TASK)[0])
        log = self.root / record["result"]["checks"][0]["evidence"]
        self.assertIn("checked", log.read_text(encoding="utf-8"))
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("is not reported", error)
        write_json(self.root / "result.json", {
            "pull_request": "https://github.com/example/portal/pull/7",
            "criteria": [{"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/test_access.py"}],
            "checks": self.rule_outcomes(),
        })
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")
        record = json.loads(self.run_cli("task", "show", TASK)[0])
        self.assertEqual(record["status"], "done")
        # The handoff of a closed task speaks of its checks in the past.
        handoff = self.run_cli("task", "handoff", TASK)[0]
        self.assertIn("## Checks task verify ran", handoff)
        self.assertNotIn("must pass before the task is done", handoff)
        self.assertEqual(record["result"]["pull_request"], "https://github.com/example/portal/pull/7")

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_command_journal_is_hashed_and_a_later_edit_blocks_completion(self):
        self.approved(git_project=True)
        self.run_cli("task", "verify", TASK)
        check = next(item for item in self.record()["result"]["checks"] if item["check"] == "command:1")
        log = self.root / check["evidence"]
        self.assertEqual(check["sha256"], hashlib.sha256(log.read_bytes()).hexdigest())
        self.assertIs(check["journal"], True)
        self.assertEqual(check["revision"], {"commit": self.git("rev-parse", "HEAD"), "clean": True})
        log.write_text(log.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("command:1: the journal", error)
        self.assertIn("no longer matches the recorded sha256", error)

    def test_a_check_recorded_before_journal_hashes_still_completes(self):
        self.approved()
        self.run_cli("task", "verify", TASK)
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        task = json.loads(path.read_text(encoding="utf-8"))
        log = None
        for item in task["result"]["checks"]:
            item.pop("sha256", None)
            item.pop("journal", None)
            if isinstance(item.get("revision"), dict):
                item["revision"] = item["revision"]["commit"]
            if item.get("check") == "command:1":
                log = self.root / item["evidence"]
        write_json(path, task)
        log.unlink()
        write_json(self.root / "result.json", {
            "pull_request": "https://github.com/example/portal/pull/7",
            "criteria": [{"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/test_access.py"}],
            "checks": self.rule_outcomes(),
        })
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")

    def test_a_decision_records_its_outcome_without_code_checks_or_a_revision(self):
        outcome = "The project owner selects a format for request history."
        self.approved(exit_code=1, answers={"kind": "decision", "outcome": outcome})
        preview, error = self.run_cli("task", "result", TASK, "--template")
        template = json.loads(preview)
        self.assertEqual(template["criteria"], [{"criterion": outcome, "status": "", "evidence": ""}])
        self.assertEqual(set(template), {"criteria", "not_concerned"})
        # Nothing is dropped silently: the rules and the check command are listed as not concerned, with the reason.
        self.assertIn("command:1", [entry.get("check") for entry in template["not_concerned"]])
        self.assertTrue(all("decision task" in entry["reason"] for entry in template["not_concerned"]))
        self.assertEqual(error, "")
        listed = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        self.assertEqual([check["id"] for check in listed if check["concerned"]], [])
        self.assertNotIn("command:1", self.run_cli("task", "verify", TASK)[0])
        report = self.root / "result.json"
        write_json(report, {"criteria": [{"criterion": outcome, "status": "met", "evidence": "Approved decision record."}]})
        self.run_cli("task", "result", TASK, "--file", report)
        self.assertIn(f"--follows {TASK}", self.run_cli("task", "complete", TASK)[0])
        self.assertNotIn("revision", self.record()["result"])
        self.assertEqual(self.record()["status"], "done")

    @unittest.skipUnless(shutil.which("git"), "needs git")
    def test_a_decision_with_project_file_changes_needs_a_delivery_reference(self):
        self.approved(answers={"kind": "decision"}, git_project=True)
        self.assertNotIn("revision", json.loads(self.run_cli("task", "result", TASK, "--template")[0]))
        self.run_cli("task", "export", TASK)
        self.git("add", ".openguildkit/decisions")
        self.assertNotIn("revision", json.loads(self.run_cli("task", "result", TASK, "--template")[0]))
        (self.root / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
        preview, error = self.run_cli("task", "result", TASK, "--template")
        self.assertIn("revision", json.loads(preview))
        self.assertIn("Project files changed since the approved revision (app.py)", error)
        report = self.root / "result.json"
        write_json(report, {"criteria": []})
        self.assertIn("Name the delivered revision", self.run_cli("task", "result", TASK, "--file", report, code=1)[1])
        self.assertIn("Name the delivered revision", self.run_cli("task", "complete", TASK, code=1)[1])
        self.git("add", "app.py")
        self.git("commit", "-qm", "Change project")
        write_json(report, {"revision": self.git("rev-parse", "HEAD"), "criteria": []})
        self.run_cli("task", "result", TASK, "--file", report)
        self.assertIn(f"--follows {TASK}", self.run_cli("task", "complete", TASK)[0])

    def test_a_failed_or_unproven_mandatory_check_blocks_completion(self):
        self.approved(exit_code=1, required_rules=["python"])
        output, _ = self.run_cli("task", "verify", TASK, code=1)
        self.assertIn(".openguildkit/tasks/", output)
        self.assertIn("command:1 is mandatory and failed", output)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": self.rule_outcomes()})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("command:1 is mandatory and failed", error)
        self.assertIn("rule:python/", error)
        self.assertIn("checked", error)

    def test_a_person_can_record_an_environment_reservation_for_a_project_command(self):
        self.approved(exit_code=1)
        options = ("--cannot-run", "command:1", "--by", "Camille", "--reason", "Dependencies unavailable offline")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("task", "verify", TASK, *options, code=1)
        self.assertIn("interactive terminal", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            _, error = self.run_cli("task", "verify", TASK, *options, "--chaosfolk", "unused.json", code=1)
            self.assertIn("without --chaosfolk", error)
            output, _ = self.run_cli("task", "verify", TASK, *options)
        self.assertIn("command:1: skipped", output)
        self.assertIn("Dependencies unavailable offline", output)
        self.report(*self.rule_outcomes())
        output, _ = self.run_cli("task", "complete", TASK)
        self.assertIn("done", output)
        self.assertIn("Dependencies unavailable offline", output)

    def test_task_verify_explains_how_to_add_project_commands(self):
        self.approved(checks=[])
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertIn("No project check command is configured", output)
        self.assertIn('openguildkit profile add check "COMMAND"', output)

    def test_skipped_checks_need_a_reason_and_an_owner(self):
        self.approved()
        rule = self.rule_outcomes()[0]["check"]
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [],
                                               "checks": [{"check": rule, "status": "skipped"}]})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("reason", error)
        write_json(self.root / "result.json", {"criteria": [], "checks": []})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("revision or pull request", error)


    def test_only_task_verify_records_a_command_check(self):
        self.approved(exit_code=1)
        self.assertIn("command:1: failed", self.run_cli("task", "verify", TASK, code=1)[0])
        _, error = self.report({"check": "command:1", "status": "passed", "evidence": "trust me"}, code=1)
        self.assertIn("task verify", error)
        checks = {item["check"]: item for item in self.record()["result"]["checks"]}
        self.assertEqual(checks["command:1"]["status"], "failed")

    def test_a_check_with_a_non_zero_exit_code_cannot_pass(self):
        self.approved()
        rule = self.rule_outcomes()[0]["check"]
        _, error = self.report({"check": rule, "status": "passed", "evidence": "ci.log", "exit_code": 1}, code=1)
        self.assertIn("exit_code", error)
        task, profile = self.record(), json.loads((self.root / ".openguildkit" / "project.json").read_text())
        with self.assertRaisesRegex(ValueError, "exit_code"):
            validate_result(task, profile, {"revision": "abc1234", "checks": [
                {"check": "command:1", "status": "passed", "evidence": "log", "exit_code": 2}]}, source="verify")

    def test_chaosfolk_checks_come_only_from_a_replay(self):
        self.approved()
        _, error = self.report({"check": "chaosfolk:anything", "status": "passed", "evidence": "trust me"}, code=1)
        self.assertIn("task verify --chaosfolk", error)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": [],
                                               "run": {"tool": "chaosfolk", "outcomes": {}}})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)

    def test_a_task_with_an_expected_outcome_needs_a_criterion(self):
        self.approved(answers={"outcome": "Customers see the status of their own requests."})
        self.run_cli("task", "verify", TASK)
        _, error = self.report(*self.rule_outcomes(), code=1)
        self.assertIn("criterion", error)
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("acceptance criterion", error)
        self.report(*self.rule_outcomes(), criteria=[
            {"criterion": "Customers see the status of their own requests.", "status": "met", "evidence": "tests/test_status.py"}])
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")

    def test_results_refuse_a_record_that_no_longer_matches_its_approval(self):
        self.approved(exit_code=1)
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["consultation"]["scope"]["checks"] = ["true"]
        record["consultation"]["scope"]["packs"] = []
        write_json(path, record)
        for action in (("verify",), ("complete",)):
            _, error = self.run_cli("task", *action, TASK, code=1)
            self.assertIn("no longer matches what was approved", error)
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": []})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("no longer matches what was approved", error)

    def test_results_refuse_a_task_whose_rules_changed(self):
        self.approved()
        path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        profile["packs"].append("web-accessibility")
        write_json(path, profile)
        self.run_cli("sync")
        _, error = self.run_cli("task", "verify", TASK, code=1)
        self.assertIn("recorded under earlier rules (pack web-accessibility added)", error)
        self.assertIn("The approval for request-status was recorded under earlier rules", error)
        self.assertIn("--follows request-status", error)

    def test_the_result_template_lists_the_criteria_and_every_expected_check(self):
        outcome = "Customers see the status of their own requests."
        self.approved(answers={"outcome": outcome})
        output, notes = self.run_cli("task", "result", TASK, "--template")
        template = json.loads(output)
        self.assertEqual(notes, "")
        self.assertEqual(template["criteria"][0]["criterion"], outcome)
        listed = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        expected = [item["id"] for item in listed if item["kind"] == "rule" and item["concerned"]]
        # A pack whose rules can be answered together is one entry of packs; the others are listed rule by rule.
        in_packs = [rule for pack in template["packs"] for rule in pack["rules"]]
        self.assertTrue(in_packs)
        self.assertEqual(sorted([item["check"] for item in template["checks"]] + in_packs), sorted(expected))
        self.assertLess(len(template["checks"]) + len(template["packs"]), len(expected))
        self.assertEqual([item["check"] for item in template["recorded_by_verify"]], ["command:1"])
        self.run_cli("task", "verify", TASK)
        template["revision"] = "abc1234"
        template["criteria"][0].update(status="met", evidence="tests/test_status.py")
        for item in template["checks"]:
            item.update(status="not-applicable", reason="No change in this area.", owner="Camille")
        for item in template["packs"]:
            item.update(status="passed", evidence="tests/test_status.py")
        write_json(self.root / "filled.json", template)
        self.run_cli("task", "result", TASK, "--file", self.root / "filled.json")
        self.assertEqual(self.run_cli("task", "complete", TASK)[0].strip(), "done")

    def test_verify_before_any_result_counts_the_rules_to_report_instead_of_listing_them(self):
        self.approved()
        output, _ = self.run_cli("task", "verify", TASK)
        listed = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        rules = [item for item in listed if item["kind"] in ("rule", "evidence") and item["concerned"]]
        self.assertIn(f"- {len(rules)} rule(s) and named evidence to report: openguildkit task result {TASK} "
                      "--template lists them", output)
        self.assertNotIn("is not reported", output)
        self.assertIn(f"{len(rules)} point(s) before the task can be done.", output)
        # Issue 291: the README's order runs task verify before task result; its output stays short.
        self.assertLess(len(output.encode("utf-8")), 1500, output)
        # Once a report answered some rules, task verify lists the ones still missing, one by one.
        self.report(self.rule_outcomes()[0])
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertIn("is not reported", output)
        self.assertNotIn("to report: openguildkit task result", output)

    def test_one_evidence_cited_for_the_passed_rules_of_several_packs_closes_with_reservations(self):
        self.approved()
        self.run_cli("task", "verify", TASK)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        rules = [item for item in checks if item["kind"] == "rule" and item["concerned"]]
        packs = {item["pack"] for item in rules}
        self.assertGreaterEqual(len(packs), 3)
        passed = [{"check": item["id"], "status": "passed", "evidence": "src/total.test.ts"} for item in rules]
        criteria = [{"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/x.py"}]
        output, _ = self.report(*passed, criteria=criteria)
        warning = (f"The same evidence src/total.test.ts is cited for {len(rules)} passed rules of {len(packs)} packs "
                   f"({', '.join(sorted(packs))})")
        self.assertIn(f"Warning: {warning}", output)
        output, notes = self.run_cli("task", "complete", TASK)
        self.assertEqual(output.splitlines()[0], "done-with-reservations")
        self.assertIn("Warnings on the result:", output)
        self.assertIn(warning, output)
        exported = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertTrue(any(warning in item for item in exported["result"]["warnings"]))

    def test_one_evidence_per_pack_or_for_two_packs_is_not_flagged(self):
        self.approved()
        self.run_cli("task", "verify", TASK)
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        rules = [item for item in checks if item["kind"] == "rule" and item["concerned"]]
        two = sorted({item["pack"] for item in rules})[:2]
        answers = [{"check": item["id"], "status": "passed", "evidence": f"tests/test_{item['pack']}.py"}
                   if item["pack"] not in two else
                   {"check": item["id"], "status": "passed", "evidence": "tests/test_shared.py"} for item in rules]
        output, _ = self.report(*answers, criteria=[
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/x.py"}])
        self.assertNotIn("The same evidence", output)

    def test_without_objection_deliberate_says_to_skip_respond(self):
        self.reviewed(verdict="revise")
        output, error = self.run_cli("task", "deliberate", TASK)
        self.assertEqual(json.loads(output)["objections"], [])
        self.assertIn(f"there is nothing to deliberate, so skip task respond. Next: openguildkit task challenge {TASK}",
                      error)
        write_json(self.root / "deliberation.json", json.loads(output)["template"])
        _, error = self.run_cli("task", "respond", TASK, "--file", self.root / "deliberation.json", code=1)
        self.assertIn(f"skip task respond. Next: openguildkit task challenge {TASK}", error)

    def test_the_result_template_names_the_statuses_of_a_criterion(self):
        self.approved()
        template = json.loads(self.run_cli("task", "result", TASK, "--template")[0])
        self.assertIn("A criterion is met or not-met", template["instructions"])
        template["revision"] = "abc1234"
        template["criteria"][0].update(criterion="Users only see their own requests.", status="passed", evidence="t")
        write_json(self.root / "filled.json", template)
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "filled.json", code=1)
        self.assertIn("met or not-met", error)


GDPR_RECORD = "evidence:gdpr/update-processing-record/processing-record"
GDPR_DPIA = "evidence:gdpr/assess-dpia-need/dpia-decision"


class ProportionateResultTests(ResultCase):
    """The closing asks what concerns the task, waits for evidence from its owner and says what stays open."""

    def gdpr_task(self):
        self.approved(patterns=["gdpr-personal-data"])
        self.run_cli("task", "verify", TASK)

    def answers(self, status="not-applicable", reason="", skip=()):
        """An answer for every asked rule, each with its own reason unless one is given; named evidence is left out."""
        checks = json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
        return [{"check": c["id"], "status": "skipped" if c["id"] in skip else status,
                 "reason": reason or f"Nothing in this change touches {c['id']}.", "owner": "Camille"}
                for c in checks if c["kind"] == "rule" and c["concerned"]]

    def file(self, *checks, packs=(), criteria=None, code=0):
        criteria = criteria if criteria is not None else [
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "tests/test_access.py"}]
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": criteria, "checks": list(checks),
                                               "packs": list(packs)})
        return self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=code)

    def documents(self):
        (self.root / "docs").mkdir(exist_ok=True)
        for name in ("record.md", "dpia.md"):
            (self.root / "docs" / name).write_text("Kept by the data protection officer.", encoding="utf-8")
        return [{"check": GDPR_RECORD, "status": "passed", "evidence": "docs/record.md", "owner": "Dana (DPO)"},
                {"check": GDPR_DPIA, "status": "passed", "evidence": "docs/dpia.md", "owner": "Dana (DPO)"}]

    def test_checks_list_each_evidence_once_under_its_rule_and_what_is_not_asked(self):
        self.gdpr_task()
        listing = self.run_cli("task", "checks", TASK)[0]
        self.assertEqual(listing.count(GDPR_RECORD), 1)
        self.assertIn(f"    {GDPR_RECORD} [passed] not reported", listing)
        self.assertNotIn("[mandatory] not reported: Supply", listing)
        template = json.loads(self.run_cli("task", "result", TASK, "--template")[0])
        entry = next(item for item in template["checks"] if item["check"] == GDPR_RECORD)
        self.assertEqual(entry["requirement"], "passed")
        self.assertIn("data protection officer", entry["owner_role"])
        self.assertIn("the person who decides it", template["instructions"])
        self.assertNotIn("mandatory", json.dumps(template))
        # One word per meaning: the requirement is written with the status the file accepts.
        self.assertNotIn("Supply", json.dumps(template))
        self.assertIn('Only passed is accepted', entry["answer"])
        _, error = self.file({"check": GDPR_RECORD, "status": "supplied", "evidence": "docs/x.md", "owner": "Dana"},
                             code=1)
        self.assertIn(f"{GDPR_RECORD} status is passed, not 'supplied'", error)

    def test_a_result_that_lacks_only_named_evidence_is_recorded_and_the_task_waits_for_its_owner(self):
        self.gdpr_task()
        handoff = self.run_cli("task", "handoff", TASK)[0]
        self.assertLess(handoff.index("## Evidence the closing will ask for"), handoff.index("## Human approval"))
        self.assertIn("data protection officer", handoff)
        self.assertIn("do not write them yourself", handoff)
        output, _ = self.file(*self.answers())
        self.assertIn(f"Waiting for {GDPR_RECORD}: Record of processing activities, provided by the data protection", output)
        self.assertEqual(len(self.record()["result"]["checks"]), len(self.answers()) + 1)
        # The wait is shown next to the status, in task show and in the exported record.
        self.assertEqual(self.record()["status"], "approved")
        self.assertTrue(self.record()["waiting_for"][0].startswith("Record of processing activities"))
        exported = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual(exported["waiting_for"], self.record()["waiting_for"])
        row = json.loads(self.run_cli("task", "list", "--json")[0])[0]
        self.assertEqual(row["status"], "approved")
        self.assertIn("Waiting for evidence: Record of processing activities from the data protection officer", row["next"])
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn(f"{GDPR_RECORD} waits for the data protection officer", error)

        self.run_cli("task", "new", "Update the record of processing.", "--id", "privacy-record", "--follows", TASK)
        _, error = self.run_cli("task", "complete", TASK, "--defer", f"{GDPR_RECORD}=privacy-record", code=1)
        self.assertIn("--by NAME", error)
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("task", "complete", TASK, "--defer", f"{GDPR_RECORD}=privacy-record",
                                    "--defer", f"{GDPR_DPIA}=privacy-record", "--by", "Camille", code=1)
        self.assertIn("interactive terminal", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            output, notes = self.run_cli("task", "complete", TASK, "--defer", f"{GDPR_RECORD}=privacy-record",
                                         "--defer", f"{GDPR_DPIA}=privacy-record", "--by", "Camille")
        self.assertEqual(output.splitlines()[0], "done-with-reservations")
        self.assertIn("Named evidence handed to a follow-up task:", notes)
        self.assertIn(f"  - {GDPR_RECORD} is handed to task privacy-record", notes)
        self.assertEqual(self.record()["status"], "done-with-reservations")

    def test_named_evidence_is_confirmed_by_a_person_and_never_read(self):
        self.gdpr_task()
        record, dpia = self.documents()
        (self.root / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
        output, _ = self.file(*self.answers(), {**record, "evidence": "Dockerfile"}, {**dpia, "evidence": "Dockerfile"},
                              criteria=[{"criterion": "403 for another user's request.", "status": "met",
                                         "evidence": "Read from code only, NOT executed."}])
        self.assertIn("looks like configuration, code or an image", output)
        self.assertIn("The same file is cited for 2 different named evidences", output)
        self.assertIn("says it was not run", output)
        self.assertIn("Criteria met: 0 tied to a check or a test, 1 declared only", output)
        output, _ = self.file(*self.answers(), record, dpia, criteria=[
            {"criterion": "403 for another user's request.", "status": "met", "evidence": "Test run.",
             "verified_by": "command:1"},
            {"criterion": "The list loads.", "status": "met", "evidence": "Tried by hand."}])
        self.assertIn("Criteria met: 1 tied to a check or a test, 1 declared only (The list loads.)", output)
        self.assertNotIn("Warning", output)
        output, notes = self.run_cli("task", "complete", TASK, "--by", "CM", typed=TASK)
        self.assertEqual(output.strip(), "done")
        self.assertIn("did not read the documents. Confirmed by: Dana (DPO)", notes)
        exported = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertIn("did not read", exported["result"]["evidence_note"])
        self.assertEqual(exported["result"]["evidence_supplied"][0]["confirmed_by"], "Dana (DPO)")
        self.assertEqual([item["verified_by"] for item in exported["result"]["criteria"]], ["command:1", "declared only"])

    def test_an_answer_not_recorded_says_that_the_earlier_one_stays_and_the_task_is_not_called_ready(self):
        self.gdpr_task()
        self.file(*self.answers(), *self.documents())
        record, dpia = self.documents()
        output, error = self.file({**record, "evidence": "docs/missing.md"})
        self.assertIn(f"Not recorded: {GDPR_RECORD}: docs/missing.md does not exist in the project. The earlier answer "
                      "stays recorded.", error)
        self.assertNotIn("Ready: run task complete.", output)
        self.assertIn("some answers were not recorded", output)
        checks = {item["check"]: item for item in self.record()["result"]["checks"]}
        self.assertEqual(checks[GDPR_RECORD]["evidence"], "docs/record.md")

    def test_a_criterion_is_tied_only_to_a_known_command_or_an_existing_test(self):
        self.approved()
        for verified, message in (("command:9", "not a check command"), ("tests/test_missing.py", "does not exist")):
            write_json(self.root / "result.json", {"revision": "abc1234", "checks": [], "criteria": [
                {"criterion": "x", "status": "met", "evidence": "y", "verified_by": verified}]})
            _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
            self.assertIn(message, error)

    def test_one_answer_covers_a_pack_but_a_sensitive_pack_needs_the_person(self):
        self.gdpr_task()
        rules = [item for item in self.answers() if not item["check"].startswith("rule:gdpr/")]
        output, _ = self.file(*rules, *self.documents(), packs=[
            {"pack": "gdpr", "status": "not-applicable", "reason": "Not in scope.", "owner": "Camille"}])
        self.assertIn("Pack gdpr was declared not applicable as a whole by Camille, although the task's answers "
                      "select it", output)
        self.assertIn("Ready to close with the person at a terminal", output)
        # An owner written in the file is not a person's confirmation: closing needs them at a terminal.
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("--by NAME", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            output, notes = self.run_cli("task", "complete", TASK, "--by", "Camille")
        self.assertEqual(output.splitlines()[0], "done-with-reservations")
        self.assertIn("  - pack gdpr is declared not applicable as a whole: Not in scope. (Camille) [data protection]",
                      notes)
        exported = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual(exported["status"], "done-with-reservations")
        self.assertTrue(any("Pack gdpr" in warning for warning in exported["result"]["warnings"]))

    def test_a_corrected_result_replaces_the_earlier_pack_answers_and_their_warnings(self):
        self.gdpr_task()
        rules = [item for item in self.answers() if not item["check"].startswith("rule:gdpr/")]
        self.file(*rules, *self.documents(), packs=[
            {"pack": "gdpr", "status": "not-applicable", "reason": "Not in scope.", "owner": "Camille"}])
        output, _ = self.file(*self.answers(), *self.documents())
        self.assertNotIn("Pack gdpr", output)
        self.assertNotIn("packs", self.record()["result"])
        self.assertNotIn("warnings", self.record()["result"])
        self.assertEqual(self.run_cli("task", "complete", TASK, "--by", "CM", typed=TASK)[0].strip(), "done")

    def pack_answers(self):
        """Every pack the result template lists, declared not applicable as a whole."""
        template = json.loads(self.run_cli("task", "result", TASK, "--template")[0])
        return [{"pack": item["pack"], "status": "not-applicable", "reason": "No change in this area.",
                 "owner": "Camille"} for item in template["packs"]]

    def points(self, output):
        return int(re.search(r"(\d+) point\(s\) before the task can be done", output).group(1))

    def assert_verify_keeps_the_pack_answers(self):
        self.run_cli("task", "verify", TASK)
        packs = self.pack_answers()
        self.assertGreaterEqual(len(packs), 3)
        before = self.points(self.file(packs=packs)[0])
        answered = [item["pack"] for item in self.record()["result"]["packs"]]
        self.assertEqual(answered, [item["pack"] for item in packs])
        output, _ = self.run_cli("task", "verify", TASK)
        self.assertEqual([item["pack"] for item in self.record()["result"]["packs"]], answered)
        self.assertEqual(self.points(output), before)

    def test_task_verify_keeps_the_pack_answers_of_a_bug_on_a_python_typescript_react_project(self):
        """Issue 377: verify records the machine checks of a pack, which is no report answering its rules one by one."""
        self.approved(answers={"kind": "bug"}, stack=["Python", "TypeScript", "React"])
        self.assert_verify_keeps_the_pack_answers()

    def test_task_verify_keeps_the_pack_answers_of_the_example_project(self):
        self.approved(stack=json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8"))["stack"])
        self.assert_verify_keeps_the_pack_answers()

    def test_checks_show_a_rule_a_pack_answer_covers_with_that_answer(self):
        """Issue 379: task checks read only the rules reported one by one, and listed the covered ones as not reported."""
        self.approved(stack=["Python", "TypeScript", "React"])
        rule = "rule:react/keep-render-pure"
        self.assertIn(f"{rule} [report] not reported", self.run_cli("task", "checks", TASK)[0])
        self.file(packs=[{"pack": "react", "status": "not-applicable", "reason": "No interface change here.",
                          "owner": "CM"}])
        listing = self.run_cli("task", "checks", TASK)[0]
        self.assertIn(f"{rule} [report] not-applicable", listing)
        self.assertNotIn(f"{rule} [report] not reported", listing)
        entry = next(item for item in json.loads(self.run_cli("task", "checks", TASK, "--json")[0])
                     if item["id"] == rule)
        self.assertEqual(entry["result"]["status"], "not-applicable")
        self.assertEqual(entry["result"]["via_pack"], "react")

    def test_closing_over_rules_the_answers_select_set_aside_lists_them_and_needs_the_person(self):
        """Issue 288: nine GDPR rules declared not applicable closed the task without a question."""
        self.gdpr_task()
        output, _ = self.file(*self.answers(), *self.documents())
        self.assertIn(f"openguildkit task complete {TASK} --by NAME", output)
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("data protection, security or AI rule(s) are declared not applicable", error)
        self.assertIn("- rule:gdpr/confirm-lawful-basis is not-applicable: Nothing in this change touches "
                      "rule:gdpr/confirm-lawful-basis. (Camille) [data protection]", error)
        self.assertIn("rule:gdpr/apply-retention-period", error)
        # A rule of a pack the answers do not select is not asked again: the python pack is no sensitive area.
        self.assertNotIn("rule:python/", error)
        self.assertIn(f"openguildkit task complete {TASK} --by NAME, at a terminal.", error)
        self.assertEqual(self.record()["status"], "approved")
        _, error = self.run_cli("task", "complete", TASK, "--by", "CM", typed="another-task", code=1)
        self.assertIn("Closing cancelled.", error)
        self.assertEqual(self.record()["status"], "approved")
        output, notes = self.run_cli("task", "complete", TASK, "--by", "CM", typed=TASK)
        self.assertIn("AI rules declared not applicable, which you confirm:\n", notes)
        self.assertIn("\n  - rule:gdpr/confirm-lawful-basis is not-applicable", notes)
        self.assertLess(notes.index("which you confirm"), notes.index(f"Type {TASK} to close it as done"))
        self.assertEqual(output.splitlines()[0], "done")
        self.assertEqual(self.record()["result"]["closing"]["by"], "CM")

    def test_rules_the_answers_select_declared_not_applicable_with_a_shared_reason_are_flagged(self):
        self.gdpr_task()
        output, _ = self.file(*self.answers(reason="Not relevant."), *self.documents())
        self.assertIn("rule:gdpr/confirm-lawful-basis", output)
        self.assertIn("with the same reason as", output)

    def test_closing_over_a_skipped_sensitive_rule_needs_the_person_and_lists_open_points_by_nature(self):
        self.gdpr_task()
        skip = ("rule:gdpr/confirm-lawful-basis", "rule:python/follow-python-style")
        output, _ = self.file(*self.answers(skip=skip), *self.documents())
        # The result does not say plain Ready when task complete needs the person.
        self.assertNotIn("Ready: run task complete.", output)
        self.assertIn(f"Ready to close with the person at a terminal", output)
        self.assertIn(f"openguildkit task complete {TASK} --by NAME", output)
        _, error = self.run_cli("task", "complete", TASK, code=1)
        self.assertIn("data protection, security or AI point(s) are skipped", error)
        self.assertIn("--by NAME", error)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            output, notes = self.run_cli("task", "complete", TASK, "--by", "Camille")
        # The person read the open points at the prompt: they are printed once.
        self.assertEqual(notes.count("  - rule:gdpr/confirm-lawful-basis is skipped"), 1)
        self.assertNotIn("rule:gdpr/confirm-lawful-basis", output)
        self.assertIn("open point(s), listed above", output)
        self.assertEqual(output.splitlines()[0], "done-with-reservations")
        self.assertIn("--follows request-status", output)
        lines = notes.splitlines()
        self.assertEqual(lines[0], "Data protection, security or AI rules skipped, failed or declared not applicable "
                                   "as a pack:")
        self.assertTrue(lines[1].startswith("  - rule:gdpr/confirm-lawful-basis is skipped"))
        self.assertLess(notes.index("rule:gdpr/confirm"), notes.index("Other rules skipped or failed:"))
        self.assertIn("  - rule:python/follow-python-style is skipped", notes)
        self.assertIn("Board verdicts at approval that asked for changes:", notes)
        record = self.record()
        self.assertEqual(record["result"]["closing"]["by"], "Camille")
        listing = self.run_cli("task", "list")[0]
        # The approver and the person who closed the task are named apart.
        self.assertIn("request-status [done-with-reservations, approved by Camille, closed by Camille]", listing)
        self.assertIn("Done with reservations", listing)
        # Every reader of the status takes a task closed with reservations as completed.
        self.run_cli("docs", "export", "--tasks", TASK, "--output", "docs-site", "--version", "1.0.0")
        self.run_cli("deliverable", "new", "campaign-brief", "--task", TASK, "--tool", "Brevo", "--output", "brief.md")
        self.assertEqual(json.loads(self.run_cli("guard", "--json")[0])["covered_by"], [])

    def test_the_listed_next_step_follows_the_recorded_result(self):
        self.approved(exit_code=1)
        next_step = lambda: json.loads(self.run_cli("task", "list", "--json")[0])[0]["next"]
        self.assertIn(f"record the results: task verify {TASK} and task result {TASK}", next_step())
        output = self.run_cli("task", "verify", TASK, code=1)[0]
        self.assertIn("- command:1 is mandatory and failed", output)
        self.assertIn(f"rule(s) and named evidence to report: openguildkit task result {TASK} --template", output)
        step = next_step()
        self.assertTrue(step.startswith("command:1 (`"), step)
        self.assertIn(f"failed: ", step)
        self.assertIn(f"Fix it, then run task verify {TASK}.", step)
        self.assertNotIn("Implement", step)

    def test_a_person_records_a_command_that_cannot_run_here_and_the_task_closes_with_that_reservation(self):
        failing = f'"{sys.executable}" -c "import sys; print(\'Cannot find module express\'); sys.exit(1)"'
        self.approved(checks=[failing, failing.replace("express", "jest")])
        handoff = self.run_cli("task", "handoff", TASK)[0]
        self.assertIn("## Checks task verify will run", handoff)
        self.assertIn("- `command:1`: `", handoff)
        self.assertIn("Install the project's dependencies", handoff)
        # A failed mandatory command makes task verify exit with 1.
        self.run_cli("task", "verify", TASK, code=1)
        declare = lambda check, *extra: ("task", "verify", TASK, "--cannot-run", check, "--by", "Camille", *extra)
        reason = ("--reason", "The sandbox has no network.")
        with patch("sys.stdin.isatty", return_value=False):
            self.assertIn("interactive terminal", self.run_cli(*declare("command:1"), *reason, code=1)[1])
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.assertIn("not a check command", self.run_cli(*declare("command:7"), *reason, code=1)[1])
            self.assertIn("in at least 3 words", self.run_cli(*declare("command:1"), "--reason", "x", code=1)[1])
            self.run_cli(*declare("command:1"), *reason, code=1)
            self.run_cli(*declare("command:2"), *reason)
        checks = {item["check"]: item for item in self.record()["result"]["checks"]}
        self.assertTrue(checks["command:1"]["cannot_run"] and checks["command:2"]["cannot_run"])
        # Running task verify again keeps the person's declarations, and says so.
        output = self.run_cli("task", "verify", TASK)[0]
        self.assertIn("command:1 still cannot run here: Camille declared it (The sandbox has no network.)", output)
        self.assertEqual({item["check"]: item["status"] for item in self.record()["result"]["checks"]
                          if item["check"].startswith("command:")}, {"command:1": "skipped", "command:2": "skipped"})
        self.report(*self.rule_outcomes(), criteria=[
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "Tried by hand."}])
        output = self.run_cli("task", "complete", TASK)[0]
        self.assertEqual(output.splitlines()[0], "done-with-reservations")
        self.assertIn("Project checks that could not run in this environment:", output)
        self.assertIn("  - command:1 could not run: The sandbox has no network. (recorded by Camille)", output)

    def test_only_the_person_who_declared_it_withdraws_a_declaration_and_a_passing_command_is_not_declared(self):
        self.approved(exit_code=1)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            self.run_cli("task", "verify", TASK, "--cannot-run", "command:1", "--by", "Camille",
                         "--reason", "No network in this sandbox.")
            error = self.run_cli("task", "verify", TASK, "--withdraw", "command:1", "--by", "Alex", code=1)[1]
            self.assertIn("Camille declared it: only they withdraw it.", error)
            self.run_cli("task", "verify", TASK, "--withdraw", "command:1", "--by", "Camille", code=1)
        statuses = {item["check"]: item for item in self.record()["result"]["checks"]}
        self.assertEqual(statuses["command:1"]["status"], "failed")
        self.assertNotIn("cannot_run", statuses["command:1"])

    def test_a_command_that_passes_here_cannot_be_declared_unable_to_run(self):
        self.approved()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            error = self.run_cli("task", "verify", TASK, "--cannot-run", "command:1", "--by", "Camille",
                                 "--reason", "No network in this sandbox.", code=1)[1]
        self.assertIn("command:1 passes in this environment: nothing to declare", error)

    def test_a_criterion_tied_to_a_check_that_has_not_passed_is_counted_apart(self):
        self.approved(exit_code=1)
        self.run_cli("task", "verify", TASK, code=1)
        output, _ = self.report(*self.rule_outcomes(), criteria=[
            {"criterion": "Users only see their own requests.", "status": "met", "evidence": "Test run.",
             "verified_by": "command:1"}])
        self.assertIn("Criteria met: 0 tied to a check or a test, 1 tied to a check that has not passed, 0 declared "
                      "only.", output)
        exported = json.loads((self.root / self.run_cli("task", "export", TASK)[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual(exported["result"]["criteria"][0]["verified_by"], "command:1, which has not passed")

    def test_task_verify_says_when_no_check_command_is_configured(self):
        self.approved(checks=[])
        output = self.run_cli("task", "verify", TASK)[0]
        self.assertIn("No project check command is configured", output)
        self.assertIn('openguildkit profile add check "COMMAND"', output)

    def test_a_task_with_nothing_open_is_done_in_one_line_and_says_when_no_command_ran(self):
        self.approved(checks=[])
        write_json(self.root / "result.json", {"revision": "abc1234", "criteria": [], "checks": self.rule_outcomes()})
        self.run_cli("task", "result", TASK, "--file", self.root / "result.json")
        output, notes = self.run_cli("task", "complete", TASK)
        self.assertEqual(output, "done\n")
        self.assertIn("No project check command ran for this task", notes)
        listing = self.run_cli("task", "list")[0]
        self.assertIn(f"{TASK} [done, approved by Camille]", listing)
        self.assertNotIn("closed by", listing)


class ResultProblemsTests(ResultCase):
    def test_a_result_with_three_defects_is_refused_once_with_the_three_of_them(self):
        """Issue #490: task result --file named one defect per call, where task submit lists them all."""
        self.approved()
        rules = self.rule_outcomes()
        del rules[0]["owner"]
        del rules[1]["owner"]
        write_json(self.root / "result.json", {
            "revision": "abc1234", "checks": rules,
            "criteria": [{"criterion": "Customers see the status", "status": "maybe", "evidence": "tests/test_access.py"}]})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("The result has 3 problems:", error)
        self.assertIn("criteria[1]: A criterion status is met or not-met, not 'maybe'.", error)
        for index in (1, 2):
            self.assertIn(f"checks[{index}]: {rules[index - 1]['check']} owner must contain text.", error)
        self.assertEqual(error.count("Run openguildkit task result"), 1)

    def test_a_result_with_one_defect_keeps_its_message(self):
        self.approved()
        write_json(self.root / "result.json", {"revision": "abc1234", "checks": self.rule_outcomes(), "criteria": [
            {"criterion": "x", "status": "maybe", "evidence": "y"}]})
        _, error = self.run_cli("task", "result", TASK, "--file", self.root / "result.json", code=1)
        self.assertIn("A criterion status is met or not-met, not 'maybe'. Run openguildkit task result", error)
        self.assertNotIn("problems:", error)


if __name__ == "__main__":
    unittest.main()
