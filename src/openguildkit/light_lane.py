"""The short lane: a shorter way through the workflow for a change a person declares trivial.

A profile that names `light_paths` (folder or file globs such as `docs/**` and `tests/**`) lets a task be opened with
`task new ID --lane light --paths GLOB...`. The lane drops what has no meaning for one reviewing board: the
questionnaire, whose answers are fixed and careful, and the deliberation between boards. It keeps the passes, the
blockers, the person's sealed decision, the handoff, the checks, the results, the closing and the export.

Everything here is a pure function of paths and records, so that every reader asks the same questions: which paths
are never in the lane, what a path in the profile or in a task may be, and which board a set of paths calls for. A glob
matches whole project paths: `*` and `?` stay inside a folder, `**` is a whole segment that crosses folders.
"""

import re

from .doc_links import doc_link
from .wording import plural

LANE = "light"
MAX_PATHS = 50
DOCS_BOARD, TESTS_BOARD, DEFAULT_BOARD = "developer-relations-and-docs", "qa", "engineering"
FULL_PATH = 'openguildkit task new "BRIEF" --id ID'
DEFAULT_PATHS = ("docs/**", "tests/**")

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
            raise ExcludedPath(f"{label}: {entry} reaches {reason}. The short lane never covers {NEVER} "
                               f"({doc_link('docs/workflow.md', 'short-lane')}).")
    return entries


def _segment(pattern: str, name: str) -> bool:
    """Whether one name matches a pattern of * and ?, by the two-pointer walk that never backtracks twice."""
    p = n = mark = 0
    star = -1
    while n < len(name):
        if p < len(pattern) and pattern[p] == "*":
            star, mark, p = p, n, p + 1
        elif p < len(pattern) and (pattern[p] == "?" or pattern[p] == name[n]):
            p, n = p + 1, n + 1
        elif star >= 0:
            mark += 1
            p, n = star + 1, mark
        else:
            return False
    return pattern[p:].strip("*") == ""


def matches(pattern: str, path: str) -> bool:
    """Whether a glob matches a whole project path. A final ** needs at least one more segment."""
    rules, parts = pattern.split("/"), path.split("/")
    last = len(rules) - 1
    states = {0}
    for part in parts:
        reached = set()
        for index in (state for state in states if state < len(rules)):
            # A ** before the last segment may match no folder at all: try the rules after it too.
            followers = [index]
            while followers[-1] < last and rules[followers[-1]] == "**":
                followers.append(followers[-1] + 1)
            for follower in followers:
                if rules[follower] == "**":
                    reached.update({follower, follower + 1} if follower == last else {follower})
                elif _segment(rules[follower], part):
                    reached.add(follower + 1)
        states = reached
        if not states:
            return False
    return len(rules) in states


def covers(path: str, task_paths: list[str], light_paths: list[str]) -> bool:
    """Whether the lane covers an edit to this file: the task names it, the profile still allows it, and it is not
    rules, dependencies, the profile or agent instructions, which no glob brings in. The case of a folder is kept: on a
    disk that ignores case, an edit to Docs/ is outside docs/**, which errs on the side of the full path."""
    return (excluded_reason(path) is None and any(matches(item, path) for item in task_paths)
            and any(matches(item, path) for item in light_paths))


def files_outside(task_paths: list[str], light_paths: list[str], files: list[str]) -> list[str]:
    """The changed files the lane does not cover."""
    return [name for name in files if not covers(name, task_paths, light_paths)]


def outside_message(task_id: str, task_paths: list[str], light_paths: list[str], outside: list[str], where: str) -> str:
    """The changed files of a short-lane task that are outside its paths, in one sentence; where says whose light_paths
    the paths are held to."""
    shown = ", ".join(outside[:10]) + (f" and {len(outside) - 10} more" if len(outside) > 10 else "")
    return (f"Short-lane task {task_id} covers only {', '.join(task_paths)}, within the light_paths of {where} "
            f"({', '.join(light_paths)}), and {plural(len(outside), 'changed file')} {'is' if len(outside) == 1 else 'are'} outside: {shown}. "
            f"Rules, dependencies, "
            f"the profile and agent instructions are never in the lane. Move the work to the full path: openguildkit "
            f'task new "BRIEF" --follows {task_id}.')


def covered_summary(approvals: list[dict]) -> str:
    """The short-lane tasks among the covering approvals, each with its paths, as the guard's messages name them."""
    return "; ".join(f"{item['task']} ({', '.join(item['paths'])})" for item in approvals if item.get("lane"))


