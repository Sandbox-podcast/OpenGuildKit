"""The controls of OpenGuildKit and the frameworks they may answer: a registry a test holds to what the code does (issue #482).

No clause of a framework is written from memory: a mapping needs the clause, the words it relies on, whether the control
matches it or only part of it with the gap, the address of the source read and the day it was read, and a cell without them
stays empty and says "to verify". The page docs/compliance.md is generated.
"""

import copy
import importlib.util
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from openguildkit import clock, controls
from openguildkit.cli import command_parser

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "compliance.md"
SCRIPT = REPO / "scripts" / "build_compliance.py"
READ = {"reference": "nist-ai-rmf", "clause": "A clause locator", "fit": "partial", "quote": "the words of the clause",
        "gap": "What the control leaves out", "source": "https://example.org/framework", "checked": "2026-11-01"}


def refused(data: dict) -> str:
    with unittest.TestCase().assertRaises(ValueError) as error:
        controls.validate(data)
    return str(error.exception)


def empty_cells(data: dict) -> int:
    return sum(1 for item in data["controls"] for name in data["frameworks"]
               if not any(entry["reference"] == name for entry in item["maps_to"]))


def with_mapping(entry: dict) -> dict:
    data = copy.deepcopy(controls.load())
    data["controls"][0]["maps_to"] = [entry]
    return data


def parser_words(command: str) -> tuple[bool, list[str]]:
    """Whether the words of a command line name real commands of the CLI, and the options the last parser lacks."""
    parser, missing = command_parser(), []
    for word in command.split():
        found = next((action.choices for action in parser._actions if action.choices and hasattr(action.choices, "get")
                      and word in action.choices), None)
        if found is not None and not word.startswith("-"):
            parser = found[word]
        elif word.startswith("--") and word not in {option for action in parser._actions for option in action.option_strings}:
            missing.append(word)
    first = command.split()[0]
    return first in {name for action in command_parser()._actions if hasattr(action.choices, "get")
                     for name in action.choices}, missing


