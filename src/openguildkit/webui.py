"""Local web interface: the built front end and a JSON API over the CLI, on the loopback interface only.

The API runs the same commands a person types, in this process, one at a time. It never runs what needs a
person at a terminal: approving a task or clearing a blocker without a signature, waiving a blocker, allowing an
external action, accepting an alert or setting its severity, declaring that a check command cannot run, closing a
task over sensitive points, or a profile change that weakens a protection. For those, it answers with the command
to type.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import mimetypes
import os
import pickle
import re
import secrets
import sys
import tempfile
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PORT = 7311
MAX_BODY = 8 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
READABLE_SUFFIXES = {".json", ".jsonl", ".md", ".markdown", ".txt", ".yaml", ".yml"}
# Files the interface may write, besides what the commands write: the Storybook proposals a person validates.
WRITABLE_FILES = {".openguildkit/storybook/proposals.json"}
SECRET_NAME = re.compile(r"(^\.env)|secret|credential|password|private[-_]?key|\.pem$|\.key$|id_rsa|id_ed25519", re.I)
UPLOAD_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")

# Commands the interface never runs. Each needs a person at a terminal, or does not belong in a page.
DENIED_COMMANDS = {
    "ci-check": "ci-check evaluates a central rule in CI.",
    "ui": "The interface is already running.",
}
HUMAN_ONLY_TEXT = "A person runs this command in their own terminal: the interface never records it."
TERMINAL_NEEDED = re.compile(
    r"interactive terminal|needs a terminal|at a terminal|in their own terminal|runs the command at", re.I)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
       "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'; "
       "object-src 'none'")


class Refused(Exception):
    """A request the interface will not run. `command` is what a person can type instead."""

    def __init__(self, message: str, command: str | None = None, status: HTTPStatus = HTTPStatus.FORBIDDEN):
        super().__init__(message)
        self.command = command
        self.status = status


def _subcommand(args) -> str | None:
    for name in ("action", "tools_action", "alerts_action", "deliverable_action", "docs_action", "profile_action",
                 "mode"):
        value = getattr(args, name, None)
        if isinstance(value, str):
            return value
    return None


def _quote(value: str) -> str:
    """Single quotes read the same in PowerShell and POSIX shells; only the escape of a quote differs."""
    if re.fullmatch(r"[A-Za-z0-9._:/@=+-]+", value):
        return value
    return "'" + value.replace("'", "''" if os.name == "nt" else "'\\''") + "'"


def terminal_command(root: Path, argv: list[str]) -> str:
    return " ".join(["openguildkit", "--project", _quote(str(root)), *(_quote(item) for item in argv)])


def check_request(args, argv: list[str], root: Path) -> None:
    """Refuse what only a person at a terminal may record, and what does not belong in a page."""
    command = args.command
    if command in DENIED_COMMANDS:
        raise Refused(DENIED_COMMANDS[command])
    action = _subcommand(args)
    human = None
    if command == "task" and action == "decide" and args.approve and not args.signature:
        human = "Approving a task needs a person at a terminal, or a signature in a project with signed approvals."
    elif command == "task" and action == "verify" and (args.cannot_run or args.withdraw):
        human = "Declaring that a check command cannot run here, or withdrawing it, needs the person at a terminal."
    elif command == "task" and action == "clear" and not args.signature and not args.payload:
        human = "Clearing a blocker without a signature needs the person at a terminal."
    elif command == "task" and action == "complete" and args.by:
        human = "Closing a task over sensitive points needs the person at a terminal."
    elif command == "tools" and action == "apply" and not args.mock:
        human = "Applying a live MCP plan needs confirmation at a terminal."
    elif command == "task" and action == "waive":
        human = "A waiver needs the named person at a terminal."
    elif command == "task" and action == "authorize" and args.allow:
        human = "Allowing an external action needs a person at a terminal."
    elif command == "alerts" and action == "accept":
        human = "Accepting a confirmed alert needs a person at a terminal."
    elif command == "alerts" and action == "severity":
        human = "Setting the severity of an alert needs a person at a terminal."
    if human:
        raise Refused(f"{human} {HUMAN_ONLY_TEXT}", terminal_command(root, argv))
    if command == "guard" and args.hook:
        raise Refused("guard --hook reads a host hook's input and runs inside the agent host.")
    if command == "tools" and action == "mock":
        raise Refused("tools mock runs an MCP server on stdio for the agent host; use tools call from the page.")
    if command == "integrations" and args.user:
        raise Refused("The interface only installs agent files in this project, not in the home folder.")
    if command == "init" and not (args.questions or args.answers):
        raise Refused("Send the setup answers: the interface cannot answer terminal prompts.", status=HTTPStatus.BAD_REQUEST)
    if command == "task" and action == "consult" and not args.answers:
        raise Refused("Send the task answers: the interface cannot answer terminal prompts.", status=HTTPStatus.BAD_REQUEST)


def _inside(root: Path, value: Path | str, uploads: set[Path]) -> bool:
    path = Path(value)
    if path.is_absolute() and path.resolve() in uploads:
        return True
    target = (path if path.is_absolute() else root / path).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError:
        return False
    return ".git" not in relative.parts


def check_paths(args, root: Path, uploads: set[Path]) -> None:
    """Every file a command reads or writes stays inside the project, except the files the page uploaded."""
    for name, value in vars(args).items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            path_like = isinstance(item, Path) or (name in ("log", "config_dir") and isinstance(item, str))
            if path_like and not _inside(root, item, uploads):
                raise Refused(f"--{name.replace('_', '-')} must name a file inside the project: {item}",
                              status=HTTPStatus.BAD_REQUEST)


def _files_signature(folder: Path | None) -> tuple:
    """Names, sizes and modification times of the JSON files under a folder: any edit changes it."""
    if folder is None or not folder.is_dir():
        return ()
    return tuple(sorted((str(path), stat.st_size, stat.st_mtime_ns)
                        for path in folder.rglob("*.json") for stat in (path.stat(),)))


def _file_signature(path: Path) -> tuple:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None)
    return (str(path), stat.st_size, stat.st_mtime_ns)


class Speedups:
    """What every command rebuilds, kept between the commands of this server: the argument parser, the
    validated catalog and the validated catalog lock. Each is reused only while its files are unchanged, and
    each command gets its own copy. Active only while the server runs a command; the CLI itself is untouched.

    The bundled registry ships with the package and is looked at again every two seconds at most; the
    project's own catalog folder and lock are looked at before every command."""

    REGISTRY_RECHECK = 2.0

    def __init__(self):
        self.parser = None
        self.catalogs: dict[tuple, bytes] = {}
        self.locks: dict[tuple, bytes] = {}
        self.registry: tuple[float, tuple] = (0.0, ())

    def _registry_signature(self, builtin: Path) -> tuple:
        checked, signature = self.registry
        now = time.monotonic()
        if now - checked > self.REGISTRY_RECHECK:
            signature = _files_signature(builtin)
            self.registry = (now, signature)
        return signature

    @staticmethod
    def _remember(cache: dict, key: tuple, value) -> None:
        if len(cache) >= 4:
            cache.clear()
        cache[key] = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)

    @contextlib.contextmanager
    def active(self, cli):
        from importlib.resources import files

        names = ("_parser", "load_catalog", "read_lock")
        if not all(callable(getattr(cli, name, None)) for name in names):
            yield  # the CLI changed shape: run its commands as they are, without the cache
            return
        originals = tuple(getattr(cli, name) for name in names)
        original_parser, original_load, original_read_lock = originals
        builtin = Path(str(files("openguildkit").joinpath("registry")))

        def parser():
            if self.parser is None:
                self.parser = original_parser()
            return self.parser

        def load_catalog(extra_dir=None, *, central_policy=None):
            if central_policy is not None:
                return original_load(extra_dir, central_policy=central_policy)
            key = (str(extra_dir), self._registry_signature(builtin), _files_signature(extra_dir))
            if key not in self.catalogs:
                self._remember(self.catalogs, key, original_load(extra_dir))
            return pickle.loads(self.catalogs[key])

        def read_lock(state):
            key = _file_signature(state / "catalog.lock.json")
            if key not in self.locks:
                self._remember(self.locks, key, original_read_lock(state))
            return pickle.loads(self.locks[key])

        for name, replacement in zip(names, (parser, load_catalog, read_lock)):
            setattr(cli, name, replacement)
        try:
            yield
        finally:
            for name, original in zip(names, originals):
                setattr(cli, name, original)


