"""A plan written by substance, and a spray logged by brand (overall review 2026-11, OV-MT-C06).

Many plans list National List substances ("Spinosad", "Copper hydroxide") where the records name
brands ("Entrust SC", "Kocide 3000-O"). The drift detector already cleared a record whose confirmed
classification is a substance on the plan, which is how a grower who types the active ingredient on
the record is read. Two gaps remained, both reproduced on this branch before the fix:

* Attaching the product's own OMRI or WSDA listing to that same record made it flag "not on the
  plan's materials list", because the listing branches returned before the substance check. More
  evidence gave a worse answer.
* A brand-name record with no classification flagged, rightly, and the finding never said how it
  clears. It now carries the plan's substances (`planSubstances`) so the app can say: if this
  product's active ingredient is one of them, type it on the record.

What does NOT change: nothing is inferred from a brand name (OMRI and WSDA rows carry no active
ingredient), a partial-name suggestion still clears nothing, a substance the plan does not list
still flags, and the CDFA check runs on the product applied, never on the substance row.
"""

from django.test import TransactionTestCase
from django.utils import timezone

from certifications.models import NationalListSubstance, OMRIProduct, OrganicSystemPlan, WSDAMaterial
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production
from product.models import Parcel


class PlanBySubstanceTests(TransactionTestCase):
    def setUp(self):
        company = Company.objects.create(name="Substance Plan Orchard")
        self.establishment = Establishment.objects.create(name="Main", company=company)
        parcel = Parcel.objects.create(name="B1", establishment=self.establishment, area=5.0)
        self.history = Production.objects.create(name="Apples", start_date=timezone.now(), parcel=parcel)
        self.spinosad = self._substance("Spinosad", "e")
        self.copper = self._substance("Copper hydroxide", "i")
        self.bicarb = self._substance("Potassium bicarbonate", "i")  # on the National List, not on this plan
        self.omri_entrust = OMRIProduct.objects.create(omri_id="OMRI-ENT-9", product_name="Entrust SC")
        self.wsda_kocide = WSDAMaterial.objects.create(brand_name="Kocide 3000-O")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.osp.approved_national_list_substances.add(self.spinosad, self.copper)

    @staticmethod
    def _substance(name, subsection):
        return NationalListSubstance.objects.create(
            substance_name=name,
            substance_name_normalized=name.lower(),
            cfr_section="205.601",
            subsection=subsection,
            status="allowed",
        )

    def _spray(self, active_ingredient=None, **kwargs):
        extra = {"active_ingredient": active_ingredient} if active_ingredient else {}
        ev = ChemicalEvent.objects.create(
            history=self.history, date=timezone.now(), description="spray", extra_data=extra, **kwargs
        )
        ev.refresh_from_db()
        return ev

    # --- the listing no longer undoes the substance ---------------------------------------------

    def test_a_typed_active_ingredient_on_the_plan_clears(self):
        """The rule this slice extends, pinned so the two listing tests below compare with it."""
        ev = self._spray(commercial_name="Entrust SC", active_ingredient="Spinosad")
        self.assertEqual(ev.national_list_substance_id, self.spinosad.id)
        self.assertEqual(ev.national_list_basis, "exact")
        self.assertIsNone(ev.drift_warning)

    def test_attaching_the_omri_listing_keeps_it_clear(self):
        ev = self._spray(commercial_name="Entrust SC", active_ingredient="Spinosad", omri_product=self.omri_entrust)
        self.assertIsNone(ev.drift_warning, "the OMRI listing turned a cleared record into a finding")

    def test_attaching_the_wsda_listing_keeps_it_clear(self):
        ev = self._spray(
            commercial_name="Kocide 3000-O", active_ingredient="Copper hydroxide", wsda_material=self.wsda_kocide
        )
        self.assertIsNone(ev.drift_warning, "the WSDA listing turned a cleared record into a finding")

    def test_the_operator_s_own_classification_clears_the_same_way(self):
        ev = self._spray(
            commercial_name="Entrust SC",
            omri_product=self.omri_entrust,
            national_list_substance=self.spinosad,
            national_list_basis="operator",
        )
        self.assertIsNone(ev.drift_warning)

    # --- boundaries --------------------------------------------------------------------------

    def test_a_substance_the_plan_does_not_list_still_flags(self):
        ev = self._spray(
            commercial_name="Entrust SC", active_ingredient="Potassium bicarbonate", omri_product=self.omri_entrust
        )
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["reason_code"], "omri_not_in_osp")
        # The record has its classification; typing again changes nothing, so no hint.
        self.assertNotIn("planSubstances", ev.drift_warning["reason_params"])

    def test_a_partial_name_suggestion_clears_nothing(self):
        """ "spinosad" inside the brand text is a suggestion, never a classification."""
        ev = self._spray(commercial_name="Entrust SC (Spinosad 22.5%)", omri_product=self.omri_entrust)
        self.assertIsNone(ev.national_list_substance_id)
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["reason_code"], "omri_not_in_osp")
        self.assertEqual(ev.drift_warning["reason_params"]["planSubstances"], ["Copper hydroxide", "Spinosad"])

    def test_a_legacy_link_gets_no_hint(self):
        """A legacy classification is kept as it is on save, so typing an ingredient would not
        reclassify it: the hint would name a step that changes nothing."""
        ev = self._spray(
            commercial_name="Kocide 3000-O",
            wsda_material=self.wsda_kocide,
            national_list_substance=self.copper,
            national_list_basis="legacy_unverified",
        )
        self.assertIsNotNone(ev.drift_warning)
        self.assertEqual(ev.drift_warning["reason_code"], "wsda_not_in_osp")
        self.assertNotIn("planSubstances", ev.drift_warning["reason_params"])

    # --- the hint ----------------------------------------------------------------------------

    def test_a_brand_with_no_ingredient_names_the_plan_s_substances(self):
        ev = self._spray(commercial_name="Kocide 3000-O")
        self.assertIsNotNone(ev.drift_warning, "a brand with no classification must not clear by itself")
        self.assertEqual(ev.drift_warning["reason_code"], "name_wsda_not_in_osp")
        self.assertEqual(ev.drift_warning["reason_params"]["planSubstances"], ["Copper hydroxide", "Spinosad"])
        # The packet prints the stored prose; the hint is for the grower's screen only.
        self.assertNotIn("Copper hydroxide", ev.drift_warning["reason"])

    def test_typing_the_ingredient_the_hint_asks_for_clears_the_finding(self):
        """The hint's promise, end to end: the same record, edited the way the hint says."""
        ev = self._spray(commercial_name="Kocide 3000-O", wsda_material=self.wsda_kocide)
        self.assertEqual(ev.drift_warning["reason_params"]["planSubstances"], ["Copper hydroxide", "Spinosad"])
        ev.extra_data = {"active_ingredient": "Copper hydroxide"}
        ev.save()
        ev.refresh_from_db()
        self.assertIsNone(ev.drift_warning)

    def test_an_unmatched_name_carries_the_hint(self):
        ev = self._spray(commercial_name="Grandpa's copper mix")
        self.assertEqual(ev.drift_warning["reason_code"], "unresolved")
        self.assertEqual(ev.drift_warning["reason_params"]["planSubstances"], ["Copper hydroxide", "Spinosad"])

    def test_no_hint_on_a_plan_that_lists_no_substance(self):
        self.osp.approved_national_list_substances.clear()
        ev = self._spray(commercial_name="Kocide 3000-O")
        self.assertEqual(ev.drift_warning["reason_code"], "name_wsda_not_in_osp")
        self.assertNotIn("planSubstances", ev.drift_warning["reason_params"])

    # --- CA checks stay on the product -------------------------------------------------------

    def test_the_cdfa_check_reads_the_product_not_the_substance(self):
        """A substance row has no CDFA registration. Checking it printed "not checked" for a product
        Trazo's CDFA set does hold. "Solubor" is a curated alias of the substance, so it clears through
        the name rescue (the path that had this bug before this slice); "Boron 10" clears through the
        record's classification. Both now read the product's own standing."""
        self.establishment.state = "CA"
        self.establishment.save()
        boron = NationalListSubstance.objects.create(
            substance_name="Soluble boron products",
            substance_name_normalized="soluble boron products",
            cfr_section="205.601",
            subsection="j",
            category="fertilizer",
            status="allowed",
        )
        self.osp.approved_national_list_substances.add(boron)
        registered = OMRIProduct.objects.create(
            omri_id="OMRI-SOL-1", product_name="Solubor", category="Fertilizers", is_cdfa_oim_registered=True
        )
        unregistered = OMRIProduct.objects.create(omri_id="OMRI-SOL-2", product_name="Boron 10", category="Fertilizers")

        clear = self._spray(
            commercial_name="Solubor", active_ingredient="Soluble boron products", omri_product=registered
        )
        self.assertIsNone(clear.drift_warning)

        flagged = self._spray(
            commercial_name="Boron 10", active_ingredient="Soluble boron products", omri_product=unregistered
        )
        self.assertIsNotNone(flagged.drift_warning)
        self.assertEqual(flagged.drift_warning["reason_code"], "approved_with_issues")
        self.assertEqual(flagged.drift_warning["reason_params"]["issues"], ["cdfa_unknown"])
        self.assertEqual(flagged.drift_warning["resolved_via"], "national_list")
        self.assertEqual(flagged.drift_warning["resolved_name"], "Soluble boron products")
