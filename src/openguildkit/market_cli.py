"""The `openguildkit market` command: create a dossier, record observations and changes, check it, list due sources."""

from pathlib import Path

from .cli_surface import add_by
from .command import Command
from .market import (
    KINDS,
    MARKET_DIR,
    add_competitor,
    add_observation,
    describe,
    dossier_gaps,
    dossier_path,
    due_issue,
    due_sources,
    load_dossier,
    mark_checked,
    mark_provided,
    new_dossier,
    record_change,
    save_dossier,
    set_paused,
    set_unknown,
    watch_source,
)
from .storage import json_text, project_lock

MODES = {
    "new": "create an empty dossier",
    "describe": "change its title, market, audience or feature",
    "competitor": "add a competitor or substitute",
    "observe": "record a dated, sourced observation",
    "unknown": "add (or --remove) what is still unknown",
    "watch": "follow a public page of a competitor",
    "checked": "record that a watched page was reviewed with no change",
    "change": "record a verified change, which marks its watched page checked",
    "provided": "record that a person reviewed a watched page and provided it (local-only research)",
    "pause": "pause the watch",
    "resume": "resume the watch",
    "check": "validate and list the gaps",
    "due": "list the watched sources to review",
}
_REQUIRED = {
    "competitor": ("competitor", "name", "kind"),
    "observe": ("competitor", "observation", "claim", "source", "date"),
    "unknown": ("text",),
    "watch": ("competitor", "url", "kind"),
    "checked": ("url",),
    "provided": ("url", "by"),
    "change": ("competitor", "what", "source", "date", "verified_by"),
}


def add_parser(commands) -> None:
    market = commands.add_parser(
        "market", help="Create and update a market dossier, check it and list the competitor sources due for review.")
    market.add_argument("mode", choices=tuple(MODES), help="; ".join(f"{mode}: {text}" for mode, text in MODES.items()) + ".")
    market.add_argument("dossier", nargs="?", help="Dossier ID in .openguildkit/market/.")
    market.add_argument("--all", action="store_true", help="due: every dossier of the project.")
    for name in ("title", "market", "audience", "feature"):
        market.add_argument(f"--{name}", help=f"new, describe{', observe' if name == 'feature' else ''}: the {name}.")
    market.add_argument("--competitor", help="Competitor ID, a lowercase slug.")
    market.add_argument("--name", help="competitor: its name.")
    market.add_argument("--kind", help="competitor: direct or substitute; watch: what the page is, such as release notes.")
    market.add_argument("--segment", help="competitor: the segment it serves.")
    market.add_argument("--url", help="competitor, watch, checked, provided: a public https page.")
    market.add_argument("--observation", help="observe: observation ID; an existing ID is replaced.")
    market.add_argument("--claim", help="observe: what the competitor offers.")
    market.add_argument("--source", help="observe: document or page the claim comes from; change: the page.")
    market.add_argument("--date", help="observe, change: the date the information dates from, YYYY-MM-DD; "
                                       "checked, provided: today by default.")
    market.add_argument("--what", help="change: what changed.")
    market.add_argument("--verified-by", help="change: the person who verified it.")
    add_by(market)
    market.add_argument("--text", help="unknown: what is still unknown.")
    market.add_argument("--remove", action="store_true", help="unknown: remove the text instead of adding it.")
    market.add_argument("--every-days", type=int, help="watch: review interval in days (30 by default).")
    market.add_argument("--json", action="store_true", help="check, due: print the result as JSON.")


def _require(args) -> None:
    missing = [name for name in _REQUIRED.get(args.mode, ()) if not getattr(args, name)]
    if missing:
        options = ", ".join("--" + name.replace("_", "-") for name in missing)
        raise ValueError(f"market {args.mode} needs {options}.")


