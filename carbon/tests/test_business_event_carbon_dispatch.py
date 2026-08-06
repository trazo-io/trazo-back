"""`calculate-event-carbon` must answer for business events instead of 500-ing.

`calculate_event_carbon_impact_enhanced` dispatches ``event_type == "business"`` to
``calculator_instance.calculate_business_event_impact`` — a method `OptimizedCarbonCalculator`
never defined. Every call raised AttributeError into the view's broad ``except Exception`` and
came back as HTTP 500 with a "Calculation failed" body, so the live carbon panel showed a
failure on the one event type whose subject is certification and trust.

`OptimizedEventProcessor.process_event_data` also had no business branch, so even once the
dispatch worked the processed payload dropped every business field and the calculator
described a generic "certification / pending" event regardless of what was entered.
"""

from django.test import TestCase

from carbon.views import OptimizedCarbonCalculator, OptimizedEventProcessor

FORM_PAYLOAD = {
    "business_type": "certification",
    "certification_type": "organic_usda",
    "verification_status": "verified",
    "sustainability_practice": "cover_cropping",
    "type": "CE",
    "name": "CCOF Annual Organic Inspection 2025",
}


class BusinessEventCarbonDispatchTests(TestCase):
    def test_calculator_exposes_the_method_the_view_dispatches_to(self):
        """The 500 was a missing method, so assert the attribute itself."""
        self.assertTrue(hasattr(OptimizedCarbonCalculator(), "calculate_business_event_impact"))

    def test_processor_keeps_the_business_fields(self):
        processed = OptimizedEventProcessor.process_event_data("business", FORM_PAYLOAD)
        self.assertEqual(processed["business_type"], "certification")
        self.assertEqual(processed["certification_type"], "organic_usda")
        self.assertEqual(processed["verification_status"], "verified")
        self.assertEqual(processed["sustainability_practice"], "cover_cropping")
        self.assertEqual(processed["business_subtype"], "CE")

    def test_calculation_returns_zero_direct_emissions_without_raising(self):
        processed = OptimizedEventProcessor.process_event_data("business", FORM_PAYLOAD)
        result = OptimizedCarbonCalculator().calculate_business_event_impact(processed)
        self.assertEqual(result["co2e"], 0.0)
        self.assertIn("direct_operational_emissions", result["calculation_method"])

    def test_breakdown_reflects_what_the_farmer_entered(self):
        """A generic default here would describe the wrong certification back to the grower."""
        processed = OptimizedEventProcessor.process_event_data("business", FORM_PAYLOAD)
        breakdown = OptimizedCarbonCalculator().calculate_business_event_impact(processed)["breakdown"]
        self.assertEqual(breakdown["certification_type"], "organic_usda")
        self.assertEqual(breakdown["verification_status"], "verified")
        self.assertEqual(breakdown["sustainability_practice"], "cover_cropping")
        self.assertEqual(breakdown["direct_emissions_kg"], 0.0)

    def test_missing_optional_fields_do_not_raise(self):
        """A half-filled form is the normal case mid-entry; it must still preview."""
        processed = OptimizedEventProcessor.process_event_data("business", {"business_type": "compliance"})
        result = OptimizedCarbonCalculator().calculate_business_event_impact(processed)
        self.assertEqual(result["co2e"], 0.0)
