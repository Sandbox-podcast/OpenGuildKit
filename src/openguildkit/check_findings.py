"""What `check` and `guard --ci` report, as findings with a stable rule code, for their SARIF output (#420).

The commands keep printing what they printed. When a person asks for `--format sarif`, a `Report` gathers each problem
under the code of its rule, a level and the file it is about, and writes them with `sarif.to_sarif`. The codes are
the ones docs/sarif.md lists, one heading each; a code is part of what a code scanning alert is keyed on, so a rule is
added or retired there, never renamed.
"""

from .project import STATE_DIR, RuleError
from .sarif import finding, sarif_text, to_sarif

_RULES = {
    # check: the instructions, the host settings and the catalog.
    "instructions-drift": ("Instructions out of date", "The agent instructions no longer match the project profile."),
    "instructions-edited": ("Managed block edited by hand", "The managed block of AGENTS.md was edited by hand."),
    "instructions-ahead-of-lock": ("Instructions ahead of the catalog lock",
                                   "The instructions follow a newer catalog than the project's lock."),
    "host-settings-missing": ("Host settings missing",
                              "The host agent's settings do not enforce a rule the profile asks for."),
    "catalog-lock-stale": ("Catalog lock out of date", "The catalog lock does not match what the profile uses."),
    "catalog-update-pending": ("Catalog update pending",
                               "The installed catalog changes the rules of records the project has locked."),
    "source-undated": ("Source without a checked date", "A project record cites a source without a checked date."),
    "brain-replaced": ("Bundled brain replaced", "The project catalog replaces parts of a bundled brain."),
    "catalog-org-replaced": ("Organization record replaced",
                            "The project catalog replaces a record of the organization catalog and no person accepted it."),
    "approvals-not-signed": ("Approvals not signed",
                             "Approvals are only sealed locally, so nothing proves who gave them."),
    "task-unreadable": ("Task record unreadable", "A task record cannot be read."),
    "task-id-clash": ("Task ID shared", "A local task and the exported decision of another task share an ID."),
    "evidence-unshared": ("Evidence out of the repository",
                          "A task cites evidence a reviewer cannot open from the repository."),
    # check and guard --ci: the approvals.
    "decision-stale": ("Approval given under earlier rules", "An approval was given under rules that have changed since."),
    "decision-seal-invalid": ("Approval seal broken", "The approval of a task has no seal, or its seal does not match."),
    "decision-record-invalid": ("Decision record invalid",
                                "An exported decision record cannot be read or does not match what was approved."),
    "decision-unsigned": ("Decision not signed", "The project requires signed approvals and a decision is not signed."),
    "decision-signature-invalid": ("Decision signature invalid",
                                   "The signature of a decision cannot be verified against the allowed signers."),
    "decision-outside-history": ("Approval outside the history",
                                 "An approval was given on a revision that is not in the history of this change."),
    "decision-expired": ("Approval older than the limit",
                         "An approval is older than the project's approval.max_age_days and covers no more work."),
    "decision-withdrawn": ("Approval withdrawn", "The approval a decision record carries was withdrawn."),
    "decision-withdrawn-here": ("Withdrawal not exported",
                                "An approval was withdrawn in this copy and its exported record still says approved."),
    "decision-superseded": ("Task already approved", "A task already had another approval on the base revision."),
    "decision-record-unverified": ("Decision record not verified",
                                   "A decision record was exported before records carried a digest."),
    "decision-waiver-expired": ("Waiver expired", "A waiver that an approval rested on has expired."),
    # guard --ci: the change itself.
    "decision-missing": ("No valid decision for the change", "The changes come with no valid exported decision."),
    "decision-files-uncovered": ("Changed files without a decision",
                                 "Changed files are in no decision record of the change."),
    "decision-lane-outside": ("Short-lane decision outside its lane",
                              "A short-lane decision covers files outside its paths, or the base revision has no lane."),
    "decision-signed-late": ("Signature later than its commit",
                             "A new decision says it was signed after the commit that brings its record."),
    "decision-role-outside": ("Decision outside the role of a board",
                              ("A blocker or an approval is by someone outside the role the base revision gives the "
                               "board.")),
    "decision-requester-approved": ("Requester approved their own task",
                                    ("The base revision separates the requester from the approver, and a decision "
                                     "was approved by its requester.")),
    "decision-requester-missing": ("Decision without a requester",
                                   ("The base revision separates the requester from the approver, and a new decision "
                                    "names no requester.")),
    "evidence-journal-changed": ("Evidence journal changed",
                                 "A journal cited as evidence no longer matches the hash recorded with it."),
    "guard-frozen": ("Project frozen", "The base revision is frozen: no change is accepted but the one that lifts it."),
    "guard-no-base-profile": ("No profile on the base revision",
                              "The base revision has no OpenGuildKit profile, so nothing is enforced."),
    "guard-workflow-edited": ("Check workflow edited", "The change edits a workflow that runs this check."),
}
RULES = {code: {"name": name, "description": description, "help": f"sarif.md#{code}"}
         for code, (name, description) in _RULES.items()}

