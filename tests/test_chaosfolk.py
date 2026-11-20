"""The optional ChaosFolk integration: pack, pattern and pinned version."""

import re
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.patterns import recommend_patterns
from openguildkit.project import render_instructions, resolved_profile, validate_profile

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "integrations" / "chaosfolk" / "README.md"
COMMIT = re.compile(r"loukan42/chaosfolk(?:/blob|/commit|@|/tree)?/?([0-9a-f]{40})")


class ChaosFolkIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.pack = cls.catalog["packs"]["chaosfolk-e2e"]

    def test_pack_covers_the_replay_outcomes_and_user_isolation(self):
        rules = {rule["id"]: rule for rule in self.pack["rules"]}
        self.assertIn("gate-ci-on-replays", rules)
        gate = rules["gate-ci-on-replays"]["instruction"]
        self.assertIn("exit code 1", gate)
        self.assertIn("exit code 2", gate)
        self.assertIn("python -m chaosfolk.user", rules["isolate-simulated-users"]["instruction"])

    def test_guide_and_pack_pin_the_same_chaosfolk_commit(self):
        pinned = {COMMIT.search(source["url"]).group(1) for source in self.pack["sources"]}
        self.assertEqual(len(pinned), 1, pinned)
        commit = pinned.pop()
        guide_commits = set(COMMIT.findall(GUIDE.read_text(encoding="utf-8")))
        self.assertEqual(guide_commits, {commit})
        self.assertIn(commit[:7], self.pack["description"])
        self.assertIn(f'chaosfolk @ git+https://github.com/loukan42/chaosfolk@{commit}', GUIDE.read_text(encoding="utf-8"))

    def test_pattern_matches_only_a_stack_that_names_chaosfolk(self):
        with_chaosfolk = recommend_patterns(self.catalog, ["React", "ChaosFolk 0.8"], "general", [])
        self.assertIn("chaosfolk-e2e", {pattern["id"] for pattern in with_chaosfolk["matched"]})
        without = recommend_patterns(self.catalog, ["React", "Playwright"], "general", [])
        self.assertNotIn("chaosfolk-e2e", {pattern["id"] for pattern in without["matched"]})

    def test_projects_without_chaosfolk_keep_their_packs(self):
        profile = validate_profile({"name": "Web app", "stack": ["React", "TypeScript"]}, self.catalog)
        self.assertNotIn("chaosfolk-e2e", resolved_profile(profile, self.catalog)["packs"])

    def test_selected_pattern_writes_the_rules_into_agents_md(self):
        profile = validate_profile(
            {"name": "Web app", "stack": ["React", "ChaosFolk"]}, self.catalog
        )
        self.assertIn("chaosfolk-e2e", profile["patterns"])
        self.assertIn("chaosfolk-e2e", resolved_profile(profile, self.catalog)["packs"])
        instructions = render_instructions(profile, self.catalog)
        self.assertIn("`chaosfolk-e2e@1.0.0`", instructions)
        self.assertIn("`gate-ci-on-replays`", instructions)


if __name__ == "__main__":
    unittest.main()
