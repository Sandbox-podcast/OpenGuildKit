"""The personal data page names every field where the tool writes a person, and the examples follow its advice.

A team describes the tool's own processing from docs/personal-data.md. The fields are found in the code, not listed
here, so a field added later fails these tests until the page names it.
"""

import json
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from openguildkit.alerts import REGISTER_FILE
from openguildkit.decisions import DECISIONS_DIR, record_digest
from openguildkit.market import MARKET_DIR
from openguildkit.project import STATE_DIR
from openguildkit.project_instructions import PROJECT_IGNORE
from openguildkit.publishing import SHARES_DIR

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "personal-data.md"
SOURCE = REPO / "src" / "openguildkit"
WEB_SOURCE = REPO / "web" / "src"
# A string literal that names a field about a person: by and *_by, owner, signer, approver, recipient, reviewer.
PERSON_FIELD = re.compile(
    r"""["']((?:[a-z]+_)*(?:by|owners?|signers?|approvers?|recipients?|reviewers?)|delegations)["']""")
REMEMBERED = re.compile(r"""useRemembered\(['"]([\w-]+)['"]""")
# An option or a JSON field of the examples that names a person, with its value.
PERSON_OPTION = re.compile(r"""--(?:by|verified-by|allowed-by|approver|signer|owner)[ =]("[^"]*"|'[^']*'|[^\s`]+)""")
PERSON_JSON = re.compile(r'''"(?:by|owner|verified_by|provided_by|approvers|allowed_by)":\s*\[?\s*"([^"]*)"''')
DELEGATE = re.compile(r"""--delegate\s+(?:"[^"=]*=([^"]*)"|'[^'=]*=([^']*)'|[\w-]+=("[^"]*"|'[^']*'|\S+))""")
PLACEHOLDERS = {"NAME", "PRINCIPAL", "PERSON"}
# A terminal prompt that asks for a name, and a hint or placeholder of the page that does.
NAME_PROMPT = re.compile(r"""(?:input|_prompt_line)\(\s*f?["'][^"']*\b[Yy]our (?:full )?name\b""")
WEB_NAME = re.compile(r"""\b[Tt]on nom\b|avec son nom\b|placeholder=["'][A-Z][a-zé]+ [A-Z][a-z]+["']""")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def person_fields(texts: list[str]) -> set[str]:
    """The field names about a person that these source texts write or read."""
    return {match for text in texts for match in PERSON_FIELD.findall(text)}


def unnamed(fields: set[str], page: str) -> list[str]:
    """The fields that no code span of the page names, as a whole word."""
    spans = re.findall(r"`([^`\n]+)`", page)
    return sorted(field for field in fields
                  if not any(re.search(rf"(?<!\w){re.escape(field)}(?!\w)", span) for span in spans))


def example_pages() -> list[Path]:
    return [REPO / "README.md", REPO / "README.fr.md", *sorted((REPO / "docs").glob("*.md")),
            *sorted((REPO / "web" / "docs").glob("*.md")), *sorted((REPO / "examples").glob("**/README.md"))]


def full_names(text: str) -> list[str]:
    """The values given for a person that are a full name or an address rather than initials or a placeholder."""
    found = []
    for pattern in (PERSON_OPTION, PERSON_JSON, DELEGATE):
        for match in pattern.finditer(text):
            value = next(group for group in match.groups() if group is not None).strip("\"'")
            # A team handle starts with @ (@security); an address has one after its first character.
            if value not in PLACEHOLDERS and (" " in value or "@" in value[1:]):
                found.append(match.group(0))
    return found


class FieldInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = _read(PAGE)
        cls.fields = person_fields([_read(path) for path in sorted(SOURCE.rglob("*.py"))])

    def test_the_search_finds_the_fields_the_audit_named(self):
        expected = {"by", "owner", "signer", "approvers", "recipients", "allowed_by", "confirmed_by", "closed_by",
                    "provided_by", "verified_by", "revoked_by", "reviewer", "delegations"}
        self.assertLessEqual(expected, self.fields)

    def test_every_field_about_a_person_in_the_code_is_on_the_page(self):
        self.assertEqual(unnamed(self.fields, self.page), [],
                         "Add each field to docs/personal-data.md: where it is written, whether Git tracks it, why, "
                         "and how to remove it; or list it among the fields named like a person that hold none.")

    def test_a_new_field_fails_until_the_page_names_it(self):
        added = person_fields(['record = {"sponsored_by": by.strip(), "at": timestamp()}'])
        self.assertEqual(added, {"sponsored_by"})
        self.assertEqual(unnamed(self.fields | added, self.page), ["sponsored_by"])

    def test_every_name_the_page_remembers_in_the_browser_is_on_the_page(self):
        keys = {key for path in sorted(WEB_SOURCE.rglob("*.ts*")) for key in REMEMBERED.findall(_read(path))}
        self.assertIn("decider", keys)
        for key in sorted(keys):
            with self.subTest(key=key):
                self.assertIn(f"`ogk-ui:{key}`", self.page)


