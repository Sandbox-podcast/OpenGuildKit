"""`check --format sarif` and `guard --ci --format sarif`: each problem under its rule, its file, its level and the
exit code the command already had; the file is the same at every run and names no folder of the machine (#420)."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from openguildkit.cli import command_parser
from openguildkit.decisions import export_digest
from openguildkit.storage import write_json

from tests.support import openguildkit_on_path, run_cli
from tests.test_sarif import machine_paths, structure_problems

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"
PROFILE_PATH = ".openguildkit/project.json"
# A project pack that cites a source without the day the page was checked.
UNDATED_PACK = {
    "id": "team-review", "title": "Team review", "version": "1.0.0",
    "description": "Ask a second person to read each change.",
    "rules": [{"id": "second-reader", "instruction": "Name a second reader.", "verification": "Read the change record."}],
    "sources": [{"title": "Example handbook", "url": "https://handbook.example.test/review"}],
}
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}


class SarifProject(unittest.TestCase):
    """A project in a temporary folder and the means to run a command in SARIF and in text."""

    guard = None  # the guard mode the project is initialized with, when the test needs one

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="ogk-sarif-user-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        openguildkit_on_path(self)

    def init(self, **extra):
        profile = {**json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")), **extra}
        write_json(self.root / "profile.json", profile)
        run_cli(self.root, "init", "--answers", self.root / "profile.json")

    def cli(self, *arguments, code=0, **options):
        return run_cli(self.root, *arguments, expect=code, **options)

    def sarif(self, *arguments, code=0):
        """Run a command with --format sarif; the document it prints, after the checks every file must pass."""
        result = self.cli(*arguments, "--format", "sarif", code=code)
        document = json.loads(result.stdout)
        self.assertEqual(structure_problems(document), [])
        self.assertEqual(machine_paths(document), [])
        self.assertNotIn(self.root.name, result.stdout)
        self.assertNotIn(str(self.root.resolve()), result.stdout)
        return document, result

    def found(self, document):
        """Each result as (rule, level, file), in the order of the file."""
        return [(item["ruleId"], item["level"], item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"])
                for item in document["runs"][0]["results"]]

    def approve(self):
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.cli("task", "template", TASK).stdout)
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                              **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        self.cli("task", "review", TASK, "--file", self.root / "review.json")
        self.cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed", typed=TASK)


class CheckSarifTests(SarifProject):
    def test_a_project_that_passes_gives_a_valid_file_without_a_result(self):
        self.init()
        document, result = self.sarif("check")
        self.assertEqual(document["runs"][0]["results"], [])
        self.assertEqual(document["runs"][0]["tool"]["driver"]["rules"], [])
        self.assertEqual(result.stderr, "")

    def test_the_file_is_the_only_thing_on_the_standard_output(self):
        self.init()
        result = self.cli("check", "--format", "sarif")
        self.assertTrue(result.stdout.startswith("{\n"))
        self.assertTrue(result.stdout.endswith("}\n"))
        self.assertNotIn("match the project profile", result.stdout)
        self.assertEqual(self.cli("check", "--format", "text").stdout, self.cli("check").stdout)

    def test_instructions_that_no_longer_match_the_profile_name_the_file_to_sync(self):
        self.init()
        profile = self.root / PROFILE_PATH
        data = json.loads(profile.read_text(encoding="utf-8"))
        write_json(profile, {**data, "conventions": [*data["conventions"], "Review tests before code."]})
        document, result = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("instructions-drift", "error", "AGENTS.md")])
        self.assertIn("out of date. Run openguildkit sync", document["runs"][0]["results"][0]["message"]["text"])
        # The command ends as it did: same exit code, same line on the standard error.
        text = self.cli("check", code=1)
        self.assertEqual(result.stderr, text.stderr)
        self.assertIn("OpenGuildKit instructions are out of date. Run openguildkit sync.", result.stderr)

    def test_a_block_edited_by_hand_has_its_own_rule(self):
        self.init()
        agents = self.root / "AGENTS.md"
        text = agents.read_text(encoding="utf-8")
        marker = "Use Conventional Commits for commit messages."
        self.assertIn(marker, text)
        agents.write_text(text.replace(marker, marker + " Never mind the tests."), encoding="utf-8")
        document, _ = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("instructions-edited", "error", "AGENTS.md")])

    def test_each_file_that_is_out_of_date_is_named(self):
        self.init()
        (self.root / ".openguildkit" / ".gitignore").write_text("work/\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("# Notes\n", encoding="utf-8")
        document, _ = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("instructions-drift", "error", ".openguildkit/.gitignore"),
                                                ("instructions-drift", "error", "CLAUDE.md")])

    def test_instructions_that_follow_a_newer_catalog_say_update_not_sync(self):
        self.init()
        lock_path = self.root / ".openguildkit" / "catalog.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock["records"]["packs"] = {name: {**pack, "version": "0.0.1"} for name, pack in lock["records"]["packs"].items()}
        write_json(lock_path, lock)
        document, _ = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("instructions-ahead-of-lock", "error", "AGENTS.md")])
        self.assertIn("openguildkit update", document["runs"][0]["results"][0]["message"]["text"])

    def test_host_settings_that_the_profile_expects_and_are_missing_have_their_rule(self):
        self.init(host="claude-code")
        document, result = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("host-settings-missing", "error", PROFILE_PATH)])
        self.assertIn("openguildkit host apply", document["runs"][0]["results"][0]["message"]["text"])
        self.assertEqual(result.stderr, self.cli("check", code=1).stderr)

    def test_a_catalog_lock_that_does_not_match_the_profile_has_its_rule(self):
        self.init()
        lock_path = self.root / ".openguildkit" / "catalog.lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        del lock["records"]["packs"][next(iter(lock["records"]["packs"]))]
        write_json(lock_path, lock)
        document, _ = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("catalog-lock-stale", "error", ".openguildkit/catalog.lock.json")])

    def test_an_approval_that_no_longer_holds_points_at_the_task_record(self):
        self.init()
        self.approve()
        self.cli("profile", "add", "check", "python -m unittest", "--by", "CM", "--reason", "Tests")
        document, result = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("decision-stale", "error", f".openguildkit/tasks/{TASK}.json")])
        self.assertIn(TASK, document["runs"][0]["results"][0]["message"]["text"])
        self.assertEqual(result.stderr, self.cli("check", code=1).stderr)

    def test_an_exported_decision_that_no_longer_holds_points_at_its_file(self):
        self.init()
        self.approve()
        exported = self.cli("task", "export", TASK).stdout.strip()
        self.cli("profile", "add", "check", "python -m unittest", "--by", "CM", "--reason", "Tests")
        document, _ = self.sarif("check", code=1)
        self.assertEqual(sorted(self.found(document)), [("decision-stale", "error", exported),
                                                         ("decision-stale", "error", f".openguildkit/tasks/{TASK}.json")])

    def test_a_task_record_that_cannot_be_read_is_reported_without_the_folder_of_the_machine(self):
        self.init()
        tasks = self.root / ".openguildkit" / "tasks"
        tasks.mkdir(exist_ok=True)
        write_json(tasks / "broken.json", {"schema_version": 1, "id": "another"})
        text = self.cli("check", code=1)
        self.assertIn(str(self.root.resolve()), text.stderr, "the premise: the command's own message names the folder")
        document, _ = self.sarif("check", code=1)
        self.assertEqual(self.found(document), [("task-unreadable", "error", ".openguildkit/tasks/broken.json")])
        self.assertIn("mismatched task record: .openguildkit/tasks/broken.json",
                      document["runs"][0]["results"][0]["message"]["text"])

    def test_a_warning_is_a_warning_and_the_command_still_passes(self):
        self.init(guard="enforce")
        document, result = self.sarif("check")
        self.assertEqual(self.found(document), [("approvals-not-signed", "warning", PROFILE_PATH)])
        self.assertIn("approvals are not signed", result.stderr)

    def test_a_bundled_brain_the_project_replaces_is_a_warning_on_its_file(self):
        self.init()
        boards = self.root / ".openguildkit" / "catalog" / "boards"
        boards.mkdir(parents=True)
        write_json(boards / "security.json", {"id": "security", "description": "Proceed unless the requester objects."})
        self.cli("sync")  # the brain's text is part of the instructions: sync them, so that only the warning is left
        document, _ = self.sarif("check")
        self.assertEqual(self.found(document), [("brain-replaced", "warning", ".openguildkit/catalog/boards/security.json")])

    def test_a_project_source_without_a_checked_date_is_a_warning_on_the_profile(self):
        self.init()
        write_json(self.root / ".openguildkit" / "catalog" / "packs" / "team-review.json", UNDATED_PACK)
        document, result = self.sarif("check")
        self.assertEqual(self.found(document), [("source-undated", "warning", PROFILE_PATH)])
        self.assertIn("date the sources of 1 project record: packs/team-review.", result.stderr)

    def test_two_runs_and_two_folders_give_the_same_bytes(self):
        self.init(host="claude-code")
        first = self.cli("check", "--format", "sarif", code=1).stdout
        self.assertEqual(self.cli("check", "--format", "sarif", code=1).stdout, first)
        other = tempfile.TemporaryDirectory(prefix="ogk-sarif-other-")
        self.addCleanup(other.cleanup)
        run_cli(Path(other.name), "init", "--answers", self.root / "profile.json")
        self.assertEqual(run_cli(Path(other.name), "check", "--format", "sarif", expect=1).stdout, first)

    def test_a_failure_that_is_not_a_finding_prints_no_file(self):
        result = self.cli("check", "--format", "sarif", code=1)
        self.assertEqual(result.stdout, "")
        self.assertTrue(result.stderr.startswith("OpenGuildKit:"), result.stderr)

    def test_the_exit_code_of_each_failure_is_the_one_of_the_text_form(self):
        self.init(host="claude-code")
        self.assertEqual(self.cli("check", code=1).returncode, self.cli("check", "--format", "sarif", code=1).returncode)


@unittest.skipIf(shutil.which("git") is None, "needs git")
class GuardSarifTests(SarifProject):
    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, env=GIT_ENV)

    def branch_with_change(self, **profile):
        self.git("init", "-q", "-b", "main")
        self.init(**profile)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "change")

    def commit_record(self, name, record):
        path = self.root / ".openguildkit" / "decisions" / name
        write_json(path, record)
        self.git("add", "-f", path)
        self.git("commit", "-q", "-m", f"record {name}")

    def ci(self, *options, code=0):
        return self.sarif("guard", "--ci", "--base", "main", *options, code=code)

    def test_a_change_without_a_decision_is_an_error_when_the_guard_enforces(self):
        self.branch_with_change(guard="enforce")
        document, result = self.ci(code=1)
        self.assertEqual(self.found(document), [("approvals-not-signed", "note", PROFILE_PATH),
                                                ("decision-missing", "error", PROFILE_PATH)])
        self.assertIn("task export", document["runs"][0]["results"][1]["message"]["text"])
        self.assertEqual(result.returncode, self.cli("guard", "--ci", "--base", "main", code=1).returncode)

    def test_the_same_problem_is_a_warning_when_the_guard_only_observes_and_the_job_passes(self):
        self.branch_with_change(guard="observe")
        document, _ = self.ci()
        self.assertEqual(self.found(document), [("approvals-not-signed", "note", PROFILE_PATH),
                                                ("decision-missing", "warning", PROFILE_PATH)])

    def test_a_valid_decision_leaves_only_the_note_about_local_approvals(self):
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.approve()
        (self.root / "app.py").write_text("print('status')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "change")
        self.git("add", self.cli("task", "export", TASK).stdout.strip())
        self.git("commit", "-q", "-m", "decision")
        document, _ = self.ci()
        self.assertEqual(self.found(document), [("approvals-not-signed", "note", PROFILE_PATH)])
        document, _ = self.ci("--require-signed", code=1)
        self.assertEqual(self.found(document), [("approvals-not-signed", "error", PROFILE_PATH)])

    def test_a_record_the_check_cannot_read_points_at_the_record(self):
        self.branch_with_change(guard="enforce")
        self.commit_record("fake.json", {"task": "nothing", "profile_fingerprint": "f", "decision": "oops"})
        document, _ = self.ci(code=1)
        self.assertEqual(self.found(document), [("decision-record-invalid", "error", ".openguildkit/decisions/fake.json"),
                                                ("approvals-not-signed", "note", PROFILE_PATH)])

    @unittest.skipIf(shutil.which("ssh-keygen") is None, "needs ssh-keygen")
    def test_a_record_a_signing_project_finds_unsigned_has_its_own_rule(self):
        keys = Path(tempfile.mkdtemp(prefix="ogk-sarif-keys-"))
        self.addCleanup(shutil.rmtree, keys, ignore_errors=True)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / "camille")], check=True)
        (self.root / "allowed_signers").write_text(f"camille@example.org {(keys / 'camille.pub').read_text().strip()}\n",
                                                   encoding="utf-8")
        self.branch_with_change(guard="enforce", approval={
            "mode": "signed", "allowed_signers": "allowed_signers", "approvers": ["camille@example.org"]})
        self.cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.cli("task", "template", TASK).stdout)
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                              **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        self.cli("task", "review", TASK, "--file", self.root / "review.json")
        self.cli("task", "decision-payload", TASK, "--by", "Camille", "--reason", "Agreed", "--output", keys / "decision.json")
        subprocess.run(["ssh-keygen", "-q", "-Y", "sign", "-f", str(keys / "camille"), "-n", "openguildkit-decision",
                        str(keys / "decision.json")], check=True, capture_output=True)
        self.cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed",
                 "--signer", "camille@example.org", "--signature", keys / "decision.json.sig")
        (self.root / "app.py").write_text("print('status page')\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "the approved work")
        record = json.loads((self.root / self.cli("task", "export", TASK).stdout.strip()).read_text(encoding="utf-8"))
        self.commit_record(f"{TASK}.json", record)
        document, _ = self.ci()
        self.assertEqual(self.found(document), [])
        # Whoever removes the signature can recompute the record's own digest; the signature check still refuses it.
        unsigned = {**record, "decision": {key: value for key, value in record["decision"].items() if key != "signature"}}
        unsigned["record_sha256"] = export_digest(unsigned)
        self.commit_record(f"{TASK}.json", unsigned)
        document, _ = self.ci(code=1)
        self.assertEqual(self.found(document), [("decision-unsigned", "error", f".openguildkit/decisions/{TASK}.json")])

    def test_a_record_approved_under_earlier_rules_points_at_the_record(self):
        self.branch_with_change(guard="enforce")
        profile_path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        write_json(profile_path, {**profile, "checks": ["python -m pytest"]})
        self.cli("sync")
        self.approve()
        self.git("add", self.cli("task", "export", TASK).stdout.strip())
        self.git("commit", "-q", "-m", "Export a decision under the branch rules")
        document, _ = self.ci(code=1)
        self.assertEqual(self.found(document), [("decision-stale", "error", f".openguildkit/decisions/{TASK}.json"),
                                                ("approvals-not-signed", "note", PROFILE_PATH)])
        self.assertIn("recorded under earlier rules", document["runs"][0]["results"][0]["message"]["text"])

    def test_changed_files_that_no_record_lists_are_one_finding_on_the_profile(self):
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.approve()
        (self.root / "README.md").write_text("Status page\n", encoding="utf-8")
        self.cli("task", "export", TASK)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base with a decision")
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "app.py").write_text("print('other work')\n", encoding="utf-8")
        self.git("add", "app.py")
        self.git("commit", "-q", "-m", "change")
        self.git("add", self.cli("task", "export", TASK).stdout.strip())
        self.git("commit", "-q", "-m", "the earlier decision again")
        document, _ = self.ci(code=1)
        self.assertEqual(self.found(document), [("approvals-not-signed", "note", PROFILE_PATH),
                                                ("decision-files-uncovered", "error", PROFILE_PATH)])
        self.assertIn("app.py", document["runs"][0]["results"][1]["message"]["text"])

    def test_a_journal_that_no_longer_matches_points_at_the_record(self):
        command = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
        self.branch_with_change(checks=[command], guard="enforce")
        self.approve()
        self.cli("task", "verify", TASK)
        self.cli("task", "export", TASK)
        record = json.loads((self.root / ".openguildkit" / "decisions" / f"{TASK}.json").read_text(encoding="utf-8"))
        log = self.root / record["result"]["journals"][0]["evidence"]
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "decision")
        log.write_text(log.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
        document, _ = self.ci(code=1)
        self.assertIn(("evidence-journal-changed", "error", f".openguildkit/decisions/{TASK}.json"), self.found(document))

    def test_a_withdrawal_is_a_finding_of_check_until_it_is_exported_and_of_the_guard_after(self):
        record = f".openguildkit/decisions/{TASK}.json"
        self.git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("Suport portal\n", encoding="utf-8")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.approve()
        (self.root / "README.md").write_text("Support portal\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "work")
        self.git("add", self.cli("task", "export", TASK).stdout.strip())
        self.git("commit", "-q", "-m", "decision")
        self.cli("task", "revoke", TASK, "--by", "CM", "--reason", "Support moves the portal", typed=TASK)
        document, _ = self.sarif("check", code=1)
        self.assertIn(("decision-withdrawn-here", "error", record), self.found(document))
        self.cli("task", "export", TASK)
        self.git("commit", "-q", "-am", "withdrawal")
        document, _ = self.ci(code=1)
        self.assertEqual(self.found(document), [("decision-withdrawn", "error", record),
                                                ("approvals-not-signed", "note", PROFILE_PATH)])

    def test_a_workflow_that_runs_the_check_is_a_note_on_its_file(self):
        workflow = self.root / ".github" / "workflows" / "openguildkit-guard.yml"
        workflow.parent.mkdir(parents=True)
        workflow.write_text("jobs:\n  guard:\n    steps:\n      - run: openguildkit guard --ci --base \"$BASE_REF\"\n",
                            encoding="utf-8")
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.approve()
        workflow.write_text("jobs:\n  guard:\n    steps:\n      - run: echo skipped\n", encoding="utf-8")
        self.git("commit", "-q", "-am", "edit the workflow")
        self.git("add", self.cli("task", "export", TASK).stdout.strip())
        self.git("commit", "-q", "-m", "decision")
        document, _ = self.ci()
        self.assertIn(("guard-workflow-edited", "note", ".github/workflows/openguildkit-guard.yml"), self.found(document))

    def test_a_base_without_a_profile_is_a_note_and_the_job_passes(self):
        self.git("init", "-q", "-b", "main")
        (self.root / "README.md").write_text("# Portal\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.init(guard="enforce")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add the profile")
        document, _ = self.ci()
        self.assertEqual(self.found(document), [("guard-no-base-profile", "note", PROFILE_PATH)])

    def test_two_runs_give_the_same_bytes(self):
        self.branch_with_change(guard="enforce")
        first = self.cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1).stdout
        self.assertEqual(self.cli("guard", "--ci", "--base", "main", "--format", "sarif", code=1).stdout, first)

    def test_the_json_form_is_unchanged_by_the_option(self):
        self.branch_with_change(guard="enforce")
        result = json.loads(self.cli("guard", "--ci", "--base", "main", "--json", code=1).stdout)
        self.assertEqual(sorted(result), ["changed", "decisions", "mode", "notes", "ok", "problems", "records"])


class ReportTests(unittest.TestCase):
    """What the report keeps of the lines `check` prints about sharing: what is wrong, not what is only said."""

    def test_the_lines_about_sharing_are_warnings_and_the_one_that_says_it_is_normal_is_left_out(self):
        from openguildkit.check_findings import Report

        report = Report(True)
        report.sharing([
            ("evidence-unshared", "task a cites evidence a reviewer cannot open: x.", ".openguildkit/tasks/a.json"),
            ("task-id-clash", "task b and the exported decision d.json are different tasks.", ".openguildkit/decisions/b.json"),
            ("task-absent", "exported decisions name tasks absent from this copy: c.", None)])
        self.assertEqual([(item["code"], item["level"], item["path"]) for item in report.items],
                         [("evidence-unshared", "warning", ".openguildkit/tasks/a.json"),
                          ("task-id-clash", "warning", ".openguildkit/decisions/b.json")])

    def test_a_report_nobody_asked_for_keeps_nothing(self):
        from openguildkit.check_findings import Report

        report = Report(False)
        report.add("decision-stale", "error", "Stale.")
        report.sharing([("task-id-clash", "Clash.", None)])
        self.assertEqual(report.items, [])

    def test_every_kind_of_approval_problem_of_a_task_has_a_rule(self):
        from openguildkit.check_findings import Report, RULES

        report = Report(True)
        kinds = ("no-seal", "invalid-seal", "earlier-rules", "unsigned", "invalid-signature", "outside-history")
        report.tasks([{"id": f"t{number}", "status": "approved", "next": "Problem.", "severity": "error",
                       "approval_problem": kind} for number, kind in enumerate(kinds)]
                     + [{"id": "ok", "status": "approved", "next": "Fine.", "severity": "note",
                         "approval_problem": "earlier-signers"}, {"id": "u", "status": "unreadable", "next": "Damaged."}])
        self.assertEqual([item["code"] for item in report.items],
                         ["decision-seal-invalid", "decision-seal-invalid", "decision-stale", "decision-unsigned",
                          "decision-signature-invalid", "decision-outside-history", "task-unreadable"])
        self.assertTrue({item["code"] for item in report.items} <= set(RULES))
        self.assertEqual({item["path"] for item in report.items if item["code"] == "task-unreadable"},
                         {".openguildkit/tasks/u.json"})


RULE_LIKE = re.compile(r"^(?:decision|instructions|host|catalog|task|source|brain|approvals|evidence|guard|policy)-[a-z]+(?:-[a-z]+)*$")
# The modules that write a rule code, and the words of theirs that look like one and are not: the `task decision-payload`
# command, and the kind of sharing issue that is not a finding.
WRITERS = ("check_findings.py", "check_cli.py", "cli.py", "guard.py", "lock.py", "org_policy.py", "project.py",
           "project_instructions.py", "requester.py", "tasks_cli.py")
NOT_CODES = {"decision-payload", "task-absent"}


def used_codes() -> Counter:
    """How many times each word that looks like a rule code is written in the modules that write one."""
    found = Counter()
    for name in WRITERS:
        tree = ast.parse((REPO / "src" / "openguildkit" / name).read_text(encoding="utf-8"))
        found.update(node.value for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and isinstance(node.value, str) and RULE_LIKE.match(node.value))
    return Counter({word: count for word, count in found.items() if word not in NOT_CODES})


class RuleTableTests(unittest.TestCase):
    def test_every_code_the_package_writes_has_a_rule_and_every_rule_is_written_somewhere(self):
        from openguildkit.check_findings import RULES

        written = used_codes()
        self.assertEqual(sorted(set(written) - set(RULES)), [], "a code with no rule")
        # Each rule is in the table once, and written by a command at least once more.
        self.assertEqual(sorted(code for code in RULES if written[code] < 2), [], "a rule no command writes")

    def test_each_rule_has_its_title_its_sentence_and_its_heading_on_the_page(self):
        from openguildkit.check_findings import RULES

        page = (REPO / "docs" / "sarif.md").read_text(encoding="utf-8")
        headings = re.findall(r"^#### `([a-z-]+)`$", page, re.MULTILINE)
        self.assertEqual(sorted(headings), sorted(RULES))
        self.assertEqual(len(headings), len(set(headings)))
        for code, rule in RULES.items():
            with self.subTest(code=code):
                self.assertEqual(rule["help"], f"sarif.md#{code}")
                self.assertTrue(rule["name"].strip() and rule["description"].strip().endswith("."))

    def test_the_page_shows_what_the_commands_do_with_the_option(self):
        page = (REPO / "docs" / "sarif.md").read_text(encoding="utf-8")
        for command in ("openguildkit check --format sarif", "openguildkit guard --ci --base origin/main --format sarif"):
            self.assertIn(command, page)
        self.assertIn("security-events: write", page)
        self.assertIn("github/codeql-action/upload-sarif", page)


class OptionTests(SarifProject):
    def test_sarif_and_json_together_are_refused_with_what_to_type(self):
        self.init()
        result = self.cli("guard", "--ci", "--format", "sarif", "--json", code=1)
        self.assertEqual(result.stdout, "")
        self.assertIn("--format sarif", result.stderr)
        self.assertIn("--json", result.stderr)
        self.assertIn("one of them", result.stderr)
        self.assertTrue(result.stderr.startswith("OpenGuildKit:"), result.stderr)

    def test_sarif_without_ci_is_refused_and_names_the_command_that_writes_it(self):
        self.init()
        for arguments in (("guard",), ("guard", "--hook", "prompt")):
            with self.subTest(arguments=arguments):
                result = self.cli(*arguments, "--format", "sarif", code=1)
                self.assertEqual(result.stdout, "")
                self.assertIn("openguildkit guard --ci --format sarif", result.stderr)

    def test_the_default_is_text_and_the_choices_are_text_and_sarif(self):
        parser = command_parser()
        for command in (("check",), ("guard", "--ci")):
            with self.subTest(command=command):
                self.assertEqual(parser.parse_args([*command]).format, "text")
                self.assertEqual(parser.parse_args([*command, "--format", "sarif"]).format, "sarif")
        refused = self.cli("check", "--format", "xml", code=2)
        self.assertIn("invalid choice: 'xml'", refused.stderr)

    def test_the_check_command_has_no_json_form_to_refuse(self):
        self.init()
        self.assertEqual(self.cli("check", "--json", code=2).stdout, "")


if __name__ == "__main__":
    unittest.main()
