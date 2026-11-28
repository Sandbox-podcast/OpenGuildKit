"""Credentials and personal data in what people and agents give the CLI (issue #155).

Every fake credential is assembled at run time from obvious filler, so no committed string looks like a real one.
"""

import base64
import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit.board_entries import received_value
from openguildkit.sensitive import (
    CREDENTIAL_SHAPES,
    credential_kind,
    personal_data_kinds,
    redact_credentials,
    redact_data,
)
from openguildkit.storage import write_json
from openguildkit.tool_registry import load_tools
from openguildkit.tools import plan_connections
from tests.support import CapturedCli

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
    "a GitLab token": fake("gl" + "pat-", "k", 20),
    "a Google API key": fake("AI" + "za", "m", 35),
    "an Anthropic API key": fake("sk" + "-ant-", "n", 40),
    "an OpenAI API key": fake("sk" + "-proj-", "Ab3", 16),
    "an npm token": fake("np" + "m_", "N4", 18),
    "a PyPI token": fake("py" + "pi-AgE", "Ip", 30),
    "a Hugging Face token": fake("h" + "f_", "H7", 17),
    "an Atlassian API token": fake("ATA" + "TT3x", "F0", 40),
    "a Linear API key": fake("lin" + "_api_", "L9", 20),
    "a Notion token": fake("nt" + "n_", "T5", 23),
    "a Sentry token": fake("sntr" + "ys_", "S3", 20),
    "a Figma token": fake("fig" + "d_", "F2", 20),
    "a Google OAuth access token": fake("ya" + "29.", "Y2", 20),
    "a Slack app token": "xa" + "pp-1-" + "A0" * 6 + "-" + "X3" * 12,
    "a Stripe webhook secret": fake("wh" + "sec_", "W8", 16),
    "a DigitalOcean token": fake("do" + "p_v1_", "d0", 32),
    "a Shopify token": fake("shp" + "at_", "a9", 16),
    "a Slack webhook link": "https://hooks." + "slack.com/services/" + "T0" * 5 + "/" + "B0" * 5 + "/" + "w9" * 12,
    "a Discord webhook link": "https://discord" + ".com/api/webhooks/" + "1" * 18 + "/" + "D4" * 20,
    "a Google OAuth client secret": fake("GOC" + "SPX-", "G6", 14),
    "a SendGrid API key": "S" + "G." + "s8" * 11 + "." + "g1" * 22,
    "an Azure storage key": "DefaultEndpointsProtocol=https;AccountName=demo;Account" + "Key=" + "Az0+" * 10 + "==;",
    "a JSON Web Token": ".".join(["ey" + "J" + "x" * 12, "ey" + "J" + "y" * 12, "z" * 16]),
    "a private key": "-----BEGIN " + "RSA PRIVATE" + " KEY-----\n" + "A" * 40 + "\n-----END " + "RSA PRIVATE" + " KEY-----",
    "a link with a password": "https://deploy:" + "w" * 10 + "@git.example.test/repo",
    "a secret in a query string": "https://api.example.test/v1?access_" + "token=" + "q" * 20,
    "a password": "pass" + "word=" + "v" * 10,
    "a password on a command line": "mysql -u app -" + "p" + "Mq" * 6 + " shop",
    "an authorization header": "Authorization: " + "Bearer " + "o7" * 12,
    "a secret in a setting": "client_" + "secret: " + "c5" * 10,
}
SECRET_PARTS = {
    "a cloud access key ID": "Q" * 16, "a Stripe secret key": "z" * 24, "a GitHub token": "y" * 36,
    "a Slack token": "7" * 16, "a GitLab token": "k" * 20, "a Google API key": "m" * 35,
    "an Anthropic API key": "n" * 40, "a JSON Web Token": "z" * 16, "a private key": "A" * 40,
    "a link with a password": "w" * 10, "a secret in a query string": "q" * 20, "a password": "v" * 10,
    "an OpenAI API key": "Ab3" * 16, "an npm token": "N4" * 18, "a PyPI token": "Ip" * 30, "a Hugging Face token": "H7" * 17,
    "an Atlassian API token": "F0" * 40, "a Linear API key": "L9" * 20, "a Notion token": "T5" * 23,
    "a Sentry token": "S3" * 20, "a Figma token": "F2" * 20, "a Slack webhook link": "w9" * 12,
    "a Google OAuth access token": "Y2" * 20, "a Slack app token": "X3" * 12, "a Stripe webhook secret": "W8" * 16,
    "a DigitalOcean token": "d0" * 32, "a Shopify token": "a9" * 16, "a password on a command line": "Mq" * 6,
    "a Discord webhook link": "D4" * 20, "a Google OAuth client secret": "G6" * 14, "a SendGrid API key": "g1" * 22,
    "an Azure storage key": "Az0+" * 10, "an authorization header": "o7" * 12, "a secret in a setting": "c5" * 10,
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

    def test_a_variable_name_or_a_placeholder_is_not_a_secret(self):
        for text in ("Read ${JIRA_TOKEN} at run time.", "The value became [credential].", "api_key: ${JIRA_TOKEN}",
                     "token: [credential]", "client_secret: <from the vault>", "client_secret: \"YOUR_SECRET\"",
                     "api_key = %API_KEY%", "token: {{ secrets.JIRA_TOKEN }}", "Authorization: Bearer <token>",
                     "Authorization: Bearer YOUR_TOKEN", "API-key auth sends `Authorization: Token token=...`",
                     "Rotate the token: it expires in 90 days.", "Store the api_key: config/settings.yml",
                     "--token-env linear=LINEAR_API_KEY", "token_env=LINEAR_API_KEY",
                     "Name classes in the sk-learn-style-naming-convention way."):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))
                self.assertEqual(redact_credentials(text), text)

    def test_a_namespaced_name_that_starts_with_token_is_not_a_secret(self):
        """Design tokens are named token:KIND:VALUE: the extracted design system's proposals hold dozens of them."""
        for text in ('"key": "token:color:#0a66c2"', '"key": "token:font-size:0.875rem"', "token:spacing:16px",
                     "secret:rotation:2026-12-01"):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))
                self.assertEqual(redact_credentials(text), text)
        self.assertEqual(credential_kind("token:x7x7x7x7x7x7"), "a secret in a setting")

    def test_a_secret_key_followed_by_a_colon_or_an_equals_sign_is_replaced_like_a_password(self):
        value = "x7" * 8
        for key in ("api_key", "apiKey", "token", "secret", "client_secret", "access_key", "AWS_SECRET_ACCESS_KEY",
                    "refresh_token", "x-api-key"):
            for separator in (": ", "=", " = "):
                with self.subTest(key=key, separator=separator):
                    text = f"Connect with {key}{separator}{value} today."
                    self.assertEqual(credential_kind(text), "a secret in a setting")
                    self.assertEqual(redact_credentials(text), f"Connect with {key}{separator}[credential] today.")
        quoted = '{"api_key": "' + "plainletters" + '", "region": "eu"}'
        self.assertEqual(redact_credentials(quoted), '{"api_key": [credential], "region": "eu"}')
        # In a link the query string shape replaces it, and keeps the rest of the link.
        self.assertEqual(redact_credentials(f"https://api.example.test/v1?token={value}&page=2"),
                         "https://api.example.test/v1?token=[credential]&page=2")

    def test_a_password_or_a_passphrase_under_a_prefixed_name_is_replaced(self):
        value = "Xq7vLm2pRt9w"
        for key in ("DB_PASSWORD", "POSTGRES_PASSWORD", "MYSQL_ROOT_PASSWORD", "DB_PWD", "PASSPHRASE", "GPG_PASSPHRASE",
                    "smtp-password", "dbPassword", '"password"', "--password"):
            for separator in ("=", ": "):
                with self.subTest(key=key, separator=separator):
                    text = f"Set {key}{separator}{value} on the server."
                    self.assertEqual(credential_kind(text), "a password")
                    self.assertEqual(redact_credentials(text), f"Set {key}{separator}[password] on the server.")
        for text in ("Set POSTGRES_PASSWORD=${PG_PASSWORD} in compose.", "Rotate the DB_PASSWORD every month.",
                     "Run mysql -p to be asked the password.", "passwordless login", "pwd: command not found"):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))

    def test_a_link_with_an_empty_user_name_has_a_password(self):
        value = "S3cr3t" + "P4ss"
        for link, expected in ((f"redis://:{value}@cache:6379/0", "redis://:[password]@cache:6379/0"),
                               (f"amqp://guest:{value}@mq.example.test/", "amqp://guest:[password]@mq.example.test/")):
            with self.subTest(link=link):
                self.assertEqual(credential_kind(link), "a link with a password")
                self.assertEqual(redact_credentials(f"Set REDIS_URL={link} first."), f"Set REDIS_URL={expected} first.")
        for text in ("redis://cache:6379/0", "redis://:@cache:6379/0", "https://example.test:8080/a@b", "ratio://:"):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))

    def test_an_npm_auth_token_is_a_secret_whatever_its_leading_underscore(self):
        value = "abcdefgh-1234-5678-abcd-" + "ef0123456789"
        text = f"Add //registry.npmjs.org/:_authToken={value} to .npmrc."
        self.assertEqual(credential_kind(text), "a secret in a setting")
        self.assertEqual(redact_credentials(text), "Add //registry.npmjs.org/:_authToken=[credential] to .npmrc.")
        self.assertIsNone(credential_kind("Add //registry.npmjs.org/:_authToken=${NPM_TOKEN} to .npmrc."))
        self.assertIn("[password]", redact_credentials("//registry.npmjs.org/:_password=" + "aGVsbG8" + "gd29ybGQ="))

    def test_an_aws_secret_access_key_is_a_secret_in_any_case(self):
        value = "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
        for text in (f'secretAccessKey: "{value}"', f'"SecretAccessKey": "{value}"', f"secret_access_key = {value}",
                     f"secret-access-key: '{value}'", f"AWS_SECRET_ACCESS_KEY={value}"):
            with self.subTest(text=text[:24]):
                self.assertEqual(credential_kind(text), "a secret in a setting")
                self.assertNotIn(value, redact_credentials(f"Config: {text} done"))
        self.assertIsNone(credential_kind("secretAccessKey: ${AWS_SECRET_ACCESS_KEY}"))
        self.assertIsNone(credential_kind("Read the secretAccessKey from the vault."))

    def test_a_password_given_as_an_argument_is_replaced(self):
        value = "Xq7vLm2" + "pRt9w"
        for command, expected in (
                (f"psql --password {value} shop", "psql --password [password] shop"),
                (f"mysql --pass {value} shop", "mysql --pass [password] shop"),
                (f"htpasswd --passwd {value}", "htpasswd --passwd [password]"),
                (f"docker login -u deploy -p {value} registry.example.test",
                 "docker login -u deploy -p [password] registry.example.test"),
                (f"sshpass -p '{value}' ssh deploy@host", "sshpass -p [password] ssh deploy@host"),
                (f'az login --password "{value}"', "az login --password [password]")):
            with self.subTest(command=command[:24]):
                self.assertEqual(credential_kind(command), "a password on a command line")
                self.assertEqual(redact_credentials(f"Run {command}"), f"Run {expected}")

    def test_a_flag_that_is_not_followed_by_a_password_is_left_alone(self):
        for text in ("mkdir -p /tmp/build", "docker run -p 8080:80 app", "ssh -p 2222 deploy@host", "cp -p a b",
                     "docker login --password-stdin", "psql --password to be asked", "Remove the --password flag",
                     "Run docker login -p $REGISTRY_PASSWORD", "psql --password <password>", "sshpass -p '' ssh host",
                     "login -p prompt", "psql --password YOUR_PASSWORD"):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))
                self.assertEqual(redact_credentials(text), text)

    def test_a_requirement_about_a_password_is_not_a_password(self):
        for text in ("Signup form. Password: required, min 12 chars.", "Password: optional", "password: min 12 characters",
                     "Password = required.", "Mot de passe: obligatoire, 12 caractères.", "Password: must contain a digit"):
            with self.subTest(text=text):
                self.assertIsNone(credential_kind(text))
                self.assertEqual(redact_credentials(text), text)
        for text, expected in (("Password: Xq7vLm2pRt9w", "Password: [password]"), ("password: hunter2", "password: [password]"),
                               ("Password: required123", "Password: [password]"), ('password: "required"', "password: [password]"),
                               ("Password: correcthorse", "Password: [password]"), ("mot de passe: Xq7vLm2pRt9w", "mot de passe: [password]")):
            with self.subTest(text=text):
                self.assertEqual(redact_credentials(text), expected)

    def test_a_pgp_private_key_block_and_a_french_password_are_replaced(self):
        block = "-----BEGIN PGP PRIVATE KEY BLOCK-----\nlQOYBF" + "x" * 40 + "\n-----END PGP PRIVATE KEY BLOCK-----"
        self.assertEqual(redact_credentials(f"Key:\n{block}\nDone."), "Key:\n[private key]\nDone.")
        self.assertEqual(redact_credentials("mdp: Xq7vLm2" + "pRt9w"), "mdp: [password]")
        self.assertEqual(redact_credentials("DB_MDP=Xq7vLm2" + "pRt9w"), "DB_MDP=[password]")

    def test_a_camel_case_token_key_is_a_secret_in_a_setting(self):
        value = "x7" * 8
        for key in ("accessToken", "refreshToken", "idToken", "clientSecret"):
            for text in (f'{{"{key}": "{value}"}}', f"{key}={value}", f"{key}: {value}"):
                with self.subTest(text=text):
                    self.assertEqual(credential_kind(text), "a secret in a setting")
                    self.assertNotIn(value, redact_credentials(text))
        self.assertIsNone(credential_kind("maxTokens: 4000"))

    def test_an_openai_key_is_recognized_with_or_without_its_project_prefix(self):
        for prefix in ("sk-", "sk-proj-", "sk-svcacct-", "sk-admin-"):
            with self.subTest(prefix=prefix):
                text = f"Call the model with {fake(prefix, 'Qz8', 16)} today."
                self.assertEqual(credential_kind(text), "an OpenAI API key")
                self.assertEqual(redact_credentials(text), "Call the model with [credential] today.")

    def test_an_authorization_header_is_replaced_whatever_its_scheme(self):
        for scheme, value in (("Bearer", "opaque" + "9f" * 10), ("Basic", "dXNl" + "cjpwYXNz"), ("Token", "t0k" * 5)):
            with self.subTest(scheme=scheme):
                text = f'curl -H "Authorization: {scheme} {value}" https://api.example.test'
                self.assertEqual(credential_kind(text), "an authorization header")
                self.assertEqual(redact_credentials(text),
                                 f'curl -H "Authorization: {scheme} [credential]" https://api.example.test')

    def test_answers_are_redacted_field_by_field(self):
        answers = {"context": f"Use {SAMPLES['a GitHub token']}.", "surface": ["customer"], "kind": "feature"}
        self.assertEqual(redact_data(answers), {"context": "Use [credential].", "surface": ["customer"], "kind": "feature"})

    def test_personal_data_is_recognized(self):
        self.assertEqual(personal_data_kinds("Write to support@example.test"), ["an email address"])
        self.assertEqual(personal_data_kinds("Call +33 6 12 34 56 78"), ["a phone number"])
        self.assertEqual(personal_data_kinds("Pay FR76 3000 6000 0112 3456 7890 189"), ["a bank account number"])
        self.assertEqual(personal_data_kinds("Ship version 1.4.0 on 2026-12-01"), [])


