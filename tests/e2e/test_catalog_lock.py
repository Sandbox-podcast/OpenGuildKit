"""The catalog lock keeps a project's rules stable until the team adopts a newer catalog."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.e2e.test_cli_flow import ENV, EXAMPLE, REPO, TASK_ID, CliTestCase


class CatalogLockTests(CliTestCase):
    def lock_path(self):
        return self.project / ".openguildkit" / "catalog.lock.json"

    def read_lock(self):
        return json.loads(self.lock_path().read_text(encoding="utf-8"))

    def pin_older_secure_sdlc(self):
        """Rewrite the lock as if the project had approved an older edition of secure-sdlc."""
        lock = self.read_lock()
        pack = lock["records"]["packs"]["secure-sdlc"]
        pack["version"] = "0.9.0"
        pack["rules"][0]["instruction"] = "Older wording approved by the team."
        pack["rules"].append({"id": "retired-rule", "instruction": "A rule the catalog removed.", "verification": "Read it."})
        self.lock_path().write_text(json.dumps(lock, indent=2), encoding="utf-8")
        return pack["rules"][0]["id"]

    def test_init_pins_the_records_the_profile_uses(self):
        self.init_example()
        records = self.read_lock()["records"]
        self.assertIn("agent-workflow", records["packs"])
        self.assertIn("secure-sdlc", records["packs"])
        self.assertIn("general", records["sectors"])
        self.assertIn("security", records["boards"])
        self.assertIn("python-fastapi-postgresql", records["patterns"])
        self.assertNotIn("kanban-delivery", records["packs"])

    def test_the_project_keeps_its_approved_rules_and_rebuilds_them_from_the_lock(self):
        self.init_example()
        rule_id = self.pin_older_secure_sdlc()
        self.run_cli("sync")
        agents_path = self.project / "AGENTS.md"
        agents = agents_path.read_text(encoding="utf-8")
        self.assertIn(f"`{rule_id}` Older wording approved by the team.", agents)
        self.assertIn("secure-sdlc@0.9.0", agents)
        self.run_cli("check")

        agents_path.unlink()
        self.run_cli("sync")
        self.assertEqual(agents_path.read_text(encoding="utf-8"), agents)

    def test_update_shows_the_changes_then_applies_them_and_flags_stale_tasks(self):
        self.init_example()
        rule_id = self.pin_older_secure_sdlc()
        self.run_cli("sync")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        self.run_cli("task", "new", "Export request history.", "--id", "export-history")

        preview = json.loads(self.run_cli("update", "--json").stdout)
        self.assertFalse(preview["applied"])
        change = next(item for item in preview["changes"] if item["id"] == "secure-sdlc")
        self.assertEqual(change["version"][0], "0.9.0")
        self.assertEqual(change["rules"]["removed"], ["retired-rule"])
        self.assertEqual(change["rules"]["changed"][0]["id"], rule_id)
        text = self.run_cli("update").stdout
        self.assertIn("- rule retired-rule", text)
        self.assertIn("update --apply", text)
        self.assertIn("Older wording", (self.project / "AGENTS.md").read_text(encoding="utf-8"))

        applied = json.loads(self.run_cli("update", "--apply", "--json").stdout)
        self.assertTrue(applied["applied"])
        self.assertEqual(applied["stale_tasks"], [{"id": TASK_ID, "status": "consulting", "step": "consult it again"}])
        agents = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("Older wording", agents)
        self.assertNotIn("retired-rule", agents)
        self.run_cli("check")
        self.assertEqual(json.loads(self.run_cli("update", "--json").stdout)["changes"], [])

    def test_update_shows_old_and_new_wording_and_names_the_same_tasks_as_the_sync_after_it(self):
        self.init_example()
        rule_id = self.pin_older_secure_sdlc()
        self.run_cli("sync")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.run_cli("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")
        preview = self.run_cli("update").stdout
        self.assertIn(f"~ rule {rule_id}\n        before: Older wording approved by the team.", preview)
        self.assertRegex(preview, r"        after:  \S")
        self.assertIn(f"Tasks this change touches:\n  {TASK_ID} (consulting): consult it again.", preview)
        applied = self.run_cli("update", "--apply").stdout
        named = f"  {TASK_ID} (consulting): consult it again."
        self.assertIn(named, applied)
        self.assertIn(named, self.run_cli("sync").stdout)

    def test_check_asks_for_update_when_the_lock_is_older_than_the_installed_catalog(self):
        self.init_example()
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK_ID)
        self.pin_older_secure_sdlc()
        result = self.run_cli("check", expect=1)
        self.assertIn("newer catalog than the project's lock. Run openguildkit update", result.stderr)
        self.assertIn("sync would rewrite the instructions from the lock's earlier rules", result.stderr)
        for command in (("task", "new", "Another thing", "--id", "another"),
                        ("task", "consult", TASK_ID, "--answers", EXAMPLE / "answers.json")):
            self.assertEqual(self.run_cli(*command, expect=1).stderr, result.stderr.splitlines()[-1] + "\n")
        self.assertIn("Run openguildkit update to review them", self.run_cli("sync").stderr)
        self.run_cli("sync")
        result = self.run_cli("check")
        self.assertIn("packs/secure-sdlc", result.stderr)
        self.assertIn("run openguildkit update to review", result.stderr)
        self.run_cli("update", "--apply")
        self.assertNotIn("openguildkit update", self.run_cli("check").stderr)

    def test_check_asks_for_sync_when_the_profile_uses_records_missing_from_the_lock(self):
        self.init_example()
        profile_path = self.project / ".openguildkit" / "project.json"
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        profile["packs"].append("web-accessibility")
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
        self.run_cli("check", expect=1)
        self.run_cli("sync")
        self.assertIn("web-accessibility", self.read_lock()["records"]["packs"])
        self.run_cli("check")

    def test_projects_created_before_the_lock_keep_working_and_can_adopt_it(self):
        self.init_example()
        self.lock_path().unlink()
        self.run_cli("check")
        self.assertIn("no catalog lock", self.run_cli("update").stdout)
        self.run_cli("update", "--apply")
        self.assertTrue(self.lock_path().is_file())
        self.run_cli("check")
        self.assertEqual(EXAMPLE.name, "request-status")


@unittest.skipUnless(os.name == "posix", "approval needs a pseudo-terminal, available on Linux and macOS")
class CatalogUpgradeTests(CliTestCase):
    """A real catalog change: the same project run by an installed package whose pack text changed."""

    NEW_TEXT = "Newer wording shipped by the next catalog edition."

    def patched_package(self):
        """A copy of the package whose secure-sdlc pack has a new version and a new first rule text."""
        source = Path(tempfile.mkdtemp(prefix="ogk-src-")).resolve()
        self.addCleanup(shutil.rmtree, source, ignore_errors=True)
        shutil.copytree(REPO / "src" / "openguildkit", source / "openguildkit",
                        ignore=shutil.ignore_patterns("__pycache__"))
        path = source / "openguildkit" / "registry" / "packs" / "secure-sdlc.json"
        pack = json.loads(path.read_text(encoding="utf-8"))
        major, minor, _ = pack["version"].split(".")
        pack["version"] = f"{major}.{int(minor) + 1}.0"
        old_text = pack["rules"][0]["instruction"]
        pack["rules"][0]["instruction"] = self.NEW_TEXT
        path.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return {**ENV, "PYTHONPATH": str(source)}, pack["rules"][0]["id"], old_text

    def run_with(self, env, *args, expect=0):
        result = subprocess.run(self.command(*args), capture_output=True, text=True, encoding="utf-8", env=env,
                                timeout=60)
        self.assertEqual(result.returncode, expect, f"{args}\n{result.stdout}\n{result.stderr}")
        return result.stdout

    def test_update_shows_old_and_new_text_and_every_task_the_new_edition_touches(self):
        self.consult_example()
        self.record_example_review()
        code, _, stderr = self.decide_in_terminal(TASK_ID)
        self.assertEqual(code, 0, stderr)
        self.run_cli("task", "new", "Export request history.", "--id", "export-history")
        self.run_cli("task", "consult", "export-history", "--answers", EXAMPLE / "answers.json")

        env, rule_id, old_text = self.patched_package()
        preview = self.run_with(env, "update")
        self.assertIn(f"~ rule {rule_id}\n        before: {old_text} Verify:", preview)
        self.assertIn(f"\n        after:  {self.NEW_TEXT} Verify:", preview)
        self.assertIn("Tasks this change touches:", preview)
        touched = preview.split("Tasks this change touches:", 1)[1]
        self.assertIn(f"  {TASK_ID} (approved)", touched)
        self.assertIn("  export-history (consulting)", touched)
        self.assertNotIn(self.NEW_TEXT, (self.project / "AGENTS.md").read_text(encoding="utf-8"))

        applied = self.run_with(env, "update", "--apply")
        for task_id in (TASK_ID, "export-history"):
            self.assertIn(f"  {task_id} (", applied)
            self.assertIn(f"  {task_id} (", self.run_with(env, "sync"))
        self.assertIn(self.NEW_TEXT, (self.project / "AGENTS.md").read_text(encoding="utf-8"))
