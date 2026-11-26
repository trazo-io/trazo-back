"""7 CFR 205.103(b)(4) — records "maintained for not less than 5 years beyond their creation".

This clause had an implementation (`compute_retention_until` plus a deletion guard on
`History`) and no dedicated test. The gap surfaced when the binding-clause conformance matrix
was built: the clause named a proof module that did not exist, and the coverage guard refused
the citation. That is the matrix doing its job — a clause claiming to be handled must name a
test, and the test must be real.

Two things are worth pinning here, and only one of them is obvious:

  * the guard refuses deletion inside the window (the obvious half);
  * the window is five CALENDAR years, not 1825 days. Every five-year span contains at least
    one leap day, so day arithmetic lands 1-2 days SHORT — and "not less than 5 years" makes
    short the one direction that is non-compliant.
"""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from history.models import Production, compute_retention_until
from history.retention import RecordLocked, assert_child_record_deletable
from product.models import Product


class RetentionWindowArithmeticTests(TestCase):
    """`compute_retention_until` is a module-level function so it can be tested directly.

    Deliberately NOT re-implemented in the assertions: the first version of this check
    computed the expected value with the same arithmetic as the code, so it passed against
    the broken 1825-day implementation too. The expectations below are written out literally.
    """

    def test_five_calendar_years_not_1825_days(self):
        # MEASURED regression: a production finishing 2026-08-08 was stamped 2031-08-07,
        # one day short, because the window always contains at least one leap day.
        self.assertEqual(compute_retention_until(date(2026, 8, 8)), date(2031, 8, 8))

    def test_a_day_arithmetic_implementation_would_fail_this(self):
        """Guards the guard: prove the naive version really is short."""
        naive = date(2026, 8, 8) + timedelta(days=5 * 365)
        self.assertLess(naive, compute_retention_until(date(2026, 8, 8)))

    def test_leap_day_rounds_forward_not_back(self):
        """29 February has no counterpart five years later.

        Rounding to 28 February would be a day SHORT of "not less than 5 years"; 1 March is a
        day over, which the regulation permits.
        """
        self.assertEqual(compute_retention_until(date(2024, 2, 29)), date(2029, 3, 1))

    def test_accepts_a_datetime_as_well_as_a_date(self):
        stamped = timezone.now().replace(year=2026, month=8, day=8)
        self.assertEqual(compute_retention_until(stamped), date(2031, 8, 8))


class RetentionDeletionGuardTests(TestCase):
    """The product must not be the reason a record disappears early."""

    def _production(self, retention_until=None):
        return Production.objects.create(
            name="Retention test production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Avocado"),
            retention_until=retention_until,
        )

    def test_deletion_inside_the_window_is_refused(self):
        production = self._production(retention_until=timezone.now().date() + timedelta(days=365))
        with self.assertRaises(ValidationError) as ctx:
            production.delete()

        self.assertIn("205.103(b)(4)", str(ctx.exception))
        self.assertTrue(
            Production.objects.filter(pk=production.pk).exists(),
            "The row must still be there — a guard that raises AFTER deleting is not a guard.",
        )

    def test_deletion_after_the_window_is_allowed(self):
        """The clause is a floor, not a prohibition. Past it, the operator's data is theirs."""
        production = self._production(retention_until=timezone.now().date() - timedelta(days=1))
        pk = production.pk
        production.delete()
        self.assertFalse(Production.objects.filter(pk=pk).exists())

    def test_no_retention_date_does_not_block_deletion(self):
        """An unfinished production has no retention floor yet; blocking it would strand
        drafts and abandoned records forever."""
        production = self._production(retention_until=None)
        pk = production.pk
        production.delete()
        self.assertFalse(Production.objects.filter(pk=pk).exists())


