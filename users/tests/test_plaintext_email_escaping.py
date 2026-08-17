"""Plain-text email templates must not HTML-escape their contents.

Found on the 2026-08-09 cold-start walkthrough: the signup verification email's
text/plain part contained

    ...verifyemail?email=dana%40example.com&amp;code=V80HOZ

because Django's autoescape is on by default and the template is a `.txt`. Any mail
client that renders the plain-text alternative hands Django `amp;code=...`, so `code`
arrives empty and verification fails. The HTML part is unaffected — which is exactly why
it went unnoticed.

Four of the six plain-text templates interpolate a link, `password_reset.txt` among them:
a broken reset link locks a user out with no way back in.

The same escaping mangles operator names — `O'Brien` renders as `O&#x27;Brien`.

This tests the CLASS, not the instance: every plain-text email template, so a new one
cannot reintroduce it.
"""

import glob
import os

from django.template.loader import render_to_string
from django.test import TestCase

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "emails")

# A link with a query string and a name with an apostrophe — the two things Django's
# HTML autoescaping corrupts in a plain-text body.
LINK = "http://app.localhost:3000/auth/verifyemail?email=a%40b.com&code=V80HOZ"
NAME = "O'Brien"

HTML_ENTITIES = ("&amp;", "&#x27;", "&#39;", "&quot;", "&lt;", "&gt;")


class _User:
    first_name = NAME
    last_name = NAME
    email = "a@b.com"

    def get_full_name(self):
        return f"{NAME} {NAME}"


def _context():
    """One permissive context — unused keys are simply ignored by each template."""
    return {
        "user": _User(),
        "inviter": _User(),
        "user_type": "producer",
        "verification_code": "V80HOZ",
        "verification_link": LINK,
        "reset_link": LINK,
        "password_reset_link": LINK,
        "invitation_link": LINK,
        "login_link": LINK,
        "company_name": "O'Brien Ranch",
        "company": "O'Brien Ranch",
        "role": "Farm Manager",
        "expiry_hours": 48,
    }


class PlaintextEmailEscapingTests(TestCase):
    def test_no_plaintext_email_template_html_escapes(self):
        templates = sorted(glob.glob(os.path.join(TEMPLATE_DIR, "*.txt")))
        self.assertTrue(templates, "no plain-text email templates found — did they move?")

        offenders = []
        for path in templates:
            name = f"emails/{os.path.basename(path)}"
            rendered = render_to_string(name, _context())
            found = [entity for entity in HTML_ENTITIES if entity in rendered]
            if found:
                offenders.append(f"{name}: {found}")

        self.assertEqual(
            offenders,
            [],
            "plain-text email templates are HTML-escaping their contents — query strings "
            "and apostrophes will be corrupted in the text/plain part: " + "; ".join(offenders),
        )

    def test_verification_link_survives_intact(self):
        rendered = render_to_string("emails/verification.txt", _context())
        self.assertIn(LINK, rendered)
        self.assertNotIn("&amp;code=", rendered)
