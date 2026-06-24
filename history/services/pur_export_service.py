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
  are not reported. Adjuvants/spreader-stickers ARE reportable in CA but Trazo
  does not yet track them as separate inputs (documented gap).
- Aggregate ("is_summary") chemical events are emitted as a single line; the PUR
  wants one line per application. Flagged in the row's notes.
- County is reported by NAME; box 10 wants the CAC county NUMBER (not stored).
- Datetimes are stored/displayed as entered (see F20 tz note); times render in
  24-hour (military) form per boxes 17-18.
"""

import csv
import io

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
        volume = _s(event.volume) or _s(getattr(event, "volume_numeric", None))
        volume_unit = _s(getattr(event, "volume_unit", None))
        total_product = f"{volume} {volume_unit}".strip()

        planted = _s(event.planted_area)
        planted_unit = _s(event.planted_area_unit)
        planted_display = f"{planted} {planted_unit}".strip()

        area_treated = _s(event.area) or _s(getattr(event, "area_numeric", None))
        area_unit = _s(getattr(event, "area_unit", None))
        area_display = f"{area_treated} {area_unit}".strip()

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
            "county": _s(event.application_county) or _s(event.ca_dpr_permit_county),
            "section": _s(event.mtrs_section),
            "township": _s(event.mtrs_township),
            "range": _s(event.mtrs_range),
            "base_meridian": _s(event.mtrs_base_meridian),
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
            "rei_days": _s(event.rei_hours),
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
        if (ed.get("is_summary") is True) or _s(event.time_period):
            notes.append("Aggregate/summary event — PUR wants one line per application.")
        row["notes"] = " | ".join(notes)
        row["_missing_required"] = missing
        return row

    def build_rows(self):
        header = self._operator_header()
        return [self._row(event, header) for event in self._applications()]

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
