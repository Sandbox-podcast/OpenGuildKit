"""The allow list of an organization: the MCP servers, models and provider addresses that `host scan --allow FILE` accepts.

A person keeps the file, in a policy repository or in the project, and passes it to the scan: what it does not name is an
error. A list without an axis does not restrict that axis, and an empty list allows nothing. Entries are written
`npm:PACKAGE[@VERSION]`, `pypi:PACKAGE[==VERSION]`, `docker:IMAGE[:TAG]` or `command:PROGRAM` for a server that runs, an
`https://` address for a remote one, the name of a model, and an address for a provider; a package without a version
allows every version, with one it allows that version only. The scan reads the file and nothing else changes.

Entry: load_allow, mcp_allowed, address_allowed.
Tests: tests/test_host_surfaces.py.
"""

import json
from pathlib import Path

AXES = ("mcp_servers", "models", "endpoints")


def load_allow(path: Path) -> dict:
    """The lists of the file: a JSON object with the axes, or with an `allow` object that holds them."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as error:
        raise ValueError(f"The allow list {path.as_posix()} cannot be read: {getattr(error, 'strerror', None) or error}.") from error
    block = data.get("allow", data) if isinstance(data, dict) else None
    if (not isinstance(block, dict) or set(block) - set(AXES)
            or any(not isinstance(items, list) or any(not isinstance(item, str) or not item.strip() for item in items)
                   for items in block.values())):
        raise ValueError(f"The allow list {path.as_posix()} must be a JSON object with the keys {', '.join(AXES)} only, "
                         "each a list of non-empty text, alone or under the key allow.")
    return {axis: [item.strip() for item in items] for axis, items in block.items()}


def normal(address: str) -> str:
    """An address as lists and settings compare it: without query, fragment and trailing slash, in lower case."""
    return address.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def mcp_allowed(listed: list[str], package: tuple[str, str, str] | None, url: str, program: str) -> bool:
    """Whether a server is named: by its package (kind, spec, name without version), its address or its command."""
    names = {item.lower() for item in listed}
    if url:
        return any(item.lower().startswith(("http://", "https://")) and normal(item) == normal(url) for item in listed)
    if package:
        kind, spec, name = package
        return f"{kind}:{spec}".lower() in names or f"{kind}:{name}".lower() in names
    return f"command:{program}".lower() in names


def address_allowed(listed: list[str], address: str) -> bool:
    """Whether an address is one the list names or lies below one it names."""
    wanted = normal(address)
    return any(wanted == normal(item) or wanted.startswith(normal(item) + "/") for item in listed)
