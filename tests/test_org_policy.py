"""An organization policy in the organization catalog (RFC #452, #481): a minimum every repository keeps, off unless
a person pins a commit that holds one."""

import hashlib
import json
import unittest

from tests import test_org_catalog
from tests.test_org_catalog import git


class OrgPolicyTests(unittest.TestCase):
    # The helpers of the organization catalog's tests, without running its scenarios again.
    _shared = test_org_catalog.OrgCatalogTests
    setUp, commit, cli, lock, pin = _shared.setUp, _shared.commit, _shared.cli, _shared.lock, _shared.pin
    commit_project, ci = _shared.commit_project, _shared.ci
    del _shared

    def policy(self, **policy) -> str:
        (self.org / "policy.json").write_text(json.dumps({"schema_version": 1, **policy}), encoding="utf-8")
        return self.commit("Policy")

    def profile(self) -> dict:
        return json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))

    def set_profile(self, *arguments):
        return self.cli("profile", "set", *arguments, "--by", "CM", "--reason", "Setup", typed=arguments[1])

    def test_issue_452_check_fails_under_the_minimum_and_cites_the_commit(self):
        """Issue #452: a policy that requires guard enforce left check silent in a project in observe."""
        self.set_profile("guard", "observe")
        commit = self.policy(minimum={"guard": "enforce"})
        self.pin(commit)
        result = self.cli("check", code=1)
        self.assertIn(f"The organization policy at {commit[:12]} requires guard enforce; the profile has observe",
                      result.stderr)
        sarif = json.loads(self.cli("check", "--format", "sarif", code=1).stdout)
        self.assertEqual([item["ruleId"] for item in sarif["runs"][0]["results"]
                          if item["ruleId"].startswith("policy")], ["policy-below-floor"])
        shown = self.cli("org-catalog", "policy").stdout
        self.assertIn(f"Organization policy at {commit[:12]}: guard: enforce.", shown)

    def test_issue_452_a_repository_may_be_stricter_never_less(self):
        """Issue #452: profile set guard observe was accepted at a terminal whatever the organization required."""
        commit = self.policy(minimum={"guard": "observe"})
        self.pin(commit)
        self.set_profile("guard", "enforce")
        before = (self.root / ".openguildkit" / "project.json").read_bytes()
        refused = self.cli("profile", "set", "guard", "off", "--by", "CM", "--reason", "Test", code=1, typed="off")
        self.assertIn(f"Refused: the organization policy at {commit[:12]} requires guard observe", refused.stderr)
        self.assertIn("Nothing was written", refused.stderr)
        self.assertEqual(before, (self.root / ".openguildkit" / "project.json").read_bytes())
        self.set_profile("guard", "observe")
        self.assertEqual(self.profile()["guard"], "observe")

    def test_issue_452_a_required_pack_cannot_be_removed(self):
        """Issue #452: the packs an organization requires were the choice of each repository."""
        # OGK-ORG-010
        self.pin(self.first)
        self.cli("profile", "add", "pack", "org-review", "--by", "CM", "--reason", "Org")
        self.pin(self.policy(required={"packs": ["org-review"]}))
        refused = self.cli("profile", "remove", "pack", "org-review", "--by", "CM", "--reason", "Test", code=1,
                           typed="org-review")
        self.assertIn("requires pack org-review", refused.stderr)

    def test_issue_452_guard_ci_takes_the_policy_from_the_option_not_the_lock(self):
        """Issue #452: guard --ci judged a pull request by the profile and pins of its own base only."""
        # OGK-ORG-011
        self.pin(self.first)  # The base pins a commit without a policy.
        commit = self.policy(required={"packs": ["org-review"]})
        self.commit_project()
        self.assertTrue(self.ci()["problems"])  # No decision: the change fails for that reason alone, in off mode.
        self.assertEqual(self.ci()["mode"], "off")
        result = self.ci("--org-policy", self.org, "--org-commit", commit, code=1)
        self.assertEqual(result["mode"], "enforce")
        self.assertIn(f"The organization policy at {commit[:12]} requires pack org-review", " ".join(result["problems"]))
        self.cli("guard", "--ci", "--base", "main", "--org-policy", self.org, code=1)

    def test_issue_481_an_organization_freeze_stops_every_change(self):
        """Issue #481: no freeze at the level of the organization; only each repository could freeze itself."""
        # OGK-ORG-012
        commit = self.policy(frozen={"by": "SEC", "reason": "Compromised model", "since": "2026-11-28"})
        self.commit_project()
        sarif = json.loads(self.cli("guard", "--ci", "--base", "main", "--format", "sarif", "--org-policy", self.org,
                                    "--org-commit", commit, code=1).stdout)
        frozen = [item for item in sarif["runs"][0]["results"] if item["ruleId"] == "policy-frozen"]
        self.assertIn("freezes every repository, by SEC since 2026-11-28: Compromised model", frozen[0]["message"]["text"])
        git(self.root, "checkout", "-q", "main")
        self.pin(commit)
        self.assertIn("freezes every repository", self.cli("check", code=1).stderr)

    def test_issue_452_an_invalid_policy_stops_the_pin(self):
        """Issue #452: a policy field OpenGuildKit does not enforce must not pass for one it does."""
        # OGK-ORG-009
        commit = self.policy(hosts=["codex"])
        before = (self.root / ".openguildkit" / "catalog.lock.json").read_bytes()
        refused = self.pin_refused(commit)
        self.assertIn("unknown field hosts", refused.stderr)
        self.assertEqual(before, (self.root / ".openguildkit" / "catalog.lock.json").read_bytes())

    def pin_refused(self, commit: str):
        return self.cli("org-catalog", "set", "--repo", self.org, "--commit", commit, "--by", "CM", "--reason", "Test",
                        code=1, typed=commit[:12])

    def test_issue_452_policy_repo_names_the_command_that_reads_a_policy(self):
        """Issue #452: --policy-repo on a policy commit said only that the export rule could not be read."""
        # OGK-CI-004
        commit = self.policy(minimum={"guard": "enforce"})
        result = self.cli("--policy-repo", self.org, "--policy-commit", commit, "check", code=1)
        self.assertIn("openguildkit org-catalog set --repo PATH --commit SHA", result.stderr)
        self.assertIn("--org-policy PATH --org-commit SHA", result.stderr)

    def test_issue_452_a_commit_without_a_policy_keeps_its_fingerprint_and_shows_none(self):
        """Issue #452: following an organization catalog without a policy changes nothing."""
        self.pin(self.first)
        digest = hashlib.sha256()  # The fingerprint as the organization catalog computed it before the policy.
        for path in ("packs/org-logging.json", "packs/org-review.json"):
            data = (self.org / path).read_bytes()
            digest.update(path.encode() + b"\0" + hashlib.sha256(data).hexdigest().encode() + b"\n")
        self.assertEqual(self.lock()["organization"]["fingerprint"], "sha256:" + digest.hexdigest())
        self.assertIn("No organization policy", self.cli("org-catalog", "policy").stdout)
        self.assertEqual(json.loads(self.cli("org-catalog", "policy", "--json").stdout), {"policy": None})


if __name__ == "__main__":
    unittest.main()
