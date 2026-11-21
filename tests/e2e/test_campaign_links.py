"""Build a tagged campaign link from the installed command, as a marketer would."""

from .test_cli_flow import CliTestCase


class CampaignLinkTests(CliTestCase):
    def test_utm_prints_the_tagged_link_and_refuses_a_value_with_capitals(self):
        self.init_example()
        common = ["deliverable", "utm", "--campaign", "spring-launch", "--source", "linkedin", "--medium", "social"]
        result = self.run_cli(*common, "--url", "https://www.example.test/webinar")
        self.assertEqual(result.stdout.strip(), "https://www.example.test/webinar"
                                                "?utm_source=linkedin&utm_medium=social&utm_campaign=spring-launch")
        refused = self.run_cli("deliverable", "utm", "--url", "https://www.example.test/", "--campaign", "Spring",
                               "--source", "linkedin", "--medium", "social", expect=1)
        self.assertTrue(refused.stderr.startswith("OpenGuildKit: "), refused.stderr)
        self.assertNotIn("Traceback", refused.stderr)
