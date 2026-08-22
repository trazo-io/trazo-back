"""
California Pesticide Use Report (PUR) export — form DPR-PML-017C.

Generates the monthly "Production Agriculture Pesticide Use Report" a California
grower must file with the County Agricultural Commissioner by the 10th of the
month following application (3 CCR 6626). Consumes logged ChemicalEvent rows
(F20 legal spray-record fields) for one establishment + month and emits a CSV in
DPR-PML-017C box order, plus a per-row completeness check (which required boxes
are still blank) so the farmer knows what to fill before filing.

Source: "Production Agriculture Monthly Pesticide Use Report," form DPR-PML-017C
(Rev. 12/24), CDPR — https://www.cdpr.ca.gov/wp-content/uploads/2024/12/dpr-pml-017c.pdf
Field requirements: 3 CCR 6624(b)/(c). See documentation/audits/.work/research-ca-spray.md.

Scope notes / known limitations (surfaced, not hidden):
- Fertilizers (FE) are EXCLUDED — box 23 instructions say nutrients/fertilizers
  are not reported. Adjuvants/spreader-stickers ARE reportable in CA; a logged
  tank-mix (extra_data["tank_mix"]) is surfaced in the row notes so the omission
  is not silent, but each partner still needs its own PUR line (not auto-split).
- Aggregate ("is_summary") chemical events are emitted as a single line; the PUR
  wants one line per application. Flagged in the row's notes.
- County (box 10) is emitted as the CAC 2-digit code + name (e.g. "37 (San Diego)");
  a county name that is not a recognized CA county is left blank and flagged.
- Datetimes are stored/displayed as entered (see F20 tz note); times render in
  24-hour (military) form per boxes 17-18.
"""

import csv
import io
import re

from common.specimen import SPECIMEN_LINE, is_specimen

# DPR-PML-017C box order. (key, human header, required?). REI/rate/dilution and
# pre-plant/block are optional per the official form instructions.
PUR_COLUMNS = [
    ("operator_id", "3. Operator ID/Permit No.", True),
    ("operator_name", "4. Operator (Grower)", True),
    ("address", "5. Address", True),
    ("city", "6. City", True),
    ("zip_code", "7. Zip Code", True),
    ("site_id", "8. Site ID No.", True),
    ("planted_area", "9. Total Planted Acres/Units", True),
    ("county", "10. County", True),
    ("section", "11. Section", True),
    ("township", "12. Township (N/S)", True),
    ("range", "13. Range (E/W)", True),
    ("base_meridian", "14. Base & Meridian (H/M/S)", True),
    ("commodity", "15. Commodity/Site Treated", True),
    ("field_location", "16. Field Location", True),
    ("application_start", "17. Date/Time Start", True),
    ("application_end", "18. Date/Time Completion", True),
    ("acreage_treated", "19. Acreage/Units Treated", True),
    ("pre_plant", "20. Pre-Plant", False),
    ("application_method", "21. Application Method", True),
    ("ffm_code", "21a. FFM Code (fumigation)", False),
    ("block_id", "22. Block ID", False),
    ("epa_registration_number", "23. EPA/State Reg. No.", True),
    ("total_product_used", "24. Total Product Used", True),
    ("rei_days", "25. Days Reentry", False),
    ("rate_per_acre", "26. Rate Per Acre", False),
    ("dilution", "27. Dilution", False),
    ("product_and_manufacturer", "28. Product and Manufacturer", True),
    ("notes", "Notes / data gaps", False),
]

REQUIRED_KEYS = [key for key, _header, required in PUR_COLUMNS if required]

# Reportable to the PUR: pesticides, fungicides, herbicides. Fertilizers (FE) are
# explicitly NOT reported (DPR-PML-017C box 23 instructions).
REPORTABLE_TYPES = ("PE", "FU", "HE")

