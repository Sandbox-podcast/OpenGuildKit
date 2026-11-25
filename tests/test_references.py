import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import ID_PATTERN, CatalogError, load_catalog
from openguildkit.cli import main
from openguildkit.project import render_instructions, resolved_profile, validate_profile
from openguildkit.references import (
    KINDS,
    check_reference_links,
    find_references,
    load_references,
    with_pattern_references,
)

# Methods that have a hand-written reference and a pattern: the index shows each one once.
PRESENTED = {
    "scrum": "scrum", "kanban-guide": "kanban", "okr": "okr", "jobs-to-be-done": "jobs-to-be-done",
    "opportunity-solution-tree": "opportunity-solution-tree", "double-diamond": "double-diamond",
    "meddpicc": "meddpicc", "spin-selling": "spin-selling", "utm": "utm-campaign-measurement",
    "playwright": "playwright-web", "owasp-asvs": "owasp-asvs-review", "wcag-22": "wcag-web-accessibility",
    "nist-ai-rmf": "nist-ai-risk-management", "iso-iec-27001": "iso-27001-isms",
    "llm-agent-evaluations": "llm-evaluation", "site-reliability-engineering": "service-reliability-sre",
    "nist-ssdf": "secure-software-lifecycle",
}


# Standards and specifications without an `edition`, and why: the cited source names none (#348).
UNDATED_STANDARDS = {
    "archimate": "The cited Open Group article compares ArchiMate with TOGAF and names no edition of the language.",
    "html": "A living standard: the WHATWG page shows only the day it was last updated.",
    "oci-image-spec": "The cited OCI page publishes the specification text without a version number.",
    "openfeature": "The cited specification page shows no version; its sections carry a stability status instead.",
    "iso-3166": "ISO says the codes are kept up to date on its Online Browsing Platform; the page names no edition.",
    "iec-62443": "A series whose parts each have their own edition; the cited IEC page covers the series.",
    "iso-iec-ieee-29119": "A series whose parts each have their own edition, such as Part 2, Edition 2, 2021.",
}
# Regulations applied by a pack: each carries the consolidated text EUR-Lex showed as current when it was read, as
# eu-ai-act does, or says here why it has none (#348).
UNDATED_REGULATIONS = {
    "facturation-electronique-france": "French law cited through impots.gouv.fr and service-public.gouv.fr, which give "
                                       "no edition; EUR-Lex holds no consolidation of it.",
}


def write_family(directory, references, family_id="team-practices", title="Team practices"):
    path = Path(directory) / f"{family_id}.json"
    path.write_text(json.dumps({"id": family_id, "title": title, "references": references}), encoding="utf-8")
    return path.parent


