"""Land-use history per parcel-year, merged from what the operator typed and what they logged.

WHY THIS EXISTS
---------------
7 CFR 205.202(b) turns on the last three years of a field's history, and both places Trazo
prints that history — the Parcel Application's "F. Land history" and the dossier's "3-Year
Field & Crop Rotation History" — read ONE source: `ParcelCropHistory`, the table the operator
fills by hand, usually once, when the parcel is first set up. Closed seasons reached the
section only as a fallback when that table was EMPTY.

So the more a farm used Trazo, the more wrong this section became. A pilot that had typed
2023-2025 at setup and then logged two full seasons — 512 events, every input, every harvest —
filed its 2028 renewal with a "3-Year" history reading 2023 / 2024 / 2025. The two years an
inspector would actually ask about were absent, and the first certified crop on a newly leased
field (the one fact that ground's § 205.202(b) clock exists to establish) was not on its own
Parcel Application. The operator would have to retype, by hand, a year Trazo already knew in
more detail than any hand entry could hold.

WHAT IT DOES
------------
One row per parcel per year, newest first:

  * a year the operator typed keeps that row verbatim — `source="recorded"`. It is the
    § 205.202(b) attestation they made and it is never rewritten from records;
  * a year with no typed row but with season records is DERIVED — `source="derived"` — from
    every season on the parcel whose span touches that calendar year: the crops, the declared
    production method, the inputs actually applied that year, and the cover crop if one was
    logged. A season that spans two years appears in both, which is what a field did.

A derived row says so. It never invents the one thing the operator must attest to themselves
— `last_prohibited_substance` / `date_last_prohibited` stay empty on derived rows; a clean
season is evidence of a clean year, not a statement that none was applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, List, Optional

from django.utils import timezone

SOURCE_RECORDED = "recorded"
SOURCE_DERIVED = "derived"


@dataclass
class LandHistoryRow:
    year: int
    source: str
    crop_grown: str = ""
    block_id: str = ""
    cover_crop: str = ""
    production_method: str = ""
    production_method_display: str = ""
    substances_applied: str = ""
    last_prohibited_substance: str = ""
    date_last_prohibited: Optional[date] = None
    notes: str = ""
    #: On a derived row, the seasons it was built from. On a TYPED row, the seasons logged for the
    #: same year — the typed row still stands (it is the operator's own statement) but it no longer
    #: hides them: the packet showed a hand-typed 2025 line while its audit trail traced eight
    #: dated records of that very season (WSDA specimen read, 2026-09-12).
    season_names: List[str] = field(default_factory=list)
    #: Only on recorded rows — the ParcelCropHistory instance, for callers that need its extras
    #: (e.g. `substance_applications`).
    recorded: object = None

    @property
    def is_derived(self) -> bool:
        return self.source == SOURCE_DERIVED


def _season_years(season) -> Iterable[int]:
    start = getattr(season, "start_date", None)
    if not start:
        return ()
    finish = getattr(season, "finish_date", None)
    end = finish or getattr(season, "expected_harvest", None) or start
    if finish is None:
        # An OPEN season is land use up to today, not up to its projection: a perennial
        # "production" opened with an expected harvest three years out must not derive
        # "in progress" rows for years that have not happened.
        today = timezone.now()
        end = min(end, today) if end.year > today.year else end
    # A season still open with no expected harvest is one year of land use so far.
    end = max(end, start)
    return range(start.year, end.year + 1)


def _season_crop(season) -> str:
    product = getattr(season, "product", None)
    crop_type = getattr(season, "crop_type", None)
    name = (getattr(product, "name", None) or getattr(crop_type, "name", None) or "").strip()
    return name or "Crop"


def _derive_year(parcel, year: int, seasons) -> Optional[LandHistoryRow]:
    from history.models import ChemicalEvent, SoilManagementEvent

    in_year = [s for s in seasons if year in _season_years(s)]
    if not in_year:
        return None
    in_year.sort(key=lambda s: s.start_date)

    crops = []
    for s in in_year:
        crop = _season_crop(s)
        variety = ""
        extra = getattr(s, "extra_data", None) or {}
        if isinstance(extra, dict):
            variety = str(extra.get("variety") or "").strip()
        label = f"{crop} ({variety})" if variety else crop
        span_note = ""
        if s.start_date.year != year:
            span_note = f"sown {s.start_date.year}"
        elif s.finish_date is None:
            span_note = "in progress"
        elif s.finish_date.year != year:
            span_note = f"harvested {s.finish_date.year}"
        if span_note:
            label = f"{label} — {span_note}"
        if label not in crops:
            crops.append(label)

    methods = {(getattr(s, "production_method", None) or "").strip().lower() for s in in_year}
    methods.discard("")
    # One declared method across the year's seasons is reportable; a mix is left for the
    # operator — the recorded table has "transitional" and "fallow" that History does not.
    method = methods.pop() if len(methods) == 1 else ""
    method_display = ""
    if method:
        choices = dict(parcel.crop_history.model._meta.get_field("production_method").choices)
        method_display = choices.get(method, method.title())
        if method not in choices:
            method = ""
            method_display = ""

    season_ids = [s.pk for s in in_year]
    names = []
    for e in (
        ChemicalEvent.objects.filter(history_id__in=season_ids, date__year=year)
        .order_by("date")
        .values_list("commercial_name", flat=True)
    ):
        n = (e or "").strip()
        if n and n not in names:
            names.append(n)
    cover = []
    for e in SoilManagementEvent.objects.filter(history_id__in=season_ids, date__year=year).order_by("date"):
        product_name = (getattr(e, "amendment_product_name", "") or "").strip()
        if product_name and product_name not in names:
            names.append(product_name)
        if getattr(e, "type", "") == "CC":
            desc = (getattr(e, "name", "") or getattr(e, "description", "") or "").strip()
            if desc and desc not in cover:
                cover.append(desc[:80])

    return LandHistoryRow(
        year=year,
        source=SOURCE_DERIVED,
        crop_grown="; ".join(crops),
        cover_crop="; ".join(cover),
        production_method=method,
        production_method_display=method_display,
        substances_applied=", ".join(names),
        notes=(
            "Derived from season records in Trazo: " + "; ".join(getattr(s, "name", "") or "season" for s in in_year)
        ),
        season_names=[getattr(s, "name", "") or "" for s in in_year],
    )


def land_history_rows(parcel, *, limit: Optional[int] = None, through_year: Optional[int] = None):
    """All land-history rows for `parcel`, newest year first.

    `through_year` caps derived rows (a renewal for year N should not show N+1's plantings);
    typed rows are never filtered — they are the operator's own statement.
    """
    from history.models import History

    recorded = {}
    for h in parcel.crop_history.all():
        row = LandHistoryRow(
            year=h.year,
            source=SOURCE_RECORDED,
            crop_grown=h.crop_grown or "",
            block_id=getattr(h, "block_id", "") or "",
            cover_crop=getattr(h, "cover_crop", "") or "",
            production_method=h.production_method or "",
            production_method_display=h.get_production_method_display() if h.production_method else "",
            substances_applied=h.substances_applied or "",
            last_prohibited_substance=getattr(h, "last_prohibited_substance", "") or "",
            date_last_prohibited=getattr(h, "date_last_prohibited", None),
            notes=h.notes or "",
            recorded=h,
        )
        # A split field is two typed rows for one year; keep both, keyed by block.
        recorded.setdefault(h.year, []).append(row)

    seasons = list(
        History.objects.filter(parcel=parcel, start_date__isnull=False).select_related("product", "crop_type")
    )
    years = set()
    for s in seasons:
        years.update(_season_years(s))
    if through_year is not None:
        years = {y for y in years if y <= through_year}

    logged_by_year: dict = {}
    for s in seasons:
        for y in _season_years(s):
            logged_by_year.setdefault(y, []).append(getattr(s, "name", "") or "season")

    rows = []
    for year in sorted(years | set(recorded), reverse=True):
        if year in recorded:
            typed = sorted(recorded[year], key=lambda r: r.block_id)
            for row in typed:
                row.season_names = list(logged_by_year.get(year, ()))
            rows.extend(typed)
            continue
        derived = _derive_year(parcel, year, seasons)
        if derived is not None:
            rows.append(derived)
    if limit is not None:
        rows = rows[:limit]
    return rows
