# Contributing to OpenGuildKit

OpenGuildKit is useful only if its catalog reflects how practitioners actually work. If you know a discipline, a standard or a sector, you can contribute without writing Python.

## Ways to contribute

| You know... | Contribute |
|---|---|
| A published specification or useful source | A [reference entry](docs/references.md) in `src/openguildkit/registry/references/` |
| A recurring stack or team method | A [pattern](docs/patterns.md) linking the context to versioned rule packs |
| A standard, regulation or convention | A rule pack in `src/openguildkit/registry/packs/` |
| A discipline (security, design, finance...) | A new board or better questions for an existing one |
| A sector (banking, health, retail...) | A sector record in `src/openguildkit/registry/sectors/` |
| A coding agent | An integration in `integrations/` |
| Python | CLI features, tests, bug fixes |

Before large work, open an issue with the matching template so a steward or maintainer can confirm the scope. [Your first contribution](docs/first-contribution.md) walks through one change from the fork to the merged pull request.

## Open a pull request

For larger changes, use an issue to discuss scope. Fork the repository, create a branch for the change and open a pull request against `main`. Use `Closes #123` for the issue the PR resolves, or `Refs #123` for related work. Include the part of the catalog or workflow you exercised.

`python scripts/check_fast.py` runs the tests [docs/agents/map.json](docs/agents/map.json) attaches to the files changed since `origin/main`, working tree included. Add a module to that map when you add one under `src/openguildkit/`. The full suite remains `python -m unittest discover -s tests`.

GitHub labels PRs from their changed files and requests a review from the owners in `.github/CODEOWNERS`. The `contribution-checks` status combines the test matrix (Python 3.11 and 3.15 on Linux, macOS and Windows), the timed performance tests (Python 3.15 on each system), the wheel build, the CI coordinator, and the checks and journeys of the web interface; a job that runs past its time limit fails.

Two kinds of cancelled jobs are not failures of your change:

- **No runner picked the job up.** Hosted macOS runners are scarce: a macOS job can wait 10 to 20 minutes, and GitHub cancels a job it cannot place after several attempts ("The job was not acquired by Runner of type hosted even after multiple attempts"). The job shows as cancelled with no step, and `contribution-checks` fails with `These jobs never started` and their names. Rerun them from the run page (Re-run jobs, then Re-run failed jobs); `contribution-checks` runs again after them. That is why `ci.yml` puts only four jobs on macOS per run.
- **You pushed again.** A new push to the pull request cancels the run of the previous commit, `contribution-checks` included, and starts one for the new commit. Read the checks of the latest commit only; nothing needs a rerun. Merges to `main` refresh a draft of the next release notes. Maintainers publish versions with the [release steps](GOVERNANCE.md#releases).

Everything you add to the repository, catalog content included (packs, references, patterns, boards, sectors and tools), is published under the MIT License in [LICENSE](LICENSE), like the code. Opening a pull request means you agree to that and that you have the right to contribute the content. Write rules and descriptions in your own words and never paste the text of a standard: only text you may license can be published under the MIT License.

## Set up

```bash
git clone https://github.com/Sandbox-podcast/OpenGuildKit.git
cd OpenGuildKit
python -m pip install -e .
python -m unittest discover -s tests
python -m openguildkit catalog
python -m openguildkit references
python -m openguildkit patterns
```

The web interface (`web/`, React and TypeScript) needs Node 22.12 or 24 and has its own checks; `npm run bundle` copies the build into the package, where `openguildkit ui` serves it:

```bash
cd web
npm ci --ignore-scripts
npm run typecheck
npm test                 # Vitest
npm run check:exports
npm run build
npm run bundle
npm run e2e:project      # Playwright journeys of openguildkit ui, after npm run build; Chrome installed
```

[web/README.md](web/README.md) has the other commands and the known pitfalls.

No runtime dependency. Tests use `unittest` from the standard library. [Testing](docs/testing.md) lists the kinds of tests (unit, end to end, concurrency, determinism, robustness, performance, upgrade), how to run each one and what they do not cover; `python scripts/bench.py` prints the time of the main commands.

## Adding a pack

1. Check [catalog coverage](docs/coverage.md) for your discipline: the brains with few packs and the documentary references that no pack applies yet show where a pack is missing.
2. Copy an existing pack, for example `src/openguildkit/registry/packs/api-design.json`, to `src/openguildkit/registry/packs/<your-id>.json`.
3. Set `version` to `1.0.0`. Start the description with the context the pack applies to, such as "For a service in production: ...".
4. Write each rule as an `instruction` the agent can follow and a `verification` a reviewer can check. See [writing good records](docs/catalog-format.md#writing-good-records).
5. Link the official source for the pack, with the day you checked the rule against it: `"checked": "YYYY-MM-DD"` right after its `url` (see [source dates](#source-dates)). Paraphrase; never paste text from a paid standard.
6. Reach the pack from a pattern for the roles that use it, and add the pack to the `packs` of the references it applies.
7. Run `python -m openguildkit catalog`, `python scripts/coverage.py` to refresh the coverage page, and the tests.
8. In the pull request, say which projects would use the pack and how you tested the rules on a real repository.

## Adding a board

Boards should map to a real discipline with its own questions. A board in `src/openguildkit/registry/boards/` holds:

- 3 `expertises` and 3 `questions` every task should answer, and `triggers` in English plus at least one other language;
- dated `sources`, as for every bundled record;
- a `review` block, which every brain needs: `specialists` (the lenses, each with an `id`, a `title`, a `focus` and the `checks` an expert of that lens makes), the `evidence` to inspect, the `challenge` questions and the `decision_criteria`. See [Brains](docs/brains.md).

To start from a complete record, run `openguildkit brains --new ID` in a scratch project: it writes the board with its review block, a method pattern, a rule pack and a reference family under `.openguildkit/catalog/`, with `TODO:` text to replace. Move the files you keep to the matching folders of `src/openguildkit/registry/`. A brain also needs a method (a pattern that lists its ID in `roles`) and references that list its ID in `brains`.

Then run `openguildkit brains --check`, which CI runs: it fails on a brain without a method or a reference, or with `TODO:` text left, and the catalog refuses a malformed `review` block with its file and field. `openguildkit brains --id ID` shows the lenses with their checks and the knowledge attached. Check that your triggers do not fire on common words: add briefs that must and must not select the board to `tests/routing_cases.json`, which CI runs on every change.

## Adding a sector

A sector record lists what an agent must ask or check in that industry: roles, data, who approves which decision, regulators. Write context items as instructions, not descriptions of the industry.

## Quality bar for the catalog

A catalog pull request is merged when:

- the JSON validates (CI runs it on Linux, macOS and Windows);
- every rule has a verification a reviewer could actually perform;
- sources are official or widely recognized, use HTTPS and link the canonical page without tracking parameters, with one address per document;
- every source carries its `checked` date, and a changed rule has its source re-read and re-dated;
- nothing claims compliance or certification;
- a steward of the domain approved it (see [GOVERNANCE.md](GOVERNANCE.md)).

## Source dates

Every source of the bundled catalog carries `checked`, a date `YYYY-MM-DD` placed right after its `url`. It is the day the page was last opened and answered; a contributor who writes or changes a rule re-reads its source and sets the date to that day. It does not certify that someone re-read the whole document on that day. The loader refuses a bundled source without it.

To refresh the dates, a maintainer runs the link check with `--stamp`, from a full clone (not a shallow one):

```bash
python3 -I scripts/check_links.py --out link-report --stamp
```

A page that answered (available, or redirected to a page that answered) gets the day of the report. A page that did not answer or refused the script keeps its date; a source that has none gets the day its URL entered the catalog, read from the Git history, and the script lists it to open by hand. Never give today's date to a page that did not answer. After a merge that adds sources, run `python3 -I scripts/check_links.py --stamp-from link-report/links-DATE.json` again, or a new `--stamp`: the result depends only on the report and the history. The diff adds one `checked` line per source and a comma after the `url`; review the pull request for any other change.

## Reviewing source links

The scheduled workflow `Check catalog links` runs every Monday and on demand. It runs `python3 -I scripts/check_links.py --out link-report`, uploads the dated `links-YYYY-MM-DD.md` and `.json` report as the `link-report` artifact, and fails only when a link is dead. The report also lists the sources whose `checked` date is older than 180 days (`--max-age DAYS`), with the records that cite them: re-read each one and re-date it. It also opens the homepage, the API documentation and the source of each MCP server in the tool registry. The script reads the bundled catalog only: catalogs that projects keep in `.openguildkit/catalog/` stay in those projects and are never fetched.

For each URL, the report gives its category and the records that cite it: references with their edition and the packs that apply them, packs with their version and rule IDs, patterns, boards and sectors. A maintainer reviews it as follows.

- **Dead:** find the page that replaces it on the publisher's site, fetch it, and check its status and title. Replace the URL and the title in every record the report lists, so the document keeps one address.
- **Redirected:** use the target when it is the publisher's new canonical page. Leave aliases such as `latest` when the catalog means to follow the current version.
- **To recheck:** open the page in a browser. Some publishers (ISO, W3C, PMI, EUR-Lex) answer scripts with 403 or 202, and GitHub sometimes answers 503 under load; keep the URL when the page works.
- **New edition:** the `Watch reference editions` workflow opens an issue titled `Edition may have changed: ID` when the edition a reference cites is no longer on its page (see [source dates](docs/catalog-format.md#source-dates) for what this check can miss or raise by mistake). Open the page. The link report lists the packs and rules that cite the old edition. Decide with the domain steward whether the rules change, bump the pack version (patch for a source or wording change, minor or major when rules change) and update the reference's `edition` and the source's `checked` date. Then run `python3 -I scripts/watch_editions.py` and commit `scripts/edition-watch.json`, which also takes the updated watch file the workflow keeps as an artifact. Projects see the change in `openguildkit update` before they apply it.

A maintainer validates every replacement in the pull request that makes it. Run the script locally with the same command before proposing one.

## Code contributions

- The agent skill and subagent live in `src/openguildkit/agent_files/` and are copied in `integrations/`; edit both, the tests check that they match.

- Python 3.11+, standard library only at runtime.
- Keep the CLI offline. It must never call a model provider or the network. The one exception is `docs share verify`, which a person runs to read their own Documentalist instance; do not add another without discussing it in an issue.
- Add unit tests in `tests/` and, for a new command, an end-to-end test in `tests/e2e/`: `tests/test_cli_coverage.py` fails when a command has no test that runs it. Run the CLI from a test with `tests/support.py` (`run_cli`, `CapturedCli`, `copy_initialized_project`): it runs in the test process unless the test needs a real one ([testing](docs/testing.md#how-the-suite-runs-the-cli)).
- Keep messages short and actionable, prefixed `OpenGuildKit:` on errors.
- Write code, rule packs and documentation in English, except the web interface. The web interface is written in French, because its screens are in French and the team that builds and uses it so far is French-speaking: `web/` (its screens, `web/README.md` and `web/docs/`) stays in French. Reference entries can keep their original language. The French README is maintained alongside the English one.

## Pull requests

- One topic per pull request.
- Describe what changes for a project that already uses OpenGuildKit. A pack change invalidates pending approvals in those projects; say so.
- Fill in the pull request template.

## Conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
