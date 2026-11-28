"""What the CLI says when a command ends on an error: the Python trace on request (OPENGUILDKIT_DEBUG=1), and the option
that named a file.

With OPENGUILDKIT_DEBUG=1, an error turned into one line prints its traceback on standard error first; the hook
that runs before every edit imports only this module for it, and `traceback` is loaded only when it is asked for.

Entry: print_trace, error_message, json_error, command_words
Tests: tests/test_cli_errors.py
"""

import os
import sys
from pathlib import Path

from .errors import OgkError, named_command, os_error_message
from .storage import SCHEMA_VERSION

VARIABLE = "OPENGUILDKIT_DEBUG"


def print_trace() -> None:
    """Print the traceback of the error being handled, when OPENGUILDKIT_DEBUG is 1: call it from the except block."""
    if os.environ.get(VARIABLE) == "1":
        import traceback

        traceback.print_exc(file=sys.stderr)


def _leaf(parser, args):
    """The parser of the command args came from."""
    for action in parser._actions:
        if action.choices and hasattr(action.choices, "get") and getattr(args, action.dest, None) in action.choices:
            return _leaf(action.choices[getattr(args, action.dest)], args)
    return parser


def command_words(parser, args) -> str:
    """The words of the command args came from, such as "task checks" or "host check", as the envelope of a --json
    answer names it: the subcommands, then the value of a positional argument that names a mode."""
    leaf = _leaf(parser, args)
    modes = [getattr(args, action.dest) for action in leaf._actions if not action.option_strings and action.choices
             and not hasattr(action.choices, "get") and getattr(args, action.dest, None) in action.choices]
    return " ".join([*leaf.prog.split()[1:], *modes])


def json_error(error: BaseException | None, text: str) -> dict:
    """An error under --json (#484): its code (errors.OgkError) or null, its message, and the command it names."""
    words = named_command(text)
    return {"schema_version": SCHEMA_VERSION, "error": {"code": error.code if isinstance(error, OgkError) else None,
                                                      "message": text,
                                                      "next": f"openguildkit {' '.join(words)}" if words else None}}


def error_message(error: BaseException, parser, args) -> str:
    """The message of an error, in words, with the option that named the file when the system could not open it:
    `Cannot open --file missing.json: it does not exist.` instead of `[Errno 2] No such file or directory: 'missing.json'`."""
    if not isinstance(error, OSError):
        return str(error) or "Input ended before completion."
    text = os_error_message(error)
    filename = getattr(error, "filename", None)
    if filename and error.strerror:
        for action in _leaf(parser, args)._actions:
            value = getattr(args, action.dest, None)
            if action.option_strings and isinstance(value, (str, Path)) and str(value) \
                    and Path(str(filename)).as_posix().endswith(Path(str(value)).as_posix()):
                return text.replace(f"Cannot open {filename}", f"Cannot open {action.option_strings[0]} {value}", 1)
    return text


