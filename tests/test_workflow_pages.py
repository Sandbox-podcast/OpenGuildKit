"""docs/workflow.md is the task path and an index; each part of it is a page of docs/workflow/, one sentence per line.

Issue #505: the page weighed 115 KB, with paragraphs up to 4,070 characters, so a search returned whole paragraphs and
an agent read the whole path to find one rule.
"""

import re
import subprocess
import unittest
from pathlib import Path

from tests.test_doc_links import anchors

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "docs" / "workflow.md"
FOLDER = REPO / "docs" / "workflow"
LINK = re.compile(r"\]\(([^)\s]+)\)")
PAGE_BUDGET = 40_000
LINE_BUDGET = 400
PARAGRAPH_BUDGET = 1_200
# Tracked Markdown files over the budget when it was set. The list only shrinks: a file that goes under the budget
# leaves it, and no file joins it.
OVER_BUDGET = {"CHANGELOG.md", "docs/catalog-format.md", "docs/testing.md", "integrations/README.md"}
# The headings of docs/workflow.md that a message, a page or the changelog cited before the split: each still lands
# on the index, which says where the section went.
OLD_ANCHORS = (
    "2-scope-the-task", "assumptions-not-confirmed", "how-boards-are-selected", "when-an-approval-no-longer-holds",
    "signed-approvals", "certificates-of-an-authority", "code-owners-of-the-touched-paths",
    "only-the-rules-that-concern-the-task", "project-checks", "delivered-diff-review",
    "evidence-changed-after-it-was-accepted", "dependencies-between-tasks", "short-lane", "requester-and-approver",
    "roles-by-board", "incident-response", "reuse-the-profile-in-another-repository",
    "when-two-copies-use-the-same-task-id", "from-a-file-to-its-decisions", "several-projects-at-once",
    "retrospective", "the-project", "every-month-in-ci",
)


def pages() -> list[Path]:
    return [INDEX, *sorted(FOLDER.glob("*.md"))]


def prose_lines(page: Path) -> list[str]:
    """The lines of a page outside its code blocks and its tables."""
    found, fence = [], False
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = not fence
        elif not fence and not line.startswith("|"):
            found.append(line)
    return found


def tracked_markdown() -> list[str]:
    listed = subprocess.run(["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
                            capture_output=True, text=True, check=True).stdout.split()
    return [name for name in listed if not name.startswith("web/data/") and (REPO / name).is_file()]


class WorkflowPagesTests(unittest.TestCase):
    def test_no_markdown_file_grows_over_the_budget_and_the_list_of_those_over_it_only_shrinks(self):
        """Issue #505: four documents were over 40 KB, docs/workflow.md at 115 KB, and nothing bounded a page."""
        # Bytes as committed: a Windows checkout with autocrlf adds a \r to each line.
        sizes = {name: len((REPO / name).read_bytes().replace(b"\r\n", b"\n")) for name in tracked_markdown()}
        over = {name for name, size in sizes.items() if size > PAGE_BUDGET}
        self.assertEqual(sorted(over - OVER_BUDGET), [])
        self.assertEqual(sorted(OVER_BUDGET - over), [], "remove from OVER_BUDGET a file now under the budget")
        self.assertLess(sizes["docs/workflow.md"], 30_000)

    def test_every_line_of_the_path_holds_one_sentence_or_less_than_400_characters(self):
        """Issue #505: 20 lines of docs/workflow.md were over 1,000 characters, the longest 4,070."""
        for page in pages():
            with self.subTest(page=page.name):
                self.assertEqual([line[:80] for line in prose_lines(page) if len(line) > LINE_BUDGET], [])

    def test_no_paragraph_of_the_index_is_over_1200_characters(self):
        blocks = "\n".join(prose_lines(INDEX)).split("\n\n")
        paragraphs = [block for block in blocks if not block.lstrip().startswith(("- ", "#"))]  # A list holds items.
        self.assertEqual([paragraph[:80] for paragraph in paragraphs if len(paragraph) > PARAGRAPH_BUDGET], [])

    def test_each_page_names_its_reader_and_the_index_links_every_page(self):
        index = INDEX.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(pages()), 15)
        for page in pages()[1:]:
            with self.subTest(page=page.name):
                lines = page.read_text(encoding="utf-8").splitlines()
                self.assertTrue(lines[0].startswith("# "))
                self.assertTrue(lines[2].startswith("For: "))
                self.assertIn("](../workflow.md)", page.read_text(encoding="utf-8"))
                self.assertIn(f"](workflow/{page.name})", index)

    def test_every_heading_cited_before_the_split_still_lands_on_the_index(self):
        self.assertEqual([anchor for anchor in OLD_ANCHORS if anchor not in anchors(INDEX)], [])

    def test_every_link_into_the_path_leads_to_a_page_and_a_heading(self):
        """Issue #505: the links of the pages that moved, and of every page that cites one, resolve after the split."""
        sources = [REPO / name for name in tracked_markdown() if name != "CHANGELOG.md"]
        for page in sources:
            text = page.read_text(encoding="utf-8")
            for target in LINK.findall(text):
                if re.match(r"[a-z]+:", target):
                    continue
                path, _, anchor = target.partition("#")
                destination = (page.parent / path).resolve() if path else page
                inside = destination == INDEX or destination.parent == FOLDER or page in pages()
                if not inside:
                    continue
                with self.subTest(page=page.relative_to(REPO).as_posix(), link=target):
                    self.assertTrue(destination.is_file(), path)
                    if anchor and destination.suffix == ".md":
                        self.assertIn(anchor, anchors(destination))


if __name__ == "__main__":
    unittest.main()
