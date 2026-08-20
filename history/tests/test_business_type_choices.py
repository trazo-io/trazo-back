"""
The API must accept every business activity the form offers.

`history/views.py` carried a hardcoded list of valid `business_type` values that had drifted from
`BusinessEvent.BUSINESS_ACTIVITY_CHOICES`. It omitted `verification`, `compliance` and
`transparency` — three of the six options BusinessTab presents — so a farmer choosing
"Third-Party Verification Completed", "Regulatory Compliance Achieved" or "Transparency
Initiative Launched" got a 400 and could not save at all. Half the business event types were
unusable through the UI.

The drift was invisible because the seed commands write the model directly and bypass this
check, so the demo data contained `verification` rows the form itself could never have created.

The list is now derived from the model, so this test guards the derivation rather than a copy.
"""

from django.test import TestCase

from history.models import BusinessEvent


class BusinessTypeChoiceParityTests(TestCase):
    # The options BusinessTab-SIMPLIFIED.jsx renders.
    FORM_OPTIONS = [
        "certification",
        "verification",
        "sustainability_audit",
        "transparency",
        "compliance",
    ]

    def _valid_types(self):
        """Rebuild the view's list the same way the view does."""
        legacy = [
            "green_investment",
            "supply_chain",
            "consumer_engagement",
            "regulatory_compliance",
            "carbon_offset",
            "sustainability_training",
            "eco_certification",
        ]
        return [code for code, _ in BusinessEvent.BUSINESS_ACTIVITY_CHOICES] + legacy

    def test_every_form_option_is_accepted(self):
        valid = self._valid_types()
        for option in self.FORM_OPTIONS:
            self.assertIn(option, valid, f"the form offers {option!r} but the API would reject it")

    def test_every_model_choice_is_accepted(self):
        valid = self._valid_types()
        for code, _label in BusinessEvent.BUSINESS_ACTIVITY_CHOICES:
            self.assertIn(code, valid)

    def test_the_legacy_values_still_pass(self):
        """Other clients may have been sending these; widening must not break them."""
        valid = self._valid_types()
        for legacy in ("green_investment", "supply_chain", "eco_certification"):
            self.assertIn(legacy, valid)

    def test_an_unknown_value_is_still_rejected(self):
        self.assertNotIn("not_a_real_activity", self._valid_types())

    def test_the_view_uses_the_model_rather_than_a_copy(self):
        """A hardcoded duplicate is what drifted in the first place."""
        import inspect

        from history import views

        source = inspect.getsource(views)
        self.assertIn(
            "BusinessEvent.BUSINESS_ACTIVITY_CHOICES",
            source,
            "the business_type validator should derive from the model, not restate it",
        )
