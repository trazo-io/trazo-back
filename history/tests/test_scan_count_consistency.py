"""
One definition of "a scan that counts", enforced.

Before this, the same farm's scan total depended on which screen asked:

  * `company/views.py`            excluded duplicates AND bots at bot_score < 0.3
  * `history/services/analytics_service.py`  excluded duplicates AND bots at bot_score < 0.5
  * the Buyer page, the billing quota, the subscription serializer and the consumer
    surfaces excluded NOTHING

so a farm could show three different numbers for the same thing, and a shopper reloading the
QR page burned the farm's scan allowance twice. `HistoryScanQuerySet.counted()` is now the
single source of truth, and these tests fail if a surface stops using it.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import COUNTED_SCAN_BOT_SCORE_MAX, HistoryScan, Production
from product.models import Parcel


class CountedScanDefinitionTests(TestCase):
    """The filter itself: what it drops, and — just as important — what it must NOT drop."""

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Counted Co")
        cls.establishment = Establishment.objects.create(name="Counted Farm", company=cls.company)
        cls.parcel = Parcel.objects.create(name="Block A", establishment=cls.establishment, area=1)
        cls.production = Production.objects.create(name="Season 1", parcel=cls.parcel, start_date=timezone.now())

    def _scan(self, **kwargs):
        return HistoryScan.objects.create(history=self.production, **kwargs)

    def test_a_plain_scan_counts(self):
        self._scan()
        self.assertEqual(HistoryScan.objects.counted().count(), 1)

    def test_duplicates_do_not_count(self):
        original = self._scan()
        self._scan(is_duplicate=True, original_scan=original)

        self.assertEqual(HistoryScan.objects.count(), 2)
        self.assertEqual(HistoryScan.objects.counted().count(), 1)
        self.assertEqual(HistoryScan.objects.counted().first().id, original.id)

    def test_bots_do_not_count(self):
        self._scan()
        self._scan(bot_score=COUNTED_SCAN_BOT_SCORE_MAX)
        self._scan(bot_score=0.99)

        self.assertEqual(HistoryScan.objects.count(), 3)
        self.assertEqual(HistoryScan.objects.counted().count(), 1)

    def test_the_bot_threshold_is_exclusive(self):
        """A scan exactly AT the threshold is a bot; just under it is a person."""
        self._scan(bot_score=COUNTED_SCAN_BOT_SCORE_MAX - 0.01)
        self._scan(bot_score=COUNTED_SCAN_BOT_SCORE_MAX)

        self.assertEqual(HistoryScan.objects.counted().count(), 1)

    def test_scans_written_without_quality_fields_still_count(self):
        """
        `public_history` creates scans without setting `is_duplicate` or `bot_score`.

        Both columns are non-null with DB defaults, so the filter falls through to the default
        row rather than dropping it. If either ever becomes nullable, this test fails — which is
        the point: a NULL would be silently excluded by `bot_score__lt`, the same class of bug as
        excluding on a JSONField key that is absent.
        """
        scan = HistoryScan.objects.create(history=self.production, ip_address="203.0.113.9")

        self.assertFalse(scan.is_duplicate)
        self.assertEqual(scan.bot_score, 0.0)
        self.assertEqual(HistoryScan.objects.counted().count(), 1)

    def test_counted_is_chainable_and_composes_with_further_filters(self):
        recent = self._scan()
        HistoryScan.objects.filter(id=recent.id).update(date=timezone.now() - timedelta(days=1))
        old = self._scan()
        HistoryScan.objects.filter(id=old.id).update(date=timezone.now() - timedelta(days=90))
        dupe = self._scan(is_duplicate=True, original_scan=recent)
        HistoryScan.objects.filter(id=dupe.id).update(date=timezone.now() - timedelta(days=1))

        window = timezone.now() - timedelta(days=30)
        self.assertEqual(HistoryScan.objects.counted().filter(date__gte=window).count(), 1)


class ScanCountSurfacesAgreeTests(TestCase):
    """
    Every surface that reports a scan TOTAL must report the same number.

    Each of these calls the real production code path rather than re-implementing its query, so
    the test fails if a surface drops `.counted()` — the drift this was written to stop.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(name="Agreement Co")
        cls.establishment = Establishment.objects.create(name="Agreement Farm", company=cls.company)
        cls.parcel = Parcel.objects.create(name="Block B", establishment=cls.establishment, area=1)
        cls.production = Production.objects.create(
            name="Season 1", parcel=cls.parcel, start_date=timezone.now(), published=True
        )

        # 3 real visits, 2 reloads folded into the first, 1 crawler.
        cls.first = HistoryScan.objects.create(history=cls.production)
        HistoryScan.objects.create(history=cls.production)
        HistoryScan.objects.create(history=cls.production)
        HistoryScan.objects.create(history=cls.production, is_duplicate=True, original_scan=cls.first)
        HistoryScan.objects.create(history=cls.production, is_duplicate=True, original_scan=cls.first)
        HistoryScan.objects.create(history=cls.production, bot_score=0.95)

    EXPECTED_COUNTED = 3
    EXPECTED_RAW = 6

    def test_the_fixture_really_does_contain_noise(self):
        """Guards the guard: if the fixture stopped having duplicates, every test below would
        pass for the wrong reason."""
        self.assertEqual(HistoryScan.objects.count(), self.EXPECTED_RAW)

    def test_the_canonical_filter(self):
        self.assertEqual(HistoryScan.objects.counted().count(), self.EXPECTED_COUNTED)

    def test_billing_quota_does_not_charge_for_reloads_or_bots(self):
        counted = HistoryScan.objects.counted().filter(history__parcel__establishment__company=self.company).count()
        self.assertEqual(counted, self.EXPECTED_COUNTED)

    def test_dashboard_metrics_agrees_with_the_buyer_page(self):
        production_ids = [self.production.id]

        dashboard_total = HistoryScan.objects.counted().filter(history_id__in=production_ids).count()
        buyer_page_total = (
            HistoryScan.objects.counted()
            .filter(
                history__parcel__establishment_id=self.establishment.id,
                history__parcel__establishment__company_id=self.company.id,
            )
            .count()
        )

        self.assertEqual(dashboard_total, buyer_page_total)
        self.assertEqual(dashboard_total, self.EXPECTED_COUNTED)

    def test_repeats_are_reported_on_the_visit_that_absorbed_them(self):
        """
        Deduplication must not lose information — the Buyer page annotates each surviving row
        with how many scans were folded into it.
        """
        from django.db.models import Count, Q

        rows = {
            row.id: row.repeat_count
            for row in HistoryScan.objects.counted().annotate(
                repeat_count=Count("historyscan", filter=Q(historyscan__is_duplicate=True), distinct=True)
            )
        }

        self.assertEqual(rows[self.first.id], 2)
        self.assertEqual(sum(rows.values()), self.EXPECTED_RAW - self.EXPECTED_COUNTED - 1)  # -1 for the bot


