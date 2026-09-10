"""
COG Pro CSV import — parse a departing subscriber's export into Trazo events.

COG Pro stops service 2026-12-31 (their own signup page), so every subscriber has to move during
Oct–Dec 2026. This module reads the CSVs their export produces and turns them into Trazo events.

The real schema is documented in `documentation/reference/cogpro-export-format.md`, captured from
COG Pro's own public demo account rather than guessed. Everything below matches that capture.

## Design

**Route on the HEADER ROW, never the filename.** Their guide says files arrive named
`cogpro_my_fertility_input_data.csv`, but farmers rename downloads, forward them through email, and
export twice into `(1)` copies. The header is unambiguous and free.

**Match English AND Spanish headers.** COG Pro is fully bilingual — a Spanish-locale farmer's
export has `"Fecha de Aplicación"` where an English one has `"Application Date"`. Matching only
English would reject the file of exactly the crew most likely to need the migration done for them.

**Index-based column access, not `dict(zip(...))`.** `"Planting Rate"` appears TWICE in their Field
Plan header; zipping into a dict silently drops one.

**Never invent.** A row with no date is skipped, not dated today. Their computed display columns
(`"bunches / sq. feet"`) and unrendered template tokens (`$[phpcode_3]`) are treated as empty. A
value we cannot map is reported, not approximated — same rule as the Common OSP workbooks.

**Dry-run by default.** `plan()` reports what would happen and writes nothing; `execute()` writes.
The management command requires an explicit `--commit`.

## Scope

Imports into EXISTING Trazo event types on an EXISTING production the operator names. It does not
create parcels, productions or a mapping UI — this is a white-glove tool run by a human who is
looking at the farm's records while they run it.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

#: Values COG Pro emits that are display artifacts or unrendered template tokens, never data.
_JUNK_VALUES = {"", "-", "n/a", "$[phpcode_3]"}


def _clean(value: Optional[str]) -> Optional[str]:
    """Trim, and turn COG Pro's junk placeholders into None.

    `$[phpcode_3]` is an unrendered template token that appears verbatim in the Gross Return
    column of their real export. Importing it as a value would put template source into a
    farmer's records.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _JUNK_VALUES:
        return None
    # Computed display columns arrive pre-joined, e.g. "bunches / sq. feet" or "/ sq. feet".
    if text.startswith("/") or text.endswith("/"):
        return None
    return text or None


def _parse_date(value: Optional[str]):
    """COG Pro exports MM/DD/YYYY. Some rows carry a weekday form ("Thu, 2025-04-24")."""
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%a, %Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _as_event_datetime(d):
    """Encode a date-only value so it renders as the SAME calendar day everywhere.

    🔴 Trazo's event `date` is a DateTimeField and USE_TZ is on. Passing a bare date stores
    midnight UTC — which in California is 5pm the PREVIOUS day, so an imported spray dated
    05/12/2016 rendered in the timeline as "May 11, 2016". On a spray record that is not
    cosmetic: REI/PHI windows and the CA monthly PUR filing are all keyed to the application
    date, and native Trazo events store local morning (07:00-08:00 UTC), not UTC midnight.

    Noon UTC is the safe encoding: it lands on the same calendar date for every timezone from
    UTC-11 through UTC+11. Same off-by-one family as the CertifierDeadlinesStrip date bug.
    """
    from datetime import datetime, time, timezone

    return datetime.combine(d, time(12, 0), tzinfo=timezone.utc)


def _parse_decimal(value: Optional[str]):
    text = _clean(value)
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


#: COG Pro area/yield units are free text; Trazo's are constrained choices. Map only what is
#: unambiguous and fall back to the model default rather than forcing a wrong choice.
_AREA_UNITS = {
    "acre": "acres",
    "acres": "acres",
    "sq. feet": "sqft",
    "sq feet": "sqft",
    "square feet": "sqft",
    "hectare": "hectares",
    "hectares": "hectares",
}
_YIELD_UNITS = {
    "lbs": "lb",
    "lb": "lb",
    "pounds": "lb",
    "kg": "kg",
    "kilograms": "kg",
    "tons": "tons",
    "bushels": "bushels",
    "boxes": "boxes",
    "crates": "crates",
}


