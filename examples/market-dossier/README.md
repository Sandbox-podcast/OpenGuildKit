# Example: market dossier

`support-portals.json` is a fictional dossier for the [request status example](../request-status/). Copy it to `.openguildkit/market/support-portals.json` in a project, then:

```bash
openguildkit market check support-portals
openguildkit market due support-portals
openguildkit market provided support-portals --url https://example.com/vendor-a/release-notes --by CM   # local-only: a person reviewed it
openguildkit task consult request-status --answers answers.json --market support-portals
```

Product and Marketing cite an observation as evidence with `{"source": "public", "ref": "market:support-portals/a-status-page", ...}`, or a verified change with `market:support-portals/change-1`. The vendor names and sources are invented. The project of the example runs under `local-only`, so `market check` flags the change taken from a public page for a person to confirm. The [scheduled market watch](../../integrations/github/openguildkit-market-watch.yml) is tested on this dossier.
