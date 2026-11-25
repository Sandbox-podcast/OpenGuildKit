"""Keep the project's dependency alerts in one register, from the reports of its own scanners.

The CLI does not scan anything: it reads the JSON report a scanner the project approves
already produced (npm audit, pip-audit, OSV-Scanner or GitHub Dependabot alerts). The register
.openguildkit/alerts.json, committed with the project, holds one entry per package and advisory,
whatever scanner reported it, with a life cycle: open, confirmed, dismissed or resolved.
Tasks link the alerts that concern them; a confirmed critical alert blocks their approval and
completion until it is resolved or a person records why it is accepted.
"""

import hashlib
import json
import re
from pathlib import Path

from . import clock
from .storage import read_json, write_json

REGISTER_FILE = "alerts.json"
STATUSES = ("open", "confirmed", "dismissed", "resolved")
REVIEW_STATUSES = ("open", "confirmed", "dismissed")
ACTIVE = ("open", "confirmed")
LEGACY_STATUSES = {"to-verify": "open"}
SEVERITY_RANK = {"unknown": 0, "low": 1, "moderate": 2, "medium": 2, "high": 3, "critical": 4}
SEVERITIES = ("low", "moderate", "high", "critical")
IMPORTS_KEPT = 20
_ECOSYSTEMS = {
    "pip": "pypi", "pypi": "pypi", "npm": "npm", "go": "go", "golang": "go", "maven": "maven", "nuget": "nuget",
    "rubygems": "rubygems", "bundler": "rubygems", "rust": "crates.io", "cargo": "crates.io", "crates.io": "crates.io",
    "composer": "packagist", "packagist": "packagist", "pub": "pub", "swift": "swifturl", "swifturl": "swifturl",
    "actions": "github-actions", "github actions": "github-actions",
}
_PRIMARY = (re.compile(r"GHSA-[a-z0-9-]+", re.IGNORECASE), re.compile(r"CVE-\d+-\d+", re.IGNORECASE))


def _ecosystem(name: str) -> str:
    """One name per ecosystem, so Dependabot's pip and pip-audit's PyPI meet."""
    key = " ".join(str(name or "unknown").lower().split())
    return _ECOSYSTEMS.get(key, key)


def _package(ecosystem: str, name: str) -> str:
    name = str(name or "unknown").strip()
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "pypi" else name.lower()


def _primary(aliases: list[str]) -> str:
    """The advisory ID an entry is named after: a GHSA, else a CVE, else the scanner's own ID."""
    for pattern in _PRIMARY:
        matches = sorted(alias for alias in aliases if pattern.fullmatch(alias))
        if matches:
            return matches[0]
    return aliases[0]


def _alert(source: str, ecosystem: str, package: str, version: str, advisory: str, aliases: list,
           severity: str | None, summary: str, fix: str | None, url: str | None = None) -> dict:
    ecosystem = _ecosystem(ecosystem)
    package = _package(ecosystem, package)
    names = [str(advisory)] + [str(alias) for alias in aliases or [] if alias and str(alias) != str(advisory)]
    names = sorted({name.upper() for name in names}, key=lambda name: (name != str(advisory).upper(), name))
    primary = _primary(names)
    alert = {
        "id": f"{ecosystem}:{package}:{primary}".lower(),
        "source": source,
        "ecosystem": ecosystem,
        "package": package,
        "version": version or "unknown",
        "advisory": primary,
        "aliases": sorted(names),
        "severity": (severity or "unknown").lower(),
        "summary": " ".join((summary or "").split())[:300],
    }
    if fix:
        alert["fix"] = fix
    if url:
        alert["url"] = url
    return alert


def _npm(report: dict) -> list[dict]:
    alerts = []
    for name, item in report["vulnerabilities"].items():
        fix = item.get("fixAvailable")
        fix_text = f"{fix['name']} {fix['version']}" if isinstance(fix, dict) else ("available" if fix is True else None)
        for via in item.get("via", []):
            if not isinstance(via, dict):
                continue
            advisory = (via.get("url") or "").rstrip("/").rsplit("/", 1)[-1] or str(via.get("source"))
            alerts.append(_alert("npm audit", "npm", name, item.get("range", ""), advisory, [], via.get("severity"),
                                 via.get("title", ""), fix_text, via.get("url")))
    return alerts


