# Example: market dossier

`support-portals.json` is a fictional dossier for the [request status example](../request-status/). Copy it to `.openguildkit/market/support-portals.json` in a project, then:

```bash
openguildkit market check support-portals
openguildkit market due support-portals
openguildkit task consult request-status --answers answers.json --market support-portals
```

Product and Marketing cite an observation as evidence with `{"source": "public", "ref": "market:support-portals/a-status-page", ...}`, or a verified change with `market:support-portals/change-1`. The vendor names and sources are invented.
