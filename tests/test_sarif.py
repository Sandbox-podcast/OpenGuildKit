"""The SARIF 2.1.0 writer: the document's shape, its determinism, its fingerprints and what it refuses (#420).

`structure_problems` is a structural check of the files OpenGuildKit writes, with the standard library only. It is not
the JSON schema of the standard: it checks the fields that GitHub code scanning and the other readers need, their
types, that each `ruleIndex` points at its `ruleId` and that every location is a path relative to the project root.
`machine_paths` finds the texts that name a folder of the machine that wrote the file. The tests of the commands use
both (tests/test_sarif_commands.py).
"""

import copy
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from openguildkit.sarif import DEFAULT_PATH, finding, fingerprint, sarif_text, to_sarif

LEVELS = {"error", "warning", "note", "none"}
FINGERPRINT = re.compile(r"[0-9a-f]{64}(:[0-9]+)?")
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
# A POSIX folder that holds users, temporary files or system files, or a Windows drive letter.
MACHINE_PATH = re.compile(r"(?<![\w.:/-])/(?:Users|home|private|tmp|var|root|opt|mnt|etc)/|(?<![A-Za-z0-9])[A-Za-z]:[\\/]")


def _texts(value):
    """Every string of a JSON value, keys included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def structure_problems(document) -> list[str]:
    """What is missing or malformed in a SARIF document; an empty list means the structure holds."""
    problems = []

    def need(condition: bool, text: str) -> bool:
        if not condition:
            problems.append(text)
        return condition

    if not need(isinstance(document, dict), "the document is not an object"):
        return problems
    need(document.get("version") == "2.1.0", "version is not 2.1.0")
    need(document.get("$schema") == "https://json.schemastore.org/sarif-2.1.0.json", "$schema is missing or other")
    runs = document.get("runs")
    if not need(isinstance(runs, list) and len(runs) == 1, "runs is not a list of one run"):
        return problems
    run = runs[0]
    driver = (run.get("tool") or {}).get("driver") if isinstance(run, dict) else None
    if not need(isinstance(driver, dict), "runs[0].tool.driver is missing"):
        return problems
    need(driver.get("name") == "OpenGuildKit", "driver.name is not OpenGuildKit")
    need(_is_text(driver.get("version")), "driver.version is missing")
    need(str(driver.get("informationUri", "")).startswith("https://"), "driver.informationUri is not an https link")
    rules = driver.get("rules")
    if not need(isinstance(rules, list), "driver.rules is not a list"):
        return problems
    identifiers = []
    for position, rule in enumerate(rules):
        label = f"rules[{position}]"
        if not need(isinstance(rule, dict), f"{label} is not an object"):
            continue
        need(_is_text(rule.get("id")), f"{label}.id is missing")
        need(_is_text(rule.get("name")), f"{label}.name is missing")
        need(_is_text((rule.get("shortDescription") or {}).get("text")), f"{label}.shortDescription.text is missing")
        need(str(rule.get("helpUri", "")).startswith("https://") and "#" in str(rule.get("helpUri", "")),
             f"{label}.helpUri is not an https link with an anchor")
        identifiers.append(rule.get("id"))
    need(len(set(identifiers)) == len(identifiers), "two rules share an id")
    results = run.get("results")
    if not need(isinstance(results, list), "runs[0].results is not a list"):
        return problems
    used = set()
    for position, result in enumerate(results):
        label = f"results[{position}]"
        if not need(isinstance(result, dict), f"{label} is not an object"):
            continue
        rule_id, index = result.get("ruleId"), result.get("ruleIndex")
        need(_is_text(rule_id), f"{label}.ruleId is missing")
        if need(isinstance(index, int) and not isinstance(index, bool) and 0 <= index < len(rules),
                f"{label}.ruleIndex is not the position of a rule"):
            need(rules[index].get("id") == rule_id, f"{label}.ruleIndex points at another rule than its ruleId")
        used.add(rule_id)
        need(result.get("level") in LEVELS, f"{label}.level is not a SARIF level")
        need(_is_text((result.get("message") or {}).get("text")), f"{label}.message.text is missing")
        locations = result.get("locations")
        if need(isinstance(locations, list) and locations, f"{label}.locations is empty"):
            physical = (locations[0] or {}).get("physicalLocation") or {}
            artifact = physical.get("artifactLocation") or {}
            uri = artifact.get("uri")
            if need(_is_text(uri), f"{label} has no artifactLocation.uri"):
                need(not uri.startswith(("/", "\\")) and not URI_SCHEME.match(uri) and ".." not in uri.split("/"),
                     f"{label}.artifactLocation.uri is not relative to the project root: {uri}")
            need(artifact.get("uriBaseId") == "%SRCROOT%", f"{label}.artifactLocation.uriBaseId is not %SRCROOT%")
            if "region" in physical:
                line = (physical["region"] or {}).get("startLine")
                need(isinstance(line, int) and not isinstance(line, bool) and line >= 1,
                     f"{label}.region.startLine is not a line number")
        prints = result.get("partialFingerprints")
        if need(isinstance(prints, dict) and prints, f"{label}.partialFingerprints is missing"):
            need(all(isinstance(value, str) and FINGERPRINT.fullmatch(value) for value in prints.values()),
                 f"{label}.partialFingerprints holds something else than a sha256")
    need(used == set(identifiers), "driver.rules lists a rule no result uses, or a result's rule is missing")
    return problems


def machine_paths(document) -> list[str]:
    """The texts of a document that name a folder of the machine, such as /Users/NAME/... or C:\\Users\\NAME."""
    return sorted({text for text in _texts(document) if MACHINE_PATH.search(text)})

RULES = {
    "demo-drift": {"name": "Demo drift", "description": "A file no longer matches what it was generated from.",
                   "help": "sarif.md#demo-drift"},
    "demo-missing": {"name": "Demo missing", "description": "A file the project expects is missing.",
                     "help": "sarif.md#demo-missing"},
    "demo-unused": {"name": "Demo unused", "description": "No finding uses this rule.", "help": "sarif.md#demo-unused"},
}


def make(code="demo-drift", level="error", message="AGENTS.md is out of date.", path="AGENTS.md", line=None):
    return {"code": code, "level": level, "message": message, "path": path, "line": line}


def document(findings, **options):
    return to_sarif(findings, rules=RULES, tool_version="1.2.3", **options)


class ShapeTests(unittest.TestCase):
    def test_a_document_without_a_finding_is_valid_and_has_no_result(self):
        result = document([])
        self.assertEqual(structure_problems(result), [])
        run = result["runs"][0]
        self.assertEqual(run["results"], [])
        self.assertEqual(run["tool"]["driver"]["rules"], [])

    def test_the_document_names_the_standard_the_tool_and_its_version(self):
        result = document([make()])
        self.assertEqual(result["version"], "2.1.0")
        self.assertEqual(result["$schema"], "https://json.schemastore.org/sarif-2.1.0.json")
        driver = result["runs"][0]["tool"]["driver"]
        self.assertEqual((driver["name"], driver["version"]), ("OpenGuildKit", "1.2.3"))
        self.assertEqual(driver["informationUri"], "https://github.com/Sandbox-podcast/OpenGuildKit")

    def test_several_findings_keep_their_rule_index_and_list_only_the_rules_they_use(self):
        findings = [make("demo-missing", "warning", "Gone.", ".openguildkit/catalog.lock.json"),
                    make(), make("demo-drift", "note", "Another.", "CLAUDE.md"), make(message="Third.", line=7)]
        result = document(findings)
        self.assertEqual(structure_problems(result), [])
        run = result["runs"][0]
        self.assertEqual([rule["id"] for rule in run["tool"]["driver"]["rules"]], ["demo-drift", "demo-missing"])
        self.assertEqual(len(run["results"]), 4)
        for item in run["results"]:
            self.assertEqual(run["tool"]["driver"]["rules"][item["ruleIndex"]]["id"], item["ruleId"])

    def test_a_rule_gets_its_title_its_description_and_a_help_link_with_an_anchor(self):
        rule = document([make()])["runs"][0]["tool"]["driver"]["rules"][0]
        self.assertEqual(rule["id"], "demo-drift")
        self.assertEqual(rule["name"], "Demo drift")
        self.assertEqual(rule["shortDescription"], {"text": "A file no longer matches what it was generated from."})
        self.assertEqual(rule["helpUri"], "https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/sarif.md#demo-drift")

    def test_a_location_is_relative_to_the_source_root_and_a_line_is_given_only_when_known(self):
        first, second = document([make(path="docs/a b.md", line=12), make(message="Other.")])["runs"][0]["results"]
        placed = {item["message"]["text"]: item["locations"][0]["physicalLocation"] for item in (first, second)}
        known = placed["AGENTS.md is out of date."]
        self.assertEqual(known["artifactLocation"], {"uri": "docs/a%20b.md", "uriBaseId": "%SRCROOT%"})
        self.assertEqual(known["region"], {"startLine": 12})
        unknown = placed["Other."]
        self.assertEqual(unknown["artifactLocation"], {"uri": "AGENTS.md", "uriBaseId": "%SRCROOT%"})
        self.assertNotIn("region", unknown)

    def test_a_finding_without_a_file_points_at_the_project_profile(self):
        item = document([make(path=None)])["runs"][0]["results"][0]
        self.assertEqual(DEFAULT_PATH, ".openguildkit/project.json")
        self.assertEqual(item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], ".openguildkit/project.json")

    def test_the_levels_the_standard_names_are_kept(self):
        levels = [item["level"] for item in document([make(level=level, message=level)
                                                       for level in ("error", "warning", "note")])["runs"][0]["results"]]
        self.assertEqual(sorted(levels), ["error", "note", "warning"])

    def test_the_structure_check_catches_what_it_is_meant_to_catch(self):
        good = document([make(), make("demo-missing", message="Other.")])
        self.assertEqual(structure_problems(good), [])
        broken = copy.deepcopy(good)
        del broken["runs"][0]["results"][0]["ruleId"]
        self.assertTrue(structure_problems(broken))
        misindexed = copy.deepcopy(good)
        misindexed["runs"][0]["results"][0]["ruleIndex"] = 1 - misindexed["runs"][0]["results"][0]["ruleIndex"]
        self.assertTrue(any("another rule" in problem for problem in structure_problems(misindexed)))
        absolute = copy.deepcopy(good)
        absolute["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] = "/etc/passwd"
        self.assertTrue(any("relative" in problem for problem in structure_problems(absolute)))
        unversioned = copy.deepcopy(good)
        unversioned["runs"][0]["tool"]["driver"].pop("version")
        self.assertTrue(structure_problems(unversioned))
        self.assertTrue(structure_problems([]))


class DeterminismTests(unittest.TestCase):
    FINDINGS = [make("demo-missing", "warning", "Gone.", ".openguildkit/catalog.lock.json"), make(),
                make(message="Ünïcode and “quotes” stay readable.", path="CLAUDE.md"), make(path=None, message="No file.")]

    def test_two_runs_write_the_same_bytes(self):
        first = sarif_text(document(self.FINDINGS)).encode("utf-8")
        second = sarif_text(document(copy.deepcopy(self.FINDINGS))).encode("utf-8")
        self.assertEqual(first, second)

    def test_the_order_of_the_findings_does_not_change_the_file(self):
        expected = sarif_text(document(self.FINDINGS))
        self.assertEqual(sarif_text(document(list(reversed(self.FINDINGS)))), expected)
        self.assertEqual(sarif_text(document(self.FINDINGS[2:] + self.FINDINGS[:2])), expected)

    def test_the_text_is_utf_8_with_readable_characters_and_one_final_newline(self):
        text = sarif_text(document(self.FINDINGS))
        self.assertTrue(text.endswith("}\n"))
        self.assertFalse(text.endswith("\n\n"))
        self.assertIn("Ünïcode and “quotes” stay readable.", text)
        self.assertEqual(json.loads(text.encode("utf-8").decode("utf-8")), document(self.FINDINGS))

    def test_the_top_level_keys_come_in_the_order_readers_expect(self):
        self.assertEqual(list(document([])), ["$schema", "version", "runs"])
        self.assertEqual(list(document([])["runs"][0]), ["tool", "results"])
        self.assertEqual(list(document([make()])["runs"][0]["results"][0]),
                         ["ruleId", "ruleIndex", "level", "message", "locations", "partialFingerprints"])


class FingerprintTests(unittest.TestCase):
    def prints(self, findings):
        return {item["message"]["text"]: item["partialFingerprints"]["openguildkit/v1"]
                for item in document(findings)["runs"][0]["results"]}

    def test_a_fingerprint_is_the_sha256_of_the_code_the_path_and_the_message(self):
        expected = hashlib.sha256("demo-drift|AGENTS.md|AGENTS.md is out of date.".encode("utf-8")).hexdigest()
        self.assertEqual(fingerprint(make()), expected)
        self.assertEqual(document([make()])["runs"][0]["results"][0]["partialFingerprints"], {"openguildkit/v1": expected})

    def test_fingerprints_do_not_move_when_the_order_of_the_findings_changes(self):
        findings = [make(message=f"Finding {number}.", path=f"docs/{number}.md") for number in range(6)]
        self.assertEqual(self.prints(findings), self.prints(list(reversed(findings))))

    def test_a_different_code_path_or_message_gives_another_fingerprint(self):
        base = fingerprint(make())
        for other in (make(code="demo-missing"), make(path="CLAUDE.md"), make(message="Something else.")):
            self.assertNotEqual(fingerprint(other), base)

    def test_the_line_and_the_level_are_not_part_of_the_fingerprint(self):
        self.assertEqual(fingerprint(make(line=3)), fingerprint(make(line=90, level="warning")))

    def test_spaces_and_line_breaks_in_the_message_do_not_change_the_fingerprint(self):
        self.assertEqual(fingerprint(make(message="AGENTS.md  is\nout of   date. ")), fingerprint(make()))

    def test_no_path_and_the_profile_path_are_the_same_finding(self):
        self.assertEqual(fingerprint(make(path=None)), fingerprint(make(path=DEFAULT_PATH)))

    def test_the_same_finding_twice_is_written_once(self):
        results = document([make(), make(), make(line=4)])["runs"][0]["results"]
        self.assertEqual(len(results), 2)

    def test_the_same_text_on_two_lines_of_a_file_gets_two_distinct_fingerprints(self):
        results = document([make(line=30), make(line=4)])["runs"][0]["results"]
        prints = [item["partialFingerprints"]["openguildkit/v1"] for item in results]
        self.assertEqual(len(set(prints)), 2)
        # The first line keeps the plain fingerprint, so one alert does not change when another appears below it.
        self.assertEqual(prints[0], fingerprint(make()))
        self.assertEqual(prints[1], fingerprint(make()) + ":2")
        self.assertEqual(structure_problems(document([make(line=30), make(line=4)])), [])


class RefusalTests(unittest.TestCase):
    def refused(self, findings, *fragments, **options):
        with self.assertRaises(ValueError) as caught:
            document(findings, **options)
        for fragment in fragments:
            self.assertIn(fragment, str(caught.exception))

    def test_a_code_without_a_rule_is_refused_by_name(self):
        # OGK-CHECK-008
        self.refused([make("demo-nothing")], "demo-nothing", "No rule describes")

    def test_a_level_the_standard_does_not_have_is_refused(self):
        # OGK-CHECK-009
        self.refused([make(level="fatal")], "fatal", "error, warning or note")

    def test_a_message_must_say_something(self):
        # OGK-CHECK-010
        self.refused([make(message="  ")], "message")

    def test_an_absolute_path_or_a_path_outside_the_project_is_refused(self):
        # OGK-CHECK-007
        for path in ("/etc/passwd", "C:\\Users\\me\\AGENTS.md", "c:/work/AGENTS.md", "../outside.md", "docs/../../x"):
            with self.subTest(path=path):
                self.refused([make(path=path)], "relative to the project root")

    def test_a_line_must_be_a_positive_whole_number(self):
        # OGK-CHECK-011
        for line in (0, -3, 2.5, "7", True):
            with self.subTest(line=line):
                self.refused([make(line=line)], "line")

    def test_a_windows_separator_and_a_leading_dot_slash_are_written_as_a_posix_path(self):
        item = document([make(path=".\\docs\\guide.md")])["runs"][0]["results"][0]
        self.assertEqual(item["locations"][0]["physicalLocation"]["artifactLocation"]["uri"], "docs/guide.md")

    def test_a_rule_that_lacks_a_field_is_refused_by_name(self):
        # OGK-CHECK-012
        with self.assertRaises(ValueError) as caught:
            to_sarif([make()], rules={"demo-drift": {"name": "Only a name"}}, tool_version="1")
        self.assertIn("demo-drift", str(caught.exception))
        self.assertIn("description", str(caught.exception))


class FindingTests(unittest.TestCase):
    def test_finding_builds_the_canonical_form(self):
        self.assertEqual(finding("demo-drift", "error", "Text."),
                         {"code": "demo-drift", "level": "error", "message": "Text.", "path": None, "line": None})
        self.assertEqual(finding("demo-drift", "note", "Text.", "a/b.md", 3),
                         {"code": "demo-drift", "level": "note", "message": "Text.", "path": "a/b.md", "line": 3})


class MachineTests(unittest.TestCase):
    def test_the_project_folder_and_the_home_folder_are_left_out_of_a_message(self):
        with tempfile.TemporaryDirectory(prefix="ogk-sarif-user-") as folder:
            root = Path(folder).resolve()
            raw = f"Unsupported or mismatched task record: {root}/.openguildkit/tasks/a.json (in {root})"
            result = document([make(message=raw)], root=root)
            text = result["runs"][0]["results"][0]["message"]["text"]
            self.assertNotIn(str(root), text)
            self.assertEqual(text, "Unsupported or mismatched task record: .openguildkit/tasks/a.json (in the project folder)")
            self.assertEqual(machine_paths(result), [])
            self.assertEqual(structure_problems(result), [])

    def test_a_windows_folder_leaves_a_relative_path_written_with_slashes(self):
        root = Path("C:\\Users\\someone\\project")
        raw = "Unsupported or mismatched task record: C:\\Users\\someone\\project\\.openguildkit\\tasks\\broken.json"
        text = document([make(message=raw)], root=root)["runs"][0]["results"][0]["message"]["text"]
        self.assertEqual(text, "Unsupported or mismatched task record: .openguildkit/tasks/broken.json")

    def test_the_form_of_the_folder_before_and_after_resolving_links_is_left_out(self):
        with tempfile.TemporaryDirectory(prefix="ogk-sarif-user-") as folder:
            root = Path(folder)
            for form in (str(root), str(root.resolve()), root.as_posix()):
                with self.subTest(form=form):
                    text = document([make(message=f"Read {form}/AGENTS.md first.")], root=root)["runs"][0]["results"][0]
                    self.assertEqual(text["message"]["text"], "Read AGENTS.md first.")

    def test_a_folder_at_the_end_of_a_sentence_is_left_out_and_a_longer_name_is_not_touched(self):
        root = Path("/tmp/ogk-sarif-root")
        for raw, expected in ((f"No profile in {root}.", "No profile in the project folder."),
                              (f"Cannot read {root}, {root}/a.md", "Cannot read the project folder, a.md"),
                              (f"{root}.json is another file", f"{root}.json is another file"),
                              (f"{root}-copy/a.md", f"{root}-copy/a.md"), (f"{root}x/a.md", f"{root}x/a.md")):
            with self.subTest(raw=raw):
                text = document([make(message=raw)], root=root)["runs"][0]["results"][0]["message"]["text"]
                self.assertEqual(text, expected)

    def test_the_home_folder_becomes_a_tilde(self):
        raw = f"The signers file {Path.home().as_posix()}/keys/allowed_signers is missing."
        text = document([make(message=raw)])["runs"][0]["results"][0]["message"]["text"]
        self.assertEqual(text, "The signers file ~/keys/allowed_signers is missing.")

    def test_the_fingerprint_does_not_depend_on_where_the_project_is(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            prints = []
            for folder in (first, second):
                raw = make(message=f"Unreadable: {Path(folder).resolve()}/AGENTS.md.")
                result = document([raw], root=Path(folder))
                prints.append(result["runs"][0]["results"][0]["partialFingerprints"])
            self.assertEqual(prints[0], prints[1])


if __name__ == "__main__":
    unittest.main()
