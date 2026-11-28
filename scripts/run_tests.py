"""Run each test file in its own process, several at once, and print only what failed.

    python scripts/run_tests.py [--jobs N] [TEST_FILE ...]

Without a file, it runs every test file that `python -m unittest discover -s tests` finds, the largest first, so
the long files do not finish last. Each file runs as `python -m unittest tests.MODULE`; the output of a file is
printed only when it fails, in full, and the command then exits 1. `--jobs` defaults to half the processors. The
sequential command stays the one for `--durations`: `python -m unittest discover -s tests --durations 25`.
scripts/check_fast.py uses the same runner for the tests it selects.
"""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - INTENTIONAL(#520): the one line an older Python gets
    raise SystemExit(f"OpenGuildKit needs Python 3.11 or later; this is Python {sys.version_info[0]}.{sys.version_info[1]}. "
                     "Run it with python3.11 or newer.")

import argparse
import os
import re
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# unittest returns 5 when a file holds no test; discover counts such a file as passed, and so does this runner.
NO_TESTS_RAN = 5


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def test_files(root: Path = ROOT) -> list[str]:
    """The test files discover finds: test*.py in tests/ and in its sub-packages."""
    found = []
    for path in sorted((root / "tests").rglob("test*.py")):
        folders = path.relative_to(root / "tests").parents
        if all((root / "tests" / folder / "__init__.py").is_file() for folder in folders):
            found.append(path.relative_to(root).as_posix())
    return found


def module_name(path: str) -> str:
    return path[:-3].replace("/", ".")


def largest_first(paths: list[str], root: Path = ROOT) -> list[str]:
    """The size of a test file stands for its duration: the long files start first."""
    return sorted(paths, key=lambda path: -(root / path).stat().st_size)


def run(paths: list[str], jobs: int, *, deadline: float | None = None, stop_on_failure: bool = False,
        root: Path = ROOT) -> dict:
    """Run the test files in that order, `jobs` at a time.

    Past `deadline` (a time.monotonic() value), or after a failure with stop_on_failure, nothing more starts and the
    files still running are stopped. Returns passed, failed (path, output), stopped and not_run paths, the number of
    tests run and the seconds taken."""
    started = time.monotonic()
    queue, lock, stop = list(paths), threading.Lock(), threading.Event()
    running: dict[str, subprocess.Popen] = {}
    killed: set[str] = set()
    result = {"passed": [], "failed": [], "stopped": [], "not_run": [], "tests": 0}
    pycache = tempfile.TemporaryDirectory(prefix="ogk-run-tests-pycache-", ignore_cleanup_errors=True)
    environment = {**os.environ, "PYTHONPATH": str(root / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""),
                   "OPENGUILDKIT_TEST_PYCACHE": pycache.name}

    def halt() -> None:
        stop.set()
        for path, process in running.items():
            killed.add(path)
            if os.name == "posix":  # The processes a test started go with it.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()
            else:
                process.kill()

    def worker() -> None:
        while True:
            with lock:
                if stop.is_set() or not queue:
                    return
                path = queue.pop(0)
                process = subprocess.Popen([sys.executable, "-m", "unittest", module_name(path)], cwd=root,
                                           env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace",
                                           start_new_session=os.name == "posix")
                running[path] = process
            output, _ = process.communicate()
            with lock:
                running.pop(path, None)
                ran = re.findall(r"^Ran (\d+) tests? in", output, flags=re.M)
                result["tests"] += int(ran[-1]) if ran else 0
                if process.returncode in (0, NO_TESTS_RAN):
                    result["passed"].append(path)
                elif path in killed:
                    result["stopped"].append(path)
                else:
                    result["failed"].append((path, output))
                    if stop_on_failure:
                        halt()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(jobs, len(paths))))]
    for thread in threads:
        thread.start()
    while any(thread.is_alive() for thread in threads):
        time.sleep(0.05)
        if deadline is not None and time.monotonic() > deadline and not stop.is_set():
            with lock:
                halt()
    pycache.cleanup()
    result["not_run"] = queue
    result["seconds"] = time.monotonic() - started
    return result


def tolerant_stdout() -> None:
    """Print what the console's encoding cannot write as escapes: the output of a file is decoded with errors="replace",
    and the cp1252 of a Windows console has no U+FFFD for the bytes it replaced (#451)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="backslashreplace")


def print_failures(result: dict) -> None:
    for path, output in result["failed"]:
        print(f"===== {path} failed\n{output.rstrip()}\n", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run each test file in its own process, several at once.")
    parser.add_argument("--jobs", type=int, default=default_jobs(), help="processes at once (default: half the processors)")
    parser.add_argument("files", nargs="*", help="test files (default: every file discover finds)")
    args = parser.parse_args(argv)
    tolerant_stdout()
    paths = args.files or largest_first(test_files())
    result = run(paths, args.jobs)
    print_failures(result)
    verdict = f"{len(result['failed'])} failed" if result["failed"] else "all passed"
    print(f"run_tests: {len(paths)} test file(s), {result['tests']} tests, {verdict}, "
          f"{result['seconds']:.1f} s with {args.jobs} job(s).")
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
