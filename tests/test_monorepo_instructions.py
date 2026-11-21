"""Instructions of a monorepo stay scoped to their components, and a team's AGENTS.md is merged safely."""

import contextlib
import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.catalog import load_catalog
from openguildkit.cli import main
from openguildkit.project import BEGIN, rule_plan, validate_profile
from openguildkit.storage import write_json

LANGUAGE_PACKS = {"Python": "services-api", "React": "apps-web", "TypeScript": "apps-web"}


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class ProjectTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()


class MonorepoScopeTests(ProjectTestCase):
    def init_audit_monorepo(self):
        """The monorepo of the audit, initialised with the components that detection proposes."""
        write(self.root, "apps/web/package.json", {"dependencies": {"next": "14.2.3", "react": "18.3.1"},
                                                   "devDependencies": {"@playwright/test": "1.44.0", "typescript": "5.4.0"}})
        write(self.root, "apps/web/tsconfig.json", "{}")
        write(self.root, "services/api/pyproject.toml",
              '[project]\nname = "api"\nrequires-python = ">=3.12"\n'
              'dependencies = ["fastapi>=0.111", "sqlalchemy>=2.0", "psycopg[binary]>=3.1"]\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions")[0])}
        components = questions["components"]["default"]
        self.assertEqual([component["id"] for component in components], ["apps-web", "services-api"])
        write_json(self.root / "answers.json", {"name": "mono", "components": components, "roles": ["engineering"]})
        self.run_cli("init", "--answers", self.root / "answers.json")

    def pack_section(self, agents: str, title: str) -> str:
        match = re.search(rf"^#### {title} \(`[^`]+`\)\n(.*?)(?=^#### |\Z)", agents, re.S | re.M)
        self.assertIsNotNone(match, title)
        return match.group(1)

    def test_language_packs_apply_only_to_their_components(self):
        self.init_audit_monorepo()
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        for title, component in LANGUAGE_PACKS.items():
            section = self.pack_section(agents, title)
            scope = re.search(r"^Applies to (.*)\.$", section, re.M)
            self.assertIsNotNone(scope, f"{title} applies to the whole repository")
            self.assertEqual(re.findall(r"`([a-z-]+)`", scope.group(1)), [component])
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        catalog = load_catalog()
        plan = {pack["id"]: pack for pack in rule_plan(validate_profile(profile, catalog), catalog)["packs"]}
        self.assertEqual(plan["python"]["scope"], ["services-api"])
        self.assertEqual(plan["react"]["scope"], ["apps-web"])
        self.assertEqual(plan["typescript"]["scope"], ["apps-web"])
        self.assertFalse({"python", "react", "typescript"} & set(profile["packs"]))
        self.run_cli("check")

    def test_a_single_component_project_keeps_its_language_packs(self):
        write_json(self.root / "answers.json", {"name": "api", "stack": ["Python 3.12"]})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertIn("python", profile["packs"])


class TeamInstructionTests(ProjectTestCase):
    def setUp(self):
        super().setUp()
        write_json(self.root / "answers.json", {"name": "Portal", "stack": ["Python"]})
        self.agents = self.root / "AGENTS.md"

    def test_an_unclosed_code_block_is_refused_with_its_line(self):
        self.agents.write_text("# Rules\n\nRun the tests:\n```sh\nnpm test\n", encoding="utf-8")
        _, error = self.run_cli("init", "--answers", self.root / "answers.json", code=1)
        self.assertIn("AGENTS.md ends inside an unclosed code block at line 4", error)
        self.assertEqual(self.agents.read_text(encoding="utf-8"), "# Rules\n\nRun the tests:\n```sh\nnpm test\n")

    def test_two_syncs_keep_one_block_when_a_code_block_is_left_open(self):
        self.agents.write_text("# Rules\n", encoding="utf-8")
        self.run_cli("init", "--answers", self.root / "answers.json")
        text = self.agents.read_text(encoding="utf-8")
        self.agents.write_text(text.replace("# Rules\n", "# Rules\n```sh\nnpm test\n", 1), encoding="utf-8")
        for _ in range(2):
            _, error = self.run_cli("sync", code=1)
            self.assertIn("unclosed code block at line 2", error)
        self.assertEqual(self.agents.read_text(encoding="utf-8").count(BEGIN), 1)
        self.agents.write_text(text, encoding="utf-8")
        self.run_cli("sync")
        self.run_cli("sync")
        self.assertEqual(self.agents.read_text(encoding="utf-8").count(BEGIN), 1)

    def test_a_file_that_is_not_utf8_is_named(self):
        self.agents.write_bytes("# Règles\n".encode("latin-1"))
        _, error = self.run_cli("init", "--answers", self.root / "answers.json", code=1)
        self.assertIn("AGENTS.md is not UTF-8", error)
        self.assertIn("convert it", error)
        self.assertNotIn("codec", error)


if __name__ == "__main__":
    unittest.main()
