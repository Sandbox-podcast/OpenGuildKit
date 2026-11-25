"""Delivery: one version everywhere (the last release, or a development version of the next one on main), a wheel
built and checked as CI proves it, release notes from the last stable release, required and bounded CI jobs, and
the entry documents (governance, security, French README) kept true."""

import json
import os
import re
import shlex
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
CHECK_INSTALLED = ROOT / ".github" / "scripts" / "check-installed-cli.py"
VERSION = re.compile(r"\bv(\d+\.\d+\.\d+)\b|openguildkit-(\d+\.\d+\.\d+)")
STABLE = re.compile(r"(\d+)\.(\d+)\.(\d+)")
DEVELOPMENT = re.compile(r"(\d+)\.(\d+)\.(\d+)\.dev(\d+)")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def release_files() -> list[str]:
    """The files that step 1 of GOVERNANCE.md#releases names: a release sets its version in each of them."""
    section = _read("GOVERNANCE.md").split("## Releases", 1)[1].split("\n## ", 1)[0]
    step = next(line for line in section.splitlines() if line.startswith("1. "))
    return re.findall(r"`([\w./-]+\.(?:toml|json|md|yml))`", step)


def project_version() -> str:
    return tomllib.loads(_read("pyproject.toml"))["project"]["version"]


def version_key(version: str) -> tuple[int, ...]:
    """The release a version leads to, to compare them: 0.17.1.dev0 leads to 0.17.1."""
    found = STABLE.fullmatch(version) or DEVELOPMENT.fullmatch(version)
    if not found:
        raise AssertionError(f"{version!r} is neither X.Y.Z nor X.Y.Z.devN")
    return tuple(int(part) for part in found.groups()[:3])


def is_development(version: str) -> bool:
    return DEVELOPMENT.fullmatch(version) is not None


def changelog_versions(changelog: str | None = None) -> list[str]:
    """The versions the CHANGELOG has a section for, newest first."""
    return re.findall(r"^## (\d+\.\d+\.\d+)\b", changelog or _read("CHANGELOG.md"), re.MULTILINE)


def released_version() -> str:
    """The last published version, the highest section of the CHANGELOG. Between two releases main is a development
    version of the next one in pyproject.toml, and every other file keeps announcing this one."""
    return max(changelog_versions(), key=version_key)


def git(*arguments: str) -> str | None:
    """What git prints in this copy, or None without git, outside a repository or on an error."""
    try:
        done = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                              timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repository_tags() -> dict[str, str]:
    """The commit of each v* tag of this copy: empty without git or without tags, and "" for a tag whose commit a
    shallow checkout does not hold."""
    return {tag: git("rev-list", "-n", "1", tag) or "" for tag in (git("tag", "--list", "v*") or "").split()}


def published_but_not_at_head(changelog: str, tags: dict[str, str], head: str | None) -> dict[str, str]:
    """Each published version whose commit is not HEAD, with where it comes from: the v* tags, or, in a copy
    without tags (a shallow CI checkout), the CHANGELOG sections. A first section that is a version is the release
    being made, which HEAD may be."""
    if tags:
        return {tag[1:]: f"the tag {tag}" for tag, commit in tags.items()
                if STABLE.fullmatch(tag[1:]) and commit != head}
    versions = changelog_versions(changelog)
    if re.search(r"^## (\S+)", changelog, re.MULTILINE).group(1) != "Unreleased":
        versions = versions[1:]
    return {version: "a section of CHANGELOG.md" for version in versions}


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
    def test_without_tags_the_changelog_sections_stand_for_the_published_versions(self):
        unreleased = "# Changelog\n\nIntro.\n\n## Unreleased\n\n- A change.\n\n## 0.17.0\n\n## 0.16.1 and earlier\n"
        release = "# Changelog\n\nIntro.\n\n## 0.17.1\n\n- A change.\n\n## 0.17.0\n\n## 0.16.1 and earlier\n"
        self.assertEqual(set(published_but_not_at_head(unreleased, {}, "head")), {"0.17.0", "0.16.1"})
        self.assertEqual(set(published_but_not_at_head(release, {}, "head")), {"0.17.0", "0.16.1"})
        tags = {"v0.17.0": "head", "v0.16.1": "older", "v0.15.0": "", "archive/x": "other"}
        self.assertEqual(set(published_but_not_at_head(unreleased, tags, "head")), {"0.16.1", "0.15.0"})

    def test_every_file_announces_the_last_release_and_only_pyproject_may_lead_to_the_next(self):
        found = announced_versions()
        for relative, versions in found.items():
            self.assertTrue(versions, f"{relative} announces no version")
        found.pop("pyproject.toml")
        self.assertEqual(set().union(*found.values()), {released_version()}, f"align the versions: {found}")

    def test_the_project_is_the_last_release_or_a_development_version_of_the_next(self):
        project, released = project_version(), released_version()
        if is_development(project):
            self.assertGreater(version_key(project), version_key(released),
                               f"{project} must lead to a version above {released}, the last release")
        else:
            self.assertEqual(project, released, f"main carries {project}, not the last release {released} or a "
                                                f"development version of the next (X.Y.Z.devN)")

    def test_the_version_differs_from_every_published_version_whose_commit_is_not_head(self):
        published = published_but_not_at_head(_read("CHANGELOG.md"), repository_tags(), git("rev-parse", "HEAD"))
        self.assertTrue(published, "neither the tags nor the CHANGELOG name a published version")
        project = project_version()
        self.assertNotIn(project, published, f"{project} is published ({published.get(project)}) and HEAD is not "
                                             f"its commit: main carries X.Y.Z.devN between two releases")

    def test_the_release_steps_name_every_versioned_file(self):
        named = set(release_files())
        for required in ("pyproject.toml", "integrations/ci/package.json", "docs/install.md",
                         "integrations/ci/README.md", "CHANGELOG.md"):
            self.assertIn(required, named)
        for template in sorted((ROOT / "integrations" / "github").glob("*.yml")):
            self.assertIn(template.relative_to(ROOT).as_posix(), named)

    def test_templates_install_the_last_published_release(self):
        version = released_version()
        for template in sorted((ROOT / "integrations" / "github").glob("*.yml")):
            with self.subTest(template=template.name):
                text = template.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"@main\b|git\+https")
                install = next(step for job in parse(template)["jobs"].values() for step in steps(job)
                               if step.get("name") == "Install OpenGuildKit")
                self.assertEqual(install["env"]["OPENGUILDKIT_TAG"], f"v{version}")
                self.assertEqual(install["env"]["OPENGUILDKIT_WHEEL"], f"openguildkit-{version}-py3-none-any.whl")
                self.assertIn("sha256sum --strict -c", install["run"])


