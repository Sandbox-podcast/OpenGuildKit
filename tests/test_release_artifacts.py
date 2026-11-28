"""Release artifacts: the SBOM of the wheel and the web interface, and the Homebrew and winget manifests filled from
SHA256SUMS.txt."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_release import ROOT, _read

MAKE_SBOM = ROOT / "scripts" / "make_sbom.py"
RELEASE_MANIFESTS = ROOT / "scripts" / "release_manifests.py"


def run_sbom(*arguments: str, env=None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(MAKE_SBOM), *arguments], capture_output=True, text=True,
                          encoding="utf-8", timeout=60, check=False, env={**os.environ, **(env or {})})


LOCK = {"lockfileVersion": 3, "packages": {
    "": {"name": "web", "dependencies": {"react": "^19.0.0", "@scope/font": "^1.0.0"}},
    "node_modules/react": {"version": "19.3.1", "integrity": "sha512-" + "QUJD" * 21 + "QQ==", "license": "MIT"},
    "node_modules/@scope/font": {"version": "1.2.3", "integrity": "sha512-" + "QUJD" * 21 + "QQ==",
                                 "license": "(OFL-1.1 OR MIT)"},
    "node_modules/react/node_modules/scheduler": {"version": "0.28.0", "optional": True},
    "node_modules/vite": {"version": "8.0.0", "dev": True, "integrity": "sha512-" + "QUJD" * 21 + "QQ=="},
    "node_modules/fsevents": {"version": "2.3.3", "dev": True, "optional": True},
    "node_modules/esbuild-helper": {"version": "1.0.0", "devOptional": True},
    "node_modules/linked": {"resolved": "../linked", "link": True},
}}


class SbomTest(unittest.TestCase):
    """Issue #503: the release has no SBOM of the web interface its wheel embeds."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="ogk-sbom-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.wheel = self.temp / "openguildkit-9.9.9-py3-none-any.whl"
        self.wheel.write_bytes(b"wheel bytes")

    def sbom(self, lock: dict, **env) -> dict:
        path = self.temp / "package-lock.json"
        path.write_text(json.dumps(lock), encoding="utf-8")
        done = run_sbom("--lock", str(path), "--wheel", str(self.wheel), env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_lists_the_runtime_packages_with_their_versions_and_leaves_the_development_ones(self):
        """Issue #503: the SBOM lists react and the other runtime packages, not vite or fsevents."""
        bom = self.sbom(LOCK)
        self.assertEqual((bom["bomFormat"], bom["specVersion"]), ("CycloneDX", "1.5"))
        found = {component["purl"]: component["version"] for component in bom["components"]}
        self.assertEqual(found, {"pkg:npm/react@19.3.1": "19.3.1", "pkg:npm/%40scope/font@1.2.3": "1.2.3",
                                 "pkg:npm/scheduler@0.28.0": "0.28.0"})

    def test_a_component_carries_its_group_hash_and_licence(self):
        font = next(component for component in self.sbom(LOCK)["components"] if component["name"] == "font")
        self.assertEqual(font["group"], "@scope")
        self.assertEqual(font["bom-ref"], font["purl"])
        self.assertEqual(font["hashes"], [{"alg": "SHA-512", "content": (b"ABC" * 21 + b"A").hex()}])
        self.assertEqual(font["licenses"], [{"expression": "(OFL-1.1 OR MIT)"}])
        react = next(component for component in self.sbom(LOCK)["components"] if component["name"] == "react")
        self.assertEqual(react["licenses"], [{"license": {"id": "MIT"}}])

    def test_the_main_component_is_the_wheel_with_its_sha256(self):
        main = self.sbom(LOCK)["metadata"]["component"]
        self.assertEqual((main["name"], main["version"]), ("openguildkit", "9.9.9"))
        self.assertEqual(main["hashes"], [{"alg": "SHA-256", "content": hashlib.sha256(b"wheel bytes").hexdigest()}])

    def test_the_same_inputs_give_the_same_bytes_when_the_date_is_fixed(self):
        first = self.sbom(LOCK, SOURCE_DATE_EPOCH="1795000000")
        second = self.sbom(LOCK, SOURCE_DATE_EPOCH="1795000000")
        self.assertEqual(first, second)
        self.assertEqual(first["metadata"]["timestamp"], "2026-11-18T11:06:40Z")
        self.assertRegex(first["serialNumber"], r"^urn:uuid:[0-9a-f-]{36}$")
        self.assertNotEqual(first["serialNumber"], self.sbom({**LOCK, "packages": {}}, SOURCE_DATE_EPOCH="1795000000")["serialNumber"])

    def test_a_lock_without_the_packages_table_is_refused(self):
        path = self.temp / "old-lock.json"
        path.write_text(json.dumps({"lockfileVersion": 1, "dependencies": {}}), encoding="utf-8")
        done = run_sbom("--lock", str(path), "--wheel", str(self.wheel))
        self.assertEqual(done.returncode, 1)
        self.assertIn("lockfile version 2 or 3", done.stderr)

    def test_the_real_lock_lists_every_runtime_dependency_of_the_web_interface(self):
        """Issue #503: the acceptance criterion, on web/package-lock.json."""
        direct = json.loads(_read("web/package.json"))["dependencies"]
        lock = json.loads(_read("web/package-lock.json"))["packages"]
        done = run_sbom("--lock", str(ROOT / "web" / "package-lock.json"), "--wheel", str(self.wheel))
        self.assertEqual(done.returncode, 0, done.stderr)
        components = {(c.get("group", "") + "/" if c.get("group") else "") + c["name"]: c["version"]
                      for c in json.loads(done.stdout)["components"]}
        for name in direct:
            self.assertEqual(components[name], lock[f"node_modules/{name}"]["version"], name)
        self.assertIn("react", components)
        for development in json.loads(_read("web/package.json"))["devDependencies"]:
            self.assertNotIn(development, components)


WHEEL_SHA, ZIP_SHA = "a" * 64, "b" * 64
SUMS = (f"{WHEEL_SHA}  openguildkit-9.8.7-py3-none-any.whl\n{'c' * 64}  openguildkit-9.8.7.tgz\n"
        f"{'d' * 64}  openguildkit-9.8.7.cdx.json\n{'e' * 64}  install.sh\n{'f' * 64}  install.ps1\n")


class ReleaseManifestsTest(unittest.TestCase):
    """Issue #503: OpenGuildKit is on no package manager; the Homebrew formula and winget manifests come from the
    SHA256SUMS.txt of a release, so the maintainer publishes them without copying a hash by hand."""

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="ogk-manifests-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.out = self.temp / "out"

    def fill(self, sums: str, *extra: str) -> subprocess.CompletedProcess:
        (self.temp / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
        return subprocess.run([sys.executable, "-I", str(RELEASE_MANIFESTS), "--sums", str(self.temp / "SHA256SUMS.txt"),
                               "--output", str(self.out), *extra], capture_output=True, text=True, encoding="utf-8",
                              timeout=60, check=False)

    def test_the_formula_gets_the_url_and_sha256_of_the_wheel_of_the_release(self):
        """Issue #503: the Homebrew formula is filled from the release manifest, with nothing left to fill."""
        done = self.fill(SUMS)
        self.assertEqual(done.returncode, 0, done.stderr)
        formula = (self.out / "homebrew" / "openguildkit.rb").read_text(encoding="utf-8")
        url = "https://github.com/Sandbox-podcast/OpenGuildKit/releases/download/v9.8.7/openguildkit-9.8.7-py3-none-any.whl"
        self.assertIn(f'url "{url}", using: :nounzip', formula)
        self.assertIn(f'sha256 "{WHEEL_SHA}"', formula)
        self.assertIn('version "9.8.7"', formula)
        self.assertNotRegex(formula, r"@[A-Z_]+@")
        template = _read("packaging/homebrew/openguildkit.rb")
        for fact in ("include Language::Python::Virtualenv", 'depends_on "python@3', "virtualenv_create(libexec",
                     "pip_install_and_link", "openguildkit --version"):
            self.assertIn(fact, template)

    def test_winget_manifests_need_the_windows_archive_and_are_filled_when_the_release_has_it(self):
        """Issue #503: winget installs an executable, not a wheel; without a Windows archive the script says so."""
        done = self.fill(SUMS)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Warning: winget:", done.stderr)
        self.assertIn("openguildkit-9.8.7-windows-x64.zip", done.stderr)
        self.assertFalse((self.out / "winget").exists())
        done = self.fill(SUMS + f"{ZIP_SHA}  openguildkit-9.8.7-windows-x64.zip\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        folder = self.out / "winget" / "manifests" / "s" / "SandboxPodcast" / "OpenGuildKit" / "9.8.7"
        names = sorted(path.name for path in folder.iterdir())
        self.assertEqual(names, ["SandboxPodcast.OpenGuildKit.installer.yaml", "SandboxPodcast.OpenGuildKit.locale.en-US.yaml",
                                 "SandboxPodcast.OpenGuildKit.yaml"])
        installer = (folder / "SandboxPodcast.OpenGuildKit.installer.yaml").read_text(encoding="utf-8")
        self.assertIn("InstallerUrl: https://github.com/Sandbox-podcast/OpenGuildKit/releases/download/v9.8.7/"
                      "openguildkit-9.8.7-windows-x64.zip", installer)
        self.assertIn(f"InstallerSha256: {ZIP_SHA.upper()}", installer)
        for path in folder.iterdir():
            text = path.read_text(encoding="utf-8")
            self.assertIn("PackageVersion: 9.8.7", text, path.name)
            self.assertIn("ManifestVersion: 1.28.0", text, path.name)
            self.assertIn("manifest.", text.splitlines()[0], "the schema line editors read")
            self.assertNotRegex(text, r"@[A-Z_]+@", path.name)

    def test_a_manifest_without_the_wheel_or_with_a_wrong_hash_is_refused(self):
        done = self.fill(SUMS.replace("openguildkit-9.8.7-py3-none-any.whl", "other.whl"))
        self.assertEqual(done.returncode, 1)
        self.assertIn("no openguildkit-X.Y.Z-py3-none-any.whl", done.stderr)
        done = self.fill(SUMS.replace(WHEEL_SHA, "z" * 64))
        self.assertEqual(done.returncode, 1)
        self.assertFalse(self.out.exists(), "nothing is written from a manifest the script refuses")

    def test_another_repository_changes_every_url(self):
        done = self.fill(SUMS, "--repository", "example/fork")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("https://github.com/example/fork/releases/download/v9.8.7/",
                      (self.out / "homebrew" / "openguildkit.rb").read_text(encoding="utf-8"))