def _map_area_unit(value):
    """Returns a Trazo unit, or None when COG Pro's unit has no safe equivalent.

    🔴 Returning a DEFAULT here fabricates magnitude. COG Pro allows "row feet", "row meter",
    "plants" — a Field Plan row reading "250 row feet" was being imported as "250 acres", a
    ~10,000x misstatement of the planted area on a record a certifier reads. Same failure class
    as the hectares/acres bug fixed in 2026-08. When the unit is unmappable the caller must NOT
    write the numeric field at all; the raw pair is preserved in extra_data instead.
    """
    return _AREA_UNITS.get((value or "").strip().lower())


def _map_yield_unit(value):
    """Returns a Trazo unit, or None when there is no safe equivalent.

    COG Pro yields come in heads, bunches, pints, "bales, lg sq". Defaulting those to pounds
    would restate the harvest.
    """
    return _YIELD_UNITS.get((value or "").strip().lower())


@dataclass(frozen=True)
class Area:
    """One COG Pro export tab.

    `signature` columns must all be present in the header for the file to match. Kept small and
    distinctive so a partial or reordered export still routes: COG Pro's own column order has
    changed across versions, and a farmer may hand us a file they edited in Excel.
    """

    key: str
    label: str
    signature_en: tuple
    signature_es: tuple
    #: Trazo event model + subtype this area maps to.
    target: str


AREAS: list = [
    Area(
        key="fertility",
        label="Fertility",
        signature_en=("Application Date", "Inputs", "Brand"),
        signature_es=("Fecha de Aplicación", "Material Usado", "Marca"),
        target="ChemicalEvent:FE",
    ),
    Area(
        key="pest",
        label="Pest Control",
        # "Target" + the interval columns are what distinguish pest from fertility.
        signature_en=("Application Date", "Target", "Input"),
        signature_es=("Fecha de Aplicación", "Objetivo", "Material Usado"),
        target="ChemicalEvent:PE",
    ),
    Area(
        key="weed",
        label="Weed Control",
        signature_en=("Application Date", "Material Used", "Equipment Used"),
        signature_es=("Fecha de Aplicación", "Material Usado", "Equipo Utilizado"),
        target="ChemicalEvent:HE",
    ),
    Area(
        key="tillage",
        label="Field Work",
        signature_en=("Type of Work Done", "Other equipment"),
        signature_es=("Tipo de Trabajo Realizado",),
        target="ProductionEvent:CU",
    ),
    Area(
        key="yield",
        label="Harvest/Sales",
        signature_en=("Harvest Lot No.", "Yield Amount", "Yield Units"),
        signature_es=("Cantidad Cosechada",),
        target="ProductionEvent:HA",
    ),
    Area(
        key="equipment",
        label="Other (equipment cleaning)",
        signature_en=("Equipment", "Target", "Material", "Method"),
        signature_es=("Equipo", "Objetivo", "Material"),
        target="ProductionEvent:EM",
    ),
    Area(
        key="field_plan",
        label="Field Plan",
        signature_en=("Planting Date", "Seed Lot #", "Planting Method"),
        signature_es=("Fecha de Siembra",),
        target="ProductionEvent:PL",
    ),
]


def detect_area(headers: list) -> Optional[Area]:
    """Which COG Pro tab is this file? Header-driven, English or Spanish.

    Ordered most-specific first: Pest and Fertility share several columns, so Pest's distinctive
    "Target"/"Input" pair must be tested before Fertility's broader signature.
    """
    present = {h.strip() for h in headers if h}
    ordered = sorted(AREAS, key=lambda a: -len(a.signature_en))
    for area in ordered:
        for signature in (area.signature_en, area.signature_es):
            if signature and all(col in present for col in signature):
                return area
    return None


@dataclass
class RowResult:
    line: int
    action: str  # "import" | "skip"
    reason: str = ""
    summary: str = ""
    payload: dict = field(default_factory=dict)


@dataclass
class ImportPlan:
    area: Optional[Area]
    rows: list = field(default_factory=list)
    error: str = ""

    @property
    def importable(self):
        return [r for r in self.rows if r.action == "import"]

    @property
    def skipped(self):
        return [r for r in self.rows if r.action == "skip"]


