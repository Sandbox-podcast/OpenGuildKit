"""The tools of a company's stack and the MCP servers that connect an agent to them.

The registry (registry/tools/, one file per category) names each tool, the review boards
that use it and the MCP servers verified on the publisher's own documentation. From it the
CLI proposes the servers that match a project's tools, writes the host configuration the
person accepted, and can replace every server with a local mock for demos and tests.

Credentials never enter a file: a server names the environment variables it reads, and the
host passes them through.
"""

import copy
import json
import os
import re
import tomllib
from pathlib import Path

from . import clock
from .catalog import CatalogError, package_file, unique_fields
from .detect import MAX_MANIFEST_BYTES, SKIPPED_DIRECTORIES
from .mcp_mock import apply_scenario, check_synthetic, validate_mock
from .sensitive import looks_like_credential
from .storage import read_json, write_json, write_text

CATEGORIES = (
    "issue-tracking", "source-control", "ci-cd", "documentation", "design", "communication", "time-tracking", "hr",
    "finance", "crm", "marketing", "support", "security", "quality", "observability", "cloud", "data", "browser",
    "testing", "analytics", "automation", "product", "identity", "ide", "registries", "containers", "api-management",
)
TRANSPORTS = ("streamable-http", "sse", "stdio")
PUBLISHERS = ("vendor", "community")
AUTH = ("oauth", "api-token", "oauth-or-token", "none")
STATUSES = ("ga", "beta", "preview", "experimental", "deprecated", "unknown")
PACKAGE_REGISTRIES = ("npm", "pypi", "docker", "github-release", "cargo", "homebrew", "other")
API_KINDS = ("rest", "graphql", "other")
HOSTS = ("claude-code", "codex")
MANIFEST = "tools.json"
SCENARIO = "scenario.json"
UNCONNECTED = "unconnected"
NOT_DOCUMENTED = "not documented by the publisher"
NOT_RECORDED = "not recorded in the registry yet"
CLAUDE_MCP_FILE = ".mcp.json"
CODEX_CONFIG_FILE = Path(".codex") / "config.toml"
CODEX_BLOCK_START = "# >>> OpenGuildKit tools (openguildkit tools apply rewrites this block)\n"
CODEX_BLOCK_END = "# <<< OpenGuildKit tools\n"

_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ENV = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
_SETTING = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_SECRET_WORD = re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|apikey|bearer)")
_INLINE_VALUE = re.compile(r"^-{0,2}[A-Za-z0-9_.-]*=(.+)$")
_SETTING_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}")
TOOL_FIELDS = {"id", "title", "vendor", "summary", "homepage", "brains", "servers"}
TOOL_OPTIONAL = {"aliases", "detect", "api", "notes"}
SERVER_FIELDS = {
    "id", "name", "publisher", "maintainer", "transport", "auth", "env", "status", "capabilities", "source", "verified",
}
SERVER_OPTIONAL = {
    "url", "command", "args", "package", "repository", "license", "settings", "access", "scopes", "pin", "read_only", "reviewed",
    "status_source",
}
DETECT_FIELDS = {"files", "npm", "pypi"}


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\n" in value:
        raise CatalogError(f"{label} must be one line of text")
    return value


