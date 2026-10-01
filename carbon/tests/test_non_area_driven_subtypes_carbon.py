"""TP / BU / SS must not be charged a per-hectare field-diesel estimate on the SAVED path.

Three Production subtypes are not area-driven, and `PRODUCTION_TYPE_MAPPING` has said so since
2026-08-20 by routing all three to `_calculate_reported_fuel_only_emissions`:

  * SS — a § 205.204(a)(1) organic-seed commercial-availability search. Phone calls and
    catalogues. It burns nothing.
  * BU — a § 205.202(c) buffer harvest/disposal. A recordkeeping act about a boundary strip.
  * TP — a load moving off-farm. It scales with DISTANCE, not with the acreage of the parcel
    it left.

That fix reached only the live PREVIEW. `calculate_production_event_impact` has explicit
branches for IR / PO / PH / CM and a list covering HA, PL, PR, EM, TH, TR, CU, FP, MO; TP, BU
and SS matched none of them and fell to the `else`, which passed the LITERAL string
"general production" instead of the event's own subtype. So the map never saw "SS" — it saw
"GENERAL PRODUCTION", an unknown code, and fell through to 2.5 gal diesel/hectare. With no
`area_covered` of its own the estimate reads the PARCEL's acreage, so a seed search on a
16.4-acre block was charged 169.4 kg CO2e and the modal labelled it a "Major Activity".

Preview said 0.0, saved said 169.4, for the same event. PO escaped only because it also has an
explicit `elif` above the `else`.

⚠️ These tests go through `EventCarbonCalculator.calculate_production_event_impact` with a
REAL ProductionEvent, never through `calculate_production_event_emissions` directly. A
factor-level test passes on the broken code — the defect was entirely in which string the
caller handed the map, and the map was already correct. Nothing in the repo referenced
`reported_fuel_only` before this file, which is why the gap survived the fix that created it.
"""

from django.test import TestCase
from django.utils import timezone

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from carbon.services.verified_emission_factors import VerifiedEmissionFactors
from company.models import Company, Establishment
from history.models import History, ProductionEvent
from product.models import Parcel, Product
from users.models import User

# Not area-driven: charging these by the hectare is the wrong physical model.
NON_AREA_DRIVEN = ("TP", "BU", "SS")

# The parcel every event below sits on. Big enough that a per-hectare estimate is
# unmistakable — the whole point is that a silent fallback produces a LARGE wrong number,
# not a rounding difference.
PARCEL_HECTARES = 6.637  # 16.4 acres


class NonAreaDrivenSubtypeCarbonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="nonarea@test.com", password="x")
        company = Company.objects.create(name="Non-Area Farm")
        establishment = Establishment.objects.create(name="NAF1", company=company, state="OR")
        product = Product.objects.create(name="Carrot")
        # ⚠️ Parcel.area is HECTARES (two-farm certifier sweep, 2026-08-20).
        parcel = Parcel.objects.create(name="BGB", establishment=establishment, area=PARCEL_HECTARES)
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
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        self.calc = EventCarbonCalculator()

    def _event(self, subtype, **kwargs):
        """A record with NO area_covered and NO fuel — the shape that triggered the fallback."""
        return ProductionEvent.objects.create(
            history=self.history,
            type=subtype,
            date=timezone.now(),
            description=f"{subtype} record",
            **kwargs,
        )

    def _co2e(self, event):
        return self.calc.calculate_production_event_impact(event)["co2e"]

    # ------------------------------------------------------------------ the defect itself

    def test_no_reported_fuel_means_zero_not_an_acreage_estimate(self):
        for subtype in NON_AREA_DRIVEN:
            with self.subTest(subtype=subtype):
                self.assertEqual(self._co2e(self._event(subtype)), 0.0)

    def test_the_calculation_says_it_counted_fuel_not_area(self):
        """A zero can be reached by accident. Assert the ROUTE, not just the number."""
        for subtype in NON_AREA_DRIVEN:
            with self.subTest(subtype=subtype):
                result = self.calc.calculate_production_event_impact(self._event(subtype))
                self.assertEqual(result["calculation_method"], "reported_fuel_only")

    def test_the_acreage_estimate_was_genuinely_available_and_declined(self):
        """Anti-vacuity: prove the 0.0 above is a CHOICE, not an empty input.

        If the parcel area failed to resolve, every assertion in this file would pass for the
        wrong reason — a fallback reading 0 hectares also returns 0 kg. So compute what the
        general-production path WOULD have charged on this exact parcel and assert it is
        large. This is the number the saved path actually produced before the fix.
        """
        charged_if_area_driven = VerifiedEmissionFactors.calculate_production_event_emissions(
            production_type="general production",
            area_covered=PARCEL_HECTARES * 2.47105,  # the calculator converts to acres
            fuel_consumed=None,
            equipment_hours=0.0,
            fuel_type="diesel",
            energy_source="grid",
        )["co2e_kg"]
        self.assertGreater(charged_if_area_driven, 100.0)

    def test_a_zero_is_STORED_so_the_modal_can_render_it(self):
        """0 must reach the client as a number, not as an absent field.

        `get_carbon_data` reads CarbonEntry; with no row it answers `carbon_data: null`, and
        `EventDetailsModal` maps null onto its `error: 'Carbon data not available'` fallback.
        Both the Carbon Impact card and the zero-emission copy are gated on `!carbonData.error`,
        so the whole section silently disappears — the grower logs a § 205.204(a)(1) search and
        is shown nothing at all where a "0 kg CO2e — no direct emissions" belongs.

        The signal only writes a zero row for an allowlist of subtypes. Before 2026-08-22
        TP/BU/SS were never on it and never needed to be: they always had a (wrong) non-zero
        entry from the acreage estimate. Fixing the number moved them from "wrong figure" to
        "no card", which is why this asserts STORAGE, not just the computed value.
        """
        from carbon.models import CarbonEntry

        for subtype in NON_AREA_DRIVEN:
            with self.subTest(subtype=subtype):
                event = self._event(subtype)
                entry = CarbonEntry.objects.filter(
                    production=self.history,
                    description__icontains=f"ProductionEvent(ID={event.id})",
                ).first()
                self.assertIsNotNone(
                    entry,
                    f"{subtype} stored no CarbonEntry, so the serializer answers carbon_data=null "
                    "and the modal hides the Carbon Impact card entirely.",
                )
                self.assertEqual(float(entry.co2e_amount or entry.amount or 0.0), 0.0)

    def test_the_serializer_reports_zero_rather_than_null(self):
        """End of the chain: what the client actually receives."""
        from history.serializers import ProductionEventSerializer

        for subtype in NON_AREA_DRIVEN:
            with self.subTest(subtype=subtype):
                data = ProductionEventSerializer(self._event(subtype)).data
                self.assertIsNotNone(data["carbon_data"], "carbon_data is null — modal shows no card")
                self.assertEqual(data["carbon_data"]["co2e"], 0.0)

    def test_a_zero_from_nothing_does_not_claim_EPA_USDA_sourcing(self):
        """The badge must describe the calculation, not the country.

        `_add_enhanced_usda_metadata` flags `usda_factors_based: True` for every US event, and
        the modal renders that as an "EPA/USDA-sourced" chip next to the figure. When the
        reported-fuel-only route counts nothing, NO factor was applied — the 0 is the absence
        of an input. Badging it lends agency provenance to an absence, which is the
        `carbon-panel-provenance` failure: the citable half of a calculation vouching for the
        uncited half. Before 2026-08-22 these events ran the EPA diesel factor via the acreage
        estimate, so the badge was earned; correcting the number un-earned it.
        """
        for subtype in NON_AREA_DRIVEN:
            with self.subTest(subtype=subtype):
                event = self._event(subtype)
                result = self.calc.calculate_production_event_impact(event)
                self.assertFalse(result["usda_factors_based"])

                # ⚠️ Assert the STORED flag too, not just the computed one. The serializer
                # reads CarbonEntry, and `create_carbon_entry_from_event` used to overwrite
                # the freshly-written False back to True from the compliance record — a
                # ONE-WAY upgrade off `is_epa_factors_based`, which reports that validation
                # ran, not that a factor was applied. Checking only the calculation result
                # passed while the badge stayed on screen.
                from carbon.models import CarbonEntry

                entry = CarbonEntry.objects.filter(
                    production=self.history,
                    description__icontains=f"ProductionEvent(ID={event.id})",
                ).first()
                self.assertIsNotNone(entry)
                self.assertFalse(entry.usda_factors_based, "stored entry still claims EPA/USDA sourcing")

                from history.serializers import ProductionEventSerializer

                served = ProductionEventSerializer(event).data["carbon_data"]
                self.assertFalse(served["usda_factors_based"], "client still receives the EPA/USDA badge")

    def test_reported_fuel_DOES_earn_the_badge(self):
        """The other half: a real EPA factor was applied, so the provenance is genuine."""
        event = self._event("TP", fuel_consumed=12, fuel_unit="gal", fuel_type="diesel")
        result = self.calc.calculate_production_event_impact(event)
        self.assertGreater(result["co2e"], 0.0)
        self.assertTrue(result["usda_factors_based"])

        from history.serializers import ProductionEventSerializer

        served = ProductionEventSerializer(event).data["carbon_data"]
        self.assertTrue(served["usda_factors_based"], "a real EPA factor was applied; the badge is earned")

    # ------------------------------------------------------------------ what still counts

    def test_reported_fuel_is_still_counted(self):
        """The fix must not turn these subtypes into a carbon blind spot.

        Haul diesel is a real direct emission. An operator who enters it should see it — the
        rule is 'never ESTIMATE from acreage', not 'never emit'.
        """
        event = self._event("TP", fuel_consumed=12, fuel_unit="gal", fuel_type="diesel")
        co2e = self._co2e(event)
        self.assertGreater(co2e, 100.0)  # 12 gal x 10.21 kg/gal
        self.assertLess(co2e, 140.0)

    # ------------------------------------------------------------------ the class, not the case

    def test_every_production_subtype_routes_through_the_mapping(self):
        """The `else` must never again invent a production_type the map cannot recognise.

        Iterates the MODEL's own subtype list rather than a hand-typed one, so a subtype added
        to `PRODUCTION_EVENTS` without a carbon decision fails here instead of silently
        collecting the 2.5 gal/ha estimate. `calculate_production_event_emissions` logs a
        warning naming any unmapped code; an unmapped code is a decision nobody made.
        """
        mapped = set(VerifiedEmissionFactors.production_type_codes())
        declared = {code for code, _label in ProductionEvent.PRODUCTION_EVENTS}
        self.assertEqual(
            declared - mapped,
            set(),
            "Production subtype(s) with no entry in PRODUCTION_TYPE_MAPPING — each will be "
            "charged the 2.5 gal/hectare general-production estimate. Add an entry (use "
            "_calculate_reported_fuel_only_emissions if the activity is not area-driven).",
        )
