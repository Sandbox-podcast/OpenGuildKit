"""The `openguildkit tools` commands: browse the tool registry, connect a project's tools, rehearse with mocks."""

import json
import sys
from functools import partial
from pathlib import Path
from typing import TextIO

from .mcp_mock import MockError, call_tool, describe, example_arguments, is_generic, serve, signature
from .project import load_profile
from .sensitive import looks_like_credential
from .shell import shell_command
from .storage import json_text, project_lock, write_text
from .tasks import read_task
from .terminal import interactive
from .tools import (
    CATEGORIES, HOSTS, PROJECT_ORIGIN, PROJECT_TOOLS, SCENARIO, apply_connections, check_settings, check_tool_links,
    choose_server, connection_status, load_mock, load_tools, mock_ids, plan_connections, read_manifest, recommend_tools,
    remove_connections, resolve_tool, scenario_fields, scenario_records,
)


def add_parser(commands) -> None:
    tools = commands.add_parser(
        "tools", help="Browse the tools of a company stack and their MCP servers, connect them or rehearse with mocks.")
    actions = tools.add_subparsers(dest="tools_action", required=True)
    listing = actions.add_parser("list", help="List the known tools and whether an MCP server is on record.")
    listing.add_argument("--category", choices=CATEGORIES, help="Only one category.")
    listing.add_argument("--brain", help="Only the tools a brain uses.")
    listing.add_argument("--mocks", action="store_true", help="Only the tools that have a mock.")
    listing.add_argument("--json", action="store_true", help="Print the entries as JSON.")
    show = actions.add_parser("show", help="Show a tool: its servers, what they need and where that was verified.")
    show.add_argument("id", help="Tool ID.")
    show.add_argument("--json", action="store_true", help="Print the entry as JSON.")
    recommend = actions.add_parser("recommend", help="Match the project's tools and repository to the registry.")
    recommend.add_argument("--json", action="store_true", help="Print the result as JSON.")
    for name, text in (("plan", "Show the MCP servers that would be configured, and what each person must provide."),
                       ("apply", "Write the accepted MCP servers to the host's project configuration.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("tool", nargs="+", metavar="TOOL", help="Tool ID, or TOOL/SERVER to pick a server.")
        command.add_argument("--host", choices=HOSTS, help="Agent host to write for (defaults to the project's host).")
        command.add_argument("--mock", action="store_true", help="Connect local mocks with synthetic data instead.")
        command.add_argument("--community", action="store_true", help="Allow community-maintained servers.")
        command.add_argument("--set", action="append", default=[], metavar="TOOL.NAME=VALUE", dest="settings",
                             help="A setting a server needs, such as a subdomain (repeatable).")
        command.add_argument("--token-env", action="append", default=[], metavar="TOOL=VARIABLE",
                             help="Environment variable that holds the bearer token of a remote server (repeatable).")
        command.add_argument("--log", metavar="FILE", help="With --mock: journal of the calls the agent makes.")
        command.add_argument("--read-only", action="store_true",
                             help="Select each server's read-only mode when its publisher documents one, "
                                  "preferring a tool's server that has one.")
        command.add_argument("--json", action="store_true", help="Print the plan as JSON.")
        if name == "apply":
            command.add_argument("--yes", action="store_true",
                                 help="Write live servers without asking: the team reviewed the plan.")
    status = actions.add_parser("status", help="Show the recorded connections and what is missing on this workstation.")
    status.add_argument("--json", action="store_true", help="Print the status as JSON.")
    remove = actions.add_parser("remove", help="Remove connections from the host's project configuration.")
    remove.add_argument("tool", nargs="+", metavar="TOOL", help="Tool ID or server name.")
    remove.add_argument("--host", choices=HOSTS, help="Agent host (defaults to the project's host).")
    mock = actions.add_parser("mock", help="Run a tool's mock MCP server on stdio: synthetic data, no network.")
    mock.add_argument("id", help="Tool ID.")
    mock.add_argument("--log", type=Path, metavar="FILE", help="Append each tool call to this file.")
    call = actions.add_parser("call", help="Call one tool of a mock and print its answer, without an MCP client.")
    call.add_argument("id", help="Tool ID.")
    call.add_argument("name", nargs="?", help="Name of the mock's tool. Omit it to list them.")
    call.add_argument("--args", default="{}", metavar="JSON", help="Arguments as a JSON object.")
    call.add_argument("--json", action="store_true", help="Without a tool name: list the mock's tools as JSON.")
    scenario = actions.add_parser(
        "scenario", help="Write a starting scenario: the mocks' records retitled for this project, all synthetic.")
    scenario.add_argument("tool", nargs="*", metavar="TOOL", help="Tools with a mock (defaults to the project's).")
    about = scenario.add_mutually_exclusive_group()
    about.add_argument("--task", metavar="ID", help="Title the records after this task's brief.")
    about.add_argument("--brief", metavar="TEXT", help="Title the records after this text.")
    scenario.add_argument("--force", action="store_true", help="Replace an existing scenario file.")


def _pairs(values: list[str], separator: str, label: str) -> dict:
    """Parse TOOL.NAME=VALUE or TOOL=VALUE options into {tool: {name: value}} or {tool: value}."""
    parsed = {}
    for value in values:
        left, equals, right = value.partition("=")
        if not equals or not left or not right:
            raise ValueError(f"Write {label}.")
        if separator:
            tool, dot, name = left.partition(separator)
            if not dot or not tool or not name:
                raise ValueError(f"Write {label}.")
            parsed.setdefault(tool.casefold(), {})[name] = right
        else:
            parsed[left.casefold()] = right
    return parsed


def _host(args, profile: dict) -> str:
    host = args.host or profile.get("host")
    if host not in HOSTS:
        raise ValueError(
            f"OpenGuildKit writes MCP settings for {' and '.join(HOSTS)}, and the project's host is {host or 'not set'}. "
            f"Add --host {HOSTS[0]} or --host {HOSTS[1]} to this command to write them for that agent, "
            "or change the project's host with openguildkit profile set host. For another agent, "
            "run openguildkit tools plan ID --host codex and adapt the server settings to that agent."
        )
    return host


# The plan for the host other: complete mcpServers blocks, the format most MCP clients read, and no other
# host's sign-in command.
GENERIC = "mcpServers"
SIGN_IN = "Each person signs in once:"
GENERIC_SIGN_IN = "Each person signs in once, with the agent's own MCP sign-in (see its documentation)."
PROJECT_MARK = "project catalog"


def _print_plan(plan: list[dict], host: str, stream: TextIO | None = None) -> None:
    """The plan as text; stream is standard output unless a JSON answer must stay alone there."""
    emit = partial(print, file=stream)
    for item in plan:
        # A record from the project catalog is the team's own: OpenGuildKit did not verify it.
        origin = f" [{PROJECT_MARK}]" if item.get("origin") == PROJECT_ORIGIN else ""
        if "skipped" in item:
            emit(f"{item['title']}{origin}: skipped. {item['skipped']}")
            continue
        covers = ", ".join(item.get("covers", [item["tool"]]))
        if item["mode"] == "mock":
            emit(f"{item['title']}{origin}: mock server `{item['key']}` (synthetic data).")
        else:
            emit(f"{covers}{origin}: server `{item['key']}` ({item['publisher']}, {item['transport']}, status {item['status']}).")
            emit(f"    Verified {item['verified']} on {item['source']}")
        if origin:
            emit(f"    From the {PROJECT_MARK} ({PROJECT_TOOLS}), not the registry OpenGuildKit ships: its facts and its "
                 "command are the team's own. Read the record before you connect it.")
        for warning in item["warnings"]:
            emit(f"    Warning: {warning}")
        for step in item["steps"]:
            emit(f"    {GENERIC_SIGN_IN if host == GENERIC and step.startswith(SIGN_IN) else step}")
        _print_review(item.get("review"), emit)
        if host == GENERIC:
            emit(f"    {json.dumps({'mcpServers': {item['key']: item['entry']}}, ensure_ascii=False)}")
        else:
            emit(f"    {host}: {json.dumps(item['entry'], ensure_ascii=False)}")


def _print_review(facts: dict | None, emit=print) -> None:
    """The facts a security officer checks before accepting a server."""
    if not facts:
        return
    for label, key in (("Publisher", "publisher"), ("Covers", "covers"), ("Access", "access"),
                       ("Scopes and consent", "scopes"), ("Read-only mode", "read_only"), ("Version", "version"),
                       ("Credentials", "credentials")):
        emit(f"    {label}: {facts[key]}")
    emit("    Alternatives: " + ("; ".join(facts["alternatives"]) or "none on record."))
    if "notes" in facts:
        emit(f"    Notes: {facts['notes']}")


def _confirm_live(plan: list[dict], args, host: str, tools: dict) -> None:
    """A live server is third-party code with access to company data: writing it needs a yes. With --json, the
    plan and the question go to standard error so that standard output holds only the JSON answer."""
    items = [item for item in plan if "skipped" not in item and item["mode"] == "live"]
    live = [item["key"] for item in items]
    if not live or args.yes:
        return
    if not interactive():
        raise ValueError(f"Review the plan of {', '.join(live)} (openguildkit tools plan), then write it with: "
                         + _apply_command(args, host, plan, tools) + " --yes")
    _print_plan(items, host, sys.stderr if args.json else None)
    print(f"Type yes to write the live servers {', '.join(live)} to the host file [y/N]: ", end="", file=sys.stderr,
          flush=True)
    if input().strip().casefold() not in ("y", "yes"):
        raise ValueError("Nothing written: the plan was not accepted.")


def _apply_command(args, host: str, plan: list[dict], tools: dict) -> str:
    """The apply command with the person's own tools and options, ready to paste; tools the plan skips are left out."""
    skipped = {item["tool"] for item in plan if "skipped" in item}
    kept = [name for name in args.tool if _known_id(name.partition("/")[0], tools) not in skipped]
    words = ["openguildkit", "tools", "apply", *kept, "--host", host]
    words += ["--mock"] * args.mock + ["--community"] * args.community + ["--read-only"] * args.read_only
    for option, values in (("--set", args.settings), ("--token-env", args.token_env)):
        for value in values:
            name, equals, given = value.partition("=")
            # A hint never repeats what looks like a credential: the person types the value again.
            words += [option, f"{name}=VALUE" if equals and looks_like_credential(given) else value]
    if args.log:
        words += ["--log", args.log]
    return shell_command(words)


def _known_id(name: str, tools: dict) -> str:
    """A tool or server name whatever its case: the registry ID when the name is a tool's."""
    try:
        return resolve_tool(name, tools)
    except ValueError:
        return name.casefold()


def _kept_log(state: Path, host: str, names: list[str], tools: dict) -> str | None:
    """The journal the existing mock entries of these tools write to, so applying again does not drop it."""
    wanted = {_known_id(name.partition("/")[0], tools) for name in names}
    logs = set()
    for item in read_manifest(state)["connections"]:
        args = item.get("entry", {}).get("args", [])
        if item["mode"] == "mock" and item["host"] == host and item["tool"] in wanted and "--log" in args[:-1]:
            logs.add(args[args.index("--log") + 1])
    if len(logs) != 1:
        return None
    log = logs.pop()
    print(f"Kept the journal {log} of the existing mock entries; pass --log FILE to change it.", file=sys.stderr)
    return log


def _apply_exit_code(result: dict) -> int:
    """0 when every requested tool is connected, 2 when some are and others are not, 1 when none could be."""
    if not result["skipped"]:
        return 0
    return 2 if result["applied"] else 1


def _scenario(args, root: Path, state: Path, tools: dict, profile: dict) -> int:
    """Write the starting scenario from the bundled records of the project's tools."""
    path = state / "catalog" / "tool-mocks" / SCENARIO
    if path.exists() and not args.force:
        raise ValueError(f".openguildkit/catalog/tool-mocks/{SCENARIO} exists. Edit it, or pass --force to replace it.")
    if args.tool:
        wanted = [resolve_tool(name, tools) for name in args.tool]
    else:
        # The project's tools, then those connected as mocks (tools apply --mock), which the profile may not name.
        wanted = [item["id"] for item in recommend_tools(profile, root, tools)["tools"]]
        wanted += [item["tool"] for item in read_manifest(state)["connections"] if item["mode"] == "mock"]
    wanted = list(dict.fromkeys(wanted))
    served = [tool_id for tool_id in wanted if tool_id in mock_ids() and load_mock(tool_id).get("records")]
    if not served:
        examined = (f"None of these tools has a mock with records: {', '.join(wanted)}." if wanted else
                    "The profile names no tool and no tool is connected as a mock.")
        raise ValueError(f"{examined} Name the tools: openguildkit tools scenario TOOL [TOOL ...] "
                         f"(those with a mock: openguildkit tools list --mocks).")
    brief = read_task(state, args.task)["brief"] if args.task else (args.brief or "")
    scenario = scenario_records(served, profile.get("name") or root.name, tools, args.task, brief)
    with project_lock(state):
        write_text(path, json_text(scenario))
    print(f"Wrote .openguildkit/catalog/tool-mocks/{SCENARIO} for {', '.join(served)}.")
    tracker = [tool_id for tool_id in served if tools[tool_id]["category"] == "issue-tracking"]
    if brief.strip() and tracker:
        print(f"It holds one {tracker[0]} record for the task, with its ID and brief. The other records are the bundled "
              "sample data about a fictional support portal.")
    else:
        print("It holds the bundled sample data about a fictional support portal.")
    print("Replace them with records that tell your project's story, synthetic values only. The fields that matter:")
    for tool_id in served:
        fields = scenario_fields(load_mock(tool_id))
        print(f"    {tool_id}: " + "; ".join(f"{name} ({', '.join(names)})" for name, names in fields.items()))
    print(f"Then check it: openguildkit tools call {served[0]}")
    return 0


def _print_mock_listing(mock: dict) -> None:
    """The tools of a mock as JSON, for a page that offers them: names only come from the mock, never from prose."""
    print(json.dumps({
        "tool": mock["tool"],
        "instructions": mock.get("instructions", ""),
        "generic": is_generic(mock) and bool(mock.get("records")),
        "tools": [{"name": tool["name"], "read_only": tool.get("read_only", False), "description": tool["description"],
                   "arguments": signature(tool), "example": example_arguments(mock, tool)} for tool in mock["tools"]],
    }, indent=2, ensure_ascii=False))


def _call(args, mock_dir: Path) -> int:
    """tools call: list a mock's tools, or call one of them."""
    args.id = args.id.casefold()
    mock = load_mock(args.id, mock_dir)
    if args.name is None:
        if args.json:
            _print_mock_listing(mock)
        else:
            print("\n".join(describe(mock)))
        return 0
    if args.json:
        raise ValueError(f"--json lists the tools of the mock: run openguildkit tools call {args.id} --json, "
                         "without a tool name.")
    try:
        arguments = json.loads(args.args)
    except ValueError as error:
        raise ValueError(f"--args is not valid JSON: {error}") from error
    try:
        answer = call_tool(mock, args.name, arguments)
    except MockError as error:
        raise ValueError(f"{error}. Run openguildkit tools call {args.id} to list the tools.") from error
    tool = next(item for item in mock["tools"] if item["name"] == args.name)
    print(answer["content"][0]["text"])
    if not tool.get("read_only") and not answer["isError"]:
        print("Warning: this operation simulates a write; the mock keeps nothing, so later calls will not show it. "
              "Use openguildkit task authorize before a real write.", file=sys.stderr)
    if answer["isError"] and answer["content"][0]["text"].startswith(("Missing argument", "Unknown argument", "Argument ")):
        example = json.dumps(example_arguments(mock, tool), ensure_ascii=False)
        print(f"Example: openguildkit tools call {args.id} {args.name} --args '{example}'", file=sys.stderr)
    return 1 if answer["isError"] else 0


def _list(args, tools: dict, mocks: set, catalog: dict) -> int:
    """tools list: the registry, filtered by category, brain or mock."""
    if args.brain and args.brain not in catalog["boards"]:
        raise ValueError(f"Unknown brain: {args.brain}. Run openguildkit brains.")
    entries = [
        tool for tool in tools.values()
        if (not args.category or tool["category"] == args.category)
        and (not args.brain or args.brain in tool["brains"]) and (not args.mocks or tool["id"] in mocks)
    ]
    if args.json:
        print(json.dumps([{**tool, "mock": tool["id"] in mocks} for tool in entries], indent=2, ensure_ascii=False))
        return 0
    for tool in entries:
        server = choose_server(tool, community=True)
        mcp = "no MCP server" if server is None else f"{server['publisher']} MCP ({server['transport']})"
        print(f"{tool['id']:<20} {tool['category']:<15} {mcp:<32}{' mock' if tool['id'] in mocks else ''}")
    print(f"{len(entries)} tool(s). Details: openguildkit tools show ID")
    return 0


def _show(args, tools: dict, mocks: set) -> int:
    """tools show: one tool, its servers and what each needs."""
    tool = tools[resolve_tool(args.id, tools)]
    if args.json:
        print(json.dumps({**tool, "mock": tool["id"] in mocks}, indent=2, ensure_ascii=False))
        return 0
    print(f"{tool['title']} ({tool['vendor']}), {tool['category']}")
    print(tool["summary"])
    print(f"Used by: {', '.join(tool['brains'])}")
    for server in tool["servers"]:
        where = server.get("url") or " ".join([server["command"], *server["args"]])
        print(f"- {server['id']}: {server['name']} [{server['publisher']}, {server['transport']}, auth {server['auth']}, status {server['status']}]")
        print(f"    {where}")
        if server["env"]:
            print(f"    Reads from the environment: {', '.join(server['env'])}")
        for setting in server.get("settings", []):
            print(f"    Needs --set {tool['id']}.{setting['name']}=VALUE ({setting['description']})")
        print(f"    {server['capabilities']}")
        print(f"    Verified {server['verified']} on {server['source']}")
    if not tool["servers"]:
        print("No MCP server on record.")
    if "api" in tool:
        print(f"API ({tool['api']['kind']}): {tool['api']['docs']}")
    if "notes" in tool:
        print(f"Notes: {tool['notes']}")
    if tool["id"] in mocks:
        print(f"Mock available: openguildkit tools call {tool['id']}")
    return 0


def _recommend(args, root: Path, state: Path, tools: dict, mocks: set, profile: dict) -> int:
    """tools recommend: the tools of the profile and the repository, and how each is connected."""
    result = recommend_tools(profile, root, tools)
    configured, unconnected = {}, {}
    for connection in connection_status(root, state):
        if connection["configured"]:
            for tool in connection["covers"]:
                configured.setdefault(tool, []).append({"host": connection["host"], "mode": connection["mode"]})
        elif "reason" in connection:
            unconnected.setdefault(connection["key"], []).append(
                {"host": connection["host"], "mode": connection["mode"], "reason": connection["reason"]})
    for item in result["tools"]:
        item["mock"] = item["id"] in mocks
        item["connections"] = configured.get(item["id"], [])
        item["not_connected"] = unconnected.pop(item["id"], [])
    result["requested_not_connected"] = [{"id": tool_id, **entry} for tool_id, entries in unconnected.items()
                                         for entry in entries]
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    for item in result["tools"]:
        origin = "named in the profile" if item["named"] else "seen in the repository: " + ", ".join(item["signals"])
        servers = ", ".join(item["servers"]) or "no MCP server on record"
        print(f"{item['id']:<20} {origin}. Servers: {servers}{'; mock available' if item['mock'] else ''}")
        if item["connections"]:
            modes = ", ".join(f"{entry['host']} ({entry['mode']})" for entry in item["connections"])
            print(f"    Configured for {modes}.")
        for entry in item["not_connected"]:
            print(f"    Requested for {entry['host']} ({entry['mode']}), not connected: {entry['reason']}")
    for entry in result["requested_not_connected"]:
        print(f"{entry['id']:<20} requested for {entry['host']} ({entry['mode']}), not connected: {entry['reason']}")
    for name in result["unknown"]:
        print(f"{name}: not in the registry. Add it in .openguildkit/catalog/tools/ or connect it yourself.")
    if not result["tools"] and not result["unknown"]:
        print("No tool named in the profile and none detected. Name them with openguildkit profile add tool TOOL "
              "--by INITIALS --reason WHY.")
    elif pending := [item["id"] for item in result["tools"] if not item["connections"]]:
        print("Next: openguildkit tools plan " + " ".join(pending))
    return 0


def _status(args, root: Path, state: Path) -> int:
    """tools status: each recorded connection and whether it holds."""
    status = connection_status(root, state)
    if args.json:
        print(json.dumps(status, indent=2, ensure_ascii=False))
        return 0
    for item in status:
        if "reason" in item:
            print(f"{item['key']:<24} {item['host']:<12} {item['mode']:<5} not connected. {item['reason']}")
            continue
        state_text = "configured" if item["configured"] else ("changed by hand" if item["changed"] else "missing from the host file")
        missing = f"; not set here: {', '.join(item['missing_env'])}" if item["missing_env"] else ""
        print(f"{item['key']:<24} {item['host']:<12} {item['mode']:<5} {state_text} ({', '.join(item['covers'])}){missing}")
    if not status:
        print("No connection recorded. Start with openguildkit tools recommend.")
    return 0 if all(item["configured"] for item in status if "reason" not in item) else 1


def run(args, root: Path, state: Path, catalog: dict) -> int:
    action = args.tools_action
    mock_dir = state / "catalog" / "tool-mocks"
    if action == "mock":
        return serve(load_mock(args.id.casefold(), mock_dir), log=args.log)
    if action == "call":
        return _call(args, mock_dir)
    tools = load_tools(state / "catalog" / "tools")
    check_tool_links(tools, catalog["boards"])
    mocks = mock_ids(mock_dir)
    if action == "list":
        return _list(args, tools, mocks, catalog)
    if action == "show":
        return _show(args, tools, mocks)
    profile = load_profile(state, catalog)
    if action == "scenario":
        return _scenario(args, root, state, tools, profile)
    if action == "recommend":
        return _recommend(args, root, state, tools, mocks, profile)
    if action == "status":
        return _status(args, root, state)
    generic = action == "plan" and not args.host and profile.get("host", "other") not in HOSTS
    # For another agent, the plan shows the mcpServers entries most MCP clients read; nothing is written.
    host = "claude-code" if generic else _host(args, profile)
    if action == "remove":
        names = [_known_id(name, tools) for name in args.tool]
        with project_lock(state):
            result = remove_connections(root, state, host, names)
        if result["removed"]:
            print(f"Removed {', '.join(result['removed'])} from {result['file']}.")
        if result.get("forgotten"):
            print(f"Cleared the unconnected requests for {', '.join(result['forgotten'])}.")
        return 0
    if args.mock and not args.log:
        args.log = _kept_log(state, host, args.tool, tools)
    plan = plan_connections(
        tools, args.tool, host, mock=args.mock, community=args.community,
        settings=_pairs(args.settings, ".", "--set TOOL.NAME=VALUE"),
        token_env=_pairs(args.token_env, "", "--token-env TOOL=VARIABLE"), mocks=mocks, log=args.log,
        read_only=args.read_only,
    )
    if action == "plan":
        if args.json:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
        elif generic:
            _print_plan(plan, GENERIC)
            print(f"Nothing is written. The project's host is {profile.get('host', 'other')}: copy each mcpServers block "
                  "above into your agent's MCP settings, or pass --host claude-code or --host codex to plan for one "
                  "of them.", file=sys.stderr)
        else:
            _print_plan(plan, host)
            if all("skipped" in item for item in plan):
                print("Nothing is written, and nothing in this plan can be connected.", file=sys.stderr)
            else:
                print("Nothing is written. Once the team accepts the plan, run:\n    " + _apply_command(args, host, plan, tools),
                      file=sys.stderr)
        return 0
    return _apply(args, root, state, host, plan, tools)


def _apply(args, root: Path, state: Path, host: str, plan: list, tools: dict) -> int:
    """tools apply: write the planned connections to the host file and report them."""
    check_settings(plan)
    _confirm_live(plan, args, host, tools)
    with project_lock(state):
        result = apply_connections(root, state, host, plan)
    exit_code = _apply_exit_code(result)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return exit_code
    _print_plan([item for item in plan if "skipped" not in item], host)
    for item in [] if args.mock else result["skipped"]:
        print(f"{item['tool']}: skipped. {item['reason']}")
    if result["applied"]:
        print(f"Wrote {', '.join(result['applied'])} to {result['file']} and recorded "
              f"{'it' if len(result['applied']) == 1 else 'them'} in .openguildkit/tools.json.")
    elif result["skipped"]:
        print(f"Nothing written to {result['file']}; the requests left unconnected are recorded for openguildkit tools status.")
    connected = ", ".join(result["applied"]) or "none"
    missing = ", ".join(item["tool"] for item in result["skipped"]) or "none"
    earlier = sorted({item["key"] for item in connection_status(root, state) if "reason" in item and item["host"] == host}
                     - {item["tool"] for item in result["skipped"]})
    if earlier:
        print(f"Still not connected from earlier requests: {', '.join(earlier)} (openguildkit tools status).")
    if args.mock:
        print(f"Connected mocks: {connected}. Tools without a mock: {missing}.")
    else:
        print(f"Connected servers: {connected}. Tools not connected: {missing}.")
    return exit_code
