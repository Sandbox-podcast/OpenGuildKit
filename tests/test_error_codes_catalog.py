"""Stable error codes of the catalog records (#487): each refusal of a pack, pattern, brain, tool, reference, feature
or deliverable record carries its own code, provoked here when no other test meets it."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import catalog, deliverables, features, references, tool_registry
from openguildkit.catalog import CatalogError, load_catalog
from openguildkit.errors import OgkError
from tests.test_error_codes import CodedRefusals

SOURCE = {"title": "Docs", "url": "https://example.com/docs"}
RULE = {"id": "r", "instruction": "Do it.", "verification": "Check it."}
PACK = {"id": "p", "title": "P", "description": "D.", "sources": [], "version": "1.0.0", "rules": [RULE]}
BOARD = {"id": "b", "title": "B", "description": "D.", "sources": [], "expertises": ["x"], "triggers": ["x"],
         "questions": ["x"]}
SPECIALIST = {"id": "s", "title": "S", "focus": "F."}
REMOTE = {"id": "demo-mcp", "name": "Demo", "publisher": "vendor", "maintainer": "Demo", "transport": "streamable-http",
          "url": "https://mcp.example.com/mcp", "auth": "oauth", "env": [], "status": "ga", "capabilities": "Reads.",
          "source": "https://example.com/docs", "verified": "2026-01-01"}
STDIO = {**{key: value for key, value in REMOTE.items() if key != "url"}, "id": "demo-local", "transport": "stdio",
         "command": "npx", "args": ["demo-mcp"], "package": {"registry": "npm", "name": "demo-mcp"}}
TOOL = {"id": "demo", "title": "Demo", "vendor": "Demo Inc", "summary": "A demo.", "homepage": "https://example.com",
        "brains": ["data"], "servers": [REMOTE]}
DELIVERABLE = {"id": "d", "title": "T", "description": "D.", "brains": ["x"], "inputs": [], "tool_actions": [],
               "sections": [], "checks": [], "sources": []}


def call(function, *args, **kwargs):
    return lambda: function(*args, **kwargs)


class CatalogRecordCodeTests(CodedRefusals):
    """Issue #487: CatalogError printed `OpenGuildKit: message`, without a code, for every record of the catalog."""

    def test_issue_487_each_wrong_field_of_a_catalog_record_has_its_code(self):
        def pattern(**fields):
            return call(catalog._validate_pattern, {"roles": ["a"], "packs": ["p"], **fields})

        evidence = [{"id": f"e{index}", "title": "E"} for index in range(catalog.MAX_EVIDENCE + 1)]
        review = {"specialists": [SPECIALIST, SPECIALIST], "evidence": ["x"], "challenge": ["x"],
                  "decision_criteria": ["x"]}
        self.assertCodes([
            ("OGK-CATALOG-006", call(catalog.validate_fields, [], "record", set())),
            ("OGK-CATALOG-012", call(catalog.validate_list, "x", "rules")),
            ("OGK-CATALOG-016", call(catalog.validate_sources, [{**SOURCE, "url": "http://example.com"}])),
            ("OGK-CATALOG-017", call(catalog.validate_sources, [{**SOURCE, "url": "https://example.com/a b"}])),
            ("OGK-CATALOG-019", call(catalog.validate_sources, [SOURCE, SOURCE])),
            ("OGK-CATALOG-021", call(catalog._validate_pack, {**PACK, "depends_on": ["a", "a"]})),
            ("OGK-CATALOG-023", call(catalog._validate_pack, {**PACK, "depends_on": ["a"], "conflicts_with": ["a"]})),
            ("OGK-CATALOG-024", call(catalog._validate_pack, {**PACK, "rules": [RULE, RULE]})),
            ("OGK-CATALOG-028", call(catalog._validate_evidence, evidence, "rules[0]")),
            ("OGK-CATALOG-037", call(catalog._validate_pattern, {"roles": ["a", "a"], "packs": ["p"]})),
            ("OGK-CATALOG-038", pattern(references=["r", "r"])),
            ("OGK-CATALOG-043", pattern(match={"stack": [["++"]]})),
            ("OGK-CATALOG-044", pattern(match={"stack": [["python"]], "min_versions": {}})),
            ("OGK-CATALOG-050", call(catalog._validate_board_review, review)),
            ("OGK-CATALOG-054", call(catalog.validate_dependencies, {"a": {"depends_on": ["b"]}})),
            ("OGK-CATALOG-055", call(catalog.validate_dependencies, {"a": {"conflicts_with": ["b"]}})),
            ("OGK-CATALOG-056", call(catalog.validate_dependencies, {"a": {"depends_on": ["b"]},
                                                                     "b": {"depends_on": ["a"]}})),
            ("OGK-CATALOG-066", call(catalog._add_central_policy, {"packs": {}}, ("c0ffee", PACK))),
            ("OGK-CATALOG-068", call(catalog._check_links, {"packs": {}, "sectors": {},
                                                             "patterns": {"x": {"packs": ["zz"]}}})),
            ("OGK-CATALOG-069", call(catalog._check_links, {"packs": {}, "sectors": {},
                                                             "patterns": {"x": {"packs": [], "match": {"sectors": ["zz"]}}}})),
        ])

    def test_issue_487_each_wrong_catalog_folder_has_its_code(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "empty").mkdir()
            (root / "bare" / "packs").mkdir(parents=True)
            (root / "project" / "packs").mkdir(parents=True)
            (root / "project" / "boards").write_text("", encoding="utf-8")
            (root / "file").write_text("", encoding="utf-8")
            self.assertCodes([
                ("OGK-CATALOG-058", call(catalog.read_record_files, root / "empty")),
                ("OGK-CATALOG-059", call(catalog.read_record_files, root / "bare")),
                ("OGK-CATALOG-065", call(load_catalog, root / "project")),
                ("OGK-CATALOG-070", call(load_catalog, root / "file")),
            ])

    def test_issue_487_each_wrong_organization_record_has_its_code(self):
        def organization(collection, name, data):
            files = {collection: [(name, data)]}
            return call(catalog._organization_records, collection, {"commit": "c0ffee" * 7, "files": files}, {})

        # The parser of Python 3.11 to 3.13 recurses on nested brackets; that of 3.15 does not.
        with patch("openguildkit.catalog.json.loads", side_effect=RecursionError):
            self.assertCodes([("OGK-CATALOG-063", organization("packs", "packs/p.json", b"[[]]"))])
        for inner, case in (
            ("OGK-CATALOG-061", organization("boards", "boards/b.json", json.dumps(BOARD).encode())),
            ("OGK-CATALOG-062", organization("packs", "packs/other.json", json.dumps(PACK).encode())),
        ):
            with self.subTest(code=inner), self.assertRaises(CatalogError) as raised:
                case()
            self.assertEqual((raised.exception.code, raised.exception.__cause__.code), ("OGK-CATALOG-064", inner))


