"""The one-line installers, scripts/install.sh and scripts/install.ps1, run against a fake release in a local folder.

No network: OPENGUILDKIT_RELEASES_URL points the script at a file:// folder laid out as GitHub serves a release
(`latest/download/ASSET` and `download/vX.Y.Z/ASSET`), and pipx and uv are small fakes on a PATH that holds
only the tools the script uses. install.ps1 runs only where PowerShell (pwsh) is installed; elsewhere only its
structure is checked.
"""

import contextlib
import functools
import hashlib
import http.server
import os
import re
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from tests.test_workflows import parse, run_text, steps

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "scripts" / "install.sh"
PS1 = ROOT / "scripts" / "install.ps1"
LINE = "curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.sh | sh"
PS_LINE = "irm https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.ps1 | iex"
TOOLS = ("curl", "grep", "head", "cut", "tr", "sed", "mktemp", "rm", "cat", "sha256sum", "shasum", "openssl", "perl")
FAKE = """#!/bin/sh
printf '%s %s\\n' "${0##*/}" "$*" >> "$FAKE_LOG"
for argument in "$@"; do
    case "$argument" in *.whl) cat "$argument" > "$FAKE_LOG.whl" ;; esac
done
exit "${FAKE_EXIT:-0}"
"""
# The same fake for PowerShell on Windows, which cannot start a sh script: pwsh finds NAME.ps1 on the PATH.
FAKE_PS1 = """$name = [IO.Path]::GetFileNameWithoutExtension($PSCommandPath)
Add-Content -LiteralPath $env:FAKE_LOG -Value ("$name " + ($args -join ' '))
foreach ($argument in $args) {
    if ("$argument" -like '*.whl') { Copy-Item -LiteralPath "$argument" -Destination "$($env:FAKE_LOG).whl" }
}
exit [int]($(if ($env:FAKE_EXIT) { $env:FAKE_EXIT } else { 0 }))
"""


def wheel_name(version: str) -> str:
    return f"openguildkit-{version}-py3-none-any.whl"


class FakeRelease:
    """A folder laid out as github.com/OWNER/REPO/releases, with a latest release and older ones."""

    def __init__(self, root: Path, latest: str, others=(), tamper=()):
        self.root = root / "releases"
        for version in (latest, *others):
            folder = self.root / "download" / f"v{version}"
            folder.mkdir(parents=True)
            content = f"wheel of {version}".encode()
            (folder / wheel_name(version)).write_bytes(content)
            digest = hashlib.sha256(b"something else" if version in tamper else content).hexdigest()
            sums = f"{digest}  {wheel_name(version)}\n{'0' * 64}  openguildkit-{version}.tgz\n"
            (folder / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
        latest_folder = self.root / "latest" / "download"
        latest_folder.mkdir(parents=True)
        shutil.copy(self.root / "download" / f"v{latest}" / "SHA256SUMS.txt", latest_folder / "SHA256SUMS.txt")

    @property
    def url(self) -> str:
        return self.root.as_uri()


@contextlib.contextmanager
def local_servers(directory: Path, temp: Path):
    """An https server for `directory` and a plain http one, with the certificate the first presents.

    A path under /redirect/ answers 302 to the plain server, which counts its requests. Skips the test when
    openssl cannot make a certificate or curl does not trust it."""
    certificate = temp / "cert.pem"
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(temp / "key.pem"),
                        "-out", str(certificate), "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                       check=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise unittest.SkipTest("openssl cannot make a certificate here") from None
    hits = []

    class Plain(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"served over http")

        def log_message(self, *arguments):
            pass

    plain = http.server.HTTPServer(("127.0.0.1", 0), Plain)

    class Secure(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/redirect/"):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{plain.server_port}{self.path}")
                self.end_headers()
            else:
                super().do_GET()

        def log_message(self, *arguments):
            pass

    secure = http.server.HTTPServer(("127.0.0.1", 0), functools.partial(Secure, directory=str(directory)))
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, temp / "key.pem")
    secure.socket = context.wrap_socket(secure.socket, server_side=True)
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (plain, secure)]
    for thread in threads:
        thread.start()
    try:
        env = {"CURL_CA_BUNDLE": str(certificate)}
        base = f"https://127.0.0.1:{secure.server_port}"
        probe = subprocess.run(["curl", "-fsS", "-o", os.devnull, f"{base}/releases/latest/download/SHA256SUMS.txt"],
                               env={**os.environ, **env}, capture_output=True, timeout=60, check=False)
        if probe.returncode != 0:
            raise unittest.SkipTest("curl does not trust the local certificate here")
        yield base, hits, env
    finally:
        for server in (plain, secure):
            server.shutdown()
            server.server_close()


