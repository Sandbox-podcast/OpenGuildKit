"""Reads one configured MCP server: the package and the pin it launches, its match in the tool registry, and its masked
command line.

Entry: registry_index, configured_server
Tests: tests/test_host_surfaces.py, tests/test_allow_list_scan.py, tests/test_registry_pins.py
"""

import json
import re
from urllib.parse import urlsplit

from .allowlist import mcp_allowed
from .sensitive import redact_credentials
from .surface_text import line_of, scan_finding, visible_text

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_MATCHED = 500  # characters of a launch or an address that are compared with the registry
DISTINCT_PATH = 20  # an address whose host is a placeholder is recognised only by a path at least this long


NPM_EXACT = re.compile(r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
PYPI_EXACT = re.compile(r"[0-9][0-9A-Za-z.!+_-]*")
COMMIT = re.compile(r"[0-9a-f]{40}")
SECRET_FLAG = re.compile(r"token|secret|key|password|passwd|auth|bearer|credential", re.IGNORECASE)
NPX_VALUE_FLAGS = frozenset({"--registry", "--cache", "--userconfig", "-c", "--call"})
UVX_VALUE_FLAGS = frozenset({"--python", "-p", "--index", "--index-url", "--extra-index-url", "--with", "--env-file",
                             "--with-requirements", "--directory", "--project", "--constraints", "-c"})
PIPX_VALUE_FLAGS = frozenset({"--python", "--index-url", "--pip-args"})
DOCKER_VALUE_FLAGS = frozenset({
    "-e", "--env", "-v", "--volume", "-p", "--publish", "--name", "--network", "--net", "--entrypoint", "-w", "--workdir",
    "-u", "--user", "--mount", "-l", "--label", "--add-host", "--platform", "-m", "--memory", "--cpus", "--env-file",
    "--pull", "--restart", "-h", "--hostname", "--tmpfs", "--cap-add", "--cap-drop", "--security-opt", "--device",
    "--group-add", "--log-driver", "--ulimit", "--dns", "--pid", "--ipc", "--shm-size", "--label-file", "--cidfile",
    "--link", "--volumes-from", "--gpus", "--runtime", "--stop-signal", "--stop-timeout"})


def _program(command: str) -> str:
    return re.sub(r"\.(?:cmd|exe|bat)$", "", command.replace("\\", "/").rsplit("/", 1)[-1].lower())


def _first_spec(args: list[str], spec_flags: set | frozenset, value_flags: frozenset) -> str:
    """The package a runner is asked to run: the value of an option that names it, else the first argument that is not
    an option or the value of one."""
    skip = False
    for index, arg in enumerate(args):
        if skip:
            skip = False
            continue
        flag, equals, value = arg.partition("=")
        if flag in spec_flags:
            return value if equals else (args[index + 1] if index + 1 < len(args) else "")
        if arg.startswith("-"):
            skip = flag in value_flags and not equals
            continue
        return arg
    return ""


def _docker_image(args: list[str]) -> str:
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("-"):
            skip = arg in DOCKER_VALUE_FLAGS
            continue
        return arg
    return ""


def _package_of(command: str, args: list[str]) -> tuple[str, str] | None:
    """The package (npm, pypi or docker) and its spec that a launch fetches and runs, or None for any other command."""
    name = _program(command)
    if name == "cmd" and len(args) > 1 and args[0].lower() == "/c":
        return _package_of(args[1], args[2:])
    if name in ("npx", "bunx"):
        kind, spec = "npm", _first_spec(args, {"-p", "--package"}, NPX_VALUE_FLAGS)
    elif name == "pnpm" and args[:1] == ["dlx"]:
        kind, spec = "npm", _first_spec(args[1:], {"-p", "--package"}, NPX_VALUE_FLAGS)
    elif name == "uvx":
        kind, spec = "pypi", _first_spec(args, {"--from"}, UVX_VALUE_FLAGS)
    elif name == "pipx" and args[:1] == ["run"]:
        kind, spec = "pypi", _first_spec(args[1:], {"--spec"}, PIPX_VALUE_FLAGS)
    elif name == "docker" and args[:1] == ["run"]:
        kind, spec = "docker", _docker_image(args[1:])
    else:
        return None
    return (kind, spec) if spec else None


def _npm_floats(spec: str) -> str | None:
    if "://" in spec or spec.startswith((".", "/", "file:", "github:", "git+")):
        return None if COMMIT.search(spec.rsplit("#", 1)[-1].rsplit("@", 1)[-1]) else "a repository reference without a commit"
    at = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
    if at == -1:
        return "no version"
    version = spec[at + 1:]
    if version == "latest":
        return "the tag latest"
    return None if NPM_EXACT.fullmatch(version) else f"the version or tag {version[:40]!r}, which is not one fixed version"


def _pypi_floats(spec: str) -> str | None:
    if "://" in spec or spec.startswith("git+"):
        return None if COMMIT.search(spec.rsplit("@", 1)[-1]) else "a repository reference without a commit"
    rest = re.sub(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[^\]]*\])?", "", spec).strip()
    if not rest:
        return "no version"
    version = rest[1:] if rest.startswith("@") else rest.lstrip("=") if rest.startswith("==") else None
    if version == "latest":
        return "the tag latest"
    if version is not None and "*" not in version and PYPI_EXACT.fullmatch(version):
        return None
    return f"the specifier {rest[:40]!r}, which is not one exact version"


