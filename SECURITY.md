# Security policy

## Reporting a vulnerability

Report vulnerabilities privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue.

Include the version or commit, the command you ran, what happened and what you expected. The maintainer acknowledges the report within 14 days, then agrees on a disclosure date with the reporter.

OpenGuildKit has one maintainer today (see [GOVERNANCE.md](GOVERNANCE.md)). When the maintainer is away, the report stays private in the **Security** tab, where only the maintainer and the reporter can read it, until the maintainer answers. Keep it private in the meantime; adding a comment to the report brings it back to the maintainer's notifications.

## In scope

- The CLI writing outside the project directory, following symbolic links, or corrupting project state.
- Ways for task text, review JSON, research results or catalog records to escape their data blocks and become instructions to the host agent.
- Ways for an agent to approve a task without a person at a terminal, beyond running commands in a shell the person controls.
- Catalog records that would lead an agent to weaken a project's security (for example, a rule that disables a control).

## Out of scope

- Behavior of the host agent or the model it uses.
- Security of the projects that use OpenGuildKit. The packs help teams ask the right questions; they are not a security audit.

## Supported versions

Only the latest release receives fixes during the 0.x series.