def _without(data, keys: set[str]):
    if isinstance(data, dict):
        return {key: _without(value, keys) for key, value in data.items() if key not in keys}
    if isinstance(data, list):
        return [_without(value, keys) for value in data]
    return data


def _options(body: dict) -> dict:
    omit = body.get("omit")
    if omit is not None and (not isinstance(omit, list) or len(omit) > 20 or not all(isinstance(k, str) for k in omit)):
        raise Refused("omit must be a list of at most 20 key names.", status=HTTPStatus.BAD_REQUEST)
    return {"keep_text": bool(body.get("raw")), "omit": omit}


class CliRunner:
    """Runs CLI commands in this process, one at a time, with a stdin that is never a terminal."""

    def __init__(self, root: Path):
        self.root = root
        self.lock = threading.Lock()
        self.speedups = Speedups()

    def parse(self, argv: list[str]):
        from . import cli

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                return cli._parser().parse_args(["--project", str(self.root), *argv])
            except SystemExit:
                message = err.getvalue().strip().splitlines()
                raise Refused(message[-1] if message else "Invalid command.", status=HTTPStatus.BAD_REQUEST) from None

    def run(self, argv: list[str], uploads: dict[str, str] | None = None, *, keep_text: bool = False,
            omit: list[str] | None = None) -> dict:
        """Run one command. Its JSON output comes back parsed; the same text is dropped unless keep_text,
        and the keys named in omit are removed at any depth (a page that shows a list of tasks does not
        need the text of each consultation)."""
        from . import cli

        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
            raise Refused("argv must be a non-empty list of strings.", status=HTTPStatus.BAD_REQUEST)
        if argv[0].startswith("-"):
            raise Refused("Start with a command; the interface sets the project itself.", status=HTTPStatus.BAD_REQUEST)
        # sys.stdout, sys.stderr and sys.stdin are process-wide: parsing and running hold the same lock, or a
        # concurrent request would capture another command's output.
        typed = list(argv)
        with tempfile.TemporaryDirectory(prefix="ogk-ui-") as folder, self.lock, self.speedups.active(cli):
            argv, written = self._with_uploads(argv, uploads or {}, Path(folder))
            args = self.parse(argv)
            check_request(args, typed, self.root)
            check_paths(args, self.root, written)
            out, err = io.StringIO(), io.StringIO()
            saved = sys.stdin
            sys.stdin = io.StringIO("")
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
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
            if not keep_text:
                stdout = ""
        stderr = err.getvalue()
        for shown in {str(Path(folder).resolve()), folder}:
            stderr = stderr.replace(shown, "<upload>")
        result = {"code": code, "stdout": stdout, "stderr": stderr, "json": data}
        # Some decisions need a person at a terminal only in some cases (dismissing a critical alert):
        # the CLI says so, and the page shows the command to type.
        if code != 0 and TERMINAL_NEEDED.search(stderr):
            result["command"] = terminal_command(self.root, typed)
        return result

    @staticmethod
    def _with_uploads(argv: list[str], uploads: dict[str, str], folder: Path) -> tuple[list[str], set[Path]]:
        if not isinstance(uploads, dict):
            raise Refused("uploads must be an object of file names and texts.", status=HTTPStatus.BAD_REQUEST)
        written: dict[str, Path] = {}
        for name, text in uploads.items():
            if not isinstance(name, str) or not UPLOAD_NAME.match(name) or not isinstance(text, str):
                raise Refused(f"Invalid upload: {name!r}", status=HTTPStatus.BAD_REQUEST)
            path = folder / name
            path.write_text(text, encoding="utf-8", newline="")
            written[name] = path.resolve()
        result = []
        for item in argv:
            if item.startswith("@upload:"):
                name = item.removeprefix("@upload:")
                if name not in written:
                    raise Refused(f"No upload named {name}.", status=HTTPStatus.BAD_REQUEST)
                item = str(written[name])
            result.append(item)
        return result, set(written.values())


