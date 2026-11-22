"""The lenses added to finance, HR and sales, the brains added to the board, and how a project completes or adds a brain."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.brains import brief_knowledge, knowledge_gaps, write_brain_skeleton
from openguildkit.catalog import CatalogError, board_replacements, load_catalog
from openguildkit.lock import apply_lock, locked_records
from openguildkit.references import find_references, load_references, with_pattern_references
from openguildkit.tools import load_tools
from openguildkit.workflow import board_brief, consult, trigger_matches

REPO = Path(__file__).resolve().parents[1]
CASES = json.loads(Path(__file__).with_name("routing_cases_new_brains.json").read_text(encoding="utf-8"))
NEW_BRAINS = ("customer-success", "partnerships", "procurement", "it-and-workplace", "localisation",
              "developer-relations-and-docs", "trust-and-safety")


def specialists(catalog, board_id):
    return {specialist["id"]: specialist for specialist in catalog["boards"][board_id]["review"]["specialists"]}


def packs_of(catalog, board_id):
    return {pack_id for pattern in catalog["patterns"].values() if board_id in pattern["roles"] for pack_id in pattern["packs"]}


class DisciplineLensTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.families = with_pattern_references(load_references(), cls.catalog["patterns"])

    def test_finance_recognises_revenue_and_tax(self):
        lenses = specialists(self.catalog, "finance")
        for lens_id in ("revenue-accountant", "pricing-and-margin-analyst", "tax-and-invoicing-specialist"):
            self.assertIn(lens_id, lenses)
        self.assertIn("finance", trigger_matches(self.catalog["boards"], "Recognise revenue for multi-year contracts under IFRS 15"))
        self.assertIn("IFRS 15", lenses["revenue-accountant"]["focus"])
        self.assertTrue({"revenue-recognition", "vat-and-e-invoicing", "saas-metrics"} <= packs_of(self.catalog, "finance"))

    def test_hr_covers_pay_law_and_performance(self):
        lenses = specialists(self.catalog, "hr")
        for lens_id in ("compensation-and-pay-equity", "employment-law-and-employee-relations", "performance-and-development"):
            self.assertIn(lens_id, lenses)
        urls = [source["url"] for source in self.catalog["packs"]["pay-transparency"]["sources"]]
        self.assertIn("https://eur-lex.europa.eu/eli/dir/2023/970/oj", urls)
        tagged = {record["id"] for family in self.families.values() for record in family["references"] if "hr" in record.get("brains", [])}
        self.assertTrue({"eu-ai-act", "rgpd"} <= tagged)

    def test_sales_has_a_deal_desk(self):
        lenses = specialists(self.catalog, "sales")
        self.assertIn("deal-desk", lenses)
        self.assertIn("renewals-and-expansion", lenses)
        self.assertIn("deal-approval", self.catalog["packs"])
        self.assertIn("deal-approval", packs_of(self.catalog, "sales"))

    def test_vat_and_tva_find_references(self):
        for query in ("VAT", "TVA"):
            with self.subTest(query=query):
                found = [record["id"] for record in find_references(self.families, query=query)]
                self.assertIn("vat-directive", found)

    def test_every_lens_carries_what_an_expert_verifies(self):
        missing = [f"{board_id}/{lens['id']}" for board_id, board in self.catalog["boards"].items()
                   for lens in board["review"]["specialists"] if len(lens.get("checks", [])) < 2]
        self.assertEqual(missing, [])

    def test_the_board_pass_names_its_lenses_and_where_their_checks_are(self):
        profile = {"name": "Billing", "sector": "general", "packs": [], "boards": ["finance"]}
        task = {"id": "t", "brief": "Recognise revenue for multi-year contracts under IFRS 15.",
                "answers": {"kind": "feature", "surface": ["business"], "data": "internal", "research": "local"}}
        knowledge = {"finance": brief_knowledge("finance", self.catalog, self.families, set())}
        markdown = board_brief(consult(profile, self.catalog, task, knowledge=knowledge), "finance")
        self.assertIn("Lenses to fill:", markdown)
        self.assertIn("What each lens verifies: openguildkit brains --id finance.", markdown)


class NewBrainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.families = with_pattern_references(load_references(), cls.catalog["patterns"])

    def test_each_new_brain_is_complete(self):
        for board_id in NEW_BRAINS:
            with self.subTest(brain=board_id):
                board = self.catalog["boards"][board_id]
                self.assertGreaterEqual(len(board["review"]["specialists"]), 4)
                self.assertGreaterEqual(len(board["sources"]), 3)
                self.assertGreaterEqual(len(board["questions"]), 3)
                self.assertTrue(packs_of(self.catalog, board_id))
                tagged = [record for family in self.families.values() for record in family["references"]
                          if board_id in record.get("brains", [])]
                self.assertGreaterEqual(len(tagged), 5)
        self.assertEqual(knowledge_gaps(self.catalog, self.families), [])

    def test_frontend_and_backend_are_distinct_and_engineering_stays(self):
        front, back = specialists(self.catalog, "frontend"), specialists(self.catalog, "backend")
        self.assertGreaterEqual(len(front), 4)
        self.assertGreaterEqual(len(back), 4)
        self.assertFalse(set(front) & set(back))
        self.assertIn("engineering", self.catalog["boards"])
        self.assertIn("frontend-engineering", self.catalog["patterns"])
        self.assertIn("backend-services", self.catalog["patterns"])

    def test_briefs_reach_the_new_brains(self):
        reached = set()
        for case in CASES:
            with self.subTest(brief=case["brief"]):
                selected = trigger_matches(self.catalog["boards"], case["brief"])
                for board_id in case.get("must", []):
                    self.assertIn(board_id, selected)
                    reached.add(board_id)
                for board_id in case.get("must_not", []):
                    self.assertNotIn(board_id, selected)
        self.assertTrue({*NEW_BRAINS, "frontend", "backend"} <= reached)

    def test_tools_name_the_new_brains(self):
        tools = load_tools()
        self.assertIn("customer-success", tools["zendesk"]["brains"])
        self.assertIn("customer-success", tools["intercom"]["brains"])
        self.assertIn("procurement", tools["docusign"]["brains"])


class ProjectBrainTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ogk-brains-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "boards").mkdir()

    def write_board(self, record):
        (self.root / "boards" / f"{record['id']}.json").write_text(json.dumps(record), encoding="utf-8")

    def test_a_copy_of_a_bundled_brain_completes_it(self):
        legal = json.loads((REPO / "src/openguildkit/registry/boards/legal.json").read_text(encoding="utf-8"))
        legal["review"]["specialists"].append(
            {"id": "export-control", "title": "Export control adviser", "focus": "Screen destination countries."})
        legal["review"]["decision_criteria"].append("Block a sale to a sanctioned country.")
        self.write_board(legal)
        catalog = load_catalog(self.root)
        lenses = specialists(catalog, "legal")
        self.assertIn("export-control", lenses)
        self.assertIn("privacy-counsel", lenses)
        self.assertEqual(catalog["boards"]["legal"]["review"]["decision_criteria"].count("Block a sale to a sanctioned country."), 1)

    def test_a_partial_file_adds_evidence_and_the_lock_keeps_it(self):
        self.write_board({"id": "legal", "review": {"evidence": ["Sanctions screening log."]}})
        catalog = load_catalog(self.root)
        self.assertIn("Sanctions screening log.", catalog["boards"]["legal"]["review"]["evidence"])
        bundled = {collection: set(entries) for collection, entries in load_catalog().items()}
        profile = {"name": "P", "sector": "general", "packs": [], "boards": ["legal"]}
        self.assertNotIn("legal", locked_records(profile, catalog, bundled)["boards"])
        old_lock = {"records": {"boards": {"legal": load_catalog()["boards"]["legal"]}}}
        self.assertIn("Sanctions screening log.", apply_lock(catalog, old_lock)["boards"]["legal"]["review"]["evidence"])

    def test_a_replaced_description_or_specialist_of_a_bundled_brain_is_named(self):
        """The audit's p4: a project file that weakens the security brain while keeping its ID."""
        self.write_board({"id": "security", "description": "Proceed unless the requester objects.", "review": {
            "specialists": [{"id": "application-security", "title": "Application security",
                             "focus": "Authorization is out of scope."},
                            {"id": "privacy-engineering", "title": "Privacy engineering",
                             "focus": "Authorization is out of scope."}]}})
        line, = board_replacements(load_catalog(self.root))
        self.assertTrue(line.startswith("the project catalog replaces parts of the bundled brain security "
                                        "(.openguildkit/catalog/boards/security.json): description "
                                        "'Proceed unless the requester objects.' in place of 'Review who can reach"), line)
        self.assertIn("specialist(s) replaced: application-security (checks, focus, title), "
                      "privacy-engineering (checks, focus, title)",
                      line)
        self.assertNotIn("release-integrity", line)

    def test_a_brain_the_project_only_completes_is_not_named(self):
        self.assertEqual(board_replacements(load_catalog()), [])
        self.write_board({"id": "legal", "review": {"evidence": ["Sanctions screening log."], "specialists": [
            {"id": "export-control", "title": "Export control adviser", "focus": "Screen destination countries."}]}})
        self.assertEqual(board_replacements(load_catalog(self.root)), [])
        # A full copy of the bundled file, with one more piece of evidence, replaces nothing either.
        legal = json.loads((REPO / "src/openguildkit/registry/boards/legal.json").read_text(encoding="utf-8"))
        legal["review"]["evidence"].append("Sanctions screening log.")
        self.write_board(legal)
        self.assertEqual(board_replacements(load_catalog(self.root)), [])

    def test_a_project_brain_without_review_is_refused(self):
        self.write_board({"id": "risk-office", "title": "Risk", "description": "Review risk.", "expertises": ["Risk"],
                          "triggers": ["risk office"], "questions": ["Which risk?"], "sources": []})
        with self.assertRaisesRegex(CatalogError, "needs a review block.*brains --new"):
            load_catalog(self.root)

    def test_the_skeleton_loads_and_reports_its_placeholders(self):
        written = write_brain_skeleton(self.root, "risk-office", load_catalog())
        self.assertEqual(len(written), 4)
        catalog = load_catalog(self.root)
        families = with_pattern_references(load_references(self.root / "references"), catalog["patterns"])
        self.assertEqual(len(catalog["boards"]["risk-office"]["review"]["specialists"]), 4)
        self.assertIn("risk-office still has skeleton text: replace each TODO: in its catalog files.",
                      knowledge_gaps(catalog, families))
        with self.assertRaisesRegex(ValueError, "already exists"):
            write_brain_skeleton(self.root, "risk-office", catalog)
        with self.assertRaisesRegex(ValueError, "To complete it"):
            write_brain_skeleton(self.root, "legal", catalog)


