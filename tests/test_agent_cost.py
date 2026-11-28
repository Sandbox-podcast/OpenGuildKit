"""scripts/agent_cost.py: the local transcript total of an agent session, by model and by day."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.support import load_script

agent_cost = load_script(Path(__file__).resolve().parents[1] / "scripts" / "agent_cost.py")


def _assistant(message_id, model, usage, *, when="2026-11-24T10:00:00.000Z", pieces=None):
    """One transcript line the way Claude Code writes it: one line per content block of a message."""
    return {"type": "assistant", "timestamp": when, "message": {
        "id": message_id, "role": "assistant", "model": model,
        "content": pieces or [{"type": "text", "text": "x"}],
        "usage": {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0, **usage},
    }}


def _write_lines(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


class AgentCostTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_totals_leave_the_transcript_text_out(self):
        secret = "secret-transcript-phrase"
        lines = [
            {"type": "assistant", "message": {
                "id": "msg_1", "role": "assistant", "model": "claude-sonnet-x",
                "content": [{"type": "text", "text": secret}],
                "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 10,
                          "cache_creation_input_tokens": 5},
            }},
            _assistant("msg_2", "claude-sonnet-x", {"input_tokens": 20, "output_tokens": 8},
                       pieces=[{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]),
            {"type": "user", "timestamp": "2026-11-24T10:00:02.500Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": secret},
            ]}},
        ]
        path = self.root / "transcript.jsonl"
        _write_lines(path, lines)
        report = agent_cost.summarise(path, rates={"claude-sonnet": (3.0, 15.0, 0.30, 3.75)})
        self.assertEqual(report["input_tokens"], 120)
        self.assertEqual(report["output_tokens"], 48)
        self.assertEqual(report["cache_read_input_tokens"], 10)
        self.assertEqual(report["cache_creation_input_tokens"], 5)
        self.assertEqual(report["turns"], 2)
        self.assertEqual(report["subagents"], 0)
        self.assertEqual(report["command_wait_seconds"], 2.5)
        expected = (120 * 3.0 + 48 * 15.0 + 10 * 0.30 + 5 * 3.75) / 1_000_000
        self.assertEqual(report["cost_usd"], expected)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(agent_cost.main([str(path)]), 0)
        text = buffer.getvalue()
        self.assertNotIn(secret, text)
        self.assertIn("input_tokens: 120", text)
        self.assertIn("cost_usd:", text)

    def test_issue_485_a_message_written_on_three_lines_counts_once(self):
        """Issue #485: a message that fills three lines of the transcript is counted three times."""
        usage = {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 10,
                 "cache_creation_input_tokens": 5}
        once = self.root / "once.jsonl"
        three = self.root / "three.jsonl"
        _write_lines(once, [_assistant("msg_1", "claude-sonnet-x", usage)])
        pieces = [[{"type": "thinking", "thinking": "a"}], [{"type": "text", "text": "b"}],
                  [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]]
        _write_lines(three, [_assistant("msg_1", "claude-sonnet-x", usage, pieces=piece) for piece in pieces])
        names = (*agent_cost._USAGE, "turns", "cost_usd")
        self.assertEqual({name: agent_cost.summarise(three)[name] for name in names},
                         {name: agent_cost.summarise(once)[name] for name in names})
        self.assertEqual(agent_cost.summarise(three)["turns"], 1)
        # The last line of a message holds its final usage.
        _write_lines(three, [_assistant("msg_1", "claude-sonnet-x", {**usage, "output_tokens": 3}),
                             _assistant("msg_1", "claude-sonnet-x", usage)])
        self.assertEqual(agent_cost.summarise(three)["output_tokens"], 40)

    def test_issue_485_a_session_folder_adds_the_subagent_files(self):
        """Issue #485: the files of subagents/*.jsonl are not read, so `subagents` stays 0."""
        usage = {"input_tokens": 10, "output_tokens": 4}
        for layout in ("sibling", "inside"):
            with self.subTest(layout=layout):
                session = self.root / layout / "session-1"
                main = session.parent / "session-1.jsonl" if layout == "sibling" else session / "main.jsonl"
                _write_lines(main, [_assistant("msg_1", "claude-sonnet-x", usage)])
                _write_lines(session / "subagents" / "agent-a.jsonl", [_assistant("msg_2", "claude-sonnet-x", usage)])
                _write_lines(session / "subagents" / "agent-b.jsonl", [
                    _assistant("msg_3", "claude-sonnet-x", usage), _assistant("msg_4", "claude-sonnet-x", usage)])
                (session / "subagents" / "agent-a.meta.json").write_text("{}", encoding="utf-8")
                report = agent_cost.summarise(session)
                self.assertEqual(report["input_tokens"], 40)
                self.assertEqual(report["turns"], 1)
                self.assertEqual(report["subagents"], 2)
                self.assertEqual(len(report["files"]), 3)
                self.assertEqual(report["files"]["subagents/agent-b.jsonl"]["turns"], 2)
        with self.assertRaises(ValueError):
            agent_cost.summarise(self.root / "absent")

    def test_issue_485_each_model_has_its_rate_and_a_model_without_rate_is_named(self):
        """Issue #485: one rate applies whatever model a line names."""
        rates = {"model-a": (1.0, 2.0, 0.0, 0.0), "model-b": (10.0, 20.0, 0.0, 0.0)}
        path = self.root / "transcript.jsonl"
        _write_lines(path, [
            _assistant("msg_1", "model-a-1", {"input_tokens": 1_000_000}),
            _assistant("msg_2", "model-b-2", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}),
            _assistant("msg_3", "model-c", {"input_tokens": 500}),
            _assistant("msg_4", "<synthetic>", {}),
        ])
        report = agent_cost.summarise(path, rates=rates)
        self.assertEqual(report["cost_usd"], 1.0 + 10.0 + 20.0)
        self.assertEqual(report["unpriced_models"], ["model-c"])
        self.assertEqual(report["models"]["model-a-1"]["cost_usd"], 1.0)
        self.assertIsNone(report["models"]["model-c"]["cost_usd"])
        self.assertEqual(report["input_tokens"], 2_000_500)

    def test_issue_485_the_wait_is_the_gap_between_a_tool_call_and_its_result(self):
        """Issue #485: command_wait_seconds reads a duration_ms that no transcript holds and stays 0."""
        path = self.root / "transcript.jsonl"
        call = [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}}]
        _write_lines(path, [
            _assistant("msg_1", "model-a", {}, when="2026-11-24T10:00:00.000Z", pieces=call),
            {"type": "user", "timestamp": "2026-11-24T10:00:03.250Z", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
                {"type": "tool_result", "tool_use_id": "toolu_unknown", "content": "ok"}]}},
        ])
        self.assertEqual(agent_cost.summarise(path)["command_wait_seconds"], 3.25)

    def test_issue_485_an_unreadable_line_is_skipped_and_counted(self):
        """Issue #485: one line that is not an object refuses the whole transcript."""
        secret = "secret-transcript-phrase"
        path = self.root / "transcript.jsonl"
        _write_lines(path, [_assistant("msg_1", "model-a", {"input_tokens": 7})])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(secret + "\n[1, 2]\n")
        report = agent_cost.summarise(path)
        self.assertEqual(report["skipped_lines"], 2)
        self.assertEqual(report["input_tokens"], 7)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self.assertEqual(agent_cost.main([str(path), "--json"]), 0)
        printed = json.loads(buffer.getvalue())
        self.assertEqual(printed["skipped_lines"], 2)
        self.assertNotIn(secret, buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
