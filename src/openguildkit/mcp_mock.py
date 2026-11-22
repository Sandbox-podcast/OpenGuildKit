"""A stand-in MCP server for demos and tests: synthetic answers, no network, no credentials.

`openguildkit tools mock ID` speaks the Model Context Protocol over stdio (JSON-RPC 2.0, one
message per line). It serves the records and canned answers of a mock file, so a host agent
can be connected to "Jira" or "Snyk" without an account. List and get tools read the same
records, so an id one call returns is accepted by the others; a project can swap in its own
records with a scenario file. The mock's tool names are
OpenGuildKit's own: it rehearses the agent's flow, it does not imitate a vendor's API.
"""

import copy
import hashlib
import json
import re
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


_SERVE_ACTIONS = ("list", "get")
_MAX_LISTED = 12
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
_RESERVED_DOMAINS = (".test", ".example", ".invalid", ".localhost", "example.com", "example.net", "example.org")


def _validate_records(mock: dict, tool_id: str) -> None:
    """Collections of records: a key that get tools look up, an optional title, references to other collections."""
    records = mock.get("records", {})
    if not isinstance(records, dict):
        raise ValueError(f"Mock {tool_id}: records maps a collection name to its key and items.")
    for name, collection in records.items():
        label = f"Mock {tool_id}/records/{name}"
        if not isinstance(collection, dict) or "items" not in collection or not collection.keys() <= {"key", "title", "items", "refs"}:
            raise ValueError(f"{label}: a collection has items, and can add key, title and refs.")
        if not isinstance(collection["items"], list) or any(not isinstance(item, dict) for item in collection["items"]):
            raise ValueError(f"{label}: items is a list of objects.")
        for field in ("key", "title"):
            if field in collection and not isinstance(collection[field], str):
                raise ValueError(f"{label}: {field} names a field of the items.")
        if "key" in collection:
            values = [_norm(item.get(collection["key"])) for item in collection["items"]]
            if None in values or len(set(values)) != len(values):
                raise ValueError(f"{label}: every item needs a unique {collection['key']}.")
        refs = collection.get("refs", {})
        if not isinstance(refs, dict) or any(target not in records or "key" not in records[target] for target in refs.values()):
            raise ValueError(f"{label}: refs maps a field to a collection that has a key.")


def _validate_serving(mock: dict, tool: dict, label: str) -> None:
    records, properties = mock.get("records", {}), tool["inputSchema"].get("properties", {})
    if ("responses" in tool) == ("serve" in tool):
        raise ValueError(f"{label}: a tool has either responses or serve.")
    serve = tool.get("serve")
    if serve is not None:
        if not isinstance(serve, dict) or serve.get("action") not in _SERVE_ACTIONS or serve.get("records") not in records \
                or not serve.keys() <= {"records", "action", "argument", "fields", "filters", "total", "wrap"}:
            raise ValueError(f"{label}: serve names one of the records and an action ({', '.join(_SERVE_ACTIONS)}).")
        collection = records[serve["records"]]
        if serve["action"] == "get":
            if "key" not in collection or serve.get("argument", collection["key"]) not in properties:
                raise ValueError(f"{label}: a get tool reads the key of a collection from a declared argument.")
        elif not set(serve.get("filters", {})) <= properties.keys():
            raise ValueError(f"{label}: filters name declared arguments.")
    for argument, rule in tool.get("check", {}).items():
        rule = _check_rule(rule)
        target = rule.get("records")
        if argument not in properties or target not in records or "key" not in records[target] \
                or not rule.keys() <= {"records", "where", "at_most"} \
                or not set(rule.get("at_most", {})) <= properties.keys():
            raise ValueError(f"{label}: check maps a declared argument to a collection that has a key, "
                             "with optional where (field values) and at_most (argument: field).")
    if "example" in tool and not isinstance(tool["example"], dict):
        raise ValueError(f"{label}: example is an object of arguments.")


def validate_mock(mock: object, tool_id: str) -> dict:
    """Check a mock file: the records it holds, the tools it serves and the answers it gives."""
    if not isinstance(mock, dict) or not {"tool", "tools"} <= mock.keys() <= {"tool", "tools", "instructions", "records"}:
        raise ValueError(f"Mock {tool_id} needs tool and tools, and can add instructions and records.")
    if mock["tool"] != tool_id:
        raise ValueError(f"Mock {tool_id} must name its tool: {tool_id}.")
    if not isinstance(mock["tools"], list) or not mock["tools"]:
        raise ValueError(f"Mock {tool_id} must serve at least one tool.")
    _validate_records(mock, tool_id)
    names = set()
    for tool in mock["tools"]:
        allowed = {"name", "description", "inputSchema", "responses", "serve", "check", "example", "read_only"}
        if not isinstance(tool, dict) or not {"name", "description", "inputSchema"} <= tool.keys() <= allowed:
            raise ValueError(f"Mock {tool_id}: each tool needs name, description, inputSchema, and responses or serve.")
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
        _validate_serving(mock, tool, f"Mock {tool_id}/{name}")
        if "serve" in tool:
            continue
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
    problems = reference_problems(mock)
    if problems:
        raise ValueError(f"Mock {tool_id}: {problems[0]}")
    return mock


