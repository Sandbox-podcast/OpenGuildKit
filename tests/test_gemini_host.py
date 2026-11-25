"""Gemini CLI as a host: the hook its documentation describes, what `host apply` writes for it, and what stays as it was.

The inputs are the ones the Gemini CLI documentation shows, with their source and the day they were read
(integrations/README.md, "Gemini CLI"). No Gemini CLI session is started here: the hook is run as the shell would run
it, with the documented input, and the settings are read back from the file the host reads.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.cli import _detected_host
from openguildkit.hosts import HOOK_HOSTS, HOSTS, host_controls
from openguildkit.project import BEGIN, init_questions
from openguildkit.storage import write_json
from tests.support import CapturedCli, openguildkit_on_path, run_cli

REPO = Path(__file__).resolve().parents[1]
README = REPO / "integrations" / "README.md"
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"
SETTINGS = Path(".gemini") / "settings.json"
# https://geminicli.com/docs/hooks/best-practices/ ("Hooks Best Practices", last updated Apr 10, 2026, read on
# 2026-11-25), section "Test hooks", the test input of a BeforeTool hook as the page shows it:
#   {
#     "session_id": "test-123",
#     "cwd": "/tmp/test",
#     "hook_event_name": "BeforeTool",
#     "tool_name": "write_file",
#     "tool_input": {
#       "file_path": "test.txt",
#       "content": "Test content"
#     }
#   }
WRITE_FILE = {"session_id": "test-123", "cwd": "/tmp/test", "hook_event_name": "BeforeTool", "tool_name": "write_file",
              "tool_input": {"file_path": "test.txt", "content": "Test content"}}
# https://geminicli.com/docs/reference/tools/ ("Tool argument keys", last updated Sep 1, 2026, read on 2026-11-25) lists
# the keys of replace: file_path, old_string, new_string, instruction, allow_multiple. No page shows a JSON input for
# it: this one is composed from those keys and from the common fields of https://geminicli.com/docs/hooks/reference/.
REPLACE = {"session_id": "test-123", "cwd": "/tmp/test", "hook_event_name": "BeforeTool", "tool_name": "replace",
           "tool_input": {"file_path": "app.py", "instruction": "Rename a", "old_string": "a", "new_string": "b"}}
# The reference page lists `prompt` as the field BeforeAgent adds to the common fields; also composed from the page.
PROMPT = {"session_id": "test-123", "cwd": "/tmp/test", "hook_event_name": "BeforeAgent", "prompt": "Add a status page"}
SH_LINE = re.compile(r"^printf '%s' '(?P<json>[^']+)' \| openguildkit guard --hook (?P<event>prompt|pre-edit)$")
PS_LINE = re.compile(r"^'(?P<json>[^']+)' \| openguildkit guard --hook (?P<event>prompt|pre-edit)$")


def approved_task(test, root: Path) -> None:
    """Approve the request-status task in the project, as the person does at a terminal."""
    run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
    run_cli(root, "task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
    consultation = json.loads(run_cli(root, "task", "template", TASK).stdout)["consultation_id"]
    write_json(root / "review.json", {"consultation_id": consultation, **json.loads((EXAMPLE / "review.json").read_text())})
    run_cli(root, "task", "review", TASK, "--file", root / "review.json")
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=TASK):
        run_cli(root, "task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")


class GeminiCase(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        on_path = patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit")
        on_path.start()
        self.addCleanup(on_path.stop)

    def init(self, guard="enforce", host="gemini-cli", **extra):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                                "guard": guard, "host": host, **extra})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def hook(self, event: str, hook_input: dict, root: Path | None = None):
        result = run_cli(root or self.root, "guard", "--hook", event, stdin=json.dumps(hook_input), expect=None)
        return result.returncode, result.stdout, result.stderr

    def settings(self) -> dict:
        return json.loads((self.root / SETTINGS).read_text(encoding="utf-8"))

    def board(self, **kwargs) -> dict:
        code = kwargs.get("code", 0)
        controls = json.loads(self.run_cli("host", "check", "--json", code=code)[0])
        return next(control for control in controls if control["id"] == "board")


class GeminiHookTests(GeminiCase):
    def test_enforce_refuses_a_write_with_the_input_the_documentation_shows(self):
        self.init("enforce")
        code, out, error = self.hook("pre-edit", WRITE_FILE)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("Edit refused for: test.txt", error)
        self.assertIn("openguildkit task new", error)

    def test_enforce_refuses_a_replace(self):
        self.init("enforce")
        code, out, error = self.hook("pre-edit", REPLACE)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("Edit refused for: app.py", error)

    def test_observe_flags_the_edit_for_the_person_and_lets_it_through(self):
        self.init("observe")
        for hook_input in (WRITE_FILE, REPLACE):
            with self.subTest(tool=hook_input["tool_name"]):
                code, out, error = self.hook("pre-edit", hook_input)
                self.assertEqual((code, error), (0, ""))
                answer = json.loads(out)
                # BeforeTool documents decision, reason, continue and systemMessage; additionalContext is documented
                # for BeforeAgent and AfterTool only, so the flag goes to the person.
                self.assertEqual(list(answer), ["systemMessage"])
                self.assertIn("Edit flagged, not blocked (guard: observe)", answer["systemMessage"])
                self.assertNotIn("refused", answer["systemMessage"])

    def test_an_approved_task_lets_the_edit_through_without_a_word(self):
        self.init("enforce")
        approved_task(self, self.root)
        for hook_input in (WRITE_FILE, REPLACE):
            with self.subTest(tool=hook_input["tool_name"]):
                self.assertEqual(self.hook("pre-edit", hook_input), (0, "", ""))

    def test_off_lets_everything_through(self):
        self.init("off")
        self.assertEqual(self.hook("pre-edit", WRITE_FILE), (0, "", ""))

    def test_the_request_hook_answers_in_the_format_of_before_agent(self):
        for guard in ("observe", "enforce"):
            with self.subTest(guard=guard):
                self.init(guard)
                code, out, error = self.hook("prompt", PROMPT)
                self.assertEqual((code, error), (0, ""))
                answer = json.loads(out)["hookSpecificOutput"]
                self.assertEqual(answer["hookEventName"], "BeforeAgent")
                self.assertIn("no approved task covers new work", answer["additionalContext"])
                shutil.rmtree(self.root / ".openguildkit")

    def test_the_request_hook_names_the_approved_task(self):
        self.init("enforce")
        approved_task(self, self.root)
        answer = json.loads(self.hook("prompt", PROMPT)[1])["hookSpecificOutput"]
        self.assertEqual(answer["hookEventName"], "BeforeAgent")
        self.assertIn(f"approved task(s) in progress: {TASK}", answer["additionalContext"])

    def test_claude_code_and_codex_keep_their_answers(self):
        self.init("observe", host="claude-code")
        claude = {"hook_event_name": "PreToolUse", "tool_name": "Edit",
                  "tool_input": {"file_path": "app.py", "old_string": "a", "new_string": "b"}}
        code, out, _ = self.hook("pre-edit", claude)
        answer = json.loads(out)["hookSpecificOutput"]
        self.assertEqual((code, answer["hookEventName"]), (0, "PreToolUse"))
        self.assertIn("Edit flagged, not blocked", answer["additionalContext"])
        answer = json.loads(self.hook("prompt", {"hook_event_name": "UserPromptSubmit", "prompt": "x"})[1])["hookSpecificOutput"]
        self.assertEqual(answer["hookEventName"], "UserPromptSubmit")

    def test_an_input_that_names_no_file_is_refused_in_enforce(self):
        self.init("enforce")
        code, out, error = self.hook("pre-edit", {**WRITE_FILE, "tool_input": {"content": "x"}})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("names no file to edit", error)

    def test_the_settings_of_the_host_are_protected_for_its_own_profile_only(self):
        self.init("enforce")
        approved_task(self, self.root)
        settings = {**WRITE_FILE, "tool_input": {"file_path": ".gemini/settings.json", "content": "{}"}}
        code, out, error = self.hook("pre-edit", settings)
        self.assertEqual((code, out), (2, ""))
        self.assertIn(".gemini/settings.json is written by the openguildkit commands", error)
        # Another project with the same file is unchanged: the edit is work an approved task covers.
        other = self.root / "other"
        other.mkdir()
        write_json(other / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                            "guard": "enforce", "host": "claude-code"})
        run_cli(other, "init", "--answers", other / "answers.json")
        approved_task(self, other)
        self.assertEqual(self.hook("pre-edit", settings, other), (0, "", ""))

    def test_the_hook_runs_as_written_in_the_settings_file(self):
        if not (os.name == "posix" or shutil.which("cmd")):
            self.skipTest("needs the platform shell")
        openguildkit_on_path(self)
        self.init("enforce")
        self.run_cli("host", "apply")
        hooks = self.settings()["hooks"]
        (group,) = hooks["BeforeTool"]
        self.assertTrue(all(re.search(group["matcher"], tool) for tool in ("write_file", "replace")))
        (handler,) = group["hooks"]
        environment = {**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONIOENCODING": "utf-8"}
        for hook_input in (WRITE_FILE, REPLACE):
            result = subprocess.run(handler["command"], shell=True, cwd=self.root, env=environment, text=True,
                                    input=json.dumps(hook_input), capture_output=True, encoding="utf-8", timeout=120)
            self.assertEqual((result.returncode, result.stdout), (2, ""), result.stderr)
            self.assertIn("Edit refused for", result.stderr)
        (prompt_group,) = hooks["BeforeAgent"]
        result = subprocess.run(prompt_group["hooks"][0]["command"], shell=True, cwd=self.root, env=environment,
                                text=True, input=json.dumps(PROMPT), capture_output=True, encoding="utf-8", timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "BeforeAgent")


class GeminiApplyTests(GeminiCase):
    PERSON = {
        "theme": "Dracula",
        "mcpServers": {"docs": {"command": "npx", "args": ["-y", "docs-server@1.2.3"]}},
        "hooks": {
            "BeforeTool": [{"matcher": "run_shell_command", "hooks": [{"type": "command", "command": "./mine.sh"}]}],
            "AfterTool": [{"matcher": "*", "hooks": [{"type": "command", "command": "./audit.sh"}]}],
        },
        "hooksConfig": {"notifications": False},
    }

    def person_settings(self, settings: dict) -> None:
        (self.root / SETTINGS).parent.mkdir(exist_ok=True)
        (self.root / SETTINGS).write_text(json.dumps(settings, indent=4), encoding="utf-8")

    def test_host_apply_declares_the_hooks_the_documentation_describes(self):
        self.init("enforce")
        _, error = self.run_cli("host", "apply")
        self.assertIn("Wrote .gemini/settings.json", error)
        hooks = self.settings()["hooks"]
        self.assertEqual(sorted(hooks), ["BeforeAgent", "BeforeTool"])
        # https://geminicli.com/docs/hooks/ (last updated Apr 13, 2026, read on 2026-11-25): an event holds groups with
        # a matcher (a regular expression for tools) and hooks of type command with a name and a command.
        self.assertEqual(hooks["BeforeTool"], [{"matcher": "write_file|replace", "hooks": [
            {"name": "openguildkit-guard", "type": "command", "command": "openguildkit guard --hook pre-edit"}]}])
        self.assertEqual(hooks["BeforeAgent"], [{"matcher": "*", "hooks": [
            {"name": "openguildkit-prompt", "type": "command", "command": "openguildkit guard --hook prompt"}]}])

    def test_host_apply_keeps_what_the_person_wrote_and_is_idempotent(self):
        self.init("enforce")
        self.person_settings(self.PERSON)
        self.run_cli("host", "apply")
        first = (self.root / SETTINGS).read_bytes()
        written = self.settings()
        for key in ("theme", "mcpServers"):
            self.assertEqual(written[key], self.PERSON[key])
        self.assertEqual(written["hooks"]["AfterTool"], self.PERSON["hooks"]["AfterTool"])
        self.assertEqual(written["hooks"]["BeforeTool"][0], self.PERSON["hooks"]["BeforeTool"][0])
        self.assertEqual(len(written["hooks"]["BeforeTool"]), 2)
        self.assertIs(written["hooksConfig"]["notifications"], False)
        self.run_cli("host", "apply")
        self.assertEqual((self.root / SETTINGS).read_bytes(), first)

    def test_a_group_the_person_already_gave_the_guard_is_not_doubled(self):
        self.init("observe")
        self.person_settings({"hooks": {"BeforeTool": [{"matcher": "write_file|replace", "hooks": [
            {"type": "command", "command": "openguildkit guard --hook pre-edit"}]}]}})
        self.run_cli("host", "apply")
        self.assertEqual(len(self.settings()["hooks"]["BeforeTool"]), 1)
        self.assertEqual(len(self.settings()["hooks"]["BeforeAgent"]), 1)

    def test_in_enforce_the_project_switches_the_hooks_on_and_in_observe_it_does_not(self):
        self.init("enforce")
        self.person_settings({"hooksConfig": {"enabled": False, "notifications": False}})
        self.run_cli("host", "apply")
        self.assertEqual(self.settings()["hooksConfig"], {"enabled": True, "notifications": False})
        shutil.rmtree(self.root / ".openguildkit")
        (self.root / SETTINGS).unlink()
        self.init("observe")
        self.run_cli("host", "apply")
        self.assertNotIn("hooksConfig", self.settings())

    def test_host_apply_enables_a_hook_the_project_had_disabled(self):
        self.init("observe")
        self.person_settings({"hooksConfig": {"disabled": ["openguildkit guard --hook pre-edit", "mine"]}})
        self.assertEqual(self.board(code=1)["status"], "missing")
        self.run_cli("host", "apply")
        self.assertEqual(self.settings()["hooksConfig"]["disabled"], ["mine"])
        self.assertEqual(self.board()["status"], "enforced")

    def test_host_apply_refuses_a_file_it_cannot_read_and_keeps_it(self):
        self.init("enforce")
        for text, message in (("{not json", "is not valid JSON"), ("[]", "must hold a JSON object"),
                              ('{"hooks": {"BeforeTool": [{"hooks": "x"}]}}', "must be a list of handlers"),
                              ('{"hooksConfig": []}', "hooksConfig must be a JSON object")):
            with self.subTest(text=text):
                (self.root / SETTINGS).parent.mkdir(exist_ok=True)
                (self.root / SETTINGS).write_text(text, encoding="utf-8")
                _, error = self.run_cli("host", "apply", code=1)
                self.assertIn(message, error)
                self.assertEqual((self.root / SETTINGS).read_text(encoding="utf-8"), text)

    def test_with_the_guard_off_nothing_is_written(self):
        self.init("off")
        self.run_cli("host", "apply")
        self.assertFalse((self.root / ".gemini").exists())


class GeminiCheckTests(GeminiCase):
    def test_host_check_before_and_after_host_apply(self):
        self.init("enforce")
        board = self.board(code=1)
        self.assertEqual(board["status"], "missing")
        self.assertIn(".gemini/settings.json", board["detail"])
        output, _ = self.run_cli("host", "check", code=1)
        self.assertIn("[missing] The board is consulted before each change", output)
        self.assertIn("setting(s) missing. Run openguildkit host apply", output)
        self.run_cli("check", code=1)
        self.run_cli("host", "apply")
        board = self.board()
        self.assertEqual(board["status"], "enforced")
        for words in ("BeforeTool", "write_file", "replace", "Only exit code 2 blocks", "when the hook cannot start",
                      "trusted folder", "Not seen in a live Gemini CLI session yet"):
            with self.subTest(words=words):
                self.assertIn(words, board["detail"])
        self.assertIn("Shell commands", board["detail"])
        output, _ = self.run_cli("host", "check")
        self.assertIn("Nothing missing.", output)
        self.run_cli("check")

    def test_the_other_rules_stay_with_the_instructions_and_a_person(self):
        self.init("enforce")
        self.run_cli("host", "apply")
        statuses = {control["id"]: control["status"] for control in json.loads(self.run_cli("host", "check", "--json")[0])}
        self.assertEqual(statuses, {"research": "instruction", "approval": "instruction", "board": "enforced",
                                    "external-actions": "human"})

    def test_a_hook_that_is_not_installed_in_the_right_place_is_missing(self):
        self.init("observe")
        self.run_cli("host", "apply")
        settings = self.settings()
        for change in (
            lambda s: s["hooks"].pop("BeforeAgent"),
            lambda s: s["hooks"].pop("BeforeTool"),
            lambda s: s["hooks"].__setitem__("PreToolUse", s["hooks"].pop("BeforeTool")),
            lambda s: s["hooks"]["BeforeTool"][0].__setitem__("matcher", "write_file"),
            lambda s: s["hooks"]["BeforeTool"][0].__setitem__("matcher", "replace"),
        ):
            with self.subTest(change=change):
                changed = json.loads(json.dumps(settings))
                change(changed)
                (self.root / SETTINGS).write_text(json.dumps(changed), encoding="utf-8")
                self.assertEqual(self.board(code=1)["status"], "missing")
        for matcher in ("", "*", "write_.*|replace", ".*"):
            with self.subTest(matcher=matcher):
                changed = json.loads(json.dumps(settings))
                changed["hooks"]["BeforeTool"][0]["matcher"] = matcher
                (self.root / SETTINGS).write_text(json.dumps(changed), encoding="utf-8")
                self.assertEqual(self.board()["status"], "enforced")

    def test_in_enforce_the_hooks_must_be_switched_on_by_the_project(self):
        self.init("enforce")
        self.run_cli("host", "apply")
        settings = self.settings()
        for value in (None, False):
            if value is None:
                settings["hooksConfig"].pop("enabled")
            else:
                settings["hooksConfig"]["enabled"] = value
            (self.root / SETTINGS).write_text(json.dumps(settings), encoding="utf-8")
            board = self.board(code=1)
            self.assertEqual(board["status"], "missing")
            self.assertIn('"hooksConfig": {"enabled": true}', board["detail"])
        self.run_cli("host", "apply")
        self.assertEqual(self.board()["status"], "enforced")

    def test_in_observe_only_an_explicit_off_counts(self):
        self.init("observe")
        self.run_cli("host", "apply")
        self.assertEqual(self.board()["status"], "enforced")
        settings = self.settings()
        settings["hooksConfig"] = {"enabled": False}
        (self.root / SETTINGS).write_text(json.dumps(settings), encoding="utf-8")
        self.assertEqual(self.board(code=1)["status"], "missing")

    def test_a_command_that_is_not_on_the_path_is_reported_as_such(self):
        self.init("enforce")
        self.run_cli("host", "apply")
        with patch("openguildkit.hosts.shutil.which", return_value=None):
            board = self.board(code=1)
        self.assertEqual((board["status"], board.get("cause")), ("missing", "path"))
        self.assertIn("not on this workstation's PATH", board["detail"])

    def test_a_settings_file_that_cannot_be_read_is_named(self):
        self.init("enforce")
        (self.root / SETTINGS).parent.mkdir()
        (self.root / SETTINGS).write_text("{nope", encoding="utf-8")
        _, error = self.run_cli("host", "check", code=1)
        self.assertIn(".gemini/settings.json is not valid JSON", error)

    def test_profile_set_host_then_host_apply(self):
        self.init("enforce", host="other")
        output, _ = self.run_cli("profile", "set", "host", "gemini-cli", "--by", "Sam", "--reason", "Team moved")
        self.assertIn("openguildkit host apply", output)
        self.assertEqual(json.loads((self.root / ".openguildkit" / "project.json").read_text())["host"], "gemini-cli")
        self.run_cli("sync")
        self.assertEqual(self.board(code=1)["status"], "missing")
        self.run_cli("host", "apply")
        self.assertEqual(self.board()["status"], "enforced")
        self.run_cli("check")

    def test_moving_away_from_gemini_cli_to_other_is_a_weakening_the_person_types(self):
        self.init("enforce")
        with patch("sys.stdin.isatty", return_value=False):
            _, error = self.run_cli("profile", "set", "host", "other", "--by", "Sam", "--reason", "x", code=1)
        self.assertIn("host gemini-cli -> other, whose settings enforce less", error)
        # Claude Code and Codex enforce more than a host that only runs hooks: moving to Gemini CLI is a weakening too.
        for source in ("claude-code", "codex"):
            with self.subTest(source=source):
                shutil.rmtree(self.root / ".openguildkit")
                self.init("enforce", host=source)
                with patch("sys.stdin.isatty", return_value=False):
                    _, error = self.run_cli("profile", "set", "host", "gemini-cli", "--by", "Sam", "--reason", "x", code=1)
                self.assertIn(f"host {source} -> gemini-cli, whose settings enforce less", error)


class GeminiInstructionTests(GeminiCase):
    def test_init_writes_the_gemini_file_that_imports_agents_md_for_this_host_only(self):
        self.init("off")
        text = (self.root / "GEMINI.md").read_text(encoding="utf-8")
        self.assertIn(BEGIN, text)
        self.assertIn("@./AGENTS.md", text)
        self.run_cli("check")
        for host in ("claude-code", "codex", "other"):
            with self.subTest(host=host):
                shutil.rmtree(self.root / ".openguildkit")
                (self.root / "GEMINI.md").unlink(missing_ok=True)
                self.init("off", host=host)
                self.assertFalse((self.root / "GEMINI.md").exists())
                self.run_cli("sync")
                self.assertFalse((self.root / "GEMINI.md").exists())

    def test_a_project_of_another_host_does_not_need_the_gemini_file(self):
        self.init("off", host="other")
        self.assertFalse((self.root / "GEMINI.md").exists())
        self.run_cli("check")

    def test_init_says_it_wrote_the_gemini_file(self):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "host": "gemini-cli"})
        output, _ = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("GEMINI.md, one line that imports AGENTS.md for Gemini CLI", output)

    def test_a_gemini_file_the_person_wrote_keeps_its_text(self):
        (self.root / "GEMINI.md").write_text("# Our Gemini notes\n\nAlways answer in French.\n", encoding="utf-8")
        self.init("off")
        text = (self.root / "GEMINI.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Our Gemini notes\n\nAlways answer in French.\n"))
        self.assertIn("@./AGENTS.md", text)
        self.run_cli("sync")
        self.assertEqual((self.root / "GEMINI.md").read_text(encoding="utf-8"), text)

    def test_an_import_the_person_already_wrote_is_enough(self):
        (self.root / "GEMINI.md").write_text("Rules:\n\n@./AGENTS.md\n", encoding="utf-8")
        self.init("off")
        self.assertEqual((self.root / "GEMINI.md").read_text(encoding="utf-8"), "Rules:\n\n@./AGENTS.md\n")
        self.run_cli("check")

    def test_check_reports_a_missing_import_and_sync_writes_it(self):
        self.init("off")
        (self.root / "GEMINI.md").unlink()
        _, error = self.run_cli("check", code=1)
        self.assertIn("instructions are out of date", error)
        self.run_cli("sync")
        self.assertIn("@./AGENTS.md", (self.root / "GEMINI.md").read_text(encoding="utf-8"))
        self.run_cli("check")

    def test_a_link_to_agents_md_already_carries_the_rules(self):
        if os.name != "posix":
            self.skipTest("symbolic links")
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "host": "gemini-cli", "guard": "off"})
        (self.root / "AGENTS.md").write_text("", encoding="utf-8")
        (self.root / "GEMINI.md").symlink_to("AGENTS.md")
        self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertTrue((self.root / "GEMINI.md").is_symlink())
        self.run_cli("check")


class GeminiHostListTests(GeminiCase):
    def test_the_host_is_known_everywhere_the_profile_names_one(self):
        self.assertIn("gemini-cli", HOSTS)
        self.assertEqual(HOOK_HOSTS, ("claude-code", "codex", "gemini-cli"))
        self.assertEqual(HOSTS[-1], "other")
        _, error = self.run_cli("integrations", "--host", "nope", code=2)
        self.assertIn("gemini-cli", error)

    def test_a_profile_with_an_unknown_host_names_the_choices(self):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "host": "nope"})
        _, error = self.run_cli("init", "--answers", self.root / "answers.json", code=1)
        self.assertIn("host must be one of claude-code, codex, gemini-cli, other", error)

    def question(self) -> dict:
        questions = init_questions(load_catalog(), "Ledger", host=_detected_host(self.root))
        return next(question for question in questions if question["id"] == "host")

    def test_the_questionnaire_offers_it_and_the_gemini_folder_suggests_it(self):
        question = self.question()
        self.assertEqual([choice["id"] for choice in question["choices"]], ["claude-code", "codex", "gemini-cli", "other"])
        self.assertEqual(question["default"], "other")
        self.assertNotIn("detected", question)
        (self.root / ".gemini").mkdir()
        self.assertEqual(_detected_host(self.root), "gemini-cli")
        question = self.question()
        self.assertEqual((question["default"], question["detected"]), ("other", "gemini-cli"))
        self.assertIn("Gemini CLI files", question["prompt"])

    def test_the_gemini_folder_does_not_hide_the_other_hosts(self):
        (self.root / ".gemini").mkdir()
        (self.root / ".codex").mkdir()
        self.assertEqual(_detected_host(self.root), "codex")
        (self.root / ".claude").mkdir()
        self.assertEqual(_detected_host(self.root), "claude-code")

    def test_integrations_install_the_skill_where_gemini_cli_reads_it(self):
        output, _ = self.run_cli("integrations", "--host", "gemini-cli")
        self.assertTrue((self.root / ".agents" / "skills" / "openguildkit" / "SKILL.md").is_file())
        self.assertFalse((self.root / ".gemini").exists())
        self.assertIn(".agents/skills/openguildkit", output)

    def test_init_next_steps_name_host_apply(self):
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "host": "gemini-cli", "guard": "observe"})
        output, _ = self.run_cli("init", "--answers", self.root / "answers.json")
        self.assertIn("openguildkit host apply    install the gemini-cli settings and hooks", output)
        self.assertNotIn("This host has no hook", output)

    def test_tools_commands_say_which_host_the_project_has(self):
        self.init("observe")
        _, error = self.run_cli("tools", "apply", "jira", "--mock", code=1)
        self.assertIn("the project's host is gemini-cli", error)
        _, error = self.run_cli("tools", "plan", "jira", "--mock")
        self.assertIn("The project's host is gemini-cli", error)
        self.assertNotIn("The project's host is other", error)


class GeminiCoverageTests(GeminiCase):
    def coverage(self, tool_id: str) -> dict:
        report = json.loads(run_cli(self.root, "host", "scan", "--json").stdout)
        return next(item for item in report["surfaces"] if item["id"] == tool_id)["coverage"]

    def test_host_scan_says_what_host_check_says_about_the_hooks(self):
        self.init("enforce")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        board = next(item for item in host_controls(self.root, profile) if item["id"] == "board")
        self.assertEqual((board["status"], self.coverage("gemini-cli")["status"]), ("missing", "missing"))
        self.assertIn("host apply", self.coverage("gemini-cli")["detail"])
        self.run_cli("host", "apply")
        board = next(item for item in host_controls(self.root, profile) if item["id"] == "board")
        self.assertEqual((board["status"], self.coverage("gemini-cli")["status"]), ("enforced", "enforced"))
        findings = json.loads(run_cli(self.root, "host", "scan", "--json").stdout)["findings"]
        self.assertEqual([item for item in findings if item["code"] == "surface-uncovered"
                          and item["message"].startswith("gemini-cli")], [])

    def test_the_off_guard_and_a_path_problem_are_said_the_same_way(self):
        self.init("off")
        self.assertEqual(self.coverage("gemini-cli")["status"], "off")
        shutil.rmtree(self.root / ".openguildkit")
        (self.root / SETTINGS).unlink(missing_ok=True)
        self.init("enforce")
        self.run_cli("host", "apply")
        with patch("openguildkit.hosts.shutil.which", return_value=None):
            coverage = self.coverage("gemini-cli")
        self.assertEqual(coverage["status"], "missing")
        self.assertIn("not on the PATH", coverage["detail"])

    def test_a_project_of_another_host_is_not_covered_by_the_gemini_hooks(self):
        self.init("enforce", host="claude-code")
        self.run_cli("host", "apply")
        (self.root / ".gemini").mkdir()
        (self.root / ".gemini" / "settings.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.coverage("claude-code")["status"], "enforced")
        coverage = self.coverage("gemini-cli")
        self.assertEqual(coverage["status"], "missing")
        self.assertIn("claude-code", coverage["detail"])

    def test_the_scan_says_where_gemini_cli_reads_its_instructions(self):
        self.init("off")
        report = json.loads(run_cli(self.root, "host", "scan", "--json").stdout)
        text = next(item for item in report["surfaces"] if item["id"] == "gemini-cli")["agents_md_text"]
        self.assertIn("agents.md list", text)
        self.assertIn("default context file is GEMINI.md", text)
        self.assertIn("context.fileName", text)

    def test_a_settings_file_that_cannot_be_read_is_reported_as_unreadable(self):
        self.init("enforce")
        (self.root / ".gemini").mkdir()
        (self.root / ".gemini" / "settings.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(self.coverage("gemini-cli")["status"], "unreadable")


class ExistingHostsAreUnchangedTests(GeminiCase):
    def test_a_project_that_does_not_name_gemini_cli_never_gets_its_files(self):
        for host in ("claude-code", "codex", "other"):
            with self.subTest(host=host):
                if (self.root / ".openguildkit").exists():
                    shutil.rmtree(self.root / ".openguildkit")
                self.init("enforce", host=host)
                (self.root / ".gemini").mkdir(exist_ok=True)
                (self.root / SETTINGS).write_text('{"theme": "Dracula"}\n', encoding="utf-8")
                self.run_cli("host", "apply", code=1 if host == "other" else 0)
                self.assertEqual((self.root / SETTINGS).read_text(encoding="utf-8"), '{"theme": "Dracula"}\n')
                self.assertFalse((self.root / "GEMINI.md").exists())
                titles = " ".join(control["title"] + control["detail"] for control in
                                  json.loads(self.run_cli("host", "check", "--json")[0]))
                self.assertNotIn("Gemini", titles)
                self.assertNotIn("gemini", titles)

    def test_the_settings_file_of_gemini_is_work_like_any_other_for_them(self):
        for host in ("claude-code", "codex", "other"):
            with self.subTest(host=host):
                if (self.root / ".openguildkit").exists():
                    shutil.rmtree(self.root / ".openguildkit")
                self.init("enforce", host=host)
                settings = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                            "tool_input": {"file_path": ".gemini/settings.json"}}
                code, _, error = self.hook("pre-edit", settings)
                self.assertEqual(code, 2)
                self.assertIn("Edit refused for: .gemini/settings.json", error)
                self.assertNotIn("written by the openguildkit commands", error)


class GeminiDocumentationTests(unittest.TestCase):
    def section(self) -> str:
        text = README.read_text(encoding="utf-8").replace("\r\n", "\n")
        return text.split("\n## Gemini CLI\n", 1)[1].split("\n## ", 1)[0]

    def test_the_section_cites_its_sources_with_the_day_and_what_was_not_seen(self):
        section = self.section()
        for url in ("https://geminicli.com/docs/hooks/", "https://geminicli.com/docs/hooks/reference/",
                    "https://geminicli.com/docs/hooks/best-practices/", "https://geminicli.com/docs/reference/tools/",
                    "https://geminicli.com/docs/cli/gemini-md/", "https://geminicli.com/docs/reference/configuration/"):
            with self.subTest(url=url):
                self.assertIn(url, section)
        for words in ("read on 2026-11-25", "not seen in a live session", "Antigravity CLI", "exit code 2",
                      "What it does not block", "systemMessage"):
            with self.subTest(words=words):
                self.assertIn(words, section)

    def test_the_decisions_for_cursor_and_copilot_are_written_with_their_reason(self):
        text = README.read_text(encoding="utf-8")
        for words in ("https://cursor.com/docs/agent/hooks", "https://docs.github.com/en/copilot/reference/hooks-configuration",
                      "no page shows the arguments of an edit"):
            with self.subTest(words=words):
                self.assertIn(words, text)

    def test_the_examples_of_the_section_give_the_answers_it_describes(self):
        section = self.section()
        found = {}
        for shell, code in re.findall(r"```(sh|powershell)\n(.*?)```", section, re.DOTALL):
            pattern = SH_LINE if shell == "sh" else PS_LINE
            for line in code.strip().splitlines():
                match = pattern.match(line)
                self.assertIsNotNone(match, f"{shell}: not a hook command: {line}")
                found.setdefault(shell, []).append((match["event"], match["json"]))
        self.assertEqual(found["sh"], found["powershell"])
        self.assertEqual(sorted(event for event, _ in found["sh"]), ["pre-edit", "pre-edit", "prompt"])
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for guard, refused in (("enforce", True), ("observe", False)):
            write_json(root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"],
                                               "guard": guard, "host": "gemini-cli"})
            run_cli(root, "init", "--answers", root / "answers.json")
            for event, raw in found["sh"]:
                with self.subTest(guard=guard, event=event, raw=raw):
                    json.loads(raw)
                    result = run_cli(root, "guard", "--hook", event, stdin=raw, expect=None)
                    if event == "prompt":
                        self.assertEqual(result.returncode, 0)
                        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"], "BeforeAgent")
                    elif refused:
                        self.assertEqual((result.returncode, result.stdout), (2, ""))
                        self.assertIn("Edit refused for: app.py", result.stderr)
                    else:
                        self.assertEqual(result.returncode, 0)
                        self.assertIn("Edit flagged, not blocked", json.loads(result.stdout)["systemMessage"])
            shutil.rmtree(root / ".openguildkit")


if __name__ == "__main__":
    unittest.main()