class ToolRecordCodeTests(CodedRefusals):
    """Issue #487: a wrong tool or MCP server record of the registry printed its refusal without a code."""

    def test_issue_487_each_wrong_server_has_its_code(self):
        def server(base=REMOTE, **fields):
            record = {**base, **fields}
            return call(tool_registry._validate_server, {key: value for key, value in record.items()
                                                         if value is not None}, "data/demo")

        self.assertCodes([
            ("OGK-CATALOG-071", call(tool_registry._catalog_line, " padded", "title")),
            ("OGK-CATALOG-075", call(tool_registry._validate_server, "x", "data/demo")),
            ("OGK-CATALOG-076", server(id="Bad_ID")),
            ("OGK-CATALOG-079", server(settings="x")),
            ("OGK-CATALOG-080", server(command="npx")),
            ("OGK-CATALOG-081", server(STDIO, url="https://mcp.example.com/mcp")),
            ("OGK-CATALOG-082", server(STDIO, args=[1])),
            ("OGK-CATALOG-083", server(STDIO, package={"registry": "zzz", "name": "demo"})),
            ("OGK-CATALOG-089", server(read_only={"how": "Reads.", "url": "https://mcp.example.com/ro/{team}"})),
            ("OGK-CATALOG-091", server(STDIO, read_only={"how": "Reads.", "args": [""]})),
        ])

    def test_issue_487_each_wrong_tool_has_its_code(self):
        def tool(**fields):
            return call(tool_registry._validate_tool, {**TOOL, **fields}, "data")

        def tool_file(record, name="data.json", tools=None, endpoints=None):
            return call(tool_registry._load_tool_file, Path(name), record, False, tools or {}, endpoints or {}, {})

        listed = {"id": "data", "title": "Data", "tools": [TOOL]}
        self.assertCodes([
            ("OGK-CATALOG-093", tool(api={"kind": "zzz", "docs": "https://example.com/api"})),
            ("OGK-CATALOG-094", tool(detect={})),
            ("OGK-CATALOG-095", tool(detect={"files": ["../secrets"]})),
            ("OGK-CATALOG-096", call(tool_registry._validate_tool, {}, "data")),
            ("OGK-CATALOG-097", tool(id="Bad")),
            ("OGK-CATALOG-098", tool(brains=[])),
            ("OGK-CATALOG-099", tool(aliases="x")),
            ("OGK-CATALOG-100", tool(servers="x")),
            ("OGK-CATALOG-101", tool(servers=[REMOTE, REMOTE])),
            ("OGK-CATALOG-103", tool_file({})),
            ("OGK-CATALOG-104", tool_file({"id": "zzz", "title": "Z", "tools": []}, "zzz.json")),
            ("OGK-CATALOG-105", tool_file({"id": "data", "title": "Data", "tools": "x"})),
            ("OGK-CATALOG-106", tool_file(listed, tools={"demo": {}})),
            ("OGK-CATALOG-107", tool_file(listed, endpoints={"demo-mcp": ("stdio",)})),
            ("OGK-CATALOG-109", call(tool_registry.check_tool_links, {"demo": TOOL}, {})),
        ])