def off_message(task_id: str, where: str) -> str:
    """A short-lane record judged by a revision that has no light_paths: the lane is off there."""
    return (f"Short-lane task {task_id} is judged by {where}, which has no light_paths: the lane is off there, and a change "
            "cannot turn on the lane it is judged by. A person turns it on in a change that is merged first "
            f"({activation_command(DEFAULT_PATHS)}), or the work takes the full path ({FULL_PATH}).")


def declared_covered(entry: str, light_paths: list[str]) -> bool:
    """Whether every file a declared path can match is one the profile's light_paths allow: the same glob, a folder
    glob of the profile whose folder the path starts with, or a path with no wildcard that a glob matches."""
    for light in light_paths:
        if entry == light or (light.endswith("/**") and entry.startswith(light[:-2])):
            return True
        if not _wild(entry) and matches(light, entry):
            return True
    return False


def outside_light_paths(entries: list[str], light_paths: list[str]) -> list[str]:
    return [entry for entry in entries if not declared_covered(entry, light_paths)]


_TEST_FOLDERS = frozenset({"test", "tests", "spec", "specs", "__tests__", "e2e"})
_DOC_FOLDERS = frozenset({"docs", "doc", "documentation"})
_TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*.spec.*", "*_spec.*")
_DOC_SUFFIXES = (".md", ".mdx", ".rst", ".adoc")


def _kind(entry: str) -> str:
    folders = [segment.casefold() for segment in entry.split("/")[:-1]]
    name = entry.split("/")[-1].casefold()
    if _TEST_FOLDERS & set(folders):
        return "tests"
    if _DOC_FOLDERS & set(folders):
        return "docs"
    if any(_segment(pattern, name) for pattern in _TEST_NAMES):
        return "tests"
    return "docs" if name.endswith(_DOC_SUFFIXES) else "code"


def board_for(paths: list[str]) -> tuple[str, str]:
    """The one board the paths call for, and why: documentation, tests, otherwise engineering."""
    kinds = {_kind(entry) for entry in paths}
    listed = ", ".join(paths)
    if kinds == {"docs"}:
        return DOCS_BOARD, f"Short lane: the paths {listed} hold documentation"
    if kinds == {"tests"}:
        return TESTS_BOARD, f"Short lane: the paths {listed} hold tests"
    return DEFAULT_BOARD, f"Short lane: the paths {listed} hold code or a mix, so engineering reviews them"


def activation_command(paths: list[str] | tuple[str, ...]) -> str:
    from .shell import shell_command

    return shell_command(["openguildkit", "profile", "set", "light-paths", *paths, "--by", "INITIALS", "--reason", "WHY"])


def _usable(paths: list[str] | None) -> list[str]:
    """The paths a person could be asked to turn on: those the task asked for when the lane can cover them."""
    try:
        return normalize_entries(list(paths or []), "paths")
    except ValueError:
        return list(DEFAULT_PATHS)


def declare(lane: str | None, paths: list[str] | None, profile: dict) -> dict:
    """The lane fields of a new task: {} for the full path, {"lane": "light", "paths": [...]} for the short lane.

    Refuses a lane the profile has not turned on (with the command a person types), a path the lane never covers, and
    a path the profile's light_paths do not cover (with the command of the full path)."""
    if lane is None:
        if paths:
            raise ValueError("--paths belongs to the short lane: add --lane light, or leave --paths out for the full path.")
        return {}
    light = profile.get("light_paths") or []
    if not light:
        raise ValueError(
            "the short lane is off in this project: its profile names no paths it may cover (light_paths). A person "
            f"turns it on at their terminal: {activation_command(_usable(paths))}; a task opened without --lane takes the "
            "full path.")
    if not paths:
        raise ValueError(f"Name the paths a short-lane task may change: --paths GLOB..., inside {', '.join(light)}.")
    try:
        entries = normalize_entries(list(paths), "--paths")
    except ExcludedPath as error:
        raise ValueError(f"{error} Open the task on the full path: {FULL_PATH}.") from None
    outside = outside_light_paths(entries, light)
    if outside:
        raise ValueError(
            f"the short lane of this project covers only {', '.join(light)}; these paths are outside it: "
            f"{', '.join(outside)}. Open the task on the full path ({FULL_PATH}, without --lane), or have a person "
            f"widen the lane at their terminal: {activation_command(sorted({*light, *outside}))}.")
    return {"lane": LANE, "paths": entries}


def is_light(task: dict) -> bool:
    return task.get("lane") == LANE


