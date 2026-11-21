"""Install the agent skill and the subagents (board, market analyst, dependency watch) shipped with this version."""

from pathlib import Path

from .catalog import package_file
from .lock import package_version
from .storage import write_text

HOST_FILES = {
    "claude-code": {
        "skills/openguildkit/SKILL.md": Path(".claude") / "skills" / "openguildkit" / "SKILL.md",
        "agents/guild-board.md": Path(".claude") / "agents" / "guild-board.md",
        "agents/market-analyst.md": Path(".claude") / "agents" / "market-analyst.md",
        "agents/dependency-watch.md": Path(".claude") / "agents" / "dependency-watch.md",
    },
    "codex": {
        "skills/openguildkit/SKILL.md": Path(".agents") / "skills" / "openguildkit" / "SKILL.md",
    },
}
VERSION_FILE = "openguildkit-version.txt"


def packaged_file(name: str) -> str:
    return package_file("agent_files", *name.split("/")).read_text(encoding="utf-8")


def install_agent_files(base: Path, host: str, force: bool = False) -> list[dict]:
    """Copy the packaged files under base (a project or the home folder). Modified files are kept
    unless force is set, in which case the previous version is saved next to them."""
    if host not in HOST_FILES:
        raise ValueError(f"Choose the host from {', '.join(HOST_FILES)}.")
    report = []
    kept: dict[Path, list[str]] = {path.parent: [] for path in HOST_FILES[host].values()}
    for name, relative in HOST_FILES[host].items():
        target = base / relative
        content = packaged_file(name)
        if target.is_symlink():
            raise ValueError(f"Refusing to replace a symbolic link: {target}")
        if not target.exists():
            write_text(target, content)
            report.append({"file": str(relative), "action": "installed"})
            continue
        current = target.read_text(encoding="utf-8-sig")
        if current == content:
            report.append({"file": str(relative), "action": "unchanged"})
        elif force:
            write_text(target.with_name(target.name + ".previous"), current)
            write_text(target, content)
            report.append({"file": str(relative), "action": "replaced, previous version saved"})
        else:
            report.append({"file": str(relative), "action": "kept: differs from this version, use --force to replace"})
            kept[relative.parent].append(relative.name)
    for folder, names in kept.items():
        write_text(base / folder / VERSION_FILE, _version_note(names))
    return report


def _version_note(kept: list[str]) -> str:
    """The installed version, or which kept files are not at this version, so the file never overstates it."""
    if not kept:
        return package_version() + "\n"
    return f"{', '.join(kept)} kept: differs from openguildkit {package_version()}, use --force to replace\n"
