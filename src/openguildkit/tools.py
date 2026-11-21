"""The tools of a company's stack and the MCP servers that connect an agent to them.

The registry (registry/tools/, one file per category) names each tool, the review boards
that use it and the MCP servers verified on the publisher's own documentation. From it the
CLI proposes the servers that match a project's tools, writes the host configuration the
person accepted, and can replace every server with a local mock for demos and tests.

Credentials never enter a file: a server names the environment variables it reads, and the
host passes them through.
"""

import json
import os
import re
import tomllib
from pathlib import Path

from .catalog import CatalogError, _unique_fields, package_file
from .detect import MAX_MANIFEST_BYTES, SKIPPED_DIRECTORIES
from .mcp_mock import validate_mock
from .storage import json_text, read_json, write_json, write_text

CATEGORIES = (
    "issue-tracking", "source-control", "ci-cd", "documentation", "design", "communication", "time-tracking", "hr",
    "finance", "crm", "marketing", "support", "security", "quality", "observability", "cloud", "data", "browser",
    "testing", "analytics", "automation", "product",
)
TRANSPORTS = ("streamable-http", "sse", "stdio")
PUBLISHERS = ("vendor", "community")
AUTH = ("oauth", "api-token", "oauth-or-token", "none")
STATUSES = ("ga", "beta", "preview", "experimental", "deprecated", "unknown")
PACKAGE_REGISTRIES = ("npm", "pypi", "docker", "github-release", "cargo", "homebrew", "other")
API_KINDS = ("rest", "graphql", "other")
HOSTS = ("claude-code", "codex")
MANIFEST = "tools.json"
CLAUDE_MCP_FILE = ".mcp.json"
CODEX_CONFIG_FILE = Path(".codex") / "config.toml"
CODEX_BLOCK_START = "# >>> OpenGuildKit tools (openguildkit tools apply rewrites this block)\n"
CODEX_BLOCK_END = "# <<< OpenGuildKit tools\n"

_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_ENV = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
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
SERVER_OPTIONAL = {"url", "command", "args", "package", "repository", "license", "settings", "access", "read_only"}
ACCESS_MODES = ("read-only", "read-write", "unknown")
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
    if "license" in server:
        _text(server["license"], f"{label} license")
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
    access = server.get("access", {})
    if not isinstance(access, dict) or not access.keys() <= {"mode", "consent", "scopes"} \
            or access.get("mode", "unknown") not in ACCESS_MODES:
        raise CatalogError(f"{label}: access describes the mode, consent and scopes")
    if "consent" in access:
        _text(access["consent"], f"{label} consent")
    if "scopes" in access:
        if not isinstance(access["scopes"], list):
            raise CatalogError(f"{label}: scopes must be a list")
        for scope in access["scopes"]:
            _text(scope, f"{label} scope")
    if "read_only" in server:
        _validate_read_only(server, label, declared)


def _validate_read_only(server: dict, label: str, settings: set[str]) -> None:
    mode = server["read_only"]
    if not isinstance(mode, dict) or len(mode) != 1:
        raise CatalogError(f"{label}: read_only needs an endpoint, read-only header or Docker environment flag")
    kind, value = next(iter(mode.items()))
    if server["transport"] != "stdio":
        if kind == "header" and value == "X-MCP-Readonly":
            return
        if kind == "url" and set(_SETTING.findall(_https(value, f"{label} read-only URL", placeholders=True))) == settings:
            return
    elif kind == "docker_env" and server["command"] == "docker" and isinstance(value, str) \
            and re.fullmatch(r"[A-Z][A-Z0-9_]*READ_?ONLY", value) and server["package"]["name"] in server["args"]:
        return
    raise CatalogError(f"{label}: invalid read-only configuration for {server['transport']}")


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


def load_tools(extra_dir: Path | None = None) -> dict[str, dict]:
    """Every known tool by ID, with its category. A project can add its own in .openguildkit/catalog/tools/."""
    roots = [package_file("registry", "tools")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    tools, endpoints = {}, {}
    for root in roots:
        for path in sorted(root.iterdir(), key=lambda item: item.name):
            if not path.name.endswith(".json"):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_fields)
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
                    for server in tool["servers"]:
                        known = endpoints.setdefault(server["id"], _endpoint(server))
                        if known != _endpoint(server):
                            raise CatalogError(f"server {server['id']} has two different endpoints")
                    tools[tool["id"]] = {**tool, "category": record["id"]}
            except (OSError, ValueError) as error:
                raise CatalogError(f"{path}: {error}") from error
    return dict(sorted(tools.items()))


