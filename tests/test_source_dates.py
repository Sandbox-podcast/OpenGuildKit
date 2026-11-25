"""Every bundled source carries the day its page was last checked; projects, the link report and update show it."""

import contextlib
import copy
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from openguildkit import catalog as catalog_module
from openguildkit import clock
from openguildkit.catalog import CatalogError, validate_entry, load_catalog
from openguildkit.deliverables import _validate as validate_deliverable, load_deliverables
from openguildkit.lock import read_lock
from openguildkit.project import profile_fingerprint
from openguildkit.references import _validate_family, load_references
from openguildkit.storage import write_json
from openguildkit.tools import load_tools

from tests.support import CapturedCli, run_cli

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "src" / "openguildkit" / "registry"
SOURCE_FOLDERS = ("packs", "boards", "patterns", "sectors", "references", "deliverables")
spec = importlib.util.spec_from_file_location("check_links_dates", ROOT / "scripts" / "check_links.py")
check_links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_links)

PACK = {
    "id": "team-review", "title": "Team review", "version": "1.0.0",
    "description": "Ask a second person to read each change.",
    "rules": [{"id": "second-reader", "instruction": "Name a second reader.", "verification": "Read the change record."}],
    "sources": [{"title": "Example handbook", "url": "https://handbook.example.test/review"}],
}


def bundled_sources():
    """Each source of the bundled registry, with the file and the record that cite it."""
    catalog = load_catalog()
    for collection in ("packs", "boards", "patterns", "sectors"):
        for record in catalog[collection].values():
            for source in record["sources"]:
                yield f"{collection}/{record['id']}", source
    for family in load_references().values():
        for record in family["references"]:
            for source in record["sources"]:
                yield f"references/{record['id']}", source
    for record in load_deliverables(catalog).values():
        for source in record["sources"]:
            yield f"deliverables/{record['id']}", source


def bundled_dates():
    """Each date of the bundled catalog: the checked day of every source, the verified and reviewed days of every
    tool server."""
    for record, source in bundled_sources():
        yield f"{record}: {source['url']}", source["checked"]
    for tool in load_tools().values():
        for server in tool["servers"]:
            for field in ("verified", "reviewed"):
                if field in server:
                    yield f"tools/{tool['id']}/{server['id']} {field}", server[field]


def dates_after(day: date) -> list[str]:
    return [f"{where} {value}" for where, value in bundled_dates() if date.fromisoformat(value) > day]


