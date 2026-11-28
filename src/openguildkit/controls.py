"""The controls of OpenGuildKit itself and the frameworks they may answer: a registry and the tables of docs/compliance.md (issue #482).

registry/controls.json lists what OpenGuildKit does that an auditor can ask about: what it guarantees, the commands and the
code that hold it, what it does not cover, and for each framework of the catalog the clause it answers. A clause is entered
only with the address of the source read and the day it was read; a cell without them stays empty and the page says "to
verify". Nothing here quotes a framework, and nothing states that a project complies with one.
Entry: load, validate, locate, render, update_page.
Tests: tests/test_controls.py.
"""

import re
from datetime import date
from functools import cache
from pathlib import Path

from . import clock
from .catalog import package_file
from .storage import load_json

FIELDS = {"id", "title", "guarantees", "not_covered", "commands", "code", "in_dossier", "maps_to"}
MAPPING_FIELDS = ("reference", "clause", "source", "checked")
MAX_CLAUSE = 80  # characters: a locator such as "Article 14", never a sentence of the text
START, END = "<!-- controls:start -->", "<!-- controls:end -->"
ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@cache
def _references() -> dict[str, dict]:
    """The references of the bundled catalog by ID."""
    found = {}
    for path in sorted(package_file("registry", "references").iterdir(), key=lambda item: item.name):
        if path.name.endswith(".json"):
            for record in load_json(path)["references"]:
                found[record["id"]] = record
    return found


def load() -> dict:
    """The registry shipped with the package, checked."""
    data = load_json(package_file("registry", "controls.json"))
    validate(data)
    return data


def _text(value: object, where: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\n" in value:
        raise ValueError(f"{where} must be a non-empty line of text.")


def _mapping(entry: object, where: str, frameworks: list) -> None:
    """One clause read from a framework: its reference in the catalog and on the page, the clause, the source, the day."""
    if not isinstance(entry, dict):
        raise ValueError(f"{where}: an entry of maps_to is an object.")
    for key in entry:
        if key not in MAPPING_FIELDS:
            raise ValueError(f"{where}: unknown field {key} in maps_to.")
    for key in MAPPING_FIELDS:
        if key not in entry:
            raise ValueError(f"{where}: an entry of maps_to needs {key}: a clause is entered with the source read and the "
                             "day it was read, and a cell without them stays empty.")
    if entry["reference"] not in _references():
        raise ValueError(f"{where}: reference {entry['reference']!r} is not a reference of the catalog.")
    if entry["reference"] not in frameworks:
        raise ValueError(f"{where}: reference {entry['reference']!r} is not one of the frameworks of the page: add it "
                         "to frameworks first.")
    _text(entry["clause"], f"{where}: clause")
    if len(entry["clause"]) > MAX_CLAUSE:
        raise ValueError(f"{where}: clause is a locator of at most {MAX_CLAUSE} characters, not a text of the framework.")
    source = entry["source"]
    if not isinstance(source, str) or not source.startswith("https://") or len(source.split()) != 1:
        raise ValueError(f"{where}: source is the https address of the page read.")
    checked = entry["checked"]
    try:
        valid = isinstance(checked, str) and DAY.fullmatch(checked) and date.fromisoformat(checked) <= clock.today()
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{where}: checked is the day the source was read, YYYY-MM-DD, not in the future.")


def validate(data: dict) -> None:
    """Refuse a registry that names an unknown framework, a control twice, or a clause without its source and its day."""
    if not isinstance(data, dict) or data.keys() != {"schema_version", "frameworks", "controls"} \
            or data["schema_version"] != 1:
        raise ValueError("controls.json holds schema_version 1, frameworks and controls.")
    frameworks = data["frameworks"]
    unknown = [item for item in frameworks if item not in _references()]
    if unknown or len(set(frameworks)) != len(frameworks):
        raise ValueError(f"frameworks lists each reference of the catalog once: {', '.join(map(str, unknown)) or 'duplicate'}.")
    seen = set()
    for item in data["controls"]:
        if not isinstance(item, dict) or item.keys() != FIELDS or not ID.fullmatch(str(item["id"])):
            raise ValueError(f"A control holds {', '.join(sorted(FIELDS))}, and an ID of lowercase words.")
        where = item["id"]
        if where in seen:
            raise ValueError(f"The control {where} is listed twice.")
        seen.add(where)
        for key in ("title", "guarantees", "not_covered"):
            _text(item[key], f"{where}: {key}")
        for key in ("commands", "in_dossier"):
            if not isinstance(item[key], list) or not all(isinstance(value, str) for value in item[key]):
                raise ValueError(f"{where}: {key} is a list of text.")
        if not item["code"] or not all(isinstance(place, dict) and place.keys() == {"file", "symbol", "line"}
                                       and isinstance(place["line"], int) for place in item["code"]):
            raise ValueError(f"{where}: code names at least one file, symbol and line.")
        if not isinstance(item["maps_to"], list):
            raise ValueError(f"{where}: maps_to is a list.")
        for entry in item["maps_to"]:
            _mapping(entry, where, frameworks)


def locate(root: Path, file: str, symbol: str) -> int | None:
    """The line where a function, a class or a constant of a file is defined, or None."""
    pattern = re.compile(rf"\s*(?:(?:async\s+)?def|class)\s+{re.escape(symbol)}\b|{re.escape(symbol)}\s*[:=]")
    for number, line in enumerate((root / file).read_text(encoding="utf-8").splitlines(), start=1):
        if pattern.match(line):
            return number
    return None


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _read(item: dict, framework: str) -> str:
    found = [f"{entry['clause']} ([source]({entry['source']}), read {entry['checked']})"
             for entry in item["maps_to"] if entry["reference"] == framework]
    return _cell("; ".join(found)) if found else "to verify"


def render(data: dict) -> str:
    """The two tables of the page, from the registry alone and the titles of the catalog: the controls with where each
    is checked and what it does not cover, then each control against each framework."""
    frameworks = data["frameworks"]
    rows = ["| Control | What OpenGuildKit guarantees | Where to check it | Not covered by OpenGuildKit |",
            "|---|---|---|---|"]
    for item in data["controls"]:
        where = [f"`{command}`" for command in item["commands"]]
        where += [f"`{place['file']}:{place['line']}` ({place['symbol']})" for place in item["code"]]
        if item["in_dossier"]:
            where.append("dossier: " + ", ".join(f"`{name}`" for name in item["in_dossier"]))
        rows.append(f"| `{item['id']}`: {_cell(item['title'])} | {_cell(item['guarantees'])} | {_cell('; '.join(where))} "
                    f"| {_cell(item['not_covered'])} |")
    matrix = ["| Control | " + " | ".join(f"`{name}`" for name in frameworks) + " |", "|---|" + "---|" * len(frameworks)]
    matrix += [f"| `{item['id']}` | " + " | ".join(_read(item, name) for name in frameworks) + " |"
               for item in data["controls"]]
    legend = [f"- `{name}`: {_references()[name].get('title_en') or _references()[name]['title']}" for name in frameworks]
    return "\n".join(["#### The controls", "", *rows, "", "#### The controls against the frameworks", "", *matrix, "",
                      *legend])


def update_page(text: str, data: dict) -> str:
    """The page with the generated part, between its two markers, replaced by the tables of the registry."""
    if START not in text or END not in text or text.index(START) > text.index(END):
        raise ValueError(f"The page needs {START} and {END} around the generated tables.")
    head, rest = text.split(START, 1)
    return f"{head}{START}\n{render(data)}\n{END}{rest.split(END, 1)[1]}"
