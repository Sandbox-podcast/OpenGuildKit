"""Check every source link of the bundled catalog and write a dated report.

    python3 -I scripts/check_links.py --out link-report

The report classifies each URL as available, redirected to another page (with its
target), dead (an HTTP error such as 404, 410 or 500) or to-recheck (401, 403, 429,
202, 502, 503, 504, a timeout or a network error: sites send these to scripts or
while overloaded, so check the page in a browser). A redirect that only adds a query
string, such as a language or view parameter, counts as available. For each URL it lists
the references, packs, patterns, boards and sectors that cite it, with the version and
rules of each pack, so a maintainer can see what a new edition would affect. Only the
bundled catalog is read: project catalogs stay in their projects. The exit code is 1
when at least one link is dead.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from openguildkit.catalog import load_catalog  # noqa: E402
from openguildkit.references import load_references  # noqa: E402
from openguildkit.tools import load_tools  # noqa: E402

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
RECHECK_CODES = {202, 401, 403, 429, 502, 503, 504}
CATEGORIES = ("dead", "redirected", "to-recheck", "available")


def collect_citations(catalog: dict, families: dict, tools: dict | None = None) -> dict[str, list[dict]]:
    """Map each source URL to the bundled records that cite it."""
    citations: dict[str, list[dict]] = {}

    def cite(url: str, entry: dict) -> None:
        citations.setdefault(url, []).append(entry)

    for collection in ("packs", "patterns", "boards", "sectors"):
        for record in catalog[collection].values():
            entry = {"collection": collection, "id": record["id"]}
            if collection == "packs":
                entry["version"] = record["version"]
                entry["rules"] = [rule["id"] for rule in record["rules"]]
            for source in record["sources"]:
                cite(source["url"], entry)
    for family in families.values():
        for record in family["references"]:
            entry = {"collection": "references", "id": record["id"], "family": family["id"]}
            if record.get("edition"):
                entry["edition"] = record["edition"]
            if record.get("packs"):
                entry["packs"] = record["packs"]
            for source in record["sources"]:
                cite(source["url"], entry)
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


def check(citations: dict[str, list[dict]], fetcher=fetch, workers: int = 8) -> dict:
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
    return {"date": date.today().isoformat(), "summary": summary, "links": links}


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
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"links-{report['date']}"
    json_path, markdown_path = stem.with_suffix(".json"), stem.with_suffix(".md")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Check the source links of the bundled catalog.")
    parser.add_argument("--out", type=Path, default=Path("link-report"), help="Directory for the dated report.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel requests.")
    parser.add_argument("--timeout", type=float, default=30, help="Seconds to wait for each URL.")
    args = parser.parse_args(argv)
    citations = collect_citations(load_catalog(), load_references(), load_tools())
    report = check(citations, lambda url: fetch(url, args.timeout), args.workers)
    json_path, markdown_path = write_report(report, args.out)
    summary = ", ".join(f"{count} {category}" for category, count in report["summary"].items())
    print(f"{len(report['links'])} links: {summary}. Report: {markdown_path} and {json_path.name}")
    return 1 if report["summary"]["dead"] else 0


if __name__ == "__main__":
    sys.exit(main())
