"""Planting/Transplanting record completeness — 7 CFR 205.204.

WHY (2026-08-15): `record_completeness.py` was chemical-only, so a planting record could reach
a certifier with no organic status, no commercial-availability ground and no treatment basis
while the farm dashboard's readiness card — the card the dashboard leads with — reported
nothing. The certifier packet already PRINTED columns for every one of those facts.

The registry is deliberately narrower than the packet. It flags what a certifier asks for, and
it does not invent requirements: the three-supplier expectation is included because USDA's
Guide states it as what "certifiers want clear indication" of, and it is framed as a readiness
check rather than a save-blocking rule, because § 205.204 sets no count.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from history.services.record_completeness import (
    PLANTING_EVENT_REQUIRED_FIELDS,
    completeness_gap_keys,
    is_complete,
    missing_required_fields,
)
from product.models import Parcel, Product
from users.models import User


class PlantingRecordCompletenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = User.objects.create_user(email="plantcomplete@test.com", password="x")
        company = Company.objects.create(name="Plant Co")
        establishment = Establishment.objects.create(name="PC1", company=company)
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        product = Product.objects.create(name="Avocado")
        cls.history = Production.objects.create(
            name="Planting Completeness",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _planting(self, **overrides):
        defaults = dict(history=self.history, type="PL", date=timezone.now(), description="Planting")
        defaults.update(overrides)
        return ProductionEvent(**defaults)

    # -- citation discipline ------------------------------------------------

    def test_every_required_field_carries_a_citation(self):
        """The rule this module was built on: no citation, no entry."""
        for rf in PLANTING_EVENT_REQUIRED_FIELDS:
            with self.subTest(field=rf.key):
                self.assertTrue(rf.cfr_cite.startswith("§ 205."), f"{rf.key} has no CFR citation")

    # -- what is owed unconditionally ---------------------------------------

    def test_a_planting_with_no_seed_status_is_incomplete(self):
        gaps = completeness_gap_keys(self._planting())
        self.assertIn("seed_certification_status", gaps)

    def test_organic_seed_needs_nothing_further(self):
        """The exemption machinery must not fire for a grower who used organic seed."""
        event = self._planting(seed_certification_status="certified_organic")
        self.assertTrue(is_complete(event), missing_required_fields(event))

    # -- what is owed only when an exemption is claimed ----------------------

    def test_non_organic_seed_owes_the_ground_and_the_searches(self):
        gaps = completeness_gap_keys(self._planting(seed_certification_status="non_organic_untreated"))
        self.assertIn("seed_nonavailability_reason", gaps)
        self.assertIn("seed_search_attempts", gaps)

    def test_three_named_suppliers_closes_the_search_gap(self):
        event = self._planting(
            seed_certification_status="non_organic_untreated",
            seed_nonavailability_reason="quantity",
            seed_search_attempts=[
                {"supplier_name": "A"},
                {"supplier_name": "B"},
                {"supplier_name": "C"},
            ],
        )
        self.assertTrue(is_complete(event), missing_required_fields(event))

    def test_two_suppliers_is_a_readiness_gap_not_a_save_block(self):
        """Below three is reported here — and, deliberately, nowhere that blocks a save."""
        event = self._planting(
            seed_certification_status="non_organic_untreated",
            seed_nonavailability_reason="quantity",
            seed_search_attempts=[{"supplier_name": "A"}, {"supplier_name": "B"}],
        )
        self.assertIn("seed_search_attempts", completeness_gap_keys(event))
        event.full_clean()  # the model validator must NOT reject it

    def test_rows_without_a_supplier_name_are_not_evidence(self):
        """205.204(a)(1) turns on WHO was contacted — a result with no name proves nothing."""
        event = self._planting(
            seed_certification_status="non_organic_untreated",
            seed_nonavailability_reason="form",
            seed_search_attempts=[{"result": "none"}, {"result": "none"}, {"result": "none"}],
        )
        self.assertIn("seed_search_attempts", completeness_gap_keys(event))

    def test_legacy_supplier_key_still_counts(self):
        """Rows written before migration 0205 used `supplier`; they are still evidence."""
        event = self._planting(
            seed_certification_status="non_organic_untreated",
            seed_nonavailability_reason="quantity",
            seed_search_attempts=[{"supplier": "A"}, {"supplier": "B"}, {"supplier": "C"}],
        )
        self.assertNotIn("seed_search_attempts", completeness_gap_keys(event))

    # -- treatment allowability ---------------------------------------------

    def test_a_named_treatment_owes_its_basis(self):
        event = self._planting(
            seed_certification_status="certified_organic",
            seed_treatment="Neem oil coating",
        )
        self.assertIn("seed_treatment_allowed_basis", completeness_gap_keys(event))

    def test_none_is_an_answer_not_a_treatment(self):
        """ "None" in the treatment box must not manufacture a 205.204(a)(2) gap."""
        for answer in ("None", "none", "n/a", "untreated", "Ninguno"):
            with self.subTest(answer=answer):
                event = self._planting(
                    seed_certification_status="certified_organic",
                    seed_treatment=answer,
                )
                self.assertNotIn("seed_treatment_allowed_basis", completeness_gap_keys(event))

    # -- purchase trace ------------------------------------------------------

    def test_purchase_evidence_without_a_supplier_is_a_half_record(self):
        event = self._planting(
            seed_certification_status="certified_organic",
            seed_purchase_invoice="INV-1",
        )
        self.assertIn("seed_supplier_name", completeness_gap_keys(event))

    def test_no_purchase_asserted_owes_no_supplier(self):
        """Farm-saved seed is not a purchase; demanding a supplier would invent a rule."""
        event = self._planting(seed_certification_status="certified_organic", seeds_source="farm_saved")
        self.assertNotIn("seed_supplier_name", completeness_gap_keys(event))

    # -- scope ---------------------------------------------------------------

    def test_transplanting_is_governed_too(self):
        self.assertIn("seed_certification_status", completeness_gap_keys(self._planting(type="TR")))

    def test_other_production_subtypes_are_silent(self):
        """Irrigation owes no seed evidence — and silence must not read as completeness."""
        self.assertEqual(completeness_gap_keys(self._planting(type="IR")), [])

    def test_a_non_production_event_does_not_run_chemical_checks(self):
        """Regression: dispatching to the chemical registry by default raised AttributeError
        inside the write-time nudge and 500'd the save for weather/soil/general events."""
        from history.models import GeneralEvent

        event = GeneralEvent(history=self.history, date=timezone.now(), description="Walkthrough")
        self.assertEqual(completeness_gap_keys(event), [])
