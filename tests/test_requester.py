"""The requester of a task and the person who approves it (RFC #445): an option of the profile, off by default.

`task new --requested-by NAME` records who asked for the work, in the task, the decision brief, the approval's seal
and the exported record. A person turns `separate-requester` on at a terminal; then every task names its requester,
and the requester cannot approve it, locally (task decide) or in CI (guard --ci reads the option at the base revision).
A project that leaves the option off, and the records written before it, read and verify as before.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from openguildkit import profile_cli, requester
from openguildkit.catalog import load_catalog
from openguildkit.decisions import check_decision_seal, decision_payload, record_digest
from openguildkit.project import profile_fingerprint, validate_profile
from openguildkit.storage import write_json

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
ANSWERS = {"kind": "bug", "surface": ["service"], "data": "none", "research": "local", "concerns": ["none"]}
# What an approval covered before the requester existed: a task without one seals exactly these fields.
PAYLOAD_KEYS = {"task", "outcome", "consultation_id", "scope_sha256", "review_sha256", "profile_fingerprint",
                "blocker_resolutions_sha256", "by", "reason", "base_revision", "shared_sha256", "brief", "summary"}
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.org"}


class ProjectCase(unittest.TestCase):
    """A project of one Python component, with the option off until a test turns it on."""

    profile_answers: dict = {}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", {"name": "Ledger", "personal_data": "no", "stack": ["Python"],
                                                **self.profile_answers})
        self.run_cli("init", "--answers", self.root / "answers.json")
        (self.root / "notes.md").write_text("The export job retries once.\n", encoding="utf-8")
        self.work = self.root / ".openguildkit" / "work"
        self.work.mkdir()
        write_json(self.work / "answers.json", ANSWERS)

    def run_cli(self, *arguments, code=0, typed=None):
        # Without a typed line, no terminal: the suite may itself run at one.
        result = run_cli(self.root, *arguments, expect=code, typed=typed, stdin="" if typed is None else None)
        return result.stdout, result.stderr

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def task(self, task_id="retry") -> dict:
        return json.loads((self.root / ".openguildkit" / "tasks" / f"{task_id}.json").read_text(encoding="utf-8"))

    def turn_on(self):
        self.run_cli("profile", "set", "separate-requester", "on", "--by", "Sam", "--reason", "Four eyes", typed="on")

    def reviewed(self, task_id="retry", *requested_by):
        options = ["--requested-by", *requested_by] if requested_by else []
        self.run_cli("task", "new", "Add a retry to the export job", "--id", task_id, *options)
        self.run_cli("task", "consult", task_id, "--answers", self.work / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        template["summary"] = "The boards agree: one retry."
        for entry in template["boards"]:
            entry.update(recommendation="Add the retry.", open_questions=[],
                         evidence=[{"source": "project-file", "ref": "notes.md", "supports": "The job retries."}])
            for lens in entry["challenge"]["specialists"]:
                lens.update(finding="Seen in the notes.", basis="observed", evidence_refs=[1])
            entry["challenge"].update(verdict="proceed", confidence="medium", alternative="No retry.",
                                      failure_mode="Nothing worth naming.", verification="Run the job twice.")
        write_json(self.work / f"{task_id}-review.json", template)
        self.run_cli("task", "review", task_id, "--file", self.work / f"{task_id}-review.json")

    def decide(self, task_id="retry", by="Camille", code=0):
        return self.run_cli("task", "decide", task_id, "--approve", "--by", by, "--reason", "Agreed", typed=task_id,
                            code=code)


class OffByDefaultTests(ProjectCase):
    def test_a_new_project_has_the_option_off_and_task_new_needs_no_requester(self):
        self.assertNotIn("separate_requester", self.profile())
        self.run_cli("task", "new", "Add a retry", "--id", "retry")
        self.assertNotIn("requested_by", self.task())

    def test_the_requester_is_recorded_in_the_task_the_brief_the_seal_and_the_export(self):
        self.reviewed("retry", "  Ann Lee ")
        self.assertEqual(self.task()["requested_by"], "Ann Lee")
        shown, _ = self.run_cli("task", "challenge", "retry")
        self.assertIn("Requested by Ann Lee.", shown)
        # Off: the requester may approve their own task, as before; the approval still seals who requested it.
        _, prompt = self.decide(by="ann lee")
        self.assertIn("Requested by Ann Lee.", prompt)
        payload = check_decision_seal(self.task())
        self.assertEqual(payload["requested_by"], "Ann Lee")
        self.assertNotIn("separate_requester", payload)
        record = json.loads((self.root / self.run_cli("task", "export", "retry")[0].strip()).read_text(encoding="utf-8"))
        self.assertEqual(record["requested_by"], "Ann Lee")
        self.assertEqual(record["decision"]["payload"]["requested_by"], "Ann Lee")
        self.assertNotIn("separate_requester", record["decision"])

    def test_a_task_without_a_requester_seals_and_exports_what_it_did_before(self):
        self.reviewed("retry")
        self.decide()
        task = self.task()
        self.assertNotIn("requested_by", task)
        self.assertNotIn("separate_requester", task["decision"])
        self.assertEqual(set(check_decision_seal(task)), PAYLOAD_KEYS)
        self.assertEqual(set(decision_payload(task, "Camille", "Agreed", None)), PAYLOAD_KEYS)
        record = json.loads((self.root / self.run_cli("task", "export", "retry")[0].strip()).read_text(encoding="utf-8"))
        self.assertNotIn("requested_by", record)
        self.assertEqual(set(record["decision"]["payload"]), PAYLOAD_KEYS)

    def test_a_requester_is_one_line_of_text(self):
        for name in ("", "   ", "Ann\nLee"):
            with self.subTest(name=name):
                _, error = self.run_cli("task", "new", "Add a retry", "--id", "retry", "--requested-by", name, code=1)
                self.assertIn("--requested-by", error)
                self.assertFalse((self.root / ".openguildkit" / "tasks" / "retry.json").exists())

    def test_a_changed_requester_breaks_the_seal(self):
        self.reviewed("retry", "Ann Lee")
        self.decide()
        task = self.task()
        path = self.root / ".openguildkit" / "tasks" / "retry.json"
        for change in ({"requested_by": "Camille"}, {"requested_by": None}):
            with self.subTest(change=change):
                write_json(path, {key: value for key, value in {**task, **change}.items() if value is not None})
                _, error = self.run_cli("task", "handoff", "retry", code=1)
                self.assertIn("no longer matches what was approved", error)
        write_json(path, task)
        self.run_cli("task", "handoff", "retry")


class ActivationTests(ProjectCase):
    def test_a_person_turns_the_option_on_at_a_terminal_and_the_profile_says_who_when_and_why(self):
        output, _ = self.run_cli("profile", "set", "separate-requester", "on", "--by", "Sam", "--reason", "Four eyes",
                                 typed="on")
        self.assertIn("Profile changed: set separate-requester on, by Sam on ", output)
        self.assertIn("--requested-by NAME", output)
        profile = self.profile()
        self.assertIs(profile["separate_requester"], True)
        self.assertEqual((profile["changes"][-1]["change"], profile["changes"][-1]["reason"]),
                         ("set separate-requester on", "Four eyes"))
        self.assertIn("--requested-by", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        _, error = self.run_cli("profile", "set", "separate-requester", "on", "--by", "Sam", "--reason", "x", code=1)
        self.assertIn("separate-requester is already on. Nothing was written.", error)
        self.run_cli("check")

    def test_an_agent_without_a_terminal_can_neither_turn_it_on_nor_off(self):
        before = (self.root / ".openguildkit" / "project.json").read_bytes()
        _, error = self.run_cli("profile", "set", "separate-requester", "on", "--by", "Agent", "--reason", "x", code=1)
        self.assertIn("requester separation turned on", error)
        self.assertIn("Ask them to run the same command at an interactive terminal.", error)
        self.assertEqual((self.root / ".openguildkit" / "project.json").read_bytes(), before)
        self.turn_on()
        before = (self.root / ".openguildkit" / "project.json").read_bytes()
        _, error = self.run_cli("profile", "set", "separate-requester", "off", "--by", "Agent", "--reason", "x", code=1)
        self.assertIn("requester separation turned off", error)
        self.assertEqual((self.root / ".openguildkit" / "project.json").read_bytes(), before)
        _, error = self.run_cli("profile", "set", "separate-requester", "off", "--by", "Sam", "--reason", "x",
                                typed="yes", code=1)
        self.assertIn("Profile change cancelled", error)
        self.run_cli("profile", "set", "separate-requester", "off", "--by", "Sam", "--reason", "Pilot over", typed="off")
        self.assertNotIn("separate_requester", self.profile())

    def test_the_web_page_cannot_change_it_and_is_told_the_command(self):
        catalog = load_catalog()
        before = self.profile()
        after = {**before, "separate_requester": True}
        on, = profile_cli.weakening_changes(before, after, catalog)
        self.assertEqual(on[1], ["profile", "set", "separate-requester", "on", "--by", "INITIALS", "--reason", "WHY"])
        off, = profile_cli.weakening_changes(after, before, catalog)
        self.assertEqual(off[1], ["profile", "set", "separate-requester", "off", "--by", "INITIALS", "--reason", "WHY"])
        with self.assertRaises(profile_cli.Weakening):
            profile_cli.save_edited(self.root, self.root / ".openguildkit", after, "Page", "Edited in the page")
        self.assertNotIn("separate_requester", self.profile())

    def test_the_option_is_not_part_of_what_an_approval_rests_on_and_voids_none(self):
        catalog = load_catalog()
        profile = validate_profile(self.profile(), catalog)
        self.assertEqual(profile_fingerprint(profile, catalog),
                         profile_fingerprint(validate_profile({**profile, "separate_requester": True}, catalog), catalog))
        for bad in (False, "yes", 1):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_profile({**profile, "separate_requester": bad}, catalog)
        self.reviewed("retry")
        self.decide()
        output, _ = self.run_cli("profile", "set", "separate-requester", "on", "--by", "Sam", "--reason", "x", typed="on")
        self.assertNotIn("voids", output)
        self.run_cli("task", "handoff", "retry")

    def test_profile_export_does_not_carry_it_and_names_the_command(self):
        self.turn_on()
        result = run_cli(self.root, "profile", "export", stdin="")
        self.assertNotIn("separate_requester", json.loads(result.stdout))
        self.assertIn("openguildkit profile set separate-requester on --by INITIALS --reason WHY", result.stderr)


class SeparationTests(ProjectCase):
    profile_answers = {"separate_requester": True}

    def test_task_new_needs_the_requester_and_says_so(self):
        _, error = self.run_cli("task", "new", "Add a retry", "--id", "retry", code=1)
        self.assertIn("--requested-by NAME", error)
        self.assertIn("Nothing was written.", error)
        self.assertFalse((self.root / ".openguildkit" / "tasks" / "retry.json").exists())

    def test_the_requester_cannot_approve_whatever_the_case_and_the_spaces(self):
        self.reviewed("retry", "Ann Lee")
        for name in ("Ann Lee", " ann  LEE ", "ANN LEE", "AnnLee"):
            with self.subTest(name=name):
                _, error = self.decide(by=name, code=1)
                self.assertIn("Ann Lee requested task retry and cannot approve it", error)
                self.assertIn("another person", error)
                self.assertIn("openguildkit task decide retry --approve --by INITIALS --reason WHY", error)
                self.assertEqual(self.task()["status"], "reviewed")
        _, error = self.run_cli("task", "decision-payload", "retry", "--by", "ann lee", "--reason", "x", code=1)
        self.assertIn("cannot approve it", error)
        # Asking for changes is not an approval: the requester may still send the task back.
        self.decide(by="Camille")
        task = self.task()
        self.assertEqual(task["status"], "approved")
        self.assertIs(task["decision"]["separate_requester"], True)
        payload = check_decision_seal(task)
        self.assertEqual((payload["requested_by"], payload["separate_requester"]), ("Ann Lee", True))
        record = json.loads((self.root / self.run_cli("task", "export", "retry")[0].strip()).read_text(encoding="utf-8"))
        self.assertIs(record["decision"]["separate_requester"], True)
        self.assertEqual(record["requested_by"], "Ann Lee")

    def test_the_requester_may_request_changes(self):
        self.reviewed("retry", "Ann Lee")
        self.run_cli("task", "decide", "retry", "--request-changes", "--by", "Ann Lee", "--reason", "Narrower")
        self.assertEqual(self.task()["status"], "changes-requested")

    def test_a_task_opened_before_the_option_has_no_requester_and_another_task_is_opened(self):
        self.run_cli("profile", "set", "separate-requester", "off", "--by", "Sam", "--reason", "x", typed="off")
        self.reviewed("retry")
        self.turn_on()
        _, error = self.decide(code=1)
        self.assertIn("Task retry records no requester", error)
        self.assertIn('openguildkit task new "BRIEF" --requested-by NAME', error)

    def test_the_brief_says_another_person_approves(self):
        self.reviewed("retry", "Ann Lee")
        shown, _ = self.run_cli("task", "challenge", "retry")
        self.assertIn("Requested by Ann Lee: another person approves it", shown)

    def test_tasks_opened_for_alerts_name_the_watch_as_their_requester_only_when_the_option_is_on(self):
        from openguildkit import alerts_cli

        state = self.root / ".openguildkit"
        self.assertEqual(alerts_cli._alert_requester(state), "openguildkit alerts")
        self.run_cli("profile", "set", "separate-requester", "off", "--by", "Sam", "--reason", "x", typed="off")
        self.assertIsNone(alerts_cli._alert_requester(state))


class MessageBudgetTests(ProjectCase):
    MESSAGE_BUDGET = 1_200

    def test_every_new_message_is_short(self):
        messages = {"agent": self.run_cli("profile", "set", "separate-requester", "on", "--by", "A", "--reason", "x",
                                          code=1)[1]}
        messages["on"] = self.run_cli("profile", "set", "separate-requester", "on", "--by", "Sam", "--reason", "x",
                                      typed="on")[0]
        messages["new"] = self.run_cli("task", "new", "Add a retry", "--id", "x", code=1)[1]
        self.reviewed("retry", "Ann Lee")
        messages["decide"] = self.decide(by="Ann Lee", code=1)[1]
        for name, text in messages.items():
            with self.subTest(message=name):
                self.assertLessEqual(len(text.encode("utf-8")), self.MESSAGE_BUDGET, text)


@unittest.skipIf(shutil.which("git") is None, "needs git")
class GitCase(ProjectCase):
    """A project in Git whose guard is on, with a feature branch for the change that guard --ci judges."""

    profile_answers = {"guard": "enforce"}

    def git(self, *args):
        result = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True,
                                env={**os.environ, **GIT_ENV})
        self.assertEqual(result.returncode, 0, f"git {' '.join(args)}: {result.stderr}")

    def commit_all(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def branch(self):
        (self.root / "app.py").write_text("print('export')\n", encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.commit_all("base")
        self.git("checkout", "-q", "-b", "feature")

    def deliver(self, task_id, *requested_by, by="Camille"):
        self.reviewed(task_id, *requested_by)
        self.decide(task_id, by=by)
        (self.root / "app.py").write_text(f"print('export {task_id}')\n", encoding="utf-8")
        self.commit_all("The work")
        self.run_cli("task", "export", task_id)
        self.commit_all("The decision")

    def ci(self, code=0) -> dict:
        return json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=code)[0])


class CiTests(GitCase):
    profile_answers = {"guard": "enforce", "separate_requester": True}

    def test_a_record_approved_by_another_person_holds(self):
        self.branch()
        self.deliver("retry", "Ann Lee")
        result = self.ci()
        self.assertEqual((result["ok"], result["decisions"]), (True, ["retry"]))

    def test_a_change_that_turns_the_option_off_cannot_approve_its_own_request(self):
        self.branch()
        self.run_cli("profile", "set", "separate-requester", "off", "--by", "Ann Lee", "--reason", "x", typed="off")
        self.deliver("retry", "Ann Lee", by="ann lee")
        result = self.ci(code=1)
        self.assertEqual(result["decisions"], [])
        problem, = [item for item in result["problems"] if "requested" in item]
        self.assertIn("Ann Lee requested task retry and approved it", problem)
        self.assertIn("separate-requester", problem)
        sarif = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1)[0])
        rules = {item["ruleId"] for item in sarif["runs"][0]["results"]}
        self.assertIn("decision-requester-approved", rules)

    def test_a_new_record_without_a_requester_is_refused_when_the_base_has_the_option(self):
        self.branch()
        self.run_cli("profile", "set", "separate-requester", "off", "--by", "Sam", "--reason", "x", typed="off")
        self.deliver("retry")
        result = self.ci(code=1)
        problem, = [item for item in result["problems"] if "requester" in item]
        self.assertIn("records no requester", problem)
        sarif = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1)[0])
        self.assertIn("decision-requester-missing", {item["ruleId"] for item in sarif["runs"][0]["results"]})

    def test_a_record_whose_requester_differs_from_the_sealed_one_is_refused(self):
        self.branch()
        self.deliver("retry", "Ann Lee")
        path = self.root / ".openguildkit" / "decisions" / "retry.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        forged = {**record, "requested_by": "Someone Else"}
        forged["record_sha256"] = record_digest(forged)
        write_json(path, forged)
        self.commit_all("Forge")
        result = self.ci(code=1)
        self.assertTrue(any("requester of the record is not the one that was approved" in item
                            for item in result["problems"]), result["problems"])


class OptionOffAtTheBaseTests(GitCase):
    def test_the_requester_may_approve_when_the_base_has_the_option_off(self):
        self.branch()
        self.deliver("retry", "Ann Lee", by="Ann Lee")
        self.assertEqual(self.ci()["decisions"], ["retry"])


@unittest.skipIf(shutil.which("ssh-keygen") is None or shutil.which("git") is None, "needs ssh-keygen and git")
class SignedTests(ProjectCase):
    """The signer is an SSH principal that the code does not link to a name: the requester is compared to both the
    name given with --by and the principal that signs."""

    def test_issue_475_in_a_signed_project_the_requester_is_a_principal_of_the_signers_file(self):
        """Issue #475: in a signed project, a requester named otherwise than their principal was not caught."""
        (self.root / "allowed_signers").write_text(
            "# The approvers\nann@example.org,*@ops.example.org ssh-ed25519 AAAA\n", encoding="utf-8")
        self.run_cli("profile", "set", "approval", "signed", "--signers", "allowed_signers", "--approver",
                     "ann@example.org", "--by", "Sam", "--reason", "Signed", typed="signed")
        self.turn_on()
        _, error = self.run_cli("task", "new", "Add a retry", "--id", "retry", "--requested-by", "Ann Lee", code=1)
        self.assertIn("Ann Lee is not a principal of allowed_signers", error)
        self.assertIn("(ann@example.org, *@ops.example.org)", error)
        self.assertFalse((self.root / ".openguildkit" / "tasks" / "retry.json").exists())
        self.run_cli("task", "new", "Add a retry", "--id", "retry", "--requested-by", "ann@example.org")
        self.run_cli("task", "new", "Add a retry", "--id", "other", "--requested-by", "lou@ops.example.org")
        self.assertEqual(self.task()["requested_by"], "ann@example.org")

    def test_the_requester_cannot_sign_the_approval_under_another_name(self):
        keys = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "ann")], check=True)
        public = (keys / "ann.pub").read_text(encoding="utf-8").strip()
        (self.root / "allowed_signers").write_text(f"ann@example.org {public}\n", encoding="utf-8")
        self.run_cli("profile", "set", "approval", "signed", "--signers", "allowed_signers", "--approver",
                     "ann@example.org", "--by", "Sam", "--reason", "Signed", typed="signed")
        self.turn_on()
        for args in (("init", "-q"), ("add", "-A"), ("commit", "-q", "-m", "signers")):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True,
                           env={**os.environ, **GIT_ENV})
        self.reviewed("retry", "ann@example.org")
        self.run_cli("task", "decision-payload", "retry", "--by", "Camille", "--reason", "Agreed",
                     "--output", keys / "decision.json")
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "ann"), "-n", "openguildkit-decision",
                        str(keys / "decision.json")], check=True, capture_output=True, stdin=subprocess.DEVNULL)
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("task", "decide", "retry", "--approve", "--by", "Camille", "--reason", "Agreed",
                                    "--signer", "ann@example.org", "--signature", keys / "decision.json.sig", code=1)
        self.assertIn("signs this approval", error)
        self.assertEqual(self.task()["status"], "reviewed")


