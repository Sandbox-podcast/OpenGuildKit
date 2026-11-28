"""Delivery: one version everywhere, a wheel built and checked as CI proves it, release notes from the last stable
release, required and bounded CI jobs, and the entry documents (governance, security, French README) kept true."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
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

from openguildkit.cli import command_parser
from tests.test_workflows import TEMPLATES, USES, WORKFLOWS, parse, run_text, steps

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".github" / "scripts" / "release-notes.sh"
CHECK_INSTALLED = ROOT / ".github" / "scripts" / "check-installed-cli.py"
VERSION = re.compile(r"\bv(\d+\.\d+\.\d+)\b|openguildkit-(\d+\.\d+\.\d+)")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def release_files() -> list[str]:
    """The files that step 1 of GOVERNANCE.md#releases names: a release sets its version in each of them."""
    section = _read("GOVERNANCE.md").split("## Releases", 1)[1].split("\n## ", 1)[0]
    step = next(line for line in section.splitlines() if line.startswith("1. "))
    return re.findall(r"`([\w./-]+\.(?:toml|json|md|yml))`", step)


def project_version() -> str:
    return tomllib.loads(_read("pyproject.toml"))["project"]["version"]


def release_version() -> str:
    match = re.search(r"^## (\d+\.\d+\.\d+)\s*$", _read("CHANGELOG.md"), re.MULTILINE)
    return match.group(1)


def announced_versions() -> dict[str, set[str]]:
    """Every version each release file announces, action tags aside."""
    found = {}
    for relative in release_files():
        if relative == "pyproject.toml":
            found[relative] = {project_version()}
        elif relative.endswith("package.json"):
            found[relative] = {json.loads(_read(relative))["version"]}
        elif relative == "CHANGELOG.md":
            found[relative] = set(re.findall(r"^## (\d+\.\d+\.\d+)\b", _read(relative), re.MULTILINE)[:1])
        else:
            text = "\n".join(line for line in _read(relative).splitlines() if "uses:" not in line)
            found[relative] = {a or b for a, b in VERSION.findall(text)}
    return found


class VersionTest(unittest.TestCase):
    def test_every_file_announces_the_same_version(self):
        found = announced_versions()
        for relative, versions in found.items():
            self.assertTrue(versions, f"{relative} announces no version")
        python_version = found.pop("pyproject.toml").pop()
        node_version = found.pop("integrations/ci/package.json").pop()
        self.assertEqual(set().union(*found.values()), {release_version()}, f"align the published versions: {found}")
        dev = re.fullmatch(r"(\d+\.\d+\.\d+)\.dev(\d+)", python_version)
        if dev:
            self.assertEqual(node_version, f"{dev[1]}-dev.{dev[2]}")
            self.assertGreater(tuple(map(int, dev[1].split("."))), tuple(map(int, release_version().split("."))))
        else:
            self.assertEqual(python_version, release_version())
            self.assertEqual(node_version, python_version)

    def test_a_published_version_is_not_reused_on_another_commit(self):
        if not (ROOT / ".git").exists():
            self.skipTest("Git checkout required")
        tag = f"refs/tags/v{project_version()}"
        exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", tag], cwd=ROOT)
        if exists.returncode == 1:
            return
        exists.check_returncode()
        commits = subprocess.check_output(["git", "rev-parse", "HEAD", f"{tag}^{{commit}}"], cwd=ROOT, text=True)
        head, published = commits.splitlines()
        self.assertEqual(head, published, f"{tag} already names a different commit")

    def test_every_top_level_command_has_a_documented_invocation(self):
        docs = _read("README.md") + "\n" + _read("CHANGELOG.md")
        commands = next(action.choices for action in command_parser()._actions
                        if isinstance(action, argparse._SubParsersAction))
        for command in commands:
            with self.subTest(command=command):
                self.assertRegex(docs, rf"openguildkit (?:--project [^ ]+ )?{re.escape(command)}\b")

    def test_the_release_steps_name_every_versioned_file(self):
        named = set(release_files())
        for required in ("pyproject.toml", "integrations/ci/package.json", "docs/install.md",
                         "integrations/ci/README.md", "CHANGELOG.md"):
            self.assertIn(required, named)
        for template in sorted((ROOT / "integrations" / "github").glob("*.yml")):
            self.assertIn(template.relative_to(ROOT).as_posix(), named)

    def test_templates_install_the_release_of_this_version(self):
        version = release_version()
        for template in sorted((ROOT / "integrations" / "github").glob("*.yml")):
            with self.subTest(template=template.name):
                text = template.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"@main\b|git\+https")
                install = next(step for job in parse(template)["jobs"].values() for step in steps(job)
                               if step.get("name") == "Install OpenGuildKit")
                self.assertEqual(install["env"]["OPENGUILDKIT_TAG"], f"v{version}")
                self.assertEqual(install["env"]["OPENGUILDKIT_WHEEL"], f"openguildkit-{version}-py3-none-any.whl")
                self.assertIn("sha256sum --strict -c", install["run"])


