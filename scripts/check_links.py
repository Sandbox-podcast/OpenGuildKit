"""Check every source link of the bundled catalog and write a dated report.

    python3 -I scripts/check_links.py --out link-report

The report classifies each URL as available, redirected to another page (with its
target), dead (an HTTP error such as 404, 410 or 500) or to-recheck (401, 403, 429,
202, 502, 503, 504, a timeout or a network error: sites send these to scripts or
while overloaded, so check the page in a browser). A redirect that only adds a query
string, such as a language or view parameter, counts as available. For each URL it lists
the references, packs, patterns, boards and sectors that cite it, with the version and
rules of each pack, so a maintainer can see what a new edition would affect. Only the
bundled catalog is read: project catalogs stay in their projects. The report also lists
the sources whose `checked` date is older than --max-age days (180 by default). The exit
code is 1 when at least one link is dead.

    python3 -I scripts/check_links.py --out link-report --stamp
    python3 -I scripts/check_links.py --stamp-from link-report/links-2026-11-21.json

--stamp writes the `checked` date of every source of the bundled catalog from the report:
a source whose page answered (available, or redirected to a page that answered) gets the
report's date; any other source keeps its date, or, when it has none, gets the day its URL
entered the catalog, read from the Git history (it needs the full history, not a shallow
clone). Run it again after a merge: the result depends only on the report and the history.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openguildkit.catalog import load_catalog  # noqa: E402
from openguildkit.clock import today  # noqa: E402
from openguildkit.deliverables import load_deliverables  # noqa: E402
from openguildkit.references import load_references  # noqa: E402
from openguildkit.tools import load_tools  # noqa: E402

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
RECHECK_CODES = {202, 401, 403, 429, 502, 503, 504}
CATEGORIES = ("dead", "redirected", "to-recheck", "available")
# A page that answered: available, or redirected to a page that answered.
ANSWERED = ("available", "redirected")
REGISTRY = ROOT / "src" / "openguildkit" / "registry"
# The registry folders whose records carry `sources`.
SOURCE_FOLDERS = ("packs", "boards", "patterns", "sectors", "references", "deliverables")
DEFAULT_MAX_AGE = 180


def collect_citations(
    catalog: dict, families: dict, tools: dict | None = None, deliverables: dict | None = None
) -> dict[str, list[dict]]:
    """Map each source URL to the bundled records that cite it."""
    citations: dict[str, list[dict]] = {}

    def cite(url: str, entry: dict, source: dict | None = None) -> None:
        if source and "checked" in source:
            entry = {**entry, "checked": source["checked"]}
        citations.setdefault(url, []).append(entry)

    for collection in ("packs", "patterns", "boards", "sectors"):
        for record in catalog[collection].values():
            entry = {"collection": collection, "id": record["id"]}
            if collection == "packs":
                entry["version"] = record["version"]
                entry["rules"] = [rule["id"] for rule in record["rules"]]
            for source in record["sources"]:
                cite(source["url"], entry, source)
    for family in families.values():
        for record in family["references"]:
            entry = {"collection": "references", "id": record["id"], "family": family["id"]}
            if record.get("edition"):
                entry["edition"] = record["edition"]
            if record.get("packs"):
                entry["packs"] = record["packs"]
            for source in record["sources"]:
                cite(source["url"], entry, source)
    for record in (deliverables or {}).values():
        for source in record["sources"]:
            cite(source["url"], {"collection": "deliverables", "id": record["id"]}, source)
    for tool in (tools or {}).values():
        entry = {"collection": "tools", "id": tool["id"]}
        cite(tool["homepage"], entry)
        if "api" in tool:
            cite(tool["api"]["docs"], entry)
        for server in tool["servers"]:
            cite(server["source"], {**entry, "server": server["id"]})
    return dict(sorted(citations.items()))


def fetch(url: str, timeout: float = 30) -> dict:
    """GET the URL with a browser User-Agent, following redirects."""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(65536)
            return {"status": response.status, "final_url": response.geturl()}
    except urllib.error.HTTPError as error:
        return {"status": error.code, "final_url": error.geturl() or url}
    except Exception as error:  # timeouts, DNS and TLS failures all need a manual check
        return {"status": None, "final_url": url, "error": f"{type(error).__name__}: {error}"[:200]}


def classify(url: str, result: dict) -> str:
    status = result.get("status")
    if status is None or status in RECHECK_CODES:
        return "to-recheck"
    if status >= 400:
        return "dead"
    final, requested = urlsplit(result.get("final_url", url)), urlsplit(url)
    if (final.scheme, final.netloc, final.path) != (requested.scheme, requested.netloc, requested.path):
        return "redirected"
    return "available"


def stale_sources(citations: dict[str, list[dict]], day: date, max_age: int) -> list[dict]:
    """The URLs that a record cites with a checked date older than max_age days, oldest first."""
    limit = (day - timedelta(days=max_age)).isoformat()
    stale = []
    for url, entries in citations.items():
        old = [entry for entry in entries if entry.get("checked") and entry["checked"] < limit]
        if old:
            stale.append({"url": url, "checked": min(entry["checked"] for entry in old), "cited_by": old})
    return sorted(stale, key=lambda item: (item["checked"], item["url"]))


def check(citations: dict[str, list[dict]], fetcher=fetch, workers: int = 8, max_age: int = DEFAULT_MAX_AGE) -> dict:
    urls = list(citations)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(fetcher, urls))
    links = []
    for url, result in zip(urls, results):
        link = {"url": url, "category": classify(url, result), "status": result.get("status"),
                "cited_by": citations[url]}
        if link["category"] == "redirected":
            link["target"] = result["final_url"]
        if result.get("error"):
            link["error"] = result["error"]
        links.append(link)
    summary = {category: sum(1 for link in links if link["category"] == category) for category in CATEGORIES}
    day = today()
    return {"date": day.isoformat(), "summary": summary, "links": links, "max_age_days": max_age,
            "stale": stale_sources(citations, day, max_age)}


def _citation(entry: dict) -> str:
    text = f"{entry['collection']}/{entry['id']}"
    if "version" in entry:
        text += f"@{entry['version']} (rules: {', '.join(entry['rules'])})"
    if "edition" in entry:
        text += f", edition {entry['edition']}"
    if "packs" in entry:
        text += f", applied by {', '.join(entry['packs'])}"
    if "server" in entry:
        text += f", server {entry['server']}"
    if "checked" in entry:
        text += f", checked {entry['checked']}"
    return text


def render_markdown(report: dict) -> str:
    lines = [
        f"# Catalog link report, {report['date']}",
        "",
        "| Category | Links |",
        "|---|---:|",
        *(f"| {category} | {report['summary'][category]} |" for category in CATEGORIES),
        "",
    ]
    for category in CATEGORIES[:3]:
        links = [link for link in report["links"] if link["category"] == category]
        lines += [f"## {category.capitalize()} ({len(links)})", ""]
        if not links:
            lines += ["None.", ""]
        for link in links:
            detail = f"HTTP {link['status']}" if link["status"] else link.get("error", "no response")
            if "target" in link:
                detail += f", now {link['target']}"
            lines.append(f"- {link['url']} ({detail})")
            lines += [f"  - {_citation(entry)}" for entry in link["cited_by"]]
        lines.append("")
    stale = report.get("stale", [])
    lines += [f"## Checked more than {report.get('max_age_days', DEFAULT_MAX_AGE)} days ago ({len(stale)})", ""]
    if not stale:
        lines += ["None.", ""]
    for item in stale:
        lines.append(f"- {item['url']} (checked {item['checked']})")
        lines += [f"  - {_citation(entry)}" for entry in item["cited_by"]]
    if stale:
        lines.append("")
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"links-{report['date']}"
    json_path, markdown_path = stem.with_suffix(".json"), stem.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _run_git(arguments: list[str], root: Path) -> str:
    result = subprocess.run(["git", *arguments], cwd=root, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"git {arguments[0]} failed in {root.as_posix()}: {result.stderr.strip()}")
    return result.stdout


def history_dates(root: Path = ROOT, git=_run_git):
    """A function that gives the author date of the oldest commit that added a URL, as YYYY-MM-DD."""
    if git(["rev-parse", "--is-shallow-repository"], root).strip() == "true":
        raise ValueError("The clone is shallow: run git fetch --unshallow so the history dates each source.")

    def introduced(url: str) -> str | None:
        dates = git(["log", "--format=%ad", "--date=short", "-S", url], root).split()
        return dates[-1] if dates else None

    return introduced


def _dated(source: dict, day: str) -> dict:
    """The source with its checked date set, placed right after the URL."""
    result = {}
    for key, value in source.items():
        if key != "checked":
            result[key] = value
        if key == "url":
            result["checked"] = day
    return result


def _source_lists(value):
    """Every `sources` list of a record file, in file order."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "sources" and isinstance(item, list):
                yield item
            else:
                yield from _source_lists(item)
    elif isinstance(value, list):
        for item in value:
            yield from _source_lists(item)


