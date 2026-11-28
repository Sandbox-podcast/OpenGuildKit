"""The `openguildkit features` commands: list the features, turn an option on or off, with who and why.

Turning an option on or off changes the profile's tools by the profile commands' path (profile_cli), so the change
is recorded with who, when and why, and the instructions follow. Connecting the tool's MCP server stays with
tools plan and tools apply.
"""

import json
from pathlib import Path

from . import profile_cli
from .cli_surface import add_by
from .features import feature_options, features_view, load_features, profile_names
from .project import load_profile
from .tools import CLAUDE_MCP_FILE, CODEX_CONFIG_FILE, connection_status, load_tools, resolve_tool
from .wording import plural


def add_parser(commands) -> None:
    features = commands.add_parser(
        "features", help="Turn features on or off: a tool the team works with, or one of its three best-known "
                         "alternatives; tools plan and tools apply then connect its MCP server.")
    actions = features.add_subparsers(dest="features_action", required=True)
    listing = actions.add_parser("list", help="List the features, their options and which are on.")
    listing.add_argument("--json", action="store_true", help="Print the features as JSON.")
    for name, text in (("enable", "Turn options on: each tool is added to the profile's tools."),
                       ("disable", "Turn options off: each tool leaves the profile's tools.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("names", nargs="+", metavar="NAME", help="A feature ID (its lead tool) or a tool of it.")
        add_by(command, required=True)
        command.add_argument("--reason", required=True, help="Why, in one line; recorded in the profile history "
                                                                 "(.openguildkit/project.json).")


def _print(view: list[dict]) -> None:
    for feature in view:
        print(f"{feature['id']}: {feature['purpose']}")
        for position, option in enumerate(feature["options"]):
            mark = "on " if option["enabled"] else "off"
            role = "lead" if position == 0 else "alternative"
            servers = f"{plural(option['servers'], 'MCP server')}" if option["servers"] else "no MCP server on record"
            print(f"  [{mark}] {option['tool']}: {option['title']} ({role}, {servers})")
    print("Turn one on: openguildkit features enable ID --by INITIALS --reason WHY. Then openguildkit tools plan ID.")


def _targets(names: list[str], features: list[dict], tools: dict) -> list[str]:
    """The tool IDs the names turn on or off. A tool outside the features goes through profile add tool."""
    options = feature_options(features)
    targets: list[str] = []
    for name in names:
        key = name.strip().casefold()
        found = options[key] if key in options else options.get(resolve_tool(name.strip(), tools))
        if not found:
            raise ValueError(f"{name} is not an option of a feature. Run openguildkit features list, or add any tool "
                             "of the registry with openguildkit profile add tool.")
        targets.extend(tool for tool in found if tool not in targets)
    return targets


def _edit(args, features: list[dict], tools: dict):
    enable = args.features_action == "enable"

    def edit(profile: dict, catalog: dict) -> tuple[dict, str]:
        names = list(profile.get("tools", []))
        for tool_id in _targets(args.names, features, tools):
            present = profile_names(profile, tool_id, tools)
            if enable and present or not enable and not present:
                state = "already on" if enable else "not on"
                raise ValueError(f"{tool_id} is {state}. Nothing was written.")
            uses = [feature["id"] for feature in features
                    if any(option["tool"] == tool_id for option in feature["options"])]
            if not enable and len(uses) > 1:
                raise ValueError(
                    f"{tools[tool_id]['title']} serves several features: {', '.join(uses)}. "
                    "Nothing was written. Use profile remove tool to remove it from the whole profile.")
            names = [*names, tools[tool_id]["title"]] if enable else [name for name in names if name not in present]
        return {**profile, "tools": names}, f"features {args.features_action} {', '.join(args.names)}"
    return edit


def _refuse(change: str, weakened: list, voided: list) -> None:
    raise ValueError(f"'{change}' would weaken a protection; turning a feature on or off never should. "
                     "Nothing was written.")


def _print_connect(targets: list[str], tools: dict) -> None:
    """After features enable: the tools plan command for the tools with an MCP server on record, and which have none."""
    served = [tool for tool in targets if tools[tool]["servers"]]
    if served:
        print(f"To connect the MCP servers: openguildkit tools plan {' '.join(served)}, then tools apply once the "
              "team accepts the plan.")
    unserved = [tool for tool in targets if not tools[tool]["servers"]]
    if unserved:
        print(f"{', '.join(unserved)}: no MCP server on record, so there is nothing to connect.")


def _print_still_connected(root: Path, state: Path, targets: list[str], tools: dict, project_host: str | None) -> None:
    """After features disable: each connection tools apply wrote that still gives the agent a tool turned off, with
    the command that removes it. Turning a feature off leaves the host files as they are."""
    for item in connection_status(root, state):
        present = "reason" not in item and (item["configured"] or item["changed"])
        if not present or not set(item["covers"]) & set(targets):
            continue
        file = CLAUDE_MCP_FILE if item["host"] == "claude-code" else CODEX_CONFIG_FILE.as_posix()
        titles = " and ".join(tools[tool]["title"] if tool in tools else tool for tool in item["covers"])
        host = "" if item["host"] == project_host else f" --host {item['host']}"
        print(f"The MCP server {item['key']} stays connected ({item['host']}, {item['mode']}, {file}): the agent keeps "
              f"access to {titles}. To remove the connection: openguildkit tools remove {item['key']}{host}.")


def run(args, root: Path, state: Path, catalog: dict) -> int:
    tools = load_tools(state / "catalog" / "tools")
    features = load_features(tools)
    if args.features_action == "list":
        view = features_view(features, tools, load_profile(state, catalog))
        if args.json:
            print(json.dumps(view, indent=2, ensure_ascii=False))
        else:
            _print(view)
        return 0
    targets = _targets(args.names, features, tools)
    updated, record, catalog = profile_cli.write_change(root, state, args, _edit(args, features, tools),
                                                  args.by.strip(), args.reason.strip(), _refuse)
    profile_cli.report_change(state, updated, record, catalog, False)
    if args.features_action == "enable":
        _print_connect(targets, tools)
    else:
        _print_still_connected(root, state, targets, tools, updated.get("host"))
    return 0
