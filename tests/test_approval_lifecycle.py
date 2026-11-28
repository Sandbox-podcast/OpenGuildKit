"""An approval that no longer holds, and the person's way to withdraw one (issue #204).

One function judges an approval for every reader; after a rebase the task is consulted again under the same ID,
keeping the passes of unchanged boards; a person withdraws an approval at a terminal; only a change of rules, checks
or boards voids an approval; the edit hook checks every approved revision with one git call.
"""

import copy
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock, decisions
from openguildkit.cli import command_parser, main
from openguildkit.decisions import decision_payload, seal
from openguildkit.guard import covering_approvals
from openguildkit.hosts import CLAUDE_APPROVAL_RULES, _codex_rules
from openguildkit.project import STATE_DIR, load_profile, project_root
from openguildkit.project_rules import profile_fingerprint
from openguildkit.catalog import load_catalog
from openguildkit.storage import read_json, write_json
from openguildkit.tasks_review import kept_passes
from openguildkit.webui import Refused, check_request
from tests.test_hosts import claude_denies, codex_forbids
from tests.support import CapturedCli, run_cli, subprocess_environment

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
NEXT = re.compile(r'openguildkit task ([a-z-]+) (?:"BRIEF" --follows )?([a-z0-9-]+)')


class ApprovalCase(unittest.TestCase):
    """A project with one approved task, in a Git repository when the test needs one."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "project"
        self.root.mkdir()
        self.copies = Path(temporary.name)

    def init(self, **profile):
        command = f'"{sys.executable}" -c "print(1)"'
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Support portal", "stack": ["Python"], "packs": [],
                                                "checks": [command], **profile})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.state = self.root / ".openguildkit"

    def run_cli(self, *arguments, code=0, typed=None, root=None):
        result = run_cli(root or self.root, *arguments, expect=code, typed=typed)
        return result.stdout, result.stderr

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True)

    def approve(self, task_id, verification_blocker=False):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", task_id)
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", task_id, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", task_id)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        if verification_blocker:
            security = next(entry for entry in review["boards"] if entry["id"] == "security")
            security["challenge"]["verdict"] = "block"
            security["challenge"]["blockers"] = [{
                "finding": "No test proves a user cannot read another user's request.", "owner": "Security lead",
                "clears_when": "An automated test with two synthetic accounts passes.", "phase": "verification"}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", task_id, "--file", self.root / "review.json")
        self.run_cli("task", "decide", task_id, "--approve", "--by", "Camille", "--reason", "Agreed", typed=task_id)

    def task(self, task_id):
        return read_json(self.state / "tasks" / f"{task_id}.json")

    def covered(self, root=None):
        return json.loads(self.run_cli("guard", "--json", root=root)[0])["covered_by"]

    def follow(self, task_id, texts):
        """Run each command a message names, each in its own copy of the project, and return what failed."""
        failed = []
        for action, target in sorted({match for text in texts for match in NEXT.findall(text)}):
            copy_root = self.copies / f"copy-{action}-{len(failed)}-{target}"
            shutil.copytree(self.root, copy_root)
            arguments, typed = {
                "consult": (["--answers", copy_root / "answers.json"], None),
                "revoke": (["--by", "Camille", "--reason", "The condition cannot be met."], target),
                "clear": (["security:1", "--evidence", "README.md", "--supports", "Two accounts are tested.",
                           "--by", "Camille"], target),
                "handoff": ([], None),
            }.get(action, (None, None))
            if action == "new":
                command = ["task", "new", "Follow-up work.", "--follows", target, "--id", "follow-up"]
            elif arguments is None:
                failed.append(f"no way to run task {action} in this test")
                continue
            else:
                command = ["task", action, target, *arguments]
            _, error = self.run_cli(*command, code=None, typed=typed, root=copy_root)
            if error.startswith("OpenGuildKit:") and "Type" not in error:
                failed.append(f"task {action} {target}: {error.strip()}")
        return failed


@unittest.skipIf(shutil.which("git") is None, "needs git")
class RebaseTests(ApprovalCase):
    def rebased(self):
        """An approval given on a feature branch, then the branch rebased on a new upstream commit."""
        self.git("init", "-q", "-b", "main")
        self.init()
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        (self.root / "status.py").write_text("STATUS = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "feature")
        self.approve("rb")
        self.assertEqual(self.covered(), ["rb"])
        self.git("checkout", "-q", "main")
        (self.root / "upstream.py").write_text("UPSTREAM = 1\n", encoding="utf-8")
        self.git("add", "upstream.py")
        self.git("commit", "-q", "-m", "upstream")
        self.git("checkout", "-q", "feature")
        self.git("rebase", "-q", "main")
        return decisions.outside_history_message("rb", self.task("rb")["decision"]["base_revision"]["commit"])

    def test_every_reader_gives_the_same_message_after_a_rebase(self):
        message = self.rebased()
        self.assertIn("Consult it again with openguildkit task consult rb", message)
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual((row["approval_problem"], row["severity"], row["next"]), ("outside-history", "error", message))
        self.assertIn(f"rb: {message}", self.run_cli("check", code=1)[1])
        for action in ("verify", "handoff", "export", "complete"):
            with self.subTest(action=action):
                self.assertEqual(self.run_cli("task", action, "rb", code=1)[1], f"OpenGuildKit: {message}\n")
        _, error = self.run_cli("task", "result", "rb", "--file", self.root / "answers.json", code=1)
        self.assertEqual(error, f"OpenGuildKit: {message}\n")
        _, error = self.run_cli("task", "decide", "rb", "--request-changes", "--by", "Camille", "--reason", "x", code=1)
        self.assertIn(f"the approval no longer holds. {message}", error)
        self.assertEqual(self.covered(), [])

    def test_consulting_again_reopens_the_task_and_keeps_every_unchanged_pass(self):
        message = self.rebased()
        output, _ = self.run_cli("task", "consult", "rb", "--answers", self.root / "answers.json")
        self.assertIn("## Passes kept from the approved round", output)
        self.assertIn("Every pass is kept: run openguildkit task review rb --summary TEXT", output)
        task = self.task("rb")
        self.assertEqual(task["status"], "consulting")
        self.assertEqual(task["rounds"][-1]["reopened"], message)
        self.assertEqual(task["rounds"][-1]["decision"]["outcome"], "approved")
        progress = json.loads(self.run_cli("task", "progress", "rb", "--json")[0])
        self.assertEqual({item["status"] for item in progress}, {"done"})
        self.run_cli("task", "review", "rb", "--summary", "The same scope after the rebase.")
        self.assertIn("Passes kept from the approved round", self.run_cli("task", "challenge", "rb")[0])
        self.run_cli("task", "decide", "rb", "--approve", "--by", "Camille", "--reason", "Same scope", typed="rb")
        self.assertEqual(self.covered(), ["rb"])
        self.run_cli("check")

    def test_every_next_printed_after_a_rebase_runs(self):
        self.rebased()
        texts = [json.loads(self.run_cli("task", "list", "--json")[0])[0]["next"], self.run_cli("check", code=1)[1]]
        for action in ("verify", "handoff", "export"):
            texts.append(self.run_cli("task", action, "rb", code=1)[1])
        texts.append(self.run_cli("task", "decide", "rb", "--request-changes", "--by", "C", "--reason", "x", code=1)[1])
        self.assertEqual(sorted({match[0] for text in texts for match in NEXT.findall(text)}), ["consult", "new"])
        self.assertEqual(self.follow("rb", texts), [])


    def test_the_reconsult_command_printed_after_a_rebase_runs_as_it_is_without_a_terminal(self):
        message = self.rebased()
        command = re.search(r"openguildkit task consult rb[^,(]*", message).group(0).strip()
        self.assertEqual(command, "openguildkit task consult rb --reuse-answers")
        answers = self.task("rb")["answers"]
        result = subprocess.run([sys.executable, "-m", "openguildkit", *shlex.split(command)[1:]], cwd=self.root,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=120,
                                env=subprocess_environment({"PYTHONPATH": os.pathsep.join(
                                    [str(REPO / "src"), os.environ.get("PYTHONPATH", "")])}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## Passes kept from the approved round", result.stdout)
        task = self.task("rb")
        self.assertEqual((task["status"], task["answers"]), ("consulting", answers))

    def test_every_reconsult_message_gives_the_one_command(self):
        texts = [self.rebased(), self.run_cli("check", code=1)[1]]
        self.run_cli("task", "consult", "rb", "--reuse-answers")
        self.run_cli("task", "review", "rb", "--summary", "The same scope after the rebase.")
        self.run_cli("task", "decide", "rb", "--request-changes", "--by", "AM", "--reason", "Add the empty state")
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        texts.append(row["next"])
        texts.append(self.run_cli("task", "handoff", "rb", code=1)[1])
        texts.append(self.run_cli("task", "decide", "rb", "--request-changes", "--by", "AM", "--reason", "x", code=1)[1])
        commands = {match.strip() for text in texts for match in re.findall(r"task consult rb[^,.;(]*", text)}
        self.assertEqual(commands, {"task consult rb --reuse-answers"}, texts)
        self.assertEqual(row["decided"], "changes requested by AM")
        self.assertIn("rb [changes-requested, changes requested by AM]", self.run_cli("task", "list")[0])


class StuckApprovalTests(ApprovalCase):
    """An approval with a condition that only evidence clears, in a project that allows no waiver."""

    def setUp(self):
        super().setUp()
        self.init()
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.approve("vb", verification_blocker=True)

    def test_a_waiver_refused_by_the_policy_names_only_steps_an_approved_task_can_take(self):
        _, error = self.run_cli("task", "waive", "vb", "security:1", "--by", "Camille", "--reason", "Pilot",
                                "--scope", "Internal", "--until", "2099-01-01", code=1, typed="vb")
        self.assertIn("allows no waiver", error)
        self.assertIn("openguildkit task clear vb security:1", error)
        self.assertIn("openguildkit task revoke vb --by INITIALS --reason TEXT", error)
        self.assertNotIn("request changes", error.casefold())
        self.assertNotIn("--request-changes", error)

    def test_task_list_names_the_withdrawal_for_an_approval_that_cannot_complete_otherwise(self):
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertIn("Condition of approval still open: security:1", row["next"])
        self.assertIn("the task cannot complete while one is open", row["next"])
        self.assertIn("openguildkit task revoke vb --by INITIALS --reason TEXT", row["next"])

    def test_the_person_withdraws_the_approval_at_a_terminal_and_the_guard_stops_counting_it(self):
        self.assertEqual(self.covered(), ["vb"])
        revoke = ["task", "revoke", "vb", "--by", "Camille", "--reason", "The test account cannot be created."]
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli(*revoke, code=1)
        self.assertIn("in their own terminal", error)
        self.run_cli(*revoke, code=1, typed="other")
        self.assertEqual(self.task("vb")["status"], "approved")
        output, error = self.run_cli(*revoke, typed="vb")
        self.assertEqual(output, "changes-requested\n")
        self.assertIn("Next: openguildkit task consult vb --reuse-answers", error)
        task = self.task("vb")
        self.assertEqual((task["status"], task["decision"]["by"]), ("changes-requested", "Camille"))
        withdrawn = task["rounds"][-1]
        self.assertEqual(withdrawn["decision"]["outcome"], "approved")
        self.assertEqual({key: withdrawn["revoked"][key] for key in ("by", "reason")},
                         {"by": "Camille", "reason": "The test account cannot be created."})
        self.assertEqual(self.covered(), [])
        self.run_cli(*revoke, code=1, typed="vb")
        self.run_cli("task", "consult", "vb", "--answers", self.root / "answers.json")
        task = self.task("vb")
        self.assertEqual((task["status"], len(task["rounds"])), ("consulting", 1))
        self.assertNotIn("passes", task)

    def test_task_list_names_who_withdrew_and_who_had_approved(self):
        self.run_cli("task", "revoke", "vb", "--by", "T O", "--reason", "Cannot be met.", typed="vb")
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertEqual((row["owner"], row["decided"]), ("T O", "withdrawn by T O (approved by Camille)"))
        self.assertIn("vb [changes-requested, withdrawn by T O (approved by Camille)]", self.run_cli("task", "list")[0])
        # --owner filters on who took the current decision: here the withdrawal.
        self.assertEqual([row["id"] for row in json.loads(self.run_cli("task", "list", "--owner", "t o", "--json")[0])],
                         ["vb"])
        self.assertEqual(json.loads(self.run_cli("task", "list", "--owner", "Camille", "--json")[0]), [])

    def test_every_next_printed_on_a_stuck_approval_runs(self):
        texts = [json.loads(self.run_cli("task", "list", "--json")[0])[0]["next"]]
        texts.append(self.run_cli("task", "waive", "vb", "security:1", "--by", "Camille", "--reason", "Pilot",
                                  "--scope", "Internal", "--until", "2099-01-01", code=1, typed="vb")[1])
        texts.append(self.run_cli("task", "decide", "vb", "--request-changes", "--by", "C", "--reason", "x", code=1)[1])
        texts.append(self.run_cli("task", "consult", "vb", "--answers", self.root / "answers.json", code=1)[1])
        self.assertEqual(sorted({match[0] for text in texts for match in NEXT.findall(text)}),
                         ["clear", "handoff", "revoke"])
        self.assertEqual(self.follow("vb", texts), [])
        after = self.run_cli("task", "revoke", "vb", "--by", "Camille", "--reason", "Cannot be met.", typed="vb")[1]
        self.assertEqual(self.follow("vb", [after]), [])

    def test_a_completed_task_keeps_its_approval(self):
        task = self.task("vb")
        write_json(self.state / "tasks" / "vb.json", {**task, "status": "done", "completed_at": task["decision"]["at"],
                                                       "result": {"checks": [], "closing": {"open_points": []}}})
        _, error = self.run_cli("task", "revoke", "vb", "--by", "Camille", "--reason", "Late.", code=1, typed="vb")
        self.assertIn("--follows vb", error)


class WaiverExpiryTests(ApprovalCase):
    """A waiver ends on its until day, by the real clock: its blocker is open again after it (issue #284)."""

    def setUp(self):
        super().setUp()
        self.until = (clock.real_today() + timedelta(days=10)).isoformat()
        self.later = clock.real_today() + timedelta(days=40)

    def waive(self, task_id):
        self.run_cli("task", "waive", task_id, "security:1", "--by", "Camille", "--reason", "Internal pilot",
                     "--scope", "Pilot users", "--until", self.until, typed=task_id)

    def expired(self):
        return patch.object(clock, "real_today", return_value=self.later)

    def test_an_expired_waiver_of_a_condition_opens_it_again(self):
        self.init(waivers={"allowed_by": ["Camille"], "max_days": 30})
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.approve("vb", verification_blocker=True)
        self.waive("vb")
        self.assertIn("[waived by Camille]", self.run_cli("task", "blockers", "vb")[0])
        with self.expired():
            output, _ = self.run_cli("task", "blockers", "vb")
            self.assertIn(f"security:1 [waiver expired on {self.until}] (due at verification)", output)
            row, = json.loads(self.run_cli("task", "list", "--json")[0])
            self.assertIn(f"The waiver of security:1 expired on {self.until}, so the blocker is open again", row["next"])
            for step in ("openguildkit task clear vb security:1", "openguildkit task waive vb security:1",
                         "openguildkit task revoke vb --by INITIALS --reason TEXT"):
                self.assertIn(step, row["next"])
            _, error = self.run_cli("task", "complete", "vb", code=1)
            self.assertIn(f"Verification blocker security:1: The waiver of security:1 expired on {self.until}", error)
            self.until = (self.later + timedelta(days=10)).isoformat()
            with patch.object(clock, "real_now", return_value=clock.real_now() + timedelta(days=40)):
                self.waive("vb")
            resolution = self.task("vb")["verification_blocker_resolutions"]["security:1"]
            self.assertEqual((resolution["until"], resolution["replaces"]["kind"]), (self.until, "waived"))
            self.assertIn("[waived by Camille]", self.run_cli("task", "blockers", "vb")[0])

    def test_an_expired_waiver_the_approval_rested_on_leads_to_the_withdrawal(self):
        self.init(waivers={"allowed_by": ["Camille"], "max_days": 30})
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "ab")
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        self.run_cli("task", "consult", "ab", "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", "ab")[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        security = next(entry for entry in review["boards"] if entry["id"] == "security")
        security["challenge"].update(verdict="block", blockers=[{
            "finding": "Retention is not decided.", "owner": "DPO", "clears_when": "The period is recorded."}])
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", "ab", "--file", self.root / "review.json")
        self.waive("ab")
        self.run_cli("task", "decide", "ab", "--approve", "--by", "Camille", "--reason", "Agreed", typed="ab")
        with self.expired():
            row, = json.loads(self.run_cli("task", "list", "--json")[0])
            self.assertIn("and the approval rested on it: the person withdraws the approval "
                          "(openguildkit task revoke ab --by INITIALS --reason TEXT)", row["next"])
            _, error = self.run_cli("task", "complete", "ab", code=1)
            self.assertIn(f"Blocker security:1: The waiver of security:1 expired on {self.until}", error)
            _, error = self.run_cli("task", "waive", "ab", "security:1", "--by", "Camille", "--reason", "Again",
                                    "--scope", "Pilot", "--until", self.until, code=1, typed="ab")
            self.assertIn("the approval rested on it", error)

    @unittest.skipIf(shutil.which("git") is None, "needs git")
    def test_guard_ci_refuses_a_record_whose_waiver_expired(self):
        self.git("init", "-q", "-b", "main")
        self.init(guard="enforce", waivers={"allowed_by": ["Camille"], "max_days": 30})
        (self.root / "README.md").write_text("Portal\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("checkout", "-q", "-b", "feature")
        self.approve("vb", verification_blocker=True)
        self.waive("vb")
        (self.root / "status.py").write_text("STATUS = 1\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "work")
        self.run_cli("task", "export", "vb")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "record")
        self.assertTrue(json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json")[0])["ok"])
        with self.expired():
            result = json.loads(self.run_cli("guard", "--ci", "--base", "main", "--json", code=1)[0])
        self.assertFalse(result["ok"])
        self.assertIn(f"the waiver of a blocker expired (security:1 on {self.until}) and task vb is not completed",
                      " ".join(result["problems"]))


class ProfileChangeTests(ApprovalCase):
    def setUp(self):
        super().setUp()
        self.init()
        self.approve("price-label")

    def test_a_new_tool_or_convention_leaves_the_approval_standing(self):
        self.run_cli("profile", "add", "tool", "Jira", "--by", "Sam", "--reason", "Tracker")
        self.run_cli("profile", "add", "convention", "Exports are CSV files encoded in UTF-8.", "--by", "Sam",
                     "--reason", "Team habit")
        self.run_cli("profile", "set", "guard", "enforce", "--by", "Sam", "--reason", "Audit")
        _, error = self.run_cli("task", "verify", "price-label")
        self.assertNotIn("earlier rules", error)
        self.run_cli("task", "handoff", "price-label")
        self.assertEqual(self.covered(), ["price-label"])
        self.run_cli("profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Unit tests")
        _, error = self.run_cli("task", "verify", "price-label", code=1)
        self.assertIn("recorded under earlier rules (checks changed)", error)

    def test_an_approval_sealed_under_the_earlier_fingerprint_holds_while_nothing_changed(self):
        catalog = load_catalog(self.state / "catalog")
        path = self.state / "tasks" / "price-label.json"
        task = read_json(path)
        task["profile_fingerprint"] = profile_fingerprint(load_profile(self.state, catalog), catalog, legacy=True)
        decision = task["decision"]
        decision["seal"] = seal(decision_payload(task, decision["by"], decision["reason"], decision["base_revision"]))
        write_json(path, task)
        self.run_cli("task", "handoff", "price-label")
        # Its exported record holds as well: the upgrade turns no record into earlier rules.
        self.run_cli("task", "export", "price-label")
        listed = json.loads(self.run_cli("task", "list", "--decisions", "--json")[0])
        self.assertEqual([row["problem"] for row in listed if row["task"] == "price-label"], [None])
        self.run_cli("profile", "add", "check", "python -m unittest", "--by", "Sam", "--reason", "Unit tests")
        self.assertIn("earlier rules", self.run_cli("task", "handoff", "price-label", code=1)[1])


class KeptPassTests(ApprovalCase):
    def test_only_the_passes_of_boards_whose_brief_is_unchanged_are_kept(self):
        self.init()
        self.approve("kp")
        task = self.task("kp")
        consultation = copy.deepcopy(task["consultation"])
        consultation["id"] = "new-consultation"
        consultation["board_briefs"]["security"]["rules"] = [
            {"pack": "team", "title": "Team", "rules": [{"id": "owner", "instruction": "Name an owner."}]}]
        consultation["review_template"]["boards"] = [
            {**item, "reviewer": "x"} if item["id"] == "legal" else item for item in consultation["review_template"]["boards"]]
        kept = kept_passes(task, consultation)
        self.assertEqual(kept["consultation_id"], "new-consultation")
        self.assertEqual(sorted(kept["boards"]), sorted(set(task["consultation"]["boards"]) - {"security", "legal"}))
        entry = kept["boards"]["product"]
        self.assertEqual((entry["status"], entry["kept_from"]), ("done", task["consultation"]["id"]))
        self.assertEqual(entry["entry"], next(item for item in task["review"]["boards"] if item["id"] == "product"))


@unittest.skipIf(shutil.which("git") is None, "needs git")
class GuardGitCallTests(ApprovalCase):
    def test_the_hook_checks_every_approved_revision_with_one_git_call(self):
        self.git("init", "-q", "-b", "main")
        self.init(guard="observe")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        for task_id in ("one", "two", "three"):
            self.approve(task_id)
        catalog = load_catalog(self.state / "catalog")
        profile = load_profile(self.state, catalog)
        calls = []
        real = subprocess.run

        def counted(command, *args, **kwargs):
            calls.append(command)
            return real(command, *args, **kwargs)

        with patch.object(decisions.subprocess, "run", side_effect=counted):
            covered = covering_approvals(self.root, self.state, profile, catalog)
        self.assertEqual(sorted(item["task"] for item in covered), ["one", "three", "two"])
        self.assertEqual([command[3] for command in calls if command[0] == "git"], ["rev-list"])
        self.git("commit", "-q", "--allow-empty", "--amend", "-m", "base, amended")
        with patch.object(decisions.subprocess, "run", side_effect=counted):
            calls.clear()
            self.assertEqual(covering_approvals(self.root, self.state, profile, catalog), [])
        self.assertEqual(len(calls), 1)


class PersonOnlyTests(unittest.TestCase):
    def test_withdrawing_an_approval_is_denied_to_the_agent_and_refused_by_the_page(self):
        for command in ("openguildkit task revoke t --by Camille --reason x",
                        "python3 -m openguildkit --project . task revoke t --by Camille --reason x"):
            self.assertTrue(claude_denies(command, CLAUDE_APPROVAL_RULES), command)
            self.assertTrue(codex_forbids(command, _codex_rules()), command)
        argv = ["task", "revoke", "t", "--by", "Camille", "--reason", "x"]
        with self.assertRaises(Refused) as refused:
            check_request(command_parser().parse_args(argv), argv, Path("/project"))
        self.assertIn("Withdrawing an approval needs the person at a terminal", str(refused.exception))


class WorkflowTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile_path = self.root / STATE_DIR / "project.json"
        self.input_path = self.root / "input.json"
        self.review_path = self.root / "review.json"
        self.task_id = "export-status"
        self.answers = {
            "kind": "feature",
            "surface": "customer",
            "data": "personal",
            "research": "public",
            "concerns": ["none"],
            "context": "Use test data. Keep the existing permission model.",
        }
        write_json(
            self.input_path,
            {"personal_data": "no", "name": "Support console", "sector": "general", "stack": ["Python"], "packs": ["python"]},
        )

    def init(self):
        self.run_cli("init", "--answers", self.input_path)

    def task(self):
        return read_json(self.root / STATE_DIR / "tasks" / f"{self.task_id}.json")

    def consult(self):
        write_json(self.input_path, self.answers)
        self.run_cli("task", "consult", self.task_id, "--answers", self.input_path)
        return self.task()["consultation"]

    def review(self):
        review = self.task()["consultation"]["review_template"]
        review["summary"] = "Export only the visible fields and test cross-account access."
        (self.root / "docs").mkdir(exist_ok=True)
        (self.root / "docs" / "permissions.md").write_text("# Permissions\n", encoding="utf-8")
        for board in review["boards"]:
            board["recommendation"] = "Cover the approved scope with a synthetic fixture."
            board["evidence"] = [{"source": "project-file", "ref": "docs/permissions.md", "supports": "The permission policy."}]
            challenge = board["challenge"]
            for specialist in challenge["specialists"]:
                specialist.update(finding="The permission policy requires scoped access.", basis="observed", evidence_refs=[1])
            challenge.update(
                verdict="revise",
                confidence="medium",
                alternative="Keep exports disabled until access is verified.",
                failure_mode="Cross-account access exposes a request.",
                verification="Verify the policy against an authorized synthetic fixture.",
            )
        write_json(self.review_path, review)
        self.run_cli("task", "review", self.task_id, "--file", self.review_path)

    def test_crlf_instructions_keep_their_newlines_and_team_text(self):
        agents = self.root / "AGENTS.md"
        claude = self.root / "CLAUDE.md"
        original_agents = b"# Team rules\r\n\r\nRun the existing tests.\r\n"
        original_claude = b"# Claude rules\r\n"
        agents.write_bytes(original_agents)
        claude.write_bytes(original_claude)
        self.init()
        before = agents.read_bytes()
        self.assertTrue(before.startswith(original_agents))
        self.assertTrue(claude.read_bytes().startswith(original_claude))
        self.assertIn(b"@AGENTS.md\r\n", claude.read_bytes())
        self.run_cli("check")
        self.run_cli("sync")
        self.assertEqual(before, agents.read_bytes())

    def test_approval_requires_correct_confirmation_and_current_scope(self):
        self.init()
        self.run_cli("task", "new", "Export request status.", "--id", self.task_id)
        consultation = self.consult()
        self.assertIn("security", consultation["boards"])
        self.assertEqual(consultation["scope"]["research"], "local-only")
        self.review()
        self.run_cli("task", "handoff", self.task_id, code=1)
        decide = ["task", "decide", self.task_id, "--approve", "--by", "Owner", "--reason", "Accept the scope"]
        with patch("sys.stdin.isatty", return_value=False):
            self.run_cli(*decide, code=1)
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="wrong-id"):
            self.run_cli(*decide, code=1)
        self.assertEqual(self.task()["status"], "reviewed")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=self.task_id):
            self.run_cli(*decide)
        output, _ = self.run_cli("task", "handoff", self.task_id)
        self.assertIn("Approved task handoff", output)
        exported, _ = self.run_cli("task", "export", self.task_id)
        profile = read_json(self.profile_path)
        # A check command is part of what an approval rests on; a convention is not (tests/test_approval_lifecycle.py).
        profile["checks"] = [*profile.get("checks", []), "python -m pytest tests/test_export.py"]
        write_json(self.profile_path, profile)
        self.run_cli("sync")
        message = f"The approval for {self.task_id} was recorded under earlier rules (checks changed)."
        for action in ("handoff", "export"):
            _, error = self.run_cli("task", action, self.task_id, code=1)
            self.assertIn(message, error)
            self.assertIn(f'--follows {self.task_id}', error)
        output, error = self.run_cli("task", "show", self.task_id)
        self.assertEqual(json.loads(output)["status"], "approved")
        self.assertIn(message, error)
        listing, _ = self.run_cli("task", "list", "--json")
        row, = json.loads(listing)
        self.assertEqual(row["approval_problem"], "earlier-rules")
        self.assertIn(message, row["next"])
        _, error = self.run_cli("check", code=1)
        self.assertIn(message, error)
        self.assertIn(exported.strip(), error)

    def test_a_consultation_checks_only_the_components_named_in_its_answers(self):
        profile = {"personal_data": "no", "name": "Shop", "components": [
            {"id": "web", "path": "apps/web", "stack": ["Next.js 14.2", "React 18"]},
            {"id": "api", "path": "services/api", "stack": ["Python", "Django"]},
        ]}
        write_json(self.input_path, profile)
        self.init()
        self.run_cli("task", "new", "Adjust the request status form.", "--id", self.task_id)
        self.answers["components"] = ["web"]
        consultation = self.consult()
        self.assertEqual([component["id"] for component in consultation["scope"]["components"]], ["web"])
        scope_packs = {pack["id"] for pack in consultation["scope"]["packs"]}
        self.assertIn("nextjs", scope_packs)
        self.assertNotIn("django", scope_packs)
        self.review()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=self.task_id):
            self.run_cli("task", "decide", self.task_id, "--approve", "--by", "Owner", "--reason", "Scope agreed")
        checks, _ = self.run_cli("task", "checks", self.task_id, "--json")
        ids = [check["id"] for check in json.loads(checks)]
        self.assertTrue(any(item.startswith("rule:nextjs/") for item in ids))
        self.assertFalse(any(item.startswith("rule:django/") for item in ids))

    def test_review_from_an_earlier_consultation_is_rejected(self):
        self.init()
        self.run_cli("task", "new", "Export request status.", "--id", self.task_id)
        old_consultation = self.consult()
        self.review()
        self.run_cli("task", "decide", self.task_id, "--request-changes", "--by", "Owner", "--reason", "Review retention")
        self.answers["context"] = "Review retention for the export as well."
        new_consultation = self.consult()
        self.assertEqual(old_consultation["boards"], new_consultation["boards"])
        self.assertNotEqual(old_consultation["id"], new_consultation["id"])
        self.assertEqual(new_consultation["scope"]["previous_decision"]["reason"], "Review retention")
        _, error = self.run_cli("task", "review", self.task_id, "--file", self.review_path, code=1)
        self.assertIn("belongs to another consultation", error)
        self.assertEqual(self.task()["status"], "consulting")

        self.review()
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=self.task_id):
            self.run_cli("task", "decide", self.task_id, "--approve", "--by", "Owner", "--reason", "Scope agreed")
        checks, _ = self.run_cli("task", "checks", self.task_id, "--json")
        rule = next(item["id"] for item in json.loads(checks) if item["kind"] == "rule" and not item["mandatory"])
        reason = "This rule applies after the deployment."
        write_json(self.input_path, {"revision": "abc1234",
                                    "checks": [{"check": rule, "status": "skipped", "reason": reason, "owner": "Owner"}]})
        self.run_cli("task", "result", self.task_id, "--file", self.input_path)
        output, _ = self.run_cli("task", "export", self.task_id)
        exported = read_json(self.root / output.strip())
        self.assertEqual(exported["boards"][0]["recommendation"], "Cover the approved scope with a synthetic fixture.")
        self.assertNotIn("evidence", exported["boards"][0])
        self.assertEqual(exported["rounds"][0]["decision"]["reason"], "Review retention")
        self.assertEqual(exported["result"]["check_exceptions"],
                         [{"check": rule, "status": "skipped", "reason": reason, "owner": "Owner"}])

    def test_catalog_dependencies_are_applied_before_dependent_rules(self):
        catalog = load_catalog()
        extra_pack = self.root / STATE_DIR / "catalog" / "packs" / "team-iso.json"
        write_json(
            extra_pack,
            {
                "id": "team-iso",
                "title": "Team ISMS",
                "version": "1.0.0",
                "description": "Follow the team's change review process.",
                "depends_on": ["iso-27001"],
                "rules": [{"id": "owner", "instruction": "Name a change owner.", "verification": "Read the change record."}],
                "sources": [],
            },
        )
        self.assertIn("iso-27001", catalog["packs"])
        write_json(self.input_path, {"personal_data": "no", "name": "Support console", "packs": ["team-iso"]})
        self.init()
        instructions = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertLess(instructions.index("iso-27001@"), instructions.index("team-iso@"))

    def test_redirected_output_uses_utf8_on_legacy_windows_locales(self):
        self.init()
        brief = "契約のステータスを表示する"
        self.run_cli("task", "new", brief, "--id", self.task_id)
        result = subprocess.run(
            [sys.executable, "-m", "openguildkit", "--project", str(self.root), "task", "show", self.task_id],
            env={**os.environ, "PYTHONIOENCODING": "cp1252"},
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["brief"], brief)

    def test_project_root_is_canonical_before_state_path_checks(self):
        nested = self.root / "nested"
        nested.mkdir()
        with patch("openguildkit.project.Path.cwd", return_value=nested / ".."):
            self.assertEqual(project_root(None), self.root.resolve())


if __name__ == "__main__":
    unittest.main()
