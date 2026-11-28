"""The features: a purpose, its lead tool and three alternatives from the tool registry, and which are on.

A feature is a purpose (issue tracking, payroll, container registry) with a lead tool and three alternatives, all
tools of the registry. Turning an option on adds the tool to the profile's tools, by the profile commands' own path,
so tools recommend, plan and apply then connect its MCP server. Nothing else records whether a feature is on: an
option is on when a name in the profile's tools resolves to its tool.

Entry: load_features, feature_options, enabled_tools, features_view, profile_names
Tests: tests/test_features.py
"""

import re

from .catalog import CatalogError, package_file, unique_fields
from .storage import load_json
from .tools import match_tools

ALTERNATIVES = 3
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _option(entry: object, label: str, tools: dict) -> dict:
    if not isinstance(entry, dict) or not {"tool"} <= entry.keys() <= {"tool", "as"}:
        raise CatalogError(f"{label}: an option is a tool ID, with an optional label (as)")
    if entry["tool"] not in tools:
        raise CatalogError(f"{label}: {entry['tool']} is not a tool of the registry")
    if "as" in entry and (not isinstance(entry["as"], str) or not entry["as"].strip() or "\n" in entry["as"]):
        raise CatalogError(f"{label}: as is one line of text")
    return {"tool": entry["tool"], "title": entry.get("as") or tools[entry["tool"]]["title"]}


def _feature(record: object, tools: dict) -> dict:
    if not isinstance(record, dict) or record.keys() != {"id", "purpose", "lead", "alternatives"}:
        raise CatalogError("a feature has id, purpose, lead and alternatives")
    label = f"feature {record['id']}"
    if not isinstance(record["id"], str) or not _ID.fullmatch(record["id"]):
        raise CatalogError(f"{label}: use a lowercase id with hyphens")
    alternatives = record["alternatives"]
    if not isinstance(alternatives, list) or len(alternatives) != ALTERNATIVES:
        raise CatalogError(f"{label}: name exactly {ALTERNATIVES} alternatives")
    options = [_option(record["lead"], label, tools), *(_option(entry, label, tools) for entry in alternatives)]
    if len({option["tool"] for option in options}) != len(options):
        raise CatalogError(f"{label}: the lead and its alternatives are different tools")
    return {"id": record["id"], "purpose": record["purpose"], "options": options}


def load_features(tools: dict) -> list[dict]:
    """The features shipped with OpenGuildKit, each option checked against the tool registry."""
    path = package_file("registry", "features", "features.json")
    record = load_json(path, pairs=unique_fields)
    features = [_feature(entry, tools) for entry in record["features"]]
    ids = [feature["id"] for feature in features]
    if len(set(ids)) != len(ids):
        raise CatalogError("a feature ID is listed twice")
    return features


def feature_options(features: list[dict]) -> dict[str, list[str]]:
    """The tools a feature ID or a tool ID turns on: a feature ID names its lead."""
    options = {feature["id"]: [feature["options"][0]["tool"]] for feature in features}
    for feature in features:
        for option in feature["options"]:
            options.setdefault(option["tool"], [option["tool"]])
    return options


def enabled_tools(profile: dict, tools: dict) -> set[str]:
    """The registry tools the profile names, whatever words the team used."""
    return set(match_tools(list(profile.get("tools", [])), tools)[0])


def features_view(features: list[dict], tools: dict, profile: dict) -> list[dict]:
    """Each feature with its options: whether the profile turns it on and how many MCP servers are on record."""
    enabled = enabled_tools(profile, tools)
    return [{**feature, "enabled": any(option["tool"] in enabled for option in feature["options"]),
             "options": [{**option, "enabled": option["tool"] in enabled, "servers": len(tools[option["tool"]]["servers"]),
                          "vendor": tools[option["tool"]]["vendor"],
                          "tool_title": tools[option["tool"]]["title"]} for option in feature["options"]]}
            for feature in features]


def profile_names(profile: dict, tool_id: str, tools: dict) -> list[str]:
    """The names in the profile's tools that resolve to this tool: turning it off removes each of them."""
    return [name for name in profile.get("tools", []) if match_tools([name], tools)[0] == [tool_id]]
