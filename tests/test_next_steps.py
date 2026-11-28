"""A refused task command names the command that runs next, and a printed command pastes as typed (issue 40)."""

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import tools_cli, webui
from openguildkit.cli import command_parser
from openguildkit.hosts import approval_warning
from openguildkit.shell import shell_command, shell_word
from openguildkit.storage import write_json
from tests.support import run_cli

ANSWERS = {"kind": "bug", "surface": "service", "data": "internal", "research": "local", "concerns": ["none"],
           "context": "The CSV export drops the status column.", "outcome": "The export has a status column."}
# The extra arguments each task action needs to get past argparse; consult comes last, as it changes the status.
ARGUMENTS = {
    "questions": [], "route": ["--answers", "answers.json"], "brief": [], "template": [], "pass": ["security"],
    "submit": ["--file", "entry.json"], "progress": [], "review": ["--summary", "Summary."], "challenge": [],
    "deliberate": [], "blockers": [], "clear": ["security:1", "--evidence", "README.md", "--supports", "x", "--by", "A"],
    "waive": ["security:1", "--by", "A", "--reason", "r", "--scope", "s", "--until", "2099-01-01"],
    "respond": ["--file", "entry.json"], "decide": ["--approve", "--by", "A", "--reason", "r"],
    "revoke": ["--by", "A", "--reason", "r"], "handoff": [], "decision-payload": ["--by", "A", "--reason", "r"],
    "show": [], "checks": [], "verify": [], "result": ["--template"], "complete": [], "runs": [], "alerts": [],
    "export": [], "authorize": ["--action", "other", "--target", "example.test", "--deny", "--by", "A", "--reason", "r"],
    "retro": [], "diff-review": [], "consult": ["--answers", "answers.json"],
}
# The commands that can run on a task in each status.
RUNS_IN = {"draft": {"questions", "route", "consult"}, "consulting": {"pass", "submit", "progress", "review", "consult"}}
# A reason with every character a shell reads in a double-quoted word, and both quotes.
REASON = "Billed at $5 per `ogk_page` view, \"net\" of the customer's $(ogk_discount) and \\n"