def changelog_section(heading: str) -> str:
    text = _read("CHANGELOG.md")
    found = re.search(rf"^## {re.escape(heading)}\b.*$", text, re.MULTILINE)
    return text[found.end():].split("\n## ", 1)[0]


class ChangelogTest(unittest.TestCase):
    def test_the_top_section_is_unreleased_on_a_development_version_and_the_release_otherwise(self):
        first = re.search(r"^## (\S+)", _read("CHANGELOG.md"), re.MULTILINE).group(1)
        project = project_version()
        self.assertEqual(first, "Unreleased" if is_development(project) else project)

    def test_0_17_0_lists_the_changes_users_see_since_the_last_release(self):
        section = changelog_section("0.17.0")
        self.assertIn("0.16.1", section)
        for change in ("done-with-reservations", "openguildkit profile", "task pass", "task export", "openguildkit ui",
                       "openguildkit tools", "mock", "openguildkit alerts", "openguildkit market",
                       "openguildkit storybook", "openguildkit docs export", "relevan"):
            self.assertIn(change, section)


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
        guide, version = _read("docs/install.md"), released_version()
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


BUILD_STEPS = ("Build the web interface into the package", "Build the wheel",
               "Check that the wheel holds the web interface")


def build_steps(job: dict) -> tuple[str, list[dict]]:
    """The Node version and the steps that build the wheel, as the job runs them."""
    node = next(step for step in steps(job) if "setup-node" in str(step.get("uses")))["with"]["node-version"]
    return node, [{key: step.get(key) for key in ("name", "working-directory", "run")}
                  for step in steps(job) if step.get("name") in BUILD_STEPS]


class WheelBuildTest(unittest.TestCase):
    def setUp(self):
        self.package = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["package"]
        self.release = parse(ROOT / ".github" / "workflows" / "release.yml")["jobs"]["build"]

    def test_the_release_builds_the_wheel_as_the_package_job_proves_it(self):
        node, release = build_steps(self.release)
        self.assertEqual([step["name"] for step in release], list(BUILD_STEPS))
        self.assertEqual(build_steps(self.package), (node, release))

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

    def test_the_package_job_installs_the_wheel_and_runs_it(self):
        script = run_text(self.package)
        self.assertIn("twine check --strict", script)
        self.assertIn("pipx install", script)
        self.assertIn('"$RUNNER_OS" = Windows', script)
        self.assertIn(".github/scripts/check-installed-cli.py", script)


@unittest.skipIf(sys.platform == "win32", "the step runs in bash on the Linux release runner")
@unittest.skipUnless(shutil.which("bash") and shutil.which("node"), "the step reads package.json with node")
class TagCheckTest(unittest.TestCase):
    """The first step of release.yml, run on small folders: a tag is released only when it names the version of
    pyproject.toml and of package.json, so a development version that gets tagged by mistake is refused."""

    def exit_code(self, tag: str, pyproject: str, package: str) -> int:
        release = parse(ROOT / ".github" / "workflows" / "release.yml")["jobs"]["build"]
        step = next(step for step in steps(release) if str(step.get("name")).startswith("Refuse a tag"))
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "pyproject.toml").write_text(f'[project]\nversion = "{pyproject}"\n', encoding="utf-8")
            (folder / "integrations" / "ci").mkdir(parents=True)
            (folder / "integrations" / "ci" / "package.json").write_text(json.dumps({"version": package}),
                                                                       encoding="utf-8")
            python = folder / "bin" / "python"  # The runner has `python`; this machine may only have python3.
            python.parent.mkdir()
            python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n', encoding="utf-8")
            python.chmod(0o755)
            env = {**os.environ, "PATH": f"{python.parent}{os.pathsep}{os.environ['PATH']}", "GITHUB_REF_NAME": tag}
            done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", step["run"]],
                                  cwd=folder, env=env, capture_output=True, text=True, check=False)
        return done.returncode

    def test_a_tag_must_name_the_version_of_both_files(self):
        self.assertEqual(self.exit_code("v0.17.1", "0.17.1", "0.17.1"), 0)
        # main between two releases: pyproject.toml leads to the next version, package.json is the last release.
        for tag in ("v0.17.1.dev0", "v0.17.1", "v0.17.0"):
            with self.subTest(tag=tag):
                self.assertNotEqual(self.exit_code(tag, "0.17.1.dev0", "0.17.0"), 0)
        self.assertNotEqual(self.exit_code("v0.17.1.dev0", "0.17.1", "0.17.1"), 0)


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
        expected = {"test": "30", "package": "20", "web-e2e": "20"}
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
