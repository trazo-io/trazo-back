"""Which supplier a seed or stock purchase names, and whether its organic certificate covered it.

The one decider every surface reads (the trace, the audit export), so they cannot disagree.

A record names its supplier as text (`ProductionEvent.seed_supplier_name`). It resolves to a
register supplier (`certifications.Supplier`) only when that text, normalised by
`normalize_supplier_name`, equals a spelling the grower confirmed on the supplier
(`SupplierName`). Nothing looser: a near spelling is a different supplier until the grower says
otherwise. Resolving never reads or writes the record itself, so it works on a finished season's
locked records.

The certificate that counts for a purchase is the newest copy issued on or before the purchase
date, judged fresh for 15 months from its issue date (the freshness CCOF and OTCO ask for). A copy
issued only after the purchase is shown for review: it may still prove the supplier was certified
then, and only the certifier can say. Everything here is the grower's record; nothing is checked
against the Organic Integrity Database.
"""

from __future__ import annotations

from datetime import date, timedelta

#: About 15 months, the same window `PostHarvestFacility.cert_is_current` uses for a handler.
CERTIFICATE_FRESH_DAYS = 456

#: Status of a purchase's supplier certificate. Only `covering` is evidence on file for it.
COVERING = "covering"
STALE = "stale"
POSTDATES_PURCHASE = "postdates_purchase"
NONE_ON_FILE = "none_on_file"
NOT_CERTIFIED = "not_certified"
UNRESOLVED = "unresolved"


def certificate_status_at(certificates, on_date: date | None, organic_status: str = "unknown"):
    """`(status, certificate)` for a purchase on `on_date`, from a supplier's certificate copies.

    `certificates` is any iterable of objects with `issued_on`. The certificate returned is the one
    the status is about (None when there is none to point at).
    """
    if organic_status == "not_certified":
        return NOT_CERTIFIED, None
    copies = sorted(certificates, key=lambda c: (c.issued_on, c.pk or 0), reverse=True)
    if not copies:
        return NONE_ON_FILE, None
    if on_date is None:
        return POSTDATES_PURCHASE, copies[-1]
    before = [c for c in copies if c.issued_on <= on_date]
    if not before:
        # The earliest copy after the purchase is the closest thing to evidence for it.
        return POSTDATES_PURCHASE, copies[-1]
    newest = before[0]
    if on_date - newest.issued_on <= timedelta(days=CERTIFICATE_FRESH_DAYS):
        return COVERING, newest
    return STALE, newest


def _text(value) -> str:
    return (value or "").strip() if isinstance(value, str) or value is None else str(value)


def is_seed_purchase(event) -> bool:
    """Whether a planting or transplanting record names a seed or stock PURCHASE.

    It names an invoice or a supplier, and the seed is not farm-saved. Farm-saved stock has no
    supplier whose receipt or certificate could exist, and a gap the grower can never close is
    noise. The trace's receipt check and this module's certificate check both read this.
    """
    return bool(_text(event.seed_purchase_invoice) or _text(event.seed_supplier_name)) and (
        event.seeds_source != "farm_saved"
    )


def certificate_expected(event) -> bool:
    """Whether a record claims certified organic stock it bought, so a supplier certificate is the
    evidence for it. The trace's gap and the audit export's "not on file" line both ask this."""
    return _text(event.seed_certification_status) == "certified_organic" and is_seed_purchase(event)


def purchase_date_of(event) -> date | None:
    """The day a seed or stock purchase is judged on: its purchase date, else the record's date."""
    if getattr(event, "seed_purchase_date", None):
        return event.seed_purchase_date
    when = getattr(event, "date", None)
    if when is None:
        return None
    return when.date() if hasattr(when, "date") and callable(when.date) else when


def resolve(establishment_id, queries: dict) -> dict:
    """`{key: evidence}` for `queries = {key: (supplier_text, on_date)}` on one farm.

    Two queries whatever the number of keys. `evidence` is a plain dict: `supplier` (or None when
    the text matches no confirmed spelling), `status`, and `certificate` (or None).
    """
    from django.db.models import Prefetch

    from certifications.models import SupplierCertificate, SupplierName, normalize_supplier_name

    wanted = {key: (normalize_supplier_name(text), on_date) for key, (text, on_date) in queries.items()}
    spellings = {n for n, _d in wanted.values() if n}
    by_spelling = {}
    if establishment_id is not None and spellings:
        rows = (
            SupplierName.objects.filter(establishment_id=establishment_id, normalized__in=spellings)
            .select_related("supplier")
            .prefetch_related(
                Prefetch(
                    "supplier__certificates",
                    queryset=SupplierCertificate.objects.select_related("document"),
                )
            )
        )
        # A spelling resolves only to a supplier of the same farm. `SupplierName.establishment` is
        # copied from its supplier on save; this read does not trust the copy alone.
        by_spelling = {
            row.normalized: row.supplier for row in rows if row.supplier.establishment_id == establishment_id
        }

    out = {}
    for key, (spelling, on_date) in wanted.items():
        supplier = by_spelling.get(spelling)
        if supplier is None:
            out[key] = dict(supplier=None, status=UNRESOLVED, certificate=None)
            continue
        # A copy counts only when its file is this farm's. The write path checks it; this read does
        # not trust that alone (same rule as record_receipts).
        copies = [c for c in supplier.certificates.all() if c.document.establishment_id == establishment_id]
        status, cert = certificate_status_at(copies, on_date, supplier.organic_status)
        out[key] = dict(
            supplier=dict(
                id=supplier.pk,
                name=supplier.name,
                certifier=supplier.certifier_name,
                nop_operation_id=supplier.nop_operation_id,
                organic_status=supplier.organic_status,
            ),
            status=status,
            certificate=(
                dict(
                    id=cert.pk,
                    issued_on=cert.issued_on.isoformat(),
                    document=dict(id=cert.document.pk, title=cert.document.title or ""),
                )
                if cert is not None
                else None
            ),
        )
    return out