def _write_like(path: Path, text: str, data) -> bool:
    """Write the data in the file's own layout (2 spaces, escaped or literal non-ASCII); False if unchanged."""
    for ascii_only in (False, True):
        if json.dumps(json.loads(text), ensure_ascii=ascii_only, indent=2) + "\n" == text:
            break
    else:
        raise ValueError(f"{path.as_posix()} is not laid out with 2 spaces and one key per line; reformat it first.")
    new = json.dumps(data, ensure_ascii=ascii_only, indent=2) + "\n"
    if new == text:
        return False
    path.write_text(new, encoding="utf-8", newline="\n")
    return True


def stamp(report: dict, introduced, registry: Path = REGISTRY) -> dict:
    """Set the checked date of every bundled source from a link report; see the module docstring."""
    answered = {link["url"] for link in report["links"] if link["category"] in ANSWERED}
    day = report["date"]
    result = {"answered": set(), "unanswered": {}, "files": []}
    history: dict[str, str | None] = {}
    for folder in SOURCE_FOLDERS:
        for path in sorted((registry / folder).glob("*.json"), key=lambda item: item.name):
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            for sources in _source_lists(data):
                for index, source in enumerate(sources):
                    url = source["url"]
                    if url in answered:
                        checked = max(day, source.get("checked", day))
                        result["answered"].add(url)
                    else:
                        if url not in history:
                            history[url] = introduced(url)
                        checked = source.get("checked") or history[url]
                        if checked is None:
                            raise ValueError(f"{url} is not in the Git history yet: commit {path.as_posix()} first.")
                        result["unanswered"][url] = checked
                    sources[index] = _dated(source, checked)
            if _write_like(path, text, data):
                result["files"].append(path.relative_to(registry).as_posix())
    result["answered"] = sorted(result["answered"])
    result["unanswered"] = dict(sorted(result["unanswered"].items()))
    return result