def check_tool_links(tools: dict, boards: dict) -> None:
    for tool in tools.values():
        unknown = [brain for brain in tool["brains"] if brain not in boards]
        if unknown:
            raise CatalogError(f"tool {tool['id']} names unknown brains: {', '.join(unknown)}")


def load_mock(tool_id: str, extra_dir: Path | None = None) -> dict:
    """The mock file of a tool: bundled, or the project's own in .openguildkit/catalog/tool-mocks/."""
    if not _ID.fullmatch(tool_id):
        raise ValueError("Use a tool ID of lowercase letters, digits and hyphens.")
    candidates = [package_file("registry", "tool-mocks", f"{tool_id}.json")]
    if extra_dir is not None:
        candidates.insert(0, extra_dir / f"{tool_id}.json")
    for path in candidates:
        if path.is_file():
            try:
                return validate_mock(json.loads(path.read_text(encoding="utf-8-sig")), tool_id)
            except ValueError as error:
                raise CatalogError(f"{path}: {error}") from error
    raise ValueError(f"No mock for {tool_id}. Run openguildkit tools list --mocks.")


def mock_ids(extra_dir: Path | None = None) -> list[str]:
    roots = [package_file("registry", "tool-mocks")]
    if extra_dir is not None and extra_dir.is_dir():
        roots.append(extra_dir)
    return sorted({path.name[:-5] for root in roots if root.is_dir() for path in root.iterdir() if path.name.endswith(".json")})


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def match_tools(names: list[str], tools: dict) -> tuple[list[str], list[str]]:
    """Resolve the tool names a team wrote ("Jira Cloud", "github") to registry IDs."""
    index = {}
    for tool in tools.values():
        for name in (tool["id"], tool["title"], f"{tool['vendor']} {tool['title']}", *tool.get("aliases", [])):
            index.setdefault(_key(name), tool["id"])
    matched, unknown = [], []
    for name in names:
        tool_id = index.get(_key(name))
        if tool_id is None:
            unknown.append(name)
        elif tool_id not in matched:
            matched.append(tool_id)
    return matched, unknown


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


def _supports_read_only(server: dict) -> bool:
    return bool(server.get("read_only")) or server.get("access", {}).get("mode") == "read-only"


def choose_server(tool: dict, server_id: str | None = None, community: bool = False, *,
                  read_only: bool = False) -> dict | None:
    """The publisher's own server first, remote before local; a community server only on request."""
    servers = tool["servers"]
    if server_id:
        server = next((item for item in servers if item["id"] == server_id), None)
        if server is None:
            raise ValueError(f"{tool['id']} has no server {server_id}. Known: {', '.join(s['id'] for s in servers) or 'none'}.")
        if server["publisher"] == "community" and not community:
            raise ValueError(f"{tool['id']}/{server_id} is a community server: review its source, then pass --community.")
        if read_only and not _supports_read_only(server):
            raise ValueError(f"{tool['id']}/{server_id} has no documented read-only mode.")
        return server
    usable = [
        item for item in servers if item["status"] != "deprecated" and (community or item["publisher"] == "vendor")
        and (not read_only or _supports_read_only(item))
    ]
    usable.sort(key=lambda item: (item["publisher"] != "vendor", TRANSPORTS.index(item["transport"])))
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


def host_entry(host: str, server: dict, settings: dict, token_env: str | None, *, read_only: bool = False) -> dict:
    """The host's own configuration entry for a server. Variables are named, never resolved."""
    restriction = server.get("read_only", {}) if read_only else {}
    if server["transport"] == "stdio":
        args = [_fill(arg, settings) for arg in server["args"]]
        if "docker_env" in restriction:
            image = args.index(server["package"]["name"])
            args[image:image] = ["-e", restriction["docker_env"] + "=true"]
        if host == "codex":
            entry = {"command": server["command"], "args": args}
            if server["env"]:
                entry["env_vars"] = list(server["env"])
            return entry
        entry = {"command": server["command"], "args": args}
        if server["env"]:
            entry["env"] = {name: "${" + name + "}" for name in server["env"]}
        return entry
    url = _fill(restriction.get("url", server["url"]), settings)
    headers = {restriction["header"]: "true"} if "header" in restriction else {}
    if host == "codex":
        entry = {"url": url}
        if token_env:
            entry["bearer_token_env_var"] = token_env
        if headers:
            entry["http_headers"] = headers
        return entry
    entry = {"type": "sse" if server["transport"] == "sse" else "http", "url": url}
    if token_env:
        headers["Authorization"] = "Bearer ${" + token_env + "}"
    if headers:
        entry["headers"] = headers
    return entry


