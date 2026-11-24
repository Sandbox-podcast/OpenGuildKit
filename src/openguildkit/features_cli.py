"""The `openguildkit features` commands: list the features, turn an option on or off, with who and why.

Turning an option on or off changes the profile's tools by the profile commands' path (profile_cli), so the change
is recorded with who, when and why, and the instructions follow. Connecting the tool's MCP server stays with
tools plan and tools apply.
"""

import json
from pathlib import Path

from . import profile_cli
from .features import feature_options, features_view, load_features, profile_names
from .project import load_profile
from .tools import load_tools, resolve_tool


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
        command.add_argument("--by", required=True, help="The person who decides the change.")
        command.add_argument("--reason", required=True, help="Why, in one line; shown in AGENTS.md and preview.")


def _print(view: list[dict]) -> None:
    for feature in view:
        print(f"{feature['id']}: {feature['purpose']}")
        for position, option in enumerate(feature["options"]):
            mark = "on " if option["enabled"] else "off"
            role = "lead" if position == 0 else "alternative"
            servers = f"{option['servers']} MCP server(s)" if option["servers"] else "no MCP server on record"
            print(f"  [{mark}] {option['tool']}: {option['title']} ({role}, {servers})")
    print("Turn one on: openguildkit features enable ID --by NAME --reason WHY. Then openguildkit tools plan ID.")


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
        print(f"To connect the MCP servers: openguildkit tools plan {' '.join(targets)}, then tools apply once the "
              "team accepts the plan.")
    return 0
