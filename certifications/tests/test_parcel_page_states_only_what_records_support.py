"""
Class A guards: the OSP packet's parcel page must not assert what the records do not support.

Two sentences on that page were making regulatory determinations on the operator's behalf:

  * "Eligible for organic harvest: Yes" — printed whenever no dated prohibited application was
    found, which is also what a parcel with NO field history at all looks like. Eligibility under
    § 205.202(b) is the certifying agent's call.
  * "crop in buffer (never sold as organic): <free text>" — the packet asserting the exact fact
    § 205.202(c) asks the operator to prove, off a free-text parcel field.

Both had already been corrected in the per-production audit export and left wrong in the packet —
the "fixed on the audited surface, alive on its sibling" class. These tests pin the shared
resolver and the wording so a third surface cannot reintroduce either.
"""

from datetime import date

from django.test import SimpleTestCase, TestCase

from product.services.transition_status_service import TransitionStatus, transition_verdict


def _status(**kw) -> TransitionStatus:
    base = dict(
        parcel_id=1,
        parcel_name="Home Field East",
        is_eligible=True,
        transition_complete_date=None,
        days_remaining=0,
        last_prohibited_date=None,
    )
    base.update(kw)
    return TransitionStatus(**base)


class TransitionVerdictTests(SimpleTestCase):
    def test_no_field_history_is_not_reported_as_eligible(self):
        # The defect, stated as a test: absence of contrary evidence is not evidence.
        verdict = transition_verdict(_status(is_eligible=True), has_field_history=False)
        self.assertIn("Not established", verdict)
        self.assertIn("205.202(b)", verdict)
        self.assertNotIn("Eligible", verdict.replace("Not established", ""))

    def test_eligible_only_when_field_history_backs_it(self):
        self.assertEqual(transition_verdict(_status(is_eligible=True), has_field_history=True), "Eligible")

    def test_unclassified_inputs_block_the_determination_without_claiming_transition(self):
        # "In transition" would assert a regulatory state — and the unfavourable one — that Trazo
        # has no basis for when nothing prohibited is on record.
        verdict = transition_verdict(
            _status(is_eligible=False, unclassified=[object()]),
            has_field_history=True,
        )
        self.assertIn("Not established from records in Trazo", verdict)
        self.assertNotIn("In transition", verdict)

    def test_a_dated_prohibited_application_reports_the_clock(self):
        verdict = transition_verdict(
            _status(
                is_eligible=False,
                last_prohibited_date=date(2024, 5, 1),
                transition_complete_date=date(2027, 5, 1),
                days_remaining=246,
            ),
            has_field_history=True,
        )
        self.assertIn("In transition", verdict)
        self.assertIn("246", verdict)

    def test_never_prints_a_bare_yes_or_no(self):
        # The old line was "Eligible for organic harvest: Yes" / "Not yet" — a verdict shaped like
        # an answer the operator gave. Every branch must read as a status, not a ruling.
        for kwargs, history in (
            (dict(is_eligible=True), False),
            (dict(is_eligible=True), True),
            (dict(is_eligible=False, unclassified=[object()]), True),
            (dict(is_eligible=False, last_prohibited_date=date(2024, 1, 1), days_remaining=10), True),
        ):
            verdict = transition_verdict(_status(**kwargs), has_field_history=history)
            self.assertNotIn("Yes", verdict)
            self.assertNotIn("Not yet", verdict)


class BufferCropWordingTests(SimpleTestCase):
    """Asserts on what the page RENDERS, not on the source text.

    The first version of this grepped osp_module_pdf.py and failed on the comments that explain
    the old wording — a test that cannot tell an assertion from an explanation of why it was
    removed. Render the flowables and read them.
    """

    def _rendered(self, buffer_zones):
        from certifications.services.osp_module_pdf import _parcel_embed_flowables, _styles

        class _Parcel:
            def __init__(self, rows):
                self.buffer_zones = rows

        flowables = _parcel_embed_flowables("buffer_editor", _Parcel(buffer_zones), _styles())
        return " ".join(getattr(f, "text", "") for f in flowables)

    def test_the_packet_names_the_buffer_crop_without_ruling_on_its_organic_status(self):
        text = self._rendered(
            [
                {
                    "direction": "West",
                    "adjoining_land_use": "Conventional ryegrass",
                    "crop_grown_in_buffer": "Blueberries",
                }
            ]
        )
        self.assertIn("crop grown in buffer: Blueberries", text)
        self.assertNotIn("never sold as organic", text)
        self.assertNotIn("not sold as organic", text)

    def test_a_parcel_with_no_buffer_rows_says_so_rather_than_printing_empty_clauses(self):
        self.assertIn("No buffer or adjoining-land records on file", self._rendered([]))


class AffidavitDatesTheTransitionClockTests(TestCase):
    """The signed affidavit is a transition-clock source, not decoration.

    Before this, a packet could print "Eligible" on the same page as an affidavit whose signer had
    dated a prohibited application — two contradicting facts in one PDF, because only one of them
    reached the clock. The affidavit covers exactly the years Trazo has no events for, which is the
    period § 205.202(b) is about.
    """

    def setUp(self):
        from company.models import Company, Establishment
        from product.models import Parcel

        company = Company.objects.create(name="Brandt Family Farms LLC")
        establishment = Establishment.objects.create(name="Calapooia Bend Farm", company=company)
        self.parcel = Parcel.objects.create(name="Bottom Ground A", establishment=establishment, area=7.5)

    def _affidavit(self, **kw):
        from certifications.models import LandownerAffidavit

        return LandownerAffidavit.objects.create(parcel=self.parcel, **kw)

    def test_a_dated_affidavit_moves_the_clock_and_blocks_eligibility(self):
        from datetime import date, timedelta

        from product.services.transition_status_service import compute_transition_status, transition_verdict

        recent = date.today() - timedelta(days=200)
        self._affidavit(last_prohibited_date=recent)

        status = compute_transition_status(self.parcel)
        self.assertFalse(status.is_eligible, "an affidavit dating a prohibited application must block eligibility")
        self.assertEqual(status.last_prohibited_date, recent)
        self.assertIn("In transition", transition_verdict(status, has_field_history=True))

    def test_an_affidavit_attesting_none_were_applied_is_not_a_finding(self):
        # NULL on this field is the signed negative — "none in living memory" — not missing data.
        from product.services.transition_status_service import compute_transition_status

        self._affidavit(last_prohibited_date=None)
        status = compute_transition_status(self.parcel)
        self.assertEqual(status.findings, [])
        self.assertIsNone(status.last_prohibited_date)

    def test_the_latest_source_wins_across_affidavit_and_field_history(self):
        from datetime import date, timedelta

        from product.models import ParcelCropHistory
        from product.services.transition_status_service import compute_transition_status

        older = date.today() - timedelta(days=1500)
        newer = date.today() - timedelta(days=400)
        ParcelCropHistory.objects.create(parcel=self.parcel, year=older.year, date_last_prohibited=older)
        self._affidavit(last_prohibited_date=newer)

        status = compute_transition_status(self.parcel)
        self.assertEqual(status.last_prohibited_date, newer, "the most recent prohibited date sets the clock")