class FilesTests(unittest.TestCase):
    """The page sorts each file by whether Git tracks it, as the .gitignore that init writes decides."""

    def setUp(self):
        page = _read(PAGE)
        self.committed = page.split("### Files the team commits", 1)[1].split("\n### ", 1)[0]
        self.local = page.split("### Files that stay on one machine", 1)[1].split("\n### ", 1)[0]

    def test_each_state_file_is_in_the_section_git_decides(self):
        ignored = [entry for entry in PROJECT_IGNORE.splitlines() if entry.endswith("/")]
        committed = (f"{STATE_DIR}/project.json", f"{STATE_DIR}/{DECISIONS_DIR}/ID.json",
                     f"{STATE_DIR}/{REGISTER_FILE}", f"{STATE_DIR}/{MARKET_DIR}/ID.json")
        local = (f"{STATE_DIR}/tasks/ID.json", f"{STATE_DIR}/{SHARES_DIR}/shares.json")
        for path in committed:
            with self.subTest(path=path):
                self.assertIn(f"`{path}`", self.committed)
                self.assertFalse(any(path.startswith(f"{STATE_DIR}/{entry}") for entry in ignored))
        for path in local:
            with self.subTest(path=path):
                self.assertIn(f"`{path}`", self.local)
                self.assertTrue(any(path.startswith(f"{STATE_DIR}/{entry}") for entry in ignored))


class ProcedureTests(unittest.TestCase):
    def test_the_digest_command_of_the_page_gives_the_digest_the_guard_recomputes(self):
        block = next(block for block in re.findall(r"```bash\n(.*?)```", _read(PAGE), re.DOTALL)
                     if "record_sha256" in block)
        words = shlex.split(block.strip())
        self.assertEqual((words[0], words[-1]), ("python3", f"{STATE_DIR}/{DECISIONS_DIR}/ID.json"))
        record = {"task": "t1", "decision": {"by": "CM", "seal": "0" * 64}, "brief": "Statut des demandes",
                  "result": {"closing": {"by": "AM", "open_points": []}}, "record_sha256": "stale"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t1.json"
            path.write_text(json.dumps(record), encoding="utf-8")
            subprocess.run([sys.executable, *words[1:-1], str(path)], check=True, capture_output=True)
            written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({key: value for key, value in written.items() if key != "record_sha256"},
                         {key: value for key, value in record.items() if key != "record_sha256"})
        self.assertEqual(written["record_sha256"], record_digest(written))


class ExampleTests(unittest.TestCase):
    """The documentation gives a person's initials, as the page recommends, never a full name or an address."""

    def test_the_check_tells_initials_from_full_names(self):
        self.assertEqual(full_names('task decide x --approve --by CM --reason "Agreed"'), [])
        self.assertEqual(full_names("task decide x --approve --by INITIALS --reason WHY"), [])
        self.assertEqual(len(full_names('task decide x --approve --by "Camille Martin" --reason R')), 1)
        self.assertEqual(len(full_names("--signer camille@example.org")), 1)
        self.assertEqual(full_names('"owner": "@security"'), [])
        self.assertEqual(len(full_names('"declined": [{"id": "x", "by": "Camille Martin"}]')), 1)
        self.assertEqual(len(full_names('--delegate security="Alex Moreau"')), 1)

    def test_no_example_names_a_person_in_full(self):
        for page in example_pages():
            with self.subTest(page=page.relative_to(REPO).as_posix()):
                self.assertEqual(full_names(_read(page)), [])

    def test_prompts_and_examples_ask_for_initials_not_a_name(self):
        """The terminal prompts, the page's hints and placeholders, and the example files follow the same advice."""
        scripts = [*sorted(SOURCE.rglob("*.py")), *sorted((REPO / "examples").rglob("*.py"))]
        for path in scripts:
            with self.subTest(path=path.relative_to(REPO).as_posix()):
                self.assertEqual(NAME_PROMPT.findall(_read(path)), [])
        for path in sorted(WEB_SOURCE.rglob("*.ts*")):
            with self.subTest(path=path.relative_to(REPO).as_posix()):
                self.assertEqual(WEB_NAME.findall(_read(path)), [])
        for path in sorted((REPO / "examples").rglob("*.json")):
            with self.subTest(path=path.relative_to(REPO).as_posix()):
                self.assertEqual(full_names(_read(path)), [])
        campaign = json.loads(_read(REPO / "examples" / "field-tests" / "campaign.json"))
        self.assertNotIn(" ", campaign["person"])

    def test_both_readmes_and_the_security_policy_link_to_the_page(self):
        for relative in ("README.md", "README.fr.md"):
            section = _read(REPO / relative).split("\n## Documentation\n", 1)[1]
            with self.subTest(page=relative):
                self.assertIn("(docs/personal-data.md)", section)
        self.assertIn("(docs/personal-data.md)", _read(REPO / "SECURITY.md"))
        self.assertIn("(personal-data.md", _read(REPO / "docs" / "glossary.md"))


if __name__ == "__main__":
    unittest.main()
