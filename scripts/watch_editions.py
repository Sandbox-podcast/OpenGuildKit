"""Watch the edition of each bundled reference on its source page.

    python3 -I scripts/watch_editions.py --changes editions.json

For each reference that declares an `edition`, the script opens its source pages in order
and looks for the edition's text ("2022", "Rev. 5", "ISO 19005-1:2005") in the page, without
regard to case, spacing or HTML markup. It records in scripts/edition-watch.json, per
reference, the page, the edition last seen there, the day it was seen and the day of the
check. When an edition recorded as seen is no longer on the page, the reference is marked
"may-have-changed": the edition may have changed, and a person opens the page to decide.

What this can and cannot tell. A page that rewrites or reformats its edition text ("Rev 5"
instead of "Rev. 5") raises a false alarm. A publisher that keeps the old edition's page
online, unchanged, hides a new edition: nothing is detected. A page whose text is built by
scripts or served as a PDF rarely shows the edition to this reader: it stays "not-found".
A short edition such as a year can match an unrelated date on the page. The watch never
changes the catalog: a person updates the reference, its rules and this file.
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openguildkit.clock import today  # noqa: E402
from openguildkit.references import load_references  # noqa: E402

STATE = ROOT / "scripts" / "edition-watch.json"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_BYTES = 4 * 1024 * 1024
CHANGED = "may-have-changed"
TITLE = "Edition may have changed: {reference}"
_TAGS = re.compile(r"<(script|style)\b.*?</\1\s*>|<[^>]+>", re.IGNORECASE | re.DOTALL)
_SPACE = re.compile(r"\s+")


def watched(families: dict) -> list[dict]:
    """The references that declare an edition, with their source pages, by ID."""
    entries = [
        {"reference": record["id"], "family": family["id"], "edition": record["edition"],
         "pages": [source["url"] for source in record["sources"]]}
        for family in families.values() for record in family["references"] if record.get("edition")
    ]
    return sorted(entries, key=lambda entry: entry["reference"])


def fetch(url: str, timeout: float = 30) -> dict:
    """GET the page with a browser User-Agent and return its text, or the reason it did not answer."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return {"status": response.status, "text": response.read(MAX_BYTES).decode(charset, "replace")}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "text": None}
    except Exception as error:  # timeouts, DNS and TLS failures: the page did not answer
        return {"status": None, "text": None, "error": f"{type(error).__name__}: {error}"[:200]}


def page_text(raw: str) -> str:
    """The visible words of a page: markup removed, entities decoded, spacing collapsed."""
    return _SPACE.sub(" ", html.unescape(_TAGS.sub(" ", raw))).strip()


def shows_edition(text: str, edition: str) -> bool:
    """True when the edition's words appear in the text as a whole, ignoring case and spacing."""
    words = [re.escape(word) for word in edition.split()]
    pattern = r"(?<![0-9A-Za-z])" + r"\s+".join(words) + r"(?![0-9A-Za-z])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def _answered(result: dict) -> bool:
    return result.get("text") is not None and result.get("status") is not None and result["status"] < 400


def observe(entry: dict, previous: dict, fetcher, day: str) -> dict:
    """The new state of one reference after opening its pages."""
    record = {"family": entry["family"], "edition": entry["edition"], "page": entry["pages"][0],
              "seen": previous.get("seen"), "seen_on": previous.get("seen_on"), "checked": day}
    if previous.get("page") in entry["pages"]:
        record["page"] = previous["page"]
    answered = False
    for url in entry["pages"]:
        result = fetcher(url)
        if not _answered(result):
            continue
        answered = True
        if shows_edition(page_text(result["text"]), entry["edition"]):
            return {**record, "page": url, "seen": entry["edition"], "seen_on": day, "status": "found"}
    if not answered:
        return {**record, "status": "unreachable"}
    status = CHANGED if previous.get("seen") == entry["edition"] else "not-found"
    return {**record, "status": status}


def watch(families: dict, state: dict, fetcher=fetch, day: str | None = None) -> dict:
    """Check every watched reference and return the new state; references gone from the catalog drop out."""
    day = day or today().isoformat()
    known = state.get("references", {})
    return {
        "schema_version": 1,
        "references": {
            entry["reference"]: observe(entry, known.get(entry["reference"], {}), fetcher, day)
            for entry in watched(families)
        },
    }


def issue(reference: str, record: dict) -> dict:
    """The title and body of the issue that asks a person to open the page."""
    body = (
        f"The page {record['page']} no longer shows the edition \"{record['edition']}\" that the catalog cites "
        f"for the reference {record['family']}/{reference}. It was last seen there on {record['seen_on']}; "
        f"checked {record['checked']}.\n\n"
        "The edition may have changed. Open the page and decide:\n\n"
        "- A new edition is out: update the reference's `edition` and its source `checked` date, review the packs "
        "and rules that cite it (see the link report), then run `python3 -I scripts/watch_editions.py` and commit "
        "`scripts/edition-watch.json`.\n"
        "- The page only rewrote or moved the edition text: run the script and commit the file, or point the "
        "reference at the page that names the edition.\n\n"
        "This check compares text only: it can raise a false alarm, and it cannot see a new edition published "
        "on another page."
    )
    return {"reference": reference, "title": TITLE.format(reference=reference), "body": body}


def changes(state: dict) -> dict:
    """The references whose edition may have changed, with the issue to open for each."""
    return {"may_have_changed": [
        {**record, **issue(reference, record)}
        for reference, record in state["references"].items() if record["status"] == CHANGED
    ]}


def read_state(path: Path) -> dict:
    if not path.is_file():
        return {"schema_version": 1, "references": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != 1 or not isinstance(state.get("references"), dict):
        raise ValueError(f"{path.as_posix()} is not an edition watch file of schema version 1.")
    return state


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Watch the edition of each bundled reference on its source page.")
    parser.add_argument("--state", type=Path, default=STATE, help="The watch file to read and update.")
    parser.add_argument("--changes", type=Path, help="Write the references whose edition may have changed, as JSON.")
    parser.add_argument("--timeout", type=float, default=30, help="Seconds to wait for each page.")
    args = parser.parse_args(argv)
    try:
        state = watch(load_references(), read_state(args.state), lambda url: fetch(url, args.timeout))
    except ValueError as error:
        print(f"watch_editions: {error}", file=sys.stderr)
        return 1
    write_json(args.state, state)
    found = changes(state)
    if args.changes:
        write_json(args.changes, found)
    counts = {}
    for record in state["references"].values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    print(f"{len(state['references'])} references with an edition: "
          + ", ".join(f"{count} {status}" for status, count in sorted(counts.items())))
    for item in found["may_have_changed"]:
        print(f"  the edition may have changed: {item['family']}/{item['reference']} ({item['edition']}), {item['page']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
