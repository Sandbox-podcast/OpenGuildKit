"""What the CLI says when a command ends on an error: the Python trace on request, and the option that named a file.

With OPENGUILDKIT_DEBUG=1, an error turned into one line prints its traceback on standard error first; the hook
that runs before every edit imports only this module for it, and `traceback` is loaded only when it is asked for.

Entry: print_trace, error_message
Tests: tests/test_cli_errors.py
"""

import os
import sys
from pathlib import Path

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


def error_message(error: BaseException, parser, args) -> str:
    """The message of an error, with the option that named the file when the system could not open it:
    `--file missing.json: No such file or directory` instead of `[Errno 2] No such file or directory: 'missing.json'`."""
    text = str(error) or "Input ended before completion."
    filename = getattr(error, "filename", None)
    if isinstance(error, OSError) and filename and error.strerror:
        for action in _leaf(parser, args)._actions:
            value = getattr(args, action.dest, None)
            if action.option_strings and isinstance(value, (str, Path)) and str(value) \
                    and Path(str(filename)).as_posix().endswith(Path(str(value)).as_posix()):
                return f"{action.option_strings[0]} {value}: {error.strerror}"
    return text