def _norm(value):
    """A key as compared: text whatever its case, numbers as numbers."""
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _values_at(item, path: list[str]) -> list:
    """The values found under a dotted path, through lists ("frames.node_id")."""
    if isinstance(item, list):
        return [value for element in item for value in _values_at(element, path)]
    if not path:
        return [item]
    if not isinstance(item, dict) or path[0] not in item:
        return []
    return _values_at(item[path[0]], path[1:])


def reference_problems(mock: dict) -> list[str]:
    """Ids that one record cites and the collection it points to does not hold."""
    records, problems = mock.get("records", {}), []
    for name, collection in records.items():
        for path, target in collection.get("refs", {}).items():
            known = {_norm(item.get(records[target]["key"])) for item in records[target]["items"]}
            for item in collection["items"]:
                for value in _values_at(item, path.split(".")):
                    if value is not None and _norm(value) not in known:
                        problems.append(f"{name} cites {path} {value}, which {target} does not hold.")
    return problems


def _check_rule(rule) -> dict:
    """A check is a collection name, or an object that also names the values the record must have."""
    return {"records": rule} if isinstance(rule, str) else rule if isinstance(rule, dict) else {}


def check_synthetic(data, label: str) -> None:
    """Refuse an email address outside the reserved test domains: mock data stays invented."""
    text = json.dumps(data, ensure_ascii=False)
    for match in _EMAIL.finditer(text):
        if not match.group(1).casefold().endswith(_RESERVED_DOMAINS):
            raise ValueError(f"{label}: {match.group(0)} is not a test address. Use a reserved domain such as example.test.")


def apply_scenario(mock: dict, collections: object, label: str) -> dict:
    """The mock with a project's own records in place of the bundled ones."""
    if not isinstance(collections, dict):
        raise ValueError(f"{label}: give the records of {mock['tool']} as an object of collections.")
    unknown = sorted(set(collections) - set(mock.get("records", {})))
    if unknown:
        known = ", ".join(mock.get("records", {})) or "none"
        raise ValueError(f"{label}: {mock['tool']} has no collection {unknown[0]}. Known: {known}.")
    check_synthetic(collections, label)
    records = {name: {**collection, "items": collections.get(name, collection["items"])}
               for name, collection in mock["records"].items()}
    instructions = (f"Mock of {mock['tool']} serving the project's own scenario. Every value is synthetic.")
    try:
        return validate_mock({**mock, "records": records, "instructions": instructions}, mock["tool"])
    except ValueError as error:
        raise ValueError(f"{label}: {error}") from error


def is_generic(mock: dict) -> bool:
    return not mock.get("instructions", "").startswith(f"Mock of {mock['tool']} serving the project's own scenario.")


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
    """Replace "$arg:NAME" with the caller's argument and "$id:PREFIX" with an id derived from the arguments."""
    if isinstance(value, str) and value.startswith("$arg:"):
        return arguments.get(value[5:])
    if isinstance(value, str) and value.startswith("$id:"):
        digest = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode("utf-8")).hexdigest()
        return value[4:] + digest[:8]
    if isinstance(value, dict):
        return {key: _fill(item, arguments) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, arguments) for item in value]
    return value


def signature(tool: dict) -> str:
    """The arguments of a mock tool in one line: name, type, required or not, admitted values."""
    schema = tool["inputSchema"]
    parts = []
    for name, spec in schema.get("properties", {}).items():
        kind = spec.get("type", "any") + (": " + "|".join(map(str, spec["enum"])) if spec.get("enum") else "")
        parts.append(f"{name} ({kind}, {'required' if name in schema.get('required', []) else 'optional'})")
    return ", ".join(parts) or "no argument"


def _argument_problem(tool: dict, arguments: dict) -> str | None:
    schema = tool["inputSchema"]
    properties = schema.get("properties", {})
    usage = f" {tool['name']} takes: {signature(tool)}."
    for name in schema.get("required", []):
        if name not in arguments:
            return f"Missing argument: {name}." + usage
    for name, value in arguments.items():
        if name not in properties:
            return f"Unknown argument: {name}." + usage
        expected = _JSON_TYPES.get(properties[name].get("type"))
        if expected and (not isinstance(value, expected) or (isinstance(value, bool) and expected is not bool)):
            kind = properties[name]["type"]
            return f"Argument {name} must be {'an' if kind[0] in 'aeiou' else 'a'} {kind}." + usage
        choices = properties[name].get("enum")
        if choices and value not in choices:
            return f"Argument {name} must be one of: {', '.join(map(str, choices))}."
        for bound, fails in (("minimum", lambda limit: value < limit), ("maximum", lambda limit: value > limit)):
            if bound in properties[name] and not isinstance(value, bool) and fails(properties[name][bound]):
                return f"Argument {name} must be at {bound[:3] == 'min' and 'least' or 'most'} {properties[name][bound]}."
    return None