class ProjectFiles:
    """Reads text files of the project for the page, and writes the few files a person edits there."""

    def __init__(self, root: Path):
        self.root = root

    def _resolve(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or "\\" in relative:
            raise Refused("Give a path relative to the project, with forward slashes.", status=HTTPStatus.BAD_REQUEST)
        target = (self.root / relative).resolve()
        try:
            parts = target.relative_to(self.root).parts
        except ValueError:
            raise Refused("The path leaves the project.", status=HTTPStatus.BAD_REQUEST) from None
        if ".git" in parts or any(SECRET_NAME.search(part) for part in parts):
            raise Refused("The interface does not read this path.")
        return target

    def list(self, relative: str) -> list[dict]:
        folder = self._resolve(relative)
        if not folder.is_dir():
            return []
        entries = []
        for child in sorted(folder.iterdir(), key=lambda item: item.name):
            if child.is_symlink() or SECRET_NAME.search(child.name) or child.name == ".git":
                continue
            stat = child.stat()
            entries.append({"name": child.name, "kind": "folder" if child.is_dir() else "file",
                            "size": stat.st_size, "modified": int(stat.st_mtime)})
        return entries

    def read(self, relative: str) -> dict:
        target = self._resolve(relative)
        if target.suffix.lower() not in READABLE_SUFFIXES:
            raise Refused("The interface only reads Markdown, JSON, YAML and text files.")
        if not target.exists():
            # A file a project has not created yet (proposals, a dossier) is an answer, not an error.
            return {"path": relative, "text": None, "missing": True}
        if not target.is_file():
            raise Refused(f"{relative} is not a file.", status=HTTPStatus.BAD_REQUEST)
        if target.stat().st_size > MAX_FILE:
            raise Refused("The file is larger than 2 MB.", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        return {"path": relative, "text": target.read_text(encoding="utf-8", errors="replace")}

    def write(self, relative: str, text: str) -> dict:
        if relative not in WRITABLE_FILES:
            raise Refused("The interface only writes the Storybook proposals; the commands write everything else.")
        if not isinstance(text, str):
            raise Refused("text must be a string.", status=HTTPStatus.BAD_REQUEST)
        try:
            json.loads(text)
        except ValueError as error:
            raise Refused(f"Invalid JSON: {error}", status=HTTPStatus.BAD_REQUEST) from None
        from .storage import write_text

        target = self._resolve(relative)
        write_text(target, text if text.endswith("\n") else text + "\n")
        return {"path": relative, "written": True}


def find_front_end(explicit: Path | None) -> Path | None:
    """The built front end: --static, the copy inside the package, or web/dist in a source checkout."""
    if explicit is not None:
        return explicit.resolve() if (explicit / "index.html").is_file() else None
    here = Path(__file__).resolve().parent
    # In a source checkout, a fresh `npm run build` wins over an older copy left by `npm run bundle`.
    found = [folder for folder in (here / "web_dist", here.parents[1] / "web" / "dist") if (folder / "index.html").is_file()]
    return max(found, key=lambda folder: (folder / "index.html").stat().st_mtime).resolve() if found else None


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenGuildKit"
    sys_version = ""
    app: "WebApp"

    def log_message(self, format, *args):  # noqa: A002 - signature of the base class
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
        body = self._compressed(json.dumps(data, ensure_ascii=False).encode("utf-8"), extra)
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _host_allowed(self) -> bool:
        return (self.headers.get("Host") or "").lower() in self.app.hosts

    def do_HEAD(self):  # noqa: N802 - http.server naming
        self.do_GET()

    def do_GET(self):  # noqa: N802
        if not self._host_allowed():
            self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Unknown host."})
            return
        path = urlsplit(self.path).path
        if path == "/api/session":
            self._json(HTTPStatus.OK, self.app.session())
            return
        if path.startswith("/api/"):
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "Use POST for the API."})
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
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found."})
            return
        body = target.read_bytes()
        if target.name == "index.html":
            # Tells the page it is served by the CLI, so it loads the project code and its session together.
            body = body.replace(b"<head>", b'<head><meta name="openguildkit-ui" content="1">', 1)
        kind = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if kind.startswith("text/") or kind in ("application/javascript", "application/json", "image/svg+xml"):
            kind += "; charset=utf-8"
        cache = "no-cache" if target.name == "index.html" else "public, max-age=31536000, immutable" \
            if "/assets/" in f"/{relative}" and re.search(r"-[A-Za-z0-9_-]{8,}\.", target.name) else "no-cache"
        extra = {"Content-Security-Policy": CSP, "Cache-Control": cache}
        if kind.startswith(("text/", "application/javascript", "application/json", "image/svg+xml")):
            body = self._compressed(body, extra)
        self._send(HTTPStatus.OK, body, kind, extra)

    def do_POST(self):  # noqa: N802
        if not self._host_allowed():
            self._json(HTTPStatus.MISDIRECTED_REQUEST, {"error": "Unknown host."})
            return
        if (self.headers.get("Origin") or "").lower() not in self.app.origins:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Requests must come from the interface's own page."})
            return
        if not secrets.compare_digest(self.headers.get("X-OGK-Token") or "", self.app.token):
            self._json(HTTPStatus.FORBIDDEN, {"error": "Missing or invalid session token. Reload the page."})
            return
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Send JSON."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "The request is too large."})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("not an object")
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "The body is not a JSON object."})
            return
        try:
            self._json(HTTPStatus.OK, self.app.handle(urlsplit(self.path).path, body))
        except Refused as refusal:
            self._json(refusal.status, {"error": str(refusal), "command": refusal.command})
        except Exception as error:  # noqa: BLE001 - report to the page instead of dropping the connection
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"{type(error).__name__}: {error}"})


