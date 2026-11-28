"""The controls host apply writes, run as written: each hook command through the shell, each deny rule matched.

Nothing here starts an agent host. The hooks are read back from .claude/settings.json and .codex/hooks.json and run
by the shell with the input each host documents, through an openguildkit launcher on the PATH, as a host would run
them. The deny rules are read back from the files and matched with the syntax each host documents
(integrations/README.md, "What the host documentation says"). examples/host-validation/README.md gives the steps of
the live session that completes this.
"""

import contextlib
import fnmatch
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.storage import write_json
from tests.support import openguildkit_on_path, run_cli
from tests.test_hosts import AGENT_FORMS, claude_denies, codex_forbids

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"
# Inputs as the hosts document them; the hosts add fields such as the session, which the guard ignores.
PROMPT = {"hook_event_name": "UserPromptSubmit", "prompt": "Add a status page", "session_id": "s1"}
EDITS = {
    "claude-code": {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                    "tool_input": {"file_path": "app.py", "old_string": "a", "new_string": "b"}},
    "codex": {"hook_event_name": "PreToolUse", "tool_name": "apply_patch",
              "tool_input": {"command": "*** Begin Patch\n*** Update File: app.py\n@@\n-a\n+b\n*** End Patch\n"}},
}
SETTINGS = {"claude-code": Path(".claude") / "settings.json", "codex": Path(".codex") / "hooks.json"}
# The command lines only the person runs, one or more per deny rule host apply writes. The withdrawal command of
# an approval joins this list once it exists.
PERSON_ONLY = (
    "openguildkit task decide t --approve --by A --reason B",
    "openguildkit --project . task decide t --approve --by A --reason B",
    "python -m openguildkit task decide t --approve --by A --reason B",
    "python -m openguildkit --project . task decide t --approve --by A --reason B",
    "python3 -m openguildkit task decide t --approve --by A --reason B",
    "python3 -m openguildkit --project ./ task decide t --approve --by A --reason B",
    "py -m openguildkit task decide t --approve",
    "py -m openguildkit --project . task decide t --approve",
    ".venv/bin/openguildkit task decide t --approve --by A --reason B",
    "openguildkit task waive t security:1 --by A --reason B",
    "openguildkit task revoke t --by A --reason B",
    "python -m openguildkit task revoke t --by A --reason B",
    "python3 -m openguildkit task revoke t --by A --reason B",
    "python3 -m openguildkit --project . task revoke t --by A --reason B",
    "python -m openguildkit task waive t security:1 --by A --reason B",
    "openguildkit task authorize t --action publish --target example.test --allow --by A --reason B",
    "python3 -m openguildkit task authorize t --action publish --target example.test --allow --by A --reason B",
    "script -q /dev/null openguildkit task decide t --approve",
    "expect -c 'spawn openguildkit task decide t --approve'",
    "unbuffer openguildkit task decide t --approve",
    "tmux new-session -d openguildkit task decide t --approve",
    "screen -dm openguildkit task decide t --approve",
    "python3 -c 'import pty; pty.spawn([\"openguildkit\"])'",
    "python3 -c 'import os, pty; pty.fork()'",
    "python3 -c 'import os; os.openpty()'",
    "python3 -c 'import pexpect; pexpect.spawn(\"openguildkit\")'",
    "python3 -c 'import ptyprocess'",
)
# The files only the person or the CLI's own commands change, one or more per Edit rule.
PERSON_FILES = (
    ".openguildkit/tasks/t.json", ".openguildkit/decisions/t.json", ".openguildkit/project.json",
    ".openguildkit/catalog.lock.json", ".claude/settings.json", ".claude/settings.local.json",
    ".openguildkit/alerts.json", ".openguildkit/catalog/boards/security.json", "keys/allowed_signers",
)
AGENT_FILES = ("app.py", "README.md", ".openguildkit/answers.json", "keys/README.md")


def claude_edit_denies(path: str, rule: str) -> bool:
    """Claude Code Edit rules: /PATTERN is relative to the project root, ** spans folders."""
    match = re.fullmatch(r"Edit\(/(.+)\)", rule)
    return bool(match) and fnmatch.fnmatchcase(path, match.group(1))