def _print_stamp(result: dict, report: dict) -> None:
    categories = {link["url"]: link for link in report["links"]}
    print(f"Dated {len(result['answered'])} answered source URLs {report['date']}; "
          f"{len(result['unanswered'])} did not answer and keep their date. {len(result['files'])} files changed.")
    for url, checked in result["unanswered"].items():
        link = categories.get(url, {})
        status = f"HTTP {link['status']}" if link.get("status") else link.get("error", "not in the report")
        print(f"  open by hand: {url} ({link.get('category', 'unchecked')}, {status}), checked {checked}")


def _stamp_and_print(report: dict) -> int:
    try:
        _print_stamp(stamp(report, history_dates()), report)
    except ValueError as error:
        print(f"check_links: {error}", file=sys.stderr)
        return 1
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the source links of the bundled catalog.")
    parser.add_argument("--out", type=Path, default=Path("link-report"), help="Directory for the dated report.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel requests.")
    parser.add_argument("--timeout", type=float, default=30, help="Seconds to wait for each URL.")
    parser.add_argument("--max-age", type=int, default=DEFAULT_MAX_AGE,
                        help="List the sources whose checked date is older than this many days.")
    parser.add_argument("--stamp", action="store_true", help="Write the checked dates of the bundled sources.")
    parser.add_argument("--stamp-from", type=Path, metavar="REPORT",
                        help="Write the checked dates from a saved JSON report, without opening the pages.")
    args = parser.parse_args(argv)
    if args.max_age < 0:
        parser.error("--max-age must be zero or more days")
    if args.stamp_from:
        report = json.loads(args.stamp_from.read_text(encoding="utf-8"))
        return _stamp_and_print(report)
    catalog = load_catalog()
    citations = collect_citations(catalog, load_references(), load_tools(), load_deliverables(catalog))
    report = check(citations, lambda url: fetch(url, args.timeout), args.workers, args.max_age)
    json_path, markdown_path = write_report(report, args.out)
    summary = ", ".join(f"{count} {category}" for category, count in report["summary"].items())
    print(f"{len(report['links'])} links: {summary}. {len(report['stale'])} checked more than {args.max_age} days ago. "
          f"Report: {markdown_path} and {json_path.name}")
    if args.stamp and _stamp_and_print(report):
        return 1
    return 1 if report["summary"]["dead"] else 0


if __name__ == "__main__":
    sys.exit(main())