class BlameIgnoreTest(unittest.TestCase):
    def test_each_line_of_the_blame_ignore_file_is_a_comment_or_a_full_commit_hash(self):
        """GitHub skips the commits of .git-blame-ignore-revs in blame; a short or mistyped hash would be ignored."""
        lines = (ROOT / ".git-blame-ignore-revs").read_text(encoding="utf-8").splitlines()
        hashes = [line for line in lines if line.strip() and not line.startswith("#")]
        self.assertTrue(hashes)
        for line in hashes:
            with self.subTest(line=line):
                self.assertRegex(line, r"^[0-9a-f]{40}$")


class ChangelogTest(unittest.TestCase):
    def test_the_next_version_lists_the_changes_users_see_since_the_last_release(self):
        text = _read("CHANGELOG.md")
        first = re.search(r"^## (\d+\.\d+\.\d+)\b.*$", text, re.MULTILINE)
        self.assertEqual(first.group(1), release_version())
        section = text[first.end():].split("\n## ", 1)[0]
        self.assertIn("0.16.1", section)
        for change in ("done-with-reservations", "openguildkit profile", "task pass", "task export", "openguildkit ui",
                       "openguildkit tools", "mock", "openguildkit alerts", "openguildkit market",
                       "openguildkit storybook", "openguildkit docs export", "relevan"):
            self.assertIn(change, section)


ENTRY_LIMIT = 400
SHAPE_BASE = ROOT / "docs" / "agents" / "changelog-shape-base.json"


def unreleased_entries() -> list[str]:
    """The entries under `## Unreleased`: a line that starts with "- ", and the lines that follow it up to a blank one."""
    section = re.search(r"^## Unreleased\s*$(.*?)(?=^## |\Z)", _read("CHANGELOG.md"), re.MULTILINE | re.DOTALL).group(1)
    return ["\n".join(block) for block in (part.split("\n") for part in re.split(r"\n(?=- )", section.strip()))]


def entry_problems(entry: str) -> list[str]:
    """What keeps an entry from being searchable by issue: it spans lines, passes 400 characters or has no final (#N)."""
    found = []
    if "\n" in entry:
        found.append("spans several lines")
    if len(entry) > ENTRY_LIMIT:
        found.append(f"is {len(entry)} characters long")
    if not re.search(r"\(#\d+\)$", entry):
        found.append("does not end with its issue (#N)")
    return found


def entry_key(entry: str) -> str:
    return hashlib.sha256(entry.strip().encode("utf-8")).hexdigest()[:12]


class ChangelogShapeTest(unittest.TestCase):
    """changelog-entry-shape: one line of 400 characters at most that ends with its issue. The entries of
    `## Unreleased` that predate the rule are listed in docs/agents/changelog-shape-base.json, each with the first 12
    characters of the SHA-256 of its line. The list can only shrink: shorten an entry and delete its line, the test
    fails on an entry that complies and is still listed, and on any entry that breaks the shape and is not."""

    def test_an_entry_is_one_line_of_400_characters_that_ends_with_its_issue(self):
        self.assertEqual(entry_problems("- `task list` shows the period (#380)"), [])
        self.assertEqual(entry_problems("- " + "x" * (ENTRY_LIMIT - 2 - len(" (#7)")) + " (#7)"), [])
        self.assertEqual(entry_problems("- " + "x" * (ENTRY_LIMIT - 1 - len(" (#7)")) + " (#7)")[0][:6], "is 401")
        self.assertEqual(entry_problems("- Shows the period"), ["does not end with its issue (#N)"])
        self.assertEqual(entry_problems("- Shows the period (#7), see #8"), ["does not end with its issue (#N)"])
        self.assertEqual(entry_problems("- Shows it\n  and more (#7)"), ["spans several lines"])
        self.assertTrue(unreleased_entries())

    def test_unreleased_has_no_entry_that_breaks_the_shape_outside_the_base(self):
        base = json.loads(SHAPE_BASE.read_text(encoding="utf-8"))
        listed = [item["sha256"] for item in base]
        self.assertEqual(listed, sorted(listed))
        breaking = {entry_key(entry): entry for entry in unreleased_entries() if entry_problems(entry)}
        new = [f"{entry[:70]}... {' and '.join(entry_problems(entry))}" for key, entry in breaking.items() if key not in listed]
        self.assertEqual(new, [], "Shorten the entry to one line of 400 characters that ends with (#N).")
        stale = [item["start"] for item in base if item["sha256"] not in breaking]
        self.assertEqual(stale, [], "These entries were fixed or removed: delete their line from the base.")


