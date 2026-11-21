# Install OpenGuildKit from GitHub Releases

Download the assets for the [release you want to deploy](https://github.com/Sandbox-podcast/OpenGuildKit/releases). The Python wheel provides the catalog, project setup and specialist reviews. The optional Node package coordinates checks across GitHub Actions and Jenkins.

## Download and verify

Download the wheel, the optional Node archive and `SHA256SUMS.txt`. For v0.16.1, use the following GitHub CLI command.

```sh
gh release download v0.16.1 --repo Sandbox-podcast/OpenGuildKit --pattern 'openguildkit-0.16.1-py3-none-any.whl' --pattern 'openguildkit-0.16.1.tgz' --pattern SHA256SUMS.txt
```

On Linux use `sha256sum -c SHA256SUMS.txt`. On macOS use `shasum -a 256 -c SHA256SUMS.txt`. On Windows use `Get-FileHash .\openguildkit-0.16.1-py3-none-any.whl, .\openguildkit-0.16.1.tgz -Algorithm SHA256` in PowerShell and compare each hash to the corresponding line in `SHA256SUMS.txt`.

## How the release assets are built

Pushing a tag `vX.Y.Z` runs `.github/workflows/release.yml` on GitHub Actions, on `ubuntu-latest`, from the tagged commit. The workflow stops if the tag differs from the version in `pyproject.toml` or `integrations/ci/package.json`. It builds the wheel with Python 3.13 (`python -m build --wheel`) and the Node archive with Node.js 22 (`npm pack ./integrations/ci`). It writes `SHA256SUMS.txt` with `sha256sum`, one line per file, then attaches the three files to the release of the tag. When that release does not exist yet, the workflow creates it as a draft, which a maintainer reviews and publishes. The run log on the Actions tab prints the hashes it computed.

## Install the Python CLI

Use Python 3.11 or later. Save the path to the wheel before switching to the project directory. On Linux or macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./openguildkit-0.16.1-py3-none-any.whl
openguildkit catalog
```

On Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\openguildkit-0.16.1-py3-none-any.whl
.\.venv\Scripts\openguildkit.exe catalog
```

Check the version you installed with `openguildkit --version`. From the project to equip, run `openguildkit init` and then `openguildkit check`. On Windows, use the full path to `openguildkit.exe` from the installed environment, or activate that environment first. Commit the generated profile, `.openguildkit/catalog.lock.json` and the instructions for the team.

## Set up the agent

The wheel ships the agent skill and the subagents (board, market analyst, dependency watch) of the same version. From the project:

```sh
openguildkit integrations --host claude-code   # .claude/skills/openguildkit and .claude/agents/ (guild-board, market-analyst, dependency-watch)
openguildkit integrations --host codex         # .agents/skills/openguildkit
openguildkit integrations --host other         # .agents/skills/openguildkit, for another agent
```

Add `--user` to install them in your home folder for every project. A file you changed is kept and reported; `--force` replaces it and saves your version as `.previous`. Each folder gets `openguildkit-version.txt` with the installed version, or the name of the file kept at another version. `openguildkit init` asks for the agent host and the board guard (`observe` unless you choose otherwise) and, when the host is Claude Code or Codex, prints `openguildkit host apply` as the next step: it installs the host settings and hooks. With the host `other` (the default), OpenGuildKit writes no host settings: see [other agents](../integrations/README.md#other-agents) for the whole path. For a project set up before, set `"host"` in `.openguildkit/project.json` and run the same command. The hooks of the board guard call `openguildkit` by name: start the agent from the activated environment, or install the CLI on the PATH (for example with `pipx`). `openguildkit host check` reports the guard as `missing` when the command is not on the PATH.

## Upgrade

1. Download and verify the new release assets as above, then `python -m pip install --upgrade ./openguildkit-NEW-py3-none-any.whl` and check `openguildkit --version`.
2. Run `openguildkit integrations --host ...` again to update the skill and subagent.
3. Run `openguildkit update` to see the date of the new catalog, the number of records it changes and what it changes for the project, and `openguildkit update --apply` once the team agrees. Tasks consulted under the previous rules are listed.
4. Run `openguildkit check` and commit the updated files.

## Add the optional CI coordinator

Use Node.js 22 or later, npm and Git. The GitHub integration also needs an authenticated GitHub CLI.

```sh
npm install --global ./openguildkit-0.16.1.tgz
openguildkit-ci --version
```

The package also provides `openguildkit-ci-agent`. Use the [CI integration guide](../integrations/ci/README.md) to set up the approved profile, rule repository, trusted workflow and Jenkins state directory. Start in observation mode, using the [shared export rule example](../examples/export-expiry/README.md) to verify one project before enabling enforcement.

Before scheduling Jenkins, run `openguildkit-ci check-state --state ./state` with the exact directory and account the job will use. The check creates and removes a temporary hard link. On Windows, choose a persistent NTFS directory. An exFAT directory fails with exit code 2 and a message explaining how to change `--state`. The job repeats the check before contacting GitHub.

To check for a newer pilot package from a machine with GitHub CLI:

```sh
openguildkit-ci releases --repo Sandbox-podcast/OpenGuildKit --channel pilot
```

For CI installs, pin the release tag and archive hash. The [guard workflow template](../integrations/github/openguildkit-guard.yml) downloads the wheel of the tag you set and installs it only when its hash matches the one you copied from `SHA256SUMS.txt`. Each consumer repository can use the public release as its distribution source. If using a workflow template that downloads from the consumer repository, set the release download to point to `Sandbox-podcast/OpenGuildKit` or mirror the verified asset under the same tag.