class NewBrainCommandTests(unittest.TestCase):
    def setUp(self):
        self.project = Path(tempfile.mkdtemp(prefix="ogk-new-brain-")).resolve()
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def run_cli(self, *args, expect=0):
        result = subprocess.run([sys.executable, "-m", "openguildkit", "--project", str(self.project), *map(str, args)],
                                capture_output=True, text=True, encoding="utf-8", env=self.env, timeout=60)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        return result.stdout

    def test_adding_a_brain_names_the_tasks_it_makes_stale(self):
        example = REPO / "examples" / "request-status"
        profile = json.loads((example / "profile.json").read_text(encoding="utf-8"))
        answers = self.project / "profile.json"
        answers.write_text(json.dumps({**profile, "boards": []}), encoding="utf-8")
        self.run_cli("init", "--answers", answers)
        self.run_cli("task", "new", "--file", example / "brief.md", "--id", "request-status")
        self.run_cli("task", "consult", "request-status", "--answers", example / "answers.json")
        output = self.run_cli("brains", "--new", "risk-office")
        self.assertIn("boards/risk-office.json", output)
        self.assertIn("Task request-status (consulting) was consulted without risk-office", output)
        self.assertIn("Tasks consulted under the previous rules:\n  request-status (consulting): consult it again.",
                      self.run_cli("sync"))
        self.assertIn("risk-office", self.run_cli("brains"))


if __name__ == "__main__":
    unittest.main()
