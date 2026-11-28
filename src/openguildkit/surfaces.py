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
"""

import json
import os
import re
import tomllib
import unicodedata
from itertools import groupby, islice
from pathlib import Path
from urllib.parse import urlsplit

from .hosts import HOOK_HOSTS, UNHOOKED_TOOLS, board_control, unhooked_detail, unhooked_source
from .project import managed_block_lines
from .sensitive import looks_like_credential, redact_credentials
from .tools import load_tools
from .wording import plural

MAX_FILES = 200
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 20_000_000
MAX_SERVER_LINES = 15
MAX_ENTRIES = 10_000  # entries of one folder that are listed
MAX_PER_CODE = 25  # findings of one code listed for one file; the rest is counted in one more finding
EXCERPT_BEFORE, EXCERPT_AFTER, EXCERPT_MAX = 40, 120, 240
CREDENTIAL_REACH = 1000  # characters around a match that are searched for a credential before an excerpt is shown
IGNORED_FOLDERS = frozenset({".git", "node_modules", ".venv"})
IGNORED_TASKS = (".openguildkit", "tasks")
LEVELS = ("error", "warning", "note")
# What an agent reads as instructions: a file, or a folder read in full.
INSTRUCTION_PATHS = (
    "AGENTS.md", "CLAUDE.md", "GEMINI.md", "WARP.md", ".claude/agents", ".claude/skills", ".claude/commands",
    ".cursor/rules", ".cursorrules", ".github/copilot-instructions.md", ".github/instructions", ".windsurf/rules",
    ".windsurfrules", ".clinerules", ".roo", ".kilocode", ".junie", ".rules",
)
# Settings and MCP configurations: read for downloads piped into an interpreter only.
CONFIG_PATHS = (".mcp.json", ".cursor/mcp.json", ".vscode/mcp.json", ".gemini/settings.json", ".codex/config.toml",
                ".codex/hooks.json", ".claude/settings.json", ".claude/settings.local.json")
MANAGED_FILES = ("AGENTS.md", "CLAUDE.md")
# The characters that make a finding. The byte order mark is one only inside the text; the two joiners are warnings.
HIDDEN = re.compile("[\U000e0000-\U000e007f\u202a-\u202e\u2066-\u2069\u200b-\u200f\u061c\u2060\ufeff]")
HIDDEN_NAMES = {
    0x200B: "zero width space", 0x200C: "zero width non-joiner", 0x200D: "zero width joiner",
    0x200E: "left-to-right mark", 0x200F: "right-to-left mark", 0x061C: "Arabic letter mark", 0x2060: "word joiner",
    0xFEFF: "byte order mark inside the text",
}
# The tag sequences of the flags of England, Scotland and Wales are emoji; no other tag text is.
FLAG_BASE = "\U0001F3F4"
FLAG_CANCEL = "\U000e007f"
FLAG_SUBDIVISIONS = frozenset({"gbeng", "gbsct", "gbwls"})
# The scripts whose words are written with a zero width joiner or non-joiner: Arabic and Persian, and the Indic scripts.
JOINER_SCRIPTS = frozenset({"ARABIC", "DEVANAGARI", "BENGALI", "GURMUKHI", "GUJARATI", "ORIYA", "TAMIL", "TELUGU",
                            "KANNADA", "MALAYALAM", "SINHALA"})
ESCAPED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def _words(text: str) -> frozenset:
    return frozenset(text.split())


_NEGATIONS = _words("not never no don't dont doesn't cannot can't ne pas jamais")
_VERBS = _words("ignore disregard forget override ignorer ignorez oublie oubliez oublier outrepasse outrepassez")
_NOUNS = _words("instructions instruction rules rule guidelines directives prompt prompts constraints guardrails "
                "restrictions policies règles règle consignes consigne directive contraintes")
_EARLIER = _words("previous prior above earlier preceding former system original initial précédentes précédents "
                  "précédente antérieures dessus préalables initiales")
_YOURS = _words("your tes vos votre ton ta")
_USER = _words("user human person operator owner developer maintainer requester utilisateur personne humain "
               "opérateur propriétaire développeur mainteneur demandeur")
_PRONOUN = _words("this it that these them")
_TELL = _words("tell show reveal mention disclose inform notify let say")
_TELL_FR = _words("dis dites dire montre montrez montrer révèle révélez révéler mentionne mentionnez mentionner cache "
                  "cachez cacher divulgue divulguez divulguer signale signalez signaler informe informez informer "
                  "préviens prévenez prévenir")
_INFORMING = _words("telling informing notifying alerting warning showing mentioning informer prévenir avertir "
                    "alerter signaler dire montrer")
# Each formula: the words it needs in order, how many other words may stand before each of them, and whether a negation
# just before the first word makes it the opposite ("do not ignore the rules above" is a rule, not an attack). A
# formula that starts with its own negation ("do not tell the user about this") cannot be negated.
OVERRIDE_FORMULAS = (
    ((_VERBS, _EARLIER | _YOURS, _NOUNS), (3, 3), True),                       # ignore all previous instructions
    ((_VERBS, _NOUNS, _EARLIER), (3, 3), True),                                # disregard the rules above
    ((_VERBS, _words("everything anything tout"), _words("above before earlier previously dessus avant")),
     (1, 1), True),                                                            # forget everything above
    ((_words("not never don't dont"), _TELL, _PRONOUN, _USER), (1, 1, 3), False),   # never show it to the user
    ((_words("not never don't dont"), _TELL, _USER, _words("about of this it what know how")), (1, 2, 1), False),
    ((_words("without sans"), _INFORMING, _USER), (2, 2), True),               # without informing the user
    ((_words("hide conceal"), _PRONOUN, _words("from"), _USER), (1, 1, 2), True),
    ((_words("keep"), _PRONOUN, _words("secret hidden confidential"), _words("from"), _USER), (1, 1, 1, 2), True),
    ((_words("you tu vous"), _words("are es êtes"), _words("now maintenant désormais"),
      _words("a an the my our un une le la mon ma notre")), (0, 0, 0), True),  # you are now a pirate
    ((_words("ne"), _words("le la les lui ceci cela ça"), _TELL_FR, _words("pas jamais"), _USER), (1, 1, 1, 2), False),
    ((_words("ne"), _TELL_FR, _words("pas jamais"), _words("ceci cela ça ce le la les"), _USER), (1, 1, 1, 2), False),
)
_FORMULAS_BY_FIRST_WORD: dict[str, list] = {}
for _formula in OVERRIDE_FORMULAS:
    for _first in _formula[0][0]:
        _FORMULAS_BY_FIRST_WORD.setdefault(_first, []).append(_formula)
# A word with its inner apostrophes, at most two: the letters of any script, never digits or underscores.
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+){0,2}")
_ELISION = frozenset({"l", "d", "j", "n", "s", "c", "m", "t", "qu", "jusqu", "lorsqu"})
_PIPE = re.compile(r"(?<!\|)\|(?!\|)")
_EVAL = re.compile(r"\beval\s{1,8}[\"']?(?:\$\(|`)\s{0,8}(?:curl|wget|iwr|irm)\b", re.IGNORECASE)
_IEX = re.compile(r"\biex[\s(]{0,8}(?:iwr|irm|invoke-webrequest|invoke-restmethod)\b", re.IGNORECASE)
_INTERPRETER = re.compile(r"(?:sh|bash|zsh|dash|ksh|python[0-9.]*|pwsh|powershell|iex)(?:\.exe)?")
_FETCHERS = _words("curl wget iwr irm invoke-webrequest invoke-restmethod base64")
_WRAPPERS = _words("sudo env doas command exec nohup time")
_POWERSHELL = _words("powershell powershell.exe pwsh pwsh.exe")
_TRIM = "\"'`,;(){}[]<>$"


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


def _visible(text: str) -> str:
    """The text with each control or invisible character written <U+XXXX>; a long run is shown by its first one."""
    parts = [(f"<U+{ord(char):04X}>", True) if unicodedata.category(char) in ESCAPED_CATEGORIES or HIDDEN.match(char)
             else (" " if char == "\t" else char, False) for char in text]
    shown = []
    for escaped, group in groupby(parts, key=lambda part: part[1]):
        pieces = [piece for piece, _ in group]
        shown.append("".join(pieces[:3]) + (f"<+{len(pieces) - 3} more>" if escaped and len(pieces) > 3 else "")
                     if escaped else "".join(pieces))
    return "".join(shown)


def _excerpt(line: str, start: int) -> str:
    """The words around a match, short and safe to print: [redacted] when the line looks like a credential."""
    if looks_like_credential(line[max(0, start - CREDENTIAL_REACH):start + CREDENTIAL_REACH]):
        return "[redacted]"
    begin, end = max(0, start - EXCERPT_BEFORE), start + EXCERPT_AFTER
    shown = _visible(line[begin:end]).strip()
    return ("..." if begin else "") + shown[:EXCERPT_MAX] + ("..." if end < len(line) or len(shown) > EXCERPT_MAX else "")


def _finding(code: str, level: str, message: str, path: str, line: int | None, excerpt: str | None = None) -> dict:
    found = {"code": code, "level": level, "message": message, "path": path, "line": line}
    if excerpt is not None:
        found["excerpt"] = excerpt
    return found


def _is_tag(char: str) -> bool:
    return "\U000e0000" <= char <= "\U000e007f"


def _flag_tags(line: str, index: int) -> bool:
    """Whether the tag character at index belongs to the flag of England, Scotland or Wales."""
    low = index
    while low > 0 and index - low < 8 and _is_tag(line[low - 1]):
        low -= 1
    if low == 0 or line[low - 1] != FLAG_BASE:
        return False
    high = index
    while high + 1 < len(line) and high - index < 8 and _is_tag(line[high + 1]):
        high += 1
    run = line[low:high + 1]
    return run[-1] == FLAG_CANCEL and "".join(chr(ord(char) - 0xE0000) for char in run[:-1]) in FLAG_SUBDIVISIONS


def _pictographic(char: str) -> bool:
    point = ord(char)
    return 0x1F000 <= point <= 0x1FFFF or 0x2190 <= point <= 0x2BFF or point == 0xFE0F or unicodedata.category(char) == "So"


def _script(char: str) -> str:
    return unicodedata.name(char, "").split(" ", 1)[0]


def _joins_legitimately(line: str, index: int) -> bool:
    """A joiner between two emoji, or between two letters of a script that is written with it."""
    before, after = line[index - 1] if index else "", line[index + 1] if index + 1 < len(line) else ""
    if not before or not after:
        return False
    return (_pictographic(before) and _pictographic(after)) or (
        _script(before) in JOINER_SCRIPTS and _script(after) in JOINER_SCRIPTS)


def _verdict(line: str, index: int, first_line: bool) -> str | None:
    char = line[index]
    if char == "\ufeff":
        return None if first_line and index == 0 else "error"
    if char in "\u200c\u200d":
        return None if _joins_legitimately(line, index) else "warning"
    if _is_tag(char) and _flag_tags(line, index):
        return None
    return "error"


def _hidden_name(point: int) -> str:
    if 0xE0000 <= point <= 0xE007F:
        return "tag character"
    if 0x202A <= point <= 0x202E or 0x2066 <= point <= 0x2069:
        return "bidirectional control"
    return HIDDEN_NAMES[point]


def _hidden_in_line(line: str, number: int, relative: str) -> dict | None:
    counts: dict[int, int] = {}
    level, start = None, None
    for match in HIDDEN.finditer(line):
        verdict = _verdict(line, match.start(), number == 1)
        if verdict is None:
            continue
        counts[ord(match.group())] = counts.get(ord(match.group()), 0) + 1
        level = "error" if "error" in (verdict, level) else "warning"
        start = match.start() if start is None else start
    if not counts:
        return None
    listed = [f"U+{point:04X} {_hidden_name(point)}" + (f" x{n}" if n > 1 else "")
              for point, n in list(counts.items())[:5]]
    more = f" and {len(counts) - 5} more kinds" if len(counts) > 5 else ""
    return _finding("hidden-character", level, f"Hidden character in this line: {'; '.join(listed)}{more}.",
                    relative, number, _excerpt(line, start))


def _tokens(line: str) -> list[tuple[str, int]]:
    """The words of a line in lower case, each with where it starts. The elided article or pronoun of a French word
    (l'utilisateur, n'oubliez) is split off: n' is the negation ne."""
    words = []
    for match in _WORD.finditer(line):
        word = match.group().casefold().replace("’", "'")
        head, quote, rest = word.partition("'")
        if quote and head in _ELISION:
            if head == "n":
                words.append(("ne", match.start()))
            words.append((rest, match.start()))
        else:
            words.append((word, match.start()))
    return words


