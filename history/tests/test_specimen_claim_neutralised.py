"""A fabricated operation may never present a registry-verified organic claim.

WHY THIS IS A RUNTIME TEST AND NOT A FIXTURE TEST
-------------------------------------------------
The 2026-09-06 audit found the seeded Calapooia Bend farm rendering the green
"Verified via USDA Organic Integrity Database" card. Two independent causes:

  1. the fixtures stamped `verification_source="usda_organic_integrity_db"` on invented
     certificates, so `Certification.consumer_display_status` — which correctly requires that
     source before allowing the claim — passed honestly on dishonest data; and
  2. nothing downstream asked whether the OPERATION was a specimen at all.

Correcting the fixtures fixes (1) for databases seeded AFTER the correction. It does nothing
for every database already seeded, for a row an admin edit or a CSV import marks verified, or
for the next fixture somebody writes. So every test in this file constructs the row EXACTLY AS
THE OLD FIXTURES WROTE IT — `verification_status="verified"`,
`verification_source="usda_organic_integrity_db"` — and asserts the runtime refuses the claim
anyway, on every consumer surface including the organic-summary block.

`test_the_fixture_is_the_pre_correction_shape` pins that premise, so this file cannot quietly
become a test of the corrected fixtures.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from certifications.models import Certification
from certifications.serializers import ConsumerCertificationSerializer
from certifications.services.consumer_claim_validator import (
    DISCLAIMER_SPECIMEN,
    ConsumerClaimValidator,
    consumer_certification_status,
    filter_certifications_for_consumer,
)
from company.models import Company, Establishment
from history.models import History
from history.serializers import PublicHistorySerializer
from product.models import Parcel, Product
from users.models import User


def flatten(node, out=None):
    out = out if out is not None else []
    if isinstance(node, dict):
        for v in node.values():
            flatten(v, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            flatten(item, out)
    elif node is not None:
        out.append(str(node))
    return out


class SpecimenClaimMixin:
    def build(self, *, is_demo):
        suffix = "demo" if is_demo else "real"
        self.user = User.objects.create_user(email=f"spec-{suffix}@test.com", password="x")
        self.company = Company.objects.create(name=f"Specimen Co {suffix}")
        self.establishment = Establishment.objects.create(
            name=f"Specimen Farm {suffix}", company=self.company, state="OR", is_demo=is_demo
        )
        self.parcel = Parcel.objects.create(name="Block", establishment=self.establishment, area=4.0)
        self.product = Product.objects.create(name=f"Blueberries {suffix}")
        self.history = History.objects.create(
            name=f"Season {suffix}",
            start_date=timezone.now() - timedelta(days=60),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=100.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # ⛔ EXACTLY the row the pre-2026-09-08 fixtures wrote. Do not "tidy" this to
        # self_reported — that would turn this file into a test of the new fixtures and stop
        # it protecting the databases seeded before them.
        self.cert = Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF Certification Services, LLC",
            effective_date=date(2022, 1, 1),
            expiry_date=date(2030, 12, 31),
            certification_scope="Crops",
            certified_items=["Blueberries"],
            verification_status="verified",
            verification_source="usda_organic_integrity_db",
            verification_source_url="https://organic.ams.usda.gov/integrity/",
            usda_operation_name="Specimen Operation",
        )

    def anonymous_payload(self):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = type("Anon", (), {"is_authenticated": False, "is_superuser": False})()
        return PublicHistorySerializer(self.history, context={"request": request}).data


class SpecimenOperationTests(SpecimenClaimMixin, TestCase):
    def setUp(self):
        self.build(is_demo=True)

    def test_the_fixture_is_the_pre_correction_shape(self):
        """The premise. Without this the rest could pass by testing the corrected fixtures."""
        self.assertEqual(self.cert.verification_status, "verified")
        self.assertEqual(self.cert.verification_source, "usda_organic_integrity_db")
        self.assertEqual(
            self.cert.consumer_display_status,
            "verified_via_database",
            "the MODEL still says verified — that is the point; the consumer layer must refuse it",
        )

    def test_the_consumer_status_helper_downgrades_it(self):
        self.assertEqual(consumer_certification_status(self.cert), "self_reported")

    def test_the_serialised_certification_never_says_verified(self):
        data = ConsumerCertificationSerializer(self.cert).data
        self.assertEqual(data["status"], "self_reported")
        self.assertTrue(data["specimen"])

    def test_the_claim_validator_refuses_the_registry_match(self):
        result = ConsumerClaimValidator().validate(self.history)
        self.assertTrue(result.specimen)
        self.assertFalse(result.oid_matched)
        self.assertEqual(result.disclaimer, DISCLAIMER_SPECIMEN)

    def test_the_claim_source_does_not_name_a_registry_or_a_certificate(self):
        from history.services.claim_resolver import build_organic_claim_evidence, resolve_lot_organic_eligibility

        claim = ConsumerClaimValidator().validate(self.history).to_dict()
        evidence = build_organic_claim_evidence(claim, resolve_lot_organic_eligibility(self.history, None))
        self.assertNotIn("Organic Integrity Database", evidence["source"])
        self.assertNotIn("Certificate on file", evidence["source"])
        self.assertIn("Demonstration data", evidence["source"])

    def test_the_filtered_consumer_list_carries_no_verified_status(self):
        kept = filter_certifications_for_consumer([self.cert])
        statuses = [ConsumerCertificationSerializer(c).data["status"] for c in kept]
        self.assertNotIn("verified_via_database", statuses)

    def test_the_transparency_payload_never_contains_verified_via_database(self):
        """End to end, including the organic-summary block that keys on that literal string."""
        resp = self.client.get(
            f"/api/transparency/{self.history.public_id}/",
            HTTP_USER_AGENT="Mozilla/5.0 (specimen-test)",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertNotIn("verified_via_database", " || ".join(flatten(body)))
        self.assertTrue(
            (body.get("specimen") or {}).get("is_specimen"),
            "the page-level specimen mark must still be present — the claim-point fix does not replace it",
        )

    def test_the_organic_summary_does_not_report_a_verified_operation(self):
        from history.transparency_views import _build_organic_summary

        certs = ConsumerCertificationSerializer(filter_certifications_for_consumer([self.cert]), many=True).data
        claim = ConsumerClaimValidator().validate(self.history).to_dict()
        summary = _build_organic_summary(self.history, certs, self.establishment, claim)
        self.assertNotIn("verified_via_database", " || ".join(flatten(summary)))

    def test_the_public_history_payload_is_clean_too(self):
        """The sibling surface. Marking one endpoint and not the other is the recurring class."""
        self.assertNotIn("verified_via_database", " || ".join(flatten(self.anonymous_payload())))


class RealOperationIsUnaffectedTests(SpecimenClaimMixin, TestCase):
    """The counter-test. A safeguard that downgrades everybody proves nothing."""

    def setUp(self):
        self.build(is_demo=False)

    def test_a_real_operation_keeps_its_verified_status(self):
        self.assertEqual(consumer_certification_status(self.cert), "verified_via_database")
        data = ConsumerCertificationSerializer(self.cert).data
        self.assertEqual(data["status"], "verified_via_database")
        self.assertFalse(data["specimen"])

    def test_a_real_operation_keeps_its_registry_claim(self):
        result = ConsumerClaimValidator().validate(self.history)
        self.assertFalse(result.specimen)
        self.assertTrue(result.oid_matched)
        self.assertNotEqual(result.disclaimer, DISCLAIMER_SPECIMEN)
