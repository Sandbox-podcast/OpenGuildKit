"""Market dossiers: competitors and substitutes, dated observations, and what is still unknown.

A dossier lives in .openguildkit/market/ID.json and is shared with the team through git.
The CLI validates it and attaches it to consultations; the host agent gathers the
observations within the project's research policy.
"""

import re
from datetime import date, timedelta
from pathlib import Path

from . import clock
from .storage import read_json, write_json

MARKET_DIR = "market"
KINDS = ("direct", "substitute")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
STALE_DAYS = 180
TO_DESCRIBE = "To describe."


def dossier_path(state: Path, dossier_id: str) -> Path:
    if not _ID.fullmatch(dossier_id) or len(dossier_id) > 64:
        raise ValueError("Use a dossier ID of lowercase letters, digits and hyphens.")
    return state / MARKET_DIR / f"{dossier_id}.json"


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip().splitlines()) != 1:
        raise ValueError(f"{field} must be a single line of text.")
    return value.strip()


def _day(value, field: str) -> str:
    """A YYYY-MM-DD date that is not in the future (one day of margin for time zones)."""
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        raise ValueError(f"{field} must be a date written YYYY-MM-DD.")
    try:
        day = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be a real date written YYYY-MM-DD: {value}.") from error
    if day > clock.today() + timedelta(days=1):
        raise ValueError(f"{field} is in the future ({value}): write the date the information dates from.")
    return value


def _list(container: dict, key: str, field: str) -> list:
    value = container.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a JSON list.")
    return value


def _competitor(item: dict, competitors: dict, label: str) -> str:
    value = item.get("competitor")
    if not isinstance(value, str) or value not in competitors:
        raise ValueError(f"{label} names an unknown competitor {value!r}: add it first with market competitor.")
    return value


def _source(value, field: str) -> dict:
    if not isinstance(value, dict) or not {"ref", "date"} <= value.keys() <= {"ref", "date", "title"}:
        raise ValueError(f"{field} needs ref and date, and can add title.")
    source = {"ref": _text(value["ref"], f"{field}.ref"), "date": _day(value["date"], f"{field}.date")}
    if "title" in value:
        source["title"] = _text(value["title"], f"{field}.title")
    return source


def validate_dossier(dossier: dict, dossier_id: str) -> dict:
    """Check a dossier's shape: competitors, dated observations, an optional watch."""
    allowed = {"id", "title", "market", "audience", "feature", "competitors", "observations", "unknowns", "watch"}
    if not isinstance(dossier, dict) or not {"id", "market", "audience", "feature", "competitors"} <= dossier.keys() <= allowed:
        raise ValueError("A dossier needs id, market, audience, feature and competitors.")
    if dossier["id"] != dossier_id:
        raise ValueError(f"The dossier's id must be {dossier_id}.")
    result = {"id": dossier_id}
    for field in ("title", "market", "audience", "feature"):
        if field in dossier:
            result[field] = _text(dossier[field], field)
    competitors = {}
    for item in dossier["competitors"] if isinstance(dossier["competitors"], list) else [None]:
        if not isinstance(item, dict) or not {"id", "name", "kind"} <= item.keys() <= {"id", "name", "kind", "url", "segment"}:
            raise ValueError("Each competitor needs id, name and kind (direct or substitute), and can add url and segment.")
        if not _ID.fullmatch(str(item["id"])) or item["id"] in competitors:
            raise ValueError(f"Competitor IDs are unique lowercase slugs: {item['id']!r}.")
        if item["kind"] not in KINDS:
            raise ValueError("A competitor's kind is direct or substitute.")
        competitors[item["id"]] = {key: (_text(item[key], key) if key != "kind" else item[key]) for key in item}
    result["competitors"] = list(competitors.values())
    observations = []
    for index, item in enumerate(_list(dossier, "observations", "observations"), start=1):
        if not isinstance(item, dict) or not {"id", "competitor", "claim", "source"} <= item.keys() <= {"id", "competitor", "claim", "source", "feature"}:
            raise ValueError("Each observation needs id, competitor, claim and source, and can add feature.")
        observation = {
            "id": _text(item["id"], "observation id"),
            "competitor": _competitor(item, competitors, f"Observation {index}"),
            "claim": _text(item["claim"], "claim"),
            "source": _source(item["source"], f"observation {index} source"),
        }
        if "feature" in item:
            observation["feature"] = _text(item["feature"], "feature")
        observations.append(observation)
    if len({item["id"] for item in observations}) != len(observations):
        raise ValueError("Observation IDs must be unique.")
    result["observations"] = observations
    result["unknowns"] = [_text(item, "unknown") for item in _list(dossier, "unknowns", "unknowns")]
    if "watch" in dossier:
        result["watch"] = validate_watch(dossier["watch"], competitors)
    return result