class PackageMetadataTest(unittest.TestCase):
    def setUp(self):
        self.project = tomllib.loads(_read("pyproject.toml"))["project"]

    def test_declares_the_supported_pythons_the_licence_the_authors_and_the_documentation(self):
        tested = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["test"]["strategy"]["matrix"]["python"]
        declared = [c.rsplit(" :: ", 1)[1] for c in self.project["classifiers"]
                    if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)]
        self.assertLessEqual(set(tested), set(declared))
        self.assertEqual(self.project["requires-python"], f">={tested[0]}")
        self.assertEqual(self.project["license"], "MIT")
        self.assertEqual(self.project["license-files"], ["LICENSE"])
        self.assertTrue(self.project["authors"] and all(author.get("name") for author in self.project["authors"]))
        for name in ("Documentation", "Changelog", "Repository", "Issues"):
            self.assertRegex(self.project["urls"][name], r"^https://github\.com/Sandbox-podcast/OpenGuildKit")

    def test_the_package_readme_has_only_absolute_links(self):
        readme = _read(self.project["readme"])
        targets = re.findall(r"\]\(([^)\s]+)\)", readme) + re.findall(r'(?:src|href)="([^"]+)"', readme)
        self.assertTrue(targets)
        self.assertEqual([target for target in targets if not target.startswith("https://")], [])

    def test_no_page_installs_openguildkit_from_pypi(self):
        pages = []
        for folder, folders, files in os.walk(ROOT):
            folders[:] = [name for name in folders if name not in {".git", "node_modules", "dist", "web_dist"}]
            pages += [Path(folder) / name for name in files if name.endswith(".md")]
        self.assertGreater(len(pages), 20)
        for page in pages:
            self.assertFalse("pip install openguildkit" in page.read_text(encoding="utf-8"), page)


class InstallGuideTest(unittest.TestCase):
    def test_a_team_installs_the_release_wheel_with_pipx_or_uv(self):
        guide, version = _read("docs/install.md"), release_version()
        self.assertIn(f"pipx install ./openguildkit-{version}-py3-none-any.whl", guide)
        self.assertIn(f"uv tool install ./openguildkit-{version}-py3-none-any.whl", guide)
        self.assertIn("not published on PyPI", guide)
        readme = _read("README.md")
        paragraph = next(block for block in readme.split("\n\n") if "pipx install" in block)
        self.assertIn("docs/install.md", paragraph)
        self.assertIn("uv tool install", paragraph)

    def test_the_guides_describe_the_web_build_of_the_release(self):
        section = _read("docs/install.md").split("## How the release assets are built", 1)[1].split("\n## ", 1)[0]
        governance = _read("GOVERNANCE.md").split("## Releases", 1)[1].split("\n## ", 1)[0]
        for text in (section, governance):
            for fact in ("npm run build", "npm run bundle", "web_dist/index.html"):
                self.assertIn(fact, text)


class ReleaseDocsTest(unittest.TestCase):
    """Issue #503: the pages say what proves a release, how to install it without GitHub, and what is still open."""

    def test_the_install_guide_gives_the_verification_the_offline_install_and_the_mirror(self):
        """Issue #503: no offline section, no gh attestation verify, curl without --proto."""
        guide = _read("docs/install.md")
        self.assertIn("curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.sh | sh", guide)
        self.assertNotIn("curl -fsSL", guide)
        verify = guide.split("## Verify where the files come from", 1)[1].split("\n## ", 1)[0]
        self.assertIn("gh attestation verify openguildkit-0.17.0-py3-none-any.whl --repo Sandbox-podcast/OpenGuildKit", verify)
        for fact in ("--signer-workflow", "--source-ref", "workflow", "tag", "does not prove", "SBOM"):
            self.assertIn(fact, verify)
        offline = guide.split("## Offline and internal mirror", 1)[1].split("\n## ", 1)[0]
        for fact in ("python -m pip install --no-index", "SHA256SUMS.txt", "internal", "no runtime dependency",
                     "openguildkit-0.17.0.cdx.json"):
            self.assertIn(fact, offline)

    def test_the_governance_steps_name_the_sbom_the_attestation_and_the_second_build(self):
        """Issue #503: the release steps of GOVERNANCE.md say nothing of what proves the files."""
        section = _read("GOVERNANCE.md").split("## Releases", 1)[1].split("\n## ", 1)[0]
        for fact in ("SBOM", "attest", "same SHA-256", "gh attestation verify", "SOURCE_DATE_EPOCH"):
            self.assertIn(fact, section)
        self.assertIn("not published on PyPI", _read("GOVERNANCE.md"), "the PyPI decision stays the maintainer's")

    def test_the_build_tools_are_pinned_in_one_file_the_guide_names(self):
        """Issue #503: build and setuptools floated; the constraints file is the single list of their versions."""
        constraints = _read(".github/build-constraints.txt")
        self.assertRegex(constraints, r"(?m)^build==\d+\.\d+\.\d+$")
        self.assertRegex(constraints, r"(?m)^setuptools==\d+\.\d+\.\d+$")
        self.assertIn(".github/build-constraints.txt", _read("docs/install.md"))


