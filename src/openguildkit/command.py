"""What every command module's run receives: the parsed arguments, and the project's root, state, catalog and profile
read on first use.

Entry: Command.
Tests: tests/test_architecture.py.
"""

from argparse import Namespace
from functools import cached_property
from pathlib import Path

from .lock import project_catalog
from .project import load_profile, project_root, state_path

# What a command reads before it runs, each step after the ones before it (Command.read).
NEEDS = ("args", "root", "catalog", "profile")


class Command:
    """One run of a command: args, then root, state, catalog and profile, each read once, when first used."""

    def __init__(self, args: Namespace):
        self.args = args

    @cached_property
    def root(self) -> Path:
        return project_root(self.args.project)

    @cached_property
    def state(self) -> Path:
        return state_path(self.root)

    @cached_property
    def catalog(self) -> dict:
        return project_catalog(self.args, self.state)

    @cached_property
    def profile(self) -> dict:
        return load_profile(self.state, self.catalog)

    def read(self, needs: str) -> None:
        """Read now what the command needs (one of NEEDS), in the order the CLI has always read it, so that a project
        that cannot be read stops each command where it stopped before, whatever the command reads afterwards."""
        readers = {"root": lambda: self.state, "catalog": lambda: self.catalog, "profile": lambda: self.profile}
        for step in NEEDS[1:NEEDS.index(needs) + 1]:
            readers[step]()
