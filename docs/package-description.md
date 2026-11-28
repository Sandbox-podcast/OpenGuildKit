# OpenGuildKit

For: anyone who finds the package and decides whether to install it.

OpenGuildKit is an open source framework for teams that build with AI agents. Choose the rules your agents should follow and get reviews from the disciplines affected by a change before you approve it.

This is the description of the Python package. The [project on GitHub](https://github.com/Sandbox-podcast/OpenGuildKit) has the documentation, the releases and the issues.

## Install

OpenGuildKit is not published on PyPI. Download the wheel of a [GitHub release](https://github.com/Sandbox-podcast/OpenGuildKit/releases) and check it against the release's `SHA256SUMS.txt`. Then install it with pipx (`pipx install ./openguildkit-X.Y.Z-py3-none-any.whl`) or uv (`uv tool install ./openguildkit-X.Y.Z-py3-none-any.whl`): both put `openguildkit` on the PATH. The [install guide](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/install.md) gives the download command, the hash check on each system and the install in a virtual environment. Python 3.11 or later; no runtime dependency.

## Use

From the repository of your project:

```sh
openguildkit init
openguildkit host apply
openguildkit check
openguildkit ui
```

`init` asks the stack, the sector, personal data and each norm they imply, then writes the profile and, in `AGENTS.md`, the task workflow and the rule packs by rule ID. `host apply` installs the settings and hooks of Claude Code, Codex or Gemini CLI; skip it for another agent. `ui` opens the project in the browser, on 127.0.0.1; approvals stay in your terminal. Every change then follows the [task workflow](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/workflow.md): the agent opens a task, the brains of the disciplines it concerns review it, you decide, and the agent delivers the approved scope.

## Documentation

- [README](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/README.md) and [French README](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/README.fr.md)
- [Changelog](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/CHANGELOG.md)
- [Specialist brains](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/brains.md) and [glossary](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/docs/glossary.md)
- [Security policy](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/SECURITY.md) and [MIT license](https://github.com/Sandbox-podcast/OpenGuildKit/blob/main/LICENSE)