def setuptools_floor() -> bool:
    try:
        return tuple(map(int, importlib.metadata.version("setuptools").split(".")[:2])) >= (77, 0)
    except (importlib.metadata.PackageNotFoundError, ValueError):
        return False


@unittest.skipUnless(importlib.util.find_spec("setuptools") and setuptools_floor(),
                     "needs setuptools 77 or later, which the wheel's pyproject.toml asks for (not installed by default)")
class ReproducibleWheelTest(unittest.TestCase):
    """Issue #503: two builds of one commit gave two wheels, because of the date of the sources."""

    def build(self, folder: Path, modified: int, **env) -> str:
        sources = folder / "tree"
        shutil.copytree(ROOT / "src", sources / "src", ignore=shutil.ignore_patterns("__pycache__", "web_dist"))
        for name in ("pyproject.toml", "LICENSE"):
            shutil.copy(ROOT / name, sources / name)
        (sources / "docs").mkdir()
        shutil.copy(ROOT / "docs" / "package-description.md", sources / "docs")
        for path in [*sources.rglob("*")]:
            os.utime(path, (modified, modified))
        out = folder / "out"
        out.mkdir()
        code = "import setuptools.build_meta as b, sys; print(b.build_wheel(sys.argv[1]))"
        done = subprocess.run([sys.executable, "-c", code, str(out)], cwd=sources, capture_output=True, text=True,
                              env={**{k: v for k, v in os.environ.items() if k != "SOURCE_DATE_EPOCH"}, **env},
                              timeout=300, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return hashlib.sha256((out / done.stdout.strip().splitlines()[-1]).read_bytes()).hexdigest()

    def test_two_builds_with_source_date_epoch_give_the_same_wheel_whatever_the_dates_of_the_files(self):
        """Issue #503: the same sources, built a year apart, give one SHA-256 when the date is the commit's."""
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            epoch = {"SOURCE_DATE_EPOCH": "1795000000"}
            self.assertEqual(self.build(Path(first), 1_700_000_000, **epoch), self.build(Path(second), 1_760_000_000, **epoch))

    def test_without_it_the_dates_of_the_files_change_the_wheel(self):
        """The control of the test above: the build does depend on the dates, so the date fixes it."""
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            self.assertNotEqual(self.build(Path(first), 1_700_000_000), self.build(Path(second), 1_760_000_000))


BUILD_STEPS = ("Build the web interface into the package", "Build the wheel",
               "Check that the wheel holds the web interface and the catalog bundle")


def build_steps(job: dict) -> tuple[str, list[dict]]:
    """The Node version (typed, or read from the .nvmrc a job names) and the steps that build the wheel."""
    setup = next(step for step in steps(job) if "setup-node" in str(step.get("uses")))["with"]
    node = setup.get("node-version") or _read(setup["node-version-file"]).strip()
    return node, [{key: step.get(key) for key in ("name", "working-directory", "run")}
                  for step in steps(job) if step.get("name") in BUILD_STEPS]


class WheelBuildTest(unittest.TestCase):
    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]
        self.wheel, self.package = self.jobs["wheel"], self.jobs["package"]
        self.release = parse(ROOT / ".github" / "workflows" / "release.yml")["jobs"]["build"]

    def test_the_release_builds_the_wheel_as_the_wheel_job_of_ci_does(self):
        node, release = build_steps(self.release)
        self.assertEqual([step["name"] for step in release], list(BUILD_STEPS))
        self.assertEqual(build_steps(self.wheel), (node, release))

    def test_the_interface_is_built_before_the_wheel_and_checked_inside_it(self):
        names = [step.get("name") for step in steps(self.release)]
        self.assertEqual([names.index(name) for name in BUILD_STEPS], sorted(names.index(name) for name in BUILD_STEPS))
        web, wheel, check = (next(step for step in steps(self.release) if step.get("name") == name)
                             for name in BUILD_STEPS)
        self.assertEqual(web["working-directory"], "web")
        self.assertEqual(web["run"].splitlines(), ["npm ci --ignore-scripts", "npm run build", "npm run bundle"])
        self.assertIn("python -m build --wheel --outdir dist", wheel["run"])
        self.assertIn("python -m zipfile -l", check["run"])
        self.assertIn("openguildkit/web_dist/index.html", check["run"])
        later = run_text({"steps": steps(self.release)[names.index(BUILD_STEPS[-1]) + 1:]})
        self.assertIn("sha256sum", later)

    def test_the_catalog_bundle_is_built_before_the_wheel_and_checked_inside_it(self):
        """Issue #533: a wheel without registry/catalog.bundle.json reads the 289 record files in every process."""
        _, wheel, check = (next(step for step in steps(self.release) if step.get("name") == name)
                           for name in BUILD_STEPS)
        commands = wheel["run"].splitlines()
        self.assertLess(commands.index("python scripts/build_catalog_bundle.py"),
                        commands.index("python -m build --wheel --outdir dist"))
        self.assertIn("openguildkit/registry/catalog.bundle.json", check["run"])
        published = parse(ROOT / ".github" / "workflows" / "release-check.yml")["jobs"]["install"]
        self.assertIn("openguildkit/registry/catalog.bundle.json", run_text(published))

    def test_the_wheel_job_checks_the_metadata_and_the_package_job_installs_the_wheel_and_runs_it(self):
        self.assertIn("twine check --strict", run_text(self.wheel))
        script = run_text(self.package)
        self.assertIn("pipx install", script)
        self.assertIn('"$RUNNER_OS" = Windows', script)
        self.assertIn(".github/scripts/check-installed-cli.py", script)


