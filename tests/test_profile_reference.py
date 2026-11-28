"""docs/profile-reference.md and docs/project.schema.json follow validate_profile: a field it gains must be written up."""

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path

from tests.support import run_cli

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "profile-reference.md"
SCHEMA = REPO / "docs" / "project.schema.json"
EXAMPLE = REPO / "examples" / "request-status"


def profile_fields() -> set[str]:
    """The fields validate_profile accepts: the set it names at its top."""
    tree = ast.parse((REPO / "src" / "openguildkit" / "project.py").read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "validate_profile")
    assignment = next(node for node in function.body if isinstance(node, ast.Assign) and node.targets[0].id == "fields")
    return {element.value for element in assignment.value.elts}


def page_fields() -> list[str]:
    """The field of each row of the table of docs/profile-reference.md."""
    table = PAGE.read_text(encoding="utf-8").split("## The 30 fields", 1)[1].split("\n## ", 1)[0]
    return re.findall(r"^\| `(\w+)` \|", table, re.MULTILINE)


def problems(value, schema: dict, root: dict, path: str = "$") -> list[str]:
    """What keeps value from matching schema: the keywords this schema uses, no more (the standard library has no validator)."""
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return problems(value, target, root, path)
    found = []
    if "const" in schema and (value != schema["const"] or type(value) is not type(schema["const"])):
        found.append(f"{path}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{path}: not one of {schema['enum']}")
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
    if "type" in schema:
        wrong = not isinstance(value, kinds[schema["type"]]) or (schema["type"] == "integer" and isinstance(value, bool))
        if wrong:
            return found + [f"{path}: not {schema['type']}"]
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            found.append(f"{path}: length")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            found.append(f"{path}: pattern")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            found.append(f"{path}: range")
    if isinstance(value, dict):
        found += [f"{path}: missing {key}" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in schema.get("properties", {}):
                found += problems(item, schema["properties"][key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{path}: unknown {key}")
    if isinstance(value, list) and "items" in schema:
        for number, item in enumerate(value):
            found += problems(item, schema["items"], root, f"{path}[{number}]")
    for part in schema.get("allOf", []):
        found += problems(value, part, root, path)
    if "oneOf" in schema and sum(not problems(value, part, root, path) for part in schema["oneOf"]) != 1:
        found.append(f"{path}: not exactly one of the shapes")
    return found


class ProfileReferenceTests(unittest.TestCase):
    def test_the_page_lists_the_30_fields_validate_profile_accepts_once_each(self):
        """Issue #491: no page listed the 28 fields of the profile, and `schema_version` was in none; #481 and #519 added two."""
        self.assertEqual(len(profile_fields()), 30)
        self.assertEqual(sorted(page_fields()), sorted(profile_fields()))

    def test_the_schema_has_one_property_for_each_field_and_refuses_the_others(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(set(schema["properties"]), profile_fields())
        self.assertIs(schema["additionalProperties"], False)

    def test_the_schema_accepts_the_profile_init_writes_for_the_example_project(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            run_cli(Path(directory), "init", "--answers", EXAMPLE / "profile.json")
            profile = json.loads((Path(directory) / ".openguildkit" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(problems(profile, schema, schema), [])
        self.assertGreaterEqual(len(profile), 10)

    def test_the_schema_accepts_a_profile_that_uses_the_optional_fields_and_refuses_a_wrong_one(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        profile = {
            "schema_version": 1, "name": "Ledger", "sector": "general", "stack": ["Python"],
            "components": [{"id": "api", "path": "services/api", "stack": ["Python"]}], "roles": ["project-management"],
            "patterns": ["python-development", {"id": "python-fastapi-postgresql", "components": ["api"]}],
            "packs": ["agent-workflow", "python"], "resolutions": [{"packs": ["a", "b"], "keep": ["a"], "reason": "A wins"}],
            "boards": [], "required_boards": ["security"], "required_rules": ["gdpr/confirm-lawful-basis"],
            "research": "local-only", "host": "gemini-cli", "guard": "enforce",
            "waivers": {"allowed_by": ["CM"], "max_days": 30},
            "approval": {"mode": "signed", "allowed_signers": ".openguildkit/allowed_signers", "approvers": ["CM"],
                         "max_age_days": 30, "roles": {"security": ["CM"]}},
            "tools": ["jira"], "conventions": ["Use Conventional Commits."], "checks": ["python -m pytest"],
            "personal_data": True, "people_decisions": False,
            "declined": ["eu-ai-act-system", {"id": "dora", "by": "CM", "on": "2026-11-27", "reason": "Not a bank"}],
            "changes": [{"change": "guard enforce", "by": "CM", "on": "2026-11-27", "reason": "Go live"}],
            "ask_every_rule": True, "light_paths": ["docs/**"],
            "declined_rules": [{"id": "python/lint", "by": "CM", "on": "2026-11-27", "reason": "Linter in CI"}],
            "separate_requester": True, "frozen": {"by": "CM", "on": "2026-11-27", "reason": "Incident"},
            "restricted_paths": [{"paths": ["data/customers/**"], "class": "restricted", "boards": ["security"]}],
        }
        self.assertEqual(set(profile), profile_fields())
        self.assertEqual(problems(profile, schema, schema), [])
        for change in ({"guard": "strict"}, {"unknown_field": 1}, {"approval": {"mode": "signed"}},
                       {"waivers": {"allowed_by": ["CM"], "max_days": 400}}, {"schema_version": 2},
                       {"frozen": {"by": "CM"}}, {"restricted_paths": [{"paths": ["/etc/**"]}]},
                       {"declined_rules": [{"id": "python", "by": "CM", "on": "2026-11-27", "reason": "x"}]}):
            with self.subTest(change=change):
                self.assertNotEqual(problems({**profile, **change}, schema, schema), [])


if __name__ == "__main__":
    unittest.main()
