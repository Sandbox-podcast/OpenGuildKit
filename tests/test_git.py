"""The one module that runs Git (issue #459): file names as they are on disk, and a machine without Git."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import git

NAMES = ["docs/résumé.md", "docs/a b.md", 'docs/say "hi".md']


@unittest.skipIf(shutil.which("git") is None, "needs git")
class GitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True, text=True).stdout

    def write(self, relative, text):
        (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
        (self.root / relative).write_text(text, encoding="utf-8")

    def base(self, names):
        for name in names:
            self.write(name, "v1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        return self.git("rev-parse", "HEAD").strip()

    def test_names_come_back_as_they_are_on_disk(self):
        """git diff and git ls-files quote an accented name ("docs/r\\303\\251sum\\303\\251.md") without -z."""
        commit = self.base(NAMES)
        for name in NAMES:
            self.write(name, "v2\n")
        self.write("new é.md", "new\n")
        self.assertEqual(sorted(git.names(self.root, "diff", "--name-only", commit, "--")), sorted(NAMES))
        self.assertEqual(git.names(self.root, "ls-files", "--others", "--exclude-standard"), ["new é.md"])

    def test_a_failure_or_a_machine_without_git_gives_none(self):
        self.assertIsNone(git.text(self.root, "rev-parse", "--verify", "no-such-ref"))
        self.assertIsNone(git.names(self.root, "diff", "--name-only", "no-such-ref", "--"))
        with patch.dict(os.environ, {"PATH": str(self.root)}):
            self.assertIsNone(git.run(self.root, "status"))
            self.assertIsNone(git.text(self.root, "status"))


if __name__ == "__main__":
    unittest.main()
