"""The export may state what Trazo KNOWS. It may not state FDA's enforcement calendar.

WHY THIS EXISTS
---------------
🔴 2026-08-29. The regulatory-scope section — which prints in the ORGANIC packet, not only the
FSMA variant — told a certifier that FSMA 204 KDEs were "required at harvest, cooling, packing,
and shipping **by 2028-07-20**", and a code comment called the rule "effective 2028-07-20".

A COMPLIANCE DATE and an ENFORCEMENT MORATORIUM are different things. The rule's own compliance
date (January 20, 2026) has passed and the recordkeeping obligation is live. What points at
2028-07-20 is an appropriations rider barring FDA from spending to enforce — which expires with
the fiscal year and must be renewed. The 30-month extension published 2025-08-07 was a PROPOSED
rule; no final rule followed. So the packet told a grower's certifier that an obligation was not
yet in force when it was.

THE RULE THIS PINS. Trazo does not track any agency's enforcement calendar, so no generated
document may assert a future compliance date as fact. Report FTL membership — which Trazo does
know — and send the operator to the authority for dates. This is the same discipline as the
carbon appendix: state the basis you have, never the verdict you do not.
"""

import inspect
import re

from django.test import SimpleTestCase

from history.services import audit_export_service


def _reader_text(source: str) -> str:
    """Approximate what a READER of the generated PDF can see, from Python source.

    Two things have to go, and the first cut of this test forgot both:

      * COMMENTS. The explanation of why a claim was removed necessarily quotes the claim, so a
        naive substring search finds the fix and calls it the bug. That is how these assertions
        first failed against a file that was already correct.
      * IMPLICIT CONCATENATION. A sentence split across lines as `"...and " "enforcement..."`
        contains the phrase for a reader and not for `str.__contains__`, so the boundary quotes
        and the whitespace between them are collapsed.
    """
    lines = [line for line in source.splitlines() if not line.lstrip().startswith("#")]
    text = "\n".join(lines)
    text = re.sub(r'"\s*\n\s*"', "", text)  # join adjacent string literals
    return re.sub(r"\s+", " ", text)


def _printed_strings() -> str:
    return _reader_text(inspect.getsource(audit_export_service))


def _scope_section_text() -> str:
    return _reader_text(inspect.getsource(audit_export_service.AuditExportService._build_regulatory_scope_section))


class NoRegulatoryDateClaimsTests(SimpleTestCase):
    def test_no_future_fsma_compliance_date_is_asserted_to_a_reader(self):
        printed = _printed_strings()
        self.assertNotIn(
            "2028-07-20",
            printed,
            "a generated document must not assert FDA's enforcement date as fact; "
            "explain it in a comment if a maintainer needs the history",
        )

    def test_the_status_line_reports_membership_not_a_deadline(self):
        service_src = _scope_section_text()
        self.assertIn("Food Traceability List", service_src)
        # "required by <date>" is the shape that misstated the obligation.
        self.assertIsNone(
            re.search(r"required.{0,40}by \d{4}-\d{2}-\d{2}", service_src),
            "the export must not tell a certifier when an obligation starts",
        )

    def test_it_defers_to_the_authority_for_dates(self):
        self.assertIn("Confirm the current compliance and enforcement dates", _scope_section_text())

    def test_it_does_not_overclaim_what_trazo_produces(self):
        # FSMA 204 compliance is a written traceability plan plus KDEs linked to a lot code the
        # INITIAL PACKER assigns. Trazo produces neither, and the export now says so rather than
        # implying its lot tracking is FSMA 204 coverage.
        self.assertIn("does not produce a FSMA 204 traceability plan", _scope_section_text())

    def test_no_other_agency_deadline_is_asserted_either(self):
        # Anti-recurrence: the class is "Trazo stating someone else's calendar", not this one date.
        printed = _printed_strings()
        offenders = re.findall(
            r"(?:effective|required|enforced|mandatory)\s+(?:by|from|on)\s+20\d\d-\d\d-\d\d", printed
        )
        self.assertEqual(offenders, [], f"regulatory dates asserted to a reader: {offenders}")