class InstallerRun:
    """Runs one installer with a PATH of the needed tools and the fakes asked for."""

    command: list[str] = []
    version_flag = "--version"

    def setUp(self):
        self.temp = Path(tempfile.mkdtemp(prefix="ogk-install-"))
        self.addCleanup(shutil.rmtree, self.temp, True)
        self.bin = self.temp / "bin"
        self.bin.mkdir()
        for tool in TOOLS:
            found = shutil.which(tool)
            if found:
                (self.bin / tool).symlink_to(found)
        self.log = self.temp / "installer.log"

    def fake(self, *names: str):
        for name in names:
            if os.name == "nt" and self.version_flag == "-Version":
                (self.bin / f"{name}.ps1").write_text(FAKE_PS1, encoding="utf-8")
                continue
            path = self.bin / name
            path.write_text(FAKE, encoding="utf-8")
            path.chmod(0o755)

    def install(self, release: FakeRelease, *arguments: str, env=None):
        environment = {"PATH": str(self.bin), "HOME": str(self.temp),
                       "TMPDIR": str(self.temp), "TEMP": str(self.temp), "TMP": str(self.temp),
                       "OPENGUILDKIT_RELEASES_URL": release.url, "FAKE_LOG": str(self.log), **(env or {})}
        arguments = [self.version_flag if argument == "--version" else argument for argument in arguments]
        return subprocess.run([*self.command, *arguments], capture_output=True, text=True, env=environment,
                              timeout=60, check=False)

    def installed(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def test_installs_the_latest_release_with_pipx_in_four_lines(self):
        self.fake("pipx", "uv")
        release = FakeRelease(self.temp, "0.18.0", others=["0.17.0"])
        result = self.install(release)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertLessEqual(len(lines), 4, result.stdout)
        self.assertIn("OpenGuildKit 0.18.0", lines[0])
        self.assertIn("SHA-256", lines[1])
        self.assertEqual(lines[2], "Installed with pipx")
        self.assertIn("openguildkit --version", lines[3])
        self.assertIn("openguildkit init", lines[3])
        self.assertRegex(self.installed(), r"^pipx install --force \S+[/\\]" + re.escape(wheel_name("0.18.0")) + r"\n$")
        self.assertEqual(Path(f"{self.log}.whl").read_bytes(), b"wheel of 0.18.0")

    def test_installs_the_version_given_even_an_older_one_or_a_named_prerelease(self):
        self.fake("pipx")
        release = FakeRelease(self.temp, "0.18.0", others=["0.17.0", "0.19.0rc1"])
        for asked, version in (("0.17.0", "0.17.0"), ("v0.19.0rc1", "0.19.0rc1")):
            with self.subTest(asked=asked):
                result = self.install(release, "--version", asked)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"OpenGuildKit {version}", result.stdout)
                self.assertEqual(Path(f"{self.log}.whl").read_bytes(), f"wheel of {version}".encode())

    def test_uses_uv_when_pipx_is_missing(self):
        self.fake("uv")
        result = self.install(FakeRelease(self.temp, "0.18.0"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Installed with uv", result.stdout)
        self.assertRegex(self.installed(), r"^uv tool install --force \S+\.whl\n$")

    def test_a_wrong_hash_installs_nothing_and_names_the_file_and_the_release(self):
        self.fake("pipx")
        result = self.install(FakeRelease(self.temp, "0.18.0", tamper=["0.18.0"]))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.installed(), "", "nothing may be installed")
        self.assertIn(wheel_name("0.18.0"), result.stderr)
        self.assertIn("v0.18.0", result.stderr)
        self.assertIn("nothing was installed", result.stderr)

    def test_without_pipx_or_uv_it_gives_both_official_commands_and_stops(self):
        result = self.install(FakeRelease(self.temp, "0.18.0"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pip install --user pipx", result.stderr)
        self.assertIn("https://astral.sh/uv/install", result.stderr)
        self.assertNotIn("Downloaded", result.stdout)

    def test_an_unknown_version_says_where_to_look(self):
        self.fake("pipx")
        result = self.install(FakeRelease(self.temp, "0.18.0"), "--version", "9.9.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("v9.9.9", result.stderr)
        self.assertIn("SHA256SUMS.txt", result.stderr)
        self.assertEqual(self.installed(), "")

    def test_a_failed_installation_shows_the_installer_output(self):
        self.fake("pipx")
        result = self.install(FakeRelease(self.temp, "0.18.0"), env={"FAKE_EXIT": "3"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pipx", result.stderr)
        self.assertNotIn("Installed with", result.stdout)


class LineEndingTest(unittest.TestCase):
    def test_git_checks_out_the_shell_scripts_with_lf_on_every_platform(self):
        attributes = (SH.parent.parent / ".gitattributes").read_text(encoding="utf-8").splitlines()
        self.assertIn("*.sh text eol=lf", attributes)
        self.assertNotIn(b"\r", SH.read_bytes())


@unittest.skipIf(os.name == "nt", "the POSIX installer runs on Linux and macOS")
class PosixShellTest(InstallerRun, unittest.TestCase):
    command = ["/bin/sh", str(SH)]

    def test_refuses_an_argument_it_does_not_know_and_a_malformed_version(self):
        self.fake("pipx")
        release = FakeRelease(self.temp, "0.18.0")
        for arguments in (["--pre"], ["--version", "../0.18.0"], ["--version"]):
            with self.subTest(arguments=arguments):
                result = self.install(release, *arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("openguildkit install:", result.stderr)
        self.assertEqual(self.installed(), "")

    def test_downloads_over_https_and_refuses_a_redirect_to_http(self):
        """Issue #503: curl followed a redirect from https to http, so the hash file and the wheel could be swapped."""
        self.fake("pipx")
        release = FakeRelease(self.temp, "0.18.0")
        with local_servers(release.root.parent, self.temp) as (base, hits, env):
            fine = self.install(release, env={**env, "OPENGUILDKIT_RELEASES_URL": f"{base}/releases"})
            self.assertEqual(fine.returncode, 0, fine.stderr)
            self.assertIn("Installed with pipx", fine.stdout)
            self.assertEqual(hits, [])
            self.log.unlink()
            redirected = self.install(release, env={**env, "OPENGUILDKIT_RELEASES_URL": f"{base}/redirect/releases"})
        self.assertNotEqual(redirected.returncode, 0)
        self.assertIn("could not download SHA256SUMS.txt", redirected.stderr)
        self.assertIn('Protocol "http" disabled', redirected.stderr, "the reason curl gives is shown")
        self.assertEqual(hits, [], "nothing was requested over http")
        self.assertEqual(self.installed(), "")

    def test_an_address_in_http_is_refused_before_any_connection(self):
        """Issue #503: the script took any scheme curl knows."""
        self.fake("pipx")
        hits = []

        class Plain(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(404)
                self.end_headers()

            def log_message(self, *arguments):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Plain)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        result = self.install(FakeRelease(self.temp, "0.18.0"),
                              env={"OPENGUILDKIT_RELEASES_URL": f"http://127.0.0.1:{server.server_port}/releases"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not download SHA256SUMS.txt", result.stderr)
        self.assertEqual(hits, [])
        self.assertEqual(self.installed(), "")


@unittest.skipIf(os.name == "nt", "the POSIX installer runs on Linux and macOS")
@unittest.skipUnless(shutil.which("dash"), "dash is not installed")
class DashTest(InstallerRun, unittest.TestCase):
    """dash has no bash extension: the script stays POSIX sh."""

    command = [shutil.which("dash") or "dash", str(SH)]


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell (pwsh) is not installed: install.ps1 is not run here")
class PowerShellTest(InstallerRun, unittest.TestCase):
    command = [shutil.which("pwsh") or "pwsh", "-NoProfile", "-NonInteractive", "-File", str(PS1)]
    version_flag = "-Version"


class ScriptStructureTest(unittest.TestCase):
    def test_both_scripts_check_the_hash_before_installing_and_read_the_test_address(self):
        for path, hashing, install in ((SH, "$SHA256", "pipx install --force"),
                                       (PS1, "Get-FileHash", "pipx install --force")):
            with self.subTest(script=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("OPENGUILDKIT_RELEASES_URL", text)
                self.assertIn("reserved", text.split("OPENGUILDKIT_RELEASES_URL", 1)[1][:200])
                self.assertIn("latest/download/SHA256SUMS.txt", text)
                self.assertLess(text.index(hashing), text.index(install), "check the hash before installing")
                self.assertIn("uv tool install --force", text)
                self.assertIn("https://pipx.pypa.io/stable/how-to/install-pipx.html", text)
                self.assertIn("https://docs.astral.sh/uv/getting-started/installation/", text)

    def test_both_scripts_download_over_https_only_with_tls_1_2(self):
        """Issue #503: the three curl calls of the line and the script took http and any TLS version."""
        text = SH.read_text(encoding="utf-8")
        calls = [line for line in text.splitlines() if re.match(r"\s*curl\s", line) and "-o " in line]
        self.assertTrue(calls)
        for line in calls:
            self.assertIn('--proto "$PROTO" --tlsv1.2', line)
        self.assertIn("PROTO='=https'", text)
        ps = PS1.read_text(encoding="utf-8")
        self.assertIn("Tls12", ps)
        self.assertRegex(ps, r'-notlike "https://\*"|StartsWith\("https://"\)')

    def test_the_shell_script_is_posix(self):
        text = SH.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/bin/sh\n"))
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        for bashism in ("[[", "function ", "local ", "<<<", "pipefail", "${!", "$'\\"):
            self.assertNotIn(bashism, code)
        self.assertTrue(os.access(SH, os.X_OK), "scripts/install.sh must be executable")

    def test_the_powershell_script_never_exits_the_session_it_is_piped_into(self):
        text = PS1.read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^param\(\[string\]\$Version")
        code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotRegex(code, r"\bexit\b", "exit would close the window of a person who ran irm | iex")
        self.assertEqual(code.count("{"), code.count("}"))
        self.assertEqual(code.count("("), code.count(")"))


class ReleaseAssetsTest(unittest.TestCase):
    def test_the_release_attaches_both_installers_with_their_hashes(self):
        jobs = parse(ROOT / ".github" / "workflows" / "release.yml")["jobs"]
        build, publish = run_text(jobs["build"]), run_text(jobs["publish"])
        self.assertIn("cp scripts/install.sh scripts/install.ps1 release/", build)
        sums = next(line for line in build.splitlines() if line.startswith("sha256sum "))
        for name in ("install.sh", "install.ps1"):
            self.assertIn(name, sums)
            self.assertIn(name, publish.split("gh release upload", 1)[1])

    def test_the_release_check_downloads_every_file_the_hashes_list(self):
        check = (ROOT / ".github" / "workflows" / "release-check.yml").read_text(encoding="utf-8")
        for name in ("install.sh", "install.ps1"):
            self.assertIn(f"--pattern {name}", check)

    def test_templates_keep_the_pinned_hash_until_a_release_ships_the_script(self):
        """The release this repository announces predates install.sh: the templates switch at the next one."""
        for template in sorted((ROOT / "integrations" / "github").glob("*.yml")):
            with self.subTest(template=template.name):
                install = next(step for job in parse(template)["jobs"].values() for step in steps(job)
                               if step.get("name") == "Install OpenGuildKit")
                self.assertIn("OPENGUILDKIT_WHEEL_SHA256", install["env"])
                self.assertIn("sha256sum --strict -c", install["run"])
        for page in ("docs/install.md", "GOVERNANCE.md"):
            self.assertIn("the first release that ships `install.sh`", (ROOT / page).read_text(encoding="utf-8"), page)


class InstallDocsTest(unittest.TestCase):
    def test_the_readmes_and_the_install_guide_give_the_line(self):
        for page in ("README.md", "README.fr.md", "docs/install.md"):
            with self.subTest(page=page):
                text = (ROOT / page).read_text(encoding="utf-8")
                self.assertIn(LINE, text)
                self.assertIn("--version", text)
        guide = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
        self.assertIn(PS_LINE, guide)
        self.assertIn("OPENGUILDKIT_RELEASES_URL", guide)
        self.assertIn("## Download and verify", guide, "the manual installation stays documented")


if __name__ == "__main__":
    unittest.main()
