"""The GitHub workflows and the templates the project ships: structure, pinned actions, release assets.

GitHub Actions cannot run here, so these tests read the YAML with a small parser for the subset the
workflows use (block mappings and lists, flow lists, block scalars) and check what a reviewer would.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
TEMPLATES = sorted([*(ROOT / "integrations" / "github").glob("*.yml"), *(ROOT / "integrations" / "ci").rglob("*.yml")])
USES = re.compile(r"^\s*(?:- )?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
# The comment ends with the tag, which is how Dependabot finds it to rewrite it; the day of the release comes before.
TAG_COMMENT = re.compile(r"^ # (?:\d{4}-\d{2}-\d{2} )?v\d+\.\d+\.\d+$")
DATED_COMMENT = re.compile(r"^ # \d{4}-\d{2}-\d{2} v\d+\.\d+\.\d+$")
KEY = re.compile(r"""^(?:"[^"]+"|'[^']+'|[\w.-]+):(?: (.*))?$""")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _skippable(line: str) -> bool:
    return not line.strip() or line.lstrip().startswith("#")


def _scalar(text: str):
    """Read a one-line scalar: flow lists, empty mappings, quoted or plain strings without their comment."""
    text = text.strip()
    if text and text[0] in "\"'":
        return text[1:text.index(text[0], 1)]
    text = re.split(r"\s#", text, maxsplit=1)[0].strip()
    if text == "{}":
        return {}
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(item) for item in text[1:-1].split(",") if item.strip()]
    return text


class _Parser:
    """Recursive descent over indented lines; raises ValueError on a line it cannot place."""

    def __init__(self, text: str):
        if "\t" in text:
            raise ValueError("tab character in YAML")
        self.lines = text.splitlines()
        self.i = 0

    def _next(self):
        while self.i < len(self.lines) and _skippable(self.lines[self.i]):
            self.i += 1
        return self.lines[self.i] if self.i < len(self.lines) else None

    def block(self, indent: int):
        line = self._next()
        if line is not None and line.strip().startswith("- "):
            return self._sequence(indent)
        return self._mapping(indent)

    def _sequence(self, indent: int):
        items = []
        while (line := self._next()) is not None and _indent(line) == indent and line.strip().startswith("- "):
            rest = line.strip()[2:]
            if KEY.match(rest):
                self.lines[self.i] = " " * (indent + 2) + rest
                items.append(self._mapping(indent + 2))
            else:
                self.i += 1
                items.append(_scalar(rest))
        return items

    def _mapping(self, indent: int):
        result = {}
        while (line := self._next()) is not None and _indent(line) >= indent:
            if _indent(line) > indent or line.strip().startswith("- "):
                raise ValueError(f"line {self.i + 1} is out of place: {line.strip()}")
            match = KEY.match(line.strip())
            if not match:
                raise ValueError(f"line {self.i + 1} is not a key: {line.strip()}")
            key = line.strip().split(":", 1)[0].strip("\"'")
            value = (match.group(1) or "").strip()
            self.i += 1
            if value and value[0] in "|>":
                result[key] = self._block_scalar(indent)
            elif value and not value.startswith("#"):
                result[key] = _scalar(value)
                self._block_scalar(indent)
            else:
                following = self._next()
                deeper = following is not None and _indent(following) > indent
                result[key] = self.block(_indent(following)) if deeper else None
        return result

    def _block_scalar(self, indent: int) -> str:
        """Collect the lines of a block scalar, or the continuation lines of a plain scalar."""
        kept = []
        while self.i < len(self.lines) and (not self.lines[self.i].strip() or _indent(self.lines[self.i]) > indent):
            kept.append(self.lines[self.i].strip())
            self.i += 1
        return "\n".join(kept)


def parse(path: Path) -> dict:
    return _Parser(path.read_text(encoding="utf-8")).block(0)


def steps(job: dict) -> list:
    return job.get("steps") or []


def run_text(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in steps(job))


class WorkflowStructureTest(unittest.TestCase):
    def test_workflows_and_templates_parse_with_permissions_and_jobs(self):
        self.assertTrue(WORKFLOWS and TEMPLATES)
        for path in [*WORKFLOWS, *TEMPLATES]:
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                workflow = parse(path)
                self.assertIn("on", workflow)
                self.assertIn("permissions", workflow, "declare the token permissions at the top")
                self.assertTrue(workflow.get("jobs"))
                for name, job in workflow["jobs"].items():
                    self.assertIn("runs-on", job, name)
                    self.assertTrue(steps(job), name)
                    for step in steps(job):
                        self.assertTrue("uses" in step or "run" in step, f"{name}: {step}")

    def test_parser_refuses_misplaced_lines(self):
        with self.assertRaises(ValueError):
            _Parser("jobs:\n  a:\n    runs-on: x\n   steps: []\n").block(0)
        with self.assertRaises(ValueError):
            _Parser("on:\n\tpush: {}\n").block(0)


