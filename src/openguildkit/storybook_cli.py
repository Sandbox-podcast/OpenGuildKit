"""The storybook command: compose the company Storybook, record its stories, and extract a design system from an
existing React application.

The Storybook modules load when the command runs, so the other commands start without them.

Entry: add_parser, run
Tests: tests/test_architecture.py, tests/test_storybook.py, tests/test_storybook_extract.py
"""

import argparse
import sys
from pathlib import Path

from .command import Command
from .stack_versions import STORYBOOK_VERSION
from .storage import print_json, project_lock, write_json


def add_parser(commands) -> None:
    storybook = commands.add_parser(
        "storybook", help="Compose the company Storybook, record its stories and extract a design system.")
    storybook_actions = storybook.add_subparsers(dest="action", required=True)
    compose = storybook_actions.add_parser(
        "compose", help="Add a published Storybook to the refs file that .storybook/main imports.")
    compose.add_argument("ref", help="Ref ID, such as company; its stories are cited as storybook:REF_STORY_ID.")
    compose.add_argument("--url", help="URL of the published Storybook.")
    compose.add_argument("--title", help="Title shown in the Storybook sidebar.")
    compose.add_argument("--remove", action="store_true", help="Remove this ref from the refs file.")
    compose.add_argument("--config-dir", default=".storybook", help="Storybook configuration folder (default .storybook).")
    sb_import = storybook_actions.add_parser(
        "import", help="Compare Storybook index.json files, report what to map and record the known stories.")
    sb_import.add_argument("--project-index", type=Path,
                           help="The project's index.json or storybook-static folder (default storybook-static).")
    sb_import.add_argument("--company-index", type=Path, help="The company Storybook's index.json or static folder.")
    sb_import.add_argument("--ref", default="company", help="Ref ID of the company Storybook (default company).")
    sb_import.add_argument("--library", type=Path, help="package.json of the company component library.")
    sb_import.add_argument("--package", type=Path, help="The project's package.json (default package.json).")
    sb_extract = storybook_actions.add_parser(
        "extract", help="Inventory the components, variants and style tokens of an existing React application.",
        description="Inventory the components, variants and style tokens of an existing React application. "
                    "Supported: React function components (function declarations, arrow functions, forwardRef and "
                    "memo) in .tsx and .jsx files, their props, literal defaults and string-union prop types, the "
                    "export aliases and re-exports of .ts and .js index files, and CSS and SCSS stylesheets. "
                    "Not supported: class components, Vue, Angular and Svelte components, CSS-in-JS and utility "
                    "classes such as Tailwind's. The sources are read with text patterns, not a full parser: "
                    "check the inventory before proposing.")
    sb_extract.add_argument("--src", type=Path, action="append", required=True,
                         help="Source folder or file to scan, such as a screen; repeat to select several.")
    sb_extract.add_argument("--preview", type=Path, action="append", default=[],
                         help="Screenshot the team may reuse; recorded with its hash, never analyzed.")
    sb_extract.add_argument("--output", type=Path, help="Inventory file (default .openguildkit/storybook/inventory.json).")
    sb_propose = storybook_actions.add_parser(
        "propose", help="Write the proposals to validate from the inventory, keeping the decisions already made.")
    sb_propose.add_argument("--inventory", type=Path, help="Inventory file (default .openguildkit/storybook/inventory.json).")
    sb_propose.add_argument("--proposals", type=Path, help="Proposals file (default .openguildkit/storybook/proposals.json).")
    sb_generate = storybook_actions.add_parser(
        "generate", help="Write tokens, stories and an index for the validated proposals; never overwrite edits.")
    sb_generate.add_argument("--proposals", type=Path, help="Proposals file (default .openguildkit/storybook/proposals.json).")
    sb_generate.add_argument("--output", dest="out", type=Path, help="Output folder (default src/design-system).")
    sb_generate.add_argument("--out", dest="out", type=Path, help=argparse.SUPPRESS)  # The name before --output.
    sb_generate.add_argument("--framework", help="Storybook framework package for the types (default: the one in "
                                                  "package.json, else @storybook/nextjs-vite for Next.js, "
                                                  "else @storybook/react-vite).")
    for storybook_action in (compose, sb_import, sb_extract, sb_propose, sb_generate):
        storybook_action.add_argument("--json", action="store_true", help="Print the result as JSON.")
    storybook.epilog = (f"Create the project Storybook with npm create storybook@{STORYBOOK_VERSION}. "
                        "storybook compose prints a minimal .storybook/main.ts when the project has none.")


