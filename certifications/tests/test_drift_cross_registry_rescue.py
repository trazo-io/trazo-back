"""Cross-registry rescue + reason codes (2026-08-25).

Live false positive on dev farm 167 (Calapooia): "Entrust SC" was stamped with
NationalListSubstance Spinosad on save, and the drift detector judged it against
the OSP's approved *National List* set alone — flagging "National List substance
not in active OSP approved inputs" while "Entrust SC Naturalyte Insect Control"
sat on the SAME plan's approved OMRI list. One product, two registries, and the
detector stopped at the wrong one, telling the farmer to send their certifier a
§ 205.400(f)(2) notice about a material already on their plan.

These tests pin:
- the rescue: an FK-classified event clears when the product is OSP-approved
  through ANY catalog (NL-FK → OMRI approval; OMRI-FK → WSDA approval);
- the boundary: no name, or a name that resolves to nothing approved, still
  flags exactly as before;
- reason codes: every finding now carries a stable ``reason_code`` +
  ``reason_params`` so the UI can localize (the English prose remains for the
  packet and as fallback for legacy findings).
"""

from django.test import TransactionTestCase
from django.utils import timezone

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, WSDAMaterial
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from product.models import Parcel


class CrossRegistryRescueTests(TransactionTestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Rescue Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P1", establishment=self.establishment, area=5.0)
        self.history = History.objects.create(
            name="Rescue Production",
            start_date=timezone.now(),
            parcel=self.parcel,
        )

        # The exact farm-167 shape: Spinosad exists as an NL row but is NOT on
        # the plan's approved NL set; the PRODUCT is approved via OMRI.
        self.nl_spinosad = NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section="205.601",
            subsection="e",
            status="allowed",
        )
        self.omri_entrust = OMRIProduct.objects.create(
            omri_id="OMRI-ENT-1",
            product_name="Entrust SC Naturalyte Insect Control",
        )
        self.omri_unrelated = OMRIProduct.objects.create(
            omri_id="OMRI-UNREL-1",
            product_name="Avenger AG Herbicide",
        )
        self.wsda_serenade = WSDAMaterial.objects.create(
            brand_name="Serenade Opti",
        )

        self.active_osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.active_osp.approved_omri_products.add(self.omri_entrust)
        self.active_osp.approved_wsda_materials.add(self.wsda_serenade)

    def _spray(self, **kwargs):
        ev = ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="spray",
            **kwargs,
        )
        ev.refresh_from_db()
        return ev

    # --- the farm-167 false positive, pinned -------------------------------

    def test_nl_fk_event_cleared_by_omri_approval_of_same_product(self):
        ev = self._spray(
            national_list_substance=self.nl_spinosad,
            commercial_name="Entrust SC",
        )
        self.assertIsNone(
            ev.drift_warning,
            "NL-classified event must clear when the product is OSP-approved "
            "via its OMRI listing — this was the live Entrust SC false positive.",
        )

    def test_omri_fk_event_cleared_by_wsda_approval(self):
        # Symmetric shape: event linked to an OMRI product NOT on the plan,
        # while the plan approves the same product's WSDA listing.
        omri_serenade = OMRIProduct.objects.create(
            omri_id="OMRI-SER-1",
            product_name="Serenade Opti",
        )
        ev = self._spray(
            omri_product=omri_serenade,
            commercial_name="Serenade Opti",
        )
        self.assertIsNone(
            ev.drift_warning,
            "OMRI-FK event must clear when the same product is OSP-approved via WSDA.",
        )

    # --- boundaries: the rescue must not over-clear ------------------------

    def test_nl_fk_event_without_name_still_flags(self):
        ev = self._spray(
            national_list_substance=self.nl_spinosad,
            commercial_name="",
        )
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["reason_code"], "nl_not_in_osp")
        self.assertEqual(ev.drift_warning["reason_params"]["substance"], "Spinosad")

    def test_nl_fk_event_with_unapproved_name_still_flags(self):
        ev = self._spray(
            national_list_substance=self.nl_spinosad,
            commercial_name="Avenger AG Herbicide",  # resolves OMRI, NOT approved
        )
        self.assertIsNotNone(
            ev.drift_warning,
            "A name that resolves to an UNAPPROVED catalog product must not rescue.",
        )
        self.assertEqual(ev.drift_warning["reason_code"], "nl_not_in_osp")

    def test_nl_fk_approved_substance_still_clears(self):
        self.active_osp.approved_national_list_substances.add(self.nl_spinosad)
        ev = self._spray(
            national_list_substance=self.nl_spinosad,
            commercial_name="Entrust SC",
        )
        self.assertIsNone(ev.drift_warning)

    # --- reason codes ------------------------------------------------------

    def test_unresolved_finding_carries_reason_code_and_params(self):
        ev = self._spray(commercial_name="Mystery Brew 9000")
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["reason_code"], "unresolved")
        self.assertEqual(ev.drift_warning["reason_params"]["input"], "Mystery Brew 9000")
        # Prose stays for the packet and legacy fallback.
        self.assertIn("Mystery Brew 9000", ev.drift_warning["reason"])

    def test_omri_fk_unapproved_finding_carries_code(self):
        ev = self._spray(
            omri_product=self.omri_unrelated,
            commercial_name="Avenger AG Herbicide",
        )
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["reason_code"], "omri_not_in_osp")
        self.assertEqual(ev.drift_warning["reason_params"]["input"], "Avenger AG Herbicide")
