"""Run one openguildkit command for a field tester and append it, with its output, to the tester's commands.log.

`field.py prepare` puts this behind the `openguildkit` command on the testers' PATH, so every call a tester makes is
recorded in RUNS/TESTER/commands.log without any effort on its part:

    python logged.py RUNS ARGUMENTS...

The tester is found from the folder the command runs in, or from its --project. A call made elsewhere runs but is
not recorded. The command keeps its input, its exit code and its separate output and error streams.
"""

import shlex
import subprocess
import sys
from pathlib import Path

LOG = "commands.log"


def _project(arguments: list[str]) -> str | None:
    for index, argument in enumerate(arguments):
        if argument == "--project" and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith("--project="):
            return argument.split("=", 1)[1]
    return None


def workspace(runs: Path, cwd: Path, arguments: list[str]) -> Path | None:
    """The tester's folder under RUNS that the command works in, or None."""
    project = _project(arguments)
    candidates = ([(cwd / project).resolve()] if project else []) + [cwd.resolve()]
    for candidate in candidates:
        try:
            parts = candidate.relative_to(runs.resolve()).parts
        except ValueError:
            continue
        if parts:
            return runs.resolve() / parts[0]
    return None


def entry(folder: Path, cwd: Path, arguments: list[str], result: subprocess.CompletedProcess) -> str:
    """One command of the transcript: what was typed, where, what it printed and how it ended."""
    try:
        where = cwd.resolve().relative_to(folder).as_posix() or "."
    except ValueError:
        where = cwd.resolve().as_posix()
    printed = result.stdout + result.stderr
    if printed and not printed.endswith("\n"):
        printed += "\n"
    return f"$ {shlex.join(['openguildkit', *arguments])}  (in {where})\n{printed}[exit {result.returncode}]\n\n"


def main(argv: list[str]) -> int:
    runs, arguments = Path(argv[1]), argv[2:]
    result = subprocess.run([sys.executable, "-m", "openguildkit", *arguments], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    cwd = Path.cwd()
    folder = workspace(runs, cwd, arguments)
    if folder is not None and folder.is_dir():
        with (folder / LOG).open("a", encoding="utf-8") as log:
            log.write(entry(folder, cwd, arguments, result))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv))