def _col(headers: list, row: list, name: str, occurrence: int = 0):
    """Index-based lookup.

    `dict(zip(headers, row))` is wrong for this data: COG Pro's Field Plan header contains
    "Planting Rate" twice, and a dict keeps only the last. `occurrence` selects which one.
    """
    seen = 0
    for i, h in enumerate(headers):
        if h and h.strip() == name:
            if seen == occurrence:
                return _clean(row[i]) if i < len(row) else None
            seen += 1
    return None


def _first(headers, row, *names):
    """First non-empty value among several possible column names (EN/ES variants)."""
    for n in names:
        v = _col(headers, row, n)
        if v:
            return v
    return None


def build_plan(file_obj) -> ImportPlan:
    """Parse a COG Pro CSV into a plan. Reads only — never writes."""
    raw = file_obj.read()
    if isinstance(raw, bytes):
        # Their export is Excel-oriented; BOM and latin-1 both show up in the wild.
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                raw = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    reader = csv.reader(io.StringIO(raw))
    try:
        headers = next(reader)
    except StopIteration:
        return ImportPlan(area=None, error="The file is empty.")

    area = detect_area(headers)
    if area is None:
        return ImportPlan(
            area=None,
            error=("This does not look like a COG Pro export. Expected one of: " + ", ".join(a.label for a in AREAS)),
        )

    plan = ImportPlan(area=area)
    for line_no, row in enumerate(reader, start=2):
        # Fully blank rows exist in their real export.
        if not any(_clean(c) for c in row):
            continue

        date = _parse_date(
            _first(headers, row, "Application Date", "Date", "Planting Date", "Fecha de Aplicación", "Fecha de Siembra")
        )
        if date is None:
            # Never date a record we cannot date — an event on the wrong day is a false record,
            # and their export genuinely contains rows with a blank date.
            plan.rows.append(
                RowResult(
                    line=line_no,
                    action="skip",
                    reason="No usable date — COG Pro allows undated rows; import it by hand if it matters.",
                    summary=_first(headers, row, "Crop", "Cultivo", "Equipment") or "(no crop)",
                )
            )
            continue

        crop = _first(headers, row, "Crop", "Cultivo")
        field_id = _first(headers, row, "Field ID", "No. Identificación del Campo")
        product = _first(
            headers,
            row,
            "Brand",
            "Brand Name",
            "Inputs",
            "Input",
            "Material Used",
            "Material",
            "Marca",
            "Material Usado",
        )
        amount = _parse_decimal(_first(headers, row, "Amount", "Yield Amount", "Cantidad"))
        measure = _first(headers, row, "Measure", "Yield Units", "Unidad de Medida")
        notes = _first(headers, row, "Notes", "Apuntes")

        # Columns this parser maps to a real Trazo field. Everything NOT in here is preserved
        # verbatim under `unmapped` — a migration must never silently discard a column, and an
        # audit of the first version found 42% of COG Pro's columns being dropped on the floor.
        mapped_cols = set()

        def take(*names, occurrence=0):
            for n in names:
                v = _col(headers, row, n, occurrence)
                if v:
                    mapped_cols.add(n)
                    return v
            for n in names:
                mapped_cols.add(n)
            return None

        crop = take("Crop", "Cultivo")
        field_id = take("Field ID", "No. Identificación del Campo")
        row_section = take("Row/Section ID", "No. identificación de fila / sección")
        # Brand and SUBSTANCE are different things and must not compete for one field.
        #
        # COG Pro's chemical tabs carry both: Pest has `Brand Name` ("Entrust SC") AND `Input`
        # ("Spinosad"); Fertility has `Brand` AND `Inputs`. Because `take()` returns the first
        # match, the brand always won and the substance was left unclaimed — it landed in
        # extra_data.unmapped.
        #
        # That silently emptied the certifier findings. `history/signals.py` classifies against
        # the National List by SUBSTANCE name, so matching a brand against it never hits:
        # "Spinosad" is a catalogue substance, "Entrust SC" is a brand and never will be one.
        product = take("Brand", "Brand Name", "Marca")
        substance = take("Inputs", "Input", "Material Used", "Material", "Material Usado")
        # Fall back so a row that names only one of the two still records something useful.
        if not product:
            product = substance
        if not substance:
            substance = product
        amount = _parse_decimal(take("Amount", "Yield Amount", "Cantidad"))
        measure = take("Measure", "Yield Units", "Unidad de Medida")
        rate = take("Rate", "Dosis/Proporción")
        method = take("Method", "Planting Method", "Método")
        equipment = take("Equipment", "Equipment Used", "Equipo Utilizado", "Equipo")
        labor = _parse_decimal(take("Labor in hrs", "Trabajo en Horas"))
        notes = take("Notes", "Apuntes")

        # 🔴 A weed row with nothing applied is CULTIVATION, not a herbicide application.
        #
        # COG Pro's Weed Control tab mixes both: "Mechanical / berm sweep", "Flame / propane
        # flamer" and "Spot spray / Suppress EC" all live in it. Routing the whole tab to
        # ChemicalEvent:HE recorded mechanical cultivation as a HERBICIDE APPLICATION WITH NO
        # HERBICIDE — on an organic farm that is a false record in the single worst place to have
        # one, since § 205.601 makes herbicide use the thing a certifier scrutinises hardest.
        #
        # It also crashed the import outright: `volume_unit` is NOT NULL, so a row with no measure
        # raised IntegrityError and killed the run. Mechanical weeding is the most common organic
        # weed practice, so essentially every organic export hit this.
        #
        # Decided on DATA, not vocabulary — nothing applied means nothing was applied — so it
        # holds for Spanish exports and for method names we have never seen.
        target = area.target
        if area.key == "weed" and not product and not substance:
            target = "ProductionEvent:CU"

        payload = {
            "cogpro_area": area.key,
            "target": target,
            "date": date,
            "crop": crop,
            "field_id": field_id,
            "row_section": row_section,
            "product": product,
            "substance": substance,
            "amount": amount,
            "measure": measure,
            "rate": rate,
            "method": method,
            "equipment": equipment,
            "labor_hours": labor,
            "notes": notes,
        }

        if area.key in ("pest", "weed"):
            payload["target_pest"] = take("Target", "Objetivo")
            # A cultivation row has no "Type of Work Done" column to name it from, and the
            # ProductionEvent namer would otherwise fall through to the equipment. The method is
            # what a certifier reads: "Mechanical", "Flame".
            if target == "ProductionEvent:CU":
                payload["work_done"] = method or "Weed control"
            payload["manufacturer"] = take("Manufacturer", "Fabricante")
            payload["rei_hours"] = _parse_decimal(take("Restricted-Entry Interval (REI) (hrs/days)"))
            payload["phi_days"] = _parse_decimal(take("Pre-harvest Interval (PHI) (hrs/days)"))
            payload["equipment_status"] = take("Equipment Status")
        elif area.key == "tillage":
            # The defining column of this tab — it says what was actually done.
            payload["work_done"] = take("Type of Work Done", "Tipo de Trabajo Realizado")
            payload["other_equipment"] = take("Other equipment")
        elif area.key == "yield":
            payload["lot"] = take("Harvest Lot No.")
            payload["variety"] = take("Variety", "Variedad")
            payload["area_planted"] = _parse_decimal(take("Area Planted"))
            payload["area_measure"] = take("Area Measure")
            payload["product_value"] = _parse_decimal(take("Product Value"))
            payload["batch"] = take("Planting Batch #")
            payload["status"] = take("Status")
            payload["classification"] = take("Classification")
            # Computed display columns — recorded as mapped so they are not reported as lost,
            # but never imported: they are derived, not entered.
            for derived in ("Yield", "Units Per Area", "Gross Return", "Per Area Planted"):
                mapped_cols.add(derived)
        elif area.key == "field_plan":
            # "Planting Rate" appears TWICE in their Field Plan header and the two carry different
            # things — spacing ("27 ft x 22 ft") and density ("73 trees/ac"). Reading only the
            # first silently dropped the second, which is the documented gotcha this parser is
            # index-based to avoid; being index-based is not enough if only one index is read.
            payload["planting_rate"] = take("Planting Rate", occurrence=0)
            second_rate = _col(headers, row, "Planting Rate", occurrence=1)
            if second_rate and second_rate != payload["planting_rate"]:
                payload["planting_rate_2"] = second_rate
            payload["seed_lot"] = take("Seed Lot #")
            payload["alt_seed_lot"] = take("Alt Seed Lot #")
            payload["transplant_lot"] = take("Transplant Lot #")
            payload["variety"] = take("Variety", "Variedad")
            payload["area_planted"] = _parse_decimal(take("Area Planted"))
            payload["area_measure"] = take("Area Measure")
            payload["season"] = take("Season")
            payload["year"] = take("Year")
            payload["status"] = take("Status")
            payload["batch"] = take("Planting Batch #")
            payload["availability"] = take("Availability")
            for d in (
                "Projected Gemination Date",
                "Actual Germination Date",
                "Projected Harvest Date",
                "Actual Harvest Date",
                "Date Finished",
            ):
                v = take(d)
                if v:
                    payload.setdefault("dates", {})[d] = v
        elif area.key == "equipment":
            payload["target_pest"] = take("Target", "Objetivo")

        # Date columns already consumed by the date resolver.
        for d in ("Application Date", "Date", "Planting Date", "Fecha de Aplicación", "Fecha de Siembra"):
            mapped_cols.add(d)

        # 🔴 Anything still unmapped is carried verbatim. A farmer migrating off a dying service
        # must not lose a column because we did not anticipate it.
        unmapped = {}
        for i, h in enumerate(headers):
            name = (h or "").strip()
            if name and name not in mapped_cols and i < len(row):
                v = _clean(row[i])
                if v:
                    unmapped[name] = v
        if unmapped:
            payload["unmapped"] = unmapped

        plan.rows.append(
            RowResult(
                line=line_no,
                action="import",
                summary=f"{date.isoformat()} · {crop or '(no crop)'} · {product or area.label}",
                payload=payload,
            )
        )
    return plan


