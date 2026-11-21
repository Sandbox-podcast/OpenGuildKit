# Your first contribution

This walk-through adds one specialist lens to a brain, then shows the same steps for a reference entry and a pattern. You need a GitHub account, Git and Python 3.11 or later; no other tool.

## 1. Agree on the scope

Open an issue with the template that matches your idea (new pattern, new pack, new board, new sector, or a bug). Say who would use it, the situation it covers and the source you rely on. A maintainer or the domain steward answers in the issue. Small fixes can start directly with a pull request.

## 2. Fork, clone and check the baseline

```bash
gh repo fork Sandbox-podcast/OpenGuildKit --clone
cd OpenGuildKit
git switch -c brain/hr-pay-equity
python -m pip install -e .
python -m unittest discover -s tests
```

The tests pass before you change anything. If they do not, say so in the issue.

## 3. Make the change

Example: the HR brain should look at pay equity when a change touches compensation. In `src/openguildkit/registry/boards/hr.json`, add a specialist under `review.specialists`:

```json
{
  "id": "pay-equity",
  "title": "Pay equity reviewer",
  "focus": "Check that a change to compensation rules or job levels can be explained per job category and does not create gaps the team cannot justify."
}
```

Keep the record's other lists in step: add the evidence this lens needs to `review.evidence`, a challenge question to `review.challenge` and, if the lens changes the verdict, a decision criterion. Add a source to `sources` only if you have read it: an official text or a recognized body, over HTTPS, without tracking parameters.

The same steps apply to:

- a **reference entry**: add an object to the right family in `src/openguildkit/registry/references/` with `id`, `title`, `category`, `kind` from the documented list, a French `summary`, `applies_when`, `sources` and the `brains` it serves;
- a **pattern**: add `src/openguildkit/registry/patterns/<id>.json` with its `roles` (brain IDs) and the `packs` it applies, as described in [Work and stack patterns](patterns.md).

## 4. Validate

```bash
openguildkit catalog > /dev/null
openguildkit references > /dev/null
openguildkit patterns > /dev/null
openguildkit brains --check
openguildkit brains --id hr
python -m unittest discover -s tests
```

Expected result: the first commands print nothing on error output, `brains --check` reports `18 brains, 0 gap(s).`, `brains --id hr` lists your lens, and the tests pass. A refused record names the file and the field.

If you changed triggers, add a brief that must and one that must not select the brain to `tests/routing_cases.json`.

## 5. Open the pull request

```bash
git commit -am "Add a pay equity lens to the HR brain"
git push -u origin brain/hr-pay-equity
gh pr create --fill
```

Fill the template: what changes, the issue (`Closes #123` if the pull request resolves it, `Refs #123` otherwise), the effect on projects that use the catalog, and what you verified. GitHub labels the pull request from the files it changes.

## 6. Follow the checks

The pull request page shows `contribution-checks`, which combines the test matrix on Linux, macOS and Windows, the wheel build and the CI coordinator tests. Open "Details" next to a failed job to read the log, fix, and push again on the same branch. A maintainer or the steward of the domain reviews and merges with a squash.
