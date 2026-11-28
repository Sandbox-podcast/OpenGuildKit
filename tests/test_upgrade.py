"""Upgrade: a project written by an older release still works with this one.

Each fixture in tests/fixtures/upgrade holds the exact files a released version
wrote (its own code, run from the release tag): profile, instructions, ignore
file, project lock and task records, one of them approved. Bundling them in one
JSON file keeps the task records out of reach of the fixture's own .gitignore.
"""

import json
from pathlib import Path

from tests.e2e.test_cli_flow import CliTestCase

FIXTURES = Path(__file__).with_name("fixtures") / "upgrade"


class UpgradeTestCase(CliTestCase):
    release = ""

    def setUp(self):
        super().setUp()
        self.bundle = json.loads((FIXTURES / f"{self.release}.json").read_text(encoding="utf-8"))
        for name, content in self.bundle["files"].items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
        self.approved = self.bundle["approved_task"]

    def old_approval_line(self):
        return (f"OpenGuildKit: {self.approved}: The approval for {self.approved} has no seal: it was edited by hand or "
                "written by a release older than sealed decisions. Consult it again with openguildkit task consult "
                f"{self.approved} --reuse-answers (--answers FILE to change the answers), or open a linked task with "
                f'openguildkit task new "BRIEF" --follows {self.approved}.')

    def assert_upgrades(self):
        """check names the old approval and the next step, update and update --apply succeed, and the rules are current.

        An approval written before sealed decisions does not cover work: check fails on it, with the command that
        reopens it, until the task is consulted again.
        """
        before = self.run_cli("check", expect=1)
        self.assertEqual(before.stderr.splitlines()[0], self.old_approval_line())
        self.assertIn("no catalog lock", self.run_cli("update").stdout)
        self.assertIn("now pins the installed catalog", self.run_cli("update", "--apply").stdout)
        self.assertTrue((self.project / ".openguildkit" / "catalog.lock.json").is_file())
        after = self.run_cli("check", expect=1)
        self.assertEqual(after.stdout, "")
        self.assertEqual(after.stderr.splitlines()[0], self.old_approval_line())
        self.assertIn("The instructions match the project profile, but 1 approval no longer holds", after.stderr)
        self.assertIn("match the installed catalog", self.run_cli("update").stdout)
        self.run_cli("sync")

    def assert_old_approval_reopens(self):
        """Consulting the old approval again keeps it in the task's rounds and leaves check clean."""
        answers = Path(__file__).resolve().parents[1] / "examples" / "request-status" / "answers.json"
        self.run_cli("task", "consult", self.approved, "--answers", answers)
        record = json.loads(self.run_cli("task", "show", self.approved, "--json").stdout)
        self.assertEqual(record["status"], "consulting")
        self.assertIn("has no seal", record["rounds"][-1]["reopened"])
        self.assertEqual(self.run_cli("check").stderr, "")

    def assert_tasks_still_load(self):
        rows = {row["id"]: row for row in json.loads(self.run_cli("task", "list", "--json").stdout)}
        self.assertEqual(rows[self.approved]["status"], "approved")
        self.assertEqual(rows["open-draft"]["status"], "draft")
        self.assertEqual(self.run_cli("task", "show", self.approved, "--json").stdout.count('"status": "approved"'), 1)
        handoff = self.run_cli("task", "handoff", self.approved, expect=1)
        self.assertEqual(handoff.stderr.strip(), self.old_approval_line().replace(f"OpenGuildKit: {self.approved}: ",
                                                                                   "OpenGuildKit [OGK-TASK-012]: ", 1))
        self.assertEqual(json.loads(self.run_cli("guard", "--json").stdout)["covered_by"], [])

    def assert_old_draft_continues(self):
        answers = Path(__file__).resolve().parents[1] / "examples" / "request-status" / "answers.json"
        self.run_cli("task", "consult", "open-draft", "--answers", answers)
        progress = json.loads(self.run_cli("task", "progress", "open-draft", "--json").stdout)
        self.assertTrue(progress)
        self.run_cli("task", "pass", "open-draft", progress[0]["board"])