def team_record(**fields):
    record = {
        "id": "team-change-record", "title": "Change record", "category": "Livraison", "kind": "pratique",
        "summary": "Trace les changements.", "applies_when": "Pour chaque mise en production.",
        "sources": [{"title": "Handbook", "url": "https://example.org/handbook"}],
    }
    return {**record, **fields}


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.families = load_references()
        cls.catalog = load_catalog()
        cls.index = with_pattern_references(cls.families, cls.catalog["patterns"])

    def test_title_matches_rank_above_mentions(self):
        matches = find_references(self.families, query="ISO 27001")
        self.assertEqual(matches[0]["id"], "iso-iec-27001")
        self.assertEqual(matches[0]["family"], "governance")

    def test_search_ignores_accents_and_can_filter_by_family(self):
        query = "observabilite"
        matches = find_references(self.families, family_id="cloud", query=query)
        self.assertTrue(matches)
        self.assertTrue(all(record["family"] == "cloud" for record in matches))
        self.assertEqual(matches, find_references(self.families, family_id="cloud", query="OBSERVABILITÉ"))

    def test_local_entries_extend_families_without_shadowing_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.json"
            family = self.families["code"]
            example = family["references"][0]
            data = {
                "id": "code",
                "title": family["title"],
                "references": [{**example, "id": "team-code-style", "title": "Team code style"}],
            }
            path.write_text(json.dumps(data), encoding="utf-8")
            merged = load_references(path.parent)
            self.assertEqual(len(merged["code"]["references"]), len(family["references"]) + 1)
            self.assertEqual(find_references(merged, record_id="team-code-style")[0]["family"], "code")
            data["references"] = [example]
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "Duplicate reference ID"):
                load_references(path.parent)

    def test_ids_use_hyphens_and_former_ids_still_resolve(self):
        records = [record for family in self.families.values() for record in family["references"]]
        self.assertEqual([record["id"] for record in records if not ID_PATTERN.fullmatch(record["id"])], [])
        for former, current in (("pd_iac", "infrastructure-as-code"), ("agent_agent_memory", "agent-memory"),
                                ("root-add-sql", "sql"), ("pd_continuous_deployment", "continuous-deployment")):
            with self.subTest(former=former):
                self.assertEqual(find_references(self.index, record_id=former)[0]["id"], current)

    def test_ids_and_aliases_are_validated_and_unique(self):
        cases = [
            (team_record(id="team_change_record"), "Use lowercase letters, digits and hyphens"),
            (team_record(aliases=["Team Change"]), "aliases must list former IDs"),
            (team_record(aliases=["team-change-record"]), "aliases must list former IDs"),
            (team_record(aliases=["pd_iac"]), "Duplicate reference ID: pd_iac"),
            (team_record(id="pd-iac", aliases=["infrastructure-as-code"]), "Duplicate reference ID"),
        ]
        for record, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                with self.assertRaisesRegex(CatalogError, message):
                    load_references(write_family(directory, [record]))

    def test_kind_uses_the_closed_vocabulary(self):
        kinds = {record["kind"] for family in self.families.values() for record in family["references"]}
        self.assertLessEqual(kinds, set(KINDS))
        self.assertLessEqual(len(KINDS), 15)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(CatalogError, "kind must be one of"):
            load_references(write_family(directory, [team_record(kind="Practice")]))

    def test_references_packs_and_patterns_name_each_other(self):
        check_reference_links(self.families, self.catalog)
        for reference_id, pattern_id in PRESENTED.items():
            with self.subTest(reference=reference_id):
                record = find_references(self.families, record_id=reference_id)[0]
                self.assertEqual(record["pattern"], pattern_id)
                self.assertIn(reference_id, self.catalog["patterns"][pattern_id]["references"])
                self.assertTrue(set(record["packs"]) <= set(self.catalog["packs"]))
        broken = json.loads(json.dumps(self.catalog))
        broken["patterns"]["scrum"]["references"] = ["definition-of-done"]
        with self.assertRaisesRegex(CatalogError, "must list reference 'scrum'"):
            check_reference_links(self.families, broken)
        with tempfile.TemporaryDirectory() as directory:
            local = load_references(write_family(directory, [team_record(packs=["no-such-pack"])]))
            with self.assertRaisesRegex(CatalogError, "unknown packs: no-such-pack"):
                check_reference_links(local, self.catalog)

    def test_the_index_shows_each_method_once(self):
        generated = [record["pattern"] for record in self.index["work-patterns"]["references"]]
        presented = [record["pattern"] for family in self.families.values() for record in family["references"] if "pattern" in record]
        self.assertLessEqual(set(PRESENTED.values()), set(presented))
        self.assertEqual(sorted(generated + presented), sorted(self.catalog["patterns"]))
        scrum = find_references(self.index, record_id="pattern-scrum")
        self.assertEqual([(record["id"], record["family"]) for record in scrum], [("scrum", "product")])
        self.assertEqual((scrum[0]["pattern"], scrum[0]["packs"], scrum[0]["status"]), ("scrum", ["scrum-delivery"], "applied"))
        titles = [record["title"] for family in self.index.values() for record in family["references"]]
        self.assertEqual(titles.count("Scrum"), 1)
        with tempfile.TemporaryDirectory() as directory:
            local = load_references(write_family(directory, [team_record(pattern="no-such-pattern")]))
            with self.assertRaisesRegex(CatalogError, "presents unknown pattern"):
                with_pattern_references(local, self.catalog["patterns"])

    def test_every_reference_names_the_brains_it_serves(self):
        for family in self.families.values():
            for record in family["references"]:
                with self.subTest(reference=record["id"]):
                    self.assertTrue(1 <= len(record.get("brains", [])) <= 3)
                    self.assertTrue(set(record["brains"]) <= set(self.catalog["boards"]))
        with tempfile.TemporaryDirectory() as directory:
            local = load_references(write_family(directory, [team_record(brains=["no-such-brain"])]))
            with self.assertRaisesRegex(CatalogError, "unknown brains: no-such-brain"):
                check_reference_links(local, self.catalog)
            with self.assertRaisesRegex(CatalogError, "brains contains duplicates"):
                load_references(write_family(directory, [team_record(brains=["hr", "hr"])]))

    def test_every_brain_has_references_of_its_discipline(self):
        counts = {board_id: 0 for board_id in self.catalog["boards"]}
        for family in self.families.values():
            for record in family["references"]:
                for board_id in record["brains"]:
                    counts[board_id] += 1
        self.assertEqual({board_id: count for board_id, count in counts.items() if count < 5}, {})
        business_brains = ("hr", "finance", "sales", "communication", "support", "legal",
                           "project-management", "operations", "leadership")
        self.assertEqual({board_id: counts[board_id] for board_id in business_brains if counts[board_id] < 6}, {})

    def test_business_references_are_found_by_family_and_by_word(self):
        for family_id in ("people", "finance", "legal", "support", "communication", "delivery", "strategy"):
            with self.subTest(family=family_id):
                self.assertTrue(find_references(self.index, family_id=family_id))
        for query, expected in (("ISO 30414", "iso-30414"), ("PMBOK", "pmbok"), ("KCS", "kcs"),
                                ("IFRS 15", "ifrs-15"), ("Barcelona Principles", "amec-barcelona-principles"),
                                ("2023/970", "eu-pay-transparency"), ("ISO 37000", "iso-37000")):
            with self.subTest(query=query):
                self.assertEqual(find_references(self.index, query=query)[0]["id"], expected)

    def test_the_e_invoicing_reference_cites_the_page_that_holds_its_reception_rule_and_timetable(self):
        """impots.gouv.fr gives the start date only; service-public A18953 gives the reception duty and the
        issuing timetable by company size, which the summary states (#301)."""
        reference = find_references(self.index, record_id="facturation-electronique-france")[0]
        self.assertIn("reçoivent", reference["summary"])
        self.assertIn("1er septembre 2027", reference["summary"])
        cited = {source["url"]: source.get("checked") for source in reference["sources"]}
        checked = cited.get("https://entreprendre.service-public.gouv.fr/actualites/A18953?lang=fr")
        self.assertIsNotNone(checked)
        self.assertGreaterEqual(checked, "2026-11-23")

    def test_references_sit_in_the_family_of_their_discipline(self):
        family_of = {record["id"]: family_id for family_id, family in self.families.items() for record in family["references"]}
        self.assertEqual(family_of["core-web-vitals"], "quality")
        self.assertEqual({family_of[name] for name in ("spf", "dkim", "dmarc")}, {"security"})
        self.assertEqual({family_of[name] for name in ("iso-10002", "iso-10004", "kcs")}, {"support"})

    def test_editions_are_shown_with_the_rules_or_the_documentary_status(self):
        records = {record["id"]: record for family in self.families.values() for record in family["references"]}
        for record in records.values():
            if record["kind"] == "norme" and re.search(r":(19|20)\d\d", record["title"]):
                with self.subTest(reference=record["id"]):
                    self.assertTrue(record.get("edition"))
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--project", directory, "references", "--id", "iso-iec-27001"]), 0)
            self.assertIn("Edition: 2022", output.getvalue())
            self.assertIn("Pack iso-27001@", output.getvalue())
            self.assertIn("confirm-isms-scope", output.getvalue())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["--project", directory, "references", "--id", "iso-9001"]), 0)
            self.assertIn("Status: documentary reference", output.getvalue())
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(CatalogError, "edition must be a non-empty string"):
            load_references(write_family(directory, [team_record(edition="")]))

    def test_standards_and_applied_regulations_carry_the_edition_they_follow(self):
        records = {record["id"]: record for family in self.families.values() for record in family["references"]}
        undated = sorted(record_id for record_id, record in records.items()
                         if record["kind"] in ("norme", "spécification") and not record.get("edition"))
        self.assertEqual(undated, sorted(UNDATED_STANDARDS))
        applied = {record_id: record for record_id, record in records.items()
                   if record["kind"] == "réglementation" and record.get("packs")}
        self.assertEqual(sorted(record_id for record_id, record in applied.items() if not record.get("edition")),
                         sorted(UNDATED_REGULATIONS))
        for record_id, record in applied.items():
            if record_id in UNDATED_REGULATIONS:
                continue
            with self.subTest(reference=record_id):
                self.assertRegex(record["edition"], r"^0\d{4}[RLD]\d{4}-\d{8}$")
                urls = [source["url"] for source in record["sources"]]
                self.assertIn(f"https://publications.europa.eu/resource/celex/{record['edition']}", urls)
                self.assertTrue(any(url.startswith("https://eur-lex.europa.eu/") for url in urls))
        openapi = records["openapi"]
        self.assertEqual(openapi["edition"], "3.2.1")
        self.assertEqual([source["url"] for source in openapi["sources"]], ["https://spec.openapis.org/oas/v3.2.1.html"])

    def test_the_documented_gdpr_example_extends_the_bundled_pack(self):
        text = (Path(__file__).resolve().parents[1] / "docs" / "references.md").read_text(encoding="utf-8")
        block = re.search(r"<!-- worked-example: team-gdpr -->\s*```json\n(.*?)```", text, re.S).group(1)
        with tempfile.TemporaryDirectory() as directory:
            packs = Path(directory) / "packs"
            packs.mkdir()
            (packs / "team-gdpr.json").write_text(block, encoding="utf-8")
            catalog = load_catalog(Path(directory))
        self.assertEqual(catalog["packs"]["team-gdpr"]["depends_on"], ["gdpr"])
        self.assertIn("gdpr", find_references(self.families, record_id="rgpd")[0]["packs"])
        profile = validate_profile({"name": "Support console", "packs": ["team-gdpr"]}, catalog)
        selected = resolved_profile(profile, catalog)["packs"]
        self.assertLess(selected.index("gdpr"), selected.index("team-gdpr"))
        instructions = render_instructions(profile, catalog)
        self.assertLess(instructions.index("`gdpr@"), instructions.index("`team-gdpr@"))
        self.assertIn("`link-processing-entry`", instructions)

