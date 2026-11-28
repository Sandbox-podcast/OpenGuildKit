"""What the local web interface refuses to run or to read: commands that need a person at a terminal, paths outside the
project, secrets, and the project files it may show or write.

Entry: Refused, terminal_command, terminal_reason, check_request, check_paths, ProjectFiles, MAX_FILE,
REFUSALS, HUMAN_ONLY_TEXT
Tests: tests/test_approval_lifecycle.py, tests/test_cli_surface.py, tests/test_next_steps.py, tests/test_org_catalog.py,
tests/test_projects.py, tests/test_webui.py
"""

from __future__ import annotations

import contextlib
import json
import re
from http import HTTPStatus
from pathlib import Path

from .errors import InternalError
from .sensitive import credential_kind
from .shell import shell_command
from .storage import project_lock, write_text

MAX_FILE = 2 * 1024 * 1024
READABLE_SUFFIXES = {".json", ".jsonl", ".md", ".markdown", ".txt", ".yaml", ".yml"}
# Files the interface may write, besides what the commands write: the Storybook proposals a person validates.
WRITABLE_FILES = {".openguildkit/storybook/proposals.json"}
# Names that suggest a secret, and the files where tools keep their tokens (token.json, auth.json, a cloud service
# account, Azure Functions' local.settings.json): the page neither lists nor reads them. The tool's own records under
# .openguildkit/ are named after task and dossier IDs, such as token-rotation.json or password-reset.json, and stay
# readable.
SECRET_NAME = re.compile(r"(^\.env)|secret|credential|password|private[-_]?key|\.pem$|\.key$|id_rsa|id_ed25519", re.I)
TOKEN_FILE = re.compile(r"^token.*\.json$|^auth\.json$|service[-_]?account.*\.json$|^local\.settings\.json$", re.I)
# The settings where package managers, containers and frameworks keep a token or a password in clear: Yarn's
# npmAuthToken, .npmrc, .pypirc, .netrc, Git's stored credentials, ASP.NET's appsettings*.json, Rails' database.yml.
CREDENTIAL_FILE = re.compile(r"^\.yarnrc(?:\.ya?ml)?$|^\.npmrc$|^\.pypirc$|^[._]netrc$|^\.git-credentials$"
                             r"|^appsettings(?:\..+)?\.json$|^database\.ya?ml$", re.I)
# Files named by their folder: Docker's registry logins.
CREDENTIAL_PATH = {(".docker", "config.json")}