def _flat_text(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flat_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flat_text(item) for item in value)
    return "" if value is None else str(value).casefold()


def _field_matches(actual, value, exact: bool) -> bool:
    if isinstance(value, str):
        if actual is None or isinstance(actual, (dict, list)):
            return False
        text = str(actual).casefold()
        return text == value.casefold() if exact else value.casefold() in text
    return _norm(actual) == _norm(value) if not isinstance(value, bool) else actual is value


def list_all_arguments(tool: dict) -> dict:
    """Arguments that make a list tool return every record: an empty text matches all."""
    properties = tool["inputSchema"].get("properties", {})
    arguments = {}
    for name in tool["inputSchema"].get("required", []):
        choices = properties[name].get("enum")
        arguments[name] = ("all" if "all" in choices else choices[0]) if choices else ""
    return arguments


def _known(values) -> str:
    listed = sorted({str(value) for value in values if value is not None and not isinstance(value, (dict, list))})
    return ", ".join(listed[:_MAX_LISTED]) + (", ..." if len(listed) > _MAX_LISTED else "")


def _hint(mock: dict, tool: dict, arguments: dict) -> str:
    serve, collection = tool["serve"], mock["records"][tool["serve"]["records"]]
    origin = "generic sample data, not your project's" if is_generic(mock) else "the project's scenario"
    parts = [f"Nothing matches. This mock serves {origin}; "
             f"{tool['name']} {json.dumps(list_all_arguments(tool))} lists every record."]
    for name in arguments:
        if name == "query":
            if "title" in collection:
                titles = [str(item.get(collection["title"])) for item in collection["items"][:3]]
                parts.append("Search words from: " + "; ".join(titles) + ".")
            continue
        field = serve.get("filters", {}).get(name, name)
        parts.append(f"Known {name} values: {_known(item.get(field) for item in collection['items']) or 'none'}.")
    return " ".join(parts)


def _serve_list(mock: dict, tool: dict, arguments: dict) -> dict:
    serve = tool["serve"]
    properties = tool["inputSchema"].get("properties", {})
    items = mock["records"][serve["records"]]["items"]
    for name, value in arguments.items():
        if value == "all" and "all" in properties[name].get("enum", []):
            continue
        field = serve.get("filters", {}).get(name, name)
        if field == "query":
            words = value.casefold().split() if isinstance(value, str) else [str(value)]
            items = [item for item in items if all(word in _flat_text(item) for word in words)]
        else:
            items = [item for item in items if _field_matches(item.get(field), value, "enum" in properties[name])]
    fields = serve.get("fields")
    rows = [{key: item[key] for key in fields if key in item} if fields else copy.deepcopy(item) for item in items]
    result = {**copy.deepcopy(serve.get("wrap", {})), serve["records"]: rows, "count": len(rows)}
    if "total" in serve:
        result[f"total_{serve['total']}"] = sum(item.get(serve["total"], 0) for item in items)
    if not rows:
        result["hint"] = _hint(mock, tool, arguments)
    return result


def _find(mock: dict, collection_name: str, value):
    collection = mock["records"][collection_name]
    return next((item for item in collection["items"] if _norm(item.get(collection["key"])) == _norm(value)), None)


def _not_found(mock: dict, collection_name: str, argument: str, value) -> str:
    collection = mock["records"][collection_name]
    known = _known(item.get(collection["key"]) for item in collection["items"])
    return f"{argument} {value} not found in this mock's {collection_name}. Known {argument} values: {known or 'none'}."


def _check_problem(mock: dict, rule: dict, argument: str, arguments: dict) -> str | None:
    """An id must name a record of its collection, in the state and within the amounts the rule asks."""
    record = _find(mock, rule["records"], arguments[argument])
    if record is None:
        return _not_found(mock, rule["records"], argument, arguments[argument])
    for field, expected in rule.get("where", {}).items():
        if record.get(field) != expected:
            return f"{argument} {arguments[argument]} has {field} {record.get(field)}; this call needs {field} {expected}."
    for name, field in rule.get("at_most", {}).items():
        if name in arguments and isinstance(record.get(field), (int, float)) and arguments[name] > record[field]:
            return f"{name} {arguments[name]} exceeds the {field} of {arguments[argument]}: {record[field]}."
    return None


