"""Source links in the catalog and the reference library."""

import json
import re
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from openguildkit.catalog import CatalogError, validate_entry, load_catalog, tracking_parameters
from openguildkit.references import load_references
from openguildkit.tools import load_tools

# The address each source publishes for its pages, checked offline: getbem.com answers 404 for /naming/
# and 200 for /naming (link check of 22 November 2026).
CANONICAL = {
    "getbem.com": re.compile(r"/(?:[a-z-]+)?"),
}


def _tool_urls():
    for tool in load_tools().values():
        yield f"tools/{tool['id']}", tool["homepage"]
        if "api" in tool:
            yield f"tools/{tool['id']}", tool["api"]["docs"]
        for server in tool["servers"]:
            for field in ("source", "repository", "status_source"):
                if field in server:
                    yield f"tools/{tool['id']}/{server['id']}", server[field]


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


# The letter of an EU act in its CELEX number, by the type that starts its ELI (reg_impl and dir_del included).
EU_ACT_LETTERS = {"reg": "R", "dir": "L", "dec": "D"}
ELI_ACT = re.compile(r"/eli/(reg|dir|dec)(?:_[a-z]+)?/(\d{4})/(\d+)(?:/.*)?")
CELEX_ACT = re.compile(r"CELEX:[03](\d{4})([RLD])(\d+)")


def _document_key(url: str) -> tuple:
    """Spellings that reach the same document share a key: an RFC on either IETF site, index.html, a final slash,
    an EU act on EUR-Lex in any language, ELI form (/oj, a consolidated date, the up-to-date form) or CELEX link,
    and the OpenAPI Specification under latest or one of its versions."""
    parts = urlsplit(url)
    host = parts.hostname.removeprefix("www.")
    rfc = re.fullmatch(r"/(?:doc/html|rfc|info)/(rfc\d+)(?:\.html|/)?", parts.path)
    if host in ("rfc-editor.org", "datatracker.ietf.org") and rfc:
        return ("rfc", rfc.group(1))
    if host == "eur-lex.europa.eu":
        eli, celex = ELI_ACT.fullmatch(parts.path), CELEX_ACT.search(unquote(parts.query))
        if eli:
            return ("eu-act", EU_ACT_LETTERS[eli.group(1)], eli.group(2), int(eli.group(3)))
        if celex:
            return ("eu-act", celex.group(2), celex.group(1), int(celex.group(3)))
    if host == "spec.openapis.org" and re.fullmatch(r"/oas/(?:latest|v\d+(?:\.\d+)*)(?:\.html)?", parts.path):
        return ("openapi",)
    path = parts.path.removesuffix("index.html").removesuffix(".html").rstrip("/")
    return (host, path.lower(), parts.query)


class SourceValidationTests(unittest.TestCase):
    def setUp(self):
        self.pack = json.loads(json.dumps(load_catalog()["packs"]["python"]))

    def check(self, url):
        self.pack["sources"] = [{"title": "Example", "url": url}]
        validate_entry("packs", self.pack)

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

    def test_spellings_of_one_eu_act_or_of_openapi_share_a_key(self):
        same = [
            ("https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra", "https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng"),
            ("https://eur-lex.europa.eu/eli/reg/2022/2065/oj", "https://eur-lex.europa.eu/eli/reg/2022/2065/oj/eng"),
            ("https://eur-lex.europa.eu/eli/dir/2022/2555/en", "https://eur-lex.europa.eu/eli/dir/2022/2555/oj/eng"),
            ("https://eur-lex.europa.eu/eli/reg/2024/1689/2026-07-27/eng", "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"),
            ("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32024R2847",
             "https://eur-lex.europa.eu/eli/reg/2024/2847/oj/eng"),
            ("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02002L0058-20091219",
             "https://eur-lex.europa.eu/eli/dir/2002/58/oj"),
            ("https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R2690",
             "https://eur-lex.europa.eu/eli/reg_impl/2024/2690/oj/eng"),
            ("https://spec.openapis.org/oas/latest.html", "https://spec.openapis.org/oas/v3.2.1.html"),
        ]
        for first, second in same:
            with self.subTest(url=first):
                self.assertEqual(_document_key(first), _document_key(second))
        different = [
            ("https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng", "https://eur-lex.europa.eu/eli/dir/2016/680/oj/eng"),
            ("https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng", "https://eur-lex.europa.eu/eli/dir/2016/679/oj/eng"),
            ("https://spec.openapis.org/oas/v3.2.1.html", "https://spec.openapis.org/arazzo/latest.html"),
        ]
        for first, second in different:
            with self.subTest(url=first):
                self.assertNotEqual(_document_key(first), _document_key(second))

    def test_eu_texts_use_one_language_and_one_eli_form(self):
        """English everywhere; an act at its Official Journal text (/oj/eng) or at a dated consolidation (#347)."""
        wrong = []
        for where, source in _all_sources():
            parts = urlsplit(source["url"])
            if parts.hostname != "eur-lex.europa.eu":
                continue
            if parts.path.startswith("/eli/"):
                if not re.fullmatch(r"/eli/[a-z_]+/\d{4}/\d+/(?:oj|\d{4}-\d{2}-\d{2})/eng", parts.path):
                    wrong.append(f"{where}: {source['url']}")
            elif not parts.path.startswith("/legal-content/EN/"):
                wrong.append(f"{where}: {source['url']}")
        self.assertEqual(wrong, [])

    def test_each_document_has_one_address(self):
        addresses = {}
        for where, source in _all_sources():
            url = source["url"].split("#")[0]
            addresses.setdefault(_document_key(url), {}).setdefault(url, where)
        duplicates = {key: spellings for key, spellings in addresses.items() if len(spellings) > 1}
        self.assertEqual(duplicates, {})

    def test_each_url_follows_the_canonical_form_of_its_source(self):
        urls = [(where, source["url"]) for where, source in _all_sources()] + list(_tool_urls())
        wrong = [f"{where}: {url}" for where, url in urls
                 if (urlsplit(url).hostname or "").removeprefix("www.") in CANONICAL
                 and not CANONICAL[urlsplit(url).hostname.removeprefix("www.")].fullmatch(urlsplit(url).path)]
        self.assertEqual(wrong, [])
        self.assertTrue(any(urlsplit(url).hostname == "getbem.com" for _, url in urls))
        self.assertIsNone(CANONICAL["getbem.com"].fullmatch("/naming/"))


if __name__ == "__main__":
    unittest.main()
