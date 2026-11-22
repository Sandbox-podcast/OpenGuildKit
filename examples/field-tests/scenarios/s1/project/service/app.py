"""Support portal service (synthetic data)."""

REQUESTS = [
    {"id": 1, "owner": "user-a@example.test", "status": "open", "next_step": "Waiting for support"},
    {"id": 2, "owner": "user-b@example.test", "status": "closed", "next_step": "None"},
    {"id": 3, "owner": "user-a@example.test", "status": "closed", "next_step": "None"},
]


def requests_for(user: str) -> list[dict]:
    """Return only the requests the signed-in user opened."""
    return [request for request in REQUESTS if request["owner"] == user]
