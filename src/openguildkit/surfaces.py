"""What an agent reads and what could act in a project: `openguildkit host scan`.

The instruction files of a project (AGENTS.md, Claude Code agents and Skills, Cursor rules, Copilot instructions...)
are read by an agent as orders. A character nobody sees or a sentence that cancels the rules passes a human review.
`scan` reads those files, offline and without running anything, and reports hidden characters, phrases that cancel
the rules or hide an action from the person, and downloads piped into an interpreter. `discover` lists the agent tools
the files show, the MCP servers they configure and the permissive settings, and says what OpenGuildKit covers for each
tool. Each finding is a dict: code, level (error, warning or note), message, path (relative, with /), line, and an
optional excerpt in which control characters are written U+XXXX and a line that looks like a credential is replaced by
[redacted]. A server is shown by its launch, never by its environment, headers or credentials.

Nothing here opens a network connection, starts a process or writes a file. Matching is by words and literal text, never
by a pattern that can backtrack, so a line of a megabyte costs one pass.

Entry: discover, scan, scan_report, render_scan, scan_exit_code
Tests: tests/test_host_scan.py, tests/test_host_surfaces.py, tests/test_allow_list_scan.py, tests/test_gemini_host.py,
tests/test_registry_pins.py
"""

import json
import os
import re
import tomllib
from itertools import islice
from pathlib import Path
from urllib.parse import urlsplit

from .allowlist import address_allowed, load_allow
from .hosts import HOOK_HOSTS, UNHOOKED_TOOLS, board_control, unhooked_detail, unhooked_source
from .surface_servers import configured_server, registry_index
from .surface_text import LEVELS, analyse_text, line_of, scan_finding, visible_text
from .tool_registry import load_tools
from .wording import plural

MAX_FILES = 200
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 20_000_000
MAX_SERVER_LINES = 15
MAX_ENTRIES = 10_000  # entries of one folder that are listed
IGNORED_FOLDERS = frozenset({".git", "node_modules", ".venv"})
IGNORED_TASKS = (".openguildkit", "tasks")
# What an agent reads as instructions: a file, or a folder read in full. The files of TOOLS that carry instructions are
# here too (tests/test_host_scan.py checks it).
INSTRUCTION_PATHS = (
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "WARP.md", ".claude/agents", ".claude/skills", ".claude/commands",
    ".cursor/rules", ".cursorrules", ".github/copilot-instructions.md", ".github/instructions", ".windsurf/rules",
    ".windsurfrules", ".clinerules", ".roo", ".kilocode", ".junie", ".rules",
    ".goosehints", ".opencode", ".claude/rules", ".claude/CLAUDE.md", "CLAUDE.local.md", "AGENTS.override.md",
    ".agents/skills", ".gemini/commands", ".github/prompts", ".github/agents", ".cursor/commands", ".windsurf/workflows",
)
# The instruction files that an agent also reads in the subfolder it works in.
NESTED_INSTRUCTIONS = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
MAX_FOLDERS = 5_000  # folders searched for NESTED_INSTRUCTIONS
# Settings and MCP configurations: read for downloads piped into an interpreter only.
CONFIG_PATHS = (".mcp.json", ".cursor/mcp.json", ".vscode/mcp.json", ".gemini/settings.json", ".codex/config.toml",
                ".codex/hooks.json", ".claude/settings.json", ".claude/settings.local.json")


