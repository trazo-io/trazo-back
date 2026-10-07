"""The certifier page lists findings; scope rows fold away; grower instructions stay with the grower.

Recordkeeping review S9 (F-15, F-16, 2026-10-07). The certifier page printed 46 rows for 21
findings, 25 of them "Not assessed" (NA, INFO, NOT ASSESSED), and the finding text was the
grower's to-do list ("3/5 inputs have supplier — fill before audit", "Add buyer +
organic-on-invoice flag"). Packet 04 printed "the route is not determined (certifying agent not
recognised, or none named)" once per question per parcel, 42 to 54 times, as if about the
addressed agent.

Each test here went red on the code before the fix, on an assertion.
"""

from collections import namedtuple

from django.test import SimpleTestCase

from certifications.services.osp_module_pdf import _open_rows_sentence
from history.services.operation_audit_export_service import OperationAuditExportService

Row = namedtuple("Row", "ref state detail")


class CertifierWordingTests(SimpleTestCase):
    def test_grower_imperatives_are_dropped_and_the_fact_kept(self):
        f = OperationAuditExportService.certifier_detail
        self.assertEqual(f("3/5 inputs have supplier — fill before audit"), "3/5 inputs have supplier")
        self.assertEqual(
            f("Add buyer + organic-on-invoice flag"),
            "No sales record carries a buyer and the organic-on-invoice flag",
        )
        self.assertEqual(
            f("6 input record(s) not confirmed against the plan's inputs list — see Inputs Not Confirmed section"),
            "6 input record(s) not confirmed against the plan's inputs list",
        )
        self.assertEqual(
            f("2/5 chemical records missing required fields — target pest (2)"),
            "2/5 chemical records missing required fields — target pest (2)",
        )

    def test_packet_04_names_the_unresolved_parcels_once_with_the_answer_to_fix(self):
        reason = "Home Field East, Upper Terrace: the route is not determined: the parcel's prior certifying agent is not named"
        rows = [
            Row("2.1", "route_unresolved", reason),
            Row("2.4", "route_unresolved", reason),
            Row("3.0", "unanswered", ""),
        ]
        text = _open_rows_sentence(rows)
        self.assertEqual(text.count("Home Field East"), 1)
        self.assertIn(
            "2.1, 2.4 not determined for Home Field East, Upper Terrace: name each parcel's prior certifying agent",
            text,
        )
        self.assertIn("3.0 not yet answered", text)
        self.assertNotIn("certifying agent not recognised, or none named", text)
