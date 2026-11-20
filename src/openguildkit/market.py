"""Market dossiers: competitors and substitutes, dated observations, and what is still unknown.

A dossier lives in .openguildkit/market/ID.json and is shared with the team through git.
The CLI validates it and attaches it to consultations; the host agent gathers the
observations within the project's research policy.
"""

import re
from datetime import date
from pathlib import Path

from .storage import read_json, write_json

MARKET_DIR = "market"
KINDS = ("direct", "substitute")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
STALE_DAYS = 180


def dossier_path(state: Path, dossier_id: str) -> Path:
    if not _ID.fullmatch(dossier_id) or len(dossier_id) > 64:
        raise ValueError("Use a dossier ID of lowercase letters, digits and hyphens.")
    return state / MARKET_DIR / f"{dossier_id}.json"


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip().splitlines()) != 1:
        raise ValueError(f"{field} must be a single line of text.")
    return value.strip()


def _day(value, field: str) -> str:
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        raise ValueError(f"{field} must be a date written YYYY-MM-DD.")
    date.fromisoformat(value)
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
    for index, item in enumerate(dossier.get("observations", []), start=1):
        if not isinstance(item, dict) or not {"id", "competitor", "claim", "source"} <= item.keys() <= {"id", "competitor", "claim", "source", "feature"}:
            raise ValueError("Each observation needs id, competitor, claim and source, and can add feature.")
        if item["competitor"] not in competitors:
            raise ValueError(f"Observation {item['id']} names an unknown competitor {item['competitor']!r}.")
        observation = {
            "id": _text(item["id"], "observation id"),
            "competitor": item["competitor"],
            "claim": _text(item["claim"], "claim"),
            "source": _source(item["source"], f"observation {index} source"),
        }
        if "feature" in item:
            observation["feature"] = _text(item["feature"], "feature")
        observations.append(observation)
    if len({item["id"] for item in observations}) != len(observations):
        raise ValueError("Observation IDs must be unique.")
    result["observations"] = observations
    result["unknowns"] = [_text(item, "unknown") for item in dossier.get("unknowns", [])]
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
    for item in watch["sources"]:
        if not isinstance(item, dict) or not {"competitor", "url", "kind"} <= item.keys() <= {"competitor", "url", "kind", "last_checked"}:
            raise ValueError("Each watched source needs competitor, url and kind, and can add last_checked.")
        if item["competitor"] not in competitors:
            raise ValueError(f"Watched source names an unknown competitor {item['competitor']!r}.")
        if not str(item["url"]).startswith("https://"):
            raise ValueError("Watched sources are public https pages.")
        source = {"competitor": item["competitor"], "url": _text(item["url"], "url"), "kind": _text(item["kind"], "kind")}
        if "last_checked" in item:
            source["last_checked"] = _day(item["last_checked"], "last_checked")
        sources.append(source)
    changes = []
    for item in watch.get("changes", []):
        if not isinstance(item, dict) or not {"competitor", "what", "date", "source", "verified_by"} <= item.keys():
            raise ValueError("Each change needs competitor, what, date, source and verified_by.")
        if item["competitor"] not in competitors:
            raise ValueError(f"A change names an unknown competitor {item['competitor']!r}.")
        changes.append({
            "competitor": item["competitor"], "what": _text(item["what"], "what"), "date": _day(item["date"], "date"),
            "source": _text(item["source"], "source"), "verified_by": _text(item["verified_by"], "verified_by"),
        })
    return {"sources": sources, "every_days": every, "paused": bool(watch.get("paused", False)), "changes": changes}


def load_dossier(state: Path, dossier_id: str) -> dict:
    path = dossier_path(state, dossier_id)
    if not path.is_file():
        raise ValueError(f"Unknown market dossier {dossier_id}. Create {path.relative_to(state.parent).as_posix()}.")
    return validate_dossier(read_json(path), dossier_id)


def save_dossier(state: Path, dossier: dict) -> None:
    write_json(dossier_path(state, dossier["id"]), validate_dossier(dossier, dossier["id"]))


def dossier_gaps(dossier: dict, research: str, today: date | None = None) -> list[str]:
    """What the dossier still lacks before Product and Marketing can rely on it."""
    today = today or date.today()
    gaps = list(dossier.get("unknowns", []))
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
    if research == "local-only":
        gaps.append("Research is local-only: public sources stay to be documented when the project allows them.")
    return gaps


def due_sources(dossier: dict, today: date | None = None) -> list[dict]:
    """Watched sources whose review is due."""
    watch = dossier.get("watch")
    if not watch or watch["paused"]:
        return []
    today = today or date.today()
    due = []
    for source in watch["sources"]:
        last = source.get("last_checked")
        if last is None or (today - date.fromisoformat(last)).days >= watch["every_days"]:
            due.append(source)
    return due


def scope_entry(dossier: dict, research: str, today: date | None = None) -> dict:
    """What a consultation carries: observations and verified changes with their age, and the gaps."""
    today = today or date.today()
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