class SalesRecordIsInsideTheAuditTrailTests(TestCase):
    """🔴 2026-09-07 — the SALE end of the audit trail had none of the protection the
    production end has.

    `SalesRecordViewSet.destroy` checked the caller's role and called `record.delete()`. No
    `delete()` override, no `pre_delete`, no retention call — while `binding_clauses` names
    `SalesRecord` as the implementation of § 205.103(b)(2) AND (b)(3) (both
    `SOFTWARE_SATISFIES`), and a single EVENT on a finished production is refused with 423
    citing § 205.103(b)(4). (b)(2) is explicit that the trail runs "to sale or transport": the
    sale is where a traceback exercise STARTS.
    """

    def _production(self, **kwargs):
        return Production.objects.create(
            name="Sales retention production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Walnut"),
            **kwargs,
        )

    def test_a_sale_on_a_closed_production_may_not_be_erased(self):
        production = self._production(
            finish_date=timezone.now(),
            retention_until=timezone.now().date() + timedelta(days=365),
        )
        with self.assertRaises(RecordLocked) as ctx:
            assert_child_record_deletable("sales records", production)

        detail = ctx.exception.detail
        self.assertEqual(ctx.exception.status_code, 423)
        self.assertIn("205.103(b)(4)", str(detail))
        self.assertEqual(str(detail["production_id"]), str(production.id))

    def test_a_sale_on_an_open_production_may_still_be_corrected_by_deleting_it(self):
        """The floor starts when the season closes. Blocking an open season would make a typo
        permanent from the moment it was typed, and § 205.103 asks for accurate records, not
        immutable ones."""
        production = self._production()
        assert_child_record_deletable("sales records", production)  # does not raise

    def test_a_legacy_finished_production_with_no_retention_date_is_still_protected(self):
        """`retention_until` is written by `History.finish()`; rows finished before that field
        existed have none. `finish_date` is what makes the season a closed record, so the
        absence of a computed floor must not read as permission."""
        production = self._production(finish_date=timezone.now(), retention_until=None)
        with self.assertRaises(RecordLocked):
            assert_child_record_deletable("sales records", production)


class SalesRecordLeavesALogEntryTests(TestCase):
    """M7-P10: an open season's sale can be hard-deleted, and `SalesRecord` was not registered with
    django-auditlog, so an invoiced sale vanished with no trace."""

    def setUp(self):
        self.production = Production.objects.create(
            name="Open season", start_date=timezone.now(), product=Product.objects.create(name="Walnut")
        )

    def _sale(self):
        from history.models import SalesRecord

        return SalesRecord.objects.create(
            production=self.production,
            sale_date=date(2026, 9, 1),
            buyer_name="Packer Co",
            quantity=100,
            quantity_unit="lb",
            invoice_number="INV-9",
        )

    def _entries(self, pk):
        from django.contrib.contenttypes.models import ContentType

        from auditlog.models import LogEntry

        from history.models import SalesRecord

        return LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(SalesRecord), object_pk=str(pk))

    def test_create_update_and_delete_are_all_logged_and_the_delete_keeps_the_invoice(self):
        from auditlog.models import LogEntry

        sale = self._sale()
        pk = sale.pk
        sale.buyer_name = "Packer Co Two"
        sale.save()
        sale.delete()
        actions = set(self._entries(pk).values_list("action", flat=True))
        self.assertEqual(actions, {LogEntry.Action.CREATE, LogEntry.Action.UPDATE, LogEntry.Action.DELETE})
        deleted = self._entries(pk).get(action=LogEntry.Action.DELETE)
        self.assertIn("INV-9", str(deleted.changes))

    def test_naming_picks_on_a_sale_logs_nothing_per_pick_and_a_clear_cannot_leak_other_events(self):
        """`m2m_fields` is deliberately not used: its `post_clear` handler logs every event in the
        database, and every add stringifies each pick with extra queries."""
        from history.models import ProductionEvent

        picks = [
            ProductionEvent.objects.create(
                history=self.production, type=ProductionEvent.HARVESTING, description="pick", date=timezone.now()
            )
            for _ in range(3)
        ]
        sale = self._sale()
        before = self._entries(sale.pk).count()
        sale.harvest_events.set(picks)
        sale.harvest_events.clear()
        self.assertEqual(self._entries(sale.pk).count(), before)
        for entry in self._entries(sale.pk):
            self.assertNotIn("harvest_events", str(entry.changes))