class BundledSourceDateTests(unittest.TestCase):
    def test_no_bundled_date_is_after_the_day_of_the_test(self):
        """A page cannot have been read in the future: such a date is a typo, and update would announce it."""
        self.assertEqual(dates_after(clock.real_today()), [])
        latest = max(date.fromisoformat(value) for _, value in bundled_dates())
        self.assertTrue(dates_after(latest - timedelta(days=1)), "the check sees the latest bundled date")

    def test_the_loaders_refuse_a_date_in_the_future(self):
        """One day of margin for time zones, as for the other dates a person writes; the test above has none."""
        tomorrow, later = (clock.real_today() + timedelta(days=days) for days in (1, 2))
        for bundled in (True, False):
            record = copy.deepcopy(PACK)
            record["sources"][0]["checked"] = later.isoformat()
            with self.subTest(bundled=bundled), self.assertRaisesRegex(CatalogError, "in the future"):
                validate_entry("packs", record, bundled=bundled)
            record["sources"][0]["checked"] = tomorrow.isoformat()
            validate_entry("packs", record, bundled=bundled)
        family = {"id": "legal", "title": "Legal", "references": [copy.deepcopy(load_references()["legal"]["references"][0])]}
        family["references"][0]["sources"][0]["checked"] = "2099-01-01"
        with self.assertRaisesRegex(CatalogError, "in the future"):
            _validate_family(family, "legal.json", bundled=True)

    def test_every_bundled_source_has_a_checked_date(self):
        undated, count = [], 0
        for record, source in bundled_sources():
            count += 1
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", source.get("checked", "")):
                undated.append(f"{record}: {source['url']}")
            else:
                date.fromisoformat(source["checked"])
        self.assertGreater(count, 900)
        self.assertEqual(undated, [])

    def test_each_stack_pattern_and_its_packs_cite_dated_sources(self):
        catalog = load_catalog()
        stacks = [pattern for pattern in catalog["patterns"].values() if pattern.get("match", {}).get("stack")]
        self.assertIn("django", {pattern["id"] for pattern in stacks})
        for pattern in stacks:
            records = [pattern, *(catalog["packs"][pack_id] for pack_id in pattern["packs"])]
            for record in records:
                for source in record["sources"]:
                    with self.subTest(pattern=pattern["id"], record=record["id"]):
                        date.fromisoformat(source["checked"])

    def test_checked_follows_url_in_every_record_file(self):
        """The layout keeps a stamping diff to the date line and the comma after the URL."""
        misplaced = []
        for folder in SOURCE_FOLDERS:
            for path in sorted((REGISTRY / folder).glob("*.json")):
                text = path.read_text(encoding="utf-8")
                for sources in check_links._source_lists(json.loads(text)):
                    for source in sources:
                        keys = list(source)
                        if keys.index("checked") != keys.index("url") + 1:
                            misplaced.append(f"{path.name}: {source['url']}")
                self.assertEqual(json.dumps(json.loads(text), ensure_ascii=False, indent=2) + "\n", text, path.name)
        self.assertEqual(misplaced, [])

    def test_the_loader_refuses_a_bundled_source_without_a_date(self):
        with tempfile.TemporaryDirectory() as folder:
            registry = Path(folder) / "registry"
            shutil.copytree(REGISTRY, registry)
            path = registry / "packs" / "gdpr.json"
            pack = json.loads(path.read_text(encoding="utf-8"))
            del pack["sources"][0]["checked"]
            write_json(path, pack)
            with self.assertRaisesRegex(CatalogError, r"gdpr\.json: sources\[0\]\.checked is missing: open the page"):
                catalog_module._read_bundled(registry)

    def test_each_loader_requires_the_date_for_bundled_records_only(self):
        undated = copy.deepcopy(PACK)
        with self.assertRaisesRegex(CatalogError, "checked is missing"):
            validate_entry("packs", undated, bundled=True)
        validate_entry("packs", undated)
        family = {"id": "legal", "title": "Legal", "references": [copy.deepcopy(
            load_references()["legal"]["references"][0])]}
        del family["references"][0]["sources"][0]["checked"]
        with self.assertRaisesRegex(CatalogError, "checked is missing"):
            _validate_family(family, "legal.json", bundled=True)
        _validate_family(family, "legal.json")
        catalog = load_catalog()
        deliverable = copy.deepcopy(next(iter(load_deliverables(catalog).values())))
        del deliverable["sources"][0]["checked"]
        with self.assertRaisesRegex(CatalogError, "checked is missing"):
            validate_deliverable(deliverable, catalog, True)
        validate_deliverable(deliverable, catalog)

    def test_a_malformed_date_is_refused_in_any_catalog(self):
        for value in ("2026-13-01", "21/11/2026", "2026-11-21T10:00", 20261121, ""):
            record = copy.deepcopy(PACK)
            record["sources"][0]["checked"] = value
            for bundled in (True, False):
                with self.subTest(value=value, bundled=bundled), self.assertRaisesRegex(CatalogError, "YYYY-MM-DD"):
                    validate_entry("packs", record, bundled=bundled)


