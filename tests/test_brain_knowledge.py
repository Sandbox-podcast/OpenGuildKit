import unittest

from openguildkit.brains import brain_knowledge, brief_knowledge, knowledge_gaps
from openguildkit.catalog import load_catalog
from openguildkit.references import load_references, with_pattern_references
from openguildkit.workflow import consult


def families_with(*references):
    return {"test": {"id": "test", "title": "Test", "references": list(references)}}


def reference(ref_id, brains):
    return {"id": ref_id, "title": ref_id.upper(), "kind": "norme", "brains": brains,
            "sources": [{"title": ref_id, "url": f"https://example.org/{ref_id}"}]}


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
        self.assertIn('"knowledge"', consultation["markdown"])
        self.assertEqual(len(knowledge["security"]["references"]), 12)

    def test_every_bundled_brain_has_methods_and_references(self):
        families = with_pattern_references(load_references(), self.catalog["patterns"])
        self.assertEqual(knowledge_gaps(self.catalog, families), [])


if __name__ == "__main__":
    unittest.main()
