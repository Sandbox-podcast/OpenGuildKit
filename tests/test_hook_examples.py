"""The hook inputs in integrations/README.md stay exact: each is fed to the guard as the README says to run it."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.storage import write_json
from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
README = REPO / "integrations" / "README.md"
COMMANDS = {
    "sh": re.compile(r"^printf '%s' '(?P<json>[^']+)' \| openguildkit guard --hook (?P<event>prompt|pre-edit)$"),
    "powershell": re.compile(r"^'(?P<json>[^']+)' \| openguildkit guard --hook (?P<event>prompt|pre-edit)$"),
}
HOSTS = ("Claude Code", "Codex")


def examples() -> dict:
    """{host: {shell: [(event, raw json)]}} from the "Try the hooks by hand" section."""
    text = README.read_text(encoding="utf-8").replace("\r\n", "\n")
    section = text.split("## Try the hooks by hand", 1)[1].split("\n## ", 1)[0]
    found = {}
    for part in section.split("\n### ")[1:]:
        host, body = part.split("\n", 1)
        for shell, code in re.findall(r"```(sh|powershell)\n(.*?)```", body, re.DOTALL):
            for line in code.strip().splitlines():
                match = COMMANDS[shell].match(line)
                if match is None:
                    raise AssertionError(f"{host} {shell}: not a hook command: {line}")
                found.setdefault(host.strip(), {}).setdefault(shell, []).append((match["event"], match["json"]))
    return found


class HookExampleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def init(self, guard):
        write_json(self.root / "answers.json", {"personal_data": False, "name": "Portal", "stack": ["Python"], "guard": guard})
        self.hook("init", "--answers", self.root / "answers.json")

    def hook(self, *arguments, stdin=None):
        result = run_cli(self.root, *arguments, stdin=stdin, expect=None)
        return result.returncode, result.stdout, result.stderr

    def test_each_host_has_both_hooks_in_both_shells_with_the_same_input(self):
        found = examples()
        self.assertEqual(sorted(found), sorted(HOSTS))
        for host in HOSTS:
            self.assertEqual(found[host]["sh"], found[host]["powershell"], host)
            self.assertEqual(sorted(event for event, _ in found[host]["sh"]), ["pre-edit", "prompt"], host)
            for _, raw in found[host]["sh"]:
                json.loads(raw)

    def test_the_examples_give_the_answers_the_readme_describes(self):
        for guard, refused in (("enforce", True), ("observe", False)):
            self.init(guard)
            for host in HOSTS:
                for event, raw in examples()[host]["sh"]:
                    with self.subTest(guard=guard, host=host, event=event):
                        code, output, error = self.hook("guard", "--hook", event, stdin=raw)
                        if event == "prompt":
                            self.assertEqual(code, 0)
                            self.assertIn("no approved task", json.loads(output)["hookSpecificOutput"]["additionalContext"])
                        elif refused:
                            self.assertEqual((code, output), (2, ""))
                            self.assertIn("Edit refused for: app.py", error)
                        else:
                            self.assertEqual(code, 0)
                            self.assertIn("Edit flagged, not blocked", json.loads(output)["hookSpecificOutput"]["additionalContext"])
            shutil.rmtree(self.root / ".openguildkit")

    @unittest.skipUnless(os.name == "posix" and shutil.which("sh"), "runs the POSIX shell commands as written")
    def test_the_posix_commands_reach_the_guard_intact(self):
        self.init("enforce")
        launcher = self.root / "bin" / "openguildkit"
        launcher.parent.mkdir()
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m openguildkit "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
        environment = {**os.environ, "PATH": f"{launcher.parent}{os.pathsep}{os.environ.get('PATH', '')}",
                       "PYTHONPATH": str(REPO / "src")}
        text = README.read_text(encoding="utf-8")
        for line in sorted(set(re.findall(r"^printf '%s' .+$", text, re.MULTILINE))):
            with self.subTest(line=line):
                result = subprocess.run(["sh", "-c", line], cwd=self.root, env=environment, capture_output=True, text=True)
                self.assertNotIn("not JSON", result.stderr)
                self.assertEqual(result.returncode, 2 if "pre-edit" in line else 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