class ProjectSourceDateTests(CapturedCli, unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        write_json(self.root / "p.json", {"personal_data": "no", "name": "Portal", "stack": ["Python"]})
        self.cli("init", "--answers", self.root / "p.json")
        self.state = self.root / ".openguildkit"

    def test_an_undated_project_source_loads_and_check_names_its_record(self):
        write_json(self.state / "catalog" / "packs" / "team-review.json", PACK)
        family = {"id": "team", "title": "Team references", "references": [{
            "id": "team-handbook", "title": "Team handbook", "category": "Process", "kind": "référentiel",
            "summary": "How the team reviews changes.", "applies_when": "A change needs a reviewer.",
            "sources": [{"title": "Handbook", "url": "https://handbook.example.test/"}],
        }]}
        write_json(self.state / "catalog" / "references" / "team.json", family)
        self.assertIn("team-review", load_catalog(self.state / "catalog")["packs"])
        out, err = self.cli("check")
        self.assertEqual(out.strip(), "OpenGuildKit instructions match the project profile.")
        self.assertIn("date the sources of 2 project records: packs/team-review, references/team-handbook.", err)
        self.assertIn('add "checked": "YYYY-MM-DD" after its url', err)
        for path, data in ((self.state / "catalog" / "packs" / "team-review.json", PACK),
                           (self.state / "catalog" / "references" / "team.json", family)):
            dated = json.loads(json.dumps(data).replace('"url": "https://handbook.example.test/', '"checked": "2026-11-21", "url": "https://handbook.example.test/'))
            write_json(path, dated)
        out, err = self.cli("check")
        self.assertNotIn("date the sources", err)

    def test_check_refuses_a_project_reference_that_names_an_unknown_pack_or_brain(self):
        """docs/catalog-format.md promises it: the references a project adds name packs and brains that exist."""
        record = {"id": "team-change-record", "title": "Change record", "category": "Livraison", "kind": "pratique",
                  "summary": "Trace les changements.", "applies_when": "Pour chaque mise en production.",
                  "brains": ["no-such-brain"], "packs": ["no-such-pack"],
                  "sources": [{"title": "Handbook", "url": "https://handbook.example.test/"}]}
        path = self.state / "catalog" / "references" / "team-practices.json"
        write_json(path, {"id": "team-practices", "title": "Team practices", "references": [record]})
        out, err = self.cli("check", code=1)
        self.assertNotIn("Traceback", err)
        self.assertRegex(err, r"Reference 'team-change-record' names .*unknown packs: no-such-pack")
        self.assertIn("unknown brains: no-such-brain", err)
        with self.assertRaisesRegex(CatalogError, "unknown packs: no-such-pack"):
            load_references(path.parent, catalog=load_catalog(self.state / "catalog"))
        # The reference library and the consultation refuse it too, with the same message, as for any other error of
        # the project's catalog.
        examples = ROOT / "examples" / "request-status"
        self.cli("task", "new", "--file", examples / "brief.md", "--id", "status")
        refused = [("references",), ("references", "--id", "team-change-record"), ("references", "--json"),
                   ("brains",), ("task", "consult", "status", "--answers", examples / "answers.json")]
        for arguments in refused:
            with self.subTest(command=arguments[:2]):
                out, err = self.cli(*arguments, code=1)
                self.assertIn("Reference 'team-change-record' names unknown brains: no-such-brain and unknown packs: "
                              "no-such-pack", err)
                self.assertNotIn("Traceback", err)
                self.assertNotIn("team-change-record", out)
        write_json(path, {"id": "team-practices", "title": "Team practices",
                          "references": [{**record, "brains": ["security"], "packs": ["gdpr"]}]})
        self.cli("check")
        self.assertIn("team-change-record", self.cli("references", "--id", "team-change-record")[0])
        self.cli("task", "consult", "status", "--answers", examples / "answers.json")

    def test_a_project_reference_may_name_a_pack_the_lock_keeps_after_a_release_drops_it(self):
        from tests.test_upgrades import ANSWERS, release_without_playwright

        from openguildkit import lock

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_json(root / "answers.json", ANSWERS)
            run_cli(root, "init", "--answers", root / "answers.json")
            record = {"id": "team-e2e", "title": "End-to-end checks", "category": "Tests", "kind": "pratique",
                      "summary": "Teste les parcours.", "applies_when": "Pour chaque parcours.", "packs": ["playwright"],
                      "sources": [{"title": "Handbook", "url": "https://handbook.example.test/"}]}
            write_json(root / ".openguildkit" / "catalog" / "references" / "team.json",
                       {"id": "team", "title": "Team", "references": [record]})
            with patch.object(lock, "load_catalog", release_without_playwright):
                run_cli(root, "check")
                write_json(root / ".openguildkit" / "catalog" / "references" / "team.json",
                           {"id": "team", "title": "Team", "references": [{**record, "packs": ["no-such-pack"]}]})
                self.assertIn("unknown packs: no-such-pack", run_cli(root, "check", expect=1).stderr)

    def test_update_prints_the_catalog_date_and_the_changed_count_before_the_changes(self):
        latest = max(source["checked"] for _, source in bundled_sources())
        out, _ = self.cli("update")
        self.assertEqual(out.splitlines()[0], f"Installed catalog: sources checked up to {latest}. 0 records changed since the project's lock.")
        lock_file = self.state / "catalog.lock.json"
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
        records = 0
        for entries in lock["records"].values():
            for record in entries.values():
                records += bool(record["sources"])
                for source in record["sources"]:
                    source.pop("checked", None)
        write_json(lock_file, lock)
        self.assertIsNotNone(read_lock(self.state), "a lock written before source dates still reads")
        out, _ = self.cli("update")
        lines = out.splitlines()
        self.assertEqual(lines[0], f"Installed catalog: sources checked up to {latest}. {records} records changed since the project's lock.")
        self.assertTrue(lines[1].startswith("~ "))
        self.assertRegex(out, r"    ~ \d+ sources? checked again, latest \d{4}-\d{2}-\d{2}")
        payload = json.loads(self.cli("update", "--json")[0])
        self.assertEqual(payload["catalog_date"], latest)
        self.assertTrue(all(change["sources"]["redated"] for change in payload["changes"]))

    def test_a_date_refresh_does_not_make_consulted_tasks_stale(self):
        catalog = load_catalog()
        profile = json.loads((self.state / "project.json").read_text(encoding="utf-8"))
        undated = json.loads(json.dumps(catalog))
        for collection in ("packs", "boards", "sectors", "patterns"):
            for record in undated[collection].values():
                for source in record["sources"]:
                    source.pop("checked")
        self.assertEqual(profile_fingerprint(profile, catalog), profile_fingerprint(profile, undated))

    def test_reference_details_show_when_each_source_was_checked(self):
        out, _ = self.cli("references", "--id", "rgpd")
        self.assertRegex(out, r"- .+: https://eur-lex\.europa\.eu/\S+ \(checked \d{4}-\d{2}-\d{2}\)")


class LinkReportAgeTests(unittest.TestCase):
    CITATIONS = {
        "https://old.example.test/": [{"collection": "packs", "id": "a", "checked": "2026-01-02"},
                                      {"collection": "references", "id": "b", "checked": "2026-11-01"}],
        "https://new.example.test/": [{"collection": "packs", "id": "c", "checked": "2026-11-01"}],
        "https://tool.example.test/": [{"collection": "tools", "id": "d"}],
    }

    def test_sources_older_than_the_age_are_listed_with_the_records_that_cite_them(self):
        stale = check_links.stale_sources(self.CITATIONS, date(2026, 11, 21), 180)
        self.assertEqual(stale, [{"url": "https://old.example.test/", "checked": "2026-01-02",
                                  "cited_by": [{"collection": "packs", "id": "a", "checked": "2026-01-02"}]}])
        self.assertEqual(len(check_links.stale_sources(self.CITATIONS, date(2026, 11, 21), 10)), 2)
        # The report is dated by the stamping clock: fix it, so the ages do not depend on the day the test runs.
        with patch.dict(os.environ, {"SOURCE_DATE_EPOCH": "1795219200"}):  # 2026-11-21
            report = check_links.check(self.CITATIONS, lambda url: {"status": 200, "final_url": url}, workers=2, max_age=180)
        self.assertEqual(report["date"], "2026-11-21")
        self.assertEqual(report["max_age_days"], 180)
        markdown = check_links.render_markdown(report)
        self.assertIn("## Checked more than 180 days ago (1)", markdown)
        self.assertIn("- https://old.example.test/ (checked 2026-01-02)\n  - packs/a, checked 2026-01-02", markdown)

    def test_the_bundled_citations_carry_each_source_date_and_the_age_is_an_option(self):
        catalog = load_catalog()
        citations = check_links.collect_citations(catalog, load_references(), None, load_deliverables(catalog))
        gdpr = [entry for entry in citations["https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra"]]
        self.assertTrue(all("checked" in entry for entry in gdpr))
        self.assertIn("deliverables", {entry["collection"] for entries in citations.values() for entry in entries})
        with tempfile.TemporaryDirectory() as folder:
            def fake_fetch(url, timeout):
                return {"status": 200, "final_url": url}
            original = check_links.fetch
            check_links.fetch = fake_fetch
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(check_links.main(["--out", folder, "--max-age", "0", "--workers", "4"]), 0)
            finally:
                check_links.fetch = original
            self.assertIn("checked more than 0 days ago", out.getvalue())
            report = json.loads(next(Path(folder).glob("*.json")).read_text(encoding="utf-8"))
            self.assertEqual(report["max_age_days"], 0)


class StampTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.registry = Path(temporary.name)
        for folder in SOURCE_FOLDERS:
            (self.registry / folder).mkdir()
        self.pack = self.registry / "packs" / "team-review.json"
        pack = copy.deepcopy(PACK)
        pack["sources"] = [
            {"title": "Answers", "url": "https://up.example.test/"},
            {"title": "Moved", "url": "https://moved.example.test/"},
            {"title": "Refuses scripts", "url": "https://refuses.example.test/"},
            {"title": "Dated before", "url": "https://dated.example.test/", "checked": "2026-06-01"},
        ]
        self.pack.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.report = {"date": "2026-11-21", "links": [
            {"url": "https://up.example.test/", "category": "available", "status": 200},
            {"url": "https://moved.example.test/", "category": "redirected", "status": 200},
            {"url": "https://refuses.example.test/", "category": "to-recheck", "status": 403},
            {"url": "https://dated.example.test/", "category": "dead", "status": 404},
        ]}
        self.asked = []

    def introduced(self, url):
        self.asked.append(url)
        return {"https://refuses.example.test/": "2026-11-20"}.get(url)

    def test_answered_pages_get_the_report_date_and_others_their_history_date(self):
        result = check_links.stamp(self.report, self.introduced, self.registry)
        sources = json.loads(self.pack.read_text(encoding="utf-8"))["sources"]
        self.assertEqual([source["checked"] for source in sources], ["2026-11-21", "2026-11-21", "2026-11-20", "2026-06-01"])
        self.assertEqual(list(sources[0]), ["title", "url", "checked"])
        self.assertEqual(result["answered"], ["https://moved.example.test/", "https://up.example.test/"])
        self.assertEqual(result["unanswered"], {"https://dated.example.test/": "2026-06-01",
                                                "https://refuses.example.test/": "2026-11-20"})
        self.assertEqual(result["files"], ["packs/team-review.json"])
        text = self.pack.read_text(encoding="utf-8")
        again = check_links.stamp(self.report, self.introduced, self.registry)
        self.assertEqual(again["files"], [])
        self.assertEqual(self.pack.read_text(encoding="utf-8"), text)

    def test_a_url_outside_the_history_is_refused_and_a_shallow_clone_too(self):
        with self.assertRaisesRegex(ValueError, "refuses.example.test/ is not in the Git history yet: commit"):
            check_links.stamp(self.report, lambda url: None, self.registry)

        def shallow(arguments, root):
            return "true\n"
        with self.assertRaisesRegex(ValueError, "shallow"):
            check_links.history_dates(self.registry, shallow)

    def test_the_history_date_is_the_oldest_commit_that_added_the_url(self):
        calls = []

        def git(arguments, root):
            calls.append(arguments)
            return "false\n" if arguments[0] == "rev-parse" else "2026-11-21\n2026-11-20\n"
        introduced = check_links.history_dates(self.registry, git)
        self.assertEqual(introduced("https://refuses.example.test/"), "2026-11-20")
        self.assertEqual(calls[1], ["log", "--format=%ad", "--date=short", "-S", "https://refuses.example.test/"])

    def test_the_repository_history_dates_a_bundled_url(self):
        if not (ROOT / ".git").exists():
            self.skipTest("Needs the Git history of the repository.")
        try:
            introduced = check_links.history_dates()
        except ValueError as error:
            self.skipTest(f"Needs the full Git history: {error}")
        self.assertRegex(introduced("https://eur-lex.europa.eu/eli/reg/2016/679/oj/fra") or "", r"^\d{4}-\d{2}-\d{2}$")


if __name__ == "__main__":
    unittest.main()