def _docker_floats(spec: str) -> str | None:
    if "@sha256:" in spec or "@sha512:" in spec:
        return None
    tag = spec.rsplit("/", 1)[-1].rpartition(":")[2] if ":" in spec.rsplit("/", 1)[-1] else ""
    if not tag:
        return "no tag and no digest"
    return "the tag latest" if tag == "latest" else None


def _pin(kind: str, spec: str) -> tuple[bool | None, str]:
    """Whether a package spec is fixed to one version (an image to a tag or a digest), and why not. A spec that names a
    variable cannot be judged: None."""
    if "$" in spec or "{" in spec:
        return None, ""
    reason = {"npm": _npm_floats, "pypi": _pypi_floats, "docker": _docker_floats}[kind](spec)
    return (reason is None), reason or ""


def _canonical(kind: str, spec: str) -> str:
    """The name of a package without its version, in the form the registry writes it."""
    if kind == "npm":
        at = spec.find("@", 1) if spec.startswith("@") else spec.find("@")
        return (spec[:at] if at != -1 else spec).lower()
    if kind == "pypi":
        match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec)
        return re.sub(r"[-_.]+", "-", match.group().lower()) if match else ""
    folder, slash, last = spec.split("@", 1)[0].rpartition("/")
    return (folder + slash + last.partition(":")[0]).lower()


def _template(text: str) -> re.Pattern:
    """A registry value as a pattern: its {placeholders} stand for any text."""
    return re.compile(r"\S+".join(re.escape(part) for part in re.split(r"\{[a-z_]+\}", text)))


