"""Release consistency: one version everywhere, and release notes that compare from the last stable release."""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "release-notes.sh"
VERSION = re.compile(r"\bv(\d+\.\d+\.\d+)\b|openguildkit-(\d+\.\d+\.\d+)")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def announced_versions() -> dict[str, set[str]]:
    """Every version each file announces, action tags aside; a release updates them together (GOVERNANCE.md)."""
    found = {
        "pyproject.toml": {tomllib.loads(_read("pyproject.toml"))["project"]["version"]},
        "integrations/ci/package.json": {json.loads(_read("integrations/ci/package.json"))["version"]},
    }
    for relative in ("docs/install.md", "integrations/ci/README.md", "integrations/github/openguildkit-guard.yml"):
        text = "\n".join(line for line in _read(relative).splitlines() if "uses:" not in line)
        found[relative] = {a or b for a, b in VERSION.findall(text)}
    return found


class VersionTest(unittest.TestCase):
    def test_every_file_announces_the_same_version(self):
        found = announced_versions()
        for relative, versions in found.items():
            self.assertTrue(versions, f"{relative} announces no version")
        self.assertEqual(len(set().union(*found.values())), 1, f"align the versions: {found}")


class GovernanceFilesTest(unittest.TestCase):
    def test_codeowners_names_the_owners_of_every_path(self):
        rules = [line.split() for line in _read(".github/CODEOWNERS").splitlines()
                 if line.strip() and not line.startswith("#")]
        catch_all = [rule for rule in rules if rule[0] == "*"]
        self.assertEqual(len(catch_all), 1)
        self.assertTrue(catch_all[0][1:] and all(re.fullmatch(r"@[\w-]+(/[\w-]+)?", owner) for owner in catch_all[0][1:]))
        self.assertIn(".github/CODEOWNERS", _read("GOVERNANCE.md"))

    def test_contributing_states_the_licence_of_catalog_content(self):
        self.assertTrue(_read("LICENSE").startswith("MIT License"))
        paragraph = next(block for block in _read("CONTRIBUTING.md").split("\n\n") if "licen" in block.lower())
        for fact in ("catalog", "MIT License", "LICENSE"):
            self.assertIn(fact, paragraph)


STUB_GH = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$GH_STUB_LOG"
case "$*" in
  *generate-notes*) printf 'Notes of the release\\n\\n**Full Changelog**: old\\n' ;;
  *"releases?per_page=100"*) cat "$GH_STUB_RELEASES" ;;
  *) exit 1 ;;
esac
"""


def _release(tag: str, published_at: str, *, draft=False, prerelease=False) -> dict:
    return {"id": len(tag), "tag_name": tag, "draft": draft, "prerelease": prerelease, "published_at": published_at}


@unittest.skipIf(sys.platform == "win32", "the script runs on the Linux release runner; Windows has no bash stub on PATH")
@unittest.skipUnless(shutil.which("bash") and shutil.which("jq"), "the release notes script needs bash and jq")
class ReleaseNotesTest(unittest.TestCase):
    def draft(self, releases: list[dict]) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            stub = folder / "gh"
            stub.write_text(STUB_GH, encoding="utf-8")
            stub.chmod(0o755)
            (folder / "releases.json").write_text(json.dumps([releases]), encoding="utf-8")
            env = {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}", "DRY_RUN": "1",
                   "GH_REPO": "example/openguildkit", "GH_TOKEN": "unused",
                   "GH_STUB_LOG": str(folder / "log.txt"), "GH_STUB_RELEASES": str(folder / "releases.json")}
            done = subprocess.run(["bash", str(SCRIPT), "draft", "a" * 40], env=env, capture_output=True,
                                  text=True, encoding="utf-8", check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout, (folder / "log.txt").read_text(encoding="utf-8")

    def test_draft_compares_from_the_last_stable_release_despite_a_newer_prerelease(self):
        body, log = self.draft([
            _release("v0.16.0", "2026-10-01T00:00:00Z"),
            _release("v0.16.1", "2026-11-01T00:00:00Z"),
            _release("v0.17.0", "2026-11-10T00:00:00Z", prerelease=True),
            _release("openguildkit-next", None, draft=True),
        ])
        self.assertIn("previous_tag_name=v0.16.1", log)
        self.assertIn(f"**Full Changelog**: https://github.com/example/openguildkit/compare/v0.16.1...{'a' * 40}", body)
        self.assertEqual(body.count("**Full Changelog**"), 1)

    def test_draft_without_a_stable_release_links_the_commits(self):
        body, log = self.draft([_release("v0.17.0", "2026-11-10T00:00:00Z", prerelease=True)])
        self.assertNotIn("previous_tag_name", log)
        self.assertIn(f"**Full Changelog**: https://github.com/example/openguildkit/commits/{'a' * 40}", body)


if __name__ == "__main__":
    unittest.main()
