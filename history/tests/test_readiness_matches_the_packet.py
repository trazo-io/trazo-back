"""The card that says "before your certifier packet" must know what the packet knows.

WHY THIS EXISTS
---------------
🔴 2026-08-28. The pilot's readiness card reported **ready · 0 blockers · 0 warnings** on the same
day its own generated packet printed *"[REVIEW] 8 product name(s) in the logged applications do
not match an entry above."* One farm, one day, two answers.

That is the defect `CertifierReadinessCard` was built to remove — its docstring says so, about two
cards showing "3" and "1 to fix" — reappearing between the card and the DOCUMENT instead of
between two cards. A farmer who notices stops trusting every number in the product.

The cause: `OperationReadinessService` checked OSP content, the fraud plan, attestation support
and whether records exist. It did not read the three things the CCOF/WSDA register work made
concrete — the materials reconciliation, the parcel map both certifiers require as an attachment,
and handler certificate freshness — even though the packet reads all three and prints them.

WORDING RULES THESE CHECKS LIVE UNDER
  · UNMATCHED IS NOT UNAPPROVED. A brand name and the National List substance covering it read
    differently; calling the difference a violation invents a compliance finding.
  · `cert_is_current` is TRI-STATE. `None` means no date recorded — an ask, not a pass, not a fail.
  · Warnings, never blockers: a certifier still accepts the packet. Trazo does not decide
    compliance.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, PostHarvestFacility
from company.models import Company, Establishment
from history.services.operation_readiness_service import OperationReadinessService
from product.models import Parcel

RING = [[-123.11, 44.54], [-123.10, 44.54], [-123.10, 44.55], [-123.11, 44.55], [-123.11, 44.54]]


class ReadinessMatchesThePacketTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Readiness Co")
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=3, status="active")

    def _keys(self, status=None):
        result = OperationReadinessService(self.est).evaluate()
        rows = result["warnings"] if status == "warning" else result["blockers"]
        return {r["key"] for r in rows}

    def _all_keys(self):
        result = OperationReadinessService(self.est).evaluate()
        return {r["key"] for r in result["warnings"] + result["blockers"]}

    # -- the plan it reads -------------------------------------------------

    def test_it_reads_the_plan_being_filed_not_the_one_in_force(self):
        """A farm mid-renewal has an active v3 and a draft v4.

        Reading the ACTIVE plan looks right and is subtly wrong: the operator fixing v4 would
        watch the warning refuse to clear because it was counting v3. On the pilot the two
        differed by exactly the material added that morning.
        """
        draft = OrganicSystemPlan.objects.create(establishment=self.est, version_number=4, status="draft")
        service = OperationReadinessService(self.est)
        self.assertEqual(service._plan_being_filed().pk, draft.pk)

    def test_superseded_versions_are_never_the_filing(self):
        OrganicSystemPlan.objects.create(establishment=self.est, version_number=9, status="superseded")
        service = OperationReadinessService(self.est)
        self.assertEqual(service._plan_being_filed().pk, self.osp.pk)

    # -- the parcel map ----------------------------------------------------

    def test_a_parcel_with_no_boundary_and_no_map_is_flagged(self):
        Parcel.objects.create(name="Back Forty", establishment=self.est, area=4.0)
        self.assertIn("parcel_maps", self._keys("warning"))

    def test_a_parcel_with_a_drawn_boundary_is_not_flagged(self):
        Parcel.objects.create(
            name="Home Field",
            establishment=self.est,
            area=4.0,
            polygon={"type": "Polygon", "coordinates": [RING]},
        )
        self.assertNotIn("parcel_maps", self._all_keys())

    def test_an_uploaded_map_also_satisfies_it(self):
        # Same two sources the packet and the module-completion service read. Three definitions
        # of "has a map" would be one too many.
        from django.core.files.uploadedfile import SimpleUploadedFile

        from certifications.services.osp_module_pdf import PARCEL_MAP_SECTION
        from documents.models import GeneratedDocument

        parcel = Parcel.objects.create(name="Back Forty", establishment=self.est, area=4.0)
        GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=parcel,
            folder="organic_system_plan",
            source="upload",
            title="map",
            file=SimpleUploadedFile("m.png", b"x", content_type="image/png"),
            linked_section=PARCEL_MAP_SECTION,
        )
        self.assertNotIn("parcel_maps", self._all_keys())

    # -- handler certificates ----------------------------------------------

    def test_an_expired_handler_certificate_is_flagged(self):
        PostHarvestFacility.objects.create(
            establishment=self.est,
            name="Marion Bend Fruit",
            certification_number="COC-1",
            effective_date=timezone.now().date() - timedelta(days=900),
        )
        self.assertIn("handler_certificates", self._keys("warning"))

    def test_an_undated_certificate_is_flagged_as_an_ask_not_a_pass(self):
        # `cert_is_current` is None here. Absence must never render as compliance.
        PostHarvestFacility.objects.create(establishment=self.est, name="Undated Co", certification_number="COC-2")
        self.assertIn("handler_certificates", self._keys("warning"))

    def test_a_current_certificate_is_not_flagged(self):
        PostHarvestFacility.objects.create(
            establishment=self.est,
            name="Current Co",
            certification_number="COC-3",
            effective_date=timezone.now().date() - timedelta(days=30),
        )
        self.assertNotIn("handler_certificates", self._all_keys())

    # -- none of this may become a compliance verdict ----------------------

    def test_the_new_checks_never_block(self):
        """A certifier decides compliance; Trazo reports what is missing from the record.

        All three read as "worth fixing before you send it", so a blocker here would stop a
        submission Trazo has no standing to stop.
        """
        Parcel.objects.create(name="Back Forty", establishment=self.est, area=4.0)
        PostHarvestFacility.objects.create(establishment=self.est, name="Undated Co")
        blockers = {r["key"] for r in OperationReadinessService(self.est).evaluate()["blockers"]}
        self.assertFalse(blockers & {"unmatched_materials", "parcel_maps", "handler_certificates"})

    def test_unmatched_materials_is_never_worded_as_unapproved(self):
        rows = OperationReadinessService(self.est).evaluate()
        text = " ".join(
            f"{r.get('title','')} {r.get('detail','')}" for r in rows["warnings"] + rows["blockers"]
        ).lower()
        for forbidden in ("unapproved", "prohibited", "violation", "non-compliant"):
            self.assertNotIn(forbidden, text)
