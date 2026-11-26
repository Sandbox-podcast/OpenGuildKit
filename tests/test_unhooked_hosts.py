"""Cursor and GitHub Copilot: what `host check` and `host scan` say when a repository holds their files (issue 430).

Their hook pages were read again on 2026-11-26 to find the path of the file an edit tool is about to change in the input
of `preToolUse`. None documents it (integrations/README.md, "Hooks of other tools"), so neither tool is a host: the
commands say, in one line, that the tool reads the AGENTS.md instructions, that no edit made through it is blocked, and
that `guard --ci` is the only barrier, with the page and the day it was read.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import surfaces
from openguildkit.hosts import HOOK_HOSTS, HOSTS, UNHOOKED_TOOLS, host_controls
from openguildkit.storage import write_json
from tests.support import run_cli
from tests.test_host_scan import write

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
READ = "2026-11-26"
CURSOR_PAGE = "https://cursor.com/docs/agent/hooks"
COPILOT_PAGES = ("https://docs.github.com/en/copilot/reference/hooks-reference",
                 "https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-hooks-reference")
# One file of each tool, as a repository that uses it holds it.
FILES = {"cursor": ".cursor/rules/style.mdc", "copilot": ".github/copilot-instructions.md"}


class UnhookedCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        on_path = patch("openguildkit.hosts.shutil.which", return_value="/opt/tools/openguildkit")
        on_path.start()
        self.addCleanup(on_path.stop)

    def init_project(self, **answers) -> dict:
        write_json(self.root / "answers.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], **answers})
        run_cli(self.root, "init", "--answers", self.root / "answers.json")
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def check_json(self, code=None) -> list[dict]:
        return json.loads(run_cli(self.root, "host", "check", "--json", expect=code).stdout)


class HostCheckTests(UnhookedCase):
    def test_neither_tool_is_a_host(self):
        for tool_id in ("cursor", "copilot"):
            self.assertNotIn(tool_id, HOSTS)
            self.assertNotIn(tool_id, HOOK_HOSTS)

    def test_host_check_says_in_one_line_that_nothing_blocks_an_edit_with_the_page_and_the_day(self):
        self.init_project(host="claude-code", guard="enforce")
        run_cli(self.root, "host", "apply")
        before = run_cli(self.root, "host", "check").stdout
        for tool_id, name, pages in (("cursor", "Cursor", (CURSOR_PAGE,)), ("copilot", "GitHub Copilot", COPILOT_PAGES)):
            with self.subTest(tool=tool_id):
                write(self.root, FILES[tool_id], "Be brief.\n")
                text = run_cli(self.root, "host", "check").stdout
                lines = [line for line in text.splitlines() if line.strip().startswith(name)]
                self.assertEqual(len(lines), 1, text)
                (line,) = lines
                for words in ("reads the AGENTS.md instructions", "no hook blocks an edit made through it",
                              "guard --ci is the only barrier", f"read {READ}", *pages):
                    self.assertIn(words, line)
                self.assertIn("Nothing missing", text)
        self.assertNotIn("Cursor", before)
        self.assertNotIn("Copilot", before)

    def test_the_json_control_is_by_instruction_with_its_sources_and_does_not_fail_the_command(self):
        self.init_project(host="claude-code", guard="enforce")
        run_cli(self.root, "host", "apply")
        write(self.root, ".cursor/hooks.json", json.dumps({"version": 1, "hooks": {}}))
        write(self.root, ".github/hooks/team.json", json.dumps({"version": 1, "hooks": {}}))
        controls = {item["id"]: item for item in self.check_json(code=0)}
        self.assertEqual(controls["tool-cursor"]["status"], "instruction")
        self.assertEqual(controls["tool-copilot"]["status"], "instruction")
        self.assertEqual(controls["tool-cursor"]["files"], [".cursor"])
        self.assertEqual(controls["tool-copilot"]["files"], [".github/hooks"])
        self.assertEqual(controls["tool-cursor"]["source"], {"pages": [CURSOR_PAGE], "read": READ})
        self.assertEqual(controls["tool-copilot"]["source"], {"pages": list(COPILOT_PAGES), "read": READ})

    def test_a_project_without_these_files_gets_the_controls_it_had(self):
        for host in ("claude-code", "codex", "gemini-cli", "other"):
            with self.subTest(host=host):
                directory = tempfile.TemporaryDirectory()
                self.addCleanup(directory.cleanup)
                self.root = Path(directory.name)
                profile = self.init_project(host=host, guard="observe")
                self.assertFalse([item for item in host_controls(self.root, profile) if item["id"].startswith("tool-")])

    def test_the_line_is_the_same_whatever_the_guard(self):
        write(self.root, FILES["cursor"], "Be brief.\n")
        for guard in ("off", "observe", "enforce"):
            with self.subTest(guard=guard):
                profile = {"host": "other", "guard": guard, "research": "local-only"}
                (control,) = [item for item in host_controls(self.root, profile) if item["id"] == "tool-cursor"]
                self.assertIn("guard --ci is the only barrier", control["detail"])

    def test_a_task_consultation_does_not_record_them(self):
        profile = self.init_project(host="claude-code", guard="observe")
        write(self.root, FILES["cursor"], "Be brief.\n")
        self.assertFalse([item for item in host_controls(self.root, profile, other_tools=False)
                          if item["id"].startswith("tool-")])
        run_cli(self.root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
        run_cli(self.root, "task", "consult", "request-status", "--answers", EXAMPLE / "answers.json")
        records = "".join(path.read_text(encoding="utf-8")
                          for path in (self.root / ".openguildkit" / "tasks").rglob("*") if path.is_file())
        self.assertIn('"host_controls"', records)
        self.assertNotIn("tool-cursor", records)


class HostScanTests(UnhookedCase):
    def test_host_scan_says_the_same_with_the_page_and_the_day(self):
        for tool_id, pages in (("cursor", [CURSOR_PAGE]), ("copilot", list(COPILOT_PAGES))):
            with self.subTest(tool=tool_id):
                write(self.root, FILES[tool_id], "Be brief.\n")
                (item,) = [entry for entry in surfaces.discover(self.root, {})["surfaces"] if entry["id"] == tool_id]
                coverage = item["coverage"]
                self.assertEqual(coverage["status"], "none")
                self.assertEqual(coverage["source"], {"pages": pages, "read": READ})
                for words in ("no hook blocks an edit made through it", "guard --ci is the only barrier", f"read {READ}",
                              *pages):
                    self.assertIn(words, coverage["detail"])
                text = run_cli(self.root, "host", "scan").stdout
                (line,) = [line for line in text.splitlines() if line.startswith(f"  {tool_id} ")]
                self.assertIn("no edit blocked, guard --ci is the only barrier", line)
                self.assertIn(f"hook docs read {READ}", line)
                self.assertIn("reads AGENTS.md", line)

    def test_copilot_hooks_folder_shows_the_tool(self):
        write(self.root, ".github/hooks/openguildkit.json", json.dumps({"version": 1, "hooks": {}}))
        (item,) = [entry for entry in surfaces.discover(self.root, {})["surfaces"] if entry["id"] == "copilot"]
        self.assertEqual(item["files"], [".github/hooks"])

    def test_the_other_tools_keep_their_line(self):
        write(self.root, ".windsurfrules", "Be brief.\n")
        (item,) = surfaces.discover(self.root, {})["surfaces"]
        self.assertNotIn("source", item["coverage"])
        self.assertEqual(item["coverage"]["detail"], f"no hook blocks an edit; {surfaces.CI_ONLY}")


class DocumentationTests(unittest.TestCase):
    def test_the_table_of_tools_and_the_pages_agree(self):
        self.assertEqual(set(UNHOOKED_TOOLS), {"cursor", "copilot"})
        by_id = {tool["id"]: tool for tool in surfaces.TOOLS}
        for tool_id, entry in UNHOOKED_TOOLS.items():
            self.assertEqual(by_id[tool_id]["files"], entry["files"])
            self.assertEqual(entry["read"], READ)

    def test_both_pages_cite_what_was_read_and_the_day(self):
        for relative in ("docs/host-scan.md", "integrations/README.md"):
            page = (REPO / relative).read_text(encoding="utf-8")
            with self.subTest(page=relative):
                for words in (CURSOR_PAGE, *COPILOT_PAGES, READ, "guard --ci"):
                    self.assertIn(words, page)


if __name__ == "__main__":
    unittest.main()
