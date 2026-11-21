# Governance

OpenGuildKit is a catalog maintained by practitioners and a small CLI maintained by a core team. The governance follows that split.

## Roles

**Contributors** open issues and pull requests. Anyone can be one.

**Domain stewards** review patterns, rules and sources for their domain, including engineering, security, finance, people operations and project management. A steward checks that rules are accurate, verifiable and sourced. A domain can have several stewards. Stewards are listed in `.github/CODEOWNERS` once named.

**Maintainers** own the CLI, the schema and releases. A maintainer records the merge decision in the pull request.

## Decisions

- **Library changes:** ask the domain steward to review when one is available. The maintainer reviews submissions for domains that have no steward yet.
- **CLI changes:** include the tests or reproduction steps in the PR for the maintainer's review.
- **Changes that affect how contributors or existing projects work:** use the RFC issue template to discuss the proposed change.

The pull request records the proposal, review and decision. Link an existing issue when there is one. For a focused contribution, open a pull request directly. GitHub adds labels from the changed paths and reports the result of the test matrix and wheel build as `contribution-checks`.

## Becoming a steward or maintainer

A contributor with several merged pull requests in a domain can ask, or be proposed, in an issue. Maintainers decide by lazy consensus. Inactive stewards and maintainers move to an emeritus list and can return by asking.

## Releases

Versions follow Semantic Versioning for the CLI. Packs carry their own versions. [Catalog format](docs/catalog-format.md)

GitHub refreshes the `openguildkit-next` release draft after changes reach `main`. It groups merged pull requests by label and compares from the last stable release. [GitHub release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)

A maintainer publishes a version in these steps:

1. In a pull request to `main`, set the new version `X.Y.Z` in `pyproject.toml`, `integrations/ci/package.json`, `docs/install.md`, `integrations/ci/README.md` and the guard template `integrations/github/openguildkit-guard.yml`. The test suite fails while they differ.
2. Once it is merged and `contribution-checks` passes on `main`, tag that commit and push the tag: `git tag -s vX.Y.Z COMMIT` then `git push origin vX.Y.Z`.
3. The tag runs `.github/workflows/release.yml`. It refuses a tag that differs from the versions, builds the wheel and the Node archive from the tagged commit, writes `SHA256SUMS.txt` and attaches the three files to the release `vX.Y.Z`, created as a draft when it does not exist. It never replaces a file already attached.
4. Download the three files from the draft and check them with `sha256sum -c SHA256SUMS.txt`. Compare the hashes with those printed in the workflow log.
5. Copy the notes of the `openguildkit-next` draft into the release, review them and list each pack whose version changed. Tick "Set as a pre-release" for a version of the `pilot` channel.
6. Publish the release. The `Draft release notes` workflow then ends its comparison link on the tag.

## Neutrality

The catalog does not favor a vendor, model provider or agent. A pack may name tools when a standard requires them, and boards may cite vendor documentation as a source, but no rule requires a commercial product.
