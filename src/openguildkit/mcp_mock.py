"""A stand-in MCP server for demos and tests: synthetic answers, no network, no credentials.

`openguildkit tools mock ID` speaks the Model Context Protocol over stdio (JSON-RPC 2.0, one
message per line). It serves the tools and canned answers of a mock file, so a host agent
can be connected to "Jira" or "Snyk" without an account. The mock's tool names are
OpenGuildKit's own: it rehearses the agent's flow, it does not imitate a vendor's API.
"""

import json
import sys
from pathlib import Path

# Revisions up to 2025-11-25 open with an initialize handshake. From 2026-07-28 every request
# names its protocol version in params._meta and the server keeps no connection state.
LEGACY_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
MODERN_VERSIONS = ("2026-07-28",)
META_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_SERVER = "io.modelcontextprotocol/serverInfo"
SERVER_VERSION = "1"
LIST_TTL_MS = 300_000
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
UNSUPPORTED_VERSION = -32022
_JSON_TYPES = {
    "string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list,
}
MAX_LINE_BYTES = 1_000_000


class MockError(Exception):
    """A JSON-RPC protocol error."""

    def __init__(self, code: int, message: str, data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data


def validate_mock(mock: object, tool_id: str) -> dict:
    """Check a mock file: the tools it serves and the answers it gives."""
    if not isinstance(mock, dict) or not {"tool", "tools"} <= mock.keys() <= {"tool", "tools", "instructions"}:
        raise ValueError(f"Mock {tool_id} needs tool and tools, and can add instructions.")
    if mock["tool"] != tool_id:
        raise ValueError(f"Mock {tool_id} must name its tool: {tool_id}.")
    if not isinstance(mock["tools"], list) or not mock["tools"]:
        raise ValueError(f"Mock {tool_id} must serve at least one tool.")
    names = set()
    for tool in mock["tools"]:
        allowed = {"name", "description", "inputSchema", "responses", "read_only"}
        if not isinstance(tool, dict) or not {"name", "description", "inputSchema", "responses"} <= tool.keys() <= allowed:
            raise ValueError(f"Mock {tool_id}: each tool needs name, description, inputSchema and responses.")
        name = tool["name"]
        if not isinstance(name, str) or not name.replace("_", "").isalnum() or name in names:
            raise ValueError(f"Mock {tool_id}: tool names are unique words with underscores: {name!r}.")
        names.add(name)
        if "read_only" in tool and not isinstance(tool["read_only"], bool):
            raise ValueError(f"Mock {tool_id}/{name}: read_only must be true or false.")
        schema = tool["inputSchema"]
        if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties", {}), dict):
            raise ValueError(f"Mock {tool_id}/{name}: inputSchema is a JSON Schema object with properties.")
        if not set(schema.get("required", [])) <= schema.get("properties", {}).keys():
            raise ValueError(f"Mock {tool_id}/{name}: required names a property that is not declared.")
        responses = tool["responses"]
        if not isinstance(responses, list) or not responses:
            raise ValueError(f"Mock {tool_id}/{name}: give at least one response.")
        for response in responses:
            if not isinstance(response, dict) or not response.keys() <= {"when", "result", "error"} \
                    or ("result" in response) == ("error" in response):
                raise ValueError(f"Mock {tool_id}/{name}: a response has an optional when, and either result or error.")
            if not isinstance(response.get("when", {}), dict):
                raise ValueError(f"Mock {tool_id}/{name}: when is an object of argument values.")
        if "when" in responses[-1]:
            raise ValueError(f"Mock {tool_id}/{name}: the last response is the default and has no when.")
    return mock


def _matches(when: dict, arguments: dict) -> bool:
    for key, expected in when.items():
        actual = arguments.get(key)
        if isinstance(expected, str) and isinstance(actual, str):
            if expected.casefold() not in actual.casefold():
                return False
        elif actual != expected:
            return False
    return True


def _fill(value, arguments: dict):
    """Replace "$arg:NAME" strings with the caller's argument, so a created record echoes its input."""
    if isinstance(value, str) and value.startswith("$arg:"):
        return arguments.get(value[5:])
    if isinstance(value, dict):
        return {key: _fill(item, arguments) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, arguments) for item in value]
    return value


def _argument_problem(schema: dict, arguments: dict) -> str | None:
    properties = schema.get("properties", {})
    for name in schema.get("required", []):
        if name not in arguments:
            return f"Missing argument: {name}."
    for name, value in arguments.items():
        if name not in properties:
            return f"Unknown argument: {name}. Known: {', '.join(properties) or 'none'}."
        expected = _JSON_TYPES.get(properties[name].get("type"))
        if expected and (not isinstance(value, expected) or (isinstance(value, bool) and expected is not bool)):
            return f"Argument {name} must be a {properties[name]['type']}."
        choices = properties[name].get("enum")
        if choices and value not in choices:
            return f"Argument {name} must be one of: {', '.join(map(str, choices))}."
    return None


