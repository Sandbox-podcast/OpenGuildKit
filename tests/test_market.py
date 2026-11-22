import contextlib
import copy
import difflib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from openguildkit.cli import main
from openguildkit import clock
from openguildkit.market import dossier_gaps, due_sources, relevance_note, scope_entry, validate_dossier
from openguildkit.storage import write_json

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

            def cli(*args, code=0):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(main(["--project", str(root), *map(str, args)]), code, err.getvalue())
                return out.getvalue(), err.getvalue()

            write_json(root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text()))
            cli("init", "--answers", root / "profile.json")
            (root / ".openguildkit" / "market").mkdir()
            shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", root / ".openguildkit" / "market")
            self.assertIn("local-only", cli("market", "check", "support-portals")[0])
            cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "status")
            consultation, _ = cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json", "--market", "support-portals")
            self.assertIn('"age_days"', consultation)
            template = json.loads(cli("task", "template", "status")[0])
            review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
            marketing = next(entry for entry in review["boards"] if entry["id"] == "marketing")
            marketing["evidence"].append({"source": "public", "ref": "market:support-portals/unknown", "supports": "x"})
            write_json(root / "review.json", review)
            _, error = cli("task", "review", "status", "--file", root / "review.json", code=1)
            self.assertIn("not an observation or change", error)
            marketing["evidence"][-1] = {"source": "public", "ref": "market:support-portals/a-status-page",
                                         "supports": "A direct competitor shows a status and a response date."}
            write_json(root / "review.json", review)
            cli("task", "review", "status", "--file", root / "review.json")
            record = json.loads(cli("task", "show", "status")[0])
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
        later = (date.today() + timedelta(days=2)).isoformat()
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
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


class MarketCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {"name": "Portal", "stack": ["Python"], "research": "public-sources"})
        self.cli("init", "--answers", self.root / "profile.json")

    def cli(self, *args, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(main(["--project", str(self.root), *map(str, args)]), code, err.getvalue())
        return out.getvalue() if code == 0 else err.getvalue()

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
        today = date.today().isoformat()
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


class MarketLayoutAndRelevanceTests(unittest.TestCase):
    """A dossier keeps one layout, says when it is about another function, and records pages a person provided."""

    URL = "https://example.com/vendor-a/release-notes"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {"name": "Portal", "stack": ["Python"]})
        MarketCommandTests.cli(self, "init", "--answers", self.root / "profile.json")
        self.path = self.root / ".openguildkit" / "market" / "support-portals.json"
        self.path.parent.mkdir()
        shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", self.path)

    def cli(self, *args, code=0):
        return MarketCommandTests.cli(self, *args, code=code)

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
        write_json(self.root / "a.json", {"kind": "decision", "surface": ["business"], "data": "none", "research": "local"})
        output = self.cli("task", "consult", "pricing", "--answers", self.root / "a.json", "--market", "support-portals")
        self.assertIn('"relevance": "The dossier support-portals is about', output)

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
        self.assertEqual(source["last_checked"], clock.today().isoformat())
        self.assertEqual(self.cli("market", "due", "support-portals").strip(), "No source due for review.")
        self.assertFalse(any(gap.startswith("- Change 1") for gap in self.cli("market", "check", "support-portals").splitlines()))
