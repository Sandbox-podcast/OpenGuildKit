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

from tests.test_workflows import TEMPLATES, USES, WORKFLOWS, parse, run_text, steps

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


class CiWorkflowTest(unittest.TestCase):
    """The checks every pull request must pass: bounded in time, run on the supported Pythons, all required."""

    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]

    def test_every_job_stops_before_the_runner_default_of_six_hours(self):
        expected = {"test": "30", "package": "20", "web-e2e": "20"}
        for name, job in self.jobs.items():
            self.assertEqual(job.get("timeout-minutes"), expected.get(name, "15"), name)

    def test_the_matrix_runs_from_the_floor_to_the_maintainers_python(self):
        versions = self.jobs["test"]["strategy"]["matrix"]["python"]
        floor = tomllib.loads(_read("pyproject.toml"))["project"]["requires-python"].removeprefix(">=")
        self.assertEqual(versions[0], floor)
        self.assertIn("3.15", versions)

    def test_contribution_checks_require_every_other_job(self):
        gate = self.jobs["contribution-checks"]
        self.assertEqual(set(gate["needs"]), set(self.jobs) - {"contribution-checks"})
        script = run_text(gate)
        for job in gate["needs"]:
            variable = next(name for name, value in gate["steps"][0]["env"].items() if f"needs.{job}.result" in value)
            self.assertIn(f'test "${variable}" = success', script)
        self.assertNotIn("once it has passed on main", _read(".github/workflows/ci.yml"))

    def test_no_checkout_leaves_the_token_in_the_git_config(self):
        for path in WORKFLOWS:
            for name, job in parse(path)["jobs"].items():
                for step in steps(job):
                    if str(step.get("uses", "")).startswith("actions/checkout@"):
                        self.assertEqual((step.get("with") or {}).get("persist-credentials"), "false",
                                         f"{path.name}: {name}")

    def test_npm_installs_run_no_dependency_scripts(self):
        for path in [*WORKFLOWS, *TEMPLATES]:
            for line in path.read_text(encoding="utf-8").splitlines():
                if re.search(r"\bnpm (ci|install)\b", line):
                    self.assertIn("--ignore-scripts", line, f"{path.name}: {line.strip()}")

    def test_each_action_has_one_pinned_version(self):
        pins: dict[str, set[str]] = {}
        for path in WORKFLOWS:
            for line in path.read_text(encoding="utf-8").splitlines():
                if (match := USES.match(line)) and "@" in match.group(1):
                    action, ref = match.group(1).split("@")
                    pins.setdefault(action, set()).add(ref)
        self.assertEqual({action: refs for action, refs in pins.items() if len(refs) > 1}, {})
        uploads = set()
        for path in [*WORKFLOWS, *TEMPLATES]:
            uploads |= set(re.findall(r"actions/upload-artifact@([0-9a-f]{40})", path.read_text(encoding="utf-8")))
        self.assertEqual(len(uploads), 1, uploads)


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
