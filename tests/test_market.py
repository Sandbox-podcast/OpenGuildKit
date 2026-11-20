import contextlib
import copy
import io
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from openguildkit.cli import main
from openguildkit.market import dossier_gaps, due_sources, validate_dossier
from openguildkit.storage import write_json

REPO = Path(__file__).resolve().parents[1]
DOSSIER = json.loads((REPO / "examples" / "market-dossier" / "support-portals.json").read_text(encoding="utf-8"))
EXAMPLE = REPO / "examples" / "request-status"


class MarketDossierTests(unittest.TestCase):
    def test_gaps_show_missing_kinds_observations_age_and_local_policy(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        gaps = dossier_gaps(dossier, "local-only", today=date(2027, 6, 1))
        self.assertIn("Prices of direct competitors for the portal option.", gaps)
        self.assertTrue(any("days old" in gap for gap in gaps))
        self.assertTrue(any("local-only" in gap for gap in gaps))
        dossier["competitors"].append({"id": "vendor-b", "name": "Vendor B", "kind": "direct"})
        self.assertIn("No dated observation for Vendor B.", dossier_gaps(dossier, "public-sources", today=date(2026, 11, 20)))

    def test_watched_sources_come_due_and_can_be_paused(self):
        dossier = validate_dossier(copy.deepcopy(DOSSIER), "support-portals")
        self.assertEqual(len(due_sources(dossier, today=date(2026, 11, 20))), 1)
        dossier["watch"]["sources"][0]["last_checked"] = "2026-11-15"
        self.assertEqual(due_sources(dossier, today=date(2026, 11, 20)), [])
        self.assertEqual(len(due_sources(dossier, today=date(2026, 12, 20))), 1)
        dossier["watch"]["paused"] = True
        self.assertEqual(due_sources(dossier, today=date(2026, 12, 20)), [])

    def test_invalid_dossiers_are_refused(self):
        broken = copy.deepcopy(DOSSIER)
        broken["observations"][0]["source"]["date"] = "last week"
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            validate_dossier(broken, "support-portals")
        broken = copy.deepcopy(DOSSIER)
        broken["watch"]["sources"][0]["url"] = "http://example.com"
        with self.assertRaisesRegex(ValueError, "https"):
            validate_dossier(broken, "support-portals")

    def test_boards_cite_dossier_observations_in_a_consultation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def cli(*args, code=0):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    self.assertEqual(main(["--project", str(root), *map(str, args)]), code, err.getvalue())
                return out.getvalue(), err.getvalue()

            write_json(root / "profile.json", json.loads((EXAMPLE / "profile.json").read_text()))
            cli("init", "--answers", root / "profile.json")
            (root / ".openguildkit" / "market").mkdir()
            shutil.copy(REPO / "examples" / "market-dossier" / "support-portals.json", root / ".openguildkit" / "market")
            self.assertIn("local-only", cli("market", "check", "support-portals")[0])
            cli("task", "new", "--file", EXAMPLE / "brief.md", "--id", "status")
            consultation, _ = cli("task", "consult", "status", "--answers", EXAMPLE / "answers.json", "--market", "support-portals")
            self.assertIn('"age_days"', consultation)
            template = json.loads(cli("task", "template", "status")[0])
            review = {"consultation_id": template["consultation_id"], **json.loads((EXAMPLE / "review.json").read_text())}
            marketing = next(entry for entry in review["boards"] if entry["id"] == "marketing")
            marketing["evidence"].append({"source": "public", "ref": "market:support-portals/unknown", "supports": "x"})
            write_json(root / "review.json", review)
            _, error = cli("task", "review", "status", "--file", root / "review.json", code=1)
            self.assertIn("not an observation or change", error)
            marketing["evidence"][-1] = {"source": "public", "ref": "market:support-portals/a-status-page",
                                         "supports": "A direct competitor shows a status and a response date."}
            write_json(root / "review.json", review)
            cli("task", "review", "status", "--file", root / "review.json")
            record = json.loads(cli("task", "show", "status")[0])
            self.assertEqual(record["status"], "reviewed")


if __name__ == "__main__":
    unittest.main()