def spelling_counts(establishment_id) -> dict:
    """`{normalized: (spelling as most recently written, record count)}` for every supplier text on
    the farm's planting and transplanting records. One query.

    Planting and transplanting only: they are the records that buy seed or stock. A seed search
    (SS) names suppliers contacted, not bought from.
    """
    from certifications.models import normalize_supplier_name
    from history.models import ProductionEvent

    out: dict[str, tuple[str, int]] = {}
    rows = (
        ProductionEvent.objects.filter(
            history__parcel__establishment_id=establishment_id,
            type__in=(ProductionEvent.PLANTING, ProductionEvent.TRANSPLANTING),
        )
        .exclude(seed_supplier_name__isnull=True)
        .exclude(seed_supplier_name="")
        .order_by("-date", "-pk")
        .values_list("seed_supplier_name", flat=True)
    )
    for text in rows:
        key = normalize_supplier_name(text)
        if not key:
            continue
        shown, count = out.get(key, (" ".join(text.split()), 0))
        out[key] = (shown, count + 1)
    return out


def seedling_suppliers(establishment) -> list[dict]:
    """One row per supplier the farm's transplant purchases name, for the plan's G3.0a.

    CCOF G3.0 A2, OTCO C3 3.1-2 and WSDA 2121-B 1/1a ask for the organic certificate of each
    supplier of purchased seedlings. The plan, the packet ZIP and the coverage page read these rows,
    so they cannot name different suppliers or different copies.

    A row is about the supplier's LATEST purchase: its `status` and `certificate` (the
    `SupplierCertificate`, or None) are that purchase's. `not_covered` counts the earlier purchases
    whose copy does not cover them, so an old gap is named, never folded away. A spelling the
    register does not hold is its own row with status `unresolved`: the grower has not said which
    supplier it is, and Trazo does not guess.

    Row keys: name, supplier (dict or None), purchases, latest (date or None), status, certificate,
    not_covered, claims_certified.
    """
    from certifications.models import SupplierCertificate, normalize_supplier_name
    from history.models import ProductionEvent

    if establishment is None:
        return []
    events = [
        ev
        for ev in ProductionEvent.objects.filter(
            history__parcel__establishment=establishment, type=ProductionEvent.TRANSPLANTING
        ).order_by("date", "pk")
        if is_seed_purchase(ev) and _text(ev.seed_supplier_name)
    ]
    if not events:
        return []
    evidence = resolve(establishment.pk, {ev.pk: (ev.seed_supplier_name, purchase_date_of(ev)) for ev in events})
    cert_ids = {e["certificate"]["id"] for e in evidence.values() if e["certificate"]}
    certs = {c.pk: c for c in SupplierCertificate.objects.filter(pk__in=cert_ids).select_related("document")}

    groups: dict = {}
    for ev in events:
        found = evidence[ev.pk]
        key = (
            ("supplier", found["supplier"]["id"])
            if found["supplier"]
            else ("spelling", normalize_supplier_name(ev.seed_supplier_name))
        )
        groups.setdefault(key, []).append((ev, found))

    rows = []
    for (kind, _ident), purchases in groups.items():
        purchases.sort(key=lambda pair: (purchase_date_of(pair[0]) or date.min, pair[0].pk))
        latest_ev, latest = purchases[-1]
        supplier = latest["supplier"]
        status = latest["status"]
        earlier_open = 0
        if supplier is not None and status != NOT_CERTIFIED:
            earlier_open = sum(1 for _ev, found in purchases[:-1] if found["status"] != COVERING)
        rows.append(
            dict(
                name=supplier["name"] if supplier else _text(latest_ev.seed_supplier_name),
                supplier=supplier,
                purchases=len(purchases),
                latest=purchase_date_of(latest_ev),
                status=status,
                certificate=certs.get(latest["certificate"]["id"]) if latest["certificate"] else None,
                not_covered=earlier_open,
                claims_certified=any(certificate_expected(ev) for ev, _found in purchases),
            )
        )
    rows.sort(key=lambda row: (row["supplier"] is None, row["name"].casefold()))
    return rows
