"""The tools of a company's stack: matches them to a project, plans the MCP servers to connect and checks the evidence
agents cite from them.

The registry (registry/tools/, one file per category) names each tool, the review boards
that use it and the MCP servers verified on the publisher's own documentation. From it the
CLI proposes the servers that match a project's tools, writes the host configuration the
person accepted, and can replace every server with a local mock for demos and tests.

Credentials never enter a file: a server names the environment variables it reads, and the
host passes them through.

Entry: read_scenario, load_mock, mock_ids
Tests: tests/test_catalog_format_doc.py, tests/test_catalog_sources.py, tests/test_check_links.py,
tests/test_features.py, tests/test_new_brains.py, tests/test_source_dates.py
"""

import copy
import json
import re
import tomllib
from pathlib import Path

from . import clock, lazy_re
from .catalog import CatalogError, package_file
from .detect import SKIPPED_DIRECTORIES
from .detect_manifest import MAX_MANIFEST_BYTES
from .errors import OgkError
from .records import Profile
from .sensitive import looks_like_credential
from .storage import load_json, unique_fields
from .tool_connections import HOSTS, read_manifest
from .tool_registry import (
    PROJECT_ORIGIN,
    SECRET_WORD,
    SETTING_NAME,
    SETTING_VALUE,
    TOOL_ID,
    TRANSPORTS,
    load_tools,
    tool_key,
    tool_names,
)

SCENARIO = "scenario.json"
NOT_DOCUMENTED = "not documented by the publisher"
NOT_RECORDED = "not recorded in the registry yet"

_VARIABLE = lazy_re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")


def read_scenario(extra_dir: Path | None) -> dict | None:
    """The project's own records for the bundled mocks (.openguildkit/catalog/tool-mocks/scenario.json)."""
    path = None if extra_dir is None else extra_dir / SCENARIO
    if path is None or not path.is_file():
        return None
    try:
        scenario = load_json(path, pairs=unique_fields)
    except ValueError as error:
        raise ValueError(f"{path.as_posix()} is not valid JSON: {error}") from error
    if not isinstance(scenario, dict) or "records" not in scenario or not scenario.keys() <= {"about", "records"} \
            or not isinstance(scenario["records"], dict):
        raise ValueError(f"{path.as_posix()} holds about and records: records maps a tool ID to its collections.")
    return scenario


def load_mock(tool_id: str, extra_dir: Path | None = None) -> dict:
    """The mock file of a tool: bundled, or the project's own in .openguildkit/catalog/tool-mocks/.

    The project's scenario file, when it gives records for this tool, replaces the bundled ones."""
    if not TOOL_ID.fullmatch(tool_id) or tool_id == SCENARIO[:-5]:
        raise ValueError("Use a tool ID of lowercase letters, digits and hyphens.")
    candidates = [package_file("registry", "tool-mocks", f"{tool_id}.json")]
    if extra_dir is not None:
        candidates.insert(0, extra_dir / f"{tool_id}.json")
    from .mcp_mock import apply_scenario, validate_mock  # Only the mocks need it (#539).

    for path in candidates:
        if path.is_file():
            try:
                mock = validate_mock(load_json(path), tool_id)
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
    from .mcp_mock import check_synthetic

    check_synthetic(records, "The scenario")
    about = (f"Starting scenario for {project}, written by openguildkit tools scenario on {clock.today().isoformat()}. "
             "Except the task's own record, these are the bundled sample records about a fictional support portal: "
             "replace them with records that tell your project's story, keep the ids consistent between collections, "
             "and keep every value invented, every address on example.test.")
    return {"about": about, "records": records}


def match_tools(names: list[str], tools: dict) -> tuple[list[str], list[str]]:
    """Resolve the tool names a team wrote ("Jira Cloud", "github") to registry IDs."""
    index = {}
    for tool in tools.values():
        for name in tool_names(tool):
            index.setdefault(tool_key(name), tool["id"])
    matched, unknown = [], []
    for name in names:
        tool_id = index.get(tool_key(name))
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
        raise OgkError("OGK-TOOLS-006", f"Unknown tool: {name}. Run openguildkit tools list.")
    return matched[0]


def _npm_names(folder: Path) -> set[str]:
    """The dependencies and dev dependencies the package.json of a folder declares."""
    names: set[str] = set()
    package = folder / "package.json"
    if package.is_file() and package.stat().st_size <= MAX_MANIFEST_BYTES:
        try:
            data = load_json(package)
        except (OSError, ValueError):
            data = {}
        for section in ("dependencies", "devDependencies"):
            if isinstance(data, dict) and isinstance(data.get(section), dict):
                names.update(data[section])
    return names


