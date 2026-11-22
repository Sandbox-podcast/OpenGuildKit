"""Size budgets of what an agent reads in full: the consultation, each board pass and the handoff.

The field campaign of November 2026 measured 75 to 220 KB for these outputs, mostly the project scope
repeated in each pass. The budgets keep the weight from coming back: the scope is printed once, a pass
carries its board's brief, rules and entry, and the rest is named with the command that prints it.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from openguildkit.cli import main
from openguildkit.storage import write_json
from openguildkit.workflow import handoff

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
# Issue 157 asks for a pass under 10 KB and a consultation under 30 KB. A pass fills what its brief leaves
# of the budget with the rules of its packs, so it stays under it whatever the number of packs.
BUDGETS = {"consultation": 30_000, "pass": 10_000, "handoff": 16_000}
EXAMPLE_PASS = 10_000
MONOREPO_ROLES = ["frontend", "backend", "devops", "security", "qa", "product", "project-management"]


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class OutputSizeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, 0, stderr.getvalue())
        return stdout.getvalue()

    def sizes(self, task_id: str, answers: dict) -> dict:
        """The size in bytes of the consultation, of each board pass and of the handoff of the approved task."""
        write_json(self.root / "answers.json", answers)
        sizes = {"consultation": len(self.run_cli("task", "consult", task_id, "--answers", self.root / "answers.json")
                                     .encode("utf-8"))}
        record = json.loads(self.run_cli("task", "show", task_id))
        for board in record["consultation"]["boards"]:
            sizes[f"pass {board}"] = len(self.run_cli("task", "pass", task_id, board).encode("utf-8"))
        review = {"consultation_id": record["consultation"]["id"], **json.loads((EXAMPLE / "review.json").read_text())}
        known = {entry["id"]: entry for entry in review["boards"]}
        review["boards"] = [known.get(board, {**known["engineering"], "id": board})
                            for board in record["consultation"]["boards"]]
        for entry in review["boards"]:
            specialists = {lens["id"] for lens in next(
                item for item in record["consultation"]["review_template"]["boards"] if item["id"] == entry["id"]
            )["challenge"]["specialists"]}
            lenses = entry["challenge"]["specialists"]
            entry["challenge"] = {**entry["challenge"], "specialists": [
                {**lenses[index % len(lenses)], "id": lens_id} for index, lens_id in enumerate(sorted(specialists))]}
        approved = {**record, "status": "approved", "review": review,
                    "decision": {"outcome": "approved", "by": "Camille Martin", "reason": "Agreed", "at": "2026-11-21"}}
        sizes["handoff"] = len(handoff(approved).encode("utf-8"))
        return sizes

    def assert_budgets(self, sizes: dict, pass_budget: int) -> None:
        for name, size in sizes.items():
            budget = pass_budget if name.startswith("pass ") else BUDGETS[name]
            with self.subTest(output=name):
                self.assertLess(size, budget, f"{name} is {size} bytes")

    def test_the_bundled_example_stays_within_its_budgets(self):
        write_json(self.root / "profile.json", {**json.loads((EXAMPLE / "profile.json").read_text()), "checks": []})
        self.run_cli("init", "--answers", self.root / "profile.json")
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "request-status")
        self.assert_budgets(self.sizes("request-status", json.loads((EXAMPLE / "answers.json").read_text())),
                            EXAMPLE_PASS)

    def test_a_monorepo_with_every_role_stays_within_its_budgets(self):
        write(self.root, "web/package.json", {"dependencies": {"react": "18.3.1"}, "devDependencies": {"typescript": "5.5.0"}})
        write(self.root, "api/pom.xml", "<project><parent><artifactId>spring-boot-starter-parent</artifactId>"
                                        "<version>3.3.0</version></parent></project>")
        write(self.root, "infra/main.tf", 'provider "aws" {}\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        answers = {"name": "shop", "sector": "e-commerce", "roles": MONOREPO_ROLES,
                   "components": questions["components"]["default"], "norms": {"online-consumer-sales": "yes"}}
        write_json(self.root / "init.json", answers)
        # As heavy as the field projects: every method of the roles, as setup preselected them before #152.
        plan = json.loads(self.run_cli("recommend", "--answers", self.root / "init.json", "--json"))
        answers["patterns"] = [
            {"id": entry["id"], "components": entry["components"]} if entry.get("components") else entry["id"]
            for entry in plan["matched"] + plan["suggested"]
            if entry.get("kind") != "regulation" and not entry.get("choice_required")
        ]
        write_json(self.root / "init.json", answers)
        self.run_cli("init", "--answers", self.root / "init.json")
        self.run_cli("task", "new", "Show signed-in customers their past orders, newest first, from the orders API.",
                     "--id", "order-history")
        sizes = self.sizes("order-history", {
            "kind": "feature", "surface": ["customer", "service"], "data": "personal", "research": "local",
            "concerns": ["none"],
            "outcome": "A customer sees their own past orders.", "affected": "Signed-in customers.",
        })
        packs = len(json.loads(self.run_cli("task", "show", "order-history"))["consultation"]["scope"]["packs"])
        self.assertGreater(packs, 25, "the fixture must carry as many packs as the field projects")
        self.assertGreater(len([name for name in sizes if name.startswith("pass ")]), 6)
        self.assert_budgets(sizes, BUDGETS["pass"])

    def test_a_monorepo_pass_prints_the_rules_of_the_components_the_task_names(self):
        """A pass chose its rules by shared words: a task on a Spring Boot endpoint got web-performance rules."""
        write(self.root, "web/package.json", {"dependencies": {"react": "18.3.1"}, "devDependencies": {"typescript": "5.5.0"}})
        write(self.root, "api/pom.xml", "<project><parent><artifactId>spring-boot-starter-parent</artifactId>"
                                        "<version>3.3.0</version></parent></project>")
        write(self.root, "infra/main.tf", 'provider "aws" {}\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        components = questions["components"]["default"]
        write_json(self.root / "init.json", {"name": "shop", "sector": "e-commerce", "roles": MONOREPO_ROLES,
                                             "components": components, "norms": {"online-consumer-sales": "yes"}})
        self.run_cli("init", "--answers", self.root / "init.json")
        api = next(item for item in components if "Spring" in " ".join(item["stack"]))
        self.run_cli("task", "new", "Return the signed-in customer's orders from GET /orders.", "--id", "orders")
        write_json(self.root / "a.json", {"kind": "feature", "surface": ["service"], "data": "personal",
                                          "research": "local", "concerns": ["none"], "components": [api["id"]],
                                          "outcome": "GET /orders returns the caller's orders only."})
        self.run_cli("task", "consult", "orders", "--answers", self.root / "a.json")
        engineering = self.run_cli("task", "pass", "orders", "engineering")
        self.assertLess(len(engineering.encode("utf-8")), BUDGETS["pass"])
        rules = engineering[engineering.index("## Rules of this board's packs"):]
        self.assertIn("(spring-boot@", rules)
        self.assertNotIn("(web-performance@", rules)
        self.assertIn(f"- Components: {api['id']} ({api['path']})", engineering)
        named = rules[rules.index("openguildkit task brief orders --pack"):] if "--pack" in rules else ""
        pack = json.loads(self.run_cli("task", "show", "orders"))["consultation"]["scope"]["packs"][0]
        printed = self.run_cli("task", "brief", "orders", "--pack", pack["id"])
        self.assertIn(pack["rules"][0]["id"], printed)
        self.assertLess(len(printed.encode("utf-8")), 10_000)
        self.assertIsNotNone(named)


if __name__ == "__main__":
    unittest.main()
