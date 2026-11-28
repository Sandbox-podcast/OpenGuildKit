"""What `__main__` reads before importing the rest of the package: the version, and the guard mode a profile declares.

Both need only the standard library and storage, so that `openguildkit --version`, and the edit hook of a project whose guard
is off, answer without importing the CLI or the guard (#539).

Entry: package_version, declared_mode, guard_declared_off
Tests: tests/test_guard.py
"""

import os
import sys
from pathlib import Path

STATE_DIR = ".openguildkit"  # project.STATE_DIR, which imports far more (tests/test_performance.py compares them)
MODES = ("off", "observe", "enforce")
# The mode when the profile cannot be read: the hook refuses edits, as in enforce, and says why.
UNKNOWN_MODE = "unknown"


def _metadata_header(folder: Path, name: str) -> str | None:
    """The header of the metadata file of a dist-info or egg-info entry named for openguildkit, as importlib.metadata
    finds them: METADATA, or PKG-INFO in a folder or in the .egg-info file itself."""
    lowered = name.lower()
    files: tuple[str, ...] = ("METADATA",)
    if lowered.endswith(".egg-info"):
        files = ("PKG-INFO", "")
    elif not lowered.endswith(".dist-info"):
        return None
    if lowered.rpartition(".")[0].partition("-")[0] != "openguildkit":
        return None
    for file in files:
        try:
            return (folder / name / file).read_text(encoding="utf-8").partition("\n\n")[0]
        except OSError:
            continue
    return None


def package_version() -> str:
    """The installed version, or the version of the source checkout the CLI runs from.

    The dist-info and egg-info entries on the import path are read first, in the order importlib.metadata reads them:
    importing that module and its search cost more than the interpreter's start (#539), so it only serves a package
    installed otherwise. A checkout that is not installed answers the version of its pyproject.toml with +source."""
    for entry in sys.path:
        folder = Path(entry or ".")
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            header = _metadata_header(folder, name)
            for line in (header or "").splitlines():
                if line.startswith("Version:"):
                    return line.partition(":")[2].strip()
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if pyproject.is_file():
        try:
            import tomllib

            return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"] + "+source"
        except (OSError, KeyError, ValueError):
            pass
    from importlib import metadata

    try:
        return metadata.version("openguildkit")
    except metadata.PackageNotFoundError:
        return "unknown"


def profile_state(project: Path | None) -> Path | None:
    """The state folder of the project the hook runs in: project's, or else the closest one from the working folder
    up; None when there is none."""
    start = project.resolve() if project is not None else Path.cwd().resolve()
    roots = [start] if project is not None else [start, *start.parents]
    return next((root / STATE_DIR for root in roots if (root / STATE_DIR).is_dir()), None)


def declared_mode(project: Path | None) -> str:
    """The guard mode written in the profile, read without validation; off without a profile, unknown when it
    cannot be read."""
    from .storage import read_json  # Not for --version.

    try:
        state = profile_state(project)
        if state is None:
            return "off"
        mode = read_json(state / "project.json").get("guard", "off")
    except Exception:
        return UNKNOWN_MODE
    return mode if mode in MODES else UNKNOWN_MODE


def guard_declared_off(project: Path | None) -> bool:
    """True when the hook runs in a project whose profile declares the guard off: the hook lets every edit through
    and says nothing, whatever the rest of the profile, the catalog or the workstation policy say."""
    try:
        return profile_state(project) is not None and declared_mode(project) == "off"
    except OSError:
        return False