def _address(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def registry_index(tools: dict) -> list[tuple[str, dict, list]]:
    """Each server of the registry with the ways a configuration can name it: package, address, command line."""
    index = []
    for tool_id in sorted(tools):
        for server in tools[tool_id]["servers"]:
            matchers = []
            if server["transport"] == "stdio":
                package = server["package"]
                if package["registry"] in ("npm", "pypi", "docker"):
                    matchers.append(("package", package["registry"], _canonical(package["registry"], package["name"])))
                matchers.append(("command", _program(server["command"]), [_template(arg) for arg in server["args"]]))
            else:
                host, _, path = _address(server["url"]).partition("://")[2].partition("/")
                # https://{host}/mcp names no product: it would take the address of any other server for this one.
                if not re.fullmatch(r"\{[a-z_]+\}", host) or len(re.sub(r"\{[a-z_]+\}", "", path)) >= DISTINCT_PATH:
                    matchers.append(("url", _template(_address(server["url"]))))
            index.append((tool_id, server, matchers))
    return index


def _names(entry: dict, matcher: tuple) -> bool:
    if matcher[0] == "package":
        return entry["package"] == (matcher[1], matcher[2])
    if matcher[0] == "url":
        return bool(entry["address"]) and matcher[1].fullmatch(entry["address"]) is not None
    return entry["program"] == matcher[1] and len(entry["args"]) == len(matcher[2]) and all(
        pattern.fullmatch(arg) for pattern, arg in zip(matcher[2], entry["args"]))


def _registry_match(entry: dict, index: list) -> dict | None:
    """The registry server a configured server is, by its package first, then by its address or its command line."""
    for kinds in (("package",), ("url", "command")):
        for _, server, matchers in index:
            if any(matcher[0] in kinds and _names(entry, matcher) for matcher in matchers):
                return {"server": server["id"],
                        "tools": sorted(tool for tool, other, _ in index if other["id"] == server["id"])}
    return None


def _mask(args: list[str]) -> list[str]:
    """The arguments of a launch with the value of an environment variable or of a secret option hidden."""
    shown, previous = [], ""
    for arg in args:
        flag, equals, _ = arg.partition("=")
        if previous in ("-e", "--env") and equals:
            shown.append(f"{flag}=[redacted]")
        elif flag == "--env" and arg.count("=") > 1:
            shown.append(f"--env={arg.split('=')[1]}=[redacted]")
        elif previous.startswith("-") and "=" not in previous and SECRET_FLAG.search(previous) and not arg.startswith("-"):
            shown.append("[redacted]")
        elif arg.startswith("-") and equals and SECRET_FLAG.search(flag):
            shown.append(f"{flag}=[redacted]")
        else:
            shown.append(redact_credentials(arg))
        previous = arg
    return shown


def _show_address(url: str) -> str:
    """An address without its user name, password and query, which may hold a credential."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname or "", parts.port
    except ValueError:
        return "[unreadable address]"
    host = f"[{host}]" if ":" in host else host
    return visible_text(f"{parts.scheme}://{host}{f':{port}' if port else ''}{parts.path}" + ("?..." if parts.query else ""))


def configured_server(name: str, spec: dict, relative: str, host: str, text: str, index: list,
            allow: dict | None = None) -> tuple[dict, list[dict]]:
    """One configured MCP server as the inventory shows it, and the findings about it. allow is the allow list, if any."""
    command = spec["command"] if isinstance(spec.get("command"), str) else ""
    args = [arg for arg in spec["args"] if isinstance(arg, str)] if isinstance(spec.get("args"), list) else []
    url = next((spec[key] for key in ("url", "httpUrl") if isinstance(spec.get(key), str)), "")
    declared = spec["type"] if isinstance(spec.get("type"), str) else ""
    transport = ({"sse": "sse", "http": "http", "streamable-http": "http"}.get(declared)
                 or ("remote" if url else "stdio" if command else "unknown"))
    package = _package_of(command, args) if command and not url else None
    pinned, why = _pin(*package) if package else (None, "")
    entry = {"name": visible_text(name), "file": relative, "host": host, "transport": transport,
             "launch": _show_address(url) if url else visible_text(" ".join([redact_credentials(command), *_mask(args)]).strip()),
             "pinned": pinned}
    line = line_of(text, f"[mcp_servers.{name}]", f'[mcp_servers."{name}"]') if relative.endswith(".toml") \
        else line_of(text, json.dumps(name))
    lookup = {"package": (package[0], _canonical(*package)) if package else None, "args": args,
              "program": _program(command), "address": _address(url) if url and len(url) < MAX_MATCHED else ""}
    entry["registry"] = None if len(" ".join(args)) > MAX_MATCHED else _registry_match(lookup, index)
    findings = []
    if allow is not None and "mcp_servers" in allow and not mcp_allowed(
            allow["mcp_servers"], (*package, _canonical(*package)) if package else None, url, _program(command)):
        what = (f"the {package[0]} package {visible_text(package[1])[:80]}" if package else _show_address(url) if url
                else f"the command {visible_text(_program(command))[:60] or 'of no name'}")
        findings.append(scan_finding(
            "mcp-not-allowed", "error", f'MCP server "{visible_text(name)[:60]}" runs {what}, which the allow list does not name.',
            relative, line))
    if pinned is False:
        what = {"npm": "npm package", "pypi": "Python package", "docker": "Docker image"}[package[0]]
        findings.append(scan_finding(
            "mcp-unpinned", "warning", f'MCP server "{visible_text(name)[:60]}" runs the {what} {visible_text(package[1])[:80]} '
            f"with {why}: pin one exact version, or an image digest, so that what runs is what was reviewed.",
            relative, line))
    if url:
        try:
            scheme, host_name = urlsplit(url).scheme, urlsplit(url).hostname
        except ValueError:
            scheme, host_name = "", None
        if scheme == "http" and host_name is not None and host_name not in LOCAL_HOSTS:
            findings.append(scan_finding(
                "mcp-insecure-transport", "error", f'MCP server "{visible_text(name)[:60]}" connects to {_show_address(url)}: an http '
                "address is not encrypted. Use https, or a server on localhost.", relative, line))
    return entry, findings
