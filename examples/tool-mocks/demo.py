"""Rehearse an agent's use of the company tools with mocks: no account, no key, no network.

    python examples/tool-mocks/demo.py [--project DIR]

It initialises a fictional project that names its tools, connects their mocks for Codex and
Claude Code, then plays what an agent does over MCP: find the ticket of a request, read the
security alert on its pull request, check who is away, and log the time spent. Every answer
comes from the synthetic data bundled with OpenGuildKit.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENV = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO / "src"), os.environ.get("PYTHONPATH")])),
       "PYTHONIOENCODING": "utf-8"}
PROFILE = {
    "name": "Acme Support Portal", "sector": "general", "personal_data": "no", "stack": ["Python"], "packs": [], "host": "codex",
    "boards": ["product", "qa", "security", "hr"], "research": "local-only",
    "tools": ["Jira", "GitHub", "Snyk", "Factorial", "Tempo", "Gryzzly"],
}
STEPS = [
    ("jira", "search_issues", {"query": "export"}, "Find the ticket of the request"),
    ("github", "list_security_alerts", {}, "Read the dependency alerts of the repository"),
    ("snyk", "list_issues", {"project": "support-portal"}, "Read the scanner's findings"),
    ("factorial", "list_time_off", {}, "Check who is away during the sprint"),
    ("tempo", "log_work", {"issue_key": "SUP-142", "hours": 1.5, "date": "2026-11-21", "description": "Review of the CSV export"},
     "Log the time spent, once the person agreed"),
]


def cli(project: Path, *args: str, expected: int = 0) -> str:
    result = subprocess.run([sys.executable, "-m", "openguildkit", "--project", str(project), *args],
                            env=ENV, text=True, encoding="utf-8", capture_output=True)
    if result.returncode != expected:
        raise SystemExit(f"openguildkit {' '.join(args)} returned {result.returncode}:\n{result.stderr}{result.stdout}")
    return result.stdout


def call(project: Path, tool: str, name: str, arguments: dict) -> dict:
    """One MCP exchange with a mock server, as a host would have it: handshake, then the call."""
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "demo", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
    ]
    result = subprocess.run(
        [sys.executable, "-m", "openguildkit", "--project", str(project), "tools", "mock", tool,
         "--log", str(project / "mock-calls.jsonl")],
        env=ENV, input="".join(json.dumps(item) + "\n" for item in messages).encode("utf-8"), capture_output=True)
    return json.loads(result.stdout.decode("utf-8").splitlines()[-1])["result"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, help="Empty folder for the demo.")
    args = parser.parse_args()
    project = (args.project or Path(tempfile.mkdtemp(prefix="ogk-tool-mocks-"))).resolve()
    project.mkdir(parents=True, exist_ok=True)
    (project / "profile.json").write_text(json.dumps(PROFILE), encoding="utf-8")
    cli(project, "init", "--answers", str(project / "profile.json"))
    print("# What the project names, resolved against the registry\n")
    print(cli(project, "tools", "recommend"))
    tools = ["jira", "github", "snyk", "factorial", "tempo", "gryzzly"]
    print("# Mocks connected for Codex and for Claude Code\n")
    for host in ("codex", "claude-code"):
        report = json.loads(cli(project, "tools", "apply", *tools, "--mock", "--host", host, "--json", expected=2))
        skipped = [item["tool"] for item in report["skipped"]]
        if skipped != ["gryzzly"] or set(report["applied"]) != set(tools) - set(skipped):
            raise SystemExit(f"Unexpected mock connections for {host}.")
        print(f"{host}: connected {', '.join(report['applied'])}. No mock for {', '.join(skipped)}.")
    print("# What an agent reads and does\n")
    for tool, name, arguments, why in STEPS:
        answer = call(project, tool, name, arguments)
        print(f"{why}: {tool}.{name}({json.dumps(arguments)})")
        print(f"    {'ERROR ' if answer['isError'] else ''}{answer['content'][0]['text'][:400]}\n")
    calls = (project / "mock-calls.jsonl").read_text(encoding="utf-8").splitlines()
    print(f"# {len(calls)} calls recorded in {project / 'mock-calls.jsonl'}")


if __name__ == "__main__":
    main()
