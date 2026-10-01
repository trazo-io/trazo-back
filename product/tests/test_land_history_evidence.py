"""Land history says what the evidence covers, input by input and day by day, and nothing more.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, T21 and T17-F2.
  * The § 205.202(b) clock read chemical events only. A soil amendment or a beneficial release
    recorded as not organic-approved never moved it.
  * The 36-month accounting counted the operator's tenure as accounted for whatever the operator
    had said, so a parcel nobody had declared anything about read "every day is accounted for".
  * WSDA AGR 2264 ref 13's "N/A, no input materials applied" had no question of its own; the
    prohibited-material declaration was standing in for it.

The rules these cases hold (Oscar's Phase 3 corrections):
  * unknown is neither prohibited (it starts no clock) nor allowed (it blocks a clean statement);
  * a logged season is not coverage: no input events means none was recorded, not none applied;
  * only an explicit statement covers a day: the operator's declaration, or an affidavit period.
"""

import io
from datetime import date, datetime, timedelta

from django.test import TestCase
from django.utils import timezone

from dateutil.relativedelta import relativedelta
from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.parcel_land_history import coverage, season_evidence_lines
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, PestManagementEvent, SoilManagementEvent
from product.models import Parcel, Product
from product.services.parcel_application_status import parcel_application_status
from product.services.transition_status_service import (
    compute_transition_status,
    operator_statement_lines,
    transition_verdict,
)


def _aware(day: date):
    return timezone.make_aware(datetime(day.year, day.month, day.day, 9, 0))


