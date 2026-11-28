# Install OpenGuildKit from GitHub Releases

For: an administrator who installs OpenGuildKit on workstations, and a developer who upgrades it.

OpenGuildKit is not published on PyPI: install the wheel attached to a [GitHub release](https://github.com/Sandbox-podcast/OpenGuildKit/releases). The Python wheel provides the CLI, the catalog, the agent files and the web interface that `openguildkit ui` serves. The optional Node package coordinates checks across GitHub Actions and Jenkins.

## Install in one line

On Linux or macOS, with pipx or uv already installed:

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.sh | sh
```

On Windows, in PowerShell:

```powershell
irm https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.ps1 | iex
```

The script downloads `SHA256SUMS.txt` and the wheel of the latest release, which GitHub never sets to a draft or a pre-release ([Get the latest release](https://docs.github.com/en/rest/releases/releases#get-the-latest-release), read on 2026-11-26). It checks the wheel's SHA-256 against that file and only then installs the wheel with pipx, or with uv when pipx is missing. It prints four lines: the version downloaded, the hash checked, the installer used and the next commands, `openguildkit --version` then `openguildkit init` in your repository. For another version, a pre-release included, name it: `curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.sh | sh -s -- --version 0.17.0`, or in PowerShell `& ([scriptblock]::Create((irm https://github.com/Sandbox-podcast/OpenGuildKit/releases/latest/download/install.ps1))) -Version 0.17.0`. The installer replaces an installed version (`--force`), so the same line upgrades.

When the hash differs, nothing is installed: the script names the file and the release and exits with 1. Without pipx or uv, it prints the official installation command of each ([pipx](https://pipx.pypa.io/stable/how-to/install-pipx.html), [uv](https://docs.astral.sh/uv/getting-started/installation/), read on 2026-11-26) and stops. `--proto '=https' --tlsv1.2` makes curl refuse an address or a redirect that is not https, and a TLS version older than 1.2; the script passes the same options to its own downloads. The script and `SHA256SUMS.txt` come from the same release, so the check catches a corrupted or tampered download of the wheel, not a release whose files were all replaced: for that, [verify where the files come from](#verify-where-the-files-come-from) and check the signed tag, as below. The scripts are `scripts/install.sh` (POSIX sh) and `scripts/install.ps1` in the repository; read them before piping them to a shell if you prefer.

`OPENGUILDKIT_RELEASES_URL` replaces the address of the releases in both scripts. It is reserved for the tests, which serve a fake release from a local folder: do not set it.

## Download and verify

Download the wheel, the optional Node archive and `SHA256SUMS.txt`. For v0.17.0, use the following GitHub CLI command.

```sh
gh release download v0.17.0 --repo Sandbox-podcast/OpenGuildKit --pattern 'openguildkit-0.17.0-py3-none-any.whl' --pattern 'openguildkit-0.17.0.tgz' --pattern SHA256SUMS.txt
```

On Linux use `sha256sum -c SHA256SUMS.txt`. On macOS use `shasum -a 256 -c SHA256SUMS.txt`. On Windows use `Get-FileHash .\openguildkit-0.17.0-py3-none-any.whl, .\openguildkit-0.17.0.tgz -Algorithm SHA256` in PowerShell and compare each hash to the corresponding line in `SHA256SUMS.txt`. From the first release that ships the one-line installers, `SHA256SUMS.txt` also lists `install.sh` and `install.ps1`, and from the first that ships the SBOM, `openguildkit-X.Y.Z.cdx.json`: add `--pattern 'install.*' --pattern '*.cdx.json'` to the download, or the Linux and macOS checks report them missing and fail.

### Verify the release tag

From v0.17.0, release tags are signed with SSH. `.github/allowed_signers` lists the keys allowed to sign them. In a clone of the repository, with Git 2.34 or later:

```sh
git fetch origin tag v0.17.0
git -c gpg.ssh.allowedSignersFile=.github/allowed_signers verify-tag v0.17.0
```

Git prints `Good "git" signature for azerothl with ED25519 key SHA256:AV5Bo/uY6JRe69aVl4+tSu/BYMJezgeBgtNCA7qlWvY`. The file comes from the same repository as the tag: compare the key with the signing keys of the signer's GitHub account (`gh api users/azerothl/ssh_signing_keys`). Earlier tags are not signed.

## Verify where the files come from

From the first release that ships attestations, the workflow that builds a release signs the SHA-256 of each of its files (the wheel, the Node archive, the SBOM, both installers and `SHA256SUMS.txt`) with a short-lived Sigstore certificate that GitHub issues to that workflow run, and stores the signature with the repository ([artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations), read on 2026-11-26). With the GitHub CLI, signed in:

```sh
gh attestation verify openguildkit-0.17.0-py3-none-any.whl --repo Sandbox-podcast/OpenGuildKit
```

Add `--signer-workflow Sandbox-podcast/OpenGuildKit/.github/workflows/release.yml` to require the release workflow and `--source-ref refs/tags/v0.17.0` to require the tag: `release-check.yml` runs the command with both on every file of a published release. A success proves that this file, byte for byte, was attested by that workflow of that repository for that tag; `--format json` prints the verified certificate and statement. It does not prove that the source is free of defects or that a maintainer reviewed the tag (check the signed tag above for that), and it needs to reach GitHub: `gh attestation download` on a connected machine saves the attestation, and `--bundle` with `--custom-trusted-root` checks it from disk (see `gh attestation verify --help`; not replayed offline here, to be verified before you rely on it).

`openguildkit-X.Y.Z.cdx.json` is the [CycloneDX](https://cyclonedx.org/) 1.5 SBOM of the release: the wheel, with its SHA-256, and the npm packages its web interface is built from (`react`, `react-dom`, `zod`, `immer`, `diff`, the two fonts and the packages they need), each with its version, hash and licence. `scripts/make_sbom.py` writes it from `web/package-lock.json`, leaving out what only the build needs. The wheel has no Python dependency and the Node archive no dependency at all, so these are all the third-party packages the release contains.

## Offline and internal mirror

The wheel has no runtime dependency, so installing it needs no package index and no access to GitHub from the workstation. On a connected machine, download the release files as above and check the hashes and the attestation. Copy `openguildkit-0.17.0-py3-none-any.whl`, `SHA256SUMS.txt` and, for your security team, `openguildkit-0.17.0.cdx.json` to the offline machine or to the internal share. There, check the hash again (`sha256sum -c --ignore-missing SHA256SUMS.txt` on Linux; on macOS compare `shasum -a 256 FILE` with its line of `SHA256SUMS.txt`), then install with no index:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --no-index ./openguildkit-0.17.0-py3-none-any.whl
openguildkit --version
```

`--no-index` makes pip read nothing but that file, and it fails if the wheel ever needs a dependency. `release-check.yml` runs this command on Linux, macOS and Windows with the wheel of every published release.

To serve the wheel to many workstations or to CI, put it in the internal Python index or artifact repository of your organization and install with `python -m pip install --index-url URL openguildkit==0.17.0`. Use `--index-url`, not `--extra-index-url`: with both, a package named `openguildkit` on a public index could be chosen over yours. The CI workflow templates still download the wheel from GitHub; pointing them at the mirror is a change of their `curl` line.

## How the release assets are built

Pushing a tag `vX.Y.Z` runs `.github/workflows/release.yml` on GitHub Actions, on `ubuntu-latest`, from the tagged commit. The workflow stops if the tag differs from the version in `pyproject.toml` or `integrations/ci/package.json`. It sets `SOURCE_DATE_EPOCH` to the date of the commit and builds the web interface with Node.js 24 (`npm ci --ignore-scripts`, `npm run build`, then `npm run bundle`, which copies it into `src/openguildkit/web_dist` and fails above its size budget), then the wheel with Python 3.11, the floor that the tests run on (`python -m build --wheel`). The versions of `build` and of setuptools come from `.github/build-constraints.txt`, which the job gives to pip as `PIP_CONSTRAINT`: the `Generator` line of the wheel names the setuptools that built it. It refuses a wheel that does not contain `openguildkit/web_dist/index.html`, then builds the wheel a second time from sources whose file dates it has changed and stops unless both builds have the same SHA-256 (the web interface is built once). It writes the CycloneDX SBOM of the web interface (`scripts/make_sbom.py`), packs the Node archive (`npm pack ./integrations/ci`), copies the one-line installers `scripts/install.sh` and `scripts/install.ps1`, and writes `SHA256SUMS.txt` with `sha256sum`, one line per file. A separate job, the only one that holds `id-token: write` and `attestations: write`, attests the build provenance of the six files; only then does the last job attach them to the release of the tag. When that release does not exist yet, the workflow creates it as a draft, which a maintainer reviews and publishes. The run log on the Actions tab prints the hashes it computed. The `package` job of `.github/workflows/ci.yml` builds the wheel with the same steps on every pull request, installs it on Linux, macOS and Windows (with `pipx` on Windows), and checks that `openguildkit ui` serves the interface. Once the release is published, `.github/workflows/release-check.yml` downloads its files, checks their hashes and their attestations, and installs them on the same three systems, the wheel also with `--no-index`.

## Install the Python CLI

Use Python 3.11 or later. For a team, install the command once per workstation with [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/): both put `openguildkit` on the PATH, which the hooks of the board guard need. `host apply` fails while a setting stays missing.

```sh
pipx install ./openguildkit-0.17.0-py3-none-any.whl
openguildkit --version
```

Or, with uv:

```sh
uv tool install ./openguildkit-0.17.0-py3-none-any.whl
openguildkit --version
```

To keep OpenGuildKit inside one project instead, install it in a virtual environment. Save the path to the wheel before switching to the project directory. On Linux or macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./openguildkit-0.17.0-py3-none-any.whl
openguildkit catalog
```

On Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\openguildkit-0.17.0-py3-none-any.whl
.\.venv\Scripts\openguildkit.exe catalog
```

Check the version you installed with `openguildkit --version`. From the project to equip, run `openguildkit init`, then `openguildkit host apply` when the host is Claude Code, Codex or Gemini CLI (`check` fails until the host settings are applied), then `openguildkit check`. On Windows, use the full path to `openguildkit.exe` from the installed environment, or activate that environment first. Commit the generated profile, `.openguildkit/catalog.lock.json` and the instructions for the team. `openguildkit ui` then opens the project in the browser, on 127.0.0.1: the wheel ships the built interface.

## Complete the commands

`openguildkit completion bash` and `openguildkit completion zsh` print a script that completes the commands, their options and their values: add `eval "$(openguildkit completion bash)"` to `~/.bashrc`, or `eval "$(openguildkit completion zsh)"` to `~/.zshrc` after `compinit`. [Every command and option](cli.md) is also written in one page.

## Set up the agent

The wheel ships the agent skill and the subagents (board, market analyst, dependency watch) of the same version. From the project:

```sh
openguildkit integrations --host claude-code   # .claude/skills/openguildkit and .claude/agents/ (guild-board, market-analyst, dependency-watch)
openguildkit integrations --host codex         # .agents/skills/openguildkit
openguildkit integrations --host gemini-cli    # .agents/skills/openguildkit, the alias of its skills folder
openguildkit integrations --host other         # .agents/skills/openguildkit, for another agent
```

Add `--user` to install them in your home folder for every project. A file you changed is kept and reported; `--force` replaces it and saves your version as `.previous`. Each folder gets `openguildkit-version.txt` with the installed version, or the name of the file kept at another version (for the skill, one note next to `SKILL.md` covers its `references/` files too). `openguildkit init` asks for the agent host and the board guard (`observe` unless you choose otherwise) and, when the host is Claude Code, Codex or Gemini CLI, prints `openguildkit host apply` as the next step: it installs the host settings and hooks. With the host `other` (the default), OpenGuildKit writes no host settings: see [other agents](../integrations/README.md#other-agents) for details. For a project set up before, change the host with `openguildkit profile set host claude-code --by INITIALS --reason WHY` (or `codex`, or `gemini-cli`) and run the same command.

For another agent (the host `other`), the whole path is:

1. `openguildkit init`, choosing `other`: it writes `AGENTS.md`, which most agents read, and `CLAUDE.md`, one line for Claude Code that you can delete.
2. `openguildkit integrations --host other`: the skill goes to `.agents/skills/openguildkit/`, `SKILL.md` and its `references/` folder; copy the whole folder to the folder your agent reads skills or instructions from if it is another one.
3. `openguildkit host check`: every rule shows `by instruction` or `by a person`, since no setting of this agent can enforce it. `openguildkit host apply` writes nothing for this host, says so and exits with 1.
4. `openguildkit tools plan TOOL...`: prints each MCP server as an `mcpServers` entry to copy into your agent's MCP settings. `tools apply` writes only for `--host claude-code` or `--host codex`.
5. `openguildkit check`, then commit `AGENTS.md`, `.openguildkit/project.json` and `.openguildkit/catalog.lock.json`. The board guard has no hook here: the AGENTS.md instruction and `openguildkit guard --ci` in CI are the controls. The hooks of the board guard call `openguildkit` by name: start the agent from the activated environment, or install the CLI on the PATH (for example with `pipx`). When the command is not on the PATH, `host check`, `host apply` and `check` report the guard as `missing`, say that the PATH is the cause and fail; running `host apply` again does not fix it, installing the CLI or activating its environment does. The web interface shows the same cause instead of offering to synchronize.

## Upgrade

1. Run the one-line installer again, with `--version` for a given release. Or download and verify the new release assets as above, then install the new wheel the way you installed the first one: `pipx install --force ./openguildkit-NEW-py3-none-any.whl`, `uv tool install ./openguildkit-NEW-py3-none-any.whl`, or `python -m pip install --upgrade ./openguildkit-NEW-py3-none-any.whl` in the virtual environment. Check `openguildkit --version`.
2. Run `openguildkit integrations --host ...` again to update the skill and subagent.
3. Run `openguildkit update` to see the date of the new catalog, the number of records it changes and what it changes for the project, and `openguildkit update --apply` once the team agrees. It shows the old and the new wording of each changed rule and names the tasks the change touches, before you apply it; `update --apply` and the `sync` after it name the same tasks. When the instructions already follow a newer catalog than the lock, `check`, `task new`, `task consult`, `task decide` and `task handoff` refuse and point to `openguildkit update`; when the installed catalog changes locked rules, `check` and `sync` say so. `sync` keeps the lock's rules: it rewrites the instructions from the lock and never adopts a newer catalog.
4. Run `openguildkit check` and commit the updated files.

From 0.16.1, also follow "Upgrading from 0.16.1" at the end of the 0.17.0 section of the [changelog](../CHANGELOG.md): run `openguildkit sync` before `check`, and set the agent host before `openguildkit host apply`.

## Add the optional CI coordinator

Use Node.js 22 or later, npm and Git. The GitHub integration also needs an authenticated GitHub CLI.

```sh
npm install --global ./openguildkit-0.17.0.tgz
openguildkit-ci --version
```

The package also provides `openguildkit-ci-agent`. Use the [CI integration guide](../integrations/ci/README.md) to set up the approved profile, rule repository, trusted workflow and Jenkins state directory. Start in observation mode, using the [shared export rule example](../examples/export-expiry/README.md) to verify one project before enabling enforcement.

Before scheduling Jenkins, run `openguildkit-ci check-state --state ./state` with the exact directory and account the job will use. The check creates and removes a temporary hard link. On Windows, choose a persistent NTFS directory. An exFAT directory fails with exit code 2 and a message explaining how to change `--state`. The job repeats the check before contacting GitHub.

To check for a newer pilot package from a machine with GitHub CLI:

```sh
openguildkit-ci releases --repo Sandbox-podcast/OpenGuildKit --channel pilot
```

For CI installs, pin the release tag and archive hash. The [guard workflow template](../integrations/github/openguildkit-guard.yml) downloads the wheel of the tag you set and installs it only when its hash matches the one you copied from `SHA256SUMS.txt`. The workflow templates keep this step until the first release that ships `install.sh`: from that release, they switch to `curl --proto '=https' --tlsv1.2 -fsSL https://github.com/Sandbox-podcast/OpenGuildKit/releases/download/vX.Y.Z/install.sh | sh -s -- --version vX.Y.Z`, pinned to the same tag, with no hash to copy. A pull request runs its own copy of that workflow: protect it with `CODEOWNERS` on `.github/workflows/` or a ruleset that requires it from the default branch ([Protect the check](../integrations/README.md#protect-the-check)), and add `--require-signed` to its guard step to fail while approvals are local. Each consumer repository can use the public release as its distribution source. If using a workflow template that downloads from the consumer repository, set the release download to point to `Sandbox-podcast/OpenGuildKit` or mirror the verified asset under the same tag.
