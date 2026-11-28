"""The `completion` command and the reference of the commands (docs/cli.md), both written from the parser: scripts that
complete the commands, the options and their values in bash and zsh.

`openguildkit completion bash` and `zsh` print a script that offers the commands, the options and the values the
parser knows; `reference` is the text of docs/cli.md, which scripts/cli_reference.py writes and a test keeps current.

Entry: add_parser, run, script, reference
Tests: tests/test_completion_cli.py
"""

import argparse
import shlex

from .cli_surface import GLOBAL_OPTIONS
from .command import Command

SHELLS = ("bash", "zsh")
# The words every shell function below shares: it finds the command typed, then prints what can follow it.
FUNCTIONS = """_openguildkit_candidates() {
  local typed='' word previous='' found
  for word in "$@"; do
    found="${typed:+$typed }$word"
    if [ -n "$(_openguildkit_words "$found")" ]; then typed="$found"; fi
    previous="$word"
  done
  found="$(_openguildkit_words "=${typed} ${previous}")"
  if [ -z "$found" ]; then
    found="$(_openguildkit_words "$typed")"
    if [ -n "$typed" ]; then found="$found -h --help GLOBALS"; fi
  fi
  echo "$found"
}
"""
GLUE = {
    "bash": """_openguildkit() {
  local candidates
  candidates="$(_openguildkit_candidates "${COMP_WORDS[@]:1:COMP_CWORD-1}")"
  COMPREPLY=($(compgen -W "$candidates" -- "${COMP_WORDS[COMP_CWORD]}"))
}
complete -F _openguildkit openguildkit
""",
    "zsh": """_openguildkit() {
  local candidates
  candidates="$(_openguildkit_candidates "${(@)words[2,CURRENT-1]}")"
  compadd -- ${=candidates}
}
compdef _openguildkit openguildkit
""",
}


def add_parser(commands) -> None:
    completion = commands.add_parser("completion", help="Print the script that completes the commands, the options and "
                                     "their values in bash or zsh.")
    completion.add_argument("shell", choices=SHELLS, help="The shell to complete for.")
    completion.epilog = ('Load it with eval "$(openguildkit completion bash)" in ~/.bashrc, or, in ~/.zshrc after '
                         'compinit, eval "$(openguildkit completion zsh)".')


def run(command: Command) -> None:
    from .cli import command_parser

    print(script(command.args.shell, command_parser()), end="")


def _commands(parser: argparse.ArgumentParser, path: tuple[str, ...] = ()):
    """Every command of the parser's tree with its path: the groups and the commands that take no action."""
    yield path, parser
    group = next((action for action in parser._actions if isinstance(action, argparse._SubParsersAction)), None)
    for name, command in (group.choices.items() if group else ()):
        yield from _commands(command, (*path, name))


def _visible(parser: argparse.ArgumentParser):
    """The actions a person can type: the options and the positionals, the hidden aliases and the actions of a group left out."""
    return [action for action in parser._actions
            if action.help is not argparse.SUPPRESS and not isinstance(action, argparse._SubParsersAction)]


def _words(parser: argparse.ArgumentParser) -> list[str]:
    """What can follow a command: its actions, the choices of its positionals and its options."""
    group = next((action for action in parser._actions if isinstance(action, argparse._SubParsersAction)), None)
    found = list(group.choices) if group else []
    for action in _visible(parser):
        if action.option_strings != ["-h", "--help"]:  # Offered after every command by the function, with GLOBALS.
            found += [str(choice) for choice in action.choices or ()] if not action.option_strings else action.option_strings
    return found


