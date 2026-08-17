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

from history.models import History, compute_retention_until
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
        return History.objects.create(
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
            History.objects.filter(pk=production.pk).exists(),
            "The row must still be there — a guard that raises AFTER deleting is not a guard.",
        )

    def test_deletion_after_the_window_is_allowed(self):
        """The clause is a floor, not a prohibition. Past it, the operator's data is theirs."""
        production = self._production(retention_until=timezone.now().date() - timedelta(days=1))
        pk = production.pk
        production.delete()
        self.assertFalse(History.objects.filter(pk=pk).exists())

    def test_no_retention_date_does_not_block_deletion(self):
        """An unfinished production has no retention floor yet; blocking it would strand
        drafts and abandoned records forever."""
        production = self._production(retention_until=None)
        pk = production.pk
        production.delete()
        self.assertFalse(History.objects.filter(pk=pk).exists())