# DPR/CACASA county codes (box 10). CalAgPermits validates the county on the
# 2-digit code (01–58, CA counties in alphabetical order), NOT the county name —
# a PUR carrying only the name fails electronic import. Map the county name the
# farmer already logged to its code so the export is file-ready.
_CA_COUNTY_CODES = {
    "alameda": "01",
    "alpine": "02",
    "amador": "03",
    "butte": "04",
    "calaveras": "05",
    "colusa": "06",
    "contra costa": "07",
    "del norte": "08",
    "el dorado": "09",
    "fresno": "10",
    "glenn": "11",
    "humboldt": "12",
    "imperial": "13",
    "inyo": "14",
    "kern": "15",
    "kings": "16",
    "lake": "17",
    "lassen": "18",
    "los angeles": "19",
    "madera": "20",
    "marin": "21",
    "mariposa": "22",
    "mendocino": "23",
    "merced": "24",
    "modoc": "25",
    "mono": "26",
    "monterey": "27",
    "napa": "28",
    "nevada": "29",
    "orange": "30",
    "placer": "31",
    "plumas": "32",
    "riverside": "33",
    "sacramento": "34",
    "san benito": "35",
    "san bernardino": "36",
    "san diego": "37",
    "san francisco": "38",
    "san joaquin": "39",
    "san luis obispo": "40",
    "san mateo": "41",
    "santa barbara": "42",
    "santa clara": "43",
    "santa cruz": "44",
    "shasta": "45",
    "sierra": "46",
    "siskiyou": "47",
    "solano": "48",
    "sonoma": "49",
    "stanislaus": "50",
    "sutter": "51",
    "tehama": "52",
    "trinity": "53",
    "tulare": "54",
    "tuolumne": "55",
    "ventura": "56",
    "yolo": "57",
    "yuba": "58",
}


def _normalize_county(name):
    """Casefold, strip a trailing 'County', and collapse whitespace for lookup."""
    norm = " ".join(_s(name).lower().split())
    if norm.endswith(" county"):
        norm = norm[: -len(" county")].strip()
    return norm


def _county_code(name):
    """Return the 2-digit DPR county code for a CA county name, or '' if unknown."""
    return _CA_COUNTY_CODES.get(_normalize_county(name), "")


# Map Trazo application methods → DPR box-21 categories (Ground / Air / Fume / Other).
_METHOD_TO_DPR = {
    "ground_spray": "Ground",
    "broadcast": "Ground",
    "banding": "Ground",
    "banded": "Ground",
    "foliar": "Ground",
    "soil_incorporation": "Ground",
    "injection": "Ground",
    "chemigation": "Ground (chemigation)",
    "air_blast": "Ground (air-blast)",
    "drip": "Ground (chemigation)",
    "fertigation": "Ground (chemigation)",
    "aerial": "Air",
    "fumigation": "Fume",
    "seed_treatment": "Other (seed treatment)",
}


_MTRS_EMPTY = {"section": "", "township": "", "range": "", "base_meridian": ""}

# "S14 T8N R2E", "14/8N/2E MD", "Sec 14 Twp 8N Rge 2E M" — the PLSS descriptor a grower
# copies off their permit or deed. Base & meridian is optional in the string.
_MTRS_RE = re.compile(
    r"""(?ix)
    \b (?:S(?:ec(?:tion)?)?[\s.]*)? (?P<section>\d{1,2}) \b
    [\s,/-]+
    (?:T(?:wp|ownship)?[\s.]*)? (?P<township>\d{1,3}\s*[NS]) \b
    [\s,/-]+
    (?:R(?:ge|ange)?[\s.]*)? (?P<range>\d{1,3}\s*[EW]) \b
    (?: [\s,/-]+ (?P<meridian>H|M|S|MD|HM|SB) \b )?
    """
)


def _parcel_county(parcel) -> str:
    """The county the operator entered on the Parcel Application (§ 205.202 identity page)."""
    answers = getattr(parcel, "application_answers", None) or {}
    if not isinstance(answers, dict):
        return ""
    return _s(answers.get("county"))


def _parse_mtrs(descriptor) -> dict:
    """Split a parcel's free-text PLSS descriptor into PUR's four separate fields.

    California's PUR form wants Section, Township, Range and Base & Meridian as distinct
    boxes (10-14). Trazo stores what the grower actually has — one string on the parcel,
    "S14 T8N R2E" — and `ChemicalEvent.mtrs_*` is capturable nowhere in the UI, so before
    this those four boxes could never be filled and every exported row was incomplete.

    Deterministic parse, never a guess: anything that does not match the pattern yields
    blanks, because a wrong section number on a state filing is worse than an empty one.
    An explicit value on the event always wins over this fallback.
    """
    text = _s(descriptor)
    if not text:
        return dict(_MTRS_EMPTY)
    match = _MTRS_RE.search(text)
    if not match:
        return dict(_MTRS_EMPTY)
    return {
        "section": match.group("section"),
        "township": re.sub(r"\s+", "", match.group("township")).upper(),
        "range": re.sub(r"\s+", "", match.group("range")).upper(),
        "base_meridian": (match.group("meridian") or "").upper(),
    }


def _fmt_dt(value):
    """Render a datetime in 24-hour (military) form per DPR boxes 17-18."""
    if not value:
        return ""
    try:
        return value.strftime("%Y-%m-%d %H%M")
    except (AttributeError, ValueError):
        return str(value)