class WrittenHookTests(unittest.TestCase):
    """The hook commands of the host files, run by the shell as the host runs them."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        openguildkit_on_path(self)
        self.environment = {**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONIOENCODING": "utf-8"}

    def project(self, host: str, guard: str) -> Path:
        root = self.base / f"{host}-{guard}"
        root.mkdir()
        (root / "app.py").write_text("a\n", encoding="utf-8")
        run_cli(root, "init", "--answers", self.answers(root, host=host, guard=guard))
        run_cli(root, "host", "apply")
        return root

    def answers(self, root: Path, **extra) -> Path:
        write_json(root / "answers.json", {**json.loads((EXAMPLE / "profile.json").read_text()), **extra})
        return root / "answers.json"

    def written_command(self, root: Path, host: str, event: str, tool: str | None = None) -> str:
        """The command of the hook the host would run for this event and tool, read from its settings file."""
        hooks = json.loads((root / SETTINGS[host]).read_text(encoding="utf-8"))["hooks"]
        commands = [handler["command"] for group in hooks[event]
                    if tool is None or re.fullmatch(group.get("matcher", ".*"), tool)
                    for handler in group["hooks"] if handler.get("type") == "command"]
        self.assertEqual(len(commands), 1, hooks)
        return commands[0]

    def run_hook(self, root: Path, command: str, hook_input: dict) -> subprocess.CompletedProcess:
        return subprocess.run(command, shell=True, cwd=root, env=self.environment, input=json.dumps(hook_input),
                              capture_output=True, text=True, encoding="utf-8", timeout=120)

    @unittest.skipUnless(os.name == "posix" or shutil.which("cmd"), "needs the platform shell")
    def test_each_host_reminds_the_agent_then_flags_or_refuses_an_edit_without_an_approved_task(self):
        for host, tool in (("claude-code", "Edit"), ("codex", "apply_patch")):
            for guard in ("observe", "enforce"):
                with self.subTest(host=host, guard=guard):
                    root = self.project(host, guard)
                    prompt = self.run_hook(root, self.written_command(root, host, "UserPromptSubmit"), PROMPT)
                    self.assertEqual(prompt.returncode, 0, prompt.stderr)
                    context = json.loads(prompt.stdout)["hookSpecificOutput"]
                    self.assertEqual(context["hookEventName"], "UserPromptSubmit")
                    self.assertIn("no approved task covers new work", context["additionalContext"])
                    edit = self.run_hook(root, self.written_command(root, host, "PreToolUse", tool), EDITS[host])
                    if guard == "enforce":
                        self.assertEqual((edit.returncode, edit.stdout), (2, ""))
                        self.assertIn("Edit refused for: app.py", edit.stderr)
                    else:
                        self.assertEqual(edit.returncode, 0, edit.stderr)
                        flagged = json.loads(edit.stdout)["hookSpecificOutput"]["additionalContext"]
                        self.assertIn("Edit flagged, not blocked (guard: observe): app.py", flagged)
                        self.assertNotIn("refused", flagged)

    @unittest.skipUnless(os.name == "posix" or shutil.which("cmd"), "needs the platform shell")
    def test_an_approved_task_lets_the_written_hook_through(self):
        root = self.project("claude-code", "enforce")
        run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        run_cli(root, "task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            main(["--project", str(root), "task", "template", TASK])
        review = {"consultation_id": json.loads(stdout.getvalue())["consultation_id"],
                  **json.loads((EXAMPLE / "review.json").read_text())}
        write_json(root / "review.json", review)
        run_cli(root, "task", "review", TASK, "--file", root / "review.json")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
            run_cli(root, "task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        edit = self.run_hook(root, self.written_command(root, "claude-code", "PreToolUse", "Write"), EDITS["claude-code"])
        self.assertEqual(edit.returncode, 0, edit.stderr)
        self.assertIn(f"approved work in progress: {TASK}", json.loads(edit.stdout)["hookSpecificOutput"]["additionalContext"])


class WrittenDenyRuleTests(unittest.TestCase):
    """Each deny rule host apply writes stops a command or a file only the person handles, and nothing else."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        openguildkit_on_path(self)
        (self.root / "keys").mkdir()
        (self.root / "keys" / "allowed_signers").write_text("pat@example.org ssh-ed25519 AAAA\n", encoding="utf-8")

    def apply(self, host: str) -> None:
        write_json(self.root / "answers.json", {"personal_data": "no", 
            "name": "Portal", "stack": ["Python"], "host": host, "guard": "enforce",
            "approval": {"mode": "signed", "allowed_signers": "keys/allowed_signers", "approvers": ["pat@example.org"]}})
        for arguments in (("init", "--answers", self.root / "answers.json"), ("host", "apply")):
            run_cli(self.root, *arguments)

    def test_each_claude_code_rule_targets_the_command_or_file_it_is_written_for(self):
        self.apply("claude-code")
        deny = json.loads((self.root / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]["deny"]
        bash = [rule for rule in deny if rule.startswith("Bash(")]
        edit = [rule for rule in deny if rule.startswith("Edit(")]
        self.assertEqual(set(deny) - set(bash) - set(edit), {"WebSearch", "WebFetch"})
        for rule in bash:
            with self.subTest(rule=rule):
                self.assertTrue(any(claude_denies(command, [rule]) for command in PERSON_ONLY), rule)
                self.assertFalse([command for command in AGENT_FORMS if claude_denies(command, [rule])])
        for rule in edit:
            with self.subTest(rule=rule):
                self.assertTrue(any(claude_edit_denies(path, rule) for path in PERSON_FILES), rule)
                self.assertFalse([path for path in AGENT_FILES if claude_edit_denies(path, rule)])
        for command in PERSON_ONLY:
            self.assertTrue(claude_denies(command, bash), command)
        for path in PERSON_FILES:
            self.assertTrue(any(claude_edit_denies(path, rule) for rule in edit), path)

    def test_each_codex_rule_targets_the_command_it_is_written_for(self):
        self.apply("codex")
        text = (self.root / ".codex" / "rules" / "openguildkit.rules").read_text(encoding="utf-8")
        rules = [line for line in text.splitlines() if line.startswith("prefix_rule(")]
        self.assertTrue(rules)
        # A Codex prefix cannot look past the subcommand, so task authorize is forbidden whole, --deny included
        # (integrations/README.md says so): the agent records a refusal through the person.
        agent_forms = [command for command in AGENT_FORMS if " task authorize " not in command]
        self.assertTrue(codex_forbids("openguildkit task authorize t --action publish --deny --by A --reason B", text))
        for rule in rules:
            with self.subTest(rule=rule):
                self.assertIn('decision = "forbidden"', rule)
                self.assertTrue(any(codex_forbids(command, rule) for command in PERSON_ONLY), rule)
                self.assertFalse([command for command in agent_forms if codex_forbids(command, rule)])
        # A Codex rule is an exact prefix: the command lines that start with the program are all forbidden.
        for command in PERSON_ONLY:
            if not command.startswith(("python3 -c", ".venv/")):
                self.assertTrue(codex_forbids(command, text), command)


if __name__ == "__main__":
    unittest.main()
