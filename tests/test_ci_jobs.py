"""What ci.yml and its neighbours run and read: the path filter, the test matrix, the log of a test job, the version
files, the optional coverage workflow, Dependabot and the sample servers of the web journeys.

GitHub Actions cannot run here, so these tests read the YAML with the small parser of tests/test_workflows.py and run
the shell steps themselves, with a fake gh, a fake CLI and temporary Git repositories.
"""

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

from tests.test_workflows import ROOT, matrix_jobs, parse, run_text, steps


@unittest.skipIf(os.name == "nt", "the script is stopped with a signal, which Windows does not send the same way")
@unittest.skipUnless(shutil.which("node"), "needs node, as the web journeys do")
class ServeSampleTest(unittest.TestCase):
    """web/scripts/serve-sample.mjs starts one sample project per server of the web journeys."""

    def start(self) -> tuple[subprocess.Popen, Path]:
        """Run the script from a copy of the tree it expects (web/scripts, web/dist, src), with its own TMPDIR."""
        folder = Path(tempfile.mkdtemp(prefix="ogk-serve-sample-test-"))
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / "web" / "scripts").mkdir(parents=True)
        (folder / "web" / "dist").mkdir()
        (folder / "web" / "dist" / "index.html").write_text("<!doctype html>", encoding="utf-8")
        shutil.copy(ROOT / "web" / "scripts" / "serve-sample.mjs", folder / "web" / "scripts")
        (folder / "src").symlink_to(ROOT / "src", target_is_directory=True)
        (folder / "tmp").mkdir()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        environment = {**os.environ, "TMPDIR": str(folder / "tmp"), "PW_PROJECT_PORT": str(port),
                       "OGK_PYTHON": sys.executable, "OPENGUILDKIT_UI_KEY": "k" * 64}
        with open(folder / "log.txt", "wb") as log:
            process = subprocess.Popen(["node", str(folder / "web" / "scripts" / "serve-sample.mjs"), "--empty"],
                                       env=environment, stdout=log, stderr=log)
        self.addCleanup(process.kill)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                return process, folder / "tmp"
            except OSError:
                self.assertIsNone(process.poll(), (folder / "log.txt").read_text(encoding="utf-8"))
                time.sleep(0.2)
        self.fail("the server did not answer: " + (folder / "log.txt").read_text(encoding="utf-8"))

    def test_the_project_folder_is_removed_when_the_script_is_stopped(self):
        """Issue #518: each server of the web journeys leaves an ogk-e2e-* folder in the temporary folder."""
        for stop in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=stop.name):
                process, temporary = self.start()
                self.assertEqual(len(list(temporary.glob("ogk-e2e-*"))), 1, "the script makes its project here")
                process.send_signal(stop)
                process.wait(timeout=30)
                self.assertEqual(list(temporary.glob("ogk-e2e-*")), [])

    def test_playwright_stops_each_server_with_a_signal_the_script_can_answer(self):
        """Issue #518: by default Playwright ends a web server with SIGKILL, which no script can answer."""
        text = (ROOT / "web" / "playwright.project.config.ts").read_text(encoding="utf-8")
        self.assertEqual(text.count("gracefulShutdown"), text.count("node scripts/serve-sample.mjs"))
        self.assertIn("SIGTERM", text)


class PythonMatrixTest(unittest.TestCase):
    """Issue #474: on a pull request, two of the six cells had never found a failure that no other cell found."""

    def setUp(self):
        self.job = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["test"]

    def cells(self, event: str) -> set[tuple[str, str]]:
        return {(c["os"], c["python"]) for c in matrix_jobs(self.job, event)}

    def test_a_pull_request_runs_four_cells_and_a_push_to_main_runs_all_six(self):
        self.assertEqual(self.cells("pull_request"), {("ubuntu-latest", "3.11"), ("ubuntu-latest", "3.15"),
                                                      ("macos-latest", "3.15"), ("windows-latest", "3.11")})
        self.assertEqual(len(self.cells("push")), 6)
        self.assertLess(self.cells("pull_request"), self.cells("push"))