def mock_entry(host: str, tool_id: str, log: str | None = None) -> dict:
    args = ["tools", "mock", tool_id] + (["--log", log] if log else [])
    return {"command": "openguildkit", "args": args}


def plan_connections(
    tools: dict, wanted: list[str], host: str, *, mock: bool = False, community: bool = False,
    settings: dict | None = None, token_env: dict | None = None, mocks: list[str] | None = None, log: str | None = None,
    read_only: bool = False,
) -> list[dict]:
    """One connection per server for the wanted tools ("jira" or "jira/atlassian-rovo")."""
    if host not in HOSTS:
        raise ValueError(f"Choose a host to write for: {', '.join(HOSTS)}.")
    if read_only and mock:
        raise ValueError("--read-only selects a live server. Use --mock separately for synthetic data.")
    settings = {key.casefold(): value for key, value in (settings or {}).items()}
    token_env = {key.casefold(): value for key, value in (token_env or {}).items()}
    mocks = mocks or []
    plan, by_key = [], {}
    for name in wanted:
        tool_id, _, server_id = name.casefold().partition("/")
        if tool_id not in tools:
            raise ValueError(f"Unknown tool: {tool_id}. Run openguildkit tools list.")
        tool = tools[tool_id]
        if mock:
            if tool_id not in mocks:
                plan.append({"tool": tool_id, "title": tool["title"], "skipped": "No mock is available for this tool."})
                continue
            plan.append({
                "tool": tool_id, "title": tool["title"], "server": "mock", "key": tool_id, "mode": "mock",
                "transport": "stdio", "needs": {"env": [], "settings": []}, "warnings": [],
                "steps": ["Synthetic data only: no account, no network."], "entry": mock_entry(host, tool_id, log),
            })
            continue
        server = choose_server(tool, server_id or None, community, read_only=read_only)
        if server is None:
            if read_only:
                raise ValueError(f"{tool_id} has no eligible server with a documented read-only mode.")
            reason = "It has no MCP server on record." if not tool["servers"] else (
                "Its only servers are community-maintained: review their source, then pass --community.")
            plan.append({"tool": tool_id, "title": tool["title"], "skipped": reason + (
                f" API: {tool['api']['docs']}" if "api" in tool else "")})
            continue
        if server["id"] in by_key:
            existing = by_key[server["id"]]
            if tool_id not in existing["covers"]:
                existing["covers"].append(tool_id)
                existing["alternatives"][tool_id] = _alternatives(tool, server["id"])
                if tool.get("notes"):
                    existing["notes"][tool_id] = tool["notes"]
            continue
        label = f"{tool_id}/{server['id']}"
        filled, missing = _settings(server, settings.get(tool_id, {}), label)
        bearer = token_env.get(tool_id)
        if bearer is not None and (not _ENV.fullmatch(bearer) or server["transport"] == "stdio"):
            raise ValueError(f"{label}: --token-env names an environment variable, for a remote server.")
        warnings, steps = [], []
        if server["publisher"] == "community":
            warnings.append(f"Community server maintained by {server['maintainer']}: review {server.get('repository', server['source'])} before use.")
        if server["status"] in ("beta", "preview", "experimental"):
            warnings.append(f"The publisher marks this server as {server['status']}.")
        if host == "codex" and server["transport"] == "sse":
            if read_only:
                raise ValueError(f"{label} uses SSE, which Codex does not support.")
            plan.append({"tool": tool_id, "title": tool["title"], "skipped": "Codex connects to streamable HTTP and stdio servers; this one is SSE only."})
            continue
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
        access = server.get("access", {})
        scope = "No credentials required" if server["auth"] == "none" else "See the publisher's source and credential permissions"
        item = {
            "tool": tool_id, "title": tool["title"], "server": server["id"], "key": server["id"], "mode": "live",
            "maintainer": server["maintainer"], "capabilities": server["capabilities"],
            "access": {
                "mode": "read-only" if read_only else access.get("mode", "unknown"),
                "consent": access.get("consent", "None" if server["auth"] == "none" else "See the publisher's source"),
                "scopes": access.get("scopes") or [scope],
                "read_only_available": _supports_read_only(server),
            },
            "alternatives": {tool_id: _alternatives(tool, server["id"])},
            "notes": {tool_id: tool["notes"]} if tool.get("notes") else {},
            "covers": [tool_id], "publisher": server["publisher"], "transport": server["transport"], "auth": server["auth"],
            "status": server["status"], "source": server["source"], "verified": server["verified"],
            "needs": {"env": list(server["env"]) + ([bearer] if bearer else []), "settings": missing},
            "settings": filled, "warnings": warnings, "steps": steps,
            "entry": host_entry(host, server, filled, bearer, read_only=read_only),
        }
        if server.get("package", {}).get("registry") == "docker":
            image = server["package"]["name"]
            item["image"] = {
                "name": image,
                "digest_pinned": bool(re.search(r"@sha256:[0-9a-f]{64}$", image)),
                "pull_always": "--pull=always" in server["args"],
            }
        if bearer:
            item["token_env"] = bearer
        if "license" in server:
            item["license"] = server["license"]
        by_key[server["id"]] = item
        plan.append(item)
    return plan