def _pip_audit(report: dict) -> list[dict]:
    alerts = []
    for dependency in report["dependencies"]:
        for vuln in dependency.get("vulns", []):
            fixes = vuln.get("fix_versions") or []
            alerts.append(_alert("pip-audit", "PyPI", dependency["name"], dependency.get("version", ""), vuln["id"],
                                 vuln.get("aliases", []), None, vuln.get("description", ""), ", ".join(fixes) or None))
    return alerts


def _osv(report: dict) -> list[dict]:
    alerts = []
    for result in report["results"]:
        for entry in result.get("packages", []):
            package = entry.get("package", {})
            for vuln in entry.get("vulnerabilities", []):
                severity = (vuln.get("database_specific") or {}).get("severity")
                alerts.append(_alert("OSV-Scanner", package.get("ecosystem", "unknown"), package.get("name", "unknown"),
                                     package.get("version", ""), vuln["id"], vuln.get("aliases", []), severity,
                                     vuln.get("summary", ""), None, f"https://osv.dev/vulnerability/{vuln['id']}"))
    return alerts


def _dependabot(report: list) -> list[dict]:
    alerts = []
    for item in report:
        if item.get("state") not in (None, "open"):
            continue
        package = item["dependency"]["package"]
        advisory = item["security_advisory"]
        vulnerability = item.get("security_vulnerability") or {}
        patched = (vulnerability.get("first_patched_version") or {}).get("identifier")
        aliases = [entry.get("value") for entry in advisory.get("identifiers", []) if isinstance(entry, dict)]
        aliases.append(advisory.get("cve_id"))
        alerts.append(_alert("GitHub Dependabot", package["ecosystem"], package["name"],
                             vulnerability.get("vulnerable_version_range", ""), advisory["ghsa_id"], aliases,
                             advisory.get("severity"), advisory.get("summary", ""), patched, item.get("html_url")))
    return alerts


def _json_documents(text: str) -> list:
    """Every JSON value in the text: `gh api --paginate` prints one array per page, back to back."""
    decoder = json.JSONDecoder()
    values, index = [], 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index == len(text):
            return values
        value, index = decoder.raw_decode(text, index)
        values.append(value)


def _dependabot_pages(values: list) -> list | None:
    """The alerts of one or several Dependabot pages, including `gh api --paginate --slurp` output."""
    pages = values[0] if len(values) == 1 and isinstance(values[0], list) and values[0] and all(
        isinstance(page, list) for page in values[0]) else values
    if not all(isinstance(page, list) for page in pages):
        return None
    items = [item for page in pages for item in page]
    if all(isinstance(item, dict) and "security_advisory" in item for item in items):
        return items
    return None


def _npm_analyzed(report: dict) -> int:
    """npm audit counts the dependencies it audited in metadata.dependencies (total, or one count per kind)."""
    counts = (report.get("metadata") or {}).get("dependencies")
    if isinstance(counts, dict):
        total = counts.get("total")
        return total if type(total) is int else sum(value for value in counts.values() if type(value) is int)
    return counts if type(counts) is int else 0


def _osv_analyzed(report: dict) -> int:
    """OSV-Scanner lists, per scanned source, the packages of its report: only the vulnerable ones by default."""
    return sum(len(result.get("packages", [])) for result in report["results"] if isinstance(result, dict))


def _pip_audit_skipped(report: dict) -> list[tuple[str, str]]:
    """The packages pip-audit did not audit (an entry with a skip_reason, and no vulns): the report says nothing of them."""
    return [("pypi", _package("pypi", dependency["name"])) for dependency in report["dependencies"]
            if "skip_reason" in dependency]