class _Collector:
    """The files to read, in a fixed order, and the ones left alone with the reason."""

    def __init__(self, root: Path):
        self.root, self.top = root, root.resolve()
        self.files: list[tuple[str, Path, bool]] = []
        self.skipped: list[dict] = []
        self._files: set[Path] = set()
        self._folders: set[Path] = set()
        self._full = False

    def skip(self, relative: str, reason: str) -> None:
        self.skipped.append({"path": relative, "reason": reason})

    def visit_nested(self, names: tuple) -> None:
        """The files of these names in the subfolders, in a walk of at most MAX_FOLDERS folders that starts no process."""
        folders = 0
        for folder, dirs, files in os.walk(self.root):
            dirs[:] = sorted(name for name in dirs if name not in IGNORED_FOLDERS)
            where = Path(folder).relative_to(self.root).as_posix()
            if where == ".":
                continue
            if where.split("/")[:2] == list(IGNORED_TASKS):
                dirs.clear()
                continue
            folders += 1
            if folders > MAX_FOLDERS:
                return self.skip(where, f"more than {MAX_FOLDERS} folders: the rest is not searched for {', '.join(names)}")
            for name in names:
                if name in files:
                    self.visit(f"{where}/{name}")

    def visit(self, relative: str, config: bool = False) -> None:
        path = self.root / relative
        if self._full or not os.path.lexists(path):
            return
        try:
            real = path.resolve(strict=True)
        except (OSError, RuntimeError):  # RuntimeError: a loop of links, before Python 3.13
            return self.skip(relative, "cannot be resolved (a loop or a broken link)")
        if real != self.top and self.top not in real.parents:
            return self.skip(relative, "symbolic link outside the project: not followed")
        inside = real.relative_to(self.top).parts
        if IGNORED_FOLDERS & set(inside) or inside[:2] == IGNORED_TASKS or IGNORED_FOLDERS & set(relative.split("/")):
            return
        if real.is_dir():
            if real in self._folders:
                return
            self._folders.add(real)
            try:
                names = sorted(islice((entry.name for entry in os.scandir(path)), MAX_ENTRIES + 1))
            except OSError:
                return self.skip(relative, "cannot be read")
            if len(names) > MAX_ENTRIES:
                return self.skip(relative, f"more than {MAX_ENTRIES} entries: not read")
            for name in names:
                self.visit(f"{relative}/{name}", config)
        elif real.is_file() and real not in self._files:
            if len(self.files) >= MAX_FILES:
                self._full = True
                return self.skip(relative, f"more than {MAX_FILES} files: the rest is not read")
            self._files.add(real)
            self.files.append((relative, real, config))


def _load(real: Path, spent: int) -> tuple[str | None, str | None]:
    """The text of a file, or the reason it is not read. A binary file is left alone without a reason."""
    try:
        size = real.stat().st_size
        if size > MAX_FILE_BYTES:
            return None, f"larger than 1 MB ({MAX_FILE_BYTES} bytes): not read"
        if spent + size > MAX_TOTAL_BYTES:
            return None, f"the files read already hold {MAX_TOTAL_BYTES // 1_000_000} MB: not read"
        data = real.read_bytes()
    except OSError:
        return None, "cannot be read"
    if b"\0" in data[:8192]:
        return None, None
    return data.decode("utf-8", errors="replace"), None


def _order(item: dict) -> tuple:
    return item["path"] or "", item["line"] or 0, item["code"]


def scan(root: Path) -> dict:
    """Read the instruction files, the settings and the MCP configurations of a project, and return the findings.

    The result holds `findings` and `scanned`: how many files were read, and the files left alone with the reason.
    """
    collector = _Collector(root)
    for relative in sorted(INSTRUCTION_PATHS):
        collector.visit(relative)
    for relative in sorted(CONFIG_PATHS):
        collector.visit(relative, config=True)
    collector.visit_nested(NESTED_INSTRUCTIONS)
    findings, read, spent = [], 0, 0
    for relative, real, config in collector.files:
        text, reason = _load(real, spent)
        if reason:
            collector.skip(relative, reason)
        if text is None:
            continue
        spent += len(text)
        read += 1
        findings += analyse_text(relative, text, config)
    return {"findings": sorted(findings, key=_order), "scanned": {"files": read, "skipped": collector.skipped}}


# What the compatibility list of agents.md says, read on 2026-11-25 (component CompatibilitySection of the repository
# agentsmd/agents.md). GitHub Copilot is its entry "Coding agent". An agent absent from the list is not documented as
# reading AGENTS.md there: that is not a claim that it does not.
AGENTS_MD_TOOLS = ("Codex", "Amp", "Jules", "Cursor", "Factory", "RooCode", "Aider", "Gemini CLI", "goose", "Kilo Code",
                   "opencode", "Zed", "Warp", "GitHub Copilot", "VS Code", "Ona", "Devin", "Windsurf", "Augment Code",
                   "Junie", "Phoenix", "Semgrep", "UiPath")


def _tool(tool_id: str, name: str, files: tuple, listed_as: str | None, note: str = "", imports: bool = False) -> dict:
    return {"id": tool_id, "name": name, "files": files, "listed_as": listed_as, "reads_agents_md": listed_as is not None,
            "note": note, "imports_agents_md": imports}