def _alternatives(tool: dict, selected: str) -> list[dict]:
    return [
        {**{field: server[field] for field in ("id", "capabilities", "status", "publisher")},
         "read_only_available": _supports_read_only(server)}
        for server in tool["servers"] if server["id"] != selected
    ]


def read_manifest(state: Path) -> dict:
    path = state / MANIFEST
    if not path.is_file():
        return {"schema_version": 1, "connections": []}
    manifest = read_json(path)
    if not isinstance(manifest.get("connections"), list):
        raise ValueError(f"{path} is damaged: connections must be a list.")
    return manifest


def _codex_table(key: str, entry: dict) -> str:
    lines = [f"[mcp_servers.{key}]"]
    for name, value in entry.items():
        if isinstance(value, dict):
            pairs = [f"{json.dumps(key)} = {json.dumps(setting)}" for key, setting in value.items()]
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


def apply_connections(root: Path, state: Path, host: str, plan: list[dict]) -> dict:
    """Record the accepted connections and write them to the host's configuration."""
    manifest = read_manifest(state)
    connections = {(item["host"], item["key"]): item for item in manifest["connections"]}
    accepted = [item for item in plan if "skipped" not in item]
    blocked = [f"{item['tool']}: provide {', '.join(item['needs']['settings'])}" for item in accepted if item["needs"]["settings"]]
    if blocked:
        raise ValueError("Settings are missing. " + "; ".join(blocked) + ".")
    if host == "claude-code":
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
    manifest["connections"] = [connections[key] for key in sorted(connections)]
    file, _ = _write_host(root, host, manifest["connections"], set())
    write_json(state / MANIFEST, manifest)
    return {"file": file, "applied": [item["key"] for item in accepted],
            "skipped": [{"tool": item["tool"], "reason": item["skipped"]} for item in plan if "skipped" in item]}


def remove_connections(root: Path, state: Path, host: str, names: list[str]) -> dict:
    manifest = read_manifest(state)
    wanted = set(names)
    removed = {item["key"] for item in manifest["connections"]
               if item["host"] == host and (item["key"] in wanted or wanted & set(item.get("covers", [])))}
    if not removed:
        raise ValueError(f"No connection to remove for {', '.join(names)} on {host}. Run openguildkit tools status.")
    manifest["connections"] = [item for item in manifest["connections"] if not (item["host"] == host and item["key"] in removed)]
    file, _ = _write_host(root, host, manifest["connections"], removed)
    write_json(state / MANIFEST, manifest)
    return {"file": file, "removed": sorted(removed)}


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
    for item in read_manifest(state)["connections"]:
        present = entries[item["host"]].get(item["key"])
        status.append({
            "key": item["key"], "host": item["host"], "mode": item["mode"], "covers": item.get("covers", [item["tool"]]),
            "configured": present == item["entry"],
            "changed": present is not None and present != item["entry"],
            "missing_env": [name for name in item.get("env", []) if not environment.get(name)],
        })
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


def manifest_text(manifest: dict) -> str:
    return json_text(manifest)