def _https(value: object, label: str, placeholders: bool = False) -> str:
    """An https URL. A server endpoint may also be a loopback address: some servers run on the workstation."""
    text = _text(value, label)
    probe = _SETTING.sub("x", text) if placeholders else text
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?(?:/[^\s?#]*)?(?:\?[^\s#]*)?", probe) and not (
            placeholders and re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):\d{2,5}(?:/[^\s?#]*)?", probe)):
        raise CatalogError(f"{label} must be an https URL")
    if "?" in text and _SECRET_WORD.search(text.split("?", 1)[1]):
        raise CatalogError(f"{label} must not carry a credential in its query string")
    return text


def _names(value: object, label: str, pattern: re.Pattern) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value) \
            or len(set(value)) != len(value):
        raise CatalogError(f"{label} must be a list of unique names")
    return value


def _validate_server(server: object, label: str) -> None:
    if not isinstance(server, dict) or not SERVER_FIELDS <= server.keys() <= SERVER_FIELDS | SERVER_OPTIONAL:
        missing = sorted(SERVER_FIELDS - server.keys()) if isinstance(server, dict) else []
        raise CatalogError(f"{label}: a server needs {', '.join(sorted(SERVER_FIELDS))}" + (
            f"; missing {', '.join(missing)}" if missing else ""))
    label = f"{label}/{server['id']}"
    if not isinstance(server["id"], str) or not _ID.fullmatch(server["id"]):
        raise CatalogError(f"{label}: use a lowercase id with hyphens")
    for field in ("name", "maintainer", "capabilities"):
        _text(server[field], f"{label} {field}")
    for field, choices in (("publisher", PUBLISHERS), ("transport", TRANSPORTS), ("auth", AUTH), ("status", STATUSES)):
        if server[field] not in choices:
            raise CatalogError(f"{label}: {field} is one of {', '.join(choices)}")
    _names(server["env"], f"{label} env", _ENV)
    _https(server["source"], f"{label} source")
    if not isinstance(server["verified"], str) or not _DAY.fullmatch(server["verified"]):
        raise CatalogError(f"{label}: verified is the date the source was read, YYYY-MM-DD")
    if "repository" in server:
        _https(server["repository"], f"{label} repository")
    if "status_source" in server:
        _https(server["status_source"], f"{label} status_source")
    if "license" in server:
        _text(server["license"], f"{label} license")
    if "reviewed" in server and (not isinstance(server["reviewed"], str) or not _DAY.fullmatch(server["reviewed"])):
        raise CatalogError(f"{label}: reviewed is the date access, scopes and read-only mode were looked for, YYYY-MM-DD")
    for field in ("access", "scopes", "pin"):
        if field in server:
            _text(server[field], f"{label} {field}")
    if server.get("command") == "docker":
        _check_forwarded(server.get("args", []), server["env"], label)
    settings = server.get("settings", [])
    if not isinstance(settings, list) or any(
        not isinstance(item, dict) or item.keys() != {"name", "description"}
        or not isinstance(item["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", item["name"])
        for item in settings
    ):
        raise CatalogError(f"{label}: settings is a list of name and description")
    for item in settings:
        _text(item["description"], f"{label} setting {item['name']}")
    declared = {item["name"] for item in settings}
    remote = server["transport"] != "stdio"
    if remote:
        if set(server) & {"command", "args", "package"} or "url" not in server:
            raise CatalogError(f"{label}: a remote server has a url and no command")
        _https(server["url"], f"{label} url", placeholders=True)
        used = set(_SETTING.findall(server["url"]))
    else:
        if "url" in server or not {"command", "args", "package"} <= server.keys():
            raise CatalogError(f"{label}: a stdio server has command, args and package, and no url")
        _text(server["command"], f"{label} command")
        if not isinstance(server["args"], list) or any(not isinstance(arg, str) or not arg for arg in server["args"]):
            raise CatalogError(f"{label}: args is a list of text")
        package = server["package"]
        if not isinstance(package, dict) or package.keys() != {"registry", "name"} \
                or package["registry"] not in PACKAGE_REGISTRIES:
            raise CatalogError(f"{label}: package has a registry ({', '.join(PACKAGE_REGISTRIES)}) and a name")
        _text(package["name"], f"{label} package name")
        for arg in server["args"]:
            inline = _INLINE_VALUE.match(arg)
            if inline and _SECRET_WORD.search(arg.split("=", 1)[0]) and not _SETTING.fullmatch(inline.group(1)):
                raise CatalogError(f"{label}: {arg.split('=', 1)[0]} must come from the environment, not from an argument")
            if "<" in arg or ">" in arg:
                raise CatalogError(f"{label}: write placeholders as {{name}} and declare them in settings")
        used = {name for arg in server["args"] for name in _SETTING.findall(arg)}
    if used != declared:
        raise CatalogError(f"{label}: settings must declare exactly the placeholders used: {', '.join(sorted(used)) or 'none'}")
    if "read_only" in server:
        _validate_read_only(server, label)


def _check_forwarded(args: list, env: list, label: str) -> None:
    """Docker passes a container only the variables its arguments name with -e."""
    forwarded = {args[index + 1].split("=", 1)[0] for index, arg in enumerate(args[:-1]) if arg == "-e"}
    missing = [name for name in env if name not in forwarded]
    if missing:
        raise CatalogError(f"{label}: docker passes only the variables named with -e: add -e {missing[0]} to args")


def _validate_read_only(server: dict, label: str) -> None:
    """The publisher's read-only mode: how it works, and the url, headers, args or env that select it. With how
    alone, the server as registered only reads: there is nothing to select."""
    variant = server["read_only"]
    remote = server["transport"] != "stdio"
    allowed = {"how", "url", "headers"} if remote else {"how", "args", "env"}
    if not isinstance(variant, dict) or "how" not in variant or not variant.keys() <= allowed:
        raise CatalogError(f"{label}: read_only has how, and {' or '.join(sorted(allowed - {'how'}))} when they select it")
    _text(variant["how"], f"{label} read_only how")
    if "url" in variant:
        _https(variant["url"], f"{label} read_only url", placeholders=True)
        if set(_SETTING.findall(variant["url"])) != set(_SETTING.findall(server["url"])):
            raise CatalogError(f"{label}: read_only url uses the same settings as url")
    headers = variant.get("headers", {})
    if not isinstance(headers, dict) or any(
            not isinstance(value, str) or name.casefold() in ("authorization", "cookie") or _SECRET_WORD.search(name)
            or _SECRET_WORD.search(value) for name, value in headers.items()):
        raise CatalogError(f"{label}: read_only headers are plain names and values, never a credential")
    if "args" in variant:
        if not isinstance(variant["args"], list) or any(not isinstance(arg, str) or not arg for arg in variant["args"]) \
                or set(_SETTING.findall(" ".join(variant["args"]))) != set(_SETTING.findall(" ".join(server["args"]))):
            raise CatalogError(f"{label}: read_only args is a list of text with the same settings as args")
        if server["command"] == "docker":
            _check_forwarded(variant["args"], server["env"], f"{label} read_only")
    if "env" in variant:
        # A variable set to a plain value, never a credential; a container receives it only through -e in args.
        env = variant["env"]
        if server["command"] == "docker" or not isinstance(env, dict) or not env or any(
                not isinstance(name, str) or not _ENV.fullmatch(name) or name in server["env"] or _SECRET_WORD.search(name)
                or not isinstance(value, str) or not _SETTING_VALUE.fullmatch(value) or _SECRET_WORD.search(value)
                for name, value in env.items()):
            raise CatalogError(f"{label}: read_only env sets plain values for a local, non-docker server, never a credential")


def _validate_tool(tool: object, label: str) -> None:
    if not isinstance(tool, dict) or not TOOL_FIELDS <= tool.keys() <= TOOL_FIELDS | TOOL_OPTIONAL:
        raise CatalogError(f"{label}: a tool needs {', '.join(sorted(TOOL_FIELDS))}")
    if not isinstance(tool["id"], str) or not _ID.fullmatch(tool["id"]):
        raise CatalogError(f"{label}: use a lowercase id with hyphens")
    label = f"{label}/{tool['id']}"
    for field in ("title", "vendor", "summary"):
        _text(tool[field], f"{label} {field}")
    _https(tool["homepage"], f"{label} homepage")
    if not tool["brains"]:
        raise CatalogError(f"{label}: name at least one brain")
    _names(tool["brains"], f"{label} brains", _ID)
    if "aliases" in tool and (not isinstance(tool["aliases"], list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in tool["aliases"])):
        raise CatalogError(f"{label}: aliases is a list of names")
    if "notes" in tool:
        _text(tool["notes"], f"{label} notes")
    if "api" in tool:
        api = tool["api"]
        if not isinstance(api, dict) or api.keys() != {"kind", "docs"} or api["kind"] not in API_KINDS:
            raise CatalogError(f"{label}: api has a kind ({', '.join(API_KINDS)}) and docs")
        _https(api["docs"], f"{label} api docs")
    if "detect" in tool:
        detect = tool["detect"]
        if not isinstance(detect, dict) or not detect or not detect.keys() <= DETECT_FIELDS or any(
            not isinstance(values, list) or not values or any(not isinstance(item, str) or not item for item in values)
            for values in detect.values()
        ):
            raise CatalogError(f"{label}: detect lists files, npm or pypi names")
        for pattern in detect.get("files", []):
            if pattern.startswith(("/", "~")) or ".." in Path(pattern).parts or "**" in pattern:
                raise CatalogError(f"{label}: detect files are paths inside the project, without ..")
    if not isinstance(tool["servers"], list):
        raise CatalogError(f"{label}: servers is a list, empty when the tool has no MCP server")
    seen = set()
    for server in tool["servers"]:
        _validate_server(server, label)
        if server["id"] in seen:
            raise CatalogError(f"{label}: server {server['id']} is listed twice")
        seen.add(server["id"])


def _endpoint(server: dict) -> tuple:
    return (server["transport"], server.get("url"), server.get("command"), tuple(server.get("args", [])))


PROJECT_ORIGIN = "project"
PROJECT_TOOLS = ".openguildkit/catalog/tools/"


def tool_names(tool: dict) -> list[str]:
    """Every name a person may type for a tool: its ID, its title with and without the vendor, and its aliases."""
    return [tool["id"], tool["title"], f"{tool['vendor']} {tool['title']}", *tool.get("aliases", [])]


def _check_project_names(tool: dict, bundled: dict[str, str], tools: dict) -> None:
    """Refuse a project tool that takes the name of a bundled one: the person would install it by typing that name."""
    for name in tool_names(tool):
        taken = bundled.get(_key(name))
        if taken is not None:
            raise CatalogError(
                f"tool {tool['id']}: the name {name!r} is the bundled tool {taken} ({tools[taken]['title']}). "
                "A tool of the project catalog takes a name of its own, so that typing a bundled tool's name never "
                "selects it.")


def load_tools(extra_dir: Path | None = None) -> dict[str, dict]:
    """Every known tool by ID, with its category. A project can add its own in .openguildkit/catalog/tools/.

    A project tool is marked with its origin and may not take a bundled tool's ID, title or alias.
    """
    roots = [package_file("registry", "tools")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    tools, endpoints, bundled = {}, {}, {}
    for from_project, root in enumerate(roots):
        if from_project:
            bundled = {_key(name): tool["id"] for tool in tools.values() for name in tool_names(tool)}
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if not path.name.endswith(".json"):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_fields)
                if not isinstance(record, dict) or record.keys() != {"id", "title", "tools"}:
                    raise CatalogError("a tool file has id, title and tools")
                if record["id"] not in CATEGORIES or path.name != f"{record['id']}.json":
                    raise CatalogError(f"name the file after its category: {', '.join(CATEGORIES)}")
                _text(record["title"], "title")
                if not isinstance(record["tools"], list):
                    raise CatalogError("tools must be a list")
                for tool in record["tools"]:
                    _validate_tool(tool, record["id"])
                    if tool["id"] in tools:
                        raise CatalogError(f"tool {tool['id']} is already defined")
                    if from_project:
                        _check_project_names(tool, bundled, tools)
                    for server in tool["servers"]:
                        known = endpoints.setdefault(server["id"], _endpoint(server))
                        if known != _endpoint(server):
                            raise CatalogError(f"server {server['id']} has two different endpoints")
                    tools[tool["id"]] = {**tool, "category": record["id"], **({"origin": PROJECT_ORIGIN} if from_project else {})}
            except (OSError, ValueError) as error:
                raise CatalogError(f"{path}: {error}") from error
    return dict(sorted(tools.items()))


def check_tool_links(tools: dict, boards: dict) -> None:
    for tool in tools.values():
        unknown = [brain for brain in tool["brains"] if brain not in boards]
        if unknown:
            raise CatalogError(f"tool {tool['id']} names unknown brains: {', '.join(unknown)}")


def read_scenario(extra_dir: Path | None) -> dict | None:
    """The project's own records for the bundled mocks (.openguildkit/catalog/tool-mocks/scenario.json)."""
    path = None if extra_dir is None else extra_dir / SCENARIO
    if path is None or not path.is_file():
        return None
    try:
        scenario = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_fields)
    except ValueError as error:
        raise ValueError(f"{path.as_posix()} is not valid JSON: {error}") from error
    if not isinstance(scenario, dict) or "records" not in scenario or not scenario.keys() <= {"about", "records"} \
            or not isinstance(scenario["records"], dict):
        raise ValueError(f"{path.as_posix()} holds about and records: records maps a tool ID to its collections.")
    return scenario


def load_mock(tool_id: str, extra_dir: Path | None = None) -> dict:
    """The mock file of a tool: bundled, or the project's own in .openguildkit/catalog/tool-mocks/.

    The project's scenario file, when it gives records for this tool, replaces the bundled ones."""
    if not _ID.fullmatch(tool_id) or tool_id == SCENARIO[:-5]:
        raise ValueError("Use a tool ID of lowercase letters, digits and hyphens.")
    candidates = [package_file("registry", "tool-mocks", f"{tool_id}.json")]
    if extra_dir is not None:
        candidates.insert(0, extra_dir / f"{tool_id}.json")
    for path in candidates:
        if path.is_file():
            try:
                mock = validate_mock(json.loads(path.read_text(encoding="utf-8-sig")), tool_id)
            except ValueError as error:
                raise CatalogError(f"{path}: {error}") from error
            scenario = read_scenario(extra_dir)
            if scenario and tool_id in scenario["records"]:
                label = f"{(extra_dir / SCENARIO).as_posix()} ({tool_id})"
                mock = apply_scenario(mock, scenario["records"][tool_id], label)
            return mock
    raise ValueError(f"No mock for {tool_id}. Run openguildkit tools list --mocks.")


def mock_ids(extra_dir: Path | None = None) -> list[str]:
    roots = [package_file("registry", "tool-mocks")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    return sorted({path.name[:-5] for root in roots if root.is_dir() for path in root.iterdir()
                   if path.name.endswith(".json") and path.name != SCENARIO})


def _topic(brief: str) -> str:
    """The first line of a task brief, short enough to title a record."""
    line = next((item.strip() for item in brief.splitlines() if item.strip()), "")
    line = re.sub(r"\s+", " ", line).rstrip(".!?;: ")
    return line[:70].rstrip() or "Sample work item"


def scenario_fields(mock: dict) -> dict:
    """The few fields per collection that tell a project's story: the id, the title and the status."""
    return {name: [field for field in (collection.get("key"), collection.get("title"), "status")
                   if field and any(field in item for item in collection["items"])]
            for name, collection in mock.get("records", {}).items()}


def _task_record(collection: dict, task_id: str | None, brief: str) -> dict:
    """One tracker record for the task, shaped like the bundled ones: its ID, its brief, today's date."""
    record = copy.deepcopy(collection["items"][0])
    record[collection["key"]] = f"{(task_id or 'task').upper()}-1"
    record[collection["title"]] = _topic(brief)
    for field in ("description", "body", "content"):
        if field in record:
            record[field] = brief.strip()
    if "created" in record:
        record["created"] = clock.today().isoformat()
    if task_id:
        record["task"] = task_id
    return record


def scenario_records(tool_ids: list[str], project: str, tools: dict, task_id: str | None = None, brief: str = "") -> dict:
    """A starting scenario: the bundled records to replace, and one tracker record for the task.

    Nothing invents the project's data: the team or its agent writes the records that tell its own story, with
    synthetic values only. The brief goes only into the record that describes the task."""
    records = {}
    for tool_id in tool_ids:
        mock = load_mock(tool_id)
        collections = {name: copy.deepcopy(collection["items"]) for name, collection in mock.get("records", {}).items()}
        if brief.strip() and tools.get(tool_id, {}).get("category") == "issue-tracking":
            name, collection = next((name, collection) for name, collection in mock["records"].items()
                                    if "key" in collection and "title" in collection)
            collections[name].insert(0, _task_record(collection, task_id, brief))
        if collections:
            records[tool_id] = collections
    check_synthetic(records, "The scenario")
    about = (f"Starting scenario for {project}, written by openguildkit tools scenario on {clock.today().isoformat()}. "
             "Except the task's own record, these are the bundled sample records about a fictional support portal: "
             "replace them with records that tell your project's story, keep the ids consistent between collections, "
             "and keep every value invented, every address on example.test.")
    return {"about": about, "records": records}


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def match_tools(names: list[str], tools: dict) -> tuple[list[str], list[str]]:
    """Resolve the tool names a team wrote ("Jira Cloud", "github") to registry IDs."""
    index = {}
    for tool in tools.values():
        for name in tool_names(tool):
            index.setdefault(_key(name), tool["id"])
    matched, unknown = [], []
    for name in names:
        tool_id = index.get(_key(name))
        if tool_id is None:
            unknown.append(name)
        elif tool_id not in matched:
            matched.append(tool_id)
    return matched, unknown


def resolve_tool(name: str, tools: dict) -> str:
    """A registry ID from what a person typed: "Notion", "notion" or "Jira Cloud"."""
    if name in tools:
        return name
    matched, _ = match_tools([name], tools)
    if not matched:
        raise ValueError(f"Unknown tool: {name}. Run openguildkit tools list.")
    return matched[0]


def _manifest_names(root: Path) -> tuple[set[str], set[str]]:
    """Dependency names declared at the project root and one level below."""
    npm, pypi = set(), set()
    folders = [root] + sorted(
        path for path in root.iterdir() if path.is_dir() and path.name not in SKIPPED_DIRECTORIES and not path.name.startswith(".")
    )[:200] if root.is_dir() else []
    for folder in folders:
        package = folder / "package.json"
        if package.is_file() and package.stat().st_size <= MAX_MANIFEST_BYTES:
            try:
                data = json.loads(package.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                data = {}
            for section in ("dependencies", "devDependencies"):
                if isinstance(data, dict) and isinstance(data.get(section), dict):
                    npm.update(data[section])
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file() and pyproject.stat().st_size <= MAX_MANIFEST_BYTES:
            try:
                data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                data = {}
            project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
            listed = list(project.get("dependencies", []) or [])
            for extra in (project.get("optional-dependencies") or {}).values():
                listed.extend(extra or [])
            pypi.update(re.split(r"[\s\[<>=!~;]", str(item), maxsplit=1)[0].casefold() for item in listed)
        for requirements in sorted(folder.glob("requirements*.txt"))[:10]:
            if requirements.is_file() and requirements.stat().st_size <= MAX_MANIFEST_BYTES:
                try:
                    lines = requirements.read_text(encoding="utf-8-sig").splitlines()
                except (OSError, ValueError):
                    lines = []
                pypi.update(
                    re.split(r"[\s\[<>=!~;]", line.strip(), maxsplit=1)[0].casefold()
                    for line in lines if line.strip() and not line.lstrip().startswith(("#", "-"))
                )
    return npm, {name.replace("_", "-") for name in pypi if name}


def detect_tools(root: Path, tools: dict) -> list[dict]:
    """Tools the repository shows signs of: a configuration file or a declared dependency."""
    npm, pypi = _manifest_names(root)
    found = []
    for tool in tools.values():
        detect = tool.get("detect", {})
        signals = [pattern for pattern in detect.get("files", []) if any(True for _ in root.glob(pattern))]
        signals += [f"npm:{name}" for name in detect.get("npm", []) if name in npm]
        signals += [f"pypi:{name}" for name in detect.get("pypi", []) if name.casefold().replace("_", "-") in pypi]
        if signals:
            found.append({"tool": tool["id"], "signals": signals})
    return found


def recommend_tools(profile: dict, root: Path, tools: dict) -> dict:
    """What the project names and what the repository shows, resolved against the registry."""
    named, unknown = match_tools(profile.get("tools", []), tools)
    detected = detect_tools(root, tools)
    ids = list(dict.fromkeys(named + [item["tool"] for item in detected]))
    return {
        "tools": [
            {"id": tool_id, "title": tools[tool_id]["title"], "category": tools[tool_id]["category"],
             "named": tool_id in named,
             "signals": next((item["signals"] for item in detected if item["tool"] == tool_id), []),
             "servers": [server["id"] for server in tools[tool_id]["servers"]],
             "mock": None}
            for tool_id in ids
        ],
        "unknown": unknown,
    }


def choose_server(tool: dict, server_id: str | None = None, community: bool = False, *,
                  read_only: bool = False) -> dict | None:
    """The publisher's own server first, remote before local; a community server only on request. With
    read_only, a server with a documented read-only mode comes before one without."""
    servers = tool["servers"]
    if server_id:
        server = next((item for item in servers if item["id"] == server_id), None)
        if server is None:
            raise ValueError(f"{tool['id']} has no server {server_id}. Known: {', '.join(s['id'] for s in servers) or 'none'}.")
        if server["publisher"] == "community" and not community:
            raise ValueError(f"{tool['id']}/{server_id} is a community server: review its source, then pass --community.")
        return server
    usable = [item for item in servers if item["status"] != "deprecated" and (community or item["publisher"] == "vendor")]
    usable.sort(key=lambda item: (item["publisher"] != "vendor", read_only and "read_only" not in item,
                                  TRANSPORTS.index(item["transport"])))
    return usable[0] if usable else None


def _settings(server: dict, values: dict, label: str) -> tuple[dict, list[str]]:
    filled, missing = {}, []
    for item in server.get("settings", []):
        value = values.get(item["name"])
        if value is None:
            missing.append(item["name"])
        elif not isinstance(value, str) or not _SETTING_VALUE.fullmatch(value) or _SECRET_WORD.search(item["name"]):
            raise ValueError(f"{label}: {item['name']} must be a plain value such as a name or a host, never a credential.")
        else:
            filled[item["name"]] = value
    unknown = sorted(set(values) - {item["name"] for item in server.get("settings", [])})
    if unknown:
        raise ValueError(f"{label} has no setting {', '.join(unknown)}.")
    return filled, missing


def _fill(text: str, values: dict) -> str:
    return _SETTING.sub(lambda match: values.get(match.group(1), match.group(0)), text)


def _read_only_server(server: dict) -> dict:
    """The server as its publisher's read-only variant selects it: unchanged when it only reads as registered."""
    variant = server["read_only"]
    selected = {**server, **{key: value for key, value in variant.items() if key in ("url", "args")}}
    if "headers" in variant:
        selected["headers"] = dict(variant["headers"])
    if "env" in variant:
        selected["set_env"] = dict(variant["env"])
    return selected


def _version(server: dict) -> str:
    """What runs on each workstation, and whether its version is pinned."""
    if server["transport"] != "stdio":
        text = "Hosted by the publisher: no version to pin, the publisher updates it."
    else:
        package, args = server["package"], server["args"]
        name = package["name"]
        spelled = next((arg for arg in args if arg == name or arg.startswith((name + ":", name + "@"))), None)
        if package["registry"] == "docker" and spelled:
            if "@sha256:" in spelled:
                text = f"Docker image {spelled}: pinned by digest."
            elif spelled != name and not spelled.endswith(":latest"):
                text = f"Docker image {spelled}: pinned by tag."
            else:
                text = f"Docker image {name} without a tag: the documented command pulls latest" + (
                    " at every start (--pull=always)." if "--pull=always" in args else ".")
        elif package["registry"] == "npm" and spelled:
            text = (f"npm package {name} without a version: npx runs the latest release." if spelled == name
                    else f"npm package {spelled}: " + ("the documented command uses latest." if spelled.endswith("@latest")
                                                       else "pinned by version."))
        else:
            text = f"{package['registry']} package {name}: version pinning {NOT_RECORDED}."
    return text + (f" {server['pin']}" if "pin" in server else "")


def _credentials(server: dict, bearer: str | None) -> str:
    if bearer:
        return f"Bearer token read from {bearer} in each person's environment; no file holds it."
    if server["transport"] == "stdio" and server["env"]:
        return "Read from each person's environment: " + ", ".join(server["env"]) + "; no file holds them."
    if server["auth"] in ("oauth", "oauth-or-token"):
        return "Each person signs in through the host, which keeps the token; no file holds it."
    if server["auth"] == "none":
        return "None."
    return f"A token the server expects; how to pass it is {NOT_RECORDED}: see the source."


def _alternatives(tool: dict, chosen: dict) -> list[str]:
    alternatives = [f"{tool['id']}/{server['id']} ({server['publisher']}, {server['transport']}, status {server['status']}"
                    + (", read-only mode available" if "read_only" in server else "")
                    + f"): {server['capabilities'].rstrip('.')}" for server in tool["servers"] if server["id"] != chosen["id"]]
    if "api" in tool:
        kind = "" if tool["api"]["kind"] == "other" else tool["api"]["kind"] + " "
        alternatives.append(f"The {kind}API without MCP: {tool['api']['docs']}")
    return alternatives


def _read_only_fact(variant: dict) -> str:
    """How the read-only mode works, and how to select it when something has to be selected."""
    selects = variant.keys() - {"how"}
    return variant["how"] + (" Select it with --read-only." if selects else "")


def review_facts(tool: dict, server: dict, bearer: str | None = None) -> dict:
    """What a security officer reads before accepting a server, each fact from the registry or marked missing."""
    variant = server.get("read_only")
    # "Not documented" is a claim about the publisher: only made once someone looked for it on the page.
    missing = (f"{NOT_DOCUMENTED} (looked for on {server['reviewed']})" if "reviewed" in server
               else f"{NOT_RECORDED}: read {server['source']}")
    return {
        "publisher": f"{server['maintainer']} ({server['publisher']})", "status": server["status"],
        "covers": server["capabilities"], "access": server.get("access", missing),
        "scopes": server.get("scopes", missing),
        "read_only": _read_only_fact(variant) if variant else missing,
        "version": _version(server), "credentials": _credentials(server, bearer),
        "alternatives": _alternatives(tool, server), **({"notes": tool["notes"]} if "notes" in tool else {}),
    }


def host_entry(host: str, server: dict, settings: dict, token_env: str | None) -> dict:
    """The host's own configuration entry for a server. Variables are named, never resolved."""
    if server["transport"] == "stdio":
        args = [_fill(arg, settings) for arg in server["args"]]
        if host == "codex":
            entry = {"command": server["command"], "args": args}
            # Codex passes the named variables through and sets the plain values of a read-only mode itself.
            if server.get("set_env"):
                entry["env"] = dict(server["set_env"])
            if server["env"]:
                entry["env_vars"] = list(server["env"])
            return entry
        entry = {"command": server["command"], "args": args}
        values = dict(server.get("set_env", {}))
        if values or server["env"]:
            entry["env"] = {**values, **{name: "${" + name + "}" for name in server["env"]}}
        return entry
    url = _fill(server["url"], settings)
    headers = server.get("headers", {})
    if host == "codex":
        entry = {"url": url}
        if token_env:
            entry["bearer_token_env_var"] = token_env
        if headers:
            entry["http_headers"] = dict(headers)
        return entry
    entry = {"type": "sse" if server["transport"] == "sse" else "http", "url": url}
    if token_env or headers:
        entry["headers"] = {**headers, **({"Authorization": "Bearer ${" + token_env + "}"} if token_env else {})}
    return entry


def mock_entry(host: str, tool_id: str, log: str | None = None) -> dict:
    args = ["tools", "mock", tool_id] + (["--log", log] if log else [])
    return {"command": "openguildkit", "args": args}


def _variable_name(name: object) -> bool:
    """An environment variable's name, in any case; a lowercase word mixing letters and digits looks like a token."""
    if not isinstance(name, str) or not _VARIABLE.fullmatch(name) or looks_like_credential(name):
        return False
    return name.isupper() or not any(re.search(r"[a-z]", part, re.IGNORECASE) and re.search(r"\d", part)
                                     for part in name.split("_"))


def plan_connections(
    tools: dict, wanted: list[str], host: str, *, mock: bool = False, community: bool = False,
    settings: dict | None = None, token_env: dict | None = None, mocks: list[str] | None = None, log: str | None = None,
    read_only: bool = False,
) -> list[dict]:
    """One connection per server for the wanted tools ("jira" or "jira/atlassian-rovo"), whatever their case."""
    if host not in HOSTS:
        raise ValueError(f"Choose a host to write for: {', '.join(HOSTS)}.")
    if read_only and mock:
        raise ValueError("--read-only selects a live server. Use --mock separately for synthetic data.")
    settings = {key.casefold(): value for key, value in (settings or {}).items()}
    token_env = {key.casefold(): value for key, value in (token_env or {}).items()}
    mocks = mocks or []
    if any(isinstance(value, str) and looks_like_credential(value)
           for values in settings.values() for value in values.values()):
        raise ValueError("--set must be a plain value such as a name or a host, never a credential: a token stays in "
                         "each person's environment, named with --token-env TOOL=VARIABLE.")
    if any(not _variable_name(name) for name in token_env.values()):
        raise ValueError("--token-env names an environment variable, such as JIRA_TOKEN, for a remote server; "
                         "never the token itself, which stays in each person's environment.")
    plan, by_key = [], {}
    for name in wanted:
        typed, _, server_id = name.partition("/")
        try:
            tool_id = resolve_tool(typed, tools)
        except ValueError:
            plan.append({"tool": typed.strip().casefold(), "title": typed.strip(), "mode": "mock" if mock else "live",
                         "skipped": "Not in the registry: add it in .openguildkit/catalog/tools/ or connect it yourself."})
            continue
        server_id = server_id.strip().casefold()
        tool = tools[tool_id]
        origin = {"origin": PROJECT_ORIGIN} if tool.get("origin") == PROJECT_ORIGIN else {}
        if mock:
            if tool_id not in mocks:
                plan.append({"tool": tool_id, "title": tool["title"], "mode": "mock",
                             "skipped": "No mock is available for this tool.", **origin})
                continue
            plan.append({
                "tool": tool_id, "title": tool["title"], "server": "mock", "key": tool_id, "mode": "mock",
                "transport": "stdio", "needs": {"env": [], "settings": []}, "warnings": [],
                "steps": ["Synthetic data only: no account, no network."], "entry": mock_entry(host, tool_id, log), **origin,
            })
            continue
        server = choose_server(tool, server_id or None, community, read_only=read_only)
        if server is None:
            reason = "It has no MCP server on record." if not tool["servers"] else (
                "Its only servers are community-maintained: review their source, then pass --community.")
            plan.append({"tool": tool_id, "title": tool["title"], "mode": "live", "skipped": reason + (
                f" API: {tool['api']['docs']}" if "api" in tool else ""), **origin})
            continue
        if server["id"] in by_key:
            _cover(by_key[server["id"]], tool, server)
            by_key[server["id"]].update(origin)
            continue
        label = f"{tool_id}/{server['id']}"
        filled, missing = _settings(server, settings.get(tool_id, {}), label)
        bearer = token_env.get(tool_id)
        if bearer is not None and server["transport"] == "stdio":
            raise ValueError(f"{label}: --token-env names an environment variable, for a remote server.")
        warnings, steps = [], []
        if server["publisher"] == "community":
            warnings.append(f"Community server maintained by {server['maintainer']}: review {server.get('repository', server['source'])} before use.")
        if server["status"] in ("beta", "preview", "experimental"):
            warnings.append(f"The publisher marks this server as {server['status']}.")
        if host == "codex" and server["transport"] == "sse":
            plan.append({"tool": tool_id, "title": tool["title"], "mode": "live",
                         "skipped": "Codex connects to streamable HTTP and stdio servers; this one is SSE only."})
            continue
        facts = review_facts(tool, server, bearer)
        if read_only and "read_only" in server:
            server = _read_only_server(server)
            steps.append(f"Read-only mode selected: {server['read_only']['how']}")
        elif read_only:
            warnings.append(("No read-only mode is documented by the publisher" if "reviewed" in server else
                             f"No read-only mode is recorded in the registry yet (read {server['source']})")
                            + ": give the account read-only permissions instead.")
        if server["transport"] == "sse":
            warnings.append("SSE transport is deprecated by hosts: prefer a streamable HTTP server when the publisher offers one.")
        if server["transport"] == "stdio":
            steps.append(f"Install {server['package']['name']} ({server['package']['registry']}) so that `{server['command']}` runs on each workstation.")
            if server["env"]:
                steps.append("Set in each person's environment, never in a file: " + ", ".join(server["env"]) + ".")
        elif bearer:
            steps.append(f"Set {bearer} in each person's environment, never in a file.")
        elif server["auth"] in ("oauth", "oauth-or-token"):
            steps.append("Each person signs in once: /mcp in Claude Code." if host == "claude-code"
                         else f"Each person signs in once: codex mcp login {server['id']}.")
        elif server["auth"] == "api-token":
            warnings.append("This server needs a token: pass --token-env TOOL=VARIABLE, or see its source for the header it expects.")
        if missing:
            steps.append("Still to provide: " + ", ".join(f"--set {tool_id}.{name}=VALUE" for name in missing) + ".")
        item = {
            "tool": tool_id, "title": tool["title"], "server": server["id"], "key": server["id"], "mode": "live",
            "covers": [tool_id], "publisher": server["publisher"], "transport": server["transport"], "auth": server["auth"],
            "status": server["status"], "source": server["source"], "verified": server["verified"],
            "needs": {"env": list(server["env"]) + ([bearer] if bearer else []), "settings": missing},
            "settings": filled, "warnings": warnings, "steps": steps, "review": facts,
            "read_only": bool(read_only and "read_only" in server),
            "entry": host_entry(host, server, filled, bearer), **origin,
        }
        if bearer:
            item["token_env"] = bearer
        if "license" in server:
            item["license"] = server["license"]
        by_key[server["id"]] = item
        plan.append(item)
    return plan


def _cover(item: dict, tool: dict, server: dict) -> None:
    """A second tool the same server covers: named once, with its own alternatives and notes."""
    if tool["id"] in item["covers"]:
        return
    item["covers"].append(tool["id"])
    review = item["review"]
    review["alternatives"] += [line for line in _alternatives(tool, server) if line not in review["alternatives"]]
    if "notes" in tool:
        review["notes"] = (review["notes"] + " " if "notes" in review else "") + f"{tool['title']}: {tool['notes']}"


def read_manifest(state: Path) -> dict:
    path = state / MANIFEST
    if not path.is_file():
        return {"schema_version": 1, "connections": []}
    manifest = read_json(path)
    if not isinstance(manifest.get("connections"), list):
        raise ValueError(f"{path} is damaged: connections must be a list.")
    if "unconnected_mocks" in manifest:
        manifest.setdefault(UNCONNECTED, manifest.pop("unconnected_mocks"))
    unconnected = manifest.get(UNCONNECTED, [])
    if not isinstance(unconnected, list) or any(
        not isinstance(item, dict) or any(not isinstance(item.get(field), str) for field in ("host", "tool", "reason"))
        or item["host"] not in HOSTS or item.get("mode", "mock") not in ("mock", "live") for item in unconnected
    ):
        raise ValueError(f"{path} is damaged: {UNCONNECTED} must contain a host, tool, mode and reason per request.")
    return manifest


def _codex_table(key: str, entry: dict) -> str:
    """A server's TOML table; headers and environment values are inline tables."""
    lines = [f"[mcp_servers.{key}]"]
    for name, value in entry.items():
        if isinstance(value, dict):
            pairs = [f"{json.dumps(field, ensure_ascii=False)} = {json.dumps(setting, ensure_ascii=False)}"
                     for field, setting in value.items()]
            value_text = "{ " + ", ".join(pairs) + " }"
        else:
            value_text = json.dumps(value, ensure_ascii=False)
        lines.append(f"{name} = {value_text}")
    return "\n".join(lines) + "\n"


def _split_codex(text: str, path: Path) -> tuple[str, str]:
    """The person's own configuration, before and after the managed block."""
    start, end = text.find(CODEX_BLOCK_START), text.find(CODEX_BLOCK_END)
    if (start == -1) != (end == -1) or end < start:
        raise ValueError(f"{path}: the OpenGuildKit tools block is damaged. Remove its marker lines and apply again.")
    if start == -1:
        return text, ""
    return text[:start], text[end + len(CODEX_BLOCK_END):]


def _write_host(root: Path, host: str, connections: list[dict], removed: set[str]) -> tuple[str, list[str]]:
    """Write the managed entries to the host's file. Entries the person wrote under the same name are kept."""
    managed = {item["key"]: item["entry"] for item in connections if item["host"] == host}
    kept = []
    if host == "claude-code":
        path = root / CLAUDE_MCP_FILE
        data = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except ValueError as error:
                raise ValueError(f"{path.as_posix()} is not valid JSON: {error}") from error
        if not isinstance(data, dict) or not isinstance(data.setdefault("mcpServers", {}), dict):
            raise ValueError(f"{path.as_posix()} must hold a JSON object with mcpServers.")
        servers = data["mcpServers"]
        for key in removed:
            servers.pop(key, None)
        servers.update(managed)
        if servers or path.is_file():
            write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return CLAUDE_MCP_FILE, kept
    path = root / CODEX_CONFIG_FILE
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    before, after = _split_codex(text, path)
    try:
        own = tomllib.loads(before + after)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path.as_posix()} is not valid TOML: {error}") from error
    taken = own.get("mcp_servers", {}) if isinstance(own.get("mcp_servers", {}), dict) else {}
    clash = sorted(set(managed) & set(taken))
    if clash:
        raise ValueError(f"{path} already defines mcp_servers.{clash[0]} outside the OpenGuildKit block. Rename or remove it first.")
    block = ""
    if managed:
        block = CODEX_BLOCK_START + "\n".join(_codex_table(key, managed[key]) for key in sorted(managed)) + CODEX_BLOCK_END
    own_text = before.rstrip("\n")
    updated = (own_text + "\n" if own_text else "") + ("\n" if own_text and block else "") + block + after
    if updated != text:
        write_text(path, updated)
    return CODEX_CONFIG_FILE.as_posix(), kept


def check_settings(plan: list[dict]) -> None:
    """Refuse a plan whose endpoints still miss a setting, before anything is asked or written."""
    blocked = [f"{item['tool']}: provide {', '.join(item['needs']['settings'])}"
               for item in plan if "skipped" not in item and item["needs"]["settings"]]
    if blocked:
        raise ValueError("Settings are missing. " + "; ".join(blocked) + ".")


def apply_connections(root: Path, state: Path, host: str, plan: list[dict]) -> dict:
    """Record the accepted connections and write them to the host's configuration."""
    manifest = read_manifest(state)
    connections = {(item["host"], item["key"]): item for item in manifest["connections"]}
    unconnected = {(item["host"], item["tool"]): item for item in manifest.get(UNCONNECTED, [])}
    accepted = [item for item in plan if "skipped" not in item]
    check_settings(plan)
    if accepted and host == "claude-code":
        path = root / CLAUDE_MCP_FILE
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding="utf-8-sig")).get("mcpServers", {})
            except (ValueError, AttributeError) as error:
                raise ValueError(f"{path} is not a valid MCP configuration: {error}") from error
            for item in accepted:
                if item["key"] in existing and (host, item["key"]) not in connections and existing[item["key"]] != item["entry"]:
                    raise ValueError(f"{path} already defines {item['key']} with other settings. Rename or remove it first.")
    for item in accepted:
        record = {key: item[key] for key in ("key", "tool", "server", "mode", "entry") if key in item}
        record["host"] = host
        record["covers"] = item.get("covers", [item["tool"]])
        for key in ("settings", "token_env"):
            if item.get(key):
                record[key] = item[key]
        record["env"] = item["needs"]["env"]
        connections[(host, item["key"])] = record
        for covered in record["covers"]:
            unconnected.pop((host, covered), None)
    for item in plan:
        if "skipped" in item:
            unconnected[(host, item["tool"])] = {"host": host, "tool": item["tool"], "mode": item["mode"],
                                                 "reason": item["skipped"]}
    manifest["connections"] = [connections[key] for key in sorted(connections)]
    if unconnected:
        manifest[UNCONNECTED] = [unconnected[key] for key in sorted(unconnected)]
    else:
        manifest.pop(UNCONNECTED, None)
    file = CLAUDE_MCP_FILE if host == "claude-code" else CODEX_CONFIG_FILE.as_posix()
    if accepted:
        file, _ = _write_host(root, host, manifest["connections"], set())
    write_json(state / MANIFEST, manifest)
    return {"file": file, "applied": [item["key"] for item in accepted],
            "skipped": [{"tool": item["tool"], "reason": item["skipped"]} for item in plan if "skipped" in item]}


def remove_connections(root: Path, state: Path, host: str, names: list[str]) -> dict:
    manifest = read_manifest(state)
    wanted = set(names)
    removed = {item["key"] for item in manifest["connections"]
               if item["host"] == host and (item["key"] in wanted or wanted & set(item.get("covers", [])))}
    unconnected = manifest.get(UNCONNECTED, [])
    forgotten = {item["tool"] for item in unconnected if item["host"] == host and item["tool"] in wanted}
    if not removed and not forgotten:
        raise ValueError(f"No connection to remove for {', '.join(names)} on {host}. Run openguildkit tools status.")
    if forgotten:
        kept = [item for item in unconnected if not (item["host"] == host and item["tool"] in forgotten)]
        if kept:
            manifest[UNCONNECTED] = kept
        else:
            manifest.pop(UNCONNECTED)
    manifest["connections"] = [item for item in manifest["connections"] if not (item["host"] == host and item["key"] in removed)]
    file = None
    if removed:
        file, _ = _write_host(root, host, manifest["connections"], removed)
    write_json(state / MANIFEST, manifest)
    result = {"file": file, "removed": sorted(removed)}
    if forgotten:
        result["forgotten"] = sorted(forgotten)
    return result


def _host_entries(root: Path, host: str) -> dict:
    if host == "claude-code":
        path = root / CLAUDE_MCP_FILE
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except ValueError:
            return {}
        return data.get("mcpServers", {}) if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict) else {}
    path = root / CODEX_CONFIG_FILE
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError:
        return {}
    return data.get("mcp_servers", {}) if isinstance(data.get("mcp_servers"), dict) else {}


