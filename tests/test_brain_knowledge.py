import contextlib
import json
import io
import tempfile
import unittest
from pathlib import Path

from openguildkit.brains import brain_knowledge, brief_knowledge, consultation_context, knowledge_gaps
from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import resolved_profile
from openguildkit.references import load_references, with_pattern_references
from openguildkit.consultation import board_brief, consult


def families_with(*references):
    return {"test": {"id": "test", "title": "Test", "references": list(references)}}


def reference(ref_id, brains, **fields):
    return {"id": ref_id, "title": ref_id.upper(), "kind": "norme", "brains": brains,
            "sources": [{"title": ref_id, "url": f"https://example.org/{ref_id}"}]} | fields


AUDIT_PROFILE = {
    "name": "Portal", "sector": "general", "boards": [],
    "stack": ["Python 3.12", "FastAPI", "PostgreSQL 16", "React", "TypeScript"],
    "packs": ["agent-workflow", "python", "react", "secure-sdlc", "typescript"],
    "patterns": ["postgresql-database", "python-development", "python-fastapi-postgresql", "react-web",
                 "typescript-development"],
}
SSO_TASK = {"id": "b13", "brief": "Add SSO with Okta for enterprise customers"}
SSO_ANSWERS = {"kind": "feature", "surface": ["service"], "data": "personal", "research": "local",
               "context": "Okta SAML SSO for enterprise tenants, FastAPI backend with PostgreSQL"}


class BrainKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_knowledge_joins_methods_packs_and_tagged_references(self):
        families = families_with(reference("ifrs-15", ["finance"]), reference("iso-30414", ["hr", "leadership"]))
        knowledge = brain_knowledge("finance", self.catalog, families, {"financial-planning"})
        self.assertIn("financial-scenario-planning", [item["id"] for item in knowledge["methods"]])
        planning = next(item for item in knowledge["packs"] if item["id"] == "financial-planning")
        self.assertTrue(planning["active"])
        self.assertEqual([item["id"] for item in knowledge["references"]], ["ifrs-15"])
        self.assertEqual(knowledge["references"][0]["url"], "https://example.org/ifrs-15")

    def test_gaps_name_brains_without_method_or_reference(self):
        gaps = knowledge_gaps(self.catalog, families_with(reference("ifrs-15", ["finance"])))
        self.assertTrue(any(gap.startswith("hr has no reference") for gap in gaps))
        self.assertFalse(any(gap.startswith("finance has no reference") for gap in gaps))

    def test_the_consultation_carries_each_selected_brains_knowledge(self):
        families = families_with(*[reference(f"r{index}", ["security"]) for index in range(20)])
        knowledge = {"security": brief_knowledge("security", self.catalog, families, set())}
        profile = {"name": "Portal", "sector": "general", "packs": [], "boards": ["security"]}
        task = {"id": "t", "brief": "Protect personal data in exports.",
                "answers": {"kind": "feature", "surface": ["service"], "data": "personal", "research": "local"}}
        consultation = consult(profile, self.catalog, task, knowledge=knowledge)
        self.assertEqual(len(knowledge["security"]["references"]), 12)
        brief = board_brief(consultation, "security")
        self.assertIn("## Reading list", brief)
        self.assertIn("more references and the board's methods: openguildkit brains --id security", brief)
        self.assertNotIn("## Reading list", consultation["markdown"])

    def reading_list(self, board_id, task, answers, profile=AUDIT_PROFILE):
        families = with_pattern_references(load_references(), self.catalog["patterns"])
        active = set(resolved_profile(profile, self.catalog)["packs"])
        context = consultation_context(task, answers, profile, self.catalog)
        knowledge = brief_knowledge(board_id, self.catalog, families, active, context)
        return [item["id"] for item in knowledge["references"]]

    def test_the_security_brain_reads_identity_standards_for_single_sign_on(self):
        reading = self.reading_list("security", SSO_TASK, SSO_ANSWERS)
        self.assertLessEqual({"saml-2", "openid-connect", "oauth-2", "owasp-asvs"}, set(reading))
        for unrelated in ("nist-ai-rmf", "owasp-llm-top-10", "mitre-atlas"):
            self.assertNotIn(unrelated, reading)
        self.assertEqual(len(reading), 12)

    def test_the_legal_brain_reads_pci_dss_for_a_card_export_in_financial_services(self):
        profile = {**AUDIT_PROFILE, "sector": "financial-services"}
        task = {"id": "c1", "brief": "Export card transactions to the customer's accounting tool"}
        answers = {"kind": "feature", "surface": ["service"], "data": "regulated", "research": "local"}
        self.assertIn("pci-dss", self.reading_list("legal", task, answers, profile))

    def test_the_sector_brings_its_references_without_a_matching_word_in_the_brief(self):
        task = {"id": "c2", "brief": "Export transactions to the accounting tool"}
        answers = {"kind": "feature", "surface": ["service"], "data": "internal", "research": "local"}
        self.assertIn("pci-dss", self.reading_list("legal", task, answers, {**AUDIT_PROFILE, "sector": "financial-services"}))
        self.assertNotIn("pci-dss", self.reading_list("legal", task, answers))

    def test_unrelated_tasks_get_different_reading_lists_and_the_same_task_the_same_one(self):
        hiring = {"id": "h1", "brief": "Use AI to screen and rank job applicants"}
        answers = {"kind": "feature", "surface": ["business"], "data": "personal", "research": "local"}
        sso = self.reading_list("legal", SSO_TASK, SSO_ANSWERS)
        self.assertNotEqual(sso, self.reading_list("legal", hiring, answers))
        self.assertIn("eu-ai-act", self.reading_list("legal", hiring, answers))
        self.assertEqual(sso, self.reading_list("legal", SSO_TASK, SSO_ANSWERS))

    def test_references_of_active_packs_come_first_then_task_words_then_applied_ones(self):
        families = families_with(
            reference("aaa", ["security"]),
            reference("bbb", ["security"], packs=["other-pack"], status="applied"),
            reference("saml", ["security"], summary="Federated sign-on with SAML assertions."),
            reference("zzz", ["security"], packs=["secure-sdlc"], status="applied"),
        )
        knowledge = brief_knowledge("security", self.catalog, families, {"secure-sdlc"}, "Add SAML sign-on")
        self.assertEqual([item["id"] for item in knowledge["references"]], ["zzz", "saml", "bbb", "aaa"])

    def test_brains_id_lists_every_reference_and_says_a_consultation_filters_them(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(output):
            self.assertEqual(main(["--project", str(Path(directory)), "brains", "--id", "security"]), 0)
        families = with_pattern_references(load_references(), self.catalog["patterns"])
        count = len(brain_knowledge("security", self.catalog, families)["references"])
        self.assertGreater(count, 12)
        self.assertIn(f"All {count} references of this brain", output.getvalue())
        self.assertIn("keeps the 12 that best fit the task", output.getvalue())

    def test_every_bundled_brain_has_methods_and_references(self):
        families = with_pattern_references(load_references(), self.catalog["patterns"])
        self.assertEqual(knowledge_gaps(self.catalog, families), [])


if __name__ == "__main__":
    unittest.main()


class ConsultKnowledgeTests(unittest.TestCase):
    """task consult works out the knowledge of the boards it convenes, not of every board of the catalog."""

    EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"

    def consulted(self, root: Path, every_board: bool) -> tuple[bytes, list[str]]:
        """The task record task consult writes with a fixed consultation ID, and the boards whose knowledge it worked
        out; every_board works it out for each board of the catalog first, as task consult did before."""
        from unittest.mock import patch

        from openguildkit import brains, tasks_consult_cli
        from tests.support import run_cli

        computed = []
        original = brains.brief_knowledge

        def counted(board_id, *args, **kwargs):
            computed.append(board_id)
            return original(board_id, *args, **kwargs)

        def eager(catalog, *args):
            knowledge = brains.BriefKnowledge(catalog, *args)
            return {board_id: knowledge[board_id] for board_id in catalog["boards"]}

        run_cli(root, "init", "--answers", self.EXAMPLE / "profile.json")
        run_cli(root, "task", "new", "--file", self.EXAMPLE / "brief.md", "--id", "status")
        with patch("openguildkit.brains.brief_knowledge", counted), \
                patch("openguildkit.consultation.uuid4", return_value=type("Id", (), {"hex": "0" * 32})()), \
                patch.object(tasks_consult_cli, "BriefKnowledge", eager if every_board else brains.BriefKnowledge):
            run_cli(root, "task", "consult", "status", "--answers", self.EXAMPLE / "answers.json")
        record = json.loads((root / ".openguildkit" / "tasks" / "status.json").read_text(encoding="utf-8"))
        for moment in ("created_at", "updated_at"):
            record.pop(moment, None)
        return json.dumps(record, sort_keys=True).encode("utf-8"), computed

    def test_only_the_convened_boards_get_their_knowledge_and_the_consultation_is_the_same(self):
        """Issue #541: task consult ranked the references of all 27 boards when routing convened 7."""
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            lazy, computed = self.consulted(Path(first), every_board=False)
            eager, every = self.consulted(Path(second), every_board=True)
        record = json.loads(lazy)
        self.assertEqual(sorted(computed), sorted(record["consultation"]["boards"]))
        self.assertLess(len(computed), len(every))
        self.assertEqual(lazy, eager)
