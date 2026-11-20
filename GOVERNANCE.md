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

GitHub refreshes the `openguildkit-next` release draft after changes reach `main`. It groups merged pull requests by label. When preparing a version, copy the generated notes into a versioned release, review them and list each pack whose version changed. A maintainer publishes the release. [GitHub release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)

## Neutrality

The catalog does not favor a vendor, model provider or agent. A pack may name tools when a standard requires them, and boards may cite vendor documentation as a source, but no rule requires a commercial product.
