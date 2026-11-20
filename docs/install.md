# Install OpenGuildKit from GitHub Releases

Download the assets for the [release you want to deploy](https://github.com/Sandbox-podcast/OpenGuildKit/releases). The Python wheel provides the catalog, project setup and specialist reviews. The optional Node package coordinates checks across GitHub Actions and Jenkins.

## Download and verify

Download the wheel, the optional Node archive and `SHA256SUMS.txt`. With GitHub CLI, the first combined release can be downloaded with:

```sh
gh release download v0.16.0 --repo Sandbox-podcast/OpenGuildKit --pattern 'openguildkit-0.16.0-py3-none-any.whl' --pattern 'openguildkit-0.16.0.tgz' --pattern SHA256SUMS.txt
```

On Linux use `sha256sum -c SHA256SUMS.txt`. On macOS use `shasum -a 256 -c SHA256SUMS.txt`. On Windows use `Get-FileHash .\openguildkit-0.16.0-py3-none-any.whl, .\openguildkit-0.16.0.tgz -Algorithm SHA256` in PowerShell and compare each hash to the corresponding line in `SHA256SUMS.txt`.

## Install the Python CLI

Use Python 3.11 or later. Save the path to the wheel before switching to the project directory. On Linux or macOS:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install ./openguildkit-0.16.0-py3-none-any.whl
openguildkit catalog
```

On Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\openguildkit-0.16.0-py3-none-any.whl
.\.venv\Scripts\openguildkit.exe catalog
```

From the project to equip, run `openguildkit init` and then `openguildkit check`. On Windows, use the full path to `openguildkit.exe` from the installed environment, or activate that environment first. Commit the generated profile and instructions for the team.

## Add the optional CI coordinator

Use Node.js 22 or later, npm and Git. The GitHub integration also needs an authenticated GitHub CLI.

```sh
npm install --global ./openguildkit-0.16.0.tgz
openguildkit-ci --version
```

The package also provides `openguildkit-ci-agent`. Use the [CI integration guide](../integrations/ci/README.md) to set up the approved profile, rule repository, trusted workflow and Jenkins state directory. Start in observation mode, using the [shared export rule example](../examples/export-expiry/README.md) to verify one project before enabling enforcement.

To check for a newer pilot package from a machine with GitHub CLI:

```sh
openguildkit-ci releases --repo Sandbox-podcast/OpenGuildKit --channel pilot
```

For CI installs, pin the release tag and archive hash. Each consumer repository can use the public release as its distribution source. If using a workflow template that downloads from the consumer repository, set the release download to point to `Sandbox-podcast/OpenGuildKit` or mirror the verified asset under the same tag.
