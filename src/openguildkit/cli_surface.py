"""What a person sees of the CLI before it runs: the help pages, the options every command shares, and where the
global options may be typed.

Entry: polish, add_by, hoist_global_options
Tests: tests/test_cli_surface.py
"""

import argparse
import sys
from pathlib import Path

from .doc_links import doc_link

# The root page lists the commands under these headings, in this order; a command named nowhere fails
# tests/test_cli_surface.py, so that none is left under the wrong heading.
GROUPS = (
    ("Set up a project", ("init", "detect", "recommend", "preview", "sync", "check", "update", "profile", "features",
                          "org-catalog", "host", "integrations")),
    ("Take a task to its closing", ("task", "guard", "deliverable", "docs", "alerts", "market", "storybook", "trace",
                                    "audit", "evidence")),
    ("Browse the catalog", ("catalog", "references", "patterns", "brains", "tools")),
    ("Connect other tools", ("ui", "mcp", "projects", "ci-check", "completion")),
)
COMMAND_ORDER = [name for _, names in GROUPS for name in names]
# The options of the root that may also follow the command: `openguildkit check --project DIR`.
FORMATS = ("text", "sarif")
GLOBAL_OPTIONS = ("--project", "--policy-repo", "--policy-commit")

# The placeholder of the options that come back in many commands; any other takes the name of its option.
PLACEHOLDERS = {"--reason": "WHY", "--task": "TASK", "--id": "ID", "--board": "BOARD", "--url": "URL", "--until": "DATE",
                "--since": "DATE", "--date": "DATE", "--commit": "SHA", "--policy-commit": "SHA", "--every-days": "DAYS",
                "--file": "FILE", "--answers": "FILE"}

BY_HELP = "Your initials or team handle, not your full name: it is committed."
BY_RULE = ("`--by` is committed with the profile, the task or the decision: write your initials or a team handle, "
           "not a name or an address")


class VersionAction(argparse.Action):
    """Print the version and exit; reading the package metadata is slow, so only --version pays for it."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings, dest=dest, default=default, nargs=0,
                         help=help or "show program's version number and exit")

    def __call__(self, parser, namespace, values, option_string=None):
        from .lock import package_version

        print(f"openguildkit {package_version()}")
        parser.exit()


def format_option(parser: argparse.ArgumentParser, what: str) -> None:
    """The --format option of the commands that can print SARIF: `what` says what is printed."""
    parser.add_argument("--format", choices=FORMATS, default="text",
                        help=f"{what} as SARIF 2.1.0 for code scanning instead of text.")


class RootHelp(argparse.HelpFormatter):
    """The help of the root parser: its commands under GROUPS' headings."""

    def _format_action(self, action) -> str:
        text = super()._format_action(action)
        for position, (title, names) in enumerate(GROUPS):
            if action.dest == names[0]:
                return f"{chr(10) if position else ''}  {title}:\n{text}"
        return text


def _subparsers(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    return next((action for action in parser._actions if isinstance(action, argparse._SubParsersAction)), None)


def _name_values(action: argparse.Action) -> None:
    """An option that takes a value shows what to type: a placeholder, and for a long list of choices (written three
    times over in the usage and under the option) the choices once in its help."""
    if isinstance(action, argparse._SubParsersAction) or action.metavar or not action.option_strings and not action.choices:
        return
    if action.choices:
        names = [str(choice) for choice in action.choices]
        if len(",".join(names)) > 30:
            action.metavar = action.dest.upper().replace("-", "_")
            if action.help is not argparse.SUPPRESS and names[-1] not in (action.help or ""):
                action.help = f"{action.help or ''} One of: {', '.join(names)}.".strip()
    elif action.nargs != 0:
        name = action.option_strings[0]
        action.metavar = PLACEHOLDERS.get(name) or ("PATH" if action.type is Path else action.dest.upper())


def polish(parser: argparse.ArgumentParser, depth: int = 0) -> None:
    """Finish a parser tree: each command's help becomes its description, the choices of a group are named once
    (COMMAND, ACTION) instead of listed twice, and the root lists its commands by heading."""
    for action in parser._actions:
        _name_values(action)
    group = _subparsers(parser)
    if group is None:
        return
    group.metavar = "ACTION" if depth else "COMMAND"
    helps = {item.dest: item.help for item in group._choices_actions}
    for name, command in group.choices.items():
        command.description = command.description or helps.get(name)
        polish(command, depth + 1)
    if not depth:
        order = {name: place for place, name in enumerate(COMMAND_ORDER)}
        group._choices_actions.sort(key=lambda item: order.get(item.dest, len(order)))
        parser.formatter_class = RootHelp


def _initials(value: str) -> str:
    """The value of --by, which is committed: a space or an address is let through with a line that gives the rule."""
    if "@" in value or " " in value.strip():
        print(f"OpenGuildKit: {BY_RULE} ({doc_link('docs/personal-data.md')}).", file=sys.stderr)
    return value


def add_by(parser: argparse.ArgumentParser, required: bool = False) -> None:
    """The --by option of every command that records a person: one text, one placeholder, one warning."""
    parser.add_argument("--by", required=required, metavar="INITIALS", help=BY_HELP, type=_initials)


def hoist_global_options(argv: list[str]) -> list[str]:
    """argv with the root's own options moved in front of the command, so that `check --project DIR` reads as
    `--project DIR check`. The options keep their order, `--` ends the search, and a value that is not there is
    left for the parser to refuse."""
    moved, kept, words = [], [], iter(range(len(argv)))
    for index in words:
        word = argv[index]
        if word == "--":
            kept.extend(argv[index:])
            break
        name = word.partition("=")[0]
        if name not in GLOBAL_OPTIONS:
            kept.append(word)
        elif "=" in word:
            moved.append(word)
        elif index + 1 < len(argv):
            moved.extend(argv[index:index + 2])
            next(words)
        else:
            kept.append(word)
    return [*moved, *kept]