def analyze(file_obj) -> dict:
    """Describe the SHAPE of a COG Pro export before importing anything.

    🔴 The structural mismatch this exists for.

    COG Pro is FIELD-CENTRIC and FLAT. Its activity tabs (fertility, pest, weed, field work,
    equipment) carry `Field ID`, `Crop` and a date — and no production, batch or season column at
    all. Only Field Plan and Harvest carry `Planting Batch #`, which is the closest thing they
    have to a production and which the activity rows never reference.

    Trazo is PRODUCTION-CENTRIC: every event belongs to a History, which belongs to a Parcel.

    So a COG Pro export contains no column saying "this spray belongs to production X", and the
    only honest join is **Field ID + Crop + Year**. A single export routinely spans many fields
    and many years — their own demo runs 2010-2026 — so importing a whole file into one Trazo
    production would collapse a decade of separate seasons into one record and destroy the
    field-to-season structure the farmer had.

    This reports that shape so the operator can create the right parcels and productions first,
    then import group by group. Reads only.
    """
    plan = build_plan(file_obj)
    if plan.area is None:
        return {"error": plan.error, "area": None}

    groups = {}
    fields, crops, years = set(), set(), set()
    unscoped = 0
    for row in plan.importable:
        p = row.payload
        raw_field = p.get("field_id")
        raw_crop = p.get("crop")
        field_id = raw_field or "(no field id)"
        crop = raw_crop or "(no crop)"
        year = p["date"].year

        # The placeholders are for GROUPING only and must never reach `fields`/`crops`: those
        # drive the "parcels to create" summary, and an operator following it would create a
        # parcel literally named "(no field id)".
        #
        # An absent Field ID is not malformed data. The Other/equipment tab is EQUIPMENT-scoped
        # by design — a sprayer tank rinse under § 205.272 belongs to the machine, not to a
        # field — so every one of its rows lands here legitimately.
        if raw_field:
            fields.add(raw_field)
        else:
            unscoped += 1
        if raw_crop:
            crops.add(raw_crop)

        years.add(year)
        groups.setdefault((field_id, crop, year), []).append(row.line)

    return {
        "area": plan.area.key,
        "label": plan.area.label,
        "rows": len(plan.importable),
        "skipped": len(plan.skipped),
        "fields": sorted(fields),
        "crops": sorted(crops),
        # Rows carrying no Field ID — equipment-scoped work, not a parcel.
        "unscoped_rows": unscoped,
        "years": sorted(years),
        "groups": [
            {"field_id": k[0], "crop": k[1], "year": k[2], "events": len(v), "lines": v}
            for k, v in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][1]))
        ],
    }