def _pyproject_names(folder: Path) -> set[str]:
    """The dependencies and optional dependencies the pyproject.toml of a folder declares, in lower case."""
    pyproject = folder / "pyproject.toml"
    if not pyproject.is_file() or pyproject.stat().st_size > MAX_MANIFEST_BYTES:
        return set()
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        data = {}
    project = data.get("project", {}) if isinstance(data.get("project"), dict) else {}
    listed = list(project.get("dependencies", []) or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        listed.extend(extra or [])
    return {re.split(r"[\s\[<>=!~;]", str(item), maxsplit=1)[0].casefold() for item in listed}


def _requirement_names(folder: Path) -> set[str]:
    """The packages the requirements*.txt files of a folder list, in lower case."""
    names: set[str] = set()
    for requirements in sorted(folder.glob("requirements*.txt"))[:10]:
        if requirements.is_file() and requirements.stat().st_size <= MAX_MANIFEST_BYTES:
            try:
                lines = requirements.read_text(encoding="utf-8-sig").splitlines()
            except (OSError, ValueError):
                lines = []
            names.update(
                re.split(r"[\s\[<>=!~;]", line.strip(), maxsplit=1)[0].casefold()
                for line in lines if line.strip() and not line.lstrip().startswith(("#", "-"))
            )
    return names


def _manifest_names(root: Path) -> tuple[set[str], set[str]]:
    """Dependency names declared at the project root and one level below."""
    npm, pypi = set(), set()
    folders = [root] + sorted(
        path for path in root.iterdir() if path.is_dir() and path.name not in SKIPPED_DIRECTORIES and not path.name.startswith(".")
    )[:200] if root.is_dir() else []
    for folder in folders:
        npm.update(_npm_names(folder))
        pypi.update(_pyproject_names(folder))
        pypi.update(_requirement_names(folder))
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


def recommend_tools(profile: Profile, root: Path, tools: dict) -> dict:
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
            raise OgkError("OGK-TOOLS-007", f"{tool['id']}/{server_id} is a community server: review its source, then pass --community.")
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
        elif not isinstance(value, str) or not SETTING_VALUE.fullmatch(value) or SECRET_WORD.search(item["name"]):
            raise OgkError("OGK-TOOLS-008", f"{label}: {item['name']} must be a plain value such as a name or a host, never a credential.")
        else:
            filled[item["name"]] = value
    unknown = sorted(set(values) - {item["name"] for item in server.get("settings", [])})
    if unknown:
        raise OgkError("OGK-TOOLS-009", f"{label} has no setting {', '.join(unknown)}.")
    return filled, missing


def _fill(text: str, values: dict) -> str:
    return SETTING_NAME.sub(lambda match: values.get(match.group(1), match.group(0)), text)


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
    day = f" Version read in the package registry on {server['pin_read']}." if "pin_read" in server else ""
    return text + day + (f" {server['pin']}" if "pin" in server else "")


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
        command, args = _fill(server["command"], settings), [_fill(arg, settings) for arg in server["args"]]
        if host == "codex":
            entry = {"command": command, "args": args}
            # Codex passes the named variables through and sets the plain values of a read-only mode itself.
            if server.get("set_env"):
                entry["env"] = dict(server["set_env"])
            if server["env"]:
                entry["env_vars"] = list(server["env"])
            return entry
        entry = {"command": command, "args": args}
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
    settings, token_env = _plan_options(host, mock, settings, token_env, read_only)
    mocks = mocks or []
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
            plan.append(_mock_connection(tool_id, tool, mocks, host, log, origin))
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
        item = _live_connection(tool_id, tool, server, host, settings.get(tool_id, {}), token_env.get(tool_id),
                                read_only, origin)
        if "skipped" not in item:
            by_key[item["key"]] = item
        plan.append(item)
    return plan


def _plan_options(host: str, mock: bool, settings: dict | None, token_env: dict | None,
                  read_only: bool) -> tuple[dict, dict]:
    """The settings and token variables of tools connect keyed by tool, whatever their case, once the host and the
    options are checked: no credential in --set, a variable name in --token-env."""
    if host not in HOSTS:
        raise ValueError(f"Choose a host to write for: {', '.join(HOSTS)}.")
    if read_only and mock:
        raise OgkError("OGK-TOOLS-010", "--read-only selects a live server. Use --mock separately for synthetic data.")
    settings = {key.casefold(): value for key, value in (settings or {}).items()}
    token_env = {key.casefold(): value for key, value in (token_env or {}).items()}
    if any(isinstance(value, str) and looks_like_credential(value)
           for values in settings.values() for value in values.values()):
        raise OgkError("OGK-TOOLS-011", "--set must be a plain value such as a name or a host, never a credential: a token stays in "
                         "each person's environment, named with --token-env TOOL=VARIABLE.")
    if any(not _variable_name(name) for name in token_env.values()):
        raise OgkError("OGK-TOOLS-012", "--token-env names an environment variable, such as JIRA_TOKEN, for a remote server; "
                         "never the token itself, which stays in each person's environment.")
    return settings, token_env


def _mock_connection(tool_id: str, tool: dict, mocks: list[str], host: str, log: str | None, origin: dict) -> dict:
    """The connection to the synthetic server of a tool, or why there is none."""
    if tool_id not in mocks:
        return {"tool": tool_id, "title": tool["title"], "mode": "mock",
                "skipped": "No mock is available for this tool.", **origin}
    return {
        "tool": tool_id, "title": tool["title"], "server": "mock", "key": tool_id, "mode": "mock",
        "transport": "stdio", "needs": {"env": [], "settings": []}, "warnings": [],
        "steps": ["Synthetic data only: no account, no network."], "entry": mock_entry(host, tool_id, log), **origin,
    }


def _live_connection(tool_id: str, tool: dict, server: dict, host: str, given: dict, bearer: str | None,
                     read_only: bool, origin: dict) -> dict:
    """The connection to the live server chosen for a tool, with its warnings, steps and host entry; skipped when
    the host cannot reach its transport."""
    label = f"{tool_id}/{server['id']}"
    filled, missing = _settings(server, given, label)
    if bearer is not None and server["transport"] == "stdio":
        raise ValueError(f"{label}: --token-env names an environment variable, for a remote server.")
    warnings, steps = [], []
    if server["publisher"] == "community":
        warnings.append(f"Community server maintained by {server['maintainer']}: review {server.get('repository', server['source'])} before use.")
    if server["status"] in ("beta", "preview", "experimental"):
        warnings.append(f"The publisher marks this server as {server['status']}.")
    if host == "codex" and server["transport"] == "sse":
        return {"tool": tool_id, "title": tool["title"], "mode": "live",
                "skipped": "Codex connects to streamable HTTP and stdio servers; this one is SSE only."}
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
    _access_steps(server, host, filled, bearer, warnings, steps)
    if missing:
        described = {item["name"]: item["description"] for item in server.get("settings", [])}
        steps.append("Still to provide: " + ", ".join(f"--set {tool_id}.{name}=VALUE ({described[name]})"
                                                      for name in missing) + ".")
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
    return item


def _access_steps(server: dict, host: str, filled: dict, bearer: str | None, warnings: list[str],
                  steps: list[str]) -> None:
    """How each person reaches the server: install its package, set its variables, or sign in."""
    if server["transport"] == "stdio":
        steps.append(f"Install {server['package']['name']} ({server['package']['registry']}) so that "
                     f"`{_fill(server['command'], filled)}` runs on each workstation.")
        if server["env"]:
            steps.append("Set in each person's environment, never in a file: " + ", ".join(server["env"]) + ".")
    elif bearer:
        steps.append(f"Set {bearer} in each person's environment, never in a file.")
    elif server["auth"] in ("oauth", "oauth-or-token"):
        steps.append("Each person signs in once: /mcp in Claude Code." if host == "claude-code"
                     else f"Each person signs in once: codex mcp login {server['id']}.")
    elif server["auth"] == "api-token":
        warnings.append("This server needs a token: pass --token-env TOOL=VARIABLE, or see its source for the header it expects.")


def _cover(item: dict, tool: dict, server: dict) -> None:
    """A second tool the same server covers: named once, with its own alternatives and notes."""
    if tool["id"] in item["covers"]:
        return
    item["covers"].append(tool["id"])
    review = item["review"]
    review["alternatives"] += [line for line in _alternatives(tool, server) if line not in review["alternatives"]]
    if "notes" in tool:
        review["notes"] = (review["notes"] + " " if "notes" in review else "") + f"{tool['title']}: {tool['notes']}"


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
            if _journal_refs(path, wanted, matched):
                return matched
        except OSError:
            continue
    return matched


def _journal_refs(path: Path, wanted: set[str], matched: set[str]) -> bool:
    """Add to matched the wanted references the calls of one mock journal carry: True once all are matched."""
    with path.open(encoding="utf-8", errors="replace") as journal:
        for line in journal:
            matched.update(_call_refs(line, wanted))
            if wanted <= matched:
                return True
    return False


def _call_refs(line: str, wanted: set[str]) -> set[str]:
    """The wanted TOOL:VALUE references one journal line of a mock call carries in its arguments."""
    try:
        call = json.loads(line)
    except (ValueError, RecursionError):
        return set()
    if not isinstance(call, dict) or not isinstance(call.get("arguments"), dict):
        return set()
    return {f"{call.get('tool')}:{value}" for value in call["arguments"].values()
            if isinstance(value, str) and f"{call.get('tool')}:{value}" in wanted}


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


