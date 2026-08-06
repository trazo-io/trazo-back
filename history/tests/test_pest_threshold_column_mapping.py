"""The pest form's threshold answer must land on its real model column.

The event form's only threshold control is "Economic Threshold Status", which posts
``economic_threshold_met`` — a key with no model column, routed into ``extra_data``. Nothing
posted ``action_threshold_met``, so that column stayed NULL on every UI-logged pest event and
``audit_export_service`` (which reads the column) printed "Not assessed" in the certifier
dossier for a grower who had explicitly answered "threshold not met".

Two rules are load-bearing here and are pinned below:
  * an affirmative answer is recorded on the column (the misreport this fixes), and
  * a blank answer still means "not assessed" (None), never a fabricated False — the F17
    rule that absence of an attestation is not a denial.
"""

from django.test import TestCase

from history.serializers import UpdatePestManagementEventSerializer


class PestThresholdColumnMappingTests(TestCase):
    """`economic_threshold_met` (form) -> `action_threshold_met` (column the PDF reads)."""

    def _internal(self, **overrides):
        payload = {
            "type": "TM",
            "date": "2025-05-28T07:15:00Z",
            "description": "Weekly NOW trap check",
            "pest_species": "Navel orangeworm (Amyelois transitella)",
        }
        payload.update(overrides)
        return UpdatePestManagementEventSerializer().to_internal_value(payload)

    def test_below_threshold_answer_reaches_the_column(self):
        """ "Not met" is an affirmative IPM finding, not a missing one."""
        self.assertIs(self._internal(economic_threshold_met="false").get("action_threshold_met"), False)

    def test_threshold_met_answer_reaches_the_column(self):
        self.assertIs(self._internal(economic_threshold_met="true").get("action_threshold_met"), True)

    def test_native_booleans_are_accepted(self):
        """The form posts strings, but the API also accepts real booleans."""
        self.assertIs(self._internal(economic_threshold_met=True).get("action_threshold_met"), True)
        self.assertIs(self._internal(economic_threshold_met=False).get("action_threshold_met"), False)

    def test_blank_answer_stays_not_assessed(self):
        """F17: a blank threshold answer must not be coerced into a definitive False."""
        self.assertIsNone(self._internal(economic_threshold_met="").get("action_threshold_met"))

    def test_absent_answer_stays_not_assessed(self):
        self.assertIsNone(self._internal().get("action_threshold_met"))

    def test_unrecognised_answer_is_not_guessed(self):
        """An unknown token must not silently become False — that would fabricate a record."""
        self.assertIsNone(self._internal(economic_threshold_met="maybe").get("action_threshold_met"))

    def test_explicit_column_value_wins_over_the_form_key(self):
        """An API caller sending the column directly is authoritative."""
        internal = self._internal(action_threshold_met=True, economic_threshold_met="false")
        self.assertIs(internal.get("action_threshold_met"), True)

    def test_explicit_false_on_the_column_is_not_overwritten(self):
        """False is an answer, not an absence.

        Guarding with `not data.get(...)` instead of `is None` would let the form key flip an
        explicit "assessed, below threshold" into "threshold met" — inventing a NOP 205.206(e)
        treatment trigger that the operation never recorded.
        """
        internal = self._internal(action_threshold_met=False, economic_threshold_met="true")
        self.assertIs(internal.get("action_threshold_met"), False)

    def test_extra_data_copy_is_preserved(self):
        """Existing readers still find the answer where it has always been."""
        internal = self._internal(economic_threshold_met="false")
        self.assertEqual(internal.get("extra_data", {}).get("economic_threshold_met"), "false")