def validate_watch(watch: dict, competitors: dict) -> dict:
    if not isinstance(watch, dict) or not {"sources", "every_days"} <= watch.keys() <= {"sources", "every_days", "paused", "changes"}:
        raise ValueError("A watch needs sources and every_days, and can add paused and changes.")
    every = watch["every_days"]
    if type(every) is not int or not 1 <= every <= 366:
        raise ValueError("every_days is a whole number of days between 1 and 366.")
    sources = []
    for item in _list(watch, "sources", "watch.sources"):
        if not isinstance(item, dict) or not {"competitor", "url", "kind"} <= item.keys() <= {"competitor", "url", "kind", "last_checked"}:
            raise ValueError("Each watched source needs competitor, url and kind, and can add last_checked.")
        competitor = _competitor(item, competitors, "A watched source")
        if not isinstance(item["url"], str) or not item["url"].startswith("https://"):
            raise ValueError("Watched sources are public https pages.")
        source = {"competitor": competitor, "url": _text(item["url"], "url"), "kind": _text(item["kind"], "kind")}
        if "last_checked" in item:
            source["last_checked"] = _day(item["last_checked"], "last_checked")
        sources.append(source)
    changes = []
    for item in _list(watch, "changes", "watch.changes"):
        if not isinstance(item, dict) or not {"competitor", "what", "date", "source", "verified_by"} <= item.keys():
            raise ValueError("Each change needs competitor, what, date, source and verified_by.")
        changes.append({
            "competitor": _competitor(item, competitors, "A change"), "what": _text(item["what"], "what"), "date": _day(item["date"], "date"),
            "source": _text(item["source"], "source"), "verified_by": _text(item["verified_by"], "verified_by"),
        })
    paused = watch.get("paused", False)
    if type(paused) is not bool:
        raise ValueError("paused is true or false, without quotes.")
    return {"sources": sources, "every_days": every, "paused": paused, "changes": changes}


def load_dossier(state: Path, dossier_id: str) -> dict:
    path = dossier_path(state, dossier_id)
    if not path.is_file():
        raise ValueError(f"Unknown market dossier {dossier_id}. Create it with openguildkit market new {dossier_id}.")
    return validate_dossier(read_json(path), dossier_id)


def save_dossier(state: Path, dossier: dict) -> None:
    write_json(dossier_path(state, dossier["id"]), validate_dossier(dossier, dossier["id"]))


def new_dossier(dossier_id: str, fields: dict) -> dict:
    """An empty dossier that market check accepts; what is not given yet is marked to describe."""
    dossier = {"id": dossier_id}
    if fields.get("title"):
        dossier["title"] = fields["title"]
    for field in ("market", "audience", "feature"):
        dossier[field] = fields.get(field) or TO_DESCRIBE
    dossier.update(competitors=[], observations=[], unknowns=[])
    return validate_dossier(dossier, dossier_id)


def describe(dossier: dict, fields: dict) -> dict:
    """Change the title, market, audience or feature of a dossier."""
    given = {key: value for key, value in fields.items() if value is not None}
    if not given:
        raise ValueError("Give --title, --market, --audience or --feature.")
    return validate_dossier({**dossier, **given}, dossier["id"])


def add_competitor(dossier: dict, competitor: dict) -> dict:
    if any(item["id"] == competitor["id"] for item in dossier["competitors"]):
        raise ValueError(f"Competitor {competitor['id']} is already in the dossier.")
    entry = {key: value for key, value in competitor.items() if value is not None}
    return validate_dossier({**dossier, "competitors": [*dossier["competitors"], entry]}, dossier["id"])


def add_observation(dossier: dict, observation: dict) -> dict:
    """Add a dated, sourced observation; an existing ID is replaced so a refresh keeps one entry."""
    entry = {key: observation[key] for key in ("id", "competitor", "claim")}
    entry["source"] = {"ref": observation["ref"], "date": observation["date"]}
    if observation.get("feature"):
        entry["feature"] = observation["feature"]
    kept = [item for item in dossier["observations"] if item["id"] != entry["id"]]
    return validate_dossier({**dossier, "observations": [*kept, entry]}, dossier["id"])


def set_unknown(dossier: dict, text: str, remove: bool = False) -> dict:
    text = _text(text, "unknown")
    unknowns = list(dossier["unknowns"])
    if remove:
        if text not in unknowns:
            raise ValueError(f"The dossier has no unknown {text!r}. Run market check to list them.")
        unknowns.remove(text)
    elif text not in unknowns:
        unknowns.append(text)
    return validate_dossier({**dossier, "unknowns": unknowns}, dossier["id"])


def _watch(dossier: dict) -> dict:
    if "watch" not in dossier:
        raise ValueError("The dossier watches no source yet: add one with market watch.")
    return dossier["watch"]


def watch_source(dossier: dict, source: dict, every_days: int | None = None) -> dict:
    """Follow a public page of a competitor; every_days sets the review interval (30 days by default)."""
    watch = dossier.get("watch", {"sources": [], "every_days": every_days or 30, "paused": False, "changes": []})
    if every_days is not None:
        watch = {**watch, "every_days": every_days}
    if any(item["url"] == source["url"] for item in watch["sources"]):
        raise ValueError(f"{source['url']} is already watched.")
    watch = {**watch, "sources": [*watch["sources"], source]}
    return validate_dossier({**dossier, "watch": watch}, dossier["id"])


