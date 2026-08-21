"""The readiness card must not ask a grower to fix a practice they do not do.

`AuditExportService.compliance_snapshot_rows()` emits five statuses: PASS, REVIEW, FAIL, NA
and "NOT ASSESSED". Only REVIEW and FAIL are action items. NA means the practice does not
occur in this period; NOT ASSESSED means there are no records of that kind to judge. The
packet renders both as a grey "N/A".

Until 2026-08-19 the endpoint filtered out PASS alone, so NA and NOT ASSESSED reached the
CertifierReadinessCard — which models two states and paints anything that is not FAIL as
amber "Needs attention". A walnut orchard's farm page told it that "No raw manure events this
period" and "No pest-control applications and no threshold records on file" needed attention,
and counted both toward the open-items headline.
"""

from django.test import TestCase

from company.views import ACTIONABLE_READINESS_STATUSES


class ActionableReadinessStatusTests(TestCase):
    def test_only_review_and_fail_are_actionable(self):
        self.assertEqual(ACTIONABLE_READINESS_STATUSES, frozenset({"REVIEW", "FAIL"}))

    def test_absence_states_are_not_actionable(self):
        # INFO joined this list on 2026-08-19: it is the status for something reported but not
        # owed — the photo count, and Land requirements where nothing is the grower's to fix.
        for status in ("PASS", "NA", "NOT ASSESSED", "INFO"):
            self.assertNotIn(
                status,
                ACTIONABLE_READINESS_STATUSES,
                f"{status!r} is not something a grower can act on; forwarding it to the "
                "readiness card displays it as 'Needs attention' and inflates the headline",
            )

    def test_every_status_the_snapshot_can_emit_is_accounted_for(self):
        """A new status must be classified deliberately, not inherited by omission."""
        import re
        from pathlib import Path

        src = Path(__file__).resolve().parent.parent.parent
        text = (src / "history" / "services" / "audit_export_service.py").read_text()

        # Statuses are the second element of the (label, status, detail) snapshot tuples.
        emitted = set(re.findall(r'snapshot_rows\.append\(\s*\(\s*[^,]+,\s*"([A-Z ]+)"', text))
        emitted |= set(re.findall(r'"(PASS|REVIEW|FAIL|NA|NOT ASSESSED)"\s*,\s*\n?\s*"', text))

        known = {"PASS", "REVIEW", "FAIL", "NA", "NOT ASSESSED", "INFO"}
        unknown = emitted - known
        self.assertEqual(
            unknown,
            set(),
            f"compliance_snapshot_rows() emits status(es) {sorted(unknown)} that this module "
            "has never classified as actionable or not. Decide, then add it here.",
        )