def read_report(content: bytes, label: str) -> dict:
    """Recognize the scanner by the report's shape: its name, its normalized alerts, how many dependencies (or, for
    Dependabot, alerts of any state) the report shows it analyzed, and the packages it skipped. A report that analyzed
    nothing resolves nothing, and neither does it for a package it skipped (import_report)."""
    try:
        values = _json_documents(content.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f"Invalid JSON in {label}: {error}") from error
    if not values:
        raise ValueError(f"{label} is empty: give the scanner's JSON report.")
    data = values[0]
    try:
        dependabot = _dependabot_pages(values)
        if dependabot is not None:
            return {"tool": "GitHub Dependabot", "alerts": _dependabot(dependabot), "analyzed": len(dependabot)}
        if len(values) > 1:
            raise ValueError(f"{label} holds several JSON documents; only Dependabot pages can be concatenated.")
        if isinstance(data, dict) and isinstance(data.get("vulnerabilities"), dict):
            return {"tool": "npm audit", "alerts": _npm(data), "analyzed": _npm_analyzed(data)}
        if isinstance(data, dict) and isinstance(data.get("dependencies"), list):
            skipped = _pip_audit_skipped(data)
            return {"tool": "pip-audit", "alerts": _pip_audit(data), "skipped": skipped,
                    "analyzed": len(data["dependencies"]) - len(skipped)}
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return {"tool": "OSV-Scanner", "alerts": _osv(data), "analyzed": _osv_analyzed(data)}
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"{label} looks like a scanner report but a field is missing: {error}") from error
    raise ValueError(f"{label} is not an npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")


def parse_report(content: bytes, label: str) -> tuple[str, list[dict]]:
    """Recognize the scanner by the report's shape and normalize its alerts."""
    report = read_report(content, label)
    return report["tool"], report["alerts"]


# Why a report that analyzed no dependency leaves the register's alerts as they are, by scanner.
NOTHING_ANALYZED = {
    "npm audit": "metadata.dependencies counts no audited dependency",
    "pip-audit": "its dependencies list holds no audited entry (an entry with a skip_reason was not audited)",
    "OSV-Scanner": "its results list no scanned package (run it so it lists every package it scanned)",
    "GitHub Dependabot": "it lists no alert in any state (fetch the alerts of every state, not only the open ones)",
}


def register_path(state: Path) -> Path:
    return state / REGISTER_FILE


def load_register(state: Path) -> dict:
    """The project's register, empty when no report was imported yet."""
    path = register_path(state)
    if not path.is_file():
        return {"schema_version": 1, "alerts": [], "imports": []}
    register = read_json(path)
    if register.get("schema_version") != 1 or not isinstance(register.get("alerts"), list):
        raise ValueError(f"Unsupported alert register: {path.as_posix()}. Restore it from git.")
    return register


def save_register(state: Path, register: dict) -> None:
    register = {**register, "alerts": sorted(register["alerts"], key=lambda alert: alert["id"])}
    write_json(register_path(state), register)


def _today() -> str:
    return clock.today().isoformat()


def _now() -> str:
    return clock.timestamp()


def _status(alert: dict) -> str:
    return LEGACY_STATUSES.get(alert.get("status", "open"), alert.get("status", "open"))


def _same(entry: dict, alert: dict) -> bool:
    """Same package and an advisory ID in common, whatever scanner named it."""
    return (entry["ecosystem"], entry["package"]) == (alert["ecosystem"], alert["package"]) and bool(
        set(entry.get("aliases", [entry["advisory"].upper()])) & set(alert["aliases"]))


def _worse(first: str, second: str) -> str:
    return first if SEVERITY_RANK.get(first, 0) >= SEVERITY_RANK.get(second, 0) else second


_KEEP_ORDER = ("confirmed", "dismissed", "open", "resolved")


def _merge(entry: dict, other: dict) -> dict:
    """Fold a second entry for the same advisory into the first: aliases, scanners, tasks, severity."""
    merged = {**entry}
    merged["aliases"] = sorted(set(entry.get("aliases", [])) | set(other.get("aliases", [])))
    # A severity a person set stays until a person changes it again; scanners only fill an unknown one.
    if "severity_set" not in entry:
        merged["severity"] = _worse(entry["severity"], other["severity"])
    for key in ("scanners", "seen_by", "tasks"):
        merged[key] = sorted(set(entry.get(key, [])) | set(other.get(key, [])))
    if _KEEP_ORDER.index(_status(other)) < _KEEP_ORDER.index(_status(entry)):
        for key in ("status", "by", "reason", "decided_at", "accepted", "resolved_on", "resolved_from", "resolved_by"):
            merged.pop(key, None)
            if key in other:
                merged[key] = other[key]
    for key in ("fix", "url"):
        if key not in merged and key in other:
            merged[key] = other[key]
    return merged