# The files that show a tool is used in the project: folders and files at the root, the names its own conventions give.
# They are not checked against each vendor's current documentation. A tool of the list with no file of its own (Amp,
# Jules, Factory, Ona, Devin, Augment Code, Phoenix, Semgrep, UiPath, VS Code) cannot be seen from the repository.
TOOLS = (
    _tool("aider", "Aider", (".aider.conf.yml",), "Aider"),
    _tool("claude-code", "Claude Code", ("CLAUDE.md", ".claude", ".mcp.json"), None, imports=True),
    _tool("cline", "Cline", (".clinerules",), None),
    _tool("codex", "Codex", (".codex",), "Codex"),
    _tool("copilot", "GitHub Copilot", UNHOOKED_TOOLS["copilot"]["files"], "GitHub Copilot", note=' as "Coding agent"'),
    _tool("cursor", "Cursor", UNHOOKED_TOOLS["cursor"]["files"], "Cursor"),
    _tool("gemini-cli", "Gemini CLI", ("GEMINI.md", ".gemini"), "Gemini CLI",
          note="; its default context file is GEMINI.md, and AGENTS.md needs its context.fileName setting"),
    _tool("goose", "goose", (".goosehints",), "goose"),
    _tool("junie", "Junie", (".junie",), "Junie"),
    _tool("kilo", "Kilo Code", (".kilocode",), "Kilo Code"),
    _tool("opencode", "opencode", ("opencode.json", "opencode.jsonc", ".opencode"), "opencode"),
    _tool("roo", "Roo Code", (".roo",), "RooCode"),
    _tool("warp", "Warp", ("WARP.md",), "Warp"),
    _tool("windsurf", "Windsurf", (".windsurf", ".windsurfrules"), "Windsurf"),
    _tool("zed", "Zed", (".rules", ".zed"), "Zed"),
)
AGENTS_MD_SOURCE = {
    "url": "https://agents.md", "repository": "https://github.com/agentsmd/agents.md", "component": "CompatibilitySection",
    "read": "2026-11-25", "tools": list(AGENTS_MD_TOOLS),
    "without_files": [name for name in AGENTS_MD_TOOLS if name not in {tool["listed_as"] for tool in TOOLS}],
}
MCP_FILES = ((".mcp.json", "mcpServers", "claude-code"), (".cursor/mcp.json", "mcpServers", "cursor"),
             (".vscode/mcp.json", "servers", "vscode"), (".gemini/settings.json", "mcpServers", "gemini-cli"),
             (".codex/config.toml", "mcp_servers", "codex"))
CLAUDE_SETTINGS = (".claude/settings.json", ".claude/settings.local.json")
CODEX_CONFIG = ".codex/config.toml"
CI_ONLY = "the CI check (guard --ci) is the only barrier"
COVERAGE_SHORT = {"enforced": "hooks installed", "missing": "hooks missing", "off": "guard off, no hook",
                  "none": "no hook, CI is the only barrier", "unreadable": "settings unreadable"}


def _agents_md(tool: dict) -> tuple[str, str]:
    """Whether the tool reads AGENTS.md according to the agents.md list, and the sentence that says so."""
    day = AGENTS_MD_SOURCE["read"]
    if tool["reads_agents_md"]:
        return "listed", f"reads AGENTS.md (agents.md list{tool['note']}, read {day})"
    if tool["imports_agents_md"]:
        return "import", f"reads CLAUDE.md, where OpenGuildKit writes an import of AGENTS.md; not on the agents.md list (read {day})"
    return "not-documented", f"not documented as reading AGENTS.md (absent from the agents.md list read {day})"


def _coverage(root: Path, tool: dict, profile: dict) -> dict:
    """What OpenGuildKit covers for a tool. Claude Code, Codex and Gemini CLI: what host check says of the guard hooks, for
    the guard of the profile; every other tool has no hook."""
    guard, host = profile.get("guard", "off"), profile.get("host", "other")
    if tool["id"] in UNHOOKED_TOOLS:
        return {"status": "none", "detail": unhooked_detail(tool["id"]), "source": unhooked_source(tool["id"])}
    if tool["id"] not in HOOK_HOSTS:
        return {"status": "none", "detail": f"no hook blocks an edit; {CI_ONLY}"}
    if guard == "off":
        return {"status": "off", "detail": f"the guard of the profile is off, so no hook runs before an edit; {CI_ONLY}"}
    try:
        control = board_control(root, tool["id"], guard)
    except ValueError as error:
        return {"status": "unreadable", "detail": f"its settings cannot be read ({error}); {CI_ONLY}"}
    if control["status"] == "enforced":
        return {"status": "enforced", "detail": f"its hooks are installed (guard {guard}); a shell command does not go "
                                               "through them, so the CI check (guard --ci) still matters"}
    if control.get("cause") == "path":
        detail = "its hooks are installed, but openguildkit is not on the PATH of this workstation, so they cannot run"
    elif host == tool["id"]:
        detail = ("its hooks are not installed or incomplete (run openguildkit host apply, then openguildkit host "
                  f"check); until then {CI_ONLY}")
    else:
        detail = (f"OpenGuildKit installs its hooks for the profile's host ({host}) only, so no hook blocks an edit "
                  f"made through it; {CI_ONLY}")
    return {"status": "missing", "detail": detail}