class RegistryTests(unittest.TestCase):
    def test_the_registry_names_each_control_once_with_what_it_does_not_cover(self):
        data = controls.load()
        ids = [item["id"] for item in data["controls"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 10)
        for item in data["controls"]:
            with self.subTest(control=item["id"]):
                self.assertTrue(item["guarantees"].strip())
                self.assertTrue(item["not_covered"].strip())
                self.assertTrue(item["code"])

    def test_an_entry_of_maps_to_without_a_reference_of_the_catalog_or_without_a_checked_date_is_refused(self):
        """Issue #482: a clause written from memory looked the same as one read from the source."""
        controls.validate(with_mapping(READ))
        self.assertIn("reference", refused(with_mapping({key: value for key, value in READ.items() if key != "reference"})))
        self.assertIn("not-a-framework", refused(with_mapping({**READ, "reference": "not-a-framework"})))
        self.assertIn("checked", refused(with_mapping({key: value for key, value in READ.items() if key != "checked"})))
        self.assertIn("checked", refused(with_mapping({**READ, "checked": "yesterday"})))
        future = (clock.real_today() + timedelta(days=2)).isoformat()
        self.assertIn("checked", refused(with_mapping({**READ, "checked": future})))
        for key in ("clause", "source"):
            self.assertIn(key, refused(with_mapping({name: value for name, value in READ.items() if name != key})))
        self.assertIn("source", refused(with_mapping({**READ, "source": "ftp://example.org/x"})))
        self.assertIn("clause", refused(with_mapping({**READ, "clause": "A sentence copied from a text. " * 6})))
        self.assertIn("unknown", refused(with_mapping({**READ, "text": "quoted"})))

    def test_an_entry_says_whether_the_control_matches_the_clause_with_the_words_it_relies_on_and_the_gap(self):
        """Issue #482: a cell named a clause without saying whether the control does all it asks."""
        controls.validate(with_mapping({key: value for key, value in READ.items() if key != "gap"} | {"fit": "matches"}))
        for key in ("fit", "quote"):
            self.assertIn(key, refused(with_mapping({name: value for name, value in READ.items() if name != key})))
        self.assertIn("fit", refused(with_mapping({**READ, "fit": "mostly"})))
        self.assertIn("quote", refused(with_mapping({**READ, "quote": "word " * 60})))
        self.assertIn("gap", refused(with_mapping({key: value for key, value in READ.items() if key != "gap"})))
        self.assertIn("gap", refused(with_mapping({**READ, "fit": "matches"})))

    def test_each_framework_has_a_note_that_says_how_it_was_read_or_why_it_was_not(self):
        data = copy.deepcopy(controls.load())
        self.assertEqual(list(data["framework_notes"]), data["frameworks"])
        del data["framework_notes"][data["frameworks"][-1]]
        self.assertIn("framework_notes", refused(data))

    def test_a_reference_the_catalog_knows_must_also_be_one_of_the_frameworks_of_the_page(self):
        data = with_mapping({**READ, "reference": "owasp-top-10"})
        self.assertIn("frameworks", refused(data))

    def test_no_cell_is_filled_today_without_a_source_read(self):
        data = controls.load()
        for item in data["controls"]:
            for entry in item["maps_to"]:
                self.assertRegex(entry["checked"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(entry["source"].startswith("https://"))
                self.assertTrue(entry["quote"].strip())
                self.assertEqual(entry["fit"] == "partial", bool(entry.get("gap")))

    def test_each_command_a_control_cites_is_one_of_the_cli_with_options_it_has(self):
        for item in controls.load()["controls"]:
            for command in item["commands"]:
                with self.subTest(control=item["id"], command=command):
                    known, missing = parser_words(command)
                    self.assertTrue(known)
                    self.assertEqual(missing, [])

    def test_each_file_and_symbol_a_control_cites_is_where_the_registry_says(self):
        for item in controls.load()["controls"]:
            for where in item["code"]:
                with self.subTest(control=item["id"], where=where["file"]):
                    found = controls.locate(REPO, where["file"], where["symbol"])
                    self.assertEqual(where["line"], found,
                                     f"{where['symbol']} of {where['file']} is at line {found}: run scripts/build_compliance.py")

    def test_each_file_the_dossier_is_said_to_hold_is_one_of_its_files(self):
        from openguildkit.evidence_cli import DOSSIER_FILES

        for item in controls.load()["controls"]:
            self.assertLessEqual(set(item["in_dossier"]), set(DOSSIER_FILES), item["id"])

    def test_the_registry_refuses_a_control_without_what_it_does_not_cover(self):
        data = copy.deepcopy(controls.load())
        data["controls"][0]["not_covered"] = " "
        self.assertIn("not_covered", refused(data))
        data = copy.deepcopy(controls.load())
        data["controls"].append(copy.deepcopy(data["controls"][0]))
        self.assertIn("twice", refused(data))


class PageTests(unittest.TestCase):
    def test_the_tables_of_the_page_are_those_the_registry_generates(self):
        """Issue #482: a page written by hand drifts from the registry it claims to show."""
        text = PAGE.read_text(encoding="utf-8")
        self.assertEqual(controls.update_page(text, controls.load()), text,
                         "docs/compliance.md differs from controls.json: run python scripts/build_compliance.py")

    def test_the_tables_change_with_the_registry(self):
        data = copy.deepcopy(controls.load())
        data["controls"][0]["title"] = "A title that is not in the page"
        text = PAGE.read_text(encoding="utf-8")
        self.assertNotEqual(controls.update_page(text, data), text)
        data = copy.deepcopy(controls.load())
        data["controls"][0]["maps_to"] = [READ]
        self.assertIn("A clause locator", controls.update_page(text, data))

    def test_every_cell_without_a_source_read_says_to_verify_and_the_page_has_a_column_of_what_is_not_covered(self):
        tables = controls.render(controls.load())
        data = controls.load()
        self.assertEqual(tables.count("to verify"), empty_cells(data))
        self.assertIn("Not covered by OpenGuildKit", tables)
        for name, note in data["framework_notes"].items():
            self.assertIn(note, tables, name)
        for item in data["controls"]:
            self.assertIn(item["not_covered"], tables)

    def test_a_cell_that_was_read_shows_its_clause_its_source_and_the_day_it_was_read(self):
        data = with_mapping(READ)
        tables = controls.render(data)
        self.assertIn("A clause locator", tables)
        self.assertIn("https://example.org/framework", tables)
        self.assertIn("read 2026-11-01", tables)
        self.assertIn("Partial: A clause locator", tables)
        self.assertIn("Gap: What the control leaves out", tables)
        self.assertIn("\u201cthe words of the clause\u201d", tables)
        self.assertEqual(tables.count("to verify"), empty_cells(data))

    def test_the_page_says_it_states_no_conformity_and_copies_no_text_of_a_framework(self):
        text = PAGE.read_text(encoding="utf-8")
        self.assertIn("does not state that", text)
        self.assertIn("No clause is written from memory", text)

    def test_the_script_refreshes_the_lines_and_writes_the_page(self):
        spec = importlib.util.spec_from_file_location("build_compliance", SCRIPT)
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "docs").mkdir()
            (root / "docs" / "compliance.md").write_text(PAGE.read_text(encoding="utf-8"), encoding="utf-8")
            data = copy.deepcopy(controls.load())
            data["controls"][0]["code"][0]["line"] = 1
            changed = script.build(root, REPO, data)
            self.assertEqual(changed["controls"]["controls"][0]["code"][0]["line"],
                             controls.load()["controls"][0]["code"][0]["line"])
            self.assertEqual(changed["page"], PAGE.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(changed["json"]), controls.load())


if __name__ == "__main__":
    unittest.main()
