"""
The sales subtotal a renewal reports, over the period the operator stated or the prior calendar year.

One reading for document 02 and for the agent-form copy sheet, so the figure the operator copies
onto the agent's form is the figure the filing printed.

An agent's fee form sets its own period: Oregon Tilth's OSP Update Step 6 asks for a full 12 months
the operation keeps the same from year to year, WSDA's AGR 2521 for the previous calendar year. The
operator states the period on the annual update (`sales_period_start` / `sales_period_end`). With
none stated, the subtotal covers the calendar year before the continuation year, as it always has,
and the wording says "calendar".

The subtotal is never an agent's fee figure. It counts live sales invoiced as organic; agents count
other things (Oregon Tilth everything on the certificate, organic or not; WSDA income received,
services included), and the operator reconciles it to their books.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class SalesSubtotal:
    start: date
    end: date
    #: True when the operator stated the period; False for the calendar-year fallback.
    stated: bool
    #: Sum of the priced sales; None when no sale carries an amount.
    total: Decimal | None
    n_sales: int
    n_priced: int
    #: The day the subtotal was read. A calendar-year fallback can still be running on it: an Oregon
    #: Tilth January cohort renews in November for the next year, before the prior year is over.
    as_of: date | None = None

    @property
    def running(self) -> bool:
        """The period has not ended yet, so its sales are not a period's figure."""
        return self.as_of is not None and self.end >= self.as_of

    @property
    def calendar_year(self) -> int | None:
        return None if self.stated else self.start.year

    @property
    def label(self) -> str:
        """ "2025", or "2025-10-01 to 2026-09-30" for a stated period."""
        return f"{self.start.isoformat()} to {self.end.isoformat()}" if self.stated else str(self.start.year)

    @property
    def complete(self) -> bool:
        """Every sale in the period carries its amount and the period is over, so the total is a total."""
        return bool(self.n_sales) and self.n_priced == self.n_sales and not self.running


def sales_period(filing) -> tuple[date, date, bool]:
    """(start, end, stated) for a filing: the operator's period, else the prior calendar year."""
    if filing.sales_period_start and filing.sales_period_end:
        return filing.sales_period_start, filing.sales_period_end, True
    year = filing.reporting_year - 1
    return date(year, 1, 1), date(year, 12, 31), False


def organic_sales_subtotal(establishment, filing) -> SalesSubtotal:
    """Live sales invoiced as organic and dated inside the filing's period, both ends included."""
    from django.db.models import Count, Sum
    from django.utils import timezone

    from history.models import SalesRecord

    start, end, stated = sales_period(filing)
    agg = (
        SalesRecord.objects.live()
        .filter(
            production__parcel__establishment=establishment,
            organic_on_invoice=True,
            sale_date__gte=start,
            sale_date__lte=end,
        )
        .aggregate(total=Sum("sale_amount"), n=Count("id"), priced=Count("sale_amount"))
    )
    return SalesSubtotal(
        start, end, stated, agg["total"], agg["n"] or 0, agg["priced"] or 0, as_of=timezone.localdate()
    )
