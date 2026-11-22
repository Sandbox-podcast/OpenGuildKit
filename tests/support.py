"""Shared CLI capture, isolated subprocess caches and small project fixtures."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main

_PYCACHE = tempfile.TemporaryDirectory(prefix="ogk-test-pycache-")


def subprocess_environment(overrides=None):
    environment = dict(os.environ)
    if overrides:
        environment.update(overrides)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment["PYTHONPYCACHEPREFIX"] = _PYCACHE.name
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