def _checked(sources: list[dict], url: str, day: str) -> list[dict]:
    return [{**item, "last_checked": day} if item["url"] == url else item for item in sources]


def mark_checked(dossier: dict, url: str, day: str | None = None) -> dict:
    """Record that a watched source was reviewed, with no change to keep."""
    watch = _watch(dossier)
    if not any(item["url"] == url for item in watch["sources"]):
        raise ValueError(f"{url} is not a watched source of the dossier. Run market due to list them.")
    day = _day(day or clock.today().isoformat(), "date")
    return validate_dossier({**dossier, "watch": {**watch, "sources": _checked(watch["sources"], url, day)}}, dossier["id"])


def record_change(dossier: dict, change: dict, today: str | None = None) -> dict:
    """Keep a verified change; when its source is a watched page, that page counts as checked today."""
    watch = _watch(dossier)
    entry = {key: change[key] for key in ("competitor", "what", "date", "source", "verified_by")}
    today = today or clock.today().isoformat()
    watch = {**watch, "changes": [*watch["changes"], entry], "sources": _checked(watch["sources"], entry["source"], today)}
    return validate_dossier({**dossier, "watch": watch}, dossier["id"])


def set_paused(dossier: dict, paused: bool) -> dict:
    return validate_dossier({**dossier, "watch": {**_watch(dossier), "paused": paused}}, dossier["id"])


def due_issue(dossier_id: str, source: dict) -> dict:
    """The title and body of the issue a scheduled job opens for a source to review."""
    return {
        "title": f"Market watch: review {source['competitor']} {source['kind']} ({dossier_id})",
        "body": (f"The watched source {source['url']} of market dossier `{dossier_id}` is due for review "
                 f"(last checked: {source.get('last_checked', 'never')}).\n\n"
                 f"Review it within the project's research policy, then record the result:\n\n"
                 f"- nothing changed: `openguildkit market checked {dossier_id} --url {source['url']}`\n"
                 f"- a change to keep: `openguildkit market change {dossier_id} --competitor {source['competitor']} "
                 f"--what TEXT --source {source['url']} --date YYYY-MM-DD --verified-by NAME`\n"),
    }


def dossier_gaps(dossier: dict, research: str, today: date | None = None) -> list[str]:
    """What the dossier still lacks before Product and Marketing can rely on it."""
    today = today or clock.today()
    gaps = list(dossier.get("unknowns", []))
    for field in ("market", "audience", "feature"):
        if dossier[field] == TO_DESCRIBE:
            gaps.append(f"Describe the dossier's {field}: openguildkit market describe {dossier['id']} --{field} TEXT.")
    kinds = {item["kind"] for item in dossier["competitors"]}
    for kind in KINDS:
        if kind not in kinds:
            gaps.append(f"No {kind} competitor is listed.")
    observed = {item["competitor"] for item in dossier["observations"]}
    for competitor in dossier["competitors"]:
        if competitor["id"] not in observed:
            gaps.append(f"No dated observation for {competitor['name']}.")
    for item in dossier["observations"]:
        age = (today - date.fromisoformat(item["source"]["date"])).days
        if age > STALE_DAYS:
            gaps.append(f"Observation {item['id']} is {age} days old.")
        if research == "local-only" and item["source"]["ref"].startswith("http"):
            gaps.append(f"Observation {item['id']} cites a public page although research is local-only: confirm it was provided.")
    for index, item in enumerate(dossier.get("watch", {}).get("changes", []), start=1):
        if research == "local-only" and item["source"].startswith("http"):
            gaps.append(f"Change {index} ({item['competitor']}) cites a public page although research is local-only: "
                        "confirm a person provided it.")
    if research == "local-only":
        gaps.append("Research is local-only: public sources stay to be documented when the project allows them.")
    return gaps


def due_sources(dossier: dict, today: date | None = None) -> list[dict]:
    """Watched sources whose review is due."""
    watch = dossier.get("watch")
    if not watch or watch["paused"]:
        return []
    today = today or clock.today()
    due = []
    for source in watch["sources"]:
        last = source.get("last_checked")
        if last is None or (today - date.fromisoformat(last)).days >= watch["every_days"]:
            due.append(source)
    return due


def scope_entry(dossier: dict, research: str, today: date | None = None) -> dict:
    """What a consultation carries: observations and verified changes with their age, and the gaps."""
    today = today or clock.today()
    entry = {key: dossier[key] for key in ("id", "market", "audience", "feature", "competitors")}
    entry["observations"] = [
        {**item, "age_days": (today - date.fromisoformat(item["source"]["date"])).days} for item in dossier["observations"]
    ]
    if dossier.get("watch", {}).get("changes"):
        entry["changes"] = [
            {**item, "age_days": (today - date.fromisoformat(item["date"])).days} for item in dossier["watch"]["changes"]
        ]
    entry["gaps"] = dossier_gaps(dossier, research, today)
    return entry
