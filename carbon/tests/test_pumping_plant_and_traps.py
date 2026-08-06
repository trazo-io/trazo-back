"""
Phase 4 / §E-6 + §E-7 — two California-coverage additions.

§E-6  A pump test is an ANNUAL measurement of ONE plant, so its results belong to the parcel,
      not repeated on every irrigation event. This is what makes the corrected irrigation
      carbon accurate rather than merely defensible: without a measured plant the calculator
      assumes 70% efficiency and derives pressure from the irrigation method. The UC Davis
      2024 organic-almond cost study budgets exactly one January pump test per year.

      Note the direction of the incentive. A neglected plant can fall below 50% efficiency,
      which RAISES emissions — so recording a real measurement can make the figure worse.
      That is correct: this is a measurement, not a credit.

§E-7  Trap types were insect-only (sticky card, pheromone lure, delta, bucket/funnel), while
      the same UC Davis study budgets gopher traps twice a year and ground-squirrel traps six
      times, March to October. Routine orchard work with nowhere to be recorded — and the
      practice most likely to be questioned at inspection, since the alternative is a
      rodenticide.
"""

from django.test import TestCase
from django.utils import timezone

from carbon.services.event_carbon_calculator import EventCarbonCalculator
from company.models import Company, Establishment
from history.models import History, PestManagementEvent, ProductionEvent
from product.models import Parcel, Product
from users.models import User


class PumpingPlantTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pump@test.com", password="x")
        company = Company.objects.create(name="Pump Farm")
        self.establishment = Establishment.objects.create(name="PF1", company=company, state="CA")
        self.product = Product.objects.create(name="Almond")
        self.calc = EventCarbonCalculator()

    def _production_on_parcel(self, **parcel_kwargs):
        parcel = Parcel.objects.create(name="pump-parcel", establishment=self.establishment, area=44.5, **parcel_kwargs)
        return History.objects.create(
            name="Pump Production",
            start_date=timezone.now(),
            product=self.product,
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

    def _irrigation_co2e(self, history):
        event = ProductionEvent.objects.create(
            history=history,
            type="IR",
            date=timezone.now(),
            description="Season irrigation",
            area_covered=110,
            area_unit="acres",
            water_source="well_groundwater",
            irrigation_method="drip",
            pump_depth_ft=120,
            irrigation_depth=42,
            irrigation_depth_unit="in",
        )
        return self.calc.calculate_production_event_impact(event)

    def test_parcel_fields_are_optional(self):
        """A farm without a pump test must still calculate."""
        result = self._irrigation_co2e(self._production_on_parcel())
        self.assertGreater(result["co2e"], 0)

    def test_a_measured_efficient_plant_lowers_the_figure(self):
        default = self._irrigation_co2e(self._production_on_parcel())["co2e"]
        efficient = self._irrigation_co2e(self._production_on_parcel(pump_efficiency_pct=80.0))["co2e"]
        self.assertLess(efficient, default)

    def test_a_measured_neglected_plant_raises_the_figure(self):
        """Recording a real measurement can make the number worse — that is the point."""
        default = self._irrigation_co2e(self._production_on_parcel())["co2e"]
        neglected = self._irrigation_co2e(self._production_on_parcel(pump_efficiency_pct=45.0))["co2e"]
        self.assertGreater(neglected, default)

    def test_measured_pressure_overrides_the_method_default(self):
        """Drip defaults to ~15 psi; a grower running 45 psi should see their own number."""
        method_default = self._irrigation_co2e(self._production_on_parcel())["co2e"]
        measured = self._irrigation_co2e(self._production_on_parcel(system_pressure_psi=45.0))["co2e"]
        self.assertGreater(measured, method_default)

    def test_efficiency_is_stored_as_percent_and_used_as_a_fraction(self):
        """80 must mean 80%, not 8000%. A unit slip here would collapse emissions to ~0."""
        result = self._irrigation_co2e(self._production_on_parcel(pump_efficiency_pct=80.0))
        self.assertAlmostEqual(result["breakdown"]["pumping_plant_efficiency"], 0.80, places=3)

    def test_breakdown_reports_the_measured_inputs(self):
        breakdown = self._irrigation_co2e(
            self._production_on_parcel(pump_efficiency_pct=72.5, system_pressure_psi=18.0)
        )["breakdown"]
        self.assertAlmostEqual(breakdown["pumping_plant_efficiency"], 0.725, places=3)
        self.assertEqual(breakdown["system_pressure_psi"], 18.0)


class PumpingPlantExportTests(TestCase):
    """The pump test is the basis for the irrigation energy figure, so it must be showable."""

    def setUp(self):
        user = User.objects.create_user(email="pumpexport@test.com", password="x")
        company = Company.objects.create(name="Pump Export Farm")
        establishment = Establishment.objects.create(name="PEF1", company=company, state="CA")
        self.parcel = Parcel.objects.create(
            name="pe-parcel",
            establishment=establishment,
            area=44.5,
            pump_efficiency_pct=72.5,
            system_pressure_psi=18.0,
            pump_test_date=timezone.now().date(),
            pump_test_provider="Valley Pump Testing",
        )
        product = Product.objects.create(name="Walnut")
        self.history = History.objects.create(
            name="Pump Export Production",
            start_date=timezone.now(),
            product=product,
            parcel=self.parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _carbon_text(self):
        from history.services.audit_export_service import AuditExportService

        out = []
        for el in AuditExportService(self.history, certification_type="all")._build_carbon_section():
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    if getattr(cell, "text", None):
                        out.append(cell.text)
            if getattr(el, "text", None):
                out.append(el.text)
        return " ".join(out)

    def test_pump_test_renders_in_the_carbon_appendix(self):
        text = self._carbon_text()
        self.assertIn("Irrigation Pumping Plant", text)
        self.assertIn("Valley Pump Testing", text)
        self.assertIn("72.5%", text)

    def test_it_stays_out_of_the_organic_packet(self):
        """Carbon is excluded from `organic` by design; the pump plant rides with it."""
        from history.services.audit_export_service import AuditExportService

        self.assertNotIn("carbon", AuditExportService.CERTIFICATION_SECTIONS["organic"])

    def test_absent_pump_test_renders_nothing(self):
        self.parcel.pump_efficiency_pct = None
        self.parcel.system_pressure_psi = None
        self.parcel.pump_test_date = None
        self.parcel.pump_test_provider = None
        self.parcel.save()
        self.assertNotIn("Irrigation Pumping Plant", self._carbon_text())


class VertebrateTrapTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="traps@test.com", password="x")
        company = Company.objects.create(name="Trap Farm")
        establishment = Establishment.objects.create(name="TF1", company=company, state="CA")
        parcel = Parcel.objects.create(name="t-parcel", establishment=establishment, area=10.0)
        product = Product.objects.create(name="Almond")
        self.history = History.objects.create(
            name="Trap Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def test_backend_accepts_the_vertebrate_trap_codes(self):
        codes = dict(PestManagementEvent._meta.get_field("trap_type").choices)
        self.assertIn("gopher_trap", codes)
        self.assertIn("ground_squirrel_trap", codes)

    def test_a_gopher_trapping_event_saves_and_renders_in_the_pdf(self):
        from history.services.audit_export_service import AuditExportService

        PestManagementEvent.objects.create(
            history=self.history,
            type="TM",
            date=timezone.now(),
            description="Gopher trap line, March set",
            pest_species="Pocket gopher",
            trap_type="gopher_trap",
            trap_count=100,
            pest_catch_count=14,
        )
        out = []
        for el in AuditExportService(self.history, certification_type="organic")._build_pest_section():
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    if getattr(cell, "text", None):
                        out.append(cell.text)
        text = " ".join(out)
        self.assertIn("Gopher trap", text, "the PDF label map is missing the vertebrate codes")
        self.assertIn("Pocket gopher", text)