class GovernanceFilesTest(unittest.TestCase):
    def test_codeowners_names_the_owners_of_every_path(self):
        rules = [line.split() for line in _read(".github/CODEOWNERS").splitlines()
                 if line.strip() and not line.startswith("#")]
        catch_all = [rule for rule in rules if rule[0] == "*"]
        self.assertEqual(len(catch_all), 1)
        self.assertTrue(catch_all[0][1:] and all(re.fullmatch(r"@[\w-]+(/[\w-]+)?", owner) for owner in catch_all[0][1:]))
        self.assertIn(".github/CODEOWNERS", _read("GOVERNANCE.md"))

    def test_the_governance_names_one_maintainer_as_codeowners_does(self):
        codeowners = _read(".github/CODEOWNERS")
        self.assertNotIn("PLACEHOLDER", codeowners)
        owners = next(line.split()[1:] for line in codeowners.splitlines() if line.startswith("* "))
        self.assertEqual(len(owners), 1)
        governance = _read("GOVERNANCE.md")
        self.assertIn("one maintainer today", governance)
        self.assertNotIn("Maintainers decide", governance)

    def test_security_reports_get_an_acknowledgement_even_when_the_maintainer_is_away(self):
        policy = _read("SECURITY.md")
        self.assertIn("within 14 days", policy)
        away = next(block for block in policy.split("\n\n") if "away" in block)
        self.assertIn("stays private", away)
        self.assertIn("Security", away)

    def test_pages_that_cite_the_release_check_step_cite_the_step_that_describes_it(self):
        section = _read("GOVERNANCE.md").split("## Releases", 1)[1].split("\n## ", 1)[0]
        steps = [line.split(". ", 1)[0] for line in section.splitlines()
                 if re.match(r"\d+\. ", line) and "release-check.yml" in line]
        self.assertEqual(len(steps), 1, steps)
        cited = {
            ".github/workflows/release-check.yml": r"step (\d+) of GOVERNANCE\.md#releases",
            "docs/testing.md": r"GOVERNANCE\.md#releases\), step (\d+)",
        }
        for relative, pattern in cited.items():
            with self.subTest(page=relative):
                self.assertEqual(set(re.findall(pattern, _read(relative))), {steps[0]})

    def test_the_governance_says_where_the_draft_starts_without_a_stable_release(self):
        draft = next(block for block in _read("GOVERNANCE.md").split("\n\n") if "openguildkit-next" in block)
        for words in ("last stable release", "pre-release", "oldest", "no release"):
            with self.subTest(words=words):
                self.assertIn(words, draft)

    def test_contributing_states_the_licence_of_catalog_content(self):
        self.assertTrue(_read("LICENSE").startswith("MIT License"))
        paragraph = next(block for block in _read("CONTRIBUTING.md").split("\n\n") if "licen" in block.lower())
        for fact in ("catalog", "MIT License", "LICENSE"):
            self.assertIn(fact, paragraph)


