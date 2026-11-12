"""The server sends Sentry no request body, no query string and no credential in a path (OV-SEC-C17)."""

import ast
from pathlib import Path

from django.test import SimpleTestCase

from backend.sentry_scrub import scrub_event, scrub_url

TOKEN = "Zq9-review-link-secret-0123456789abcdef"
PROD = Path(__file__).resolve().parents[1] / "settings" / "prod.py"


class SentryScrubTests(SimpleTestCase):
    def test_review_and_invitation_paths_are_masked(self):
        self.assertEqual(
            scrub_url(f"https://api.trazo.io/api/certifier-review/{TOKEN}/documents/7/"),
            "https://api.trazo.io/api/certifier-review/[redacted]/documents/7/",
        )
        self.assertEqual(scrub_url(f"/api/buyer-review/{TOKEN}/"), "/api/buyer-review/[redacted]/")
        self.assertEqual(scrub_url(f"/api/invitation/{TOKEN}/accept/"), "/api/invitation/[redacted]/accept/")
        self.assertEqual(scrub_url("/api/users/me/"), "/api/users/me/")

    def test_an_event_keeps_where_it_failed_and_loses_every_secret(self):
        event = scrub_event(
            {
                "request": {
                    "url": f"https://api.trazo.io/api/certifier-review/{TOKEN}/?token={TOKEN}",
                    "query_string": f"token={TOKEN}",
                    "data": {"email": "grower@example.com", "code": "AB12CD"},
                    "cookies": {"access": TOKEN},
                    "method": "GET",
                },
                "breadcrumbs": {"values": [{"category": "httplib", "data": {"url": f"/api/invitation/{TOKEN}/"}}]},
            }
        )
        sent = repr(event)
        self.assertNotIn(TOKEN, sent)
        self.assertNotIn("grower@example.com", sent)
        self.assertNotIn("AB12CD", sent)
        self.assertEqual(event["request"]["method"], "GET")
        self.assertEqual(event["request"]["url"], "https://api.trazo.io/api/certifier-review/[redacted]/")

    def test_prod_wires_it(self):
        call = next(
            node
            for node in ast.walk(ast.parse(PROD.read_text(encoding="utf-8")))
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "init"
        )
        kwargs = {kw.arg: kw.value for kw in call.keywords}
        self.assertIs(kwargs["send_default_pii"].value, False)
        self.assertEqual(kwargs["max_request_body_size"].value, "never")
        self.assertEqual(kwargs["before_send"].id, "scrub_event")
        self.assertEqual(kwargs["before_send_transaction"].id, "scrub_event")