def _jsonc(text: str) -> str:
    """JSON with the comments and trailing commas that VS Code writes, removed outside strings."""
    out, index, in_string = [], 0, False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < len(text):
                out.append(text[index + 1])
                index += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith("//", index):
            index = text.find("\n", index)
            if index == -1:
                break
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        else:
            out.append(char)
        index += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


class _Configs:
    """The settings and MCP files, each read and parsed once, with the ones that cannot be read."""

    def __init__(self, root: Path):
        self.root, self.skipped, self._seen = root, [], {}

    def get(self, relative: str) -> tuple[dict | None, str]:
        if relative not in self._seen:
            self._seen[relative] = self._read(relative)
        return self._seen[relative]

    def _read(self, relative: str) -> tuple[dict | None, str]:
        collector = _Collector(self.root)
        collector.visit(relative, config=True)
        self.skipped += collector.skipped
        if not collector.files:
            return None, ""
        text, reason = _load(collector.files[0][1], 0)
        if reason or text is None:
            self.skipped += [{"path": relative, "reason": reason}] if reason else []
            return None, ""
        kind = "TOML" if relative.endswith(".toml") else "JSON"
        try:
            body = text.lstrip("\ufeff")
            data = tomllib.loads(body) if kind == "TOML" else _json_or_jsonc(body)
        except (ValueError, RecursionError) as error:
            self.skipped.append({"path": relative, "reason": f"not valid {kind}: {str(error)[:80]}"})
            return None, text
        if not isinstance(data, dict):
            self.skipped.append({"path": relative, "reason": f"not valid {kind}: the top level is not an object"})
            return None, text
        return data, text