def connection_status(root: Path, state: Path, environment: dict | None = None) -> list[dict]:
    """Each recorded connection: is it still in the host file, and which variables are not set here."""
    environment = os.environ if environment is None else environment
    status = []
    entries = {host: _host_entries(root, host) for host in HOSTS}
    manifest = read_manifest(state)
    for item in manifest["connections"]:
        present = entries[item["host"]].get(item["key"])
        status.append({
            "key": item["key"], "host": item["host"], "mode": item["mode"], "covers": item.get("covers", [item["tool"]]),
            "configured": present == item["entry"],
            "changed": present is not None and present != item["entry"],
            "missing_env": [name for name in item.get("env", []) if not environment.get(name)],
        })
    status.extend({
        "key": item["tool"], "host": item["host"], "mode": item.get("mode", "mock"), "covers": [item["tool"]],
        "configured": False, "changed": False, "missing_env": [], "reason": item["reason"],
    } for item in manifest.get(UNCONNECTED, []))
    return status


def connected_tools(state: Path, tools: dict, board_id: str | None = None) -> list[dict]:
    """The connected tools a board can query, with the server name the host knows them by."""
    connected = []
    for item in read_manifest(state)["connections"]:
        for tool_id in item.get("covers", [item["tool"]]):
            tool = tools.get(tool_id)
            if tool is None or (board_id is not None and board_id not in tool["brains"]):
                continue
            entry = {"id": tool_id, "title": tool["title"], "server": item["key"], "mode": item["mode"]}
            if entry not in connected:
                connected.append(entry)
    return connected


