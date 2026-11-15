"""Four certification states, six readers, one matrix.

WHY A MATRIX AND NOT MORE PER-SURFACE TESTS
-------------------------------------------
`test_specimen_claim_neutralised.py` already proves a specimen cannot present a registry match,
and it does so surface by surface. That shape catches the leak it was written for and misses the
one that came next: on 2026-09-16 three readers were found asserting certification for a
specimen — `_build_organic_summary` (`certification_verified`), the frontend practices pillar,
and `serializers_consumer` — because each compared `status == "certified_organic"` and the
specimen mark lived in a SEPARATE field none of them read.

So the unit under test here is the whole table, not a surface. Every reader answers for every
state, and a reader that regresses fails in exactly one cell, which is what names it.

The four states are genuinely different facts and must stay distinguishable:

  specimen          `Establishment.is_demo` — the operation itself is invented.
  registry-verified a real farm whose certificate WAS matched against Trazo's copy of the USDA
                    Organic Integrity Database. ⛔ This row is the over-correction guard: a
                    safeguard that downgrades everybody proves nothing, and this is the claim
                    the product legitimately makes.
  producer-reported a real farm holding a real certificate that Trazo has NOT matched. Not a
                    finding against the operation (§ `DISCLAIMER_CERTIFIED_ON_FILE`), and not a
                    verified claim either.
  unknown           nothing established yet. Absence stated as absence, never as a denial.

⛔ Every certificate row below is written the way a PRE-correction fixture wrote it. Do not
"tidy" `verification_status="verified"` to something honest: the runtime has to refuse the claim
on rows that already exist in seeded databases, on a row an admin edit marks verified, and on
the next fixture somebody writes. `test_the_fixtures_are_the_pre_correction_shape` pins that.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from certifications.models import Certification
from certifications.serializers import CertificationSerializer, ConsumerCertificationSerializer
from certifications.services.consumer_claim_validator import (
    DISCLAIMER_CERTIFIED,
    DISCLAIMER_CERTIFIED_ON_FILE,
    DISCLAIMER_SPECIMEN,
    STATUS_SPECIMEN,
    ConsumerClaimValidator,
    consumer_certification_status,
)
from company.models import Company, Establishment
from history.models import HistoryScan, Production
from history.serializers_consumer import EnhancedHistoryScanSerializer
from history.transparency_views import _build_organic_summary
from product.models import Parcel, Product
from users.models import User

#: (label, is_demo, verification_status, verification_source)
STATES = (
    ("specimen", True, "verified", "usda_organic_integrity_db"),
    ("registry_verified", False, "verified", "usda_organic_integrity_db"),
    # The row an admin edit, a CSV import or a fixture creates: marked verified, but no source
    # naming what verified it. `Certification.consumer_display_status` exists for exactly this.
    ("producer_reported", False, "verified", ""),
    ("unknown", False, "pending", ""),
)


def flatten(node, out=None):
    out = out if out is not None else []
    if isinstance(node, dict):
        for value in node.values():
            flatten(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            flatten(item, out)
    elif node is not None:
        out.append(str(node))
    return out


class CertificationClaimStateMatrixTests(TestCase):
    """One fixture per state, then every reader asked about every state."""

    @classmethod
    def setUpTestData(cls):
        cls.fixtures_by_state = {}
        for label, is_demo, status, source in STATES:
            cls.fixtures_by_state[label] = cls._build(label, is_demo, status, source)

    @classmethod
    def _build(cls, label, is_demo, verification_status, verification_source):
        user = User.objects.create_user(email=f"matrix-{label}@test.com", password="x")
        company = Company.objects.create(name=f"Matrix Co {label}")
        establishment = Establishment.objects.create(
            name=f"Matrix Farm {label}",
            company=company,
            state="OR",
            is_demo=is_demo,
        )
        parcel = Parcel.objects.create(name=f"Block {label}", establishment=establishment, area=4.0)
        product = Product.objects.create(name=f"Blueberries {label}")
        history = Production.objects.create(
            name=f"Season {label}",
            start_date=timezone.now() - timedelta(days=60),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=100.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
            # ⛔ LOAD-BEARING, do not drop to "make the fixture minimal".
            #
            # `_build_organic_summary` returns None when a farm is not an organic operation at
            # all, and `is_organic_farm` ORs in this very field. With it unset, the specimen
            # assertion below passed for the WRONG REASON: the summary was None because the
            # fixture looked conventional, not because the specimen guard fired. Mutating the
            # guard away on 2026-09-16 broke nothing, which is how this was caught.
            production_method="organic",
        )
        cert = Certification.objects.create(
            establishment=establishment,
            certification_type="usda_organic",
            certifier_name="CCOF Certification Services, LLC",
            effective_date=date(2022, 1, 1),
            expiry_date=date(2030, 12, 31),
            certification_scope="Crops",
            certified_items=["Blueberries"],
            verification_status=verification_status,
            verification_source=verification_source,
            verification_source_url="https://organic.ams.usda.gov/integrity/",
            usda_operation_name=f"Matrix Operation {label}",
        )
        scan = HistoryScan.objects.create(history=history, user=user)
        return {
            "user": user,
            "establishment": establishment,
            "history": history,
            "cert": cert,
            "scan": scan,
        }

    # -- helpers ---------------------------------------------------------------------------

    def claim(self, label):
        return ConsumerClaimValidator().validate(self.fixtures_by_state[label]["history"])

    def summary(self, label):
        fixture = self.fixtures_by_state[label]
        return _build_organic_summary(
            fixture["history"],
            [ConsumerCertificationSerializer(fixture["cert"]).data],
            fixture["establishment"],
            self.claim(label).to_dict(),
        )

    def scan_payload(self, label):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.fixtures_by_state[label]["user"]
        return EnhancedHistoryScanSerializer(self.fixtures_by_state[label]["scan"], context={"request": request}).data

    # -- the premise -----------------------------------------------------------------------

    def test_the_fixtures_are_the_pre_correction_shape(self):
        """Without this the matrix could pass by testing corrected fixtures instead of the runtime."""
        specimen_cert = self.fixtures_by_state["specimen"]["cert"]
        self.assertEqual(specimen_cert.verification_status, "verified")
        self.assertEqual(
            specimen_cert.consumer_display_status,
            "verified_via_database",
            "the MODEL still says verified — that is the point; the consumer layer must refuse it",
        )
        producer_cert = self.fixtures_by_state["producer_reported"]["cert"]
        self.assertEqual(producer_cert.verification_status, "verified")
        self.assertEqual(
            producer_cert.consumer_display_status,
            "self_reported",
            "a 'verified' row with no source is what the model already refuses to call verified",
        )

    # -- reader 1: ConsumerClaimValidator --------------------------------------------------

    def test_claim_status_per_state(self):
        self.assertEqual(self.claim("specimen").status, STATUS_SPECIMEN)
        self.assertEqual(self.claim("registry_verified").status, "certified_organic")
        self.assertEqual(self.claim("producer_reported").status, "certified_organic")
        # No active certificate reaches the certified branch, and nothing else is established.
        self.assertIn(self.claim("unknown").status, {"self_reported", "conventional"})

    def test_claim_disclaimer_per_state(self):
        self.assertEqual(self.claim("specimen").disclaimer, DISCLAIMER_SPECIMEN)
        self.assertEqual(self.claim("registry_verified").disclaimer, DISCLAIMER_CERTIFIED)
        self.assertEqual(self.claim("producer_reported").disclaimer, DISCLAIMER_CERTIFIED_ON_FILE)

    def test_only_a_real_registry_match_sets_oid_matched(self):
        self.assertTrue(self.claim("registry_verified").oid_matched)
        for label in ("specimen", "producer_reported", "unknown"):
            self.assertFalse(self.claim(label).oid_matched, label)

    def test_a_specimen_may_not_display_organic_at_all(self):
        self.assertFalse(self.claim("specimen").can_display_organic)
        self.assertTrue(self.claim("specimen").specimen)
        # And the real farms are untouched by that refusal.
        self.assertTrue(self.claim("registry_verified").can_display_organic)
        self.assertTrue(self.claim("producer_reported").can_display_organic)

    def test_a_specimen_without_any_certificate_still_gets_the_specimen_status(self):
        """Priority 0 sits above the certificate lookup, so no branch can lose the mark.

        The regression this pins: with the check inside the certified branch, a seeded farm with
        no certificate row fell through to `self_reported` and rendered "This farm reports
        following organic practices" — a claim about a farm that does not exist.
        """
        fixture = self.fixtures_by_state["specimen"]
        fixture["cert"].delete()
        try:
            result = ConsumerClaimValidator().validate(fixture["history"])
            self.assertEqual(result.status, STATUS_SPECIMEN)
            self.assertEqual(result.disclaimer, DISCLAIMER_SPECIMEN)
            self.assertFalse(result.can_display_organic)
        finally:
            fixture["cert"] = Certification.objects.create(
                establishment=fixture["establishment"],
                certification_type="usda_organic",
                certifier_name="CCOF Certification Services, LLC",
                effective_date=date(2022, 1, 1),
                expiry_date=date(2030, 12, 31),
                certification_scope="Crops",
                certified_items=["Blueberries"],
                verification_status="verified",
                verification_source="usda_organic_integrity_db",
            )

    # -- reader 2: the organic summary (drives the QR narrative) ---------------------------

    def test_certification_verified_flag_per_state(self):
        self.assertIsNone(
            self.summary("specimen"),
            "a fabricated operation gets no organic narrative at all — not even the self-reported one",
        )
        self.assertEqual(
            self.fixtures_by_state["specimen"]["history"].production_method,
            "organic",
            "the premise: without this the None above would prove only that the fixture looked "
            "conventional. See the note on the fixture.",
        )
        self.assertTrue(self.summary("registry_verified")["certification_verified"])
        self.assertTrue(
            self.summary("producer_reported")["certification_verified"],
            "a real certificate on file is still a certified operation; only the REGISTRY claim "
            "is withheld, and that distinction lives in the disclaimer",
        )

    # -- reader 3: the per-certificate consumer row ----------------------------------------

    def test_consumer_certification_status_per_state(self):
        expected = {
            "specimen": "self_reported",
            "registry_verified": "verified_via_database",
            "producer_reported": "self_reported",
            "unknown": "pending",
        }
        for label, want in expected.items():
            self.assertEqual(consumer_certification_status(self.fixtures_by_state[label]["cert"]), want, label)

    def test_only_the_specimen_row_is_flagged_specimen(self):
        for label, _, _, _ in STATES:
            data = ConsumerCertificationSerializer(self.fixtures_by_state[label]["cert"]).data
            self.assertEqual(bool(data["specimen"]), label == "specimen", label)

    # -- reader 4: the producer dashboard serializer ---------------------------------------

    def test_the_producer_serializer_ships_what_the_badge_needs(self):
        """The farm profile badge reads `consumer_display_status` + `specimen`, never the raw column."""
        for label, _, _, _ in STATES:
            data = CertificationSerializer(self.fixtures_by_state[label]["cert"]).data
            self.assertIn("consumer_display_status", data, label)
            self.assertIn("specimen", data, label)
            self.assertEqual(bool(data["specimen"]), label == "specimen", label)
        self.assertEqual(
            CertificationSerializer(self.fixtures_by_state["producer_reported"]["cert"]).data[
                "consumer_display_status"
            ],
            "self_reported",
            "the field the badge reads must already be downgraded — the component does no logic",
        )

    # -- reader 5: the signed-in shopper payload -------------------------------------------

    def test_the_scan_payload_says_verified_only_for_a_real_registry_match(self):
        self.assertTrue(self.scan_payload("registry_verified")["is_verified"])
        for label in ("specimen", "producer_reported", "unknown"):
            self.assertFalse(self.scan_payload(label)["is_verified"], label)

    def test_the_word_verified_never_appears_for_an_unmatched_or_invented_operation(self):
        for label in ("specimen", "producer_reported", "unknown"):
            practices = self.scan_payload(label)["sustainability_practices"]
            self.assertNotIn("(verified)", " | ".join(practices), f"{label}: {practices}")
        self.assertIn(
            "(verified)",
            " | ".join(self.scan_payload("registry_verified")["sustainability_practices"]),
            "the legitimate claim must survive — a safeguard that downgrades everybody proves nothing",
        )

    # -- reader 6: the anonymous transparency payload, end to end --------------------------

    def test_the_public_payload_never_carries_a_registry_claim_it_has_not_earned(self):
        for label in ("specimen", "producer_reported", "unknown"):
            fixture = self.fixtures_by_state[label]
            resp = self.client.get(
                f"/api/transparency/{fixture['history'].public_id}/",
                HTTP_USER_AGENT="Mozilla/5.0 (claim-matrix-test)",
            )
            self.assertEqual(resp.status_code, 200, label)
            body = " || ".join(flatten(resp.json()))
            self.assertNotIn("verified_via_database", body, label)
            self.assertNotIn("USDA-certified organic farm", body, label)

    def test_the_public_payload_keeps_the_claim_a_real_match_earned(self):
        fixture = self.fixtures_by_state["registry_verified"]
        resp = self.client.get(
            f"/api/transparency/{fixture['history'].public_id}/",
            HTTP_USER_AGENT="Mozilla/5.0 (claim-matrix-test)",
        )
        self.assertEqual(resp.status_code, 200)
        body = " || ".join(flatten(resp.json()))
        self.assertIn("verified_via_database", body)
