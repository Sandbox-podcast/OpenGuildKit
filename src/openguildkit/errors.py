"""The one-line forms of the errors a person reads: a file that cannot be opened, in words, an unknown identifier
with the command that lists them, and the stable code of an error (`OpenGuildKit [OGK-TASK-004]: ...`).

docs/errors.md lists each code with its module, function and test (scripts/build_errors.py writes it).
A code names its module's zone (OGK-TASK-, OGK-WEB-), except the FILE codes: a file the system could not open, one
code per kind of failure, shared by every command. They are the only codes built in one function (file_error) for
many callers.

Entry: os_error_message, file_error, unknown, OgkError, InternalError, error_line, named_command
Tests: tests/test_error_forms.py, tests/test_error_codes.py
"""

import os
import re

# Words that end the command a message names and start its prose again: "run openguildkit init only to set up...".
PROSE = frozenset({"only", "to", "in", "and", "or", "then", "at", "with", "if", "when", "for", "on", "from", "first"})


class OgkError(ValueError):
    """An error a person reads, with its stable code: `raise OgkError("OGK-TASK-004", f"Task already exists: {x}")`.
    The message is unchanged (`str(error)`); the CLI prints the code before it, and in `error.code` under --json."""

    def __init__(self, code: str, message: object):
        super().__init__(message)
        self.code = code


class InternalError(ValueError):
    """A broken invariant of the code itself, which no command or file a person writes can reach: it has no code
    (#487). An error a person can meet is an OgkError."""


def error_line(error: BaseException, text: str) -> str:
    """The one line the CLI prints for an error: its code first when it has one."""
    return f"OpenGuildKit [{error.code}]: {text}" if isinstance(error, OgkError) else f"OpenGuildKit: {text}"


def os_error_message(error: OSError) -> str:
    """What failed on which file, in words, never the `[Errno N]` text of Python."""
    name = error.filename
    if name is None:
        return f"{error.strerror or error}".rstrip(".") + "."
    if isinstance(error, FileNotFoundError):
        return f"Cannot open {name}: it does not exist."
    if _is_folder(error):
        return f"Cannot open {name}: it is a folder, not a file."
    if isinstance(error, PermissionError):
        return f"Cannot open {name}: permission denied."
    return f"Cannot open {name}: {(error.strerror or 'it cannot be read').rstrip('.').lower()}."


def _is_folder(error: OSError) -> bool:
    """Windows answers PermissionError, not IsADirectoryError, when a folder is opened as a file."""
    if isinstance(error, IsADirectoryError):
        return True
    return isinstance(error, PermissionError) and isinstance(error.filename, str) and os.path.isdir(error.filename)


def file_error(error: OSError, text: str) -> OgkError:
    """The error a person reads for a file the system could not open, with the code of its kind: missing, permission
    denied, a folder given as a file, or any other failure. `text` is its line, os_error_message or a longer form."""
    if isinstance(error, FileNotFoundError):
        return OgkError("OGK-FILE-001", text)
    if _is_folder(error):
        return OgkError("OGK-FILE-003", text)
    if isinstance(error, PermissionError):
        return OgkError("OGK-FILE-002", text)
    return OgkError("OGK-FILE-004", text)


def unknown(kind: str, value: object, command: str) -> str:
    """The error for an identifier the project does not know: the kind, the value and the command that lists them."""
    return f"Unknown {kind}: {value}. Run openguildkit {command}."


def named_command(message: str) -> list[str] | None:
    """The words of the command a CLI refusal names ("... openguildkit task complete t1 --by INITIALS, at a terminal."),
    up to the end of its clause or the prose that follows it ("openguildkit init in it"), or None when it names none."""
    match = re.search(r"\bopenguildkit (.+)", message)
    if match is None:
        return None
    words: list[str] = []
    for word in match.group(1).split():
        if words and word in PROSE:
            break
        words.append(word.rstrip(",;."))
        if word.endswith((",", ";", ".")):
            break
    words = [word for word in words if word]
    if "--project" in words[:1]:
        words = words[2:]
    return words or None
