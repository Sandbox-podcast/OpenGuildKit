import unittest

from app import requests_for


class RequestAccessTests(unittest.TestCase):
    def test_users_only_see_their_requests(self):
        self.assertEqual([request["id"] for request in requests_for("user-a@example.test")], [1, 3])


if __name__ == "__main__":
    unittest.main()
