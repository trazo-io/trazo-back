"""Claim safety for the two emails every new grower receives on day one.

The signup emails are collateral, and collateral drifts out of step with the product it
describes. On 2026-08-19 a pilot dress rehearsal ran a real signup and read what actually
arrived:

  - "Blockchain-recorded production data" (verification) and "Build consumer trust with
    blockchain-recorded data" (welcome, twice). BLOCKCHAIN_ENABLED is False and the $15/mo
    add-on is withdrawn (is_active=False). The surface was removed; the collateral kept
    selling it. This is the DATA != UI != COLLATERAL class.
  - "20 pre-configured US crops", when populate_usda_crop_types ships 33.
  - The welcome email's ONLY button pointed at https://producer.trazo.io, which does not
    resolve. Every producer who clicked the primary CTA hit NXDOMAIN. The plain-text half of
    the same email already said app.trazo.io.

These assert the templates, not a rendered message, because the failure mode is someone
editing the copy — and a template that never renders in tests still lands in an inbox.
"""

from pathlib import Path

from django.test import TestCase

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "emails"

# The mails a brand-new grower receives before they have logged anything.
ONBOARDING_TEMPLATES = (
    "verification.txt",
    "verification.html",
    "welcome.txt",
    "welcome.html",
    "welcome_invited.txt",
    "welcome_invited.html",
)

# Hosts an onboarding email is allowed to send someone to. producer.trazo.io is deliberately
# absent: it has never resolved.
ALLOWED_TRAZO_HOSTS = {"trazo.io", "www.trazo.io", "app.trazo.io", "consumer.trazo.io"}


class OnboardingEmailClaimTests(TestCase):
    def _read(self, name):
        return (TEMPLATE_DIR / name).read_text()

    def test_no_onboarding_email_sells_the_withdrawn_blockchain_addon(self):
        offenders = []
        for name in ONBOARDING_TEMPLATES:
            for lineno, line in enumerate(self._read(name).splitlines(), 1):
                if "blockchain" in line.lower():
                    offenders.append(f"{name}:{lineno}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "Blockchain is disabled and the add-on is withdrawn; these onboarding emails "
            "still advertise it:\n" + "\n".join(offenders),
        )

    def test_no_onboarding_email_points_at_a_host_that_does_not_resolve(self):
        import re

        offenders = []
        for name in ONBOARDING_TEMPLATES:
            for lineno, line in enumerate(self._read(name).splitlines(), 1):
                for host in re.findall(r"https?://([a-z0-9.-]*trazo\.io)", line):
                    if host not in ALLOWED_TRAZO_HOSTS:
                        offenders.append(f"{name}:{lineno}: {host}")
        self.assertEqual(
            offenders,
            [],
            "Onboarding email links to a Trazo host outside the known-good set "
            f"{sorted(ALLOWED_TRAZO_HOSTS)}:\n" + "\n".join(offenders),
        )

    def test_crop_count_in_the_welcome_email_matches_the_seeder(self):
        from carbon.management.commands.populate_usda_crop_types import Command

        actual = len(Command()._get_crop_type_data())
        import re

        for name in ("welcome.txt", "welcome.html"):
            body = self._read(name)
            claimed = [int(n) for n in re.findall(r"(\d+)\s+pre-configured US crops", body)]
            self.assertTrue(claimed, f"{name} no longer states a crop count — update this test")
            for n in claimed:
                self.assertEqual(
                    n,
                    actual,
                    f"{name} claims {n} pre-configured US crops; the seeder ships {actual}.",
                )