def _production_event_name(p: dict, subtype: str) -> str:
    """What the event is CALLED — the first thing a farmer or certifier reads in the timeline.

    A generic "first non-empty column" fallback produced records named after whatever tool was
    used: an equipment-cleaning record called **"Water"** and an orchard planting called
    **"Auger"**. Neither says what happened, and on a § 205.272 commingling record or a planting
    record that is the whole point of the entry.

    Each tab therefore names from ITS OWN defining column.
    """
    if subtype == "EM":
        # Equipment tab: "Target" is the job — "Tank cleanout", "Equipment cleaning".
        base = p.get("target_pest") or "Equipment cleaning"
        equipment = p.get("equipment")
        return f"{base} — {equipment}" if equipment else base
    if subtype == "PL":
        variety = p.get("variety")
        crop = p.get("crop")
        label = " ".join(x for x in (variety, crop) if x)
        return f"Planting — {label}" if label else "Planting"
    if subtype == "HA":
        label = " ".join(x for x in (p.get("variety"), p.get("crop")) if x)
        return f"Harvest — {label}" if label else "Harvest"
    # Field Work and weed-cultivation: "Type of Work Done" / the method.
    return p.get("work_done") or p.get("product") or p.get("equipment") or p.get("crop") or "Field work"


def execute(plan: ImportPlan, production, created_by=None) -> dict:
    """Write the plan's importable rows onto `production` as Trazo events.

    Deliberately narrow: attaches to an EXISTING production the operator names. COG Pro data spans
    many fields and years (their demo runs 2010–2026), and deciding which Trazo production each
    row belongs to is a judgement call a human makes while looking at the farm — not something to
    infer. The white-glove operator runs this once per production.
    """
    from history.models import ChemicalEvent, ProductionEvent

    if plan.area is None:
        raise ValueError(plan.error or "No importable area detected.")

    created = []
    for row in plan.importable:
        p = row.payload
        model, subtype = p["target"].split(":")

        # Traceability + everything Trazo has no column for. `unmapped` is the guarantee that a
        # migrating farm loses nothing: any COG Pro column this parser does not map to a real
        # field is preserved here verbatim, visible to the operator.
        extra = {
            "cogpro_import": {
                "area": p["cogpro_area"],
                "source_line": row.line,
                "crop": p.get("crop"),
                "field_id": p.get("field_id"),
                "row_section": p.get("row_section"),
                "original_notes": p.get("notes"),
            }
        }
        if p.get("unmapped"):
            extra["cogpro_import"]["unmapped"] = p["unmapped"]

        # The ACTIVE INGREDIENT goes where native events keep it: `extra_data["active_ingredient"]`
        # (78 existing rows use that key; ChemicalEvent has no such column). It must be a real key
        # rather than an `unmapped` leftover, because the National List classifier reads it — the
        # list is keyed on substances like "Spinosad", never on brands like "Entrust SC".
        substance = p.get("substance")
        if substance and substance != p.get("product"):
            extra["active_ingredient"] = substance
        for key in (
            "season",
            "year",
            "status",
            "classification",
            "availability",
            "batch",
            "dates",
            "equipment_status",
            "alt_seed_lot",
            "transplant_lot",
            "product_value",
            # Written to a real column on ChemicalEvent, but the ProductionEvent branch has no
            # target field — and `take()` already marked the column mapped, so without this a
            # cultivation row would drop "Winter annuals" with no trace in `unmapped`.
            "target_pest",
            # Same shape: ChemicalEvent has no equipment/labour columns at all, so a fertility or
            # pest row's "Equipment" and "Labor in hrs" vanished silently. The importer's own
            # promise is that a migrating farm loses no column.
            "equipment",
            "labor_hours",
        ):
            if p.get(key) is not None:
                extra["cogpro_import"][key] = p[key]

        if model == "ChemicalEvent":
            obj = ChemicalEvent.objects.create(
                history=production,
                type=subtype,
                date=_as_event_datetime(p["date"]),
                commercial_name=p.get("product"),
                manufacturer=p.get("manufacturer"),
                volume=str(p["amount"]) if p.get("amount") is not None else None,
                volume_numeric=p.get("amount"),
                # NEVER None: `volume_unit` is NOT NULL, so passing None overrode the model
                # default and raised IntegrityError, aborting the whole migration on one row.
                # Empty rather than falling back to the model's 'gal' default — a blank unit is a
                # visible gap, "gal" on a record that named no unit is an invented measurement.
                volume_unit=p.get("measure") or "",
                # COG Pro's "Rate" is free text ("50 lbs per acre"), which is what
                # `concentration` already holds — do not try to parse it into a number.
                concentration=p.get("rate"),
                way_of_application=p.get("method"),
                # COG Pro's "Row/Section ID" IS Trazo's block_id — CommonEvent defines it as
                # "Farm block or section identifier" and the CA PUR export already emits it as
                # box 22 (Block ID). Leaving it in extra_data would have hidden a value the
                # regulator form asks for.
                block_id=p.get("row_section"),
                target_pest_disease=p.get("target_pest"),
                rei_hours=p.get("rei_hours"),
                phi_days=p.get("phi_days"),
                observation=p.get("notes"),
                extra_data=extra,
            )
        else:
            # ProductionEvent has no column for any of these, and `take()` had already marked the
            # source columns mapped — so without this they were dropped with no trace in
            # `unmapped`, which is exactly what the migration guarantee forbids:
            #   other_equipment  Field Work's second equipment column ("Chain saws")
            #   planting_rate    orchard spacing ("27 ft x 22 ft"), checked against the OSP
            #   variety          "Chandler" — material to the certifier AND the buyer page
            #   method           on an EM row this is the § 205.272 CLEANING METHOD ("Triple
            #                    rinse"), which IS the substance of a commingling record
            #   amount/measure   200 gallons of rinse water, likewise
            # Only on this branch: ChemicalEvent writes them to real columns already.
            for key in ("other_equipment", "planting_rate", "planting_rate_2", "method", "rate", "lot"):
                if p.get(key) is not None:
                    extra["cogpro_import"][key] = p[key]
            if p["cogpro_area"] != "yield" and p.get("amount") is not None:
                extra["cogpro_import"]["amount"] = f"{p['amount']} {p.get('measure') or ''}".strip()
            # On the Other/equipment tab the material IS the cleaning agent — water versus an
            # OMRI-listed sanitiser is the § 205.272 question. It has no ProductionEvent column
            # and, since the event is now named after the job rather than the material, nothing
            # else would carry it.
            if p.get("product"):
                extra["cogpro_import"]["material"] = p["product"]

            fields = dict(
                history=production,
                type=subtype,
                date=_as_event_datetime(p["date"]),
                name=_production_event_name(p, subtype),
                block_id=p.get("row_section"),
                observation=p.get("notes"),
                equipment_hours=p.get("labor_hours"),
                extra_data=extra,
            )
            # A number is only written together with a unit Trazo can represent. An unmappable
            # unit means the raw pair is preserved verbatim and the typed field is left empty —
            # an empty field is a gap the operator can see, a wrong unit is a false record.
            if p.get("area_planted") is not None:
                unit = _map_area_unit(p.get("area_measure"))
                if unit:
                    fields["area_covered"] = p["area_planted"]
                    fields["area_unit"] = unit
                else:
                    extra["cogpro_import"][
                        "area_planted_raw"
                    ] = f"{p['area_planted']} {p.get('area_measure') or ''}".strip()
            if p["cogpro_area"] == "yield" and p.get("amount") is not None:
                unit = _map_yield_unit(p.get("measure"))
                if unit:
                    fields["yield_quantity"] = p["amount"]
                    fields["yield_unit"] = unit
                else:
                    extra["cogpro_import"]["yield_raw"] = f"{p['amount']} {p.get('measure') or ''}".strip()
            if p.get("seed_lot"):
                fields["seed_lot_number"] = p["seed_lot"]
            # ProductionEvent HAS a variety column; the importer was only stashing it in
            # extra_data, so "Chandler" never reached the field the app and the buyer page read.
            if p.get("variety"):
                fields["variety"] = p["variety"]
            obj = ProductionEvent.objects.create(**fields)
        created.append(obj)

    return {
        "area": plan.area.key,
        "created": len(created),
        "skipped": len(plan.skipped),
        "production": getattr(production, "name", None),
    }
