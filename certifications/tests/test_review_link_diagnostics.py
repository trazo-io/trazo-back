"""Why a review link refused, and who pays for the refusal.

Two defects behind the 2026-09-06 audit's T04, where a link created minutes earlier failed to
open while the farmer's dashboard showed it active:

  * the landing pages shared the 50/hour `anon` throttle bucket, and each page load costs TWO
    requests (metadata + readiness) — so a certifier's office behind one NAT address got 25
    loads an hour before being cut off; and
  * a refusal left no trace at all, so nobody could tell an expired link from a revoked one
    from a buyer token pasted into the certifier route.

The 404-for-everything contract toward the CALLER is deliberate and unchanged (see
`_resolve_link_or_404`). What changes is that the operator can now see the reason in the log,
and that a throttle is no longer charged against the shared anonymous bucket.
"""

from datetime import timedelta

from django.http import Http404
from django.test import TestCase
from django.utils import timezone

from certifications.models import CertifierAccessLink
from certifications.views import CertifierReviewThrottle, _resolve_link_or_404
from company.models import Company, Establishment


def throttle_decorator_for(view_name: str) -> str:
    """The `@throttle_classes([...])` line that applies to `view_name`.

    Two things this deliberately is NOT:

    * a fixed character window before the `def` — that reaches back into the PREVIOUS endpoint's
      decorators and reports its scope as this one's; and
    * the whole decorator block — the block contains prose, and a `assertNotIn(<class>, block)`
      then fails on a COMMENT explaining why that class was not used. A guard that forbids
      naming the thing it excludes makes the exclusion undocumentable.
    """
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "views.py").read_text()
    index = text.index(f"def {view_name}(")
    start = text.rindex("@api_view", 0, index)
    match = re.search(r"^@throttle_classes\(\[(.*?)\]\)$", text[start:index], re.M)
    assert match, f"{view_name} has no @throttle_classes decorator"
    return match.group(1)


class ReviewThrottleScopeTests(TestCase):
    """The review pages must not spend the shared anonymous budget."""

    def test_the_review_throttle_has_its_own_scope(self):
        self.assertEqual(CertifierReviewThrottle.scope, "certifier_review")

    def test_the_scope_has_a_configured_rate_in_every_settings_module(self):
        """A scope with no rate raises `ImproperlyConfigured` at request time — and `dev.py`
        REDEFINES `DEFAULT_THROTTLE_RATES` wholesale rather than extending base, which is how a
        scope added to base alone has broken dev before."""
        from django.conf import settings

        rates = settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]
        self.assertIn("certifier_review", rates)
        self.assertTrue(rates["certifier_review"])

    def test_base_settings_also_define_it(self):
        import re
        from pathlib import Path

        base = Path(__file__).resolve().parents[2] / "backend" / "settings" / "base.py"
        self.assertIsNotNone(
            re.search(r'"certifier_review":\s*"[^"]+"', base.read_text()),
            "base.py must define the rate; prod reads it from there",
        )

    def test_the_landing_endpoints_are_not_on_the_shared_anon_scope(self):
        """Enumerated from the module, so a NEW landing endpoint added on `AnonRateThrottle`
        fails here rather than quietly costing a certifier their page loads."""
        for view in (
            "certifier_review_metadata",
            "certifier_review_readiness",
            "buyer_review_metadata",
        ):
            self.assertIn(
                "CertifierReviewThrottle",
                throttle_decorator_for(view),
                f"{view} is not on the review throttle scope",
            )

    def test_the_dossier_download_keeps_the_tighter_default(self):
        """⛔ The expensive one must NOT ride the landing-page scope.

        `certifier_review_dossier` streams a PDF that takes ~a minute to build on a
        12-production farm and pins a gthread worker while it does. Sweeping it into the 240/hour
        landing scope — which exists because cheap page loads cost two requests each — would
        quadruple the anonymous ceiling on the most expensive route in the product as a side
        effect. The cheap status poll beside it has its own generous scope, which is what a
        waiting reviewer actually hits.
        """
        decorators = throttle_decorator_for("certifier_review_dossier")
        self.assertIn("AnonRateThrottle", decorators)
        self.assertNotIn("CertifierReviewThrottle", decorators)


class ReviewRefusalLoggingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Diag Co")
        self.establishment = Establishment.objects.create(name="Diag Farm", company=self.company, state="OR")

    def _link(self, **kwargs):
        defaults = dict(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            label="Diagnostics",
            audience="certifier",
            expires_at=timezone.now() + timedelta(days=30),
        )
        defaults.update(kwargs)
        return CertifierAccessLink.objects.create(**defaults)

    def test_an_expired_link_logs_the_reason(self):
        link = self._link(expires_at=timezone.now() - timedelta(days=1))
        with self.assertLogs("certifications.views", level="WARNING") as captured:
            with self.assertRaises(Http404):
                _resolve_link_or_404(link.token)
        self.assertIn("reason=expired", " ".join(captured.output))

    def test_a_revoked_link_logs_the_reason(self):
        link = self._link()
        link.revoke()
        with self.assertLogs("certifications.views", level="WARNING") as captured:
            with self.assertRaises(Http404):
                _resolve_link_or_404(link.token)
        self.assertIn("reason=revoked", " ".join(captured.output))

    def test_a_cross_audience_token_logs_that_it_did_not_match(self):
        buyer = self._link(audience="buyer")
        with self.assertLogs("certifications.views", level="WARNING") as captured:
            with self.assertRaises(Http404):
                _resolve_link_or_404(buyer.token, audience="certifier")
        joined = " ".join(captured.output)
        self.assertIn("audience=certifier", joined)
        self.assertIn("no link with this token", joined)

    def test_the_log_never_contains_the_token_itself(self):
        """⛔ A log line that carries the token is a second copy of the credential: anyone with
        log access could open the operation's dossier."""
        link = self._link()
        link.revoke()
        with self.assertLogs("certifications.views", level="WARNING") as captured:
            with self.assertRaises(Http404):
                _resolve_link_or_404(link.token)
        joined = " ".join(captured.output)
        self.assertNotIn(link.token, joined)
        self.assertIn("token_sha256_12=", joined)

    def test_an_active_link_logs_nothing(self):
        """The mirror: a log on every resolve would bury the refusals it exists to surface."""
        link = self._link()
        with self.assertNoLogs("certifications.views", level="WARNING"):
            self.assertEqual(_resolve_link_or_404(link.token).pk, link.pk)


class ReviewLinkAudienceFilterTests(TestCase):
    """`?audience=` on the management list. Both cards render from one endpoint and split it
    client-side, which is a rendering convention rather than a contract."""

    def setUp(self):
        from users.models import User, WorksIn

        self.user = User.objects.create_user(email="aud@test.com", password="x")
        self.company = Company.objects.create(name="Aud Co")
        self.establishment = Establishment.objects.create(name="Aud Farm", company=self.company, state="OR")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        for audience in ("certifier", "buyer"):
            CertifierAccessLink.objects.create(
                establishment=self.establishment,
                token=CertifierAccessLink.generate_token(),
                label=f"{audience} link",
                audience=audience,
                expires_at=timezone.now() + timedelta(days=30),
            )
        self.url = f"/api/companies/{self.company.id}/establishments/{self.establishment.id}/certifier-links/"

    def _get(self, query=""):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=self.user)
        response = client.get(f"{self.url}{query}")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        return body["results"] if isinstance(body, dict) and "results" in body else body

    def test_unfiltered_returns_both_audiences(self):
        """The default is unchanged, so existing callers keep working."""
        audiences = {row["audience"] for row in self._get()}
        self.assertEqual(audiences, {"certifier", "buyer"})

    def test_filtering_to_certifier_excludes_buyer_links(self):
        rows = self._get("?audience=certifier")
        self.assertTrue(rows)
        self.assertEqual({row["audience"] for row in rows}, {"certifier"})

    def test_filtering_to_buyer_excludes_certifier_links(self):
        rows = self._get("?audience=buyer")
        self.assertTrue(rows)
        self.assertEqual({row["audience"] for row in rows}, {"buyer"})

    def test_an_unknown_audience_is_ignored_rather_than_returning_nothing(self):
        """Fail open on a bad filter: silently returning zero rows would read to the farmer as
        'you have no links', which is a worse lie than ignoring the parameter."""
        self.assertEqual(len(self._get("?audience=nonsense")), 2)