class WebApp:
    def __init__(self, root: Path, front: Path | None, port: int, verbose: bool = False):
        from .lock import package_version

        self.root = root
        self.front = front
        self.token = secrets.token_urlsafe(32)
        self.runner = CliRunner(root)
        self.files = ProjectFiles(root)
        self.version = package_version()
        self.verbose = verbose
        self.set_port(port)

    def set_port(self, port: int) -> None:
        self.port = port
        self.hosts = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}
        self.origins = {f"http://{host}" for host in self.hosts}

    def session(self) -> dict:
        return {
            "app": "openguildkit-ui",
            "version": self.version,
            "token": self.token,
            "project": {"root": str(self.root), "name": self.root.name,
                        "initialized": (self.root / ".openguildkit" / "project.json").is_file()},
            "human_only": ["task decide --approve", "task clear", "task waive", "task authorize --allow",
                           "task verify --cannot-run", "task verify --withdraw", "task complete --by", "alerts accept",
                           "alerts severity", "profile (weakening a protection)", "tools apply (live)"],
        }

    def handle(self, path: str, body: dict):
        if path == "/api/run":
            if "batch" in body:
                batch = body["batch"]
                if not isinstance(batch, dict) or len(batch) > 40:
                    raise Refused("batch must be an object of at most 40 commands.", status=HTTPStatus.BAD_REQUEST)
                options = _options(body)
                results = {}
                for key, argv in batch.items():
                    try:
                        results[key] = self.runner.run(argv, **options)
                    except Refused as refusal:
                        results[key] = {"code": 1, "stdout": "", "stderr": str(refusal), "json": None,
                                        "command": refusal.command}
                return {"results": results}
            return self.runner.run(body.get("argv"), body.get("uploads"), **_options(body))
        if path == "/api/files/list":
            return {"entries": self.files.list(body.get("path", ""))}
        if path == "/api/files/read":
            return self.files.read(body.get("path", ""))
        if path == "/api/files/write":
            return self.files.write(body.get("path", ""), body.get("text"))
        if path == "/api/profile/save":
            return self.save_profile(body.get("text"))
        raise Refused("Unknown endpoint.", status=HTTPStatus.NOT_FOUND)

    def save_profile(self, text) -> dict:
        """Write .openguildkit/project.json and run sync; put the previous profile back when sync refuses it.

        A change that weakens a protection is the person's decision at a terminal, as with the profile commands:
        it is refused with the command to type, and nothing is written."""
        from .storage import write_text

        if not isinstance(text, str):
            raise Refused("text must be a string.", status=HTTPStatus.BAD_REQUEST)
        try:
            profile = json.loads(text)
            if not isinstance(profile, dict):
                raise ValueError("the profile is a JSON object")
        except ValueError as error:
            raise Refused(f"Invalid JSON: {error}", status=HTTPStatus.BAD_REQUEST) from None
        target = self.root / ".openguildkit" / "project.json"
        if not target.is_file():
            raise Refused("The project is not initialized: set it up first.", status=HTTPStatus.CONFLICT)
        previous = target.read_text(encoding="utf-8")
        # An invalid profile is refused as such, before anything is compared: the page puts the previous one back.
        problem = profile_problem(self.root, profile)
        if problem:
            return {"code": 1, "stdout": "", "stderr": f"OpenGuildKit: {problem}", "json": None, "restored": True}
        weakening = weakening_changes(self.root, json.loads(previous), profile)
        if weakening:
            raise Refused(f"{'; '.join(change for change, _ in weakening)}: this weakens a protection, which is the "
                          f"person's decision at an interactive terminal. {HUMAN_ONLY_TEXT} Nothing was written.",
                          terminal_command(self.root, weakening[0][1]))
        with self.runner.lock:
            write_text(target, text if text.endswith("\n") else text + "\n")
        result = self.runner.run(["sync"])
        if result["code"] != 0:
            with self.runner.lock:
                write_text(target, previous)
            result["restored"] = True
        return result


