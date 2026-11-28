"""The launches of the tool registry that host scan judges not fixed to one version (issue #489)."""

import copy
import unittest

from openguildkit import surfaces
from openguildkit.catalog import CatalogError
from openguildkit.tool_registry import _validate_tool, load_tools
from openguildkit.tools import review_facts
from tests.test_tool_registry import local_tool

# The servers of the registry whose launch names no one version (npm, PyPI or Docker), each with the day it was counted.
# On 2026-11-28 the version of each of the 34 launches counted on 2026-11-27 was read in its package registry (the
# latest tag of registry.npmjs.org, the JSON of pypi.org, the tags of Docker Hub and ghcr.io, the tags of GitHub for a
# Git source) and written with its pin_read: none is left. A launch that floats again fails the test below.
UNFIXED: dict[str, str] = {}


def unfixed_servers() -> set[str]:
    found = set()
    for tool in load_tools().values():
        for server in tool["servers"]:
            package = surfaces._package_of(server["command"], server["args"]) if server["transport"] == "stdio" else None
            if package and surfaces._pin(*package)[0] is False:
                found.add(server["id"])
    return found


class RegistryPinTests(unittest.TestCase):
    def test_issue_489_every_fixed_launch_of_the_registry_says_the_day_its_version_was_read(self):
        """Issue #489: the registry wrote no version, so tools apply wrote launches that pull the latest at each start."""
        for tool in load_tools().values():
            for server in tool["servers"]:
                package = surfaces._package_of(server["command"], server["args"]) if server["transport"] == "stdio" else None
                if package and surfaces._pin(*package)[0] and server["id"] not in ("terraform-mcp-server", "mailchimp-marketing-local"):
                    with self.subTest(server=server["id"]):
                        self.assertEqual(server.get("pin_read"), "2026-11-28")
        playwright = next(server for server in load_tools()["playwright"]["servers"] if server["id"] == "playwright-mcp")
        self.assertEqual(playwright["args"], ["@playwright/mcp@0.0.86"])


    def test_the_unfixed_launches_are_the_dated_list_and_no_new_one_joins_it(self):
        """Issue #489: 34 launches of the registry pull the latest version at every start, and nothing stops a 35th."""
        found = unfixed_servers()
        self.assertEqual(sorted(found - UNFIXED.keys()), [],
                         "a launch of the registry names no one version: fix it, or list it in UNFIXED with the day "
                         "it was counted")
        self.assertEqual(sorted(UNFIXED.keys() - found), [],
                         "these launches are fixed now: remove them from UNFIXED")
        self.assertEqual(len(found), 0)

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
