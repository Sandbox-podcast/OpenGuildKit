"""The one module that runs Git (issue #459): file names as they are on disk, and a machine without Git."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import git
from openguildkit.catalog import load_catalog
from openguildkit.project import resolved_profile, validate_profile
from openguildkit.relevance import changed_files, pack_relevance

# Windows refuses a quote in a file name; Git quotes such a name elsewhere, so it is tested where it can exist.
NAMES = ["docs/résumé.md", "docs/a b.md", *([] if os.name == "nt" else ['docs/say "hi".md'])]


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
        """Issue #458: git diff and git ls-files quoted an accented name ("docs/r\\303\\251sum\\303\\251.md")."""
        commit = self.base(NAMES)
        for name in NAMES:
            self.write(name, "v2\n")
        self.write("new é.md", "new\n")
        self.assertEqual(sorted(git.names(self.root, "diff", "--name-only", commit, "--")), sorted(NAMES))
        self.assertEqual(git.names(self.root, "ls-files", "--others", "--exclude-standard"), ["new é.md"])

    def test_a_quoted_name_from_an_earlier_record_is_read_as_it_is_on_disk(self):
        """Issue #458: a record exported before the fix holds the quoted form."""
        self.assertEqual(git.unquote('"docs/r\\303\\251sum\\303\\251.md"'), "docs/résumé.md")
        self.assertEqual(git.unquote('"docs/say \\"hi\\".md"'), 'docs/say "hi".md')
        self.assertEqual(git.unquote('"tab\\there"'), "tab\there")
        for name in ("docs/a b.md", '"quoted".md', '"plain"'):
            self.assertEqual(git.unquote(name), name)

    def test_a_failure_or_a_machine_without_git_gives_none(self):
        self.assertIsNone(git.text(self.root, "rev-parse", "--verify", "no-such-ref"))
        self.assertIsNone(git.names(self.root, "diff", "--name-only", "no-such-ref", "--"))
        with patch.dict(os.environ, {"PATH": str(self.root)}):
            self.assertIsNone(git.run(self.root, "status"))
            self.assertIsNone(git.text(self.root, "status"))

    def test_a_pack_scoped_to_a_component_is_asked_when_its_only_changed_file_has_an_accent(self):
        """Issue #458: changed_files quoted apps/web/Tâche.tsx, so the react pack of component web was not asked."""
        catalog = load_catalog()
        profile = validate_profile({
            "name": "Shop", "stack": ["Python"], "packs": ["python"],
            "components": [{"id": "web", "path": "apps/web", "stack": ["React 18"]},
                           {"id": "api", "path": "apps/api", "stack": ["Python"]}],
            "patterns": [{"id": "react-web", "components": ["web"]}]}, catalog)
        commit = self.base(["apps/web/Tâche.tsx"])
        self.write("apps/web/Tâche.tsx", "v2\n")
        self.write("apps/web/new file.tsx", "new\n")
        answers = {"kind": "bug", "surface": ["service"], "data": "internal", "research": "local",
                   "concerns": ["none"], "outcome": "x"}
        packs = [catalog["packs"][pack] for pack in resolved_profile(profile, catalog)["packs"]]
        task = {"id": "t", "brief": "Fix.", "answers": answers, "decision": {"base_revision": {"commit": commit}},
                "consultation": {"boards": ["engineering"], "scope": {"answers": answers, "checks": [], "packs": packs}}}
        changed = changed_files(self.root, task)
        self.assertEqual(changed, ["apps/web/Tâche.tsx", "apps/web/new file.tsx"])
        self.assertTrue(pack_relevance(task, profile, catalog, changed)["react"]["concerned"])


if __name__ == "__main__":
    unittest.main()
