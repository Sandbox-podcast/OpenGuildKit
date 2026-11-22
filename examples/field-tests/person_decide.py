"""Stand-in for the person who decides, in field campaigns only.

    person-decide --project DIR TASK_ID --approve|--request-changes --by NAME --reason TEXT [--answer TEXT ...]
                  [--signature FILE --signer PRINCIPAL]

A tester plays two roles, the coding agent and the person it works for. The agent may never
approve its own plan, and `task decide` only accepts a person at a terminal. This script is
how the tester lets the person speak: it runs `openguildkit task decide` at a pseudo-terminal,
types the task ID at the confirmation prompt (then each --answer, one per further prompt) and
prints what the prompt showed. A tester calls it only when its scenario says the person decides.
In a project with signed approvals, --signature and --signer are passed on to `task decide`:
the person signs the decision payload with their own key, the stand-in never holds one.

Linux and macOS only: Windows has no pseudo-terminal in the standard library.
"""

import argparse
import os
import select
import subprocess
import sys
import tempfile
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
# Bytecode goes to a folder of its own, not next to the sources, and is reused from one command to the next.
ENV = {**{key: value for key, value in os.environ.items() if key != "PYTHONDONTWRITEBYTECODE"},
       "PYTHONPATH": os.pathsep.join(filter(None, [str(SRC), os.environ.get("PYTHONPATH")])),
       "PYTHONPYCACHEPREFIX": os.environ.get("PYTHONPYCACHEPREFIX") or str(Path(tempfile.gettempdir()) / "openguildkit-pycache"),
       "PYTHONIOENCODING": "utf-8"}


def decide(project: Path, task: str, action: str, by: str, reason: str, answers: list[str],
           signature: Path | None = None, signer: str | None = None) -> tuple[int, str]:
    """Run the decision at a pseudo-terminal and return the exit code and what was shown."""
    import pty

    if (signature is None) != (signer is None):
        raise ValueError("Pass both --signature and --signer, or neither.")
    command = [sys.executable, "-m", "openguildkit", "--project", str(project), "task", "decide", task,
               f"--{action}", "--by", by, "--reason", reason]
    if signature is not None:
        command += ["--signature", str(signature), "--signer", signer]
    master, slave = pty.openpty()
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, close_fds=True, env=ENV)
    os.close(slave)
    typed = [task, *answers]
    shown = b""
    while True:
        ready, _, _ = select.select([master], [], [], 1.0)
        if ready:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                break
            if not chunk:
                break
            shown += chunk
            if shown.rstrip().endswith((b":", b"?")) and typed:
                os.write(master, (typed.pop(0) + "\n").encode())
        elif process.poll() is not None:
            break
    process.wait()
    os.close(master)
    return process.returncode, shown.decode("utf-8", "replace")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("task")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--request-changes", action="store_true")
    parser.add_argument("--by", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--answer", action="append", default=[])
    parser.add_argument("--signature", type=Path, help="The person's signature of the decision payload.")
    parser.add_argument("--signer", help="The signer's principal in the allowed signers file.")
    args = parser.parse_args()
    if os.name != "posix":
        raise SystemExit("person-decide needs a pseudo-terminal, available on Linux and macOS.")
    try:
        code, shown = decide(args.project, args.task, "approve" if args.approve else "request-changes",
                             args.by, args.reason, args.answer, args.signature, args.signer)
    except ValueError as error:
        raise SystemExit(f"person-decide: {error}")
    sys.stdout.write(shown)
    sys.exit(code)


if __name__ == "__main__":
    main()
