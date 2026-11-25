"""The short lane: a shorter way through the workflow for a change a person declares trivial.

A profile that names `light_paths` (folder or file globs such as `docs/**` and `tests/**`) lets a task be opened with
`task new ID --lane light --paths GLOB...`. The lane drops what has no meaning for one reviewing board: the
questionnaire, whose answers are fixed and careful, and the deliberation between boards. It keeps the passes, the
blockers, the person's sealed decision, the handoff, the checks, the results, the closing and the export.

Everything here is a pure function of paths and records, so that every reader asks the same questions: which paths are
never in the lane, and what a path in the profile or in a task may be. A glob matches whole project paths: `*` and `?`
stay inside a folder, `**` is a whole segment that crosses folders.
"""

import re

MAX_PATHS = 50

# What the lane never covers, whatever the profile says: a change of rules, dependencies or the profile is judged by
# the full path. Folders: the item itself or anything under it; the case of a name is ignored.
_STATE_FOLDER = ".openguildkit"
_FOLDERS = ((_STATE_FOLDER, "the profile, the catalog and the decisions of the project"),
            (".github/workflows", "a CI workflow"), (".github/actions", "a CI action"))
# The instruction files and settings of agents, as `host scan` reads them (surfaces.INSTRUCTION_PATHS and CONFIG_PATHS,
# whole folders where it reads a folder): a test keeps both lists in step.
_AGENT_FOLDERS = (".claude", ".codex", ".cursor", ".cursorrules", ".windsurf", ".windsurfrules", ".clinerules", ".roo",
                  ".kilocode", ".junie", ".rules", ".gemini", ".vscode/mcp.json", ".mcp.json",
                  ".github/copilot-instructions.md", ".github/instructions")
_INSTRUCTION_NAMES = frozenset({"agents.md", "claude.md", "gemini.md", "warp.md"})
_MANIFEST_NAMES = frozenset({
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "pnpm-workspace.yaml",
    "bun.lock", "bun.lockb", ".npmrc", ".yarnrc", ".yarnrc.yml", "pyproject.toml", "setup.py", "setup.cfg", "pipfile",
    "pipfile.lock", "poetry.lock", "uv.lock", "pdm.lock", "go.mod", "go.sum", "go.work", "go.work.sum", "cargo.toml",
    "cargo.lock", "composer.json", "composer.lock", "gemfile", "gemfile.lock", "pom.xml", "build.gradle",
    "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.lockfile", "libs.versions.toml",
    "packages.config", "directory.packages.props", "directory.build.props", "package.swift", "package.resolved",
    "mix.exs", "mix.lock", "pubspec.yaml", "pubspec.lock", "deno.json", "deno.jsonc", "deno.lock", "environment.yml",
    "conda-lock.yml", "flake.lock",
})
_MANIFEST_SUFFIXES = (".lock", ".lockb", ".csproj", ".fsproj", ".vbproj", ".gemspec", "-lock.json", "-lock.yaml",
                      "-lock.yml")
_MANIFEST_TEXT = re.compile(r"(?:requirements|constraints)[\w.-]*\.txt")
NEVER = "rules, dependencies, the profile and the instructions of agents"


class ExcludedPath(ValueError):
    """A path the lane never covers, named with what it is."""


def _inside(folded: str, folder: str) -> bool:
    return folded == folder or folded.startswith(f"{folder}/")


def excluded_reason(path: str) -> str | None:
    """What a project file is when the lane never covers it (rules, dependencies, the profile, an agent's
    instructions), or None. The case of the name is ignored: the same file on a case-insensitive disk."""
    folded = path.casefold()
    for folder, reason in _FOLDERS:
        if _inside(folded, folder):
            return reason
    if any(_inside(folded, folder) for folder in _AGENT_FOLDERS):
        return "the instructions or settings of an agent"
    name = folded.rsplit("/", 1)[-1]
    if name in _INSTRUCTION_NAMES:
        return "an instruction file of agents"
    if name in _MANIFEST_NAMES or name.endswith(_MANIFEST_SUFFIXES) or _MANIFEST_TEXT.fullmatch(name):
        return "a dependency manifest or lockfile"
    return None


def _wild(segment: str) -> bool:
    return "*" in segment or "?" in segment


def declared_excluded(entry: str) -> str | None:
    """What a declared path (a glob) names of what the lane never covers: a file, a folder it starts in, a folder it
    reaches into from above (`.github/**`), or a file name it ends with. A wildcard that only could match such a file
    is let through: the file stays outside the lane at every check (covers)."""
    segments = entry.split("/")
    literal = []
    for segment in segments:
        if _wild(segment):
            break
        literal.append(segment)
    if len(literal) == len(segments):
        return excluded_reason(entry)
    prefix = "/".join(literal).casefold()
    if prefix:
        if reason := excluded_reason(f"{prefix}/x"):
            return reason
        for folder, reason in (*_FOLDERS, *((folder, "the instructions or settings of an agent")
                                            for folder in _AGENT_FOLDERS)):
            if folder.startswith(f"{prefix}/"):
                return reason
    return excluded_reason(f"x/{segments[-1]}") if not _wild(segments[-1]) else None


def normalize_entry(entry: object) -> str:
    """A path or glob as the lane keeps it: inside the project, with `*`, `?` and `**` as the only wildcards, and not
    the whole project. A trailing slash names a folder."""
    if not isinstance(entry, str) or not entry.strip():
        raise ValueError(f"{entry!r} is not a path: write a folder or file glob such as docs/** or README.md.")
    text = entry.strip()
    if text.endswith("/"):
        text += "**"
    segments = text.split("/")
    problem = None
    if "\\" in text or any(ord(character) < 32 for character in text) or len(text) > 255:
        problem = "write it with / and at most 255 characters"
    elif text.startswith("/") or any(segment in ("", ".", "..") for segment in segments):
        problem = "write a path inside the project, without ./, .. or a leading /"
    elif any(character in text for character in "[]{}!"):
        problem = "the wildcards are * and ? within a folder, and ** as a whole segment"
    elif any("**" in segment and segment != "**" for segment in segments):
        problem = "** is a whole segment, as in docs/**"
    elif segments[0] == "**":
        problem = "that is the whole project: start from a folder or a file name, as in docs/**"
    if problem:
        raise ValueError(f"{entry!r} is not a path of the short lane: {problem}.")
    return text


def normalize_entries(values: object, label: str) -> list[str]:
    """The paths of light_paths or of a task, each normalized, without repeats, in one order: a list that never
    covers rules, dependencies, the profile or agent instructions (ExcludedPath names the first that does)."""
    if not isinstance(values, list) or not values:
        raise ValueError(f"{label} needs a list of at least one path, such as docs/**.")
    entries = sorted({normalize_entry(item) for item in values})
    if len(entries) > MAX_PATHS:
        raise ValueError(f"{label} lists {len(entries)} paths: at most {MAX_PATHS}; use folders such as docs/**.")
    for entry in entries:
        reason = declared_excluded(entry)
        if reason:
            raise ExcludedPath(f"{label}: {entry} reaches {reason}. The short lane never covers {NEVER} (docs/workflow.md, "
                               '"Short lane").')
    return entries