def _absorb(alerts: list[dict], alert: dict, tool: str, today: str) -> tuple[list[dict], str, bool]:
    """Add one reported alert to the list; say whether it is new, known or reopened, and whether reopening it removed
    the acceptance of a person."""
    matches = [entry for entry in alerts if _same(entry, alert)]
    rest = [entry for entry in alerts if not _same(entry, alert)]
    if not matches:
        fresh = {**{key: value for key, value in alert.items() if key != "source"},
                 "status": "open", "scanners": [tool], "seen_by": [tool], "tasks": [], "first_seen": today,
                 "last_seen": today}
        return [*rest, fresh], "new", False
    entry = matches[0]
    for other in matches[1:]:
        entry = _merge(entry, other)
    entry = _merge(entry, {**alert, "status": "resolved", "scanners": [tool], "seen_by": [tool]})
    for key in ("version", "summary", "fix", "url"):
        if alert.get(key) and (entry.get(key) in (None, "", "unknown") or tool in matches[0].get("scanners", [])):
            entry[key] = alert[key]
    entry["status"] = _status(entry)
    entry["last_seen"] = today
    change, unaccepted = "known", False
    if entry["status"] == "resolved":
        entry["status"] = entry.pop("resolved_from", "open")
        unaccepted = "accepted" in entry
        for key in ("resolved_on", "resolved_by", "accepted", "by", "reason", "decided_at"):
            entry.pop(key, None)
        change = "reopened"
    return [*rest, entry], change, unaccepted


def import_report(register: dict, path: Path, task_id: str | None = None, today: str | None = None) -> tuple[dict, dict]:
    """Merge a scanner report into the register.

    Alerts that this scanner listed before and no longer lists lose it as a source; when no scanner
    lists them anymore, open and confirmed ones become resolved, and keep the report that resolved them (file,
    SHA-256, day, dependencies analyzed). A resolved alert that a report lists again is reopened with its earlier
    status and without the decision of a person (who confirmed it, who accepted it), so a confirmed critical alert
    blocks again. A report that analyzed no dependency resolves nothing and says why, and one that skipped a package
    resolves none of its alerts. With task_id, the report's alerts are linked to that task.
    """
    today = today or _today()
    content = path.read_bytes()
    report = read_report(content, path.name)
    tool, reported = report["tool"], report["alerts"]
    digest = hashlib.sha256(content).hexdigest()
    alerts = [{**alert, "status": _status(alert)} for alert in register["alerts"]]
    changes = {"tool": tool, "new": [], "reopened": [], "resolved": [], "reported": [], "analyzed": report["analyzed"],
               "acceptance_removed": []}
    if not report["analyzed"]:
        changes["nothing_analyzed"] = NOTHING_ANALYZED[tool]
    for alert in reported:
        alerts, change, unaccepted = _absorb(alerts, alert, tool, today)
        current = next(entry for entry in alerts if _same(entry, alert))
        if change in ("new", "reopened"):
            changes[change].append(current["id"])
        if unaccepted:
            changes["acceptance_removed"].append(current["id"])
        changes["reported"].append(current["id"])
        if task_id and task_id not in current["tasks"]:
            current["tasks"] = sorted([*current["tasks"], task_id])
    reported_ids = set(changes["reported"])
    source = {"tool": tool, "file": path.name, "sha256": digest, "date": today, "dependencies": report["analyzed"]}
    skipped = report.get("skipped", [])
    for alert in alerts:
        # A report that analyzed nothing, or skipped the alert's package, cannot show that an alert is gone.
        if alert["id"] in reported_ids or tool not in alert.get("scanners", []) or not report["analyzed"] or (
                (alert["ecosystem"], alert["package"]) in skipped):
            continue
        alert["scanners"] = [name for name in alert["scanners"] if name != tool]
        if not alert["scanners"] and alert["status"] in ACTIVE:
            alert.update(resolved_from=alert["status"], status="resolved", resolved_on=today, resolved_by=source)
            changes["resolved"].append(alert["id"])
    changes = {key: sorted(set(value)) if isinstance(value, list) else value for key, value in changes.items()}
    entry = {"tool": tool, "file": path.name, "sha256": digest, "date": today, "dependencies": report["analyzed"],
             "alerts": len(changes["reported"]), "new": len(changes["new"]), "resolved": len(changes["resolved"])}
    imports = [*register.get("imports", []), entry][-IMPORTS_KEPT:]
    return {**register, "alerts": alerts, "imports": imports}, changes


