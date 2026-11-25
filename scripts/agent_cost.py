"""Summarise a local Claude Code transcript without printing its text.

    python scripts/agent_cost.py TRANSCRIPT.jsonl

Reads one JSONL file offline. Prints totals only: input tokens, cache read,
cache creation, output tokens, turns, subagents, command wait, and a cost from
the rates named below. It does not call a network, it does not measure a live
session, and it prints no prompt and no tool result.

The rates are the prices this script applies. They are not a measurement.
"""

import argparse
import json
import sys
from pathlib import Path

# USD per million tokens. Named here so a total can be read against a price, not taken for a measured bill.
INPUT_USD_PER_MILLION = 3.0
OUTPUT_USD_PER_MILLION = 15.0
CACHE_READ_USD_PER_MILLION = 0.30
CACHE_CREATION_USD_PER_MILLION = 3.75

_USAGE = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)


def _usage(item: dict) -> dict:
    message = item.get("message")
    if isinstance(message, dict) and isinstance(message.get("usage"), dict):
        return message["usage"]
    usage = item.get("usage")
    return usage if isinstance(usage, dict) else {}


def _contents(item: dict) -> list:
    message = item.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    return content if isinstance(content, list) else []


def summarise(path: Path) -> dict:
    """Totals for one JSONL transcript. The result holds numbers only."""
    report = {name: 0 for name in _USAGE}
    report.update(turns=0, subagents=0, command_wait_seconds=0.0)
    text = path.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"transcript line {number} is not a JSON object") from None
        if not isinstance(item, dict):
            raise ValueError(f"transcript line {number} is not a JSON object")
        for name in _USAGE:
            value = _usage(item).get(name, 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                report[name] += int(value)
        sidechain = item.get("isSidechain") is True or item.get("type") == "subagent"
        assistant = item.get("type") == "assistant" or (
            isinstance(item.get("message"), dict) and item["message"].get("role") == "assistant"
        )
        if sidechain and assistant:
            report["subagents"] += 1
        elif assistant:
            report["turns"] += 1
        for piece in _contents(item):
            if isinstance(piece, dict) and piece.get("type") == "tool_result":
                duration = piece.get("duration_ms")
                if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                    report["command_wait_seconds"] += duration / 1000
    report["cost_usd"] = (
        report["input_tokens"] * INPUT_USD_PER_MILLION
        + report["output_tokens"] * OUTPUT_USD_PER_MILLION
        + report["cache_read_input_tokens"] * CACHE_READ_USD_PER_MILLION
        + report["cache_creation_input_tokens"] * CACHE_CREATION_USD_PER_MILLION
    ) / 1_000_000
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print token and cost totals for one local transcript.")
    parser.add_argument("transcript", type=Path)
    args = parser.parse_args(argv)
    try:
        report = summarise(args.transcript)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    for name in (*_USAGE, "turns", "subagents"):
        print(f"{name}: {report[name]}")
    print(f"command_wait_seconds: {report['command_wait_seconds']:.3f}")
    print(f"cost_usd: {report['cost_usd']:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