def _documentation_links(relative: str) -> list[str]:
    section = _read(relative).split("\n## Documentation\n", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"\]\(([^)\s]+)\)", section)


class FrenchPagesTest(unittest.TestCase):
    """The French README addresses the reader one way, says once what is in French, and lists the same pages."""

    def test_the_french_readme_says_tu_and_uses_one_kind_of_apostrophe(self):
        text = _read("README.fr.md")
        self.assertEqual(re.findall(r"\b(?:vous|votre|vos)\b", text, re.IGNORECASE), [])
        self.assertNotIn("\u2019", text)
        self.assertEqual(text.count("Chaque brain traite la demande sous plusieurs angles"), 0)

    def test_both_readmes_list_the_same_documentation(self):
        english, french = _documentation_links("README.md"), _documentation_links("README.fr.md")
        self.assertGreater(len(english), 15)
        self.assertEqual(french, english)

    def test_the_language_rule_names_the_french_folder_and_why(self):
        rule = next(line for line in _read("CONTRIBUTING.md").splitlines() if line.startswith("- Write code"))
        self.assertIn("`web/`", rule)
        self.assertIn("French", rule)
        self.assertIn("because", rule)
        for report in ("resume-check-2026-11-24.md", "resume-check-2026-11-25.md"):
            self.assertIn(f"`examples/export-expiry/{report}`", rule)
            self.assertTrue((ROOT / "examples" / "export-expiry" / report).is_file())
        top = _read("README.fr.md").split("\n## ", 1)[0]
        self.assertIn("`web/`", top)
        self.assertIn("en français", top)


WEB_DOCS = ROOT / "web" / "docs"


class WebDocsTest(unittest.TestCase):
    """The web pages: no stale screenshot series, links that resolve, and the origin of the images said plainly."""

    def test_only_the_screenshot_series_that_are_regenerated_remain(self):
        self.assertEqual(sorted(path.name for path in WEB_DOCS.glob("captures*")), ["captures-apres", "captures-pro"])
        verification = (WEB_DOCS / "verification.md").read_text(encoding="utf-8")
        self.assertNotIn("Avant", verification)
        self.assertNotIn("captures-avant", verification)

    def test_relative_links_of_the_web_pages_resolve(self):
        pages = [ROOT / "web" / "README.md", *sorted(WEB_DOCS.rglob("*.md"))]
        for page in pages:
            for target in re.findall(r"\]\(([^)\s]+)\)", page.read_text(encoding="utf-8")):
                path = target.split("#")[0]
                if re.match(r"[a-z]+:", target) or not path or "node_modules" in path:
                    continue
                with self.subTest(page=page.relative_to(ROOT).as_posix(), link=target):
                    self.assertTrue((page.parent / path).exists())

    def test_the_web_readme_says_when_to_regenerate_the_screenshots(self):
        readme = (ROOT / "web" / "README.md").read_text(encoding="utf-8")
        paragraph = next(block for block in readme.split("\n\n") if "captures-apres" in block and "CAPTURES=1" in block
                         and not block.startswith("```"))
        self.assertIn("après", paragraph)

    def test_the_assets_page_says_where_the_images_come_from_and_what_was_not_checked(self):
        paragraph = next(block for block in (WEB_DOCS / "assets.md").read_text(encoding="utf-8").split("\n\n")
                         if "ImageGen" in block)
        self.assertRegex(paragraph, r"\d{1,2} novembre 2026")
        self.assertIn("docs/art", paragraph)
        self.assertIn("lecture juridique", paragraph)
        self.assertNotIn("restent à vérifier", paragraph)