def _mock_call_logs(root: Path, connections: list[dict]) -> set[Path]:
    """Only read journals from recorded mock connections inside the project."""
    root = root.resolve()
    logs = set()
    for connection in connections:
        args = connection.get("entry", {}).get("args", [])
        if (connection["mode"] == "mock" and len(args) == 5 and args[:2] == ["tools", "mock"]
                and args[3] == "--log"):
            path = (root / args[4]).resolve()
            if root in path.parents and path.is_file():
                logs.add(path)
    return logs


def _recorded_tool_refs(logs: set[Path], wanted: set[str]) -> set[str]:
    matched = set()
    for path in logs:
        try:
            with path.open(encoding="utf-8", errors="replace") as journal:
                for line in journal:
                    try:
                        call = json.loads(line)
                    except (ValueError, RecursionError):
                        continue
                    if not isinstance(call, dict) or not isinstance(call.get("arguments"), dict):
                        continue
                    matched.update(f"{call.get('tool')}:{value}" for value in call["arguments"].values()
                                   if isinstance(value, str) and f"{call.get('tool')}:{value}" in wanted)
                    if wanted <= matched:
                        return matched
        except OSError:
            continue
    return matched


def tool_evidence_warnings(root: Path, state: Path, boards: list[dict]) -> list[str]:
    """Flag citations that have no recorded call or use a tool outside the board's remit."""
    evidence = [
        (entry["id"], index, item["ref"])
        for entry in boards for index, item in enumerate(entry["evidence"], start=1)
        if isinstance(item, dict) and item["source"] == "tool"
    ]
    if not evidence:
        return []
    registry = load_tools(state / "catalog" / "tools")
    connections = read_manifest(state)["connections"]
    connected = {tool for item in connections for tool in item.get("covers", [item["tool"]])}
    mocked = {tool for item in connections if item["mode"] == "mock" for tool in item.get("covers", [item["tool"]])}
    matched = _recorded_tool_refs(_mock_call_logs(root, connections), {ref for _, _, ref in evidence})
    warnings = []
    for board, index, ref in evidence:
        tool, _, record = ref.partition(":")
        label = f"{board} evidence #{index}"
        if tool not in connected or board not in registry.get(tool, {}).get("brains", []):
            warnings.append(f"{label}: {tool} is not connected for this board.")
        if tool in mocked:
            warnings.append(_mock_citation(state, tool, record, label))
        elif ref not in matched:
            warnings.append(f"{label}: no recorded {tool} call matches the cited record. Verify it in the tool.")
    return warnings


def _mock_citation(state: Path, tool: str, record: str, label: str) -> str:
    """A citation of a mock: synthetic data when the mock holds the record, unsupported when it does not."""
    try:
        mock = load_mock(tool, state / "catalog" / "tool-mocks")
    except (ValueError, CatalogError):
        mock = {"records": {}, "tools": []}
    keys = {_norm_key(item.get(collection.get("key"))) for collection in mock.get("records", {}).values()
            for item in collection["items"]}
    if _norm_key(record) in keys:
        return (f"{label}: the cited record comes from the {tool} mock, synthetic sample data, not a record of the "
                f"real {tool}. The decision brief and the exported record label it as mock data.")
    return (f"{label}: the {tool} mock holds no record with the cited id, so nothing supports this citation. Cite a "
            f"record the mock returns (openguildkit tools call {tool}); a simulated write keeps nothing.")


def _norm_key(value) -> str:
    return str(value).strip().casefold()


