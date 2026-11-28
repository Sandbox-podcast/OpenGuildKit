"""Summarise a local Claude Code session without printing its text.

    python scripts/agent_cost.py TRANSCRIPT.jsonl | SESSION_FOLDER [--json]

Reads JSONL transcripts offline. A file is read alone. A session folder adds the
files of `subagents/*.jsonl` to its main transcript (`*.jsonl` inside the folder,
or `FOLDER.jsonl` beside it, the layout Claude Code writes). Prints totals only:
input tokens, cache read, cache creation, output tokens, turns, subagents (the
number of subagent files), command wait, lines skipped, a cost from the rates
named below and one line per file. It does not call a network, it does not
measure a live session, and it prints no prompt and no tool result.

A message is counted once however many lines it fills (the last line holds its
final usage). Each model is priced at its own rate; a model with no rate is named
and counted apart, without a price. The wait is the time between a tool call and
its result, parallel calls included.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

# USD per million tokens: input, output, cache read, cache creation. The rate of a model is the one of the
# first prefix its name starts with. These are the prices this script applies, not a measurement and not a bill;
# the one below is the rate the script applied to every model before, and was not read from a price page
# (to verify). Add a line per model to price it.
RATES = {
    "claude-sonnet": (3.0, 15.0, 0.30, 3.75),
}

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


def _time(item: dict) -> datetime | None:
    try:
        when = datetime.fromisoformat(item["timestamp"])
    except (KeyError, TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _number(value) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _read(path: Path) -> dict:
    """One transcript: tokens by model (once per message), turns, wait and unreadable lines."""
    messages = {}  # message id -> (model, usage); the last line of a message wins
    calls = {}  # tool call id -> time of the line that made it
    report = {"models": {}, "turns": 0, "command_wait_seconds": 0.0, "skipped_lines": 0}
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = None
        if not isinstance(item, dict):
            report["skipped_lines"] += 1
            continue
        message = item.get("message") if isinstance(item.get("message"), dict) else {}
        usage = _usage(item)
        if item.get("type") == "assistant" or message.get("role") == "assistant" or usage:
            model = message.get("model")
            messages[message.get("id") or f"line {number}"] = (model if isinstance(model, str) else "unknown", usage)
        when = _time(item)
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for piece in content:
            if not isinstance(piece, dict):
                continue
            if piece.get("type") == "tool_use" and isinstance(piece.get("id"), str):
                calls.setdefault(piece["id"], when)
            elif piece.get("type") == "tool_result" and calls.get(piece.get("tool_use_id")) and when:
                report["command_wait_seconds"] += max(0.0, (when - calls.pop(piece["tool_use_id"])).total_seconds())
    report["turns"] = len(messages)
    for model, usage in messages.values():
        totals = report["models"].setdefault(model, dict.fromkeys(_USAGE, 0))
        for name in _USAGE:
            totals[name] += _number(usage.get(name))
    return report


def _cost(tokens: dict, model: str, rates: dict) -> float | None:
    """The cost of a model's tokens, or None when no rate names the model."""
    for prefix, (price_in, price_out, price_read, price_creation) in rates.items():
        if model.startswith(prefix):
            return (
                tokens["input_tokens"] * price_in
                + tokens["output_tokens"] * price_out
                + tokens["cache_read_input_tokens"] * price_read
                + tokens["cache_creation_input_tokens"] * price_creation
            ) / 1_000_000
    return None


def _transcripts(path: Path) -> tuple[list[Path], list[Path]]:
    """The main transcripts and the subagent transcripts of a file or of a session folder."""
    if path.is_file():
        return [path], []
    if not path.is_dir():
        raise ValueError(f"{path} is neither a transcript nor a session folder")
    main = sorted(path.glob("*.jsonl"))
    beside = path.with_name(path.name + ".jsonl")
    if beside.is_file():
        main.append(beside)
    subagents = sorted((path / "subagents").glob("*.jsonl"))
    if not main and not subagents:
        raise ValueError(f"{path} holds no transcript")
    return main, subagents


def summarise(path: Path, rates: dict = RATES) -> dict:
    """Totals for a transcript or a session folder. The result holds numbers and model names only."""
    main, subagents = _transcripts(path)
    report = dict.fromkeys(_USAGE, 0)
    report.update(turns=0, subagents=len(subagents), command_wait_seconds=0.0, skipped_lines=0, cost_usd=0.0,
                  models={}, unpriced_models=[], files={})
    for file in (*main, *subagents):
        one = _read(file)
        name = file.name if file in main else f"subagents/{file.name}"
        total = {"turns": one["turns"], "command_wait_seconds": one["command_wait_seconds"], "cost_usd": 0.0,
                 **dict.fromkeys(_USAGE, 0)}
        for model, tokens in one["models"].items():
            cost = _cost(tokens, model, rates)
            kept = report["models"].setdefault(model, {**dict.fromkeys(_USAGE, 0), "cost_usd": None})
            for key in _USAGE:
                kept[key] += tokens[key]
                total[key] += tokens[key]
                report[key] += tokens[key]
            if cost is not None:
                kept["cost_usd"] = (kept["cost_usd"] or 0.0) + cost
                total["cost_usd"] += cost
                report["cost_usd"] += cost
        report["files"][name] = total
        report["command_wait_seconds"] += one["command_wait_seconds"]
        report["skipped_lines"] += one["skipped_lines"]
        if file in main:
            report["turns"] += one["turns"]
    report["unpriced_models"] = sorted(
        model for model, kept in report["models"].items()
        if kept["cost_usd"] is None and any(kept[key] for key in _USAGE)
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print token and cost totals for a local transcript or session.")
    parser.add_argument("path", type=Path, help="a transcript, or a session folder with its subagents/ folder")
    parser.add_argument("--json", action="store_true", help="print the whole report as JSON")
    args = parser.parse_args(argv)
    try:
        report = summarise(args.path)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    for name in (*_USAGE, "turns", "subagents"):
        print(f"{name}: {report[name]}")
    print(f"command_wait_seconds: {report['command_wait_seconds']:.3f}")
    print(f"skipped_lines: {report['skipped_lines']}")
    print(f"cost_usd: {report['cost_usd']:.8f}")
    for model in report["unpriced_models"]:
        print(f"unpriced_model: {model}")
    if len(report["files"]) > 1:
        for name, total in report["files"].items():
            print(f"file {name}: turns {total['turns']}, output_tokens {total['output_tokens']}, "
                  f"cost_usd {total['cost_usd']:.8f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
