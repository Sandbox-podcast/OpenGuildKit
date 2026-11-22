"""The link checker classifies results and lists who cites each URL, without network access."""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.catalog import load_catalog
from openguildkit.references import load_references

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_links.py"
spec = importlib.util.spec_from_file_location("check_links", SCRIPT)
check_links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_links)

GDPR = "https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra"


class ClassificationTests(unittest.TestCase):
    def test_each_kind_of_result_gets_its_category(self):
        url = "https://example.org/spec/"
        cases = {
            "available": {"status": 200, "final_url": url},
            "redirected": {"status": 200, "final_url": "https://example.org/spec/v2/"},
            "dead": {"status": 404, "final_url": url},
            "to-recheck": {"status": 403, "final_url": url},
        }
        for category, result in cases.items():
            with self.subTest(category=category):
                self.assertEqual(check_links.classify(url, result), category)
        self.assertEqual(check_links.classify(url, {"status": 410, "final_url": url}), "dead")
        self.assertEqual(check_links.classify(url, {"status": 500, "final_url": url}), "dead")
        self.assertEqual(check_links.classify(url, {"status": 503, "final_url": url}), "to-recheck")
        self.assertEqual(check_links.classify(url, {"status": 200, "final_url": url + "?view=11"}), "available")
        self.assertEqual(check_links.classify(url, {"status": 202, "final_url": url}), "to-recheck")
        self.assertEqual(check_links.classify(url, {"status": None, "final_url": url, "error": "TimeoutError"}), "to-recheck")


class CitationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.citations = check_links.collect_citations(cls.catalog, load_references())

    def test_the_tool_registry_sources_are_checked_too(self):
        from openguildkit.tools import load_tools

        tools = load_tools()
        citations = check_links.collect_citations(self.catalog, load_references(), tools)
        server = tools["jira"]["servers"][0]
        cited = [entry for entry in citations[server["source"]] if entry["collection"] == "tools"]
        self.assertIn({"collection": "tools", "id": "jira", "server": server["id"]}, cited)
        self.assertIn("tools/jira, server " + server["id"], [check_links._citation(entry) for entry in cited])
        self.assertIn(tools["gryzzly"]["api"]["docs"], citations)
        # The page that states a server's status is checked as well.
        status = tools["jira"]["servers"][0]["status_source"]
        self.assertIn({"collection": "tools", "id": "jira", "server": server["id"], "status": True}, citations[status])
        self.assertFalse([url for url in citations if not url.startswith("https://")])

    def test_every_bundled_source_is_indexed_with_the_records_citing_it(self):
        for collection in ("packs", "patterns", "boards", "sectors"):
            for record in self.catalog[collection].values():
                for source in record["sources"]:
                    cited = {(entry["collection"], entry["id"]) for entry in self.citations[source["url"]]}
                    self.assertIn((collection, record["id"]), cited)
        cited = {(entry["collection"], entry["id"]): entry for entry in self.citations[GDPR]}
        self.assertEqual(cited[("references", "rgpd")]["packs"], ["gdpr"])
        pack = cited[("packs", "gdpr")]
        self.assertEqual(pack["version"], self.catalog["packs"]["gdpr"]["version"])
        self.assertIn("update-processing-record", pack["rules"])
        self.assertIn(("patterns", "gdpr-personal-data"), cited)

    def test_report_lists_categories_and_citations_and_fails_only_on_dead_links(self):
        def fetcher(url):
            if url == GDPR:
                return {"status": 404, "final_url": url}
            if url.startswith("https://www.iso.org/"):
                return {"status": 403, "final_url": url}
            return {"status": 200, "final_url": url}

        report = check_links.check(self.citations, fetcher, workers=4)
        self.assertEqual(report["summary"]["dead"], 1)
        self.assertGreater(report["summary"]["to-recheck"], 0)
        self.assertEqual(sum(report["summary"].values()), len(self.citations))
        with tempfile.TemporaryDirectory() as directory:
            json_path, markdown_path = check_links.write_report(report, Path(directory))
            self.assertEqual(json_path.name, f"links-{report['date']}.json")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["summary"], report["summary"])
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertLess(markdown.index("## Dead (1)"), markdown.index("## Redirected"))
            self.assertIn(f"- {GDPR} (HTTP 404)", markdown)
            self.assertIn("packs/gdpr@", markdown)
            with patch.object(check_links, "fetch", lambda url, timeout: fetcher(url)), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_links.main(["--out", directory, "--workers", "4"]), 1)
            with patch.object(check_links, "fetch", lambda url, timeout: {"status": 200, "final_url": url}), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(check_links.main(["--out", directory, "--workers", "4"]), 0)


if __name__ == "__main__":
    unittest.main()
