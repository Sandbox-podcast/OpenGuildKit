"""An approval that no longer holds, and the person's way to withdraw one (issue #204).

One function judges an approval for every reader; after a rebase the task is consulted again under the same ID,
keeping the passes of unchanged boards; a person withdraws an approval at a terminal; only a change of rules, checks
or boards voids an approval; the edit hook checks every approved revision with one git call.
"""

import contextlib
import copy
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import decisions
from openguildkit.cli import _parser, main
from openguildkit.decisions import decision_payload, seal
from openguildkit.guard import covering_approvals
from openguildkit.hosts import CLAUDE_APPROVAL_RULES, _codex_rules
from openguildkit.project import load_profile, profile_fingerprint
from openguildkit.catalog import load_catalog
from openguildkit.storage import read_json, write_json
from openguildkit.tasks import kept_passes
from openguildkit.webui import Refused, check_request
from tests.test_hosts import claude_denies, codex_forbids

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
        write_json(self.root / "profile.json", {"name": "Support portal", "stack": ["Python"], "packs": [],
                                                "checks": [command], **profile})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.state = self.root / ".openguildkit"

    def run_cli(self, *arguments, code=0, typed=None, root=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            if typed is not None:
                stack.enter_context(patch("sys.stdin.isatty", return_value=True))
                stack.enter_context(patch("builtins.input", return_value=typed))
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            result = main(["--project", str(root or self.root), *map(str, arguments)])
        if code is not None:
            self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.email=dev@example.test", "-c", "user.name=Dev",
                        *arguments], check=True, capture_output=True)

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
        self.assertIn("openguildkit task revoke vb --by NAME --reason TEXT", error)
        self.assertNotIn("request changes", error.casefold())
        self.assertNotIn("--request-changes", error)

    def test_task_list_names_the_withdrawal_for_an_approval_that_cannot_complete_otherwise(self):
        row, = json.loads(self.run_cli("task", "list", "--json")[0])
        self.assertIn("Condition(s) of approval still open: security:1", row["next"])
        self.assertIn("the task cannot complete while one is open", row["next"])
        self.assertIn("openguildkit task revoke vb --by NAME --reason TEXT", row["next"])

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
        self.assertIn("Next: openguildkit task consult vb --answers FILE", error)
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
            check_request(_parser().parse_args(argv), argv, Path("/project"))
        self.assertIn("Withdrawing an approval needs the person at a terminal", str(refused.exception))


if __name__ == "__main__":
    unittest.main()