class CostTests(unittest.TestCase):
    """A long line costs one pass of each shape, not one pass per character (issue #378)."""

    # A linear pass over these lines takes a few milliseconds; the quadratic one took ten seconds or more.
    BUDGET = 2.0

    @staticmethod
    def long_lines(size):
        noise = random.Random(378).randbytes(size * 3 // 4)
        return {
            "one word": "a" * size, "words joined by underscores": "a_" * (size // 2),
            "words joined by hyphens": "a-1" * (size // 3), "dotted words": "x." * (size // 2),
            "base64": base64.b64encode(noise).decode(), "base64 with hyphens": base64.urlsafe_b64encode(noise).decode(),
            "mysql on one line": "mysql " * (size // 6), "login on one line": "login " * (size // 6),
            "repeated flags": "--pass x " * (size // 9), "at signs": "a@" * (size // 2),
            "a word and an at sign": "a" * (size - 1) + "@", "sk- prefixes": "sk-" * (size // 3),
        }

    def assertQuick(self, function, size):
        for label, text in self.long_lines(size).items():
            with self.subTest(line=label):
                started = time.perf_counter()
                function(text)
                self.assertLess(time.perf_counter() - started, self.BUDGET)

    def test_redacting_a_long_line_stays_linear(self):
        self.assertQuick(redact_credentials, 50_000)

    def test_looking_for_personal_data_in_a_long_line_stays_linear(self):
        self.assertQuick(personal_data_kinds, 200_000)

    def test_an_error_line_cuts_a_long_value_before_looking_for_secrets(self):
        searched = []
        with patch("openguildkit.board_entries.redact_credentials", side_effect=lambda text: searched.append(text) or text):
            received = received_value("a" * 200_000)
        self.assertLess(len(searched[0]), 5_000)
        self.assertEqual(len(received), 60)
        self.assertEqual(received_value(f"Key {SAMPLES['a GitHub token']}"), '"Key [credential]"')

    def test_a_long_line_still_hides_the_secret_it_ends_with(self):
        for text in ("a_" * 2_000 + "DB_PASSWORD=Xq7vLm2pRt9w", "a_" * 2_000 + " dbPassword=Xq7vLm2pRt9w",
                     "a_" * 2_000 + " --password=Xq7vLm2pRt9w"):
            with self.subTest(end=text[-30:]):
                self.assertTrue(redact_credentials(text).endswith("=[password]"))
        self.assertEqual(personal_data_kinds("a." * 5_000 + " ops@example.test"), ["an email address"])
        self.assertEqual(personal_data_kinds("a" * 5_000 + "@example.test"), ["an email address"])
        self.assertEqual(redact_credentials("mysql " * 1_000 + "-u app -pMq7Lm2pRt9 shop").count("[password]"), 1)


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
        for value in (*SAMPLES.values(), "jira_t0ken9", "JIRA TOKEN", "1TOKEN", "abc123secretvalue"):
            with self.subTest(value=value[:12]):
                with self.assertRaisesRegex(ValueError, "names an environment variable") as raised:
                    plan_connections(tools, ["linear"], "codex", token_env={"linear": value})
                self.assertNotIn(value, str(raised.exception))
        plan = plan_connections(tools, ["linear"], "codex", token_env={"linear": "LINEAR_API_KEY"})
        self.assertEqual(plan[0]["token_env"], "LINEAR_API_KEY")
        self.assertEqual(plan_connections(tools, ["linear"], "codex", token_env={"linear": "jira_token"})[0]["token_env"],
                         "jira_token")


class TaskInputTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text(encoding="utf-8")))
        self.run_cli("init", "--answers", self.root / "profile.json")

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

    def test_a_prefixed_password_and_a_google_access_token_in_a_brief_are_replaced(self):
        password, token = "Xq7vLm2pRt9w", SAMPLES["a Google OAuth access token"]
        _, warning = self.run_cli("task", "new", f"Move the database: POSTGRES_PASSWORD={password} and the accessToken "
                                                 f"{token} are in the old runbook.", "--id", TASK)
        self.assertIn("replaced a possible credential in the task brief with a placeholder", warning)
        self.assertEqual(self.brief(), "Move the database: POSTGRES_PASSWORD=[password] and the accessToken [credential] "
                                       "are in the old runbook.")
        record = (self.root / ".openguildkit" / "tasks" / f"{TASK}.json").read_text(encoding="utf-8")
        for part in (password, SECRET_PARTS["a Google OAuth access token"]):
            self.assertNotIn(part, record)
            self.assertNotIn(part, warning)

    def test_the_forms_the_detector_once_missed_are_recorded_without_their_secret(self):
        redis, npm, aws = "S3cr3t" + "P4ss", "abcdefgh-1234-5678-abcd-" + "ef0123456789", "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
        brief = (f'Fix cache: REDIS_URL=redis://:{redis}@cache:6379/0 and secretAccessKey: "{aws}" in '
                 f"//registry.npmjs.org/:_authToken={npm}")
        _, warning = self.run_cli("task", "new", brief, "--id", TASK)
        self.assertIn("replaced a possible credential in the task brief", warning)
        record = (self.root / ".openguildkit" / "tasks" / f"{TASK}.json").read_text(encoding="utf-8")
        for secret in (redis, npm, aws):
            self.assertNotIn(secret, record)
            self.assertNotIn(secret, warning)

    def test_a_requirement_that_names_a_password_is_recorded_as_written(self):
        brief = "Signup form. Password: required, min 12 chars."
        _, warning = self.run_cli("task", "new", brief, "--id", TASK)
        self.assertEqual(self.brief(), brief)
        self.assertNotIn("replaced a possible credential", warning)

    def test_a_brief_with_registry_tokens_is_recorded_without_them(self):
        atlassian, openai = SAMPLES["an Atlassian API token"], SAMPLES["an OpenAI API key"]
        brief = f"Connect the Jira export. Use api_key: {atlassian} and Authorization: Bearer {openai} for the calls."
        _, warning = self.run_cli("task", "new", brief, "--id", TASK)
        self.assertIn("replaced a possible credential in the task brief", warning)
        self.assertEqual(self.brief(), "Connect the Jira export. Use api_key: [credential] and Authorization: Bearer "
                                       "[credential] for the calls.")
        record = (self.root / ".openguildkit" / "tasks" / f"{TASK}.json").read_text(encoding="utf-8")
        for part in (SECRET_PARTS["an Atlassian API token"], SECRET_PARTS["an OpenAI API key"]):
            self.assertNotIn(part, record)
            self.assertNotIn(part, warning)

    def consult(self, answers):
        write_json(self.root / "answers.json", answers)
        return self.run_cli("task", "consult", TASK, "--answers", self.root / "answers.json")[1]

    def test_a_long_brief_and_a_long_answer_are_recorded_without_a_wait(self):
        started = time.perf_counter()
        self.run_cli("task", "new", "a" * 30_000, "--id", TASK)
        self.assertLess(time.perf_counter() - started, 2 * CostTests.BUDGET)
        answers = json.loads((EXAMPLE / "answers.json").read_text(encoding="utf-8"))
        started = time.perf_counter()
        self.consult({**answers, "context": "x" * 30_000})
        self.assertLess(time.perf_counter() - started, 2 * CostTests.BUDGET)

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
