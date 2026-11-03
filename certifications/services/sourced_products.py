"""The suppliers a farm buys organic crops or products from, for G6.5 (2026.11.08).

CCOF G6.5 A1/A2 and OTCO C12 12.2-4/4a ask what the operation sources from other operations, from
whom, and for each supplier's current organic certificate (issued within the last 15 months). An
uncertified supplier (a broker or distributor) is listed with the certified operation it sources
from, and its Exempt Handler Affidavit is attached. The supplier register holds all of it; the module
PDF, the packet ZIP and the coverage page read `sourcing_rows`, so they cannot disagree about which
supplier is still open.

Every state is the operation's record. A copy is the operation's own; whether an old one still
proves the supplier's status is the certifier's call (205.404(d)), so it prints for review.
"""

from __future__ import annotations

from datetime import date, timedelta

#: About 15 months, the currency CCOF G6.5 A2 states and `supplier_certificates` uses.
CERTIFICATE_FRESH_DAYS = 456

ON_FILE = "on_file"
CERTIFICATE_MISSING = "certificate_missing"
CERTIFICATE_OLD = "certificate_old"
AFFIDAVIT_MISSING = "affidavit_missing"
SOURCE_UNNAMED = "source_unnamed"
STATUS_UNKNOWN = "status_unknown"


def sourcing_shown(osp) -> bool:
    """Whether G6.5 asks about sourcing: the operation says it buys in or co-markets organic product,
    and the module is not attested not applicable."""
    from certifications.osp_modules.conditions import answer_value

    entry = ((osp.module_responses or {}).get("modules") or {}).get("g6_5_sales_soe") or {}
    if entry.get("not_applicable"):
        return False
    return answer_value(entry.get("answers") or {}, "sales_soe_supplier_verification") == "yes"


def supplier_state(supplier, today: date | None = None) -> tuple[str, object]:
    """(state, the copy to show or None) for one sourcing supplier. The register's API, G6.5 and the
    coverage page all read this."""
    today = today or date.today()
    farm = supplier.establishment_id
    if supplier.organic_status == "certified":
        copies = [c for c in supplier.certificates.all() if c.document.establishment_id == farm]
        if not copies:
            return CERTIFICATE_MISSING, None
        newest = max(copies, key=lambda c: (c.issued_on, c.pk))
        if today - newest.issued_on > timedelta(days=CERTIFICATE_FRESH_DAYS):
            return CERTIFICATE_OLD, newest.document
        return ON_FILE, newest.document
    if supplier.organic_status == "not_certified":
        affidavit = supplier.exempt_handler_affidavit if supplier.exempt_handler_affidavit_id else None
        if affidavit is not None and affidavit.establishment_id != farm:
            affidavit = None
        if affidavit is None:
            return AFFIDAVIT_MISSING, None
        if not supplier.source_operation.strip():
            return SOURCE_UNNAMED, affidavit
        return ON_FILE, affidavit
    return STATUS_UNKNOWN, None


def sourcing_rows(establishment, today: date | None = None) -> list[dict]:
    """{supplier, state, document} for every supplier on file that the operation buys organic product
    from (`sourced_products` is not empty), archived ones aside."""
    if establishment is None:
        return []
    from django.db.models import Prefetch

    from certifications.models import SupplierCertificate

    suppliers = (
        establishment.suppliers.filter(archived_at__isnull=True)
        .exclude(sourced_products="")
        .select_related("exempt_handler_affidavit")
        .prefetch_related(Prefetch("certificates", queryset=SupplierCertificate.objects.select_related("document")))
        .order_by("name", "pk")
    )
    rows = []
    for supplier in suppliers:
        if not supplier.sourced_products.strip():
            continue
        state, document = supplier_state(supplier, today)
        rows.append(dict(supplier=supplier, state=state, document=document))
    return rows


def document_source(document) -> str:
    """The packet key of a copy: the document, as every other upload of that file uses."""
    return f"doc:{document.pk}"
