"""A board's entry: every problem reported at once with its key and accepted values, and passes that can be
read again without counting an attempt."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.board_entries import validate_board_entry
from openguildkit.catalog import load_catalog
from openguildkit.consultation import board_brief, code_not_found, consult
from openguildkit.project import validate_profile
from openguildkit.project_rules import resolved_profile
from openguildkit.storage import write_json
from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
TASK = "request-status"


def example_entries() -> dict:
    return {entry["id"]: entry for entry in json.loads((EXAMPLE / "review.json").read_text())["boards"]}


class EntryValidationTests(unittest.TestCase):
    def setUp(self):
        catalog = load_catalog()
        profile = resolved_profile(validate_profile(json.loads((EXAMPLE / "profile.json").read_text()), catalog), catalog)
        task = {"id": TASK, "brief": (EXAMPLE / "brief.md").read_text(),
                "answers": json.loads((EXAMPLE / "answers.json").read_text())}
        self.catalog, self.profile, self.task = catalog, profile, task
        self.consultation = consult(profile, catalog, task)

    def test_every_problem_of_an_entry_comes_at_once_with_its_key_and_the_accepted_values(self):
        """Issue 166: a team learnt one error per submission, without the key or the accepted values."""
        entry = copy.deepcopy(example_entries()["marketing"])
        entry["evidence"][0]["source"] = "opinion"
        entry["challenge"].update(verdict="go", confidence="top")
        entry["challenge"]["specialists"][0]["basis"] = "seen"
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(self.consultation, entry)
        message = str(raised.exception)
        self.assertTrue(message.startswith("marketing entry has 4 problems:"), message)
        self.assertIn('marketing.evidence[1].source: got "opinion"; accepted: requester, project-file', message)
        self.assertIn('marketing.challenge.verdict: got "go"; accepted: proceed, revise, block, insufficient-evidence.',
                      message)
        self.assertIn('marketing.challenge.confidence: got "top"; accepted: low, medium, high.', message)
        lens = entry["challenge"]["specialists"][0]["id"]
        self.assertIn(f'marketing/{lens} basis: got "seen"; accepted: observed, assumption, missing.', message)

    def test_an_entry_of_the_wrong_shape_names_its_keys(self):
        with self.assertRaisesRegex(ValueError, r"id: got null; write the board's ID, one of product, "):
            validate_board_entry(self.consultation, {"board": "security"})
        entry = copy.deepcopy(example_entries()["security"])
        del entry["open_questions"]
        entry["notes"] = "x"
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(self.consultation, entry)
        self.assertIn("security: missing open_questions.", str(raised.exception))
        self.assertIn("security: unknown notes; accepted keys: ", str(raised.exception))

    def test_a_structural_error_does_not_hide_the_others_and_a_blocker_is_reported_once(self):
        """Issue 166: a missing key hid the shape errors of the other fields."""
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(self.consultation, {"id": "security", "evidence": "x", "challenge": {"specialists": "y"}})
        message = str(raised.exception)
        self.assertIn("security: missing open_questions, recommendation.", message)
        self.assertIn('security.evidence: got "x"; expected a list of evidence items.', message)
        self.assertIn('security.challenge.specialists: got "y"; expected a list of lens findings.', message)
        self.assertIn("security.challenge: missing", message)
        entry = copy.deepcopy(example_entries()["security"])
        entry["challenge"].update(verdict="block", blockers=[{"finding": "No limit."}])
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(self.consultation, entry)
        message = str(raised.exception)
        self.assertEqual(message.count("blockers[0]"), 1, message)
        self.assertIn("security.challenge.blockers[0]: missing clears_when, owner.", message)

    def test_a_bad_evidence_ref_is_reported_once_counted_from_one(self):
        entry = copy.deepcopy(example_entries()["security"])
        entry["evidence"][0] = {"source": "public", "ref": "https://example.com/x?token=ghp_" + "a" * 36,
                                "supports": "A page.", "date": "2026-11-20"}
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(self.consultation, entry, Path(__file__).resolve().parents[1])
        message = str(raised.exception)
        self.assertNotIn("evidence[0]", message)
        self.assertEqual(message.count("security.evidence[1].ref"), 1, message)

    def test_a_tool_name_is_accepted_in_any_case_and_recorded_in_the_registry_case(self):
        consultation = consult(self.profile, self.catalog, self.task,
                               tools=[{"id": "jira", "title": "Jira", "server": "jira", "mode": "mock"}])
        entry = copy.deepcopy(example_entries()["security"])
        entry["evidence"][0] = {"source": "tool", "ref": "JIRA:SUP-142", "supports": "The ticket."}
        self.assertEqual(validate_board_entry(consultation, entry)["evidence"][0]["ref"], "jira:SUP-142")

    def test_evidence_refs_are_positions_in_the_entry_counted_from_one(self):
        """Issue 166: a team read evidence_refs as paths, another counted from zero."""
        entry = copy.deepcopy(example_entries()["product"])
        entry["challenge"]["specialists"][0]["evidence_refs"] = [0, 9]
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(self.consultation, entry)
        message = str(raised.exception)
        count = len(entry["evidence"])
        self.assertIn("[0, 9] must point to the board's evidence list", message)
        self.assertIn(f"counted from 1 ([1, 3] cites its first and third items); valid here: 1 to {count}.", message)

    def test_the_template_shows_the_accepted_values_of_each_choice(self):
        challenge = self.consultation["review_template"]["boards"][0]["challenge"]
        self.assertEqual(challenge["verdict"], "proceed | revise | block | insufficient-evidence")
        self.assertEqual(challenge["confidence"], "low | medium | high")
        self.assertEqual(challenge["specialists"][0]["basis"], "observed | assumption | missing")
        self.assertEqual(set(self.consultation["review_template"]["blocker_item"]), {"finding", "owner", "clears_when", "phase"})
        self.assertIn("approval | verification", self.consultation["review_template"]["blocker_item"]["phase"])
        self.assertIn("counted from 1", board_brief(self.consultation, "security"))

    def test_the_consultation_shows_the_market_dossier_relevance_in_one_line(self):
        market = {"id": "portals", "observations": [], "relevance": "The dossier support-portals shares no word with the brief."}
        markdown = consult(self.profile, self.catalog, self.task, market=market)["markdown"]
        self.assertIn("Relevance: The dossier support-portals shares no word with the brief.\n", markdown)

    def test_a_lens_that_names_other_surfaces_is_listed_as_not_concerned_and_not_demanded(self):
        catalog = copy.deepcopy(self.catalog)
        lenses = catalog["boards"]["engineering"]["review"]["specialists"]
        lenses[0]["applies_to"] = ["customer"]
        lenses[1]["applies_to"] = ["infrastructure"]
        task = {**self.task, "answers": {**self.task["answers"], "surface": ["service"]}}
        consultation = consult(self.profile, catalog, task)
        template = next(item for item in consultation["review_template"]["boards"] if item["id"] == "engineering")
        demanded = [lens["id"] for lens in template["challenge"]["specialists"]]
        # The bundled browser lenses name customer too (#152), so a service task is not asked for them either.
        self.assertEqual(demanded, [lens["id"] for lens in lenses[2:] if "service" in lens.get("applies_to", ["service"])])
        self.assertNotIn("frontend-rendering", demanded)
        brief = board_brief(consultation, "engineering")
        self.assertIn(f"- Not concerned: {lenses[0]['id']}, which applies to tasks that touch the customer-facing "
                      "experience, and this task does not.", brief)
        entry = copy.deepcopy(example_entries()["engineering"])
        entry["challenge"]["specialists"] = [
            {"id": lens["id"], "finding": "Checked.", "basis": "assumption", "evidence_refs": []} for lens in lenses]
        with self.assertRaises(ValueError) as raised:
            validate_board_entry(consultation, entry)
        self.assertIn(f"{lenses[0]['id']} is not concerned by this task's surfaces: remove it from the entry.",
                      str(raised.exception))
        unsure = consult(self.profile, catalog, {**task, "answers": {**task["answers"], "surface": ["unsure"]}})
        template = next(item for item in unsure["review_template"]["boards"] if item["id"] == "engineering")
        self.assertEqual(len(template["challenge"]["specialists"]), len(lenses))


class CodeNotFoundTests(unittest.TestCase):
    def test_a_bug_brief_naming_missing_code_is_flagged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.js").write_text("function health() { return 'ok'; }\n", encoding="utf-8")
            (root / "node_modules" / "x").mkdir(parents=True)
            (root / "node_modules" / "x" / "export.js").write_text("function exportCsv() {}\n", encoding="utf-8")
            brief = "Fix the CSV bug in src/export.js: exportCsv() and `health` escape cells; see src/app.js."
            self.assertEqual(code_not_found(brief, root), ["src/export.js", "exportCsv()"])
            self.assertEqual(code_not_found("Fix the bug in src/app.js function missingFn: wrong total", root),
                             ["missingFn()"])
            self.assertEqual(code_not_found("Fix the bug in src/app.js function health: wrong total", root), [])
            self.assertEqual(code_not_found("Corrige la fonction calculerTotal dans src/app.js", root),
                             ["calculerTotal()"])


class PassCommandTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.run_cli("task", "consult", TASK, "--answers", EXAMPLE / "answers.json")

    def progress(self, board):
        items = json.loads(self.run_cli("task", "progress", TASK, "--json")[0])
        return next(item for item in items if item["board"] == board)

    def test_a_submitted_pass_is_printed_read_only_unless_asked_again(self):
        """A host that ran task pass again on a done pass silently reopened it and lost the entry."""
        self.run_cli("task", "pass", TASK, "qa")
        write_json(self.root / "qa.json", example_entries()["qa"])
        self.run_cli("task", "submit", TASK, "--file", self.root / "qa.json")
        printed, note = self.run_cli("task", "pass", TASK, "qa")
        self.assertIn("# Board pass: qa", printed)
        self.assertIn(f"already submitted; to redo it on purpose, run openguildkit task pass {TASK} qa --again", note)
        self.assertEqual((self.progress("qa")["status"], self.progress("qa")["attempts"]), ("done", 1))
        self.run_cli("task", "pass", TASK, "qa", "--again")
        self.assertEqual((self.progress("qa")["status"], self.progress("qa")["attempts"]), ("started", 2))

    def test_a_regulation_the_answers_select_comes_before_the_stack_in_a_pass(self):
        """A security pass printed nextjs and postgresql rules and left gdpr unprinted for lack of room."""
        self.root = self.root / "personal-data"
        self.root.mkdir()
        profile = json.loads((EXAMPLE / "profile.json").read_text())
        profile.update(checks=[], patterns=["gdpr-personal-data", "python-fastapi-postgresql", "nextjs-react"])
        write_json(self.root / "profile.json", profile)
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "personal")
        self.run_cli("task", "consult", "personal", "--answers", EXAMPLE / "answers.json")
        security, _ = self.run_cli("task", "pass", "personal", "security")
        rules = security[security.index("## Rules of this board's packs"):]
        first_pack = rules.splitlines()[2]
        self.assertIn("(gdpr@", first_pack)

    def test_reading_a_pass_again_counts_no_attempt(self):
        """Issue 166: reading a pass twice showed attempts 2."""
        first, _ = self.run_cli("task", "pass", TASK, "security")
        again, _ = self.run_cli("task", "pass", TASK, "security")
        self.assertEqual(first, again)
        self.assertEqual(self.progress("security")["attempts"], 1)
        read, _ = self.run_cli("task", "brief", TASK, "--board", "product")
        self.assertIn("# Board pass: product", read)
        self.assertEqual(self.progress("product")["status"], "missing")
        scope = json.loads(self.run_cli("task", "brief", TASK, "--scope")[0])
        self.assertTrue(all(pack["rules"] for pack in scope["packs"]))

    def test_a_damaged_stored_brief_is_reported_when_the_pass_is_printed(self):
        path = self.root / ".openguildkit" / "tasks" / f"{TASK}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["consultation"]["board_briefs"]["security"]["lenses"] = [None]
        path.write_text(json.dumps(record), encoding="utf-8")
        self.run_cli("task", "list")
        for command in (("task", "pass", TASK, "security"), ("task", "brief", TASK, "--board", "security")):
            _, error = self.run_cli(*command, code=1)
            self.assertIn("consultation.board_briefs.security.lenses[0] must be an object", error)

    def test_an_entry_needs_its_pass_started_on_the_current_consultation(self):
        """Issue 166: an entry was accepted for a board whose pass was never started."""
        write_json(self.root / "qa.json", example_entries()["qa"])
        _, error = self.run_cli("task", "submit", TASK, "--file", self.root / "qa.json", code=1)
        self.assertIn(f"The qa pass was not started on the current consultation. Run openguildkit task pass {TASK} qa",
                      error)
        self.run_cli("task", "pass", TASK, "qa")
        broken = {**example_entries()["qa"], "recommendation": ""}
        write_json(self.root / "qa.json", broken)
        _, error = self.run_cli("task", "submit", TASK, "--file", self.root / "qa.json", code=1)
        self.assertIn("qa.recommendation must contain text", error)
        self.assertIn(f"send it again: openguildkit task submit {TASK} --file", error)
        write_json(self.root / "qa.json", example_entries()["qa"])
        self.assertEqual(self.run_cli("task", "submit", TASK, "--file", self.root / "qa.json")[0].strip(), "done")
        self.assertEqual(self.progress("qa")["attempts"], 1)

    def test_the_consultation_of_a_bug_says_in_one_line_which_named_code_is_missing(self):
        self.run_cli("task", "new", "Fix the export bug: exportCsv() in src/export.js lets a cell start with =.",
                     "--id", "csv")
        write_json(self.root / "bug.json", {"kind": "bug", "surface": ["service"], "data": "none", "research": "local", "concerns": ["none"],
                                            "outcome": "A cell that starts with = is escaped."})
        consultation, _ = self.run_cli("task", "consult", "csv", "--answers", self.root / "bug.json")
        lines = [line for line in consultation.splitlines() if "code not found" in line]
        self.assertEqual(lines, ["- The brief names code not found in the project: src/export.js, exportCsv(). Check "
                                 "the brief with the requester or find the code it means."])


if __name__ == "__main__":
    unittest.main()
