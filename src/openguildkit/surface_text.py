"""Reads one instruction or configuration file for what a person does not see: hidden characters, sentences that cancel
the rules, downloads piped into an interpreter.

Entry: visible_text, scan_finding, analyse_text, line_of, LEVELS
Tests: tests/test_host_scan.py, tests/test_host_surfaces.py, tests/test_allow_list_scan.py
"""

import re
import unicodedata
from itertools import groupby

from .project_instructions import managed_block_lines
from .sensitive import looks_like_credential

MAX_PER_CODE = 25  # findings of one code listed for one file; the rest is counted in one more finding
EXCERPT_BEFORE, EXCERPT_AFTER, EXCERPT_MAX = 40, 120, 240
CREDENTIAL_REACH = 1000  # characters around a match that are searched for a credential before an excerpt is shown


LEVELS = ("error", "warning", "note")


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


def visible_text(text: str) -> str:
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
    shown = visible_text(line[begin:end]).strip()
    return ("..." if begin else "") + shown[:EXCERPT_MAX] + ("..." if end < len(line) or len(shown) > EXCERPT_MAX else "")


def scan_finding(code: str, level: str, message: str, path: str, line: int | None, excerpt: str | None = None) -> dict:
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
    return scan_finding("hidden-character", level, f"Hidden character in this line: {'; '.join(listed)}{more}.",
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
            kept.append(scan_finding(code, level, f"{len(same) - MAX_PER_CODE} more lines of this file have this finding; "
                                              f"the first {MAX_PER_CODE} are listed.", relative, None))
    return kept


def analyse_text(relative: str, text: str, config: bool) -> list[dict]:
    block = managed_block_lines(text) if relative in MANAGED_FILES else None
    found = []
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        if not config:
            if hidden := _hidden_in_line(line, number, relative):
                found.append(hidden)
            if not (block and block[0] <= number <= block[1]) and (start := _override_start(line)) is not None:
                found.append(scan_finding(
                    "instruction-override", "warning",
                    "This line asks the agent to drop its rules or to hide an action from the person.",
                    relative, number, _excerpt(line, start)))
        if (remote := _remote_execution(line)) is not None:
            found.append(scan_finding("remote-execution", "warning", f"This line runs code as it arrives ({remote[1]}).",
                                  relative, number, _excerpt(line, remote[0])))
    return _cap(found, relative)


def line_of(text: str, *needles: str) -> int | None:
    for number, line in enumerate(text.split("\n"), start=1):
        if any(needle in line for needle in needles):
            return number
    return None
