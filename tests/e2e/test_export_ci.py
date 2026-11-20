"""Replay a central policy change against two unchanged Git commits."""

import json
import subprocess
from pathlib import Path

from .test_cli_flow import CliTestCase


EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "export-expiry"
POLICY = Path("packs/export-link-expiry.json")


class ExportCiTests(CliTestCase):
    def git(self, repo, *args):
        return subprocess.check_output(
            ["git", "-C", str(repo), *args], text=True, encoding="utf-8"
        ).strip()

    def commit(self, repo, path, data):
        if not (repo / ".git").is_dir():
            repo.mkdir()
            self.git(repo, "init", "--quiet")
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data), encoding="utf-8")
        self.git(repo, "add", str(path))
        self.git(
            repo, "-c", "user.name=OpenGuildKit tests", "-c", "user.email=tests@example.invalid",
            "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "Record fixture",
        )
        return self.git(repo, "rev-parse", "HEAD")

    def setUp(self):
        super().setUp()
        self.policy = self.project / "policy"
        self.pack = json.loads((EXAMPLE / "policy" / POLICY).read_text(encoding="utf-8"))
        self.original = self.commit(self.policy, POLICY, self.pack)
        self.with_policy(self.original, "init", "--answers", EXAMPLE / "project.json")

    def with_policy(self, policy_commit, *args, expect=0):
        return self.run_cli(
            "--policy-repo", self.policy, "--policy-commit", policy_commit, *args, expect=expect
        )

    def evaluate(self, policy, repo, commit, expect=0):
        return self.with_policy(policy, "ci-check", "--target-repo", repo, "--commit", commit, expect=expect)

    def test_two_targets_are_rechecked_with_identical_inputs_per_policy(self):
        first = self.project / "repo-a"
        second = self.project / "repo-b"
        head_a = self.commit(first, "export.json", {"downloadLinkMinutes": 45})
        head_b = self.commit(second, "export.json", {"downloadLinkMinutes": 30})

        before_a = json.loads(self.evaluate(self.original, first, head_a).stdout)
        before_b = json.loads(self.evaluate(self.original, second, head_b).stdout)
        self.assertEqual((before_a["status"], before_b["status"]), ("success", "success"))

        self.pack["version"] = "2.0.0"
        self.pack["rules"][0]["check"]["max_minutes"] = 30
        updated = self.commit(self.policy, POLICY, self.pack)
        (first / "export.json").write_text('{"downloadLinkMinutes": 10}', encoding="utf-8")
        self.with_policy(updated, "check", expect=1)
        self.with_policy(updated, "sync")
        self.with_policy(updated, "check")

        after_a = json.loads(self.evaluate(updated, first, head_a, expect=1).stdout)
        after_b = json.loads(self.evaluate(updated, second, head_b).stdout)
        self.assertEqual((after_a["status"], after_b["status"]), ("failure", "success"))
        self.assertEqual((after_a["actual_minutes"], after_b["actual_minutes"]), (45, 30))
        instructions = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        for previous, current, head in [(before_a, after_a, head_a), (before_b, after_b, head_b)]:
            self.assertEqual((previous["commit"], current["commit"]), (head, head))
            self.assertEqual((previous["policy_commit"], current["policy_commit"]), (self.original, updated))
            self.assertEqual(current["max_minutes"], 30)
            self.assertIn(current["instruction"], instructions)
            self.assertIn(current["policy_commit"], instructions)
            self.assertIn(current["profile_fingerprint"], instructions)
        self.assertEqual(json.loads(self.evaluate(self.original, first, head_a).stdout), before_a)

    def test_invalid_values_and_unpinned_revisions_fail_closed(self):
        target = self.project / "repo"
        head = self.commit(target, "export.json", {"downloadLinkMinutes": True})
        invalid = json.loads(self.evaluate(self.original, target, head, expect=1).stdout)
        self.assertEqual(invalid["status"], "failure")
        self.assertIsNone(invalid["actual_minutes"])
        self.assertIn("full lowercase Git commit SHA", self.evaluate(self.original, target, "HEAD", expect=2).stderr)
        self.assertIn("full lowercase Git commit SHA", self.evaluate("HEAD", target, head, expect=2).stderr)

        self.pack["rules"][0]["check"]["max_minutes"] = True
        malformed = self.commit(self.policy, POLICY, self.pack)
        self.assertIn("positive integer max_minutes", self.evaluate(malformed, target, head, expect=2).stderr)
