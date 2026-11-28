"""The release workflow: its jobs, the provenance of what it publishes and the PyPI and image channels, off until the
maintainer turns them on."""

import re
import unittest

from tests.test_workflows import ROOT, parse, run_text, steps


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
        """Issue #503: no attestation of the build; the identity token belongs to the jobs without project code
        (the PyPI job only uploads the wheel the build job made, see ReleaseChannelsTest)."""
        expected = {"attest": {"id-token", "attestations"}, "pypi": {"id-token"}}
        for name, job in self.jobs.items():
            granted = set(job["permissions"]) & {"id-token", "attestations"}
            self.assertEqual(granted, expected.get(name, set()), name)
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


class ReleaseChannelsTest(unittest.TestCase):
    """Issue #503: PyPI, the container image, Homebrew and winget are ready for the maintainer and off until set up."""

    def setUp(self):
        self.jobs = parse(ROOT / ".github" / "workflows" / "release.yml")["jobs"]

    def test_each_publishing_job_runs_only_when_its_repository_variable_says_true(self):
        """Issue #503: publishing needs an account only the maintainer can create; nothing runs before that."""
        self.assertEqual(self.jobs["pypi"]["if"], "vars.PYPI_PUBLISH == 'true'")
        self.assertEqual(self.jobs["image"]["if"], "vars.GHCR_PUBLISH == 'true'")
        for name in ("build", "attest", "publish"):
            self.assertNotIn("if", self.jobs[name], name)
        for name in ("pypi", "image"):
            self.assertEqual(self.jobs[name]["needs"], ["build", "attest"], f"{name}: only attested files go out")
            self.assertIn("timeout-minutes", self.jobs[name])

    def test_pypi_uploads_the_attested_wheel_by_trusted_publishing_without_a_secret(self):
        """Issue #503: PyPI by OIDC, with the wheel the build job attested, not a wheel built again."""
        pypi = self.jobs["pypi"]
        self.assertEqual(pypi["permissions"], {"id-token": "write"})
        self.assertEqual(pypi["environment"]["name"], "pypi")
        self.assertEqual(run_text(pypi).strip(), "", "the job that holds the identity token runs no command")
        fetched, publish = steps(pypi)
        self.assertTrue(str(fetched["uses"]).startswith("actions/download-artifact@"))
        self.assertEqual((fetched["with"]["name"], fetched["with"]["path"]), ("wheel", "dist"))
        self.assertTrue(str(publish["uses"]).startswith("pypa/gh-action-pypi-publish@"))
        self.assertEqual(publish["with"], {"packages-dir": "dist/"})
        upload = next(step for step in steps(self.jobs["build"])
                      if "upload-artifact@" in str(step.get("uses")) and step["with"]["name"] == "wheel")
        self.assertEqual(upload["with"]["path"], "release/openguildkit-*-py3-none-any.whl")
        text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertNotIn("secrets.", text, "trusted publishing needs no token")

    def test_the_image_installs_the_attested_wheel_runs_as_a_user_and_pushes_to_ghcr(self):
        """Issue #503: no container image; the job pushes with the token of the run and the image runs as a user."""
        image = self.jobs["image"]
        self.assertEqual(image["permissions"], {"contents": "read", "packages": "write"})
        build, push = (step for step in steps(image) if "run" in step)
        self.assertIn("docker build", build["run"])
        self.assertIn("--version", build["run"], "the image starts before it is pushed")
        self.assertNotIn("env", build, "the build and the smoke test run without the token")
        self.assertEqual(push["env"]["GH_TOKEN"], "${{ github.token }}")
        self.assertIn("--password-stdin", push["run"])
        self.assertIn("ghcr.io/", push["run"])
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"(?m)^FROM python:3\.\d+-slim@sha256:[0-9a-f]{64}$")
        self.assertRegex(dockerfile, r"(?m)^# \d{4}-\d{2}-\d{2} ", "date the digest of the base image")
        self.assertIn("--no-index", dockerfile)
        self.assertRegex(dockerfile, r"(?m)^USER (?!root)\w+$")
        self.assertIn('ENTRYPOINT ["openguildkit"]', dockerfile)

    def test_the_release_steps_and_the_install_guide_say_the_channels_are_ready_and_not_published(self):
        """Issue #503: the maintainer needs the one step that turns each channel on, and a user what exists today."""
        section = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8").split("## Releases", 1)[1].split("\n## ", 1)[0]
        for fact in ("PYPI_PUBLISH", "GHCR_PUBLISH", "environment `pypi`", "scripts/release_manifests.py",
                     "packaging/homebrew/openguildkit.rb", "packaging/winget/", "read 2026-11-28"):
            self.assertIn(fact, section)
        guide = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
        channels = guide.split("## Package managers", 1)[1].split("\n## ", 1)[0]
        for fact in ("none of them is published yet", "PYPI_PUBLISH", "GHCR_PUBLISH", "Dockerfile",
                     "scripts/release_manifests.py", "winget installs an executable"):
            self.assertIn(fact, channels)
