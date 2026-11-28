"""Loads the tool registry and the project's own tools, and checks each tool and MCP server it declares."""

import re
from pathlib import Path

from . import lazy_re
from .catalog import CatalogError, package_file, record_files, validate_day

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


TOOL_ID = lazy_re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


_ENV = lazy_re.compile(r"[A-Z][A-Z0-9_]{1,63}")


SETTING_NAME = lazy_re.compile(r"\{([a-z][a-z0-9_]*)\}")


SECRET_WORD = lazy_re.compile(r"(?i)(token|secret|password|passwd|api[_-]?key|apikey|bearer)")


_INLINE_VALUE = lazy_re.compile(r"^-{0,2}[A-Za-z0-9_.-]*=(.+)$")


# A plain value: a name, a host, or a path on the workstation, absolute ones included.
SETTING_VALUE = lazy_re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}|/[A-Za-z0-9][A-Za-z0-9._:/@-]{0,198}")


# What a publisher writes in place of a value the reader fills in: /path/to/server, <your-site>.
_STAND_IN = lazy_re.compile(r"(?i)path/to/|[<>]")


TOOL_FIELDS = {"id", "title", "vendor", "summary", "homepage", "brains", "servers"}


TOOL_OPTIONAL = {"aliases", "detect", "api", "notes"}


SERVER_FIELDS = {
    "id", "name", "publisher", "maintainer", "transport", "auth", "env", "status", "capabilities", "source", "verified",
}


SERVER_OPTIONAL = {
    "url", "command", "args", "package", "repository", "license", "settings", "access", "scopes", "pin", "read_only", "reviewed",
    "status_source", "pin_read",
}


DETECT_FIELDS = {"files", "npm", "pypi"}


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or "\n" in value:
        raise CatalogError(f"{label} must be one line of text")
    return value


