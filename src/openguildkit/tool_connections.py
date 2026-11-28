"""Writes the MCP servers a person accepted into each host's configuration, removes them, and reports which are connected.

Entry: read_manifest, check_settings, apply_connections, remove_connections, connection_status, connected_tools, HOSTS,
CLAUDE_MCP_FILE, CODEX_CONFIG_FILE
Tests: tests/test_catalog_format_doc.py, tests/test_catalog_sources.py, tests/test_check_links.py,
tests/test_features.py, tests/test_new_brains.py, tests/test_source_dates.py, tests/test_tool_registry.py,
tests/test_tools.py
"""

import json
import os
import tomllib
from pathlib import Path

from .errors import OgkError
from .storage import NestedTooDeeply, load_json, read_json, write_json, write_text

HOSTS = ("claude-code", "codex")


MANIFEST = "tools.json"


UNCONNECTED = "unconnected"


CLAUDE_MCP_FILE = ".mcp.json"


CODEX_CONFIG_FILE = Path(".codex") / "config.toml"


CODEX_BLOCK_START = "# >>> OpenGuildKit tools (openguildkit tools apply rewrites this block)\n"


CODEX_BLOCK_END = "# <<< OpenGuildKit tools\n"


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


def _mcp_file(path: Path) -> dict:
    """The JSON object of Claude Code's .mcp.json, with an mcpServers object (empty when the file is missing); refused
    with the file's name when it is not valid JSON or not such an object."""
    try:
        data = load_json(path) if path.is_file() else {}
    except ValueError as error:
        raise OgkError("OGK-TOOLS-001", f"{path.as_posix()} is not valid JSON: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.setdefault("mcpServers", {}), dict):
        raise ValueError(f"{path.as_posix()} must hold a JSON object with mcpServers.")
    return data


def _write_host(root: Path, host: str, connections: list[dict], removed: set[str]) -> tuple[str, list[str]]:
    """Write the managed entries to the host's file. Entries the person wrote under the same name are kept."""
    managed = {item["key"]: item["entry"] for item in connections if item["host"] == host}
    kept = []
    if host == "claude-code":
        path = root / CLAUDE_MCP_FILE
        data = _mcp_file(path)
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
        raise OgkError("OGK-TOOLS-002", f"{path} already defines mcp_servers.{clash[0]} outside the OpenGuildKit block. Rename or remove it first.")
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
        raise OgkError("OGK-TOOLS-003", "Settings are missing. " + "; ".join(blocked) + ".")


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
            existing = _mcp_file(path)["mcpServers"]
            for item in accepted:
                if item["key"] in existing and (host, item["key"]) not in connections and existing[item["key"]] != item["entry"]:
                    raise OgkError("OGK-TOOLS-004", f"{path} already defines {item['key']} with other settings. Rename or remove it first.")
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
        try:
            return _mcp_file(path)["mcpServers"]
        except ValueError as error:
            if isinstance(error.__cause__, NestedTooDeeply):
                raise OgkError("OGK-TOOLS-005", f"{path.as_posix()}: {error.__cause__}") from error
            return {}
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
