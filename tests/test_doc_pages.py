"""The pages written for a reader (administration, support, threat model, host coverage, troubleshooting) stay true:
each names its reader, its links lead somewhere, its commands exist, and what it says of the code follows the code."""

import re
import unittest
from pathlib import Path

from openguildkit import hosts
from openguildkit.decisions import PAYLOAD_VERSIONS
from openguildkit.project import SCHEMA_VERSION
from tests.test_doc_links import anchors
from tests.test_entry_pages import _commands, _parse_error

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
LINK = re.compile(r"\]\(([^)\s]+)\)")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
STATUSES = {"enforced", "partial", "instruction", "none", "not established"}
READER_PAGES = ("README", "admin-guide", "support", "threat-model", "host-coverage", "troubleshooting",
                "profile-reference", "exit-codes")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def table(page: str, heading: str) -> list[list[str]]:
    """The rows of the first table under a level-two heading, each as its cells; the header and the rule come first."""
    section = page.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
    return [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in section.splitlines()
            if line.startswith("|")]


class ReaderTests(unittest.TestCase):
    def test_every_page_of_docs_names_its_reader_on_the_line_after_its_title(self):
        """Issue #491: none of the 23 pages of docs/ said whom it was written for."""
        pages = sorted(DOCS.glob("*.md"))
        self.assertGreaterEqual(len(pages), 30)
        for page in pages:
            with self.subTest(page=page.name):
                lines = [line for line in read(page).splitlines() if line.strip()]
                self.assertTrue(lines[0].startswith("# "), lines[0])
                self.assertRegex(lines[1], r"^(For|Pour) ?: \S")

    def test_the_index_lists_every_page_of_docs(self):
        links = {target.split("#")[0] for target in LINK.findall(read(DOCS / "README.md"))}
        self.assertEqual(sorted(page.name for page in DOCS.glob("*.md") if page.name != "README.md"
                                and page.name not in links), [])

    def test_the_links_of_the_reader_pages_lead_to_a_page_and_a_heading(self):
        for name in READER_PAGES:
            page = DOCS / f"{name}.md"
            for target in LINK.findall(read(page)):
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, anchor = target.partition("#")
                with self.subTest(page=name, link=target):
                    destination = (page.parent / path) if path else page
                    self.assertTrue(destination.exists(), path)
                    if anchor:
                        self.assertIn(anchor, anchors(destination))

    def test_the_commands_of_the_reader_pages_are_accepted_by_the_cli(self):
        for name in READER_PAGES:
            for words in _commands(read(DOCS / f"{name}.md")):
                with self.subTest(page=name, command=" ".join(words)):
                    self.assertIsNone(_parse_error(words))


class TroubleshootingTests(unittest.TestCase):
    def test_each_message_of_the_page_is_still_in_the_code(self):
        source = "\n".join(read(path) for path in sorted((REPO / "src" / "openguildkit").glob("*.py")))
        every = [row[0].strip("`") for heading in ("Setup", "Host settings and the guard", "Tasks and results",
                                                   "Catalog and CI")
                 for row in table(read(DOCS / "troubleshooting.md"), heading)[2:]]
        self.assertGreaterEqual(len(every), 15)
        for message in every:
            with self.subTest(message=message):
                self.assertIn(message, source)