BEFORE = json.loads((REPO / "tests" / "fixtures" / "upgrade" / "before-light-lane.json").read_text(encoding="utf-8"))


class BeforeTheRequesterTests(unittest.TestCase):
    """A project written by an earlier release (tests/fixtures/upgrade/before-light-lane.json) keeps its records and
    their seals: nothing names a requester, the export is written again byte for byte, and turning the option on voids
    no approval."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for name, content in BEFORE["files"].items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        clock = patch("openguildkit.clock.real_now", return_value=datetime.fromisoformat(BEFORE["now"]))
        clock.start()
        self.addCleanup(clock.stop)

    def test_the_old_records_name_no_requester_and_their_seals_hold(self):
        for name, content in BEFORE["files"].items():
            if name.startswith(".openguildkit/"):
                self.assertNotIn("requested_by", content, name)
                self.assertNotIn("separate_requester", content, name)
        for task_id in ("approved-task", "done-task"):
            task = json.loads(BEFORE["files"][f".openguildkit/tasks/{task_id}.json"])
            self.assertEqual(set(check_decision_seal(task)) - PAYLOAD_KEYS, set())

    def test_the_export_is_written_again_byte_for_byte_with_the_option_off_and_on(self):
        target = self.root / "again.json"
        expected = BEFORE["files"][".openguildkit/decisions/done-task.json"]
        run_cli(self.root, "task", "export", "done-task", "--output", target)
        self.assertEqual(target.read_text(encoding="utf-8"), expected)
        output = run_cli(self.root, "profile", "set", "separate-requester", "on", "--by", "Sam", "--reason", "x",
                         typed="on").stdout
        self.assertNotIn("voids", output)
        self.assertIn("# Approved task handoff", run_cli(self.root, "task", "handoff", "approved-task").stdout)
        run_cli(self.root, "task", "export", "done-task", "--output", target)
        self.assertEqual(target.read_text(encoding="utf-8"), expected)


class SamePersonTests(unittest.TestCase):
    def test_names_compare_without_case_or_spaces(self):
        self.assertTrue(requester.same_person("Ann Lee", " ann  lee "))
        self.assertTrue(requester.same_person("Ann Lee", "ANNLEE"))
        self.assertFalse(requester.same_person("Ann Lee", "Anne Lee"))
        self.assertFalse(requester.same_person("Ann Lee", None))


if __name__ == "__main__":
    unittest.main()