def script(shell: str, parser: argparse.ArgumentParser) -> str:
    """The completion script of one shell: a table of what follows each command, the functions that read it, and the
    few lines that hand the result to the shell."""
    rows = []
    for path, command in _commands(parser):
        rows.append(f"    {shlex.quote(' '.join(path))}) echo {shlex.quote(' '.join(_words(command)))} ;;")
        for action in _visible(command):
            if action.option_strings and action.choices:
                for option in action.option_strings:
                    key = shlex.quote(f"={' '.join(path)} {option}")
                    rows.append(f"    {key}) echo {shlex.quote(' '.join(map(str, action.choices)))} ;;")
    return (f"# Completion of openguildkit for {shell}, written by `openguildkit completion {shell}`: load it with\n"
            f'# eval "$(openguildkit completion {shell})"{" after compinit" if shell == "zsh" else ""}.\n'
            "_openguildkit_words() {\n  case \"$1\" in\n" + "\n".join(rows) + "\n  esac\n}\n"
            + FUNCTIONS.replace("GLOBALS", " ".join(GLOBAL_OPTIONS)) + GLUE[shell])


def _value(action: argparse.Action) -> str:
    """What a person types for an action, written here and not by argparse, whose wording changed between versions."""
    metavar = " ".join(action.metavar) if isinstance(action.metavar, tuple) else action.metavar
    name = metavar or ("{" + ",".join(map(str, action.choices)) + "}" if action.choices else action.dest.upper())
    if action.nargs in ("*", "+"):
        name += " ..."
    return f"[{name}]" if action.nargs in ("?", "*") and not action.option_strings else name


def _line(parser: argparse.ArgumentParser, action: argparse.Action) -> str:
    """One option or positional of the reference: how it is typed, and its help."""
    help_text = parser._get_formatter()._expand_help(action) if action.help else ""
    if action.option_strings:
        name = action.option_strings[0] + ("" if action.nargs == 0 else f" {_value(action)}")
    else:
        name = _value(action)
    return f"- `{name}`" + (f": {help_text}" if help_text else "")


# What every --json output shares (#484), said once at the top of the reference.
JSON_OUTPUT = (
    "With `--json`, a command prints its answer as JSON on standard output. With `OPENGUILDKIT_JSON_ENVELOPE=1` in "
    "the environment, every answer comes in one object, `{\"schema_version\": 1, \"command\": \"task checks\", "
    "\"data\": ...}`, whose `data` is the answer printed without the variable; the default keeps the shape scripts "
    "and the web interface read. Under `--json`, an error is also JSON on standard output, with the same exit code "
    "and its line on standard error: `{\"schema_version\": 1, \"error\": {\"code\": \"OGK-TASK-004\", "
    "\"message\": ..., \"next\": ...}}`, where `code` is null for an error that has no code yet "
    "([error codes](errors.md)) and `next` is the command the message names, or null.")


def reference(parser: argparse.ArgumentParser) -> str:
    """The reference of every command, one section each, with its options and their help, as Markdown."""
    lines = ["# Command reference", "",
             "For: anyone who looks up a command or an option of the CLI, or writes a script around it.", "",
             ("Generated by `python scripts/cli_reference.py` from the parser of the CLI. Do not edit this page by "
              "hand: `tests/test_completion_cli.py` fails when it is out of date."), "",
             ("`openguildkit COMMAND --help` prints the same text for one command, and `openguildkit completion bash` "
              "or `zsh` prints a script that completes it. These options come before the command, or after it:"), ""]
    lines += [_line(parser, action) for action in _visible(parser)
              if action.option_strings and action.option_strings[0] in (*GLOBAL_OPTIONS, "--version")]
    lines += ["", "## JSON output", "", JSON_OUTPUT]
    for path, command in _commands(parser):
        if not path:
            continue
        lines += ["", f"{'#' * (len(path) + 1)} {' '.join(path)}", "", command.description or "", ""]
        lines += [_line(command, action) for action in _visible(command) if action.option_strings != ["-h", "--help"]]
        if command.epilog:
            lines += ["", command.epilog]
    return "\n".join(lines).replace("\n\n\n", "\n\n").rstrip("\n") + "\n"
