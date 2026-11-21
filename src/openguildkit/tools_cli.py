"""The `openguildkit tools` commands: browse the tool registry, connect a project's tools, rehearse with mocks."""

import json
import sys
from pathlib import Path

from .mcp_mock import MockError, call_tool, serve
from .storage import project_lock
from .tools import (
    CATEGORIES, HOSTS, apply_connections, check_tool_links, choose_server, connection_status, load_mock, load_tools,
    mock_ids, plan_connections, recommend_tools, remove_connections,
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
        command.add_argument("--json", action="store_true", help="Print the plan as JSON.")
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
            parsed.setdefault(tool, {})[name] = right
        else:
            parsed[left] = right
    return parsed


def _host(args, profile: dict) -> str:
    host = args.host or profile.get("host")
    if host not in HOSTS:
        raise ValueError(f"Name the agent host with --host ({', '.join(HOSTS)}): the project's host is {host or 'not set'}.")
    return host


def _print_plan(plan: list[dict], host: str) -> None:
    for item in plan:
        if "skipped" in item:
            print(f"{item['title']}: skipped. {item['skipped']}")
            continue
        covers = ", ".join(item.get("covers", [item["tool"]]))
        if item["mode"] == "mock":
            print(f"{item['title']}: mock server `{item['key']}` (synthetic data).")
        else:
            print(f"{covers}: server `{item['key']}` ({item['publisher']}, {item['transport']}, status {item['status']}).")
            print(f"    Verified {item['verified']} on {item['source']}")
        for warning in item["warnings"]:
            print(f"    Warning: {warning}")
        for step in item["steps"]:
            print(f"    {step}")
        print(f"    {host}: {json.dumps(item['entry'], ensure_ascii=False)}")


def run(args, root: Path, state: Path, catalog: dict, load_profile) -> int:
    action = args.tools_action
    mock_dir = state / "catalog" / "tool-mocks"
    if action == "mock":
        return serve(load_mock(args.id, mock_dir), log=args.log)
    if action == "call":
        mock = load_mock(args.id, mock_dir)
        if args.name is None:
            for tool in mock["tools"]:
                access = "read" if tool.get("read_only") else "write"
                print(f"{tool['name']:<28} [{access}] {tool['description']}")
            return 0
        try:
            arguments = json.loads(args.args)
        except ValueError as error:
            raise ValueError(f"--args is not valid JSON: {error}") from error
        try:
            answer = call_tool(mock, args.name, arguments)
        except MockError as error:
            raise ValueError(f"{error}. Run openguildkit tools call {args.id} to list the tools.") from error
        tool = next(item for item in mock["tools"] if item["name"] == args.name)
        if not tool.get("read_only"):
            print("Warning: this operation simulates a write. Use openguildkit task authorize before a real write.",
                  file=sys.stderr)
        print(answer["content"][0]["text"])
        return 1 if answer["isError"] else 0
    tools = load_tools(state / "catalog" / "tools")
    check_tool_links(tools, catalog["boards"])
    mocks = mock_ids(mock_dir)
    if action == "list":
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
    if action == "show":
        if args.id not in tools:
            raise ValueError(f"Unknown tool: {args.id}. Run openguildkit tools list.")
        tool = tools[args.id]
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
    profile = load_profile(state, catalog)
    if action == "recommend":
        result = recommend_tools(profile, root, tools)
        configured = {}
        for connection in connection_status(root, state):
            if connection["configured"]:
                for tool in connection["covers"]:
                    configured.setdefault(tool, []).append({"host": connection["host"], "mode": connection["mode"]})
        for item in result["tools"]:
            item["mock"] = item["id"] in mocks
            item["connections"] = configured.get(item["id"], [])
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
        for name in result["unknown"]:
            print(f"{name}: not in the registry. Add it in .openguildkit/catalog/tools/ or connect it yourself.")
        if not result["tools"] and not result["unknown"]:
            print("No tool named in the profile and none detected. List them under tools in .openguildkit/project.json.")
        elif pending := [item["id"] for item in result["tools"] if not item["connections"]]:
            print("Next: openguildkit tools plan " + " ".join(pending))
        return 0
    if action == "status":
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
    host = _host(args, profile)
    if action == "remove":
        with project_lock(state):
            result = remove_connections(root, state, host, args.tool)
        if result["removed"]:
            print(f"Removed {', '.join(result['removed'])} from {result['file']}.")
        if result.get("forgotten"):
            print(f"Cleared unavailable mock requests for {', '.join(result['forgotten'])}.")
        return 0
    plan = plan_connections(
        tools, args.tool, host, mock=args.mock, community=args.community,
        settings=_pairs(args.settings, ".", "--set TOOL.NAME=VALUE"),
        token_env=_pairs(args.token_env, "", "--token-env TOOL=VARIABLE"), mocks=mocks, log=args.log,
    )
    if action == "plan":
        if args.json:
            print(json.dumps(plan, indent=2, ensure_ascii=False))
        else:
            _print_plan(plan, host)
            print("Nothing is written. Review the plan with the team, then run the same command with apply.", file=sys.stderr)
        return 0
    with project_lock(state):
        result = apply_connections(root, state, host, plan)
    exit_code = 1 if args.mock and result["skipped"] else 0
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return exit_code
    _print_plan([item for item in plan if "skipped" not in item], host)
    if not args.mock:
        for item in result["skipped"]:
            print(f"{item['tool']}: skipped. {item['reason']}")
    if result["applied"]:
        print(f"Wrote {', '.join(result['applied'])} to {result['file']} and recorded them in .openguildkit/tools.json.")
    elif not args.mock:
        print("Nothing to write.")
    if args.mock:
        connected = ", ".join(result["applied"]) or "none"
        missing = ", ".join(item["tool"] for item in result["skipped"]) or "none"
        print(f"Connected mocks: {connected}. Tools without a mock: {missing}.")
    return exit_code
