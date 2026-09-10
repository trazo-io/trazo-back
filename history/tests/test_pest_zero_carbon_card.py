"""A pest record logged without fuel must still get its Carbon Impact card.

Every pest subtype counts REPORTED fuel and nothing else — `calculate_pest_management_event_impact`
adds no base emissions — so a scouting pass with no fuel entered computes 0 kg CO2e. Until
2026-09-10 the post_save signal only stored a CarbonEntry when `abs(co2e) > 0.05`, so that 0 was
never stored. `get_carbon_data` reads CarbonEntry; with no row it answers `carbon_data: null`, and
`EventDetailsModal` maps null onto its `error: 'Carbon data not available'` fallback. Both the
Carbon Impact card and the "No direct emissions" caption are gated on `!carbonData.error`, so the
whole section silently disappeared from every scouting record.

Same defect, same fix as the Production subtypes on 2026-08-22
(carbon/tests/test_non_area_driven_subtypes_carbon.py). These tests assert what is STORED and
SERVED, not just what is computed: the computed value was always correct.

Storing the 0 made one older defect visible. A scouting SUMMARY collects its fuel as
`extra_data.fuel_consumed_total`, and no pest calculation read it: a summary flagged
`is_summary: True` took an aggregate path that returned a hardcoded 0, and one flagged with the
string "true" took the per-event path, which reads only the `fuel_consumed` column. While a 0
stored nothing, that fuel was silently dropped; once a 0 is stored, it would print "No direct
emissions" on a record whose grower entered their season's diesel.
"""

from unittest import mock

from django.test import TestCase
from django.utils import timezone

from carbon.models import CarbonEntry
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import History, PestManagementEvent
from history.serializers import PestManagementEventSerializer
from history.signals import PEST_SUBTYPES_ZERO_IS_AN_ANSWER
from product.models import Parcel, Product
from users.models import User

# Subtypes where a 0 with no fuel entered is a GAP, not an answer: no row, no card, and no
# "No direct emissions" line. A sanitation shake or brush shred runs a tractor.
GAP_WHEN_ZERO = {PestManagementEvent.CULTURAL_CONTROL}


class PestZeroCarbonCardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pestzero@test.com", password="x")
        company = Company.objects.create(name="Pest Zero Farm")
        establishment = Establishment.objects.create(name="PZF1", company=company, state="OR")
        product = Product.objects.create(name="Carrot")
        # ⚠️ Parcel.area is HECTARES (two-farm certifier sweep, 2026-08-20).
        parcel = Parcel.objects.create(name="BGA", establishment=establishment, area=7.527)
        self.history = History.objects.create(
            name="Carrots 2026",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _event(self, subtype, **kwargs):
        """A pest record. With no kwargs it carries NO fuel — the shape that lost its card."""
        return PestManagementEvent.objects.create(
            history=self.history,
            type=subtype,
            date=timezone.now(),
            description=f"{subtype} record",
            **kwargs,
        )

    def _entries(self, event):
        return CarbonEntry.objects.filter(
            production=self.history,
            description__icontains=f"PestManagementEvent(ID={event.id})",
        )

    # ------------------------------------------------------------------ the defect itself

    def test_a_zero_is_STORED_for_every_subtype_where_zero_is_the_answer(self):
        for subtype in PEST_SUBTYPES_ZERO_IS_AN_ANSWER:
            with self.subTest(subtype=subtype):
                entry = self._entries(self._event(subtype)).first()
                self.assertIsNotNone(
                    entry,
                    f"{subtype} stored no CarbonEntry, so the serializer answers carbon_data=null "
                    "and the modal hides the Carbon Impact card entirely.",
                )
                self.assertEqual(float(entry.co2e_amount or entry.amount or 0.0), 0.0)

    def test_the_serializer_serves_zero_rather_than_null(self):
        """End of the chain: what the client actually receives.

        Not vacuous: `test_cultural_control_zero_stays_a_gap` shows the same serializer, on the
        same fixture, still answering None when no row exists.
        """
        for subtype in PEST_SUBTYPES_ZERO_IS_AN_ANSWER:
            with self.subTest(subtype=subtype):
                data = PestManagementEventSerializer(self._event(subtype)).data
                self.assertIsNotNone(data["carbon_data"], "carbon_data is null — modal shows no card")
                self.assertEqual(data["carbon_data"]["co2e"], 0.0)

    def test_a_zero_from_nothing_does_not_claim_EPA_USDA_sourcing(self):
        """The badge must describe the calculation, not the country.

        `_add_enhanced_usda_metadata` flags every US event `usda_factors_based: True`, and the modal
        renders that as an "EPA/USDA-sourced" chip. With no fuel entered NO factor was applied.
        Before this change no row existed, so the badge could not show; storing the 0 would have
        shown it. Asserted on the computed, stored AND served values — `create_carbon_entry_from_event`
        has a one-way upgrade that used to flip a computed False back to True on the row.
        """
        calc = EventCarbonCalculator()
        for subtype in PEST_SUBTYPES_ZERO_IS_AN_ANSWER:
            with self.subTest(subtype=subtype):
                event = self._event(subtype)
                self.assertFalse(calc.calculate_pest_management_event_impact(event)["usda_factors_based"])

                entry = self._entries(event).first()
                self.assertIsNotNone(entry)
                self.assertFalse(entry.usda_factors_based, "stored entry still claims EPA/USDA sourcing")

                served = PestManagementEventSerializer(event).data["carbon_data"]
                self.assertFalse(served["usda_factors_based"], "client still receives the EPA/USDA badge")

    # ------------------------------------------------------------------ what must not change

    def test_reported_fuel_is_still_counted_and_earns_the_badge(self):
        """The other half: an EPA factor WAS applied, so the provenance is genuine."""
        event = self._event(PestManagementEvent.SCOUTING, fuel_consumed=4.0, fuel_unit="gal", fuel_type="diesel")
        served = PestManagementEventSerializer(event).data["carbon_data"]
        self.assertGreater(served["co2e"], 35.0)  # 4 gal x 10.21 kg/gal
        self.assertLess(served["co2e"], 45.0)
        self.assertTrue(served["usda_factors_based"], "a real EPA factor was applied; the badge is earned")

    def test_a_scouting_summary_counts_its_season_fuel_total(self):
        """The flag can be stored as True or as the string "true" (PestManagementTab's schema holds it
        as a string), and each used to lose the fuel a different way."""
        for flag in (True, "true"):
            with self.subTest(is_summary=flag):
                event = self._event(
                    PestManagementEvent.SCOUTING,
                    fuel_unit="gal",
                    fuel_type="diesel",
                    extra_data={"is_summary": flag, "fuel_consumed_total": "12"},
                )
                served = PestManagementEventSerializer(event).data["carbon_data"]
                self.assertIsNotNone(served, "summary fuel produced no stored row")
                self.assertGreater(served["co2e"], 110.0)  # 12 gal x 10.21 kg/gal
                self.assertLess(served["co2e"], 135.0)
                self.assertTrue(served["usda_factors_based"], "a real EPA factor was applied")

    def test_a_scouting_summary_without_fuel_is_a_stored_zero(self):
        event = self._event(PestManagementEvent.SCOUTING, extra_data={"is_summary": True})
        served = PestManagementEventSerializer(event).data["carbon_data"]
        self.assertIsNotNone(served)
        self.assertEqual(served["co2e"], 0.0)
        self.assertFalse(served["usda_factors_based"])

    def test_cultural_control_zero_stays_a_gap(self):
        """A sanitation shake with no fuel entered is missing data, not a zero-emission activity."""
        event = self._event(PestManagementEvent.CULTURAL_CONTROL)
        self.assertFalse(self._entries(event).exists())
        self.assertIsNone(PestManagementEventSerializer(event).data["carbon_data"])

    def test_a_failed_calculation_is_never_stored_as_zero(self):
        """The calculator's except branch returns co2e 0 plus an `error` key. Storing it would
        render "No direct emissions" for an event nobody computed (the F09 note in signals.py)."""
        failed = {"co2e": 0.0, "efficiency_score": 75.0, "verification_status": "calculation_error", "error": "boom"}
        with mock.patch.object(EventCarbonCalculator, "calculate_pest_management_event_impact", return_value=failed):
            event = self._event(PestManagementEvent.SCOUTING)
        self.assertFalse(self._entries(event).exists())

    def test_re_saving_keeps_exactly_one_row(self):
        """Zero rows are now written on every save; the update path must replace, not append."""
        event = self._event(PestManagementEvent.SCOUTING)
        event.description = "SC record, corrected"
        event.save()
        self.assertEqual(self._entries(event).count(), 1)

    # ------------------------------------------------------------------ the list itself

    def test_every_pest_subtype_is_sorted_into_answer_or_gap(self):
        """A new subtype must be decided, not defaulted. Unsorted, it silently gets no card."""
        answer = set(PEST_SUBTYPES_ZERO_IS_AN_ANSWER)
        self.assertFalse(answer & GAP_WHEN_ZERO, "a subtype cannot be both an answer and a gap")
        every_subtype = {code for code, _label in PestManagementEvent.PEST_TYPE_CHOICES}
        self.assertEqual(
            every_subtype,
            answer | GAP_WHEN_ZERO,
            "sort the new pest subtype into PEST_SUBTYPES_ZERO_IS_AN_ANSWER (history/signals.py) "
            "or GAP_WHEN_ZERO here",
        )
