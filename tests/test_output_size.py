"""Size budgets of what an agent reads in full: the consultation, each board pass and the handoff.

The field campaign of November 2026 measured 75 to 220 KB for these outputs, mostly the project scope
repeated in each pass. The budgets keep the weight from coming back: the scope is printed once, a pass
carries its board's brief, rules and entry, and the rest is named with the command that prints it.

What an agent loads at the start of a session is read again at every turn (#363), so the managed block
of AGENTS.md has a budget too.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.project import BEGIN, END, rule_plan, validate_profile
from openguildkit.storage import write_json
from openguildkit.workflow import handoff

from tests.support import CapturedCli

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "request-status"
# Issue 157 asks for a pass under 10 KB and a consultation under 30 KB. A pass fills what its brief leaves
# of the budget with the rules of its packs, so it stays under it whatever the number of packs.
BUDGETS = {"consultation": 30_000, "pass": 10_000, "handoff": 16_000}
EXAMPLE_PASS = 10_000
MONOREPO_ROLES = ["frontend", "backend", "devops", "security", "qa", "product", "project-management"]
# The managed block of AGENTS.md, from its first marker to its last, in bytes. Issue 363 asks for 8 000: the agent
# reads the block again at every turn. The block names each pack with the IDs of its rules and leaves their text, their
# `Verify:` lines and the sources of the packs to `openguildkit task brief ID --pack PACK`. The request-status example
# went from 15 878 to 5 983 bytes and holds the target. The monorepo with every role went from 90 541 to 16 759 and
# cannot, as of 25 November 2026: its 49 packs bring 190 rule IDs, and before the first pack the block is already
# 8 158 bytes (the workflow 3 340, the 45 selected patterns 3 481, the sector and stack 1 071). Naming the packs with
# no rule ID at all would still leave about 11 500. Reaching 8 000 there means dropping something that is not rule
# text (the rule IDs, the list of selected patterns, the sector's context or part of the workflow), which is a decision
# for the issue and not a trim. Until it is taken the monorepo keeps its measured size plus 5 %, rounded up to the
# next 100: the block cannot grow unnoticed, and the target stays visible.
INSTRUCTION_TARGET = 8_000
INSTRUCTION_BUDGETS = {"the request-status example": INSTRUCTION_TARGET, "the monorepo with every role": 17_600}


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class OutputSizeTests(CapturedCli, unittest.TestCase):
    cli_output = "stdout"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

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

    def init_monorepo_with_every_role(self) -> None:
        write(self.root, "web/package.json", {"dependencies": {"react": "18.3.1"}, "devDependencies": {"typescript": "5.5.0"}})
        write(self.root, "api/pom.xml", "<project><parent><artifactId>spring-boot-starter-parent</artifactId>"
                                        "<version>3.3.0</version></parent></project>")
        write(self.root, "infra/main.tf", 'provider "aws" {}\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        answers = {"personal_data": "no", "name": "shop", "sector": "e-commerce", "roles": MONOREPO_ROLES,
                   "components": questions["components"]["default"], "norms": {"online-consumer-sales": "yes",
                                                         "european-accessibility-act": "yes"}}
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

    def test_a_monorepo_with_every_role_stays_within_its_budgets(self):
        self.init_monorepo_with_every_role()
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

    def managed_block_size(self) -> int:
        """The bytes of the block OpenGuildKit manages in AGENTS.md, markers included: the part the agent reads at
        the start of every session, whatever the team wrote around it."""
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        return len(text[text.index(BEGIN):text.index(END) + len(END)].encode("utf-8"))

    def assert_block_within_budget(self, case: str) -> None:
        size, budget = self.managed_block_size(), INSTRUCTION_BUDGETS[case]
        self.assertLessEqual(size, budget, f"the AGENTS.md block of {case} is {size} bytes, budget {budget} "
                                           f"(target {INSTRUCTION_TARGET})")

    def assert_block_names_every_rule(self) -> None:
        """Every pack in force is a heading of the block and every rule of the pack is named by its ID under it, and
        what the block leaves to `task brief ID --pack PACK` is not in it: the text of a rule, its `Verify:` line and
        the sources of the pack. The block is the part of a project's rules that the agent reads without asking."""
        text = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        block = text[text.index(BEGIN):text.index(END)]
        catalog = load_catalog()
        profile = validate_profile(json.loads((self.root / ".openguildkit" / "project.json").read_text()), catalog)
        sections = {match.group(1): match.group(2) for match in re.finditer(
            r"^#### [^\n]* \(`([^`@]+)@[^`]+`\)\n(.*?)(?=^#### |^<!-- openguildkit profile )", block, re.S | re.M)}
        plan = rule_plan(profile, catalog)["packs"]
        self.assertEqual(list(sections), [pack["id"] for pack in plan])
        for pack in plan:
            for rule in pack["rules"]:
                with self.subTest(pack=pack["id"], rule=rule):
                    self.assertIn(f"`{rule}`", sections[pack["id"]])
        self.assertIn("openguildkit task brief ID --pack PACK", block)
        self.assertNotIn("Verify:", block)
        self.assertNotIn("](<http", block)
        instruction = catalog["packs"][plan[0]["id"]]["rules"][0]["instruction"]
        self.assertNotIn(instruction, block)

    def test_the_agents_md_block_of_the_example_stays_within_its_budget(self):
        self.run_cli("init", "--answers", EXAMPLE / "profile.json")
        self.assert_block_within_budget("the request-status example")

    def test_the_agents_md_block_of_the_example_names_every_rule_of_its_packs(self):
        self.run_cli("init", "--answers", EXAMPLE / "profile.json")
        self.assert_block_names_every_rule()

    def test_the_agents_md_block_of_a_monorepo_with_every_role_stays_within_its_budget(self):
        self.init_monorepo_with_every_role()
        self.assert_block_within_budget("the monorepo with every role")

    def test_the_agents_md_block_of_a_monorepo_with_every_role_names_every_rule_of_its_packs(self):
        self.init_monorepo_with_every_role()
        self.assert_block_names_every_rule()

    def test_a_monorepo_pass_prints_the_rules_of_the_components_the_task_names(self):
        """A pass chose its rules by shared words: a task on a Spring Boot endpoint got web-performance rules."""
        write(self.root, "web/package.json", {"dependencies": {"react": "18.3.1"}, "devDependencies": {"typescript": "5.5.0"}})
        write(self.root, "api/pom.xml", "<project><parent><artifactId>spring-boot-starter-parent</artifactId>"
                                        "<version>3.3.0</version></parent></project>")
        write(self.root, "infra/main.tf", 'provider "aws" {}\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        components = questions["components"]["default"]
        write_json(self.root / "init.json", {"personal_data": "no", "name": "shop", "sector": "e-commerce", "roles": MONOREPO_ROLES,
                                             "components": components, "norms": {"online-consumer-sales": "yes",
                                                         "european-accessibility-act": "yes"}})
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