class HostCoverageTests(unittest.TestCase):
    def setUp(self):
        self.page = read(DOCS / "host-coverage.md")
        self.rows = table(self.page, "Each host and surface")[2:]

    def test_the_page_follows_the_hosts_with_a_hook_and_the_tools_without_one(self):
        """Issue #476: a host added to HOOK_HOSTS, or a tool of UNHOOKED_TOOLS, must reach the page."""
        for host in hosts.HOOK_HOSTS:
            with self.subTest(host=host):
                self.assertIn(f"| `{host}` |", self.page)
        for tool_id, tool in hosts.UNHOOKED_TOOLS.items():
            with self.subTest(tool=tool_id):
                row = next(row for row in self.rows if row[0] == f"`{tool_id}`")
                for page in tool["pages"]:
                    self.assertIn(page, row[4])
                self.assertIn(tool["read"], row[4])
                self.assertIn("none", row[2])

    def test_a_cell_enforced_or_none_names_the_page_read_and_the_day(self):
        for row in self.rows:
            with self.subTest(row=row[:2]):
                cells = row[2:4]
                for cell in cells:
                    self.assertIn(cell.split(":")[0].strip("` "), STATUSES)
                if any(cell.startswith(("`enforced`", "`none`")) for cell in cells):
                    self.assertIn("https://", row[4])
                    self.assertRegex(row[4], DAY)

    def test_the_page_says_what_the_claude_code_page_says_of_a_cloud_session(self):
        section = self.page.split("### What the Claude Code page says about a cloud session", 1)[1]
        self.assertIn("none of a repository's `.claude/settings.json` permission rules, hooks, or `env` apply", section)
        self.assertIn("https://code.claude.com/docs/en/settings", section)
        self.assertIn("2026-11-26", section)

    def test_the_matrix_of_the_hosts_has_a_column_for_each_host_init_offers_and_a_version_row(self):
        """Issue #491: the table of what the host enforces had no column for Gemini CLI."""
        text = read(REPO / "integrations" / "README.md")
        rows = table(text.replace("## What the host enforces", "## What the host enforces", 1), "What the host enforces")
        header = rows[0]
        self.assertEqual(header[0], "Rule")
        self.assertEqual(len(header) - 1, len(hosts.HOSTS))
        for host, column in zip(hosts.HOSTS, header[1:], strict=True):
            self.assertEqual(column.lower().replace(" ", "-").replace("other-hosts", "other"), host)
        version = next(row for row in rows if row[0] == "Version checked")
        self.assertEqual(len(version), len(header))


class SupportTests(unittest.TestCase):
    def test_the_versions_the_page_says_are_read_are_the_ones_the_code_reads(self):
        rows = {row[0]: row[2] for row in table(read(DOCS / "support.md"), "What the code reads today")[2:]}
        self.assertEqual(rows["Profile (`.openguildkit/project.json`)"], str(SCHEMA_VERSION))
        self.assertEqual(SCHEMA_VERSION, 1)
        for module, label in (("lock", "Catalog lock (`.openguildkit/catalog.lock.json`)"), ("tasks", "Task record")):
            source = read(REPO / "src" / "openguildkit" / f"{module}.py")
            self.assertRegex(source, r'\.get\("schema_version"\) != 1\b')
            self.assertEqual(rows[label], "1")
        self.assertEqual(rows["Exported decision record"].split(" (")[0], "3, 2 and 1")
        self.assertEqual(PAYLOAD_VERSIONS, (3, 2, 1))

    def test_no_duration_is_invented_and_the_security_policy_points_to_the_page(self):
        page = read(DOCS / "support.md")
        decided = page.split("## To be decided by the maintainer", 1)[1]
        self.assertGreaterEqual(decided.count("à décider par le mainteneur"), 3)
        self.assertNotRegex(decided, r"\b\d+ (months?|years?|minor versions?)\b")
        self.assertIn("docs/support.md", read(REPO / "SECURITY.md"))


class ThreatModelTests(unittest.TestCase):
    def test_each_residual_risk_cites_a_sentence_that_the_cited_page_holds(self):
        """Issue #477: a residual risk of the model must lead to the sentence or the test that establishes it."""
        rows = table(read(DOCS / "threat-model.md"), "Residual risks")[2:]
        self.assertGreaterEqual(len(rows), 10)
        for risk, evidence in rows:
            with self.subTest(risk=risk[:50]):
                target = LINK.search(evidence).group(1).split("#")[0]
                quoted = re.search(r'"([^"]+)"', evidence).group(1)
                self.assertIn(quoted, read((DOCS / target).resolve()))


if __name__ == "__main__":
    unittest.main()
