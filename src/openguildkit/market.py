"""Market dossiers: competitors and substitutes, dated observations, and what is still unknown.

A dossier lives in .openguildkit/market/ID.json and is shared with the team through git.
The CLI validates it and attaches it to consultations; the host agent gathers the
observations within the project's research policy. Its dates decide what is stale, due or in
the future: they follow the real clock, whatever SOURCE_DATE_EPOCH says.
"""

import codecs
import json
import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from . import clock
from .sensitive import public_evidence_url
from .storage import parse_json, read_bytes, read_json, write_text

MARKET_DIR = "market"
KINDS = ("direct", "substitute")
_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_SPACE = re.compile(r"[ \t\r\n]*")
STALE_DAYS = 180
TO_DESCRIBE = "To describe."
COMPETITOR_FIELDS = ("id", "name", "kind", "url", "segment")
# Words that say nothing about a feature, in English and French, left out of the relevance check.
_COMMON_WORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "our", "their", "should", "whether", "what", "which", "when",
    "how", "les", "des", "une", "pour", "avec", "dans", "sur", "que", "qui", "est", "par", "aux", "nos", "leur",
})


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
    if day > clock.real_today() + timedelta(days=1):
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


def _cited(text: str, field: str) -> str:
    """A source that is a link must be a public https link without credentials; notes and documents stay as written."""
    if re.match(r"https?://", text, re.IGNORECASE):
        public_evidence_url(text, field)
    return text


def _source(value, field: str) -> dict:
    if not isinstance(value, dict) or not {"ref", "date"} <= value.keys() <= {"ref", "date", "title"}:
        raise ValueError(f"{field} needs ref and date, and can add title.")
    source = {"ref": _cited(_text(value["ref"], f"{field}.ref"), f"{field}.ref"), "date": _day(value["date"], f"{field}.date")}
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
        competitors[item["id"]] = {key: (_text(item[key], key) if key != "kind" else item[key])
                                   for key in COMPETITOR_FIELDS if key in item}
    result["competitors"] = list(competitors.values())
    observations = []
    for index, item in enumerate(_list(dossier, "observations", "observations"), start=1):
        if not isinstance(item, dict) or not {"id", "competitor", "claim", "source"} <= item.keys() <= {"id", "competitor", "claim", "source", "feature"}:
            raise ValueError("Each observation needs id, competitor, claim and source, and can add feature.")
        observation = {
            "id": _text(item["id"], "observation id"),
            "competitor": _competitor(item, competitors, f"Observation {index}"),
            "claim": _text(item["claim"], "claim"),
        }
        if "feature" in item:
            observation["feature"] = _text(item["feature"], "feature")
        observation["source"] = _source(item["source"], f"observation {index} source")
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
        if not isinstance(item, dict) or not {"competitor", "url", "kind"} <= item.keys() <= {
                "competitor", "url", "kind", "last_checked", "provided_by"}:
            raise ValueError("Each watched source needs competitor, url and kind, and can add last_checked and provided_by.")
        competitor = _competitor(item, competitors, "A watched source")
        if not isinstance(item["url"], str) or not item["url"].startswith("https://"):
            raise ValueError("Watched sources are public https pages.")
        public_evidence_url(item["url"].strip(), "url")
        source = {"competitor": competitor, "url": _text(item["url"], "url"), "kind": _text(item["kind"], "kind")}
        if "last_checked" in item:
            source["last_checked"] = _day(item["last_checked"], "last_checked")
        if "provided_by" in item:
            if "last_checked" not in item:
                raise ValueError("A source provided by a person also has last_checked, the day it was provided.")
            source["provided_by"] = _text(item["provided_by"], "provided_by")
        sources.append(source)
    changes = []
    for item in _list(watch, "changes", "watch.changes"):
        if not isinstance(item, dict) or not {"competitor", "what", "date", "source", "verified_by"} <= item.keys():
            raise ValueError("Each change needs competitor, what, date, source and verified_by.")
        changes.append({
            "competitor": _competitor(item, competitors, "A change"), "what": _text(item["what"], "what"), "date": _day(item["date"], "date"),
            "source": _cited(_text(item["source"], "source"), "source"), "verified_by": _text(item["verified_by"], "verified_by"),
        })
    paused = watch.get("paused", False)
    if type(paused) is not bool:
        raise ValueError("paused is true or false, without quotes.")
    return {"every_days": every, "paused": paused, "sources": sources, "changes": changes}


def load_dossier(state: Path, dossier_id: str) -> dict:
    path = dossier_path(state, dossier_id)
    if not path.is_file():
        raise ValueError(f"Unknown market dossier {dossier_id}. Create it with openguildkit market new {dossier_id}.")
    return validate_dossier(read_json(path), dossier_id)


def _json_list(items: list, indent: str) -> str:
    """A list with one item per line, so that adding, changing or removing an item touches its own line."""
    if not items:
        return "[]"
    inner = indent + "  "
    return "[\n" + ",\n".join(inner + json.dumps(item, ensure_ascii=False) for item in items) + f"\n{indent}]"