# Why the interface refuses a request: a stable code, sent as "reason" next to the English message, that the page
# translates. The acts left to a person at a terminal come first; web/docs/interface-projet.md lists every code.
REFUSALS = {
    "approve-at-terminal": "Approving a task needs a person at a terminal, or a signature in a project with signed "
                           "approvals.",
    "withdraw-at-terminal": "Withdrawing an approval needs the person at a terminal.",
    "cannot-run-at-terminal": "Declaring that a check command cannot run here, or withdrawing it, needs the person "
                              "at a terminal.",
    "clear-at-terminal": "Clearing a blocker without a signature needs the person at a terminal.",
    "complete-at-terminal": "Closing a task over sensitive points needs the person at a terminal.",
    "live-plan-at-terminal": "Applying a live MCP plan needs confirmation at a terminal.",
    "waiver-at-terminal": "A waiver needs the named person at a terminal.",
    "external-action-at-terminal": "Allowing an external action needs a person at a terminal.",
    "alert-accept-at-terminal": "Accepting a confirmed alert needs a person at a terminal.",
    "alert-severity-at-terminal": "Setting the severity of an alert needs a person at a terminal.",
    "alert-status-at-terminal": "Dismissing a critical alert, or taking a confirmed critical alert back, needs a "
                                "person at a terminal.",
    "weakens-protection": "A profile change that weakens a protection is the person's decision at an interactive "
                          "terminal.",
    "person-at-terminal": "Another decision the CLI leaves to a person at a terminal.",
    "send-setup-answers": "Send the setup answers: the interface cannot answer terminal prompts.",
    "send-task-answers": "Send the task answers: the interface cannot answer terminal prompts.",
    "invalid-profile": "The profile sent is not a valid profile.",
    "not-initialized": "The project is not initialized: set it up first.",
    "outside-project": "A path leaves the project.",
    "secret-file": "The name or the text of the file suggests a secret, or the file is inside .git: the interface "
                   "neither lists nor reads it.",
    "not-readable": "The interface only reads Markdown, JSON, YAML and text files.",
    "too-large": "The request or the file is too large.",
    "not-in-page": "A command or a file that does not belong in a page.",
    "project-busy": "Another OpenGuildKit command is writing this project. Try again.",
    "stale-token": "Missing or invalid session token: the server was restarted. Reload the page.",
    "foreign-page": "The request does not come from the interface's own page.",
    "bad-request": "A malformed request.",
    "not-found": "No such endpoint or file.",
    "open-printed-link": "Open the address openguildkit ui printed in its terminal: it carries the key of this run.",
    "server-error": "The server failed while handling the request.",
}
# The task action that withdraws an approval: the person's act at a terminal, like the approval itself.
WITHDRAW_ACTION = "revoke"
# The acts a person records at a terminal, by command and action, with the code of their refusal.
TERMINAL_ACTS = {
    ("task", "decide"): "approve-at-terminal", ("task", WITHDRAW_ACTION): "withdraw-at-terminal",
    ("task", "verify"): "cannot-run-at-terminal", ("task", "clear"): "clear-at-terminal",
    ("task", "complete"): "complete-at-terminal", ("task", "waive"): "waiver-at-terminal",
    ("task", "authorize"): "external-action-at-terminal", ("tools", "apply"): "live-plan-at-terminal",
    ("alerts", "accept"): "alert-accept-at-terminal", ("alerts", "severity"): "alert-severity-at-terminal",
    ("alerts", "set"): "alert-status-at-terminal", ("task", "alerts"): "alert-status-at-terminal",
    ("task", "consult"): "send-task-answers",
    ("init", None): "send-setup-answers",
}
# Commands the interface never runs. Each needs a person at a terminal, or does not belong in a page.
DENIED_COMMANDS = {
    "ci-check": "ci-check evaluates a central rule in CI.",
    "mcp": "mcp serves project metadata to a local MCP client on stdio, for the agent host.",
    "ui": "The interface is already running.",
}
HUMAN_ONLY_TEXT = "A person runs this command in their own terminal: the interface never records it."


class Refused(Exception):
    """A request the interface will not run. `code` is its stable error code (OGK-WEB-NNN, #487); `reason` is its
    kind in REFUSALS, which the page translates; `command` is what a person can type instead. It derives from
    Exception, not ValueError, so that code catching ValueError does not catch a refusal."""

    def __init__(self, code: str, message: str, command: str | None = None,
                 status: HTTPStatus = HTTPStatus.FORBIDDEN, *, reason: str):
        if reason not in REFUSALS:
            raise InternalError(f"Unknown refusal code: {reason}")
        super().__init__(message)
        self.code = code
        self.command = command
        self.status = status
        self.reason = reason

    def answer(self) -> dict:
        return {"error": str(self), "code": self.code, "command": self.command, "reason": self.reason}


def _subcommand(args) -> str | None:
    for name in ("action", "tools_action", "features_action", "alerts_action", "deliverable_action", "docs_action", "profile_action",
                 "mode"):
        value = getattr(args, name, None)
        if isinstance(value, str):
            return value
    return None


def terminal_command(root: Path, argv: list[str]) -> str:
    """The command the page asks the person to run at their terminal, quoted as the CLI quotes its own."""
    return shell_command(["openguildkit", "--project", str(root), *argv])


def terminal_reason(args) -> str:
    """The code of a refusal that leaves the act to a person at a terminal, from the command the page sent."""
    if args.command == "profile":
        return "weakens-protection"
    return TERMINAL_ACTS.get((args.command, _subcommand(args)), "person-at-terminal")


