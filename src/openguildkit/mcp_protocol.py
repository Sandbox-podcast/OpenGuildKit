"""Shared stdio transport, handshake and tool dispatch for local MCP servers.

Entry: ProtocolError, ToolServer, handle, serve
Tests: tests/e2e/test_tool_mocks.py, tests/test_project_mcp.py
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import BinaryIO

# Revisions up to 2025-11-25 open with an initialize handshake. From 2026-07-28 every request
# names its protocol version in params._meta and the server keeps no connection state.
LEGACY_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MODERN_VERSIONS = ("2026-07-28",)
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER = "io.modelcontextprotocol/serverInfo"
LIST_TTL_MS = 300_000
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
UNSUPPORTED_VERSION = -32022
MAX_LINE_BYTES = 1_000_000


class ProtocolError(Exception):
    """A JSON-RPC protocol error."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data


@dataclass(frozen=True)
class ToolServer:
    """A fixed set of tools and the handler for their calls."""

    info: dict[str, str]
    instructions: str
    tools: list[dict]
    call: Callable[[str, object], dict]


def _modern(server: ToolServer, method: str, params: dict, meta: dict) -> dict:
    """Stateless requests of the 2026-07-28 revision: the version travels with each request."""
    requested = meta[META_VERSION]
    if requested not in MODERN_VERSIONS:
        raise ProtocolError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                        {"supported": list(MODERN_VERSIONS + LEGACY_VERSIONS[::-1]), "requested": requested})
    if not isinstance(meta.get(META_CAPABILITIES), dict):
        raise ProtocolError(INVALID_PARAMS, f"params._meta needs {META_CAPABILITIES}")
    if method == "server/discover":
        return {
            "resultType": "complete", "supportedVersions": list(MODERN_VERSIONS), "capabilities": {"tools": {}},
            "instructions": server.instructions, "ttlMs": LIST_TTL_MS, "cacheScope": "public",
            "_meta": {META_SERVER: server.info},
        }
    if method == "tools/list":
        return {"resultType": "complete", "tools": server.tools, "ttlMs": LIST_TTL_MS, "cacheScope": "public"}
    if method == "tools/call":
        if not isinstance(params.get("name"), str):
            raise ProtocolError(INVALID_PARAMS, "tools/call needs the tool name")
        return {"resultType": "complete", **server.call(params["name"], params.get("arguments"))}
    raise ProtocolError(METHOD_NOT_FOUND, f"Method not found: {method}")


def _legacy(server: ToolServer, method: str, params: dict) -> dict:
    """Requests of the revisions that open with initialize."""
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[-1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": server.info,
            "instructions": server.instructions,
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": server.tools}
    if method == "tools/call":
        if not isinstance(params.get("name"), str):
            raise ProtocolError(INVALID_PARAMS, "tools/call needs the tool name")
        return server.call(params["name"], params.get("arguments"))
    if method == "server/discover":
        raise ProtocolError(INVALID_PARAMS, f"server/discover needs params._meta with {META_VERSION}")
    raise ProtocolError(METHOD_NOT_FOUND, f"Method not found: {method}")


def handle(server: ToolServer, message: object) -> dict | None:
    """Answer one JSON-RPC message, in the era the request opens with. Notifications get no answer."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        identifier = message.get("id") if isinstance(message, dict) else None
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": INVALID_REQUEST, "message": "Invalid request"}}
    if "id" not in message:
        return None
    identifier, method, params = message["id"], message["method"], message.get("params") or {}
    try:
        if not isinstance(params, dict):
            raise ProtocolError(INVALID_PARAMS, "params must be an object")
        meta = params.get("_meta")
        if method != "initialize" and isinstance(meta, dict) and META_VERSION in meta:
            result = _modern(server, method, params, meta)
        else:
            result = _legacy(server, method, params)
    except ProtocolError as error:
        failure = {"code": error.code, "message": str(error)}
        if error.data is not None:
            failure["data"] = error.data
        return {"jsonrpc": "2.0", "id": identifier, "error": failure}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def serve(
    server: ToolServer,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
    on_message: Callable[[object], None] | None = None,
) -> int:
    """Serve UTF-8 JSON-RPC over stdio until the client closes its input."""
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    for line in stdin:
        if not line.strip():
            continue
        if len(line) > MAX_LINE_BYTES:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Message too long"}}
        else:
            try:
                message = json.loads(line.decode("utf-8"))
            except (ValueError, RecursionError):
                answer = {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Parse error"}}
            else:
                answer = handle(server, message)
                if on_message:
                    on_message(message)
        if answer is not None:
            stdout.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
    return 0