def _json_value(value, indent: str) -> str:
    """A value in the dossier layout, for a field whose line starts with indent."""
    if isinstance(value, dict):
        return _json_fields(value, indent)
    if isinstance(value, list):
        return _json_list(value, indent)
    return json.dumps(value, ensure_ascii=False)


def _json_fields(fields: dict, indent: str) -> str:
    inner = indent + "  "
    lines = [f"{inner}{json.dumps(key)}: {_json_value(value, inner)}" for key, value in fields.items()]
    return "{\n" + ",\n".join(lines) + f"\n{indent}}}"


def dossier_text(dossier: dict) -> str:
    """The dossier file: fields in a fixed order and one list item per line, so a one-line change is a one-line diff."""
    return _json_fields(validate_dossier(dossier, dossier["id"]), "") + "\n"


def _top_fields(source: str) -> dict:
    """Where each top-level field of a JSON object sits: the space before its key, its key, its value's span."""
    decoder, fields = json.JSONDecoder(), {}
    position = _SPACE.match(source).end() + 1
    while True:
        start = _SPACE.match(source, position).end()
        if source[start] == "}":
            return fields
        key, end = decoder.raw_decode(source, start)
        value_start = _SPACE.match(source, source.index(":", end) + 1).end()
        value_end = decoder.raw_decode(source, value_start)[1]
        fields[key] = (position, start, value_start, value_end)
        position = _SPACE.match(source, value_end).end()
        if source[position] == "}":
            return fields
        position += 1


def _patched(source: str, old: dict, new: dict) -> str:
    """The file text with only the changed top-level fields rewritten in the dossier layout; the rest keeps its bytes."""
    newline = "\r\n" if "\r\n" in source else "\n"
    fields = _top_fields(source)
    if not fields.keys() <= new.keys():
        return dossier_text(new).replace("\n", newline)

    def value(key: str, at: int) -> str:
        """The new value of key, indented like the line of the key that starts at `at`."""
        line = source[source.rfind("\n", 0, at) + 1:at]
        indent = line[:len(line) - len(line.lstrip(" \t"))]
        return _json_value(new[key], indent).replace("\n", newline)

    order, edits = list(new), []
    for index, key in enumerate(order):
        if old.get(key) == new[key]:
            continue
        if key in fields:
            _, start, value_start, value_end = fields[key]
            edits.append((value_start, value_end, value(key, start)))
            continue
        # A field the file lacks goes before the next field of the layout, or after the last one.
        later = next((name for name in order[index + 1:] if name in fields), None)
        if later is not None:
            space, start = fields[later][:2]
            edits.append((start, start, f"{json.dumps(key)}: {value(key, start)}," + source[space:start]))
        else:
            space, start, _, value_end = fields[list(fields)[-1]]
            edits.append((value_end, value_end, "," + source[space:start] + f"{json.dumps(key)}: {value(key, start)}"))
    pieces, last = [], 0
    for start, end, text in sorted(edits, key=lambda edit: edit[0]):
        pieces += [source[last:start], text]
        last = end
    return "".join(pieces) + source[last:]


def save_dossier(state: Path, dossier: dict) -> None:
    """Write a dossier. In an existing file only the changed fields are rewritten, so the rest keeps its form,
    its byte order mark and its line endings, and a one-line change stays a one-line diff."""
    path = dossier_path(state, dossier["id"])
    new = validate_dossier(dossier, dossier["id"])
    if not path.is_file():
        write_text(path, dossier_text(new))
        return
    raw = read_bytes(path)
    old = validate_dossier(parse_json(raw, str(path)), dossier["id"])
    mark = "﻿" if raw.startswith(codecs.BOM_UTF8) else ""
    write_text(path, mark + _patched(raw.decode("utf-8-sig"), old, new))


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
    day = _day(day or clock.real_today().isoformat(), "date")
    return validate_dossier({**dossier, "watch": {**watch, "sources": _checked(watch["sources"], url, day)}}, dossier["id"])


def mark_provided(dossier: dict, url: str, by: str, day: str | None = None) -> dict:
    """Record that a person reviewed a watched page and provided what it says, for a project under local-only."""
    watch = _watch(dossier)
    if not any(item["url"] == url for item in watch["sources"]):
        raise ValueError(f"{url} is not a watched source of the dossier. Run market due to list them.")
    by = _text(by, "--by")
    day = _day(day or clock.real_today().isoformat(), "date")
    sources = [{**item, "provided_by": by} if item["url"] == url else item for item in _checked(watch["sources"], url, day)]
    return validate_dossier({**dossier, "watch": {**watch, "sources": sources}}, dossier["id"])


def record_change(dossier: dict, change: dict, today: str | None = None) -> dict:
    """Keep a verified change; when its source is a watched page, that page counts as checked today."""
    watch = _watch(dossier)
    entry = {key: change[key] for key in ("competitor", "what", "date", "source", "verified_by")}
    today = today or clock.real_today().isoformat()
    watch = {**watch, "changes": [*watch["changes"], entry], "sources": _checked(watch["sources"], entry["source"], today)}
    return validate_dossier({**dossier, "watch": watch}, dossier["id"])


