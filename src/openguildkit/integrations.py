"""Install the agent skill and the board subagent shipped with this version of OpenGuildKit."""

from importlib.resources import files
from pathlib import Path

from .lock import package_version
from .storage import write_text

HOST_FILES = {
    "claude-code": {
        "skills/openguildkit/SKILL.md": Path(".claude") / "skills" / "openguildkit" / "SKILL.md",
        "agents/guild-board.md": Path(".claude") / "agents" / "guild-board.md",
    },
    "codex": {
        "skills/openguildkit/SKILL.md": Path(".agents") / "skills" / "openguildkit" / "SKILL.md",
    },
}
VERSION_FILE = "openguildkit-version.txt"


def packaged_file(name: str) -> str:
    return files("openguildkit").joinpath("agent_files", *name.split("/")).read_text(encoding="utf-8")


def install_agent_files(base: Path, host: str, force: bool = False) -> list[dict]:
    """Copy the packaged files under base (a project or the home folder). Modified files are kept
    unless force is set, in which case the previous version is saved next to them."""
    if host not in HOST_FILES:
        raise ValueError(f"Choose the host from {', '.join(HOST_FILES)}.")
    report = []
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
        write_text(target.parent / VERSION_FILE, package_version() + "\n")
    for relative in {path.parent for path in HOST_FILES[host].values()}:
        write_text(base / relative / VERSION_FILE, package_version() + "\n")
    return report