# The code of each kind of problem tasks.approval_problem names; the others of its kinds are notes, which check says
# and does not fail on.
APPROVAL_CODES = {
    "no-seal": "decision-seal-invalid",
    "invalid-seal": "decision-seal-invalid",
    "earlier-rules": "decision-stale",
    "approval-expired": "decision-expired",
    "unsigned": "decision-unsigned",
    "invalid-signature": "decision-signature-invalid",
    "outside-history": "decision-outside-history",
}
# What check prints about sharing and says to be a problem. The line that says it is normal (tasks absent from this
# copy, which every checkout of a repository that keeps the task records out of git shows) is not a finding.
SHARING_CODES = ("task-id-clash", "evidence-unshared")


class Report:
    """The findings of one run of a command, gathered only when `active`: a command that was not asked for SARIF
    pays nothing and prints what it printed."""

    def __init__(self, active: bool):
        self.active = active
        self.items: list[dict] = []

    def add(self, code: str, level: str, message: str, path: str | None = None) -> None:
        if self.active:
            self.items.append(finding(code, level, message, path))

    def tasks(self, rows: list[dict]) -> None:
        """The tasks of `list_tasks` whose approval no longer holds, or that cannot be read."""
        for row in rows:
            path = f"{STATE_DIR}/tasks/{row['id']}.json"
            if row["status"] == "unreadable":
                self.add("task-unreadable", "error", f"{row['id']}: {row['next']}", path)
            elif row.get("severity") == "error":
                self.add(APPROVAL_CODES[row["approval_problem"]], "error", f"{row['id']}: {row['next']}", path)

    def records(self, rows: list[dict]) -> None:
        """The exported decisions of `exported_decisions` whose record does not hold."""
        for row in rows:
            problem = row["problem"]
            if problem and problem["severity"] == "error":
                self.add(problem["code"], "error", problem["message"], row["path"])

    def boards(self, replaced: dict[str, str]) -> None:
        """Bundled brains the project completes, by ID, and organization records it replaces, by collection/id."""
        for key, message in replaced.items():
            code, path = ("catalog-org-replaced", key) if "/" in key else ("brain-replaced", f"boards/{key}")
            self.add(code, "warning", message, f"{STATE_DIR}/catalog/{path}.json")

    def sharing(self, issues: list[tuple[str, str, str | None]]) -> None:
        for kind, message, path in issues:
            if kind in SHARING_CODES:
                self.add(kind, "warning", message, path)

    def blocked(self, error: RuleError) -> None:
        """The problem that stopped `check`: an error on each file it names, or on the profile when it names none."""
        if error.code is not None:
            for path in error.files or (None,):
                self.add(error.code, "error", str(error), path)

    def guard(self, items: list[dict], mode: str) -> None:
        """The findings of `ci_guard`. A problem stops the job only when the guard of the base revision enforces; in
        another mode it is flagged, not blocking, which is what a warning says."""
        for item in items:
            level = "warning" if item["level"] == "error" and mode != "enforce" else item["level"]
            self.add(item["code"], level, item["message"], item["path"])

    def text(self, root) -> str:
        """The SARIF document, in the bytes `sarif_text` writes."""
        from .lock import package_version

        return sarif_text(to_sarif(self.items, rules=RULES, tool_version=package_version(), root=root))