def _follows(words: list[str], first: int, formula: tuple) -> bool:
    slots, gaps, _ = formula
    index = first
    for slot, gap in zip(slots[1:], gaps):
        for later in range(index + 1, min(len(words), index + 2 + gap)):
            if words[later] in slot:
                index = later
                break
        else:
            return False
    return True


def _override_start(line: str) -> int | None:
    """Where the first formula that cancels the rules or hides an action from the person starts, or None."""
    tokens = _tokens(line)
    words = [word for word, _ in tokens]
    for index, word in enumerate(words):
        for formula in _FORMULAS_BY_FIRST_WORD.get(word, ()):
            if formula[2] and any(earlier in _NEGATIONS for earlier in words[max(0, index - 3):index]):
                continue
            if _follows(words, index, formula):
                return tokens[index][1]
    return None


def _bare(word: str) -> str:
    """The program a word names: without quotes, brackets and folder, in lower case; a link names none."""
    return "" if "://" in word else word.strip(_TRIM).rsplit("/", 1)[-1].lower()


def _runs_code(words: list[str]) -> bool:
    """Whether the first command of a pipeline segment is an interpreter, after sudo, env and their options."""
    first = next((word for word in words if _bare(word) not in _WRAPPERS and not word.startswith("-")
                  and "=" not in word), "")
    return bool(_INTERPRETER.fullmatch(_bare(first)))


