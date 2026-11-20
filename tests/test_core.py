import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import STATE_DIR, project_root
from openguildkit.storage import read_json, write_json


class WorkflowTests(unittest.TestCase):
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
            "context": "Use test data. Keep the existing permission model.",
        }
        write_json(
            self.input_path,
            {"name": "Insurance console", "sector": "insurance", "stack": ["Python"], "packs": ["python"]},
        )

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

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
        for board in review["boards"]:
            board["recommendation"] = "Cover the approved scope with a synthetic fixture."
            board["evidence"] = ["docs/permissions.md"]
            challenge = board["challenge"]
            for specialist in challenge["specialists"]:
                specialist.update(finding="The permission policy requires scoped access.", basis="observed", evidence_refs=[1])
            challenge.update(
                verdict="revise",
                confidence="medium",
                alternative="Keep exports disabled until access is verified.",
                failure_mode="Cross-account access exposes a claim.",
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
        self.run_cli("task", "new", "Export claim status.", "--id", self.task_id)
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
        profile = read_json(self.profile_path)
        profile["conventions"] = ["Write an audit event for each export."]
        write_json(self.profile_path, profile)
        self.run_cli("sync")
        _, error = self.run_cli("task", "handoff", self.task_id, code=1)
        self.assertIn("project profile or catalog changed", error)

    def test_review_from_an_earlier_consultation_is_rejected(self):
        self.init()
        self.run_cli("task", "new", "Export claim status.", "--id", self.task_id)
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
        write_json(self.input_path, {"name": "Insurance console", "packs": ["team-iso"]})
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