def set_paused(dossier: dict, paused: bool) -> dict:
    return validate_dossier({**dossier, "watch": {**_watch(dossier), "paused": paused}}, dossier["id"])


def due_issue(dossier_id: str, source: dict, research: str = "public-sources") -> dict:
    """The title and body of the issue a scheduled job opens for a source to review. Under local-only, no agent
    opens the page: a person reviews it and records it with market provided."""
    if research == "local-only":
        return {
            "title": f"Market watch: review {source['competitor']} {source['kind']} ({dossier_id})",
            "body": (f"The watched source {source['url']} of market dossier `{dossier_id}` is due for review "
                     f"(last checked: {source.get('last_checked', 'never')}).\n\n"
                     f"Research is local-only: no agent opens the page. A person reviews it, then records it:\n\n"
                     f"- `openguildkit market provided {dossier_id} --url {source['url']} --by INITIALS`\n"
                     f"- then, for a change to keep: `openguildkit market change {dossier_id} --competitor "
                     f"{source['competitor']} --what TEXT --source {source['url']} --date YYYY-MM-DD "
                     f"--verified-by NAME`\n"),
        }
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
    today = today or clock.real_today()
    gaps = list(dossier.get("unknowns", []))
    for field in ("market", "audience", "feature"):
        if dossier[field] == TO_DESCRIBE:
            gaps.append(f"Describe the dossier's {field}: openguildkit market describe {dossier['id']} --{field} TEXT.")
    kinds = {item["kind"] for item in dossier["competitors"]}
    for kind in KINDS:
        if kind not in kinds:
            gaps.append(f"No {kind} competitor is listed.")
    provided = {item["url"] for item in dossier.get("watch", {}).get("sources", []) if "provided_by" in item}
    observed = {item["competitor"] for item in dossier["observations"]}
    for competitor in dossier["competitors"]:
        if competitor["id"] not in observed:
            gaps.append(f"No dated observation for {competitor['name']}.")
    for item in dossier["observations"]:
        age = (today - date.fromisoformat(item["source"]["date"])).days
        if age > STALE_DAYS:
            gaps.append(f"Observation {item['id']} is {age} days old.")
        if research == "local-only" and item["source"]["ref"].startswith("http") and item["source"]["ref"] not in provided:
            gaps.append(f"Observation {item['id']} cites a public page although research is local-only: confirm it was provided.")
    for index, item in enumerate(dossier.get("watch", {}).get("changes", []), start=1):
        if research == "local-only" and item["source"].startswith("http") and item["source"] not in provided:
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
    today = today or clock.real_today()
    due = []
    for source in watch["sources"]:
        last = source.get("last_checked")
        if last is None or (today - date.fromisoformat(last)).days >= watch["every_days"]:
            due.append(source)
    return due


def _words(text: str) -> set[str]:
    """Significant words of a text, without accents, case or a plural s."""
    plain = unicodedata.normalize("NFKD", text.casefold()).encode("ascii", "ignore").decode()
    return {word.removesuffix("s") for word in re.findall(r"[a-z0-9]{3,}", plain) if word not in _COMMON_WORDS}


def relevance_note(dossier: dict, brief: str) -> str | None:
    """One line when the dossier's feature shares no word with the task brief: it may be about another function.

    A mention of the dossier itself, by its ID or its file name, says which dossier to use, not what the task is
    about, so it does not count as a shared word.
    """
    brief = re.sub(rf"(?<![\w-]){re.escape(dossier['id'])}(?:\.json)?(?![\w-])", " ", brief, flags=re.IGNORECASE)
    if dossier["feature"] == TO_DESCRIBE or _words(dossier["feature"]) & _words(brief):
        return None
    return (f"The dossier {dossier['id']} is about \"{dossier['feature']}\", which shares no word with the task brief: "
            "check that it is the right dossier before citing it, or describe its feature with market describe.")


def scope_entry(dossier: dict, research: str, today: date | None = None, brief: str | None = None) -> dict:
    """What a consultation carries: observations and verified changes with their age, the gaps, and a relevance note."""
    today = today or clock.real_today()
    entry = {key: dossier[key] for key in ("id", "market", "audience", "feature", "competitors")}
    entry["observations"] = [
        {**item, "age_days": (today - date.fromisoformat(item["source"]["date"])).days} for item in dossier["observations"]
    ]
    if dossier.get("watch", {}).get("changes"):
        entry["changes"] = [
            {**item, "age_days": (today - date.fromisoformat(item["date"])).days} for item in dossier["watch"]["changes"]
        ]
    entry["gaps"] = dossier_gaps(dossier, research, today)
    note = relevance_note(dossier, brief) if brief else None
    if note:
        entry["relevance"] = note
    return entry
