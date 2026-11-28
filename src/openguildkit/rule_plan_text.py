"""Prints the rule plan as a person reads it, for `preview` and for the confirmation `init` asks.

The plan lists the patterns with why they apply, the regulations, the packs in the order `AGENTS.md` lists them, and
the conflicts between packs.

Entry: `_print_rule_plan`
Tests: `tests/test_proportionate_setup.py`, `tests/test_command_output_budget.py`
"""

import sys

from .project import RULES_NOTE
from .storage import json_text


def _print_rule_plan(plan: dict, as_json: bool, file=None) -> None:
    file = file or sys.stdout
    if as_json:
        print(json_text(plan), end="", file=file)
        return
    if plan["patterns"]:
        print("Patterns, with why they apply and their rules", file=file)
        for pattern in plan["patterns"]:
            print(f"  {pattern['id']} ({pattern['rules']} rules): {pattern['reason']}", file=file)
        print(f"  {RULES_NOTE}", file=file)
    for regulation in plan["regulations"]:
        print(f"  {regulation['id']} asks: {regulation['asks']}", file=file)
    for entry in plan["declined"]:
        who = f" by {entry['by']} on {entry['on']}: {entry['reason']}" if "by" in entry else ""
        print(f"  Declined, not active: {entry['id']}{who}", file=file)
    print(f"{plan['rule_count']} rules in force; a task is asked only those that concern it.", file=file)
    if plan["rule_warning"]:
        print(f"Warning: {plan['rule_warning']}", file=file)
    print("Rule packs, in the order AGENTS.md lists them", file=file)
    for pack in plan["packs"]:
        scope = f" [{', '.join(pack['scope'])}]" if pack["scope"] else ""
        print(f"  {pack['id']}@{pack['version']}{scope}: {'; '.join(pack['provenance'])}", file=file)
    for pack_id in plan["excluded"]:
        print(f"  {pack_id}: not applied, see the rule decisions", file=file)
    if plan["conflicts"]:
        print("Conflicting packs", file=file)
        for conflict in plan["conflicts"]:
            where = f" in {', '.join(conflict['scope'])}" if conflict["scope"] else ""
            resolution = conflict["resolution"]
            outcome = (
                f"keep {', '.join(resolution['keep'])} ({resolution['reason']})" if resolution
                else "unresolved: add a resolution to the profile"
            )
            print(f"  {' / '.join(conflict['packs'])}{where}: {outcome}", file=file)
    for title, field in (("Team conventions", "conventions"), ("Project checks", "checks")):
        if plan[field]:
            print(title, file=file)
            for item in plan[field]:
                print(f"  - {item}", file=file)