def _json_or_jsonc(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(_jsonc(text))


def _outside_allow_list(configs: _Configs, allow: dict) -> list[dict]:
    """The model and the provider address of Claude Code and Codex that the allow list does not name. A finding names the
    key and the host of an address, never another value of the environment, and carries no excerpt."""
    found = []
    for relative, group_key in ((CLAUDE_SETTINGS[0], "env"), (CLAUDE_SETTINGS[1], "env"), (CODEX_CONFIG, "model_providers")):
        data, text = configs.get(relative)
        if not data:
            continue
        model = data.get("model")
        if "models" in allow and isinstance(model, str) and model not in allow["models"]:
            found.append(scan_finding("model-not-allowed", "error", f'{relative} sets the model "{visible_text(model)[:60]}", '
                                  "which the allow list does not name.", relative, line_of(text, '"model"', "model =")))
        if "endpoints" not in allow:
            continue
        raw = data.get(group_key)
        group: dict = raw if isinstance(raw, dict) else {}
        if group_key == "env":
            addresses = [("env.ANTHROPIC_BASE_URL", "ANTHROPIC_BASE_URL", group.get("ANTHROPIC_BASE_URL"))]
        else:
            addresses = [(f"model_providers.{visible_text(str(name))[:40]}.base_url", "base_url", spec.get("base_url"))
                         for name, spec in sorted(group.items(), key=lambda item: str(item[0])) if isinstance(spec, dict)]
        for label, needle, value in addresses:
            if isinstance(value, str) and not address_allowed(allow["endpoints"], value):
                try:
                    host_name = urlsplit(value).hostname or "[no host]"
                except ValueError:
                    host_name = "[unreadable address]"
                found.append(scan_finding("endpoint-not-allowed", "error", f"{relative} sets {label} to an address on "
                                      f"{visible_text(host_name)[:80]}, which the allow list does not name.", relative,
                                      line_of(text, needle)))
    return found


def _setting(relative: str, text: str, needle: str, message: str) -> dict:
    return scan_finding("permissive-setting", "warning", f"Permissive setting: {message}.", relative, line_of(text, needle))


def _permissive(configs: _Configs) -> list[dict]:
    """The settings of Claude Code and Codex that hand the agent every tool or take away its sandbox."""
    found = []
    for relative in CLAUDE_SETTINGS:
        data, text = configs.get(relative)
        if not data:
            continue
        permissions = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
        if permissions.get("defaultMode") == "bypassPermissions":
            found.append(_setting(relative, text, '"defaultMode"', 'permissions.defaultMode is "bypassPermissions"'))
        allow = permissions.get("allow") if isinstance(permissions.get("allow"), list) else []
        for rule in dict.fromkeys(rule.strip() for rule in allow if isinstance(rule, str)):
            if rule in ("Bash", "Bash(*)"):
                found.append(_setting(relative, text, f'"{rule}"', f'permissions.allow holds "{rule}", every shell command'))
        if data.get("enableAllProjectMcpServers") is True:
            found.append(_setting(relative, text, '"enableAllProjectMcpServers"', "enableAllProjectMcpServers is true"))
    data, text = configs.get(CODEX_CONFIG)
    if data and data.get("approval_policy") == "never" and data.get("sandbox_mode") == "danger-full-access":
        found.append(_setting(CODEX_CONFIG, text, "approval_policy",
                              'approval_policy is "never" and sandbox_mode is "danger-full-access"'))
    return found


def discover(root: Path, profile: dict | None = None, tools: dict | None = None, allow: dict | None = None) -> dict:
    """The agent tools the files of a project show, its MCP servers, and the findings about them and about the
    permissive settings. The profile gives the guard and the host; tools is the registry (the bundled one by default);
    allow is an allow list (allowlist.py), whose absence leaves the findings as they were."""
    profile, configs = profile or {}, _Configs(root)
    servers, found, index = [], [], None
    for relative, key, host in MCP_FILES:
        data, text = configs.get(relative)
        listed = data.get(key) if data and isinstance(data.get(key), dict) else {}
        for name, spec in sorted((str(name), spec) for name, spec in listed.items() if isinstance(spec, dict)):
            index = registry_index(load_tools() if tools is None else tools) if index is None else index
            entry, findings = configured_server(name, spec, relative, host, text, index, allow)
            servers.append(entry)
            found += findings
    found += _permissive(configs) + (_outside_allow_list(configs, allow) if allow is not None else [])
    present = []
    for tool in TOOLS:
        files = [path for path in tool["files"] if os.path.lexists(root / path)]
        if not files:
            continue
        reads, sentence = _agents_md(tool)
        coverage = _coverage(root, tool, profile)
        present.append({"id": tool["id"], "name": tool["name"], "files": files, "reads_agents_md": tool["reads_agents_md"],
                        "agents_md": reads, "agents_md_text": sentence, "coverage": coverage})
        if coverage["status"] != "enforced":
            found.append(scan_finding(
                "surface-uncovered", "warning" if profile.get("guard") == "enforce" else "note",
                f"{tool['id']}: {', '.join(files)} present, and {coverage['detail'].rstrip('.')}.", files[0], None))
    return {"surfaces": present, "mcp_servers": sorted(servers, key=lambda item: (item["file"], item["name"])),
            "findings": sorted(found, key=_order), "skipped": configs.skipped}


def scan_report(root: Path, profile: dict | None = None, tools: dict | None = None, allow: Path | None = None) -> dict:
    """What `host scan` prints with --json: the inventory, the findings of both analyses in one list, the sources.
    allow is the file of an allow list: what it does not name is an error."""
    content, inventory = scan(root), discover(root, profile, tools, load_allow(allow) if allow else None)
    skipped = {(item["path"], item["reason"]): item for item in content["scanned"]["skipped"] + inventory["skipped"]}
    return {"surfaces": inventory["surfaces"], "mcp_servers": inventory["mcp_servers"],
            "findings": sorted(content["findings"] + inventory["findings"], key=_order),
            "source": {"agents_md": AGENTS_MD_SOURCE},
            "scanned": {"files": content["scanned"]["files"], "skipped": list(skipped.values())}}


def _tool_lines(tools: list[dict]) -> list[str]:
    width = max(len(item["id"]) for item in tools)
    return [f"Agent tools present (AGENTS.md reading from the agents.md list, read {AGENTS_MD_SOURCE['read']}):"] + [
        f"  {item['id']:<{width}}  {_short(item['coverage'])}; {item['agents_md_text']}" for item in tools]


def _short(coverage: dict) -> str:
    if "source" in coverage:
        return f"no edit blocked, guard --ci is the only barrier (hook docs read {coverage['source']['read']})"
    return COVERAGE_SHORT[coverage["status"]]


def _server_lines(servers: list[dict]) -> list[str]:
    lines = [f"MCP servers ({len(servers)}):"]
    for item in servers[:MAX_SERVER_LINES]:
        registry = f"registry: {item['registry']['server']}" if item["registry"] else "not in the registry"
        pin = {True: "version fixed", False: "version not fixed", None: ""}[item["pinned"]]
        launch = item["launch"] if len(item["launch"]) <= 70 else item["launch"][:67] + "..."
        lines.append(f"  {item['name']} ({visible_text(item['file'])}): {launch}; {registry}" + (f"; {pin}" if pin else ""))
    if len(servers) > MAX_SERVER_LINES:
        lines.append(f"  ... and {len(servers) - MAX_SERVER_LINES} more")
    return lines


def render_scan(result: dict) -> str:
    """The short text of `host scan`: the totals, one line per tool and per server, one line per code with its first
    place, and the command for the rest."""
    findings, scanned = result["findings"], result["scanned"]
    detail = ", ".join(f"{count} {level}{'' if count == 1 else 's'}" for level in LEVELS
                       if (count := sum(item["level"] == level for item in findings)))
    lines = [f"host scan read {plural(scanned['files'], 'file')} and found {plural(len(findings), 'finding')}"
             + (f" ({detail})." if findings else ".")]
    if result["surfaces"]:
        lines += _tool_lines(result["surfaces"])
    if result["mcp_servers"]:
        lines += _server_lines(result["mcp_servers"])
    for code in sorted({item["code"] for item in findings},
                       key=lambda name: (min(LEVELS.index(item["level"]) for item in findings if item["code"] == name),
                                         name)):
        items = [item for item in findings if item["code"] == code]
        worst = min((item["level"] for item in items), key=LEVELS.index)
        first = next(item for item in items if item["level"] == worst)
        where = visible_text((first["path"] or "") + (f":{first['line']}" if first["line"] else ""))
        lines.append(f"  {worst:<7} {code} x{len(items)}  {where}")
    if scanned["skipped"]:
        first = scanned["skipped"][0]
        lines.append(f"Not read: {plural(len(scanned['skipped']), 'file')} "
                     f"(first: {visible_text(first['path'])}, {visible_text(first['reason'])}).")
    lines.append("Run openguildkit host scan --json for every finding with its line and excerpt, and the whole inventory.")
    return "\n".join(lines)


def scan_exit_code(result: dict, strict: bool) -> int:
    """1 when a finding is an error, or any finding at all with --strict."""
    return int(any(item["level"] == "error" or strict for item in result["findings"]))


SARIF_HELP = "host-scan.md#what-the-findings-mean"
SARIF_RULES = {code: {"name": name, "description": description, "help": SARIF_HELP} for code, name, description in (
    ("hidden-character", "Hidden character",
     "A file an agent reads holds a character a person does not see."),
    ("instruction-override", "Instruction that cancels the rules",
     "A file an agent reads asks it to ignore its rules or to hide an action from the user."),
    ("remote-execution", "Code run as it arrives",
     "A file an agent reads, or a setting, pipes a download into an interpreter or runs an encoded command."),
    ("mcp-unpinned", "MCP server without a fixed version",
     "An MCP server starts a package or an image that is not pinned to one version."),
    ("mcp-insecure-transport", "MCP server over plain http",
     "An MCP server is reached over http outside the machine."),
    ("permissive-setting", "Permissive agent setting",
     "A setting gives the agent every shell command or takes away its prompts or its sandbox."),
    ("mcp-not-allowed", "MCP server outside the allow list",
     "An MCP server is not named by the allow list given to the scan."),
    ("model-not-allowed", "Model outside the allow list", "A setting names a model that the allow list does not name."),
    ("endpoint-not-allowed", "Provider address outside the allow list",
     "A setting points at a model provider address that the allow list does not name."),
    ("surface-uncovered", "Agent tool the guard cannot block",
     "An agent tool is present in the project and no hook of OpenGuildKit blocks an edit made through it."),
)}


def scan_sarif(result: dict, root: Path) -> str:
    """The findings of `scan_report` as the SARIF 2.1.0 document `host scan --format sarif` prints."""
    from .lock import package_version
    from .sarif import finding, sarif_text, to_sarif

    found = [finding(item["code"], item["level"], item["message"], item.get("path"), item.get("line"))
             for item in result["findings"]]
    return sarif_text(to_sarif(found, rules=SARIF_RULES, tool_version=package_version(), root=root))
