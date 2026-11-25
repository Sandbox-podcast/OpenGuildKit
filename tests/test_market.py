import copy
import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from openguildkit import clock
from openguildkit.market import dossier_gaps, due_sources, relevance_note, scope_entry, validate_dossier
from openguildkit.storage import write_json

from tests.support import CapturedCli, run_cli

REPO = Path(__file__).resolve().parents[1]
DOSSIER = json.loads((REPO / "examples" / "market-dossier" / "support-portals.json").read_text(encoding="utf-8"))
EXAMPLE = REPO / "examples" / "request-status"
WATCH_TEMPLATE = REPO / "integrations" / "github" / "openguildkit-market-watch.yml"


def run_block(workflow: str, step: str) -> str:
    """The shell script of a workflow step's `run: |` block."""
    lines = workflow.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == f"- name: {step}")
    begin = next(index for index in range(start, len(lines)) if lines[index].strip() == "run: |") + 1
    indent = len(lines[begin]) - len(lines[begin].lstrip())
    block = []
    for line in lines[begin:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        block.append(line[indent:])
    return "\n".join(block) + "\n"


def pinned_actions(text: str) -> list[str]:
    return re.findall(r"uses: (\S+)", text)


class MarketDossierTests(unittest.TestCase):
    def test_gaps_show_missing_kinds_observations_age_and_local_policy(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        gaps = dossier_gaps(dossier, "local-only", today=date(2027, 6, 1))
        self.assertIn("Prices of direct competitors for the portal option.", gaps)
        self.assertTrue(any("days old" in gap for gap in gaps))
        self.assertTrue(any("local-only" in gap for gap in gaps))
        dossier["competitors"].append({"id": "vendor-b", "name": "Vendor B", "kind": "direct"})
        self.assertIn("No dated observation for Vendor B.", dossier_gaps(dossier, "public-sources", today=date(2026, 11, 20)))

    def test_watched_sources_come_due_and_can_be_paused(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        self.assertEqual(len(due_sources(dossier, today=date(2026, 11, 20))), 1)
        dossier["watch"]["sources"][0]["last_checked"] = "2026-11-15"
        self.assertEqual(due_sources(dossier, today=date(2026, 11, 20)), [])
        self.assertEqual(len(due_sources(dossier, today=date(2026, 12, 20))), 1)
        dossier["watch"]["paused"] = True
        self.assertEqual(due_sources(dossier, today=date(2026, 12, 20)), [])

    def test_invalid_dossiers_are_refused(self):
        broken = copy.deepcopy(DOSSIER)
        broken["observations"][0]["source"]["date"] = "last week"
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_dossier(broken, "support-portals")
        broken = copy.deepcopy(DOSSIER)
        broken["watch"]["sources"][0]["url"] = "http://example.com"
        with self.assertRaisesRegex(ValueError, "https"):
            validate_dossier(broken, "support-portals")

    def test_boards_cite_dossier_observations_in_a_consultation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            write_json(root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text()))
            run_cli(root, "init", "--answers", root / "profile.json")
            (root / ".openguildkit" / "market").mkdir()
            shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", root / ".openguildkit" / "market")
            self.assertIn("local-only", run_cli(root, "market", "check", "support-portals").stdout)
            run_cli(root, "task", "new", "--file", EXAMPLE / "brief.md", "--id", "status")
            consultation = run_cli(root, "task", "consult", "status", "--answers", EXAMPLE / "answers.json", "--market", "support-portals").stdout
            self.assertIn('"age_days"', consultation)
            template = json.loads(run_cli(root, "task", "template", "status").stdout)
            review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
            marketing = next(entry for entry in review["boards"] if entry["id"] == "marketing")
            marketing["evidence"].append({"source": "public", "ref": "market:support-portals/unknown", "supports": "x"})
            write_json(root / "review.json", review)
            error = run_cli(root, "task", "review", "status", "--file", root / "review.json", expect=1).stderr
            self.assertIn("not an observation or change", error)
            marketing["evidence"][-1] = {"source": "public", "ref": "market:support-portals/a-status-page",
                                         "supports": "A direct competitor shows a status and a response date."}
            write_json(root / "review.json", review)
            run_cli(root, "task", "review", "status", "--file", root / "review.json")
            record = json.loads(run_cli(root, "task", "show", "status").stdout)
            self.assertEqual(record["status"], "reviewed")



class MalformedDossierTests(unittest.TestCase):
    def broken(self, change):
        dossier = copy.deepcopy(DOSSIER)
        change(dossier)
        return dossier

    def test_wrongly_typed_fields_get_a_one_line_error(self):
        cases = {
            "observations must be a JSON list": lambda d: d.update(observations=None),
            "unknown competitor \\['vendor-a'\\]": lambda d: d["observations"][0].update(competitor=["vendor-a"]),
            "watch.sources must be a JSON list": lambda d: d["watch"].update(sources=None),
            "watch.changes must be a JSON list": lambda d: d["watch"].update(changes="none"),
            "unknowns must be a JSON list": lambda d: d.update(unknowns="Prices"),
            "paused is true or false": lambda d: d["watch"].update(paused="false"),
            "Watched sources are public https": lambda d: d["watch"]["sources"][0].update(url=["https://x"]),
            "real date": lambda d: d["observations"][0]["source"].update(date="2026-02-30"),
        }
        for message, change in cases.items():
            with self.subTest(message), self.assertRaisesRegex(ValueError, message):
                validate_dossier(self.broken(change), "support-portals")

    def test_dates_after_tomorrow_are_refused(self):
        later = (clock.real_today() + timedelta(days=2)).isoformat()
        tomorrow = (clock.real_today() + timedelta(days=1)).isoformat()
        for change in (lambda d: d["observations"][0]["source"].update(date=later),
                       lambda d: d["watch"]["sources"][0].update(last_checked=later),
                       lambda d: d["watch"]["changes"][0].update(date=later)):
            with self.assertRaisesRegex(ValueError, "in the future"):
                validate_dossier(self.broken(change), "support-portals")
        validate_dossier(self.broken(lambda d: d["observations"][0]["source"].update(date=tomorrow)), "support-portals")

    def test_under_local_only_a_change_from_a_public_page_is_flagged(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        flagged = [gap for gap in dossier_gaps(dossier, "local-only", today=date(2026, 11, 20)) if gap.startswith("Change 1")]
        self.assertEqual(len(flagged), 1)
        self.assertIn("public page", flagged[0])
        self.assertFalse(any(gap.startswith("Change") for gap in dossier_gaps(dossier, "public-sources", today=date(2026, 11, 20))))


class MarketCommandTests(CapturedCli, unittest.TestCase):
    cli_output = "status-stream"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"], "research": "public-sources"})
        self.cli("init", "--answers", self.root / "profile.json")

    def dossier(self, dossier_id="portals"):
        return json.loads((self.root / ".openguildkit" / "market" / f"{dossier_id}.json").read_text(encoding="utf-8"))

    def test_market_new_creates_a_dossier_that_market_check_accepts(self):
        self.assertIn("market new nope", self.cli("market", "check", "nope", code=1))
        self.cli("market", "new", "nope")
        gaps = json.loads(self.cli("market", "check", "nope", "--json"))["gaps"]
        self.assertIn("Describe the dossier's market: openguildkit market describe nope --market TEXT.", gaps)
        self.assertIn("already exists", self.cli("market", "new", "nope", code=1))
        self.cli("market", "describe", "nope", "--market", "B2B help desks", "--audience", "Support leads",
                 "--feature", "Request status")
        self.assertFalse(any("Describe" in gap for gap in json.loads(self.cli("market", "check", "nope", "--json"))["gaps"]))

    def test_commands_record_observations_changes_and_last_checked(self):
        today = clock.real_today().isoformat()
        self.cli("market", "new", "portals", "--market", "B2B help desks", "--audience", "Support leads", "--feature", "Status")
        self.cli("market", "competitor", "portals", "--competitor", "vendor-a", "--name", "Vendor A", "--kind", "direct")
        self.assertIn("--kind is direct or substitute",
                      self.cli("market", "competitor", "portals", "--competitor", "x", "--name", "X", "--kind", "other", code=1))
        self.assertIn("needs --claim, --source, --date", self.cli("market", "observe", "portals", "--competitor", "vendor-a",
                                                                  "--observation", "status-page", code=1))
        self.cli("market", "observe", "portals", "--competitor", "vendor-a", "--observation", "status-page",
                 "--claim", "Shows a status per request.", "--source", "https://example.com/vendor-a/features", "--date", "2026-11-02")
        self.cli("market", "unknown", "portals", "--text", "Prices of the portal option.")
        self.cli("market", "watch", "portals", "--competitor", "vendor-a", "--url", "https://example.com/vendor-a/releases",
                 "--kind", "release notes", "--every-days", "14")
        self.assertIn("vendor-a release notes", self.cli("market", "due", "portals"))
        self.cli("market", "checked", "portals", "--url", "https://example.com/vendor-a/releases")
        self.assertEqual(self.dossier()["watch"]["sources"][0]["last_checked"], today)
        self.assertIn("No source due", self.cli("market", "due", "portals"))
        self.cli("market", "change", "portals", "--competitor", "vendor-a", "--what", "Added priority labels.",
                 "--source", "https://example.com/vendor-a/releases", "--date", "2026-11-10", "--verified-by", "Camille Martin")
        watch = self.dossier()["watch"]
        self.assertEqual(watch["changes"][0]["verified_by"], "Camille Martin")
        self.assertEqual(watch["sources"][0]["last_checked"], today)
        self.assertIn("unknown competitor", self.cli("market", "change", "portals", "--competitor", "nobody", "--what", "x",
                                                     "--source", "https://example.com", "--date", "2026-11-10",
                                                     "--verified-by", "Camille", code=1))
        self.assertIn("in the future", self.cli("market", "observe", "portals", "--competitor", "vendor-a", "--observation",
                                                "later", "--claim", "x", "--source", "notes", "--date", "2099-01-01", code=1))
        self.cli("market", "unknown", "portals", "--text", "Prices of the portal option.", "--remove")
        self.cli("market", "pause", "portals")
        self.assertIn("Watch paused.", self.cli("market", "due", "portals"))
        self.assertEqual(self.dossier()["unknowns"], [])

    def test_market_resume_lists_the_sources_due_again_after_a_pause(self):
        self.cli("market", "new", "portals", "--market", "B2B help desks", "--audience", "Support leads", "--feature", "Status")
        self.cli("market", "competitor", "portals", "--competitor", "vendor-a", "--name", "Vendor A", "--kind", "direct")
        self.cli("market", "watch", "portals", "--competitor", "vendor-a", "--url", "https://example.com/vendor-a/releases",
                 "--kind", "release notes")
        self.cli("market", "pause", "portals")
        self.assertIn("Watch paused.", self.cli("market", "due", "portals"))
        self.cli("market", "resume", "portals")
        self.assertFalse(self.dossier()["watch"]["paused"])
        self.assertIn("vendor-a release notes", self.cli("market", "due", "portals"))

    def test_market_unknown_preserves_the_other_sections_and_line_endings(self):
        self.cli("market", "new", "portals", "--market", "B2B help desks", "--audience", "Support leads",
                 "--feature", "Status")
        path = self.root / ".openguildkit" / "market" / "portals.json"
        text = path.read_text(encoding="utf-8").replace(
            '"observations": [],', '"observations"   :   [],'
        ).replace('"unknowns": []', '"unknowns": [\n    "Unknown A",\n    "Unknown B"\n  ]')
        source = b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode("utf-8")
        path.write_bytes(source)
        self.cli("market", "unknown", "portals", "--text", "Unknown A", "--remove")
        self.assertEqual(path.read_bytes(), source.replace(b'    "Unknown A",\r\n', b""))
        self.cli("market", "describe", "portals", "--title", "Portals in Europe")
        self.assertIn(b'"observations"   :   [],', path.read_bytes())
        self.assertEqual(json.loads(path.read_bytes())["title"], "Portals in Europe")

    def test_local_only_due_explains_how_to_record_a_page_given_by_a_person(self):
        path = self.root / ".openguildkit" / "project.json"
        profile = json.loads(path.read_text(encoding="utf-8"))
        write_json(path, {**profile, "research": "local-only"})
        self.cli("market", "new", "portals")
        self.cli("market", "competitor", "portals", "--competitor", "vendor-a", "--name", "Vendor A", "--kind", "direct")
        url = "https://example.com/vendor-a/releases"
        self.cli("market", "watch", "portals", "--competitor", "vendor-a", "--url", url, "--kind", "release notes")
        due = self.cli("market", "due", "portals")
        self.assertIn("a person reviews each page, then records it with openguildkit market provided", due)
        self.assertIn(url, due)
        self.cli("market", "provided", "portals", "--url", url, "--by", "Camille Martin")
        self.assertEqual(self.dossier()["watch"]["sources"][0]["provided_by"], "Camille Martin")
        self.assertEqual(json.loads(self.cli("market", "due", "portals", "--json"))["due"], [])

    def test_the_scheduled_job_opens_one_issue_per_source_due_in_the_example_dossier(self):
        workflow = WATCH_TEMPLATE.read_text(encoding="utf-8")
        repository_pins = set()
        for path in (REPO / ".github" / "workflows").glob("*.yml"):
            repository_pins |= {use for use in pinned_actions(path.read_text(encoding="utf-8")) if "@" in use}
        for use in pinned_actions(workflow):
            self.assertRegex(use, r"@[0-9a-f]{40}$")
            self.assertIn(use, repository_pins)
        self.assertIn("run: openguildkit market due --all --json > due.json", workflow)
        (self.root / ".openguildkit" / "market").mkdir()
        shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", self.root / ".openguildkit" / "market")
        due = json.loads(self.cli("market", "due", "--all", "--json"))
        self.assertEqual([item["url"] for item in due["due"]], ["https://example.com/vendor-a/release-notes"])
        issue = due["due"][0]["issue"]
        self.assertEqual(issue["title"], "Market watch: review vendor-a release notes (support-portals)")
        self.assertIn("openguildkit market checked support-portals --url https://example.com/vendor-a/release-notes", issue["body"])
        bash, jq = shutil.which("bash"), shutil.which("jq")
        if os.name == "nt" or not bash or not jq:
            self.skipTest("Running the workflow step needs bash and jq, as on the GitHub runner.")
        work = self.root / "job"
        (work / "bin").mkdir(parents=True)
        (work / "due.json").write_text(json.dumps(due), encoding="utf-8")
        fake = work / "bin" / "gh"
        fake.write_text("#!/bin/sh\nif [ \"$2\" = list ]; then cat \"$OPEN_TITLES\"; exit 0; fi\n"
                        "printf '%s\\n' \"$@\" >> \"$GH_LOG\"\n", encoding="utf-8")
        fake.chmod(0o755)
        script = run_block(workflow, "Open an issue per source to review")
        environment = {**os.environ, "PATH": f"{work / 'bin'}{os.pathsep}{os.environ['PATH']}",
                       "GH_LOG": str(work / "gh.log"), "OPEN_TITLES": str(work / "open.txt")}
        (work / "open.txt").write_text("Unrelated issue\n", encoding="utf-8")
        subprocess.run([bash, "-e", "-c", script], cwd=work, env=environment, check=True, capture_output=True)
        calls = (work / "gh.log").read_text(encoding="utf-8")
        self.assertIn(f"--title\n{issue['title']}\n--body\n", calls)
        self.assertIn("market checked support-portals", calls)
        (work / "gh.log").unlink()
        (work / "open.txt").write_text(issue["title"] + "\n", encoding="utf-8")
        result = subprocess.run([bash, "-e", "-c", script], cwd=work, env=environment, check=True, capture_output=True, text=True)
        self.assertIn("Already open", result.stdout)
        self.assertFalse((work / "gh.log").exists())


if __name__ == "__main__":
    unittest.main()


class MarketLayoutAndRelevanceTests(CapturedCli, unittest.TestCase):
    """A dossier keeps one layout, says when it is about another function, and records pages a person provided."""

    cli_output = "status-stream"
    URL = "https://example.com/vendor-a/release-notes"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.cli("init", "--answers", self.root / "profile.json")
        self.path = self.root / ".openguildkit" / "market" / "support-portals.json"
        self.path.parent.mkdir()
        shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", self.path)

    def changed_lines(self, *args):
        """The lines a command removes and adds in the dossier file, as a unified diff counts them."""
        before = self.path.read_text(encoding="utf-8").splitlines()
        self.cli("market", *args)
        after = self.path.read_text(encoding="utf-8").splitlines()
        diff = list(difflib.unified_diff(before, after, lineterm="", n=0))[2:]
        removed = [line[1:] for line in diff if line.startswith("-")]
        added = [line[1:] for line in diff if line.startswith("+")]
        return removed, added

    def test_a_one_line_change_gives_a_one_line_diff(self):
        self.assertEqual(self.changed_lines("describe", "support-portals", "--title", "Customer support portals"), ([], []))
        self.assertEqual(self.changed_lines("describe", "support-portals", "--audience", "Support leads"),
                         (['  "audience": "Customers of a support desk who follow their own requests",'],
                          ['  "audience": "Support leads",']))
        removed, added = self.changed_lines("unknown", "support-portals", "--text", "Renewal discounts.")
        self.assertEqual(removed, ['    "Prices of direct competitors for the portal option."'])
        self.assertEqual(added, ['    "Prices of direct competitors for the portal option.",', '    "Renewal discounts."'])
        self.assertEqual(self.changed_lines("unknown", "support-portals", "--text", "Renewal discounts.", "--remove"),
                         (added, removed))
        profile = self.root / ".openguildkit" / "project.json"
        write_json(profile, {**json.loads(profile.read_text(encoding="utf-8")), "research": "public-sources"})
        removed, added = self.changed_lines("checked", "support-portals", "--url", self.URL, "--date", "2026-11-12")
        self.assertEqual(len(removed), 1)
        self.assertEqual(len(added), 1)
        self.assertIn('"last_checked": "2026-11-12"', added[0])

    def test_a_consultation_says_in_one_line_when_the_dossier_is_about_another_function(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        note = scope_entry(dossier, "local-only", date(2026, 11, 20),
                           brief="Recommend whether the pricing page should compare our plans with competitors.")
        self.assertEqual(len(note["relevance"].splitlines()), 1)
        self.assertIn("support-portals", note["relevance"])
        self.assertNotIn("relevance", scope_entry(dossier, "local-only", date(2026, 11, 20),
                                                  brief="Show the next step of each request in the customer portal."))
        self.assertIsNone(relevance_note(dossier, "Add a portal page"))
        self.cli("task", "new", "Recommend whether the pricing page should compare our plans with competitors.",
                 "--id", "pricing")
        write_json(self.root / "a.json", {"kind": "decision", "surface": ["business"], "data": "none", "research": "local",
                                          "concerns": ["none"]})
        output = self.cli("task", "consult", "pricing", "--answers", self.root / "a.json", "--market", "support-portals")
        self.assertIn('\nRelevance: The dossier support-portals is about', output)

    def test_the_field_scenario_that_names_the_dossier_in_its_answers_still_gets_the_note(self):
        scenario = json.loads((REPO / "examples" / "field-tests" / "scenarios" / "s2" / "task.json").read_text(
            encoding="utf-8"))
        self.cli("task", "new", scenario["brief"], "--id", scenario["id"])
        answers = write_json(self.root / "s2.json", scenario["answers"]) or self.root / "s2.json"
        output = self.cli("task", "consult", scenario["id"], "--answers", answers, "--market", "support-portals")
        self.assertIn('\nRelevance: The dossier support-portals is about', output)
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        for mention in ("support-portals", "market/support-portals.json", "SUPPORT-PORTALS"):
            with self.subTest(mention=mention):
                self.assertIsNotNone(relevance_note(dossier, f"Compare plan prices. Use the dossier {mention}."))
        self.assertIsNone(relevance_note(dossier, "Use support-portals to compare the customer portal status pages."))

    def test_under_local_only_no_page_is_marked_reviewed_without_a_person(self):
        before = self.path.read_bytes()
        refused = self.cli("market", "checked", "support-portals", "--url", self.URL, code=1)
        self.assertIn("Research is local-only", refused)
        self.assertIn(f"openguildkit market provided support-portals --url {self.URL} --by NAME", refused)
        change = ("market", "change", "support-portals", "--competitor", "vendor-a", "--what", "Added labels.",
                  "--source", self.URL, "--date", "2026-11-10", "--verified-by", "Camille Martin")
        refused = self.cli(*change, code=1)
        self.assertIn(f"openguildkit market provided support-portals --url {self.URL} --by NAME", refused)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertIn(self.URL, self.cli("market", "due", "support-portals"))
        # The issue the scheduled job opens names the command the policy allows.
        body = json.loads(self.cli("market", "due", "--all", "--json"))["due"][0]["issue"]["body"]
        self.assertIn(f"openguildkit market provided support-portals --url {self.URL} --by NAME", body)
        self.assertNotIn("market checked", body)
        # A change from a page that is not watched does not mark a page reviewed: it is recorded.
        self.cli("market", "change", "support-portals", "--competitor", "vendor-a", "--what", "Shared in a meeting.",
                 "--source", "Notes of the sales meeting", "--date", "2026-11-10", "--verified-by", "Camille Martin")
        # Once a person provided the page, the change it holds is recorded.
        self.cli("market", "provided", "support-portals", "--url", self.URL, "--by", "Camille Martin")
        self.cli(*change)
        changes = json.loads(self.path.read_text(encoding="utf-8"))["watch"]["changes"]
        self.assertEqual([item["what"] for item in changes][-2:], ["Shared in a meeting.", "Added labels."])

    def test_under_local_only_a_person_records_a_page_they_provided(self):
        due = self.cli("market", "due", "support-portals")
        self.assertIn(self.URL, due)
        self.assertIn("market provided", due)
        self.assertIn("needs --by", self.cli("market", "provided", "support-portals", "--url", self.URL, code=1))
        self.assertIn("not a watched source",
                      self.cli("market", "provided", "support-portals", "--url", "https://example.com/other", "--by",
                               "Camille Martin", code=1))
        self.cli("market", "provided", "support-portals", "--url", self.URL, "--by", "Camille Martin")
        source = json.loads(self.path.read_text(encoding="utf-8"))["watch"]["sources"][0]
        self.assertEqual(source["provided_by"], "Camille Martin")
        self.assertEqual(source["last_checked"], clock.real_today().isoformat())
        self.assertEqual(self.cli("market", "due", "support-portals").strip(), "No source due for review.")
        self.assertFalse(any(gap.startswith("- Change 1") for gap in self.cli("market", "check", "support-portals").splitlines()))