class PreviousReleaseTests(UpgradeTestCase):
    """v0.16.1, the release before the catalog lock existed."""

    release = "v0.16.1"

    def test_the_previous_release_project_passes_check_update_and_update_apply(self):
        self.assert_upgrades()
        self.assert_old_approval_reopens()

    def test_its_tasks_load_and_an_old_approval_asks_for_a_new_task(self):
        self.assert_tasks_still_load()

    def test_its_draft_continues_through_consultation(self):
        self.run_cli("sync")
        self.assert_old_draft_continues()

    def test_sync_promises_no_kept_pass_for_an_approval_without_a_seal(self):
        output = self.run_cli("sync").stdout
        self.assertIn(f"  {self.approved} (approved): consult it again (openguildkit task consult {self.approved} "
                      "--reuse-answers): its approval has no valid seal, so every board reviews again and check fails "
                      "on it until then; or open a linked task with --follows.", output)
        self.assertNotIn("keeps the passes", output)
        self.assertIn(f"{self.approved} [approved, approved by Test Owner, approval no longer holds]",
                      self.run_cli("task", "list").stdout)

    def test_the_printed_command_reopens_the_old_approval_without_a_terminal(self):
        """Its answers predate the concerns question: without a terminal, the command consults them as unsure."""
        self.run_cli("sync")
        result = self.run_cli("task", "consult", self.approved, "--reuse-answers")
        self.assertIn("have no concerns", result.stderr)
        record = json.loads(self.run_cli("task", "show", self.approved, "--json").stdout)
        self.assertEqual((record["status"], record["answers"]["concerns"]), ("consulting", ["unsure"]))
        self.assertNotIn("passes", record)
        self.assertEqual(self.run_cli("check").stderr, "")

    def test_the_printed_command_reopens_the_old_approval_from_a_device_that_is_not_a_console(self):
        """Windows gives NUL as a device whose isatty() is true: no person types there, so it consults as unsure (#357)."""
        from tests.test_terminal import device_that_is_not_a_console

        self.run_cli("sync")
        with device_that_is_not_a_console():
            result = self.run_cli("task", "consult", self.approved, "--reuse-answers", stdin_text=None)
        self.assertIn("have no concerns", result.stderr)
        record = json.loads(self.run_cli("task", "show", self.approved, "--json").stdout)
        self.assertEqual((record["status"], record["answers"]["concerns"]), ("consulting", ["unsure"]))


class FirstReleaseTests(UpgradeTestCase):
    """v0.1.0, the oldest release. Its insurance sector left the catalog for a time and is bundled again."""

    release = "v0.1.0"

    def test_a_sector_missing_from_the_catalog_is_a_clean_error_naming_the_sector(self):
        profile = self.project / ".openguildkit" / "project.json"
        profile.write_text(profile.read_text(encoding="utf-8").replace('"insurance"', '"retired-sector"'), encoding="utf-8")
        for command in (("check",), ("update",), ("task", "list")):
            result = self.run_cli(*command, expect=1)
            self.assertEqual(result.stderr.strip(), (
                "OpenGuildKit: .openguildkit/project.json names the sector 'retired-sector', which neither this release "
                "nor the catalog lock provides: choose one listed by openguildkit catalog, set it in "
                ".openguildkit/project.json, then run openguildkit sync."))
            self.assertNotIn("Traceback", result.stderr)

    def test_the_first_release_project_upgrades_and_its_tasks_load(self):
        sectors = json.loads(self.run_cli("catalog", "--json").stdout)["sectors"]
        self.assertIn("insurance", sectors)
        self.assert_upgrades()
        self.assert_tasks_still_load()
        self.assert_old_draft_continues()
        self.assert_old_approval_reopens()


if __name__ == "__main__":
    import unittest

    unittest.main()
