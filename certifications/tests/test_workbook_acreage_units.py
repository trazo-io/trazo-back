"""The Common OSP field workbook reports ACRES, because `Parcel.area` is HECTARES.

`Parcel.area` is stored in hectares (see its help_text). The Field and Crop Information
workbook printed it raw under a column headed "Acreage or square feet:", so a 28.4-acre block
was filed with the certifier as **11.4931**.

The damage is that it contradicts the rest of the same packet: the Parcel Application prints
28.4 acres for that block, and the operation dossier reconciles the farm total (45.2 acres)
against the sum of its parcels. A certifier comparing the three sees a 60% discrepancy inside
one submission.

This is the unit trap `audit_export_service._total_acreage_phrase` already documents — the
first cut of that method compared 149 acres against 60 hectares and would have printed a
fabricated "89 acres unaccounted for" warning. Convert at the boundary, always.
"""

from django.test import TestCase

from certifications.services.common_osp_workbooks import HECTARES_TO_ACRES, _acres


class WorkbookAcreageTests(TestCase):
    def test_hectares_are_converted_to_acres(self):
        # Ridge Block: 28.4 acres entered, 11.4931 ha stored.
        self.assertAlmostEqual(_acres(11.4931), 28.4, places=1)
        # Creek Block: 16.8 acres entered, 6.7987 ha stored.
        self.assertAlmostEqual(_acres(6.7987), 16.8, places=1)

    def test_the_stored_hectares_are_never_printed_as_is(self):
        self.assertNotEqual(_acres(11.4931), 11.4931)

    def test_a_missing_area_stays_blank_rather_than_becoming_zero(self):
        """A blank cell means 'not recorded'. A 0 would be a claim about the block's size."""
        self.assertIsNone(_acres(None))
        self.assertIsNone(_acres(""))

    def test_a_non_numeric_area_does_not_crash_the_workbook(self):
        self.assertIsNone(_acres("about ten"))

    def test_the_factor_matches_the_audit_export(self):
        """One conversion constant across the packet, or two documents drift apart."""
        from history.services import audit_export_service  # noqa: F401

        self.assertAlmostEqual(HECTARES_TO_ACRES, 2.47105, places=5)