class PinnedActionsTest(unittest.TestCase):
    def test_every_action_is_pinned_by_commit_with_its_tag(self):
        unpinned = []
        for path in [*WORKFLOWS, *TEMPLATES]:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = USES.match(line)
                if not match or match.group(1).startswith("./"):
                    continue
                if not PINNED.match(match.group(1)) or not TAG_COMMENT.match(match.group(2)):
                    unpinned.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(unpinned, [], "pin each action to a commit SHA with '# vX.Y.Z' after it")

    def test_the_pins_of_the_workflows_and_the_github_templates_say_the_day_of_their_release(self):
        """Issue #473: a pin that says only its tag does not say how late it is."""
        undated = []
        for path in [*WORKFLOWS, *sorted((ROOT / "integrations" / "github").glob("*.yml"))]:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = USES.match(line)
                if match and not DATED_COMMENT.match(match.group(2)):
                    undated.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
        self.assertEqual(undated, [], "write '# YYYY-MM-DD vX.Y.Z' after the commit: the release day, then the tag")

    def test_workflows_and_shipped_templates_cite_one_commit_of_each_action(self):
        """Issue #473: the workflows were on actions/checkout v5.1.0 and the pilot templates on v7.0.1."""
        pins: dict[str, dict[str, list[str]]] = {}
        for path in [*WORKFLOWS, *TEMPLATES]:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = USES.match(line)
                if match and "@" in match.group(1) and not match.group(1).startswith("./"):
                    action, ref = match.group(1).split("@")
                    pins.setdefault(action, {}).setdefault(ref, []).append(path.name)
        self.assertEqual({action: refs for action, refs in pins.items() if len(refs) > 1}, {})

    def test_the_check_catches_a_tag_reference(self):
        self.assertFalse(PINNED.match("actions/checkout@v5"))
        self.assertTrue(PINNED.match("actions/checkout@" + "a" * 40))

    def test_guard_template_installs_a_release_verified_by_its_hash(self):
        text = (ROOT / "integrations" / "github" / "openguildkit-guard.yml").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"@main\b|git\+https")
        job = parse(ROOT / "integrations" / "github" / "openguildkit-guard.yml")["jobs"]["guard"]
        install = next(step for step in steps(job) if step.get("name") == "Install OpenGuildKit")
        self.assertRegex(install["env"]["OPENGUILDKIT_TAG"], r"^v\d+\.\d+\.\d+$")
        self.assertIn("OPENGUILDKIT_WHEEL_SHA256", install["env"])
        self.assertIn("releases/download/$OPENGUILDKIT_TAG/", install["run"])
        self.assertIn("sha256sum --strict -c", install["run"])


@unittest.skipIf(os.name == "nt", "the template runs on ubuntu-latest: its bash step is not run on Windows")
class RetroTemplateTest(unittest.TestCase):
    """The monthly retrospective template, its issue step run with a fake gh and the real jq."""

    TEMPLATE = ROOT / "integrations" / "github" / "openguildkit-retro.yml"
    STEP = "Open or update the retrospective issue"
    FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG"
