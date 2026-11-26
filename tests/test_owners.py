"""Code owners of the paths a task touches, read from CODEOWNERS with GitHub's syntax (#437): shown in the decision
brief and the handoff, never written into a record."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import owners
from openguildkit.storage import write_json

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"

# The example file of GitHub's page about code owners, as it explains each line.
GITHUB_EXAMPLE = """\
# This is a comment.
*       @global-owner1 @global-owner2
*.js    @js-owner #This is an inline comment.
*.go docs@example.com
*.txt @octo-org/octocats
/build/logs/ @doctocat
docs/*  docs@example.com
apps/ @octocat
/docs/ @doctocat
/scripts/ @doctocat @octocat
**/logs @octocat
/apps/ @octocat
/apps/github
"""


class SyntaxTests(unittest.TestCase):
    def setUp(self):
        self.rules, self.skipped = owners.parse(GITHUB_EXAMPLE)

    def owners(self, path, directory=False):
        return owners.owners_of(self.rules, path, directory)

    def test_the_last_matching_rule_wins(self):
        self.assertEqual(self.owners("README.md"), ["@global-owner1", "@global-owner2"])
        self.assertEqual(self.owners("src/app.js"), ["@js-owner"])
        self.assertEqual(self.owners("scripts/app.js"), ["@doctocat", "@octocat"])
        self.assertEqual(self.owners("main.go"), ["docs@example.com"])

    def test_patterns_follow_github_examples(self):
        # /build/logs/ names @doctocat, but **/logs comes later and also covers build/logs, as GitHub's page says.
        self.assertEqual(self.owners("build/logs/today/app.log"), ["@octocat"])
        self.assertEqual(owners.owners_of(owners.parse("/build/logs/ @doctocat\n")[0], "build/logs/a/b.log"),
                         ["@doctocat"])
        self.assertIsNone(owners.owners_of(owners.parse("/build/logs/ @doctocat\n")[0], "src/build/logs/b.log"))
        self.assertEqual(self.owners("docs/getting-started.md"), ["@doctocat"])
        self.assertEqual(self.owners("docs/build-app/troubleshooting.md"), ["@doctocat"])
        self.assertEqual(self.owners("services/apps/main.py"), ["@octocat"])
        self.assertEqual(self.owners("deep/scripts/logs/run.log"), ["@octocat"])
        self.assertEqual(self.owners("apps/web/index.html"), ["@octocat"])

    def test_a_slash_in_the_middle_anchors_and_a_star_stays_in_its_folder(self):
        rules, _ = owners.parse("* @all\ndocs/* @docs\n")
        self.assertEqual(owners.owners_of(rules, "docs/getting-started.md"), ["@docs"])
        self.assertEqual(owners.owners_of(rules, "docs/build-app/troubleshooting.md"), ["@all"])
        self.assertEqual(owners.owners_of(rules, "guide/docs/getting-started.md"), ["@all"])

    def test_a_rule_without_owner_leaves_the_path_without_one(self):
        self.assertEqual(self.owners("apps/github/main.py"), [])

    def test_paths_are_case_sensitive(self):
        self.assertEqual(self.owners("Docs/guide.md"), ["@global-owner1", "@global-owner2"])

    def test_negation_and_character_ranges_are_skipped_as_github_does_not_support_them(self):
        rules, skipped = owners.parse("*.py @python\n!tests/*.py @nobody\n[ab].py @range\n")
        self.assertEqual(skipped, [2, 3])
        self.assertEqual(owners.owners_of(rules, "tests/a.py"), ["@python"])
        self.assertEqual(owners.owners_of(rules, "a.py"), ["@python"])

    def test_a_path_no_rule_matches_has_no_owner(self):
        rules, _ = owners.parse("/api/ @team-api\n")
        self.assertIsNone(owners.owners_of(rules, "web/index.html"))

    def test_a_folder_reads_the_rule_for_its_files_in_general(self):
        rules, _ = owners.parse("* @all\n/api/ @team-api\n*.sql @dba\n/api/legacy/ @old\n")
        self.assertEqual(owners.owners_of(rules, "api", directory=True), ["@team-api"])
        self.assertEqual(owners.owners_of(rules, "web", directory=True), ["@all"])
        self.assertEqual(owners.owners_of(rules, "api/legacy", directory=True), ["@old"])


class LocationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_no_file_reads_nothing(self):
        self.assertIsNone(owners.read_codeowners(self.root))

    def test_github_folder_then_root_then_docs_the_first_found_only(self):
        self.write("docs/CODEOWNERS", "* @docs\n")
        self.assertEqual(owners.read_codeowners(self.root)["file"], "docs/CODEOWNERS")
        self.write("CODEOWNERS", "* @root\n")
        self.assertEqual(owners.read_codeowners(self.root)["file"], "CODEOWNERS")
        self.write(".github/CODEOWNERS", "* @github\n")
        found = owners.read_codeowners(self.root)
        self.assertEqual(found["file"], ".github/CODEOWNERS")
        self.assertEqual(owners.owners_of(found["rules"], "x.py"), ["@github"])

    def test_a_file_over_three_megabytes_is_not_loaded(self):
        self.write("CODEOWNERS", "* @all\n" + "# padding\n" * 320_000)
        found = owners.read_codeowners(self.root)
        self.assertTrue(found["too_large"])
        self.assertIn("over 3 MB", owners.owner_line(self.root, {"id": "t", "brief": "x"}))


class DisplayTests(CapturedCli, unittest.TestCase):
    """What task challenge and task handoff print for an approved task."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        (self.root / "api").mkdir()
        (self.root / "api" / "status.py").write_text("STATUS = 1\n", encoding="utf-8")
        (self.root / "web").mkdir()

    def approved(self, brief):
        """What task challenge and task handoff print for the task, approved in between."""
        self.run_cli("task", "new", brief, "--id", TASK)
        write_json(self.root / "answers.json", json.loads((EXAMPLE / "answers.json").read_text()))
        self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
        review["boards"] = [entry for entry in review["boards"] if entry["id"] in {b["id"] for b in template["boards"]}]
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        challenge = self.run_cli("task", "challenge", TASK)[0]
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=[TASK]):
            self.run_cli("task", "decide", TASK, "--approve", "--by", "Camille", "--reason", "Agreed")
        handoff = self.run_cli("task", "handoff", TASK)[0]
        return challenge, handoff

    def test_the_decision_brief_and_the_handoff_name_the_owners_and_no_record_keeps_them(self):
        (self.root / ".github").mkdir()
        (self.root / ".github" / "CODEOWNERS").write_text("/api/ @team-api\n", encoding="utf-8")
        challenge, handoff = self.approved("Show the status from api/status.py in the web/ folder of the portal.")
        for output in (challenge, handoff):
            self.assertIn("Code owners, read from .github/CODEOWNERS (shown here, never recorded): api/status.py "
                          "@team-api; web/ no owner declared.", output)
        self.run_cli("task", "export", TASK)
        for path in (self.root / ".openguildkit").rglob("*"):
            if path.is_file():
                self.assertNotIn("@team-api", path.read_text(encoding="utf-8", errors="replace"), path)

    def test_a_task_that_names_no_path_reads_the_owners_of_the_whole_project(self):
        (self.root / "CODEOWNERS").write_text("* @everyone\n", encoding="utf-8")
        challenge, _ = self.approved("Show customers the status of their requests.")
        self.assertIn("whole project @everyone.", challenge)

    def test_a_project_without_codeowners_sees_nothing_more(self):
        challenge, handoff = self.approved("Show the status from api/status.py in the web/ folder of the portal.")
        self.assertNotIn("Code owners", challenge + handoff)


if __name__ == "__main__":
    unittest.main()