@unittest.skipIf(os.name == "nt", "the step is bash, as on the ubuntu-latest runner")
@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "needs git and bash, as on the GitHub runner")
class ChangedFilesTest(unittest.TestCase):
    """Issue #474: a pull request that touches only docs/ ran the CI coordinator and the web checks."""

    NOTHING = {"coordinator": "false", "web": "false", "journeys": "false"}
    EVERYTHING = {"coordinator": "true", "web": "true", "journeys": "true"}

    def setUp(self):
        self.job = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["changes"]
        self.step = next(step for step in steps(self.job) if step.get("id") == "filter")
        self.repo = Path(tempfile.mkdtemp(prefix="ogk-changes-test-"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q")
        (self.repo / "README.md").write_text("first\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "first")

    def git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                               "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def outputs(self, *paths: str, base: str | None = None) -> dict:
        """What the step writes for a commit that touches these files, compared with its parent (or with BASE)."""
        parent = self.git("rev-parse", "HEAD")
        for path in paths:
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text("changed\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "change")
        written = self.repo / "github-output"
        environment = {**os.environ, "GITHUB_OUTPUT": str(written), "BASE": parent if base is None else base}
        result = subprocess.run(["bash", "-e", "-c", self.step["run"]], cwd=self.repo, env=environment,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in written.read_text(encoding="utf-8").splitlines())

    def test_documentation_alone_starts_none_of_the_three_jobs(self):
        self.assertEqual(self.outputs("docs/testing.md", "CHANGELOG.md", "README.md"), self.NOTHING)

    def test_each_folder_starts_the_jobs_that_read_it(self):
        cases = {
            "integrations/ci/lib/a.mjs": {**self.NOTHING, "coordinator": "true"},
            "examples/export-expiry/policy/rule.json": {**self.NOTHING, "coordinator": "true"},
            "web/src/App.tsx": {**self.NOTHING, "web": "true", "journeys": "true"},
            "src/openguildkit/guard.py": {**self.NOTHING, "journeys": "true"},
            ".github/workflows/ci.yml": self.EVERYTHING,
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(self.outputs(path), expected)

    def test_what_the_web_checks_read_outside_web_starts_them(self):
        """The web checks read the registry of the CLI and the glossary of docs/ from outside web/."""
        for path in ("src/openguildkit/registry/packs/x.json", "docs/glossary.md"):
            with self.subTest(path=path):
                self.assertEqual(self.outputs(path)["web"], "true")

    def test_every_file_the_web_folder_reads_outside_itself_starts_the_web_checks(self):
        web = ROOT / "web"
        pattern = re.compile(r"""['"`]((?:\.\./)+[\w./*-]*)""")
        outside = {}
        for folder in ("src", "tests", "scripts"):
            for path in sorted((web / folder).rglob("*")):
                if not path.is_file() or path.suffix not in {".ts", ".tsx", ".mjs", ".js", ".py"}:
                    continue
                for found in pattern.findall(path.read_text(encoding="utf-8")):
                    target = (path.parent / found.split("*")[0]).resolve()
                    if web not in target.parents and target != web and (ROOT in target.parents) and target.exists():
                        outside[target.relative_to(ROOT).as_posix()] = path.relative_to(ROOT).as_posix()
        self.assertTrue(outside, "the web folder reads the registry of the CLI")
        for target, reader in outside.items():
            with self.subTest(target=target, reader=reader):
                self.assertEqual(self.outputs(target if "." in Path(target).name else f"{target}/x.json")["web"], "true")

    def test_when_the_files_cannot_be_listed_every_job_runs(self):
        for base in ("", "0" * 40, "f" * 40):
            with self.subTest(base=base):
                self.assertEqual(self.outputs("docs/testing.md", base=base), self.EVERYTHING)

    def test_the_step_reads_git_and_no_third_party_action(self):
        self.assertEqual([step for step in steps(self.job) if "uses" in step and "checkout" not in step["uses"]], [])
        checkout = next(step for step in steps(self.job) if "checkout" in str(step.get("uses")))
        self.assertEqual(checkout["with"], {"persist-credentials": "false", "fetch-depth": "0"})


class CoverageWorkflowTest(unittest.TestCase):
    """Issue #472: no workflow measured which lines of the package the tests run, guard.py included."""

    def setUp(self):
        self.workflow = parse(ROOT / ".github" / "workflows" / "coverage.yml")
        self.job = self.workflow["jobs"]["coverage"]
        self.config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["coverage"]

    def test_it_is_an_option_off_by_default_that_a_person_starts_by_hand(self):
        """A floor that blocks merges is a constraint the maintainers choose: the workflow only runs on request."""
        self.assertEqual(set(self.workflow["on"]), {"workflow_dispatch"})
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        gate = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["contribution-checks"]
        self.assertNotIn("coverage", gate["needs"])

    def test_it_measures_branches_in_the_processes_the_tests_start_and_reports_each_module(self):
        self.assertEqual(self.config["run"]["branch"], True)
        self.assertEqual(self.config["run"]["parallel"], True, "one data file per process, combined afterwards")
        self.assertIn("subprocess", self.config["run"]["patch"], "the CLI processes the tests start count")
        self.assertEqual(self.config["run"]["source"], ["src/openguildkit"])
        script = run_text(self.job)
        self.assertLess(script.index("coverage run -m unittest discover -s tests"), script.index("coverage combine"))
        self.assertLess(script.index("coverage combine"), script.index("coverage report --format=markdown"))
        self.assertIn("$GITHUB_STEP_SUMMARY", script)

    def test_guard_and_hosts_each_have_a_floor_that_fails_the_job(self):
        script = run_text(self.job)
        floors = dict(re.findall(r"coverage report --include='\*/openguildkit/(\w+)\.py' --fail-under=(\d+)", script))
        self.assertEqual(set(floors), {"guard", "hosts"})
        for module, floor in floors.items():
            self.assertTrue(0 < int(floor) < 100, module)

    def test_the_testing_guide_tells_the_coverage_of_the_code_from_that_of_the_catalog(self):
        guide = (ROOT / "docs" / "testing.md").read_text(encoding="utf-8")
        section = guide.split("## Code coverage", 1)[1].split("\n## ", 1)[0]
        for fact in (".github/workflows/coverage.yml", "scripts/coverage.py", "catalog", "guard.py", "hosts.py"):
            self.assertIn(fact, section)


class DependabotConfigTest(unittest.TestCase):
    """Issue #473: nothing proposed the update of the pinned actions or of the npm packages of web/."""

    def setUp(self):
        config = parse(ROOT / ".github" / "dependabot.yml")
        self.assertEqual(config["version"], "2")
        self.updates = {update["package-ecosystem"]: update for update in config["updates"]}

    @staticmethod
    def directories(update: dict) -> list[str]:
        return update.get("directories") or [update["directory"]]

    def test_actions_npm_and_pip_get_one_grouped_weekly_pull_request_each(self):
        self.assertEqual(set(self.updates), {"github-actions", "npm", "pip"})
        for ecosystem, update in self.updates.items():
            with self.subTest(ecosystem=ecosystem):
                self.assertEqual(update["schedule"]["interval"], "weekly")
                self.assertTrue(update["groups"], "one pull request per ecosystem, not one per package")

    def test_each_directory_holds_what_dependabot_reads_there(self):
        """For github-actions, dependabot reads .github/workflows from /, and the *.yml files of any other directory."""
        for ecosystem, manifest in (("npm", "package.json"), ("pip", "pyproject.toml")):
            for directory in self.directories(self.updates[ecosystem]):
                self.assertTrue((ROOT / directory.lstrip("/") / manifest).is_file(), f"{ecosystem}: {directory}")
        actions = self.directories(self.updates["github-actions"])
        self.assertEqual(set(actions), {"/", "/integrations/github", "/integrations/ci/pilot"})
        for directory in actions:
            folder = ROOT / directory.lstrip("/")
            self.assertTrue(list((folder / ".github" / "workflows" if directory == "/" else folder).glob("*.yml")), directory)

    def test_npm_follows_the_web_interface_and_groups_minor_and_patch_updates(self):
        npm = self.updates["npm"]
        self.assertEqual(self.directories(npm), ["/web"])
        self.assertEqual(sorted(next(iter(npm["groups"].values()))["update-types"]), ["minor", "patch"])


class CiLogTest(unittest.TestCase):
    """Issue #517: the log of a test job held 15,355 lines, 81 % of them the catalog JSON that a step printed."""

    def setUp(self):
        self.job = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["test"]

    def step(self, name: str) -> dict:
        return next(step for step in steps(self.job) if step.get("name") == name)

    def test_the_catalog_check_prints_nothing_and_still_fails_on_a_bad_catalog(self):
        step = self.step("Validate the catalog")
        self.assertEqual(step["shell"], "bash", "PowerShell, the default on Windows, has no /dev/null")
        bash = shutil.which("bash")
        if os.name == "nt" or not bash:
            self.skipTest("The step is run with bash, as on the GitHub runner.")
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        fake = directory / "openguildkit"
        fake.write_text('#!/bin/sh\nyes \'{"id": "pack"}\' | head -n 12000\n[ "$FAKE_FAILS" = 1 ] && '
                        'echo "catalog problem" >&2 && exit 3\nexit 0\n', encoding="utf-8")
        fake.chmod(0o755)
        environment = {**os.environ, "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}"}
        passed = subprocess.run([bash, "-e", "-c", step["run"]], env=environment, capture_output=True, text=True)
        self.assertEqual((passed.returncode, passed.stdout), (0, ""))
        failed = subprocess.run([bash, "-e", "-c", step["run"]], env={**environment, "FAKE_FAILS": "1"},
                                capture_output=True, text=True)
        self.assertEqual((failed.returncode, failed.stdout), (3, ""))
        self.assertIn("catalog problem", failed.stderr, "the reason of a failure stays in the log")

    def test_the_log_of_the_tests_ends_with_the_slowest_ones_where_unittest_can_list_them(self):
        """unittest has --durations from Python 3.12; the floor of requires-python does not."""
        run = self.step("Unit and end-to-end tests")["run"]
        match = re.fullmatch(r"python -m unittest discover -s tests -v \$\{\{ matrix\.python != '([\d.]+)' && '(--durations 25)' \|\| '' \}\}", run)
        self.assertIsNotNone(match, run)
        floor = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["requires-python"]
        floor = floor.removeprefix(">=")
        self.assertEqual(match.group(1), floor, "the one Python that has no --durations")
        self.assertLess(tuple(map(int, floor.split("."))), (3, 12), "from Python 3.12 on, drop the condition")
        for version in self.job["strategy"]["matrix"]["python"]:
            if version != floor:
                self.assertGreaterEqual(tuple(map(int, version.split("."))), (3, 12), version)


class ToolVersionFilesTest(unittest.TestCase):
    """Issue #520: the versions of Python and Node of a workstation and of CI live in .python-version and .nvmrc."""

    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]

    def setups(self, action: str) -> list[tuple[str, dict]]:
        return [(name, step) for name, job in self.jobs.items() for step in steps(job) if action in str(step.get("uses"))]

    def test_the_files_hold_the_versions_the_maintainers_work_with(self):
        python = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
        node = (ROOT / ".nvmrc").read_text(encoding="utf-8").strip()
        self.assertRegex(python, r"^3\.\d+$")
        self.assertRegex(node, r"^\d+$")
        self.assertEqual(python, self.jobs["test"]["strategy"]["matrix"]["python"][-1], "the newest Python of the matrix")
        release = parse(ROOT / ".github" / "workflows" / "release.yml")["jobs"]["build"]
        built_with = next(step for step in steps(release) if "setup-node" in str(step.get("uses")))["with"]["node-version"]
        self.assertEqual(node, built_with, "the release builds the web interface with the Node of .nvmrc")

    def test_ci_reads_the_versions_from_the_files(self):
        for name, step in self.setups("setup-python"):
            with self.subTest(job=name, action="setup-python"):
                with_ = step["with"]
                if "python-version-file" in with_:
                    self.assertEqual(with_["python-version-file"], ".python-version")
                else:
                    self.assertEqual(with_["python-version"], "${{ matrix.python }}", "a version typed in the job")
        floor = json.loads((ROOT / "integrations" / "ci" / "package.json").read_text(encoding="utf-8"))["engines"]["node"]
        for name, step in self.setups("setup-node"):
            with self.subTest(job=name, action="setup-node"):
                with_ = step["with"]
                if "node-version-file" in with_:
                    self.assertEqual(with_["node-version-file"], ".nvmrc")
                else:
                    self.assertEqual(f">={with_['node-version']}", floor, "only the floor of integrations/ci is typed")



if __name__ == "__main__":
    unittest.main()