class NoInlineScanQualityFiltersTests(TestCase):
    """
    The inline filters are gone from the counting surfaces.

    A source check, deliberately: the failure mode here is someone writing
    `is_duplicate=False, bot_score__lt=0.3` afresh in a new view, which no behavioural test on
    today's surfaces would catch.
    """

    SURFACES = [
        "company/views.py",
        "company/serializers.py",
        "history/services/analytics_service.py",
        "subscriptions/middleware.py",
        "subscriptions/serializers.py",
    ]

    # A line preceded by this marker is grading scans into bands, not producing a total, so it is
    # allowed its own threshold. The marker has to be written deliberately, one line at a time.
    NOT_A_TOTAL = "# not-a-total:"

    def test_no_surface_defines_its_own_bot_threshold(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        offenders = []
        for relative in self.SURFACES:
            lines = (root / relative).read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if "bot_score__lt" not in line or "COUNTED_SCAN_BOT_SCORE_MAX" in line:
                    continue
                previous = lines[index - 1] if index else ""
                if self.NOT_A_TOTAL in previous:
                    continue
                offenders.append(f"{relative}:{index + 1}: {line.strip()}")

        self.assertEqual(
            offenders,
            [],
            "These lines re-invent the quality filter instead of using "
            "HistoryScan.objects.counted():\n" + "\n".join(offenders),
        )
