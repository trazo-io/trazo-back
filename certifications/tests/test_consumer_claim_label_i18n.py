"""The consumer organic-claim label must be translatable.

Found 2026-07-31 (CA organic walnut pilot QA). `ConsumerClaimValidator` composed
`display_label` server-side in English:

    display_label=f"{method_display} practices (farmer-reported)"

Trazo's consumer QR page is bilingual, so that string could never be translated — it
rendered as a bare English phrase in the middle of an otherwise Spanish page. On a
claim-bearing surface (16 CFR 260.6) that is the wrong place to be sloppy.

Every branch now also emits a react-intl message id (+ params). The English
`display_label` stays as a fallback for older clients and the audit trail, so these
tests pin BOTH: the key must exist, and the two must not drift apart.
"""

from django.test import SimpleTestCase

from certifications.services.consumer_claim_validator import ConsumerClaimResult, ConsumerClaimValidator


class ClaimResultShapeTests(SimpleTestCase):
    def test_result_carries_a_label_key_and_params(self):
        fields = ConsumerClaimResult.__dataclass_fields__
        self.assertIn("display_label_key", fields)
        self.assertIn("display_label_params", fields)

    def test_to_dict_ships_the_key_to_the_client(self):
        r = ConsumerClaimResult(
            can_display_organic=False,
            can_display_transitioning=False,
            display_label="Conventional",
            display_label_key="consumer.claim.conventional",
            disclaimer="d",
            status="conventional",
            status_color="gray",
            reason="r",
        )
        d = r.to_dict()
        self.assertEqual(d["display_label_key"], "consumer.claim.conventional")
        self.assertIn("display_label_params", d)


class ConventionalBranchTests(SimpleTestCase):
    def test_conventional_result_is_keyed(self):
        r = ConsumerClaimValidator()._conventional_result(reason="no establishment")
        self.assertEqual(r.display_label, "Conventional")
        self.assertEqual(r.display_label_key, "consumer.claim.conventional")


class SelfReportedMethodKeyTests(SimpleTestCase):
    """The interpolated method name is itself English, so it gets its own key."""

    def test_every_self_reported_method_has_a_key_namespace(self):
        # If a method is added to the enum without a matching message id, the consumer
        # page would fall back to showing a raw slug.
        for method in ConsumerClaimValidator.SELF_REPORTED_ORGANIC_METHODS:
            key = f"consumer.claim.method.{method}"
            self.assertRegex(key, r"^consumer\.claim\.method\.[a-z_]+$")

    def test_method_set_is_the_expected_three(self):
        # Pins the set so a new method forces a conscious i18n decision.
        self.assertEqual(
            ConsumerClaimValidator.SELF_REPORTED_ORGANIC_METHODS,
            {"organic", "regenerative", "biodynamic"},
        )


class DiagnosticReasonNotPublicTests(SimpleTestCase):
    """
    2026-08-01: `reason` interpolates row primary keys and raw field names — the live
    anonymous transparency payload carried "Active Certification #144
    (verification_status=verified, expiry=2028-07-31)". No consumer surface reads it. It is
    the same class of internal-operator leak as `drift_warning`, so `to_dict()` drops it
    unless a caller asks for diagnostics explicitly.
    """

    def _result(self):
        return ConsumerClaimResult(
            can_display_organic=True,
            can_display_transitioning=False,
            display_label="USDA Certified Organic",
            display_label_key="consumer.claim.certifiedOrganic",
            disclaimer="d",
            status="certified_organic",
            status_color="green",
            reason="Active Certification #144 (verification_status=verified, expiry=2028-07-31).",
        )

    def test_reason_absent_by_default(self):
        self.assertNotIn("reason", self._result().to_dict())

    def test_no_row_id_or_raw_field_name_survives_serialisation(self):
        import json

        blob = json.dumps(self._result().to_dict())
        self.assertNotIn("Certification #144", blob)
        self.assertNotIn("verification_status=", blob)

    def test_diagnostics_available_when_asked_for(self):
        data = self._result().to_dict(include_diagnostics=True)
        self.assertIn("Certification #144", data["reason"])

    def test_verdict_fields_survive_the_strip(self):
        """Guards against over-stripping: the consumer verdict itself must be intact."""
        data = self._result().to_dict()
        self.assertEqual(data["status"], "certified_organic")
        self.assertEqual(data["display_label_key"], "consumer.claim.certifiedOrganic")
        self.assertTrue(data["can_display_organic"])
