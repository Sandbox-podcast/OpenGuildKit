# Governance

OpenGuildKit is a catalog maintained by practitioners and a small CLI maintained by its maintainers. The governance follows that split.

## Roles

**Contributors** open issues and pull requests. Anyone can be one.

**Domain stewards** review patterns, rules and sources for their domain, including engineering, security, finance, people operations and project management. A steward checks that rules are accurate, verifiable and sourced. A domain can have several stewards. Stewards are listed in `.github/CODEOWNERS` with the paths of their domain once named.

**Maintainers** own the CLI, the schema and releases. They are listed in `.github/CODEOWNERS`, so GitHub requests their review on every pull request. A maintainer records the merge decision in the pull request.

OpenGuildKit has one maintainer today. Until a second one joins, that maintainer takes the decisions this page gives to the maintainers, and records the reason in the issue or the pull request.

## Decisions

- **Library changes:** ask the domain steward to review when one is available. The maintainer reviews submissions for domains that have no steward yet.
- **CLI changes:** include the tests or reproduction steps in the PR for the maintainer's review.
- **Changes that affect how contributors or existing projects work:** use the RFC issue template to discuss the proposed change.

The pull request records the proposal, review and decision. Link an existing issue when there is one. For a focused contribution, open a pull request directly. GitHub adds labels from the changed paths and reports the result of the test matrix, the wheel build and the web interface checks as `contribution-checks`.

## Becoming a steward or maintainer

A contributor with several merged pull requests in a domain can ask, or be proposed, in an issue. The maintainer decides; once there are several maintainers, they decide by lazy consensus. Inactive stewards and maintainers move to an emeritus list and can return by asking.

## Releases

Versions follow Semantic Versioning for the CLI. Packs carry their own versions. [Catalog format](docs/catalog-format.md)

GitHub refreshes the `openguildkit-next` release draft after changes reach `main`. It groups merged pull requests by label and compares from the last stable release. When every published release is a pre-release, it compares from the oldest one, so the first stable notes also list what the pilots shipped; with no release published yet, its link lists the commits up to `main`. [GitHub release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)

A maintainer publishes a version in these steps:

1. In a pull request to `main`, set the new version `X.Y.Z` in `pyproject.toml`, `integrations/ci/package.json`, `docs/install.md`, `integrations/ci/README.md` and the three workflow templates `integrations/github/openguildkit-guard.yml`, `integrations/github/openguildkit-market-watch.yml` and `integrations/github/openguildkit-dependency-watch.yml`, and give the version its section at the top of `CHANGELOG.md`, with the changes users will see since the last release. The test suite fails while they differ.
2. Once it is merged and `contribution-checks` passes on `main`, tag that commit and push the tag: `git tag -s vX.Y.Z COMMIT` then `git push origin vX.Y.Z`.
3. The tag runs `.github/workflows/release.yml`. It refuses a tag that differs from the versions. From the tagged commit, it builds the web interface (`npm ci --ignore-scripts`, `npm run build` and `npm run bundle` in `web/`), then the wheel that ships it, and refuses a wheel without `openguildkit/web_dist/index.html`. It packs the Node archive, writes `SHA256SUMS.txt` and attaches the three files to the release `vX.Y.Z`, created as a draft when it does not exist. It never replaces a file already attached.
4. Download the three files from the draft and check them with `sha256sum -c SHA256SUMS.txt`. Compare the hashes with those printed in the workflow log. The installation on each system is checked once the release is published (step 7).
5. Copy the section of the version from `CHANGELOG.md` into the release. Compare it with the `openguildkit-next` draft for a merged change it misses, and list each pack whose version changed. Tick "Set as a pre-release" for a version of the `pilot` channel.
6. Publish the release. The `Draft release notes` workflow then ends its comparison link on the tag.
7. Publishing runs `.github/workflows/release-check.yml` on the files of the release, with a read-only token. On Linux, macOS and Windows, it checks the hashes with the command `docs/install.md` gives for the system, installs the wheel in a fresh virtual environment, requires `openguildkit --version` to match the tag, sets up a project with `init --answers`, runs `check`, opens `openguildkit ui` with its key, installs the Node archive with npm and runs `openguildkit-ci --version` and `check-state`. On Linux, it upgrades a project set up with v0.16.1 as "Upgrading from 0.16.1" in `CHANGELOG.md` says and requires the task files to stay unchanged. A release tagged before the workflow existed does not run it: start it from the Actions tab (Release check, Run workflow) with the tag.

OpenGuildKit is not published on PyPI. Sending it there is a separate decision; until then, `docs/install.md` installs the wheel of the GitHub release with `pipx`, `uv` or a virtual environment.

## Neutrality

The catalog does not favor a vendor, model provider or agent. A pack may name tools when a standard requires them, and boards may cite vendor documentation as a source, but no rule requires a commercial product.