def call_tool(mock: dict, name: str, arguments: object) -> dict:
    """Answer one tools/call: the first response whose `when` matches, or a tool error the agent can read."""
    tool = next((item for item in mock["tools"] if item["name"] == name), None)
    if tool is None:
        raise MockError(INVALID_PARAMS, f"Unknown tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise MockError(INVALID_PARAMS, "arguments must be an object")
    problem = _argument_problem(tool["inputSchema"], arguments)
    if problem:
        return {"content": [{"type": "text", "text": problem}], "isError": True}
    response = next(item for item in tool["responses"] if _matches(item.get("when", {}), arguments))
    if "error" in response:
        return {"content": [{"type": "text", "text": str(response["error"])}], "isError": True}
    result = _fill(response["result"], arguments)
    answer = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}
    if isinstance(result, dict):
        answer["structuredContent"] = result
    return answer


def _server_info(mock: dict) -> dict:
    return {"name": f"openguildkit-mock-{mock['tool']}", "version": SERVER_VERSION}


def _instructions(mock: dict) -> str:
    return mock.get("instructions") or "Mock server: every answer is synthetic data for a demo or a test."


def _tool_list(mock: dict) -> list[dict]:
    return [
        {"name": tool["name"], "description": tool["description"], "inputSchema": tool["inputSchema"],
         "annotations": {"readOnlyHint": bool(tool.get("read_only", False))}}
        for tool in mock["tools"]
    ]


def _modern(mock: dict, method: str, params: dict, meta: dict) -> dict:
    """Stateless requests of the 2026-07-28 revision: the version travels with each request."""
    requested = meta[META_VERSION]
    if requested not in MODERN_VERSIONS:
        raise MockError(UNSUPPORTED_VERSION, "Unsupported protocol version",
                        {"supported": list(MODERN_VERSIONS + LEGACY_VERSIONS[::-1]), "requested": requested})
    if not isinstance(meta.get(META_CAPABILITIES), dict):
        raise MockError(INVALID_PARAMS, f"params._meta needs {META_CAPABILITIES}")
    if method == "server/discover":
        return {
            "resultType": "complete", "supportedVersions": list(MODERN_VERSIONS), "capabilities": {"tools": {}},
            "instructions": _instructions(mock), "ttlMs": LIST_TTL_MS, "cacheScope": "public",
            "_meta": {META_SERVER: _server_info(mock)},
        }
    if method == "tools/list":
        return {"resultType": "complete", "tools": _tool_list(mock), "ttlMs": LIST_TTL_MS, "cacheScope": "public"}
    if method == "tools/call":
        if not isinstance(params.get("name"), str):
            raise MockError(INVALID_PARAMS, "tools/call needs the tool name")
        return {"resultType": "complete", **call_tool(mock, params["name"], params.get("arguments"))}
    raise MockError(METHOD_NOT_FOUND, f"Method not found: {method}")


def _legacy(mock: dict, method: str, params: dict) -> dict:
    """Requests of the revisions that open with initialize."""
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested if requested in LEGACY_VERSIONS else LEGACY_VERSIONS[-1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": _server_info(mock),
            "instructions": _instructions(mock),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _tool_list(mock)}
    if method == "tools/call":
        if not isinstance(params.get("name"), str):
            raise MockError(INVALID_PARAMS, "tools/call needs the tool name")
        return call_tool(mock, params["name"], params.get("arguments"))
    if method == "server/discover":
        raise MockError(INVALID_PARAMS, f"server/discover needs params._meta with {META_VERSION}")
    raise MockError(METHOD_NOT_FOUND, f"Method not found: {method}")


def handle(mock: dict, message: object) -> dict | None:
    """Answer one JSON-RPC message, in the era the request opens with. Notifications get no answer."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        identifier = message.get("id") if isinstance(message, dict) else None
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": INVALID_REQUEST, "message": "Invalid request"}}
    if "id" not in message:
        return None
    identifier, method, params = message["id"], message["method"], message.get("params") or {}
    try:
        if not isinstance(params, dict):
            raise MockError(INVALID_PARAMS, "params must be an object")
        meta = params.get("_meta")
        if method != "initialize" and isinstance(meta, dict) and META_VERSION in meta:
            result = _modern(mock, method, params, meta)
        else:
            result = _legacy(mock, method, params)
    except MockError as error:
        failure = {"code": error.code, "message": str(error)}
        if error.data is not None:
            failure["data"] = error.data
        return {"jsonrpc": "2.0", "id": identifier, "error": failure}
    return {"jsonrpc": "2.0", "id": identifier, "result": result}


def serve(mock: dict, stdin=None, stdout=None, log: Path | None = None) -> int:
    """Serve the mock over stdio until the client closes the stream."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    journal = log.open("a", encoding="utf-8") if log else None
    try:
        for line in stdin:
            if not line.strip():
                continue
            if len(line) > MAX_LINE_BYTES:
                answer = {"jsonrpc": "2.0", "id": None, "error": {"code": INVALID_REQUEST, "message": "Message too long"}}
            else:
                try:
                    message = json.loads(line.decode("utf-8"))
                except (ValueError, RecursionError):
                    message, answer = None, {"jsonrpc": "2.0", "id": None,
                                             "error": {"code": PARSE_ERROR, "message": "Parse error"}}
                else:
                    answer = handle(mock, message)
                    if journal and isinstance(message, dict) and message.get("method") == "tools/call":
                        params = message.get("params") if isinstance(message.get("params"), dict) else {}
                        journal.write(json.dumps({"tool": mock["tool"], "call": params.get("name"),
                                                  "arguments": params.get("arguments")}, ensure_ascii=False) + "\n")
                        journal.flush()
            if answer is not None:
                stdout.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()
    finally:
        if journal:
            journal.close()
    return 0
