"""The `profile` commands: parse a change and confirm at a terminal what weakens a protection; the change itself goes
through `profile_changes.py`.

Each change goes through profile_changes.write_change, the path the web page saves through too. What weakens a
protection is the person's decision: here it needs an interactive terminal and the typed confirmation (_confirm).
Entry: add_parser, run.
Tests: tests/test_profile_commands.py, tests/test_profile_reference.py, tests/test_audit_log.py,
tests/test_gemini_host.py, tests/test_org_catalog.py, tests/test_requester.py, tests/test_rule_decline.py,
tests/test_short_lane.py.
"""

import sys
from pathlib import Path

from . import incident, requester
from .cli_surface import add_by
from .command import Command
from .doc_links import doc_link
from .lock import project_catalog
from .profile_changes import Weakening, export_answers, report_change, voided_note, write_change
from .profile_edits import LIST_FIELDS, SET_FIELDS, changed_profile, rule_argument
from .project import load_profile
from .shell import shell_word
from .storage import print_json
from .terminal import typed


def add_parser(commands) -> None:
    profile = commands.add_parser(
        "profile", help="Change the project profile after setup: adopt or decline a pattern, add or remove a pack, "
                        "role, tool, check or board, set the host, guard or research policy.")
    actions = profile.add_subparsers(dest="profile_action", required=True)
    for name, text in (("adopt", "Adopt a pattern or regulation: it becomes active. adopt rule PACK/RULE restores a "
                                 "declined rule."),
                       ("decline", "Decline a pattern or regulation: it is not active and not proposed again. decline "
                                   "rule PACK/RULE sets one rule aside: no task is asked it.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("pattern", metavar="PATTERN", help="Pattern ID, from openguildkit recommend or patterns; "
                                                                "or the word rule, followed by PACK/RULE.")
        command.add_argument("rule", nargs="?", metavar="PACK/RULE",
                             help="After the word rule: one rule, as AGENTS.md lists it under its pack.")
    for name, text in (("add", "Add entries to a list of the profile."), ("remove", "Remove entries from a list.")):
        command = actions.add_parser(name, help=text)
        command.add_argument("field", choices=sorted(LIST_FIELDS), help="The list to change.")
        command.add_argument("values", nargs="+", metavar="VALUE", help="IDs, tool names or check commands.")
    setter = actions.add_parser(
        "set", help="Set the host, guard, research policy, sector, approval mode, waiver policy, whether every rule "
                    "is asked, the paths of the short lane, whether the requester of a task may approve it, the "
                    "freeze of the project, the longest age of an approval, who clears a board's blockers (approver-roles), "
                    "the paths closed to the agents (restricted-paths), or a setup answer.")
    setter.add_argument("field", choices=sorted(SET_FIELDS), help="The setting to change.")
    setter.add_argument("value", help="Its new value (light-paths: a folder or file glob such as 'docs/**', or none).")
    setter.add_argument("more", nargs="*", metavar="PATH",
                        help="light-paths and restricted-paths: more paths. approver-roles: the people of the role (VALUE is "
                             "the board), or none.")
    setter.add_argument("--signers", metavar="PATH",
                        help="approval signed: the allowed signers file, a path inside the project.")
    setter.add_argument("--approver", action="append", metavar="NAME",
                        help="approval signed: a person whose signature approves a task; repeat for each.")
    setter.add_argument("--allowed-by", action="append", metavar="NAME",
                        help="waivers allowed: a person who may waive a blocker; repeat for each.")
    setter.add_argument("--max-days", type=int, metavar="DAYS",
                        help="waivers allowed: how long a waiver may last, 1 to 366 days.")
    for name, command in actions.choices.items():
        add_by(command, required=True)
        # Only an adopted or declined pattern shows its reason in AGENTS.md and preview (profile_decision_lines).
        shown = " and shown in AGENTS.md and preview" if name in ("adopt", "decline") else ""
        command.add_argument("--reason", required=True, help="Why, in one line; recorded in the profile history "
                                                             f"(.openguildkit/project.json){shown}.")
    # Reading only: no --by or --reason, since nothing is written.
    actions.add_parser("export", help="Print the setup answers that give another repository this profile's patterns, "
                                      "packs, boards and settings, for openguildkit init --answers FILE there.")


def _confirm(change: str, target: str, weakened: list[tuple[str, list[str]]], voided: list[str]) -> None:
    """A change that weakens a protection is typed by the person at a terminal, never run by an agent."""
    what = "; ".join(text for text, _ in weakened)
    refusal = Weakening(f"'{change}' weakens a protection ({what}): it is the person's decision. Ask them to run the "
                        f"same command at an interactive terminal.{voided_note(voided)} Nothing was written.", weakened)
    typed(target, f"'{change}' weakens a protection of the project ({what}).{voided_note(voided)} Type {target} to "
          "confirm: ", refusal=refusal, cancelled="Profile change cancelled. Nothing was written.")


def _target(args) -> str:
    """What the person types to confirm a change that weakens a protection: the pattern, the values given."""
    if args.profile_action in ("adopt", "decline"):
        rule = rule_argument(args)
        return args.pattern if rule is None else rule.strip().removeprefix("rule:")
    return " ".join([args.value, *args.more] if args.profile_action == "set" else args.values)


# What profile export never carries, whatever the profile holds: in the words of its last line.
LEFT_ASIDE = ("the project name", "the history of changes", "people's names", "the signers file",
              "component paths", "check commands", "the host's tool connections")


def export(args, state: Path) -> int:
    """Print the setup answers on standard output, and on standard error what stays behind and what follows."""
    catalog = project_catalog(args, state)
    profile = load_profile(state, catalog)
    answers, steps = export_answers(profile, catalog)
    print_json(answers)
    print(f"Left aside: {', '.join(LEFT_ASIDE)}.", file=sys.stderr)
    for step in steps:
        print(step, file=sys.stderr)
    print("Next: in the other repository, openguildkit init --answers answers.json, with this output saved as "
          "answers.json (openguildkit profile export > answers.json).", file=sys.stderr)
    return 0


def run(command: Command) -> int:
    """Apply one profile command, rewrite the instructions and the catalog lock, and say what follows."""
    args, root, state = command.args, command.root, command.state
    if args.profile_action == "export":
        return export(args, state)
    target = _target(args)
    updated, record, catalog = write_change(
        root, state, args, lambda profile, catalog: changed_profile(profile, args, catalog),
        args.by, args.reason, lambda change, weakened, voided: _confirm(change, target, weakened, voided))
    host_settings = args.profile_action == "set" and args.field in ("host", "guard", "research", "approval",
                                                                    "restricted-paths")
    report_change(state, updated, record, catalog, host_settings)
    rule = rule_argument(args) if args.profile_action in ("adopt", "decline") else None
    if rule is not None:
        name = record["change"].split(" ", 2)[2]
        print(f"Tasks consulted from now on are not asked {name}; to restore it: openguildkit profile adopt rule "
              f"{name} --by INITIALS --reason WHY." if args.profile_action == "decline" else
              f"Rule {name} is asked again of the tasks it concerns, from their next consultation.")
    if updated.get("light_paths") and args.profile_action == "set" and args.field == "light-paths":
        print(f'Short lane: openguildkit task new "BRIEF" --id ID --lane light --paths '
              f'{shell_word(updated["light_paths"][0])} ({doc_link("docs/workflow.md", "short-lane")}).')
    if args.profile_action == "set" and args.field == "freeze" and incident.frozen(updated) \
            and updated.get("guard", "off") == "off":
        print("Note: the guard is off, so the freeze stops nothing until it is on: openguildkit profile set guard "
              "enforce --by INITIALS --reason WHY.")
    if requester.active(updated) and args.profile_action == "set" and args.field == "separate-requester":
        print(f'Requester and approver: openguildkit task new "BRIEF" --requested-by NAME; another person approves the '
              f"task ({requester.section()}).")
    return 0


