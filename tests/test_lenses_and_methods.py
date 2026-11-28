"""Lenses that follow the task, and a method of its own for each discipline."""

import copy
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import CatalogError, load_catalog, validate_entry
from openguildkit.consultation import _board_template
from openguildkit.patterns import is_stack_pattern
from openguildkit.references import find_references, load_references
from openguildkit.rule_checks import evaluate_check
from openguildkit.storage import write_json
from tests.support import CapturedCli

SURFACES = (["customer"], ["service"], ["infrastructure"], ["business"])
CONCERNS = (["none"], ["money"], ["ai"], ["people-decisions"], ["credentials"])
# Boards whose every lens concerns any task they review, with the reason.
ALL_LENSES = {
    "project-management": "planning, capacity, decisions and risks concern every task the board reviews",
}
# Roles without a core method, with the reason: the methods depend on the matter at hand.
NO_CORE_METHOD = {"legal": "contracts, notices, licences and regulations each have their own method; none fits every matter"}


def lenses(board, surfaces, concerns):
    return [item["id"] for item in _board_template(board, surfaces=surfaces, concerns=concerns)["challenge"]["specialists"]]


class LensScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()

    def test_a_business_task_without_money_is_not_asked_the_pay_lens(self):
        hr = self.catalog["boards"]["hr"]
        self.assertNotIn("compensation-and-pay-equity", lenses(hr, ["business"], ["none"]))
        self.assertIn("compensation-and-pay-equity", lenses(hr, ["business"], ["money"]))
        # An open or missing answer keeps the lens.
        for concerns in (["unsure"], [], None):
            self.assertIn("compensation-and-pay-equity", lenses(hr, ["business"], concerns))

    def test_a_billing_service_task_is_asked_the_revenue_lens_and_not_the_cloud_cost_one(self):
        finance = self.catalog["boards"]["finance"]
        asked = lenses(finance, ["service"], ["money"])
        self.assertIn("revenue-accountant", asked)
        self.assertNotIn("finops-lead", asked)
        self.assertIn("finops-lead", lenses(finance, ["infrastructure"], ["money"]))

    def test_each_board_asks_fewer_lenses_for_some_task(self):
        for board_id, board in self.catalog["boards"].items():
            every = len(board["review"]["specialists"])
            fewer = [(surfaces, concerns) for surfaces in SURFACES for concerns in CONCERNS
                     if len(lenses(board, surfaces, concerns)) < every]
            with self.subTest(board=board_id):
                if board_id in ALL_LENSES:
                    self.assertEqual(fewer, [], "remove the exception: a lens of the board has a scope now")
                else:
                    self.assertTrue(fewer)

    def test_the_catalog_validates_the_concerns_of_a_lens(self):
        # OGK-CATALOG-048, OGK-CATALOG-049
        board = copy.deepcopy(self.catalog["boards"]["hr"])
        lens = board["review"]["specialists"][0]
        for value in (["payroll"], ["money", "money"], ["none"], []):
            lens["applies_to_concerns"] = value
            with self.subTest(value=value), self.assertRaisesRegex(CatalogError, "applies_to_concerns"):
                validate_entry("boards", board)
        lens["applies_to_concerns"] = ["money", "people-decisions"]
        validate_entry("boards", board)


class BriefTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_task_brief_of_a_billing_service_change_lists_the_revenue_accountant(self):
        write_json(self.root / "profile.json", {"personal_data": "no", "name": "Billing", "stack": ["Python"], "packs": [], "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        (self.root / "brief.md").write_text(
            "Change how the billing service prorates annual subscriptions and the invoice lines it emits.\n",
            encoding="utf-8")
        self.run_cli("task", "new", "--file", self.root / "brief.md", "--id", "proration")
        write_json(self.root / "answers.json", {
            "kind": "feature", "surface": ["service"], "data": "internal", "research": "local", "concerns": ["money"],
            "outcome": "An annual plan changed mid-year is invoiced pro rata.",
        })
        self.run_cli("task", "consult", "proration", "--answers", self.root / "answers.json")
        brief = self.run_cli("task", "brief", "proration", "--board", "finance")
        lenses_part = brief.split("Lenses to fill:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("revenue-accountant", lenses_part)
        self.assertNotIn("- finops-lead", lenses_part)
        self.assertIn("Not concerned: finops-lead", brief)


class MethodTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.references = load_references()

    def test_each_role_has_a_method_beyond_its_stacks_and_a_core_one_or_a_reason(self):
        for role in self.catalog["boards"]:
            methods = [pattern for pattern in self.catalog["patterns"].values()
                       if role in pattern["roles"] and not is_stack_pattern(pattern)
                       and pattern.get("kind", "method") == "method"]
            with self.subTest(role=role):
                self.assertTrue(methods)
                core = [pattern["id"] for pattern in methods if role in pattern.get("core_for", [])]
                self.assertEqual(not core, role in NO_CORE_METHOD, core)

    def test_qa_and_data_have_a_core_method_with_dated_sources(self):
        for role, pattern_id, pack_id in (("qa", "risk-based-testing", "test-strategy"),
                                          ("data", "data-definitions-and-quality", "data-definitions")):
            with self.subTest(role=role):
                pattern = self.catalog["patterns"][pattern_id]
                self.assertEqual(pattern["core_for"], [role])
                self.assertEqual(pattern["packs"], [pack_id])
                pack = self.catalog["packs"][pack_id]
                self.assertGreaterEqual(len(pack["rules"]), 3)
                self.assertTrue(pack["sources"])
                self.assertTrue(all(source["checked"] == "2026-11-22" for source in pack["sources"]))
        text = " ".join(rule["instruction"] for rule in self.catalog["packs"]["test-strategy"]["rules"])
        for fact in ("likelihood and impact", "regression", "5.2.3", "2.2.3"):
            self.assertIn(fact, text)

    def test_a_licence_policy_pack_checks_a_dependency_file(self):
        pack = self.catalog["packs"]["licence-policy"]
        self.assertIn("SPDX", pack["description"])
        checks = [rule["check"] for rule in pack["rules"] if "check" in rule]
        self.assertTrue(checks)
        self.assertTrue({"package.json", "pyproject.toml"} <= set(checks[0]["paths"]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text('[tool.licenses]\ncommand = "pip-licenses --allow-only=MIT"\n',
                                                 encoding="utf-8")
            self.assertEqual(evaluate_check(root, checks[0])["status"], "passed")
            (root / "pyproject.toml").write_text('[project]\nname = "app"\n', encoding="utf-8")
            self.assertEqual(evaluate_check(root, checks[0])["status"], "failed")
        reference = find_references(self.references, record_id="spdx-license-list")[0]
        self.assertEqual(reference["pattern"], "licence-policy")


if __name__ == "__main__":
    unittest.main()
