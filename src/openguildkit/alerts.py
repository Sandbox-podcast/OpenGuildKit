"""Bring dependency alerts from the project's own scanners into a task.

The CLI does not scan anything: it reads the JSON report a scanner the project approves
already produced (npm audit, pip-audit, OSV-Scanner or GitHub Dependabot alerts), keeps one
normalized entry per alert, and lets the reviewers mark each one confirmed, to verify or
dismissed with a reason.
"""

import hashlib
from pathlib import Path


STATUSES = ("to-verify", "confirmed", "dismissed")


def _alert(source: str, ecosystem: str, package: str, version: str, advisory: str, severity: str | None,
           summary: str, fix: str | None, url: str | None = None) -> dict:
    alert = {
        "id": f"{ecosystem}:{package}:{advisory}".lower(),
        "source": source,
        "ecosystem": ecosystem,
        "package": package,
        "version": version or "unknown",
        "advisory": advisory,
        "severity": (severity or "unknown").lower(),
        "summary": " ".join((summary or "").split())[:300],
        "status": "to-verify",
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
            alerts.append(_alert("npm audit", "npm", name, item.get("range", ""), advisory, via.get("severity"),
                                 via.get("title", ""), fix_text, via.get("url")))
    return alerts


def _pip_audit(report: dict) -> list[dict]:
    alerts = []
    for dependency in report["dependencies"]:
        for vuln in dependency.get("vulns", []):
            fixes = vuln.get("fix_versions") or []
            alerts.append(_alert("pip-audit", "PyPI", dependency["name"], dependency.get("version", ""), vuln["id"],
                                 None, vuln.get("description", ""), ", ".join(fixes) or None))
    return alerts


def _osv(report: dict) -> list[dict]:
    alerts = []
    for result in report["results"]:
        for entry in result.get("packages", []):
            package = entry.get("package", {})
            for vuln in entry.get("vulnerabilities", []):
                severity = (vuln.get("database_specific") or {}).get("severity")
                alerts.append(_alert("OSV-Scanner", package.get("ecosystem", "unknown"), package.get("name", "unknown"),
                                     package.get("version", ""), vuln["id"], severity, vuln.get("summary", ""), None,
                                     f"https://osv.dev/vulnerability/{vuln['id']}"))
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
        alerts.append(_alert("GitHub Dependabot", package["ecosystem"], package["name"],
                             vulnerability.get("vulnerable_version_range", ""), advisory["ghsa_id"],
                             advisory.get("severity"), advisory.get("summary", ""), patched, item.get("html_url")))
    return alerts


def parse_report(content: bytes, label: str) -> tuple[str, list[dict]]:
    """Recognize the scanner by the report's shape and normalize its alerts."""
    import json

    try:
        data = json.loads(content.decode("utf-8-sig"))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ValueError(f"Invalid JSON in {label}: {error}") from error
    try:
        if isinstance(data, list) and all(isinstance(item, dict) and "security_advisory" in item for item in data):
            return "GitHub Dependabot", _dependabot(data)
        if isinstance(data, dict) and isinstance(data.get("vulnerabilities"), dict):
            return "npm audit", _npm(data)
        if isinstance(data, dict) and isinstance(data.get("dependencies"), list):
            return "pip-audit", _pip_audit(data)
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            return "OSV-Scanner", _osv(data)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"{label} looks like a scanner report but a field is missing: {error}") from error
    raise ValueError(f"{label} is not an npm audit, pip-audit, OSV-Scanner or Dependabot JSON report.")


def import_alerts(task: dict, path: Path) -> dict:
    """Add a report's alerts to the task, keeping the review status of alerts already known."""
    content = path.read_bytes()
    tool, alerts = parse_report(content, str(path))
    current = {alert["id"]: alert for alert in task.get("dependency_alerts", {}).get("alerts", [])}
    for alert in alerts:
        if alert["id"] in current:
            alert.update({key: current[alert["id"]][key] for key in ("status", "reason", "by") if key in current[alert["id"]]})
        current[alert["id"]] = alert
    imports = [*task.get("dependency_alerts", {}).get("imports", []), {
        "tool": tool, "file": path.name, "sha256": hashlib.sha256(content).hexdigest(), "alerts": len(alerts),
    }]
    return {**task, "dependency_alerts": {"alerts": sorted(current.values(), key=lambda a: a["id"]), "imports": imports}}


def set_alert_status(task: dict, alert_id: str, status: str, by: str, reason: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"Choose the status from {', '.join(STATUSES)}.")
    alerts = task.get("dependency_alerts", {}).get("alerts", [])
    if not any(alert["id"] == alert_id for alert in alerts):
        raise ValueError(f"Unknown alert {alert_id}. Run task alerts ID to list them.")
    if status == "dismissed" and not reason.strip():
        raise ValueError("Give the reason for dismissing the alert.")
    if not by.strip():
        raise ValueError("Name the person who reviewed the alert.")
    updated = []
    for alert in alerts:
        if alert["id"] == alert_id:
            alert = {**alert, "status": status, "by": by.strip()}
            if reason.strip():
                alert["reason"] = reason.strip()
        updated.append(alert)
    return {**task, "dependency_alerts": {**task["dependency_alerts"], "alerts": updated}}


def alert_summary(task: dict) -> dict:
    data = task.get("dependency_alerts", {})
    alerts = data.get("alerts", [])
    counts = {status: sum(alert["status"] == status for alert in alerts) for status in STATUSES}
    severities = {}
    for alert in alerts:
        severities[alert["severity"]] = severities.get(alert["severity"], 0) + 1
    return {"total": len(alerts), "by_status": counts, "by_severity": severities, "imports": data.get("imports", [])}