def _print_compose(result: dict) -> list[str]:
    lines = [f"{result['file']}: " + (", ".join(f"{key} ({value['url']})" for key, value in result["refs"].items())
                                       or "no composed Storybook")]
    if result["main"] is None:
        lines.append(f"No Storybook main file was found. Create the project Storybook first, or start from this "
                     f"{result['minimal_main_file']}:")
        lines.extend(f"  {line}" if line else "" for line in result["minimal_main"].splitlines())
    elif not result["imported"]:
        lines.append(f"Add these lines to {result['main']}, then rebuild Storybook:")
        lines.extend(f"  {line}" for line in result["add_to_main"])
    return lines


def _print_import(report: dict) -> list[str]:
    from .storybook import PROJECT_REF  # Loaded by run already.

    lines = []
    for key in ("company", PROJECT_REF):
        if key in report:
            item = report[key]
            lines.append(f"{key.capitalize()} Storybook ({item['source']}): {len(item['components'])} titles, "
                         f"{item['stories']} stories.")
    if "matched" in report:
        lines.append(f"Matched components: {len(report['matched'])}.")
        lines.extend(f"- To map: {item['title']}" for item in report["to_map"])
        for kind, label in (("story_ids", "story ID"), ("titles", "title")):
            lines.extend(f"- Conflict, same {label} in both: {value}" for value in report["conflicts"][kind])
    for row in report.get("dependencies", []):
        if row["status"] != "ok":
            lines.append(f"- Dependency {row['status']}: {row['name']} {row['library']} in the library, "
                         f"{row.get('installed') or row['project'] or 'absent'} in the project"
                         + (" (styling)" if row["styling"] else ""))
    lines.extend(f"- Theme source: {item.get('title') or item.get('path')}" for item in report.get("themes", []))
    lines.append(f"Recorded the known stories in {report['record']}.")
    return lines


def _print_extract(result: dict, output: str) -> list[str]:
    hypotheses = sum(item["confidence"] == "hypothesis" for field in ("components", "variants", "tokens")
                     for item in result[field])
    return [
        f"Scanned {result['scanned']['components']} component files and {result['scanned']['styles']} style files.",
        f"{len(result['components'])} components, {len(result['variants'])} variants, {len(result['tokens'])} "
        f"token candidates; {hypotheses} seen once are hypotheses.",
        f"Inventory written to {output}. Run openguildkit storybook propose next.",
    ]


def run(command: Command) -> int | None:
    """Run one storybook action and print what it did, or its result as JSON."""
    args, root, state = command.args, command.root, command.state
    from .storybook import INVENTORY, committed_path, compose, import_indexes, propose
    from .storybook_extract import extract
    from .storybook_stories import generate

    if args.action == "compose":
        result = compose(root, args.ref, args.url, args.title, args.remove, args.config_dir)
        lines = _print_compose(result)
    elif args.action == "import":
        result = import_indexes(root, state, args.project_index, args.company_index, args.ref, args.library, args.package)
        lines = _print_import(result)
    elif args.action == "extract":
        result = extract(root, args.src, args.preview)
        output = args.output or state / INVENTORY
        with project_lock(state):
            write_json(output, result)
        lines = _print_extract(result, committed_path(root, output))
    elif args.action == "propose":
        result = propose(root, state, args.inventory, args.proposals)
        lines = [f"{result['proposals']}: {result['new']} new, {result['kept']} kept with their decision, "
                 f"{result['not_observed']} no longer observed, {result['hypotheses']} hypotheses.",
                 "Set each status to validated or rejected and adjust the names, then run storybook generate."]
    elif args.action == "generate":
        result = generate(root, state, args.proposals, args.out, args.framework)
        lines = [f"Written: {path}" for path in result["written"]]
        lines += [f"Unchanged: {path}" for path in result["unchanged"]]
        lines += [f"Kept, changed by the team: {path}" for path in result["kept"]]
        lines += [f"No longer generated, left in place: {path}" for path in result["left"]]
        lines += [f"Skipped {item['key']}: {item['reason']}" for item in result["skipped"]]
        lines = lines or ["Nothing is validated yet."]
        if any(path.endswith(".stories.tsx") for path in result["written"]):
            lines.append(f"The stories use the Storybook framework {result['framework']}; --framework sets another.")
    else:
        raise ValueError(f"Unknown storybook action {args.action}.")
    if args.json:
        print_json(result)
    else:
        print("\n".join(lines))
        for warning in result.get("warnings", []):
            print(f"Warning: {warning}", file=sys.stderr)
    return None