class CiWorkflowTest(unittest.TestCase):
    """The checks every pull request must pass: bounded in time, run on the supported Pythons, all required."""

    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]

    def test_every_job_stops_before_the_runner_default_of_six_hours(self):
        expected = {"test": "30", "package": "20", "wheel": "20", "web-e2e": "20", "changes": "5"}
        for name, job in self.jobs.items():
            self.assertEqual(job.get("timeout-minutes"), expected.get(name, "15"), name)

    def test_the_matrix_runs_from_the_floor_to_the_maintainers_python(self):
        versions = self.jobs["test"]["strategy"]["matrix"]["python"]
        floor = tomllib.loads(_read("pyproject.toml"))["project"]["requires-python"].removeprefix(">=")
        self.assertEqual(versions, [floor, "3.15"])
        self.assertEqual(self.jobs["package"]["strategy"]["matrix"]["python"], versions)

    def test_contribution_checks_require_every_other_job(self):
        gate = self.jobs["contribution-checks"]
        self.assertEqual(set(gate["needs"]), set(self.jobs) - {"contribution-checks"})
        script = run_text(gate)
        for job in gate["needs"]:
            variable = next(name for name, value in gate["steps"][0]["env"].items() if f"needs.{job}.result" in value)
            self.assertIn(f'test "${variable}" = success', script)
        self.assertNotIn("once it has passed on main", _read(".github/workflows/ci.yml"))

    def test_contributing_names_every_job_contribution_checks_requires(self):
        named = {"changes": "list of the changed files", "test": "test matrix", "performance": "performance tests",
                 "wheel": "wheel build", "package": "installation of the wheel", "ci-coordinator": "CI coordinator",
                 "web": "checks and journeys of the web interface",
                 "web-e2e": "checks and journeys of the web interface", "lint": "lint ratchet",
                 "conventions": "conventions for agents"}
        self.assertEqual(set(named), set(self.jobs["contribution-checks"]["needs"]))
        paragraph = next(block for block in _read("CONTRIBUTING.md").split("\n\n") if "`contribution-checks` status" in block)
        for job, words in named.items():
            with self.subTest(job=job):
                self.assertIn(words, paragraph)

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


# The workflows of this repository and the templates a project copies. The workflow of the legacy fixture in
# integrations/ci/prototype/demo reproduces the original prototype as it ran; the Node package does not ship it.
TIMED_WORKFLOWS = [*WORKFLOWS, *(path for path in TEMPLATES if "prototype" not in path.relative_to(ROOT).parts)]


class TimeLimitTest(unittest.TestCase):
    def test_every_job_of_the_workflows_and_shipped_templates_has_a_time_limit(self):
        for folder in (".github/workflows", "integrations/github", "integrations/ci/pilot"):
            self.assertTrue(any(path.parent == ROOT / folder for path in TIMED_WORKFLOWS), folder)
        for path in TIMED_WORKFLOWS:
            for name, job in parse(path)["jobs"].items():
                with self.subTest(workflow=path.relative_to(ROOT).as_posix(), job=name):
                    limit = job.get("timeout-minutes")
                    self.assertIsNotNone(limit, "GitHub stops a job without timeout-minutes after six hours.")
                    self.assertTrue(limit.isdigit() and 0 < int(limit) <= 30, limit)


def _glob(pattern: str) -> re.Pattern:
    """A labeler glob as actions/labeler reads it (minimatch with dot files): ** spans folders, * and ? do not."""
    parts = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    wildcards = {"**/": "(?:.*/)?", "**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(wildcards.get(part, re.escape(part)) for part in parts))


def labeler_globs() -> dict[str, list[str]]:
    """The globs of each label in .github/labeler.yml."""
    found = {}
    for label, rules in parse(ROOT / ".github" / "labeler.yml").items():
        for rule in rules:
            for match in rule["changed-files"]:
                globs = match["any-glob-to-any-file"]
                found.setdefault(label, []).extend([globs] if isinstance(globs, str) else globs)
    return found


def labels_for(path: str) -> set[str]:
    return {label for label, globs in labeler_globs().items() if any(_glob(glob).fullmatch(path) for glob in globs)}


class LabelTest(unittest.TestCase):
    """GitHub labels a pull request from its changed files, and the release notes group pull requests by label."""

    def test_the_globs_use_only_the_wildcards_this_test_reads(self):
        for label, globs in labeler_globs().items():
            for glob in globs:
                self.assertNotRegex(glob, r"[{}\[\]!]", label)
        self.assertTrue(_glob("web/**").fullmatch("web/src/main.tsx"))
        self.assertTrue(_glob("web/**").fullmatch("web/.gitignore"))
        self.assertFalse(_glob("src/openguildkit/*.py").fullmatch("src/openguildkit/agent_files/skills/x.py"))

    def test_every_tracked_file_outside_the_root_gets_a_label(self):
        listed = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=False)
        if listed.returncode != 0:
            self.skipTest("needs a Git checkout of the repository")
        files = [name for name in listed.stdout.decode("utf-8").split("\0") if "/" in name]
        self.assertGreater(len(files), 500)
        globs = [_glob(glob) for globs in labeler_globs().values() for glob in globs]
        unlabeled = [name for name in files if not any(glob.fullmatch(name) for glob in globs)]
        self.assertEqual(unlabeled, [], "Add a rule to .github/labeler.yml for these files.")

    def test_the_web_interface_and_the_whole_registry_get_their_labels(self):
        self.assertEqual(labels_for("web/src/project/ProjectShell.tsx"), {"web"})
        for folder in ("packs", "references", "tools", "tool-mocks", "deliverables", "features"):
            self.assertIn("catalog", labels_for(f"src/openguildkit/registry/{folder}/example.json"), folder)

    def test_each_label_has_a_category_in_the_release_notes(self):
        categories = parse(ROOT / ".github" / "release.yml")["changelog"]["categories"]
        grouped = {label for category in categories[:-1] for label in category["labels"]}
        self.assertEqual(categories[-1]["labels"], ["*"])
        self.assertEqual(set(labeler_globs()) - grouped, set())