def profile_problem(root: Path, profile: dict) -> str | None:
    """Why a hand-edited profile cannot be used, by the same validation as init and sync, or None."""
    from .catalog import load_catalog
    from .project import validate_profile

    try:
        validate_profile(profile, load_catalog(root / ".openguildkit" / "catalog"))
    except ValueError as error:
        return str(error)
    return None


def weakening_changes(root: Path, before: dict, after: dict) -> list[tuple[str, list[str]]]:
    """What a hand-edited profile weakens, by the profile commands' own rule, each with the command to type."""
    from .catalog import load_catalog
    from .profile_cli import weakening_changes as weakened

    return weakened(before, after, load_catalog(root / ".openguildkit" / "catalog"))


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    # A page load opens a dozen connections at once; Windows refuses them past the default backlog of 5.
    request_queue_size = 64

    def handle_error(self, request, client_address):
        # A browser that navigates away closes its connections: nothing to report.
        if isinstance(sys.exc_info()[1], (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def make_server(root: Path, port: int = DEFAULT_PORT, front: Path | None = None, verbose: bool = False):
    """Bind the server on 127.0.0.1. Port 0 picks a free port."""
    app = WebApp(root, front, port, verbose)

    class BoundHandler(Handler):
        pass

    BoundHandler.app = app
    server = LocalServer(("127.0.0.1", port), BoundHandler)
    server.daemon_threads = True
    app.set_port(server.server_address[1])
    return server, app


def serve(root: Path, port: int = DEFAULT_PORT, static: Path | None = None, open_browser: bool = True,
          verbose: bool = False) -> int:
    front = find_front_end(static)
    os.chdir(root)  # relative paths given in the page resolve inside the project, as in a terminal opened there
    try:
        server, app = make_server(root, port, front, verbose)
    except OSError:
        if port == 0:
            raise
        server, app = make_server(root, 0, front, verbose)
        print(f"Port {port} is busy; using {app.port}.", file=sys.stderr)
    url = f"http://127.0.0.1:{app.port}/"
    print(f"OpenGuildKit interface for {root}\n{url}\nPress Ctrl+C to stop.", flush=True)
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
