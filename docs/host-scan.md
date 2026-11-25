# Scan the files an agent reads

An agent reads `AGENTS.md`, the agents, Skills and commands of `.claude/`, the rules of Cursor and the instructions of Copilot as orders, without questioning them. A character nobody sees, or a sentence that tells it to drop its rules, passes a human review. `openguildkit check` verifies that the instructions match the profile and `sensitive.py` looks for credentials; neither reads the rest of these files. `openguildkit host scan` does.

```bash
openguildkit host scan                 # a few lines: the totals, one line per code, the command for the rest
openguildkit host scan --json          # every finding with its path, line and excerpt, for a script
openguildkit host scan --strict        # exit 1 on any finding, not only on an error
```

The command works offline and in read-only mode. It opens no network connection, starts no process, writes no file and runs nothing it reads. It needs no initialized project.

## What it reads

| Path | Read for |
|---|---|
| `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `WARP.md`, `.cursorrules`, `.windsurfrules`, `.rules`, `.github/copilot-instructions.md` | all three codes |
| `.claude/agents/`, `.claude/skills/`, `.claude/commands/`, `.cursor/rules/`, `.github/instructions/`, `.windsurf/rules/`, `.roo/`, `.kilocode/`, `.junie/`, `.clinerules` (a file or a folder) | all three codes, every file under the folder |
| `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, `.gemini/settings.json`, `.codex/config.toml`, `.codex/hooks.json`, `.claude/settings.json`, `.claude/settings.local.json` | `remote-execution` only |

Only the files at these places are read: an `AGENTS.md` in a subfolder is not. The reading is bounded like the machine checks of the rule packs (`rule_checks.py`):

- a file larger than 1 MB is not read, and neither are the files past the 200th or past 20 MB in all;
- a symbolic link that leaves the project is not followed, and a link that stays in the project is read once, under the first name in alphabetical order (`CLAUDE.md` linked to `AGENTS.md` is `AGENTS.md`);
- `.git`, `node_modules`, `.venv` and `.openguildkit/tasks` are not read, and neither is a file that looks binary.

Each file left alone is listed in `scanned.skipped` of the JSON with the reason, and the text output counts them: a scan that skips a file says so.

## What it reports

Each finding has a `code`, a `level` (`error`, `warning` or `note`), a `message`, a `path` relative to the project and written with `/`, a `line`, and an `excerpt`. In the excerpt the control and invisible characters are written `<U+XXXX>`, never as the character, and a line that looks like a credential (the detector of `sensitive.py`) is replaced by `[redacted]`: a secret never appears in the output. A file with more than 25 findings of one code lists the first 25 and one more finding that counts the rest.

| Code | Level | What it means |
|---|---|---|
| `hidden-character` | error | The line holds a character a person does not see: a Unicode tag (U+E0000 to U+E007F), a bidirectional control (U+202A to U+202E, U+2066 to U+2069), a directional mark (U+200E, U+200F, U+061C), a zero width space (U+200B), a word joiner (U+2060), or a byte order mark (U+FEFF) that is not the first character of the file. |
| `hidden-character` | warning | The line holds a zero width non-joiner (U+200C) or joiner (U+200D) that is neither inside an emoji sequence nor between two letters of Arabic, Persian or an Indic script, which are written with them. |
| `instruction-override` | warning | The line asks the agent to ignore or forget the previous instructions or rules, to hide an action or a fact from the user, to act without informing the person, or tells it "you are now" a role (the same in French: "ignore les instructions précédentes", "ne le dis pas à l'utilisateur", "sans en informer la personne", "tu es maintenant un..."). The block that OpenGuildKit manages in `AGENTS.md` and `CLAUDE.md` is not read for this code; it is read for the other two. |
| `remote-execution` | warning | The line runs code as it arrives: `curl`, `wget`, `iwr` or `irm` piped into `sh`, `bash`, `zsh`, `python`, `pwsh` or `iex`; `base64 -d` piped into an interpreter; `eval "$(curl ...)"`; `powershell -enc`; `Invoke-Expression`. |

What is never a finding: a no-break space (U+00A0), a narrow no-break space (U+202F), a thin space (U+2009), accents, curly quotes, a byte order mark at the start of a file, a zero width joiner in an emoji such as a family or a flag, and the three flag sequences of England, Scotland and Wales.

A `warning` is a line to read, not proof of an attack: "Never ignore the rules above" is a rule, and the matching skips a formula that follows a negation ("do not", "never", "ne jamais"). A sentence like "Do not tell the user about this" in a file that asks for it is flagged on purpose, whoever wrote it.

## Exit code and JSON

The exit code is 1 when a finding is an `error`, and with `--strict` when there is any finding; 0 otherwise. `--json` prints:

```json
{
  "findings": [
    {"code": "hidden-character", "level": "error", "message": "Hidden character in this line: U+200B zero width space.",
     "path": ".claude/commands/ship.md", "line": 1, "excerpt": "x<U+200B>y"}
  ],
  "scanned": {"files": 2, "skipped": []}
}
```

## What it does not prove

- It blocks nothing. No hook of any agent runs it: a person runs it, or CI does. A clean scan says that these patterns are absent from these files, not that the files are safe.
- It does not detect every injection. Matching is by a short list of words in English and French, in the order and the distance the list names; a sentence in another language, another wording, a text split over lines or an instruction hidden in an image passes. Hidden characters outside the list above (soft hyphen, variation selectors, invisible mathematical operators) are not flagged. A `bash <(curl ...)` or `sh -c "$(curl ...)"` is not detected as `remote-execution`.
- It reads files, not what an agent does with them. It does not check that a command a file asks for is safe, only that a line has this shape.
- It does not read what a person puts elsewhere: `README.md`, source code, the files of a subfolder, the user-level settings of an agent in the home folder.
- A settings file is read as text, line by line, for `remote-execution` only: it does not read hooks as structured data.
