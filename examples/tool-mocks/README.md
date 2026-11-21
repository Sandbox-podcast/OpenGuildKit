# Tools with mocks

A fictional company, Acme Support Portal, names the tools it works with: Jira, GitHub, Snyk, Factorial, Tempo and Gryzzly. This example connects their mocks and plays what an agent does with them, without an account, a key or a network.

```bash
python examples/tool-mocks/demo.py
```

The script:

1. initialises a project whose profile lists the tools;
2. runs `openguildkit tools recommend`: five tools have a mock, and Gryzzly, which has no MCP server on record, is reported with its API;
3. connects the mocks for Codex (`.codex/config.toml`) and for Claude Code (`.mcp.json`) with `openguildkit tools apply ... --mock`;
4. talks to each mock over MCP, as a host does: it finds the ticket SUP-142, reads the alert on a synthetic dependency, checks who is away during the sprint and logs an hour and a half on the ticket;
5. shows the journal of the calls (`mock-calls.jsonl`), which a test can assert on.

To try the same servers in a host, run `openguildkit tools apply jira tempo --mock` in your own project and ask the agent for the ticket about the export. Replace `--mock` by nothing to plan the real servers; see [docs/tools.md](../../docs/tools.md).

Every name, ticket, amount and address in the mocks is invented.