def _piped_into_interpreter(line: str) -> tuple[int, str] | None:
    seen, offset, start = False, 0, 0
    for segment in _PIPE.split(line):
        words = segment.split()
        if seen and _runs_code(words):
            return start, "a download or a decoded text piped into an interpreter"
        if not seen and any(_bare(word) in _FETCHERS for word in words):
            seen, start = True, offset
        offset += len(segment) + 1
    return None


def _encoded_powershell(line: str) -> int | None:
    words = line.split()
    for index, word in enumerate(words):
        if _bare(word) in _POWERSHELL:
            for later in words[index + 1:index + 9]:
                option = later.lower()
                if option.startswith("-e") and (option == "-ec" or "-encodedcommand".startswith(option)):
                    return line.lower().find(_bare(word))
    return None


def _remote_execution(line: str) -> tuple[int, str] | None:
    """Where a command that runs downloaded or encoded code starts, and which kind, or None."""
    lowered = line.lower()
    if "|" in line and (found := _piped_into_interpreter(line)):
        return found
    if "eval" in lowered and (match := _EVAL.search(line)):
        return match.start(), "eval of a download"
    if "iex" in lowered and (match := _IEX.search(line)):
        return match.start(), "Invoke-Expression of a download"
    if "invoke-expression" in lowered:
        return lowered.find("invoke-expression"), "Invoke-Expression"
    if ("powershell" in lowered or "pwsh" in lowered) and (start := _encoded_powershell(line)) is not None:
        return start, "an encoded PowerShell command"
    return None


