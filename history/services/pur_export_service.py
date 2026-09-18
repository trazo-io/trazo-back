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
- Applications made by a licensed pest control business (``applied_by_pcb``) are NOT
  rows: the business is the reporter for those (3 CCR 6626(b); PUE Compendium Vol. 1
  Ch. 4 p. 4-8 — "the grower ... should not include applications made by pest control
  businesses on his/her use report"). They are counted and listed in the preamble and
  the preview so the omission is visible, never silent.
- Hectares are converted to acres for boxes 9/19/26 (the PUR has no hectare unit) and
  the original figure is kept in the row notes.
- Box 3 falls back to the farm's ``Establishment.ca_operator_id`` and box 8 to the
  parcel's ``Parcel.ca_site_id`` when the event carries neither — the county issues
  both numbers to the OPERATOR and the SITE, not to a spray.
- The filing is per COUNTY (3 CCR 6626(a)). Rows are grouped by county code and a
  multi-county month says so in the preamble; one CSV still covers the establishment.
"""

import csv
import io
import re

# DPR-PML-017C box order. (key, human header, required?). REI/rate/dilution and
# pre-plant/block are optional per the official form instructions.
from common.field_registry import APPLICATION_METHOD, SCHOOLSITE_CODE_SUGGESTION, SCHOOLSITE_METHODS_WITHOUT_CODE
from common.specimen import SPECIMEN_LINE, is_specimen
from history.constants import CHEMICAL_EVENT_TYPE

#: slug -> the label a County Agricultural Commissioner reads. The note used to interpolate the
#: raw slug ("for air_blast that is code 5102"), which is Trazo's internal name leaking onto a
#: regulator-facing artifact.
_METHOD_LABEL = dict(APPLICATION_METHOD)

#: Declared-rate unit -> (the total's unit it can be compared against, the area basis).
#:
#: `ChemicalEvent.application_rate` is what the grower SAYS the rate was, and `volume_numeric`
#: is the TOTAL applied. Neither is derived from the other on purpose (§ 205.103(b)(2) mass
#: balance wants the total; the label check wants the rate), which is exactly what makes them a
#: cross-check: rate x treated area should land on the total, and a decimal slip in either one
#: breaks the identity by a power of ten.
#:
#: Rate units with no exact partner in UNIT_VOLUME are absent and simply are not checked:
#: pints, quarts, tons, g/ha and t/ha. Absent means "no opinion", never "fine".
_RATE_TO_VOLUME_UNIT = {
    "gal_ac": ("gal", "acre"),
    "oz_ac": ("oz", "acre"),
    "fl_oz_ac": ("oz", "acre"),
    "lb_ac": ("lbs", "acre"),
    "L_ha": ("L", "hectare"),
    "mL_ha": ("mL", "hectare"),
    "kg_ha": ("kg", "hectare"),
}

#: 1 hectare in acres. Same constant as Parcel.HECTARES_TO_ACRES; duplicated rather than
#: imported to keep this module free of a product/ import, and asserted equal in the tests.
_HECTARES_TO_ACRES = 2.47105

#: Flag only an ORDER-OF-MAGNITUDE disagreement, never a near miss.
#:
#: The error this exists for is a decimal slip: "instead of 4.57 oz, they enter 457.0 oz"
#: (Tulare County Agricultural Commissioner, 2026-09-17), i.e. 100x. A 2x gap has honest
#: explanations — a spot treatment over part of the block, a re-application, a rate quoted for
#: the dilute mix — and flagging those would train the grower to dismiss the column.
#:
#: It also makes `fl_oz_ac` -> `oz` safe to compare. "fl oz" is a volume and UNIT_VOLUME's "oz"
#: reads as a weight, so the pairing is an assumption; but no real formulation's density makes
#: those differ by 10x, so the threshold absorbs the ambiguity instead of the code guessing.
_QUANTITY_ORDER_OF_MAGNITUDE = 10.0


def _quantity_discrepancy(event, acres):
    """``(expected_total, logged_total, ratio, unit)`` when the declared rate and the logged
    total disagree by an order of magnitude, else ``None``.

    Box 24 (total product) is a passthrough and box 26 (rate per acre) divides that same number
    by the treated area, so before this existed the ONE number a county keys most often got no
    sanity check at all even though a second, independent statement of it was sitting on the
    record.

    Returns None — no opinion — whenever anything needed is missing or the units have no exact
    partner. NEVER a blocker: an unusual rate is the grower's to declare, so the caller notes it.
    """
    rate = getattr(event, "application_rate", None)
    rate_unit = _s(getattr(event, "application_rate_unit", None))
    if rate is None or not rate_unit or not acres:
        return None
    pairing = _RATE_TO_VOLUME_UNIT.get(rate_unit)
    if not pairing:
        return None
    want_unit, basis = pairing
    if _s(getattr(event, "volume_unit", None)) != want_unit:
        return None
    try:
        logged = float(_s(event.volume) or _s(getattr(event, "volume_numeric", None)))
        rate = float(rate)
    except (TypeError, ValueError):
        return None
    if logged <= 0 or rate <= 0:
        return None
    area = acres if basis == "acre" else acres / _HECTARES_TO_ACRES
    expected = rate * area
    if expected <= 0:
        return None
    ratio = logged / expected
    if 1 / _QUANTITY_ORDER_OF_MAGNITUDE < ratio < _QUANTITY_ORDER_OF_MAGNITUDE:
        return None
    return expected, logged, ratio, want_unit


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
    ("ffm_code", "21a. Method Code (fumigation / schoolsite)", False),
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
# Box 21 is "Check One: Ground / Air / Fume / Other". CDPR's own definition of the
# aerial/ground indicator (CalPIP glossary): "A - Aerially applied; G - Ground (ground-based
# equipment) applied; O - Other application methods. Other application methods (O) may
# include: paint, ear tag, injection, chemigation, etc.; F - Fumigant". Chemigation — product
# metered into irrigation water — is therefore OTHER, not Ground, however the water is
# delivered; until 2026-09-05 drip/fertigation/chemigation all ticked the Ground box.
_METHOD_TO_DPR = {
    "ground_spray": "Ground",
    "broadcast": "Ground",
    "banding": "Ground",
    "banded": "Ground",
    "foliar": "Ground",
    "soil_incorporation": "Ground",
    "subsurface": "Ground (subsurface)",
    "air_blast": "Ground (air-blast)",
    "injection": "Other (injection)",
    "chemigation": "Other (chemigation)",
    "drip": "Other (chemigation)",
    "fertigation": "Other (chemigation)",
    "aerial": "Air",
    "fumigation": "Fume",
    "seed_treatment": "Other (seed treatment)",
}

# Boxes 9, 19 and 26 are acres (or square feet / units). DPR's unit-treated codes are
# A, S, U, C, T, P, K — there is no hectare, and CalAgPermits rejects "ha". Trazo's spray
# form still offers hectares (Parcel.area is stored in hectares), so convert here and keep
# the grower's original figure in the notes rather than emit a unit the county cannot key.
_ACRES_PER_HECTARE = 2.47105
_HECTARE_UNITS = ("ha", "hectare", "hectares", "hectárea", "hectáreas")
# The spray form's unit slugs → what the box should read. Anything else passes through.
_AREA_UNIT_DISPLAY = {"sq_ft": "sq ft", "sqft": "sq ft", "square_feet": "sq ft"}


def _area_for_pur(value, unit):
    """Return ``(display, original)`` for an area box.

    ``display`` is what the box carries ("68 acres", "12.35 acres"); ``original`` is the
    grower's figure when a conversion happened ("5 ha"), else None. Blank value → ("", None):
    a unit alone is never a value (see the box 24 note in ``_row``).
    """
    v = _s(value)
    u = _s(unit)
    if not v:
        return "", None
    if u.lower() in _HECTARE_UNITS:
        try:
            acres = float(v) * _ACRES_PER_HECTARE
        except ValueError:
            return f"{v} {u}".strip(), None
        return f"{acres:.2f} acres", f"{v} {u}"
    return f"{v} {_AREA_UNIT_DISPLAY.get(u.lower(), u)}".strip(), None


def _acres(value, unit):
    """Numeric acres for the box-26 rate, or None when the area is not in acres/hectares."""
    v = _s(value)
    u = _s(unit).lower()
    if not v:
        return None
    try:
        num = float(v)
    except ValueError:
        return None
    if u in _HECTARE_UNITS:
        return num * _ACRES_PER_HECTARE
    if u in ("acre", "acres"):
        return num
    return None


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
        method_slug = method_raw.lower()
        method = _METHOD_TO_DPR.get(method_slug, method_raw)

        # Operator ID (box 3): F20 operator_id, else the restricted-materials permit number
        # (same numbering slot per the form), else the farm's own Operator ID. The county
        # issues the OIN to the operator, not to a spray — a quick-form or voice record that
        # never showed the CA block is still box-3 complete when the farm carries the number.
        operator_id = (
            _s(event.operator_id)
            or _s(event.ca_dpr_permit_number)
            or _s(getattr(self.establishment, "ca_operator_id", None))
        )
        # Site ID (box 8): the event's own, else the parcel's — a site ID is issued per site.
        site_id = _s(event.site_id) or _s(getattr(parcel, "ca_site_id", None))

        # Total product used (box 24): formulated product + unit (NOT diluted mix).
        # Only build the "value unit" string when the VALUE is present — the units
        # default to "gal"/"acres" on the model, so a unit-only string ("gal") is a
        # phantom that would let a blank box 24/19/9 pass the completeness check
        # (the PUR's most important numeric boxes). Blank when no number → flagged missing.
        volume = _s(event.volume) or _s(getattr(event, "volume_numeric", None))
        volume_unit = _s(getattr(event, "volume_unit", None))
        total_product = f"{volume} {volume_unit}".strip() if volume else ""

        planted_display, planted_original = _area_for_pur(event.planted_area, event.planted_area_unit)

        area_treated = _s(event.area) or _s(getattr(event, "area_numeric", None))
        area_unit = _s(getattr(event, "area_unit", None))
        area_display, area_original = _area_for_pur(area_treated, area_unit)

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
            # Same number box 24 carries: `volume` here is the legacy string, else volume_numeric.
            vnum = float(volume) if volume else None
            # Box 26 is "Rate Per ACRE": only computable when the treated area is in acres (or
            # hectares, converted). A square-foot or per-unit area leaves it blank rather than
            # print a per-something rate under an acre heading.
            anum = _acres(area_treated, area_unit)
            if vnum is not None and anum and volume_unit:
                rate_display = f"{vnum / anum:.2f} {volume_unit}/acre"
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
            "site_id": site_id,
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
        # Box 21a is ONE field serving TWO rules, and until 2026-09-17 it only knew the first.
        #
        #   (1) Fumigation, any ground: the 4-digit field fumigation method code,
        #       3 CCR 6624(c)(8). This is what the gate used to say, and alone.
        #   (2) Schoolsites, any method: 3 CCR 6691 via 6434(6)(A) and 6626(c). DPR ENF 25-16,
        #       effective 2026-01-01 under AB 1864, REPURPOSED this same 4-digit field for every
        #       application made to produce an agricultural commodity within 1/4 mile of a
        #       schoolsite. A ground rig (5101), an airblast sprayer (5102) or a drip line
        #       (5162) near a school all owe a code, and none of them is a fumigation.
        #
        # So a `method == "Fume"` gate silently under-reported every non-fumigant application on
        # school-adjacent ground for the nine months the rule had been in force. Source: Tulare
        # County Agricultural Commissioner, 2026-09-17, forwarding ENF 25-16.
        #
        # NEVER guess the code. Only four of Trazo's application methods map to exactly one DPR
        # row (SCHOOLSITE_CODE_SUGGESTION); "foliar", "broadcast", "banding" and bare
        # "chemigation" each span several, and a wrong 4-digit code on a filing the CAC keys is
        # worse than a blank one. Blank is a visible gap; wrong is a silent misstatement.
        # Aircraft owes no code at all (3 CCR 6691(a)(1)). Tested BOTH ways on purpose: the slug
        # set catches a structured "aerial", and the DPR category catches free text that
        # `_METHOD_TO_DPR` resolved to "Air" but that never equalled the slug (way_of_application
        # is free text, so "Aerial application" would otherwise have been billed for a code).
        near_school = getattr(parcel, "ca_near_schoolsite", None)
        exempt_from_school_code = method_slug in SCHOOLSITE_METHODS_WITHOUT_CODE or method == "Air"
        needs_school_code = near_school is True and not exempt_from_school_code
        if not row["ffm_code"] and (method == "Fume" or needs_school_code):
            missing.append("ffm_code")

        # Two renderings of every gap, on purpose. `notes` is the English prose the CSV's
        # "Notes / data gaps" column carries — the county commissioner reads it. `flags` is
        # the same finding as a CODE plus its parameters, for the preview: the client labels
        # codes in the farmer's locale, whereas a server sentence opts it out of i18n (the
        # es-419 badge read "requieren datos" over an English "Missing required: …" row).
        notes = []
        flags = []
        if missing:
            headers = {k: h for k, h, _r in PUR_COLUMNS}
            notes.append("Missing required: " + ", ".join(headers.get(m, m) for m in missing))
        # Say WHY box 21a is owed, not just that it is blank: "Missing required: Method Code"
        # tells a grower nothing, and the schoolsite rule is nine months old and not widely known.
        if needs_school_code and not row["ffm_code"]:
            suggested = SCHOOLSITE_CODE_SUGGESTION.get(method_slug)
            notes.append(
                "Within 1/4 mile of a schoolsite: this application needs a method code on the PUR "
                "(3 CCR 6691; DPR ENF 25-16, effective 2026-01-01)"
                + (
                    f". For {_METHOD_LABEL.get(method_slug, method_raw)} that is code {suggested}."
                    if suggested
                    else ", to be picked from the DPR list."
                )
            )
            # The LABEL, not the slug: this reaches the farmer's preview through
            # `FLAG_LABEL_IDS`, and "air_blast" is Trazo's internal name. Same leak the CSV
            # note had. `suggested` is "none" rather than null so the ICU `select` in both
            # locales has a branch to land on.
            flags.append(
                {
                    "code": "schoolsite_method_code_required",
                    "method": _METHOD_LABEL.get(method_slug, method_raw),
                    "suggested": suggested or "none",
                }
            )
        # None is NOT False. An unanswered parcel is a gap in the filing, not a clear parcel —
        # see Parcel.ca_near_schoolsite. Noted, never auto-resolved either way.
        #
        # Raised only where the answer would CHANGE this row: a blank box 21a on a method that
        # could owe one. An unanswered parcel otherwise puts an identical flag on every row of
        # every export forever, which is how a gaps column trains people to stop reading it. If
        # the grower already entered a code, or the method is aircraft (3 CCR 6691(a)(1)), the
        # question is moot for this line.
        # Box 24 against the grower's OWN declared rate. The county's single most common error
        # is a decimal slip in this number, and the record already carries a second, independent
        # statement of it (`application_rate`), so the check needs no new input and no catalog.
        # NEVER blocks: an unusual rate is the grower's to declare, and this only ever speaks
        # when the two disagree by 10x or more.
        discrepancy = _quantity_discrepancy(event, _acres(area_treated, area_unit))
        if discrepancy:
            expected, logged, ratio, unit = discrepancy
            notes.append(
                f"Box 24 reads {logged:g} {unit}, but the rate logged for this application works "
                f"out to about {expected:.4g} {unit} over the treated area — roughly {ratio:.0f}x "
                f"apart. Worth a second look before filing."
                if ratio >= 1
                else f"Box 24 reads {logged:g} {unit}, but the rate logged for this application "
                f"works out to about {expected:.4g} {unit} over the treated area — roughly "
                f"{1 / ratio:.0f}x more than the total. Worth a second look before filing."
            )
            flags.append(
                {
                    "code": "quantity_rate_mismatch",
                    "logged": f"{logged:g}",
                    "expected": f"{expected:.4g}",
                    "unit": unit,
                    "factor": f"{(ratio if ratio >= 1 else 1 / ratio):.0f}",
                }
            )
        actionable = not row["ffm_code"] and not exempt_from_school_code
        if near_school is None and actionable:
            notes.append(
                "Schoolsite proximity not recorded for this parcel — if any part is within 1/4 mile "
                "of a schoolsite, this row needs a method code (3 CCR 6691)."
            )
            flags.append({"code": "schoolsite_proximity_unknown"})
        # Distinguish "no county logged" from "county logged but not a CA county" —
        # the latter can't map to a CAC code and box 10 was blanked above.
        if county_name and not county_code:
            notes.append(f"County '{county_name}' is not a recognized CA county — box 10 needs the CAC county number.")
            flags.append({"code": "county_unrecognized", "county": county_name})
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
            flags.append({"code": "tank_mix_unexported", "partners": tank_mix})
        if (ed.get("is_summary") is True) or _s(event.time_period):
            notes.append("Aggregate/summary event — PUR wants one line per application.")
            flags.append({"code": "aggregate_event"})
        converted = [o for o in (planted_original, area_original) if o]
        if converted:
            notes.append("Acres converted from hectares (" + ", ".join(converted) + ") — the PUR has no hectare unit.")
            flags.append({"code": "area_converted_from_ha", "from": ", ".join(converted)})
        row["notes"] = " | ".join(notes)
        # Preview-only (never CSV columns): the county as code + name so the client can group
        # and warn on a multi-county month — the filing is per county (3 CCR 6626(a)).
        row["county_code"] = county_code
        row["county_name"] = county_name
        self._attach_preview_fields(row, event, getattr(parcel, "id", None), missing, flags)
        return row

    @staticmethod
    def _pcb_entry(event):
        """A hired application, listed rather than exported (see module notes)."""
        history = getattr(event, "history", None)
        parcel = getattr(history, "parcel", None)
        event_date = getattr(event, "date", None)
        return {
            "event_id": event.id,
            "event_type": CHEMICAL_EVENT_TYPE,
            "parcel_id": getattr(parcel, "id", None),
            "event_date": event_date.isoformat() if event_date else "",
            "product": _s(event.commercial_name),
            "pcb_name": _s(getattr(event, "pcb_name", None)),
        }

    @staticmethod
    def _attach_preview_fields(row, event, parcel_id, missing, flags):
        """Preview-only fields for the JSON summary.

        None of these keys is in PUR_COLUMNS, so `to_csv` — which writes `row.get(key)` for
        the DPR box keys only — never emits them; the filed CSV keeps its column contract
        (guard: test_preview_only_fields_never_reach_csv).

        They exist because the preview showed two rows reading "Kocide 3000-O / Ground
        (air-blast)" with no date and no way to open either. `application_start` (box 17)
        was one of the blanks, so the row lost its only date exactly when the farmer most
        needed to find the event — and the modal said "open the event" while carrying
        nothing to open it with.
        """
        row["event_id"] = event.id
        row["event_type"] = CHEMICAL_EVENT_TYPE
        row["parcel_id"] = parcel_id
        # The event's own `date` is always set — it is what _applications filters on —
        # unlike application_start. ISO, so the client formats it in the farmer's locale.
        event_date = getattr(event, "date", None)
        row["event_date"] = event_date.isoformat() if event_date else ""
        row["missing"] = list(missing)
        row["flags"] = flags

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
                anum = _acres(_s(event.area) or _s(getattr(event, "area_numeric", None)), area_unit)
                if vnum is not None and anum and vol_unit:
                    rate_display = f"{vnum / anum:.2f} {vol_unit}/acre"
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
            # `primary_row["missing"]` already knows whether box 21a is owed, and it is the same
            # application on the same ground by the same method — so read that verdict rather
            # than re-deriving the schoolsite rule here and letting the two drift.
            if not row.get("ffm_code") and (
                row.get("application_method") == "Fume" or "ffm_code" in (primary_row.get("missing") or [])
            ):
                missing.append("ffm_code")

            notes = []
            if missing:
                headers = {k: h for k, h, _r in PUR_COLUMNS}
                notes.append("Missing required: " + ", ".join(headers.get(m, m) for m in missing))
            notes.append(f"Tank-mix adjuvant applied with {primary_name} — separate PUR line per 3 CCR 6624.")
            row["notes"] = " | ".join(notes)
            self._attach_preview_fields(
                row,
                event,
                primary_row.get("parcel_id"),
                missing,
                [{"code": "adjuvant_line", "primary": primary_name}],
            )
            rows.append(row)
        return rows

    def build(self):
        """``(rows, pcb_excluded)`` for the month.

        Rows are the grower's own applications (plus adjuvant lines), grouped by county code
        and dated within each county — the filing is per county (3 CCR 6626(a)), so a
        multi-county month reads as N contiguous blocks rather than one interleaved list.
        ``pcb_excluded`` are the hired applications that are NOT the grower's to report.
        """
        header = self._operator_header()
        rows, excluded = [], []
        for event in self._applications():
            if getattr(event, "applied_by_pcb", False):
                excluded.append(self._pcb_entry(event))
                continue
            primary = self._row(event, header)
            rows.append(primary)
            rows.extend(self._adjuvant_rows(event, primary))
        # Stable: within a county the query's date order survives, and an adjuvant line
        # shares its primary's key so it stays directly under it. A blank county sorts last.
        rows.sort(key=lambda r: (r.get("county_code") or "99", r.get("event_date") or ""))
        return rows, excluded

    def build_rows(self):
        return self.build()[0]

    @staticmethod
    def _counties(rows):
        """Ordered ``[{code, name, count}]`` over the rows, unknown county last as code ''."""
        seen = {}
        for r in rows:
            code = r.get("county_code") or ""
            entry = seen.setdefault(code, {"code": code, "name": r.get("county_name") or "", "count": 0})
            entry["count"] += 1
        return list(seen.values())

    def summary(self):
        rows, excluded = self.build()
        complete = sum(1 for r in rows if not r["missing"])
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
            "counties": self._counties(rows),
            "pcb_excluded_count": len(excluded),
            "pcb_excluded": excluded,
            "rows": rows,
        }

    def to_csv(self, built=None):
        rows, excluded = built if built is not None else self.build()
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
        if excluded:
            # Visible, not silent: the county reader can reconcile against the business's filing.
            names = sorted({e["pcb_name"] for e in excluded if e["pcb_name"]})
            by = f" ({', '.join(names)})" if names else ""
            writer.writerow(
                [
                    f"Applied by a licensed pest control business — NOT reported here: {len(excluded)}{by}. "
                    "The business files its own use report within 7 days of the application and sends "
                    "the operator a copy within 30 days (3 CCR 6626(b))."
                ]
            )
        counties = self._counties(rows)
        if len(counties) > 1:

            def _label(c):
                if c["code"]:
                    return f"{c['code']} {c['name']}"
                if c["name"]:
                    return f"{c['name']} (not a recognized CA county)"
                return "county not recorded"

            parts = ", ".join(f"{_label(c)} — {c['count']}" for c in counties)
            writer.writerow(
                [
                    f"Counties: {parts}. A use report is filed with the Agricultural Commissioner of each county "
                    "where the work was performed (3 CCR 6626(a)); rows below are grouped by county."
                ]
            )
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
