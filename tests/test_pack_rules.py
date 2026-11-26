"""Pack rules that must not weaken their source, repeat each other or stay out of reach."""

import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.brains import brain_knowledge
from openguildkit.catalog import load_catalog
from openguildkit.project import render_instructions, resolved_profile, rule_plan, validate_profile
from openguildkit.references import find_references, load_references, with_pattern_references
from openguildkit.rule_checks import evaluate_check

REGULATORY_PACKS = ("gdpr", "nis2", "dora", "cyber-resilience-act", "eu-ai-act")
# Words that only a French title would contain; an English title has none of them.
FRENCH_WORDS = {
    "de", "des", "du", "la", "le", "les", "et", "sur", "pour", "aux", "dans", "avec", "relative", "relatif",
    "concernant", "ue", "ce", "matrice", "liste", "norme", "principe", "principes", "livraison", "continue",
    "immuable", "manifeste", "normalisation", "relationnelle", "gestion", "contrats",
    "lignes", "directrices", "examen", "rapport", "entretiens", "effectifs", "uni", "immobilisations",
}
FRENCH_LETTERS = re.compile(r"[éèêàâçùûôîïœ]")


def french_marks(title: str) -> list[str]:
    words = [word for word in re.findall(r"[^\W\d_]+", title.casefold()) if word in FRENCH_WORDS]
    return words + FRENCH_LETTERS.findall(title.casefold())


class PackRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.families = with_pattern_references(load_references(), cls.catalog["patterns"])

    def rule(self, pack_id: str, rule_id: str) -> dict:
        return next(rule for rule in self.catalog["packs"][pack_id]["rules"] if rule["id"] == rule_id)

    def test_offboarding_rotates_shared_credentials_under_the_termination_control(self):
        rule = self.rule("employee-offboarding", "rotate-shared-credentials")
        self.assertIn("PS-4", rule["instruction"])
        self.assertNotIn("PS-5", rule["instruction"])
        self.assertIn("rotate", rule["instruction"])
        self.assertRegex(rule["verification"], r"last rotation .* (after|later than) the departure date")

    def test_ai_act_logs_are_kept_at_least_six_months(self):
        rule = self.rule("eu-ai-act", "keep-high-risk-logs")
        self.assertIn("at least six months", rule["instruction"])
        self.assertIn("Art. 19(1)", rule["instruction"])
        self.assertIn("Art. 26(6)", rule["instruction"])
        self.assertNotIn("the period the owner sets", rule["instruction"])

    def test_scrum_and_kanban_apply_together_without_a_resolution(self):
        profile = validate_profile({"name": "Scrumban team", "patterns": ["scrum", "kanban"]}, self.catalog)
        self.assertEqual(rule_plan(profile, self.catalog)["conflicts"], [])
        instructions = render_instructions(profile, self.catalog)
        self.assertIn("`scrum-delivery@", instructions)
        self.assertIn("`kanban-delivery@", instructions)

    def test_a_choice_recorded_under_the_former_conflict_stays_in_force(self):
        answers = {
            "name": "Support team", "patterns": ["scrum", "kanban"],
            "resolutions": [{"packs": ["kanban-delivery", "scrum-delivery"], "keep": ["kanban-delivery"],
                             "reason": "Support work arrives continuously."}],
        }
        profile = validate_profile(answers, self.catalog)
        self.assertEqual(rule_plan(profile, self.catalog)["excluded"], ["scrum-delivery"])
        instructions = render_instructions(profile, self.catalog)
        self.assertIn("- `kanban-delivery` applies instead of `scrum-delivery`.", instructions)
        self.assertNotIn("`scrum-delivery@", instructions)

    def test_a_pattern_selects_release_management_and_devops_lists_it(self):
        selecting = [pattern["id"] for pattern in self.catalog["patterns"].values() if "release-management" in pattern["packs"]]
        self.assertTrue(selecting)
        packs = [pack["id"] for pack in brain_knowledge("devops", self.catalog, self.families)["packs"]]
        self.assertIn("release-management", packs)

    def test_one_shared_matrix_lists_each_regulation_and_the_regulatory_packs_use_it(self):
        pack = self.catalog["packs"]["incident-notification"]
        rows = {
            "gdpr-personal-data-breach": ("Art. 33(1)", "supervisory authority", "72 hours"),
            "nis2-significant-incident": ("Art. 23(4)", "CSIRT", "24 hours"),
            "dora-major-ict-incident": ("Art. 19(1)", "competent authority", "four hours"),
            "cra-actively-exploited-vulnerability": ("Art. 14(2)", "ENISA", "24 hours"),
            "ai-act-serious-incident": ("Art. 73(2)", "market surveillance authorit", "15 days"),
        }
        for rule_id, expected in rows.items():
            with self.subTest(rule=rule_id):
                instruction = self.rule("incident-notification", rule_id)["instruction"]
                for text in expected:
                    self.assertIn(text, instruction)
        self.assertIn("keep-notification-matrix", [rule["id"] for rule in pack["rules"]])
        for pack_id in REGULATORY_PACKS:
            with self.subTest(pack=pack_id):
                regulation = self.catalog["packs"][pack_id]
                self.assertIn("incident-notification", regulation.get("depends_on", []))
                runbook = [rule["id"] for rule in regulation["rules"] if "incident runbook" in rule["instruction"]]
                self.assertEqual(runbook, [])

    def test_english_names_find_the_references(self):
        def found(query):
            return [record["id"] for record in find_references(self.families, query=query)]

        self.assertIn("rgpd", found("GDPR"))
        self.assertIn("wcag-22", found("accessibility"))
        self.assertIn("vat-directive", found("VAT"))
        self.assertIn("vat-directive", found("TVA"))
        self.assertIn("rgpd", found("protection des données"))
        self.assertIn("infrastructure-as-code", found("pd_iac"))

    def test_every_reference_has_an_english_title(self):
        for family in load_references().values():
            for record in family["references"]:
                title = record.get("title_en", record["title"])
                with self.subTest(reference=record["id"]):
                    self.assertEqual(french_marks(title), [], title)

    def test_the_device_lifecycle_pattern_poses_one_access_removal_rule(self):
        profile = validate_profile({"name": "Team", "patterns": ["device-and-access-lifecycle"], "packs": []},
                                   self.catalog)
        packs = resolved_profile(profile, self.catalog)["packs"]
        removal = [f"{pack_id}/{rule['id']}" for pack_id in packs for rule in self.catalog["packs"][pack_id]["rules"]
                   if "access" in rule["id"] and ("remov" in rule["id"] or "depart" in rule["id"])]
        self.assertEqual(removal, ["employee-offboarding/schedule-access-removal"])
        self.assertIn("employee-offboarding", self.catalog["packs"]["device-and-access-lifecycle"]["depends_on"])


# The ten risks of the OWASP Top 10 for Agentic Applications 2026, with the identifiers its page gives them
# (genai.owasp.org, read on 25 November 2026). Each one is answered by a rule of the agentic security pack.
OWASP_AGENTIC_RISKS = {
    "ASI01": "Agent Goal Hijack", "ASI02": "Tool Misuse and Exploitation", "ASI03": "Identity and Privilege Abuse",
    "ASI04": "Agentic Supply Chain Vulnerabilities", "ASI05": "Unexpected Code Execution (RCE)",
    "ASI06": "Memory & Context Poisoning", "ASI07": "Insecure Inter-Agent Communication",
    "ASI08": "Cascading Failures", "ASI09": "Human-Agent Trust Exploitation", "ASI10": "Rogue Agents",
}
MCP_RULES = ("pin-mcp-server-versions", "expose-minimal-mcp-tools", "keep-mcp-tokens-inside-the-server-boundary",
             "treat-mcp-metadata-and-results-as-untrusted", "bind-local-mcp-servers-to-loopback")
AGENTIC_REFERENCES = ("owasp-agentic-top-10", "model-context-protocol", "agent-tool-permissions", "human-in-the-loop",
                      "agent-execution-limits", "agent-memory", "agent2agent")


class AgenticSecurityPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.pack = cls.catalog["packs"]["agentic-application-security"]
        cls.pattern = cls.catalog["patterns"]["agentic-application-security"]

    def test_each_risk_of_the_owasp_list_is_answered_by_a_rule_that_names_it(self):
        for risk in OWASP_AGENTIC_RISKS:
            with self.subTest(risk=risk):
                rules = [rule["id"] for rule in self.pack["rules"] if risk in rule["instruction"]]
                self.assertTrue(rules, f"no rule names {risk}")
        cited = set(re.findall(r"\bASI\d{2}\b", " ".join(rule["instruction"] for rule in self.pack["rules"])))
        self.assertEqual(cited - set(OWASP_AGENTIC_RISKS), set())

    def test_the_pack_has_twelve_to_sixteen_rules_with_the_mcp_ones_among_them(self):
        ids = [rule["id"] for rule in self.pack["rules"]]
        self.assertTrue(12 <= len(ids) <= 16, ids)
        self.assertLessEqual(set(MCP_RULES), set(ids))
        for rule in self.pack["rules"]:
            with self.subTest(rule=rule["id"]):
                self.assertRegex(rule["id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertNotIn("manual", rule)

    def test_the_pack_starts_with_its_context_and_claims_no_conformity(self):
        self.assertTrue(self.pack["description"].startswith("For a project that builds"))
        text = " ".join([self.pack["description"], self.pattern["description"],
                         *(f"{rule['instruction']} {rule['verification']}" for rule in self.pack["rules"])]).casefold()
        for word in ("compliant", "compliance with", "certified", "certification of", "guarantee", "ensures conformity"):
            self.assertNotIn(word, text)
        self.assertTrue(all(source["checked"] == "2026-11-25" for source in self.pack["sources"]))
        self.assertTrue(all(source["url"].startswith("https://") for source in self.pack["sources"]))

    def test_the_pattern_reaches_the_pack_through_the_mcp_sdks_and_the_agent_frameworks(self):
        self.assertIn("agentic-application-security", self.pattern["packs"])
        group = {alias.casefold() for alias in self.pattern["match"]["stack"][0]}
        for name in ("mcp", "langgraph", "crewai", "openai agents sdk", "pydantic ai", "claude agent sdk", "autogen"):
            self.assertIn(name, group)
        self.assertEqual(len(self.pattern["match"]["stack"]), 1)

    def test_every_reference_the_pack_applies_names_it_and_is_listed_by_the_pattern(self):
        families = load_references()
        records = {record["id"]: record for family in families.values() for record in family["references"]}
        self.assertEqual(set(self.pattern["references"]), set(AGENTIC_REFERENCES))
        for reference_id in AGENTIC_REFERENCES:
            with self.subTest(reference=reference_id):
                self.assertIn("agentic-application-security", records[reference_id]["packs"])

    def test_the_mcp_pinning_check_flags_a_floating_version_and_passes_without_an_mcp_file(self):
        check = next(rule["check"] for rule in self.pack["rules"] if rule["id"] == "pin-mcp-server-versions")
        cases = (
            ({}, "passed"),
            ({".mcp.json": '{"mcpServers": {"a": {"command": "npx", "args": ["a-mcp@1.4.2"]}}}'}, "passed"),
            ({".mcp.json": '{"mcpServers": {"a": {"command": "npx", "args": ["a-mcp@latest"]}}}'}, "failed"),
            ({".mcp.json": '{"mcpServers": {"a": {"command": "docker", "args": ["run", "-i", "acme/a-mcp:latest"]}}}'},
             "failed"),
            ({".codex/config.toml": '[mcp_servers.a]\ncommand = "npx"\nargs = ["a-mcp@latest"]\n'}, "failed"),
        )
        for files, expected in cases:
            with self.subTest(files=files), tempfile.TemporaryDirectory() as directory:
                for relative, content in files.items():
                    path = Path(directory, relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                self.assertEqual(evaluate_check(Path(directory), check)["status"], expected)


if __name__ == "__main__":
    unittest.main()