def _cap(findings: list[dict], relative: str) -> list[dict]:
    """At most MAX_PER_CODE findings of a code for one file, then one that counts the rest."""
    kept = []
    for code in dict.fromkeys(item["code"] for item in findings):
        same = [item for item in findings if item["code"] == code]
        kept += same[:MAX_PER_CODE]
        if len(same) > MAX_PER_CODE:
            level = min((item["level"] for item in same), key=LEVELS.index)
            kept.append(_finding(code, level, f"{len(same) - MAX_PER_CODE} more lines of this file have this finding; "
                                              f"the first {MAX_PER_CODE} are listed.", relative, None))
    return kept


def _analyse(relative: str, text: str, config: bool) -> list[dict]:
    block = managed_block_lines(text) if relative in MANAGED_FILES else None
    found = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        if not config:
            if hidden := _hidden_in_line(line, number, relative):
                found.append(hidden)
            if not (block and block[0] <= number <= block[1]) and (start := _override_start(line)) is not None:
                found.append(_finding(
                    "instruction-override", "warning",
                    "This line asks the agent to drop its rules or to hide an action from the person.",
                    relative, number, _excerpt(line, start)))
        if (remote := _remote_execution(line)) is not None:
            found.append(_finding("remote-execution", "warning", f"This line runs code as it arrives ({remote[1]}).",
                                  relative, number, _excerpt(line, remote[0])))
    return _cap(found, relative)


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
    findings, read, spent = [], 0, 0
    for relative, real, config in collector.files:
        text, reason = _load(real, spent)
        if reason:
            collector.skip(relative, reason)
        if text is None:
            continue
        spent += len(text)
        read += 1
        findings += _analyse(relative, text, config)
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
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
MAX_MATCHED = 500  # characters of a launch or an address that are compared with the registry
DISTINCT_PATH = 20  # an address whose host is a placeholder is recognised only by a path at least this long
CI_ONLY = "the CI check (guard --ci) is the only barrier"
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


def _registry_index(tools: dict) -> list[tuple[str, dict, list]]:
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
    return _visible(f"{parts.scheme}://{host}{f':{port}' if port else ''}{parts.path}" + ("?..." if parts.query else ""))


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


def _line_of(text: str, *needles: str) -> int | None:
    for number, line in enumerate(text.split("\n"), start=1):
        if any(needle in line for needle in needles):
            return number
    return None


