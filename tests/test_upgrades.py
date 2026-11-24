"""A release that stops shipping a pack or a pattern must not leave the project unusable."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import lock
from openguildkit.catalog import load_catalog
from openguildkit.lock import COLLECTIONS, catalog_changes, lock_is_current, locked_records, update_target
from openguildkit.project import validate_profile
from openguildkit.storage import write_json

from tests.support import CapturedCli

DROPPED = {"packs": "playwright", "patterns": "playwright-web"}
ANSWERS = {"personal_data": "no", 
    "name": "Mono",
    "components": [
        {"id": "apps-web", "path": "apps/web", "stack": ["Next.js 14.2.3", "Playwright 1.44.0", "React 18.3.1"]},
        {"id": "services-api", "path": "services/api", "stack": ["Python 3.12", "FastAPI 0.111"]},
    ],
}


def release_without_playwright(extra_dir=None, **options):
    """The catalog of a simulated release that no longer ships the playwright pack and pattern."""
    catalog = load_catalog(extra_dir, **options)
    for collection, record_id in DROPPED.items():
        catalog[collection].pop(record_id, None)
    return catalog


class UpgradeTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "answers.json", ANSWERS)
        self.run_cli("init", "--answers", self.root / "answers.json")
        self.lock_file = self.root / ".openguildkit" / "catalog.lock.json"
        self.profile_file = self.root / ".openguildkit" / "project.json"

    def upgraded(self, *arguments, code=0):
        with patch.object(lock, "load_catalog", release_without_playwright):
            return self.run_cli(*arguments, code=code)

    def locked_ids(self):
        records = json.loads(self.lock_file.read_text(encoding="utf-8"))["records"]
        return {collection: set(records[collection]) for collection in COLLECTIONS}

    def assert_kept(self):
        locked = self.locked_ids()
        for collection, record_id in DROPPED.items():
            self.assertIn(record_id, locked[collection])
        self.assertIn("#### Playwright", (self.root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_the_profile_uses_the_records_the_release_drops(self):
        self.assert_kept()

    def test_check_passes_right_after_the_upgrade(self):
        output, _ = self.upgraded("check")
        self.assertIn("OpenGuildKit instructions match the project profile.", output)

    def test_update_apply_keeps_the_dropped_records_and_check_passes(self):
        output, _ = self.upgraded("update")
        self.assertIn("patterns/playwright-web: removed from the catalog, kept from the lock", output)
        self.assertIn(".openguildkit/project.json", output)
        self.upgraded("update", "--apply")
        self.assert_kept()
        self.upgraded("check")
        self.upgraded("task", "new", "Add a status page.", "--id", "status")

    def test_sync_keeps_the_dropped_records_and_says_so(self):
        _, error = self.upgraded("sync")
        self.assert_kept()
        self.assertIn("patterns/playwright-web is no longer shipped", error)
        self.upgraded("check")
        self.upgraded("sync")
        self.assert_kept()

    def test_the_records_go_once_the_team_removes_them_from_the_profile(self):
        self.upgraded("sync")
        profile = json.loads(self.profile_file.read_text(encoding="utf-8"))
        profile["patterns"] = [entry for entry in profile["patterns"] if "playwright-web" not in json.dumps(entry)]
        write_json(self.profile_file, profile)
        _, error = self.upgraded("sync")
        self.assertNotIn("no longer shipped", error)
        locked = self.locked_ids()
        self.assertNotIn("playwright-web", locked["patterns"])
        self.assertNotIn("playwright", locked["packs"])
        self.upgraded("check")

    def test_a_record_that_exists_nowhere_names_the_entry_to_remove(self):
        self.lock_file.unlink()
        _, error = self.upgraded("check", code=1)
        self.assertIn(".openguildkit/project.json", error)
        self.assertIn('remove "playwright-web" from "patterns"', error)
        self.assertNotIn("Traceback", error)


class LockRuleTests(unittest.TestCase):
    """locked_records and lock_is_current follow the rule catalog_changes already applies."""

    def test_locked_records_keep_dropped_packs_and_patterns(self):
        full = load_catalog()
        profile = validate_profile(ANSWERS, full)
        bundled = {collection: set(entries) for collection, entries in full.items()}
        lock = {"schema_version": 1, "records": locked_records(profile, full, bundled)}
        live = release_without_playwright()
        shipped = {collection: set(entries) for collection, entries in live.items()}
        target = update_target(live, lock)
        for collection, record_id in DROPPED.items():
            self.assertIn(record_id, locked_records(profile, target, shipped, lock)[collection])
        self.assertTrue(lock_is_current(lock, profile, target, shipped))
        changes = catalog_changes(lock, live, target, profile, shipped)
        removed = {(item["collection"], item["id"]) for item in changes if item["status"] == "removed from the catalog"}
        self.assertEqual(removed, set(DROPPED.items()))
        self.assertFalse([item for item in changes if item["status"] == "added"])


if __name__ == "__main__":
    unittest.main()