def _https(value: object, label: str, placeholders: bool = False) -> str:
    """An https URL. A server endpoint may also be a loopback address: some servers run on the workstation."""
    text = _text(value, label)
    probe = SETTING_NAME.sub("x", text) if placeholders else text
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::\d+)?(?:/[^\s?#]*)?(?:\?[^\s#]*)?", probe) and not (
            placeholders and re.fullmatch(r"http://(?:127\.0\.0\.1|localhost):\d{2,5}(?:/[^\s?#]*)?", probe)):
        raise CatalogError(f"{label} must be an https URL")
    if "?" in text and SECRET_WORD.search(text.split("?", 1)[1]):
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
    if not isinstance(server["id"], str) or not TOOL_ID.fullmatch(server["id"]):
        raise CatalogError(f"{label}: use a lowercase id with hyphens")
    for field in ("name", "maintainer", "capabilities"):
        _text(server[field], f"{label} {field}")
    for field, choices in (("publisher", PUBLISHERS), ("transport", TRANSPORTS), ("auth", AUTH), ("status", STATUSES)):
        if server[field] not in choices:
            raise CatalogError(f"{label}: {field} is one of {', '.join(choices)}")
    _names(server["env"], f"{label} env", _ENV)
    _https(server["source"], f"{label} source")
    _read_on(server, "verified", label, "the source was read")
    _server_optional_fields(server, label)
    if server.get("command") == "docker":
        _check_forwarded(server.get("args", []), server["env"], label)
    declared = _server_settings(server, label)
    remote = server["transport"] != "stdio"
    used = _remote_placeholders(server, label) if remote else _stdio_placeholders(server, label)
    if used != declared:
        raise CatalogError(f"{label}: settings must declare exactly the placeholders used: {', '.join(sorted(used)) or 'none'}")
    if "read_only" in server:
        _validate_read_only(server, label)


def _server_optional_fields(server: dict, label: str) -> None:
    """The optional fields of a server: its repository, status source and license, the dates it was reviewed and
    its pin read, its access, scopes and pin."""
    if "repository" in server:
        _https(server["repository"], f"{label} repository")
    if "status_source" in server:
        _https(server["status_source"], f"{label} status_source")
    if "license" in server:
        _text(server["license"], f"{label} license")
    if "reviewed" in server:
        _read_on(server, "reviewed", label, "access, scopes and read-only mode were looked for")
    if "pin_read" in server:
        _read_on(server, "pin_read", label, "the version written in the launch was read in the package registry")
    for field in ("access", "scopes", "pin"):
        if field in server:
            _text(server[field], f"{label} {field}")


def _server_settings(server: dict, label: str) -> set[str]:
    """The names of the settings a server declares, each with its description."""
    settings = server.get("settings", [])
    if not isinstance(settings, list) or any(
        not isinstance(item, dict) or item.keys() != {"name", "description"}
        or not isinstance(item["name"], str) or not re.fullmatch(r"[a-z][a-z0-9_]*", item["name"])
        for item in settings
    ):
        raise CatalogError(f"{label}: settings is a list of name and description")
    for item in settings:
        _text(item["description"], f"{label} setting {item['name']}")
    return {item["name"] for item in settings}


def _remote_placeholders(server: dict, label: str) -> set[str]:
    """The setting placeholders of a remote server's url, once it has a url and no command."""
    if set(server) & {"command", "args", "package"} or "url" not in server:
        raise CatalogError(f"{label}: a remote server has a url and no command")
    _https(server["url"], f"{label} url", placeholders=True)
    return set(SETTING_NAME.findall(server["url"]))


def _stdio_placeholders(server: dict, label: str) -> set[str]:
    """The setting placeholders of a stdio server's command and args, once its launch, package and arguments are
    checked: no stand-in, no secret written inline."""
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
    _check_stand_ins([server["command"], *server["args"]], label)
    for arg in server["args"]:
        inline = _INLINE_VALUE.match(arg)
        if inline and SECRET_WORD.search(arg.split("=", 1)[0]) and not SETTING_NAME.fullmatch(inline.group(1)):
            raise CatalogError(f"{label}: {arg.split('=', 1)[0]} must come from the environment, not from an argument")
    return {name for text in [server["command"], *server["args"]] for name in SETTING_NAME.findall(text)}


def _read_on(server: dict, field: str, label: str, meaning: str) -> None:
    """verified and reviewed pass the check of a catalog source's checked: a calendar day, not in the future."""
    try:
        validate_day(server[field], f"{label} {field}")
    except CatalogError as error:
        raise CatalogError(f"{error}; {field} is the date {meaning}") from None


def _check_stand_ins(values: list[str], label: str) -> None:
    """A command written with the publisher's stand-in starts nothing on a workstation: a placeholder makes tools
    plan ask for the real value instead."""
    for value in values:
        if _STAND_IN.search(value):
            raise CatalogError(f"{label}: {value!r} stands in for a value: write placeholders as {{name}} and declare "
                               "them in settings, with where to find the value")


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
        if set(SETTING_NAME.findall(variant["url"])) != set(SETTING_NAME.findall(server["url"])):
            raise CatalogError(f"{label}: read_only url uses the same settings as url")
    headers = variant.get("headers", {})
    if not isinstance(headers, dict) or any(
            not isinstance(value, str) or name.casefold() in ("authorization", "cookie") or SECRET_WORD.search(name)
            or SECRET_WORD.search(value) for name, value in headers.items()):
        raise CatalogError(f"{label}: read_only headers are plain names and values, never a credential")
    if "args" in variant:
        _read_only_args(server, variant["args"], label)
    if "env" in variant:
        _read_only_env(server, variant["env"], label)


def _read_only_args(server: dict, args: object, label: str) -> None:
    """The args that select a read-only mode: text, with the same settings as the server's args."""
    if not isinstance(args, list) or any(not isinstance(arg, str) or not arg for arg in args) \
            or set(SETTING_NAME.findall(" ".join(args))) != set(SETTING_NAME.findall(" ".join(server["args"]))):
        raise CatalogError(f"{label}: read_only args is a list of text with the same settings as args")
    _check_stand_ins(args, f"{label} read_only")
    if server["command"] == "docker":
        _check_forwarded(args, server["env"], f"{label} read_only")


def _read_only_env(server: dict, env: object, label: str) -> None:
    """A variable set to a plain value, never a credential; a container receives it only through -e in args."""
    if server["command"] == "docker" or not isinstance(env, dict) or not env or any(
            not isinstance(name, str) or not _ENV.fullmatch(name) or name in server["env"] or SECRET_WORD.search(name)
            or not isinstance(value, str) or not SETTING_VALUE.fullmatch(value) or SECRET_WORD.search(value)
            for name, value in env.items()):
        raise CatalogError(f"{label}: read_only env sets plain values for a local, non-docker server, never a credential")


def _tool_api_and_detect(tool: dict, label: str) -> None:
    """The API a tool documents, and the files or package names that detect it in a project."""
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


def _validate_tool(tool: object, label: str) -> None:
    if not isinstance(tool, dict) or not TOOL_FIELDS <= tool.keys() <= TOOL_FIELDS | TOOL_OPTIONAL:
        raise CatalogError(f"{label}: a tool needs {', '.join(sorted(TOOL_FIELDS))}")
    if not isinstance(tool["id"], str) or not TOOL_ID.fullmatch(tool["id"]):
        raise CatalogError(f"{label}: use a lowercase id with hyphens")
    label = f"{label}/{tool['id']}"
    for field in ("title", "vendor", "summary"):
        _text(tool[field], f"{label} {field}")
    _https(tool["homepage"], f"{label} homepage")
    if not tool["brains"]:
        raise CatalogError(f"{label}: name at least one brain")
    _names(tool["brains"], f"{label} brains", TOOL_ID)
    if "aliases" in tool and (not isinstance(tool["aliases"], list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in tool["aliases"])):
        raise CatalogError(f"{label}: aliases is a list of names")
    if "notes" in tool:
        _text(tool["notes"], f"{label} notes")
    _tool_api_and_detect(tool, label)
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
        taken = bundled.get(tool_key(name))
        if taken is not None:
            raise CatalogError(
                f"tool {tool['id']}: the name {name!r} is the bundled tool {taken} ({tools[taken]['title']}). "
                "A tool of the project catalog takes a name of its own, so that typing a bundled tool's name never "
                "selects it. Rename the project tool and update the profile, or remove the project definition "
                "to use OpenGuildKit's bundled tool.")


def _load_tool_file(path: Path, record: object, from_project: bool, tools: dict, endpoints: dict,
                    bundled: dict) -> None:
    """Add the tools of one category file to tools, refusing a tool defined twice, a server with two endpoints, and
    a project tool that takes a bundled tool's name."""
    if not isinstance(record, dict) or record.keys() != {"id", "title", "tools"}:
        raise CatalogError("a tool file has id, title and tools")
    if record["id"] not in CATEGORIES or path.name != f"{record['id']}.json":
        raise CatalogError(f"name the file after its category: {', '.join(CATEGORIES)}")
    _text(record["title"], "title")
    if not isinstance(record["tools"], list):
        raise CatalogError("tools must be a list")
    for tool in record["tools"]:
        _validate_tool(tool, record["id"])
        if from_project:
            _check_project_names(tool, bundled, tools)
        if tool["id"] in tools:
            raise CatalogError(f"tool {tool['id']} is already defined")
        for server in tool["servers"]:
            known = endpoints.setdefault(server["id"], _endpoint(server))
            if known != _endpoint(server):
                raise CatalogError(f"server {server['id']} has two different endpoints")
        tools[tool["id"]] = {**tool, "category": record["id"], **({"origin": PROJECT_ORIGIN} if from_project else {})}


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
            bundled = {tool_key(name): tool["id"] for tool in tools.values() for name in tool_names(tool)}
        for path, record in record_files(root):
            try:
                _load_tool_file(path, record, bool(from_project), tools, endpoints, bundled)
            except (OSError, ValueError) as error:
                raise CatalogError(f"{path}: {error}") from error
    return dict(sorted(tools.items()))


def check_tool_links(tools: dict, boards: dict) -> None:
    for tool in tools.values():
        unknown = [brain for brain in tool["brains"] if brain not in boards]
        if unknown:
            raise CatalogError(f"tool {tool['id']} names unknown brains: {', '.join(unknown)}")


def tool_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.casefold())
