"""Prints the rule plan as a person reads it, for `preview` and for the confirmation `init` asks (patterns, regulations,
packs and conflicts), and the patterns `recommend` preselects.

The plan lists the patterns with why they apply, the regulations, the packs in the order `AGENTS.md` lists them, and
the conflicts between packs.

Entry: `print_rule_plan`, `print_recommendations`
Tests: `tests/test_proportionate_setup.py`, `tests/test_command_output_budget.py`
"""

import sys

from .project import RULES_NOTE
from .storage import print_json


def print_rule_plan(plan: dict, as_json: bool, file=None) -> None:
    if as_json:
        print_json(plan)
        return
    file = file or sys.stdout
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


def print_recommendations(plan: dict, as_json: bool) -> None:
    if as_json:
        print_json(plan)
        return
    print("Preselected patterns, confirm or remove them")
    for pattern in plan["matched"]:
        where = f" [{', '.join(pattern['components'])}]" if pattern.get("components") else ""
        print(f"  {pattern['id']}{where}: {'; '.join(pattern['reasons'])} ({pattern['rules']} rules)")
        if pattern.get("version_unknown"):
            print(f"    version unknown, confirm {', '.join(pattern['version_unknown'])}")
    if plan.get("excluded"):
        print("Not applicable because of a version")
        for item in plan["excluded"]:
            where = f" [{item['component']}]" if item["component"] else ""
            print(f"  {item['id']}{where}: {'; '.join(item['reasons'])}")
    print("Suggested, not selected: add one only if the team uses it")
    for pattern in plan["suggested"]:
        reason = "choose one overlapping pattern" if pattern.get("choice_required") else "; ".join(pattern["reasons"])
        print(f"  {pattern['id']}: {reason} ({pattern['rules']} rules)")
    print(f"Recommended packs: {', '.join(plan['recommended_packs'])} ({plan['rule_count']} rules in all)")
    print(RULES_NOTE)
    if plan.get("declined"):
        print("Declined in the profile, not proposed again (openguildkit profile adopt brings one back)")
        for entry in plan["declined"]:
            who = f" by {entry['by']} on {entry['on']}: {entry['reason']}" if isinstance(entry, dict) else ""
            print(f"  {entry['id'] if isinstance(entry, dict) else entry}{who}")
    if plan.get("review"):
        print("Selected patterns to review")
        for item in plan["review"]:
            print(f"  {item['id']}: {'; '.join(item['reasons'])}")
