"""An organization catalog, pinned at a commit of a local Git copy (RFC #446): an option, off by default."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import org_catalog
from openguildkit.catalog import load_catalog

from tests.support import copy_initialized_project, run_cli

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "examples" / "request-status" / "profile.json"


def git(folder: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *arguments], check=True, capture_output=True,
                          text=True).stdout.strip()


def pack(pack_id: str, version: str = "1.0.0", **extra) -> dict:
    return {
        "id": pack_id, "title": f"Pack {pack_id}", "version": version,
        "description": "For every service of the organization: a shared rule.", "sources": [],
        "rules": [{"id": "shared-rule", "instruction": "Follow the shared rule.", "verification": "Read the diff."}],
        **extra,
    }


def write_record(folder: Path, collection: str, record: dict) -> None:
    path = folder / collection / f"{record['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


class OrgCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ogk-org-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project"
        copy_initialized_project(self, PROFILE, self.root)
        self.org = self.base / "org"
        self.org.mkdir()
        git(self.org, "init", "-q", "-b", "main")
        write_record(self.org, "packs", pack("org-review"))
        write_record(self.org, "packs", pack("org-logging"))
        self.first = self.commit("First edition")

    def commit(self, message: str) -> str:
        git(self.org, "add", "-A")
        git(self.org, "commit", "-q", "-m", message)
        return git(self.org, "rev-parse", "HEAD")

    def cli(self, *arguments, code=0, typed=None):
        return run_cli(self.root, *arguments, expect=code, typed=typed)

    def lock(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "catalog.lock.json").read_text(encoding="utf-8"))

    def pin(self, commit: str, reason: str = "Follow the platform team's packs"):
        return self.cli("org-catalog", "set", "--repo", self.org, "--commit", commit, "--by", "Camille Martin",
                        "--reason", reason, typed=commit[:12])

    def test_a_project_that_does_not_use_it_runs_no_git_and_keeps_its_lock(self):
        before = (self.root / ".openguildkit" / "catalog.lock.json").read_bytes()
        with patch.object(org_catalog.subprocess, "run", side_effect=AssertionError("git ran")):
            self.cli("check")
            self.cli("sync")
            self.cli("update", "--apply")
            shown = self.cli("org-catalog", "show")
        self.assertEqual((self.root / ".openguildkit" / "catalog.lock.json").read_bytes(), before)
        self.assertNotIn("organization", self.lock())
        self.assertIn("No organization catalog", shown.stdout)
        self.assertIn("openguildkit org-catalog set --repo PATH --commit SHA", shown.stdout)
        self.assertNotIn("organization", load_catalog(self.root / ".openguildkit" / "catalog"))

    def test_set_shows_what_the_commit_brings_then_a_person_pins_it_at_a_terminal(self):
        preview = self.cli("org-catalog", "set", "--repo", self.org, "--commit", self.first)
        self.assertIn("+ packs/org-review 1.0.0", preview.stdout)
        self.assertIn("--by INITIALS --reason WHY", preview.stdout)
        self.assertNotIn("organization", self.lock())
        refused = self.cli("org-catalog", "set", "--repo", self.org, "--commit", self.first, "--by", "CM",
                           "--reason", "Pilot", code=1)
        self.assertIn("interactive terminal", refused.stderr)
        self.assertNotIn("organization", self.lock())

        pinned = self.pin(self.first)
        self.assertIn(f"Pinned the organization catalog at {self.first[:12]}", pinned.stdout)
        organization = self.lock()["organization"]
        self.assertEqual(organization["commit"], self.first)
        self.assertTrue(organization["fingerprint"].startswith("sha256:"))
        self.assertEqual(organization["pinned"]["by"], "Camille Martin")
        self.assertEqual(organization["repo"], "../org")
        self.assertIn("org-review", json.loads(self.cli("catalog", "--json").stdout)["packs"])
        self.cli("profile", "add", "pack", "org-review", "--by", "CM", "--reason", "Shared rule")
        self.assertIn("org-review", (self.root / "AGENTS.md").read_text(encoding="utf-8"))
        self.cli("check")
        self.cli("sync")
        self.cli("update", "--apply")
        self.assertEqual(self.lock()["organization"]["commit"], self.first)

    def test_changing_the_commit_shows_additions_removals_and_versions(self):
        self.pin(self.first)
        write_record(self.org, "packs", pack("org-review", "1.1.0"))
        (self.org / "packs" / "org-logging.json").unlink()
        write_record(self.org, "packs", pack("org-privacy"))
        second = self.commit("Second edition")
        preview = json.loads(self.cli("org-catalog", "set", "--repo", self.org, "--commit", second, "--json").stdout)
        self.assertFalse(preview["applied"])
        self.assertEqual(preview["changes"]["added"], ["packs/org-privacy"])
        self.assertEqual(preview["changes"]["removed"], ["packs/org-logging"])
        self.assertEqual(preview["changes"]["changed"], [{"record": "packs/org-review", "version": ["1.0.0", "1.1.0"]}])
        self.assertEqual(self.lock()["organization"]["commit"], self.first)
        text = self.cli("org-catalog", "set", "--repo", self.org, "--commit", second).stdout
        self.assertIn("~ packs/org-review 1.0.0 -> 1.1.0", text)
        self.assertIn("- packs/org-logging", text)
        self.pin(second, "Second edition")
        self.assertEqual(self.lock()["organization"]["commit"], second)

    def test_a_removed_record_the_profile_uses_is_refused_with_what_to_do(self):
        self.pin(self.first)
        self.cli("profile", "add", "pack", "org-logging", "--by", "CM", "--reason", "Logs")
        (self.org / "packs" / "org-logging.json").unlink()
        second = self.commit("Drop logging")
        refused = self.cli("org-catalog", "set", "--repo", self.org, "--commit", second, "--by", "CM",
                           "--reason", "Next", code=1, typed=second[:12])
        self.assertIn("org-logging", refused.stderr)
        self.assertEqual(self.lock()["organization"]["commit"], self.first)

    def test_check_fails_when_the_copy_or_the_commit_is_missing_and_says_how_to_fix_it(self):
        self.pin(self.first)
        moved = self.base / "elsewhere"
        shutil.move(self.org, moved)
        missing = self.cli("check", code=1)
        self.assertIn("../org", missing.stderr)
        self.assertIn("openguildkit org-catalog set --repo PATH", missing.stderr)
        shutil.move(moved, self.org)
        self.cli("check")
        lock = self.lock()
        lock["organization"]["commit"] = "0" * 40
        (self.root / ".openguildkit" / "catalog.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        unknown = self.cli("check", code=1)
        self.assertIn("git -C ../org fetch", unknown.stderr)

    def test_files_that_differ_from_the_pinned_fingerprint_stop_every_command(self):
        self.pin(self.first)
        lock = self.lock()
        lock["organization"]["fingerprint"] = "sha256:" + "0" * 64
        (self.root / ".openguildkit" / "catalog.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        refused = self.cli("check", code=1)
        self.assertIn("fingerprint", refused.stderr)
        self.assertIn("org-catalog set", refused.stderr)

    def test_a_local_replacement_is_shown_until_a_person_accepts_it(self):
        self.pin(self.first)
        write_record(self.root / ".openguildkit" / "catalog", "packs", pack("org-review", "1.0.1"))
        checked = self.cli("check")
        self.assertIn("replaces packs/org-review of the organization catalog", checked.stderr)
        self.assertIn("openguildkit org-catalog accept packs/org-review --by INITIALS --reason WHY", checked.stderr)
        shown = json.loads(self.cli("org-catalog", "show", "--json").stdout)
        self.assertEqual(shown["replaced"], [{"record": "packs/org-review", "accepted": None}])
        self.cli("org-catalog", "accept", "packs/org-review", "--by", "CM", "--reason", "Local", code=1)
        self.cli("org-catalog", "accept", "packs/org-review", "--by", "CM", "--reason", "Stricter locally",
                 typed="packs/org-review")
        self.assertNotIn("organization catalog", self.cli("check").stderr)
        accepted = json.loads(self.cli("org-catalog", "show", "--json").stdout)["replaced"][0]["accepted"]
        self.assertEqual((accepted["by"], accepted["reason"]), ("CM", "Stricter locally"))
        self.assertIn("packs/org-review (accepted by CM", self.cli("org-catalog", "show").stdout)
        # The organization changes the record: the acceptance no longer covers it.
        write_record(self.org, "packs", pack("org-review", "2.0.0"))
        self.pin(self.commit("Rewrite review"), "Second edition")
        self.assertIn("replaces packs/org-review", self.cli("check").stderr)

    def test_sarif_names_the_replacement(self):
        self.pin(self.first)
        write_record(self.root / ".openguildkit" / "catalog", "packs", pack("org-review", "1.0.1"))
        report = json.loads(self.cli("check", "--format", "sarif").stdout)
        rules = [result["ruleId"] for result in report["runs"][0]["results"]]
        self.assertIn("catalog-org-replaced", rules)

    def test_organization_records_pass_the_project_checks_and_never_run_commands(self):
        cases = {
            "command": pack("org-run", rules=[{"id": "run", "check": {"kind": "command", "command": "true"}}]),
            "bundled": pack("secure-sdlc"),
            "field": {**pack("org-typo"), "instructions": "x"},
        }
        for name, record in cases.items():
            with self.subTest(name):
                write_record(self.org, "packs", record)
                commit = self.commit(name)
                refused = self.cli("org-catalog", "set", "--repo", self.org, "--commit", commit, code=1)
                self.assertIn(f"{commit[:12]}:packs/{record['id']}.json", refused.stderr)
                if name == "command":
                    self.assertIn("runs a command", refused.stderr)
                (self.org / "packs" / f"{record['id']}.json").unlink()
                self.commit(f"Drop {name}")

    def test_a_short_or_unknown_commit_is_refused(self):
        refused = self.cli("org-catalog", "set", "--repo", self.org, "--commit", self.first[:12], code=1)
        self.assertIn("full", refused.stderr)
        absent = self.cli("org-catalog", "set", "--repo", self.base / "absent", "--commit", self.first, code=1)
        self.assertIn("not a Git repository", absent.stderr)

    def test_profile_export_names_the_pin_and_a_new_repository_pins_it_before_init(self):
        self.pin(self.first)
        self.cli("profile", "add", "pack", "org-review", "--by", "CM", "--reason", "Shared rule")
        exported = self.cli("profile", "export")
        self.assertIn(f"openguildkit org-catalog set --repo PATH --commit {self.first}", exported.stderr)
        answers = self.base / "answers.json"
        answers.write_text(exported.stdout, encoding="utf-8")
        second = self.base / "second"
        second.mkdir()
        run_cli(second, "init", "--answers", answers, expect=1)
        run_cli(second, "org-catalog", "set", "--repo", self.org, "--commit", self.first, "--by", "CM",
                "--reason", "Same packs", typed=self.first[:12])
        run_cli(second, "init", "--answers", answers)
        lock = json.loads((second / ".openguildkit" / "catalog.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["organization"]["commit"], self.first)
        self.assertIn("org-review", (second / "AGENTS.md").read_text(encoding="utf-8"))
        run_cli(second, "check")

    def test_off_stops_following_it(self):
        self.pin(self.first)
        self.cli("profile", "add", "pack", "org-review", "--by", "CM", "--reason", "Shared rule")
        refused = self.cli("org-catalog", "off", "--by", "CM", "--reason", "Pilot over", typed="off", code=1)
        self.assertIn("openguildkit profile remove pack ID", refused.stderr)
        self.assertEqual(self.lock()["organization"]["commit"], self.first)
        self.cli("profile", "remove", "pack", "org-review", "--by", "CM", "--reason", "Pilot over")
        self.cli("org-catalog", "off", "--by", "CM", "--reason", "Pilot over", typed="off")
        self.assertNotIn("organization", self.lock())
        self.assertIn("No organization catalog", self.cli("org-catalog", "show").stdout)
        self.cli("check")


if __name__ == "__main__":
    unittest.main()