def _needs_person(args) -> bool:
    """What the page never records, whatever the CLI would answer: each is the person's act at a terminal."""
    command, action = args.command, _subcommand(args)
    if command == "task":
        return bool(action == "decide" and args.approve and not args.signature
                    or action == "verify" and (args.cannot_run or args.withdraw)
                    or action == "clear" and not args.signature and not args.payload
                    or action == "complete" and args.by
                    or action in ("waive", WITHDRAW_ACTION)
                    or action == "authorize" and args.allow)
    return bool(command == "tools" and action == "apply" and not args.mock
                or command == "alerts" and action in ("accept", "severity"))


def check_request(args, argv: list[str], root: Path) -> None:
    """Refuse what only a person at a terminal may record, and what does not belong in a page."""
    command = args.command
    if command in DENIED_COMMANDS:
        raise Refused("OGK-WEB-003", DENIED_COMMANDS[command], reason="not-in-page")
    action = _subcommand(args)
    if _needs_person(args):
        reason = terminal_reason(args)
        raise Refused("OGK-WEB-004", f"{REFUSALS[reason]} {HUMAN_ONLY_TEXT}", terminal_command(root, argv), reason=reason)
    if command == "guard" and args.hook:
        raise Refused("OGK-WEB-005", "guard --hook reads a host hook's input and runs inside the agent host.", reason="not-in-page")
    if command == "tools" and action == "mock":
        raise Refused("OGK-WEB-006", "tools mock runs an MCP server on stdio for the agent host; use tools call from the page.",
                      reason="not-in-page")
    if command == "integrations" and args.user:
        raise Refused("OGK-WEB-007", "The interface only installs agent files in this project, not in the home folder.",
                      reason="not-in-page")
    if command == "init" and not (args.questions or args.answers):
        raise Refused("OGK-WEB-008", REFUSALS["send-setup-answers"], status=HTTPStatus.BAD_REQUEST, reason="send-setup-answers")
    if command == "task" and action == "consult" and not args.answers:
        raise Refused("OGK-WEB-009", REFUSALS["send-task-answers"], status=HTTPStatus.BAD_REQUEST, reason="send-task-answers")


def _out_of_reach(root: Path, value: Path | str, uploads: set[Path]) -> str | None:
    """The code of the refusal for a path a command names, or None when the page may let the command use it."""
    path = Path(value)
    if path.is_absolute() and _resolved(path) in uploads:
        return None
    target = _resolved(path if path.is_absolute() else root / path)
    try:
        relative = target.relative_to(root)
    except ValueError:
        return "outside-project"
    return "secret-file" if _in_git(relative.parts) or _secret(relative.parts) else None


def _resolved(path: Path) -> Path:
    """The path with its links followed; a request whose path no file can have (a NUL, a lone surrogate) is refused."""
    try:
        return path.resolve()
    except ValueError:
        raise Refused("OGK-WEB-010", "A path holds a character no file name can hold, such as a NUL.", status=HTTPStatus.BAD_REQUEST,
                      reason="bad-request") from None


def _in_git(parts) -> bool:
    """.git whatever its case: a disk that ignores case writes .GIT/x into the repository's own folder."""
    return any(part.casefold() == ".git" for part in parts)


def _secret(parts: tuple[str, ...]) -> bool:
    """A path the page neither lists nor reads: a name that suggests a secret, or a tool's token file."""
    if not parts or parts[0] == ".openguildkit":
        return False
    if any(SECRET_NAME.search(part) for part in parts):
        return True
    return bool(TOKEN_FILE.search(parts[-1]) or CREDENTIAL_FILE.search(parts[-1])
                or tuple(part.casefold() for part in parts[-2:]) in CREDENTIAL_PATH)


def check_paths(args, root: Path, uploads: set[Path]) -> None:
    """Every file a command reads or writes stays inside the project and is one the page itself would read, except the
    files the page uploaded."""
    for name, value in vars(args).items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            path_like = isinstance(item, Path) or (name in ("log", "config_dir") and isinstance(item, str))
            reason = _out_of_reach(root, item, uploads) if path_like else None
            if reason == "outside-project":
                raise Refused("OGK-WEB-011", f"--{name.replace('_', '-')} must name a file inside the project: {item}",
                              status=HTTPStatus.BAD_REQUEST, reason=reason)
            if reason:
                raise Refused("OGK-WEB-012", f"--{name.replace('_', '-')} names a path the interface does not read, because its name "
                              f"suggests a secret or it is inside .git: {item}", reason=reason)