WRITE_NOTE = ("Mock: nothing was changed anywhere. With the real server this call writes; a person authorizes it "
              "first (openguildkit task authorize).")


def call_tool(mock: dict, name: str, arguments: object) -> dict:
    """Answer one tools/call from the mock's records, or its first response whose `when` matches."""
    tool = next((item for item in mock["tools"] if item["name"] == name), None)
    if tool is None:
        raise MockError(INVALID_PARAMS, f"Unknown tool: {name}")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise MockError(INVALID_PARAMS, "arguments must be an object")
    problem = _argument_problem(tool, arguments)
    for argument, rule in tool.get("check", {}).items():
        if problem is None and argument in arguments:
            problem = _check_problem(mock, _check_rule(rule), argument, arguments)
    if problem:
        return {"content": [{"type": "text", "text": problem}], "isError": True}
    serve = tool.get("serve")
    if serve and serve["action"] == "get":
        argument = serve.get("argument", mock["records"][serve["records"]]["key"])
        record = _find(mock, serve["records"], arguments[argument])
        if record is None:
            return {"content": [{"type": "text", "text": _not_found(mock, serve["records"], argument, arguments[argument])}],
                    "isError": True}
        result = copy.deepcopy(record)
    elif serve:
        result = _serve_list(mock, tool, arguments)
    else:
        response = next(item for item in tool["responses"] if _matches(item.get("when", {}), arguments))
        if "error" in response:
            return {"content": [{"type": "text", "text": str(response["error"])}], "isError": True}
        result = _fill(response["result"], arguments)
    answer = {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}
    if not tool.get("read_only", False):
        answer["content"].append({"type": "text", "text": WRITE_NOTE})
    if isinstance(result, dict):
        answer["structuredContent"] = result
    return answer


def example_arguments(mock: dict, tool: dict) -> dict:
    """Arguments of a call that works: the tool's own example, or values taken from its records."""
    if "example" in tool:
        return tool["example"]
    serve, properties = tool.get("serve", {}), tool["inputSchema"].get("properties", {})
    records = mock.get("records", {})
    first = (records.get(serve.get("records"), {}).get("items") or [{}])[0]
    arguments = {}
    for name in tool["inputSchema"].get("required", []):
        spec = properties[name]
        if spec.get("enum"):
            arguments[name] = spec["enum"][0]
        elif serve.get("action") == "get":
            arguments[name] = first.get(records[serve["records"]]["key"])
        elif name in tool.get("check", {}):
            target = records[_check_rule(tool["check"][name])["records"]]
            arguments[name] = target["items"][0][target["key"]] if target["items"] else ""
        elif name == "query" and serve:
            title = str(first.get(records[serve["records"]].get("title", ""), ""))
            arguments[name] = next((word for word in title.split() if len(word) > 3), "")
        elif serve:
            arguments[name] = ""
        else:
            when = next((item["when"] for item in tool["responses"] if name in item.get("when", {})), {})
            arguments[name] = when.get(name, {"integer": 1, "number": 1.5, "boolean": True}.get(spec.get("type"), "example"))
    return arguments


def describe(mock: dict) -> list[str]:
    """The listing `tools call TOOL` prints: where the data comes from, then each tool with its arguments."""
    lines = [_instructions(mock)]
    if is_generic(mock) and mock.get("records"):
        lines.append("Generic sample data, not your project's: openguildkit tools scenario writes records for your own.")
    for tool in mock["tools"]:
        kind = "read" if tool.get("read_only", False) else "write"
        lines += ["", f"{tool['name']}  [{kind}]  {tool['description']}", f"    Arguments: {signature(tool)}"]
        lines.append(f"    Example: openguildkit tools call {mock['tool']} {tool['name']} --args "
                     f"'{json.dumps(example_arguments(mock, tool), ensure_ascii=False)}'")
        if tool.get("serve", {}).get("action") == "list" and list_all_arguments(tool) != example_arguments(mock, tool):
            lines.append(f"    Every record: --args '{json.dumps(list_all_arguments(tool))}'")
    return lines


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


def log_call(journal, tool_id: str, name, arguments, write: bool = False) -> None:
    """Append one call to the journal that --log names, so a test can assert what the agent did."""
    entry = {"tool": tool_id, "call": name, "arguments": arguments}
    if write:
        entry["write"] = True
    journal.write(json.dumps(entry, ensure_ascii=False) + "\n")
    journal.flush()


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
                        tool = next((item for item in mock["tools"] if item["name"] == params.get("name")), None)
                        log_call(journal, mock["tool"], params.get("name"), params.get("arguments"),
                                 write=tool is not None and not tool.get("read_only", False))
            if answer is not None:
                stdout.write(json.dumps(answer, ensure_ascii=False).encode("utf-8") + b"\n")
                stdout.flush()
    finally:
        if journal:
            journal.close()
    return 0