class ReferenceAndFeatureCodeTests(CodedRefusals):
    """Issue #487: a wrong reference family, feature or deliverable record printed its refusal without a code."""

    def test_issue_487_each_wrong_reference_has_its_code(self):
        patterns = load_catalog()["patterns"]
        pattern_id, pattern = next(iter(patterns.items()))
        family = {"id": "f", "title": "F", "references": []}

        def links(**patterns_):
            return {"boards": {}, "packs": {}, "patterns": patterns_}

        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "file").write_text("", encoding="utf-8")
            self.assertCodes([
                ("OGK-DOCS-007", call(references._validate_links, {"aliases": ["old_a", "old_a"]}, "r")),
                ("OGK-DOCS-009", call(references._validate_links, {"packs": ["p", "p"]}, "r")),
                ("OGK-DOCS-010", call(references._validate_family, family, "g.json")),
                ("OGK-DOCS-013", call(references._merge_family, {**family, "title": "G"}, {"f": family}, set(), None)),
                ("OGK-DOCS-015", call(references.load_references, Path(folder) / "file")),
                ("OGK-DOCS-020", call(references.check_reference_links, {},
                                      links(x={"packs": [], "references": ["r"]}))),
                ("OGK-DOCS-021", call(references.check_reference_links, {"f": {"references": [{"id": "r"}]}},
                                      links(x={"packs": [], "references": ["r"]}))),
                ("OGK-DOCS-022", call(references.with_pattern_references, {references.PATTERN_FAMILY: {}}, {})),
                ("OGK-DOCS-024", call(references.with_pattern_references, {"f": {"references": [
                    {"id": "a", "pattern": pattern_id}, {"id": "b", "pattern": pattern_id}]}}, patterns)),
                ("OGK-DOCS-025", call(references.with_pattern_references, {"f": {"references": [
                    {"id": f"pattern-{pattern_id}"}]}}, {pattern_id: pattern})),
            ])
            with patch("openguildkit.references.package_file", return_value=Path(folder)):
                (Path(folder) / "file").unlink()
                self.assertCodes([("OGK-DOCS-017", references.load_references)])

    def test_issue_487_each_wrong_feature_has_its_code(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "features.json"
            path.write_text(json.dumps({"features": [{}, {}]}), encoding="utf-8")
            with patch("openguildkit.features.package_file", return_value=path), \
                    patch("openguildkit.features._feature", return_value={"id": "twice"}):
                self.assertCodes([("OGK-FEATURE-011", call(features.load_features, {}))])
        self.assertCodes([
            ("OGK-FEATURE-004", call(features._option, "x", "feature f", {})),
            ("OGK-FEATURE-006", call(features._option, {"tool": "t", "as": ""}, "feature f", {"t": {"title": "T"}})),
            ("OGK-FEATURE-007", call(features._feature, {}, {})),
            ("OGK-FEATURE-008", call(features._feature, {"id": "Bad", "purpose": "P", "lead": {}, "alternatives": []},
                                     {})),
        ])

    def test_issue_487_each_wrong_deliverable_has_its_code(self):
        known = {"patterns": {}, "boards": {"x": {}}}

        def deliverable(**fields):
            return call(deliverables._validate, {**DELIVERABLE, **fields}, known)

        self.assertCodes([
            ("OGK-RESULT-036", deliverable(market="yes")),
            ("OGK-RESULT-037", deliverable(method="zz")),
            ("OGK-RESULT-038", deliverable(brains=["zz"])),
            ("OGK-RESULT-039", deliverable(inputs=[{"id": "i", "label": "L", "data": "zz"}])),
            ("OGK-RESULT-040", deliverable(inputs=[{"id": "i", "label": "L", "data": "none"}],
                                          tool_actions=[{"action": "zz", "description": "D."}])),
        ])
        loaded = load_catalog()
        bundled = next(iter(deliverables.load_deliverables(loaded).values()))
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "wrong.json").write_text(json.dumps(bundled), encoding="utf-8")
            with self.assertRaises(OgkError) as raised:
                deliverables.load_deliverables(loaded, Path(folder))
        self.assertEqual((raised.exception.code, raised.exception.__cause__.code), ("OGK-RESULT-042", "OGK-RESULT-041"))


if __name__ == "__main__":
    unittest.main()
