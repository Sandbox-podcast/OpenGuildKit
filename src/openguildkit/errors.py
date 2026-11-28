"""The one-line forms of the errors a person reads: a file that cannot be opened, in words, an unknown identifier
with the command that lists them, and the stable code of an error (`OpenGuildKit [OGK-TASK-004]: ...`).

docs/errors.md lists each code with its module, function and test (scripts/build_errors.py writes it).

Entry: os_error_message, unknown, OgkError, error_line, named_command
Tests: tests/test_error_forms.py, tests/test_error_codes.py
"""

import re

# Words that end the command a message names and start its prose again: "run openguildkit init only to set up...".
PROSE = frozenset({"only", "to", "in", "and", "or", "then", "at", "with", "if", "when", "for", "on", "from", "first"})


class OgkError(ValueError):
    """An error a person reads, with its stable code: `raise OgkError("OGK-TASK-004", f"Task already exists: {x}")`.
    The message is unchanged (`str(error)`); the CLI prints the code before it, and in `error.code` under --json."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


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
    if isinstance(error, PermissionError):
        return f"Cannot open {name}: permission denied."
    if isinstance(error, IsADirectoryError):
        return f"Cannot open {name}: it is a folder, not a file."
    return f"Cannot open {name}: {(error.strerror or 'it cannot be read').rstrip('.').lower()}."


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