def _s(value):
    return "" if value is None else str(value).strip()


def _fmt_rei(hours):
    """Format box 25 ("25. Days Reentry") from ChemicalEvent.rei_hours.

    The DPR-PML-017C box is titled *Days* Reentry, but the filing instruction is
    "Enter the reentry interval as required by the pesticide label or regulation"
    and modern labels state short REIs in HOURS (Entrust SC, EPA Reg. 62719-621:
    "REI of 4 hours"). Writing the bare number 4 into a box headed "Days" tells
    the county agricultural commissioner the block was restricted for four DAYS —
    a 24x misstatement of a worker-safety interval on a form filed with a
    regulator. Always emit the unit so the value cannot be misread.
    """
    if hours in (None, ""):
        return ""
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return _s(hours)
    if h <= 0:
        return ""
    if h % 24 == 0:
        days = h / 24
        return f"{days:g} day" if days == 1 else f"{days:g} days"
    return f"{h:g} hour" if h == 1 else f"{h:g} hours"


class PURExportService:
    """Build the DPR-PML-017C monthly PUR for one establishment + month."""

    def __init__(self, establishment, month, year):
        self.establishment = establishment
        self.month = int(month)
        self.year = int(year)

    # ------------------------------------------------------------------
    def _applications(self):
        """Reportable chemical events for the establishment in the report month.

        Filters on the event ``date`` (always present) rather than the optional
        ``application_start`` so events without a start time are still included.
        """
        from history.models import ChemicalEvent

        return (
            ChemicalEvent.objects.filter(
                history__parcel__establishment=self.establishment,
                type__in=REPORTABLE_TYPES,
                date__year=self.year,
                date__month=self.month,
            )
            .select_related("history__parcel", "history__product", "history__crop_type")
            .order_by("date")
        )

    def _operator_header(self):
        est = self.establishment
        company = getattr(est, "company", None)
        return {
            "operator_name": _s(getattr(company, "name", None)) or _s(est.name),
            "address": _s(getattr(est, "address", None)),
            "city": _s(getattr(est, "city", None)),
            "zip_code": _s(getattr(est, "zip_code", None)),
        }

    def _row(self, event, header):
        ed = getattr(event, "extra_data", None) or {}
        history = getattr(event, "history", None)
        parcel = getattr(history, "parcel", None)

        # Commodity (box 15): specific crop/product, not a generic group.
        commodity = ""
        if history is not None:
            product = getattr(history, "product", None)
            crop = getattr(history, "crop_type", None)
            commodity = _s(getattr(product, "name", None)) or _s(getattr(crop, "name", None))

        method_raw = _s(event.application_method_structured) or _s(event.way_of_application)
        method = _METHOD_TO_DPR.get(method_raw.lower(), method_raw)

        # Operator ID (box 3): F20 operator_id, else the restricted-materials permit number.
        operator_id = _s(event.operator_id) or _s(event.ca_dpr_permit_number)

        # Total product used (box 24): formulated product + unit (NOT diluted mix).
        # Only build the "value unit" string when the VALUE is present — the units
        # default to "gal"/"acres" on the model, so a unit-only string ("gal") is a
        # phantom that would let a blank box 24/19/9 pass the completeness check
        # (the PUR's most important numeric boxes). Blank when no number → flagged missing.
        volume = _s(event.volume) or _s(getattr(event, "volume_numeric", None))
        volume_unit = _s(getattr(event, "volume_unit", None))
        total_product = f"{volume} {volume_unit}".strip() if volume else ""

        planted = _s(event.planted_area)
        planted_unit = _s(event.planted_area_unit)
        planted_display = f"{planted} {planted_unit}".strip() if planted else ""

        area_treated = _s(event.area) or _s(getattr(event, "area_numeric", None))
        area_unit = _s(getattr(event, "area_unit", None))
        area_display = f"{area_treated} {area_unit}".strip() if area_treated else ""

        # County (box 10): CalAgPermits validates on the 2-digit CAC county code, not
        # the name. Resolve the logged county name to its code and emit "37 (San Diego)".
        # If the name doesn't resolve to a CA county, leave box 10 BLANK (so the
        # completeness check flags it) rather than emit an unvalidatable name.
        # Falls back to the county the operator entered on the Parcel Application — the
        # same PLSS-adjacent identity data as MTRS above, and the value they typed, not an
        # inference. `planted_area` deliberately does NOT fall back to `parcel.area`: the
        # box asks for planted acres and a parcel can be partly planted, so deriving it
        # would overstate a state filing. Parse what the operator wrote; never infer.
        county_name = _s(event.application_county) or _s(event.ca_dpr_permit_county) or _parcel_county(parcel)
        county_code = _county_code(county_name)
        county_display = f"{county_code} ({county_name})" if county_code else ""

        # F-PUR (2026-06): box 26 (Rate Per Acre) was hard-coded blank. Compute it from the product
        # volume and treated area the farmer already logged — no new input. e.g. 10 gal / 15 acres
        # -> "0.67 gal/acre". Leave blank if either is missing/zero (can't fabricate a rate).
        rate_display = ""
        try:
            vnum = float(event.volume) if event.volume not in (None, "") else None
            anum = float(event.area) if event.area not in (None, "") else None
            # Need both units for a meaningful rate; without them the value is ambiguous, so leave
            # box 26 blank rather than print "gal/" or " /acre".
            if vnum is not None and anum and volume_unit and area_unit:
                # singularize the area unit for the rate ("acres" -> "acre", "ha" -> "ha")
                area_singular = area_unit[:-1] if area_unit.endswith("s") else area_unit
                rate_display = f"{vnum / anum:.2f} {volume_unit}/{area_singular}"
        except (TypeError, ValueError, ZeroDivisionError):
            rate_display = ""

        mtrs_fallback = _parse_mtrs(getattr(parcel, "section_township_range", None))

        product_mfr = _s(event.commercial_name)
        manufacturer = _s(event.manufacturer)
        if manufacturer:
            product_mfr = f"{product_mfr} / {manufacturer}".strip(" /")

        timing = _s(event.application_timing).lower()
        pre_plant = "Yes" if timing in ("pre_planting", "pre-planting", "preplant") else ""

        row = {
            "operator_id": operator_id,
            "operator_name": header["operator_name"],
            "address": header["address"],
            "city": header["city"],
            "zip_code": header["zip_code"],
            "site_id": _s(event.site_id),
            "planted_area": planted_display,
            "county": county_display,
            "section": _s(event.mtrs_section) or mtrs_fallback["section"],
            "township": _s(event.mtrs_township) or mtrs_fallback["township"],
            "range": _s(event.mtrs_range) or mtrs_fallback["range"],
            "base_meridian": _s(event.mtrs_base_meridian) or mtrs_fallback["base_meridian"],
            "commodity": commodity,
            "field_location": _s(getattr(parcel, "name", None)) or _s(event.block_id),
            "application_start": _fmt_dt(event.application_start),
            "application_end": _fmt_dt(event.application_end),
            "acreage_treated": area_display,
            "pre_plant": pre_plant,
            "application_method": method,
            "ffm_code": _s(event.ffm_code),
            "block_id": _s(event.block_id),
            "epa_registration_number": _s(event.epa_registration_number),
            "total_product_used": total_product,
            "rei_days": _fmt_rei(event.rei_hours),
            "rate_per_acre": rate_display,
            "dilution": "",
            "product_and_manufacturer": product_mfr,
        }

        # Per-row completeness: which REQUIRED boxes are still blank.
        missing = [key for key in REQUIRED_KEYS if not _s(row.get(key))]
        # Fumigation requires the FFM code (box 21 / 3 CCR 6624(c)(8)).
        if method == "Fume" and not row["ffm_code"]:
            missing.append("ffm_code")

        notes = []
        if missing:
            headers = {k: h for k, h, _r in PUR_COLUMNS}
            notes.append("Missing required: " + ", ".join(headers.get(m, m) for m in missing))
        # Distinguish "no county logged" from "county logged but not a CA county" —
        # the latter can't map to a CAC code and box 10 was blanked above.
        if county_name and not county_code:
            notes.append(f"County '{county_name}' is not a recognized CA county — box 10 needs the CAC county number.")
        # Structured tank_mix_partners are exported as their own PUR rows (see
        # _adjuvant_rows). Only fall back to the free-text extra_data["tank_mix"]
        # note when there is NO structured list, so a legacy free-text tank mix
        # isn't silently dropped.
        structured_partners = getattr(event, "tank_mix_partners", None) or []
        tank_mix = _s(ed.get("tank_mix"))
        if tank_mix and not structured_partners:
            notes.append(
                f"Tank-mix partner(s) logged ({tank_mix}) — each CA-registered adjuvant/"
                "spreader-sticker needs its own PUR line (boxes 23/24); not auto-exported."
            )
        if (ed.get("is_summary") is True) or _s(event.time_period):
            notes.append("Aggregate/summary event — PUR wants one line per application.")
        row["notes"] = " | ".join(notes)
        row["_missing_required"] = missing
        return row

    def _adjuvant_rows(self, event, primary_row):
        """One PUR line per structured tank-mix partner (adjuvant/spreader-sticker).

        Each CA-registered adjuvant is reportable on its own DPR-PML-017C line with
        its own EPA/State reg (box 23), total product (box 24) and product/mfr (box
        28). The application context (site, county, MTRS, dates, method, treated
        acreage) is shared with the primary product, so it is copied from the
        already-built primary row and only the product-specific boxes are overridden.
        """
        partners = getattr(event, "tank_mix_partners", None) or []
        area_unit = _s(getattr(event, "area_unit", None))
        primary_name = _s(event.commercial_name) or "primary product"
        rows = []
        for p in partners:
            if not isinstance(p, dict):
                continue
            name = _s(p.get("commercial_name"))
            mfr = _s(p.get("manufacturer"))
            epa = _s(p.get("epa_registration_number"))
            vol = _s(p.get("volume"))
            vol_unit = _s(p.get("volume_unit"))
            # Skip empty partner entries (blank UI rows) — nothing to report.
            if not (name or epa or vol):
                continue

            product_mfr = f"{name} / {mfr}".strip(" /") if mfr else name
            total_product = f"{vol} {vol_unit}".strip() if vol else ""

            rate_display = ""
            try:
                vnum = float(vol) if vol else None
                anum = float(event.area) if event.area not in (None, "") else None
                if vnum is not None and anum and vol_unit and area_unit:
                    area_singular = area_unit[:-1] if area_unit.endswith("s") else area_unit
                    rate_display = f"{vnum / anum:.2f} {vol_unit}/{area_singular}"
            except (TypeError, ValueError, ZeroDivisionError):
                rate_display = ""

            row = dict(primary_row)
            row.update(
                {
                    "epa_registration_number": epa,
                    "total_product_used": total_product,
                    "rate_per_acre": rate_display,
                    "dilution": "",
                    "product_and_manufacturer": product_mfr,
                }
            )

            missing = [key for key in REQUIRED_KEYS if not _s(row.get(key))]
            if row.get("application_method") == "Fume" and not row.get("ffm_code"):
                missing.append("ffm_code")

            notes = []
            if missing:
                headers = {k: h for k, h, _r in PUR_COLUMNS}
                notes.append("Missing required: " + ", ".join(headers.get(m, m) for m in missing))
            notes.append(f"Tank-mix adjuvant applied with {primary_name} — separate PUR line per 3 CCR 6624.")
            row["notes"] = " | ".join(notes)
            row["_missing_required"] = missing
            rows.append(row)
        return rows

    def build_rows(self):
        header = self._operator_header()
        rows = []
        for event in self._applications():
            primary = self._row(event, header)
            rows.append(primary)
            rows.extend(self._adjuvant_rows(event, primary))
        return rows

    def summary(self):
        rows = self.build_rows()
        complete = sum(1 for r in rows if not r["_missing_required"])
        return {
            "establishment_id": self.establishment.id,
            "establishment_name": self.establishment.name,
            "month": self.month,
            "year": self.year,
            "form": "DPR-PML-017C",
            "filing_deadline": f"{self.year}-{self.month + 1:02d}-10" if self.month < 12 else f"{self.year + 1}-01-10",
            "application_count": len(rows),
            "complete_count": complete,
            "incomplete_count": len(rows) - complete,
            "rows": rows,
        }

    def to_csv(self):
        rows = self.build_rows()
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        # Report header block.
        header = self._operator_header()
        writer.writerow(["California Pesticide Use Report (DPR-PML-017C)"])
        # A PUR is filed with a county agricultural commissioner. A fabricated one that
        # reads as a real monthly filing is the most consequential unmarked document this
        # codebase produces, so the marking goes in the preamble the format already has —
        # no column contract is disturbed, and it sits above the operator's own name.
        if is_specimen(self.establishment):
            writer.writerow([SPECIMEN_LINE])
        writer.writerow([f"Operator (Grower): {header['operator_name']}"])
        writer.writerow([f"Establishment: {self.establishment.name}"])
        writer.writerow([f"Report period: {self.year}-{self.month:02d}"])
        writer.writerow([f"Applications: {len(rows)}"])
        writer.writerow([])

        # Column headers + rows in DPR box order.
        headers = [h for _k, h, _r in PUR_COLUMNS]
        writer.writerow(headers)
        for r in rows:
            writer.writerow([r.get(key, "") for key, _h, _req in PUR_COLUMNS])

        # Encode to bytes for FileResponse.
        out = io.BytesIO(buffer.getvalue().encode("utf-8-sig"))
        out.seek(0)
        return out
