"""Check an installed openguildkit command the way a team uses it after installing the release wheel.

    python .github/scripts/check-installed-cli.py [--static DIR] -- COMMAND...

COMMAND is the installed `openguildkit` (or `python -m openguildkit`). The script runs `--version`,
`tools list` and `alerts --help` in an empty folder, then starts `ui --no-browser --port 0` there, opens the
address the server prints (its key opens the session, as in a browser), and requires `/` to answer 200 with the
built page and each script it loads.
`--static DIR` is passed to `ui`, for the tests. Standard library only: any Python of the runner runs it.
"""

import argparse
import http.client
import http.cookiejar
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ADDRESS = re.compile(r"http://[a-z0-9-]+\.localhost:\d+/\S*")
SCRIPT = re.compile(r'<script[^>]*\bsrc="(?:\./|/)?([^"]+)"')


def run(command: list[str], *args: str, cwd: Path) -> str:
    done = subprocess.run([*command, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", timeout=120)
    if done.returncode != 0:
        raise SystemExit(f"openguildkit {' '.join(args)} exited with {done.returncode}: {done.stderr.strip()}")
    return done.stdout


class Loopback(http.client.HTTPConnection):
    """The printed address names the run under .localhost, which browsers send to the loopback interface; the
    system resolver of a runner may not. Connect to 127.0.0.1 and keep the name in the Host header."""

    def __init__(self, host, **options):
        super().__init__("127.0.0.1", int(host.rpartition(":")[2]), **options)


class LoopbackHandler(urllib.request.HTTPHandler):
    def http_open(self, request):
        return self.do_open(Loopback, request)


def fetch(opener: urllib.request.OpenerDirector, url: str) -> tuple[int, bytes]:
    try:
        with opener.open(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def check_interface(command: list[str], project: Path, extra: list[str]) -> str:
    """Start the server, check the page and its scripts, stop the server; return the address it used."""
    server = subprocess.Popen([*command, "--project", str(project), "ui", "--no-browser", "--port", "0", *extra],
                              cwd=project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              encoding="utf-8")
    try:
        address = next((match.group(0) for line in server.stdout if (match := ADDRESS.search(line))), None)
        if address is None:
            raise SystemExit(f"openguildkit ui printed no address: {server.communicate(timeout=10)[1].strip()}")
        # The printed address carries the key of this run: opening it sets the session cookie, then goes to /.
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                             LoopbackHandler())
        status, body = fetch(opener, address)
        address = address.split("?", 1)[0]
        if status != 200:
            raise SystemExit(f"GET / answered {status}, not 200: the installed package has no web interface. "
                             f"{body[:200].decode('utf-8', 'replace')}")
        page = body.decode("utf-8")
        if 'name="openguildkit-ui"' not in page:
            raise SystemExit("GET / answered a page that openguildkit ui did not mark as its own.")
        scripts = SCRIPT.findall(page)
        if not scripts:
            raise SystemExit("The page loads no script: the built interface is incomplete.")
        for script in scripts:
            status, _ = fetch(opener, address + script)
            if status != 200:
                raise SystemExit(f"GET /{script} answered {status}: the package misses a file of the interface.")
        return address
    finally:
        server.terminate()
        server.communicate(timeout=10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--static", help="Folder of a built interface, passed to openguildkit ui.")
    parser.add_argument("command", nargs="+", help="The installed openguildkit command, after --.")
    args = parser.parse_args(argv)
    command = [shutil.which(args.command[0]) or args.command[0], *args.command[1:]]
    extra = ["--static", args.static] if args.static else []
    with tempfile.TemporaryDirectory() as folder:
        project = Path(folder)
        print(run(command, "--version", cwd=project).strip())
        tools = run(command, "tools", "list", cwd=project).splitlines()
        if not tools:
            raise SystemExit("openguildkit tools list printed no tool.")
        run(command, "alerts", "--help", cwd=project)
        print(f"tools list: {len(tools)} tools; alerts --help: ok")
        print(f"ui: {check_interface(command, project, extra)} answered 200 with the built interface")
    return 0


if __name__ == "__main__":
    sys.exit(main())
