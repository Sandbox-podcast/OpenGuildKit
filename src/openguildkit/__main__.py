"""Start openguildkit, as python -m openguildkit and as the installed openguildkit command.

Host hooks run openguildkit guard --hook before every edit an agent makes. That call goes straight to the guard,
without importing the rest of the CLI, and ends before importing the guard when the profile declares it off; a bare
--version answers without the CLI too. Every other command, and a hook call written any other way, goes to cli.main,
which parses it as before.
"""

import os
import sys
from pathlib import Path

# Before the first annotation, which an older Python cannot read: say what is missing, in one line. The floor is
# the requires-python of pyproject.toml (tests/test_python_floor.py compares them).
if sys.version_info < (3, 11):  # noqa: UP036 - INTENTIONAL(#520): the one line an older Python gets, which ruff's target cannot see
    raise SystemExit(f"OpenGuildKit needs Python 3.11 or later; this is Python {sys.version_info[0]}.{sys.version_info[1]}. "
                     "Run it with python3.11 or newer.")

HOOK_EVENTS = ("prompt", "pre-edit")


def hook_call(arguments: list[str]) -> tuple[str, Path | None] | None:
    """The event and project of a plain [--project PATH] guard --hook EVENT call; None for anything else."""
    project = None
    if arguments[:1] == ["--project"] and len(arguments) > 1:
        project, arguments = arguments[1], arguments[2:]
    elif arguments[:1] and arguments[0].startswith("--project="):
        project, arguments = arguments[0].partition("=")[2], arguments[1:]
    if len(arguments) == 3 and arguments[:2] == ["guard", "--hook"]:
        event = arguments[2]
    elif len(arguments) == 2 and arguments[0] == "guard" and arguments[1].startswith("--hook="):
        event = arguments[1].partition("=")[2]
    else:
        return None
    if event not in HOOK_EVENTS:
        return None
    if project is None:
        return event, None
    # A missing project folder, or a value cli.main reads differently, gets cli.main's own message.
    if not project or project.startswith("-") or not Path(project).is_dir():
        return None
    return event, Path(project)


def _run_hook(event: str, project: Path | None, console: bool) -> int:
    """The hook with the same output encoding and the same endings as cli.main."""
    if console:
        for stream in (sys.stdout, sys.stderr):
            if not stream.isatty() and hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(errors="backslashreplace")
    from .startup import guard_declared_off

    if guard_declared_off(project):  # Before importing the guard: an edit costs the interpreter and one read (#539).
        try:
            if not sys.stdin.isatty():
                sys.stdin.buffer.read()  # Read the host's input, as the guard does, so its write never fails.
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    from .guard import hook_command

    try:
        code = hook_command(event, project)
        sys.stdout.flush()
        return code
    except BrokenPipeError:
        try:  # The host stopped reading: end quietly, as cli.main does.
            null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(null, sys.stdout.fileno())
            os.close(null)
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    except OSError as error:
        from .cli_errors import print_trace

        print_trace()
        print(f"OpenGuildKit: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOpenGuildKit: Cancelled.", file=sys.stderr)
        return 130


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else list(argv)
    if arguments == ["--version"]:  # Without the CLI, whose import costs four times the interpreter's start (#539).
        from .startup import package_version

        print(f"openguildkit {package_version()}")
        return 0
    call = hook_call(arguments)
    if call is not None:
        return _run_hook(*call, console=argv is None)
    from .cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
