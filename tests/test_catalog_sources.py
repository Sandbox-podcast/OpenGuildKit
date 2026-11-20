"""Source links in the catalog and the reference library."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from openguildkit.catalog import CatalogError, _validate_entry, load_catalog, tracking_parameters
from openguildkit.references import load_references


def _all_sources():
    catalog = load_catalog()
    for collection, records in catalog.items():
        for record in records.values():
            for source in record["sources"]:
                yield f"{collection}/{record['id']}", source
    for family in load_references().values():
        for record in family["references"]:
            for source in record["sources"]:
                yield f"references/{record['id']}", source


def _document_key(url: str) -> tuple:
    """Spellings that reach the same document share a key: an RFC on either IETF site, index.html, a final slash."""
    parts = urlsplit(url)
    host = parts.hostname.removeprefix("www.")
    rfc = re.fullmatch(r"/(?:doc/html|rfc|info)/(rfc\d+)(?:\.html|/)?", parts.path)
    if host in ("rfc-editor.org", "datatracker.ietf.org") and rfc:
        return ("rfc", rfc.group(1))
    path = parts.path.removesuffix("index.html").removesuffix(".html").rstrip("/")
    return (host, path.lower(), parts.query)


class SourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.pack = json.loads(json.dumps(load_catalog()["packs"]["python"]))

    def check(self, url):
        self.pack["sources"] = [{"title": "Example", "url": url}]
        _validate_entry("packs", self.pack)

    def test_tracking_parameters_are_refused(self):
        for url in (
            "https://example.org/guide?utm_source=newsletter&utm_medium=email",
            "https://example.org/guide?trk=public_post",
            "https://example.org/guide?rd=1&visit_id=123",
            "https://example.org/guide?siteLocation=bottom-page",
            "https://example.org/guide?_src_ref=someone&triedRedirect=true",
            "https://example.org/guide?gclid=abc",
            "https://example.org/guide#:~:text=copied%20quote",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(CatalogError, "tracking parameter"):
                self.check(url)

    def test_queries_and_fragments_that_name_content_are_kept(self):
        for url in (
            "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R2847",
            "https://www.pcisecuritystandards.org/document_library/?class=pcidss&doc=pci_dss",
            "https://learn.microsoft.com/en-us/aspnet/core/fundamentals/use-http-context#requestaborted",
        ):
            with self.subTest(url=url):
                self.assertEqual(tracking_parameters(url), [])
                self.check(url)

    def test_reference_files_use_the_same_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            family = {
                "id": "team-practices",
                "title": "Team practices",
                "references": [{
                    "id": "team-change-record", "title": "Change record", "category": "Livraison",
                    "kind": "pratique", "summary": "Trace les changements.", "applies_when": "Toujours.",
                    "sources": [{"title": "Handbook", "url": "https://example.org/handbook?utm_campaign=launch"}],
                }],
            }
            (Path(directory) / "team-practices.json").write_text(json.dumps(family), encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "tracking parameter 'utm_campaign'"):
                load_references(Path(directory))


class BundledSourceTests(unittest.TestCase):
    def test_bundled_sources_carry_no_tracking_parameter(self):
        for where, source in _all_sources():
            self.assertEqual(tracking_parameters(source["url"]), [], where)

    def test_each_document_has_one_address(self):
        addresses = {}
        for where, source in _all_sources():
            url = source["url"].split("#")[0]
            addresses.setdefault(_document_key(url), {}).setdefault(url, where)
        duplicates = {key: spellings for key, spellings in addresses.items() if len(spellings) > 1}
        self.assertEqual(duplicates, {})


if __name__ == "__main__":
    unittest.main()
