"""Whether an OMRI listing had lapsed by the day an input was applied (overall review 2026-11, OV-MT-C04).

`OMRIProduct.delisted_on` is the edition date of the first OMRI Crop Products List Trazo loaded that no
longer carried the product. Until this module only the plan's materials list and the buyer-page claim
check read it; the lookup, the drift detector and the audit dossier's input table treated a lapsed
listing as current. So a spray applied months after OMRI dropped the product read as an ordinary
OMRI-listed, plan-approved input on every record.

The question is asked as of the APPLICATION, never as of today: a record from before the drop was made
while the product was listed, and nothing about it changes. A record on or after the drop date was made
after OMRI had stopped vouching for the product.

What a lapse is NOT: a finding that the material is prohibited. OMRI stopped listing it; the material
may still be allowed, and the certifier decides. Every reader states the date and asks for the
certifier's confirmation, never a verdict. One place decides it, so the four readers cannot disagree.
"""

from __future__ import annotations

import datetime
from typing import Optional


def application_day(applied_at) -> Optional[datetime.date]:
    """The calendar day of an application, as the records and the dossier print it (`date.date()`)."""
    if applied_at is None:
        return None
    if isinstance(applied_at, datetime.datetime):
        return applied_at.date()
    return applied_at


def omri_listing_lapsed_by(product, applied_at) -> Optional[datetime.date]:
    """The edition date OMRI stopped listing `product`, when that was on or before the application day.

    None when the product is still listed, when the application came before the drop, and when there is
    no application date to compare (a lookup with no record yet asks `omri_listing_lapsed_on` instead)."""
    delisted = getattr(product, "delisted_on", None) if product is not None else None
    day = application_day(applied_at)
    if delisted is None or day is None:
        return None
    return delisted if day >= delisted else None


def omri_listing_lapsed_on(product) -> Optional[datetime.date]:
    """The edition date OMRI stopped listing `product`, whatever the date; None while it is listed."""
    return getattr(product, "delisted_on", None) if product is not None else None
