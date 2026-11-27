# Working on OpenGuildKit

Instructions for a coding agent that changes this repository. `tests/test_agent_native.py` keeps this file under 4 KB and checks that every path and command it names exists.

## Run

- Python 3.11 or later, standard library only. The `/usr/bin/python3` of macOS is 3.9 and fails.
- CLI from a checkout: `PYTHONPATH=src python -m openguildkit --help`.
- Check a change: `python scripts/check_fast.py` runs the tests that `docs/agents/map.json` attaches to the files changed since `origin/main`.
- One test module: `PYTHONPATH=src python -m unittest tests.test_guard`.
- An error shown as one line: run the command again with `OPENGUILDKIT_DEBUG=1` in front, and its Python traceback comes first on standard error.
- Full suite, several minutes, run by CI: `PYTHONPATH=src python -m unittest discover -s tests`. From a background shell, prefix it with `perl -e '$SIG{INT}="DEFAULT"; exec @ARGV'`, or three server tests of `tests/test_webui.py` time out.
- Web interface: `cd web && npm ci --ignore-scripts && npm run typecheck && npm test` (Node 22.12 or 24).
- CI coordinator: `cd integrations/ci && npm test`.

## Find

- `docs/agents/map.json`: each module of `src/openguildkit/` with its role, entry points, tests and documentation page.
- `docs/architecture.md` describes the modules, `docs/testing.md` the test files, `docs/workflow.md` the task path.
- `docs/agents/conventions.md`: the conventions that let an agent go from a symptom to its cause, its test and its fix with few reads.

## Change

- Code, CLI and documentation in English; `web/` and `README.fr.md` in French.
- `tests/test_architecture.py` holds modules under 2,000 lines, `cli.py` under 1,500, command functions under 120.
- A new module, test file or entry point goes in `docs/agents/map.json`, or `tests/test_agent_native.py` fails.
- A new command gets a test that runs it (`tests/test_cli_coverage.py`). Tests run the CLI through `tests/support.py`.
- `docs/testing.md` is a table of four columns: add a test file to the row of its area.
- A regression test names its issue in its docstring: `Issue #N: symptom`.
- One line in `CHANGELOG.md` under `## Unreleased`, ending with `(#N)`.
- Remove `web/dist` and `src/openguildkit/web_dist` after a web build, before the Python tests.

## Deliver

- Pull request against `main`, `Closes #N` for each issue. `main` takes a squash merge after one approval and a green `contribution-checks`.
- Say under `## Not verified` what you did not run.
- A vulnerability within `SECURITY.md` goes to a private advisory, never to a public issue.