def task_actions() -> set[str]:
    def choices(parser):
        return next(action.choices for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    return set(choices(choices(command_parser())["task"]))


def powershell_words(line: str) -> list[str]:
    """Split a line as PowerShell reads bare and single-quoted words, the only forms shell_word writes."""
    quotes = "'\u2018\u2019\u201a\u201b"
    words, index = [], 0
    while index < len(line):
        if line[index] == " ":
            index += 1
            continue
        word = ""
        while index < len(line) and line[index] != " ":
            if line[index] not in quotes:
                word += line[index]
                index += 1
                continue
            index += 1
            # Inside single quotes nothing is read but a doubled quote, which stands for its second character.
            while line[index] not in quotes or index + 1 < len(line) and line[index + 1] in quotes:
                index += 1 if line[index] in quotes else 0
                word += line[index]
                index += 1
            index += 1
        words.append(word)
    return words


class Project(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        write_json(self.root / "setup.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.cli("init", "--answers", self.root / "setup.json")
        write_json(self.root / "answers.json", ANSWERS)
        write_json(self.root / "entry.json", {"id": "qa"})

    def cli(self, *arguments, code=0):
        """Run a command; a file name of the project folder is passed as its path."""
        words = [str(self.root / word) if str(word).endswith(".json") else str(word) for word in arguments]
        result = run_cli(self.root, *words, expect=code)
        return result.returncode, result.stdout, result.stderr


class StateRefusalTests(Project):
    def test_every_task_action_refused_on_a_draft_or_during_consultation_names_a_command_that_runs(self):
        self.assertEqual(task_actions() - {"new", "list"}, set(ARGUMENTS), "give the new action its arguments here")
        self.cli("task", "new", "Fix the CSV export of request statuses", "--id", "draft")
        self.cli("task", "new", "Fix the CSV export of request statuses", "--id", "open")
        self.cli("task", "consult", "open", "--answers", "answers.json")
        self.cli("task", "pass", "open", "security")
        for status, task_id in (("draft", "draft"), ("consulting", "open")):
            for action, extra in ARGUMENTS.items():
                with self.subTest(status=status, action=action):
                    code, _, error = self.cli("task", action, task_id, *extra, code=None)
                    if code == 0:
                        continue
                    named = set(re.findall(rf"openguildkit task ([a-z-]+) {task_id}\b", error))
                    self.assertTrue(named, error)
                    self.assertLessEqual(named, RUNS_IN[status], error)

    def test_the_brief_is_revised_during_the_consultation_and_the_passes_start_over(self):
        self.cli("task", "new", "Fix the export", "--id", "open")
        self.cli("task", "consult", "open", "--answers", "answers.json")
        self.cli("task", "pass", "open", "security")
        self.cli("task", "consult", "open", "--answers", "answers.json", "--brief", "Fix the CSV export of statuses")
        record = json.loads(self.cli("task", "show", "open")[1])
        self.assertEqual((record["brief"], record["status"]), ("Fix the CSV export of statuses", "consulting"))
        progress = json.loads(self.cli("task", "progress", "open", "--json")[1])
        self.assertEqual({item["status"] for item in progress}, {"missing"})

    def test_new_and_submit_say_what_comes_next(self):
        _, output, error = self.cli("task", "new", "Fix the export", "--id", "open")
        self.assertEqual(output, "open\n")
        # The steps of the README, in its order, with the folder Git ignores for the working files.
        steps = ["openguildkit task questions open;", "save the answers in .openguildkit/work/",
                 "openguildkit task questions open --answers FILE --follow-ups",
                 "openguildkit task route open --answers FILE", "openguildkit task consult open --answers FILE"]
        positions = [error.find(step) for step in steps]
        self.assertNotIn(-1, positions, error)
        self.assertEqual(positions, sorted(positions))
        self.cli("task", "consult", "open", "--answers", "answers.json")
        boards = json.loads(self.cli("task", "show", "open")[1])["consultation"]["boards"]
        template = {entry["id"]: entry for entry in json.loads(self.cli("task", "template", "open")[1])["boards"]}
        for index, board in enumerate(boards, start=1):
            self.cli("task", "pass", "open", board)
            write_json(self.root / f"{board}.json", filled(template[board]))
            _, output, error = self.cli("task", "submit", "open", "--file", f"{board}.json")
            self.assertEqual(output, "done\n")
            left = len(boards) - index
            if left:
                self.assertIn(f"{left} pass{'es' if left > 1 else ''} left: run the passes of "
                              f"{', '.join(boards[index:])} (openguildkit task pass open BOARD)", error)
            else:
                self.assertIn("Every pass is done: write the summary and run openguildkit task review open --summary",
                              error)

    def test_review_decide_and_export_say_what_comes_next(self):
        """Issue #529: task review, task decide and task export printed "reviewed", "approved" and a path, no next step."""
        self.cli("task", "new", "Fix the export", "--id", "open")
        self.cli("task", "consult", "open", "--answers", "answers.json")
        boards = json.loads(self.cli("task", "show", "open")[1])["consultation"]["boards"]
        template = {entry["id"]: entry for entry in json.loads(self.cli("task", "template", "open")[1])["boards"]}
        for board in boards:
            self.cli("task", "pass", "open", board)
            write_json(self.root / f"{board}.json", filled(template[board]))
            self.cli("task", "submit", "open", "--file", f"{board}.json")
        _, output, error = self.cli("task", "review", "open", "--summary", "The boards agree.")
        self.assertEqual(output, "reviewed\n")
        self.assertIn("Next: openguildkit task deliberate open", error)
        self.assertIn("openguildkit task challenge open", error)
        decided = run_cli(self.root, "task", "decide", "open", "--approve", "--by", "A", "--reason", "Agreed", typed="open")
        self.assertEqual(decided.stdout, "approved\n")
        self.assertIn("Next: openguildkit task handoff open", decided.stderr)
        _, output, error = self.cli("task", "export", "open")
        self.assertIn("Next: git add .openguildkit/decisions", error)

    def test_the_list_does_not_count_a_started_pass_as_pending(self):
        self.cli("task", "new", "Fix the export", "--id", "open")
        self.cli("task", "consult", "open", "--answers", "answers.json")
        self.cli("task", "pass", "open", "security")
        boards = json.loads(self.cli("task", "show", "open")[1])["consultation"]["boards"]
        others = ", ".join(board for board in boards if board != "security")
        listed = self.cli("task", "list")[1]
        self.assertIn(f"next: Board reviews pending: {others}; passes started, waiting for their entry: security.",
                      listed)


def filled(template: dict) -> dict:
    """A board entry with every field filled from the template's choices, and no evidence."""
    entry = json.loads(json.dumps(template))
    entry.update(recommendation=f"{template['id']} agrees with the fix.", evidence=[], open_questions=[])
    challenge = entry["challenge"]
    for lens in challenge["specialists"]:
        lens.update(finding="Nothing to add.", basis="assumption", evidence_refs=[])
    challenge.update(verdict="insufficient-evidence", confidence="low", alternative="Leave it.", failure_mode="None seen.",
                     verification="The export test.", blockers=[])
    return entry


class QuotingTests(Project):
    def test_one_quoting_function_serves_the_cli_the_tool_commands_and_the_local_server(self):
        for module in (webui, tools_cli):
            self.assertFalse(hasattr(module, "_quote"), module.__name__)
        root = Path("/work/my app")
        self.assertEqual(webui.terminal_command(root, ["task", "revoke", "t", "--reason", REASON]),
                         shell_command(["openguildkit", "--project", str(root), "task", "revoke", "t", "--reason", REASON]))
        args = argparse.Namespace(tool=["zendesk"], mock=False, community=False, read_only=False, log=REASON,
                                  settings=[], token_env=[])
        self.assertEqual(tools_cli._apply_command(args, "codex", [], {}),
                         shell_command(["openguildkit", "tools", "apply", "zendesk", "--host", "codex", "--log", REASON]))

    def test_a_quoted_word_reads_back_unchanged_in_a_posix_shell_and_in_powershell(self):
        for value in (REASON, "it\u2019s", "", "RUNNER~1", "~/notes", "a=~b", "=ls", "a,b", "@team", "C:\\Users\\a b",
                      "line\nbreak", "plain-word_1.json"):
            with self.subTest(value=value):
                self.assertEqual(shlex.split(shell_word(value, powershell=False)), [value])
                self.assertEqual(powershell_words(shell_word(value, powershell=True)), [value])
        self.assertEqual(shell_word("RUNNER~1", powershell=False), "RUNNER~1")
        self.assertEqual(shell_word("--reason", powershell=True), "--reason")

    @unittest.skipIf(os.name == "nt" or shutil.which("sh") is None, "needs a POSIX sh")
    def test_a_quoted_reason_reaches_a_real_shell_as_typed(self):
        printed = subprocess.run(["sh", "-c", f"printf '%s' {shell_word(REASON, powershell=False)}"],
                                 capture_output=True, text=True, check=True).stdout
        self.assertEqual(printed, REASON)

    def test_the_printed_consult_command_gives_back_the_reason_as_typed(self):
        self.cli("task", "new", "Fix the export", "--id", "q1")
        output = self.cli("task", "route", "q1", "--answers", "answers.json", "--add", "frontend",
                          "--reason", REASON)[1]
        line = next(line for line in output.splitlines() if line.startswith("Apply: "))[len("Apply: "):]
        typed = ["openguildkit", "task", "consult", "q1", "--answers", (self.root / "answers.json").as_posix(),
                 "--add", "frontend", "--reason", REASON]
        self.assertEqual(powershell_words(line) if os.name == "nt" else shlex.split(line), typed)
        if os.name != "nt" and shutil.which("sh"):
            # shlex expands nothing: a real shell shows what $ and backticks would do to a double-quoted reason.
            pasted = subprocess.run(["sh", "-c", f"printf '%s\\n' {line}"], capture_output=True, text=True).stdout
            self.assertEqual(pasted, "".join(f"{word}\n" for word in typed))


class ApprovalWarningTests(Project):
    def test_the_unsigned_approval_warning_names_the_command_that_requires_signatures(self):
        warning = approval_warning({"guard": "enforce"})
        self.assertNotIn('"approval": {', warning)
        start = warning.index("openguildkit profile set")
        command = warning[start:warning.index(" (https://", start)]
        self.assertEqual(command, "openguildkit profile set approval signed --signers PATH --approver NAME --by INITIALS "
                                  "--reason WHY")
        values = {"PATH": ".openguildkit/allowed_signers", "NAME": "camille@example.test", "WHY": "The guard enforces"}
        words = [values.get(word, word) for word in command.split()[1:]]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="signed"):
            self.cli(*words)
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["approval"]["mode"], "signed")
        self.assertIsNone(approval_warning({**profile, "guard": "enforce"}))


if __name__ == "__main__":
    unittest.main()