def _changed(args, dossier: dict) -> dict:
    """Apply one recording mode to a dossier."""
    mode = args.mode
    if mode == "describe":
        return describe(dossier, {name: getattr(args, name) for name in ("title", "market", "audience", "feature")})
    if mode == "competitor":
        if args.kind not in KINDS:
            raise ValueError("A competitor's --kind is direct or substitute.")
        return add_competitor(dossier, {"id": args.competitor, "name": args.name, "kind": args.kind,
                                        "url": args.url, "segment": args.segment})
    if mode == "observe":
        return add_observation(dossier, {"id": args.observation, "competitor": args.competitor, "claim": args.claim,
                                         "ref": args.source, "date": args.date, "feature": args.feature})
    if mode == "unknown":
        return set_unknown(dossier, args.text, args.remove)
    if mode == "watch":
        return watch_source(dossier, {"competitor": args.competitor, "url": args.url, "kind": args.kind}, args.every_days)
    if mode == "checked":
        return mark_checked(dossier, args.url, args.date)
    if mode == "provided":
        return mark_provided(dossier, args.url, args.by, args.date)
    if mode == "change":
        return record_change(dossier, {"competitor": args.competitor, "what": args.what, "date": args.date,
                                       "source": args.source, "verified_by": args.verified_by})
    return set_paused(dossier, mode == "pause")


LOCAL_ONLY_DUE = ("Research is local-only: a person reviews each page, then records it with "
                  "openguildkit market provided ID --url URL --by INITIALS.")


def _due(args, state: Path, research: str) -> None:
    if args.all == bool(args.dossier):
        raise ValueError("Name one dossier, or pass --all for every dossier of the project.")
    folder = state / MARKET_DIR
    ids = sorted(path.stem for path in folder.glob("*.json")) if args.all and folder.is_dir() else [args.dossier] if args.dossier else []
    results = []
    for dossier_id in ids:
        dossier = load_dossier(state, dossier_id)
        due = [{**source, "dossier": dossier_id, "issue": due_issue(dossier_id, source, research)}
               for source in due_sources(dossier)]
        results.append({"dossier": dossier_id, "due": due, "paused": dossier.get("watch", {}).get("paused", False)})
    if args.json:
        print(json_text(results[0] if not args.all else {"dossiers": results,
                                                         "due": [item for result in results for item in result["due"]]}), end="")
        return
    for result in results:
        if args.all:
            print(f"{result['dossier']}:")
        lines = [f"- {item['competitor']} {item['kind']}: {item['url']}" for item in result["due"]] or [
            "Watch paused." if result["paused"] else "No source due for review."]
        print("\n".join(lines))
    if not results:
        print("No market dossier in .openguildkit/market/.")
    elif research == "local-only" and any(result["due"] for result in results):
        print(LOCAL_ONLY_DUE)


def _person_reviews(args, dossier: dict, research: str) -> None:
    """Under local-only, no agent opens a page: a watched page counts as reviewed only when a person recorded it
    with market provided. market checked would mark it reviewed without anyone; market change on a watched page
    would too, unless a person provided that page."""
    if research != "local-only":
        return
    url = args.url if args.mode == "checked" else args.source
    sources = dossier.get("watch", {}).get("sources", [])
    watched = next((item for item in sources if item.get("url") == url), None)
    if watched is None or (args.mode == "change" and watched.get("provided_by")):
        return
    then = " first, then record the change" if args.mode == "change" else ""
    raise ValueError(f"Research is local-only: no agent opens {url}. A person reviews it and records it with "
                     f"openguildkit market provided {args.dossier} --url {url} --by INITIALS{then}.")


def run(command: Command) -> None:
    args, state, profile = command.args, command.state, command.profile
    if args.mode == "due":
        return _due(args, state, profile.get("research", "local-only"))
    if not args.dossier:
        raise ValueError(f"Name the dossier: openguildkit market {args.mode} ID.")
    if args.mode == "check":
        dossier = load_dossier(state, args.dossier)
        result = {"dossier": args.dossier, "gaps": dossier_gaps(dossier, profile.get("research", "local-only"))}
        if args.json:
            print(json_text(result), end="")
        else:
            print("\n".join(f"- {gap}" for gap in result["gaps"]) or "No gap found.")
        return
    _require(args)
    with project_lock(state):
        if args.mode == "new":
            path = dossier_path(state, args.dossier)
            if path.exists():
                raise ValueError(f"Market dossier {args.dossier} already exists. Update it with the other market commands.")
            dossier = new_dossier(args.dossier, {name: getattr(args, name) for name in ("title", "market", "audience", "feature")})
        else:
            dossier = load_dossier(state, args.dossier)
            if args.mode in ("checked", "change"):
                _person_reviews(args, dossier, profile.get("research", "local-only"))
            dossier = _changed(args, dossier)
        save_dossier(state, dossier)
    print(f"Market dossier {args.dossier}: {MODES[args.mode]}, done. Run openguildkit market check {args.dossier}.")
