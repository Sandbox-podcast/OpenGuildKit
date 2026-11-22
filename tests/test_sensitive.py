"""Credentials and personal data in what people and agents give the CLI (issue #155).

Every fake credential is assembled at run time from obvious filler, so no committed string looks like a real one.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.cli import main
from openguildkit.sensitive import (
    CREDENTIAL_SHAPES, credential_kind, personal_data_kinds, redact_credentials, redact_data,
)
from openguildkit.storage import write_json
from openguildkit.tools import load_tools, plan_connections

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "request-status"
TASK = "request-status"


def fake(prefix: str, filler: str, count: int) -> str:
    return prefix + filler * count


# One fake value per row of CREDENTIAL_SHAPES, in the table's order.
SAMPLES = {
    "a cloud access key ID": fake("AK" + "IA", "Q", 16),
    "a Stripe secret key": fake("sk" + "_live_", "z", 24),
    "a GitHub token": fake("gh" + "p_", "y", 36),
    "a Slack token": fake("xo" + "xb-", "7", 16),
    "a JSON Web Token": ".".join(["ey" + "J" + "x" * 12, "ey" + "J" + "y" * 12, "z" * 16]),
    "a private key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----\n" + "A" * 40 + "\n-----END " + "RSA PRIVATE" + " KEY-----",
    "a link with a password": "https://deploy:" + "w" * 10 + "@git.example.test/repo",
    "a secret in a query string": "https://api.example.test/v1?access_" + "token=" + "q" * 20,
    "a password": "pass" + "word=" + "v" * 10,
}
SECRET_PARTS = {
    "a cloud access key ID": "Q" * 16, "a Stripe secret key": "z" * 24, "a GitHub token": "y" * 36,
    "a Slack token": "7" * 16, "a JSON Web Token": "z" * 16, "a private key": "A" * 40,
    "a link with a password": "w" * 10, "a secret in a query string": "q" * 20, "a password": "v" * 10,
}


class ShapeTests(unittest.TestCase):
    def test_the_samples_cover_every_shape_of_the_table(self):
        self.assertEqual(list(SAMPLES), [name for name, _, _ in CREDENTIAL_SHAPES])

    def test_each_shape_is_recognized_and_replaced_by_a_placeholder(self):
        for name, value in SAMPLES.items():
            with self.subTest(shape=name):
                text = f"Deploy with {value} tonight."
                self.assertEqual(credential_kind(text), name)
                redacted = redact_credentials(text)
                self.assertNotIn(SECRET_PARTS[name], redacted)
                self.assertTrue(redacted.startswith("Deploy with ") and redacted.endswith(" tonight."), redacted)
                self.assertIsNone(credential_kind(redacted), redacted)

    def test_ordinary_words_and_variable_references_are_not_credentials(self):
        for text in ("Rotate the GitHub token every month.", "Read JIRA_TOKEN from the environment.",
                     "https://api.example.test/v1?token=${API_TOKEN}", "password=[password]", "A sketchy idea",
                     "Release 2026-12-01, version 0.12.3."):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))
                self.assertEqual(redact_credentials(text), text)

    def test_answers_are_redacted_field_by_field(self):
        answers = {"context": f"Use {SAMPLES['a GitHub token']}.", "surface": ["customer"], "kind": "feature"}
        self.assertEqual(redact_data(answers), {"context": "Use [credential].", "surface": ["customer"], "kind": "feature"})

    def test_personal_data_is_recognized(self):
        self.assertEqual(personal_data_kinds("Write to support@example.test"), ["an email address"])
        self.assertEqual(personal_data_kinds("Call +33 6 12 34 56 78"), ["a phone number"])
        self.assertEqual(personal_data_kinds("Pay FR76 3000 6000 0112 3456 7890 189"), ["a bank account number"])
        self.assertEqual(personal_data_kinds("Ship version 1.4.0 on 2026-12-01"), [])


class SettingTests(unittest.TestCase):
    def test_set_refuses_each_shape_without_repeating_it(self):
        tools = load_tools()
        for name, value in SAMPLES.items():
            with self.subTest(shape=name):
                with self.assertRaisesRegex(ValueError, "never a credential") as raised:
                    plan_connections(tools, ["zendesk"], "claude-code", settings={"zendesk": {"subdomain": value}})
                self.assertNotIn(SECRET_PARTS[name], str(raised.exception))

    def test_token_env_takes_only_a_variable_name(self):
        tools = load_tools()
        for value in (*SAMPLES.values(), "jira_token", "JIRA TOKEN", "1TOKEN", "abc123secretvalue"):
            with self.subTest(value=value[:12]):
                with self.assertRaisesRegex(ValueError, "names an environment variable") as raised:
                    plan_connections(tools, ["linear"], "codex", token_env={"linear": value})
                self.assertNotIn(value, str(raised.exception))
        plan = plan_connections(tools, ["linear"], "codex", token_env={"linear": "LINEAR_API_KEY"})
        self.assertEqual(plan[0]["token_env"], "LINEAR_API_KEY")


class TaskInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")))
        self.run_cli("init", "--answers", self.root / "profile.json")

    def run_cli(self, *arguments, code=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["--project", str(self.root), *map(str, arguments)])
        self.assertEqual(result, code, stderr.getvalue())
        return stdout.getvalue(), stderr.getvalue()

    def brief(self):
        return json.loads(self.run_cli("task", "show", TASK)[0])["brief"]

    def test_task_new_keeps_the_words_replaces_the_credential_and_warns_without_blocking(self):
        key, password = SAMPLES["a cloud access key ID"], SAMPLES["a password"]
        _, warning = self.run_cli("task", "new", f"Publish with {key}, {password}. Ask ops@example.test or +33 6 12 34 56 78.",
                                  "--id", TASK)
        self.assertIn("replaced a possible credential in the task brief with a placeholder", warning)
        self.assertIn("an email address and a phone number", warning)
        for value in (key, SECRET_PARTS["a password"], "ops@example.test", "56 78"):
            self.assertNotIn(value, warning)
        self.assertEqual(self.brief(), "Publish with [credential], password=[password]. Ask ops@example.test or +33 6 12 34 56 78.")

    def consult(self, answers):
        write_json(self.root / "answers.json", answers)
        return self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")[1]

    def test_answers_and_a_revised_brief_are_recorded_without_the_credential(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        answers = json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8"))
        token = SAMPLES["a GitHub token"]
        warning = self.consult({**answers, "context": answers["context"] + f" Reference {token}."})
        self.assertIn("replaced a possible credential in the task answers", warning)
        self.assertNotIn(token, warning)
        record = json.loads(self.run_cli("task", "show", TASK)[0])
        self.assertNotIn(token, json.dumps(record))
        self.assertIn("Reference [credential].", record["answers"]["context"])

        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        write_json(self.root / "review.json", review)
        self.run_cli("task", "review", TASK, "--file", self.root / "review.json")
        self.run_cli("task", "decide", TASK, "--request-changes", "--by", "Camille", "--reason", "Narrow the scope")
        stripe = SAMPLES["a Stripe secret key"]
        write_json(self.root / "answers.json", answers)
        _, warning = self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json",
                                  "--brief", f"Show the status only. Test key {stripe}.")
        self.assertIn("replaced a possible credential in the revised brief", warning)
        self.assertNotIn(stripe, warning)
        self.assertEqual(self.brief(), "Show the status only. Test key [credential].")

    def test_a_review_entry_with_a_credential_is_refused_with_the_field_named(self):
        self.run_cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", TASK)
        self.consult(json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8")))
        template = json.loads(self.run_cli("task", "template", TASK)[0])
        review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text(encoding="utf-8"))}
        token = SAMPLES["a Slack token"]
        review["boards"][0]["open_questions"].append(f"Should the bot keep using {token}?")
        write_json(self.root / "review.json", review)
        _, error = self.run_cli("task", "review", TASK, "--file", self.root / "review.json", code=1)
        board = review["boards"][0]["id"]
        self.assertIn(f"{board}.open_questions[{len(review['boards'][0]['open_questions'])}]: contains what looks like "
                      "a Slack token", error)
        self.assertNotIn(token, error)


if __name__ == "__main__":
    unittest.main()
