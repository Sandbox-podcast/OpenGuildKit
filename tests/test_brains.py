import unittest

from openguildkit.catalog import load_catalog
from openguildkit.workflow import challenge_report, consult, handoff, validate_review


class BrainReviewTests(unittest.TestCase):
    def setUp(self):
        profile = {"name": "Support portal", "sector": "general", "packs": [], "boards": ["security"]}
        task = {
            "id": "request-access",
            "brief": "Allow signed-in users to view their support requests.",
            "answers": {"kind": "feature", "surface": "customer", "data": "personal", "research": "local"},
        }
        self.consultation = consult(profile, load_catalog(), task)
        self.review = self.consultation["review_template"].copy()
        self.review["summary"] = "Review ownership before exposing requests."
        self.entry = self.review["boards"][0].copy()
        self.review["boards"] = [self.entry]
        self.entry["recommendation"] = "Use server-side ownership checks."
        self.entry["evidence"] = [{"source": "project-file", "ref": "docs/permissions.md", "supports": "Documented roles."}]
        self.challenge = self.entry["challenge"].copy()
        self.entry["challenge"] = self.challenge
        self.challenge.update(
            specialists=[
                {**lens, "finding": "Review the ownership model.", "basis": "observed", "evidence_refs": [1]}
                for lens in self.challenge["specialists"]
            ],
            verdict="proceed",
            confidence="medium",
            alternative="Show a generic contact link until ownership is verified.",
            failure_mode="An account can see a request that belongs to someone else.",
            verification="Verify own-request and other-request behavior with synthetic users.",
        )

    def test_challenge_reports_verdicts_and_checks(self):
        review = validate_review(self.consultation, self.review)
        result = challenge_report({"consultation": self.consultation, "review": review})
        self.assertIn('"proceed"', result)
        self.assertIn("generic contact link", result)
        self.assertIn("synthetic users", result)

    def test_all_specialist_lenses_must_return_a_finding(self):
        self.challenge["specialists"].pop()
        with self.assertRaisesRegex(ValueError, "specialist findings are missing"):
            validate_review(self.consultation, self.review)

    def test_observed_findings_need_a_citation(self):
        self.challenge["specialists"][0]["evidence_refs"] = []
        with self.assertRaisesRegex(ValueError, "needs an evidence reference"):
            validate_review(self.consultation, self.review)

    def test_proceed_cannot_be_justified_with_assumptions_alone(self):
        for lens in self.challenge["specialists"]:
            lens.update(basis="assumption", evidence_refs=[])
        with self.assertRaisesRegex(ValueError, "observed finding"):
            validate_review(self.consultation, self.review)

    def test_decision_task_handoff_is_a_record_without_implementation_order(self):
        review = validate_review(self.consultation, self.review)
        task = {
            "id": "request-access", "status": "approved", "consultation": self.consultation, "review": review,
            "decision": {"by": "Owner", "reason": "Agreed"},
            "answers": {"kind": "decision", "surface": "customer", "data": "personal", "research": "local"},
        }
        record = handoff(task)
        self.assertIn("# Approved decision record", record)
        self.assertNotIn("Implement the approved scope", record)
        task["answers"]["kind"] = "feature"
        self.assertIn("# Approved task handoff", handoff(task))

    def test_evidence_records_its_origin_and_what_it_supports(self):
        self.entry["evidence"] = [{"source": "public", "ref": "https://example.org/guide", "supports": "A guide."}]
        with self.assertRaisesRegex(ValueError, "needs the date"):
            validate_review(self.consultation, self.review)
        self.entry["evidence"][0]["date"] = "2026-11-20"
        validate_review(self.consultation, self.review)
        self.entry["evidence"] = ["docs/permissions.md"]
        with self.assertRaisesRegex(ValueError, "source, ref and supports"):
            validate_review(self.consultation, self.review)
        self.entry["evidence"] = [{"source": "project-file", "ref": "docs/a.md", "supports": "x", "revision": "not-a-sha"}]
        with self.assertRaisesRegex(ValueError, "commit SHA"):
            validate_review(self.consultation, self.review)

    def test_the_requesters_words_alone_cannot_justify_proceeding(self):
        self.entry["evidence"] = [{"source": "requester", "ref": "brief", "supports": "Users want to see requests."}]
        with self.assertRaisesRegex(ValueError, "requester's own words"):
            validate_review(self.consultation, self.review)
        self.challenge["verdict"] = "revise"
        validate_review(self.consultation, self.review)

    def test_the_decision_brief_shows_the_decisive_evidence(self):
        review = validate_review(self.consultation, self.review)
        report = challenge_report({"consultation": self.consultation, "review": review})
        self.assertIn('"decisive_evidence"', report)
        self.assertIn("docs/permissions.md", report)

    def test_reviews_recorded_before_structured_evidence_stay_readable(self):
        self.consultation.pop("evidence_format")
        self.entry["evidence"] = ["Documented roles in docs/permissions.md."]
        self.assertEqual(validate_review(self.consultation, self.review)["boards"][0]["evidence"], self.entry["evidence"])

    def test_previous_review_format_still_validates_against_its_template(self):
        self.entry.pop("challenge")
        self.consultation["review_template"]["boards"][0].pop("challenge")
        self.assertEqual(validate_review(self.consultation, self.review)["boards"][0], self.entry)
