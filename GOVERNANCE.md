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

## Merging

`main` takes a squash merge and no other kind: the ruleset "Protect main contributions" of the repository allows only the squash method, and asks one approval, resolved review threads and a green `contribution-checks` (ruleset read on 28 November 2026). This holds whatever the number of issues the pull request closes.

A pull request that closes several issues is merged as one squash commit that names each issue on a line of its own:

1. Each commit of the branch names one issue in its subject, which ends with `(#N)` and names no range or list (`#377 to #407`, `#12, #13`), and its body has the line `#N symptom (file:function)`.
2. The description has `Closes #N` and one line `#N symptom (file:function)` for each issue it closes, and a `## Not verified` section. `scripts/check_pr_text.py`, run by the `conventions` job, refuses a title or a commit subject that names a range or a list, a `Closes #N` without its line, and a missing or empty `## Not verified`.
3. The squash commit takes the title of the pull request, and as its body the messages of the branch's commits, as the repository settings write it. Before confirming, the person who merges checks that the body keeps one line `#N symptom (file:function)` per issue closed, and pastes the lines of the description when it does not.

`git log --grep '#N'` then finds each issue, and `git blame` leads to the squash whose body names it. `.git-blame-ignore-revs` lists the two squashes of whole branches (387 and 523 files) that came before this rule; [set up](CONTRIBUTING.md#set-up) says how to use it. A merge commit or a rebase, which would keep one commit per issue on `main` (proposed in issue #483), needs the maintainers to change the ruleset: it is not adopted.

## Becoming a steward or maintainer

A contributor with several merged pull requests in a domain can ask, or be proposed, in an issue. The maintainer decides; once there are several maintainers, they decide by lazy consensus. Inactive stewards and maintainers move to an emeritus list and can return by asking.

## Releases

Versions follow Semantic Versioning for the CLI. Packs carry their own versions. [Catalog format](docs/catalog-format.md)

GitHub refreshes the `openguildkit-next` release draft after changes reach `main`. It groups merged pull requests by label and compares from the last stable release. When every published release is a pre-release, it compares from the oldest one, so the first stable notes also list what the pilots shipped; with no release published yet, its link lists the commits up to `main`. [GitHub release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)

A maintainer publishes a version in these steps:

1. In a pull request to `main`, set the new version `X.Y.Z` in `pyproject.toml`, `integrations/ci/package.json`, `docs/install.md`, `integrations/ci/README.md` and the workflow templates `integrations/github/openguildkit-guard.yml`, `integrations/github/openguildkit-market-watch.yml`, `integrations/github/openguildkit-dependency-watch.yml`, `integrations/github/openguildkit-retro.yml`, `integrations/github/openguildkit-org-catalog-update.yml` and `integrations/github/openguildkit-status.yml`, and give the version its section at the top of `CHANGELOG.md`, with the changes users will see since the last release. The test suite fails while the release versions differ. After publication, set the package versions to the next development version (`X.Y.Z.dev0` in Python and `X.Y.Z-dev.0` in Node). Keep the install examples and templates pinned to the published version and put new changes under Unreleased. The templates keep their pinned wheel hash until the first release that ships `install.sh`: in that release's pull request, replace their "Install OpenGuildKit" step with the `install.sh` line of `docs/install.md`, pinned to the tag.
2. Once it is merged and `contribution-checks` passes on `main`, tag that commit and push the tag: `git tag -s vX.Y.Z COMMIT` then `git push origin vX.Y.Z`.
3. The tag runs `.github/workflows/release.yml`. It refuses a tag that differs from the versions. From the tagged commit, with `SOURCE_DATE_EPOCH` set to the date of the commit and the build tools of `.github/build-constraints.txt`, it builds the web interface (`npm ci --ignore-scripts`, `npm run build` and `npm run bundle` in `web/`), then the wheel that ships it, and refuses a wheel without `openguildkit/web_dist/index.html`. It then builds the wheel a second time from sources with new file dates and stops unless both builds have the same SHA-256. It writes the CycloneDX SBOM of the web interface (`scripts/make_sbom.py`), packs the Node archive, copies the installers `scripts/install.sh` and `scripts/install.ps1` and writes `SHA256SUMS.txt`. The `attest` job, the only one with `attestations: write`, attests the build provenance of the six files; the last job then attaches them to the release `vX.Y.Z`, created as a draft when it does not exist. It never replaces a file already attached.
4. Download the six files from the draft and check them with `sha256sum -c SHA256SUMS.txt`. Compare the hashes with those printed in the workflow log. Run `gh attestation verify FILE --repo Sandbox-podcast/OpenGuildKit` on the wheel. The installation on each system is checked once the release is published (step 7).
5. Copy the section of the version from `CHANGELOG.md` into the release. Compare it with the `openguildkit-next` draft for a merged change it misses, and list each pack whose version changed. Tick "Set as a pre-release" for a version of the `pilot` channel.
6. Publish the release. The `Draft release notes` workflow then ends its comparison link on the tag.
7. Publishing runs `.github/workflows/release-check.yml` on the files of the release, with a read-only token. On Linux, macOS and Windows, it checks the hashes with the command `docs/install.md` gives for the system, runs `gh attestation verify` on each file with the repository, the workflow `release.yml` and the tag, installs the wheel with no index (`--no-index`) and in a fresh virtual environment, requires `openguildkit --version` to match the tag, sets up a project with `init --answers`, runs `check`, opens `openguildkit ui` with its key, installs the Node archive with npm and runs `openguildkit-ci --version` and `check-state`. On Linux, it upgrades a project set up with v0.16.1 as "Upgrading from 0.16.1" in `CHANGELOG.md` says and requires the task files to stay unchanged. A release tagged before the workflow existed does not run it: start it from the Actions tab (Release check, Run workflow) with the tag, and untick "attestations" for a release that predates them.

8. Optional, once per channel: PyPI, a container image, Homebrew and winget are ready but off. Each needs an account or a setting only the maintainer can create, and nothing is published until it exists.
   - PyPI: on PyPI, add a pending trusted publisher (account sidebar, Publishing) with the project `openguildkit`, the owner `Sandbox-podcast`, the repository `OpenGuildKit`, the workflow `release.yml` and the environment `pypi`; a pending publisher does not reserve the name until the first upload ([creating a project through OIDC](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/), read 2026-11-28). In the repository settings, create the environment `pypi` with a required reviewer, so that each upload waits for a person, then set the repository variable `PYPI_PUBLISH` to `true`. The `pypi` job of `release.yml` then uploads the wheel the `attest` job signed, by OIDC with `id-token: write` and no token or secret ([trusted publishers](https://docs.pypi.org/trusted-publishers/using-a-publisher/), read 2026-11-28); `pypa/gh-action-pypi-publish` adds its own attestations by default ([README](https://github.com/pypa/gh-action-pypi-publish), read 2026-11-28).
   - Container image: set the repository variable `GHCR_PUBLISH` to `true`. The `image` job builds the `Dockerfile` around the attested wheel, requires `openguildkit --version` to match the tag, and pushes `ghcr.io/sandbox-podcast/openguildkit:X.Y.Z` with the token of the run and `packages: write` ([publishing a package with GitHub Actions](https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions), read 2026-11-28). Check the visibility of the package in its settings after the first push. The base image is pinned by digest in the `Dockerfile`; update it by hand.
   - Homebrew and winget: after step 6, download `SHA256SUMS.txt` and run `python scripts/release_manifests.py --sums SHA256SUMS.txt --output DIR`. It fills `packaging/homebrew/openguildkit.rb` with the url, version and sha256 of the wheel, for a tap the maintainer creates (`brew tap-new`; [Python formulae](https://docs.brew.sh/Language-Specific-Formulae#python), read 2026-11-28). It fills the winget manifests of `packaging/winget/` (schema 1.28.0, which the pull request template of microsoft/winget-pkgs names on 2026-11-28; [manifest schema](https://github.com/microsoft/winget-pkgs/tree/master/doc/manifest/schema/1.28.0)) only when the release carries `openguildkit-X.Y.Z-windows-x64.zip` with `openguildkit.exe`: winget installs an executable, not a wheel, and `release.yml` builds none yet. Check them with `winget validate` and `winget install --manifest`, then open the pull request to microsoft/winget-pkgs.

OpenGuildKit is not published on PyPI. Sending it there is the maintainer's decision, taken by step 8; until then, `docs/install.md` installs the wheel of the GitHub release with `pipx`, `uv` or a virtual environment.

## Neutrality

The catalog does not favor a vendor, model provider or agent. A pack may name tools when a standard requires them, and boards may cite vendor documentation as a source, but no rule requires a commercial product.
