# Contributing to OpenGuildKit

OpenGuildKit is useful only if its catalog reflects how practitioners actually work. If you know a discipline, a standard or a sector, you can contribute without writing Python.

## Ways to contribute

| You know... | Contribute |
|---|---|
| A published specification or useful source | A [reference entry](docs/references.md) in `src/openguildkit/registry/references/` |
| A standard, regulation or convention | A rule pack in `src/openguildkit/registry/packs/` |
| A discipline (security, design, finance...) | A new board or better questions for an existing one |
| A sector (banking, health, retail...) | A sector record in `src/openguildkit/registry/sectors/` |
| A coding agent | An integration in `integrations/` |
| Python | CLI features, tests, bug fixes |

Before large work, open an issue with the matching template so a steward or maintainer can confirm the scope.

## Set up

```bash
git clone https://github.com/loukan42/OpenGuildKit.git
cd OpenGuildKit
python -m pip install -e .
python -m unittest discover -s tests
python -m openguildkit catalog
python -m openguildkit references
```

No runtime dependency. Tests use `unittest` from the standard library.

## Adding a pack

1. Copy an existing pack, for example `src/openguildkit/registry/packs/api-design.json`, to `src/openguildkit/registry/packs/<your-id>.json`.
2. Set `version` to `1.0.0`.
3. Write each rule as an `instruction` the agent can follow and a `verification` a reviewer can check. See [writing good records](docs/catalog-format.md#writing-good-records).
4. Link the official source for the pack. Paraphrase; never paste text from a paid standard.
5. Run `python -m openguildkit catalog` and the tests.
6. In the pull request, say which projects would use the pack and how you tested the rules on a real repository.

## Adding a board

Boards should map to a real discipline with its own questions. Give it 3 expertises, 3 questions every task should answer, and triggers in English plus at least one other language. Check that your triggers do not fire on common words: run `openguildkit task consult` on a few briefs and read the routing reasons.

## Adding a sector

A sector record lists what an agent must ask or check in that industry: roles, data, who approves which decision, regulators. Write context items as instructions, not descriptions of the industry.

## Quality bar for the catalog

A catalog pull request is merged when:

- the JSON validates (CI runs it on Linux, macOS and Windows);
- every rule has a verification a reviewer could actually perform;
- sources are official or widely recognized and use HTTPS;
- nothing claims compliance or certification;
- a steward of the domain approved it (see [GOVERNANCE.md](GOVERNANCE.md)).

## Code contributions

- Python 3.11+, standard library only at runtime.
- Keep the CLI offline. It must never call a model provider or the network.
- Add unit tests in `tests/` and, for a new command, an end-to-end test in `tests/e2e/`.
- Keep messages short and actionable, prefixed `OpenGuildKit:` on errors.
- Write code, rule packs and contribution docs in English. Reference entries can keep their original language. The French README is maintained alongside the English one.

## Pull requests

- One topic per pull request.
- Describe what changes for a project that already uses OpenGuildKit. A pack change invalidates pending approvals in those projects; say so.
- Fill in the pull request template.

## Conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
