# Governance

OpenGuildKit is a catalog maintained by practitioners and a small CLI maintained by a core team. The governance follows that split.

## Roles

**Contributors** open issues and pull requests. Anyone can be one.

**Domain stewards** review catalog changes in their domain: security, engineering, design, product, QA, DevOps, performance, marketing, sales, finance, project management, and each sector. A steward checks that rules are accurate, verifiable and sourced. A domain can have several stewards; a steward can cover several domains. Stewards are listed in `.github/CODEOWNERS` once named.

**Maintainers** own the CLI, the schema, releases and this document. They merge pull requests that have the required approvals.

## Decisions

- **Catalog changes** (new or edited packs, boards, sectors): one approval from a steward of the domain, plus CI passing. If no steward exists yet for the domain, a maintainer reviews.
- **CLI changes:** one maintainer approval.
- **Schema changes, new commands, changes to the task flow or to this document:** an RFC issue first, then a decision by maintainers by lazy consensus (no maintainer objects). Objections must state what would change the objector's mind.

## Becoming a steward or maintainer

A contributor with several merged pull requests in a domain can ask, or be proposed, in an issue. Maintainers decide by lazy consensus. Inactive stewards and maintainers move to an emeritus list and can return by asking.

## Releases

Versions follow Semantic Versioning for the CLI. Packs carry their own versions (see [catalog format](docs/catalog-format.md)). Release notes list every pack whose version changed, since that invalidates pending approvals in projects that use it.

## Neutrality

The catalog does not favor a vendor, model provider or agent. A pack may name tools when a standard requires them, and boards may cite vendor documentation as a source, but no rule requires a commercial product.
