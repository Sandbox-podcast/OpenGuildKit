"""The GitHub workflows and the templates the project ships: structure, pinned actions, release assets.

GitHub Actions cannot run here, so these tests read the YAML with a small parser for the subset the
workflows use (block mappings and lists, flow lists, block scalars) and check what a reviewer would.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
TEMPLATES = sorted([*(ROOT / "integrations" / "github").glob("*.yml"), *(ROOT / "integrations" / "ci").rglob("*.yml")])
USES = re.compile(r"^\s*(?:- )?uses:\s*(\S+)(.*)$")
PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
TAG_COMMENT = re.compile(r"^ # v\d+\.\d+\.\d+$")
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
        self.assertEqual(publish["needs"], "build")
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


class PackageJobTest(unittest.TestCase):
    def test_wheel_is_built_and_installed_on_three_systems_and_the_python_bounds(self):
        job = parse(ROOT / ".github" / "workflows" / "ci.yml")["jobs"]["package"]
        matrix = job["strategy"]["matrix"]
        self.assertEqual(set(matrix["os"]), {"ubuntu-latest", "macos-latest", "windows-latest"})
        self.assertLessEqual({"3.11", "3.14"}, set(matrix["python"]))
        setup = next(s for s in steps(job) if "setup-python" in str(s.get("uses")))
        self.assertEqual(setup["with"]["python-version"], "${{ matrix.python }}")
        script = run_text(job)
        self.assertIn("python -m build", script)
        self.assertIn("pip install dist/*.whl", script)


if __name__ == "__main__":
    unittest.main()
