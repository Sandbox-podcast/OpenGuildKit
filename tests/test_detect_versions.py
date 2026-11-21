"""Detection keeps only versions it can read, and the person can correct them during init."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import _prompt_components, main
from openguildkit.detect import detect_stack
from openguildkit.storage import write_json


def write(root: Path, relative: str, content) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


class DetectedVersionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def stacks(self):
        return {component["path"]: component["stack"] for component in detect_stack(self.root)["components"]}

    def test_a_client_library_version_is_not_the_database_version(self):
        write(self.root, "web/package.json", {"dependencies": {"pg": "^8.11.3"}})
        write(self.root, "api/pyproject.toml", '[project]\nname = "api"\ndependencies = ["psycopg[binary]>=3.1"]\n')
        write(self.root, "worker/requirements.txt", "asyncpg==0.29.0\n")
        stacks = self.stacks()
        self.assertEqual(stacks["web"], ["PostgreSQL"])
        self.assertIn("PostgreSQL", stacks["api"])
        self.assertIn("PostgreSQL", stacks["worker"])
        self.assertFalse([item for stack in stacks.values() for item in stack if item.startswith("PostgreSQL ")])

    def test_the_profile_and_instructions_carry_no_inferred_version(self):
        write(self.root, "api/pyproject.toml",
              '[project]\nname = "api"\nrequires-python = ">=3.12"\ndependencies = ["fastapi>=0.115", "psycopg[binary]>=3.2"]\n')
        questions = {item["id"]: item for item in json.loads(self.run_cli("init", "--questions"))}
        write_json(self.root / "answers.json", {"name": "Acme", "components": questions["components"]["default"]})
        self.run_cli("init", "--answers", self.root / "answers.json")
        profile = json.loads((self.root / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertIn("PostgreSQL", profile["stack"])
        self.assertNotIn("PostgreSQL 3.2", profile["stack"])
        agents = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("PostgreSQL 3.2", agents)
        self.assertIn("PostgreSQL", agents)

    def test_a_declared_database_version_wins_over_a_client_library(self):
        write(self.root, "pyproject.toml", '[project]\nname = "api"\ndependencies = ["psycopg>=3.1"]\n')
        write(self.root, "compose.yaml", "services:\n  db:\n    image: postgres:16-alpine\n")
        self.assertIn("PostgreSQL 16", self.stacks()["."])

    def test_official_image_names_are_recognised(self):
        write(self.root, "full/compose.yaml", "services:\n  db:\n    image: docker.io/library/postgres:16\n")
        write(self.root, "bare/compose.yaml", "services:\n  db:\n    image: postgres\n")
        write(self.root, "quoted/Dockerfile", "FROM postgres AS base\n")
        stacks = self.stacks()
        self.assertEqual(stacks["full"], ["PostgreSQL 16"])
        self.assertEqual(stacks["bare"], ["PostgreSQL"])
        self.assertEqual(stacks["quoted"], ["PostgreSQL"])

    def run_cli(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, 0, stderr.getvalue())
        return stdout.getvalue()


class ComponentPromptTests(unittest.TestCase):
    QUESTION = {
        "id": "components",
        "prompt": "Which components does the repository contain?",
        "default": [
            {"id": "apps-web", "path": "apps/web", "stack": ["Next.js 14.2.3", "React 18.3.1"]},
            {"id": "services-api", "path": "services/api", "stack": ["FastAPI 0.111", "PostgreSQL 3.1"]},
        ],
    }

    def prompt(self, *answers):
        with patch("builtins.input", side_effect=list(answers)), contextlib.redirect_stderr(io.StringIO()):
            return _prompt_components(self.QUESTION)

    def test_a_version_can_be_corrected_without_dropping_the_components(self):
        components = self.prompt("e", "", "FastAPI 0.111, PostgreSQL 16")
        self.assertEqual(components[0], self.QUESTION["default"][0])
        self.assertEqual(components[1], {"id": "services-api", "path": "services/api",
                                         "stack": ["FastAPI 0.111", "PostgreSQL 16"]})
        self.assertEqual(self.QUESTION["default"][1]["stack"], ["FastAPI 0.111", "PostgreSQL 3.1"])

    def test_keep_and_refuse_still_work(self):
        self.assertEqual(self.prompt(""), self.QUESTION["default"])
        self.assertEqual(self.prompt("n"), [])


if __name__ == "__main__":
    unittest.main()
