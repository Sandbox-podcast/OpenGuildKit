"""The one argument of every task action that acts on a task: the command line, the project and the task record.

Entry: TaskCommand
Tests: tests/test_approval_lifecycle.py, tests/test_next_steps.py
"""

from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskCommand:
    """One task action to run: the parsed arguments, the project root and its state folder, the profile and the
    catalog in force, and the record of the task it acts on."""

    args: Namespace
    root: Path
    state: Path
    profile: dict
    catalog: dict
    task: dict
