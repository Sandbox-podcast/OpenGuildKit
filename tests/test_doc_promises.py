"""Boundaries the documentation promises, each held by a test that a one-character change to the code fails.

A mutation sample of the third audit (#298) changed each of them without any test noticing: the last day of a
share, the observed finding that high confidence needs, and the age at which a market observation is stale.
"""

import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import clock
from openguildkit.market import dossier_gaps, validate_dossier
from openguildkit.storage import write_json
from tests.support import CapturedCli

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
DOSSIER = json.loads((REPO / "examples" / "market-dossier" / "support-portals.json").read_text(encoding="utf-8"))
TASK = "request-status"


class Project(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")


class ShareLastDayTests(Project):
    """docs/documentation.md: `--until` is the last day of access; from the next day, share check lists the share."""

    def test_a_share_is_active_on_its_last_day_and_listed_by_share_check_the_next_day(self):
        page = self.root / "docs-site" / "reference" / "request-status.md"
        page.parent.mkdir(parents=True)
        page.write_text("# Shared page\n", encoding="utf-8")
        today = clock.real_today()
        self.run_cli("docs", "share", "add", "--deliverable", "docs-site/reference/request-status.md",
                     "--portal", "https://docs.example.org/p/portal", "--recipient", "client@example.org",
                     "--until", (today + timedelta(days=14)).isoformat(), "--by", "Camille")
        # docs share add refuses a last day that is not after today: the register is moved to today by hand.
        register = self.root / ".openguildkit" / "shares" / "shares.json"
        data = json.loads(register.read_text(encoding="utf-8"))
        data["shares"][0]["until"] = today.isoformat()
        register.write_text(json.dumps(data), encoding="utf-8")

        with patch("openguildkit.clock.real_today", return_value=today):
            self.assertEqual(json.loads(self.run_cli("docs", "share", "list", "--json")[0])[0]["state"], "active")
            output, _ = self.run_cli("docs", "share", "check")
            self.assertNotIn("expired", output)
        with patch("openguildkit.clock.real_today", return_value=today + timedelta(days=1)):
            output, error = self.run_cli("docs", "share", "check", code=1)
        self.assertIn("expired", output + error)
        self.assertIn("client@example.org", output + error)


class HighConfidenceTests(Project):
    """The pass instructions and docs/brains.md: proceed or high confidence needs an observed finding."""

    def entry(self, confidence):
        review = json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))
        entry = copy.deepcopy(next(board for board in review["boards"] if board["id"] == "engineering"))
        self.assertEqual(entry["challenge"]["verdict"], "revise")
        entry["challenge"]["confidence"] = confidence
        for specialist in entry["challenge"]["specialists"]:
            specialist["basis"] = "assumption"
        write_json(self.root / "engineering.json", entry)
        return self.root / "engineering.json"

    def test_a_revise_entry_with_high_confidence_and_only_assumptions_is_refused(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        self.run_cli("task", "pass", TASK, "engineering")
        _, error = self.run_cli("task", "submit", TASK, "--file", self.entry("high"), code=1)
        self.assertIn("engineering needs an observed finding and cited evidence for this review", error)
        # The same entry at medium confidence is a revise the boards may give on assumptions.
        self.assertEqual(self.run_cli("task", "submit", TASK, "--file", self.entry("medium"))[0].strip(), "done")


class MarketStaleObservationTests(unittest.TestCase):
    """docs/market.md: market check lists observations older than 180 days."""

    def test_an_observation_of_181_days_is_flagged_and_one_of_180_is_not(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        observation = dossier["observations"][0]
        observed = date.fromisoformat(observation["source"]["date"])

        def flagged(days):
            gaps = dossier_gaps(dossier, "public-sources", today=observed + timedelta(days=days))
            return f"Observation {observation['id']} is {days} days old." in gaps

        self.assertFalse(flagged(180))
        self.assertTrue(flagged(181))


class ApprovalNeutralChangeTests(Project):
    """docs/patterns.md and docs/workflow/decide.md: only a change of the rules, the checks or the boards voids an approval;
    a new tool or the guard leaves it standing."""

    RULE = "Only a change of the rules, the checks or the boards voids an approval"

    def problem(self):
        return json.loads(self.run_cli("task", "list", "--json")[0])[0].get("approval_problem")

    def test_both_pages_give_the_rule(self):
        section = (REPO / "docs" / "patterns.md").read_text(encoding="utf-8").split(
            "## Change the profile after setup", 1)[1].split("\n## ", 1)[0]
        workflow = (REPO / "docs" / "workflow" / "decide.md").read_text(encoding="utf-8")
        for page, text in (("patterns.md", section), ("workflow/decide.md", workflow)):
            with self.subTest(page=page):
                self.assertIn(self.RULE, text)
                self.assertRegex(text, r"A new (tool or convention|convention or tool), the guard[^.]*leave approvals "
                                       r"standing")
        self.assertNotIn("makes earlier approvals stale", section)

    def test_an_approval_holds_after_a_tool_and_the_guard_and_not_after_a_pack(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        write_json(self.root / "review.json", {"consultation_id": template["consultation_id"],
                                               **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))})
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        self.run_cli("task", "decide", TASK, "--approve", "--by", "CM", "--reason", "Agreed", typed=TASK)
        self.run_cli("profile", "add", "tool", "Jira", "--by", "CM", "--reason", "Tracker")
        self.run_cli("profile", "set", "guard", "enforce", "--by", "CM", "--reason", "Audit")
        self.assertIsNone(self.problem())
        output, _ = self.run_cli("profile", "add", "pack", "threat-modeling", "--by", "CM", "--reason", "Threats")
        self.assertIn(f"This change voids the approval of {TASK}", output)
        self.assertEqual(self.problem(), "earlier-rules")
        self.assertIn("earlier rules (pack threat-modeling added)", self.run_cli("check", code=1)[1])


if __name__ == "__main__":
    unittest.main()