def lane_problem(task: dict, profile: dict) -> str | None:
    """Why a short-lane task no longer fits the profile (the lane was turned off or narrowed after the task was
    opened), or None. A task of the full path has none."""
    if not is_light(task):
        return None
    light = profile.get("light_paths") or []
    if not light:
        return (f"Task {task['id']} is in the short lane, and the profile no longer names light_paths: the lane is off. A "
                f"person turns it on again at their terminal ({activation_command(task['paths'])}), or the work moves to "
                f'the full path: openguildkit task new "BRIEF" --follows {task["id"]}.')
    outside = outside_light_paths(task["paths"], light)
    if outside:
        return (f"Task {task['id']} is in the short lane for {', '.join(task['paths'])}, and the profile's light_paths "
                f"({', '.join(light)}) no longer cover {', '.join(outside)}. A person widens the lane at their terminal "
                f"({activation_command(sorted({*light, *outside}))}), or the work moves to the full path: openguildkit "
                f'task new "BRIEF" --follows {task["id"]}.')
    return None


DEFAULTS = "maintenance work, no sensitive data, local research, no particular topic"


def default_answers(task: dict) -> dict:
    """The answers of a short-lane task, in place of the questionnaire: the careful ones. Maintenance work, no
    sensitive data, local research and no particular topic leave the rules of every other surface open (surface other
    is an open answer), so the lane asks the closing no less than a person's unsure would."""
    return {"kind": "maintenance", "surface": ["other"], "data": "none", "research": "local", "concerns": ["none"],
            "context": f"Short lane: these answers are the lane's defaults, not the requester's ({DEFAULTS}). The task "
                       f"may change only {', '.join(task['paths'])}."}


def proposed_routing(task: dict, profile: dict, catalog: dict) -> dict | None:
    """The routing of a short-lane task, one board by its paths (routing.select_boards then adds the project's
    required boards); None for the full path. A board the project has not enabled is named, never replaced."""
    if not is_light(task):
        return None
    board, reason = board_for(task["paths"])
    if board not in set(profile.get("boards") or catalog["boards"]):
        raise ValueError(
            f"The short lane calls for the {board} board for {', '.join(task['paths'])}, and this project has not "
            f"enabled it: a person adds it at their terminal (openguildkit profile add board {board} --by INITIALS "
            f"--reason WHY), or the work takes the full path ({FULL_PATH}).")
    return {board: [reason]}


def options_message(task_id: str, used: list[str]) -> str:
    return (f"The short lane asks no questions and convenes one board: {', '.join(used)} does not apply to task {task_id}. "
            f"For your own answers or another board, open the task on the full path ({FULL_PATH}); to consult this one "
            f"again, run openguildkit task consult {task_id}.")


def no_questions_message(task_id: str) -> str:
    return (f"The short lane asks no questions: its answers are fixed ({DEFAULTS}). Next: openguildkit task consult "
            f"{task_id}.")


def no_route_message(task_id: str) -> str:
    return (f"The short lane picks its board from the paths, so there is no route to preview. Next: openguildkit task "
            f"consult {task_id} convenes it and prints the request.")


def decision_lines(task: dict) -> list[str]:
    """What the person reads before approving a short-lane task: the lane and its paths come with the approval."""
    if not is_light(task):
        return []
    boards = ", ".join(task["consultation"]["boards"])
    return [f"Short lane, covering only {', '.join(task['paths'])}: {boards} reviewed it without the requester's answers "
            f"(the lane's defaults: {DEFAULTS}) and without deliberation between boards. The guard, task complete and "
            f"guard --ci refuse a change outside these paths, and rules, dependencies, the profile and agent "
            f"instructions are never in the lane. Approving also approves the lane and these paths."]


def handoff_note(task: dict) -> str:
    if not is_light(task):
        return ""
    return (f" Short lane: change only {', '.join(task['paths'])}; the guard, task complete and guard --ci refuse "
            "anything else, and rules, dependencies, the profile and agent instructions are never in the lane.")


def scope_line(lane: dict) -> str:
    return (f"- Short lane: {', '.join(lane['paths'])}. One board reviews it, its answers are the lane's defaults, "
            "there is no deliberation, and the edit hook, task complete and guard --ci hold the task to these paths.")


def next_line(task_id: str, paths: list[str]) -> str:
    return (f"Short lane for {', '.join(paths)}: no questions. Next: openguildkit task consult {task_id} convenes the one "
            f"board its paths call for; run its pass (task pass {task_id} BOARD), submit the entry, record the review "
            f"(task review {task_id} --summary TEXT), and the person decides, as on the full path "
            f"({doc_link('docs/workflow.md', 'short-lane')}).")