class _Parcel(TestCase):
    def setUp(self):
        self.today = timezone.now().date()
        self.company = Company.objects.create(name="Evidence Co")
        self.est = Establishment.objects.create(name="Evidence Farm", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(
            name="Upper Block",
            establishment=self.est,
            area=4.0,
            date_began_managing=self.today - relativedelta(years=2),
        )
        self.product = Product.objects.create(name="Apples")

    def _season(self, start, end, name="Season"):
        return History.objects.create(
            name=name,
            parcel=self.parcel,
            product=self.product,
            start_date=_aware(start),
            finish_date=_aware(end) if end else None,
        )

    def _soil(self, season, day, status, product="Composted manure"):
        return SoilManagementEvent.objects.create(
            history=season,
            date=_aware(day),
            description="amendment",
            type=SoilManagementEvent.ORGANIC_MATTER,
            amendment_type="compost",
            amendment_product_name=product,
            amendment_organic_approved=status,
        )

    def _release(self, season, day, status, species="Aphidius colemani"):
        return PestManagementEvent.objects.create(
            history=season,
            type=PestManagementEvent.BENEFICIAL_RELEASE,
            date=_aware(day),
            description="release",
            beneficial_species=species,
            beneficial_organic_approved=status,
        )

    def _answers(self, **answers):
        self.parcel.application_answers = answers
        self.parcel.save(update_fields=["application_answers"])


class UnknownIsNotProhibitedTests(_Parcel):
    def test_a_not_organic_soil_amendment_starts_the_clock_on_its_date(self):
        day = self.today - timedelta(days=200)
        season = self._season(day - timedelta(days=30), None)
        self._soil(season, day, "not_organic")
        status = compute_transition_status(self.parcel)
        self.assertEqual(status.last_prohibited_date, day)
        self.assertEqual(status.transition_complete_date, day + relativedelta(months=36))
        self.assertIn("In transition", transition_verdict(status, has_field_history=True))

    def test_a_release_with_no_status_starts_no_clock_and_blocks_a_clean_statement(self):
        season = self._season(self.today - timedelta(days=100), None)
        self._release(season, self.today - timedelta(days=50), None)
        status = compute_transition_status(self.parcel)
        self.assertIsNone(status.last_prohibited_date)
        self.assertIsNone(status.transition_complete_date)
        verdict = transition_verdict(status, has_field_history=True)
        self.assertIn("Not established", verdict)
        self.assertIn("Aphidius colemani", verdict)
        self.assertNotIn("No prohibited substance on record", verdict)
        self.assertNotIn("In transition", verdict)

    def test_with_both_the_clock_runs_from_the_prohibited_one_and_the_unknown_is_still_named(self):
        prohibited_day = self.today - timedelta(days=300)
        season = self._season(prohibited_day - timedelta(days=10), None)
        self._soil(season, prohibited_day, "not_organic", product="Synthetic 10-10-10")
        self._release(season, self.today - timedelta(days=20), "")
        status = compute_transition_status(self.parcel)
        self.assertEqual(status.last_prohibited_date, prohibited_day)
        verdict = transition_verdict(status, has_field_history=True)
        self.assertIn("at the earliest", verdict)
        self.assertIn("Aphidius colemani", verdict)

    def test_an_unknown_input_older_than_the_window_does_not_block(self):
        old = self.today - relativedelta(months=40)
        season = self._season(old - timedelta(days=5), old + timedelta(days=5))
        self._release(season, old, None)
        self.assertEqual(compute_transition_status(self.parcel).unclassified, [])

    def test_an_allowed_amendment_moves_nothing(self):
        season = self._season(self.today - timedelta(days=90), None)
        self._soil(season, self.today - timedelta(days=60), "omri_listed")
        status = compute_transition_status(self.parcel)
        self.assertIsNone(status.last_prohibited_date)
        self.assertEqual(status.unclassified, [])


class ASeasonIsNotCoverageTests(_Parcel):
    def test_a_season_with_no_input_events_leaves_its_days_uncovered(self):
        self._season(self.today - timedelta(days=500), self.today - timedelta(days=200), name="2025 apples")
        account = coverage(self.parcel, [])
        self.assertFalse(account.complete)
        self.assertIn("no declaration", account.text)
        lines = " ".join(season_evidence_lines(self.parcel))
        self.assertIn("2025 apples", lines)
        self.assertIn("not a statement that none was applied", lines)

    def test_an_open_season_says_it_has_no_end_and_fills_no_gap(self):
        self._season(self.today - timedelta(days=60), None, name="Open season")
        self.assertFalse(coverage(self.parcel, []).complete)
        self.assertIn("no end date", " ".join(season_evidence_lines(self.parcel)))

    def test_a_partly_overlapping_season_prints_the_range_it_actually_spans(self):
        start = self.today - relativedelta(months=40)
        end = self.today - relativedelta(months=30)
        self._season(start, end, name="Old orchard season")
        line = " ".join(season_evidence_lines(self.parcel))
        self.assertIn(f"{start.isoformat()} to {end.isoformat()}", line)

    def test_seasons_alone_do_not_complete_the_land_history_check(self):
        for year in (1, 2, 3):
            self._season(self.today - relativedelta(years=year), self.today - relativedelta(years=year, days=-90))
        self.assertIn("land_history", parcel_application_status(self.parcel)["missing"])

    def test_a_declaration_covers_the_operators_own_period(self):
        self.parcel.date_began_managing = self.today - relativedelta(years=5)
        self.parcel.save(update_fields=["date_began_managing"])
        self.assertFalse(coverage(self.parcel, []).complete)
        self._answers(no_inputs_within_tenure=True)
        account = coverage(self.parcel, [])
        self.assertTrue(account.complete)
        self.assertIn("no input materials of any kind (declared)", account.text)


class NoInputsStatementTests(_Parcel):
    def test_yes_with_a_dated_input_inside_the_tenure_is_flagged(self):
        season = self._season(self.today - timedelta(days=90), None)
        self._soil(season, self.today - timedelta(days=30), "omri_listed")
        self._answers(no_inputs_within_tenure=True)
        lines = " ".join(operator_statement_lines(self.parcel))
        self.assertIn("states no input materials of any kind", lines)
        self.assertIn("[REVIEW] 1 dated input record(s)", lines)

    def test_unanswered_is_not_stated(self):
        lines = " ".join(operator_statement_lines(self.parcel))
        self.assertIn("has not stated whether any input materials were applied", lines)

    def test_no_is_a_declined_statement_never_an_application(self):
        self._answers(no_inputs_within_tenure=False)
        lines = " ".join(operator_statement_lines(self.parcel))
        self.assertIn("answered No to the statement that no input materials", lines)
        self.assertNotIn("was applied", lines)

    def test_the_parcel_page_prints_dated_inputs_beside_each_year(self):
        day = date(self.today.year, 1, 15) if self.today.month > 1 else date(self.today.year - 1, 6, 15)
        season = self._season(day - timedelta(days=5), None, name="This year")
        self._soil(season, day, "not_organic", product="Synthetic 10-10-10")
        ChemicalEvent.objects.create(
            history=season,
            date=_aware(day + timedelta(days=1)),
            description="spray",
            commercial_name="Mystery spray",
            organic_approved="",
        )
        osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        text = " ".join(
            extract_text(io.BytesIO(generate_module_pdf(osp, PARCEL_APPLICATION.key, parcel=self.parcel))).split()
        )
        self.assertIn(
            f"{day.isoformat()} · Synthetic 10-10-10 · soil amendment · recorded as not organic-approved", text
        )
        self.assertIn("Mystery spray · chemical application · organic status not recorded", text)
        self.assertIn("(dated record)", text)
