"""Local web interface: the built front end and a JSON API over the CLI, on the loopback interface only.

The API runs the same commands a person types, in this process, one at a time. It never runs what needs a
person at a terminal: approving a task or clearing a blocker without a signature, waiving a blocker, allowing an
external action, accepting an alert, setting its severity or dismissing a critical one, declaring that a check
command cannot run, closing a task over sensitive points, or a profile change that weakens a protection. For those,
it answers with the command to type.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import socket
import socketserver
import sys
import tempfile
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

from . import cli, profile_changes, tasks
from .lock import package_version
from .storage import write_text
from .web_requests import (
    HUMAN_ONLY_TEXT,
    REFUSALS,
    ProjectFiles,
    Refused,
    check_paths,
    check_request,
    named_command,
    terminal_command,
    terminal_reason,
)

DEFAULT_PORT = 7311
MAX_BODY = 8 * 1024 * 1024
# A script that starts the server for its own browser, such as the end-to-end tests, may set the key of the run.
KEY_VARIABLE = "OPENGUILDKIT_UI_KEY"
UPLOAD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

TERMINAL_NEEDED = re.compile(
    r"interactive terminal|needs a terminal|at a terminal|in their own terminal|runs the command at", re.I)
# What a browser without the key of the run sees in place of the page.
GATE = ("<!doctype html><html lang=\"fr\"><meta charset=utf-8><title>OpenGuildKit</title><p>Ouvre l'adresse que "
        "<code>openguildkit ui</code> a imprimée dans ton terminal : elle porte la clé de cette session, qui change "
        "à chaque lancement.</p><p lang=\"en\">Open the address <code>openguildkit ui</code> printed in your "
        "terminal: it carries the key of this run, which changes at each start.</p></html>")
# The types of the files the page is made of, kept here: mimetypes reads the registry of the workstation, where a
# program can declare .js as text/plain, and nosniff then leaves the page blank.
CONTENT_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json",
                 ".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png", ".woff2": "font/woff2"}
TEXT_TYPES = ("text/", "application/json", "image/svg+xml")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
       "object-src 'none'")


def _without(data, keys: set[str]):
    if isinstance(data, dict):
        return {key: _without(value, keys) for key, value in data.items() if key not in keys}
    if isinstance(data, list):
        return [_without(value, keys) for value in data]
    return data


# What a consultation holds that no screen of the page reads, and that makes up most of a task record: the brief of each
# board and the domains they cover. The page never receives them; the CLI prints them, and `raw` keeps that text.
UNREAD_CONSULTATION = {"board_briefs", "domains"}


def _without_unread(data, inside: bool = False):
    """The JSON of a command without the keys of a consultation that the page does not read, at any depth."""
    if isinstance(data, dict):
        return {key: _without_unread(value, key == "consultation") for key, value in data.items()
                if not (inside and key in UNREAD_CONSULTATION)}
    if isinstance(data, list):
        return [_without_unread(value) for value in data]
    return data


def _options(body: dict) -> dict:
    omit = body.get("omit")
    if omit is not None and (not isinstance(omit, list) or len(omit) > 20 or not all(isinstance(k, str) for k in omit)):
        raise Refused("omit must be a list of at most 20 key names.", status=HTTPStatus.BAD_REQUEST,
                      reason="bad-request")
    return {"keep_text": bool(body.get("raw")), "omit": omit}


class CliRunner:
    """Runs CLI commands in this process, one at a time, with a stdin that is never a terminal."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.records = tasks.KeptRecords()

    def parse(self, argv: list[str]):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                return cli.command_parser().parse_args(["--project", str(self.root), *argv])
            except SystemExit:
                message = err.getvalue().strip().splitlines()
                raise Refused(message[-1] if message else "Invalid command.", status=HTTPStatus.BAD_REQUEST,
                              reason="bad-request") from None

    def run(self, argv: list[str], uploads: dict[str, str] | None = None, *, keep_text: bool = False,
            omit: list[str] | None = None) -> dict:
        """Run one command. Its JSON output comes back parsed; the same text is dropped unless keep_text,
        and the keys named in omit are removed at any depth (a page that shows a list of tasks does not
        need the text of each consultation)."""
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise Refused("argv must be a non-empty list of strings.", status=HTTPStatus.BAD_REQUEST,
                          reason="bad-request")
        if argv[0].startswith("-"):
            raise Refused("Start with a command; the interface sets the project itself.", status=HTTPStatus.BAD_REQUEST,
                          reason="bad-request")
        # sys.stdout, sys.stderr and sys.stdin are process-wide: parsing and running hold the same lock, or a
        # concurrent request would capture another command's output.
        typed = list(argv)
        with tempfile.TemporaryDirectory(prefix="ogk-ui-") as folder, self.lock:
            argv, written = self._with_uploads(argv, uploads or {}, Path(folder))
            args = self.parse(argv)
            check_request(args, typed, self.root)
            check_paths(args, self.root, written)
            out, err = io.StringIO(), io.StringIO()
            saved = sys.stdin
            sys.stdin = io.StringIO("")
            try:
                # The server outlives its commands: the task records stay in memory while their files do not change.
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                        tasks.keeping_records(self.records):
                    try:
                        code = cli.main(["--project", str(self.root), *argv])
                    except SystemExit as exit_:
                        code = exit_.code if isinstance(exit_.code, int) else 2
            finally:
                sys.stdin = saved
        stdout = out.getvalue()
        data = None
        if stdout.lstrip()[:1] in ("{", "["):
            with contextlib.suppress(ValueError):
                data = json.loads(stdout)
        if data is not None:
            if omit:
                data = _without(data, set(omit))
            if '"consultation"' in stdout:
                data = _without_unread(data)
            if not keep_text:
                stdout = ""
        stderr = err.getvalue()
        # The resolved form can contain the given one (/private/var/folders on macOS holds /var/folders): it goes first.
        for shown in sorted({str(Path(folder).resolve()), folder}, key=len, reverse=True):
            stderr = stderr.replace(shown, "<upload>")
        result = {"code": code, "stdout": stdout, "stderr": stderr, "json": data}
        # Some decisions need a person at a terminal only in some cases (dismissing a critical alert): the CLI says
        # so, and the page shows the command to type, the one the CLI names when it names one.
        refusal = next((line for line in stderr.splitlines() if TERMINAL_NEEDED.search(line)), None)
        if code != 0 and refusal:
            result["command"] = terminal_command(self.root, named_command(refusal) or typed)
            result["reason"] = terminal_reason(args)
        return result

    def call(self, function) -> tuple[dict, Exception | None]:
        """Run a function of the CLI's modules as a command runs: under the same lock, with its output captured and
        a stdin that is not a terminal, a refusal printed as the CLI prints it. Returns the result and the refusal."""
        out, err = io.StringIO(), io.StringIO()
        failure = None
        with self.lock:
            saved = sys.stdin
            sys.stdin = io.StringIO("")
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    try:
                        function()
                    except (OSError, ValueError) as error:
                        failure = error
                        print(f"OpenGuildKit: {error}", file=sys.stderr)
            finally:
                sys.stdin = saved
        return {"code": 1 if failure else 0, "stdout": out.getvalue(), "stderr": err.getvalue(), "json": None}, failure

    @staticmethod
    def _with_uploads(argv: list[str], uploads: dict[str, str], folder: Path) -> tuple[list[str], set[Path]]:
        if not isinstance(uploads, dict):
            raise Refused("uploads must be an object of file names and texts.", status=HTTPStatus.BAD_REQUEST,
                          reason="bad-request")
        written: dict[str, Path] = {}
        for name, text in uploads.items():
            if not isinstance(name, str) or not UPLOAD_NAME.match(name) or not isinstance(text, str):
                raise Refused(f"Invalid upload: {name!r}", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
            path = folder / name
            try:
                path.write_text(text, encoding="utf-8", newline="")
            except UnicodeEncodeError:
                raise Refused(f"Invalid upload: {name!r} holds a character UTF-8 cannot encode.",
                              status=HTTPStatus.BAD_REQUEST, reason="bad-request") from None
            written[name] = path.resolve()
        result = []
        for item in argv:
            if item.startswith("@upload:"):
                name = item.removeprefix("@upload:")
                if name not in written:
                    raise Refused(f"No upload named {name}.", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
                item = str(written[name])
            result.append(item)
        return result, set(written.values())


def find_front_end(explicit: Path | None) -> Path | None:
    """The built front end: --static, the copy inside the package, or web/dist in a source checkout."""
    if explicit is not None:
        return explicit.resolve() if (explicit / "index.html").is_file() else None
    here = Path(__file__).resolve().parent
    # In a source checkout, a fresh `npm run build` wins over an older copy left by `npm run bundle`.
    found = [folder for folder in (here / "web_dist", here.parents[1] / "web" / "dist") if (folder / "index.html").is_file()]
    return max(found, key=lambda folder: (folder / "index.html").stat().st_mtime).resolve() if found else None


class Asset(NamedTuple):
    """A file of the front end as the page gets it: its type, its ETag, its body, and its gzip form when it has one."""

    kind: str
    etag: str
    body: bytes
    packed: bytes | None


def _matches(header: str | None, etag: str) -> bool:
    """Whether an If-None-Match header names this ETag, weak or strong, or any."""
    tags = [part.strip().removeprefix("W/") for part in (header or "").split(",")]
    return "*" in tags or etag in tags


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenGuildKit"
    sys_version = ""
    app: "WebApp"

    def log_message(self, format, *args):  # noqa: A002 - INTENTIONAL(#522): signature of the base class
        if self.app.verbose:
            sys.stderr.write("ui: " + (format % args) + "\n")

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _compressed(self, body: bytes, extra: dict) -> bytes:
        """Gzip a text answer larger than 2 KB when the browser accepts it: it matters through a tunnel or a
        forwarded port, much less on the loopback, so the fastest level is enough."""
        if len(body) > 2048 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            extra["Content-Encoding"] = "gzip"
            extra["Vary"] = "Accept-Encoding"
            return gzip.compress(body, compresslevel=1, mtime=0)
        return body

    def _json(self, status: int, data) -> None:
        extra = {"Cache-Control": "no-store"}
        try:
            text = json.dumps(data, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:  # A lone surrogate, from a file name an error repeats: escaped, never a 500 (#528).
            text = json.dumps(data).encode("ascii")
        body = self._compressed(text, extra)
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _refuse(self, refusal: Refused) -> None:
        self._json(refusal.status, refusal.answer())

    def _host_allowed(self) -> bool:
        return (self.headers.get("Host") or "").lower() in self.app.hosts

    def do_HEAD(self):  # noqa: N802 - INTENTIONAL(#522): http.server naming
        self.do_GET()

    def do_GET(self):  # noqa: N802 - INTENTIONAL(#522): http.server naming
        address = urlsplit(self.path)
        if (self.headers.get("Host") or "").lower() in self.app.loopback:
            # 127.0.0.1 and localhost are shared by every local server: the session never opens there.
            if address.path.startswith("/api/"):
                self._refuse(Refused(REFUSALS["open-printed-link"], reason="open-printed-link"))
            else:
                self._send(HTTPStatus.FORBIDDEN, GATE.encode("utf-8"), "text/html; charset=utf-8",
                           {"Content-Security-Policy": CSP, "Cache-Control": "no-store"})
            return
        if not self._host_allowed():
            self._refuse(Refused("Unknown host.", status=HTTPStatus.MISDIRECTED_REQUEST, reason="foreign-page"))
            return
        key = parse_qs(address.query).get("key")
        if key and _same(key[0], self.app.key):
            # The printed address: its key becomes a cookie of this browser and leaves the address bar.
            self._send(HTTPStatus.SEE_OTHER, b"", "text/plain; charset=utf-8",
                       {"Location": address.path or "/", "Set-Cookie": self.app.set_cookie(), "Cache-Control": "no-store"})
            return
        path, opened = address.path, self.app.opened(self.headers.get("Cookie"))
        if path == "/api/session":
            if opened:
                self._json(HTTPStatus.OK, self.app.session())
            else:
                self._refuse(Refused(REFUSALS["open-printed-link"], reason="open-printed-link"))
            return
        if path.startswith("/api/"):
            self._refuse(Refused("Use POST for the API.", status=HTTPStatus.METHOD_NOT_ALLOWED, reason="bad-request"))
            return
        if not opened and path in ("", "/", "/index.html"):
            self._send(HTTPStatus.FORBIDDEN, GATE.encode("utf-8"), "text/html; charset=utf-8",
                       {"Content-Security-Policy": CSP, "Cache-Control": "no-store"})
            return
        self._static(path)

    def _static(self, path: str) -> None:
        front = self.app.front
        if front is None:
            body = ("<!doctype html><meta charset=utf-8><title>OpenGuildKit</title><p>The web interface is not "
                    "built. In a source checkout, run <code>npm ci &amp;&amp; npm run build</code> in <code>web/</code>, "
                    "or pass <code>--static</code>.</p>").encode("utf-8")
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, body, "text/html; charset=utf-8", {"Content-Security-Policy": CSP})
            return
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (front / relative).resolve()
        try:
            target.relative_to(front)
        except ValueError:
            target = front / "missing"
        if not target.is_file():
            self._refuse(Refused("Not found.", status=HTTPStatus.NOT_FOUND, reason="not-found"))
            return
        asset = self.app.asset(target)
        cache = "no-cache" if target.name == "index.html" else "public, max-age=31536000, immutable" \
            if "/assets/" in f"/{relative}" and re.search(r"-[A-Za-z0-9_-]{8,}\.", target.name) else "no-cache"
        packed = asset.packed if "gzip" in (self.headers.get("Accept-Encoding") or "") else None
        # The gzip form is another representation: it has its own ETag.
        etag = asset.etag[:-1] + '-gzip"' if packed is not None else asset.etag
        extra = {"Content-Security-Policy": CSP, "Cache-Control": cache, "ETag": etag}
        if asset.packed is not None:
            extra["Vary"] = "Accept-Encoding"
        if _matches(self.headers.get("If-None-Match"), etag):
            self._send(HTTPStatus.NOT_MODIFIED, b"", asset.kind, extra)
            return
        if packed is not None:
            extra["Content-Encoding"] = "gzip"
        self._send(HTTPStatus.OK, asset.body if packed is None else packed, asset.kind, extra)

    def do_POST(self):  # noqa: N802 - INTENTIONAL(#522): http.server naming
        try:
            body = self._body()
            self._json(HTTPStatus.OK, self.app.handle(urlsplit(self.path).path, body))
        except Refused as refusal:
            self._refuse(refusal)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            return  # The browser closed the connection, a tab closed or reloaded: no one is left to answer.
        except Exception as error:  # noqa: BLE001 - INTENTIONAL(#522): report to the page instead of dropping the connection
            self._report(error)
            self._refuse(Refused(f"{type(error).__name__}: {error}", status=HTTPStatus.INTERNAL_SERVER_ERROR,
                                 reason="server-error"))

    def _report(self, error: Exception) -> None:
        """Leave the failure in the terminal that runs the server, where the page's text for it sends the person."""
        # Under the runner's lock: a command running now has sys.stderr captured for its own answer.
        with self.app.runner.lock:
            print(f"OpenGuildKit: the request to {urlsplit(self.path).path} failed.", file=sys.stderr)
            traceback.print_exception(error, file=sys.stderr)

    def _body(self) -> dict:
        """The JSON object a request of the interface's own page sends, with its origin and session token. The body
        announced is read first, up to MAX_BODY, refused or not: on Windows, closing a connection with bytes left
        unread resets it, and the client can lose the answer."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        raw = self.rfile.read(length) if 0 <= length <= MAX_BODY else None
        if not self._host_allowed():
            raise Refused("Unknown host.", status=HTTPStatus.MISDIRECTED_REQUEST, reason="foreign-page")
        if (self.headers.get("Origin") or "").lower() not in self.app.origins:
            raise Refused("Requests must come from the interface's own page.", reason="foreign-page")
        if not _same(self.headers.get("X-OGK-Token") or "", self.app.token):
            raise Refused("Missing or invalid session token. Reload the page.", reason="stale-token")
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            raise Refused("Send JSON.", status=HTTPStatus.UNSUPPORTED_MEDIA_TYPE, reason="bad-request")
        if raw is None:
            raise Refused("The request is too large.", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, reason="too-large")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise Refused("The body is not a JSON object.", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
        return body


# The page's preferences, kept by the project so that they outlive the run's host name (#463): a closed list of keys,
# each with its allowed values or, for a name, a single line of at most PREF_NAME_LENGTH characters.
PREF_CHOICES = {"mode": ("explorer", "focus"), "motion": ("system", "reduced"), "shortcuts": ("on", "off")}
PREF_NAMES = ("decider", "signer")
PREF_NAME_LENGTH = 80
PREFS_FILE = Path(".openguildkit", "work", "ui-prefs.json")


def _pref_problem(key, value) -> str | None:
    if key in PREF_CHOICES:
        return None if value in PREF_CHOICES[key] else f"{key} must be one of {', '.join(PREF_CHOICES[key])}."
    if key in PREF_NAMES:
        fits = isinstance(value, str) and len(value) <= PREF_NAME_LENGTH and value.isprintable()
        return None if fits else f"{key} must be one line of at most {PREF_NAME_LENGTH} characters."
    return f"Unknown preference: {key}"


def read_prefs(root: Path) -> dict:
    """The preferences the project keeps for the page, each one the endpoint would accept; none for a missing or
    unreadable file."""
    try:
        data = json.loads((root / PREFS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if _pref_problem(key, value) is None} \
        if isinstance(data, dict) else {}


def _same(given: str, secret: str) -> bool:
    """Compare a secret in constant time, whatever characters a request sent."""
    return secrets.compare_digest(given.encode("utf-8", "replace"), secret.encode("utf-8"))


def session_name(key: str) -> str:
    """The host name of the run, under .localhost, which browsers send to the loopback interface. A browser sends a
    cookie to every port of the host that set it: on 127.0.0.1, another local server, such as the development server
    of the project, would receive the key. A name drawn from the key of the run is known only to who holds the key."""
    return f"ogk-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]}.localhost"


def stable_name(root: Path) -> str:
    """The host name of a project for a person who asks to find the same address at each launch, so that the browser
    keeps the preferences of the page, which it keeps per origin. It comes from the path of the project, not from the
    key of the run: whoever knows the path can compute it, which session_name's does not allow."""
    path = os.fsencode(os.path.normcase(str(root.resolve())))
    return f"ogk-{hashlib.sha256(path).hexdigest()[:24]}.localhost"


def launch_key() -> str:
    """The key of this run, which only the printed address carries. A script that starts the server for its own
    browser sets it with OPENGUILDKIT_UI_KEY; it is then as secret as that script keeps it."""
    value = os.environ.get(KEY_VARIABLE, "").strip()
    if not value:
        return secrets.token_urlsafe(32)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value):
        raise ValueError(f"Set {KEY_VARIABLE} to 32 to 128 letters, digits, - or _, or unset it.")
    return value


class WebApp:
    """The project behind the page. A browser opens the session with the key of the printed address, kept in a
    cookie of the host name of the run; the session gives the page the token that every API call carries."""

    def __init__(self, root: Path, front: Path | None, port: int, verbose: bool = False, stable_address: bool = False):
        self.root = root
        self.stable_address = stable_address
        self.front = front
        self.key = launch_key()
        self.token = secrets.token_urlsafe(32)
        self.runner = CliRunner(root)
        self.files = ProjectFiles(root)
        self.version = package_version()
        self.verbose = verbose
        self.assets: dict[Path, tuple[tuple[int, int], Asset]] = {}
        self.set_port(port)

    def set_port(self, port: int) -> None:
        self.port = port
        # The page lives on the host name of the run only. The loopback names answer with the gate page.
        self.host = f"{stable_name(self.root) if self.stable_address else session_name(self.key)}:{port}"
        self.hosts = {self.host}
        self.loopback = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        self.origin = f"http://{self.host}"
        self.origins = {self.origin}
        self.cookie = f"ogk-{port}"

    @property
    def url(self) -> str:
        return f"{self.origin}/?key={self.key}"

    def set_cookie(self) -> str:
        return f"{self.cookie}={self.key}; Path=/; HttpOnly; SameSite=Strict"

    def opened(self, header: str | None) -> bool:
        """Whether the browser opened the printed address of this run."""
        cookies = SimpleCookie()
        try:
            cookies.load(header or "")
        except CookieError:
            return False
        morsel = cookies.get(self.cookie)
        return morsel is not None and _same(morsel.value, self.key)

    def asset(self, target: Path) -> Asset:
        """The file as it is served, kept until its size or modification time changes: a text file past 2 KB is
        compressed once, at a level that costs more than a request can spare but pays back through a tunnel."""
        with open(target, "rb") as handle:
            info = os.fstat(handle.fileno())
            stamp = (info.st_size, info.st_mtime_ns)
            kept = self.assets.get(target)
            if kept is not None and kept[0] == stamp:
                return kept[1]
            body = handle.read()
        if target.name == "index.html":
            # Tells the page it is served by the CLI, so it loads the project code and its session together.
            body = body.replace(b"<head>", b'<head><meta name="openguildkit-ui" content="1">', 1)
        kind = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        text = kind.startswith(TEXT_TYPES)
        packed = gzip.compress(body, compresslevel=6, mtime=0) if text and len(body) > 2048 else None
        asset = Asset(kind + "; charset=utf-8" if text else kind, f'"{stamp[0]:x}-{stamp[1]:x}"', body, packed)
        self.assets[target] = (stamp, asset)
        return asset

    def session(self) -> dict:
        return {
            "app": "openguildkit-ui",
            "version": self.version,
            "token": self.token,
            "project": {"root": str(self.root), "name": self.root.name,
                        "initialized": (self.root / ".openguildkit" / "project.json").is_file()},
            "prefs": read_prefs(self.root),
            "human_only": ["task decide --approve", "task revoke", "task clear", "task waive",
                           "task authorize --allow", "task verify --cannot-run", "task verify --withdraw",
                           "task complete --by", "alerts accept", "alerts severity",
                           "alerts set or task alerts --set (critical alert dismissed or taken back)",
                           "profile (weakening a protection)", "tools apply (live)"],
        }

    def handle(self, path: str, body: dict):
        if path == "/api/run":
            if "batch" in body:
                batch = body["batch"]
                if not isinstance(batch, dict) or len(batch) > 40:
                    raise Refused("batch must be an object of at most 40 commands.", status=HTTPStatus.BAD_REQUEST,
                                  reason="bad-request")
                options = _options(body)
                results = {}
                for key, argv in batch.items():
                    try:
                        results[key] = self.runner.run(argv, **options)
                    except Refused as refusal:
                        results[key] = {"code": 1, "stdout": "", "stderr": str(refusal), "json": None,
                                        "command": refusal.command, "reason": refusal.reason}
                return {"results": results}
            return self.runner.run(body.get("argv"), body.get("uploads"), **_options(body))
        if path == "/api/files/list":
            return {"entries": self.files.list(body.get("path", ""))}
        if path == "/api/files/read":
            return self.files.read(body.get("path", ""))
        if path == "/api/files/write":
            return self.files.write(body.get("path", ""), body.get("text"))
        if path == "/api/profile/save":
            return self.save_profile(body.get("text"), body.get("by"), body.get("reason"))
        if path == "/api/prefs":
            return {"prefs": self.save_prefs(body.get("prefs"))}
        raise Refused("Unknown endpoint.", status=HTTPStatus.NOT_FOUND, reason="not-found")

    def save_prefs(self, patch) -> dict:
        """Merge the page's preferences into the file the project keeps for them, in .openguildkit/work/ (which the
        project's .gitignore leaves out), and return them all. Nothing is written for an unknown key, a value out of
        its bounds, a project not set up, or a folder on the way that is a link."""
        if not isinstance(patch, dict) or not patch:
            raise Refused("prefs must be an object of preferences.", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
        problem = next(filter(None, (_pref_problem(key, value) for key, value in patch.items())), None)
        if problem:
            raise Refused(problem, status=HTTPStatus.BAD_REQUEST, reason="bad-request")
        state = self.root / ".openguildkit"
        if not (state / "project.json").is_file():
            raise Refused(REFUSALS["not-initialized"], status=HTTPStatus.CONFLICT, reason="not-initialized")
        target = self.root / PREFS_FILE
        if state.is_symlink() or target.parent.is_symlink() or target.is_symlink():
            raise Refused(f"{PREFS_FILE.parent.as_posix()} is a link: the preferences are not written.",
                          status=HTTPStatus.BAD_REQUEST, reason="outside-project")
        with self.runner.lock:
            prefs = {**read_prefs(self.root), **patch}
            write_text(target, json.dumps(prefs, ensure_ascii=False, indent=2) + "\n")
        return prefs

    def save_profile(self, text, by=None, reason=None) -> dict:
        """Save the profile edited in the page by the profile commands' own path: under the project lock, recorded
        in the history with who and why, then the instructions and the catalog lock are rewritten. A change that
        weakens a protection is the person's decision at a terminal: it is refused with the profile command to
        type. An invalid profile, or one that rewrites the history, is refused too; nothing is written then."""
        if not isinstance(text, str):
            raise Refused("text must be a string.", status=HTTPStatus.BAD_REQUEST, reason="invalid-profile")
        try:
            profile = json.loads(text)
            if not isinstance(profile, dict):
                raise ValueError("the profile is a JSON object")
        except ValueError as error:
            raise Refused(f"Invalid JSON: {error}", status=HTTPStatus.BAD_REQUEST, reason="invalid-profile") from None
        who = _decision_line(by, "by", "web interface")
        why = _decision_line(reason, "reason", "Saved from the web interface.")
        state = self.root / ".openguildkit"
        if not (state / "project.json").is_file():
            raise Refused(REFUSALS["not-initialized"], status=HTTPStatus.CONFLICT, reason="not-initialized")
        result, failure = self.runner.call(lambda: profile_changes.save_edited(self.root, state, profile, who, why))
        if isinstance(failure, profile_changes.Weakening):
            raise Refused(f"{failure} {HUMAN_ONLY_TEXT}", terminal_command(self.root, failure.changes[0][1]),
                          reason="weakens-protection")
        # Nothing is written when the save fails: the profile on disk is still the previous one.
        result["restored"] = failure is not None
        if isinstance(failure, profile_changes.InvalidProfile):
            result["reason"] = "invalid-profile"
        return result


def _decision_line(value, field: str, default: str) -> str:
    """Who saves the profile from the page and why: one line each, or the page's own words when it sends none."""
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip() or "\n" in value or "\r" in value:
        raise Refused(f"{field} must be a non-empty single line.", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
    return value.strip()


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # A page load opens a dozen connections at once; Windows refuses them past the default backlog of 5.
    request_queue_size = 64
    # On Windows, SO_REUSEADDR lets another program bind the same port and receive the page's requests: the port is
    # held exclusively there instead.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if exclusive is not None:
            self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
        # HTTPServer.server_bind looks up the host's name with socket.getfqdn, a reverse lookup that nothing reads and
        # that took 35 s on macOS runners (issue #450): bind as a TCP server and keep the address as the name.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        # A browser that navigates away closes its connections: nothing to report.
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def make_server(root: Path, port: int = DEFAULT_PORT, front: Path | None = None, verbose: bool = False,
                stable_address: bool = False):
    """Bind the server on 127.0.0.1. Port 0 picks a free port."""
    app = WebApp(root, front, port, verbose, stable_address)

    class BoundHandler(Handler):
        pass

    BoundHandler.app = app
    server = LocalServer(("127.0.0.1", port), BoundHandler)
    server.daemon_threads = True
    app.set_port(server.server_address[1])
    return server, app


def serve(root: Path, port: int = DEFAULT_PORT, static: Path | None = None, open_browser: bool = True,
          verbose: bool = False, stable_address: bool = False) -> int:
    front = find_front_end(static)
    os.chdir(root)  # relative paths given in the page resolve inside the project, as in a terminal opened there
    try:
        server, app = make_server(root, port, front, verbose, stable_address)
    except OSError:
        if port == 0:
            raise
        server, app = make_server(root, 0, front, verbose, stable_address)
        print(f"Port {port} is busy; using {app.port}.", file=sys.stderr)
    url = app.url
    print(f"OpenGuildKit interface for {root}\n{url}\nOpen this address: it carries the key of this run. "
          "Press Ctrl+C to stop.", flush=True)
    if front is None:
        print("OpenGuildKit: the web interface is not built; the page explains how to build it.", file=sys.stderr)
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nOpenGuildKit interface stopped.", file=sys.stderr)
    finally:
        server.server_close()
    return 0
