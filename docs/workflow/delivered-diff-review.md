# Delivered diff review

For: the person who reviews a delivered change, and the agent that prepares the review.
A part of the [task workflow](../workflow.md).

The boards review the task before the change; they can also read the change itself.
After `task verify` or `task result` recorded the delivered revision, and before `task complete`, the agent has each board of the decision review the diff between the approved revision and the delivered one:

```bash
openguildkit task diff-review ID                    # the files of the change and one command per board, with its state
openguildkit task diff-review ID --board security   # one board's brief, in its own pass (a subagent when the host has them)
openguildkit task diff-review ID --submit findings.json
```

A board's brief holds the diff limited to the files of the change (the tool's `.openguildkit/` folder left out), cut at 6 000 characters with the `git diff` command that prints the rest; when the working tree is delivered rather than a commit, the new files Git does not track yet are named, to be read in full.
Then what the decision asked: the expected outcome, who approved and why, the board's recommendation, verdict and failure mode at approval, the questions it left open, its blockers and how they were resolved, the disagreements left open that concern it, and its decision criteria.
Then its lens (the purpose and the focus of each specialist) and the format to return.
`--json` prints the same as JSON.

The board returns one JSON file: `{"board": "security", "findings": [{"file": "api/auth.py", "line": 42, "severity": "blocking", "action": "fix", "finding": "..."}]}`.
`file` is a file of the change and `line` a line of its delivered version; `severity` is `blocking` (must not ship as is), `important` or `minor`; `action` is `fix` (now), `defer` (a later task) or `decision` (the person decides at the closing).
An empty list records that the board found nothing.
A file with problems is refused with every problem at once, and nothing is recorded; a `defer` on a line the change added is refused, because a problem the change causes is fixed or brought to the person, never deferred.
A board that submits again replaces its earlier findings.
The output counts the boards that reviewed the delivered revision and the blocking findings with their board, file and line, then names the next step: the boards still to review, or fixing a blocking finding and recording the new revision with `task result`, or `task complete`.

At the closing, each blocking finding, each finding classed `decision`, and each review of an earlier revision than the delivered one is an open point of the group "Findings on the delivered diff": the task closes as `done-with-reservations`, and `task show ID --closing` prints them again.
`task export` carries the findings, board by board, under `delivered_review`.
A task whose diff no board reviewed closes and exports as before, and records written before this review read the same.
The review needs a project in Git with an approval that named its revision; a task of kind `decision` delivers no diff.