class ProjectFiles:
    """Reads text files of the project for the page, and writes the few files a person edits there."""

    def __init__(self, root: Path):
        self.root = root

    def _resolve(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or relative.startswith("/") or Path(relative).is_absolute() or "\\" in relative:
            raise Refused("OGK-WEB-013", "Give a path relative to the project, with forward slashes.", status=HTTPStatus.BAD_REQUEST,
                          reason="bad-request")
        target = _resolved(self.root / relative)
        try:
            parts = target.relative_to(self.root).parts
        except ValueError:
            raise Refused("OGK-WEB-014", "The path leaves the project.", status=HTTPStatus.BAD_REQUEST,
                          reason="outside-project") from None
        if _in_git(parts):
            raise Refused("OGK-WEB-015", "The interface does not read or write inside .git.", reason="secret-file")
        if _secret(parts):
            raise Refused("OGK-WEB-016", "The name of this path suggests a secret: the interface does not read it.",
                          reason="secret-file")
        return target

    def list(self, relative: str) -> list[dict]:
        folder = self._resolve(relative)
        if not folder.is_dir():
            return []
        entries = []
        for child in sorted(folder.iterdir(), key=lambda item: item.name):
            parts = child.relative_to(self.root).parts
            if child.is_symlink() or _secret(parts) or _in_git(parts):
                continue
            stat = child.stat()
            entries.append({"name": child.name, "kind": "folder" if child.is_dir() else "file",
                            "size": stat.st_size, "modified": int(stat.st_mtime)})
        return entries

    def read(self, relative: str) -> dict:
        target = self._resolve(relative)
        if target.suffix.lower() not in READABLE_SUFFIXES:
            raise Refused("OGK-WEB-017", REFUSALS["not-readable"], reason="not-readable")
        if not target.exists():
            # A file a project has not created yet (proposals, a dossier) is an answer, not an error.
            return {"path": relative, "text": None, "missing": True}
        if not target.is_file():
            raise Refused("OGK-WEB-018", f"{relative} is not a file.", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
        if target.stat().st_size > MAX_FILE:
            raise Refused("OGK-WEB-019", "The file is larger than 2 MB.", status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                          reason="too-large")
        text = target.read_text(encoding="utf-8", errors="replace")
        # A cloud key keeps its generated name, and a setting holds a token in clear: the text decides too. The file is
        # refused whole, as a secret name is, rather than masked: the page saves back what it reads.
        kind = credential_kind(text)
        if kind:
            raise Refused("OGK-WEB-020", f"{relative} holds what looks like {kind}: the interface does not read it.",
                          reason="secret-file")
        return {"path": relative, "text": text}

    def write(self, relative: str, text: str) -> dict:
        if relative not in WRITABLE_FILES:
            raise Refused("OGK-WEB-021", "The interface only writes the Storybook proposals; the commands write everything else.",
                          reason="not-in-page")
        if not isinstance(text, str):
            raise Refused("OGK-WEB-022", "text must be a string.", status=HTTPStatus.BAD_REQUEST, reason="bad-request")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError:
            raise Refused("OGK-WEB-023", "text holds a character UTF-8 cannot encode.", status=HTTPStatus.BAD_REQUEST,
                          reason="bad-request") from None
        try:
            json.loads(text)
        except ValueError as error:
            raise Refused("OGK-WEB-024", f"Invalid JSON: {error}", status=HTTPStatus.BAD_REQUEST, reason="bad-request") from None
        target = self._resolve(relative)
        # storybook propose writes the same file under the project lock.
        with contextlib.ExitStack() as held:
            try:
                held.enter_context(project_lock(self.root / ".openguildkit"))
            except ValueError as error:
                raise Refused("OGK-WEB-025", str(error), status=HTTPStatus.CONFLICT, reason="project-busy") from None
            write_text(target, text if text.endswith("\n") else text + "\n")
        return {"path": relative, "written": True}