class InstalledCommandCheckTest(unittest.TestCase):
    """The script the package job runs on the installed wheel: it must pass on a built interface only."""

    def check(self, static: Path) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        return subprocess.run([sys.executable, str(CHECK_INSTALLED), "--static", str(static), "--",
                               sys.executable, "-m", "openguildkit"],
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=180, check=False)

    def test_passes_when_the_page_and_its_scripts_are_served(self):
        with tempfile.TemporaryDirectory() as folder:
            front = Path(folder)
            (front / "assets").mkdir()
            (front / "index.html").write_text('<!doctype html><html><head></head><body>'
                                              '<script type="module" src="./assets/index-a1b2c3d4.js"></script>'
                                              '</body></html>', encoding="utf-8")
            (front / "assets" / "index-a1b2c3d4.js").write_text("export {};\n", encoding="utf-8")
            done = self.check(front)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("answered 200 with the built interface", done.stdout)
        self.assertIn("alerts --help: ok", done.stdout)

    def test_fails_when_the_interface_is_not_built(self):
        with tempfile.TemporaryDirectory() as folder:
            done = self.check(Path(folder))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("answered 503", done.stderr)

    def test_fails_when_a_script_of_the_page_is_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            front = Path(folder)
            (front / "index.html").write_text('<head></head><script src="./assets/gone-a1b2c3d4.js"></script>',
                                              encoding="utf-8")
            done = self.check(front)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("assets/gone-a1b2c3d4.js answered 404", done.stderr)


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

    def assert_one_bound(self, body: str, log: str, tag: str) -> None:
        """GitHub lists the pull requests from previous_tag_name; the Full Changelog link starts at the same tag."""
        self.assertEqual(re.findall(r"previous_tag_name=(\S+)", log), [tag])
        self.assertEqual(re.findall(r"\*\*Full Changelog\*\*: https://github\.com/example/openguildkit/compare/"
                                    r"([^.\s]+(?:\.[^.\s]+)*)\.\.\." + "a" * 40 + r"$", body, re.MULTILINE), [tag])
        self.assertEqual(body.count("**Full Changelog**"), 1)

    def test_draft_compares_from_the_last_stable_release_despite_a_newer_prerelease(self):
        body, log = self.draft([
            _release("v0.16.0", "2026-10-01T00:00:00Z"),
            _release("v0.16.1", "2026-11-01T00:00:00Z"),
            _release("v0.17.0", "2026-11-10T00:00:00Z", prerelease=True),
            _release("openguildkit-next", None, draft=True),
        ])
        self.assert_one_bound(body, log, "v0.16.1")

    def test_draft_without_a_stable_release_compares_from_the_oldest_published_release(self):
        body, log = self.draft([
            _release("v0.17.0", "2026-11-10T00:00:00Z", prerelease=True),
            _release("v0.1.0", "2026-09-01T00:00:00Z", prerelease=True),
            _release("v0.16.1", "2026-11-01T00:00:00Z", prerelease=True),
            _release("openguildkit-next", None, draft=True),
        ])
        self.assert_one_bound(body, log, "v0.1.0")

    def test_draft_without_any_published_release_links_the_commits(self):
        for releases in ([], [_release("openguildkit-next", None, draft=True)]):
            with self.subTest(releases=len(releases)):
                body, log = self.draft(releases)
                self.assertNotIn("previous_tag_name", log)
                self.assertIn(f"**Full Changelog**: https://github.com/example/openguildkit/commits/{'a' * 40}", body)
                self.assertNotIn("/compare/", body)


if __name__ == "__main__":
    unittest.main()
