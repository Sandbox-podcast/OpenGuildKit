"""The catalog lock keeps a project's rules stable until the team adopts a newer catalog."""

import json

from tests.e2e.test_cli_flow import EXAMPLE, TASK_ID, CliTestCase


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
        self.assertEqual(applied["stale_tasks"], [{"id": TASK_ID, "status": "consulting"}])
        agents = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("Older wording", agents)
        self.assertNotIn("retired-rule", agents)
        self.run_cli("check")
        self.assertEqual(json.loads(self.run_cli("update", "--json").stdout)["changes"], [])

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