case "$1 $2" in
    "issue list") cat "$FAKE_ISSUES" ;;
    "issue create" | "issue edit")
        while [ $# -gt 0 ]; do
            if [ "$1" = "--body-file" ]; then cat "$2" > "$FAKE_LOG.body"; fi
            shift
        done ;;
esac
"""

    def setUp(self):
        self.workflow = parse(self.TEMPLATE)
        self.job = self.workflow["jobs"]["retro"]

    def test_runs_monthly_with_a_time_limit_and_the_narrowest_permissions(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read", "issues": "write"})
        cron = self.workflow["on"]["schedule"][0]["cron"].split()
        self.assertEqual(cron[2:], ["1", "*", "*"], "once a month, on the first day")
        self.assertIn("workflow_dispatch", self.workflow["on"])
        self.assertLessEqual(int(self.job["timeout-minutes"]), 15)
        checkout = next(step for step in steps(self.job) if str(step.get("uses", "")).startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        script = run_text(self.job)
        self.assertIn("openguildkit task retro --all --json > retro.json", script)
        for writes in ("git push", "git commit", "profile ", "pull-requests"):
            self.assertNotIn(writes, script.replace("profile command", ""))

    @staticmethod
    def _month() -> str:
        """The month the step names, read the way the step reads it, with date on the runner."""
        return subprocess.run(["date", "-u", "+%Y-%m"], capture_output=True, text=True, check=True).stdout.strip()

    def _issue_step(self, recurrences, issues, tasks=4):
        temp = Path(tempfile.mkdtemp(prefix="ogk-retro-"))
        self.addCleanup(shutil.rmtree, temp, True)
        fake = temp / "bin" / "gh"
        fake.parent.mkdir()
        fake.write_text(self.FAKE_GH, encoding="utf-8")
        fake.chmod(0o755)
        (temp / "issues.json").write_text(json.dumps(issues), encoding="utf-8")
        summary = {"minimum": 3, "tasks": {"read": tasks}, "recurrences": recurrences}
        (temp / "retro.json").write_text(json.dumps(summary), encoding="utf-8")
        step = next(step for step in steps(self.job) if step.get("name") == self.STEP)
        log = temp / "gh.log"
        environment = {**os.environ, "PATH": f"{fake.parent}{os.pathsep}{os.environ['PATH']}",
                       "FAKE_LOG": str(log), "FAKE_ISSUES": str(temp / "issues.json"), "GH_TOKEN": "fake"}
        result = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=temp, env=environment, capture_output=True,
                                text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        body = (temp / "gh.log.body").read_text(encoding="utf-8") if (temp / "gh.log.body").exists() else None
        return calls, body, result.stdout

    RULE = {"kind": "rule", "label": "pack:gdpr skipped", "count": 3, "tasks": ["a", "b", "c"],
            "command": "openguildkit profile remove pack gdpr --by INITIALS --reason WHY", "needs_terminal": True,
            "also_drops": []}
    COMMITTEE = {"kind": "committee", "label": "design @someone", "count": 4, "tasks": ["a", "b", "c", "d"],
                 "command": None, "needs_terminal": False, "also_drops": []}

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash, as on the GitHub runner")
    def test_nothing_that_comes_back_opens_no_issue(self):
        calls, body, out = self._issue_step([], [])
        self.assertEqual(calls, [])
        self.assertIn("no issue", out)

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash, as on the GitHub runner")
    def test_a_recurrence_opens_one_issue_of_the_month_with_the_commands_to_type(self):
        month = self._month()
        calls, body, _ = self._issue_step([self.RULE, self.COMMITTEE], [{"number": 7, "title": "Other", "state": "OPEN"}])
        self.assertEqual([call.split(" --")[0] for call in calls], ["issue list", "issue create"])
        self.assertIn(f"--title OpenGuildKit retrospective {month}", calls[1])
        self.assertIn("pack:gdpr skipped", body)
        self.assertIn("`openguildkit profile remove pack gdpr --by INITIALS --reason WHY`", body)
        self.assertIn("interactive terminal", body)
        self.assertIn("3 tasks", body)
        self.assertNotIn("@someone", body, "a name typed in a finding must not notify anyone")
        self.assertIn("not run", body)

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash, as on the GitHub runner")
    def test_the_issue_still_open_from_an_earlier_month_is_updated_not_duplicated(self):
        month = self._month()
        calls, body, _ = self._issue_step([self.RULE], [{"number": 12, "title": "OpenGuildKit retrospective 2020-01",
                                                         "state": "OPEN"}])
        self.assertEqual([call.split(" --")[0] for call in calls], ["issue list", "issue edit 12"])
        self.assertIn(f"--title OpenGuildKit retrospective {month}", calls[1])
        self.assertIn("pack:gdpr skipped", body)

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash, as on the GitHub runner")
    def test_the_issue_of_this_month_closed_by_a_person_is_not_opened_again(self):
        month = self._month()
        calls, body, out = self._issue_step([self.RULE], [{"number": 15, "title": f"OpenGuildKit retrospective {month}",
                                                           "state": "CLOSED"}])
        self.assertEqual([call.split(" --")[0] for call in calls], ["issue list"])
        self.assertIn("#15", out)

    @unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash, as on the GitHub runner")
    def test_the_command_to_type_is_pasted_as_written_and_a_name_outside_it_stays_neutralized(self):
        """Issue #524: the command of a check with an @ carries an invisible character, and fails once pasted."""
        command = "openguildkit profile remove check 'npx @biomejs/biome check' --by NAME --reason WHY"
        finding = {**self.RULE, "kind": "check", "label": "check @biomejs skipped", "command": command}
        _, body, _ = self._issue_step([finding], [])
        typed = next(line for line in body.splitlines() if "A person may type:" in line)
        self.assertIn(f"`{command}`", typed)
        self.assertTrue(typed.isascii(), ascii(typed))
        label = next(line for line in body.splitlines() if line.startswith("- **check**"))
        self.assertIn("@\u200bbiomejs", label, "a name in a label, outside a code span, still notifies nobody")

    def test_no_shipped_github_template_holds_an_invisible_character_in_clear(self):
        """Issue #524: the template had U+200B in its source, which `host scan` reports in an instructions file."""
        invisible = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")
        for path in sorted((ROOT / "integrations" / "github").glob("*.yml")):
            with self.subTest(path=path.name):
                self.assertEqual(invisible.findall(path.read_text(encoding="utf-8")), [], "write it as \\u200b in jq")

    def test_the_workflow_guide_describes_the_template_next_to_task_retro(self):
        section = (ROOT / "docs" / "workflow" / "retrospective.md").read_text(encoding="utf-8")
        self.assertIn("integrations/github/openguildkit-retro.yml", section)
        self.assertIn("issues: write", section)


@unittest.skipUnless(os.name == "posix" and shutil.which("jq"), "the template runs bash and jq on ubuntu-latest")
class StatusTemplateTest(unittest.TestCase):
    """Issue #479: a fleet view needed a clone of every repository."""

    TEMPLATE = ROOT / "integrations" / "github" / "openguildkit-status.yml"

    def test_issue_479_each_push_keeps_the_status_of_the_repository_as_an_artifact_with_a_read_only_token(self):
        """Issue #479: the openguildkit-status.yml template did not exist, so a fleet view needed a clone of each repository."""
        workflow = parse(self.TEMPLATE)
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertIn("push", workflow["on"])
        job = workflow["jobs"]["status"]
        upload = next(step for step in steps(job) if str(step.get("uses", "")).startswith("actions/upload-artifact@"))
        self.assertEqual(upload["with"]["name"], "openguildkit-status")
        step = next(step for step in steps(job) if step.get("name") == "Read the status of the repository")
        temp = Path(tempfile.mkdtemp(prefix="ogk-status-"))
        self.addCleanup(shutil.rmtree, temp, True)
        tools = temp / "bin"
        tools.mkdir()
        (tools / "openguildkit").write_text(f'#!/bin/sh\nPYTHONPATH="{ROOT / "src"}" exec "{sys.executable}" -m '
                                            'openguildkit "$@"\n', encoding="utf-8")
        (tools / "openguildkit").chmod(0o755)
        repository = temp / "portal"
        (repository / ".claude").mkdir(parents=True)
        (repository / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        environment = {**os.environ, "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}", "REPOSITORY": "acme/portal",
                       "REVISION": "0" * 40}
        result = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", step["run"]], cwd=repository, env=environment,
                                capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads((repository / "openguildkit-status.json").read_text(encoding="utf-8"))
        self.assertEqual((status["repository"], status["revision"]), ("acme/portal", "0" * 40))
        [row] = status["projects"]
        self.assertEqual((row["state"], row["tools"]), ("not-a-project", ["claude-code"]))

    def test_issue_479_the_guide_gives_the_gh_loop_that_gathers_the_artifacts(self):
        text = (ROOT / "docs" / "workflow" / "several-projects.md").read_text(encoding="utf-8")
        section = text.split("## A fleet without clones", 1)[1].split("\n## ", 1)[0]
        self.assertIn("integrations/github/openguildkit-status.yml", section)
        self.assertIn("gh run download", section)


class ReleaseWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = parse(ROOT / ".github" / "workflows" / "release.yml")
        self.jobs = self.workflow["jobs"]

    def test_runs_on_version_tags_with_the_narrowest_permissions(self):
        self.assertEqual(self.workflow["on"], {"push": {"tags": ["v*"]}})
        self.assertEqual(self.workflow["permissions"], {})
        self.assertEqual(self.jobs["build"]["permissions"], {"contents": "read"})
        self.assertEqual(self.jobs["publish"]["permissions"], {"contents": "write"})

    def test_builds_the_three_assets_from_the_tagged_commit(self):
        build = self.jobs["build"]
        checkout = next(step for step in steps(build) if str(step.get("uses", "")).startswith("actions/checkout@"))
        self.assertEqual(checkout["with"]["persist-credentials"], "false")
        self.assertNotIn("ref", checkout["with"], "check out the tag that triggered the run")
        script = run_text(build)
        for command in ("python -m build --wheel", "npm pack ./integrations/ci", "sha256sum", "SHA256SUMS.txt"):
            self.assertIn(command, script)
        self.assertIn("GITHUB_REF_NAME", script, "refuse a tag that does not match the versions")

    def test_publish_job_holds_the_write_token_without_running_project_code(self):
        publish = self.jobs["publish"]
        self.assertEqual(publish["needs"], ["build", "attest"])
        actions = [str(step["uses"]) for step in steps(publish) if "uses" in step]
        self.assertEqual([action.split("@")[0] for action in actions], ["actions/download-artifact"])
        for step in steps(publish):
            self.assertNotIn("token", step.get("with") or {})
        script = run_text(publish)
        self.assertIn("gh release upload", script)
        for name in ("openguildkit-$VERSION-py3-none-any.whl", "openguildkit-$VERSION.tgz", "SHA256SUMS.txt"):
            self.assertIn(name, script)

    def test_install_guide_describes_what_the_workflow_builds(self):
        build = self.jobs["build"]
        python = next(s for s in steps(build) if "setup-python" in str(s.get("uses")))["with"]["python-version"]
        node = next(s for s in steps(build) if "setup-node" in str(s.get("uses")))["with"]["node-version"]
        guide = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
        section = guide.split("## How the release assets are built", 1)[1].split("\n## ", 1)[0]
        for fact in (f"Python {python}", f"Node.js {node}", "`.github/workflows/release.yml`", "SHA256SUMS.txt",
                     "`sha256sum`", build["runs-on"], "draft"):
            self.assertIn(fact, section)

    def test_governance_lists_the_release_steps(self):
        text = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        section = text.split("## Releases", 1)[1].split("\n## ", 1)[0]
        steps_listed = re.findall(r"^\d+\. ", section, re.MULTILINE)
        self.assertGreaterEqual(len(steps_listed), 5)
        for fact in ("git tag", "release.yml", "SHA256SUMS.txt", "pyproject.toml", "package.json"):
            self.assertIn(fact, section)


def _constraints() -> dict[str, str]:
    """The exact versions of .github/build-constraints.txt, by normalised name."""
    text = (ROOT / ".github" / "build-constraints.txt").read_text(encoding="utf-8")
    return {name.lower().replace("-", "_"): version for name, version in re.findall(r"^([\w.-]+)==(\S+)$", text, re.M)}


class ReleaseProvenanceTest(unittest.TestCase):
    """Issue #503: the release says where its files come from, and a third party can rebuild the wheel."""

    def setUp(self):
        self.workflow = parse(ROOT / ".github" / "workflows" / "release.yml")
        self.jobs = self.workflow["jobs"]

    def test_only_the_attest_job_can_mint_an_identity_token(self):
        """Issue #503: no attestation of the build; the identity token belongs to one job without project code."""
        for name, job in self.jobs.items():
            granted = set(job["permissions"]) & {"id-token", "attestations"}
            self.assertEqual(granted, {"id-token", "attestations"} if name == "attest" else set(), name)
        attest = self.jobs["attest"]
        self.assertEqual(attest["permissions"], {"contents": "read", "id-token": "write", "attestations": "write"})
        self.assertEqual(attest["needs"], "build")
        self.assertEqual(self.jobs["publish"]["needs"], ["build", "attest"], "nothing is attached without its attestation")
        self.assertEqual([str(step["uses"]).split("@")[0] for step in steps(attest)],
                         ["actions/download-artifact", "actions/attest"])
        self.assertEqual(run_text(attest).strip(), "", "the job that holds the identity token runs no project code")

    def test_every_file_of_the_release_is_a_subject_of_the_attestation(self):
        """Issue #503: the attestation covers the wheel, the archive, both installers, the SBOM and the hashes."""
        attest = next(step for step in steps(self.jobs["attest"]) if "attest@" in str(step["uses"]))
        self.assertEqual(attest["with"]["subject-path"], "release/*")
        fetched = next(step for step in steps(self.jobs["attest"]) if "download-artifact@" in str(step["uses"]))
        self.assertEqual((fetched["with"]["name"], fetched["with"]["path"]), ("release-assets", "release"))

    def test_the_wheel_is_dated_by_its_commit_and_built_with_pinned_tools(self):
        """Issue #503: the wheel depends on the date of the sources and on build tools that float."""
        build = self.jobs["build"]
        listed = steps(build)
        names = [step.get("name") for step in listed]
        epoch = next(step for step in listed if "SOURCE_DATE_EPOCH" in str(step.get("run")))
        self.assertIn("git log -1 --format=%ct", epoch["run"])
        self.assertIn("GITHUB_ENV", epoch["run"])
        self.assertLess(listed.index(epoch), names.index("Build the wheel"))
        self.assertEqual(build["env"]["PIP_CONSTRAINT"], "${{ github.workspace }}/.github/build-constraints.txt")
        self.assertTrue({"build", "setuptools", "packaging", "pyproject_hooks"} <= set(_constraints()))
        python = next(step for step in listed if "setup-python" in str(step.get("uses")))["with"]["python-version"]
        matrix = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["test"]["strategy"]["matrix"]["python"]
        self.assertIn(python, matrix, "build with a Python the tests run on")

    def test_the_setuptools_the_wheel_is_built_with_is_the_one_pinned(self):
        """Issue #503: the Generator line of the wheel names the setuptools of the day."""
        floor = next(re.search(r"setuptools>=([\d.]+)", line)[1] for line in
                     (ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines() if "setuptools>=" in line)
        pinned = tuple(int(part) for part in _constraints()["setuptools"].split("."))
        self.assertGreaterEqual(pinned, tuple(int(part) for part in floor.split(".")))

    def test_a_second_build_must_give_the_same_wheel_before_anything_is_attached(self):
        """Issue #503: two builds of one commit were not compared."""
        build = self.jobs["build"]
        names = [step.get("name") for step in steps(build)]
        second = next(step for step in steps(build) if step.get("name") == "Check that a second build gives the same wheel")
        for command in ("python -m build --wheel --outdir", "sha256sum", 'test "$first" = "$second"', "touch"):
            self.assertIn(command, second["run"])
        self.assertLess(names.index("Build the wheel"), names.index(second["name"]))
        self.assertLess(names.index(second["name"]), names.index("Build the Node archive, add the installers, then write the hashes of the assets"))

    def test_the_release_carries_the_cyclonedx_sbom_with_its_hash(self):
        """Issue #503: no SBOM of the web interface the wheel embeds."""
        build, publish = run_text(self.jobs["build"]), run_text(self.jobs["publish"])
        self.assertIn("python scripts/make_sbom.py --lock web/package-lock.json", build)
        sums = next(line for line in build.splitlines() if line.startswith("sha256sum "))
        self.assertIn('"openguildkit-$version.cdx.json"', sums)
        self.assertIn('"openguildkit-$VERSION.cdx.json"', publish.split("gh release upload", 1)[1])

    def test_the_release_check_verifies_every_attestation_and_installs_without_an_index(self):
        """Issue #503: nothing replays gh attestation verify, nor the offline installation of docs/install.md."""
        path = ROOT / ".github" / "workflows" / "release-check.yml"
        script = run_text(parse(path)["jobs"]["install"])
        for fact in ("gh attestation verify", '--repo "$GITHUB_REPOSITORY"', "--signer-workflow", "--source-ref",
                     "--no-index", "release.yml"):
            self.assertIn(fact, script)
        self.assertIn('--pattern "openguildkit-$VERSION.cdx.json"', path.read_text(encoding="utf-8"))
        manual = parse(path)["on"]["workflow_dispatch"]["inputs"]["attestations"]
        self.assertEqual(manual["default"], "true", "a manual run of a release that predates attestations says so")


class PackageJobTest(unittest.TestCase):
    """Issue #474: the wheel and its web interface were built five times, once by each job that installs it."""

    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]

    def test_the_wheel_is_built_once_on_ubuntu_and_handed_on_as_an_artifact(self):
        wheel = self.jobs["wheel"]
        self.assertEqual(wheel["runs-on"], "ubuntu-latest")
        self.assertNotIn("strategy", wheel)
        script = run_text(wheel)
        for command in ("npm ci --ignore-scripts", "npm run build", "npm run bundle", "python -m build"):
            self.assertIn(command, script)
        upload = next(step for step in steps(wheel) if "upload-artifact" in str(step.get("uses")))
        self.assertEqual(upload["with"]["path"], "dist/*.whl")
        self.assertEqual(upload["with"]["if-no-files-found"], "error")
        for name, job in self.jobs.items():
            if name != "wheel":
                self.assertNotIn("python -m build", run_text(job), f"{name} builds a wheel of its own")

    def test_the_wheel_is_installed_on_three_systems_and_the_python_bounds_without_being_built_again(self):
        job = self.jobs["package"]
        self.assertEqual(job["needs"], "wheel")
        matrix = job["strategy"]["matrix"]
        self.assertEqual(set(matrix["os"]), {"ubuntu-latest", "macos-latest", "windows-latest"})
        self.assertEqual({"3.11", "3.15"}, set(matrix["python"]))
        setup = next(s for s in steps(job) if "setup-python" in str(s.get("uses")))
        self.assertEqual(setup["with"]["python-version"], "${{ matrix.python }}")
        upload = next(step for step in steps(self.jobs["wheel"]) if "upload-artifact" in str(step.get("uses")))
        download = next(step for step in steps(job) if "download-artifact" in str(step.get("uses")))
        self.assertEqual(download["with"], {"name": upload["with"]["name"], "path": "dist"})
        script = run_text(job)
        self.assertIn("pip install dist/*.whl", script)
        for built in ("npm ", "python -m build", "twine"):
            self.assertNotIn(built, script)
        self.assertFalse([step for step in steps(job) if "setup-node" in str(step.get("uses"))], "no Node to install a wheel")


class PerformanceJobTest(unittest.TestCase):
    def test_the_benchmarks_time_the_catalog_bundle_the_wheel_ships(self):
        """Issue #533: the performance job timed the 289 catalog record files, which an installed wheel does not read."""
        job = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["performance"]
        commands = [step.get("run", "") for step in steps(job)]
        measured = next(index for index, command in enumerate(commands) if "tests.test_performance" in command)
        self.assertIn("python scripts/build_catalog_bundle.py", commands[:measured])


# A matrix key whose value is an expression: the list it gives when the event is the one named, [] otherwise.
EVENT_LIST = re.compile(r"\$\{\{ fromJSON\(github\.event_name == '(\w+)' && '(\[.*\])' \|\| '\[\]'\) \}\}")


def matrix_jobs(job: dict, event: str = "push") -> list[dict]:
    """The combinations a job's matrix runs for an event: the product of its lists, less its excludes (no include is used)."""
    matrix = dict(job["strategy"]["matrix"])
    excluded = matrix.pop("exclude", None) or []
    if isinstance(excluded, str):
        named, listed = EVENT_LIST.fullmatch(excluded).groups()
        excluded = json.loads(listed) if event == named else []
    combinations = [{}]
    for key, values in matrix.items():
        combinations = [{**combination, key: value} for combination in combinations for value in values]
    return [c for c in combinations if not any(all(c.get(k) == v for k, v in rule.items()) for rule in excluded)]


class MacosRunnersTest(unittest.TestCase):
    """Each macOS job of a CI run waits for a hosted macOS runner, which can take minutes or never come."""

    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]

    def macos(self, name, event="push"):
        job = self.jobs[name]
        if "matrix" not in job.get("strategy", {}):
            return [{}] if job["runs-on"] == "macos-latest" else []
        return [c for c in matrix_jobs(job, event) if c.get("os") == "macos-latest"]

    def test_a_push_places_at_most_four_jobs_on_macos(self):
        self.assertEqual([c["python"] for c in self.macos("test")], ["3.11", "3.15"])
        self.assertEqual(len(self.macos("package")), 1)
        self.assertEqual(sum(len(self.macos(name)) for name in self.jobs), 4)
        for name in ("test", "package"):
            linux = [c for c in matrix_jobs(self.jobs[name]) if c["os"] == "ubuntu-latest"]
            self.assertEqual(len(linux), len(self.jobs[name]["strategy"]["matrix"]["python"]), name)

    def test_a_pull_request_places_three(self):
        self.assertEqual([c["python"] for c in self.macos("test", "pull_request")], ["3.15"])
        self.assertEqual(sum(len(self.macos(name, "pull_request")) for name in self.jobs), 3)

    def test_the_matrix_reader_applies_the_excludes(self):
        job = {"strategy": {"matrix": {"os": ["a", "b"], "python": ["1", "2"], "exclude": [{"os": "b", "python": "1"}]}}}
        self.assertEqual(matrix_jobs(job), [{"os": "a", "python": "1"}, {"os": "a", "python": "2"},
                                            {"os": "b", "python": "2"}])
        job["strategy"]["matrix"]["exclude"] = ("${{ fromJSON(github.event_name == 'pull_request' && "
                                                "'[{\"os\":\"b\",\"python\":\"1\"}]' || '[]') }}")
        self.assertEqual(len(matrix_jobs(job, "pull_request")), 3)
        self.assertEqual(len(matrix_jobs(job, "push")), 4)


class ContributionChecksTest(unittest.TestCase):
    """The gate tells a job that never got a runner from a job that failed, and says to rerun the first."""

    def setUp(self):
        self.gate = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["contribution-checks"]
        self.step = steps(self.gate)[0]
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)

    def run_gate(self, results: dict, jobs: list) -> subprocess.CompletedProcess:
        bash, jq = shutil.which("bash"), shutil.which("jq")
        if os.name == "nt" or not bash or not jq:
            self.skipTest("The gate's script needs bash and jq, as on the GitHub runner.")
        (self.directory / "jobs.json").write_text(json.dumps({"jobs": jobs}), encoding="utf-8")
        # A stand-in for gh api: logs the call and applies its --jq filter to the jobs of the run.
        gh = self.directory / "gh"
        gh.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$GH_LOG"\n'
                      'while [ $# -gt 0 ]; do [ "$1" = --jq ] && filter="$2"; shift; done\n'
                      'exec jq -r "$filter" "$JOBS"\n', encoding="utf-8")
        gh.chmod(0o755)
        environment = {**os.environ, "PATH": f"{self.directory}{os.pathsep}{os.environ['PATH']}",
                       "JOBS": str(self.directory / "jobs.json"), "GH_LOG": str(self.directory / "gh.log"),
                       "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1"}
        for variable, value in self.step["env"].items():
            job = re.search(r"needs\.([\w-]+)\.result", value)
            environment[variable] = results.get(job.group(1), "success") if job else "token"
        return subprocess.run([bash, "-e", "-c", self.step["run"]], env=environment, capture_output=True, text=True)

    def test_the_gate_reads_the_jobs_of_its_run_with_a_read_only_token(self):
        self.assertEqual(self.gate["permissions"], {"actions": "read"})
        self.assertEqual(self.step["env"]["GH_TOKEN"], "${{ github.token }}")

    def test_a_job_that_never_got_a_runner_is_named_with_the_advice_to_rerun_it(self):
        jobs = [{"name": "Python 3.11 on macos-latest", "conclusion": "cancelled", "steps": [], "runner_name": ""},
                {"name": "Python 3.11 on ubuntu-latest", "conclusion": "success", "steps": [{"name": "x"}]}]
        result = self.run_gate({"test": "cancelled"}, jobs)
        self.assertEqual(result.returncode, 1)
        self.assertIn("never started", result.stdout)
        self.assertIn("Python 3.11 on macos-latest", result.stdout)
        self.assertIn("Re-run failed jobs", result.stdout)
        self.assertIn("runs/7/attempts/1/jobs", (self.directory / "gh.log").read_text(encoding="utf-8"))

    def test_a_failed_job_is_not_called_a_missing_runner(self):
        jobs = [{"name": "Python 3.15 on windows-latest", "conclusion": "failure", "steps": [{"name": "Install"}]},
                {"name": "Web app", "conclusion": "cancelled", "steps": [{"name": "npm test"}]}]
        result = self.run_gate({"test": "failure", "web": "cancelled"}, jobs)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("never started", result.stdout)
        self.assertIn("Details", result.stdout)

    def test_contributing_describes_both_kinds_of_cancelled_jobs(self):
        text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        section = text.split("## Open a pull request", 1)[1].split("\n## ", 1)[0]
        for words in ("No runner picked the job up", "These jobs never started", "Re-run failed jobs",
                      "You pushed again", "cancels the run of the previous commit", "3.11 and 3.15 on Linux, macOS and Windows"):
            self.assertIn(words, section)

    def test_a_job_the_path_filter_skipped_counts_as_passed_when_the_filter_itself_ran(self):
        """Issue #474: `contribution-checks` must pass on a pull request that only touches docs/."""
        for job in ("ci-coordinator", "web", "web-e2e"):
            with self.subTest(job=job):
                passed = self.run_gate({job: "skipped"}, [])
                self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
                failed = self.run_gate({job: "skipped", "changes": "failure"}, [])
                self.assertEqual(failed.returncode, 1, "a job skipped because the filter failed is not a pass")

    def test_the_jobs_the_filter_does_not_govern_must_succeed(self):
        for job in ("changes", "test", "performance", "wheel", "package"):
            for result in ("skipped", "cancelled", "failure"):
                with self.subTest(job=job, result=result):
                    self.assertEqual(self.run_gate({job: result}, []).returncode, 1)

    def test_every_job_passed(self):
        result = self.run_gate({}, [])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.directory / "gh.log").exists())


if __name__ == "__main__":
    unittest.main()
