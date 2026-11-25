"""The test suite does not sign commits with the contributor's Git configuration (issue #342)."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import isolate_git


class GitIsolationTests(unittest.TestCase):
    def test_a_commit_passes_when_the_global_config_would_sign(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        signing = root / "signing.gitconfig"
        signing.write_text("[commit]\n\tgpgsign = true\n", encoding="utf-8")
        os.environ["GIT_CONFIG_GLOBAL"] = str(signing)
        isolate_git()
        self.assertEqual(os.environ["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(os.environ["GIT_CONFIG_NOSYSTEM"], "1")
        repo = root / "repo"
        repo.mkdir()
        environment = os.environ.copy()
        subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=repo, check=True, env=environment)
        (repo / "note.txt").write_text("ok\n", encoding="utf-8")
        subprocess.run(["git", "add", "note.txt"], cwd=repo, check=True, env=environment)
        subprocess.run(["git", "commit", "--quiet", "-m", "note"], cwd=repo, check=True, env=environment)
