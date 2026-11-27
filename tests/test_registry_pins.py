"""The launches of the tool registry that host scan judges not fixed to one version (issue #489)."""

import copy
import unittest

from openguildkit import surfaces
from openguildkit.catalog import CatalogError
from openguildkit.tools import _validate_tool, load_tools, review_facts
from tests.test_tool_registry import local_tool

# The servers of the registry whose launch names no one version (npm, PyPI or Docker), each with the day it was counted.
# The versions are to be read in the package registry of each (npm view, pip index versions, the Docker Hub tags): none
# was read on 2026-11-27, so none was written. A server leaves this list when its launch is fixed (and its pin_read says
# the day), and the list can only shrink.
UNFIXED = dict.fromkeys((
    "appdynamics-mcp-docker", "auth0-mcp-server", "azure-devops-local", "azure-mcp", "canva-dev-mcp",
    "chrome-devtools-mcp", "contentful-local", "dbt-mcp-local", "discord-mcp-saseq", "gcloud-mcp", "gitguardian-local",
    "github-local", "google-analytics-mcp", "gravitee-apim-mcp", "kubernetes-mcp-server", "mcp-grafana", "mcp-k6",
    "mcp-toolbox-postgres", "monday-api-mcp", "mongodb-mcp-server", "netlify-local", "okta-mcp-server", "playwright-mcp",
    "portainer-mcp", "postman-local", "redis-mcp-server", "redmine-mcp-server-jztan", "smartbear-local",
    "sonarqube-mcp-server", "spark-history-server-mcp", "toggl-local", "wordpress-mcp-adapter", "work-iq-cli",
    "xero-local"), "2026-11-27")


def unfixed_servers() -> set[str]:
    found = set()
    for tool in load_tools().values():
        for server in tool["servers"]:
            package = surfaces._package_of(server["command"], server["args"]) if server["transport"] == "stdio" else None
            if package and surfaces._pin(*package)[0] is False:
                found.add(server["id"])
    return found


class RegistryPinTests(unittest.TestCase):
    def test_the_unfixed_launches_are_the_dated_list_and_no_new_one_joins_it(self):
        """Issue #489: 34 launches of the registry pull the latest version at every start, and nothing stops a 35th."""
        found = unfixed_servers()
        self.assertEqual(sorted(found - UNFIXED.keys()), [],
                         "a launch of the registry names no one version: fix it, or list it in UNFIXED with the day "
                         "it was counted")
        self.assertEqual(sorted(UNFIXED.keys() - found), [],
                         "these launches are fixed now: remove them from UNFIXED")
        self.assertLessEqual(len(found), 34)

    def test_a_fixed_launch_says_the_day_its_version_was_read_and_a_floating_one_does_not(self):
        """Issue #489: tools plan must say the version written and the day it was checked."""
        fixed = local_tool(command="npx", args=["-y", "acme-mcp@1.2.3"], package={"registry": "npm", "name": "acme-mcp"},
                           pin_read="2026-11-27")
        _validate_tool(fixed, "tools/acme")
        server = fixed["servers"][0]
        facts = review_facts(fixed, server)["version"]
        self.assertIn("acme-mcp@1.2.3", facts)
        self.assertIn("2026-11-27", facts)
        floating = copy.deepcopy(fixed)
        floating["servers"][0]["args"] = ["-y", "acme-mcp@latest"]
        del floating["servers"][0]["pin_read"]
        self.assertNotIn("read in the package registry", review_facts(floating, floating["servers"][0])["version"])

    def test_pin_read_is_a_day_that_is_not_in_the_future(self):
        tool = local_tool(command="npx", args=["-y", "acme-mcp@1.2.3"], package={"registry": "npm", "name": "acme-mcp"},
                          pin_read="2999-01-01")
        with self.assertRaises(CatalogError) as caught:
            _validate_tool(tool, "tools/acme")
        self.assertIn("pin_read", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
