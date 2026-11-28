"""Install the agent skill and the subagents (board, market analyst, dependency watch) shipped with this version.

Entry: packaged_file, install_agent_files
Tests: tests/test_gemini_host.py
"""

from pathlib import Path

from .catalog import package_file
from .lock import package_version
from .storage import write_text

SKILL = "skills/openguildkit"
# SKILL.md and the reference files it says when to read: the skill is the whole folder.
SKILL_FILES = (
    f"{SKILL}/SKILL.md",
    *(f"{SKILL}/references/{name}.md" for name in (
        "closing-a-task", "deliberation", "dependency-alerts", "market-dossiers", "setup", "storybook",
        "tools-and-mcp")),
)


def _skill_files(folder: str) -> dict[str, Path]:
    return {name: Path(folder) / name for name in SKILL_FILES}


HOST_FILES = {
    "claude-code": {
        **_skill_files(".claude"),
        "agents/guild-board.md": Path(".claude") / "agents" / "guild-board.md",
        "agents/market-analyst.md": Path(".claude") / "agents" / "market-analyst.md",
        "agents/dependency-watch.md": Path(".claude") / "agents" / "dependency-watch.md",
    },
    "codex": _skill_files(".agents"),
    # Gemini CLI reads the workspace skills of .gemini/skills/ and of its alias .agents/skills/.
    "gemini-cli": _skill_files(".agents"),
    # Other agents: the folder of the Agent Skills format, which Codex and other agents read.
    "other": _skill_files(".agents"),
}
OTHER_HOST_NOTE = (
    "Other agents: the skill is in .agents/skills/openguildkit/, the folder of the Agent Skills format. "
    "If your agent reads its skills or instructions from another folder, copy the whole folder there, "
    "references/ included; AGENTS.md already carries the same workflow."
)
VERSION_FILE = "openguildkit-version.txt"


def packaged_file(name: str) -> str:
    return package_file("agent_files", *name.split("/")).read_text(encoding="utf-8")


def install_agent_files(base: Path, host: str, force: bool = False) -> list[dict]:
    """Copy the packaged files under base (a project or the home folder). Modified files are kept
    unless force is set, in which case the previous version is saved next to them."""
    if host not in HOST_FILES:
        raise ValueError(f"Choose the host from {', '.join(HOST_FILES)}.")
    report = []
    # One version note per folder of files, next to SKILL.md for the skill: not one in references/.
    kept: dict[Path, list[str]] = {_version_folder(path): [] for path in HOST_FILES[host].values()}
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
            kept[_version_folder(relative)].append(relative.relative_to(_version_folder(relative)).as_posix())
    for folder, names in kept.items():
        write_text(base / folder / VERSION_FILE, _version_note(names))
    return report


def _version_folder(relative: Path) -> Path:
    """The folder that holds the version note of a file: a reference file shares the note of its skill."""
    return relative.parent.parent if relative.parent.name == "references" else relative.parent


def _version_note(kept: list[str]) -> str:
    """The installed version, or which kept files are not at this version, so the file never overstates it."""
    if not kept:
        return package_version() + "\n"
    return f"{', '.join(kept)} kept: differs from openguildkit {package_version()}, use --force to replace\n"