def _server(name: str, spec: dict, relative: str, host: str, text: str, index: list) -> tuple[dict, list[dict]]:
    """One configured MCP server as the inventory shows it, and the findings about it."""
    command = spec["command"] if isinstance(spec.get("command"), str) else ""
    args = [arg for arg in spec["args"] if isinstance(arg, str)] if isinstance(spec.get("args"), list) else []
    url = next((spec[key] for key in ("url", "httpUrl") if isinstance(spec.get(key), str)), "")
    declared = spec["type"] if isinstance(spec.get("type"), str) else ""
    transport = ({"sse": "sse", "http": "http", "streamable-http": "http"}.get(declared)
                 or ("remote" if url else "stdio" if command else "unknown"))
    package = _package_of(command, args) if command and not url else None
    pinned, why = _pin(*package) if package else (None, "")
    entry = {"name": _visible(name), "file": relative, "host": host, "transport": transport,
             "launch": _show_address(url) if url else _visible(" ".join([redact_credentials(command), *_mask(args)]).strip()),
             "pinned": pinned}
    line = _line_of(text, f"[mcp_servers.{name}]", f'[mcp_servers."{name}"]') if relative.endswith(".toml") \
        else _line_of(text, json.dumps(name))
    lookup = {"package": (package[0], _canonical(*package)) if package else None, "args": args,
              "program": _program(command), "address": _address(url) if url and len(url) < MAX_MATCHED else ""}
    entry["registry"] = None if len(" ".join(args)) > MAX_MATCHED else _registry_match(lookup, index)
    findings = []
    if pinned is False:
        what = {"npm": "npm package", "pypi": "Python package", "docker": "Docker image"}[package[0]]
        findings.append(_finding(
            "mcp-unpinned", "warning", f'MCP server "{_visible(name)[:60]}" runs the {what} {_visible(package[1])[:80]} '
            f"with {why}: pin one exact version, or an image digest, so that what runs is what was reviewed.",
            relative, line))
    if url:
        try:
            scheme, host_name = urlsplit(url).scheme, urlsplit(url).hostname
        except ValueError:
            scheme, host_name = "", None
        if scheme == "http" and host_name is not None and host_name not in LOCAL_HOSTS:
            findings.append(_finding(
                "mcp-insecure-transport", "error", f'MCP server "{_visible(name)[:60]}" connects to {_show_address(url)}: an http '
                "address is not encrypted. Use https, or a server on localhost.", relative, line))
    return entry, findings


def _setting(relative: str, text: str, needle: str, message: str) -> dict:
    return _finding("permissive-setting", "warning", f"Permissive setting: {message}.", relative, _line_of(text, needle))


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


def discover(root: Path, profile: dict | None = None, tools: dict | None = None) -> dict:
    """The agent tools the files of a project show, its MCP servers, and the findings about them and about the
    permissive settings. The profile gives the guard and the host; tools is the registry (the bundled one by default)."""
    profile, configs = profile or {}, _Configs(root)
    servers, found, index = [], [], None
    for relative, key, host in MCP_FILES:
        data, text = configs.get(relative)
        listed = data.get(key) if data and isinstance(data.get(key), dict) else {}
        for name, spec in sorted((str(name), spec) for name, spec in listed.items() if isinstance(spec, dict)):
            index = _registry_index(load_tools() if tools is None else tools) if index is None else index
            entry, findings = _server(name, spec, relative, host, text, index)
            servers.append(entry)
            found += findings
    found += _permissive(configs)
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
            found.append(_finding(
                "surface-uncovered", "warning" if profile.get("guard") == "enforce" else "note",
                f"{tool['id']}: {', '.join(files)} present, and {coverage['detail'].rstrip('.')}.", files[0], None))
    return {"surfaces": present, "mcp_servers": sorted(servers, key=lambda item: (item["file"], item["name"])),
            "findings": sorted(found, key=_order), "skipped": configs.skipped}


def scan_report(root: Path, profile: dict | None = None, tools: dict | None = None) -> dict:
    """What `host scan` prints with --json: the inventory, the findings of both analyses in one list, the sources."""
    content, inventory = scan(root), discover(root, profile, tools)
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
        lines.append(f"  {item['name']} ({_visible(item['file'])}): {launch}; {registry}" + (f"; {pin}" if pin else ""))
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
        where = _visible((first["path"] or "") + (f":{first['line']}" if first["line"] else ""))
        lines.append(f"  {worst:<7} {code} x{len(items)}  {where}")
    if scanned["skipped"]:
        first = scanned["skipped"][0]
        lines.append(f"Not read: {plural(len(scanned['skipped']), 'file')} "
                     f"(first: {_visible(first['path'])}, {_visible(first['reason'])}).")
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