def find_alert(register: dict, alert_id: str) -> dict:
    """An alert by its ID, or by ecosystem:package:ALIAS for any advisory ID it is known by."""
    wanted = alert_id.strip().lower()
    for alert in register["alerts"]:
        names = {alert["id"]} | {f"{alert['ecosystem']}:{alert['package']}:{alias}".lower()
                                 for alias in alert.get("aliases", [])}
        if wanted in names:
            return alert
    raise ValueError(f"Unknown alert {alert_id}. Run openguildkit alerts list to see the register.")


def _replace(register: dict, alert: dict) -> dict:
    return {**register, "alerts": [alert if item["id"] == alert["id"] else item for item in register["alerts"]]}


def needs_person(alert: dict, status: str) -> bool:
    """Dismissing a critical alert, or taking a confirmed critical one back, is a person's decision."""
    critical = alert["severity"] == "critical"
    return critical and (status == "dismissed" or (_status(alert) == "confirmed" and status != "confirmed"))


def set_status(register: dict, alert_id: str, status: str, by: str, reason: str = "") -> dict:
    """Record a reviewer's status on an alert: open, confirmed, or dismissed with a reason."""
    status = LEGACY_STATUSES.get(status, status)
    if status not in REVIEW_STATUSES:
        raise ValueError(f"Choose the status from {', '.join(REVIEW_STATUSES)}; an import marks alerts resolved.")
    alert = find_alert(register, alert_id)
    if status == "dismissed" and not reason.strip():
        raise ValueError("Give the reason for dismissing the alert with --reason.")
    if not by.strip():
        raise ValueError("Name the person who reviewed the alert with --by.")
    if _status(alert) == "resolved":
        raise ValueError(f"{alert['id']} is resolved: no scanner lists it anymore.")
    updated = {key: value for key, value in alert.items() if key not in ("reason", "accepted")}
    updated.update(status=status, by=by.strip(), decided_at=_now())
    if reason.strip():
        updated["reason"] = reason.strip()
    return _replace(register, updated)


def set_severity(register: dict, alert_id: str, severity: str, by: str, reason: str) -> dict:
    """Record the severity a person gives an alert, such as one pip-audit reports without any, with who and why."""
    if severity not in SEVERITIES:
        raise ValueError(f"Choose the severity from {', '.join(SEVERITIES)}.")
    if not by.strip() or not reason.strip():
        raise ValueError("Name the person with --by and say why with --reason, such as the advisory's CVSS score.")
    alert = find_alert(register, alert_id)
    record = {"from": alert["severity"], "by": by.strip(), "reason": reason.strip(), "at": _now()}
    return _replace(register, {**alert, "severity": severity, "severity_set": record})


def accept_alert(register: dict, alert_id: str, by: str, reason: str) -> dict:
    """Record why a person accepts a confirmed alert, so it stops blocking its tasks."""
    alert = find_alert(register, alert_id)
    if _status(alert) != "confirmed":
        raise ValueError(f"{alert['id']} is {_status(alert)}: only a confirmed alert is accepted.")
    if not by.strip() or not reason.strip():
        raise ValueError("Name the person with --by and say why the risk is accepted with --reason.")
    return _replace(register, {**alert, "accepted": {"by": by.strip(), "reason": reason.strip(), "at": _now()}})


def link_alert(register: dict, alert_id: str, task_id: str) -> dict:
    alert = find_alert(register, alert_id)
    return _replace(register, {**alert, "tasks": sorted(set(alert.get("tasks", [])) | {task_id})})


