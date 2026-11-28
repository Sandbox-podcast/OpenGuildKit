"""Shared CLI capture, isolated subprocess caches and small project fixtures."""

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from tests import GIT_ENVIRONMENT

# scripts/run_tests.py runs each test file in its own process and gives them one bytecode folder to share, so the
# children of every file do not compile the package again (#451).
_SHARED_PYCACHE = os.environ.get("OPENGUILDKIT_TEST_PYCACHE")
_PYCACHE = None if _SHARED_PYCACHE else tempfile.TemporaryDirectory(prefix="ogk-test-pycache-")


def subprocess_environment(overrides=None):
    """This process's environment for a child, with Git isolated from the machine's configuration."""
    environment = {**os.environ, **GIT_ENVIRONMENT}
    if overrides:
        environment.update(overrides)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment["PYTHONPYCACHEPREFIX"] = _SHARED_PYCACHE or _PYCACHE.name
    return environment


def run_cli(project, *arguments, expect=0, stdin=None, typed=None, subprocess_mode=False, env=None):
    """Return an isolated CLI result. Use a real process for tests of host behaviour."""
    argv = ["--project", str(project), *map(str, arguments)]
    if subprocess_mode:
        result = subprocess.run(
            [sys.executable, "-m", "openguildkit", *argv], capture_output=True, text=True,
            encoding="utf-8", input=stdin if stdin is not None else "", env=subprocess_environment(env), timeout=120,
        )
    else:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            if env:
                stack.enter_context(patch.dict(os.environ, {key: str(value) for key, value in env.items()}))
            if stdin is not None:
                stack.enter_context(patch("sys.stdin", io.StringIO(stdin)))
            if typed is not None:
                stack.enter_context(patch("sys.stdin.isatty", return_value=True))
                stack.enter_context(patch("builtins.input", return_value=typed))
            try:
                code = main(argv)
            except SystemExit as exit_:
                code = exit_.code
        result = subprocess.CompletedProcess(argv, code, stdout.getvalue(), stderr.getvalue())
    if expect is not None and result.returncode != expect:
        command = " ".join(map(str, arguments))
        raise AssertionError(
            f"openguildkit {command}: expected exit {expect}, got {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


class CapturedCli:
    """CLI unittest helper for a project stored on self.root."""

    cli_output = "both"

    def run_cli(self, *arguments, code=0, stdin=None, typed=None):
        result = run_cli(self.root, *arguments, expect=code, stdin=stdin, typed=typed)
        if self.cli_output == "stdout":
            return result.stdout
        if self.cli_output == "status-stream":
            return result.stdout if code == 0 else result.stderr
        if self.cli_output == "combined-on-error":
            return result.stdout + result.stderr if code else result.stdout
        return result.stdout, result.stderr

    cli = run_cli


def registry_days_on_the_real_clock(test) -> None:
    """Check the days the bundled tool registry was read (verified, pin_read) on the real clock while the test stops
    the clock at the day of an upgrade fixture: a registry read after that day is not in the future (#489)."""
    from openguildkit import clock, tool_registry

    real_now, validate_day = clock.real_now, tool_registry.validate_day

    def validate_on_the_real_clock(value, label):
        with patch("openguildkit.clock.real_now", real_now):
            validate_day(value, label)

    registry = patch("openguildkit.tool_registry.validate_day", validate_on_the_real_clock)
    registry.start()
    test.addCleanup(registry.stop)


def openguildkit_on_path(test) -> Path:
    """Put an openguildkit launcher on the PATH for the test, as pipx or uv would: host apply and check fail while
    the hooks cannot find the command, and a source checkout does not install it. Returns the launchers' folder."""
    temporary = tempfile.TemporaryDirectory(prefix="ogk-test-bin-")
    test.addCleanup(temporary.cleanup)
    launchers = Path(temporary.name)
    posix = launchers / "openguildkit"
    posix.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m openguildkit "$@"\n', encoding="utf-8")
    posix.chmod(0o755)
    (launchers / "openguildkit.cmd").write_text(f'@"{sys.executable}" -m openguildkit %*\r\n', encoding="utf-8")
    on_path = patch.dict(os.environ, {"PATH": f"{launchers}{os.pathsep}{os.environ.get('PATH', '')}"})
    on_path.start()
    test.addCleanup(on_path.stop)
    return launchers


def copy_initialized_project(test, profile: Path, destination: Path) -> None:
    """Initialize once per test class, then give each test its own writable copy."""
    cls = type(test)
    if "_initialized_project" not in cls.__dict__:
        template = tempfile.TemporaryDirectory(prefix="ogk-test-project-")
        cls.addClassCleanup(template.cleanup)
        cls.addClassCleanup(delattr, cls, "_initialized_project")
        cls._initialized_project = Path(template.name)
        run_cli(cls._initialized_project, "init", "--answers", profile)
    shutil.copytree(cls._initialized_project, destination, dirs_exist_ok=True)


def load_script(path: Path):
    """Import a script of scripts/ (or a copy of one) as a module, without running its main()."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
