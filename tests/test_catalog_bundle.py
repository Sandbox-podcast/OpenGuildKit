"""The bundled catalog in one file: scripts/build_catalog_bundle.py writes registry/catalog.bundle.json before the
wheel is built, and a process reads it instead of the record files while they keep the names and sizes it lists."""

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from openguildkit import catalog
from tests import support

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "src" / "openguildkit" / "registry"
spec = importlib.util.spec_from_file_location("build_catalog_bundle", REPO / "scripts" / "build_catalog_bundle.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def record_texts(records: dict) -> dict:
    """Each record's JSON text, by collection and ID: equal only when the fields are in the same order too."""
    return {collection: {record_id: json.dumps(record, ensure_ascii=False) for record_id, record in entries.items()}
            for collection, entries in records.items()}


class CatalogBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()
        self.registry = self.folder / "registry"
        for collection in catalog.COLLECTION_FIELDS:
            shutil.copytree(REGISTRY / collection, self.registry / collection)
        self.bundle = self.registry / catalog.BUNDLE_FILE

    @contextlib.contextmanager
    def fresh(self):
        """The copy as the bundled catalog, read as a new process reads it; yields the mock that counts the record
        folders read one file at a time."""
        with patch("openguildkit.catalog.registry_folder", return_value=self.registry), \
                patch("openguildkit.catalog_queries.registry_folder", return_value=self.registry), \
                patch.dict(catalog._BUNDLED, clear=True), patch.dict(catalog._MERGED, clear=True), \
                patch("openguildkit.catalog._read_records", wraps=catalog._read_records) as folders:
            yield folders

    def test_the_bundle_holds_the_records_the_loader_validates(self):
        """Issue #533: the bundle must hold what the record files give once read and validated, or it misleads."""
        expected = record_texts(catalog._read_bundled(self.registry))
        builder.write_bundle(self.registry)
        first = self.bundle.read_bytes()
        builder.write_bundle(self.registry)
        self.assertEqual(self.bundle.read_bytes(), first, "two builds of the same files differ")
        with self.fresh() as folders:
            bundled = catalog._read_bundled(self.registry)
        self.assertEqual(folders.call_count, 0, "the bundle was not read")
        self.assertEqual(record_texts(bundled), expected)
        built = REGISTRY / catalog.BUNDLE_FILE
        if built.is_file():
            self.assertEqual(built.read_bytes(), builder.bundle_text(REGISTRY).encode("utf-8"),
                             f"{built} is out of date: run python scripts/build_catalog_bundle.py or delete it")

    def test_a_fresh_process_opens_one_file_of_the_bundled_catalog(self):
        """Issue #533: a fresh process opened and validated the 289 record files of the bundled catalog."""
        builder.write_bundle(self.registry)
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from openguildkit import catalog\n"
            "registry = Path(sys.argv[1])\n"
            "catalog.registry_folder = lambda: registry\n"
            "opened = []\n"
            "sys.addaudithook(lambda event, args: event == 'open' and opened.append(str(args[0])))\n"
            "catalog.load_catalog()\n"
            "print(json.dumps([name for name in opened if name.startswith(str(registry))]))\n"
        )
        environment = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        done = subprocess.run([sys.executable, "-c", script, str(self.registry)], capture_output=True, text=True,
                              encoding="utf-8", env=environment, timeout=60, check=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [str(self.bundle)])

    def test_record_files_changed_since_the_bundle_are_read_again(self):
        """Issue #533: a record file renamed, added or resized since the build must not be hidden by the bundle."""
        builder.write_bundle(self.registry)
        with self.fresh() as folders:
            catalog.load_catalog()
        self.assertEqual(folders.call_count, 0)

        path = self.registry / "packs" / "python.json"
        pack = json.loads(path.read_text(encoding="utf-8"))
        pack["title"] += " (edited)"
        path.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        sector = json.loads((self.registry / "sectors" / "healthcare.json").read_text(encoding="utf-8"))
        sector["id"] = "added-sector"
        (self.registry / "sectors" / "added-sector.json").write_text(json.dumps(sector), encoding="utf-8")
        with self.fresh() as folders:
            loaded = catalog.load_catalog()
        self.assertEqual(folders.call_count, len(catalog.COLLECTION_FIELDS))
        self.assertTrue(loaded["packs"]["python"]["title"].endswith(" (edited)"))
        self.assertIn("added-sector", loaded["sectors"])

        self.bundle.write_text("{", encoding="utf-8")
        with self.fresh() as folders:
            self.assertIn("added-sector", catalog.load_catalog()["sectors"])
        self.assertEqual(folders.call_count, len(catalog.COLLECTION_FIELDS))

    def run_cli(self, root: Path, *arguments) -> str:
        return support.run_cli(root, *arguments).stdout

    def test_catalog_json_and_a_new_lock_are_the_same_with_and_without_the_bundle(self):
        """Issue #533: reading the bundle must not change a byte of what a command prints or locks."""
        answers = self.folder / "answers.json"
        answers.write_text(json.dumps({"name": "Bundle check", "stack": ["Python"], "personal_data": "no"}),
                           encoding="utf-8")
        root = self.folder / "project"
        results = []
        for build in (False, True):
            if build:
                builder.write_bundle(self.registry)
            shutil.rmtree(root, ignore_errors=True)
            root.mkdir()
            with self.fresh() as folders:
                self.run_cli(root, "init", "--answers", answers)
                listed = self.run_cli(root, "catalog", "--json")
            self.assertEqual(folders.call_count, 0 if build else len(catalog.COLLECTION_FIELDS))
            results.append((listed, (root / ".openguildkit" / "catalog.lock.json").read_bytes()))
        self.assertEqual(results[1], results[0])

    def test_the_bundle_ships_in_the_wheel_and_stays_out_of_git(self):
        """Issue #533: the bundle is built for the wheel, never committed."""
        package_data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]
        self.assertIn(f"registry/{catalog.BUNDLE_FILE}", package_data["package-data"]["openguildkit"])
        ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(f"/src/openguildkit/registry/{catalog.BUNDLE_FILE}", ignored)


if __name__ == "__main__":
    unittest.main()