def _legacy(task: dict) -> list[dict]:
    """Alerts an earlier version stored inside the task itself."""
    return [{**alert, "status": _status(alert), "tasks": [task["id"]]}
            for alert in task.get("dependency_alerts", {}).get("alerts", [])]


def migrate_task(register: dict, task: dict) -> tuple[dict, dict]:
    """Move the alerts an earlier version kept inside a task into the register, linked to the task."""
    alerts = list(register["alerts"])
    for old in _legacy(task):
        known = next((entry for entry in alerts if entry["id"] == old["id"]), None)
        if known is None:
            old = {key: value for key, value in old.items() if key != "source"}
            alerts.append({"aliases": [old["advisory"].upper()], "scanners": [], "seen_by": [], **old})
        else:
            alerts = [_merge(entry, old) if entry is known else entry for entry in alerts]
    task = {key: value for key, value in task.items() if key != "dependency_alerts"}
    return {**register, "alerts": alerts}, task


def task_alerts(register: dict, task: dict, statuses: tuple = ACTIVE) -> list[dict]:
    """The alerts linked to a task, with the given statuses (open and confirmed by default)."""
    known = {alert["id"] for alert in register["alerts"]}
    linked = [alert for alert in register["alerts"] if task["id"] in alert.get("tasks", [])]
    linked += [alert for alert in _legacy(task) if alert["id"] not in known]
    return sorted((alert for alert in linked if _status(alert) in statuses), key=lambda alert: alert["id"])


def blocking_alerts(register: dict, task: dict) -> list[str]:
    """Why the task's confirmed critical alerts stop its approval and completion."""
    return [
        f"Dependency alert {alert['id']} ({alert['package']} {alert['version']}) is confirmed and critical: "
        f"resolve it, or have a person run openguildkit alerts accept {alert['id']} --by NAME --reason WHY."
        for alert in task_alerts(register, task, ("confirmed",))
        if alert["severity"] == "critical" and not alert.get("accepted")
    ]


def alert_task_id(alert: dict) -> str:
    """The ID of the task that handles an alert: the same in every copy of the project and in every scheduled run."""
    words = re.sub(r"[^a-z0-9]+", "-", f"dep-{alert['package']}-{alert['advisory']}".lower()).strip("-")
    return words[:64].rstrip("-")


def unhandled_alerts(register: dict) -> list[dict]:
    """The confirmed alerts that no task handles yet and no person accepted: each needs a task of its own."""
    return [alert for alert in register["alerts"]
            if _status(alert) == "confirmed" and not alert.get("tasks") and not alert.get("accepted")]


def task_brief(alert: dict) -> str:
    """The brief of the task opened for an alert, with what the register knows of it."""
    return (f"Fix dependency alert {alert['id']}: {alert['package']} {alert['version']} is affected by "
            f"{alert['advisory']} ({alert['severity']}). Fixed version: {alert.get('fix') or 'unknown'}.")


def resolved_by_import(register: dict, task: dict, since: str | None = None) -> list[dict]:
    """The task's alerts that were confirmed and critical and that an import resolved, not a person, on or after the
    day of since: the person reads each with its report before deciding."""
    return [alert for alert in task_alerts(register, task, ("resolved",))
            if alert.get("resolved_from") == "confirmed" and alert["severity"] == "critical" and alert.get("resolved_by")
            and (since is None or alert["resolved_by"]["date"] >= since[:10])]


def resolution_line(alert: dict) -> str:
    """One resolved alert and the report that resolved it, as the decision brief shows it."""
    report = alert["resolved_by"]
    return (f"Dependency alert {alert['id']} ({alert['package']} {alert['version']}) was confirmed and critical, and an "
            f"import resolved it on {report['date']}, not a person: {report['tool']} report {report['file']} (sha256 "
            f"{report['sha256'][:12]}), {report['dependencies']} dependencies analyzed. Check that report before "
            "deciding.")


def summary(alerts: list[dict], imports: list[dict]) -> dict:
    counts = {status: sum(_status(alert) == status for alert in alerts) for status in STATUSES}
    severities = {}
    for alert in alerts:
        severities[alert["severity"]] = severities.get(alert["severity"], 0) + 1
    return {"total": len(alerts), "by_status": counts, "by_severity": severities, "imports": imports}
