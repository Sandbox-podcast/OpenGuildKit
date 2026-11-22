# Your first contribution

This walk-through adds one specialist lens to a brain, then shows the same steps for a reference entry and a pattern. You need a GitHub account, Git and Python 3.11 or later; no other tool.

## 1. Agree on the scope

Open an issue with the template that matches your idea (new pattern, new pack, new board, new sector, or a bug). Say who would use it, the situation it covers and the source you rely on. A maintainer or the domain steward answers in the issue. Small fixes can start directly with a pull request.

## 2. Fork, clone and check the baseline

```bash
gh repo fork Sandbox-podcast/OpenGuildKit --clone
cd OpenGuildKit
git switch -c brain/hr-health-and-safety
python -m pip install -e .
python -m unittest discover -s tests
```

The tests pass before you change anything. If they do not, say so in the issue.

## 3. Make the change

Example: the HR brain has lenses for hiring, onboarding, workforce planning, people data, pay, employment law and performance, but none for health and safety at work. Check with `openguildkit brains --id hr`, which lists each lens. In `src/openguildkit/registry/boards/hr.json`, add a specialist under `review.specialists`, with the `checks` an expert of that lens makes, as every bundled lens has:

```json
{
  "id": "health-and-safety-at-work",
  "title": "Health and safety at work reviewer",
  "focus": "Check whether a change to working time, workload, shifts or remote work adds a physical or psychosocial risk, and who assesses it.",
  "checks": [
    "Each risk the change adds to working conditions is listed with the prevention measure and its owner.",
    "The written risk assessment of the teams concerned is updated before the change applies."
  ]
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

Expected result: the first commands print nothing on error output, `brains --check` reports `27 brains, 0 gap(s).`, `brains --id hr` lists your lens, and the tests pass. A refused record names the file and the field.

If you changed triggers, add a brief that must and one that must not select the brain to `tests/routing_cases.json`.

## 5. Open the pull request

```bash
git commit -am "Add a health and safety lens to the HR brain"
git push -u origin brain/hr-health-and-safety
gh pr create --fill
```

Fill the template: what changes, the issue (`Closes #123` if the pull request resolves it, `Refs #123` otherwise), the effect on projects that use the catalog, and what you verified. GitHub labels the pull request from the files it changes.

## 6. Follow the checks

The pull request page shows `contribution-checks`, which combines the test matrix on Linux, macOS and Windows, the wheel build and the CI coordinator tests. Open "Details" next to a failed job to read the log, fix, and push again on the same branch. A maintainer or the steward of the domain reviews and merges with a squash.
