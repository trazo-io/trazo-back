"""
Trazo Audit Export Service
Generates PDF and CSV audit-ready reports from production data.

Supports certification-specific filtering for:
  organic, globalgap, roc, fsma204, scs, all
"""

# Defer annotation evaluation (PEP 563) so PEP 604 syntax like `str | None`
# works on Python 3.9. Production runs python:3.9-slim per Dockerfile, where
# `X | None` raises TypeError at class-body execution time without this.
from __future__ import annotations

import csv
import hashlib
import io
import logging
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from certifications.constants import NOP_CERTIFICATION_TYPES as _NOP_CERTIFICATION_TYPES
from certifications.constants import ORGANIC_CONFERRING_CERT_TYPES as _ORGANIC_CONFERRING_CERT_TYPES
from certifications.services.registry_identifiers import CDFA_OIM_REGISTERED_LABEL, wsda_identifier_label
from common.field_registry import (
    NO_TREATMENT_ANSWERS,
    NON_ORGANIC_SEED_STATUSES,
    ORGANIC_APPROVED,
    UNIT_APPLICATION_RATE,
)
from common.pdf_text import glyph_safe
from common.specimen import (
    SPECIMEN_BODY,
    SPECIMEN_LINE,
    SPECIMEN_TITLE,
    establishment_of,
    is_specimen,
    specimen_page_callback,
)
from common.us_states import resolve_establishment_state

logger = logging.getLogger(__name__)

# Trazo brand green
TRAZO_GREEN = colors.HexColor("#4CAF50")
# Section headings AND table-header fills. #4CAF50 (TRAZO_GREEN) is the brand primary, but
# white text on it measures 2.78:1 — under the WCAG AA floor of 4.5:1 for 7pt table headers,
# and it greys out further on a laser printer, which is how an inspector usually reads this.
# #2E7D32 is the same brand ramp (the app's green.700 active-state token) at 5.13:1.
TRAZO_GREEN_DARK = colors.HexColor("#2E7D32")
LIGHT_GRAY = colors.HexColor("#F5F5F5")
MID_GRAY = colors.HexColor("#CCCCCC")
DARK_GRAY = colors.HexColor("#333333")

# Display labels for event type codes
# Tillage practice vocabulary, § 205.203(a).
#
# 🔴 2026-08-19: the Tillage Detail table printed these raw — an inspector read
# "Direction: across_slope · Residue: surface_left". The words below are the ones the grower
# actually chose in the soil form (SoilManagementTab.jsx), minus the trailing explainer the
# select shows ("Across Slope - Erosion control"), because the packet states the practice and
# does not need to sell it back to the person who performed it.
#
# Unknown keys fall through to the raw value rather than blanking: a value we cannot name is
# still evidence, and silently dropping it would hide a practice the grower recorded.
TILLAGE_PRACTICE_LABELS = {
    # tillage_type
    "conventional_plow": "Conventional plow",
    "chisel_plow": "Chisel plow",
    "disk_harrow": "Disk harrow",
    "no_till": "No-till",
    "strip_till": "Strip till",
    "minimum_till": "Minimum till",
    "subsoiling": "Subsoiling",
    "cultivator": "Cultivator",
    # tillage_intensity
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "conservation": "Conservation",
    # tillage_direction
    "across_slope": "Across slope",
    "up_down_slope": "Up/down slope",
    "contour": "Contour",
    "random": "Random",
    # residue_management
    "incorporated": "Incorporated into soil",
    "surface_left": "Left on surface",
    "removed": "Removed",
    "mulched": "Mulched in place",
    "partial_removal": "Partially removed",
}

# The pest form's own crop-stage vocabulary. Deliberately separate from the model's
# growth_stage choices, which it does not overlap — see the note at the read site.
PEST_CROP_STAGE_LABELS = {
    "seedling": "Seedling",
    "vegetative": "Vegetative",
    "flowering": "Flowering",
    "fruit_development": "Fruit development",
    "maturity": "Maturity",
    "harvest": "Harvest",
}

PRODUCTION_TYPE_LABELS = {
    "PL": "Planting",
    "HA": "Harvesting",
    "IR": "Irrigation",
    "PR": "Pruning",
    "TR": "Transplanting",
    "EM": "Equipment Maintenance",
    "CU": "Cultivation",
    "TH": "Thinning",
    "PO": "Pollination",
    "PH": "Post-Harvest Processing",
    "CM": "Canopy Management",
    "FP": "Frost Protection",
    "MO": "Mowing",
    "TP": "Transport",
    "BU": "Buffer Use",
    "SS": "Seed Search",
}
# ⚠️ Hand-maintained against ProductionEvent.PRODUCTION_EVENTS, and the lookups below fall back
# to the RAW CODE — so a subtype missing here prints "TP" to an inspector rather than
# "Transport". `test_production_label_map_is_exhaustive` fails when the model grows a subtype
# this map has not seen, which is the only thing that keeps the two in step.

# Frost-protection technique labels. The FP subtype persists its technique under
# extra_data.protection_method (NOT extra_data.method), so the production-events
# Method cell must translate it explicitly or it renders blank for every frost row.
PROTECTION_METHOD_LABELS = {
    "wind_machine": "Wind machine",
    "orchard_heater": "Orchard heater",
    "under_tree_sprinkler": "Under-tree sprinkler",
    "other": "Other",
}

# Compact application-method labels for the audit tables. The canonical list lives in
# common.field_registry.APPLICATION_METHOD, but several of its labels ("Air-Blast (orchard
# sprayer)") are written for a form field and are too long for a 0.5" PDF column. The PDF was
# printing the RAW KEY instead — "air_blast", "fertigation" — which reads as a database dump in
# a document a certifier signs off.
APPLICATION_METHOD_LABELS = {
    "broadcast": "Broadcast",
    "injection": "Soil injection",
    "foliar": "Foliar",
    "drip": "Drip / fertigation",
    "fertigation": "Fertigation",
    "banding": "Banded",
    "ground_spray": "Ground spray",
    "air_blast": "Air-blast",
    "aerial": "Aerial",
    "fumigation": "Fumigation",
    "chemigation": "Chemigation",
    "soil_incorporation": "Soil incorporation",
}


#: Units that mean "a countable container", i.e. the ones `box_weight_lb` can convert to pounds.
#: Extracted from an inline literal so the boxes→pounds reconciliation and the mass-balance
#: section share one vocabulary — two lists would be the same defect this module just fixed.
_BOX_LIKE_UNITS = frozenset({"boxes", "box", "cartons", "carton", "lugs", "lug"})


def _is_box_unit(unit, *, blank_counts_as_boxes=False):
    """True when a sold-quantity unit can be multiplied by `box_weight_lb`.

    `blank_counts_as_boxes` is for legacy rows: `History.quantity_sold_unit` was often left
    empty, and the field only ever paired with `box_weight_lb`, which is meaningless for a
    mass unit. Never pass it for `SalesRecord` rows — those always carry an explicit unit.
    """
    cleaned = (unit or "").strip().lower()
    if not cleaned:
        return blank_counts_as_boxes
    return cleaned in _BOX_LIKE_UNITS


@dataclass(frozen=True)
class SalesDisclosure:
    """What the packet may say about who bought this production, and on what basis.

    ``source`` is "sales_records" or "legacy"; ``quantity`` is None when the rows disagree on
    unit and therefore cannot be summed honestly.
    """

    buyer: str
    sale_date: object
    organic_on_invoice: bool
    quantity: object
    quantity_unit: str
    source: str
    #: § 205.301 labeling category the product is sold under, which § 205.103(b)(3) requires
    #: records to carry. "" means not documented — never inferred. When sales rows disagree
    #: (a lot split across categories), this is "" and `label_categories` holds the set, so
    #: the packet reports the split instead of silently picking one.
    label_category: str = ""
    label_categories: tuple = ()


def resolve_sales_disclosure(production):
    """Single source of truth for the production's sales facts.

    SOE (§ 205.307(a)) supports multiple itemized sales per production, so `SalesRecord` rows
    win when present and the legacy single `sold_to` / `quantity_sold` / `organic_on_invoice`
    fields on `History` are the fallback.

    WHY THIS IS A FUNCTION AND NOT A BRANCH
    ---------------------------------------
    That precedence was implemented inline in the packet body while the compliance-snapshot
    row branched on `production.sold_to` alone. The result, verified on a rendered PDF
    (2026-08-10): page 1 said "Sales documentation (§ 205.103) — REVIEW: Add buyer +
    organic-on-invoice flag" while page 12 of the same document itemised the buyer, the
    invoice number and the bill of lading. The packet contradicted itself, and it under-
    reported the operation's own compliance to the certifier who reads page 1 first.

    This is the third recorded instance of one defect class: two writers for the same fact
    with disjoint key vocabularies, where fixing the surface under audit leaves the sibling
    surface wrong. So the precedence lives here once, and callers ask.
    """
    # `.live()`, not `.all()`: a VOIDED sale is kept on the record (§ 205.103(b)(4)) but it did
    # not happen, so it must not set the buyer, the sale date, the quantity sold, or — worst —
    # the "organic identification on every invoice" flag, which is an `all()` over these rows
    # and would be dragged to False by a row the operation itself retracted.
    try:
        sales = list(production.sales_records.live())
    except Exception:  # noqa: BLE001 — relation always present in practice
        sales = []

    if sales:
        first_unit = (sales[0].quantity_unit or "").strip()
        same_unit = all((s.quantity_unit or "").strip() == first_unit for s in sales)
        # A lot can legitimately ship under more than one labeling category. Collect the
        # distinct set; only collapse to a single value when the rows agree, so the packet
        # never picks one category on the operation's behalf.
        categories = tuple(sorted({(s.organic_label_category or "").strip() for s in sales} - {""}))
        return SalesDisclosure(
            buyer=", ".join(sorted({(s.buyer_name or "").strip() for s in sales if (s.buyer_name or "").strip()})),
            sale_date=max((s.sale_date for s in sales if s.sale_date), default=None),
            # ALL rows must be flagged. One unflagged shipment means the operation cannot
            # claim its organic identification was carried on every invoice.
            organic_on_invoice=all(s.organic_on_invoice for s in sales),
            quantity=sum(float(s.quantity) for s in sales) if same_unit else None,
            quantity_unit=first_unit,
            source="sales_records",
            label_category=categories[0] if len(categories) == 1 else "",
            label_categories=categories,
        )

    legacy_category = (getattr(production, "organic_label_category", "") or "").strip()
    return SalesDisclosure(
        buyer=(production.sold_to or "").strip(),
        sale_date=production.sale_date,
        organic_on_invoice=bool(production.organic_on_invoice),
        quantity=production.quantity_sold,
        quantity_unit=(production.quantity_sold_unit or "").strip(),
        source="legacy",
        label_category=legacy_category,
        label_categories=(legacy_category,) if legacy_category else (),
    )


def _seed_treatment_basis_display(event):
    """The § 205.204(a)(2) allowability basis for a seed treatment, in regulation wording.

    Prints the ask when a treatment is named with no basis, rather than a blank: silence in a
    certifier packet reads as "nothing to report" instead of "not yet recorded". Says nothing
    at all when no treatment was named — absence of a treatment is not a missing record, and
    neither is a grower writing "None" in the box.

    🔴 2026-08-15: this used to test the treatment string for truthiness alone. The input
    is free text whose own placeholder reads "e.g., Rhizobium inoculant, None", so "None" is
    the answer the UI invites — and the packet printed "Not recorded — 205.204(a)(2) asks why
    the treatment is allowed" beside it, telling a grower who correctly reported that nothing
    was applied that their record had a gap. A fabricated finding in a certifier packet is the
    same class of error as a fabricated claim.
    """
    from history.models import ProductionEvent

    basis = (getattr(event, "seed_treatment_allowed_basis", None) or "").strip()
    if basis:
        return dict(ProductionEvent.SEED_TREATMENT_BASIS_CHOICES).get(basis, basis)
    treatment = (getattr(event, "seed_treatment", None) or "").strip()
    if treatment and treatment.lower() not in NO_TREATMENT_ANSWERS:
        return "Not recorded — \u00a7 205.204(a)(2) asks why the treatment is allowed"
    return None


def _applied_by(ev):
    """The Applicator cell: who physically made the application.

    A hired pass names the pest control BUSINESS, because that is the record 3 CCR 6624(d)
    asks the grower to hold and the reason the same spray is absent from the grower's own
    monthly PUR (the business reports it, 3 CCR 6626(b)). The named applicator, when the
    grower recorded one, follows in parentheses so the packet does not lose the person.
    """
    business = (getattr(ev, "pcb_name", None) or "").strip()
    person = (getattr(ev, "applicator_name", None) or getattr(ev, "performed_by", None) or "").strip()
    if getattr(ev, "applied_by_pcb", False):
        who = business or "Pest control business (name not recorded)"
        return f"{who} — for hire" + (f" ({person})" if person else "")
    return person or None


def _target_or_purpose(event):
    """The form's "Purpose / Reason for Use" for one input application.

    Prefers the specific target where one exists (a pest name says more than a use category),
    and falls back to the § 205.601 use category — which is the only answer a fertilizer has.
    Both are shown when both are recorded, because "aphids" and "insecticide use" are different
    facts and § 205.601 lists synthetics by the latter.
    """
    from history.models import ChemicalEvent

    target = (getattr(event, "target_pest_disease", None) or "").strip()
    purpose_key = (getattr(event, "application_purpose", None) or "").strip()
    purpose = dict(ChemicalEvent.APPLICATION_PURPOSE_CHOICES).get(purpose_key, purpose_key)
    if target and purpose:
        return f"{target} \u00b7 {purpose}"
    return target or purpose or None


def _label_category_display(disclosure):
    """How the packet renders the § 205.301 labeling category.

    Three outcomes, and the distinction between them is the point:
      * one category on file  → its regulation wording
      * several (a lot split across categories) → all of them, never one picked for the operation
      * none → an explicit ask, because § 205.103(b)(3) requires this and silence in a
        certifier packet reads as "nothing to report" rather than "not yet recorded"
    """
    from history.models import ORGANIC_LABEL_CATEGORY_CHOICES

    labels = dict(ORGANIC_LABEL_CATEGORY_CHOICES)
    categories = [c for c in (disclosure.label_categories or ()) if c]
    if not categories:
        return "Not recorded — § 205.103(b)(3) requires records to identify the labeling category"
    if len(categories) == 1:
        return labels.get(categories[0], categories[0])
    return "Mixed: " + "; ".join(labels.get(c, c) for c in categories)


def _method_label(value):
    """Human label for an application method, falling back to a de-slugged key."""
    if not value:
        return None
    key = str(value).strip()
    if key in APPLICATION_METHOD_LABELS:
        return APPLICATION_METHOD_LABELS[key]
    return key.replace("_", " ").capitalize()


CHEMICAL_TYPE_LABELS = {
    "FE": "Fertilizer",
    "PE": "Pesticide",
    "FU": "Fungicide",
    "HE": "Herbicide",
}

SOIL_TYPE_LABELS = {
    "ST": "Soil Test",
    "PA": "pH Adjustment",
    "OM": "Organic Matter Addition",
    "CC": "Cover Crop",
    "TI": "Tillage",
    "CO": "Composting",
    "GR": "Grazing Management",
    "HD": "Habitat Development",
    "NS": "Nesting / Shelter Structures",
    "LA": "Lab Analysis",
}

# Humanize SoilManagementEvent.habitat_type (HD / NS subtypes) for the Biodiversity & Habitat
# Records sub-table. Mirrors the frontend HABITAT_TYPES enum (soilEvent.ts); unknown values fall through.
HABITAT_TYPE_LABELS = {
    # HD — Habitat Development (NRCS conservation practice codes noted for the certifier)
    "hedgerow": "Hedgerow (NRCS 422)",
    "insectary_strip": "Insectary / Beneficial-Insect Strip",
    "native_planting": "Native Planting",
    "pollinator_habitat": "Pollinator Habitat (NRCS 327)",
    "field_border": "Field Border (NRCS 386)",
    "riparian_buffer": "Riparian Buffer (NRCS 391)",
    "living_groundcover_habitat": "Living Groundcover Habitat",
    "wildlife_corridor": "Wildlife Corridor",
    # NS — Nesting / Shelter structures
    "barn_owl_box": "Barn-Owl Box",
    "raptor_perch": "Raptor Perch",
    "songbird_box": "Songbird Box",
    "native_bee_block": "Native-Bee Nest Block",
    "bat_box": "Bat Box",
    "insect_hotel": "Insect Hotel",
    "beetle_bank": "Beetle Bank",
    "brush_pile_hibernacula": "Brush Pile / Hibernacula",
}

# SoilManagementEvent.amendment_type is a free CharField (no model-level choices),
# so get_<field>_display() is unavailable. Mirror the frontend
# AMENDMENT_TYPE_LABELS (soilEvent.ts) so the inspector sees "Quick Lime" instead
# of raw "calcium_oxide". Unknown values fall through to the stored string.
AMENDMENT_TYPE_LABELS = {
    "limestone": "Limestone",
    "dolomite": "Dolomite",
    "calcium_oxide": "Quick Lime",
    "calcium_hydroxide": "Hydrated Lime",
    "gypsum": "Gypsum",
    "compost": "Compost",
    "manure": "Manure",
    "other": "Other Amendment",
}

# Humanize SoilManagementEvent.grazing_purpose for the Grazing Management Records sub-table.
# Mirrors the frontend grazing_purpose choices (soilEvent.ts); unknown values fall through.
GRAZING_PURPOSE_LABELS = {
    "weed_control": "Weed Control",
    "cover_crop": "Cover Crop Termination",
    "soil_health": "Soil Health",
    "vegetation_management": "Vegetation Management",
}


def _amendment_type_label(value, fallback="\u2014"):
    """Humanize amendment_type for PDF/CSV display; fall back to stored value.

    Matches `_val()` semantics: returns the em-dash fallback when the stored
    value is empty/None so CSV cells and PDF cells render consistently.
    Callers inside `_cell()` may override with fallback="" — `_cell()` will
    substitute an em-dash on its own.
    """
    if value is None or value == "":
        return fallback
    return AMENDMENT_TYPE_LABELS.get(value, value)


PEST_TYPE_LABELS = {
    "SC": "Scouting",
    "BR": "Beneficial Release",
    "TM": "Trap Monitoring",
    "PI": "Pest Identification",
    "TA": "Threshold Assessment",
    "IP": "IPM Implementation",
    "CU": "Cultural / Sanitation Control",
}

#: Pest-event types that are OBSERVATION, not intervention: scouting, trap monitoring,
#: identifying what is in the orchard, and deciding whether a threshold has been crossed.
#:
#: § 205.206(a) requires cultural, mechanical and biological practices BEFORE resorting to a
#: pest-control substance. That duty attaches to an intervention. Asking a trap-count record
#: which IPM strategy it implemented is asking the wrong question of the right record — and
#: it put "[WARNING] 3 pest event(s) missing IPM strategy" on a packet whose three events
#: were one sanitation practice (which IS the preventive practice) and two monitoring
#: records. Amber is for something the grower can do; there is nothing to do here.
PEST_MONITORING_TYPES = frozenset({"SC", "TM", "PI", "TA"})

# §E-4 — preventive cultural practices (7 CFR 205.206(a)). Mirrors
# PestManagementEvent.CULTURAL_PRACTICE_CHOICES.
CULTURAL_PRACTICE_LABELS = {
    "mummy_removal": "Mummy nut removal (hand poling)",
    "sanitation_shake": "Sanitation shake",
    "brush_shred": "Brush / mummy shredding",
    "pruning_removal": "Pruning removal and destruction",
    "field_sanitation": "Field sanitation / debris removal",
    "trap_crop": "Trap crop",
}

EQUIPMENT_TYPE_LABELS = {
    "MN": "Maintenance",
    "RE": "Repair",
    "CA": "Calibration",
    "FC": "Fuel Consumption",
    "BD": "Breakdown",
    "EI": "Inspection",
}

WEATHER_TYPE_LABELS = {
    "FR": "Frost",
    "DR": "Drought",
    "HL": "Hailstorm",
    "HT": "High Temperature",
    "TS": "Tropical Storm",
    "HW": "High Winds",
    "HH": "High Humidity",
    "LH": "Low Humidity",
}

# Meteorological magnitudes carried in WeatherEvent.extra_data, grouped by concept.
#
# Two ground truths this table encodes, both of which the exporter previously got wrong:
#
# 1. KEY NAMES. UpdateWeatherEventSerializer writes ``lower_temperature`` (frost),
#    ``precipitation_amount`` (tropical storm) and ``humidity_level`` (high/low humidity).
#    The exporter used to probe ``lowest_temperature`` / ``precipitation`` / ``humidity``,
#    so those three magnitudes NEVER rendered — a frost row showed a blank where the
#    inspector expected the temperature that triggered the protection measure. Both
#    spellings are listed because historical rows may carry either; WeatherEvent.clean()
#    likewise bounds-checks both.
#
# 2. UNITS. WeatherTab collects wind in km/h and precipitation in mm (labels read
#    "Wind Speed (km/h)" / "Precipitation Amount (mm)"), and WeatherEvent's plausibility
#    bounds are metric to match. The exporter labelled them " mph" and " in", stating the
#    wrong unit on an inspector-facing document. Hail is genuinely inches (see
#    ``hail_size_in`` bound); it has no writer today but legacy rows may carry it.
#
# Each entry is (keys, unit, prefix). Keys within one entry are SPELLINGS OF THE SAME
# measurement, ordered most-specific-first: the first present wins, so a row never prints
# the same reading twice. Distinct measurements get distinct entries — max and min
# temperature are separate, because a heat event and a frost event mean different things
# and an event carrying both must show both.
#
# The prefix disambiguates: two bare temperatures in one cell ("95°F, 28°F") would leave an
# inspector guessing which is which, so they render as "max 95°F" and "min 28°F".
# `unit=None` means "use the event's own temperature unit".
_WEATHER_MAGNITUDE_GROUPS = (
    (("highest_temperature",), None, "max "),
    (("lower_temperature", "lowest_temperature"), None, "min "),
    (("temperature",), None, ""),
    (("wind_speed",), " km/h", ""),
    (("precipitation_amount", "precipitation"), " mm", ""),
    (("humidity_level", "humidity"), "%", ""),
    (("hail_size",), " in", ""),
)


#: GeneralEvent.activity_type is a free CharField whose values come from GeneralTab's select,
#: so the column stores the option VALUE ("training", "precision_ag"). The packet printed that
#: slug verbatim under "Activity Type" until 2026-09-06 — an inspector read "training" and
#: "precision_ag" in a document where every other enum is a sentence. Mirrors
#: GENERAL_ACTIVITY_TYPES in trazo-app/src/config/events/enums.ts; a value with no entry here
#: falls back to a title-cased de-underscored form rather than disappearing.
GENERAL_ACTIVITY_LABELS = {
    "maintenance": "Maintenance",
    "planning": "Planning",
    "training": "Training",
    "documentation": "Documentation",
    "inspection": "Inspection",
    "meeting": "Meeting",
    "community": "Community Engagement",
    "precision_ag": "Precision Agriculture",
    "emergency": "Emergency Response",
    "other": "Other",
}


def _general_activity_label(value):
    """ "training" -> "Training"; an unmapped slug still reads as words, never as a key."""
    if value in (None, ""):
        return None
    key = str(value).strip()
    if key in GENERAL_ACTIVITY_LABELS:
        return GENERAL_ACTIVITY_LABELS[key]
    return key.replace("_", " ").strip().title()


def _temperature_suffix(extra):
    """The unit a stored temperature carries, or a statement that none was recorded.

    Run 7 (R7-13): a missing unit used to default to "C" (the serializer's default), so seeded
    and imported rows holding Fahrenheit printed "30°C" for a frost and "101°C" for a heat
    spike. The serializer writes `temperature_unit` explicitly on every API save, so a row
    without one has no recorded unit, and saying so is the only honest rendering."""
    unit = str((extra or {}).get("temperature_unit") or "").strip().upper() if isinstance(extra, dict) else ""
    if unit in ("F", "C"):
        return f"°{unit}"
    return " (unit not recorded)" if not unit else "°"


def _weather_magnitudes(extra):
    """Return every magnitude recorded for a weather event, formatted with its unit.

    Returns a list so callers can render all of them — a storm with both a wind speed and
    a rainfall total has two numbers an inspector needs, and the previous
    first-match-then-break lost one of them.
    """
    if not isinstance(extra, dict):
        return []

    temp_suffix = _temperature_suffix(extra)

    out = []
    for keys, unit, prefix in _WEATHER_MAGNITUDE_GROUPS:
        for key in keys:
            value = extra.get(key)
            if value not in (None, ""):
                out.append(f"{prefix}{value}{temp_suffix if unit is None else unit}")
                break  # one reading per measurement, not one per spelling
    return out


def _stored_file_sha256(field_file):
    """SHA-256 of a stored file; "" when none is recorded; None when one is recorded but cannot be
    read (a missing blob or a storage outage), so callers never call an unreadable copy absent."""
    if not field_file:
        return ""
    try:
        field_file.open("rb")
        try:
            digest = hashlib.sha256()
            for chunk in field_file.chunks():
                digest.update(chunk)
            return digest.hexdigest()
        finally:
            field_file.close()
    except Exception:  # noqa: BLE001 — a missing blob must not take the dossier down
        logger.warning("Could not hash stored file %s", getattr(field_file, "name", ""), exc_info=True)
        return None


def _retention_detail(scope, retained):
    """The retention row's detail: the calculated date, and only the enforcement Trazo performs.

    Run 7 (R7-10): "Until" printed finish + 5 years beside a promise of five years from creation,
    and an open season printed nothing. The stored date is now the floor (`retention_floor`), an
    open season shows its calculated floor, and the text says which seasons Trazo protects."""
    from history.retention import retention_floor

    parts = []
    if retained:
        earliest = min(p.retention_until for p in retained)
        latest = max(p.retention_until for p in retained)
        # The earliest date is the one true of every season in scope; enforcement is per season
        # (review of #113).
        text = (
            f"Kept until at least {earliest}: five years after each season finished or after its newest "
            "record was created, whichever is later. Deletion of a season is refused before its date"
        )
        text += f" (dates run to {latest})." if latest != earliest else "."
        parts.append(text)
    running = [p for p in scope if p not in retained]
    if running:
        floors = [f for f in (retention_floor(p) for p in running) if f is not None]
        line = f"{len(running)} season(s) still running"
        if floors:
            line += f": calculated date at least {max(floors)} so far"
        line += "; not deletion-protected by Trazo until finished."
        parts.append(line)
    return " ".join(parts) or "No records yet."


def _held_content_hash_note(filing) -> str | None:
    """The hash of the content this database holds, kept apart from the hash that was signed.

    The signed hash is signing evidence: it is printed as recorded and never recomputed into
    agreement. The summary rows above are read from the database, so when what the database
    holds no longer hashes to the signed value the reader is told the summary is not shown to
    be the signed content, and the filed document is the record (run 7c, R7-02).
    """
    if not filing.signed_content_sha256:
        return None
    held = filing.content_sha256()
    if held == filing.signed_content_sha256:
        return "sha256 matches the signed content hash"
    return (
        f"sha256 {held}, recomputed from this database. It differs from the signed content hash, "
        "so the summary above is read from the database and is not shown to be the signed "
        "content; the filed document is the record"
    )


def _revision_state(rev):
    """One annual-update revision as "revision N: <state> <date>" for a list of the year's revisions."""
    if rev.withdrawn_at:
        state = f"withdrawn {_fmt_date(rev.withdrawn_at)}"
    elif rev.superseded_at:
        state = f"superseded {_fmt_date(rev.superseded_at)}"
    elif rev.submitted_at:
        state = f"filed {_fmt_date(rev.submitted_at)}"
    else:
        state = "not filed"
    return f"revision {rev.revision_number}: {state}"


_COMPOST_NO_MANURE = (
    "no manure",
    "manure-free",
    "manure free",
    "without manure",
    "plant material only",
    "plant-only",
    "plant only",
)
_COMPOST_MANURE = ("manure", "poultry litter", "chicken litter", "guano", "dung")


def _compost_feedstock_kind(ev):
    """ "manure", "plant_only", "not_stated" (feedstock recorded, manure neither named nor
    excluded) or "not_recorded"."""
    text = (getattr(ev, "compost_feedstock", None) or "").strip().lower()
    if not text:
        return "not_recorded"
    excluded = any(phrase in text for phrase in _COMPOST_NO_MANURE)
    # The exclusion phrases themselves contain "manure"; look for a manure word outside them.
    remainder = text
    for phrase in _COMPOST_NO_MANURE:
        remainder = remainder.replace(phrase, " ")
    named = any(word in remainder for word in _COMPOST_MANURE)
    if excluded and named:
        # "plant material only, plus chicken litter": contradictory, so not established
        # (review of #112: the exclusion used to win and the row fell back to N/A).
        return "not_stated"
    if named:
        return "manure"
    if excluded:
        return "plant_only"
    return "not_stated"


def _compost_cn_is_initial(ev):
    """True when the recorded C:N is the starting mix of the operation's own pile.

    Trazo stores one C:N field, labelled initial. For a purchased compost the operator may have
    copied the finished-product analysis into it, and the record does not say which, so only an
    on-farm pile (type CO, no product or supplier named) is read as an initial C:N."""
    purchased = (getattr(ev, "amendment_product_name", None) or "").strip() or (
        getattr(ev, "amendment_supplier_name", None) or ""
    ).strip()
    return ev.type == "CO" and not purchased


def _compost_out_of_range_assessment(ev, harvest_dates, rule_days):
    """(branch, sentence) for a compost record whose C:N is outside § 205.203(c)(2)(i)'s 25:1-40:1.

    Run 7 (R7-09): every such record was declared "handled as raw manure", and the raw-manure row
    then printed "N/A". Plant-only material is never raw manure; manure content or the C:N basis
    that is not established leaves the interval assessment unresolved, naming what is missing.
    """
    cn = float(ev.compost_initial_cn_ratio)
    label = f"{_fmt_date(ev.date)} {(ev.amendment_product_name or '').strip() or 'on-farm compost'}"
    kind = _compost_feedstock_kind(ev)
    if kind == "plant_only":
        return (
            "plant_only",
            f"{label}: C:N {cn:g}:1 is outside 25:1-40:1, so the compost pathway is not met as recorded. The "
            "feedstock is recorded as plant material only, so it is not raw manure (uncomposted plant "
            "material is § 205.203(c)(3)).",
        )
    missing = []
    if kind == "not_recorded":
        missing.append("the feedstock")
    elif kind == "not_stated":
        missing.append("whether the feedstock contained manure")
    if not _compost_cn_is_initial(ev):
        missing.append(
            "whether the C:N is the starting mix or a finished-product analysis (supplier documentation of "
            "the composting process)"
        )
    if missing:
        return (
            "unresolved",
            f"{label}: C:N {cn:g}:1 is outside 25:1-40:1. Manure interval assessment unresolved; missing: "
            + "; ".join(missing)
            + ".",
        )
    later = sorted(d for d in harvest_dates if d >= ev.date.date())
    lead = (
        f"{label}: manure-containing feedstock with initial C:N {cn:g}:1, outside 25:1-40:1, so the compost "
        f"pathway is not met as recorded and the § 205.203(c)(1) interval applies ({rule_days} days for this crop)"
    )
    if not later:
        return ("manure_no_interval", lead + "; interval not recorded (no harvest recorded after the application).")
    days = (later[0] - ev.date.date()).days
    return ("manure_interval", lead + f"; recorded application to first harvest: {days} days.")


@dataclass
class PurchaseLine:
    """One purchase as an application record carries it. Trazo has no purchase model: every
    chemical and amendment event repeats the purchase fields of the bag it came from."""

    product: str
    type_label: str
    supplier: str
    invoice: str
    lot: str
    purchase_date: object
    quantity: float
    unit: str
    applied_on: object


@dataclass
class PurchaseRow:
    """A row of the purchase table: one purchase line, or several identical ones counted once."""

    state: str  # "grouped" | "single" | "no_identifier" | "unresolved"
    lines: list

    @property
    def first(self):
        return self.lines[0]


def _purchase_rows(chemical_events, soil_events):
    """The purchase table's rows and totals (run 7, R7-06; run 1, T07).

    Summing `quantity_purchased` over every application counted one 128 oz invoice twice when two
    sprays came from it. A lot number never identifies a purchase on its own and one invoice can
    hold several lines, so lines are grouped only when product, supplier, invoice, lot, purchase
    date, quantity and unit all match, and the grouping is labelled provisional: Trazo holds no
    purchase-line identifier. Lines of one product that share an invoice or a lot but differ in
    any other detail are unresolved: each is kept, none is merged, and their quantity is reported
    beside the total, never silently left out of it. Units are never summed together.

    Returns (rows, totals) where totals maps unit to {"counted", "unresolved_qty",
    "unresolved_lines", "provisional"}.
    """

    def _s(value):
        return (str(value).strip() if value is not None else "") or ""

    lines = []
    for ev in chemical_events:
        if ev.quantity_purchased is None:
            continue
        lines.append(
            PurchaseLine(
                product=_s(ev.commercial_name),
                type_label=CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                supplier=_s(ev.supplier_name),
                invoice=_s(ev.purchase_invoice),
                lot=_s(ev.chemical_lot_number),
                purchase_date=ev.purchase_date,
                quantity=float(ev.quantity_purchased),
                unit=_val(ev.quantity_purchased_unit, "units"),
                applied_on=ev.date,
            )
        )
    for ev in soil_events:
        qty = getattr(ev, "amendment_quantity_purchased", None)
        if qty is None:
            continue
        lines.append(
            PurchaseLine(
                product=_s(ev.amendment_product_name) or _amendment_type_label(ev.amendment_type),
                type_label=SOIL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                supplier=_s(getattr(ev, "amendment_supplier_name", None)),
                invoice=_s(getattr(ev, "amendment_purchase_invoice", None)),
                lot=_s(getattr(ev, "amendment_lot_number", None)),
                purchase_date=getattr(ev, "amendment_purchase_date", None),
                quantity=float(qty),
                unit=_val(getattr(ev, "amendment_quantity_purchased_unit", None), "units"),
                applied_on=ev.date,
            )
        )

    def _norm(text):
        return " ".join(text.lower().split())

    keyed, rows = {}, []
    for ln in lines:
        if not (ln.invoice or ln.lot):
            rows.append(PurchaseRow("no_identifier", [ln]))
            continue
        # Identifiers are free text: case and spacing are not a different invoice (review of #112).
        key = (
            _norm(ln.product),
            _norm(ln.supplier),
            _norm(ln.invoice),
            _norm(ln.lot),
            ln.purchase_date,
            ln.quantity,
            _norm(ln.unit),
        )
        keyed.setdefault(key, []).append(ln)

    # Groups of one product that share an invoice or a lot but differ elsewhere conflict.
    groups = list(keyed.items())
    conflicted = set()
    for i, (key_a, _) in enumerate(groups):
        for key_b, _ in groups[i + 1 :]:
            same_product = key_a[0] == key_b[0]
            shares = (key_a[2] and key_a[2] == key_b[2]) or (key_a[3] and key_a[3] == key_b[3])
            if same_product and shares:
                conflicted.update({key_a, key_b})
    for key, group in groups:
        if key in conflicted:
            # One row per distinct purchase details, its identical lines kept together: a proven
            # duplicate pair is not split again because another line conflicts (review of #112).
            rows.append(PurchaseRow("unresolved", group))
        else:
            rows.append(PurchaseRow("grouped" if len(group) > 1 else "single", group))

    rows.sort(key=lambda r: (str(r.first.purchase_date or r.first.applied_on or ""), r.first.product.lower()))

    totals = {}
    for row in rows:
        t = totals.setdefault(
            row.first.unit, {"counted": 0.0, "unresolved_qty": 0.0, "unresolved_lines": 0, "provisional": False}
        )
        if row.state == "unresolved":
            t["unresolved_qty"] += row.first.quantity
            t["unresolved_lines"] += 1
        else:
            t["counted"] += row.first.quantity
            if row.state == "grouped":
                t["provisional"] = True
    return rows, totals


def _purchase_row_note(row):
    """What a purchase row's Product cell adds after the product name."""
    if row.state == "grouped":
        dates = ", ".join(_fmt_date(ln.applied_on) for ln in row.lines)
        return (
            f" (carried by {len(row.lines)} applications: {dates}; counted once, provisional grouping: "
            "Trazo holds no purchase-line identifier)"
        )
    if row.state == "unresolved":
        carried = f"carried by {len(row.lines)} applications; " if len(row.lines) > 1 else ""
        return (
            f" ({carried}unresolved: same invoice or lot as another line of this product with different details; "
            "not in the total)"
        )
    if row.state == "no_identifier":
        return " (no invoice or lot recorded)"
    return ""


def _purchase_total_text(total, unit):
    if not total["counted"] and total["unresolved_lines"]:
        # A bare 0.00 would read as a definitive total of nothing.
        text = "no line counted"
    else:
        text = _fmt_float(total["counted"])
    if total["provisional"]:
        text += " (provisional: identical purchase details carried by several applications counted once)"
    if total["unresolved_lines"]:
        text += (
            f"; {total['unresolved_lines']} unresolved line(s) totalling {_fmt_float(total['unresolved_qty'])} "
            f"{unit} are not included"
        )
    return text


def _osp_status_label(osp):
    """The plan's status without claiming an approval Trazo has no record of (run 7, R7-02b).

    The model's choice label for `active` is "Active / Approved", which printed beside a blank
    approval date. Approval is stated only from `approved_at`."""
    if osp.status == "active":
        if osp.approved_at:
            return f"Active, approved {_fmt_date(osp.approved_at)}"
        return "Active (approval date not recorded in Trazo)"
    return osp.get_status_display()


def _fmt_date(dt):
    """Format a datetime or date as YYYY-MM-DD; return dash if None."""
    if dt is None:
        return "\u2014"
    if hasattr(dt, "date"):
        return dt.date().isoformat()
    if isinstance(dt, date):
        return dt.isoformat()
    return str(dt)


def _fmt_generated_date():
    """The report's generation date, explicitly labelled UTC.

    `django.setup()` forces the process timezone to settings.TIME_ZONE ("UTC"),
    so `date.today()` is the UTC date \u2014 NOT the farm's. A Ventura grower
    exporting at 18:00 on 15 October got a dossier stamped 16 October, a day
    that had not started for them, on a document a certifier date-stamps
    against a deadline.

    We do not store a per-establishment timezone, so inventing a local date
    would be guessing. Naming the zone removes the ambiguity instead: a
    certifier reading "2026-08-04 (UTC)" cannot be misled about which day is
    meant. If per-farm timezones are ever modelled, render the farm's local
    date here and drop the suffix.
    """
    return f"{date.today().isoformat()} (UTC)"


def _fmt_float(value, decimals=2):
    """Format a numeric value with fixed decimals; return dash if None."""
    if value is None:
        return "\u2014"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------------------
# Table column widths (inches * inch).
#
# Module-level ON PURPOSE. These were inline literals inside their render methods, and the
# comment beside one of them claimed "test_audit_pdf_column_fit.py holds this true" — a file
# that has never existed. With nothing able to reach the numbers, two tables silently drifted
# below the width of their own identifiers and split "YAS-2025-4417" across lines.
#
# The rule, unchanged: a column carrying an ATOMIC token (a date, an invoice number, a lot
# code, an EPA registration) must be at least `stringWidth(token) + 6pt padding`, because
# ReportLab splits a long unbroken token mid-value rather than overflowing. Columns carrying
# prose (product names, supplier names, target pests) are meant to wrap and get the leftovers.
#
# Frame width is 7.00in (letter less 0.75in margins). test_audit_pdf_column_fit.py now
# enforces both halves: every list fits the frame, and every identifier column fits its token.
# ---------------------------------------------------------------------------------------

#: Mass-Balance "Inputs Purchased" table.
MASS_BALANCE_PURCHASE_WIDTHS = [
    0.62 * inch,  # Date          — "2025-03-23"
    1.20 * inch,  # Product       — wraps on word boundaries
    0.62 * inch,  # Type          — "Fertilizer"
    1.10 * inch,  # Supplier      — wraps on word boundaries
    0.80 * inch,  # Invoice #     — "YAS-2025-4417", must not split
    0.78 * inch,  # Lot #         — "NH2025-04127", must not split
    0.78 * inch,  # Qty Purchased — header is the widest token
    0.50 * inch,  # Unit          — "gal"
]

#: "Input Purchase Traceability" table, California variant (carries the CA DPR column).
INPUT_TRACEABILITY_WIDTHS_CA = [
    0.60 * inch,  # Date Applied  — "2025-03-23" = 0.50in
    0.70 * inch,  # Product       — wraps on word boundaries
    0.75 * inch,  # Supplier      — wraps on word boundaries
    0.60 * inch,  # Purchase Date — "2025-03-10" = 0.50in
    0.78 * inch,  # Invoice #     — "YAS-2025-4417" = 0.69in, must not split
    0.75 * inch,  # Lot #         — "NH2025-04127" = 0.66in, must not split
    0.62 * inch,  # Qty Purchased — header "Purchased" is 0.52in in BOLD, not 0.47in
    0.62 * inch,  # Applicator    — header word is 0.50in in bold; values wrap below it
    0.55 * inch,  # Cert #
    0.60 * inch,  # CA DPR Permit
]

#: Same table for a non-California operation — ONLY the DPR column is dropped.
#:
#: 🔴 This list had EIGHT entries against NINE headers until 2026-08-18. The header builder
#: always appended "Cert #" and added "CA DPR Permit" on top of it for California, so the
#: non-CA table handed ReportLab nine columns and eight widths. Kept in lockstep with the CA
#: list below (CA == this + "CA DPR Permit") so the two can no longer disagree.
INPUT_TRACEABILITY_WIDTHS_NON_CA = [
    0.60 * inch,  # Date Applied  — "2025-03-23" = 0.50in
    1.10 * inch,  # Product       — wraps on word boundaries
    1.10 * inch,  # Supplier      — wraps on word boundaries
    0.60 * inch,  # Purchase Date
    0.78 * inch,  # Invoice #     — must not split
    0.75 * inch,  # Lot #         — must not split
    0.62 * inch,  # Qty Purchased — header "Purchased" is 0.52in in BOLD
    0.62 * inch,  # Applicator    — header word is 0.50in in bold
    0.55 * inch,  # Cert #
]

#: Header row for each width list, in column order. Kept beside the widths because HEADERS
#: render in Helvetica-BOLD, which is wider than the 7pt regular used for values — sizing a
#: column from a regular-weight measurement (as "Qty Purchased" and "Applicator" briefly were)
#: leaves the header itself wrapping, the same "Pestici / de" defect recorded above.
#: "Production Events (Common OSP G6.0 / G6.1)" table — the carbon-in-scope variant, which
#: carries two extra columns. Both variants budget 6.90in inside the 7.00in frame.
#:
#: 🔴 2026-08-19 — Date was 0.55in here, which is 39.6pt against a 35.8pt date plus 6pt of
#: cell padding. ReportLab does not overflow: it SPLIT every row, printing "2026-02-0" over
#: "4". Same defect the invoice and lot columns had, in the one column an inspector uses to
#: line this table up against every other record in the packet. The 0.07in came off
#: Description, which is prose and wraps by design.
PRODUCTION_EVENT_WIDTHS_CARBON = [
    0.62 * inch,  # Date          — "2026-02-04"
    0.95 * inch,  # Type (+ growth stage)
    1.63 * inch,  # Description   — prose, wraps
    0.85 * inch,  # Method
    0.60 * inch,  # Area Covered
    0.50 * inch,  # Block
    0.55 * inch,  # Fuel Used
    0.50 * inch,  # Equip. Hours
    0.70 * inch,  # Operator
]

#: Same table without the carbon columns — Description absorbs the 1.05in they free.
PRODUCTION_EVENT_WIDTHS_PLAIN = [
    0.62 * inch,  # Date
    0.95 * inch,  # Type (+ growth stage)
    2.68 * inch,  # Description   — prose, wraps
    0.85 * inch,  # Method
    0.60 * inch,  # Area Covered
    0.50 * inch,  # Block
    0.70 * inch,  # Operator
]

#: "Harvest & Transport Records" analytics table. Twelve columns, 7.00in exactly.
#: Date was 0.58in = 41.76pt against the 41.8pt an ISO date needs with padding — under by
#: four hundredths of a point, which is still a split. The 0.04in came off Method.
#: 🔴 Rebalanced 2026-08-19 once the guard could see this list. Three columns were under
#: their own contents at once: Lot needed 1.164in and had 0.920in — the comment above it had
#: claimed since 2026-08-17 that "Lot keeps the widest cell ... a wrapped lot code is a
#: misread lot code", which is exactly what it was doing — and the "Determined By" and
#: "Destination" HEADERS were wrapping. Twelve columns do not fit at those widths, so
#: "Determined By" became "Yield Basis" (same fact, narrower header word) and every column
#: was cut to its own measured minimum plus slack. 6.90in of a 7.00in frame.
HARVEST_ANALYTICS_WIDTHS = [
    0.60 * inch,  # Date          — "2026-02-04" needs 0.581in; a harvest RANGE wraps by design
    1.17 * inch,  # Lot           — "HAS-BLOCK2-20260410" needs 1.164in, must not split
    0.45 * inch,  # Block
    0.45 * inch,  # Variety
    0.50 * inch,  # Yield
    # "Scale-Verified" is one token needing 0.688in and printed as "Scale-V" / "erified" at
    # 0.45in — the § 205.103(b)(2) accuracy basis, split into two words that are not words.
    0.70 * inch,  # Yield Basis
    0.45 * inch,  # Quality Grade
    0.50 * inch,  # Method
    0.52 * inch,  # Brix / Moisture
    0.62 * inch,  # Destination   — bold header word needs 0.613in; values wrap
    0.50 * inch,  # Storage
    0.51 * inch,  # Operator
]

#: "Pest Management (Common OSP G5.0)" table. Eleven columns, 7.00in.
#:
#: 🔴 2026-08-19 — Type was 0.52in while the vocabulary it renders contains "Identification"
#: (0.63in), "Assessment" (0.61in) and "Implementation" (0.75in), so a live packet printed
#: "Pest Iden / tification" and "Threshold Assessm / ent". A column whose contents come from
#: a FIXED vocabulary can be sized exactly — there is no excuse for guessing — and
#: test_audit_pdf_column_fit.py now sizes it against every label in PEST_TYPE_LABELS.
#: The 0.24in came off the three prose columns, which wrap on word boundaries by design.
PEST_EVENT_WIDTHS = [
    0.70 * inch,  # Date
    0.76 * inch,  # Type            — widest label word "Implementation" needs 0.748in
    0.79 * inch,  # Pest Species    — prose, wraps
    0.65 * inch,  # Crop Stage
    0.68 * inch,  # Identified By
    0.50 * inch,  # Pressure
    0.50 * inch,  # Damage %
    0.50 * inch,  # Area
    0.45 * inch,  # Block
    0.75 * inch,  # IPM Strategy    — prose, wraps
    0.72 * inch,  # Beneficial / Qty — prose, wraps
]

TABLE_HEADERS = {
    "MASS_BALANCE_PURCHASE_WIDTHS": [
        "Purchase Date",
        "Product",
        "Type",
        "Supplier",
        "Invoice #",
        "Lot #",
        "Qty Purchased",
        "Unit",
    ],
    "INPUT_TRACEABILITY_WIDTHS_CA": [
        "Date Applied",
        "Product",
        "Supplier",
        "Purchase Date",
        "Invoice #",
        "Lot #",
        "Qty Purchased",
        "Applicator",
        "Cert #",
        "CA DPR Permit",
    ],
    "INPUT_TRACEABILITY_WIDTHS_NON_CA": [
        "Date Applied",
        "Product",
        "Supplier",
        "Purchase Date",
        "Invoice #",
        "Lot #",
        "Qty Purchased",
        "Applicator",
        "Cert #",
    ],
    "PRODUCTION_EVENT_WIDTHS_CARBON": [
        "Date",
        "Type",
        "Description",
        "Method",
        "Area Covered",
        "Block",
        "Fuel Used",
        "Equip. Hours",
        "Operator",
    ],
    "PRODUCTION_EVENT_WIDTHS_PLAIN": [
        "Date",
        "Type",
        "Description",
        "Method",
        "Area Covered",
        "Block",
        "Operator",
    ],
    "PEST_EVENT_WIDTHS": [
        "Date",
        "Type",
        "Pest Species",
        "Crop Stage",
        "Identified By",
        "Pressure",
        "Damage %",
        "Area",
        "Block",
        "IPM Strategy",
        "Beneficial / Qty",
    ],
    "HARVEST_ANALYTICS_WIDTHS": [
        "Date",
        "Lot",
        "Block",
        "Variety",
        "Yield",
        "Yield Basis",
        "Quality Grade",
        "Method",
        "Brix / Moisture",
        "Destination",
        "Storage",
        "Operator",
    ],
}

#: Index of every column in the lists above that carries an ATOMIC identifier, i.e. one that
#: must never be split. Keyed by constant name so the guard reports which column failed.
IDENTIFIER_COLUMNS = {
    "MASS_BALANCE_PURCHASE_WIDTHS": {0: "Purchase Date", 4: "Invoice #", 5: "Lot #"},
    "INPUT_TRACEABILITY_WIDTHS_CA": {0: "Date Applied", 3: "Purchase Date", 4: "Invoice #", 5: "Lot #"},
    "INPUT_TRACEABILITY_WIDTHS_NON_CA": {0: "Date Applied", 3: "Purchase Date", 4: "Invoice #", 5: "Lot #"},
    "PRODUCTION_EVENT_WIDTHS_CARBON": {0: "Date"},
    "PRODUCTION_EVENT_WIDTHS_PLAIN": {0: "Date"},
    "HARVEST_ANALYTICS_WIDTHS": {0: "Date", 1: "Lot"},
    "PEST_EVENT_WIDTHS": {0: "Date"},
}


def _fmt_qty(value):
    """Quantity for a table cell: grouped, and only as many decimals as the value needs.

    52500 -> "52,500"; 52500.5 -> "52,500.5". Matches how `_fmt_mass` renders the same
    number in the Output Reconciliation block, so the two cannot look like different figures.
    """
    if value is None or str(value).strip() == "":
        return "\u2014"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _fmt_mass(value, unit):
    """
    Format a harvest / sales mass for a US audit reader. US growers, CCOF, and
    wholesale buyers think in pounds (and tons), so pounds are the primary figure
    \u2014 with short tons added when the quantity is large, and the recorded metric
    value kept in brackets so the source record stays auditable. Pounds pass
    through unchanged; an unrecognized / non-mass unit is shown as recorded
    (never guessed).
    """
    if value is None:
        return "\u2014"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _val(value)
    u = (unit or "").strip().lower()
    if u in ("kg", "kgs", "kilogram", "kilograms"):
        lbs = v * 2.20462
    elif u in ("lb", "lbs", "pound", "pounds"):
        lbs = v
    else:
        # Unknown / non-mass unit (boxes, cartons, units\u2026): show as recorded.
        return f"{_fmt_float(v)} {unit}".strip() if unit else _fmt_float(v)
    if abs(lbs) >= 4000:  # >= ~2 short tons: tons aid readability
        primary = f"{lbs:,.0f} lb ({lbs / 2000.0:,.1f} short tons)"
    else:
        primary = f"{lbs:,.0f} lb"
    # Keep the recorded metric value visible for audit fidelity when source was kg.
    # The ".2f" guarantees a decimal point, so stripping trailing zeros is safe and
    # preserves real fractional values (2.5 -> "2.5", 180000.00 -> "180,000").
    if u in ("kg", "kgs", "kilogram", "kilograms"):
        kg_str = f"{v:,.2f}".rstrip("0").rstrip(".")
        return f"{primary} [{kg_str} kg]"
    return primary


def _last_prohibited_input(entry):
    """USDA's "Name and Application Date of Last Prohibited Input", from one ParcelCropHistory row.

    Both halves matter and either can stand alone: a name with no date cannot be checked
    against the 36-month window, and a date with no name cannot be checked against the
    National List. Returns a dash when neither is recorded \u2014 deliberately NOT "none applied",
    which would be an attestation nobody made.
    """
    name = (getattr(entry, "last_prohibited_substance", "") or "").strip()
    date = _fmt_date(entry.date_last_prohibited) if entry.date_last_prohibited else ""
    if name and date:
        return f"{name} \u2014 {date}"
    return name or date or "\u2014"


def _esc(value, fallback="\u2014"):
    """`_val`, plus the XML escaping any raw `Paragraph(f"...{user_text}...")` needs.

    ReportLab Paragraphs parse a mini-HTML dialect, so interpolating farmer free text into
    one is not cosmetic \u2014 it is a correctness and availability bug. Measured 2026-08-12 on
    the buffer detail lines:

        "Walnuts & almonds <north lot>"  -> renders as "Walnuts & almonds", the operator's
                                           own text SILENTLY DESTROYED in a document whose
                                           entire purpose is to record it
        "Bob & Sons <b>bold"             -> ValueError, the whole certifier packet fails
                                           to generate

    `_cell` already escapes, so table cells were never exposed; only the hand-built
    Paragraph lines were. Use this for those.
    """
    text = glyph_safe(_val(value, fallback))
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _val(value, fallback="\u2014"):
    """Return value as string if truthy, else the fallback dash."""
    if value is None or value == "":
        return fallback
    return str(value)


def _humanize_enum(raw):
    """Turn a SLUG into a label, and leave anything the operator typed exactly as typed.

    🔴 2026-08-20, raised independently by two certifier reviewers. `harvest_quality_grade` is
    free text, and the packet ran `.title()` over it — so "WA Extra Fancy" printed as
    "Wa Extra Fancy" and "US No. 1" as "Us No. 1". Neither is a grade. A reviewer checking a
    lot against a packing record looks the grade up in a controlled vocabulary, and a
    silently re-cased abbreviation does not match it.

    `.title()` is right for a slug (`shake_and_catch` → "Shake and Catch") and wrong for
    everything else: it lowercases every acronym a US agricultural record is full of — WA, US,
    NOP, OMRI, CCOF, DPR. The test is therefore the SHAPE of the value, not the field it came
    from. A slug here means underscore-separated and already lowercase; anything with a
    capital in it is a human's writing and is reproduced verbatim.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # The slug signature is "no capital anywhere" — `manual`, `shake_and_catch`,
    # `cover_cropping`. Underscores are not required: plenty of single-word enum values
    # carry none. Anything holding a capital was typed by a person (or is an acronym), and
    # is reproduced exactly.
    if text == text.lower():
        return text.replace("_", " ").title()
    return text


def _organic_basis_label(raw):
    """The verification basis for an input, or None when nothing was recorded.

    🔴 2026-08-19 — `amendment_organic_approved` / `organic_approved` are CharFields with
    `choices`, and Django does not enforce choices on `.save()`. A management command, an
    importer or a data-repair script can put anything there, and Django's own
    `get_..._display()` falls through to the RAW VALUE when it does not recognise it. A live
    packet printed "Organic Status: True" — a Python boolean stringified by a seeding script,
    rendered in the column an inspector reads as the § 205.203(b) / § 205.601 verification
    basis. "True" is not a basis; it asserts approval while naming no listing, no seal and no
    certifier.

    So the label comes from the enum or not at all. An unrecognised value is reported as
    unspecified WITH the raw value disclosed — discarding what the operator's record actually
    holds would be its own kind of lie.
    """
    value = str(raw).strip() if raw is not None else ""
    if not value:
        return None
    for choice_value, choice_label in ORGANIC_APPROVED:
        if value == choice_value:
            return choice_label
    return f'NOT SPECIFIED (recorded as "{value}" — not a recognised verification basis)'


#: Dropdown values that name a THIRD PARTY as the basis. Selecting one is the grower saying
#: where they believe the approval comes from; it is not the listing itself.
_THIRD_PARTY_BASIS_VALUES = frozenset(
    {"omri_listed", "wsda_listed", "nop_seal_on_label", "certifier_approved", "usda_nop_approved"}
)


#: Sentinel for "caller did not name a field", distinct from "the field holds None". Without
#: it, passing an amendment's NULL `amendment_organic_approved` would silently fall through to
#: `event.organic_approved` — a different field, with a different meaning, on any model that
#: happens to have both. SoilManagementEvent has no `organic_approved` today, so this is a
#: latent trap rather than a live bug; the sentinel closes it before someone adds one.
_UNSET = object()


def _organic_basis_cell(event, raw=_UNSET):
    """The Input Log's Organic Status cell, with the EVIDENCE behind it.

    🔴 2026-08-20, found by two certifier reviewers reading the generated packet
    independently. The Input Application Log printed a flat "OMRI Listed" on every row, taken
    straight from the grower's dropdown, while the OMRI / National List Verification table on
    the facing page gave the same products "OMRI ID: —", "Status: Self-reported" and a note
    saying they "remain UNCLASSIFIED". Both reviewers led with it: one table asserts a
    third-party listing, the next denies it, and the reviewer cannot tell which the packet
    means.

    OMRI and WSDA run real listing programmes, so an unbacked "OMRI Listed" is not vague
    puffery — it is an unearned certification-mark claim, the same defect `claim_authority`
    was built to end on the consumer page in 2026-08-09. It reached this surface because the
    fix landed on the chip and never on its sibling.

    The certifier packet's answer is not to HIDE the grower's selection — a reviewer needs to
    know what the operator believes and recorded. It is to attribute it: print the selection
    and, where it names a third party Trazo cannot corroborate, say so in the same cell.
    """
    raw_value = getattr(event, "organic_approved", None) if raw is _UNSET else raw
    label = _organic_basis_label(raw_value)
    if label is None:
        return None
    if str(raw_value).strip() == "yes":
        # Run 7 (R7-04): the legacy "Yes - Organic Approved" names no listing, seal or certifier,
        # and printed bare beside qualified OMRI and certifier selections.
        return f"{label} — grower-selected, basis not recorded"
    if str(raw_value).strip() not in _THIRD_PARTY_BASIS_VALUES:
        return label
    # Either catalogue backs the claim. WSDA added 2026-09-02: `wsda_listed` was already in
    # the set above, so a WSDA basis was claimable and unbackable — it carried the
    # "no listing on file" suffix even when the operator had attached the WSDA row.
    if getattr(event, "omri_product_id", None) or getattr(event, "wsda_material_id", None):
        return label
    return f"{label} — grower-selected, no listing on file"


def _qty_with_unit(value, unit):
    """A measured quantity for a table cell, or None.

    A bare "12.50" under a header reading "Amount" or "Area" is uninterpretable — gal, lb, oz,
    acres, hectares? — and acres vs hectares differ by 2.47x. When the unit was never recorded
    the cell says so, because a reader cannot tell a missing unit from an implied one.
    """
    if value is None or str(value).strip() == "":
        return None
    number = _fmt_float(value)
    unit_text = str(unit or "").strip()
    if unit_text:
        return f"{number} {unit_text}"
    return f"{number} (unit not recorded)"


def _choice_label(instance, field_name):
    """A choice field's LABEL, or the stored value plainly marked as unrecognised.

    🔴 2026-08-20 — Django's `get_FOO_display()` returns the RAW VALUE when the stored string
    is not among the field's choices, and Django enforces choices on neither `.save()` nor a
    DRF write. So an importer, a management command or a hand edit puts `district_canal` in
    `water_source` and the certifier packet prints "district_canal" in the Irrigation Records
    table — machine text in a regulatory document, with no signal that a label went missing.

    Third occurrence of this class in this file: `organic_approved = "True"` printed as a
    § 205.203(b) verification basis, an unrecognised OSP option printed as a chosen answer, and
    now this. Same rule each time: name what is stored, never dress it up as an answer the
    operator chose.
    """
    value = getattr(instance, field_name, None)
    if value in (None, ""):
        return None
    try:
        field = instance._meta.get_field(field_name)
        valid = {c[0] for c in (field.choices or [])}
    except Exception:  # noqa: BLE001 — a display helper must never break the export
        return str(value)
    if not valid or value in valid:
        getter = getattr(instance, f"get_{field_name}_display", None)
        return getter() if getter else str(value)
    return f'"{value}" (unrecognised value — not in the current form)'


def _rate_per_area(amount, area, amount_unit, area_unit):
    """Return "8.00 oz/acre" for an amount applied over an area, or None.

    A label maximum, a manure-loading limit and a nitrogen budget are all written PER UNIT
    AREA, so the rate — not the total — is the number a reviewer checks an application
    against. Both exports used to print only the total and leave the division to the reader.

    Returns None rather than guessing when either side is missing or the area is zero.
    """
    if amount is None or area is None:
        return None
    try:
        amount_d = Decimal(str(amount))
        area_d = Decimal(str(area))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if area_d <= 0:
        return None
    # "acres" -> "acre" so the rate reads "8.00 oz/acre", not "oz/acres".
    area_unit_singular = (str(area_unit or "").strip()).rstrip("s")
    if not area_unit_singular:
        return None
    numerator_unit = str(amount_unit or "").strip()
    # Symmetrical with the area-unit guard above: "12.50 /acre" is a number with no unit and a
    # stray space, in the column a reviewer checks a label maximum against. Say nothing rather
    # than print a rate whose numerator is unnamed. (Reachable since the 2026-08-19 backfill
    # populated volume_numeric on records whose volume_unit was never recorded.)
    if not numerator_unit:
        return None
    # 🔴 2026-08-19 — the amount can ALREADY be a rate. Soil amendments are recorded in
    # "lb/acre" because that is how the bag and the soil report are written, and dividing a
    # rate by an area produced "300.00 lb/acre (142.86 lb/acre/acre)" on a live packet: a
    # unit that does not exist, and a number 143x smaller than the one the operator applied.
    # A rate divided by an area is not a rate — there is nothing to derive, so say nothing.
    if "/" in numerator_unit or "per" in numerator_unit.lower().split():
        return None
    return f"{_fmt_float(amount_d / area_d)} {numerator_unit}/{area_unit_singular}".strip()


#: The rate codes stored on `ChemicalEvent.application_rate_unit`, and the words a certifier
#: reads them in. Read from the model's own choices so the packet cannot print a spelling the
#: form does not offer; an UNRECOGNISED code prints nothing at all rather than raw machine text.
_RATE_UNIT_LABELS = dict(UNIT_APPLICATION_RATE)

#: Unit -> (dimension, size in that dimension's base unit). One table for both halves of the
#: reconciliation below, because the only thing it needs is a ratio.
#:
#: `oz` is LIQUID here, not mass. The volume dropdown's own option reads "Fluid Ounces (oz)"
#: (ChemicalTab-ENHANCED), and `UNIT_APPLICATION_RATE` carries `fl_oz_ac` beside `oz_ac`. Where
#: the two sides use the same token the factor cancels and the reading does not matter; where
#: they differ, guessing mass would be the more damaging half of the ambiguity.
_UNIT_IN_BASE = {
    # Liquid volume, base mL
    "mL": ("volume", Decimal("1")),
    "ml": ("volume", Decimal("1")),
    "L": ("volume", Decimal("1000")),
    "l": ("volume", Decimal("1000")),
    "gal": ("volume", Decimal("3785.411784")),
    "qt": ("volume", Decimal("946.352946")),
    "pt": ("volume", Decimal("473.176473")),
    "oz": ("volume", Decimal("29.5735295625")),
    "fl_oz": ("volume", Decimal("29.5735295625")),
    # Mass, base g
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "lb": ("mass", Decimal("453.59237")),
    "lbs": ("mass", Decimal("453.59237")),
    "ton": ("mass", Decimal("907184.74")),
    "t": ("mass", Decimal("1000000")),
}

#: Area, expressed in the two denominators a rate can be quoted against.
_AREA_IN_ACRES = {
    "acres": Decimal("1"),
    "acre": Decimal("1"),
    "ac": Decimal("1"),
    "ha": Decimal("2.4710538147"),
    "m2": Decimal("0.0002471054"),
    "km2": Decimal("247.10538147"),
}
_ACRES_PER_HECTARE = Decimal("2.4710538147")

#: How far a recorded total may sit from (recorded rate x recorded area) before the packet
#: refuses to present it as the product amount.
#:
#: Deliberately loose. A grower who treated part of a block, rounded a tank, or applied a second
#: partial pass is inside 2x, and a certifier document must not accuse an operation of a
#: discrepancy it did not commit. The failure this exists to catch is not a rounding error: a
#: carrier volume mistaken for a product amount is 50x to 900x out (the Entrust record that
#: prompted this was 71x), because a spray is measured in tank gallons and a product in fluid
#: ounces.
_AMOUNT_RATE_TOLERANCE = Decimal("4")


def _recorded_rate_text(event):
    """The label rate the OPERATOR recorded, in the words of the form's own dropdown, or None.

    🔴 2026-09-03 — `application_rate` became a real column on 2026-09-03 and this packet never
    read it. The Input Application Log printed only a rate DERIVED from total / area, so the one
    number a reviewer checks against a label maximum was Trazo's arithmetic rather than the
    operator's record, and the recorded value appeared nowhere in the document at all.
    """
    value = getattr(event, "application_rate", None)
    code = (getattr(event, "application_rate_unit", "") or "").strip()
    if value in (None, "") or not code:
        return None
    label = _RATE_UNIT_LABELS.get(code)
    if not label:
        # Same rule as `_choice_label`: an unrecognised stored code is machine text, and machine
        # text in a regulatory document is worse than a missing cell.
        return None
    return f"{_fmt_float(value)} {label}"


def _rate_unit_parts(code):
    """`"fl_oz_ac"` -> `("fl_oz", "ac")`, or None when the code is not one this file knows."""
    if code not in _RATE_UNIT_LABELS:
        return None
    numerator, _, denominator = str(code).rpartition("_")
    if not numerator or denominator not in ("ac", "ha"):
        return None
    return numerator, denominator


def _amount_reconciles_with_rate(event):
    """Can the recorded TOTAL and the recorded RATE describe the same application?

    Returns True (they agree), False (they cannot both be true) or None (not enough recorded to
    ask, which is the common case and is never reported as a discrepancy).

    🔴 2026-09-03, found in the wizard's buyer-page preview while filming. The grower said
    "six fluid ounces an acre, 40 gallons total" and the 40 gallons — the TANK, the carrier the
    product was mixed into — landed in `volume_numeric`, which this table prints under
    "Amount / Rate" as the amount of product applied. Six fluid ounces an acre over twelve acres
    is 72 fl oz; 40 gallons is 5,120. The two numbers are on the same row of the same table and
    the packet asserted both.

    § 205.103(b)(2) reconciles what was PURCHASED against what was APPLIED, so the total is the
    number an inspector runs a mass balance on. A carrier volume there is not a rounding error,
    it is a different fact. The voice mapper no longer writes one (`productTotalFromAmounts`);
    this is the half that also holds for a value typed by hand, imported, or already on file.
    """
    total = getattr(event, "volume_numeric", None)
    rate = getattr(event, "application_rate", None)
    area = getattr(event, "area_numeric", None)
    code = (getattr(event, "application_rate_unit", "") or "").strip()
    if total in (None, "") or rate in (None, "") or area in (None, ""):
        return None

    parts = _rate_unit_parts(code)
    if parts is None:
        return None
    numerator, denominator = parts

    total_unit = _UNIT_IN_BASE.get((getattr(event, "volume_unit", "") or "").strip())
    rate_unit = _UNIT_IN_BASE.get(numerator)
    if total_unit is None or rate_unit is None or total_unit[0] != rate_unit[0]:
        # Different dimensions, or a unit this table does not know. We cannot compare, and an
        # unverifiable comparison must not become an accusation.
        return None

    acres = _AREA_IN_ACRES.get((getattr(event, "area_unit", "") or "").strip())
    if acres is None:
        return None

    try:
        area_d = Decimal(str(area)) * acres
        if denominator == "ha":
            area_d = area_d / _ACRES_PER_HECTARE
        expected = Decimal(str(rate)) * rate_unit[1] * area_d
        actual = Decimal(str(total)) * total_unit[1]
    except (InvalidOperation, TypeError, ValueError):
        return None
    if expected <= 0 or actual <= 0:
        return None

    ratio = actual / expected if actual >= expected else expected / actual
    return ratio <= _AMOUNT_RATE_TOLERANCE


# Last-resort ceiling for an uncapped cell. No legitimate audit value approaches this; it
# exists so a corrupt or pathological field cannot render a single row taller than a page.
_RUNAWAY_CELL_CHARS = 2000


# Storage slugs for the units that appear in summary-mode totals, in the words a grower and an
# inspector use. Anything not listed falls through unchanged.
SUMMARY_UNIT_LABELS = {
    "acre_feet": "acre-feet",
    "cubic_meters": "cubic metres",
    "gallons": "gallons",
    "liters": "litres",
    "lbs": "lb",
    "kgs": "kg",
    "tons": "tons",
    "boxes": "boxes",
    "bins": "bins",
}


def _osp_section_date(value):
    """A plain YYYY-MM-DD for the OSP section table, whatever shape the stamp arrived in.

    🔴 2026-08-19: `last_updated` has two authors — the module compiler writes a full ISO-8601
    datetime, the section editor writes a plain date — and the table printed whichever it
    found, raw. A certifier document showed a column mixing "2026-08-19" against
    "2026-08-20T00:47:01.9185" wrapped onto a second line as "56+00:00". The reader needs the
    day; the microseconds and the UTC offset are noise in a cell 1.1 inches wide.

    Unparseable values are returned untouched rather than blanked — a stamp we cannot read is
    still evidence of when something moved, and silently dropping it would be worse.
    """
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 and text[4] == "-" and text[7] == "-" else text


def _truncate(text, max_len=80):
    """Truncate text to max_len characters, appending ellipsis if needed."""
    if text is None:
        return "\u2014"
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "\u2026"


# A credential number: a token carrying at least one digit, e.g. "C-0-123456",
# "QAL 128844", "128844". Four-digit years are excluded so an expiry date is not
# mistaken for the licence itself.
_CREDENTIAL_TOKEN = re.compile(r"[A-Za-z]*[-/]?\d[\w\-/]*")
_CREDENTIAL_EXPIRY = re.compile(r"exp(?:ires|iry|\.)?\s*:?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
# California applicator credentials are NOT interchangeable, and an inspector reads the
# type as closely as the number: QAL (Qualified Applicator Licence), QAC (Qualified
# Applicator Certificate), PAC (Private Applicator Certificate), PCA (Pest Control
# Adviser). Reducing "QAL 128844" to "128844" throws away which one it is.
_CREDENTIAL_TYPE = re.compile(r"\b(QAL|QAC|PAC|PCA)\b", re.IGNORECASE)


def _amendment_nitrogen_kg(ev):
    """kg of nitrogen applied by a soil amendment, or None when not declared.

    Both the amendment tonnage and the N% are on an AS-RECEIVED (wet) basis — the field
    help text says so explicitly, because compost analyses also publish a dry-weight
    column and the two differ by roughly 2x at typical 30-50% moisture.

    Returns None (not 0) when nitrogen was never declared: an undeclared figure is not a
    zero figure, and rendering "0 kg N" would assert something the grower never said.
    """
    pct = getattr(ev, "amendment_nitrogen_percentage", None)
    qty = getattr(ev, "amendment_amount_numeric", None)
    if not pct or not qty:
        return None
    try:
        kg = float(qty)
        unit = (getattr(ev, "amendment_amount_unit", None) or "kg").lower()
        if unit == "tons":
            kg *= 1000.0  # metric tons, per the form's own unit label
        elif unit == "lbs":
            kg *= 0.453592
        return kg * (float(pct) / 100.0)
    except (TypeError, ValueError):
        return None


def _fmt_credential(text):
    """Reduce a free-text applicator credential to the identifier a certifier needs.

    The "Cert #" column is ~0.85" wide and head-truncates at 20 characters. Growers
    type prose into it ("CA DPR Qualified Applicator Certificate C-0-123456 (Cat. B,
    exp. 2027-06-30)"), so head-truncation produced "CA DPR Qualified Ap\u2026" and dropped
    the certificate number entirely \u2014 the one value the column exists to carry. Pull
    the credential token (and expiry, if stated) to the front so it always survives.

    Returns the original string unchanged when no number-like token is present:
    inventing structure from an unparseable value would be worse than showing it.
    """
    if not text:
        return text
    s = str(text).strip()
    expiry = _CREDENTIAL_EXPIRY.search(s)
    # Ignore the expiry substring when hunting for the licence number.
    hunt = _CREDENTIAL_EXPIRY.sub(" ", s)
    tokens = [t for t in _CREDENTIAL_TOKEN.findall(hunt) if any(c.isdigit() for c in t)]
    # A bare 4-digit year is a date, not a licence.
    tokens = [t for t in tokens if not (len(t) == 4 and t.isdigit())]
    if not tokens:
        return s
    # Keep EVERY distinct credential number, longest first. A PCA who also holds a QAL
    # legitimately records two, and silently dropping one is the same class of loss as the
    # truncation this function exists to fix.
    seen = []
    for t in sorted(set(tokens), key=len, reverse=True):
        if t not in seen:
            seen.append(t)
    numbers = " / ".join(seen)
    # Preserve the credential TYPE when the grower stated it explicitly. Only an explicit
    # abbreviation counts — inferring "QAC" from the prose "Qualified Applicator
    # Certificate" would be putting a regulatory classification in the grower's mouth.
    types = {m.group(1).upper() for m in _CREDENTIAL_TYPE.finditer(hunt)}
    prefix = ""
    if len(types) == 1:
        only = types.pop()
        # "PAC-54-2211" already carries its type — do not render "PAC PAC-54-2211".
        if not numbers.upper().startswith(only):
            prefix = f"{only} "
    out = f"{prefix}{numbers}"
    return f"{out} exp {expiry.group(1)}" if expiry else out


# Minimum narrative length considered "materially complete" for § 205.201(a)
# sections. Used by both the audit PDF snapshot and the OSP serializer's
# registry-sync diff so the inspector-facing banners and the PDF never disagree.
# Research basis: real CCOF / Oregon Tilth OSP templates show per-section
# narratives average 150-500 words; 400 chars (~70 words) is a reasonable floor.
OSP_NARRATIVE_MATERIAL_FLOOR = 400

# A character floor measures length, not content. "Test " repeated to 602 characters
# cleared the 400-char floor and produced "100% of § 205.201(a)(1)-(6) substantively
# filled" with no DRAFT banner (2026-08-04, defeated in one attempt).
#
# Lexical diversity is the robust signal: real narrative uses many distinct words,
# padding repeats a few. Applied only above MIN_TOKENS so a genuinely terse answer
# ("No material changes.") is never judged by it.
PADDING_MIN_TOKENS = 12
PADDING_MAX_DOMINANT_SHARE = 0.35
PADDING_MIN_UNIQUE_RATIO = 0.35


def looks_like_padding(text) -> bool:
    """True when a passage is long but says almost nothing.

    Catches word-repetition padding. It does NOT catch a single run of keyboard
    noise ("tetreterterrtret") — that needs a dictionary, and guessing at it would
    reject real abbreviations. Callers should not assume this proves quality.
    """
    if not text:
        return False
    tokens = [t for t in re.split(r"\W+", str(text).lower()) if t]
    if len(tokens) < PADDING_MIN_TOKENS:
        return False
    unique_ratio = len(set(tokens)) / len(tokens)
    dominant_share = Counter(tokens).most_common(1)[0][1] / len(tokens)  # was O(n²): list.count per token
    return unique_ratio < PADDING_MIN_UNIQUE_RATIO or dominant_share > PADDING_MAX_DOMINANT_SHARE


# Below this structured-input count, a long narrative implies the farmer is
# describing inputs in prose that aren't wired into the drift detector's
# baseline. Surface a REVIEW so the farmer reconciles before the audit.
REGISTRY_THIN_THRESHOLD = 3


def _normalize_input_name(name):
    """Lowercase + strip all non-alphanumerics for registry↔narrative matching.
    'Kocide 3000' and 'kocide-3000' collapse to the same key so a farmer's
    casual narrative mention still matches the registry entry.
    """
    import re

    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


# Words that carry no brand identity in a registry product name. Used only to
# reject a leading-token key that is entirely generic ("All Natural ...").
_INPUT_NAME_GENERIC_TOKENS = {
    "the",
    "and",
    "for",
    "all",
    "to",
    "of",
    "organic",
    "natural",
    "agricultural",
    "crop",
    "plant",
    "biological",
    "broad",
}

# A leading-token key shorter than this is too generic to match on safely
# ("Down To" → "downto" would match any narrative containing "down to").
_BRAND_KEY_MIN_CHARS_SINGLE = 6
_BRAND_KEY_MIN_CHARS_PAIR = 8


def _input_name_match_keys(name):
    """Candidate normalized keys that count as naming `name` in a narrative.

    Registry entries carry the full listing title — "Kocide 3000-O Fungicide
    Bactericide Dry Flowable" — while a farmer writing their § 205.201(a)(2)
    narrative says "Kocide 3000". Matching only on the full title reported 5 of
    7 correctly-named inputs as absent (2026-08-04 walkthrough), which both
    trains farmers to ignore the warning and pins a correct OSP below 100%.

    So we also accept the *brand head*: the first token, and the first two
    tokens, of a name that has a droppable descriptor tail (≥ 3 tokens). Length
    floors keep generic heads out.

    Deliberately biased toward under-warning. Two sibling products sharing a
    head ("Neptune's Harvest Organic Fish Fertilizer 2-4-1" and "... Fish and
    Seaweed 2-3-1") both match when the narrative names either one. A missed
    warning costs a farmer nothing; a false one costs the warning its meaning.
    """
    full = _normalize_input_name(name)
    if not full:
        return []

    keys = [full]
    tokens = [t for t in re.split(r"[^a-z0-9]+", (name or "").lower()) if t]
    if len(tokens) < 3:
        # 2-token entries ("Elemental sulfur", "Copper oxychloride") ARE the
        # distinctive name — there is no descriptor tail to drop.
        return keys

    def _usable(token_slice, floor):
        key = "".join(token_slice)
        if len(key) < floor:
            return None
        if all(t in _INPUT_NAME_GENERIC_TOKENS for t in token_slice):
            return None
        return key

    for candidate in (
        _usable(tokens[:1], _BRAND_KEY_MIN_CHARS_SINGLE),
        _usable(tokens[:2], _BRAND_KEY_MIN_CHARS_PAIR),
    ):
        if candidate and candidate not in keys:
            keys.append(candidate)
    return keys


def _name_in_narrative(name, normalized_narrative):
    """True when `name` is referenced in an already-normalized narrative."""
    return any(key in normalized_narrative for key in _input_name_match_keys(name))


def _compute_registry_sync_diff(*, inputs_narrative, plan_rows):
    """Forward-match every material on the plan against the § 205.201(a)(2) narrative text.

    Returns:
      - registry_total: how many materials the plan holds
      - registry_entries: [{source, name, in_narrative: bool}, ...]

    ⛔ Takes `plan_rows` — the output of `plan_materials(osp)` — rather than one list per
    registry. It used to take three: `omri_products`, `wsda_materials`, `nl_substances`. That
    shape made the source count the CALLER's problem, and when operator-entered rows shipped
    every caller silently under-counted: a plan holding seven compost and manure entries and no
    catalog rows reported `registry_total = 0` against a long narrative, so the panel warned
    "the narrative is N characters but only 0 structured inputs are registered" about a list the
    compiler had just written the narrative FROM. Passing the rows makes that arithmetic
    impossible to get wrong, and a fifth source needs no change here at all.

    We deliberately only do FORWARD matching (registry ⊂ narrative). Reverse extraction (find
    narrative-only mentions) requires NLP-style name detection that's too error-prone to surface
    to farmers without high false-positive rates. The inspector-value signal is "you have a
    registered input the narrative doesn't describe" — fixed by editing the narrative.
    """
    normalized_narrative = _normalize_input_name(inputs_narrative)
    entries = [
        {
            "source": row.source,
            "name": row.name or "",
            "in_narrative": _name_in_narrative(row.name or "", normalized_narrative),
        }
        for row in plan_rows
    ]
    return {
        "registry_total": len(entries),
        "registry_entries": entries,
    }


def _photo_count(event):
    """Return integer photo count for an event instance."""
    try:
        return len(album_images(getattr(event, "album", None)))
    except Exception:
        return 0


def album_images(album):
    """An album's images, oldest first, read from the prefetch cache when the caller loaded it.

    `album.images.all().order_by("id")` looks like it uses the `album__images` prefetch every
    export view sets up; it does not — `order_by()` (like `filter()` and `count()`) builds a NEW
    queryset and goes back to the database, once per album. Sorting in Python keeps the cache.
    """
    if album is None:
        return []
    cache = getattr(album, "_prefetched_objects_cache", None) or {}
    rows = list(cache["images"]) if "images" in cache else list(album.images.all())
    rows.sort(key=lambda img: img.pk or 0)
    return rows


_EVENT_DATE_FLOOR = datetime.min.replace(tzinfo=timezone.utc)


def _event_sort_key(field):
    """Postgres puts NULLs last on ASC and first on DESC. A NULL key that sorts ABOVE every real
    value gives exactly that under both `sorted()` and `sorted(reverse=True)`, so a prefetched
    read orders as the query it replaces did."""

    def key(ev):
        value = getattr(ev, field, None)
        if value is None:
            return (True, _EVENT_DATE_FLOOR if field == "date" else 0)
        if field == "date":
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
            else:
                value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        return (False, value)

    return key


def _event_matches(ev, filters):
    for lookup, expected in filters.items():
        field, _, op = lookup.partition("__")
        actual = getattr(ev, field, None)
        if op == "in":
            if actual not in tuple(expected):
                return False
        elif op == "isnull":
            if (actual is None) != bool(expected):
                return False
        elif op:
            raise ValueError(f"related_events() does not support the lookup {lookup!r}")
        elif actual != expected:
            return False
    return True


def related_events(production, related_name, *, order="date", **filters):
    """Rows of one event relation of `production`, ordered, from the prefetch cache when present.

    Every export view prefetches all eight `history_*_events` relations (and their photo albums)
    precisely so the section builders do not go back to the database per production. The
    builders then called `.order_by("date")`, `.filter(type="HA")` or `.count()` on those
    relations — each of which discards the cache and runs a query. Measured on a 12-production
    operation dossier (2026-09-05): ~350 extra queries on `history_productionevent` alone.

    `filters` accepts the small lookup set the builders actually use: `field=value`,
    `field__in=(...)` and `field__isnull=bool`. Anything else raises rather than silently
    returning the wrong rows. Falls back to a real query when the relation was not prefetched
    (tests, ad-hoc callers) so the result is the same either way.
    """
    reverse = order.startswith("-")
    field = order.lstrip("-")
    cache = getattr(production, "_prefetched_objects_cache", None) or {}
    if related_name in cache:
        rows = [ev for ev in cache[related_name] if _event_matches(ev, filters)]
    else:
        manager = getattr(production, related_name)
        rows = list(manager.filter(**filters) if filters else manager.all())
    rows.sort(key=_event_sort_key(field), reverse=reverse)
    return rows


class _PageNumCanvas:
    """
    Mixin used by SimpleDocTemplate to add page numbers in the footer.
    ReportLab calls build() with onFirstPage / onLaterPages callbacks;
    we use a single callback for both.
    """

    pass


def _fmt_change_entries(entries):
    """Render § 205.406 additions/deletions for a certifier, whatever shape they were stored in.

    `OSPAnnualUpdate.additions` / `.deletions` are JSONFields and hold BOTH plain strings (the
    operator typed a sentence) and structured dicts (a UI or seeder recorded a field-level
    change). They were joined with `str(a)`, which is fine for the strings and, for the dicts,
    printed the Python repr straight onto the annual-update table:

        {'new': '24 replant trees, North Block', 'field': 'planting', 'section': 'practices_procedures'}

    That is the `[object Object]` failure in a compliance document — the § 205.406 filing is
    what tells a certifier what changed on the operation this year, and it was showing them a
    dict literal. Live on the walnut showcase farm, which is the landing hero.

    Unknown shapes fall back to a readable join of their values rather than a repr: the goal is
    that this function can never be the reason a certifier reads punctuation instead of a fact.
    """
    if not entries:
        return None

    def _one(entry):
        if isinstance(entry, str):
            return entry.strip()
        if not isinstance(entry, dict):
            return str(entry)
        new_value = entry.get("new")
        old_value = entry.get("old")
        # `field` and `section` are machine keys ("practices_procedures"); the operator never
        # typed them, so they are titled rather than shown raw.
        where = " / ".join(
            str(entry[k]).replace("_", " ").strip().title() for k in ("section", "field") if entry.get(k)
        )
        if new_value and old_value:
            # ReportLab's base-14 Helvetica carries no U+2192: an arrow here printed as the "fi"
            # ligature in every packet ("old ﬁ new"). Plain words render in every font.
            body = f"{old_value} to {new_value}"
        elif new_value or old_value:
            body = str(new_value or old_value)
        else:
            body = "; ".join(str(v) for v in entry.values() if v)
        return f"{where}: {body}" if where else body

    rendered = [text for text in (_one(e) for e in entries) if text]
    return "; ".join(rendered) if rendered else None


def production_period(production, joiner=" to ", compact=False):
    """A production's date range, never presenting a PROJECTION as a closed cycle.

    `finish_date or expected_harvest` was printed at three separate sites — this packet's cover
    line, and twice in the operation dossier — so an OPEN season rendered as a finished one:
    "Carrot Production — 2026-06-20 to 2026-10-05" for a crop still in the ground, with an end
    date that had not happened yet. A certifier reads that as a completed cycle and can ask for
    harvest records against a date the farm has not reached.

    Three copies of one decision, none of them disclosing it — so this is the single place that
    decides, and both modules call it. `joiner` covers the cover line's "to" against the
    dossier's en dash; `compact` drops the expected date for the contents index, whose cells are
    plain strings ReportLab will not wrap inside 2.1in.
    """
    start = _fmt_date(production.start_date)
    if production.finish_date:
        return f"{start}{joiner}{_fmt_date(production.finish_date)}"
    if production.expected_harvest and not compact:
        return f"{start}, in progress (expected {_fmt_date(production.expected_harvest)})"
    return f"{start}, in progress"


_EVENT_RELATIONS = (
    "history_chemicalevent_events",
    "history_productionevent_events",
    "history_soilmanagementevent_events",
    "history_pestmanagementevent_events",
    "history_generalevent_events",
    "history_businessevent_events",
    "history_weatherevent_events",
)


def records_span(production):
    """(earliest, latest) record date on a production, or (None, None) — iterated in Python over
    the prefetched relations, for the same reason `_last_covered_year` does."""
    dates = []
    for related in _EVENT_RELATIONS:
        try:
            dates.extend(e.date for e in getattr(production, related).all() if e.date)
        except Exception:  # noqa: BLE001 — a missing relation must never kill the PDF
            continue
    if not dates:
        return None, None
    return min(dates), max(dates)


def records_outside_period(production):
    """The record span when it reaches OUTSIDE the declared production period, else None.

    `production_period()` prints the crop cycle the operator declared — sowing to last pick,
    or the projected harvest. It is the right headline and it stays. But 13.5% of a pilot's
    records sat outside it: dormant pruning and the seed search weeks before `start_date`,
    winter cover, the irrigation summary and a storage crop's third load weeks after
    `finish_date`. A certifier reading "Period: 1 March – 12 July" and then a record dated
    9 February inside the packet queries it — reasonably, because the document stated a range
    it does not keep to.

    Returns a dict {"earliest", "latest", "before", "after"} (the last two are booleans saying
    which side was overrun) when anything sits outside, so the caller can print one honest line
    beside the period: "Records: 2026-02-09 to 2026-08-31 — pre-season work from 9 Feb; post-harvest
    through 31 Aug". Returns None when every record sits inside the declared period.
    """
    earliest, latest = records_span(production)
    if earliest is None:
        return None
    start = production.start_date
    end = production.finish_date or production.expected_harvest
    before = bool(start and earliest.date() < start.date())
    after = bool(end and latest.date() > end.date())
    if not (before or after):
        return None
    return {"earliest": earliest, "latest": latest, "before": before, "after": after}


def records_span_line(production):
    """The one-line disclosure for the cover / section header, or "" when none is owed."""
    over = records_outside_period(production)
    if not over:
        return ""
    notes = []
    if over["before"]:
        notes.append(f"pre-season work from {_fmt_date(over['earliest'])}")
    if over["after"]:
        notes.append(f"post-harvest records through {_fmt_date(over['latest'])}")
    return f"Records: {_fmt_date(over['earliest'])} to {_fmt_date(over['latest'])} \u2014 " + "; ".join(notes)


def _add_page_number(canvas, doc):
    """Footer callback: renders page number at bottom-right."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    page_num_text = f"Page {doc.page}"
    canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch, page_num_text)
    canvas.drawString(0.75 * inch, 0.5 * inch, "Generated by Trazo  |  Organic recordkeeping platform  |  trazo.io")
    canvas.restoreState()


def _page_furniture(specimen=False):
    """Per-page callback: footer always, specimen wash when the records are fabricated.

    The wash itself and the decision to draw it live in `common.specimen`, not here — see
    that module's docstring. Marking the packet PDF while its CSV twin went unmarked is
    precisely the sibling-surface failure this codebase keeps repeating, so there is one
    authority and every surface consults it.
    """
    return specimen_page_callback(letter, base_callback=_add_page_number, specimen=specimen)


class PhotoEmbedMisconfigurationError(Exception):
    """
    Raised when the audit PDF cannot embed inspector-visible photo evidence
    because the host environment is misconfigured (prod without S3 bucket, or
    prod with S3 bucket but 100% photo fetch failures). A PDF without embedded
    photos is not audit-defensible — inspectors, downstream organic operations,
    and supply-chain traceability auditors (§ 205.501(a)(21)) all rely on the
    evidence layer actually being present.

    The caller (the download view) catches this and returns a 503 with a
    human-readable message rather than silently shipping a degraded PDF.
    """

    def __init__(self, mode: str, detail: str):
        self.mode = mode
        self.detail = detail
        super().__init__(f"[{mode}] {detail}")


class OFPPMissingError(Exception):
    """
    Raised when strict-mode export is requested for an organic audit and the
    establishment either (a) has no Organic Fraud Prevention Plan uploaded, or
    (b) has an OFPP upload whose filename matches the misfiled-invoice
    heuristic. SOE 2024 (88 FR 3622, effective 2024-03-19) makes the OFPP a
    certification-eligibility requirement under 7 CFR 205.201(a)(3).

    Strict mode is OPT-IN: it is meant for the "Mark as Submitted" or
    certifier-handoff export flow. The default ``generate_pdf()`` call still
    produces a PDF with a page-1 FAIL row so farmers can DIAGNOSE missing
    OFPP in a preview. Blocking generation entirely would hide the finding
    from the farmer, which is exactly the feedback loop we want.

    The caller (the download view) catches this and returns a 422 with a
    structured message prompting OFPP upload before re-submission.
    """

    def __init__(self, reason: str, doc_name: str | None = None):
        self.reason = reason
        self.doc_name = doc_name
        super().__init__(f"OFPP blocker: {reason}" + (f" (file: {doc_name})" if doc_name else ""))


#: What may be said about the factor behind one carbon line — never about the RESULT.
#:
#: `CarbonEntry.verification_status` is an untyped CharField that accumulated values reading as
#: third-party verification (`usda_verified`, `epa_usda_verified_aggregate`, `factors_verified`).
#: Printing them raw put "usda_verified" in a document a certifier reads. Per
#: `.claude/rules/compliance.md`: factors are "EPA/USDA-sourced"; "USDA Verified" is forbidden.
#: An unrecognised value degrades to "not stated" rather than inheriting a neighbour's claim.
_EMISSION_FACTOR_BASIS = {
    "factors_verified": "EPA/USDA-sourced factor applied",
    "usda_verified": "EPA/USDA-sourced factor applied",
    "epa_usda_verified_aggregate": "EPA/USDA-sourced factors, aggregated",
    "no_factor_applied": "No factor applied",
    "estimated": "Estimated \u2014 no published factor applied",
}


def _emission_factor_basis(status) -> str:
    return _EMISSION_FACTOR_BASIS.get((status or "").strip().lower(), "Factor basis not stated")


def readiness_row_key(label: str) -> str:
    """The stable key of a readiness row: its label without the citation, as a slug.

    "Record completeness — chemical (§ 205.103(b)(2))" -> "record_completeness_chemical";
    the raw-manure variants that differ only in their citation share "raw_manure_interval".
    """
    name = re.split(r"\s\(", label or "", maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


class OutlinedHeading(Paragraph):
    """A section heading that also adds a PDF outline (bookmark) entry where it is drawn.

    Run 8 (R8-28, Astra 2026-10-05): the 263-page recipient dossier had no outline and its
    Contents named productions without page numbers, so a reviewer could not jump from a
    finding to its section. Every `_section_header` is now one of these: the heading text is
    unchanged and the outline gains an entry at `level` (0 at the top). `on_page`, when given,
    is told the page the heading landed on (the operation dossier uses it to number its
    Contents).
    """

    _keys = __import__("itertools").count()

    def __init__(self, text, style, level=0, on_page=None):
        super().__init__(text, style)
        self.outline_level = level
        self.outline_title = __import__("html").unescape(re.sub(r"<[^>]+>", "", text)).strip() or "Section"
        self.on_page = on_page

    def draw(self):
        super().draw()
        key = f"trazo-h{next(OutlinedHeading._keys)}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(self.outline_title, key, level=self.outline_level, closed=self.outline_level > 0)
        if self.on_page is not None:
            self.on_page(self.canv.getPageNumber())


class AuditExportService:
    """
    Generates audit-ready PDF and CSV exports for a given production.

    Usage:
        service = AuditExportService(production, certification_type="organic")
        pdf_buffer = service.generate_pdf()    # BytesIO
        csv_buffer = service.generate_csv()    # BytesIO
    """

    CERTIFICATION_SECTIONS = {
        "all": [
            "osp_reference",
            "drift_findings",
            "producer_attestation",
            "regulatory_scope",
            "farm",
            "field_map",
            "buffer_zones",
            "production",
            "chemicals",
            "production_events",
            "post_harvest",
            "seed_stock",
            "soil",
            "pest",
            "equipment",
            "weather",
            "traceability",
            "photos",
            # CCOF grower checklist: four of its eight items name a DOCUMENT as the record.
            "attached_documents",
            "custom_data",
            "certifications",
            # 🔴 2026-08-22 — absent here while the organic set carried it, so the modal's
            # DEFAULT ("All Certifications — every event across all supported standards")
            # produced a California packet with no CDFA producer registration in it. A label
            # that promises a superset has to be one.
            "state_organic_registration",  # CDFA SOP (CA Food & Ag Code §§ 46000-46029)
            "business_events",
            "mass_balance",
            "field_history",
            "general_events",
            "soe_compliance",
            "change_history",
            "carbon",  # appendix — informational only, not an NOP requirement; placed last
        ],
        "organic": [
            "osp_reference",  # 7 CFR 205.201 — OSP header (Sprint 5A)
            "drift_findings",  # Sprint 5.1 — OSP ↔ events drift (§ 205.400(f)(2) operation change)
            "producer_attestation",  # 7 CFR 205.401 / 205.400(a) — signed attestation
            "regulatory_scope",  # FSMA 204 + PSR + ICS scoping statements
            "farm",
            "field_map",  # Common OSP Parcel Application — schematic boundary + adjoining land
            "buffer_zones",  # 7 CFR 205.202(c) buffer / drift-prevention record
            "production",
            "chemicals",
            "production_events",  # 7 CFR 205.272 water mgmt + 205.270 post-harvest
            "post_harvest",  # 7 CFR 205.272 / 205.270 — hulling/drying/storage + handler cert
            "seed_stock",
            "soil",
            "pest",  # NOP 7 CFR 205.206(e) requires pest mgmt + threshold rationale docs
            "equipment",
            "weather",  # Weather/climate context — informational; no Part 205 section requires a weather record
            # "carbon" intentionally excluded from NOP organic export — USDA inspectors
            # do not grade on environmental footprint, and including emissions data in
            # an audit PDF risks greenwashing-by-association claims. Carbon remains in
            # the "all" (admin), "roc", and "scs" exports where certifiers request it.
            "photos",
            # CCOF grower checklist: receipts, handler certificates, delivery documents and
            # pack-out summaries are DOCUMENTS, and the packet listed none of them until now.
            "attached_documents",
            "custom_data",
            "certifications",
            "state_organic_registration",  # CDFA SOP producer registration (CA Food & Ag Code §§ 46000-46029)
            "business_events",
            "mass_balance",
            "field_history",
            "general_events",  # § 205.103(b)(1) "adapted to particular business" notes
            "soe_compliance",
            "change_history",
        ],
        "globalgap": [
            "farm",
            "production",
            "chemicals",
            "soil",
            "pest",
            "equipment",
            "photos",
            "custom_data",
            "business_events",
        ],
        "roc": [
            "farm",
            "field_map",
            "buffer_zones",
            "production",
            "chemicals",
            "production_events",
            "post_harvest",
            "seed_stock",
            "soil",
            "pest",
            "weather",
            "photos",
            "attached_documents",
            "custom_data",
            "certifications",
            "business_events",
            "mass_balance",
            "field_history",
            "carbon",  # appendix — informational only, placed last
        ],
        "fsma204": ["farm", "production", "traceability", "photos", "custom_data"],
        "scs": ["farm", "production", "chemicals", "soil", "pest", "photos", "custom_data", "carbon"],
    }

    CERTIFICATION_LABELS = {
        "all": "All Sections",
        "organic": "USDA Organic",
        "globalgap": "GlobalG.A.P.",
        "roc": "Regenerative Organic Certified",
        "fsma204": "FSMA 204 Traceability",
        "scs": "SCS Global Services",
    }

    def __init__(self, production, certification_type="all"):
        self.production = production
        self.certification_type = certification_type.lower()
        self.sections = self.CERTIFICATION_SECTIONS.get(
            self.certification_type,
            self.CERTIFICATION_SECTIONS["all"],
        )
        # CERTIFICATION_SECTIONS already declares that "carbon" is out of scope for the NOP
        # organic export, and says why: USDA inspectors do not grade on environmental
        # footprint, and emissions data in an audit PDF risks greenwashing-by-association.
        # That intent was honoured at SECTION granularity and bypassed at COLUMN granularity —
        # the production table still printed Fuel Used / Equip. Hours, the CSV still carried a
        # Carbon (kg CO2e) column, and the cover still cited EPA emission factors. One
        # predicate, used at every carbon-bearing column, so the declared scope actually holds.
        self.carbon_in_scope = "carbon" in self.sections
        self._styles = self._build_styles()
        # Photo-embed counters. Dev-skipped (expected in local-dev without S3)
        # are separated from prod-failed (genuine S3 misconfig or fetch errors)
        # so the PDF banner can match the severity. Any bare `_photos_not_embedded`
        # reference treats both as the same — we keep it for backward compat.
        self._photos_not_embedded = 0
        self._photos_dev_skipped = 0
        self._photos_prod_failed = 0
        self._photos_prod_errors = []  # list of (url, reason) tuples, capped at 10
        # pk -> (jpeg BytesIO | None, failure) filled by _prefetch_photo_images(); read by
        # _fetch_image_for_pdf() so the gallery loop never waits on the network.
        self._image_cache = {}

    def _establishment_state(self):
        """Canonical 2-letter state for this production's farm, or None.

        None means "not recorded / not a US state" — callers must treat that as
        unknown rather than assuming California, but may still choose to keep a
        state-specific section visible when the underlying data is present.
        """
        try:
            return resolve_establishment_state(self.production.parcel.establishment)
        except AttributeError:
            return None

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    def _build_styles(self):
        base = getSampleStyleSheet()
        styles = {}

        styles["title"] = ParagraphStyle(
            "AuditTitle",
            parent=base["Title"],
            fontSize=22,
            textColor=TRAZO_GREEN_DARK,
            spaceAfter=6,
            alignment=TA_CENTER,
        )
        styles["subtitle"] = ParagraphStyle(
            "AuditSubtitle",
            parent=base["Normal"],
            fontSize=13,
            textColor=DARK_GRAY,
            spaceAfter=4,
            alignment=TA_CENTER,
        )
        styles["section_header"] = ParagraphStyle(
            "SectionHeader",
            parent=base["Heading2"],
            fontSize=12,
            textColor=TRAZO_GREEN_DARK,
            spaceBefore=14,
            spaceAfter=4,
            borderPad=2,
        )
        styles["body"] = ParagraphStyle(
            "AuditBody",
            parent=base["Normal"],
            fontSize=9,
            textColor=DARK_GRAY,
            spaceAfter=3,
        )
        styles["label"] = ParagraphStyle(
            "AuditLabel",
            parent=base["Normal"],
            fontSize=9,
            textColor=colors.HexColor("#555555"),
            spaceAfter=2,
        )
        styles["footer_note"] = ParagraphStyle(
            "FooterNote",
            parent=base["Normal"],
            fontSize=8,
            textColor=colors.HexColor("#888888"),
            spaceBefore=6,
            alignment=TA_LEFT,
        )
        styles["cell"] = ParagraphStyle(
            "CellText",
            parent=base["Normal"],
            fontSize=7,
            textColor=DARK_GRAY,
            leading=9,
        )
        styles["cell_header"] = ParagraphStyle(
            "CellHeader",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.white,
            fontName="Helvetica-Bold",
            leading=9,
            alignment=TA_CENTER,
        )
        return styles

    #: Outline depth of this service's section headings. The operation dossier nests them
    #: under its parcel and production headings (run 8, R8-28).
    outline_level = 0

    def _section_header(self, text, level=None):
        return OutlinedHeading(
            text, self._styles["section_header"], level=self.outline_level if level is None else level
        )

    def _body(self, text):
        return Paragraph(text, self._styles["body"])

    def _label_value(self, label, value):
        # _esc on the VALUE (39 call sites): it is operator-entered — farm name, contact,
        # lot ID, seed source — and lands unescaped in a markup-parsing Paragraph. An "&"
        # in a farm name mangles the line; a stray "<" fails the whole export with a
        # ValueError. No caller passes deliberate markup as a value (checked 2026-08-12).
        # `label` stays raw: every one comes from a developer-authored constant, and some
        # legitimately carry markup.
        v = _esc(value)
        return Paragraph(f"<b>{label}:</b> {v}", self._styles["body"])

    def _total_acreage_phrase(self, est):
        """Farm acreage, reconciled against the parcels actually in this dossier.

        The bare figure invited the worst possible inspector question. The demo
        farm printed "Total Acreage: 149.0 acres" a few pages from "Parcel Area:
        15.0 ha" and two pages from "Split Operation (7 CFR 205.272): No". A
        certifier reading only the numbers sees 149 against 15+20+25 and asks
        what is on the other 89 acres.

        ⚠️ THE TWO FIELDS ARE IN DIFFERENT UNITS. `Establishment.total_acreage`
        is ACRES; `Parcel.area` is HECTARES (see its help_text). 60 ha = 148.3
        acres, which is the 149 — the land reconciles exactly and there is no
        gap. A first cut of this method compared 149 against 60 directly and
        would have printed a fabricated "89 acres unaccounted for, confirm
        split-operation status" warning into the certifier's copy. Convert
        before comparing, always.
        """
        total = est.total_acreage
        if not total:
            return None

        from product.models import Parcel

        HECTARES_TO_ACRES = 2.47105
        parcel_hectares = sum(p.area or 0 for p in Parcel.objects.filter(establishment=est))
        if not parcel_hectares:
            return f"{total} acres"

        parcel_acres = float(parcel_hectares) * HECTARES_TO_ACRES
        gap = float(total) - parcel_acres
        # Tolerance absorbs rounding between a hand-entered farm total and the
        # summed parcel geometry; only a material gap is worth an inspector's
        # time. 2% or 1 acre, whichever is larger.
        tolerance = max(1.0, parcel_acres * 0.02)
        if abs(gap) <= tolerance:
            return f"{total} acres (parcels in this dossier total {parcel_acres:.1f} acres)"
        if gap < 0:
            return (
                f"{total} acres recorded for the operation, but the parcels in this dossier "
                f"total {parcel_acres:.1f} acres — the farm-level figure is lower than the land "
                f"it contains and should be corrected."
            )
        return (
            f"{total} acres total; {parcel_acres:.1f} acres in the parcels covered by this "
            f"dossier. The remaining {gap:.1f} acres are not represented by a parcel record "
            f"here — operator to confirm to the inspector whether that land is non-crop "
            f"(roads, buildings, buffers, unfarmed) or carries production certified "
            f"separately (see 7 CFR 205.272 split-operation status below)."
        )

    def _farming_method_phrase(self, est):
        """Suppress vague self-descriptors on a regulatory document.

        The demo farm carried farming_method="sustainable", which printed on a
        USDA Organic dossier. "Sustainable" has no definition under 7 CFR 205,
        is an unsubstantiated general environmental benefit claim of the kind
        FTC 16 CFR 260.6 targets, and next to a real certification it reads as
        either padding or an unearned second claim. The organic status is already
        stated by the Active Certification Summary; a free-text field must not
        appear to add to it.

        🔴 2026-08-17 — the denylist was only half the hazard.

        `Establishment.farming_method` is a choice-less CharField, and the showcase farm
        (Blue Oak Orchards) carries the literal string "Certified Organic". That is not vague
        at all — it is a SPECIFIC regulatory status, typed by the operator into a field that
        carries no evidence, printed in Farm Overview several pages above the Active
        Certification Summary that actually substantiates it. A word-for-word denylist of
        greenwash terms sails straight past it, which is the "a denylist encodes only the last
        incident" failure in miniature.

        So the rule is inverted: instead of naming the bad values, only the terms this document
        can actually stand behind pass through unqualified. Everything else is labelled as
        operator-entered. The allow-list is the production/farming vocabulary the forms offer
        (see StandardFarmForm.FARMING_METHOD_OPTIONS), which is now itself constrained.
        """
        raw = (est.farming_method or "").strip()
        if not raw:
            return None

        # Terms that describe a PRACTICE and assert no third-party status. These are the four
        # the farm form offers; anything else reached the column before the list was narrowed,
        # or was written by an importer.
        SUBSTANTIATED_PRACTICE_TERMS = {
            "conventional",
            "organic",
            "biodynamic",
            "regenerative",
            "integrated pest management",
            "no-till",
            "no till",
        }
        if raw.lower() in SUBSTANTIATED_PRACTICE_TERMS:
            return raw

        # Anything else — vague ("sustainable"), or a certification name the operator typed by
        # hand ("Certified Organic", "CCOF Certified") — is attributed and de-fanged. Naming
        # where the real answer lives matters more than the caveat itself.
        return (
            f"Operator-entered: “{raw}” — a free-text description, not a term defined under "
            f"7 CFR 205 and not substantiated by this export. Certification status is stated "
            f"in the Active Certification Summary."
        )

    def _osp_declares_split_operation(self, est):
        """The operator's own § 205.272 answer from the OSP, or None if never answered.

        Three states, not two: True / False / never answered. Returning False for an
        unanswered question would let the plan silently override the farm-profile checkbox
        with a declaration nobody made — the same rule as `no_materials_applied`.

        Delegates to `certifications.services.split_operation` so this document and the farm
        profile resolve the declaration through ONE definition — the fix for F25 was a
        binding, and a second copy of the resolution order here would reintroduce the drift
        one layer up.
        """
        from certifications.services.split_operation import osp_split_operation_answer

        return osp_split_operation_answer(est)

    def _parcels_with_a_crop_grown_in_buffer(self, est):
        """Parcel names whose § 205.202(c) buffer carries a recorded crop, as a prose list.

        Reads BOTH the canonical `crop_grown_in_buffer` and the pre-2026-08-09
        `crop_in_buffer` spelling, for the same reason the buffer table does: a database
        restored from before product migration 0023 still holds the old key.
        """
        from product.models import Parcel

        names = []
        for parcel in Parcel.objects.filter(establishment=est).order_by("name"):
            rows = getattr(parcel, "buffer_zones", None) or []
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                crop = row.get("crop_grown_in_buffer") or row.get("crop_in_buffer")
                if crop and str(crop).strip():
                    # _esc, not the raw name: the caller interpolates this into a hand-built
                    # Paragraph, and a parcel called "Smith & Sons <Ranch>" either loses its
                    # own text or — with an unclosed tag — fails the WHOLE export. Found by
                    # test_packet_markup_escaping, which is why that fuzz test exists.
                    names.append(_esc(parcel.name, fallback="") or f"Parcel {parcel.pk}")
                    break
        if not names:
            return ""
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " and " + names[-1]

    def _actor_cell(self, actor):
        """An actor identity for the change log, wrapped where a reader can still parse it.

        An email address is one unbroken token, so ReportLab splits it wherever the column
        runs out — "paula.reyes@blueoakwalnut.e" over "xample". Under § 205.103 this column IS
        the attribution, and a broken address reads as a different person with nothing marking
        the break. Splitting at the "@" instead costs the reader nothing: everyone knows where
        an address divides, and neither half is altered.
        """
        text = str(actor).strip() if actor else ""
        if "@" not in text:
            return self._cell(text or None)
        local, _, domain = text.partition("@")
        # _esc, not a hand-rolled replace chain: escaping belongs in one place, and this is a
        # hand-built Paragraph, which is exactly the shape that fails the whole export on an
        # unclosed tag. `fallback=""` so an empty half stays empty rather than becoming a dash.
        return Paragraph(
            f'{_esc(local, fallback="")}<br/>@{_esc(domain, fallback="")}',
            self._styles["cell"],
        )

    def _spacer(self, height=0.1):
        return Spacer(1, height * inch)

    def _cell(self, text, max_len=None):
        """Wrap text in a Paragraph so ReportLab can word-wrap inside table cells.

        Truncation is OPT-IN (2026-08-01). It used to default to 120 characters, and 128 call
        sites additionally capped at 8-80, which quietly destroyed values in a document whose
        purpose is to record them: a lab name became "Dellavalle Laboratory Inc., F…", a
        certifier "Organic Farmers (C…", a cover-crop species "sativ…", and several cells were
        cut to a character and an ellipsis ("f…", "O…"). Cells are Paragraphs, so ReportLab
        already wraps them on word boundaries — the cap was never doing the job it looked like
        it was doing.

        Pass `max_len` only where SHORTENING NARRATIVE is the intent (a long free-text note in
        a summary row). Never on an identity or regulatory value.
        """
        t = _truncate(text, max_len if max_len is not None else _RUNAWAY_CELL_CHARS) if text else "\u2014"
        # Escape XML special characters for Paragraph
        t = glyph_safe(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return Paragraph(t, self._styles["cell"])

    def _hdr(self, text):
        """Header cell wrapped in Paragraph for word-wrapping."""
        return Paragraph(str(text), self._styles["cell_header"])

    def _warning_style(self):
        """Return a ParagraphStyle for NOP compliance warnings."""
        if not hasattr(self, "_cached_warning_style"):
            self._cached_warning_style = ParagraphStyle(
                "nop_warning",
                parent=self._styles["body"],
                fontSize=7,
                textColor=colors.HexColor("#B71C1C"),
                spaceBefore=4,
                spaceAfter=4,
            )
        return self._cached_warning_style

    def _sub_header_style(self):
        """Return a ParagraphStyle for sub-section headers within audit sections."""
        if not hasattr(self, "_cached_sub_header_style"):
            self._cached_sub_header_style = ParagraphStyle(
                "nop_sub_header",
                parent=self._styles["body"],
                fontSize=8,
                spaceBefore=6,
                spaceAfter=4,
            )
        return self._cached_sub_header_style

    # ------------------------------------------------------------------
    # Table style helpers
    # ------------------------------------------------------------------

    def _base_table_style(self):
        return TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TRAZO_GREEN_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                ("GRID", (0, 0), (-1, -1), 0.4, MID_GRAY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 1), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                # 3pt, not 4 (2026-08-01): the Input Application Log carries 14 columns, so
                # 8pt of horizontal padding per column was consuming 1.55" of a 7.0" budget and
                # squeezing values until words broke mid-character ("Pestici / de").
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )

    def _empty_table(self, headers):
        """Return a single-row table with headers and 'No records' message.

        🔴 2026-08-19 — the headers went in as RAW STRINGS with no colWidths, so ReportLab
        auto-sized each column to its own text and then centred the whole table (Table.hAlign
        defaults to CENTER). An eight-column empty section printed as one crushed line —
        "Date Activity Type Name People Duration Notes By" — floating in the middle of a page
        whose every other table starts at the left margin. Headers are Paragraphs and the
        table spans the frame, so an empty section now looks like the table it is.
        """
        # `or ["\u2014"]`, not `len(headers) or 1`: the latter would build a 0-cell header row
        # against a 1-cell body row and ReportLab raises on ragged tables. No caller passes an
        # empty list today, and this keeps it that way if one ever does.
        safe_headers = list(headers) or ["\u2014"]
        col_count = len(safe_headers)
        empty_style = ParagraphStyle(
            "EmptyTableNote",
            parent=self._styles["cell"],
            textColor=colors.HexColor("#888888"),
            alignment=TA_CENTER,
        )
        data = [
            [self._hdr(h) for h in safe_headers],
            [Paragraph("No records for this production", empty_style)] + [""] * (col_count - 1),
        ]
        # Written as `7.00 * inch / n`, not via a FRAME_WIDTH constant: test_packet_table_widths
        # measures width expressions by matching `* inch` in the source, and a symbolic constant
        # is invisible to it — the guard reported this table as "unmeasured" the moment it
        # stopped being a literal.
        t = Table(data, colWidths=[7.00 * inch / col_count] * col_count, repeatRows=1)
        style = self._base_table_style()
        style.add("SPAN", (0, 1), (-1, 1))
        style.add("ALIGN", (0, 1), (-1, 1), "CENTER")
        style.add("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#888888"))
        t.setStyle(style)
        return t

    def _event_note_text(self, ev):
        """
        Farmer-authored free-text note for an event.

        ChemicalEvent (and Production/General) carry a dedicated
        ``observation`` column. Soil and Pest events have NO observation
        column — the form's note arrives via ``extra_data`` (``observation``
        / ``observations_summary``, the keys the event serializers stash
        free-text into). Returns "" when no note exists.
        """
        note = (getattr(ev, "observation", None) or "").strip()
        if note:
            return note
        extra = getattr(ev, "extra_data", None)
        if isinstance(extra, dict):
            for key in ("observation", "observations_summary", "notes"):
                value = extra.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    def _event_private_note_text(self, ev):
        """The grower's PRIVATE note (`CommonEvent.private_note`).

        Deliberately separate from :meth:`_event_note_text`, for the same reason
        :meth:`_event_description_text` is: a reader must be able to tell which text the operation
        published in its own words from which it wrote only for this document. The notes tables
        carry a Source column precisely so the three kinds stay apart.

        It belongs in the packet: § 205.103(b)(2) is satisfied by what the operation actually
        recorded, not by the subset it chose to publish.
        """
        return (getattr(ev, "private_note", None) or "").strip()

    def _event_description_text(self, ev):
        """Free-text ``description`` for an event — NOT attributable to the farmer.

        Deliberately separate from :meth:`_event_note_text`. ``description`` may be written by
        any of the 328+ AI templates, so it must never be folded into a cell that presents text
        as the grower's own words (see the consumer-side regression where a template's
        CFR-citing description was rendered in quotes as a farmer's field note).

        It is still substantive audit evidence — on legacy events it is where the §205.206(a)
        IPM justification and the §205.203(c)(1) grazing interval actually live — so the
        dossier surfaces it under an explicitly different label rather than dropping it.
        """
        return (getattr(ev, "description", None) or "").strip()

    def _event_note_or_description(self, ev):
        """Note text for single-column tables (weather, business) that have no Source column.

        Same rule as :meth:`_event_description_text`: a description is surfaced but is
        explicitly marked as record text so it is never read as the grower's own words.
        """
        note = self._event_note_text(ev)
        if note:
            return note
        description = self._event_description_text(ev)
        return f"[Record description] {description}" if description else ""

    def _build_event_notes_subtable(self, events, title, type_labels):
        """
        Supplemental notes sub-table (date | type label | note ≤120 chars).

        Mirrors the Production Event Notes pattern: the main section tables
        keep one compact row per event, so free-text notes — the richest
        farmer-authored documentation — would overflow them. Renders ONLY
        when at least one event has a non-empty note; returns [] otherwise.
        """
        # Farmer-authored note first; fall back to the record description so the substance is
        # not lost. The Source column keeps the two apart — a description may be
        # template-generated, so it is shown as record text, never as the grower's words.
        noted = []
        for ev in events:
            note = self._event_note_text(ev)
            if note:
                noted.append((ev, note, "Farmer note"))
            else:
                description = self._event_description_text(ev)
                if description:
                    noted.append((ev, description, "Record description"))
            # A PRIVATE note is ADDITIVE, never a fallback: an event can carry both, and the
            # published one must not suppress it. (The description fallback above stays either/or —
            # it exists only to avoid losing substance when there is no note at all.)
            private = self._event_private_note_text(ev)
            if private:
                noted.append((ev, private, "Private note"))
        if not noted:
            return []

        elements = [self._spacer(0.15), self._body(f"<b>{title}</b>"), self._spacer(0.05)]

        notes_headers = ["Date", "Type", "Source", "Notes"]
        notes_data = [[self._hdr(h) for h in notes_headers]]
        for ev, note, source in noted:
            # The Type cell. A typed event keeps its EXACT previous behaviour — mapped label,
            # else the raw code — because `_humanize_enum` deliberately DROPS short all-caps
            # codes, and silently turning an unmapped "LA" into an em-dash in the Application /
            # Soil / Pest notes tables is not a change this was meant to make.
            #
            # Only the general-event path is new: GeneralEvent has no `type` column at all (its
            # kind lives in `activity_type`, a free CharField with no choices), so the original
            # `ev.type` would have raised AttributeError the moment contamination events started
            # using this helper. `_humanize_enum` gives "emergency" -> "Emergency" and leaves
            # operator-typed text as typed, without a fourth copy of the form's activity list.
            ev_type = getattr(ev, "type", None)
            if ev_type:
                type_cell = type_labels.get(ev_type) or _val(ev_type)
            else:
                type_cell = _humanize_enum(getattr(ev, "activity_type", None)) or _val(None)
            notes_data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(type_cell),
                    self._cell(source),
                    # NOT truncated. 120 chars cut the §205.203(c)(1) grazing interval and the
                    # §205.206(a) IPM justification mid-sentence — the exact content a
                    # certifier reads this table for. A 600-char cap was no better: chemical
                    # event 1004's spinosad justification is 628 characters, so the National
                    # List citation at the end was still lost. Per the `_cell` contract,
                    # truncation is opt-in and never applied to a regulatory value; the cell is
                    # a Paragraph, so ReportLab word-wraps it.
                    self._cell(note),
                ]
            )

        notes_widths = [0.7 * inch, 1.0 * inch, 1.0 * inch, 3.9 * inch]
        notes_table = Table(notes_data, colWidths=notes_widths, repeatRows=1)
        notes_table.setStyle(self._base_table_style())
        elements.append(notes_table)
        return elements

    # ------------------------------------------------------------------
    # PDF generation — public entry point
    # ------------------------------------------------------------------

    def _section_builders(self):
        """Map section-key → builder method. Exposed as a method (not an inline dict) so the
        operation-wide export (OperationAuditExportService) can reuse individual per-production
        section builders when assembling one combined dossier across many productions."""
        return {
            "osp_reference": self._build_osp_reference_section,
            "drift_findings": self._build_drift_findings_section,
            "producer_attestation": self._build_producer_attestation_section,
            "regulatory_scope": self._build_regulatory_scope_section,
            "farm": self._build_farm_overview,
            "field_map": self._build_field_map_section,
            "buffer_zones": self._build_buffer_zone_section,
            "post_harvest": self._build_post_harvest_section,
            "production": self._build_production_summary,
            "chemicals": self._build_chemical_log,
            "production_events": self._build_production_events,
            "seed_stock": self._build_seed_stock_section,
            "soil": self._build_soil_section,
            "pest": self._build_pest_section,
            "equipment": self._build_equipment_section,
            "weather": self._build_weather_section,
            "carbon": self._build_carbon_section,
            "traceability": self._build_traceability_section,
            "photos": self._build_photos_section,
            "attached_documents": self._build_attached_documents_section,
            "custom_data": self._build_custom_data_section,
            "certifications": self._build_certifications_section,
            "state_organic_registration": self._build_state_organic_registration_section,
            "business_events": self._build_business_events_section,
            "mass_balance": self._build_mass_balance_section,
            "field_history": self._build_field_history_section,
            "general_events": self._build_general_events_section,
            "soe_compliance": self._build_soe_compliance_section,
            "change_history": self._build_change_history_section,
        }

    def generate_pdf(
        self,
        strict_photos: bool = True,
        strict_ofpp: bool | None = None,
    ):
        """
        Return a BytesIO containing the complete audit PDF.

        Parameters
        ----------
        strict_photos : bool, default True
            When True AND this production has photos attached, the PDF
            emission is GATED on photo-evidence integrity:
              * in ``prod_s3_misconfig`` (prod without S3 bucket configured),
                a pre-flight check raises ``PhotoEmbedMisconfigurationError``
                BEFORE the document is built — an inspector-grade PDF cannot
                be shipped without the evidence layer, and the misconfig is
                unrecoverable in-process.
              * after build, if ANY photo fetch failed in prod mode
                (``_photos_prod_failed > 0``), ``PhotoEmbedMisconfigurationError``
                is raised post-build and the partial buffer is discarded.
                Unembedded photo evidence is not acceptable for an
                inspector-facing artifact.
            Productions with zero photos are NOT gated — an all-text PDF
            does not need S3 to be inspector-ready.

            Callers that want a best-effort preview (farmer dashboard,
            internal debugging) can pass ``strict_photos=False`` to bypass
            both gates and accept a PDF that transparently declares its
            photo-evidence gap via the in-document banner.

        strict_ofpp : bool | None, default None (derives from cert type)
            When True AND this is an organic export (``certification_type``
            = "organic" or "all"), refuse to emit the PDF if the
            establishment's OFPP is a [FAIL] on the compliance snapshot
            (not uploaded at all OR uploaded with a misfiled-invoice
            filename pattern). Raises ``OFPPMissingError`` before building.

            When None (the default), the flag is derived from the
            certification type:
              * "organic" or "all" → strict_ofpp defaults to True, on the
                premise that any export filtered for NOP compliance must
                be submission-ready. A partial-preview dossier that
                silently admits a § 205.201(a)(3) non-compliance is the
                exact "NO-GO" artifact an inspector will not process.
              * All other cert types → False.

            Callers that explicitly want a diagnostic preview (farmer
            dashboard, pre-submit gap-analysis) MUST pass
            ``strict_ofpp=False`` to opt out of the gate. The view layer
            threads ``strict_ofpp=false`` from a query parameter for
            exactly this purpose.

            Non-organic cert types are unaffected regardless — OFPP is a
            NOP construct.
        """
        # Pre-flight: in prod without S3 bucket, refuse to emit a PDF only
        # when this production actually has photos to embed. A production
        # with zero photos attached is text-only and unaffected by the S3
        # gap, so there's no reason to block it here.
        env = self._photo_embed_environment()
        has_photos = self._production_has_any_photos()
        if strict_photos and has_photos and env["mode"] == "prod_s3_misconfig":
            raise PhotoEmbedMisconfigurationError(
                mode=env["mode"],
                detail=(
                    "Production environment has no AWS_STORAGE_BUCKET_NAME "
                    "configured — photo evidence cannot be embedded. Refusing "
                    "to emit audit PDF. Configure S3 before re-exporting."
                ),
            )

        # Pre-flight: strict-OFPP gate for organic / all-certs exports.
        # Runs BEFORE document build so the caller gets a fast, structured
        # error rather than a PDF that effectively admits non-compliance.
        # When the caller passes None (our default), derive strict from
        # the cert type: organic / all-certs exports are strict by default
        # because a NOP-filtered dossier MUST be submission-ready under
        # SOE 2024. Diagnostic previews must explicitly opt out via
        # ``strict_ofpp=False``.
        if strict_ofpp is None:
            strict_ofpp = self.certification_type in ("organic", "all")
        if strict_ofpp and self.certification_type in ("organic", "all"):
            ofpp_flags = self._ofpp_flags()
            if ofpp_flags["establishment"]:
                if not ofpp_flags["uploaded"]:
                    raise OFPPMissingError(
                        reason=(
                            "No Organic Fraud Prevention Plan on file. SOE "
                            "2024 (7 CFR 205.201(a)(3), effective 2024-03-"
                            "19) requires every certified operation to "
                            "maintain a written OFPP with a vulnerability "
                            "assessment and monitoring procedures. An "
                            "operation without a valid OFPP is ineligible "
                            "for certification."
                        )
                    )
                if ofpp_flags["filename_suspicious"]:
                    raise OFPPMissingError(
                        reason=(
                            "OFPP upload filename matches the misfiled-"
                            "invoice heuristic. Trazo treats this as a "
                            "missing OFPP for submission purposes — upload "
                            "a substantive OFPP (vulnerability assessment + "
                            "monitoring procedures + supplier verification) "
                            "before re-exporting."
                        ),
                        doc_name=ofpp_flags.get("doc_name"),
                    )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.75 * inch,
            leftMargin=0.75 * inch,
            topMargin=0.9 * inch,
            bottomMargin=0.75 * inch,
            title=f"Trazo Audit Report — {self._farm_name()}",
        )

        story = []
        story += self._build_cover_page()
        story.append(PageBreak())

        section_builders = self._section_builders()

        for section_key in self.sections:
            builder = section_builders.get(section_key)
            if builder:
                story += builder()

        furniture = _page_furniture(specimen=self._is_specimen())
        doc.build(story, onFirstPage=furniture, onLaterPages=furniture)

        # Post-build gate: in prod with S3 configured, any photo that failed
        # to embed indicates a bucket-policy / IAM / DNS issue that must be
        # resolved before the PDF ships to a certifier. An inspector-facing
        # audit artifact is only as trustworthy as its evidence layer; a
        # banner that says "3 of 25 photos unavailable" reads as an
        # incomplete filing to a CCOF reviewer. Refuse rather than emit.
        if strict_photos and env["mode"] == "prod_s3_ok":
            prod_failed = getattr(self, "_photos_prod_failed", 0)
            if prod_failed > 0:
                raise PhotoEmbedMisconfigurationError(
                    mode=env["mode"],
                    detail=(
                        f"{prod_failed} photo(s) failed to embed in production "
                        "(S3 fetch errors). Refusing to emit an inspector-grade "
                        "audit PDF without complete evidence. Check IAM "
                        "permissions / bucket policy / DNS and re-export."
                    ),
                )

        buffer.seek(0)
        return buffer

    def _production_has_any_photos(self) -> bool:
        """
        Cheap existence check — does this production have ANY photos
        attached across all event categories? Used by the photo-evidence
        gate to skip the S3 check for text-only productions.

        Walks the same related managers as ``_build_photos_section`` but
        returns on the first hit instead of building the full category
        list. Never raises — a DB error here must not prevent PDF export.
        """
        try:
            for _, related_name in self._photos_category_order_for():
                qs = getattr(self.production, related_name, None)
                if qs is None:
                    continue
                for ev in qs.all():
                    if _photo_count(ev) > 0:
                        return True
        except Exception:  # noqa: BLE001 — gate must degrade open, not crash.
            return False
        return False

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------

    def _farm_name(self):
        try:
            return self.production.parcel.establishment.name
        except AttributeError:
            return "Farm"

    def _last_covered_year(self, target_year):
        """The last calendar year this production's RECORDS reach.

        Deliberately not `finish_date.year`. An OPEN season has no finish date, and that is
        exactly when a packet is most likely to be generated — mid-cycle, for a certifier who
        asked. A season sown in October 2025 and still running today carries records dated 2026,
        and keying off `finish_date` alone would disclose nothing about them, which is the very
        gap this whole block exists to close.

        So the range is taken from the records themselves: the newest event actually in the
        packet, and the closing dates when they exist. What a certifier reads is the records, so
        the years disclosed have to be the years the records span.

        Never earlier than `target_year` — a malformed row with a finish date before its start
        must not produce a backwards range.
        """
        candidates = [target_year]
        for value in (self.production.finish_date, self.production.expected_harvest):
            if value is not None:
                candidates.append(value.year)

        for related in (
            "history_chemicalevent_events",
            "history_productionevent_events",
            "history_soilmanagementevent_events",
            "history_pestmanagementevent_events",
            "history_generalevent_events",
            "history_businessevent_events",
            "history_weatherevent_events",
        ):
            try:
                # Iterated in PYTHON, not `.order_by("-date").first()`. The operation dossier
                # prefetches every one of these relations, and adding a queryset modifier throws
                # that prefetch away — 7 extra queries per production, 49 for a seven-season
                # dossier — for a number the rows already in memory can answer. Same trap as the
                # prefetched-M2M ordering fixed elsewhere in this codebase.
                dates = [e.date for e in getattr(self.production, related).all() if e.date]
            except Exception:  # noqa: BLE001 — a missing relation must never kill the PDF
                continue
            if dates:
                candidates.append(max(dates).year)

        return max(candidates)

    def _is_specimen(self):
        """True when this farm's records are FABRICATED (`Establishment.is_demo`).

        Resolves to False when the establishment cannot be reached, and that direction is
        deliberate. The two ways to be wrong are not symmetric: failing to mark a synthetic
        packet leaves the pre-2026-08-21 status quo, whereas marking a REAL packet tells a
        certifier that a legitimate operation's 205.103 records are a demo \u2014 which
        invites them to reject the farmer's filing. So an unreachable establishment exports
        unmarked, exactly as every packet did before this flag existed.
        """
        return is_specimen(establishment_of(self.production))

    def _specimen_cover_banner(self):
        """Cover-page notice for fabricated records.

        Says what the document IS and what it is not, in the certifier's own vocabulary:
        the risk is not that someone thinks Trazo is fake, it is that this PDF gets filed
        or forwarded as a real operation's organic records, since it is otherwise
        structurally identical to one \u2014 same cover, same CFR citations, same handler
        certificates, same audit trail.
        """
        style = ParagraphStyle(
            "SpecimenBanner",
            parent=self._styles["body"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=colors.HexColor("#B71C1C"),
        )
        body = f"{_esc(SPECIMEN_TITLE)}<br/><font size=8.5>{_esc(SPECIMEN_BODY)}</font>"
        table = Table([[Paragraph(body, style)]], colWidths=[7.00 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDECEA")),
                    ("BOX", (0, 0), (-1, -1), 1.4, colors.HexColor("#C62828")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ]
            )
        )
        return table

    def _build_cover_page(self):
        p = self.production
        elements = []

        # Belt to the watermark's braces. The wash on every page survives excerpting; this
        # states it in words a reader cannot mistake for decoration, ABOVE the farm name, so
        # it is the first thing read rather than a footnote under a real-looking title block.
        if self._is_specimen():
            elements.append(self._specimen_cover_banner())
            elements.append(self._spacer(0.35))
        else:
            elements.append(self._spacer(1.2))

        # _esc: the farm name is operator text on a markup-parsing Paragraph. "Smith & Sons"
        # mangles the title; an unclosed tag raised ValueError here and produced no packet
        # at all — this line, not _label_value, was the first thing the export hit.
        elements.append(Paragraph(f"Audit Report \u2014 {_esc(self._farm_name())}", self._styles["title"]))
        elements.append(self._spacer(0.1))

        crop_name = ""
        try:
            crop_name = p.crop_type.name if p.crop_type else (p.product.name if p.product else "")
        except AttributeError:
            pass

        period = production_period(p, joiner=" to ")
        # Crop types are stored as plural nouns for list display ("Avocados", "Walnuts"), which
        # reads as a slip in a singular noun phrase \u2014 the cover printed "Avocados Production".
        # Trim a trailing "s" only where it is unambiguous; "Grass"/"Citrus" keep theirs.
        #
        # 2026-08-22: stripping a bare "s" mangled four of the seeded crops, and they are exactly
        # the ones this platform sells to \u2014 "Blueberries" became "Blueberrie Production" on the
        # cover line of the certifier packet, alongside "Strawberrie", "Potatoe" and "Tomatoe".
        # English plurals in -ies take -y, and in -oes take -o; handle those before the bare -s.
        crop_label = _esc(crop_name, fallback="")
        if len(crop_label) > 3 and crop_label.endswith("s") and not crop_label.endswith(("ss", "us", "is")):
            if crop_label.endswith("ies"):
                crop_label = crop_label[:-3] + "y"
            elif crop_label.endswith("oes"):
                crop_label = crop_label[:-2]
            else:
                crop_label = crop_label[:-1]
        elements.append(
            Paragraph(
                f"{crop_label} Production \u2014 {period}",
                self._styles["subtitle"],
            )
        )
        # The declared cycle is the headline; when the records reach outside it, say so on the
        # same page rather than let the reader discover a 9 February record under a 1 March
        # period. See `records_outside_period`.
        span_line = records_span_line(p)
        if span_line:
            elements.append(Paragraph(_esc(span_line), self._styles["footer_note"]))

        elements.append(self._spacer(0.6))

        cert_label = self.CERTIFICATION_LABELS.get(self.certification_type, self.certification_type.upper())
        meta_rows = [
            ["Generated", _fmt_generated_date()],
            ["Certification Filter", cert_label],
            ["Lot ID", _val(p.lot_id)],
        ]
        # The raw production UUID used to sit on the cover above the Lot ID. It is an internal
        # database key: a certifier cannot look it up, cannot cross-reference it to any document
        # the operation holds, and the Lot ID directly below is the identifier they actually use
        # at inspection. Kept out of the cover, retained in the traceability section for support.
        meta_table = Table(meta_rows, colWidths=[2 * inch, 4 * inch])
        meta_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, MID_GRAY),
                    ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        elements.append(meta_table)

        elements.append(self._spacer(0.4))

        # Non-compliant-dossier banner. We compute this from the OFPP flag
        # (the SOE 2024 hard-blocker under § 205.201(a)(3)). When OFPP is
        # FAIL the dossier is NOT submission-ready; surface that ABOVE the
        # snapshot so an inspector reading page 1 can never mistake a
        # diagnostic preview for a submission-ready filing. Default mode
        # (non-strict) still produces the PDF so the farmer can see WHY
        # they are non-compliant; strict-mode export raises a 422 instead.
        try:
            ofpp_flags = self._ofpp_flags()
        except Exception:  # noqa: BLE001 — banner must not crash the cover page
            ofpp_flags = {"establishment": False, "uploaded": False, "filename_suspicious": False}
        ofpp_blocker = (
            self.certification_type in ("organic", "all")
            and ofpp_flags.get("establishment")
            and (not ofpp_flags.get("uploaded") or ofpp_flags.get("filename_suspicious"))
        )
        if ofpp_blocker:
            banner_style = ParagraphStyle(
                "noncompliant_banner",
                parent=self._styles["body"],
                fontSize=11,
                fontName="Helvetica-Bold",
                textColor=colors.white,
                backColor=colors.HexColor("#B71C1C"),
                alignment=TA_CENTER,
                leading=14,
                borderPadding=8,
                spaceBefore=4,
                spaceAfter=8,
            )
            banner_text = (
                "[NON-COMPLIANT DOSSIER \u2014 DO NOT SUBMIT TO CERTIFIER] "
                "OFPP (\u00a7 205.201(a)(3)) is FAIL. SOE 2024 prohibits "
                "certification without a valid Organic Fraud Prevention Plan. "
                "Resolve the OFPP finding on page 1 / SOE Compliance Status "
                "before handing this PDF to the certifier."
            )
            elements.append(Paragraph(banner_text, banner_style))

        elements += self._build_compliance_snapshot()

        # Pre-Export Consistency Check — cross-references production
        # header fields against the raw event stream (yield, carton count,
        # lot ID, handler). Surfaces internal inconsistencies to the farmer
        # BEFORE the PDF reaches a certifier. Under SOE § 205.103(b)(2) and
        # § 205.501(a)(21), these are exactly the kind of questions a
        # supply-chain traceability audit is designed to ask.
        # The linter must NEVER crash PDF generation — an unexpected data
        # shape in the narrative should degrade to "no findings" rather
        # than an empty PDF.
        try:
            consistency = self._build_consistency_findings()
        except Exception:  # noqa: BLE001 — linter is informational, not blocking
            logger.exception("Consistency linter raised; rendering PDF without it")
            consistency = []
        if consistency:
            elements.append(self._spacer(0.15))
            elements += consistency

        elements.append(self._spacer(0.3))
        elements.append(
            Paragraph(
                "Generated by Trazo  |  Organic recordkeeping platform  |  trazo.io",
                self._styles["footer_note"],
            )
        )
        # Only where carbon is in scope. On a NOP organic export there are no emission figures
        # in the document, so citing emission factors states a methodology for data that is not
        # there — and puts an environmental-claim sentence on the cover of a compliance dossier.
        if self.carbon_in_scope:
            elements.append(
                Paragraph(
                    "Emission factors sourced from EPA 40 CFR Part 98 and USDA Agricultural Research Service.",
                    self._styles["footer_note"],
                )
            )

        return elements

    # ------------------------------------------------------------------
    # Compliance Snapshot — page-1 executive summary
    # ------------------------------------------------------------------

    def compliance_snapshot_rows(self):
        """The page-1 Compliance Snapshot as DATA, without building a PDF.

        Extracted from _build_compliance_snapshot() (2026-08-03) so the same rows can feed a
        dashboard card. This is a pure code move: no condition is recomputed and no
        regulation logic changed — the renderer below now iterates what this returns.

        Returns a list of dicts: {label, status, detail, section_hint}, where status is one of
        PASS | REVIEW | FAIL. "REVIEW"/"FAIL" mean the RECORD needs attention in Trazo — the
        certifying agent makes the compliance determination, not us.
        """

        """
        One-table audit snapshot: ✓ / ⚠ / ✗ for the items an inspector
        scans for first. Goal is a 30-second compliance overview that
        replaces the inspector's manual checklist for this operation.
        """

        from certifications.models import OrganicSystemPlan

        from .record_completeness import summarize_chemical_events

        p = self.production

        # Counts — each section header below mirrors a real inspector worksheet.
        # All seven event types contribute to the documentation-depth roll-up
        # at the bottom of the snapshot; weather/equipment/business are quieter
        # but still part of the operation's record-keeping footprint.
        chemicals = list(p.history_chemicalevent_events.all())
        soils = list(p.history_soilmanagementevent_events.all())
        pests = list(p.history_pestmanagementevent_events.all())
        production_events = list(p.history_productionevent_events.all())
        gen_events = list(p.history_generalevent_events.all())
        weather_events = list(p.history_weatherevent_events.all())
        business_events = list(p.history_businessevent_events.all())
        equipment_events = list(p.history_equipmentevent_events.all())
        all_events = (
            chemicals
            + soils
            + pests
            + production_events
            + gen_events
            + weather_events
            + business_events
            + equipment_events
        )
        photos_total = sum(_photo_count(ev) for ev in all_events)

        # OSP completeness — material floor is 400 chars per § 205.201(a).
        osp = None
        try:
            est = p.parcel.establishment
            osp = (
                OrganicSystemPlan.objects.filter(establishment=est, status="active").order_by("-version_number").first()
            )
            if osp is None:
                osp = OrganicSystemPlan.objects.filter(establishment=est).order_by("-version_number").first()
        except Exception:  # noqa: BLE001 — snapshot must never crash the PDF
            est = None

        if osp:
            from certifications.models import OSP_SECTION_KEYS

            sections_data = osp.sections or {}
            section_hits = {
                k: len((sections_data.get(k) or {}).get("narrative", "").strip()) >= 400 for k in OSP_SECTION_KEYS
            }

            # Registry Sync gate: (a)(2) inputs narrative is not "substantively
            # filled" if the OSP's structured approved-inputs registry has
            # entries that are not referenced in the narrative. Prevents the
            # page-1 snapshot from reading "100% complete" while the detail
            # section shows unreferenced registry entries (a CCOF inspector
            # would call this a contradiction on the face of the document).
            try:
                inputs_narrative_text = (sections_data.get("inputs_list") or {}).get("narrative", "") or ""
                from certifications.services.plan_materials import plan_materials

                registry_diff = _compute_registry_sync_diff(
                    inputs_narrative=inputs_narrative_text,
                    plan_rows=plan_materials(osp),
                )
                unref = sum(1 for r in registry_diff["registry_entries"] if not r["in_narrative"])
                # Total, so an EMPTY registry is not reported as "all referenced". unref == 0
                # is true both when every input is described and when there are no inputs at
                # all, and those are opposite facts to a certifier.
                registry_total = len(registry_diff["registry_entries"])
                if unref > 0:
                    section_hits["inputs_list"] = False
            except Exception:  # noqa: BLE001 — snapshot must never crash the PDF
                unref = 0
                registry_total = 0

            material_complete = sum(1 for hit in section_hits.values() if hit)
            osp_pct = int(material_complete * 100 / len(OSP_SECTION_KEYS))
            osp_status = "PASS" if osp_pct >= 100 else ("REVIEW" if osp_pct >= 50 else "FAIL")

            # Name the thin sections. This row's substance is section completeness — the
            # "Draft (not yet submitted)" text is only the status label riding along, and the
            # OSP-not-submitted ACTION already has its own whole-operation item on the
            # readiness card. Reporting a bare percentage next to that item read as the same
            # finding twice, and gave the grower nothing to act on: "66% materially complete"
            # does not say which two sections are short.
            SECTION_LABELS = {
                "practices_procedures": "Practices & procedures (a)(1)",
                "inputs_list": "Input list (a)(2)",
                "monitoring_plan": "Monitoring plan (a)(3)",
                "recordkeeping_description": "Recordkeeping system (a)(4)",
                "commingling_barriers": "Commingling barriers (a)(5)",
                "additional_certifier_info": "Additional certifier info (a)(6)",
            }
            thin = [SECTION_LABELS.get(k, k) for k in OSP_SECTION_KEYS if not section_hits.get(k, False)]
            osp_detail = f"v{osp.version_number} {_osp_status_label(osp)} — {osp_pct}% materially complete"
            if thin:
                osp_detail += f"; below the narrative floor: {', '.join(thin)}"
            if unref > 0:
                osp_detail += f"; (a)(2) gap: {unref} registry entr" f"{'y' if unref == 1 else 'ies'} unreferenced"
        else:
            osp_status = "FAIL"
            osp_detail = "No Organic System Plan on file"

        # Drift findings (Sprint 5.1 detector).
        # Planting records too: the section this row points at lists chemical, soil and planting
        # (PL) findings, so the row counts the same three (review of back #116).
        drift_count = sum(1 for ev in chemicals + soils if ev.drift_warning) + sum(
            1 for ev in production_events if ev.type == "PL" and ev.drift_warning
        )

        # Compost compliance per § 205.203(c)(2).
        # Full classifier: C:N 25–40 AND temp 131–170°F AND method-specific duration/turnings.
        # - Windrow: 15+ days at temp, 5+ turnings.
        # - Static aerated / in-vessel: 3+ days at temp.
        # Missing C:N / method / temp / duration → REVIEW. C:N out of range → FAIL.
        # `type == "CO"` alone was a FALSE CLEAN. The soil form offers
        # "Compost - Organic amendment" as an `amendment_type` on the OM (organic matter)
        # subtype, so a real 170-ton OMRI compost application is stored as OM/compost and was
        # never inspected — the dossier then printed "No compost events to validate" as
        # DOCUMENTED on a production that had applied compost. An unevaluated application must
        # reach the § 205.203(c)(2) classifier, not bypass it.
        compost_events = [
            ev
            for ev in soils
            if ev.type == "CO" or (getattr(ev, "amendment_type", None) or "").strip().lower() == "compost"
        ]
        compost_compliant = 0
        compost_missing_cn = 0
        compost_cn_out_of_range = 0
        compost_missing_method = 0
        compost_missing_temp_or_duration = 0
        # Pathway tracking — § 205.203(c)(2) has three pathways: (i) C:N
        # precondition 25:1–40:1, (ii) in-vessel 131–170°F × 3+ days, (iii)
        # windrow 131–170°F × 15+ days with 5+ turnings. Static-aerated piles
        # follow the same 3-day duration as in-vessel. Inspector wants to know
        # which pathway(s) were used, not just PASS/FAIL.
        compost_pathway_counts = {"windrow": 0, "static_aerated": 0, "in_vessel": 0, "unspecified": 0}
        compost_cn_min = None
        compost_cn_max = None
        for ev in compost_events:
            cn = float(ev.compost_initial_cn_ratio) if ev.compost_initial_cn_ratio is not None else None
            if cn is not None:
                compost_cn_min = cn if compost_cn_min is None else min(compost_cn_min, cn)
                compost_cn_max = cn if compost_cn_max is None else max(compost_cn_max, cn)
            method_key = getattr(ev, "compost_method", None) or "unspecified"
            if method_key not in compost_pathway_counts:
                method_key = "unspecified"
            compost_pathway_counts[method_key] = compost_pathway_counts.get(method_key, 0) + 1
            if cn is None:
                compost_missing_cn += 1
                continue
            if not (25.0 <= cn <= 40.0):
                compost_cn_out_of_range += 1
                continue
            if not ev.compost_method:
                compost_missing_method += 1
                continue
            if ev.compost_peak_temp_f is None or ev.compost_duration_days_at_temp is None:
                compost_missing_temp_or_duration += 1
                continue
            temp_ok = 131 <= float(ev.compost_peak_temp_f) <= 170
            if ev.compost_method == "windrow":
                duration_ok = ev.compost_duration_days_at_temp >= 15 and (ev.compost_turning_count or 0) >= 5
            else:
                duration_ok = ev.compost_duration_days_at_temp >= 3
            if temp_ok and duration_ok:
                compost_compliant += 1

        _harvest_dates = [
            ev.date.date()
            for ev in related_events(self.production, "history_productionevent_events", type__in=("HA",))
            if ev.date
        ]
        _rule_days = self._manure_interval_rule_for_crop()["days"]
        compost_assessments = [
            _compost_out_of_range_assessment(ev, _harvest_dates, _rule_days)
            for ev in compost_events
            if ev.compost_initial_cn_ratio is not None and not (25.0 <= float(ev.compost_initial_cn_ratio) <= 40.0)
        ]
        compost_manure_notes = [text for branch, text in compost_assessments if branch != "plant_only"]

        def _compost_pathway_summary():
            """Human-readable pathway + C:N summary for the snapshot detail cell."""
            labels = {
                "windrow": "Windrow (§ 205.203(c)(2)(iii))",
                "static_aerated": "Static aerated pile (§ 205.203(c)(2))",
                "in_vessel": "In-vessel (§ 205.203(c)(2)(ii))",
                "unspecified": "Pathway unspecified",
            }
            parts = [f"{count}× {labels[k]}" for k, count in compost_pathway_counts.items() if count]
            pathway_str = "; ".join(parts) if parts else "no pathway data"
            if compost_cn_min is not None and compost_cn_max is not None:
                if abs(compost_cn_max - compost_cn_min) < 0.05:
                    cn_str = f"C:N {compost_cn_min:.1f}:1"
                else:
                    cn_str = f"C:N {compost_cn_min:.1f}–{compost_cn_max:.1f}:1"
                if compost_cn_min < 25.0 or compost_cn_max > 40.0:
                    cn_str += " [outside § 205.203(c)(2)(i) 25:1–40:1 floor]"
                return f"{pathway_str} · {cn_str}"
            return pathway_str

        # Manure interval — every raw-manure event must have an interval set.
        # NOP 5006 processed manure and (c)(2) composted manure are interval-
        # exempt, so they are counted separately and excluded from the raw row.
        all_manure_events = [ev for ev in soils if ev.manure_application_date or ev.manure_harvest_interval]
        processed_5006_events = [ev for ev in soils if ev.manure_treatment == "processed_5006"]
        processed_5006_documented = sum(
            1
            for ev in processed_5006_events
            if ev.processed_manure_temp_f is not None or (ev.processed_manure_attestation or "").strip()
        )
        manure_events = [ev for ev in all_manure_events if ev.manure_treatment not in ("processed_5006", "composted")]
        manure_with_interval = sum(1 for ev in manure_events if ev.manure_harvest_interval)
        # Classification-mismatch count: farmer selected an interval that
        # doesn't match the crop's soil-contact rule. The timing may still
        # be compliant (e.g. farmer chose 120-day on a tree crop and
        # harvested at 99 days — compliant under the correct 90-day floor
        # but IN-violation under the farmer's own 120-day selection).
        # Either reading makes page-1 an executive-summary signal, not a
        # clean PASS. Count it here so the snapshot row below can demote
        # the status without re-deriving the rule.
        _rule_for_count = self._manure_interval_rule_for_crop()
        _expected_days = _rule_for_count["days"]
        manure_classification_mismatches = 0
        for ev in manure_events:
            raw = (ev.manure_harvest_interval or "").split("_")[0]
            if raw.isdigit() and int(raw) != _expected_days:
                manure_classification_mismatches += 1

        # Pest threshold rationale per § 205.206(e). Strip whitespace so a
        # placeholder " " doesn't pass for a documented rationale.
        threshold_met_events = [ev for ev in pests if ev.action_threshold_met]
        # Pesticide/fungicide/herbicide applications. § 205.601's preamble permits a listed
        # synthetic "only when the provisions set forth in § 205.206(a) through (d) prove
        # insufficient", so these are the events whose lawfulness depends on the two rows
        # below having evidence behind them. Fertilizer (FE) is excluded: it is not a
        # pest-control substance and carries no § 205.206 precondition.
        control_substance_events = [ev for ev in chemicals if getattr(ev, "type", None) in ("PE", "FU", "HE")]
        threshold_with_rationale = sum(
            1 for ev in threshold_met_events if ev.threshold_rationale and ev.threshold_rationale.strip()
        )

        # IPM strategy presence per § 205.206(a).
        pests_with_ipm = sum(1 for ev in pests if ev.ipm_strategy and ev.ipm_strategy.strip())

        # Chemical traceability per § 205.103(b) — supplier required for every input.
        # Also detect supplier-name variants ("Hydra", "Hydra Gardens", "Hydra-Gardens")
        # that collapse to the same normalized form — inspector treats those as REVIEW,
        # not PASS, because it's a data-integrity signal.
        import re

        def _normalize_supplier(name):
            return re.sub(r"[\s\-_,.]+", "", (name or "").strip().lower())

        chems_with_supplier = sum(1 for ev in chemicals if ev.supplier_name and ev.supplier_name.strip())
        supplier_variants = {}
        for ev in chemicals:
            raw = (ev.supplier_name or "").strip()
            if not raw:
                continue
            key = _normalize_supplier(raw)
            supplier_variants.setdefault(key, set()).add(raw)
        supplier_variant_groups = [raws for raws in supplier_variants.values() if len(raws) > 1]

        # § 205.272 contamination prevention — when the operation uses equipment
        # shared with conventional, evidence is required in the form of EM
        # (Equipment Maintenance) events carrying cleaning date + method + performer.
        # One shared-equipment exposure ⇒ at least one fully-documented EM event
        # should exist. Rinse-step documentation lands in P0-6.
        any_shared_equipment = any(ev.shared_with_conventional for ev in production_events)
        em_cleaning_events = [ev for ev in production_events if ev.type == "EM"]

        def _is_documented_cleaning(ev):
            return bool(ev.cleaning_date and (ev.cleaning_method or "").strip() and (ev.cleaned_by or "").strip())

        em_fully_documented = sum(1 for ev in em_cleaning_events if _is_documented_cleaning(ev))

        # §E-5 — per-operation cleaning evidence. The aggregate test above answers "does this
        # operation keep cleaning records at all"; it cannot answer "was THIS shared-equipment
        # pass preceded by a cleaning", which is what § 205.272 actually asks. Where a grower
        # links the covering EM event, report that directly.
        #
        # The aggregate remains the verdict when NO links are in use, so an operation that has
        # not adopted the field is judged exactly as before rather than being retroactively
        # downgraded for a record-keeping feature that did not exist when it logged its season.
        # A cleaning event is not an operation that needs cleaning coverage — asking the
        # wash-down record to reference a wash-down is circular, and counting it would report
        # "1/2 covered" for a season with exactly one harvest and its cleaning.
        shared_operations = [ev for ev in production_events if ev.shared_with_conventional and ev.type != "EM"]
        linked_shared_operations = [ev for ev in shared_operations if ev.equipment_cleaning_event_id]
        covered_shared_operations = [
            ev
            for ev in linked_shared_operations
            if _is_documented_cleaning(ev.equipment_cleaning_event)
            and (not ev.date or not ev.equipment_cleaning_event.date or ev.equipment_cleaning_event.date <= ev.date)
        ]

        # Contamination incidents per § 205.201(b). Both fields must be non-empty.
        contamination_events = [ev for ev in gen_events if ev.is_contamination_incident]
        contamination_with_action = sum(
            1
            for ev in contamination_events
            if ev.corrective_action_taken and ev.corrective_action_taken.strip() and ev.certifier_notified
        )

        # Render the internal PASS/REVIEW/FAIL signal as a DOCUMENTATION-STATUS
        # mark, not a self-assigned compliance verdict — the certifying agent makes
        # the compliance determination, so the operation only attests to whether the
        # supporting record is on file. Colors are kept; only the displayed word and
        # the legend change. Internal status codes stay PASS/REVIEW/FAIL so all the
        # row-building logic below is untouched.
        # Build rows. Each row: (Requirement, status PASS/REVIEW/FAIL, detail).
        snapshot_rows = []

        # OSP filed
        snapshot_rows.append(("Organic System Plan (§ 205.201)", osp_status, osp_detail))

        # OSP completeness — § 205.201(a)(2) requires the OSP to "include a
        # description of the substances to be used as production or
        # handling inputs." A registry-narrative gap is a technical
        # violation: the structured registry has inputs the narrative does
        # not describe. Surface this as its OWN row (not just a suffix on
        # the OSP row above) so an inspector reading the snapshot does
        # not miss the load-bearing (a)(2) signal. Status:
        #   PASS  — every registry input is referenced in the narrative
        #   REVIEW — 1-3 unreferenced (typo / minor narrative gap)
        #   FAIL — 4+ unreferenced (substantive narrative deficit)
        if osp:
            if registry_total == 0:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "REVIEW",
                        (
                            "No production or handling inputs are on file, so (a)(2) cannot be "
                            "evaluated \u2014 this is an absence of evidence, not a clean result"
                        ),
                    )
                )
            elif unref == 0:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "PASS",
                        "All registry inputs are referenced in the OSP narrative",
                    )
                )
            elif unref <= 3:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "REVIEW",
                        (
                            f"{unref} registry input"
                            f"{'s are' if unref != 1 else ' is'} not "
                            "referenced in the OSP narrative \u2014 update "
                            "the narrative or remove the unused entries"
                        ),
                    )
                )
            else:
                snapshot_rows.append(
                    (
                        "OSP completeness (\u00a7 205.201(a)(2))",
                        "FAIL",
                        (
                            f"{unref} registry inputs are not referenced in "
                            "the OSP narrative. \u00a7 205.201(a)(2) requires "
                            "the OSP to describe every input used; an "
                            "inspector will issue an RFI before approving "
                            "the materials."
                        ),
                    )
                )

        # Unapproved-input findings (OSP practice change)
        #
        # drift_count is a tally of stamped drift_warnings. It reads 0 both when every input was
        # compared and cleared, and when there was NOTHING TO COMPARE AGAINST — no approved-
        # inputs list on file, or an OSP still in draft so the detector never ran at all. The
        # section body already says exactly that ("an absence of evidence, NOT a clean result");
        # this row used to contradict it with a green DOCUMENTED, and the pre-read is the first
        # thing a certifier reads. Same predicate as the body, so the two cannot diverge again.
        # ⛔ Through `plan_materials()`, which reads all four sources. The comment above claims
        # "same predicate as the body, so the two cannot diverge again" — and it had already
        # diverged: this counted National List + OMRI while the body also counted WSDA, so a
        # WSDA-only plan got "No approved-inputs list on file" here and "No drift findings"
        # three pages later. Neither side counted operator-entered rows at all. One reader now,
        # which is the only arrangement in which that comment is true.
        approved_inputs_on_file = False
        if osp is not None:
            try:
                from certifications.services.plan_materials import plan_materials

                approved_inputs_on_file = bool(plan_materials(osp))
            except Exception:  # noqa: BLE001 — snapshot must never crash the PDF
                approved_inputs_on_file = False
        if drift_count == 0 and not approved_inputs_on_file:
            snapshot_rows.append(
                (
                    "Inputs not matched to the plan's approved inputs (§ 205.400(f)(2))",
                    "REVIEW",
                    (
                        "No approved-inputs list on file, so conformance could not be evaluated "
                        "— see Inputs Not Matched to the Plan's Approved Inputs section"
                    ),
                )
            )
        elif drift_count == 0:
            snapshot_rows.append(
                (
                    "Inputs not matched to the plan's approved inputs (§ 205.400(f)(2))",
                    "PASS",
                    "No input record is unmatched to the plan's approved inputs",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Inputs not matched to the plan's approved inputs (§ 205.400(f)(2))",
                    "REVIEW",
                    f"{drift_count} input record(s) not matched to the plan's approved inputs \u2014 see "
                    "Inputs Not Matched to the Plan's Approved Inputs section",
                )
            )

        # Chemical input traceability — FAIL on missing supplier, REVIEW on
        # name variants that may refer to the same vendor (data-integrity signal).
        if not chemicals:
            snapshot_rows.append(("Input traceability (§ 205.103)", "NA", "No chemical inputs applied this period"))
        elif chems_with_supplier != len(chemicals):
            snapshot_rows.append(
                (
                    "Input traceability (§ 205.103)",
                    "FAIL",
                    f"{chems_with_supplier}/{len(chemicals)} inputs have supplier — fill before audit",
                )
            )
        elif supplier_variant_groups:
            # Render the first variant group inline so the farmer sees what to fix.
            first_group = sorted(supplier_variant_groups[0])
            sample = ", ".join(f'"{n}"' for n in first_group[:3])
            extra = f" (+ {len(supplier_variant_groups) - 1} more)" if len(supplier_variant_groups) > 1 else ""
            snapshot_rows.append(
                (
                    "Input traceability (§ 205.103)",
                    "REVIEW",
                    f"Supplier name variants may refer to same vendor: {sample}{extra}",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Input traceability (§ 205.103)",
                    "PASS",
                    f"{chems_with_supplier}/{len(chemicals)} inputs have supplier on file",
                )
            )

        # Record completeness — does each chemical event itself carry what an inspector reads:
        # product name, amount, area, target pest (see history/services/record_completeness.py).
        # Distinct from "Input traceability" above, which only asks whether a SUPPLIER is on file.
        # A spray record with a supplier but no rate or target pest passes that check and fails
        # this one — every field here is `blank=True, null=True` at the model level, so nothing
        # upstream of this row currently catches it.
        if not chemicals:
            snapshot_rows.append(
                ("Record completeness — chemical (§ 205.103(b)(2))", "NA", "No chemical inputs applied this period")
            )
        else:
            record_summary = summarize_chemical_events(chemicals)
            if record_summary.all_complete:
                snapshot_rows.append(
                    (
                        "Record completeness — chemical (§ 205.103(b)(2))",
                        "PASS",
                        f"{record_summary.complete}/{record_summary.total} chemical records have product, amount, area (and target pest where applicable)",
                    )
                )
            else:
                missing_summary = ", ".join(
                    f"{label} ({count})"
                    for label, count in sorted(record_summary.missing_field_counts.items(), key=lambda kv: -kv[1])
                )
                snapshot_rows.append(
                    (
                        "Record completeness — chemical (§ 205.103(b)(2))",
                        "FAIL",
                        f"{record_summary.incomplete}/{record_summary.total} chemical records missing required fields — {missing_summary}",
                    )
                )

        # Compost compliance — C:N out of range is a hard FAIL (pile reverts to
        # raw manure). Pathway info is surfaced in every case so the inspector
        # sees which § 205.203(c)(2) route was used.
        if not compost_events:
            snapshot_rows.append(("Compost (§ 205.203(c)(2))", "NA", "No compost events this period"))
        elif compost_cn_out_of_range > 0:
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "REVIEW",
                    (
                        f"{compost_cn_out_of_range}/{len(compost_events)} event(s) record a C:N outside 25:1–40:1: "
                        + " ".join(text for _, text in compost_assessments)
                        + f" Pathway: {_compost_pathway_summary()}"
                    ),
                )
            )
        elif compost_missing_cn > 0 or compost_missing_method > 0 or compost_missing_temp_or_duration > 0:
            missing_parts = []
            if compost_missing_cn > 0:
                missing_parts.append(f"{compost_missing_cn} missing C:N")
            if compost_missing_method > 0:
                missing_parts.append(f"{compost_missing_method} missing method")
            if compost_missing_temp_or_duration > 0:
                missing_parts.append(f"{compost_missing_temp_or_duration} missing temp/duration")
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "REVIEW",
                    f"{' · '.join(missing_parts)} — add before inspection. " f"Pathway: {_compost_pathway_summary()}",
                )
            )
        elif compost_compliant == len(compost_events):
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "PASS",
                    f"{compost_compliant}/{len(compost_events)} events meet C:N 25–40 + temp + method duration. "
                    f"Pathway: {_compost_pathway_summary()}",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Compost (§ 205.203(c)(2))",
                    "REVIEW",
                    f"{compost_compliant}/{len(compost_events)} compliant — review non-compliant events. "
                    f"Pathway: {_compost_pathway_summary()}",
                )
            )

        # Manure interval — § 205.203(c)(1) governs raw manure (compost is (c)(2)).
        # (c)(1)(i) land used for a crop not intended for human consumption.
        # (c)(1)(ii) 120 days when the edible portion has direct soil contact
        # (root crops, leafy greens, fruits on the ground).
        # (c)(1)(iii) 90 days when the edible portion does NOT have direct soil
        # contact (tree fruits, tree nuts, elevated vine fruits).
        # Citing (ii) for a 90-day interval inverts the rule — a CCOF inspector
        # would read it as a category mismatch / regulatory misanchor.
        manure_interval_rule = self._manure_interval_rule_for_crop()
        manure_row_label = f"Raw manure interval ({manure_interval_rule['cite']})"
        if not manure_events and compost_manure_notes:
            # Run 7 (R7-09): never "N/A" after the compost row raised the interval question.
            snapshot_rows.append(
                (
                    manure_row_label,
                    "REVIEW",
                    "No raw manure application is recorded, but compost records raise the interval question: "
                    + " ".join(compost_manure_notes),
                )
            )
        elif not manure_events:
            snapshot_rows.append((manure_row_label, "NA", "No raw manure events this period"))
        elif manure_with_interval != len(manure_events):
            # Missing interval selection on at least one event — hard FAIL
            # regardless of classification; can't verify safety without the
            # selection.
            snapshot_rows.append(
                (
                    manure_row_label,
                    "FAIL",
                    (
                        f"{manure_with_interval}/{len(manure_events)} events have the "
                        f"{manure_interval_rule['label']} interval recorded — safety-critical"
                    ),
                )
            )
        elif manure_classification_mismatches > 0:
            # Every event has an interval AND the timing may satisfy the
            # regulatory floor, BUT the farmer-selected classification
            # (90/120-day category) doesn't match the crop rule. REVIEW
            # rather than PASS: an inspector reading the record will ask
            # why the selection conflicts with the crop's soil-contact
            # classification, and if the farmer's selected interval is
            # stricter than the regulatory floor, the actual harvest may
            # sit INSIDE the farmer's own self-imposed window — a record-
            # integrity issue under § 205.103(b)(2) even when the
            # regulatory timing passes.
            snapshot_rows.append(
                (
                    manure_row_label,
                    "REVIEW",
                    (
                        f"{manure_with_interval}/{len(manure_events)} events meet the "
                        f"{manure_interval_rule['label']} regulatory floor, but "
                        f"{manure_classification_mismatches} event(s) have a farmer-"
                        f"selected interval that does not match the crop-rule "
                        f"classification — see Pre-Export Consistency Check + "
                        f"Manure Handling Records for the per-event mismatch list."
                    ),
                )
            )
        else:
            snapshot_rows.append(
                (
                    manure_row_label,
                    "PASS",
                    (
                        f"{manure_with_interval}/{len(manure_events)} events meet the "
                        f"{manure_interval_rule['label']} pre-harvest interval"
                    ),
                )
            )

        # Processed manure — NOP 5006. Processed (pathogen-reduced) manure is
        # exempt from the (c)(1) raw interval, but only when the processing is
        # DOCUMENTED (peak temperature and/or an OMRI/supplier attestation).
        # Undocumented processed manure reverts to raw and is flagged REVIEW.
        if processed_5006_events:
            if processed_5006_documented == len(processed_5006_events):
                snapshot_rows.append(
                    (
                        "Processed manure (NOP 5006 / § 205.203)",
                        "PASS",
                        (
                            f"{processed_5006_documented}/{len(processed_5006_events)} processed-manure "
                            "event(s) documented (temperature and/or OMRI/supplier attestation) — "
                            "exempt from the raw-manure pre-harvest interval per NOP 5006"
                        ),
                    )
                )
            else:
                snapshot_rows.append(
                    (
                        "Processed manure (NOP 5006 / § 205.203)",
                        "REVIEW",
                        (
                            f"{processed_5006_documented}/{len(processed_5006_events)} processed-manure "
                            "event(s) carry the NOP 5006 processing basis (temperature or "
                            "OMRI/supplier attestation); undocumented events revert to the raw "
                            "§ 205.203(c)(1) interval"
                        ),
                    )
                )

        # § 205.272 contamination prevention — cleaning-log evidence when any
        # equipment is shared with conventional operations. Distinguish:
        # - no EM events at all → FAIL (no cleaning record created)
        # - EM events exist but all incomplete / partially documented → REVIEW
        # - all EM events fully documented → PASS
        if not any_shared_equipment:
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "PASS",
                    "No equipment shared with conventional operations",
                )
            )
        elif linked_shared_operations:
            # The grower is using per-operation links, so report what they actually establish.
            covered = len(covered_shared_operations)
            total = len(shared_operations)
            if covered == total:
                snapshot_rows.append(
                    (
                        "Contamination prevention (§ 205.272)",
                        "PASS",
                        (
                            f"All {total} shared-equipment operation(s) reference a documented "
                            "cleaning event performed beforehand"
                        ),
                    )
                )
            else:
                snapshot_rows.append(
                    (
                        "Contamination prevention (§ 205.272)",
                        "REVIEW",
                        (
                            f"{covered}/{total} shared-equipment operation(s) reference a documented "
                            "prior cleaning — link the covering EM cleaning event on the remainder"
                        ),
                    )
                )
        elif not em_cleaning_events:
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "FAIL",
                    "Shared equipment in use but no Equipment Maintenance cleaning events on file",
                )
            )
        elif em_fully_documented < len(em_cleaning_events):
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "REVIEW",
                    (
                        f"{em_fully_documented}/{len(em_cleaning_events)} EM cleaning events fully documented — "
                        "remaining events missing date / method / performer"
                    ),
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Contamination prevention (§ 205.272)",
                    "PASS",
                    (
                        f"{em_fully_documented} EM cleaning event(s) on file with date + method + performer for "
                        "shared-equipment exposure"
                    ),
                )
            )

        # Pest threshold rationale
        #
        # 🔴 2026-08-15. This used to emit PASS when `threshold_met_events` was empty, i.e.
        # precisely when there was no evidence. An operation that logged ten § 205.601
        # applications and zero pest events collected a green PASS on the clause that makes
        # those applications lawful. A packet may report a gap; it must never invent a pass.
        #
        # The honest states are three, not two: SATISFIED, a real gap, and "nothing to assess".
        # And the third is only benign when no control substance was applied — if substances
        # WERE applied with no threshold record, that is the § 205.206(e) gap itself.
        if not threshold_met_events:
            if control_substance_events:
                snapshot_rows.append(
                    (
                        "Pest threshold rationale (§ 205.206(e))",
                        "REVIEW",
                        (
                            f"{len(control_substance_events)} pest-control application(s) on file with no "
                            "action-threshold record — § 205.601 permits a substance only where "
                            "§ 205.206(a)-(d) proved insufficient"
                        ),
                    )
                )
            else:
                snapshot_rows.append(
                    (
                        "Pest threshold rationale (§ 205.206(e))",
                        "NOT ASSESSED",
                        "No pest-control applications and no threshold records on file",
                    )
                )
        elif threshold_with_rationale == len(threshold_met_events):
            snapshot_rows.append(
                (
                    "Pest threshold rationale (§ 205.206(e))",
                    "PASS",
                    f"{threshold_with_rationale}/{len(threshold_met_events)} threshold-met events documented",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Pest threshold rationale (§ 205.206(e))",
                    "FAIL",
                    f"{threshold_with_rationale}/{len(threshold_met_events)} have rationale — required before any control material",
                )
            )

        # IPM strategy
        #
        # 🔴 Same defect, same date. "No pest events" is not compliance with § 205.206(a) —
        # it is an absence of evidence, and it reads as a pass only because the row was
        # written as a two-state check.
        if not pests:
            if control_substance_events:
                snapshot_rows.append(
                    (
                        "IPM strategy (§ 205.206(a))",
                        "REVIEW",
                        (
                            f"{len(control_substance_events)} pest-control application(s) on file with no pest "
                            "management records documenting the preventive practices tried first"
                        ),
                    )
                )
            else:
                snapshot_rows.append(
                    ("IPM strategy (§ 205.206(a))", "NOT ASSESSED", "No pest management records on file")
                )
        elif pests_with_ipm == len(pests):
            snapshot_rows.append(
                ("IPM strategy (§ 205.206(a))", "PASS", f"{pests_with_ipm}/{len(pests)} pest events document IPM")
            )
        else:
            snapshot_rows.append(
                (
                    "IPM strategy (§ 205.206(a))",
                    "REVIEW",
                    f"{pests_with_ipm}/{len(pests)} have IPM strategy — fill before inspection",
                )
            )

        # Lot traceability — post-SOE § 205.307(a) requires (1) organic identity
        # and (2) lot/shipping-ID on every non-retail container; § 205.103(b)(2)
        # requires records that enable one-step trace from sales unit back to
        # production lot. § 205.273 is the Imports section — NOT the correct
        # cite for domestic lot traceability.
        if p.lot_id:
            snapshot_rows.append(("Lot traceability (§ 205.307 / § 205.103(b)(2))", "PASS", f"Lot ID: {p.lot_id}"))
        else:
            snapshot_rows.append(
                ("Lot traceability (§ 205.307 / § 205.103(b)(2))", "REVIEW", "Lot ID assigned at finish")
            )

        # Sales record. Reads through resolve_sales_disclosure() — the SAME precedence the
        # packet body uses — because this row previously branched on `p.sold_to` alone and
        # therefore ignored SalesRecord entirely. A production with a complete sales record
        # printed "REVIEW — Add buyer + organic-on-invoice flag" on page 1 while page 12 of
        # the same PDF printed "Sold To: <buyer> / Organic Identified on Invoice: Yes".
        # Confirmed on a rendered packet 2026-08-10.
        sales_disclosure = resolve_sales_disclosure(p)
        if sales_disclosure.buyer:
            snapshot_rows.append(
                (
                    "Sales documentation (§ 205.103)",
                    "PASS",
                    f"Sold to: {_truncate(sales_disclosure.buyer, 50)}; "
                    f"organic on invoice = {'Yes' if sales_disclosure.organic_on_invoice else 'No'}",
                )
            )
        else:
            snapshot_rows.append(("Sales documentation (§ 205.103)", "REVIEW", "Add buyer + organic-on-invoice flag"))

        # Contamination — § 205.272 is the commingling/contact-with-prohibited-substance
        # prevention practice standard. § 205.201(b) is the OSP-substitution clause and
        # is NOT the correct cite for contamination incident logs.
        if not contamination_events:
            snapshot_rows.append(
                (
                    "Contamination log (§ 205.272)",
                    "PASS",
                    "Contamination incidents logged this period: 0 (logging system active)",
                )
            )
        elif contamination_with_action == len(contamination_events):
            snapshot_rows.append(
                (
                    "Contamination log (§ 205.272)",
                    "PASS",
                    f"{len(contamination_events)} incident(s); all have corrective action + certifier notified",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "Contamination log (§ 205.272)",
                    "FAIL",
                    f"{contamination_with_action}/{len(contamination_events)} incidents complete — finish corrective action + notify certifier",
                )
            )

        # Land requirements (§ 205.202) — 36-month transition. Under NOP, an
        # organic certification is only issued once a land parcel has completed
        # its 3-year transition, so an ACTIVE verified organic cert covering the
        # production period is evidence of transition compliance. Self-reported
        # certs get REVIEW (transition not independently verified via the USDA
        # Organic Integrity Database). We do NOT parse OSP narrative text.
        est_for_land = None
        try:
            est_for_land = self.production.parcel.establishment
        except AttributeError:
            est_for_land = None
        if est_for_land is not None:
            from certifications.models import Certification as _Cert

            prod_start = self.production.start_date.date() if self.production.start_date else date.today()
            # Certification.certification_type stores enum keys (e.g. "usda_organic",
            # "roc") — NOT display labels, so an icontains="organic" match would miss
            # CNG / ROC / ROP whose keys do not contain the string "organic". The
            # allow-list is right; restating its members here was not. It is one import
            # now, shared with OperationReadinessService, and guarded by
            # certifications/tests/test_cert_type_set_authority.py.
            organic_certs = list(
                _Cert.objects.filter(
                    establishment=est_for_land,
                    certification_type__in=_ORGANIC_CONFERRING_CERT_TYPES,
                ).order_by("effective_date")
            )
            covering = [
                c
                for c in organic_certs
                if c.is_active
                and c.effective_date
                and c.effective_date <= prod_start
                and (not c.expiry_date or c.expiry_date >= prod_start)
            ]
            if covering:
                # The PASS text asserts "USDA OID verified", so it must be gated on the source
                # that substantiates it — not on `verification_status` alone.
                #
                # 🔴 2026-08-19: this read `verification_status == "verified"` by itself, so a
                # row marked verified by a manual admin edit, a data import or a fixture made
                # the certifier packet print "(USDA OID verified)" for a database match that
                # never happened. `Certification.consumer_display_status` closed exactly this
                # hole on the public QR page and says so in its docstring (16 CFR 260.6); the
                # same file already gates on `verification_source` at the Active Certification
                # Summary. This check was the one place still taking the flag at face value —
                # in the document that goes to a certifier.
                verified = [
                    c
                    for c in covering
                    if c.verification_status == "verified"
                    and getattr(c, "verification_source", "") == _Cert.DATABASE_VERIFICATION_SOURCE
                ]
                if verified:
                    earliest = min((c.effective_date for c in verified))
                    snapshot_rows.append(
                        (
                            "Land requirements (§ 205.202)",
                            "PASS",
                            f"Certified organic since {earliest.isoformat()} (USDA OID verified) — 36-month transition complete",
                        )
                    )
                else:
                    # INFO, not REVIEW.
                    #
                    # § 205.202 asks for land history, boundaries and buffers. § 205.201(a)
                    # lists five OSP elements plus whatever the agent asks for; the operation's
                    # OWN certificate is in neither list. A certificate is the OUTPUT of
                    # certification, not evidence a grower owes.
                    #
                    # 🔴 2026-08-19: this was REVIEW, and it fired in both real-world cases.
                    # A CERTIFIED farm has a certificate and its § 205.202 position was settled
                    # by the agent that issued it — nothing to fix. An APPLICANT (this product's
                    # ICP: cert years 1-5, free pilots) cannot have one at all. So the amber
                    # "Needs attention" appeared when nothing was wrong, and its action text
                    # asked the grower to "confirm transition via USDA OID" — which is Trazo's
                    # lookup, not something they can do. Third instance of the same cry-wolf
                    # pattern as the raw-manure absence and the photo count.
                    #
                    # What is genuinely reportable is Trazo's own confidence, and that belongs
                    # in the packet (a certifier wants to know we did not verify it) rather than
                    # on an action card. FAIL/REVIEW stay available below for a real gap.
                    earliest = min((c.effective_date for c in covering))
                    snapshot_rows.append(
                        (
                            "Land requirements (§ 205.202)",
                            "INFO",
                            f"Organic certification recorded, effective {earliest.isoformat()} "
                            "(self-reported — no USDA Organic Integrity Database match on file). "
                            "The 36-month determination under § 205.202(b) is the certifying "
                            "agent's.",
                        )
                    )
            else:
                # Report the evidence § 205.202 actually turns on, not only the certificate.
                #
                # USDA's own instrument here is the "Field History / Previous Land Use Record":
                # three years of crop and materials applied, "in order to establish a date of
                # last application of prohibited materials and determine eligibility for
                # organic certification". That form exists to be filed BEFORE a certificate
                # exists — which is the position of every first-year applicant, and of the
                # free-pilot farms this product is aimed at.
                #
                # 🔴 2026-08-19: this branch said only "No active organic certification
                # covering production period", so a parcel carrying three clean years of field
                # history was told what it lacked and never what it held. Same failure as the
                # photo row: implying a gap where the evidence is present.
                #
                # It stays REVIEW either way. Field history is farmer-reported, and § 205.202
                # is the certifying agent's determination — the card's own footer says so.
                # PASS remains reserved for a third-party USDA OID match.
                status = "REVIEW"
                detail = (
                    "No active organic certification covering production period, and no field "
                    "history on file — nothing on record evidences the § 205.202(b) 36-month "
                    "period"
                )
                try:
                    from product.models import ParcelCropHistory
                    from product.services.transition_status_service import compute_transition_status

                    parcel = self.production.parcel
                    years = ParcelCropHistory.objects.filter(parcel=parcel).count()
                    if years:
                        ts = compute_transition_status(parcel)
                        if ts.last_prohibited_date:
                            # A dated prohibited application IS actionable: it sets the clock.
                            status = "REVIEW"
                            detail = (
                                f"{years} year(s) of field history on file; last prohibited "
                                f"application {ts.last_prohibited_date.isoformat()} — "
                                "certifying agent confirms the 36-month date"
                            )
                        elif ts.unclassified:
                            # Also actionable, and the grower is the one who can do it.
                            status = "REVIEW"
                            detail = (
                                f"{years} year(s) of field history on file, no prohibited "
                                f"application recorded, but {len(ts.unclassified)} input(s) have "
                                "no organic status recorded — classify them, then the certifying "
                                "agent confirms the 36-month period"
                            )
                        else:
                            # The § 205.202 evidence USDA's own form asks for is complete.
                            # Nothing is owed; report it and let the agent determine.
                            status = "INFO"
                            detail = (
                                f"{years} year(s) of field history on file with no prohibited "
                                "application recorded (farmer-reported). The 36-month "
                                "determination under § 205.202(b) is the certifying agent's."
                            )
                except Exception:  # noqa: BLE001 — never let the enrichment break the row
                    pass

                # Neither a certificate nor any field history: nothing evidences § 205.202 at
                # all, which is a real documentation gap and stays REVIEW.
                snapshot_rows.append(("Land requirements (§ 205.202)", status, detail))

        # OFPP (§ 205.201(a)(3)) — page-1 signal. A suspicious-filename upload
        # is a harder FAIL than "not uploaded" because it looks compliant at a
        # glance. Inspector must open the document to confirm.
        # compute_hash=False: the snapshot rows never display doc_hash, and hashing the OFPP
        # document is a blocking S3 GET. Skipping it is what makes these rows cheap enough to
        # serve on a dashboard request.
        ofpp_flags = self._ofpp_flags(compute_hash=False)
        if not ofpp_flags["establishment"]:
            pass  # no snapshot row when establishment missing — covered elsewhere
        elif not ofpp_flags["uploaded"]:
            snapshot_rows.append(
                (
                    "OFPP (§ 205.201(a)(3))",
                    "FAIL",
                    "No Organic Fraud Prevention Plan on file — required under SOE 2024",
                )
            )
        elif ofpp_flags["filename_suspicious"]:
            snapshot_rows.append(
                (
                    "OFPP (§ 205.201(a)(3))",
                    "FAIL",
                    f"Uploaded file <{ofpp_flags['doc_name']}> matches the "
                    "misfiled-invoice pattern. Trazo treats this as a missing "
                    "Organic Fraud Prevention Plan — SOE 2024 requires a "
                    "substantive plan with vulnerability assessment + monitoring "
                    "procedures; no certification without one.",
                )
            )
        else:
            snapshot_rows.append(
                (
                    "OFPP (§ 205.201(a)(3))",
                    "PASS",
                    f"Uploaded {ofpp_flags['date_str']}: {ofpp_flags['doc_name']}",
                )
            )

        # Documentation depth — all 7 event types + photos total. PASS at 10+
        # photos is a reasonable floor for a 22-event organic production; below
        # that, an inspector will likely ask for more visual evidence.
        #
        # ⚠️ INFO, never REVIEW — this row must not read as a certifier finding.
        #
        # It is the one row in this snapshot with no CFR citation, because there is no rule
        # behind it. § 205.103(b) asks for records sufficient to demonstrate compliance and
        # does not enumerate photographs. Where a photograph DOES appear in the source
        # material it is always bound to one specific fact: USDA's crop documentation forms
        # use a dated photo of the buffer marking; Quick Organics asks growers to photograph
        # the seed tag, the product label, the sanitizer label, the invoice. Nobody asks for a
        # photo COUNT, and no certifier has a floor of ten.
        #
        # Emitting REVIEW put "25 events, 0 photos" in amber "Needs attention", beside
        # § 205.203(c)(2), on a card titled "Before your certifier packet" — telling a grower
        # their packet falls short of a requirement that does not exist. A caveat sentence does
        # not fix that: the badge and the colour do the talking.
        #
        # The count is still worth surfacing — photo evidence carries the BUYER story, and the
        # packet keeps its Photo Evidence section — so this stays in the snapshot as INFO and
        # drops out of the readiness card's action list (see ACTIONABLE_READINESS_STATUSES).
        snapshot_rows.append(
            (
                "Documentation depth",
                "PASS" if photos_total >= 10 else "INFO",
                (
                    f"{len(all_events)} events, {photos_total} photos. Photos are not required by "
                    "the NOP; they corroborate a specific claim when one needs it — a dated shot "
                    "of the flagged buffer rows, a seed tag, an input label."
                    if photos_total < 10
                    else f"{len(all_events)} events, {photos_total} photos"
                ),
            )
        )

        # Deterministic pointer to the section carrying the full evidence for any row that is
        # not PASS. Travels with the data so a non-PDF caller gets the same breadcrumb.
        section_hint_by_label = {
            "Organic System Plan (§ 205.201)": "Organic System Plan section",
            "Inputs not matched to the plan's approved inputs (§ 205.400(f)(2))": "Inputs Not Matched to the Plan's Approved Inputs section",
            # 🔴 2026-09-06 — these named sections that do not exist under those titles
            # ("Chemical Log", "Soil Management", "General Documentation"). A finding whose
            # "where to look" line points at a heading the reader cannot find is worse than one
            # with no pointer. Kept in step with the _section_header() calls below by
            # test_packet_section_vocabulary.py.
            "Input traceability (§ 205.103)": "Input Material Application Records section",
            "Record completeness — chemical (§ 205.103(b)(2))": "Input Material Application Records section",
            "Compost (§ 205.203(c)(2))": "Soil & Water Management section",
            "Raw manure interval (§ 205.203(c)(1))": "Soil & Water Management section",
            "Raw manure interval (§ 205.203(c)(1)(ii))": "Soil & Water Management section",
            "Raw manure interval (§ 205.203(c)(1)(iii))": "Soil & Water Management section",
            "Contamination log (§ 205.272)": "Training, Maintenance & Other Farm Records section",
            "Land requirements (§ 205.202)": "Farm Overview section",
            "OFPP (§ 205.201(a)(3))": "SOE Compliance Status section",
            "Lot traceability (§ 205.307 / § 205.103(b)(2))": "Traceability section",
            "Documentation depth": "Event logs + Photo Evidence sections",
        }

        return [
            {
                "label": label,
                # Run 8 (R8-27): a stable key per row, so a reader in another language gets the
                # row's name from its own catalogue instead of this English label.
                "row_key": readiness_row_key(label),
                "status": status,
                "detail": detail,
                "section_hint": (section_hint_by_label.get(label) if status not in ("PASS", "NA") else None),
            }
            for label, status, detail in snapshot_rows
        ]

    def _build_compliance_snapshot(self):
        """Render the page-1 Compliance Snapshot table.

        The row COMPUTATION lives in compliance_snapshot_rows(); this method only turns those
        rows into flowables.
        """

        # Computed once — the row build walks every event relation, so calling it twice would
        # double that work for no reason.
        rows = self.compliance_snapshot_rows()
        snapshot_rows = [(r["label"], r["status"], r["detail"]) for r in rows]
        section_hint_by_label = {r["label"]: r["section_hint"] for r in rows if r["section_hint"]}

        def status_paragraph(status):
            # MEASURED on white, WCAG AA normal text (4.5:1): #2E7D32 = 5.13, #BF360C = 5.60,
            # #B71C1C = 6.57, #555555 = 7.46. REVIEW was #E65100 — the theme's amber ceiling —
            # which is only 3.79:1 and FAILED, on the most-repeated word in the auditor pre-read
            # table. Same failure class as the app's amber pills: the token is the darkest amber
            # available, which is not the same as an accessible one.
            # Four states, not three. "NA" exists because DOCUMENTED was being printed for two
            # different things: "we checked this and it holds" and "there was nothing here to
            # check". A certifier scanning this column cannot tell those apart, and the second
            # one is not a pass — it is an absence. Compare the contamination-log row, which
            # already words it correctly ("0 incidents (logging system active)").
            color = {
                "PASS": "#2E7D32",
                "REVIEW": "#BF360C",
                "FAIL": "#B71C1C",
                "NA": "#5F6B5C",
                # INFO is reported, not owed — grey like NA so it cannot be mistaken for a gap.
                "INFO": "#5F6B5C",
            }.get(status, "#555555")
            # "N/A", not "NOT APPLICABLE": the Documentation column is 0.95in, sized for
            # "DOCUMENTED", and the longer phrase wrapped onto two lines in every absence row.
            mark = {
                "PASS": "DOCUMENTED",
                "REVIEW": "REVIEW",
                "FAIL": "GAP",
                "NA": "N/A",
                "INFO": "FYI",
            }.get(status, status)
            return Paragraph(
                f'<b><font color="{color}">{mark}</font></b>',
                ParagraphStyle("snap_status", parent=self._styles["body"], fontSize=8, alignment=TA_CENTER),
            )

        def detail_paragraph(text):
            return Paragraph(
                self._safe_narrative(str(text)),
                ParagraphStyle("snap_detail", parent=self._styles["body"], fontSize=8, leading=10),
            )

        def detail_paragraph_with_hint(detail_text, hint_text):
            """Escape the data-origin detail, then append a trusted-origin
            section-hint fragment verbatim. The hint is Trazo-authored and
            safe to pass as ReportLab inline markup (``<i>...</i>``); the
            detail comes from user/DB data and must be escaped."""
            safe_detail = self._safe_narrative(str(detail_text))
            return Paragraph(
                f"{safe_detail} <i>({hint_text})</i>",
                ParagraphStyle("snap_detail", parent=self._styles["body"], fontSize=8, leading=10),
            )

        # textColor is set on each ParagraphStyle, NOT left to the TableStyle below. A
        # TableStyle ("TEXTCOLOR", (0, 0), (-1, 0), colors.white) colours plain string cells;
        # it does not reach text inside a Paragraph flowable, which carries its own style. So
        # these three headers were rendering in the body colour on the dark-green band and only
        # LOOKED white-ish at display resolution — the whitest of them was antialiasing.
        _snap_header_style = dict(
            parent=self._styles["body"],
            fontSize=8,
            fontName="Helvetica-Bold",
            textColor=colors.white,
        )
        header = [
            Paragraph("<b>Compliance check</b>", ParagraphStyle("snap_h1", **_snap_header_style)),
            Paragraph("<b>Documentation</b>", ParagraphStyle("snap_h2", alignment=TA_CENTER, **_snap_header_style)),
            Paragraph("<b>Detail</b>", ParagraphStyle("snap_h3", **_snap_header_style)),
        ]
        # Section-lookup table: when a snapshot row is NOT PASS, the inspector
        # needs a deterministic pointer to the section that carries the full
        # evidence. Without this, a FAIL row on page 1 reads as an unresolved
        # finding rather than a "see page N" breadcrumb. Key is the row label
        # as written above; value is the downstream section header text.
        table_data = [header]
        for label, status, detail in snapshot_rows:
            hint = None
            # NA joins PASS here: "no compost events this period" needs no breadcrumb to a
            # compost section that will also be empty.
            if status not in ("PASS", "NA"):
                hint_candidate = section_hint_by_label.get(label)
                if hint_candidate and hint_candidate.lower() not in (detail or "").lower():
                    hint = hint_candidate
            if hint:
                detail_cell = detail_paragraph_with_hint(detail, f"see {hint}")
            else:
                detail_cell = detail_paragraph(detail)
            table_data.append(
                [
                    detail_paragraph(label),
                    status_paragraph(status),
                    detail_cell,
                ]
            )

        # Documentation column is wide enough for the "DOCUMENTED" mark on one line.
        col_widths = [2.6 * inch, 0.95 * inch, 3.45 * inch]
        snap_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        snap_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), TRAZO_GREEN_DARK),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                    ("ALIGN", (1, 0), (1, 0), "CENTER"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ("TOPPADDING", (0, 0), (-1, 0), 4),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                    ("GRID", (0, 0), (-1, -1), 0.4, MID_GRAY),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 1), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ]
            )
        )

        return [
            Paragraph(
                "<b>Documentation Snapshot</b> — auditor pre-read",
                ParagraphStyle(
                    "snap_title",
                    parent=self._styles["section_header"],
                    fontSize=11,
                    spaceBefore=2,
                    spaceAfter=4,
                ),
            ),
            snap_table,
            Paragraph(
                "DOCUMENTED = the supporting record is on file in Trazo. REVIEW = the record "
                "is present but needs inspector attention or is incomplete. GAP = a required "
                "record appears to be missing. N/A = this requirement has nothing to check on "
                "this production — it is an absence of records, not a clean result. These marks "
                "reflect documentation status in "
                "Trazo, not a compliance determination — the certifying agent makes the "
                "compliance decision. Each row links to its source section in the body of "
                "this report. Section headers cross-reference the corresponding Common OSP Grower "
                # RANGE CORRECTED 2026-08-19 against CCOF's own "Guide to Grower OSP Forms"
                # (NOPB50, May 2025). CCOF publishes G3.0–G8.0 plus sub-forms; there is no
                # G2.0 and no G9.0 in their set. The old text sent an inspector looking for two
                # forms that do not exist — a claim of correspondence wider than the
                # correspondence. (G2.0 elsewhere in this file is TRAZO's own OSP module
                # numbering, which is internal and unrelated to CCOF's.)
                "OSP form numbers (G3.0–G8.0) for inspector navigation.",
                self._styles["footer_note"],
            ),
        ]

    # ------------------------------------------------------------------
    # Pre-Export Consistency Check — cross-references production header
    # fields against the raw event stream. An inspector conducting a
    # supply-chain traceability audit (§ 205.501(a)(21)) will ask:
    #   - "Your sales invoice says 1700 boxes × 25 lb = 42,500 lb but your
    #      packing-shed event says 1500 cartons. Which is on the lot?"
    #   - "Your Production record says lot SV-AVO-2026-001 but your packing-
    #      shed event narrative says SVR-2026-HA-001. Which is on the boxes?"
    #   - "Your sales record says Whole Foods but your post-harvest narrative
    #      says OGC pickup. How many channels is this fruit moving through?"
    # Trazo's value-add is catching these before the certifier does.
    # ------------------------------------------------------------------

    # Tolerance for the harvest-yield vs event-narrative cross-check.
    # Field-to-narrative deltas are common (thinning estimates vs post-
    # thinning yields, drying losses, carrier-weight rounding). ±15% leaves
    # room for that without tolerating an order-of-magnitude mismatch.
    CONSISTENCY_YIELD_TOLERANCE = 0.15

    @staticmethod
    def _extract_pound_values(text: str):
        """
        Extract numbers quoted in 'lb' / 'lbs' / 'pound(s)' from a free-text
        description. Handles commas ("45,000 lb"), decimals ("11,200.5 lbs"),
        and mixed unit adjacency. Returns a list of floats. Used by the
        consistency linter to find yield claims inside event narratives.
        """
        import re

        if not text:
            return []
        values = []
        # Match e.g. "45,000 lb", "11200 lbs", "5,080 kg (11,200 pounds)"
        pattern = re.compile(
            r"(\d[\d,]*(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds)\b",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            try:
                values.append(float(m.group(1).replace(",", "")))
            except ValueError:
                continue
        return values

    @staticmethod
    def _extract_lot_ids(text: str):
        """
        Pull lot-ID-shaped tokens from a narrative (``Lot: <ID>`` or common
        alphanumeric prefixes like ``SV-AVO-`` / ``SVR-`` seen on Solana
        Verde packing labels). Case-insensitive. Used by the consistency
        linter so an event that mentions a different lot ID than the
        production record triggers a finding.
        """
        import re

        if not text:
            return []
        # "Lot: <token>" explicit mentions — strongest signal
        explicit = re.findall(r"[Ll]ot\s*[:#]\s*([A-Z0-9][A-Z0-9\-]{4,})", text)
        return [tok.strip() for tok in explicit]

    def _build_consistency_findings(self):
        """
        Run cross-consistency checks and return a list of flowables for the
        cover page. Returns an empty list when everything reconciles — an
        all-clean PDF shows only the Compliance Snapshot, no additional
        section. When one or more checks fail, a small table surfaces each
        finding with its source and the two conflicting values.
        """
        p = self.production
        findings = []

        # ---------- Check 1: yield reconciliation -------------------------
        # Production header yield vs the yield numbers appearing in harvest
        # event descriptions. Only flag when the delta exceeds the
        # tolerance — normal shrinkage / rounding is tolerated. Harvest
        # events are ProductionEvent rows with type == "HA"; the
        # WeatherEvent code "HH" (High Humidity) is a distinct model and
        # MUST NOT be mixed in here — an earlier draft did, with no
        # effective harm since production events cannot have type "HH",
        # but the test reads wrong.
        harvest_events = [ev for ev in p.history_productionevent_events.all() if ev.type == "HA"]
        narrative_yields = []
        for ev in harvest_events:
            narrative_yields.extend(self._extract_pound_values(ev.description or ""))
        header_yield_lb = None
        if p.production_amount and p.production_unit:
            unit = str(p.production_unit).lower().strip()
            if unit in ("lb", "lbs", "pound", "pounds"):
                header_yield_lb = float(p.production_amount)
            elif unit in ("kg", "kilogram", "kilograms"):
                header_yield_lb = float(p.production_amount) * 2.20462
            elif unit in ("t", "ton", "tons"):
                # Short ton (US) = 2000 lb. We do NOT attempt to detect
                # metric tonne here — ambiguous unit label; skip rather
                # than guess and risk a false-positive finding.
                header_yield_lb = float(p.production_amount) * 2000.0
        if header_yield_lb and narrative_yields:
            # Smart-match: pick the narrative value CLOSEST to the header
            # yield, not the MAX. A farmer's narrative may legitimately
            # quote multiple sub-totals ("Field A: 25,000 lb, Field B:
            # 20,000 lb, total 45,000 lb") and MAX would arbitrarily pick
            # the largest regardless of whether a matching total appears.
            # Closest-match gives the benefit of the doubt — flag only
            # when NO narrative value lands within tolerance of the header.
            closest = min(narrative_yields, key=lambda v: abs(v - header_yield_lb))
            delta_pct = abs(closest - header_yield_lb) / header_yield_lb
            if delta_pct > self.CONSISTENCY_YIELD_TOLERANCE:
                # Report the full spread so the farmer sees what the
                # linter saw. Deduplicate + sort for stable output.
                unique_sorted = sorted({int(round(v)) for v in narrative_yields})
                narrative_summary = ", ".join(f"{v:,}" for v in unique_sorted)
                findings.append(
                    (
                        "Yield reconciliation",
                        (
                            f"Production header: {int(header_yield_lb):,} lb · "
                            f"Harvest-event narrative value(s): {narrative_summary} lb · "
                            f"closest delta {delta_pct * 100:.1f}% (tolerance ±"
                            f"{int(self.CONSISTENCY_YIELD_TOLERANCE * 100)}%)"
                        ),
                    )
                )

        # ---------- Check 2: quantity_sold vs packed-carton narrative ------
        # quantity_sold × box_weight should match the carton count mentioned
        # in the post-harvest event description. A mismatch means the
        # packing-shed log and the sales invoice are telling different
        # stories — exactly what a supply-chain traceability audit asks.
        import re

        ph_events = [ev for ev in p.history_productionevent_events.all() if ev.type == "PH"]
        # Read through the disclosure: this branched on the legacy `p.quantity_sold` alone, so
        # an operation recording sales as SalesRecord rows (the SOE-supported path) silently
        # skipped this cross-check entirely — a missing audit check reads as a clean one.
        #
        # The unit guard is new and deliberate. `box_weight_lb` only converts a COUNT of
        # containers; multiplying a pounds figure by it produced a fabricated number in a
        # certifier document. Legacy rows frequently left the unit blank while pairing with
        # box_weight_lb, so blank is treated as boxes there and never for SalesRecord rows,
        # which always carry an explicit unit.
        _boxes_disclosure = resolve_sales_disclosure(p)
        _sold_qty_boxes = (
            _boxes_disclosure.quantity
            if _is_box_unit(
                _boxes_disclosure.quantity_unit,
                blank_counts_as_boxes=_boxes_disclosure.source == "legacy",
            )
            else None
        )
        if ph_events and _sold_qty_boxes and p.box_weight_lb:
            sold_lb_equivalent = float(_sold_qty_boxes) * float(p.box_weight_lb)
            narrative_cartons = []
            for ev in ph_events:
                for m in re.finditer(r"(\d[\d,]*)\s*(?:cartons?|boxes)", ev.description or "", re.IGNORECASE):
                    try:
                        narrative_cartons.append(int(m.group(1).replace(",", "")))
                    except ValueError:
                        continue
            if narrative_cartons and sold_lb_equivalent:
                # Use closest-match to the sold total for the same reason
                # as the yield check: a PH narrative may quote pallet /
                # batch sub-totals as well as the grand total, and MAX
                # would pick the largest regardless of whether a matching
                # total is present.
                sold_boxes_equivalent = sold_lb_equivalent / float(p.box_weight_lb)
                closest_cartons = min(narrative_cartons, key=lambda v: abs(v - sold_boxes_equivalent))
                packed_lb = closest_cartons * float(p.box_weight_lb)
                delta_pct = abs(packed_lb - sold_lb_equivalent) / sold_lb_equivalent
                if delta_pct > self.CONSISTENCY_YIELD_TOLERANCE:
                    unique_sorted = sorted(set(narrative_cartons))
                    narrative_summary = ", ".join(f"{v:,}" for v in unique_sorted)
                    findings.append(
                        (
                            "Packed cartons vs sold quantity",
                            (
                                f"Packing-shed narrative: {narrative_summary} cartons · "
                                f"closest match {closest_cartons:,} × {float(p.box_weight_lb):g} lb "
                                f"= {int(packed_lb):,} lb · "
                                # Must print the SAME figure the math above used. Printing the
                                # legacy field here while computing from the disclosure would
                                # make the sentence contradict its own arithmetic.
                                f"Sales record: {_fmt_float(_sold_qty_boxes)} "
                                f"{_boxes_disclosure.quantity_unit or 'units'} × "
                                f"{float(p.box_weight_lb):g} lb = {int(sold_lb_equivalent):,} lb · "
                                f"delta {delta_pct * 100:.1f}%"
                            ),
                        )
                    )

        # ---------- Check 3: lot ID in production vs event narratives ------
        header_lot = (p.lot_id or "").strip()
        if header_lot:
            lot_mismatches = set()
            for ev in p.history_productionevent_events.all():
                for tok in self._extract_lot_ids(ev.description or ""):
                    if tok.upper() != header_lot.upper():
                        lot_mismatches.add(tok)
            if lot_mismatches:
                findings.append(
                    (
                        "Lot ID consistency (§ 205.307)",
                        (
                            f"Production record lot: {header_lot} · "
                            f"Other lot ID(s) in event narratives: "
                            f"{', '.join(sorted(lot_mismatches))}. "
                            "Inspector will ask which lot is on the non-retail containers."
                        ),
                    )
                )

        # ---------- Check 4: drift-response notification delay -------------
        # § 205.400(f)(1) requires the producer to notify the certifying
        # agent "immediately" when a prohibited substance has been applied
        # or come into contact with a certified operation. A multi-day gap
        # between the incident date and the certifier-notified date is the
        # kind of finding a CCOF inspector would circle in red even if the
        # corrective action was eventually taken. Surface the gap here so
        # the farmer addresses it BEFORE the inspector does. 3-day threshold
        # is lenient — "immediately" reasonably accommodates a weekend plus
        # a verification phone call. Longer than that needs a why.
        try:
            contamination_incidents = [
                ev for ev in related_events(p, "history_generalevent_events", is_contamination_incident=True)
            ]
        except Exception:  # noqa: BLE001 — linter degrades to no finding
            contamination_incidents = []
        notify_delay_rows = []
        from datetime import date as _date
        from datetime import datetime as _datetime

        for cev in contamination_incidents:
            incident_date = getattr(cev, "date", None)
            notify_date = getattr(cev, "certifier_notification_date", None)
            if incident_date is None or notify_date is None:
                continue
            # ``CommonEvent.date`` is a datetime; ``certifier_notification_date``
            # is a date. Subtracting datetime from date raises TypeError, so
            # we MUST explicitly downcast datetime → date. Note that
            # ``isinstance(datetime_obj, date)`` returns True (datetime is a
            # subclass of date), so a ``not isinstance(..., type(notify_date))``
            # branch would silently skip the conversion and hide this bug —
            # do the conversion unconditionally based on the concrete type.
            if isinstance(incident_date, _datetime):
                incident_date = incident_date.date()
            if not isinstance(incident_date, _date) or not isinstance(notify_date, _date):
                continue
            try:
                gap_days = (notify_date - incident_date).days
            except Exception:  # noqa: BLE001 — odd date types shouldn't kill the linter
                continue
            if gap_days > 3:
                notify_delay_rows.append((cev, gap_days, incident_date, notify_date))
        if notify_delay_rows:
            # One row per incident so the inspector sees each gap distinctly.
            for cev, gap_days, incident_date, notify_date in notify_delay_rows:
                source = ""
                try:
                    if cev.contamination_source:
                        source = cev.get_contamination_source_display()
                except Exception:
                    source = ""
                source_suffix = f" ({source})" if source else ""
                findings.append(
                    (
                        "Drift-response notification delay (§ 205.400(f)(1))",
                        (
                            f"Contamination incident {incident_date}{source_suffix} · "
                            f"certifier notified {notify_date} · gap {gap_days} days. "
                            "§ 205.400(f)(1) requires 'immediately.' Inspector will ask "
                            "why the delay — document the reason in the event record."
                        ),
                    )
                )

        # ---------- Check 5: downstream handler consistency ----------------
        # sold_to (sales record) should match any handler named in the OSP
        # (a)(5) commingling narrative AND any handler/pickup mentioned in
        # the post-harvest event narrative. Detect mismatched distributor /
        # retailer names — the classic "packing says OGC, sales says Whole
        # Foods" signal.
        # Same read-through: branching on the legacy field alone meant an operation whose
        # buyers live in SalesRecord skipped the handler-consistency check silently.
        sold_to = resolve_sales_disclosure(p).buyer
        if sold_to:
            handler_tokens = set()
            recorded_handlers: set = set()
            # Scan post-harvest narratives for "<Name> pickup" or
            # "delivery to <Name>" — simple tokeniser that looks for a
            # capitalised two-word name adjacent to a handler verb.
            # The verb portion uses an inline (?i:...) case-insensitive
            # group so "Transport" / "transport" / "Delivery" / "delivery"
            # all match, while the capture group stays case-sensitive —
            # we need "[A-Z][A-Za-z&]+" to match Capitalized words only,
            # otherwise a phrase like "Transport to Mission Produce uses
            # Missions" swallows the lowercase "uses" and captures four
            # words instead of the intended two.
            # "takes" and "goes to" were missing, which is how a real pilot's
            # "Organically Grown Company takes the fresh blueberries" passed this check
            # unseen (found 2026-08-28 auditing the checker itself).
            handler_verbs = re.compile(
                r"(?i:pickup by|pickup on [^\n]{0,30}?by|delivery to|shipped to|goes to|"
                r"sold to|takes|transport(?:ed)? to)\s+"
                r"([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,3})",
            )
            pickup_verbs = re.compile(
                r"([A-Z][A-Za-z&]+(?:\s+[A-Z][A-Za-z&]+){0,3})\s+(?i:pickup)\b",
            )
            for ev in ph_events:
                text = ev.description or ""
                for m in handler_verbs.finditer(text):
                    handler_tokens.add(m.group(1).strip())
                for m in pickup_verbs.finditer(text):
                    handler_tokens.add(m.group(1).strip())
            # Also pull handler names out of the OSP narrative, and load the facilities the
            # operation actually has on file.
            try:
                establishment = p.parcel.establishment

                # A name that matches a facility ON FILE is not a discrepancy — it is the record
                # doing its job. Comparing prose against prose could never tell the difference,
                # which is why this check had never once fired on a real mismatch.
                #
                # Loaded INDEPENDENTLY of the OSP: a facility record belongs to the
                # establishment, not to a plan version, and an operation mid-renewal has only a
                # DRAFT plan. Nesting this under `if osp:` (as the first cut did) meant exactly
                # the farms most likely to be assembling a packet had no facilities to compare
                # against, so every handler they named read as a mismatch.
                for facility in establishment.post_harvest_facilities.all():
                    if facility.name:
                        recorded_handlers.add(facility.name)

                from certifications.models import OrganicSystemPlan

                osp = (
                    OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
                    .order_by("-version_number")
                    .first()
                )
                if osp:
                    # § 205.201(a)(5) is where commingling lives, but the sales-channel answer
                    # that names the handler compiles into (a)(3) `monitoring_plan` — so a
                    # check reading only (a)(5) was blind to the one sentence most likely to
                    # name a handler. Read all three narrative homes (2026-08-28).
                    sections = osp.sections or {}
                    for key in ("commingling_barriers", "monitoring_plan", "practices_procedures"):
                        narrative = (sections.get(key) or {}).get("narrative", "") or ""
                        for m in handler_verbs.finditer(narrative):
                            handler_tokens.add(m.group(1).strip())
                        for m in pickup_verbs.finditer(narrative):
                            handler_tokens.add(m.group(1).strip())
            except Exception:  # noqa: BLE001 — a linter finding must never take the PDF down
                # Deliberate fail-open, but never silent: without the log this degrades into
                # "the check found nothing", which reads identically to "the check passed".
                logger.exception("Handler-chain check could not load OSP or facility records")

            def _normalise(s: str) -> str:
                return re.sub(r"[^a-z0-9]", "", s.lower())

            sold_to_norm = _normalise(sold_to)
            recorded_norm = {_normalise(name) for name in recorded_handlers if name}

            def _accounted_for(token: str) -> bool:
                tok = _normalise(token)
                if not tok:
                    return True
                # Consistent if it is the buyer, or references it — handles "Mission Produce →
                # Whole Foods" chains where Mission is the intermediate handler.
                if tok in sold_to_norm or sold_to_norm in tok:
                    return True
                # Or if it is a facility the operation has on file. Before the handler record
                # reached the plan layer there was nothing to compare against, so every named
                # handler looked like a discrepancy or none did.
                return any(tok in rec or rec in tok for rec in recorded_norm)

            handler_mismatches = [tok for tok in handler_tokens if not _accounted_for(tok)]
            # Flag only when ≥2 distinct handler names appear that do not
            # match the sales-record retailer. A single-handler mismatch
            # (e.g. "Mission Produce" as the intermediate handler with
            # Whole Foods as the retailer) is usually a legitimate
            # handoff chain, not a discrepancy — the farmer names the
            # handler in OSP (a)(5) and mentions them at packing-shed
            # pickup, which is exactly the correct paper trail. Two or
            # more distinct non-retailer names is the channel-confusion
            # signal we actually want ("packing says OGC, OSP says
            # Mission, sales says Whole Foods" = three channels = ask).
            if handler_mismatches and len(handler_mismatches) >= 2:
                findings.append(
                    (
                        "Handler chain (§ 205.201(a)(5))",
                        (
                            f"Sales record: {sold_to} · "
                            f"Other handler(s) named in event/OSP narratives: "
                            f"{', '.join(sorted(set(handler_mismatches)))}. "
                            "Confirm the handoff chain with the inspector."
                        ),
                    )
                )

        # ---------- Check 6: manure interval vs crop-rule consistency -----
        # Per eCFR 7 CFR 205.203(c)(1), the required pre-harvest interval is
        # determined by whether the edible portion contacts the soil:
        # (c)(1)(ii) 120 days when it does, (c)(1)(iii) 90 days when it
        # does not. Farmers enter their interval selection directly on the
        # SoilManagementEvent form; a mismatch between what the farmer
        # selected and what the crop's soil-contact flag dictates is a
        # classic inspector-will-flag signal ("operator doesn't understand
        # their own practice standard"). Surface it here so the producer
        # fixes it before the inspection.
        try:
            from history.models import SoilManagementEvent

            manure_events_strict = list(
                SoilManagementEvent.objects.filter(
                    history_id=getattr(p, "id", None),
                )
                .exclude(manure_harvest_interval__in=["", "na"])
                .exclude(manure_harvest_interval__isnull=True)
            )
        except Exception:  # noqa: BLE001 — linter must not kill the PDF
            manure_events_strict = []
        if manure_events_strict:
            rule = self._manure_interval_rule_for_crop()
            expected_days = rule["days"]  # 90 or 120
            expected_cite = rule["cite"]
            # Build a label describing what the crop rule dictates so the
            # finding text reads as a question the inspector would ask.
            if expected_days == 90:
                crop_description = "tree / canopy crop (edible portion does NOT contact soil)"
            else:
                crop_description = "soil-contact crop (edible portion has direct contact with soil)"
            mismatched = []
            for mev in manure_events_strict:
                try:
                    farmer_days = int(mev.manure_harvest_interval)
                except (TypeError, ValueError):
                    continue
                if farmer_days != expected_days:
                    mismatched.append((mev, farmer_days))
            if mismatched:
                # One row per mismatched event so the farmer sees each
                # date/interval distinctly. Keeps the finding actionable.
                for mev, farmer_days in mismatched:
                    event_date = getattr(mev, "date", None)
                    event_date_str = (
                        event_date.date().isoformat()
                        if hasattr(event_date, "date")
                        else (event_date.isoformat() if event_date else "unknown date")
                    )
                    findings.append(
                        (
                            f"Manure interval vs crop rule ({expected_cite})",
                            (
                                f"Soil event {event_date_str}: farmer selected "
                                f"{farmer_days}-day interval. Crop rule derived "
                                f"from {expected_cite} requires {expected_days}-day "
                                f"interval for this production — "
                                f"{crop_description}. Inspector will ask why the "
                                "selected interval does not match the crop's "
                                "soil-contact classification."
                            ),
                        )
                    )

            # The plan itself, not the label on it. The loop above asks whether the farmer
            # picked the interval their crop requires; this asks whether the dates they wrote
            # down actually clear the interval they picked. The two are independent — selecting
            # the correct 120 days for a soil-contact crop passes the check above and still
            # violates § 205.203(c)(1) if harvest is planned 60 days after application. This
            # was the gap: both dates were printed in the manure table and never compared.
            for mev in manure_events_strict:
                planned = getattr(mev, "manure_harvest_date_planned", None)
                applied = getattr(mev, "manure_application_date", None)
                if not (planned and applied):
                    continue
                try:
                    farmer_days = int(str(mev.manure_harvest_interval).split("_")[0])
                except (TypeError, ValueError):
                    continue
                # A date column can hold an ISO STRING on rows written outside the ORM, and
                # `str - date` raises TypeError, which the surrounding `except (ValueError,
                # AttributeError)` idiom in this file does not catch. An unparseable date must
                # cost this one finding, never the whole export.
                try:
                    planned_d = planned.date() if hasattr(planned, "date") else planned
                    applied_d = applied.date() if hasattr(applied, "date") else applied
                    actual_gap = (planned_d - applied_d).days
                except (TypeError, ValueError, AttributeError):
                    continue

                if actual_gap < 0:
                    # Harvest planned BEFORE the manure went on. Not an interval shortfall —
                    # one of the two dates is wrong — and reporting it as "N days short" would
                    # send the farmer to fix the interval instead of the typo.
                    findings.append(
                        (
                            "Manure dates out of order (§ 205.203(c)(1))",
                            (
                                f"Manure applied {applied_d.isoformat()} but harvest is planned for "
                                f"{planned_d.isoformat()}, which is {abs(actual_gap)} days EARLIER. "
                                "One of the two dates is wrong; the interval cannot be checked "
                                "until they are in order."
                            ),
                        )
                    )
                elif actual_gap < farmer_days:
                    findings.append(
                        (
                            "Planned harvest inside the manure interval (§ 205.203(c)(1))",
                            (
                                f"Manure applied {applied_d.isoformat()} with a {farmer_days}-day "
                                f"interval selected, but harvest is planned for "
                                f"{planned_d.isoformat()} — {actual_gap} days later, "
                                f"{farmer_days - actual_gap} days short. Either the harvest plan "
                                "moves out, or this application cannot be used on this crop."
                            ),
                        )
                    )

        # ---------- Check 7: OSP narrative cert-continuity vs metadata ----
        # When the OSP narrative claims "since YEAR" or "first certified
        # YEAR" (a transition / 36-month-history / continuous-management
        # claim under § 205.401(c) or § 205.202), and that year does NOT
        # match the earliest certification on file, an inspector reads it
        # as either (a) a record-keeping gap (the cert metadata is
        # incomplete) or (b) an unsupported land-eligibility claim. Either
        # way it is a question the producer must be ready to answer.
        # Tolerance: ±1 year — a "since 2012" narrative against a 2013
        # cert is well within the rounding farmers use when speaking
        # casually; a 6-year gap (2012 vs 2018) is the signal we want.
        try:
            from certifications.models import Certification as _Cert
            from certifications.models import OrganicSystemPlan as _OSP

            est_for_cert = p.parcel.establishment
        except Exception:  # noqa: BLE001
            est_for_cert = None
        if est_for_cert is not None:
            # Earliest cert effective_date on file (active or historical) —
            # represents the operation's documented certification chain.
            try:
                earliest_cert_date = None
                for c in _Cert.objects.filter(establishment=est_for_cert).only("effective_date"):
                    if c.effective_date is None:
                        continue
                    if earliest_cert_date is None or c.effective_date < earliest_cert_date:
                        earliest_cert_date = c.effective_date
            except Exception:  # noqa: BLE001
                earliest_cert_date = None
            if earliest_cert_date is not None:
                # Pull narrative text we already need to scan. Look at the
                # active OSP's (a)(1) / (a)(6) sections specifically.
                narrative_text = ""
                try:
                    osp = (
                        _OSP.objects.filter(establishment=est_for_cert, status="active")
                        .order_by("-version_number")
                        .first()
                    )
                    if osp:
                        secs = osp.sections or {}
                        for key in ("practices_procedures", "additional_certifier_info"):
                            sec = secs.get(key) or {}
                            narrative_text += " " + (sec.get("narrative", "") or "")
                except Exception:  # noqa: BLE001
                    narrative_text = ""
                # Match certification-context year claims ONLY. Bare "since
                # 2012" is too loose — a farmer saying "using drip
                # irrigation since 2020" is NOT making a cert-continuity
                # claim and would false-positive. We require the year to
                # sit alongside a word that unambiguously anchors the
                # claim to certification / organic status: "first
                # certified", "first certified in", "certified organic",
                # "organic since", "certified since". Years 1990-2099.
                year_pattern = re.compile(
                    r"(?i:\b(?:first\s+certified(?:\s+in)?|certified\s+organic|organic\s+since|certified\s+since)\s+)(\d{4})\b"
                )
                narrative_years = []
                for m in year_pattern.finditer(narrative_text):
                    try:
                        y = int(m.group(1))
                        if 1990 <= y <= 2099:
                            narrative_years.append(y)
                    except ValueError:
                        continue
                if narrative_years:
                    # Smallest narrative year is the strongest claim
                    # ("since 2012" beats "since 2015" — they imply each
                    # other but 2012 is the load-bearing assertion).
                    earliest_narrative_year = min(narrative_years)
                    earliest_cert_year = earliest_cert_date.year
                    delta_years = earliest_cert_year - earliest_narrative_year
                    # Flag only when narrative reaches MORE than 1 year
                    # earlier than the metadata. The reverse direction
                    # (cert older than narrative claim) is normal — a
                    # producer may simply not have updated the OSP text.
                    if delta_years > 1:
                        findings.append(
                            (
                                "Cert continuity vs OSP narrative (\u00a7 205.401(c))",
                                (
                                    f"OSP narrative claims continuous organic "
                                    f"management / first-certified year "
                                    f"{earliest_narrative_year}; earliest "
                                    f"certification on file is "
                                    f"{earliest_cert_date.isoformat()} "
                                    f"({delta_years}-year gap). \u00a7 205.401(c) "
                                    "requires a history of previous applications. "
                                    "Either upload the missing certificate(s) "
                                    "from the gap years or update the OSP "
                                    "narrative to match the documented chain."
                                ),
                            )
                        )

        # ---------- Render ------------------------------------------------
        if not findings:
            return []

        header = [
            Paragraph(
                "<b>Check</b>",
                ParagraphStyle("cons_h1", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold"),
            ),
            Paragraph(
                "<b>Detail</b>",
                ParagraphStyle("cons_h2", parent=self._styles["body"], fontSize=8, fontName="Helvetica-Bold"),
            ),
        ]
        cell_style = ParagraphStyle("cons_cell", parent=self._styles["body"], fontSize=8, leading=10)
        table_data = [header]
        for label, detail in findings:
            table_data.append(
                [
                    Paragraph(self._safe_narrative(label), cell_style),
                    Paragraph(self._safe_narrative(detail), cell_style),
                ]
            )
        col_widths = [2.2 * inch, 4.8 * inch]
        cons_table = Table(table_data, colWidths=col_widths, repeatRows=1)
        cons_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E65100")),  # orange "review"
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 8),
                    ("ALIGN", (0, 0), (-1, 0), "LEFT"),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                    ("TOPPADDING", (0, 0), (-1, 0), 4),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT_GRAY]),
                    ("GRID", (0, 0), (-1, -1), 0.4, MID_GRAY),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 1), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
                ]
            )
        )
        return [
            Paragraph(
                "<b>Pre-Export Consistency Check</b> — cross-reference against event stream",
                ParagraphStyle(
                    "cons_title",
                    parent=self._styles["section_header"],
                    fontSize=11,
                    spaceBefore=2,
                    spaceAfter=4,
                ),
            ),
            cons_table,
            Paragraph(
                "These findings cross-check the production header (yield, sales, lot, handler) "
                "against what the individual event narratives actually say. Resolve each row "
                "before handing this PDF to a certifier — under SOE § 205.103(b)(2) and § 205.501(a)(21), "
                "a supply-chain traceability audit will ask the same questions. Trazo's value-add is "
                "catching these gaps first. An empty section (no findings shown) means all cross-checks passed.",
                self._styles["footer_note"],
            ),
        ]

    # ------------------------------------------------------------------
    # Section 2: Farm Overview
    # ------------------------------------------------------------------

    def _build_farm_overview(self):
        p = self.production
        elements = [self._section_header("Farm Overview")]

        try:
            est = p.parcel.establishment
        except AttributeError:
            elements.append(self._body("Farm data not available."))
            return elements

        # Rows required by § 205.400(a): operator legal identity + contact info.
        # Render blanks as "(not provided)" rather than em-dash so an inspector
        # sees an explicit disclosure gap instead of ambiguous silence.
        #
        # 🔴 2026-08-19: these read the establishment only, so a dress-rehearsal farm printed
        # "(not provided)" for country, contact person, phone AND email — all four of which
        # the operator HAD given, at company level, in the signup wizard. The farm wizard
        # never asks for them again. § 205.400(a) wants the operator's contact details, not
        # specifically the parcel's, so the company is a legitimate fallback and an inspector
        # reading four blank contact rows on an operation that supplied them is a false gap.
        # Establishment still wins where it is set — a farm with its own manager is the more
        # specific answer.
        company = getattr(est, "company", None)

        def _est_then_company(est_value, company_attr):
            if est_value:
                return est_value
            return getattr(company, company_attr, None) if company else None

        required_contact_rows = [
            ("Farm Name", est.name),
            ("Address", est.address),
            ("City", est.city),
            ("State / Province", est.state),
            ("Country", _est_then_company(est.country, "country")),
            ("Contact Person", est.contact_person),
            ("Contact Phone", _est_then_company(est.contact_phone, "contact_phone")),
            ("Contact Email", _est_then_company(est.contact_email or est.email, "contact_email")),
        ]
        optional_rows = [
            (
                "GPS Coordinates",
                f"{est.latitude:.6f}, {est.longitude:.6f}" if est.latitude and est.longitude else None,
            ),
            ("Total Acreage", self._total_acreage_phrase(est)),
            ("Farming Method", self._farming_method_phrase(est)),
            # "Certifications" legacy text field — suppressed here because the
            # structured Active Certification Summary table renders the real data.
            # Leaving this row would duplicate and confuse.
            ("Year Established", str(est.year_established) if est.year_established else None),
        ]

        def _render(label, value, required):
            if not value:
                shown = "(not provided)" if required else "\u2014"
            else:
                shown = value
            elements.append(self._label_value(label, shown))

        for label, value in required_contact_rows:
            _render(label, value, required=True)
        for label, value in optional_rows:
            _render(label, value, required=False)

        return elements

    # ------------------------------------------------------------------
    # Section 3: Production Summary
    # ------------------------------------------------------------------

    def _build_production_summary(self):
        p = self.production
        elements = [self._section_header("Production Summary")]

        crop_name = ""
        try:
            crop_name = p.crop_type.name if p.crop_type else (p.product.name if p.product else "")
        except AttributeError:
            pass

        parcel_name = ""
        parcel_area = ""
        try:
            parcel_name = p.parcel.name
            # `Parcel.area` is hectares. This document is read by US certifiers
            # and states farm size in acres elsewhere, so a bare "15.0 ha" three
            # pages from "149.0 acres" reads as a contradiction rather than the
            # same land in two units. Lead with acres, keep the stored value.
            if p.parcel.area:
                # Round BOTH halves. The acres side was formatted and the hectares side was
                # interpolated raw, so a stored float printed as
                # "12.5 acres (5.0585705280033855 ha)" — sixteen significant figures, i.e.
                # sub-micron precision on a field boundary, in a document where every other
                # number is formatted. It reads as a bug on a regulatory record.
                parcel_area = f"{float(p.parcel.area) * 2.47105:.1f} acres ({float(p.parcel.area):.2f} ha)"
            else:
                parcel_area = ""
        except AttributeError:
            pass

        rows = [
            ("Production Name", p.name),
            ("Crop Type", crop_name),
            ("Parcel", parcel_name),
            ("Parcel Area", parcel_area),
            ("Start Date", _fmt_date(p.start_date)),
            ("Expected Harvest", _fmt_date(p.expected_harvest)),
            ("Finish Date", _fmt_date(p.finish_date)),
            ("Lot ID", p.lot_id),
            (
                "Harvest Amount",
                _fmt_mass(p.production_amount, p.production_unit) if p.production_amount else None,
            ),
            # `_humanize_enum`, NOT `get_quality_grade_display()`. The column carries free text
            # now (the packing record's own words), so there is no `choices` to display from —
            # and while there was, the display map would have printed a row written before the
            # 2026-08-21 change as "Grade A (legacy)". `_humanize_enum` reproduces a real grade
            # verbatim ("WA Extra Fancy") and still turns an old `grade_a` slug into "Grade A".
            ("Quality Grade", _humanize_enum(p.quality_grade)),
            ("Harvest Method", p.get_harvest_method_display() if p.harvest_method else None),
            ("Production Method", p.get_production_method_display() if p.production_method else None),
        ]
        # Transparency Score is a Trazo product / engagement metric (self-
        # reported), NOT a regulatory quantity. It is deliberately omitted from
        # EVERY audit export (organic / roc / scs / all): a self-assigned score
        # on a certifier- or buyer-facing document reads as a self-created
        # sustainability grade (ECGT 2024/825 / FTC 16 CFR 260.6 risk) and a
        # reviewer may misread it as a compliance verdict. The score lives on
        # the producer dashboard only.

        for label, value in rows:
            elements.append(self._label_value(label, value))

        return elements

    # ------------------------------------------------------------------
    # Section 4: Input Application Log (Chemical Events)
    # ------------------------------------------------------------------

    def _build_chemical_log(self):
        """
        Input Application Log — 7 CFR 205.103(b)(2).

        Auditor-facing table with two parts:
        1. Application details: what was applied, where, how, and compliance fields
        2. NOP supplier/purchase traceability: links each application to a purchase
           record for mass-balance cross-reference (top non-conformance finding)
        """
        elements = [self._section_header("Input Material Application Records (7 CFR 205.103(b)(2))")]

        events = related_events(self.production, "history_chemicalevent_events")

        if not events:
            elements.append(
                self._empty_table(
                    ["Date", "Product", "Type", "NPK / Conc.", "Amount", "Area", "Method", "Organic Status"]
                )
            )
            return elements

        # --- Table 1: Application Details (primary audit record) ---
        app_headers = [
            "Date",
            "Product",
            "Type",
            "NPK / Conc.",
            "Amount / Rate",
            "Area",
            "Method",
            # USDA's form calls this "Purpose / Reason for Use". `target_pest_disease`
            # answers it for PE/FU/HE ("aphids"); `application_purpose` answers it for
            # fertilizer, which previously had no purpose at all. One column, both facts,
            # header naming both rather than implying the pest reading covers fertiliser.
            "Target / Purpose",
            "Organic Status",
        ]

        # Add EPA/WPS columns for organic and globalgap certifications
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            # Units without parentheses: "(days)" is wider than "days" by more than the column
            # can spare, and the parens carry no meaning a certifier needs.
            app_headers.extend(["REI hrs", "PHI days", "Buffer"])

        # 7 CFR 205.206 + EPA WPS — restricted-use materials require EPA reg #
        # documentation for organic and ROC inspections, not just GlobalG.A.P.
        # RUP flag (40 CFR 152.175): inspectors cross-check restricted-use
        # materials against the applicator certification in Table 2.
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            app_headers.append("EPA Reg #")
            app_headers.append("RUP")

        app_header_row = [self._hdr(h) for h in app_headers]
        app_data = [app_header_row]

        for ev in events:
            amount = ""
            if ev.volume_numeric:
                amount = _qty_with_unit(ev.volume_numeric, ev.volume_unit) or ""
            elif ev.volume:
                # The unit matters here too — a bare "420" is uninterpretable (gal? L? lb?)
                # and cannot support a mass-balance or rate review.
                raw_volume = _val(ev.volume)
                volume_unit = (ev.volume_unit or "").strip()
                if volume_unit and volume_unit not in raw_volume:
                    amount = f"{raw_volume} {volume_unit}"
                elif volume_unit:
                    amount = raw_volume
                else:
                    amount = f"{raw_volume} (unit not recorded)"

            # The rate a reviewer checks a label maximum against. A label maximum is written per
            # ACRE ("4-10 fl oz/acre, 29 fl oz/acre/season"), so the rate — not the total — is
            # the number the application is checked against, and the export used to print only
            # the total and leave the division to the reader.
            #
            # 🔴 2026-09-03 — the RECORDED rate now wins over the derived one. `application_rate`
            # became a real column the day before and this table never read it, so the packet
            # showed Trazo's arithmetic where the operator's own record existed, and the recorded
            # value appeared nowhere in the document. Derivation stays as the fallback for every
            # row written before the column existed.
            rate_txt = _recorded_rate_text(ev) or _rate_per_area(
                ev.volume_numeric, ev.area_numeric, ev.volume_unit, ev.area_unit
            )

            # 🔴 2026-09-03 — and when the two recorded numbers cannot both be true, this column
            # must not present the total as the amount of product applied. See
            # `_amount_reconciles_with_rate`: the case that prompted it is a TANK volume ("40
            # gallons total" beside a six fluid ounce an acre label rate) reaching
            # `volume_numeric`, which prints here as 5,120 fl oz of a spinosad product and feeds
            # the § 205.103(b)(2) mass balance an inspector runs against the purchase records.
            #
            # The rate is kept and the total is stated as UNRECONCILED rather than dropped: the
            # operator did record it, a reviewer is entitled to see it, and silently deleting a
            # recorded number from an audit document is its own defect.
            if _amount_reconciles_with_rate(ev) is False:
                unreconciled = f"amount {amount} not reconciled" if amount else None
                amount = " · ".join(part for part in (rate_txt, unreconciled) if part)
            elif rate_txt:
                amount = f"{amount} ({rate_txt})" if amount else rate_txt

            area = ""
            if ev.area_numeric:
                area = _qty_with_unit(ev.area_numeric, ev.area_unit) or ""
            elif ev.area:
                # The legacy string branch used to drop area_unit on the floor, so a record
                # holding area="12.5" / area_unit="acres" printed a bare "12.5" under a
                # header reading "Area". Acres and hectares differ by 2.47x and the packet
                # gave the reader no way to tell which one a spray covered.
                raw_area = _val(ev.area)
                unit = (ev.area_unit or "").strip()
                if unit and unit not in raw_area:
                    area = f"{raw_area} {unit}"
                elif unit:
                    area = raw_area
                else:
                    area = f"{raw_area} (unit not recorded)"
            # The Input Application Log Table 1 is already at the 7.0" portrait width budget
            # (organic packs Date…RUP), so Block can't be a separate column. Fold the block /
            # section ID into the Area cell — a spatial qualifier — so the spray still ties to a
            # block for lot traceability (it also rides the Production/Pest/Irrigation tables and
            # the CA PUR export). Wraps to a second line in the narrow column.
            if ev.block_id:
                # Growers name blocks "Block 1", so a blind "Blk " prefix produced
                # "Blk Block 1" on the live export. Only prefix when the id is a bare
                # designator ("1", "B-7") that would otherwise read as a stray number.
                block_txt = str(ev.block_id).strip()
                if not re.match(r"(?i)^(blk|block|bl)\b", block_txt):
                    block_txt = f"Blk {block_txt}"
                area = f"{area} · {block_txt}".strip(" ·") if area else block_txt

            # Use structured application method with fallback to legacy field
            method = _method_label(ev.application_method_structured or ev.way_of_application)

            # NOTE: growth_stage / is_fertigation / authorizer_name are NOT folded into this
            # table. It is hard against the 7.0" portrait budget — Target is 0.55" in the
            # organic variant — so appending to a cell here would wrap every row to four or
            # five lines on the most-read table in the document. They live in the
            # "Application Context" sub-table below instead.
            row = [
                self._cell(_fmt_date(ev.date)),
                # No length caps on identity fields (2026-08-01). Cells are Paragraphs, so
                # ReportLab already wraps them on word boundaries; the caps were additionally
                # chopping the value with an ellipsis. The live export read "Organic Gem Liquid
                # Fish Fertilizer 3-3-…", losing the NPK grade, and "Entrust SC Naturalyte
                # Insect Control (a.i. Spinosad 22.5%) [mfr: Cort…", losing the manufacturer —
                # in the document whose purpose is to fully identify what was applied
                # (7 CFR 205.103(b)). The default 120-char cap stays as a runaway guard.
                self._cell(ev.commercial_name),
                self._cell(CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                self._cell(ev.concentration),
                self._cell(amount or None),
                self._cell(area or None),
                self._cell(method),
                self._cell(_target_or_purpose(ev)),
                # _organic_basis_label, not get_organic_approved_display(): Django falls
                # through to the raw value for an unrecognised choice, so a stray "True"
                # printed as a verification basis. See the helper.
                self._cell(_organic_basis_cell(ev)),
            ]

            if self.certification_type in ("organic", "globalgap", "roc", "all"):
                row.append(self._cell(str(ev.rei_hours) if ev.rei_hours is not None else None))
                row.append(self._cell(str(ev.phi_days) if ev.phi_days is not None else None))
                # Feet first, metres retained (2026-08-01). The column stores metres, but this
                # is a US document: every other measure on the row is acres and ounces, and a
                # CA DPR permit condition states buffers in FEET. "15" alone made a reviewer
                # convert in their head against the permit they are holding.
                if ev.buffer_zone_meters is not None:
                    _buffer_ft = _fmt_float(Decimal(str(ev.buffer_zone_meters)) * Decimal("3.28084"), 0)
                    # Whole numbers: a buffer is a pace-it-out distance, and "15.00 m" is
                    # wider than the column can hold without breaking mid-token.
                    row.append(self._cell(f"{_buffer_ft} ft ({_fmt_float(ev.buffer_zone_meters, 0)} m)"))
                else:
                    row.append(self._cell(None))

            if self.certification_type in ("organic", "globalgap", "roc", "all"):
                row.append(self._cell(ev.epa_registration_number))
                row.append(self._cell("Yes" if ev.restricted_use_pesticide else None))

            app_data.append(row)

            # 🔴 2026-08-31 — tank-mix partners had NO route into this packet, for any subtype.
            #
            # An adjuvant, spreader-sticker or surfactant is a material APPLIED TO THE CROP, so
            # § 205.105 governs it exactly as it governs the product it rides with, and the
            # inspector needs it on the input log. It reached the CA PUR export (its own
            # DPR-PML-017C line, `_adjuvant_rows`) and nothing else: the display registry gated
            # it to PE/FU/HE so the grower could not even see it on a fertilizer record, and the
            # certifier packet never rendered it at all. Recorded, exported to the state, and
            # invisible to the certifier — the one reader the packet exists for.
            #
            # A row per partner rather than a column: Table 1 already carries 14 columns at the
            # 7.0" portrait budget, and each partner has its own amount, EPA/state registration
            # and organic basis to account for. Same shape the reviewer expects a tank mix in.
            for partner in getattr(ev, "tank_mix_partners", None) or []:
                if not isinstance(partner, dict):
                    continue
                p_name = (partner.get("commercial_name") or "").strip()
                p_mfr = (partner.get("manufacturer") or "").strip()
                p_epa = (partner.get("epa_registration_number") or "").strip()
                p_vol = (str(partner.get("volume")) if partner.get("volume") not in (None, "") else "").strip()
                p_vol_unit = (partner.get("volume_unit") or "").strip()
                # Same skip rule as the PUR exporter: the form leaves blank partner rows behind.
                if not (p_name or p_epa or p_vol):
                    continue

                product_txt = f"Tank-mix partner: {p_name}" if p_name else "Tank-mix partner"
                if p_mfr:
                    product_txt = f"{product_txt} [mfr: {p_mfr}]"

                # A bare boolean off a checkbox, so it may only be reported as what it is. The
                # sibling column on the parent row says "OMRI Listed — grower-selected, no
                # listing on file" for exactly this reason; naming a listing programme on the
                # strength of a tick is the unearned certification-mark claim `_organic_basis_cell`
                # was written to stop.
                # Em dash, matching the parent row's "OMRI Listed — grower-selected, no listing on
                # file" in the same column. MEASURED at the column's 0.51": the dash form wraps on
                # a word boundary ("— grower / -reported") while the parenthesised alternative
                # breaks mid-word ("(grower-r / eported)"), because ReportLab does not hyphenate.
                p_organic = "Organic-approved — grower-reported" if partner.get("organic_approved") else "Not recorded"

                by_header = {
                    # The date is repeated rather than blanked: a blank date cell in an
                    # application log reads as a missing record, and the row has to stand on its
                    # own once a reviewer sorts or extracts the table.
                    "Date": _fmt_date(ev.date),
                    "Product": product_txt,
                    "Type": "Adjuvant",
                    "Amount / Rate": f"{p_vol} {p_vol_unit}".strip() or None,
                    "Organic Status": p_organic,
                    "EPA Reg #": p_epa or None,
                }
                app_data.append([self._cell(by_header.get(header)) for header in app_headers])

        # Dynamic column widths based on columns present
        # Target total <=7.0" (letter portrait, 0.75" margins). Globalgap+all cert
        # packs the most columns and must still fit — trimmed Target + EPA Reg to budget.
        # Widths are declared per variant rather than as base-minus-deltas (2026-08-01). The
        # delta form hid what the packed variant actually ended up with, and it had starved two
        # columns below the width of their own contents: Date broke "2025-07-08" across two
        # lines and Type broke "Pesticide" mid-word into "Pestici / de".
        #
        # Sizing rule: a column must fit its widest ATOMIC token — a date, a type label, a
        # header word — on one line at 7pt Helvetica, less 6pt of padding. Multi-word values
        # (product names, target pests) are expected to wrap and are given area, not width.
        # Widths are declared per variant rather than as base-minus-deltas (2026-08-01). The
        # delta form hid what the packed variant actually ended up with, and it had starved
        # columns below the width of their own contents: Date broke "2025-07-08" over two lines,
        # Type broke "Pesticide" into "Pestici / de", Method broke "Fertigation", Target broke
        # "orangeworm". A certifier document cannot look like that, and neither can a screenshot
        # of one.
        #
        # Every width below is measured, not guessed: it is at least
        # `stringWidth(longest_atomic_token) + 6pt padding` for that column, where the atomic
        # tokens are the header words, the type/method labels, a date, and an EPA number.
        # Multi-word values (product names, target pests) are meant to wrap, so the leftover
        # budget goes to them. test_audit_pdf_column_fit.py holds this true.
        if self.certification_type in ("organic", "globalgap", "roc", "all"):
            base_widths = [
                0.64 * inch,  # Date        — "2025-07-08"
                0.65 * inch,  # Product     — wraps; longest word "Naturalyte"
                0.53 * inch,  # Type        — "Pesticide"
                0.45 * inch,  # NPK / Conc. — header "Conc."
                0.51 * inch,  # Amount      — header "Amount"
                0.40 * inch,  # Area        — wraps; "acres", block designator
                0.60 * inch,  # Method      — "Fertigation"
                0.68 * inch,  # Target      — wraps; "transitella)"
                0.51 * inch,  # Organic     — "certified"
                0.30 * inch,  # REI hrs
                0.36 * inch,  # PHI days
                0.43 * inch,  # Buffer m
                0.60 * inch,  # EPA Reg #   — "62719-621"
                0.34 * inch,  # RUP
            ]  # = 7.00 in
        else:
            base_widths = [
                0.64 * inch,  # Date
                0.95 * inch,  # Product
                0.53 * inch,  # Type
                0.45 * inch,  # NPK / Conc.
                0.51 * inch,  # Amount
                0.50 * inch,  # Area
                0.60 * inch,  # Method
                0.85 * inch,  # Target
                0.51 * inch,  # Organic
            ]  # = 5.54 in

        t = Table(app_data, colWidths=base_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # --- Summary-mode applications (§ 205.103(b)(2)) ---
        #
        # Summary mode is a headline feature: a grower logs a season of fertigation as ONE
        # event carrying date range, pass count and season totals. The per-event columns above
        # are empty for such a row by design — the totals ARE the record — and none of those
        # totals reached the packet. A farm that used the feature handed its certifier a row
        # with a product name and blanks where twelve passes and 480 kg of nitrogen should be.
        #
        # Only grazing summaries were handled before this (soil section), which is how the gap
        # survived: the FEATURE was covered somewhere, so it read as covered everywhere.
        summary_rows = []
        for ev in events:
            ed = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            if ed.get("is_summary") not in (True, "true"):
                continue
            span = " to ".join(x for x in (ed.get("date_start"), ed.get("date_end")) if x)
            totals = []
            for key, label in (
                ("event_count", "Applications"),
                ("volume_applied_total", "Volume"),
                ("area_treated_total", "Area treated"),
                ("nitrogen_total_kg", "N (kg)"),
                ("phosphorus_total_kg", "P (kg)"),
                ("potassium_total_kg", "K (kg)"),
                ("active_ingredient_total_kg", "Active ingredient (kg)"),
            ):
                v = ed.get(key)
                if v not in (None, "", []):
                    totals.append(f"{label}: {v}")
            if totals:
                summary_rows.append(
                    [
                        self._cell(span or _fmt_date(ev.date)),
                        self._cell(_val(ev.commercial_name)),
                        self._cell(" · ".join(totals)),
                    ]
                )
        if summary_rows:
            elements.append(self._spacer(0.12))
            elements.append(self._body("<b>Summary-Mode Applications (7 CFR 205.103(b)(2))</b>"))
            sm_data = [[self._hdr(h) for h in ["Period", "Product", "Season totals"]]] + summary_rows
            sm = Table(sm_data, colWidths=[1.35 * inch, 1.4 * inch, 4.25 * inch], repeatRows=1)
            sm.setStyle(self._base_table_style())
            elements.append(sm)

        # --- Table 2: NOP Supplier & Purchase Traceability ---
        # Required for mass-balance audit (7 CFR 205.103(b)(2))
        # This is the #1 non-conformance finding in organic audits
        if self.certification_type in ("organic", "roc", "all"):
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Input Purchase Traceability (7 CFR 205.103)</b>"))
            elements.append(self._spacer(0.05))

            # The CA DPR restricted-materials permit is issued by a California county
            # Ag Commissioner, so the column is meaningless on an out-of-state packet —
            # an OEFFA or PCO inspector was being handed a permanently blank column
            # titled "CA DPR Permit". Show it for a CA operation, OR whenever any event
            # actually carries a permit: never hide data the grower already entered just
            # because the farm's state field is blank or wrong.
            show_dpr_permit = self._establishment_state() == "CA" or any(ev.ca_dpr_permit_number for ev in events)

            # Same source as the widths (see TABLE_HEADERS). The CA list IS the non-CA list
            # plus the DPR column, mirroring how the two width constants relate, so slicing
            # keeps one definition rather than two that must be kept in step by hand.
            trace_headers = list(
                TABLE_HEADERS["INPUT_TRACEABILITY_WIDTHS_CA"]
                if show_dpr_permit
                else TABLE_HEADERS["INPUT_TRACEABILITY_WIDTHS_NON_CA"]
            )
            trace_header_row = [self._hdr(h) for h in trace_headers]
            trace_data = [trace_header_row]
            missing_supplier = 0

            for ev in events:
                qty_purchased = ""
                if ev.quantity_purchased is not None:
                    qty_purchased = f"{_fmt_float(ev.quantity_purchased)} {_val(ev.quantity_purchased_unit, '')}"

                # CA DPR restricted-materials permit (county Ag Commissioner).
                # Surface expiry inline so the inspector can check validity
                # against the application date without leaving the table.
                dpr_permit = None
                if ev.ca_dpr_permit_number:
                    dpr_permit = ev.ca_dpr_permit_number
                    if ev.ca_dpr_permit_expires:
                        dpr_permit += f" exp {ev.ca_dpr_permit_expires:%Y-%m-%d}"

                # NOP input identity: the traceability record must identify the MATERIAL, not
                # just the brand. active_ingredient lives in extra_data; manufacturer is a model
                # column. Fold both under the product name here (word-wraps in the cell) so the
                # inspector sees "Entrust SC (a.i. spinosad) [mfr: Corteva]" rather than a bare
                # brand. _cell escapes markup, so this is a plain compound string, not <br/>.
                product_bits = [ev.commercial_name or ""]
                _ai = ev.extra_data.get("active_ingredient") if isinstance(ev.extra_data, dict) else None
                if _ai:
                    product_bits.append(f"(a.i. {_ai})")
                if ev.manufacturer:
                    product_bits.append(f"[mfr: {ev.manufacturer}]")
                product_txt = " ".join(b for b in product_bits if b).strip()

                trace_row = [
                    self._cell(_fmt_date(ev.date)),
                    # Same reasoning as Table 1: these identify the material and its
                    # source for a mass-balance review, so they must not be chopped.
                    self._cell(product_txt or None),
                    self._cell(ev.supplier_name),
                    self._cell(_fmt_date(ev.purchase_date) if ev.purchase_date else None),
                    # "[receipt on file]" marks that the invoice FILE itself is in the
                    # packet ZIP's receipts/ folder (2026-08-25) — the inspector no longer
                    # has to ask the farmer to courier the paper behind the number.
                    self._cell(
                        f"{ev.purchase_invoice} [receipt on file]"
                        if ev.purchase_invoice and ev.receipt_document_id
                        else ("[receipt on file]" if ev.receipt_document_id else ev.purchase_invoice)
                    ),
                    self._cell(ev.chemical_lot_number),
                    self._cell(qty_purchased or None),
                    # authorizer_name is NOT folded in here — this column is 0.70" and the
                    # table is at the 7.0" budget. See the Application Context sub-table.
                    self._cell(_applied_by(ev)),
                    # 26 fits "C-0-123456 exp 2027-06-30" (25) without ellipsising the
                    # expiry. The cell is a wrapping Paragraph, so this is a truncation
                    # guard, not a line-width limit — and the number now leads, so any
                    # future truncation costs the expiry, never the licence.
                    self._cell(_fmt_credential(ev.applicator_certification)),
                ]
                if show_dpr_permit:
                    trace_row.append(self._cell(dpr_permit))
                trace_data.append(trace_row)

                if not ev.supplier_name:
                    missing_supplier += 1

            # Column widths: Purchase Date widened to fit "YYYY-MM-DD" without
            # wrapping; Supplier widened so common org names ("Hydra Organics",
            # "Pacific Gold Dairy") render fully.
            # CA DPR Permit gets 0.85" so "PERMIT-# exp YYYY-MM-DD" wraps to
            # two clean lines; total stays inside the 7.0" budget.
            # 2026-07-31: Cert # 0.45" -> 0.70". At 0.45" ReportLab broke a real CA
            # licence ("C-0-123456") across FIVE lines — "C-0-12 / 3456 / exp 20 /
            # 27-06-3 / 0" — which is not a readable certificate number on an audit
            # packet. 0.70" holds a 10-char licence on one line with the expiry
            # beneath. Paid for out of Qty Purchased, which is blank for every input
            # a grower buys by the container rather than by weight.
            # 2026-08-02: when the DPR column is dropped for a non-CA operation its
            # 0.85" is returned to Product (+0.45) and Supplier (+0.40) rather than
            # left as a gap — those two are the columns the comments above record as
            # having been squeezed. Both layouts total exactly 7.0".
            if show_dpr_permit:
                trace_widths = INPUT_TRACEABILITY_WIDTHS_CA
            else:
                trace_widths = INPUT_TRACEABILITY_WIDTHS_NON_CA
            t2 = Table(trace_data, colWidths=trace_widths, repeatRows=1)
            t2.setStyle(self._base_table_style())
            elements.append(t2)

            if missing_supplier > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"Warning: {missing_supplier} input(s) missing supplier information. "
                        "NOP auditors require supplier traceability for all purchased inputs "
                        "to complete mass-balance reconciliation.",
                        self._styles["footer_note"],
                    )
                )

        # --- Table 3: OMRI / National List Verification (Sprint 3) ---
        # 7 CFR 205.601 (allowed synthetics) + 205.602 (prohibited nonsynthetics).
        # Distinguishes farmer-confirmed OMRI IDs, National List matches, and
        # pure self-report. Flags any National List "prohibited" match.
        if self.certification_type in ("organic", "roc", "all") and events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>OMRI / National List Verification (7 CFR 205.601 / 205.602)</b>"))
            elements.append(self._spacer(0.05))

            # Cross-check each input against the active OSP's approved-materials
            # sets — CCOF requires inputs be approved on the OSP Material List
            # before use. Reuses the same M2Ms the drift detector reads.
            approved_omri_ids = set()
            approved_nl_ids = set()
            # The event-side WSDA FK, and the names on the plan's other two sources. This table
            # read OMRI + National List only, so an event whose ONLY listing is a grower-attached
            # WSDA row printed "Self-reported" with an OSP-approval of "—" — contradicting
            # `claim_authority.may_claim_input_listing`, which grants LABEL_INPUT_WSDA_LISTED for
            # that same record, and contradicting the drift section of this same PDF, which does
            # check WSDA. `plan_materials.py:12-13` names that contradiction as the defect it was
            # written to end.
            approved_wsda_ids = set()
            approved_plan_names = set()
            osp_loaded = False
            try:
                from certifications.models import OrganicSystemPlan

                est = self.production.parcel.establishment
                _osp = (
                    OrganicSystemPlan.objects.filter(establishment=est, status="active")
                    .order_by("-version_number")
                    .first()
                    or OrganicSystemPlan.objects.filter(establishment=est).order_by("-version_number").first()
                )
                if _osp:
                    osp_loaded = True
                    approved_omri_ids = set(_osp.approved_omri_products.values_list("id", flat=True))
                    approved_nl_ids = set(_osp.approved_national_list_substances.values_list("id", flat=True))
                    approved_wsda_ids = set(_osp.approved_wsda_materials.values_list("id", flat=True))
                    # Operator-entered rows carry no catalog id to compare, so they are matched
                    # by name — exactly and only, the same rule `plan_materials` applies: these
                    # are the operator's own words and a fuzzy match would mark a material as
                    # covered when nobody decided that it was.
                    approved_plan_names = {
                        " ".join((n or "").split()).strip().lower()
                        for n in _osp.plan_material_entries.values_list("product_name", flat=True)
                    }
            except Exception:  # noqa: BLE001 — OSP cross-check is best-effort
                pass

            ver_headers = ["Date", "Product", "OMRI ID", "National List Match", "Status", "OSP Approval"]
            ver_data = [[self._hdr(h) for h in ver_headers]]
            prohibited_hits = 0
            self_reported_count = 0
            not_on_osp_count = 0
            # NOP 5012 — liquid-fertilizer nitrogen source. Count fertilizer events
            # whose N source is synthetic (prohibited) or unverified.
            unverified_n_count = sum(
                1
                for ev in events
                if getattr(ev, "nitrogen_percentage", None)
                and getattr(ev, "nitrogen_source", None) in ("synthetic_prohibited", "unknown", None)
            )
            synthetic_n_count = sum(
                1 for ev in events if getattr(ev, "nitrogen_source", None) == "synthetic_prohibited"
            )
            documented_n_count = sum(
                1 for ev in events if getattr(ev, "nitrogen_source", None) in ("organic", "mined_natural")
            )

            restricted_hits = 0
            for ev in events:
                omri = getattr(ev, "omri_product", None)
                # Phase 5 slice 1: the dossier cites a confirmed classification only. A legacy one or
                # a partial-name suggestion is printed as what it is, never as a citation.
                from history.services.national_list_basis import (
                    confirmed_national_list_substance,
                    unconfirmed_national_list,
                )

                nl = confirmed_national_list_substance(ev)
                unconfirmed_nl, unconfirmed_note = unconfirmed_national_list(ev) if nl is None else (None, "")

                omri_display = omri.omri_id if omri else None
                if nl:
                    nl_display = (
                        f"{nl.substance_name} ({nl.cfr_section}{nl.subsection or ''})"
                        if nl.is_national_list_entry
                        else f"{nl.substance_name} (nonsynthetic — no National List entry)"
                    )
                    # 🔴 2026-08-20 — a bare "PROHIBITED" MISSTATES the regulation whenever the
                    # entry carries an annotation, and § 205.601/§ 205.602 are full of them.
                    #
                    # Live example: calcium chloride (brine process) is on § 205.602, and its own
                    # row in this database says "Allowed only as foliar spray for calcium uptake
                    # disorders." A Honeycrisp block's seven-spray calcium programme for bitter
                    # pit IS that exception — bitter pit is the physiological calcium-uptake
                    # disorder the annotation names. The packet reported the compliant use as a
                    # flat PROHIBITED and told the certifier the crop was disqualified from
                    # organic sale.
                    #
                    # The annotation is the regulation. Print it, and say the use is restricted
                    # rather than forbidden, so the certifier reads the same rule the CFR states.
                    #
                    # ⚠️ The test is the TYPED `annotation_kind`, never "does restriction_notes
                    # have text in it". Glyphosate's § 205.105 row also carries a note
                    # ("Synthetic herbicide; not on § 205.601") — presence-of-prose would have
                    # printed glyphosate as "Restricted use" and moved it out of the [WARNING]
                    # block. See NationalListSubstance.is_conditionally_permitted.
                    restriction = (getattr(nl, "restriction_notes", "") or "").strip()
                    conditional = bool(getattr(nl, "is_conditionally_permitted", False))
                    if nl.status == "allowed":
                        status_display = "Allowed"
                    elif conditional:
                        status_display = "Restricted use"
                    else:
                        status_display = "PROHIBITED"
                    if restriction:
                        nl_display = f"{nl_display} — {restriction}"
                    if nl.status == "prohibited" and not conditional:
                        prohibited_hits += 1
                    elif nl.status == "prohibited":
                        restricted_hits += 1
                else:
                    nl_display = f"{unconfirmed_nl.substance_name}: {unconfirmed_note}" if unconfirmed_nl else None
                    # WSDA is a third-party listing the grower attached, so a record carrying
                    # one is not "self-reported". Saying it was understated the evidence on
                    # exactly the products where WSDA is the ONLY listing that exists — and
                    # contradicted `claim_authority.may_claim_input_listing`, which grants
                    # LABEL_INPUT_WSDA_LISTED for the same record.
                    if omri:
                        status_display = "Farmer-reported OMRI"
                    elif getattr(ev, "wsda_material", None):
                        status_display = "Farmer-reported WSDA"
                    else:
                        status_display = "Self-reported"

                wsda = getattr(ev, "wsda_material", None)
                if not omri and not nl and not wsda:
                    self_reported_count += 1

                event_name = " ".join((ev.commercial_name or "").split()).strip().lower()
                on_plan = (
                    (omri and omri.id in approved_omri_ids)
                    or (nl and nl.id in approved_nl_ids)
                    or (wsda and wsda.id in approved_wsda_ids)
                    or (event_name and event_name in approved_plan_names)
                )
                if on_plan:
                    osp_approval = "OSP-approved"
                elif osp_loaded and (omri or nl or wsda):
                    osp_approval = "Listed — not on OSP"
                    not_on_osp_count += 1
                else:
                    osp_approval = "—"

                ver_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.commercial_name),
                        self._cell(omri_display),
                        self._cell(nl_display),
                        self._cell(status_display),
                        self._cell(osp_approval),
                    ]
                )

            ver_widths = [0.6 * inch, 1.2 * inch, 0.8 * inch, 1.95 * inch, 0.95 * inch, 1.3 * inch]
            t3 = Table(ver_data, colWidths=ver_widths, repeatRows=1)
            t3.setStyle(self._base_table_style())
            elements.append(t3)

            if prohibited_hits > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[WARNING] 7 CFR 205.105 / 205.602: {prohibited_hits} input(s) match a "
                        f"PROHIBITED substance (a synthetic not on § 205.601, a nonsynthetic on "
                        f"§ 205.602, or an excluded substance/method under § 205.105). Use of these "
                        f"inputs disqualifies the crop from organic sale. Review with certifier "
                        f"immediately.</b>",
                        self._warning_style(),
                    )
                )

            if restricted_hits > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] 7 CFR 205.601 / 205.602:</b> {restricted_hits} input(s) are listed "
                        "with a USE RESTRICTION, shown beside the substance above. The listing does not "
                        "forbid the material outright — it allows it only for the stated use. Confirm "
                        "the recorded purpose matches the annotation.",
                        self._warning_style(),
                    )
                )

            if self_reported_count > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        # ⚠️ `omri_product` has NO writer in production code — it is read by
                        # claim_authority, claim_resolver and readiness, and set by nothing but
                        # seeders. So this count includes every input whose only missing piece
                        # is an OMRI FK the product cannot yet populate, which inflates it.
                        # Said plainly here rather than quietly overstating a finding.
                        f"Note: {self_reported_count} input(s) have no National List match on file "
                        f"and remain UNCLASSIFIED (OMRI catalog matching is not yet applied "
                        f"automatically, so an OMRI-listed product may appear here). Per NOP 5033 "
                        f"(Classification "
                        f"of Materials), each must be resolved through the synthetic/non-synthetic and "
                        f"agricultural/non-agricultural decision trees before use — verify each against "
                        f"omri.org or 7 CFR 205.601/205.602 directly rather than treating an unmatched "
                        f"input as allowed by default.",
                        self._styles["footer_note"],
                    )
                )

            if osp_loaded and not_on_osp_count > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] OSP material approval:</b> {not_on_osp_count} input(s) are OMRI / "
                        "National-List recognized but are NOT on this operation's active OSP Material List. "
                        "Certifiers generally require every input to be approved on the OSP before use — add "
                        "them to the OSP "
                        "Material List or confirm approval with the certifier.",
                        self._warning_style(),
                    )
                )

            # NOP 5012 — liquid/soluble fertilizer nitrogen-source verification.
            if synthetic_n_count > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[WARNING] NOP 5012 / § 205.105(a): {synthetic_n_count} fertilizer event(s) "
                        f"declare a SYNTHETIC nitrogen source. Synthetic N is prohibited in organic crop "
                        f"production — review with certifier immediately.</b>",
                        self._warning_style(),
                    )
                )
            elif unverified_n_count > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"[REVIEW] NOP 5012: {unverified_n_count} fertilizer event(s) with a nitrogen "
                        f"content have no verified nitrogen source on file. Liquid/soluble fertilizers must "
                        f"be confirmed free of prohibited synthetic N (sodium nitrate is capped at 20% of "
                        f"the crop's N requirement) — record the N source for each.",
                        self._styles["footer_note"],
                    )
                )
            elif documented_n_count > 0:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"NOP 5012: the operator recorded the nitrogen source as organic or mined-natural for "
                        f"{documented_n_count} fertilizer event(s). This is the operator's selection, not a "
                        "product analysis, and does not establish that no synthetic nitrogen was used.",
                        self._styles["footer_note"],
                    )
                )

        elements.extend(self._build_application_context_subtable(events))
        elements.extend(self._build_micronutrient_subtable(events))

        # --- Application Notes (mirrors the Production Event Notes pattern) ---
        elements.extend(self._build_event_notes_subtable(events, "Application Notes", CHEMICAL_TYPE_LABELS))

        return elements

    # Micronutrient → the test_results key that carries its lab result. Only the four the soil
    # form collects; the rest resolve to no key and are reported as "not on file" rather than
    # being silently passed.
    _MICRONUTRIENT_LAB_KEYS = {
        "zinc": "zinc_ppm",
        "boron": "boron_ppm",
        "manganese": "manganese_ppm",
        "iron": "iron_ppm",
    }

    # The nutrients 7 CFR 205.601(j)(7) actually governs: soluble boron products under (j)(7)(i)
    # and the sulfates/carbonates/oxides/silicates of zinc, copper, iron, manganese, molybdenum,
    # selenium and cobalt under (j)(7)(ii). Calcium, magnesium and sulfur are SECONDARY
    # macronutrients and are allowed on other grounds (gypsum, elemental sulfur, dolomite), so
    # demanding a documented deficiency for them would misstate the rule to a certifier — the
    # kind of false flag that makes an operation distrust every other flag in the document.
    # "other" stays in scope because it may well be molybdenum, selenium or cobalt.
    _JS601_MICRONUTRIENTS = {"zinc", "boron", "manganese", "iron", "copper", "other"}

    def _build_micronutrient_subtable(self, events):
        """Micronutrient applications paired with the lab analysis that documents the deficiency.

        7 CFR 205.601(j)(7) permits synthetic micronutrients only where a documented soil or
        plant-tissue deficiency exists, and never as a defoliant, herbicide or desiccant. So the
        application on its own is not the record — the application PLUS the analysis is. This
        table puts them on the same page and states plainly which applications have a matching
        result on file, so the operation finds the gap before an inspector does.

        The status column reports only what the data shows. An application with no matching lab
        result is marked REVIEW, not "non-compliant": the deficiency may be documented outside
        Trazo, and non-synthetic sources of calcium, magnesium and sulfur are permitted on other
        grounds entirely.
        """
        applications = [ev for ev in events if getattr(ev, "micronutrient_type", None)]
        if not applications:
            return []

        # Every lab result available in this production, as {test_results key: [(date, ppm)]}.
        lab_results = {}
        for sev in self.production.history_soilmanagementevent_events.all():
            results = sev.test_results if isinstance(sev.test_results, dict) else {}
            for key in self._MICRONUTRIENT_LAB_KEYS.values():
                value = results.get(key)
                if value not in (None, "") and sev.date:
                    lab_results.setdefault(key, []).append((sev.date, value))

        rows = []
        unsupported = 0
        in_scope = 0
        for ev in applications:
            nutrient = ev.get_micronutrient_type_display()
            rate = None
            if ev.micronutrient_rate is not None:
                rate = f"{_fmt_float(ev.micronutrient_rate)} {_val(ev.micronutrient_rate_unit, '')}".strip()

            if ev.micronutrient_type not in self._JS601_MICRONUTRIENTS:
                # A secondary macronutrient: listed for completeness, but (j)(7) does not apply.
                status = "n/a — not a § 205.601(j)(7) micronutrient"
            else:
                in_scope += 1
                lab_key = self._MICRONUTRIENT_LAB_KEYS.get(ev.micronutrient_type)
                # A deficiency is only evidence for an application made AFTER it was measured.
                prior = [(d, v) for d, v in lab_results.get(lab_key, []) if ev.date and d <= ev.date] if lab_key else []
                if prior:
                    sample_date, value = max(prior, key=lambda pair: pair[0])
                    status = f"DOCUMENTED — {value} ppm ({_fmt_date(sample_date)})"
                else:
                    status = "REVIEW — no prior lab result on file"
                    unsupported += 1

            rows.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(ev.commercial_name),
                    self._cell(nutrient),
                    self._cell(rate),
                    self._cell(status),
                ]
            )

        elements = [
            Spacer(1, 10),
            Paragraph(
                "<b>Micronutrient Applications &amp; Deficiency Basis (7 CFR 205.601(j)(7))</b>",
                self._sub_header_style(),
            ),
        ]
        table = Table(
            [[self._hdr(h) for h in ("Date", "Product", "Micronutrient", "Rate", "Deficiency Record")]] + rows,
            colWidths=[0.75 * inch, 1.6 * inch, 1.15 * inch, 0.9 * inch, 2.0 * inch],  # 6.4"
            repeatRows=1,
        )
        table.setStyle(self._base_table_style())
        elements.append(table)

        # Counts are over the IN-SCOPE applications only: a gypsum or elemental-sulfur row is
        # listed above for completeness but is not governed by (j)(7), so counting it either way
        # would misstate the operation's position.
        if unsupported:
            elements.append(
                Paragraph(
                    f"{unsupported} of {in_scope} § 205.601(j)(7) micronutrient application(s) have no "
                    f"prior laboratory result recorded in Trazo. The rule permits synthetic "
                    f"micronutrients only where a deficiency is documented by soil OR TISSUE testing, or "
                    f"by another documented and verifiable method the certifying agent approves — "
                    f"log the soil test or lab analysis (Soil event, Lab Analysis) that supports "
                    f"each application, or attach the certifier-held documentation.",
                    self._styles["footer_note"],
                )
            )
        elif in_scope:
            elements.append(
                Paragraph(
                    f"All {in_scope} § 205.601(j)(7) micronutrient application(s) are supported by a "
                    f"prior laboratory result recorded in Trazo.",
                    self._styles["footer_note"],
                )
            )

        return elements

    @staticmethod
    def _applied_scope_display(event):
        """Render `applied_scope` + `applied_scope_detail` as one auditable locator.

        Returns None when the question was not answered. An unanswered scope is NOT a claim
        that the whole planting was covered — the same absence-is-not-denial rule the buffer
        disposition and the manure attestation already follow.

        A "part of planting" answer with no locator is flagged, not silently printed: the
        whole regulatory point of the field (§ 205.103(b)(2), records that permit the input
        to be traced to where it went) is unmet by "part" alone.
        """
        scope = getattr(event, "applied_scope", None)
        if not scope:
            return None
        detail = (getattr(event, "applied_scope_detail", None) or "").strip()
        if scope == "part":
            return f"Part — {detail}" if detail else "Part — [REVIEW] area not specified"
        label = event.get_applied_scope_display() if hasattr(event, "get_applied_scope_display") else scope
        return label

    def _build_application_context_subtable(self, events):
        """Crop stage, delivery route, treated scope and authorisation for each application.

        These fields were collected and rendered nowhere. They get their own table rather
        than being folded into Table 1 or Table 2, both of which are hard against the
        7.0" portrait budget (Target is 0.55" in the organic variant) — appending to a cell
        there would wrap every row to four or five lines on the two most-read tables in the
        document.

        Why an inspector wants each:
          * Growth stage — the timing a PHI or a bee-safety restriction is judged against.
            "Spinosad at hull split" is a different record from "spinosad at bloom".
          * Fertigated — a material delivered through the irrigation system raises
            § 205.272 water-system contact questions a foliar spray does not.
          * Treated scope — § 205.103(b)(2) requires records that permit the input to be
            traced to WHERE it went. `applied_scope` was added for exactly this and reached
            only the in-app detail modal, so a spray covering rows 12-18 printed identically
            to one covering the whole block. The acreage in Table 1 is the how-much; this is
            the where.
          * Authorised by — GLOBALG.A.P. FV-GFS 32.02.01 #10 asks for the
            technically-responsible person who approved the application, who is often not
            the operator who made it.
        """
        rows = []
        for ev in events:
            stage = ev.get_growth_stage_display() if ev.growth_stage else None
            scope = self._applied_scope_display(ev)
            if not (stage or ev.is_fertigation or ev.authorizer_name or scope):
                continue
            rows.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(ev.commercial_name),
                    self._cell(stage),
                    self._cell("Yes" if ev.is_fertigation else "No"),
                    self._cell(scope),
                    self._cell(ev.authorizer_name),
                ]
            )

        if not rows:
            return []

        elements = [
            Spacer(1, 10),
            Paragraph(
                "<b>Application Context — Crop Stage, Delivery, Treated Scope &amp; Authorisation "
                "(7 CFR 205.103(b)(2))</b>",
                self._sub_header_style(),
            ),
        ]
        # Six columns, 7.00" (was five at 6.40"). Treated Scope's 1.90" is 0.60" of unused
        # width plus 0.30" each off Product and Crop Stage, 0.20" off Fertigated, 0.45" off
        # Authorised By and 0.05" off Date. It needs the room because the answer is a
        # free-text locator ("rows 12-18, north end") and a wrapped locator is a useless one.
        table = Table(
            [[self._hdr(h) for h in ("Date", "Product", "Crop Stage", "Fertigated", "Treated Scope", "Authorised By")]]
            + rows,
            colWidths=[0.7 * inch, 1.6 * inch, 1.05 * inch, 0.6 * inch, 1.9 * inch, 1.15 * inch],
            repeatRows=1,
        )
        table.setStyle(self._base_table_style())
        elements.append(table)
        return elements

    # ------------------------------------------------------------------
    # Section 5: Production Events
    # ------------------------------------------------------------------

    def _build_production_events(self):
        elements = [self._section_header("Planting, Harvest & Field Operation Records (Common OSP G6.0 / G6.1)")]

        # Method (operation technique — e.g. "Hand thinning", "Mechanical harvester")
        # and Block/Section ID are required for NOP lot traceability and practice
        # documentation. Method lives in extra_data.method (distinct from
        # History.production_method, which is organic/conventional).
        headers = [
            "Date",
            "Type",
            "Description",
            "Method",
            "Area Covered",
            "Block",
            *(["Fuel Used", "Equip. Hours"] if self.carbon_in_scope else []),
            "Operator",
        ]

        events = related_events(self.production, "history_productionevent_events")

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        for ev in events:
            area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None
            fuel = f"{_fmt_float(ev.fuel_consumed)} {_val(ev.fuel_unit, '')}" if ev.fuel_consumed else None
            extra = ev.extra_data or {}
            method = extra.get("method") if isinstance(extra, dict) else None
            # Frost-protection (FP) persists its technique under extra_data.protection_method
            # (not .method) and its trigger temperature under low_temperature. Surface both so
            # the Method cell isn't blank and the certifier sees wind-machine vs sprinkler.
            if not method and ev.type == "FP" and isinstance(extra, dict):
                technique = PROTECTION_METHOD_LABELS.get(extra.get("protection_method"), extra.get("protection_method"))
                low_temp = extra.get("low_temperature")
                if technique and low_temp not in (None, ""):
                    method = f"{technique} (to {_val(low_temp)}{_temperature_suffix(extra)})"
                elif technique:
                    method = technique
                elif low_temp not in (None, ""):
                    method = f"Frost protection (to {_val(low_temp)}{_temperature_suffix(extra)})"
            # Growth stage dates the operation against the crop rather than the calendar —
            # a thinning "at fruit set" is the record an inspector reads, not "on 12 May".
            # Folded into the Type cell; this table is already at the 7.0" portrait budget.
            type_display = PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))
            if ev.growth_stage:
                type_display = f"{type_display} · {ev.get_growth_stage_display() or ev.growth_stage}"

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(type_display),
                    # Description can be long (post-harvest sanitation steps,
                    # lot-tracking details, etc.); let ReportLab word-wrap
                    # inside the column instead of cutting mid-sentence at
                    # 80 chars. A 600-char cap still guards against pasted
                    # walls of text that would blow the row height, but
                    # normal regulatory-detail descriptions fit under it.
                    # NOT truncated: 600 characters is not enough either — a real spinosad
                    # justification runs 628 and lost its National List citation off the end.
                    self._cell(ev.description),
                    self._cell(method),
                    self._cell(area),
                    self._cell(ev.block_id),
                    *(
                        [
                            self._cell(fuel),
                            self._cell(str(ev.equipment_hours) if ev.equipment_hours else None),
                        ]
                        if self.carbon_in_scope
                        else []
                    ),
                    self._cell(ev.performed_by),
                ]
            )

        # Module constants, not literals — inline width lists are invisible to
        # test_audit_pdf_column_fit.py, which is exactly how this table's Date column sat
        # 2.2pt too narrow and split every date in the packet.
        col_widths = PRODUCTION_EVENT_WIDTHS_CARBON if self.carbon_in_scope else PRODUCTION_EVENT_WIDTHS_PLAIN
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # --- Irrigation Records (7 CFR 205.272 water quality / NOP water use) ---
        # Irrigation details (water source, method, depth, pump/energy) are model
        # columns on ProductionEvent (IR subtype) but aren't shown in the summary
        # table. Required for organic water-quality compliance and carbon audits.
        ir_events = [ev for ev in events if ev.type == "IR"]
        if ir_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Irrigation Records (7 CFR 205.272 / NOP water management)</b>"))
            elements.append(self._spacer(0.05))

            ir_headers = [
                "Date",
                "Water Source",
                "Method",
                "Depth",
                "Pump Depth (ft)",
                "Power Source",
                "Area",
                "Block",
            ]
            ir_header_row = [self._hdr(h) for h in ir_headers]
            ir_data = [ir_header_row]

            for ev in ir_events:
                depth_display = None
                if ev.irrigation_depth is not None:
                    depth_display = f"{_fmt_float(ev.irrigation_depth)} {_val(ev.irrigation_depth_unit, 'in')}"
                water_src = _choice_label(ev, "water_source")
                method_disp = ev.get_irrigation_method_display() if ev.irrigation_method else None
                elec_src = ev.get_electricity_source_display() if ev.electricity_source else None
                ir_area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None

                ir_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(water_src),
                        self._cell(method_disp),
                        self._cell(depth_display),
                        self._cell(_fmt_float(ev.pump_depth_ft) if ev.pump_depth_ft else None),
                        self._cell(elec_src),
                        self._cell(ir_area),
                        self._cell(ev.block_id),
                    ]
                )

            ir_widths = [
                0.7 * inch,
                1.0 * inch,
                1.0 * inch,
                0.75 * inch,
                0.85 * inch,
                1.0 * inch,
                0.6 * inch,
                0.5 * inch,
            ]
            ir_table = Table(ir_data, colWidths=ir_widths, repeatRows=1)
            ir_table.setStyle(self._base_table_style())
            elements.append(ir_table)

            # --- Irrigation/Well Water Quality Test (CCOF water-source analysis;
            #     FDA FSMA Produce Safety Rule, 21 CFR 112) ---
            # Water-quality testing is NOT a 7 CFR Part 205 organic requirement
            # (§ 205.671 is exclusion-from-sale for residue exceedance; § 205.272 is
            # commingling/contact prevention). CCOF requires an annual water-source
            # analysis, and microbial ag-water testing lives in the FDA FSMA Produce
            # Safety Rule. Surfaced from the IR water-test fields; if irrigation is
            # logged but no test is on file, flag it for the inspector.
            water_test_events = [
                ev for ev in ir_events if ev.water_test_date or ev.water_test_lab or ev.water_test_results
            ]
            elements.append(self._spacer(0.12))
            elements.append(
                self._body(
                    "<b>Irrigation Water Quality Test (certifier water-source analysis · "
                    "FDA FSMA Produce Safety Rule, 21 CFR 112)</b>"
                )
            )
            elements.append(self._spacer(0.05))
            if water_test_events:
                wt_data = [[self._hdr(h) for h in ["Date", "Laboratory", "Results", "Block"]]]
                for ev in water_test_events:
                    results = ev.water_test_results if isinstance(ev.water_test_results, list) else []
                    parts = []
                    for r in results:
                        if not isinstance(r, dict):
                            continue
                        param = str(r.get("parameter") or "").strip()
                        measure = " ".join(
                            v for v in [str(r.get("value") or "").strip(), str(r.get("unit") or "").strip()] if v
                        )
                        seg = ": ".join(p for p in [param, measure] if p)
                        outcome = str(r.get("result") or "").strip()
                        if outcome:
                            seg = f"{seg} ({outcome})" if seg else outcome
                        if seg:
                            parts.append(seg)
                    wt_data.append(
                        [
                            self._cell(_fmt_date(ev.water_test_date) if ev.water_test_date else None),
                            self._cell(ev.water_test_lab),
                            self._cell("; ".join(parts) or None),
                            self._cell(ev.block_id),
                        ]
                    )
                wt_table = Table(wt_data, colWidths=[0.8 * inch, 1.6 * inch, 3.6 * inch, 0.6 * inch], repeatRows=1)
                wt_table.setStyle(self._base_table_style())
                elements.append(wt_table)
            else:
                elements.append(
                    self._body(
                        "No irrigation/well water analysis is on file for this operation. Where "
                        "required by the certifier, the operation must maintain an annual water-source "
                        "test demonstrating the absence of prohibited substances."
                    )
                )
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] Certifier water-source analysis / FDA FSMA Produce Safety Rule "
                        "(21 CFR 112):</b> add the irrigation/well water test (date, laboratory, "
                        "results) so the inspector can verify water-source compliance. Water-quality "
                        "testing is not itself a 7 CFR Part 205 requirement.",
                        self._warning_style(),
                    )
                )

        # --- Post-Harvest Processing Records (7 CFR 205.270-272) ---
        # Handlers of organic product must document cleaning/sanitation, processing
        # aids, and temperature controls to maintain organic integrity. PH-specific
        # fields live in extra_data (no model columns).
        ph_events = [ev for ev in events if ev.type == "PH"]
        if ph_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Post-Harvest Processing Records (7 CFR 205.270-272)</b>"))
            elements.append(self._spacer(0.05))

            ph_headers = [
                "Date",
                "Processing Type",
                "Duration (hrs)",
                "Temp. Controlled",
                "Variety",
                "Operator",
            ]
            ph_header_row = [self._hdr(h) for h in ph_headers]
            ph_data = [ph_header_row]

            # Mirror frontend PROCESSING_TYPE_LABELS (productionEvent.ts) so the PDF
            # shows identical labels to the consumer QR view. A raw .title() fallback
            # silently loses e.g. "Cooling / Pre-cooling" → "Cooling".
            PROCESSING_TYPE_PDF_LABELS = {
                "washing": "Washing",
                "cooling": "Cooling / Pre-cooling",
                "drying": "Drying",
                "sorting": "Sorting",
                "grading": "Grading",
                "packing": "Packing",
                "hulling": "Hulling",
                "shelling": "Shelling",
                "pressing": "Pressing",
                "milling": "Milling",
                "smoking": "Smoking",
            }

            for ev in ph_events:
                extra = ev.extra_data or {}
                proc_type_raw = extra.get("processing_type") or ""
                proc_type_display = (
                    PROCESSING_TYPE_PDF_LABELS.get(proc_type_raw, _humanize_enum(proc_type_raw))
                    if proc_type_raw
                    else None
                )
                duration = extra.get("processing_duration_hours")
                temp_ctrl = extra.get("temperature_control")
                if isinstance(temp_ctrl, str):
                    temp_display = "Yes" if temp_ctrl.lower() in ("true", "yes", "1") else "No"
                elif isinstance(temp_ctrl, bool):
                    temp_display = "Yes" if temp_ctrl else "No"
                else:
                    temp_display = None

                ph_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(proc_type_display),
                        self._cell(_fmt_float(duration) if duration else None),
                        self._cell(temp_display),
                        self._cell(ev.variety),
                        self._cell(ev.performed_by),
                    ]
                )

            ph_widths = [0.75 * inch, 1.3 * inch, 0.85 * inch, 1.0 * inch, 1.0 * inch, 1.2 * inch]
            ph_table = Table(ph_data, colWidths=ph_widths, repeatRows=1)
            ph_table.setStyle(self._base_table_style())
            elements.append(ph_table)

        # --- Harvest Records (per-event detail) ---
        # NOP / GlobalG.A.P. auditors expect per-harvest documentation: yield,
        # variety, quality grade, method. The main Production Events table
        # above lists every event generically; this table surfaces the
        # harvest-specific fields (stored on ProductionEvent HA subtype) so
        # reviewers can reconcile yield, variety, and quality without opening
        # each row. harvest_method lives in extra_data; we mirror from
        # top-level if present for forward compat.
        # Transport endpoints (§ 205.272 / § 205.307). `harvest_destination` is a CATEGORY —
        # stored / sold / handler / feed — which answers "what kind of move" and not "to whom,
        # where". For a load going to a custom huller there is no sale either, so no
        # SalesRecord carries the counterparty. Quick Organics asks for both endpoints by name
        # and address; this prints them when the operator recorded them.
        endpoint_events = [
            ev
            for ev in events
            if getattr(ev, "transport_origin", None) or getattr(ev, "transport_destination_address", None)
        ]
        if endpoint_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Transport Endpoints (7 CFR 205.272)</b>"))
            ep_headers = ["Date", "Lot", "From", "To"]
            ep_data = [[self._hdr(h) for h in ep_headers]]
            for ev in endpoint_events:
                ep_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(getattr(ev, "harvest_lot_code", None)),
                        self._cell(getattr(ev, "transport_origin", None)),
                        self._cell(getattr(ev, "transport_destination_address", None)),
                    ]
                )
            ep_widths = [0.85 * inch, 1.15 * inch, 2.5 * inch, 2.5 * inch]
            ep_table = Table(ep_data, colWidths=ep_widths, repeatRows=1)
            ep_table.setStyle(self._base_table_style())
            elements.append(ep_table)

        # TP (Transport) and BU (Buffer Use) belong here too. All three carry the columns this
        # table prints — lot code, block, quantity, and where the crop went — because they are
        # three points on ONE chain: what came off, where it went, and what happened to the
        # buffer rows. Selecting HA alone meant a load recorded as its own activity, which is
        # the whole reason those subtypes exist, never reached the page an inspector reads.
        #
        # The two other `type == "HA"` selections in this file are deliberately left alone:
        # both are about YIELD (header reconciliation and the CSV yield columns), and neither
        # a transport nor a buffer disposal carries one.
        # BU deliberately NOT here. A Buffer Use event has its own § 205.202(c) Buffer Crop
        # Disposition Record, which shows the disposition, the quantity and the documentation —
        # the facts it exists for. In this twelve-column table it produced a row with a lot code
        # and ten dashes, duplicating a record that is better presented elsewhere and burying
        # the transport rows beside it. Noise on an inspector's page is not neutral.
        ha_events = [ev for ev in events if ev.type in ("HA", "TP")]
        if ha_events:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Harvest &amp; Transport Records</b>"))
            elements.append(self._spacer(0.05))

            # 🔴 2026-08-15 — Block and Destination added.
            #
            # USDA's Harvest Record is five columns: Harvest Date | LOCATION (Field or Parcel
            # ID) | Crop | Quantity | WHERE STORED OR SOLD. Two of those were missing here.
            # `block_id` printed only in the generic Production Events table, so an inspector
            # reconciling a harvest could not see which block it came from in the harvest
            # table itself; and `harvest_destination` — the direct analogue of "Where Stored
            # or Sold", and the § 205.103(b)(2) production→sale hinge — had ZERO occurrences
            # anywhere in this file despite being collected, validated and serialized.
            # Header list and HARVEST_ANALYTICS_WIDTHS are index-for-index; TABLE_HEADERS
            # carries the same list so test_audit_pdf_column_fit.py can size each column
            # against its own bold header word.
            ha_headers = [
                "Date",
                "Lot",
                "Block",
                "Variety",
                "Yield",
                # "Determined By" until 2026-08-19: its bold header word alone needed 0.618in
                # in a twelve-column, 7.00in table. Same fact, a header that fits.
                "Yield Basis",
                "Quality Grade",
                "Method",
                "Brix / Moisture",
                "Destination",
                "Storage",
                "Operator",
            ]
            ha_header_row = [self._hdr(h) for h in ha_headers]
            ha_data = [ha_header_row]

            # Match the frontend HARVEST_METHOD_LABELS (productionEvent.ts) so the
            # audit PDF shows the same consumer-facing labels as the QR transparency
            # flow. Unknown values pass through with underscores converted to spaces.
            HARVEST_METHOD_PDF_LABELS = {
                "hand_picking": "Hand Picking",
                "selective_hand_picking": "Selective Hand Picking",
                "mechanical": "Mechanical Harvester",
                "shake_and_catch": "Shake and Catch",
                "strip_picking": "Strip Picking",
                "manual": "Manual Harvest",
                "mixed": "Mixed (Manual + Mechanical)",
            }

            for ev in ha_events:
                extra = ev.extra_data or {}
                yield_display = _fmt_mass(ev.yield_quantity, ev.yield_unit) if ev.yield_quantity else None
                quality_raw = ev.harvest_quality_grade or None
                quality_display = _humanize_enum(quality_raw)

                # harvest_method: prefer top-level (defensive, if ever promoted),
                # fall back to extra_data where the form currently writes it.
                method_raw = getattr(ev, "harvest_method", None) or extra.get("harvest_method") or ""
                structured_method = (
                    HARVEST_METHOD_PDF_LABELS.get(method_raw, _humanize_enum(method_raw)) if method_raw else None
                )

                # Free-text production_method ("Hand harvest with ATV bin transport")
                # stored at extra_data.method by ProductionTab.jsx onSubmit. This is
                # the richer narrative that drives the manual-operation carbon
                # short-circuit — auditors need to see both the structured dropdown
                # value AND the farmer's documented detail to reconcile the carbon
                # calculation basis and NOP labor-documentation expectations.
                freetext_method = (extra.get("method") or extra.get("production_method") or "").strip()
                if structured_method and freetext_method and freetext_method.lower() != structured_method.lower():
                    method_display = f"{structured_method} ({freetext_method})"
                elif structured_method:
                    method_display = structured_method
                elif freetext_method:
                    method_display = freetext_method
                else:
                    method_display = None

                # Brix vs grain moisture: show whichever is populated (fruits use
                # Brix, grain crops use moisture %). Both shown if both filled.
                measurements = []
                brix = ev.brix_level or extra.get("brix_level") or extra.get("brix_levels")
                if brix:
                    try:
                        measurements.append(f"{_fmt_float(float(brix))}° Brix")
                    except (TypeError, ValueError):
                        measurements.append(f"{brix}° Brix")
                if ev.grain_moisture:
                    measurements.append(f"{_fmt_float(ev.grain_moisture)}% moisture")
                # F43: dry-matter % — avocado/nut maturity (the CA orchard ICP metric)
                if getattr(ev, "dry_matter_percentage", None) is not None:
                    measurements.append(f"{_fmt_float(ev.dry_matter_percentage)}% dry matter")
                measurement_display = " / ".join(measurements) if measurements else None

                # Sprint 3.2 — storage location + optional temperature on HA events
                storage_parts = []
                if ev.storage_location:
                    storage_parts.append(ev.storage_location)
                if ev.storage_temperature_f is not None:
                    storage_parts.append(f"{_fmt_float(ev.storage_temperature_f)}°F")
                storage_display = " @ ".join(storage_parts) if storage_parts else None

                # "Estimated" vs "verified via certified scale" is what makes a yield figure
                # auditable under § 205.103(b)(2) ("readily understood and audited") — and it
                # is the question USDA's own harvest guidance asks about quantity.
                determined_display = (
                    ev.get_amount_determination_display() if getattr(ev, "amount_determination", None) else None
                )
                destination_display = (
                    ev.get_harvest_destination_display() if getattr(ev, "harvest_destination", None) else None
                )
                # A harvest spanning several days is one record with a range, not a lie about
                # a single date. USDA's column header is "Harvest Date(s)", plural.
                date_display = _fmt_date(ev.date)
                if getattr(ev, "harvest_date_end", None):
                    date_display = f"{date_display} – {_fmt_date(ev.harvest_date_end)}"

                ha_data.append(
                    [
                        self._cell(date_display),
                        # § 205.103(b)(2) — the per-pass lot. This is the key a sales record
                        # references, and the thing that makes a multi-pick season traceable.
                        self._cell(getattr(ev, "harvest_lot_code", None)),
                        self._cell(ev.block_id),
                        self._cell(ev.variety),
                        self._cell(yield_display),
                        self._cell(determined_display),
                        self._cell(quality_display),
                        self._cell(method_display),
                        self._cell(measurement_display),
                        self._cell(destination_display),
                        self._cell(storage_display),
                        self._cell(ev.performed_by),
                    ]
                )

            # Twelve columns, 7.00in.
            #
            # 🔴 CORRECTED 2026-08-17. This said "7.44in — inside the 7.5in text block". There
            # is no 7.5in text block: the document is letter with 0.75in margins on both sides
            # (see SimpleDocTemplate above), so the frame is 8.5 - 1.5 = 7.00in. The table was
            # overflowing 0.44in into the right margin and the Operator column was printing
            # outside the printable area. Every other table in this file budgets 7.00 — this
            # one and Itemized Sales were the two that inherited the wrong premise.
            #
            # Lot keeps the widest cell after Method because a code like "HAS-BLOCK2-20260410"
            # is the thing an inspector reads across from a sales record, and a wrapped lot
            # code is a misread lot code. The 0.44in came off the eight widest other columns.
            ha_widths = HARVEST_ANALYTICS_WIDTHS
            ha_table = Table(ha_data, colWidths=ha_widths, repeatRows=1)
            ha_table.setStyle(self._base_table_style())
            elements.append(ha_table)

        # --- Activity Detail (subtype-specific facts) ---
        #
        # WHY THIS EXISTS. Four subtypes recorded their defining facts and showed the certifier
        # none of them: a Pollination event carried hive counts and placement dates, a Canopy
        # pass carried the operation and pass number, an Orchard-Floor pass carried the floor
        # treatment, a Tillage pass carried type/intensity/direction and residue handling — and
        # each arrived in the packet as a bare row with a date and a label. The farmer answered
        # the question; the inspector never saw the answer.
        #
        # ONE generic table rather than four subtype-specific ones. The alternative is widening
        # tables that already sit at ten and twelve columns against a 7.00in frame, and adding a
        # fifth the next time a subtype appears. Here a new subtype is one map entry, and
        # `test_subtype_detail_coverage` fails until that entry exists.
        #
        # Values are rendered through the model's own display methods so an enum reads as its
        # authored label ("Conservation tillage"), not its stored code ("conservation").
        detail_specs = {
            "PO": [
                ("pollinator_type", "Pollinator"),
                ("hive_count", "Hives"),
                ("placement_date", "Placed"),
                ("removal_date", "Removed"),
            ],
            "CM": [("canopy_operation", "Canopy operation"), ("pass_number", "Pass #")],
            "MO": [("floor_management_type", "Floor management")],
            "PR": [("pruning_passes", "Passes")],
            "HA": [("harvest_contract_number", "Contract / work order")],
            # A load leaving the farm carries the same work-order reference as the pick it came
            # from; the form asks for it on TP and the packet printed it for HA only (2026-09-06).
            "TP": [("harvest_contract_number", "Contract / work order")],
        }
        # Summary-mode totals, per subtype. Same gap as the chemical and pest logs: a grower
        # who records a season of harvest or irrigation as ONE event carries the totals in
        # extra_data and leaves the per-event columns blank by design. HA/IR/PR are the
        # subtypes whose forms offer summary mode.
        summary_specs = {
            # (value_key, label, unit_key) — the unit JOINS its value rather than printing as
            # its own entry. "Season yield: 88000 · Unit: lb" is two facts a reader has to
            # reassemble; "Season yield: 88000 lb" is the fact.
            "HA": [("event_count", "Harvest events", None), ("yield_total", "Season yield", "yield_total_unit")],
            "IR": [
                ("event_count", "Irrigation events", None),
                ("water_volume_total", "Water applied", "water_volume_unit"),
            ],
            "PR": [("event_count", "Pruning passes", None)],
        }
        detail_rows = []
        for ev in events:
            extra = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            spec = [(k, lbl, None) for k, lbl in (detail_specs.get(ev.type) or [])]
            if extra.get("is_summary") in (True, "true"):
                spec += summary_specs.get(ev.type, [])
            if not spec:
                continue
            parts = []
            for key, label, unit_key in spec:
                # Column first, then the extra_data mirror: these subtypes persist through
                # extra_data, and a future migration promoting one to a column must not
                # silently drop it from this table.
                getter = f"get_{key}_display"
                raw = getattr(ev, key, None)
                if raw not in (None, "") and hasattr(ev, getter):
                    raw = getattr(ev, getter)()
                if raw in (None, ""):
                    raw = extra.get(key)
                if raw not in (None, "", []):
                    # Units come off the form as storage slugs. Printed raw they reach an
                    # inspector as "Water applied: 4.5 acre_feet" — a machine token in a
                    # sentence about a season's irrigation. Unknown units fall through
                    # unchanged: a unit we cannot name is still the operator's unit.
                    unit = extra.get(unit_key) if unit_key else None
                    if unit:
                        unit = SUMMARY_UNIT_LABELS.get(str(unit), str(unit))
                    parts.append(f"{label}: {raw} {unit}" if unit else f"{label}: {raw}")
            if parts:
                detail_rows.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(" · ".join(parts)),
                    ]
                )
        if detail_rows:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Activity Detail</b>"))
            dt_data = [[self._hdr(h) for h in ["Date", "Activity", "Detail"]]] + detail_rows
            dt = Table(dt_data, colWidths=[0.9 * inch, 1.35 * inch, 4.75 * inch], repeatRows=1)
            dt.setStyle(self._base_table_style())
            elements.append(dt)

        # --- Partial-Area Operations (7 CFR 205.103(b)(2)) ---
        # An operation that covered only part of a planting is the row whose quantity cannot
        # be read against the block's full acreage. The scope answer lives on the event and
        # reached no export; the harvest table already fills the 7.00" frame exactly and has no
        # room for a free-text locator, so partial passes get their own short table.
        #
        # (This comment said "7.44" of a 7.5" block" until 2026-08-18 — the same phantom 7.5"
        # premise corrected 30 lines above, re-introduced by the change set that fixed it.
        # The frame is 7.00"; ha_widths was corrected to sum to exactly that.)
        #
        # Deliberately OUTSIDE the `if ha_events` block and not filtered to HA: ProductionTab
        # collects `applied_scope` on Planting as well as Harvest, and a partial planting has
        # the same audit consequence — trees-per-acre computed against the whole block is
        # wrong by whatever fraction went unplanted.
        #
        # Whole-planting operations are omitted: listing every one would bury the exception
        # this table exists to surface.
        partial_scope_events = [ev for ev in events if getattr(ev, "applied_scope", None) == "part"]
        if partial_scope_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Partial-Area Operations (7 CFR 205.103(b)(2))</b>",
                    self._sub_header_style(),
                )
            )
            # "Area Covered" is the ACREAGE (ev.area_covered, same fact and same header as in
            # the main Production Events table); "Applied Scope" is the LOCATOR the operator
            # wrote. Until 2026-08-18 the locator was printed under the "Area Covered" header
            # and the acreage was absent, so an inspector read "Area Covered: Part — south half
            # only" and the two tables used one header for two different facts.
            pa_data = [
                [
                    self._hdr(h)
                    for h in ("Date", "Operation", "Lot", "Block", "Variety", "Area Covered", "Applied Scope")
                ]
            ]
            for ev in partial_scope_events:
                pa_area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None
                pa_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(getattr(ev, "harvest_lot_code", None)),
                        self._cell(ev.block_id),
                        self._cell(ev.variety),
                        self._cell(pa_area),
                        self._cell(self._applied_scope_display(ev)),
                    ]
                )
            pa_table = Table(
                pa_data,
                # Seven columns: 0.7+1.0+1.1+0.75+0.75+0.9+1.8 = 7.00" exactly, the real text
                # block (letter, 0.75" margins each side). Verified by test_packet_table_widths.
                colWidths=[
                    0.7 * inch,
                    1.0 * inch,
                    1.1 * inch,
                    0.75 * inch,
                    0.75 * inch,
                    0.9 * inch,
                    1.8 * inch,
                ],
                repeatRows=1,
            )
            pa_table.setStyle(self._base_table_style())
            elements.append(pa_table)

        # --- Production Event Notes (Field Notes / observation) ---
        # The main Production Events table keeps one row per event compact (Date,
        # Type, Description, Method, Area, Block, Fuel, Hours, Operator). Free-text
        # observations — the richest farmer-authored documentation surfaced on the
        # consumer QR card as "Farmer's Field Notes" — would overflow that table.
        # Auditors still need these, so we surface them here as a supplemental
        # sub-table. Mirrors the Business Events "Supporting Detail" pattern.
        # A Source column, matching the sibling `_build_event_notes_subtable`: an event may carry
        # BOTH a published note and a private one, and a certifier must be able to tell which is
        # which. Widths re-split from [0.7, 1.0, 4.9] to [0.7, 1.0, 0.9, 4.0] — same 6.6in total,
        # so the 7.00in frame budget is unchanged.
        notes_rows = []
        for ev in events:
            published = (ev.observation or "").strip()
            if published:
                notes_rows.append((ev, published, "Farmer note"))
            private = self._event_private_note_text(ev)
            if private:
                notes_rows.append((ev, private, "Private note"))
        if notes_rows:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Production Event Notes (Field Notes)</b>"))
            elements.append(self._spacer(0.05))

            notes_headers = ["Date", "Type", "Source", "Notes"]
            notes_header_row = [self._hdr(h) for h in notes_headers]
            notes_data = [notes_header_row]

            for ev, note_text, source in notes_rows:
                notes_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(source),
                        # NOT truncated. 120 characters cut the grower's own field notes
                        # mid-sentence — "kept separate from the…", "filed in the OSP…",
                        # "variety tags f…" — losing the substance exactly where it sat. The
                        # sibling notes table (_build_event_notes_subtable) had this cap
                        # removed for the same reason; this one was missed. `_cell` still
                        # applies the runaway ceiling, and the cell word-wraps.
                        self._cell(note_text),
                    ]
                )

            notes_widths = [0.7 * inch, 1.0 * inch, 0.9 * inch, 4.0 * inch]
            notes_table = Table(notes_data, colWidths=notes_widths, repeatRows=1)
            notes_table.setStyle(self._base_table_style())
            elements.append(notes_table)

        return elements

    # ------------------------------------------------------------------
    # Section 5b: Seed & Planting Stock Records (7 CFR 205.204)
    # ------------------------------------------------------------------

    def _stock_established_since(self):
        """(year, crop label) when the records show this perennial's stock on the parcel in an
        earlier season, else None (run 7, R7-14).

        Two gates, both from records, never from the crop's name alone:
        - the production is recorded as a perennial planting (`type == "OR"`): for an annual crop a
          prior season's row is normal rotation, not stock carried into this season;
        - an earlier season shows the same crop: a finished production of the same crop type or
          product in an earlier year, or a crop-history row in an earlier year whose crop name
          starts with this crop's name as a whole word ("Peas" never matches "Peaches").
        Returns the most recent such year, which is what the records establish (review of #113).
        """
        import re

        from history.models import History

        prod = self.production
        parcel = getattr(prod, "parcel", None)
        start = getattr(prod, "start_date", None)
        if parcel is None or start is None or getattr(prod, "type", None) != "OR":
            return None
        crop = getattr(prod, "crop_type", None) or getattr(prod, "product", None)
        crop_name = (getattr(crop, "name", "") or "").strip()
        if not crop_name:
            return None
        pattern = re.compile(rf"^\s*{re.escape(crop_name.lower())}\b")
        years = []
        try:
            for row in parcel.crop_history.all():
                if row.year and row.year < start.year and pattern.match((row.crop_grown or "").lower()):
                    years.append(row.year)
        except Exception:  # noqa: BLE001 — a missing relation must not take the section down
            logger.warning("Crop history unavailable for parcel %s", getattr(parcel, "pk", None), exc_info=True)
        same_crop = {"crop_type_id": prod.crop_type_id} if prod.crop_type_id else {"product_id": prod.product_id}
        if any(same_crop.values()):
            earlier = (
                History.objects.filter(
                    parcel=parcel, finish_date__isnull=False, start_date__year__lt=start.year, **same_crop
                )
                .exclude(pk=prod.pk)
                .values_list("start_date", flat=True)
            )
            years += [d.year for d in earlier if d]
        if not years:
            return None
        return max(years), crop_name

    def _build_seed_stock_section(self):
        """Seed & Planting Stock Records — 7 CFR 205.204.

        NOP 5029 is now frozen at ``documentation/reference/usda-nop-handbook/`` and CAN be
        cited. Earlier revisions cited it from a live URL while it appeared in no frozen
        source, which is exactly what the corpus discipline forbids.

        The two sources say different-strength things, and the difference is the whole point:

        * **7 CFR 205.204(a)(1) — BINDING.** Non-organic seed is permitted only when an
          equivalent organic variety is not commercially available. It imposes NO supplier
          count.
        * **NOP 5029 § 4.2 b.1 — GUIDANCE.** Asks for "documentation of contact with three or
          more seed or planting stock sources". AMS states the Handbook is non-binding and
          that any citation issued must reference the regulations.

        So this section states the REGULATION as the rule and the three-source figure as what
        certifiers EXPECT. NOP 5029 § 4.4.3 is why the expectation still carries weight:
        certifying agents verify commercial availability at inspection.

        Writing "NOP requires 3+ supplier searches" — as this docstring previously did —
        states guidance as law inside the document a certifier reads.
        """
        elements = [self._section_header("Seed & Planting Stock Records (Common OSP G3.0)")]

        # Seed source data lives on ProductionEvent (PL subtype), NOT on History.
        # Query all planting events for seed info.
        planting_events = related_events(self.production, "history_productionevent_events", type="PL")

        # Also check ANY production event for seed_source (some templates set it on non-PL events)
        all_prod_events = list(self.production.history_productionevent_events.all())
        events_with_seed = [
            ev
            for ev in all_prod_events
            if ev.seeds_source or ev.seed_certification_status
            # A purchase record with no source/status still belongs in the traceability table.
            or ev.seed_supplier_name or ev.seed_purchase_invoice or ev.seed_lot_number
        ]

        if not planting_events and not events_with_seed:
            # Run 7 (R7-14): applicability is read from the records, never from the crop name or
            # production type. A crop-name list missed blueberries and printed a "standard
            # inspection finding" for a block planted in 2006; a list that included them would
            # have hidden a replacement planting. What the records can show is whether this crop
            # was already on the parcel before the season.
            established = self._stock_established_since()
            if established is not None:
                elements.append(
                    self._body(
                        f"No planting event is recorded for this season. The records show {_esc(established[1])} "
                        f"on this parcel in {established[0]}, an earlier season, so the stock predates this one. "
                        "§ 205.204 applies to stock as it is planted, so any replacement planting needs its own "
                        "record (source and organic status)."
                    )
                )
            else:
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] 7 CFR 205.204:</b> no planting record for this season, and the parcel record "
                        "does not show this crop here before it. If seed or planting stock was planted, its source "
                        "and organic status are required. Where non-organic seed or stock is used, certifiers look "
                        "for commercial-availability searches; how many is certifier guidance (NOP 5029), not the "
                        "regulation.",
                        self._warning_style(),
                    )
                )
            return elements

        # Seed source information from production events
        if events_with_seed:
            # Use the first event with seed source as the representative
            seed_ev = events_with_seed[0]
            # "Seed Origin", not "Seed Source". MEASURED complaint from the Planting teardown:
            # printed as "Seed Source: Commercial" an inspector reads it as the SUPPLIER, which
            # it is not — it is where the stock came from as a category. The teardown proposed
            # merging this field into `seed_certification_status`; that was reconsidered and
            # REJECTED, because the two are orthogonal axes and the merge would destroy
            # `farm_saved` — a distinct § 205.204 story (no purchase, so no availability search
            # to run) that the status enum cannot express. Renaming fixes the actual defect.
            seed_source_display = seed_ev.get_seeds_source_display() if seed_ev.seeds_source else None
            elements.append(self._label_value("Seed Origin", seed_source_display))

            # § 205.105(e) — excluded methods. The third leg of USDA Form 11's allowed-status
            # triple; the packet previously asserted an organic planting while saying nothing
            # about the one § 205.105 prohibition that is unconditional.
            if seed_ev.seed_non_gmo_status:
                elements.append(
                    self._label_value(
                        "Excluded methods (\u00a7 205.105(e))",
                        seed_ev.get_seed_non_gmo_status_display(),
                    )
                )
            else:
                elements.append(
                    self._label_value(
                        "Excluded methods (\u00a7 205.105(e))",
                        "Not recorded",
                    )
                )

            # § 205.204(a)(4) — PERENNIAL planting stock must be under continuous organic
            # management for at least a year before its crop sells as organic. Printed as a
            # computed elapsed time rather than a bare date, because the date alone leaves the
            # inspector to do the arithmetic the rule is actually about.
            _mgmt_start = getattr(seed_ev, "stock_organic_management_start", None)
            # 🔴 2026-08-21 — the 12-month rule is about PERENNIAL planting stock. This fired on
            # ANY planting event carrying an organic-management date, so an organic vegetable
            # grower who recorded the nursery date for purchased onion transplants was told
            # "this perennial planting stock … its crop may not be sold as organic until the
            # year has elapsed" — a false compliance verdict about an annual crop that is
            # perfectly saleable. Annual seedlings are governed by § 205.204(a)(2)-(3), which
            # carries no 12-month clock; the field is still worth printing on an annual crop,
            # just without the perennial verdict attached to it.
            _is_perennial = getattr(self.production, "type", None) == "OR"
            if _mgmt_start:
                _ref = seed_ev.date.date() if getattr(seed_ev, "date", None) else None
                if _ref:
                    _days = (_ref - _mgmt_start).days
                    _met = _days >= 365 or not _is_perennial
                    elements.append(
                        self._label_value(
                            "Organic management since" + (" (\u00a7 205.204(a)(4))" if _is_perennial else ""),
                            f"{_fmt_date(_mgmt_start)} \u2014 "
                            + (
                                f"{_days // 365} yr {(_days % 365) // 30} mo at planting"
                                if _days >= 365
                                else (
                                    f"{max(_days, 0)} days at planting, UNDER the 12-month minimum"
                                    if _is_perennial
                                    else f"{max(_days, 0)} days at planting"
                                )
                            ),
                        )
                    )
                    if not _met:
                        elements.append(
                            Paragraph(
                                "<b>[REVIEW] 7 CFR 205.204(a)(4):</b> this perennial planting stock had "
                                "been under organic management for less than one year at planting. Its "
                                "crop may not be sold as organic until the year has elapsed.",
                                self._warning_style(),
                            )
                        )
                else:
                    elements.append(
                        self._label_value("Organic management since (\u00a7 205.204(a)(4))", _fmt_date(_mgmt_start))
                    )

            # Organic seed search documentation (7 CFR 205.204(a)(1))
            search_attempts = getattr(seed_ev, "seed_search_attempts", None) or []

            # § 205.204(a)(1) permits non-organic seed only when an equivalent organic variety
            # is not "commercially available", and § 205.2 defines that by FORM, QUALITY or
            # QUANTITY. The supplier rows say WHO was contacted; this says the GROUND the
            # exemption rests on.
            #
            # Rendered before the branch below, not inside it. The first version sat inside the
            # "has supplier rows" branch, so an operation that recorded the ground but not the
            # contacts showed nothing — and the "no search documented" note, the case where a
            # certifier most needs the ground, never showed it either.
            #
            # Only when an exemption is actually claimed: printing "not recorded" for a grower
            # who planted certified organic seed would invent a finding out of a rule that does
            # not apply to them.
            #
            # 🔴 2026-08-15: this used to also treat "has search rows" as claiming an
            # exemption. That inference held only while the search widget was GATED to
            # non-organic seed — the presence of rows implied the status. The widget is now
            # available on every planting, precisely so a grower who compared suppliers and
            # then bought ORGANIC seed can record it (and so correcting a status no longer
            # hides evidence they already entered). With that gate gone, the old heuristic
            # prints "Ground for the exemption: not recorded" underneath a certified-organic
            # planting — a fabricated finding, which is the one thing a certifier packet must
            # never contain. The STATUS is the only thing that claims an exemption.
            _claims_seed_exemption = seed_ev.seed_certification_status in NON_ORGANIC_SEED_STATUSES
            if _claims_seed_exemption:
                from history.models import ProductionEvent as _PE

                _reason_key = (getattr(seed_ev, "seed_nonavailability_reason", None) or "").strip()
                _reason = dict(_PE.SEED_NONAVAILABILITY_REASON_CHOICES).get(_reason_key, _reason_key)
                elements.append(self._spacer(0.05))
                elements.append(
                    self._body(
                        f"Ground for the exemption (\u00a7 205.204(a)(1)): {_reason}"
                        if _reason_key
                        else "Ground for the exemption (\u00a7 205.204(a)(1)): not recorded \u2014 "
                        "\u00a7 205.2 asks whether organic seed was unavailable in the required "
                        "form, quality or quantity."
                    )
                )
            if search_attempts and isinstance(search_attempts, list) and len(search_attempts) > 0:
                elements.append(self._spacer(0.1))
                elements.append(self._body("<b>Organic Seed Commercial-Availability Search (7 CFR 205.204(a)(1))</b>"))
                elements.append(self._spacer(0.05))

                search_headers = ["Supplier Contacted", "Date", "Result", "Notes"]
                search_header_row = [self._hdr(h) for h in search_headers]
                search_data = [search_header_row]

                for attempt in search_attempts:
                    if isinstance(attempt, dict):
                        # `supplier` is the pre-2026-08-15 key written by the planting form.
                        # Migration 0161 rewrites stored rows and the serializer normalises
                        # new ones, but a packet must never print a blank supplier column for
                        # a row that has the name under the old key — that column IS the
                        # § 205.204(a)(1) evidence.
                        supplier = attempt.get("supplier_name") or attempt.get("supplier") or ""
                        search_data.append(
                            [
                                self._cell(supplier),
                                self._cell(attempt.get("date_contacted", "")),
                                self._cell(attempt.get("result", "")),
                                self._cell(attempt.get("notes", "")),
                            ]
                        )

                if len(search_data) > 1:
                    sw = [1.5 * inch, 0.8 * inch, 1.2 * inch, 3.0 * inch]
                    t = Table(search_data, colWidths=sw, repeatRows=1)
                    t.setStyle(self._base_table_style())
                    elements.append(t)
            elif seed_ev.seed_certification_status in (
                "non_organic_untreated",
                "non_organic_treated",
            ):
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        # 7 CFR 205.204 imposes NO supplier count. "At least three" is NOP
                        # 5029 § 4.2 b.1 — "documentation of contact with three or more seed or
                        # planting stock sources" — now frozen at
                        # documentation/reference/usda-nop-handbook/txt/NOP-5029.txt. That is
                        # GUIDANCE: AMS states the Handbook is non-binding and that any citation
                        # issued must reference the regulations. So it is phrased below as what
                        # certifiers expect, never as what the rule requires.
                        "Note: Non-organic seed or planting stock is indicated but no "
                        "commercial-availability search is documented. 7 CFR 205.204(a)(1) "
                        "permits non-organic seed only when an equivalent organic variety is "
                        "not commercially available; certifiers typically expect at least "
                        "three suppliers to have been contacted.",
                        self._styles["footer_note"],
                    )
                )

        # Planting event details
        if planting_events:
            elements.append(self._spacer(0.1))
            elements.append(self._body("<b>Planting Event Details</b>"))
            elements.append(self._spacer(0.05))

            # Rootstock and plant count added 2026-08-15. On a perennial operation these are
            # the two facts an inspector reconciles against the nursery invoice, and until
            # they had columns the packet carried a written disclosure that Trazo did not
            # structure them.
            # 🔴 Block added 2026-08-16. CCOF's grower checklist item 2 is literally "what you
            # plant, when you planted it, and WHERE it was planted". The parcel is answered by
            # the production header, but within a parcel two plantings in different blocks were
            # indistinguishable — the same defect fixed for the harvest table on 2026-08-15 and
            # not carried across. `block_id` was collected and declared all along.
            pl_headers = [
                "Date",
                "Block",
                "Variety",
                "Rootstock",
                "Plants",
                "Spacing",
                "Seed Source",
                "Cert Status",
                "Area",
                "Operator",
            ]
            pl_header_row = [self._hdr(h) for h in pl_headers]
            pl_data = [pl_header_row]

            for ev in planting_events:
                area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None
                seed_src = ev.get_seeds_source_display() if ev.seeds_source else None
                cert_status = ev.get_seed_certification_status_display() if ev.seed_certification_status else None
                pl_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.block_id),
                        self._cell(ev.variety),
                        self._cell(getattr(ev, "rootstock", None)),
                        self._cell(str(ev.plants_established) if getattr(ev, "plants_established", None) else None),
                        self._cell(getattr(ev, "plant_spacing", None)),
                        self._cell(seed_src),
                        self._cell(cert_status),
                        self._cell(area),
                        self._cell(ev.performed_by),
                    ]
                )

            # Description dropped from this table: it repeats the narrative already printed
            # in the event log above, and the row is now carrying the columns a certifier
            # actually reconciles. Widths sum to 7.0in — the full text block (letter,
            # 0.75in margins each side). Ten columns, 7.0in exactly.
            pl_widths = [
                0.6 * inch,
                0.6 * inch,
                0.72 * inch,
                0.95 * inch,
                0.45 * inch,
                0.75 * inch,
                0.8 * inch,
                0.85 * inch,
                0.58 * inch,
                0.7 * inch,
            ]
            t = Table(pl_data, colWidths=pl_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

        # --- NOP 7 CFR 205.204 Seed Traceability Sub-Table ------------------
        # Supplier / invoice / lot / treatment for EVERY production event that carries
        # seed-purchase data, not only PL rows.
        #
        # 🔴 2026-09-06 — the Seed Search (SS) form asks for supplier, purchase date, invoice,
        # lot number and treatment, the record saved all five, and this table iterated
        # `planting_events` (type="PL") only — so a seed search that ended in a purchase
        # printed its § 205.204(a)(1) search and none of the purchase it justified. Found by
        # the per-tile sweep on the demo farm; the transplant (TR) form has the same inputs.
        traceable = [
            ev
            for ev in all_prod_events
            if any(
                [
                    ev.seed_supplier_name,
                    ev.seed_purchase_invoice,
                    ev.seed_lot_number,
                    ev.seed_purchase_date,
                    ev.seed_treatment,
                ]
            )
        ]
        if traceable:
            elements.append(self._spacer(0.12))
            elements.append(self._body("<b>Seed Supplier &amp; Purchase Traceability (NOP 7 CFR 205.204)</b>"))
            elements.append(self._spacer(0.05))

            trace_headers = [
                "Date",
                "Variety",
                "Supplier",
                "Purchase Date",
                "Invoice #",
                "Lot #",
                "Treatment",
                # USDA "Seed Records Part C" pairs every named treatment with its
                # "Documentation of Allowed Status". A treatment with no basis is
                # unreviewable under § 205.204(a)(2).
                "Allowed Because",
            ]
            trace_rows = [[self._hdr(h) for h in trace_headers]]
            for ev in traceable:
                trace_rows.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.variety),
                        self._cell(ev.seed_supplier_name),
                        self._cell(_fmt_date(ev.seed_purchase_date)),
                        self._cell(ev.seed_purchase_invoice),
                        self._cell(ev.seed_lot_number),
                        self._cell(ev.seed_treatment),
                        self._cell(_seed_treatment_basis_display(ev)),
                    ]
                )
            trace_widths = [
                0.6 * inch,
                0.75 * inch,
                1.0 * inch,
                0.7 * inch,
                0.7 * inch,
                0.7 * inch,
                1.0 * inch,
                1.45 * inch,
            ]
            tt = Table(trace_rows, colWidths=trace_widths, repeatRows=1)
            tt.setStyle(self._base_table_style())
            elements.append(tt)

            # Warning for non-organic treated seed (disqualifying per 7 CFR 205.204(a)(2))
            treated = [ev for ev in traceable if ev.seed_certification_status == "non_organic_treated"]
            if treated:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        "<b>[WARNING] NOP 7 CFR 205.204(a)(2):</b> Non-organic seed treated "
                        "with substances not on the National List disqualifies the crop from "
                        "organic sale. "
                        "Review the highlighted planting events with your certifier before harvest.",
                        self._warning_style(),
                    )
                )

        return elements

    # ------------------------------------------------------------------
    # Section 6: Soil & Water Management
    # ------------------------------------------------------------------

    def _build_amendment_purchase_subtable(self, events):
        """Supplier / invoice / lot for purchased soil amendments — 7 CFR 205.103(b)(1)-(2).

        🔴 2026-08-16. The mirror of the chemical log's supplier sub-table, which had no
        counterpart here: CCOF's grower checklist asks for receipts for "fertilizer, compost,
        soil amendments, planting mixes" in a single line, and only one of those two models
        could answer. On a certified organic orchard the compost invoice is usually the
        largest input receipt of the year.

        Rows appear only where a purchase was actually recorded — on-farm compost is not a
        purchase, and printing an empty row for it would invent a gap that does not exist.
        """
        traceable = [
            ev
            for ev in events
            if any(
                [
                    getattr(ev, "amendment_supplier_name", None),
                    getattr(ev, "amendment_purchase_date", None),
                    getattr(ev, "amendment_purchase_invoice", None),
                    getattr(ev, "amendment_quantity_purchased", None) is not None,
                    getattr(ev, "amendment_lot_number", None),
                ]
            )
        ]
        if not traceable:
            return []

        elements = [self._spacer(0.12)]
        elements.append(
            Paragraph(
                "<b>Amendment Supplier &amp; Purchase Traceability (7 CFR 205.103(b)(2))</b>",
                self._sub_header_style(),
            )
        )
        elements.append(self._spacer(0.05))

        headers = ["Date", "Product", "Supplier", "Purchase Date", "Invoice #", "Lot #", "Qty Purchased"]
        data = [[self._hdr(h) for h in headers]]
        for ev in traceable:
            qty = None
            if getattr(ev, "amendment_quantity_purchased", None) is not None:
                qty = f"{_fmt_float(ev.amendment_quantity_purchased)} {_val(ev.amendment_quantity_purchased_unit, '')}"
            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(ev.amendment_product_name or _amendment_type_label(ev.amendment_type)),
                    self._cell(ev.amendment_supplier_name),
                    self._cell(_fmt_date(ev.amendment_purchase_date) if ev.amendment_purchase_date else None),
                    # Invoice and lot numbers are audit-trail identifiers — never truncated to
                    # a stub an inspector cannot match against the paper record.
                    self._cell(
                        f"{ev.amendment_purchase_invoice} [receipt on file]"
                        if ev.amendment_purchase_invoice and ev.receipt_document_id
                        else ("[receipt on file]" if ev.receipt_document_id else ev.amendment_purchase_invoice)
                    ),
                    self._cell(ev.amendment_lot_number),
                    self._cell(qty and qty.strip()),
                ]
            )

        widths = [0.65 * inch, 1.5 * inch, 1.25 * inch, 0.8 * inch, 0.9 * inch, 0.85 * inch, 1.0 * inch]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)
        return elements

    def _build_soil_section(self):
        elements = [self._section_header("Soil & Water Management (Common OSP G4.0)")]

        # "Operator" added 2026-09-06. Production Events, Irrigation and Pest scouting have all
        # printed `performed_by` under the organic filter from the start; soil printed nobody, so
        # a packet could name the supervisor who REVIEWED a soil record (FSMA § 112.161(b))
        # beside no one who performed it. § 205.103(b)(2) wants detail "readily understood and
        # audited", and who to interview about a pass is the first thing an inspector needs.
        # It is deliberately ALSO in the Equipment & Operator sub-table below: there it sits
        # beside the implement, which is how § 205.201(a)(5) asks the question ("whose machine
        # was on organic ground"); here it answers the plainer one, per soil record, with no
        # filter in front of it. Date and Type already repeat across four soil tables.
        headers = [
            "Date",
            "Type",
            "Soil pH",
            "Organic Matter %",
            "Amendment",
            "Amount",
            "Area",
            "Organic Status",
            "Operator",
        ]

        events = related_events(self.production, "history_soilmanagementevent_events")

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        has_amendments_without_approval = False
        compost_events = []
        grazing_events = []
        habitat_events = []
        st_events = []  # F19: soil tests carrying lab results (test_results JSON)
        for ev in events:
            amount = ""
            if ev.amendment_amount_numeric:
                amount = f"{_fmt_float(ev.amendment_amount_numeric)} {_val(ev.amendment_amount_unit, '')}"
            elif ev.amendment_amount:
                # Legacy CharField path: still append the unit when one is recorded
                # so an inspector reading "3500 kg" knows the magnitude, not just "3500".
                unit = ev.amendment_amount_unit or ""
                amount = f"{_val(ev.amendment_amount)} {unit}".strip()

            # Nitrogen applied via the amendment, appended to the Amount cell so it sits
            # beside the tonnage it derives from. California's Irrigated Lands Regulatory
            # Program requires an annual Irrigation & Nitrogen Management Plan summary of
            # total nitrogen applied FROM ALL SOURCES, and on an organic orchard compost is
            # usually the largest single source — a tonnage alone does not answer it.
            # Each total is paired with its own per-acre rate rather than stacking two
            # parentheticals: the reviewable number is PER ACRE. A compost tonnage answers
            # "how much left the pile"; tons/acre and kg N/acre answer "was the loading
            # appropriate", which is what 7 CFR 205.203 and the California ILRP nitrogen
            # summary actually ask.
            tonnage_rate = _rate_per_area(
                ev.amendment_amount_numeric, ev.area_covered, ev.amendment_amount_unit, ev.area_unit
            )
            if amount and tonnage_rate:
                amount = f"{amount} ({tonnage_rate})"

            _n_kg = _amendment_nitrogen_kg(ev)
            if _n_kg is not None:
                nitrogen_txt = f"{_n_kg:,.0f} kg N"
                nitrogen_rate = _rate_per_area(_n_kg, ev.area_covered, "kg N", ev.area_unit)
                if nitrogen_rate:
                    nitrogen_txt = f"{nitrogen_txt} ({nitrogen_rate})"
                amount = f"{amount}; {nitrogen_txt}" if amount else nitrogen_txt

            area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}" if ev.area_covered else None

            # Track amendment approval gaps
            organic_status = ""
            if ev.amendment_type:
                organic_status = _organic_basis_cell(ev, ev.amendment_organic_approved)
                if organic_status is None:
                    organic_status = "NOT SPECIFIED"
                    has_amendments_without_approval = True
                elif organic_status.startswith("NOT SPECIFIED"):
                    has_amendments_without_approval = True

            # Cover-crop species lives in extra_data.cover_crop_species, NOT amendment_type, so a
            # cover-crop row otherwise showed a blank "Amendment" cell — the planted mix (the whole
            # point of the record) was dropped from the dossier. Surface it in the Amendment column.
            amendment_display = _amendment_type_label(ev.amendment_type)
            # Specific product identity (NOP/CCOF input record) takes precedence over the
            # generic category; the category is appended in parens for context.
            _product = (getattr(ev, "amendment_product_name", "") or "").strip()
            _maker = (getattr(ev, "amendment_manufacturer", "") or "").strip()
            if _product:
                _label = f"{_product} — {_maker}" if _maker else _product
                if amendment_display and amendment_display != "—":
                    _label = f"{_label} ({amendment_display})"
                amendment_display = _label
            if not ev.amendment_type and not _product and ev.type == "CC":
                _ed = ev.extra_data if isinstance(ev.extra_data, dict) else {}
                _species = _ed.get("cover_crop_species")
                if _species:
                    amendment_display = _species

            # Block / section rides the Area cell, exactly as on the Input Application Log:
            # § 205.103(b)(2) wants the LOCATION of an amendment application, and the soil form
            # collects it on every subtype while this table had no column for it (2026-09-06).
            if getattr(ev, "block_id", None):
                block_txt = str(ev.block_id).strip()
                if not re.match(r"(?i)^(blk|block|bl)\b", block_txt):
                    block_txt = f"Blk {block_txt}"
                area = f"{area} · {block_txt}".strip(" ·") if area else block_txt

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(SOIL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell(str(ev.soil_ph) if ev.soil_ph is not None else None),
                    self._cell(str(ev.organic_matter_percentage) if ev.organic_matter_percentage is not None else None),
                    self._cell(amendment_display),
                    self._cell(amount or None),
                    self._cell(area),
                    self._cell(organic_status or None),
                    self._cell(ev.performed_by),
                ]
            )

            # Collect composting events for sub-table. Same selection as the compliance snapshot
            # (run 7, R7-09): purchased compost logged as OM/compost was absent from this table.
            if ev.type == "CO" or (ev.amendment_type or "").strip().lower() == "compost":
                compost_events.append(ev)
            # Collect grazing events for sub-table — the main soil table's amendment-oriented
            # columns leave every grazing detail blank, so integrated grazing (a key regenerative
            # practice) was invisible to the certifier. Surface it in a dedicated sub-table below.
            if ev.type == "GR":
                grazing_events.append(ev)
            # Collect biodiversity / habitat events (HD developed habitat, NS nesting/shelter) for a
            # dedicated sub-table — the amendment-oriented main columns leave habitat detail blank.
            if ev.type in ("HD", "NS"):
                habitat_events.append(ev)
            # F19: collect soil tests that carry lab RESULTS (test_results JSON) for a dedicated
            # sub-table — the main table shows only pH/OM; a certifier needs N/P/K/CEC + lab + date.
            # §E-2: lab analyses (LA) of any matrix — leaf, petiole, hull, compost, water — file
            # into the same table. An LA event is listed even with no results yet, because the
            # sample itself is the record a farmer logs on the day it ships to the lab.
            if (ev.type == "ST" and isinstance(ev.test_results, dict) and ev.test_results) or ev.type == "LA":
                st_events.append(ev)

        # 7.00in exactly — the full frame (letter 8.5in less two 0.75in margins, see the
        # SimpleDocTemplate). The eight original columns summed to 6.20in; Operator takes the
        # 0.80in that was left. A name wraps to two lines at this width, the same as it already
        # does in the Production Events table. ⛔ Nothing else may be added to this row without
        # taking width from a column that can spare it — cells wrap, they never truncate.
        col_widths = [
            0.6 * inch,
            0.8 * inch,
            0.5 * inch,
            0.7 * inch,
            1.1 * inch,
            0.8 * inch,
            0.7 * inch,
            1.0 * inch,
            0.8 * inch,
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # NOP Warning: amendments without organic approval status
        if has_amendments_without_approval:
            elements.append(
                Paragraph(
                    "<b>[WARNING] NOP 7 CFR 205.203(b):</b> Some amendments are missing organic approval status. "
                    "All soil amendments must be OMRI-listed or NOP-approved for organic operations.",
                    self._warning_style(),
                )
            )

        elements += self._build_amendment_purchase_subtable(events)

        # NOP Composting Records Sub-Table (7 CFR 205.203(c)(2)).
        # § 205.203(c)(1) is the raw-manure interval rule; composted plant /
        # animal materials live under (c)(2). Header was previously mis-cited
        # to (c)(1) — fixed 2026-04-15.
        if compost_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Compost Temperature Records (7 CFR 205.203(c)(2) · Common OSP G4.1)</b>",
                    self._sub_header_style(),
                )
            )
            compost_headers = [
                "Date",
                "Peak Temp (°F)",
                "Days at Temp",
                "Turnings",
                "Feedstock",
                "C:N (as recorded)",
                "Compliant",
            ]
            compost_data = [[self._hdr(h) for h in compost_headers]]
            for cev in compost_events:
                peak = str(cev.compost_peak_temp_f) if cev.compost_peak_temp_f is not None else "—"
                days = str(cev.compost_duration_days_at_temp) if cev.compost_duration_days_at_temp is not None else "—"
                turns = str(cev.compost_turning_count) if cev.compost_turning_count is not None else "—"

                # NOP compliance check per § 205.203(c)(2). Two acceptable pathways:
                #   • Windrow:        131-170°F for 15+ days, with 5+ turnings
                #   • In-vessel /
                #     static pile:    131-170°F for 3+ days  (no turning requirement)
                # Most demo / windrow operations document turnings; small organic farms
                # often run static piles (no turnings) and were previously stamped
                # "Non-Compliant" by the windrow-only rule.
                compliant = "—"
                cn_value = float(cev.compost_initial_cn_ratio) if cev.compost_initial_cn_ratio is not None else None
                if cn_value is not None and not (25.0 <= cn_value <= 40.0):
                    # Run 7b: "No" only when the C:N is the operation's own starting mix; a
                    # purchased compost's figure may be a finished-product analysis.
                    compliant = "No (C:N)" if _compost_cn_is_initial(cev) else "Not established (C:N basis)"
                elif cev.compost_peak_temp_f is not None and cev.compost_duration_days_at_temp is not None:
                    temp_ok = 131 <= float(cev.compost_peak_temp_f) <= 170
                    windrow_path = cev.compost_duration_days_at_temp >= 15 and (cev.compost_turning_count or 0) >= 5
                    static_path = cev.compost_duration_days_at_temp >= 3
                    compliant = "Yes" if (temp_ok and (windrow_path or static_path)) else "No"

                compost_data.append(
                    [
                        self._cell(_fmt_date(cev.date)),
                        self._cell(peak),
                        self._cell(days),
                        self._cell(turns),
                        self._cell(cev.compost_feedstock),
                        self._cell(f"{cn_value:g}:1" if cn_value is not None else None),
                        self._cell(compliant),
                    ]
                )
            compost_widths = [
                0.65 * inch,
                0.8 * inch,
                0.65 * inch,
                0.55 * inch,
                1.25 * inch,
                0.95 * inch,
                0.6 * inch,
            ]
            ct = Table(compost_data, colWidths=compost_widths, repeatRows=1)
            ct.setStyle(self._base_table_style())
            elements.append(ct)
            _harvest_dates = [
                hev.date.date()
                for hev in related_events(self.production, "history_productionevent_events", type__in=("HA",))
                if hev.date
            ]
            _rule_days = self._manure_interval_rule_for_crop()["days"]
            for cev in compost_events:
                if cev.compost_initial_cn_ratio is None or 25.0 <= float(cev.compost_initial_cn_ratio) <= 40.0:
                    continue
                _, sentence = _compost_out_of_range_assessment(cev, _harvest_dates, _rule_days)
                elements.append(Spacer(1, 3))
                elements.append(Paragraph(f"[REVIEW] {_esc(sentence)}", self._warning_style()))

            # F24: the NOP 5021 temperature-monitoring readings (free-text log) — the detailed
            # readings behind the peak-temp summary above. Shown verbatim per event.
            log_events = [ev for ev in compost_events if (ev.compost_temperature_log or "").strip()]
            if log_events:
                elements.append(Spacer(1, 6))
                # Pile ID and reading method come from USDA's Compost Production Record, which
                # heads every sheet with both. A § 205.203(c)(2) series is unattributable
                # without them: two piles and one temperature log, and an inspector cannot tell
                # which pile it describes — nor reproduce a reading with no stated depth or
                # instrument. Blank prints an em-dash rather than nothing, so a missing answer
                # reads as missing rather than as absent-by-design.
                log_data = [
                    [
                        self._hdr("Date"),
                        self._hdr("Pile / Windrow"),
                        self._hdr("Reading Location & Method"),
                        self._hdr("Temperature Monitoring Readings"),
                    ]
                ]
                for lev in log_events:
                    log_data.append(
                        [
                            self._cell(_fmt_date(lev.date)),
                            self._cell(lev.compost_unit_id),
                            self._cell(lev.compost_temp_reading_method),
                            # § 205.203(c)(2) evidence — the log is the proof of the pathway.
                            self._cell(lev.compost_temperature_log),
                        ]
                    )
                lt = Table(
                    log_data,
                    colWidths=[0.7 * inch, 0.85 * inch, 1.45 * inch, 3.4 * inch],
                    repeatRows=1,
                )
                lt.setStyle(self._base_table_style())
                elements.append(lt)

            # Warning if any compost event is missing temperature data
            missing_temp = any(
                ev.compost_peak_temp_f is None or ev.compost_duration_days_at_temp is None for ev in compost_events
            )
            if missing_temp:
                elements.append(
                    Paragraph(
                        "<b>[WARNING] NOP 7 CFR 205.203(c)(2):</b> Some composting events are missing temperature "
                        "or duration records. Composting must document peak temperature (131-170°F) and either "
                        "(a) windrow: minimum 15 days at temperature with 5+ turnings, or "
                        "(b) in-vessel / static pile: minimum 3 days at temperature.",
                        self._warning_style(),
                    )
                )

        # --- Grazing Management Records ---
        # Integrated livestock grazing is a documented soil-health / weed-control practice (and a
        # core regenerative signal). The main soil table carries no animal columns, so surface the
        # detail here: animal type/count, grazing days, purpose, and — for summary-mode entries —
        # the rotation period and number of passes.
        if grazing_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Grazing Management Records</b>",
                    self._sub_header_style(),
                )
            )
            grazing_headers = ["Period", "Animal", "Count", "Grazing Days", "Passes", "Purpose", "Area"]
            grazing_data = [[self._hdr(h) for h in grazing_headers]]
            for gev in grazing_events:
                ed = gev.extra_data if isinstance(gev.extra_data, dict) else {}
                is_summary = ed.get("is_summary") in (True, "true")

                if is_summary and ed.get("date_start") and ed.get("date_end"):
                    period = f"{ed.get('date_start')} – {ed.get('date_end')}"
                else:
                    period = _fmt_date(gev.date)

                grazing_days = ed.get("total_grazing_days") if is_summary else gev.grazing_duration_days
                # Pass count only applies to a summary rotation; single events render a dash via _cell.
                passes = ed.get("event_count") if is_summary else None

                area_total = ed.get("area_covered_total") if is_summary else None
                area_val = area_total if area_total else gev.area_covered
                area_disp = f"{_fmt_float(area_val)} {_val(gev.area_unit, '')}".strip() if area_val else None

                purpose = GRAZING_PURPOSE_LABELS.get(gev.grazing_purpose, _val(gev.grazing_purpose))

                grazing_data.append(
                    [
                        self._cell(period),
                        self._cell(_val(gev.animal_type)),
                        self._cell(str(gev.animal_count) if gev.animal_count is not None else None),
                        self._cell(str(grazing_days) if grazing_days not in (None, "") else None),
                        self._cell(str(passes) if passes not in (None, "") else None),
                        self._cell(purpose),
                        self._cell(area_disp),
                    ]
                )
            grazing_widths = [1.3 * inch, 0.8 * inch, 0.6 * inch, 0.9 * inch, 0.6 * inch, 1.2 * inch, 0.7 * inch]
            gt = Table(grazing_data, colWidths=grazing_widths, repeatRows=1)
            gt.setStyle(self._base_table_style())
            elements.append(gt)

        # --- Natural Resources & Biodiversity Conservation narrative (7 CFR 205.200 / NOP 5020) ---
        # § 205.200 requires practices that "maintain or improve the natural resources of the
        # operation, including soil and water quality." NOP 5020 is the guidance inspectors read
        # when assessing it. Rather than a score, assemble the FACTUAL practice counts already in
        # this dossier (cover crops, soil-building amendments, habitat, buffers) into one framing
        # paragraph so the conservation story is explicit, not scattered.
        cover_crop_events = [e for e in events if e.type == "CC"]
        soil_building_events = [
            e for e in events if e.type in ("OM", "CO", "PA") and (e.amendment_type or e.type == "CO")
        ]
        _conservation_parts = []
        if cover_crop_events:
            _conservation_parts.append(f"{len(cover_crop_events)} cover-crop / living-ground-cover event(s)")
        if soil_building_events:
            _conservation_parts.append(f"{len(soil_building_events)} soil-building amendment / compost event(s)")
        if habitat_events:
            _conservation_parts.append(f"{len(habitat_events)} biodiversity / habitat practice(s)")
        try:
            _parcel = self.production.parcel
            _buffers = getattr(_parcel, "buffer_zones", None) if _parcel else None
            if _buffers:
                _conservation_parts.append("documented buffer / adjoining-land record(s)")
        except Exception:  # noqa: BLE001 — buffer data is best-effort
            pass
        if _conservation_parts:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Natural Resources &amp; Biodiversity Conservation (7 CFR 205.200)</b>",
                    self._sub_header_style(),
                )
            )
            elements.append(
                self._body(
                    "Per 7 CFR 205.200 the operation must maintain or improve its natural resources "
                    "(soil, water, wetlands, woodlands, wildlife). Documented conservation practices in "
                    "this record: " + "; ".join(_conservation_parts) + ". Detail rows appear in the "
                    "soil-amendment table above, the Biodiversity &amp; Habitat Records below, and the "
                    "Buffer Zone section. (NOP 5020 — factual practice record, not a self-assigned score.)"
                )
            )

        # --- Biodiversity & Habitat Records ---
        # Documented habitat PRACTICES (HD: hedgerows, insectary, riparian, living groundcover) and
        # nesting/shelter structures (NS: owl/raptor/bee/bat boxes, insect hotels) — facts a ROC /
        # Bee Better auditor reads directly. NO biodiversity score/index (banned self-label class);
        # the living-floor / bugs / birds proof rides on the event photos, not a number.
        if habitat_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Biodiversity &amp; Habitat Records (Common OSP G4.2)</b>",
                    self._sub_header_style(),
                )
            )
            habitat_headers = [
                "Date",
                "Category",
                "Practice / Structure",
                "Count",
                "Since",
                "Area",
                "Species / Notes",
            ]
            habitat_data = [[self._hdr(h) for h in habitat_headers]]
            for hev in habitat_events:
                ed = hev.extra_data if isinstance(hev.extra_data, dict) else {}
                category = SOIL_TYPE_LABELS.get(hev.type, _val(hev.type))
                practice = HABITAT_TYPE_LABELS.get(hev.habitat_type, _val(hev.habitat_type))
                count = str(hev.habitat_structure_count) if hev.habitat_structure_count is not None else None
                since = _fmt_date(hev.habitat_install_date) if hev.habitat_install_date else None
                area_disp = (
                    f"{_fmt_float(hev.area_covered)} {_val(hev.area_unit, '')}".strip() if hev.area_covered else None
                )
                notes = (
                    " · ".join(
                        p
                        for p in (
                            ed.get("species_planted"),
                            ed.get("structure_notes"),
                            ed.get("wildlife_observed"),
                        )
                        if p
                    )
                    or None
                )
                habitat_data.append(
                    [
                        self._cell(_fmt_date(hev.date)),
                        self._cell(category),
                        self._cell(practice),
                        self._cell(count),
                        self._cell(since),
                        self._cell(area_disp),
                        self._cell(notes),
                    ]
                )
            habitat_widths = [0.8 * inch, 1.0 * inch, 1.3 * inch, 0.45 * inch, 0.7 * inch, 0.6 * inch, 1.45 * inch]
            ht = Table(habitat_data, colWidths=habitat_widths, repeatRows=1)
            ht.setStyle(self._base_table_style())
            elements.append(ht)

        # --- Laboratory Analysis Results (F19 + §E-2) ---
        # Lab results (N/P/K/CEC) + provenance for soil tests (ST) and lab analyses (LA) of any
        # matrix. A soil test showing only pH/OM is an incomplete agronomic/certifier record, and
        # a micronutrient application has no basis without the analysis that documents the
        # deficiency (7 CFR 205.601(j)(7)). Read from the test_results JSONField.
        if st_events:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("<b>Laboratory Analysis Results</b>", self._sub_header_style()))
            st_headers = [
                "Date",
                "Sample",
                "Lab",
                "Sample #",
                "Report Date",
                "N (ppm)",
                "P (ppm)",
                "K (ppm)",
                "CEC",
            ]
            st_data = [[self._hdr(h) for h in st_headers]]
            for sev in st_events:
                tr = sev.test_results if isinstance(sev.test_results, dict) else {}
                # ST predates the sample_matrix column and is soil by definition.
                matrix = (
                    sev.get_sample_matrix_display() if sev.sample_matrix else ("Soil" if sev.type == "ST" else None)
                )
                st_data.append(
                    [
                        self._cell(_fmt_date(sev.date)),
                        self._cell(matrix),
                        self._cell(tr.get("lab_name")),
                        self._cell(tr.get("sample_id")),
                        self._cell(tr.get("report_date")),
                        self._cell(_val(tr.get("nitrogen"))),
                        self._cell(_val(tr.get("phosphorus"))),
                        self._cell(_val(tr.get("potassium"))),
                        self._cell(_val(tr.get("cec"))),
                    ]
                )
            st_widths = [
                0.7 * inch,
                0.9 * inch,
                1.2 * inch,
                0.8 * inch,
                0.8 * inch,
                0.6 * inch,
                0.6 * inch,
                0.6 * inch,
                0.6 * inch,
            ]  # 6.8" — inside the 7.0" portrait budget
            st_table = Table(st_data, colWidths=st_widths, repeatRows=1)
            st_table.setStyle(self._base_table_style())
            elements.append(st_table)

            # --- Micronutrient Results (§E-2) ---
            # Kept as its own table rather than four more columns above: the results table is
            # already at 6.8" of a 7.0" budget. This is the deficiency record § 205.601(j)(7)
            # requires before a synthetic micronutrient may be applied, so it is the page an
            # inspector turns to when they see zinc or boron in the chemicals section.
            _MICRO_KEYS = (
                ("zinc_ppm", "Zn (ppm)"),
                ("boron_ppm", "B (ppm)"),
                ("manganese_ppm", "Mn (ppm)"),
                ("iron_ppm", "Fe (ppm)"),
            )
            micro_events = [
                sev
                for sev in st_events
                if isinstance(sev.test_results, dict)
                and any(sev.test_results.get(k) not in (None, "") for k, _ in _MICRO_KEYS)
            ]
            if micro_events:
                elements.append(Spacer(1, 8))
                elements.append(
                    Paragraph(
                        "<b>Micronutrient Results (7 CFR 205.601(j)(7) deficiency record)</b>",
                        self._sub_header_style(),
                    )
                )
                micro_headers = ["Date", "Sample", "Lab"] + [label for _, label in _MICRO_KEYS]
                micro_data = [[self._hdr(h) for h in micro_headers]]
                for sev in micro_events:
                    tr = sev.test_results if isinstance(sev.test_results, dict) else {}
                    matrix = (
                        sev.get_sample_matrix_display() if sev.sample_matrix else ("Soil" if sev.type == "ST" else None)
                    )
                    micro_data.append(
                        [
                            self._cell(_fmt_date(sev.date)),
                            self._cell(matrix),
                            self._cell(tr.get("lab_name")),
                            *[self._cell(_val(tr.get(key))) for key, _ in _MICRO_KEYS],
                        ]
                    )
                micro_widths = [
                    0.7 * inch,
                    0.9 * inch,
                    1.4 * inch,
                    0.7 * inch,
                    0.7 * inch,
                    0.7 * inch,
                    0.7 * inch,
                ]  # 5.8"
                micro_table = Table(micro_data, colWidths=micro_widths, repeatRows=1)
                micro_table.setStyle(self._base_table_style())
                elements.append(micro_table)

        # --- Soil Condition & Working Depth ---
        # working_depth / soil_texture are collected by SoilManagementTab
        # and, until now, rendered nowhere. They are the § 205.203 context for whether an
        # operation was appropriate: incorporation depth for an amendment, and the texture
        # and moisture that govern compaction and leaching risk when it was performed.
        # Kept as its own sub-table rather than squeezed into the test-results or equipment
        # tables — those are already near the 7.0" portrait budget, and these apply to any
        # soil sub-type, not only ST or fuel-bearing events.
        #
        # 🔴 `soil_moisture` dropped from this table 2026-08-15. Its input was removed from
        # SoilManagementTab in Sprint 2 Epic 2.1.3 (it duplicated the Weather event), so the
        # column could only ever print "—" for any record created since. A packet column with
        # no writer behind it is not disclosure — it is an empty promise on a certifier's desk.
        # The model column and its `modal` surface stay so pre-removal rows still render.
        condition_events = [ev for ev in events if ev.working_depth or ev.soil_texture]
        if condition_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Soil Condition &amp; Working Depth (7 CFR 205.203)</b>",
                    self._sub_header_style(),
                )
            )
            cond_headers = ["Date", "Type", "Working Depth", "Texture"]
            cond_data = [[self._hdr(h) for h in cond_headers]]
            for ev in condition_events:
                depth_disp = None
                if ev.working_depth:
                    depth_disp = f"{_fmt_float(ev.working_depth)} {_val(ev.depth_unit, '')}".strip()
                cond_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(SOIL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(depth_disp),
                        self._cell(ev.soil_texture),
                    ]
                )
            cond_widths = [0.85 * inch, 1.3 * inch, 1.3 * inch, 1.8 * inch]
            cond_table = Table(cond_data, colWidths=cond_widths, repeatRows=1)
            cond_table.setStyle(self._base_table_style())
            elements.append(cond_table)

        # --- Tillage Detail (7 CFR 205.203(a)) ---
        #
        # § 205.203(a) requires the operation to maintain or improve soil condition through
        # tillage and cultivation practices. A TI event records the type, the intensity, the
        # direction and how residue was handled — the four facts that ARE the practice — and
        # every one of them persists in extra_data, which no export service read. The soil table
        # above showed a date and "Tillage", which tells an inspector that something happened
        # and nothing about whether it conserves soil.
        tillage_rows = []
        for ev in events:
            if ev.type != "TI":
                continue
            extra = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            parts = []
            for key, label in (
                ("tillage_type", "Type"),
                ("tillage_intensity", "Intensity"),
                ("tillage_direction", "Direction"),
                ("residue_management", "Residue"),
            ):
                val = getattr(ev, key, None) or extra.get(key)
                if val not in (None, "", []):
                    parts.append(f"{label}: {TILLAGE_PRACTICE_LABELS.get(val, val)}")
            if parts:
                # Working depth carries its unit. The Soil Condition table above already prints
                # "4.00 inches"; printing a bare "4.00" here invites an inspector to read a
                # 4-inch pass as 4 cm (or the reverse) on the one number that distinguishes a
                # conservation pass from an inversion pass.
                depth = getattr(ev, "working_depth", None)
                depth_disp = (
                    f"{_fmt_float(depth)} {_val(ev.depth_unit, '')}".strip() if depth not in (None, "") else None
                )
                tillage_rows.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(depth_disp),
                        self._cell(" · ".join(parts)),
                    ]
                )
        if tillage_rows:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("<b>Tillage Detail (7 CFR 205.203(a))</b>", self._sub_header_style()))
            ti_data = [[self._hdr(h) for h in ["Date", "Working Depth", "Practice"]]] + tillage_rows
            ti_table = Table(ti_data, colWidths=[0.9 * inch, 1.1 * inch, 5.0 * inch], repeatRows=1)
            ti_table.setStyle(self._base_table_style())
            elements.append(ti_table)

        # --- Soil Operations: Equipment & Operator ---
        #
        # 🔴 2026-09-06 — WHO ran the pass and WITH WHAT survived a carbon-free organic export.
        #
        # This table used to be carbon-only, on the reasoning that fuel and hours are carbon
        # inputs and `CERTIFICATION_SECTIONS` excludes carbon from the NOP organic export. The
        # fuel half of that is right. The other half took the implement and the operator down
        # with it, and those are § 205 facts, not carbon facts:
        #
        #   EQUIPMENT — `_build_equipment_section` already states the rule for this exact
        #   trade-off, in these words: "Fuel/hours are carbon inputs; equipment IDENTITY and
        #   area worked are the § 205.272 shared-equipment facts a certifier reads. Keep the
        #   second pair on a NOP organic export, drop the first." The soil section dropped all
        #   seven columns together, so the same fact survived in one section and vanished in
        #   another. On a SPLIT OPERATION § 205.201(a)(5) makes the implement load-bearing: the
        #   OSP must describe the barriers that keep organic ground clear of prohibited
        #   substances, and an inspector cannot tie an Equipment Cleaning Log (§ 205.272) to a
        #   pass whose record names no implement. MEASURED on the Calapooia Bend carrot packet
        #   (2026-09-06): "Split operation: Yes", "Parallel production: Yes", an (a)(5) narrative
        #   of 6,968 characters — and a June tillage pass that named neither its tractor nor its
        #   harrow, because the packet ran with the USDA Organic filter.
        #
        #   OPERATOR — `performed_by` is on CommonEvent, and Production Events, Irrigation and
        #   Pest scouting all print it under the same organic filter. Soil was the only family
        #   that printed nobody, so a packet could name the supervisor who REVIEWED a soil
        #   record (FSMA § 112.161(b)) beside no one who performed it. § 205.103(b)(2) asks for
        #   detail "readily understood and audited"; who to interview about a pass is the first
        #   thing an inspector needs from it.
        #
        # ⛔ NOT a new question for the farmer. Both fields are already collected — equipment by
        # SoilManagementTab, `performed_by` by wizard step 0 for every event type. This only
        # stops discarding them.
        #
        # The row filter widens with the columns. Filtering on fuel-or-hours alone yielded "the
        # tillage passes where someone happened to log diesel" under a heading that reads like a
        # complete equipment record; adding equipment-or-operator makes the table cover every
        # soil operation that names either, which is what the heading now claims.
        equip_events = [
            ev
            for ev in events
            if ev.equipment_used
            or ev.performed_by
            or (self.carbon_in_scope and ((ev.fuel_consumed and float(ev.fuel_consumed) > 0) or ev.equipment_hours))
        ]
        if equip_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Soil Operations \u2014 Equipment &amp; Operator (7 CFR 205.201(a)(5))</b>",
                    self._sub_header_style(),
                )
            )
            # Equipment and Operator are adjacent on purpose: § 205.201(a)(5) is answered by the
            # PAIR ("whose machine was on organic ground"), not by either alone.
            eq_headers = [
                "Date",
                "Type",
                "Equipment",
                "Operator",
                *(["Fuel", "Fuel Type", "Hours"] if self.carbon_in_scope else []),
            ]
            eq_data = [[self._hdr(h) for h in eq_headers]]
            for ev in equip_events:
                fuel_disp = f"{_fmt_float(ev.fuel_consumed)} {_val(ev.fuel_unit, '')}" if ev.fuel_consumed else None
                eq_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(SOIL_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        # ⛔ No `or ev.name` fallback. It printed the ACTIVITY TITLE ("Spinach
                        # residue incorporated + beds reformed") in a column headed Equipment,
                        # which answers the § 205.201(a)(5) question with something that is not
                        # an implement. A dash says "not recorded"; a title says the wrong thing
                        # confidently, on a document an inspector reads as a record.
                        self._cell(ev.equipment_used),
                        self._cell(ev.performed_by),
                        *(
                            [
                                self._cell(fuel_disp),
                                self._cell(ev.fuel_type),
                                self._cell(str(ev.equipment_hours) if ev.equipment_hours else None),
                            ]
                            if self.carbon_in_scope
                            else []
                        ),
                    ]
                )
            eq_widths = (
                [0.65 * inch, 0.8 * inch, 1.4 * inch, 1.0 * inch, 0.75 * inch, 0.7 * inch, 0.55 * inch]
                if self.carbon_in_scope
                # 6.00" of the 7.00" portrait budget. The implement string is the long one
                # ("John Deere 6120M + 15 ft flail, 18 ft offset disc, Perfecta harrow"), so the
                # width freed by dropping three carbon columns goes to it rather than being
                # spread evenly — cells wrap, they never truncate.
                else [0.75 * inch, 1.05 * inch, 2.85 * inch, 1.35 * inch]
            )
            eq_table = Table(eq_data, colWidths=eq_widths, repeatRows=1)
            eq_table.setStyle(self._base_table_style())
            elements.append(eq_table)

        # NOP Raw Manure Harvest Interval Records Sub-Table (7 CFR 205.203(c)(1)).
        # Raw animal manure requires 90 or 120 day pre-harvest interval depending on
        # crop-soil contact (§ 205.203(c)(1)(ii)/(iii)). Certifiers review this to
        # verify no contamination risk. Composted materials live under (c)(2) — do
        # not confuse the citations.
        # Filter on the manure-specific fields rather than the OM subtype: farmers
        # may log a manure application as Cover Crop (CC) or Organic Matter (OM);
        # the regulatory data is on the model, not the subtype label.
        manure_events = [ev for ev in events if ev.manure_harvest_interval or ev.manure_application_date]
        if manure_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Manure Handling Records (7 CFR 205.203(c)(1))</b>",
                    self._sub_header_style(),
                )
            )
            # "Planned Harvest" mirrors the "Date of Harvest — Estimated" column on USDA's
            # crop documentation form. The ACTUAL harvest date is the harvest event, which
            # `_validate_raw_manure_harvest_interval` already checks; showing the estimate
            # beside the earliest safe date is what lets an inspector see whether the plan was
            # sound when the manure went on, rather than only whether the outcome happened to be.
            manure_headers = [
                "Date Applied",
                "Harvest Interval",
                "Amendment Type",
                "Earliest Safe Harvest",
                "Planned Harvest",
                "Crop-Rule Check",
            ]
            # Resolve the crop's required interval ONCE so each row can be
            # checked against it. Inline per-row rule check makes the
            # mismatch impossible to miss when an inspector flips to this
            # page (the page-2 Pre-Export Consistency Check covers the
            # same finding at the executive summary level).
            try:
                expected_rule = self._manure_interval_rule_for_crop()
            except Exception:  # noqa: BLE001
                expected_rule = None
            manure_data = [[self._hdr(h) for h in manure_headers]]
            row_warning_indices = []  # 1-based row indices that need red-text styling
            any_mismatch = False
            for mev in manure_events:
                interval_display = mev.get_manure_harvest_interval_display() if mev.manure_harvest_interval else "—"
                # Earliest safe harvest = application_date + interval days (if both present)
                earliest_harvest = None
                if mev.manure_application_date and mev.manure_harvest_interval:
                    try:
                        from datetime import timedelta

                        # manure_harvest_interval stored as "90", "120", or "na"
                        # (MANURE_INTERVAL_CHOICES on SoilManagementEvent). Split on
                        # "_" is a defensive no-op that also tolerates legacy
                        # "90_days" / "120_days" rows imported before the schema
                        # tightened — isdigit() filters out "na".
                        interval_str = str(mev.manure_harvest_interval).split("_")[0]
                        if interval_str.isdigit():
                            earliest_harvest = (
                                mev.manure_application_date + timedelta(days=int(interval_str))
                            ).isoformat()
                    except (TypeError, ValueError, AttributeError):
                        # TypeError added: `str + timedelta` on an ISO-string date column was
                        # uncaught here and would have taken the whole PDF down with it.
                        earliest_harvest = None

                # Crop-rule check column. The page-2 consistency linter
                # surfaces these mismatches at the cover-page level; here
                # we annotate the offending row directly so the inspector
                # sees it in context, not just as an executive-summary line.
                rule_check_text = "—"
                rule_check_is_warning = False
                if expected_rule and mev.manure_harvest_interval:
                    interval_str = str(mev.manure_harvest_interval).split("_")[0]
                    if interval_str.isdigit():
                        try:
                            farmer_days = int(interval_str)
                            if farmer_days == expected_rule["days"]:
                                rule_check_text = f"OK — matches {expected_rule['cite']}"
                            else:
                                rule_check_text = (
                                    f"MISMATCH — crop requires "
                                    f"{expected_rule['days']}-day per "
                                    f"{expected_rule['cite']}"
                                )
                                rule_check_is_warning = True
                                any_mismatch = True
                        except ValueError:
                            pass

                # Does the PLAN clear the interval it declares?
                #
                # The crop-rule check above compares the farmer's SELECTED interval against the
                # crop's soil-contact classification — it validates the LABEL. It says nothing
                # about the dates: a farmer can select the correct 120 days for a soil-contact
                # crop, clearing that check, and plan harvest 60 days after application. Both
                # dates were already printed side by side here, in black, leaving the arithmetic
                # to whoever read the page. The field's own help text promises the opposite —
                # "so the 90/120-day interval can be checked against your plan".
                plan_short_by = None
                if earliest_harvest and mev.manure_harvest_date_planned:
                    try:
                        from datetime import date as _date

                        earliest_d = _date.fromisoformat(earliest_harvest)
                        planned_d = mev.manure_harvest_date_planned
                        planned_d = planned_d.date() if hasattr(planned_d, "date") else planned_d
                        if planned_d < earliest_d:
                            plan_short_by = (earliest_d - planned_d).days
                    except (ValueError, TypeError, AttributeError):
                        plan_short_by = None

                if plan_short_by:
                    rule_check_is_warning = True
                    any_mismatch = True
                    # Terse on purpose: this column is 1.35in wide. The full sentence — which
                    # date, which clause, what to do about it — is the page-2 finding.
                    short_note = f"Plan short by {plan_short_by} days"
                    rule_check_text = short_note if rule_check_text == "—" else f"{rule_check_text}; {short_note}"

                manure_data.append(
                    [
                        self._cell(_fmt_date(mev.manure_application_date) if mev.manure_application_date else None),
                        self._cell(interval_display),
                        self._cell(_amendment_type_label(mev.amendment_type)),
                        self._cell(earliest_harvest),
                        self._cell(
                            _fmt_date(mev.manure_harvest_date_planned) if mev.manure_harvest_date_planned else None
                        ),
                        self._cell(rule_check_text),
                    ]
                )
                if rule_check_is_warning:
                    row_warning_indices.append(len(manure_data) - 1)
            manure_widths = [0.8 * inch, 0.9 * inch, 1.0 * inch, 0.95 * inch, 0.9 * inch, 1.35 * inch]
            mt = Table(manure_data, colWidths=manure_widths, repeatRows=1)
            # Apply red text to mismatched rows so the inspector's eye is
            # drawn straight to the offending entry. Merge the warning
            # overlays into the base style's command list BEFORE the
            # single setStyle() call — ReportLab's Table.setStyle contract
            # between versions has varied between "append" and "replace",
            # so we assemble one TableStyle and set it once to be safe.
            # Coordinate convention: (col, row), 0-indexed, header is
            # row 0.
            base_cmds = list(self._base_table_style().getCommands())
            warning_overlay_cmds = []
            for ridx in row_warning_indices:
                warning_overlay_cmds.append(("TEXTCOLOR", (5, ridx), (5, ridx), colors.HexColor("#B71C1C")))
                warning_overlay_cmds.append(("FONTNAME", (5, ridx), (5, ridx), "Helvetica-Bold"))
            mt.setStyle(TableStyle(base_cmds + warning_overlay_cmds))
            elements.append(mt)

            # USDA's form also asks "How Applied / Incorporated" ("Manure spreader disk in")
            # and "Manure Type, Form and Source" ("Chicken, dry, on farm"). They are rendered
            # as per-row detail LINES rather than two more columns: the table is already
            # 5.9in of the ~6.4in available, and two more would need ~2.2in. This is the same
            # treatment the buffer-zone section gives its CCOF Section D&E descriptors.
            #
            # Adding columns would also have shifted the warning overlay's hard-coded column
            # index 5 — the reindexing trap this file has hit before.
            manure_detail_lines = []
            for mev in manure_events:
                tfs = mev.manure_type_form_source_display()
                applied = mev.get_manure_application_method_display() if mev.manure_application_method else ""
                if not (tfs or applied):
                    continue
                bits = []
                if tfs:
                    bits.append(_esc(tfs))
                if applied:
                    bits.append("applied: " + _esc(applied))
                date_txt = _esc(_fmt_date(mev.manure_application_date) if mev.manure_application_date else None)
                manure_detail_lines.append(f"<b>{date_txt}:</b> " + "; ".join(bits))
            if manure_detail_lines:
                elements.append(self._spacer(0.06))
                elements.append(self._body("Manure type, form, source and application method:"))
                for line in manure_detail_lines:
                    elements.append(Paragraph("&bull; " + line, self._styles["footer_note"]))
            if any_mismatch:
                elements.append(
                    Paragraph(
                        "<b>[WARNING] § 205.203(c)(1):</b> One or more manure "
                        "events above have a farmer-selected harvest interval "
                        "that does not match the soil-contact classification "
                        "required for this crop. The Pre-Export Consistency "
                        "Check on page 2 lists each mismatched event by date "
                        "with the correct interval. Update the event record "
                        "before submitting this dossier to a certifier — an "
                        "inspector will flag the mismatch as a record-keeping "
                        "failure even when no contamination occurred.",
                        self._warning_style(),
                    )
                )

        # --- Soil Notes (mirrors the Production Event Notes pattern) ---
        elements.extend(self._build_event_notes_subtable(events, "Soil Notes", SOIL_TYPE_LABELS))

        return elements

    # ------------------------------------------------------------------
    # Section 7: Pest Management
    # ------------------------------------------------------------------

    def _build_pest_section(self):
        elements = [self._section_header("Pest Management (Common OSP G5.0)")]

        headers = [
            "Date",
            "Type",
            "Pest Species",
            "Crop Stage",
            "Identified By",
            "Pressure",
            "Damage %",
            "Area",
            "Block",
            "IPM Strategy",
            "Beneficial / Qty",
        ]

        events = related_events(self.production, "history_pestmanagementevent_events")

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        has_threshold_without_rationale = False
        for ev in events:
            identified = ""
            if ev.identified_by:
                identified = ev.get_identified_by_display()
                if ev.identification_method:
                    identified += f" ({ev.identification_method[:30]})"

            if ev.action_threshold_met and not ev.threshold_rationale:
                has_threshold_without_rationale = True

            beneficial_display = ev.beneficial_species or ""
            if ev.release_quantity:
                beneficial_display = (
                    f"{beneficial_display} ({ev.release_quantity})" if beneficial_display else str(ev.release_quantity)
                )
            # Surface natural-enemy use/conservation status even when no species was named
            # (beneficial_insects_used was previously dropped from the export entirely).
            if not beneficial_display and getattr(ev, "beneficial_insects_used", "") in ("yes", "planning"):
                beneficial_display = f"Natural enemies: {ev.beneficial_insects_used}"

            damage_display = f"{_fmt_float(ev.damage_percentage)}%" if ev.damage_percentage is not None else None
            area_display = (
                f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}".strip() if ev.area_covered else None
            )

            # F44: surface the quantitative UC-IPM monitoring count next to the qualitative pressure
            pressure_display = ev.pest_pressure_level or None
            if ev.monitoring_count is not None:
                # Compact units (the Pressure column is narrow) — e.g. "low · 5/leaf".
                _unit_lbls = {
                    "per_leaf": "/leaf",
                    "per_trap": "/trap",
                    "per_tree": "/tree",
                    "per_100_fruit": "/100fr",
                    "percent_infested": "% inf",
                    "per_sample": "/sample",
                }
                _cnt = f"{_fmt_float(ev.monitoring_count)}{_unit_lbls.get(ev.monitoring_unit, '')}"
                pressure_display = f"{pressure_display} · {_cnt}" if pressure_display else _cnt

            # Crop growth stage is what makes a pest count actionable — the same mite
            # density is trivial at dormancy and economic at bloom. It lives on CommonEvent
            # and appeared in no export. This table had 0.5" of unused width, so it gets a
            # real column rather than being crammed into the 0.8" species cell.
            # PestManagementTab stores it under `crop_growth_stage` in extra_data, so read
            # the model column first and fall back to the form's key.
            stage = ev.get_growth_stage_display() if ev.growth_stage else None
            if not stage and isinstance(ev.extra_data, dict):
                raw_stage = ev.extra_data.get("crop_growth_stage") or None
                # 🔴 2026-08-19: printed raw, so an inspector read "fruit_development".
                #
                # The two vocabularies are genuinely disjoint, which is why the display call
                # above can never resolve this value: the MODEL's growth_stage is
                # dormant/budbreak/bloom/fruit_set/vegetative/maturation/harvest_ready/
                # post_harvest, while the pest form's crop_growth_stage is
                # seedling/vegetative/flowering/fruit_development/maturity/harvest. Unifying
                # them is the real fix and touches the form plus stored rows; until then this
                # at least names the stage in the grower's own words instead of a slug.
                stage = PEST_CROP_STAGE_LABELS.get(raw_stage, raw_stage)

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(PEST_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell(ev.pest_species),
                    self._cell(stage),
                    self._cell(identified or None),
                    self._cell(pressure_display),
                    self._cell(damage_display),
                    self._cell(area_display),
                    self._cell(ev.block_id),
                    self._cell(ev.ipm_strategy),
                    self._cell(beneficial_display or None),
                ]
            )

        # Total 7.00" — letter portrait with 0.75" margins.
        #
        # 🔴 2026-08-19: at twelve columns this table averaged 0.58" and ReportLab wrapped
        # values mid-token — a dress-rehearsal packet printed the event date as "2025-05-1"
        # over "4", and headers as "Pressur/e", "Damag/e %", "Threshol/d Met". A broken date
        # on the one column an inspector traces by is not a cosmetic problem.
        #
        # "Threshold Met" was dropped rather than narrowed: the Action Threshold Monitoring &
        # Rationale table immediately below already carries it PLUS the rationale, so the
        # column was duplicating a fact that is better presented there. The freed 0.50" went
        # to Date (never wraps an ISO date now) and Crop Stage.
        t = Table(data, colWidths=PEST_EVENT_WIDTHS, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # --- Summary-mode scouting (§ 205.206(a)) ---
        #
        # Same defect as the chemical Input Application Log, in a different family: a grower who
        # logs a season of scouting as ONE summary event carries the pass count, the species seen
        # across the season and the average pressure in `extra_data`, and the per-event columns
        # above are blank by design. None of it reached the certifier — the monitoring record
        # that § 205.206(a) turns on arrived as an empty row.
        pest_summary_rows = []
        for ev in events:
            ed = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            if ed.get("is_summary") not in (True, "true"):
                continue
            span = " to ".join(x for x in (ed.get("date_start"), ed.get("date_end")) if x)
            parts = []
            for key, label in (
                ("event_count", "Scouting passes"),
                ("pest_species_observed", "Species observed"),
                ("average_pest_pressure", "Average pressure"),
                ("area_covered_total", "Area covered"),
            ):
                v = ed.get(key)
                if v not in (None, "", []):
                    parts.append(f"{label}: {v}")
            if parts:
                pest_summary_rows.append([self._cell(span or _fmt_date(ev.date)), self._cell(" · ".join(parts))])
        if pest_summary_rows:
            elements.append(self._spacer(0.12))
            elements.append(self._body("<b>Summary-Mode Monitoring (7 CFR 205.206(a))</b>"))
            ps_data = [[self._hdr(h) for h in ["Period", "Season totals"]]] + pest_summary_rows
            ps = Table(ps_data, colWidths=[1.5 * inch, 5.5 * inch], repeatRows=1)
            ps.setStyle(self._base_table_style())
            elements.append(ps)

        # --- Beneficial-Release & Trap Detail (7 CFR 205.206) ---
        # Source traceability for introduced biological controls (supplier / lot / organic status)
        # and real trap-monitoring catch data — the main table stays readable; a certifier reads the
        # release provenance and trap pressure here.
        BR_ORGANIC_LABELS = {"yes": "Yes", "no": "No", "unknown": "Unknown"}
        TRAP_TYPE_LABELS = {
            "sticky": "Sticky card",
            "pheromone": "Pheromone lure",
            "delta": "Delta trap",
            "bucket_funnel": "Bucket / funnel",
            "gopher_trap": "Gopher trap",
            "ground_squirrel_trap": "Ground squirrel trap",
            "other": "Other",
        }
        detail_events = [
            ev
            for ev in events
            if ev.beneficial_supplier
            or ev.beneficial_lot_number
            or ev.beneficial_organic_approved
            or ev.trap_type
            or ev.trap_count is not None
            or ev.pest_catch_count is not None
            or ev.chemical_free_period_days is not None
        ]
        if detail_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Beneficial-Release &amp; Trap Detail (7 CFR 205.206)</b>",
                    self._sub_header_style(),
                )
            )
            detail_headers = [
                "Date",
                "Type",
                "Supplier",
                "Lot #",
                "Organic OK",
                "Trap Type",
                # A catch count without a trap count is not a pressure reading. 180 moths
                # across 3 traps and 180 across 40 traps are opposite findings, and the
                # per-trap figure is what UC IPM thresholds are written against. The model
                # has carried `trap_count` since the TM subtype shipped; this table printed
                # the catch beside the trap KIND and left the denominator off the page.
                "Traps",
                "Catch",
                # chemical_free_period_days was collected by PestManagementTab and rendered
                # nowhere. It is the interval an organic operation can actually point to when
                # asked how long a block went without an intervention — the practical evidence
                # behind a § 205.206 prevention-first claim.
                "Chem-Free (days)",
            ]
            detail_data = [[self._hdr(h) for h in detail_headers]]
            for ev in detail_events:
                detail_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PEST_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.beneficial_supplier),
                        self._cell(ev.beneficial_lot_number),
                        self._cell(BR_ORGANIC_LABELS.get(ev.beneficial_organic_approved)),
                        self._cell(TRAP_TYPE_LABELS.get(ev.trap_type) if ev.trap_type else None),
                        self._cell(str(ev.trap_count) if ev.trap_count is not None else None),
                        self._cell(str(ev.pest_catch_count) if ev.pest_catch_count is not None else None),
                        self._cell(
                            str(ev.chemical_free_period_days) if ev.chemical_free_period_days is not None else None
                        ),
                    ]
                )
            # Nine columns, 7.00" — letter portrait with 0.75" margins. The table had 0.50"
            # of unused width, which is exactly what "Traps" costs, so NO existing column was
            # narrowed to make room for it.
            detail_widths = [
                0.7 * inch,  # Date
                0.9 * inch,  # Type
                1.3 * inch,  # Supplier
                0.8 * inch,  # Lot #
                0.65 * inch,  # Organic OK
                0.9 * inch,  # Trap Type
                0.5 * inch,  # Traps
                0.55 * inch,  # Catch
                0.7 * inch,  # Chem-Free (days)
            ]
            dt = Table(detail_data, colWidths=detail_widths, repeatRows=1)
            dt.setStyle(self._base_table_style())
            elements.append(dt)

        # NOP Threshold Monitoring & Rationale Sub-Table (7 CFR 205.206(a) + (e))
        # Per § 205.206(a), scouting/monitoring decisions are documented whether or
        # not an action threshold was met — hiding "below-threshold" rationale
        # would erase the IPM paper trail an inspector needs to confirm prevention.
        rationale_events = [ev for ev in events if ev.threshold_rationale and ev.threshold_rationale.strip()]
        if rationale_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Action Threshold Monitoring &amp; Rationale (7 CFR 205.206(a), (e))</b>",
                    self._sub_header_style(),
                )
            )
            rationale_headers = ["Date", "Pest Species", "Threshold Met", "Rationale"]
            rationale_data = [[self._hdr(h) for h in rationale_headers]]
            for ev in rationale_events:
                rationale_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(ev.pest_species),
                        self._cell(
                            "Not assessed"
                            if ev.action_threshold_met is None
                            else ("Yes" if ev.action_threshold_met else "No")
                        ),
                        # NOT truncated — this is the § 205.206(e) justification for
                        # applying a material, which is the whole reason the row exists.
                        self._cell(ev.threshold_rationale),
                    ]
                )
            rationale_widths = [0.7 * inch, 1.5 * inch, 0.7 * inch, 3.3 * inch]
            rt = Table(rationale_data, colWidths=rationale_widths, repeatRows=1)
            rt.setStyle(self._base_table_style())
            elements.append(rt)

        # Warning if threshold met but no rationale documented
        if has_threshold_without_rationale:
            elements.append(
                Paragraph(
                    "<b>[WARNING] NOP 7 CFR 205.206(e):</b> Some pest events have action threshold met "
                    "but no rationale documented. Organic operations must document why the threshold "
                    "was reached before applying any pest control material.",
                    self._warning_style(),
                )
            )

        # Warning when the IPM strategy field is blank on an INTERVENTION — § 205.206(a)
        # requires a documented prevention strategy (cultural/mechanical/biological
        # practices) before a pest-control substance is used. Monitoring records are excluded:
        # see PEST_MONITORING_TYPES.
        missing_ipm = [
            ev
            for ev in events
            if ev.type not in PEST_MONITORING_TYPES and not (ev.ipm_strategy and ev.ipm_strategy.strip())
        ]
        if missing_ipm:
            elements.append(
                Paragraph(
                    f"<b>[WARNING] NOP 7 CFR 205.206(a):</b> {len(missing_ipm)} pest event(s) "
                    "missing IPM strategy. Operations must document the cultural, mechanical, "
                    "or biological prevention practices used before any pest-control intervention.",
                    self._warning_style(),
                )
            )

        # --- Preventive Cultural Practices (§E-4, 7 CFR 205.206(a)) ---
        # Its own sub-table because the main pest table is a 12-column monitoring record already
        # at the 7.0" portrait budget, and because this is what an inspector reads FIRST: the
        # § 205.206(e) justification for any substance applied later rests on these practices
        # having been performed and found insufficient.
        cultural_events = [ev for ev in events if ev.type == "CU" or ev.cultural_practice]
        if cultural_events:
            elements.append(Spacer(1, 10))
            elements.append(
                Paragraph(
                    "<b>Preventive Cultural Practices (7 CFR 205.206(a))</b>",
                    self._sub_header_style(),
                )
            )
            # No "Custom Operator" column: operator_is_custom lives on ProductionEvent (§E-5),
            # so on a pest event it would print "—" on every row — an empty column that reads
            # like missing data rather than an absent concept. `performed_by` names who did it.
            cu_headers = ["Date", "Practice", "Target Pest", "Area", "Performed By"]
            cu_data = [[self._hdr(h) for h in cu_headers]]
            for ev in cultural_events:
                practice = CULTURAL_PRACTICE_LABELS.get(ev.cultural_practice, _val(ev.cultural_practice))
                area = f"{_fmt_float(ev.area_covered)} {_val(ev.area_unit, '')}".strip() if ev.area_covered else None
                cu_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(practice),
                        self._cell(ev.pest_species),
                        self._cell(area),
                        self._cell(ev.performed_by),
                    ]
                )
            cu_widths = [
                0.8 * inch,
                2.1 * inch,
                1.5 * inch,
                0.9 * inch,
                1.6 * inch,
            ]  # 6.9"
            cu_table = Table(cu_data, colWidths=cu_widths, repeatRows=1)
            cu_table.setStyle(self._base_table_style())
            elements.append(cu_table)
            elements.append(
                Paragraph(
                    f"{len(cultural_events)} preventive cultural practice(s) documented. § 205.206(a) "
                    "requires cultural, mechanical and biological practices before any pest-control "
                    "substance; these records are the basis for that sequence.",
                    self._styles["footer_note"],
                )
            )

        # --- Pest Notes (mirrors the Production Event Notes pattern) ---
        elements.extend(self._build_event_notes_subtable(events, "Pest Notes", PEST_TYPE_LABELS))

        return elements

    # ------------------------------------------------------------------
    # Section 8: Equipment & Maintenance
    # ------------------------------------------------------------------

    def _build_shared_equipment_coverage_subtable(self):
        """§E-5 — which shared-equipment operations are covered by which cleaning (§ 205.272).

        The cleaning-log table above proves cleanings HAPPENED. This one answers the question an
        inspector actually asks next: was THIS organic pass preceded by one? A custom operator's
        harvester can be in a conventional block the same morning, so the pairing — not the count
        — is the evidence.

        A row without a link says exactly that, rather than borrowing credit from an unrelated
        cleaning elsewhere in the season.
        """
        operations = [
            ev
            for ev in related_events(self.production, "history_productionevent_events")
            # EM events ARE the cleaning records; they belong in the cleaning-log table above,
            # not in the list of operations that need one.
            if (ev.shared_with_conventional or ev.operator_is_custom) and ev.type != "EM"
        ]
        if not operations:
            return []

        rows = []
        for ev in operations:
            cleaning = ev.equipment_cleaning_event
            if cleaning is None:
                coverage = "REVIEW — no cleaning event linked"
            elif not (
                cleaning.cleaning_date
                and (cleaning.cleaning_method or "").strip()
                and (cleaning.cleaned_by or "").strip()
            ):
                coverage = "REVIEW — linked cleaning incomplete"
            elif ev.date and cleaning.date and cleaning.date > ev.date:
                # clean() blocks this going forward; historical rows may predate the guard.
                coverage = "REVIEW — linked cleaning is dated after the operation"
            else:
                coverage = f"Cleaned {_fmt_date(cleaning.cleaning_date)} — {_val(cleaning.cleaning_method)}"

            rows.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell("Yes" if ev.shared_with_conventional else "No"),
                    self._cell("Yes" if ev.operator_is_custom else "No"),
                    self._cell(ev.performed_by),
                    self._cell(coverage),
                ]
            )

        elements = [
            self._spacer(0.15),
            Paragraph(
                "<b>Shared Equipment &amp; Custom Operators — Cleaning Coverage (7 CFR 205.272)</b>",
                self._sub_header_style(),
            ),
        ]
        table = Table(
            [[self._hdr(h) for h in ("Date", "Operation", "Shared", "Custom Op.", "Performed By", "Cleaning Coverage")]]
            + rows,
            colWidths=[0.7 * inch, 1.2 * inch, 0.6 * inch, 0.7 * inch, 1.2 * inch, 2.4 * inch],  # 6.8"
            repeatRows=1,
        )
        table.setStyle(self._base_table_style())
        elements.append(table)
        return elements

    def _build_equipment_section(self):
        """
        Equipment & Maintenance — includes cleaning logs per 7 CFR 205.272.

        NOP requires equipment cleaning documentation when equipment is shared
        between organic and conventional operations. This is a common audit
        non-conformance finding.
        """
        elements = [self._section_header("Equipment Cleaning & Maintenance (7 CFR 205.272)")]

        headers = [
            "Date",
            "Type",
            "Equipment",
            # Fuel/hours are carbon inputs; equipment IDENTITY and area worked are the
            # § 205.272 shared-equipment facts a certifier reads. Keep the second pair on a
            # NOP organic export, drop the first.
            *(["Fuel Used", "Fuel Type", "Hours"] if self.carbon_in_scope else []),
            "Area Worked",
        ]

        events = related_events(self.production, "history_equipmentevent_events")

        if not events:
            # 🔴 2026-08-15 — the placeholder table is gone.
            #
            # EquipmentEvent has no form: the tab was removed when equipment merged into
            # Production as the EM subtype, and type 4 was dropped from the event picker. So
            # this section printed "No records for this production" on EVERY farm onboarded
            # since — an empty table for a record type the product no longer lets anyone
            # create, which reads to a certifier as a gap rather than a non-applicable.
            #
            # Still no early return: the Equipment Cleaning Logs and Post-Harvest Sanitation
            # subsections below live on ProductionEvent and must render regardless.
            pass
        else:
            header_row = [self._hdr(h) for h in headers]
            data = [header_row]
            for ev in events:
                fuel = ev.fuel_consumed or ev.fuel_amount
                fuel_display = f"{_fmt_float(fuel)} {_val(ev.fuel_unit, '')}" if fuel else None
                hours = ev.hours_operated or ev.hours_used
                area = str(ev.area_worked) if ev.area_worked else (str(ev.area_covered) if ev.area_covered else None)

                data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(EQUIPMENT_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.equipment_name),
                        *(
                            [
                                self._cell(fuel_display),
                                self._cell(ev.fuel_type),
                                self._cell(str(hours) if hours else None),
                            ]
                            if self.carbon_in_scope
                            else []
                        ),
                        self._cell(area),
                    ]
                )

            # Equipment absorbs the 2.30" freed when the three carbon columns drop, so both
            # layouts total 6.25in inside the 7.00in frame.
            col_widths = [
                0.65 * inch,
                0.9 * inch,
                (1.5 if self.carbon_in_scope else 3.8) * inch,  # Equipment
                *([0.85 * inch, 0.85 * inch, 0.6 * inch] if self.carbon_in_scope else []),
                0.9 * inch,
            ]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

        # --- Equipment Cleaning Logs (7 CFR 205.272) ---
        # Required for shared equipment between organic and conventional.
        # Cleaning fields are on ProductionEvent (EM subtype), NOT EquipmentEvent.
        # An EM event counts as a cleaning record if it carries ANY of the
        # cleaning-log fields OR any of the post-harvest sanitizer fields —
        # otherwise the sanitation subsection below would be hidden on events
        # that recorded sanitizer detail without completing the cleaning core.
        # 🔴 2026-08-15 — PH included, not EM alone.
        #
        # The form has sent the five sanitizer fields for POST-HARVEST events since 2026-07-31
        # (a fix whose own comment says "a post-harvest wash could never submit them"). This
        # query never followed, so a produce wash's sanitizer name, ppm, residual-at-discharge,
        # rinse step and § 205.605 reference were written, stored, serialized — and printed
        # nowhere. That is the FOOD-CONTACT case, i.e. the one § 205.605(b) actually governs,
        # and it was the one case the packet could not show.
        cleaning_events = [
            ev
            for ev in related_events(self.production, "history_productionevent_events", type__in=("EM", "PH"))
            if ev.cleaning_date
            or ev.cleaning_method
            or ev.shared_with_conventional
            or ev.sanitizer_name
            or ev.sanitizer_ppm is not None
            or ev.sanitizer_nop_reference
            or ev.rinse_step_documented
        ]

        if cleaning_events or self.certification_type in ("organic", "roc", "all"):
            elements.append(self._spacer(0.15))
            # No CFR cite here: the section heading above already carries § 205.272, and
            # repeating it nine lines later is noise on a page an inspector scans.
            elements.append(self._body("<b>Equipment Cleaning Logs</b>"))
            elements.append(self._spacer(0.05))

            if cleaning_events:
                # "What Was Cleaned" added 2026-08-15. USDA's Equipment Cleaning Log column is
                # "Equipment **or Surface**", and `equipment_type`'s enum (tractor / harvester /
                # sprayer / truck / generator / pump / other) cannot say bins, cooler or
                # trailer — the three answers a certifier most wants on a § 205.272 log.
                # `cleaning_asset_class` is exactly that field and had zero packet occurrences.
                cl_headers = [
                    "What Was Cleaned",
                    "Equipment",
                    "Op Type",
                    "Cleaning Date",
                    "Method",
                    "Materials Used",
                    "Cleaned By",
                    "Rinse",
                    "Shared w/ Conv.",
                    "Protocol Ref",
                ]
                cl_header_row = [self._hdr(h) for h in cl_headers]
                cl_data = [cl_header_row]

                # Map equipment_operation_type code → human-readable label for audit clarity
                EQ_OP_LABELS = {
                    "FC": "Fuel Consumption",
                    "MN": "Maintenance",
                    "RE": "Repair",
                    "CA": "Calibration",
                    "BD": "Breakdown",
                    "EI": "Inspection",
                    "CL": "Cleaning",
                }

                for ev in cleaning_events:
                    op_type_display = EQ_OP_LABELS.get(ev.equipment_operation_type, ev.equipment_operation_type or "—")
                    # FIX: ProductionEvent has no `equipment_used` column (that lives on
                    # SoilManagementEvent). Prefer equipment_type display, then event name,
                    # then description. The previous reference would AttributeError at runtime.
                    equipment_label = (
                        (ev.get_equipment_type_display() if ev.equipment_type else None) or ev.name or ev.description
                    )
                    asset_class = _choice_label(ev, "cleaning_asset_class")
                    cl_data.append(
                        [
                            self._cell(asset_class),
                            self._cell(equipment_label),
                            self._cell(op_type_display),
                            self._cell(_fmt_date(ev.cleaning_date) if ev.cleaning_date else None),
                            self._cell(ev.cleaning_method),
                            self._cell(ev.cleaning_materials_used),
                            self._cell(ev.cleaned_by),
                            self._cell("Yes" if ev.rinse_step_documented else "No"),
                            self._cell("Yes" if ev.shared_with_conventional else "No"),
                            self._cell(ev.cleaning_protocol_reference),
                        ]
                    )

                # Ten columns, 6.95in — inside the 7.00in text block (letter, 0.75in margins).
                #
                # 🔴 2026-08-19: Method at 0.75in broke mid-word — a real changeover record
                # printed "compressed-ai" over "r blow-down". Method carries the sentence that
                # says HOW the line was cleaned, which is the § 205.272 substance, so it takes
                # the width; Rinse and Shared-with-conventional are yes/no and give it up.
                cl_widths = [
                    0.9 * inch,  # What Was Cleaned
                    0.85 * inch,  # Equipment
                    0.6 * inch,  # Op Type
                    0.6 * inch,  # Cleaning Date
                    1.0 * inch,  # Method
                    0.75 * inch,  # Materials Used
                    0.65 * inch,  # Cleaned By
                    0.4 * inch,  # Rinse
                    0.5 * inch,  # Shared w/ Conv.
                    0.7 * inch,  # Protocol Ref
                ]
                t2 = Table(cl_data, colWidths=cl_widths, repeatRows=1)
                t2.setStyle(self._base_table_style())
                elements.append(t2)

                # --- Purge records (§ 205.272) ---
                # Its own narrow table rather than three more columns on the log above: that
                # one already carries ten against a 7.00in frame, and ReportLab does not raise
                # when a table runs past the margin — it just draws off the page.
                #
                # The end-use column is the one that matters. A purge fed to livestock, sold as
                # conventional or discarded are three different compliance stories, and the
                # cleaning record alone tells none of them.
                purge_events = [
                    ev
                    for ev in cleaning_events
                    if (ev.purge_material or ev.purge_quantity or ev.purge_material_end_use)
                ]
                if purge_events:
                    elements.append(self._spacer(0.1))
                    elements.append(self._body("<b>Purge Records (7 CFR 205.272)</b>"))
                    pg_headers = ["Date", "What Was Cleaned", "Purge Material", "Quantity", "End Use"]
                    pg_data = [[self._hdr(h) for h in pg_headers]]
                    for ev in purge_events:
                        pg_data.append(
                            [
                                self._cell(_fmt_date(ev.cleaning_date or ev.date)),
                                self._cell(
                                    _choice_label(ev, "cleaning_asset_class")
                                    if getattr(ev, "cleaning_asset_class", None)
                                    else None
                                ),
                                self._cell(ev.purge_material),
                                self._cell(ev.purge_quantity),
                                self._cell(ev.purge_material_end_use),
                            ]
                        )
                    pg_widths = [0.8 * inch, 1.3 * inch, 1.4 * inch, 0.9 * inch, 2.6 * inch]
                    pg_table = Table(pg_data, colWidths=pg_widths, repeatRows=1)
                    pg_table.setStyle(self._base_table_style())
                    elements.append(pg_table)

                elements.extend(self._build_shared_equipment_coverage_subtable())

                # --- Post-Harvest Sanitation subsection (7 CFR 205.272 + § 205.605) ---
                # Only render when at least one cleaning event has actual SANITIZER detail.
                # rinse_step_documented is deliberately NOT a trigger: a water-only purge
                # (rinse=Yes, no sanitizer) is a compliant record, not a sanitation event —
                # including it here would false-flag it as "missing sanitizer name/ppm/§205.605".
                # Its rinse confirmation now surfaces in the Equipment Cleaning Logs "Rinse" column.
                sanitizer_events = [
                    ev
                    for ev in cleaning_events
                    if ev.sanitizer_name or ev.sanitizer_ppm is not None or ev.sanitizer_nop_reference
                ]
                if sanitizer_events:
                    elements.append(self._spacer(0.2))
                    elements.append(self._body("<b>Post-Harvest Sanitation (7 CFR 205.272 + § 205.605)</b>"))
                    elements.append(self._spacer(0.05))

                    # Run 7 (R7-05): a chlorine MRDL (4.0, or 0.8 when the name said "dioxide") was
                    # applied to every sanitizer, peracetic acid included, and printed PASS. Trazo
                    # does not store the compound and use a limit depends on, so it assesses none.
                    def _residual_cell(ev):
                        residual = getattr(ev, "sanitizer_residual_ppm_at_discharge", None)
                        if residual is None:
                            return None
                        return f"{residual} ppm (no limit assessed in Trazo)"

                    def _sanitation_date(ev):
                        when = ev.cleaning_date or ev.date
                        return _fmt_date(when) if when else None

                    san_headers = [
                        "Date",
                        "Sanitizer",
                        "Applied ppm",
                        "Residual @ Discharge",
                        "Rinse Step",
                        "Reference (as entered)",
                    ]
                    san_data = [[self._hdr(h) for h in san_headers]]
                    for ev in sanitizer_events:
                        san_data.append(
                            [
                                self._cell(_sanitation_date(ev)),
                                self._cell(ev.sanitizer_name),
                                self._cell(str(ev.sanitizer_ppm) if ev.sanitizer_ppm is not None else None),
                                self._cell(_residual_cell(ev)),
                                self._cell("Yes" if ev.rinse_step_documented else "No"),
                                self._cell(ev.sanitizer_nop_reference),
                            ]
                        )
                    san_widths = [
                        0.75 * inch,
                        1.25 * inch,
                        0.6 * inch,
                        1.15 * inch,
                        0.65 * inch,
                        1.5 * inch,
                    ]
                    t_san = Table(san_data, colWidths=san_widths, repeatRows=1)
                    t_san.setStyle(self._base_table_style())
                    elements.append(t_san)

                    # The reference is the operator's. One citing § 205.601 (crop production) on a
                    # post-harvest record is named, never ruled on (same reading as
                    # `plan_materials.post_harvest_listing_review`).
                    crop_cited = [ev for ev in sanitizer_events if "205.601" in (ev.sanitizer_nop_reference or "")]
                    if crop_cited:
                        elements.append(self._spacer(0.05))
                        elements.append(
                            Paragraph(
                                f"[REVIEW] {len(crop_cited)} post-harvest sanitation record(s) cite § 205.601, "
                                "which lists sanitizers for crop production; sanitizers for post-harvest wash "
                                "and rinse water are listed at § 205.605(b). The reference is as entered by the "
                                "operator; confirm the listing that covers each product.",
                                self._warning_style(),
                            )
                        )

                    # Per-event attestation gaps: missing name / ppm / rinse step / ref → inspector flag.
                    gap_notes = []
                    for ev in sanitizer_events:
                        missing = []
                        if not (ev.sanitizer_name or "").strip():
                            missing.append("sanitizer name")
                        if ev.sanitizer_ppm is None:
                            missing.append("concentration (ppm)")
                        if not ev.rinse_step_documented:
                            missing.append("rinse step")
                        if not (ev.sanitizer_nop_reference or "").strip():
                            missing.append("regulatory reference")
                        if missing:
                            label = _sanitation_date(ev) or (ev.name or "event")
                            gap_notes.append(f"{label}: not recorded: {', '.join(missing)}")
                    if gap_notes:
                        elements.append(self._spacer(0.05))
                        elements.append(
                            self._body(
                                "<b>Inspector flag:</b> "
                                + "; ".join(gap_notes)
                                + ". § 205.605(b) sets conditions per material (for example, a residual "
                                "limit for chlorine materials, and FDA limitations for peracetic acid in wash "
                                "or rinse water); it does not set one rinse rule for every sanitizer. Check the "
                                "product label and the use."
                            )
                        )
                    else:
                        elements.append(self._spacer(0.05))
                        elements.append(
                            self._body(
                                "Sanitizer name, concentration, rinse step and a regulatory reference are "
                                "recorded, as entered by the operator, for every post-harvest cleaning event."
                            )
                        )
            else:
                elements.append(
                    self._body(
                        "No equipment cleaning records found. If equipment is shared between "
                        "organic and conventional operations, cleaning logs are required."
                    )
                )

        # A section that is nothing but its own heading is worse than an absent section — an
        # inspector reads the empty space as a gap. Since the EquipmentEvent placeholder was
        # removed (see above), this can now happen on a non-organic packet with no cleaning
        # records, so drop the whole section rather than print a bare title.
        if len(elements) <= 1:
            return []

        return elements

    # ------------------------------------------------------------------
    # Section 8b: Weather Events
    # ------------------------------------------------------------------

    def _build_weather_section(self):
        """
        Weather events — operational context only — § 205.201(a)(3) is OSP-implementation, supplier and fraud monitoring, not meteorology.

        Documents climate impacts (frost, heat waves, storms) so an inspector can
        cross-reference yield variances and emergency irrigation events to the
        weather they responded to. Most detail-level fields (temperature,
        start/end dates, wind speed) live in `WeatherEvent.extra_data` since the
        model itself only carries `type`, `observation`, and `extra_data`.
        """

        elements = [self._section_header("Weather Events & Crop Impact")]

        events = related_events(self.production, "history_weatherevent_events")

        headers = ["Date", "Type", "Magnitude", "Start", "End", "Impact / Notes"]

        if not events:
            elements.append(self._empty_table(headers))
            return elements

        # ISO timestamps in extra_data ("2026-04-12T11:21") are noisy in a
        # date column — keep only the date portion so the table reads cleanly.
        def _iso_date_only(raw):
            if raw in (None, ""):
                return None
            s = str(raw)
            for sep in ("T", " "):
                if sep in s:
                    return s.split(sep, 1)[0]
            return s

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        for ev in events:
            extra = ev.extra_data if isinstance(ev.extra_data, dict) else {}

            # Every magnitude the event recorded, not just the first one found — see
            # _WEATHER_MAGNITUDE_GROUPS for the key-name and unit ground truth.
            magnitudes = _weather_magnitudes(extra)
            magnitude = ", ".join(magnitudes) if magnitudes else None

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(WEATHER_TYPE_LABELS.get(ev.type, _val(ev.type))),
                    self._cell(magnitude),
                    self._cell(_iso_date_only(extra.get("start_date"))),
                    self._cell(_iso_date_only(extra.get("end_date"))),
                    self._cell(self._event_note_or_description(ev)),
                ]
            )

        col_widths = [
            0.7 * inch,  # Date
            1.0 * inch,  # Type
            1.3 * inch,  # Magnitude (can now hold two readings, e.g. wind + rainfall)
            0.8 * inch,  # Start
            0.8 * inch,  # End
            2.4 * inch,  # Impact / Notes
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        elements.extend(self._build_weather_response_subtable(events))
        return elements

    @staticmethod
    def _duration_label(weather_type):
        """Column label for WeatherEvent.extra_data['duration'], whose unit varies by sub-type.

        WeatherTab labels the input "Duration (minutes)" for hailstorms and "Duration (hours)"
        for tropical storms, high winds and humidity events. The stored value carries no unit
        of its own, so the sub-type is the only thing that says which it is — and printing
        "minutes" for a 6-hour wind event on an inspector-facing document would be a
        24-fold misstatement.

        The underlying fragility is real: `duration` should carry an explicit unit rather
        than relying on the form label. Until it does, this mapping must track WeatherTab.
        """
        return "Duration (min)" if weather_type == "HL" else "Duration (hrs)"

    def _build_weather_response_subtable(self, events):
        """Protective action taken in response to a weather event.

        The six-column summary table above has no room for these, so they were collected by
        WeatherTab and then never rendered anywhere. They matter to an inspector because
        § 205.201(a)(3) asks what the operation DOES about monitored conditions, not merely
        that it observed them — "frost, 28°F" is an observation; "frost, 28°F, wind machines
        run 4 h" is the monitoring plan working.

        Rendered only for events that actually recorded a response, so a production with
        plain observations does not gain an empty table.
        """
        # (extra_data key, column label)
        response_fields = (
            ("way_of_protection", "Protection Used"),
            ("protection_measures", "Protection Measures"),
            ("duration", None),  # unit is sub-type dependent — see _duration_label below
            ("water_deficit", "Water Deficit"),
            ("damage_assessment", "Damage Assessment"),
            ("crop_impact", "Crop Impact"),
        )

        rows = []
        for ev in events:
            extra = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            details = [
                f"{self._duration_label(ev.type) if label is None else label}: {extra.get(key)}"
                for key, label in response_fields
                if extra.get(key) not in (None, "")
            ]
            if details:
                rows.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(WEATHER_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(" · ".join(details), 220),
                    ]
                )

        if not rows:
            return []

        elements = [
            Spacer(1, 10),
            Paragraph(
                "<b>Weather Response &amp; Protective Measures (7 CFR 205.201(a)(3))</b>",
                self._sub_header_style(),
            ),
        ]
        table = Table(
            [[self._hdr(h) for h in ("Date", "Type", "Response Recorded")]] + rows,
            colWidths=[0.7 * inch, 1.0 * inch, 5.3 * inch],
            repeatRows=1,
        )
        table.setStyle(self._base_table_style())
        elements.append(table)
        return elements

    # ------------------------------------------------------------------
    # Section 9: Environmental Impact
    # ------------------------------------------------------------------

    def _build_carbon_section(self):
        elements = [self._section_header("Appendix — Environmental Impact (informational; not a USDA NOP requirement)")]

        try:
            from carbon.models import CarbonEntry

            entries = list(CarbonEntry.objects.filter(production=self.production).select_related("source"))
        except Exception as exc:
            logger.warning("Could not load carbon data for audit: %s", exc)
            entries = []

        total_co2e = sum(e.co2e_amount or e.amount or 0.0 for e in entries)

        elements.append(
            self._label_value(
                "Total Carbon Emissions",
                f"{_fmt_float(total_co2e)} kg CO2e",
            )
        )
        elements.append(
            self._label_value("Methodology", "Direct Operational Emissions \u2014 EPA/USDA-sourced factors")
        )
        # NOTE: the Transparency Score is a Trazo product / engagement metric, NOT a
        # compliance measure. It is deliberately NOT printed on any certifier-facing
        # audit export (organic / roc / scs / all) \u2014 a self-assigned score on a
        # regulatory document reads as a self-created sustainability grade and a
        # certifier may misread it as a compliance verdict. It lives on the producer
        # dashboard only.

        elements.append(self._spacer(0.15))

        if entries:
            # 🔴 2026-08-29 — this column was headed "Verification Status" and printed
            # `CarbonEntry.verification_status` RAW. That field is a free CharField whose live
            # values include `usda_verified` (88 rows on the pilot alone) and
            # `epa_usda_verified_aggregate`, so a certifier-facing PDF stated "usda_verified"
            # against emission lines — the precise claim `.claude/rules/compliance.md` forbids by
            # name ("EPA/USDA-sourced" is SAFE; "USDA Verified" is UNSAFE), and an FTC 16 CFR
            # 260.6 exposure. Nothing about a Trazo calculation is verified by USDA.
            #
            # The honest vocabulary already exists: `carbon/services/verified_emission_factors.py`
            # types provenance as published-vs-internal-estimate precisely so no surface has to
            # invent its own wording. This says which FACTOR BASIS was applied, and never that
            # anyone verified the result.
            headers = ["Source", "Type", "Amount (kg CO2e)", "Emission factor basis"]
            header_row = [self._hdr(h) for h in headers]
            data = [header_row]
            for entry in entries:
                source_name = entry.source.name if entry.source else _val(entry.description)
                data.append(
                    [
                        self._cell(source_name),
                        self._cell(entry.type),
                        self._cell(_fmt_float(entry.co2e_amount or entry.amount)),
                        self._cell(_emission_factor_basis(entry.verification_status)),
                    ]
                )
            col_widths = [2.2 * inch, 1.0 * inch, 1.5 * inch, 1.6 * inch]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)
        else:
            elements.append(self._body("No carbon emission records found for this production."))

        elements.extend(self._build_pumping_plant_subtable())
        elements.extend(self._build_application_fuel_subtable())

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Note: Emissions represent direct operational activities (fuel, fertilizer, equipment) "
                "within the farm boundary. Full lifecycle or supply-chain emissions are excluded.",
                self._styles["footer_note"],
            )
        )

        return elements

    def _build_pumping_plant_subtable(self):
        """The measured irrigation pumping plant behind the irrigation energy figure (§E-6).

        Irrigation is the largest energy line in a California orchard, and its emissions are
        driven by total dynamic head and pumping-plant efficiency. When the grower has had a
        pump test done, showing its inputs is what lets anyone reconcile the number against
        their own utility bill instead of taking a coefficient on trust — the same reason the
        head build-up is exposed in the calculation breakdown.

        Lives in the carbon appendix rather than the organic packet: this is a carbon input,
        and CERTIFICATION_SECTIONS deliberately excludes carbon from `organic`.
        Rendered only when a pump test has been recorded.
        """
        try:
            parcel = self.production.parcel
        except AttributeError:
            return []

        efficiency = getattr(parcel, "pump_efficiency_pct", None)
        pressure = getattr(parcel, "system_pressure_psi", None)
        test_date = getattr(parcel, "pump_test_date", None)
        provider = getattr(parcel, "pump_test_provider", None)
        if not any([efficiency, pressure, test_date, provider]):
            return []

        rows = [
            [self._hdr(h) for h in ("Pump Test Date", "Tested By", "Plant Efficiency", "System Pressure")],
            [
                self._cell(_fmt_date(test_date) if test_date else "—"),
                self._cell(provider),
                self._cell(f"{_fmt_float(efficiency)}%" if efficiency else "—"),
                self._cell(f"{_fmt_float(pressure)} psi" if pressure else "—"),
            ],
        ]

        elements = [
            self._spacer(0.15),
            Paragraph(
                "<b>Irrigation Pumping Plant (measured — informational)</b>",
                self._sub_header_style(),
            ),
        ]
        table = Table(rows, colWidths=[1.3 * inch, 2.4 * inch, 1.4 * inch, 1.4 * inch], repeatRows=1)
        table.setStyle(self._base_table_style())
        elements.append(table)
        elements.append(
            Paragraph(
                "Pumping-plant efficiency and system pressure set the energy per acre-foot used in "
                "the irrigation figures above. Where no test is on file, a 70% efficiency and a "
                "method-derived pressure are assumed.",
                self._styles["footer_note"],
            )
        )
        return elements

    def _build_application_fuel_subtable(self):
        """Fuel burned applying inputs — the Scope-1 input behind the chemical figures above.

        Deliberately confined to this appendix. `application_fuel_type` / `_consumed` /
        `_unit` were collected and never rendered anywhere, but they are a CARBON input, not
        an organic-compliance record — and the carbon appendix is excluded from the
        `organic` export by design (CERTIFICATION_SECTIONS), because energy figures on a
        certifier document invite greenwashing-by-association. Putting them here surfaces
        the data without leaking it into the organic packet.
        """
        events = [
            ev
            for ev in related_events(self.production, "history_chemicalevent_events")
            if ev.application_fuel_consumed and float(ev.application_fuel_consumed) > 0
        ]
        if not events:
            return []

        elements = [
            self._spacer(0.15),
            Paragraph(
                "<b>Application Equipment Fuel (Scope 1 — informational)</b>",
                self._sub_header_style(),
            ),
        ]
        rows = [[self._hdr(h) for h in ("Date", "Product", "Fuel Type", "Fuel Used", "Fertigated")]]
        for ev in events:
            rows.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(ev.commercial_name),
                    self._cell(ev.application_fuel_type),
                    self._cell(
                        f"{_fmt_float(ev.application_fuel_consumed)} " f"{_val(ev.application_fuel_unit, '')}".strip()
                    ),
                    # Fertigated applications ride the irrigation event's energy, so their
                    # application fuel is intentionally zero in the carbon model — flagging
                    # it here explains an otherwise puzzling blank to anyone reconciling.
                    self._cell("Yes" if ev.is_fertigation else "No"),
                ]
            )
        table = Table(rows, colWidths=[0.8 * inch, 2.0 * inch, 1.1 * inch, 1.2 * inch, 0.9 * inch], repeatRows=1)
        table.setStyle(self._base_table_style())
        elements.append(table)
        return elements

    # ------------------------------------------------------------------
    # Section 10: Traceability (FSMA 204)
    # ------------------------------------------------------------------

    def _fsma_ftl_coverage(self):
        """FSMA 204 Food Traceability List status: 'covered' | 'not_covered' | 'unknown'.

        Raw/in-shell tree nuts (walnut, almond, pecan…) are NOT on the FTL — only
        nut BUTTERS are. Single source of truth for both the Regulatory Scope
        declaration and the Traceability-section footer so they can't contradict.
        """
        try:
            crop_type_name = (self.production.crop_type.name or "").lower() if self.production.crop_type else ""
        except AttributeError:
            crop_type_name = ""
        ftl_covered_keywords = (
            "leafy green",
            "spinach",
            "lettuce",
            "arugula",
            "kale",
            "tomato",
            "pepper",
            "cucumber",
            "herb",
            "melon",
            "sprout",
        )
        ftl_exempt_keywords = (
            "avocado",
            "citrus",
            "orange",
            "lemon",
            "apple",
            "pear",
            "stone fruit",
            "cherry",
            "peach",
            "walnut",
            "almond",
            "pecan",
            "pistachio",
            "hazelnut",
            "tree nut",
        )
        nut_names = ("walnut", "almond", "pecan", "pistachio", "hazelnut", "cashew", "peanut", "macadamia")
        is_nut_butter = "butter" in crop_type_name and any(n in crop_type_name for n in nut_names)
        if is_nut_butter or any(kw in crop_type_name for kw in ftl_covered_keywords):
            return "covered"
        if any(kw in crop_type_name for kw in ftl_exempt_keywords):
            return "not_covered"
        return "unknown"

    def _build_traceability_section(self):
        p = self.production
        elements = [self._section_header("Traceability Record (FSMA 204)")]

        lat = lon = None
        try:
            lat = p.parcel.establishment.latitude
            lon = p.parcel.establishment.longitude
        except AttributeError:
            pass

        gps_display = f"{lat:.6f}, {lon:.6f}" if lat and lon else None

        # Resolve the actual harvest date from the last harvesting (HA) event so
        # the traceability record matches the Harvest Records table. Fall back to
        # the production finish date only when no harvest event exists (the finish
        # date can be days later than the harvest — e.g. after packing/close-out).
        _harvests = related_events(self.production, "history_productionevent_events", order="-date", type="HA")
        harvest_ev = _harvests[0] if _harvests else None
        harvest_date = harvest_ev.date if (harvest_ev and harvest_ev.date) else p.finish_date

        rows = [
            ("Lot ID", p.lot_id),
            ("Harvest Date", _fmt_date(harvest_date)),
            ("Harvest Location (GPS)", gps_display),
            (
                "Quantity Harvested",
                _fmt_mass(p.production_amount, p.production_unit) if p.production_amount else None,
            ),
            # `_humanize_enum`, NOT `get_quality_grade_display()`. The column carries free text
            # now (the packing record's own words), so there is no `choices` to display from —
            # and while there was, the display map would have printed a row written before the
            # 2026-08-21 change as "Grade A (legacy)". `_humanize_enum` reproduces a real grade
            # verbatim ("WA Extra Fancy") and still turns an old `grade_a` slug into "Grade A".
            ("Quality Grade", _humanize_enum(p.quality_grade)),
            ("Harvest Method", p.get_harvest_method_display() if p.harvest_method else None),
        ]

        # Harvester name from the same harvesting production event
        harvester = None
        try:
            if harvest_ev:
                harvester = harvest_ev.performed_by or (
                    harvest_ev.created_by.get_full_name() if harvest_ev.created_by else None
                )
        except Exception:
            pass

        rows.append(("Operator / Harvester", harvester))

        # Farm-to-first-receiver haul distance. `transportation_distance` is collected on
        # harvest events, validated in ProductionEvent.clean(), shown to consumers — and
        # rendered in no export. It belongs here rather than in the production stats: it is
        # a movement of the lot, which is the shipping CTE an FSMA-204 record describes.
        haul_events = [
            ev
            for ev in self.production.history_productionevent_events.all()
            if ev.transportation_distance and float(ev.transportation_distance) > 0
        ]
        if haul_events:
            # Sort on the formatted date string: `date` is an aware datetime under USE_TZ,
            # so a naive sentinel for the nullable case would raise on comparison. ISO
            # strings sort correctly and the em-dash placeholder sorts undated rows last.
            hauls = ", ".join(
                f"{_fmt_float(ev.transportation_distance)} {_val(ev.transportation_unit, '')}".strip()
                + f" ({_fmt_date(ev.date)})"
                for ev in sorted(haul_events, key=lambda e: _fmt_date(e.date))
            )
            rows.append(("Transport Distance (farm to first receiver)", hauls))

        for label, value in rows:
            elements.append(self._label_value(label, value))

        elements.append(self._spacer(0.1))
        if self._fsma_ftl_coverage() == "not_covered":
            footer_text = (
                "This crop is not on the FDA Food Traceability List (21 CFR 1.1300), so FSMA "
                "Section 204 KDE/CTE tracking is not required. Lot IDs are maintained "
                "voluntarily and link to the production record in Trazo."
            )
        else:
            footer_text = (
                "This section supports FSMA Section 204 traceability requirements for "
                "produce supply chains. Lot IDs link to the production record in Trazo."
            )
        elements.append(Paragraph(footer_text, self._styles["footer_note"]))

        return elements

    # ------------------------------------------------------------------
    # Section 11: Photo Evidence Summary
    # ------------------------------------------------------------------

    # Photos-section limits — keep the PDF reliably under ~30 MB even for a
    # production with dense photographic evidence. Inspectors who need every
    # photo have the dashboard URL; the PDF embeds the most useful subset.
    PHOTOS_MAX_PER_EVENT = 4
    PHOTOS_MAX_TOTAL = 60
    PHOTOS_FETCH_TIMEOUT_SEC = 8
    # Concurrent S3 fetches per section. Each photo was a sequential HTTPS round-trip plus a
    # decode/resize; at ~0.2-0.4 s each, 60 photos cost a production 15-20 s on their own.
    PHOTOS_FETCH_WORKERS = 6
    PHOTOS_TARGET_PIXEL_WIDTH = 1400

    # NOP-priority order: events whose photo evidence usually decides a finding
    # appear first in the gallery so a remote inspector can verify them without
    # paging through routine production shots. Default order is generalist
    # (fits GlobalG.A.P. / ROC / SCS); organic-specific NOP inspectors risk-
    # weight restricted-synthetic applications (copper/sulfur) and raw-manure
    # applications above routine pest monitoring, so the organic export
    # reorders the categories below via ``_photos_category_order_for()``.
    PHOTOS_CATEGORY_ORDER = [
        ("Pest Management", "history_pestmanagementevent_events"),
        ("Soil Management", "history_soilmanagementevent_events"),
        ("Chemical Applications", "history_chemicalevent_events"),
        ("Equipment / Cleaning", "history_equipmentevent_events"),
        ("Contamination & General", "history_generalevent_events"),
        ("Field Operations", "history_productionevent_events"),
        ("Weather", "history_weatherevent_events"),
        ("Business / Certification", "history_businessevent_events"),
    ]

    # NOP-organic photo ordering: chemical applications (restricted synthetics
    # like copper hydroxide) precede soil/compost, which precede pest
    # management. Rationale: NOP inspectors flag synthetic applications and
    # raw-manure intervals first; IPM/pest evidence is secondary.
    PHOTOS_CATEGORY_ORDER_ORGANIC = [
        ("Chemical Applications", "history_chemicalevent_events"),
        ("Soil Management", "history_soilmanagementevent_events"),
        ("Pest Management", "history_pestmanagementevent_events"),
        ("Equipment / Cleaning", "history_equipmentevent_events"),
        ("Contamination & General", "history_generalevent_events"),
        ("Field Operations", "history_productionevent_events"),
        ("Weather", "history_weatherevent_events"),
        ("Business / Certification", "history_businessevent_events"),
    ]

    def _photos_category_order_for(self):
        """Return the category ordering appropriate to this export's cert type."""
        if self.certification_type == "organic":
            return self.PHOTOS_CATEGORY_ORDER_ORGANIC
        return self.PHOTOS_CATEGORY_ORDER

    def _photo_embed_environment(self):
        """
        Classify the environment for photo embedding so the PDF can surface
        an accurate banner. The three states matter to an inspector:

          * ``prod_s3_ok``         - prod with S3 configured; any fetch failure
                                     is a genuine error worth flagging loudly.
          * ``prod_s3_misconfig``  - prod with ``AWS_STORAGE_BUCKET_NAME`` unset
                                     (should never ship; banner fails hardest).
          * ``dev_no_s3``          - local dev without S3; "None.s3" URLs are
                                     expected, not a compliance issue.

        Cached on the instance so we don't re-read settings for every photo.
        """
        if hasattr(self, "_photo_env_cache"):
            return self._photo_env_cache
        try:
            from django.conf import settings

            debug = bool(getattr(settings, "DEBUG", False))
            bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", None)
        except Exception:
            debug, bucket = True, None
        if bucket:
            mode = "prod_s3_ok" if not debug else "dev_with_s3"
        else:
            mode = "dev_no_s3" if debug else "prod_s3_misconfig"
        self._photo_env_cache = {"mode": mode, "bucket": bucket, "debug": debug}
        return self._photo_env_cache

    def _fetch_image_for_pdf(self, image_obj):
        """
        Download an image from S3 (or local storage), normalize, resize, and
        return a BytesIO of JPEG bytes ready to embed via ReportLab. Returns
        None on any failure — callers must render a placeholder in that case.
        Failures are tracked in two buckets:

          * dev-expected (``_photos_dev_skipped``) — S3 not configured locally.
          * prod-failure (``_photos_prod_failed``) — real error the inspector
            must know about; first 10 errors retained in
            ``_photos_prod_errors`` for structured per-photo rendering.

        Failures are logged but never raise; one bad image must not break the
        whole PDF.
        """
        env = self._photo_embed_environment()
        url = self._image_url(image_obj)
        if not url:
            # No URL at all — count as prod-failure in prod, dev-skip in dev.
            if env["mode"].startswith("prod"):
                self._photos_prod_failed += 1
                if len(self._photos_prod_errors) < 10:
                    self._photos_prod_errors.append(("<no-url>", "thumbnail_url and url both unavailable"))
            else:
                self._photos_dev_skipped += 1
            return None
        # Malformed-bucket URL: expected in dev_no_s3, a critical misconfig in prod.
        if "None.s3" in url or "://None" in url:
            if env["mode"] in ("dev_no_s3", "dev_with_s3"):
                logger.info("Audit photo S3 URL has None bucket (dev, expected): %s", url)
                self._photos_dev_skipped += 1
            else:
                logger.error(
                    "Audit photo S3 URL has None bucket in prod — AWS_STORAGE_BUCKET_NAME " "not configured: %s",
                    url,
                )
                self._photos_prod_failed += 1
                if len(self._photos_prod_errors) < 10:
                    self._photos_prod_errors.append((url, "S3 bucket not configured (None.s3 URL)"))
            return None

        cached = self._image_cache.get(image_obj.pk)
        if cached is None:
            cached = self._download_image_bytes(url, self.PHOTOS_FETCH_TIMEOUT_SEC, self.PHOTOS_TARGET_PIXEL_WIDTH)
            self._image_cache[image_obj.pk] = cached
        buf, failure = cached
        if buf is not None:
            return buf
        kind, reason = failure
        if kind == "http":
            # A reachable bucket answering non-200 is a real error whatever the environment —
            # the object is missing or the policy is wrong — so it counts as a prod failure
            # even in dev, as it always has.
            logger.warning("Audit photo fetch %s returned %s", url, reason)
            self._photos_prod_failed += 1
            if len(self._photos_prod_errors) < 10:
                self._photos_prod_errors.append((url, reason))
            return None
        logger.warning("Audit photo embed failed for %s: %s", url, reason)
        if env["mode"].startswith("prod"):
            self._photos_prod_failed += 1
            if len(self._photos_prod_errors) < 10:
                self._photos_prod_errors.append((url, reason))
        else:
            self._photos_dev_skipped += 1
        return None

    @staticmethod
    def _image_url(image_obj):
        """The URL to fetch for one photo: the medium thumbnail when one exists, else the
        original. None when the row carries no usable location at all."""
        try:
            url = image_obj.thumbnail_url("md")
        except Exception:
            url = None
        if not url:
            try:
                url = image_obj.url
            except Exception:
                url = None
        return url or None

    @staticmethod
    def _download_image_bytes(url, timeout, target_px):
        """Fetch one image and normalise it for ReportLab.

        Returns `(BytesIO, None)` on success, else `(None, (kind, reason))` where kind is
        "http" (the server answered, not with 200) or "error" (no answer / undecodable).
        Deliberately touches no instance state and no ORM, so it can run on a worker thread;
        the caller classifies the outcome against the embed environment.
        """
        try:
            import requests
            from PIL import Image as PILImage

            resp = requests.get(url, timeout=timeout)
            if resp.status_code != 200:
                return None, ("http", f"HTTP {resp.status_code}")

            img = PILImage.open(io.BytesIO(resp.content))
            # ReportLab's JPEG embedder needs RGB. PNG-with-alpha and grayscale
            # both flatten to white-background RGB.
            if img.mode in ("RGBA", "LA", "P"):
                background = PILImage.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")

            if max(img.size) > target_px:
                img.thumbnail((target_px, target_px), PILImage.LANCZOS)

            out = io.BytesIO()
            img.save(out, format="JPEG", quality=78, optimize=True)
            out.seek(0)
            return out, None
        except Exception as exc:
            return None, ("error", f"fetch/decode error: {exc!r}")

    def _prefetch_photo_images(self, category_events):
        """Download every photo the gallery below will embed, concurrently, into `_image_cache`.

        Walks the events in the gallery's own order with the gallery's own caps, so it fetches
        exactly the set `_build_event_photo_block` will ask for. Only the network and the resize
        run on the pool; URL resolution and the prod/dev bookkeeping stay on the calling thread.
        """
        remaining = self.PHOTOS_MAX_TOTAL
        planned = []
        for _label, events in category_events:
            for ev in events:
                if remaining <= 0:
                    break
                photos = album_images(getattr(ev, "album", None))[: min(self.PHOTOS_MAX_PER_EVENT, remaining)]
                planned.extend(photos)
                remaining -= len(photos)
        to_fetch = {}
        for photo in planned:
            if photo.pk in self._image_cache:
                continue
            url = self._image_url(photo)
            # Malformed-bucket URLs are classified (and counted) by _fetch_image_for_pdf.
            if url and "None.s3" not in url and "://None" not in url:
                to_fetch[photo.pk] = url
        if not to_fetch:
            return
        with ThreadPoolExecutor(max_workers=min(self.PHOTOS_FETCH_WORKERS, len(to_fetch))) as pool:
            futures = {
                pk: pool.submit(
                    self._download_image_bytes, url, self.PHOTOS_FETCH_TIMEOUT_SEC, self.PHOTOS_TARGET_PIXEL_WIDTH
                )
                for pk, url in to_fetch.items()
            }
            for pk, future in futures.items():
                self._image_cache[pk] = future.result()

    def _photo_caption(self, image_obj, idx, total):
        """
        Build a short caption with the metadata an inspector needs to trust the
        photo: ordinal, capture date (EXIF when present, else upload date), GPS,
        and Vision-API validation status. Falls back gracefully when fields are
        missing.
        """
        extra = image_obj.extra_data if isinstance(image_obj.extra_data, dict) else {}
        parts = [f"Photo {idx} of {total}"]

        # EXIF capture date if Vision API or upload pipeline stored it.
        captured = extra.get("captured_at") or extra.get("exif_datetime")
        if captured:
            captured_str = str(captured)
            if "T" in captured_str:
                captured_str = captured_str.split("T", 1)[0]
            elif " " in captured_str:
                captured_str = captured_str.split(" ", 1)[0]
            parts.append(f"taken {captured_str}")
        elif image_obj.created_at:
            parts.append(f"uploaded {image_obj.created_at.date().isoformat()}")

        # GPS coordinates if EXIF carried them through.
        gps = extra.get("gps") if isinstance(extra.get("gps"), dict) else None
        if gps:
            lat = gps.get("lat") or gps.get("latitude")
            lng = gps.get("lng") or gps.get("longitude") or gps.get("lon")
            if lat is not None and lng is not None:
                try:
                    parts.append(f"GPS {float(lat):.4f}, {float(lng):.4f}")
                except (TypeError, ValueError):
                    pass

        # Vision-API validation status (Trazo runs Google Vision on each upload
        # to confirm the image is agricultural — flagged-as-non-agri is rare
        # but worth surfacing for the auditor.)
        validation = extra.get("content_validation")
        if isinstance(validation, dict):
            if validation.get("is_valid") is False:
                parts.append("[Vision: NON-AGRICULTURAL FLAG]")
            elif validation.get("is_valid") is True:
                parts.append("Vision-validated")

        # File size for inspector confidence (>50 KB suggests not a placeholder
        # / corrupt image). Skip when missing.
        if image_obj.file_size and image_obj.file_size >= 1024:
            kb = image_obj.file_size / 1024
            parts.append(f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB")

        return " · ".join(parts)

    def _build_event_photo_block(self, event, category_label, photos_remaining):
        """
        Return a list of flowables for one event's photo block: a one-line
        header (category, date, description, total count) followed by a 2-column
        grid of up to PHOTOS_MAX_PER_EVENT photos. The block is wrapped in
        KeepTogether so the header doesn't orphan from its photos across page
        breaks.

        `photos_remaining` is the global budget so callers can stop adding
        photos once the document-wide cap is reached.
        """
        try:
            all_photos = album_images(getattr(event, "album", None))
        except Exception:
            all_photos = []
        if not all_photos:
            return [], 0

        photos_for_this_event = all_photos[: min(self.PHOTOS_MAX_PER_EVENT, photos_remaining)]
        if not photos_for_this_event:
            return [], 0

        block = []

        # Header line — keep it dense; auditor reads this row first.
        type_label = ""
        if hasattr(event, "type") and event.type:
            type_label = (
                CHEMICAL_TYPE_LABELS.get(event.type)
                or SOIL_TYPE_LABELS.get(event.type)
                or PEST_TYPE_LABELS.get(event.type)
                or PRODUCTION_TYPE_LABELS.get(event.type)
                or EQUIPMENT_TYPE_LABELS.get(event.type)
                or WEATHER_TYPE_LABELS.get(event.type)
                or str(event.type)
            )
        descriptor = (
            getattr(event, "description", None)
            or getattr(event, "name", None)
            or getattr(event, "commercial_name", None)
            or getattr(event, "amendment_type", None)
            or getattr(event, "pest_species", None)
            or ""
        )
        # Escape ONLY the user-content slots (descriptor + type label) — the
        # <b>/<i> tags are ours and must reach ReportLab's Paragraph parser
        # un-escaped so they render as bold/italic instead of literal text.
        # Earlier version escaped the whole header and the markup leaked
        # through as "&lt;b&gt;..." in the PDF (caught in screenshot review).
        safe_descriptor = self._safe_narrative(_truncate(str(descriptor), 80)) if descriptor else ""
        safe_type_label = self._safe_narrative(type_label) if type_label else ""
        header_text = (
            f"<b>{category_label}</b> · {_fmt_date(event.date)}"
            + (f" · <i>{safe_type_label}</i>" if safe_type_label else "")
            + (f" · {safe_descriptor}" if safe_descriptor else "")
            + f" · {len(all_photos)} photo(s) on file, {len(photos_for_this_event)} embedded below"
        )
        header_style = ParagraphStyle(
            "PhotoBlockHeader",
            parent=self._styles["body"],
            fontSize=8,
            textColor=DARK_GRAY,
            spaceBefore=6,
            spaceAfter=4,
        )
        block.append(Paragraph(header_text, header_style))

        # Build the grid. Two photos per row at 2.7" wide x 2.1" max height
        # (proportional). Each cell is [Image, caption Paragraph]. We use
        # Image with `kind="proportional"` so portrait shots aren't squashed.
        cell_caption_style = ParagraphStyle(
            "PhotoCaption",
            parent=self._styles["body"],
            fontSize=7,
            leading=9,
            textColor=colors.HexColor("#555555"),
            alignment=TA_CENTER,
            spaceBefore=2,
            spaceAfter=4,
        )
        photo_cells = []
        for idx, photo in enumerate(photos_for_this_event, 1):
            buf = self._fetch_image_for_pdf(photo)
            caption_text = self._photo_caption(photo, idx, len(photos_for_this_event))
            if buf is None:
                self._photos_not_embedded += 1
                # P0-2 — Render photo metadata instead of a useless placeholder.
                # Inspector sees: filename, upload date, file size — enough to
                # request the image directly or verify it in the dashboard.
                meta_parts = [f"<i>[Photo {idx}: image not embedded]</i>"]
                fname = None
                try:
                    fname = os.path.basename(photo.image.name) if photo.image and photo.image.name else None
                except Exception:
                    pass
                if fname:
                    meta_parts.append(f"File: {self._safe_narrative(fname)}")
                if photo.created_at:
                    meta_parts.append(f"Uploaded: {photo.created_at.date().isoformat()}")
                if photo.file_size:
                    kb = photo.file_size / 1024
                    meta_parts.append(f"Size: {kb:.0f} KB" if kb < 1024 else f"Size: {kb / 1024:.1f} MB")
                meta_parts.append("Visible in dashboard")
                cell = [
                    Paragraph("<br/>".join(meta_parts), cell_caption_style),
                    Paragraph(self._safe_narrative(caption_text), cell_caption_style),
                ]
            else:
                rl_img = RLImage(buf, width=2.7 * inch, height=2.1 * inch, kind="proportional")
                cell = [rl_img, Paragraph(self._safe_narrative(caption_text), cell_caption_style)]
            photo_cells.append(cell)

        # Pack cells two per row.
        rows = []
        for i in range(0, len(photo_cells), 2):
            row = [photo_cells[i]]
            row.append(photo_cells[i + 1] if i + 1 < len(photo_cells) else "")
            rows.append(row)

        grid_style = TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
        grid = Table(rows, colWidths=[3.3 * inch, 3.3 * inch])
        grid.setStyle(grid_style)
        block.append(grid)

        # Wrap in KeepTogether so a 4-photo block doesn't orphan its header
        # at the bottom of a page. ReportLab will start a new page if needed.
        return [KeepTogether(block)], len(photos_for_this_event)

    def _build_photos_section(self):
        """
        Photo Evidence section — three layers:
          1. Summary table (count per event with photos) for fast scanning.
          2. Embedded photo gallery, NOP-priority order, with captions.
          3. Footer note explaining the dashboard cross-reference and the
             SHA-256 audit trail Trazo retains for tamper-evidence.
        """

        elements = [self._section_header("Photo Evidence")]

        # Track photos that fail to embed. Reset both counters so a previous
        # section's failures don't leak into this one.
        self._photos_not_embedded = 0
        self._photos_dev_skipped = 0
        self._photos_prod_failed = 0
        self._photos_prod_errors = []

        # Environment banner — inspector sees this FIRST, before the summary
        # table, so there's no ambiguity about why embeds may be missing.
        env = self._photo_embed_environment()
        if env["mode"] == "prod_s3_misconfig":
            elements.append(
                Paragraph(
                    "<b>[ERROR] PDF generated without S3 configuration.</b> "
                    "<code>AWS_STORAGE_BUCKET_NAME</code> is not set in this environment, "
                    "so NO photo evidence can be embedded for inspector review. "
                    "This PDF should not be relied upon for a real audit until "
                    "the S3 configuration is corrected and the report is re-exported.",
                    self._warning_style(),
                )
            )
            elements.append(self._spacer(0.08))
        # No blanket dev-mode banner: photos embed fine from public image URLs
        # even without S3 configured, so a top-of-section "metadata in place of
        # images" claim is false whenever images actually embed. Any individual
        # photo that genuinely fails to embed is reported accurately by the
        # trailing "[N photo(s) rendered as metadata-only …]" note below.

        # Pull all events across categories once. Cache for both the summary
        # table and the gallery so we don't double-query.
        category_events = []
        for label, related_name in self._photos_category_order_for():
            category_events.append((label, related_events(self.production, related_name)))

        # ---------- Layer 1: summary table ----------
        summary_headers = ["Event Category", "Event Date", "Description", "Photos"]
        summary_header_row = [self._hdr(h) for h in summary_headers]
        summary_data = [summary_header_row]
        total_photos = 0

        for category_label, events in category_events:
            for ev in events:
                count = _photo_count(ev)
                if count > 0:
                    summary_data.append(
                        [
                            self._cell(category_label),
                            self._cell(_fmt_date(ev.date)),
                            self._cell(ev.description if hasattr(ev, "description") else None),
                            self._cell(str(count)),
                        ]
                    )
                    total_photos += count

        if len(summary_data) == 1:
            elements.append(self._body("No photo evidence has been attached to events in this production."))
            elements.append(self._spacer(0.1))
            elements.append(
                Paragraph(
                    "When photos are uploaded, Trazo records each file's S3 object key, "
                    "upload timestamp, file size, and uploader account on the producer "
                    "dashboard for audit-trail cross-reference.",
                    self._styles["footer_note"],
                )
            )
            return elements

        col_widths = [1.5 * inch, 0.85 * inch, 4.0 * inch, 0.65 * inch]
        summary_table = Table(summary_data, colWidths=col_widths, repeatRows=1)
        summary_table.setStyle(self._base_table_style())
        elements.append(summary_table)
        elements.append(self._spacer(0.08))
        elements.append(self._label_value("Total Photos Attached", str(total_photos)))
        elements += self._photo_reuse_findings(category_events)

        # ---------- Layer 2: embedded gallery ----------
        elements.append(self._spacer(0.18))
        elements.append(
            Paragraph(
                "<b>Photo Gallery</b> — embedded for inspector pre-read",
                self._sub_header_style(),
            )
        )
        elements.append(
            Paragraph(
                (
                    "Photos appear in NOP-organic priority order: chemical "
                    "applications (restricted synthetics), soil/compost + manure, "
                    "pest management, equipment cleaning, contamination, then "
                    "routine production. "
                    if self.certification_type == "organic"
                    else "Photos appear in NOP-priority order: pest, soil/compost, "
                    "chemical, equipment cleaning, contamination, then routine production. "
                )
                + "Each photo carries its capture date and (when EXIF was preserved at "
                "upload) its GPS coordinates and Vision-API validation status. "
                f"Embedded photos are resized to ~{self.PHOTOS_TARGET_PIXEL_WIDTH}px "
                "wide for PDF size; originals remain in the dashboard.",
                self._styles["footer_note"],
            )
        )
        elements.append(self._spacer(0.05))

        self._prefetch_photo_images(category_events)
        photos_remaining = self.PHOTOS_MAX_TOTAL
        embedded_count = 0
        skipped_events = 0
        for category_label, events in category_events:
            for ev in events:
                if photos_remaining <= 0:
                    if _photo_count(ev) > 0:
                        skipped_events += 1
                    continue
                block_elements, embedded = self._build_event_photo_block(ev, category_label, photos_remaining)
                if block_elements:
                    elements.extend(block_elements)
                    photos_remaining -= embedded
                    embedded_count += embedded

        # Prominent failure banner for PROD-only failures (dev-skipped photos
        # are expected and covered by the dev-mode header banner). Listed with
        # per-photo error codes so the inspector can triage quickly.
        if self._photos_prod_failed > 0:
            total_attempts = embedded_count + self._photos_prod_failed
            elements.append(self._spacer(0.08))
            elements.append(
                Paragraph(
                    f"<b>[WARNING: {self._photos_prod_failed} of {total_attempts} "
                    "photo(s) could not be embedded — S3 access error.]</b> "
                    "Inspector should verify originals via the Trazo producer dashboard "
                    "and treat this section as incomplete.",
                    self._warning_style(),
                )
            )
            if self._photos_prod_errors:
                err_lines = []
                for url, reason in self._photos_prod_errors:
                    display_url = url if len(url) < 80 else url[:77] + "…"
                    err_lines.append(f"• {self._safe_narrative(reason)} — {self._safe_narrative(display_url)}")
                if self._photos_prod_failed > len(self._photos_prod_errors):
                    err_lines.append(
                        f"• (additional {self._photos_prod_failed - len(self._photos_prod_errors)}"
                        " error(s) not shown)"
                    )
                elements.append(Paragraph("<br/>".join(err_lines), self._styles["footer_note"]))

        # Dev-skipped photos — quiet note, not a failure.
        if self._photos_dev_skipped > 0 and self._photos_prod_failed == 0:
            elements.append(self._spacer(0.06))
            elements.append(
                Paragraph(
                    f"<i>[{self._photos_dev_skipped} photo(s) rendered as metadata-only "
                    "because this PDF was generated in a development environment without "
                    "S3. Production exports will embed the actual images.]</i>",
                    self._styles["footer_note"],
                )
            )

        # ---------- Layer 3: footer with cap notice + tamper-evidence ----------
        elements.append(self._spacer(0.12))
        if skipped_events > 0 or embedded_count >= self.PHOTOS_MAX_TOTAL:
            elements.append(
                Paragraph(
                    f"<b>Note:</b> Embedded {embedded_count} of {total_photos} photos "
                    f"(PDF cap: {self.PHOTOS_MAX_TOTAL} photos to keep file size under "
                    "~30 MB). The remaining photos are available in the Trazo producer "
                    "dashboard under each event.",
                    self._styles["footer_note"],
                )
            )
        elements.append(
            Paragraph(
                "Audit-trail metadata for each embedded photo: original S3 object key, "
                "upload timestamp, file size, and uploader account are retained in the "
                "producer dashboard and can be cross-referenced against the photos shown "
                "above. Captions reflect EXIF capture date and GPS when those tags were "
                "preserved at upload; photos taken on a device that strips EXIF will show "
                "the upload date instead.",
                self._styles["footer_note"],
            )
        )
        return elements

    # ------------------------------------------------------------------
    # Section 11b: Additional Farmer-Recorded Data (Custom Fields)
    # ------------------------------------------------------------------

    def _build_custom_data_section(self):
        """
        Custom fields added by the farmer on any event.

        Auditors need to see ALL data recorded by the farmer, including
        ad-hoc fields they created (lab reference numbers, supplier certs,
        equipment calibration notes, etc.). Omitting these would be an
        incomplete audit record.
        """
        elements = [self._section_header("Additional Farmer-Recorded Data")]

        from history.custom_fields import extract_custom_fields_for_display

        event_querysets = [
            ("Production", self.production.history_productionevent_events.all()),
            ("Chemical", self.production.history_chemicalevent_events.all()),
            ("Soil Management", self.production.history_soilmanagementevent_events.all()),
            ("Pest Management", self.production.history_pestmanagementevent_events.all()),
            ("Equipment", self.production.history_equipmentevent_events.all()),
            ("General", self.production.history_generalevent_events.all()),
            ("Weather", self.production.history_weatherevent_events.all()),
            ("Business", self.production.history_businessevent_events.all()),
        ]

        headers = ["Event Date", "Event Category", "Event Description", "Field Name", "Field Value", "Type"]
        header_row = [self._hdr(h) for h in headers]
        data = [header_row]

        for category_label, qs in event_querysets:
            for ev in qs:
                extra = getattr(ev, "extra_data", None)
                if not extra or not isinstance(extra, dict):
                    continue

                # Extract all custom fields (visibility=all for audit — auditors see everything)
                custom_fields = extract_custom_fields_for_display(extra, visibility_filter="all", include_empty=False)

                for cf in custom_fields:
                    data.append(
                        [
                            self._cell(_fmt_date(ev.date)),
                            self._cell(category_label),
                            self._cell(ev.description),
                            self._cell(cf.get("label", "")),
                            self._cell(cf.get("value", "")),
                            self._cell(cf.get("field_type", "text")),
                        ]
                    )

        if len(data) == 1:
            elements.append(self._body("No additional custom fields were recorded on events in this production."))
        else:
            col_widths = [0.65 * inch, 0.75 * inch, 1.5 * inch, 1.1 * inch, 1.8 * inch, 0.5 * inch]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)
            elements.append(self._spacer(0.05))
            elements.append(self._label_value("Total Custom Fields", str(len(data) - 1)))

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Custom fields are farmer-created data points added during event documentation. "
                "All fields are self-reported. Field visibility: consumer (shown on QR page), "
                "internal (producer only), b2b (shared with buyers).",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 11b: Attached Documents (DMS index)
    # ------------------------------------------------------------------

    def _build_attached_documents_section(self):
        """Index of the operation's uploaded documents — 7 CFR 205.103(b)(1).

        🔴 2026-08-16 (CCOF grower-checklist audit). Four of CCOF's eight grower checklist
        items name a DOCUMENT as the record: purchase receipts, the handler's organic
        certificate, delivery or receiving documents, and invoices / pack-out summaries. Trazo
        has held those files since WS-3 and this export referenced `GeneratedDocument` ZERO
        times, so a farmer who scanned a receipt filed it somewhere no certifier would ever
        encounter. The upload endpoint now accepts a production link; this is the other half.

        What this section is NOT: the documents themselves. The bytes stay in the DMS behind
        an authenticated download. An INDEX is what a certifier needs on paper — it tells them
        what exists and to ask for it, which is exactly what "maintain original documents such
        as receipts" is asking the operation to be able to show.

        In a single-production packet, rows are limited to this production's own attachments
        plus farm-wide uploads. In the operation dossier (`documents_scope="establishment"`)
        every upload is listed once, labelled with the production it belongs to — the section
        is classified establishment-level there, so it renders once rather than per production.

        Generated artifacts (dossiers, OSP snapshots, PUR exports) are excluded either way — a
        packet listing previous copies of itself is noise, not evidence.
        """
        elements = [self._section_header("Attached Documents (7 CFR 205.103(b)(1))")]

        try:
            from django.db.models import Q

            from documents.models import GeneratedDocument

            establishment = self.production.parcel.establishment if self.production.parcel else None
            if establishment is None:
                elements.append(self._body("No farm is linked to this production, so no documents can be listed."))
                return elements

            qs = GeneratedDocument.objects.filter(establishment=establishment, source="upload")
            if getattr(self, "documents_scope", "production") != "establishment":
                qs = qs.filter(Q(history=self.production) | Q(history__isnull=True))
            # 🔴 2026-08-20 — `[:60]` was applied silently. A farm with 80 uploads had 20 of
            # them disappear from the index with nothing to say so, and an index whose whole
            # job is to tell a certifier WHAT EXISTS is worse than useless when it quietly
            # omits rows: the reviewer reads a complete list. Count first, then disclose.
            # (Project rule since the audit-PDF work: truncation is opt-in and never silent.)
            document_limit = 60
            total_documents = qs.count()
            docs = list(qs.select_related("parcel", "history").order_by("-created_at")[:document_limit])
        except Exception:
            logger.exception("Attached-documents section failed to load")
            elements.append(
                Paragraph(
                    "<b>[REVIEW]</b> The document index could not be read for this export. "
                    "Provide uploaded records (receipts, handler certificates, delivery "
                    "documents) directly at inspection.",
                    self._warning_style(),
                )
            )
            return elements

        if not docs:
            elements.append(
                self._body(
                    "No documents have been uploaded for this operation. The Common OSP grower "
                    "recordkeeping checklist expects original documents to be retained — "
                    "purchase receipts for seed and inputs, the organic certificate of any "
                    "handler this crop was sent to, delivery or receiving documents, and "
                    "invoices or pack-out summaries for the finished product. Upload them on "
                    "the farm's Documents page so they travel with this packet."
                )
            )
            return elements

        headers = ["Uploaded", "Title", "Folder", "Linked To", "Size"]
        data = [[self._hdr(h) for h in headers]]
        for doc in docs:
            # Named, not "this production": the same builder renders inside the operation
            # dossier, where "this production" would be a lie on every row but one.
            if doc.history_id and doc.history:
                linked = doc.history.name or f"Production {doc.history_id}"
            elif doc.parcel_id:
                linked = f"Parcel: {doc.parcel.name}" if doc.parcel else "Parcel"
            else:
                linked = "Farm-wide"
            size_mb = (doc.size_bytes or 0) / (1024 * 1024)
            data.append(
                [
                    self._cell(_fmt_date(doc.created_at)),
                    # Titles are how the certifier asks for the file by name — never truncated
                    # to a stub, same rule as invoice numbers and lot codes.
                    self._cell(doc.title),
                    self._cell(doc.get_folder_display()),
                    self._cell(linked),
                    self._cell(f"{size_mb:.1f} MB" if size_mb >= 0.1 else "<0.1 MB"),
                ]
            )

        widths = [0.85 * inch, 2.7 * inch, 1.35 * inch, 1.35 * inch, 0.75 * inch]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        elements.append(self._spacer(0.1))
        if total_documents > len(docs):
            elements.append(
                Paragraph(
                    f"<b>[REVIEW]</b> This index shows the {len(docs)} most recently uploaded "
                    f"documents of <b>{total_documents}</b> on file; "
                    f"{total_documents - len(docs)} older document(s) are not listed above. "
                    "Request the full index from the operation.",
                    self._warning_style(),
                )
            )
            elements.append(self._spacer(0.06))
        elements.append(
            Paragraph(
                "This is an index, not the documents. The files themselves are retained in the "
                "operation's records and are produced on request at inspection "
                "(7 CFR 205.103(c)). Documents generated by Trazo — dossiers, OSP snapshots, "
                "regulatory exports — are deliberately excluded from this list.",
                self._styles["footer_note"],
            )
        )
        return elements

    # ------------------------------------------------------------------
    # Section 12: Active Certification Summary
    # ------------------------------------------------------------------

    def _build_certifications_section(self):
        """
        Render two tables: Active Certifications (is_active=True) and
        Historical / Expired (is_active=False). Inspector-review finding:
        an expired cert in an "Active" table is flagged as misleading; split
        prevents any ambiguity.
        """
        from certifications.models import Certification

        elements = []

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            elements.append(self._section_header("Active Certification Summary"))
            elements.append(self._body("Farm data not available."))
            return elements

        all_certs = list(
            Certification.objects.filter(establishment=establishment).order_by("certification_type", "-created_at")
        )

        if not all_certs:
            elements.append(self._section_header("Active Certification Summary"))
            elements.append(self._body("No certification records found for this farm."))
            return elements

        today = date.today()
        warning_threshold_days = 90

        active_certs = [c for c in all_certs if c.is_active]
        historical_certs = [c for c in all_certs if not c.is_active]

        # Column header uses neutral wording. Per NOP 2603 and 7 CFR
        # § 205.404(d), USDA Organic certificates do NOT have expiration
        # dates — the stored date is the annual-update / anniversary due
        # date. Private-label certifications (ROC, GlobalG.A.P., SCS) DO
        # have true expiry semantics. "Next Review Date" reads correctly
        # for BOTH cases without putting the misleading word "Expiry"
        # anywhere in a USDA Organic row.
        headers = [
            "Certification Type",
            "Certifier",
            "Certificate #",
            "Effective Date",
            "Next Review Date",
            "Verification",
        ]
        col_widths = [
            1.2 * inch,  # Certification Type
            1.2 * inch,  # Certifier
            1.0 * inch,  # Certificate #
            0.85 * inch,  # Effective Date
            1.1 * inch,  # Next Review Date
            1.35 * inch,  # Verification
        ]

        def _verification_label(cert):
            # The OID claim is gated on the SOURCE that substantiates it, not on
            # verification_status alone — the same 16 CFR 260.6 rule already applied
            # to Certification.consumer_display_status, which this had never picked
            # up. A status set by a manual edit, an import, or a fixture was printing
            # "Verified (USDA OID)" next to a certifier that is not an accredited
            # agent and appears in no USDA database.
            from certifications.models import Certification as _Cert

            if cert.verification_status == "verified":
                if getattr(cert, "verification_source", "") == _Cert.DATABASE_VERIFICATION_SOURCE:
                    return "Verified (USDA OID)"
                return "Self-Reported"
            if cert.verification_status == "self_reported":
                return "Self-Reported"
            if cert.verification_status in ("expired", "revoked", "suspended"):
                return cert.get_verification_status_display()
            return _val(cert.get_verification_status_display())

        # USDA Organic certificates do NOT expire — per 7 CFR § 205.404(d) a
        # certification "continues in effect until surrendered by the organic
        # operation or suspended or revoked by the certifying agent..." NOP
        # 2603 likewise instructs that certificates cannot include expiration
        # dates. For USDA Organic rows we render the stored date as
        # "Anniversary: YYYY-MM-DD" and explicitly state no expiry applies;
        # private-label certs continue to render as "Expires: YYYY-MM-DD"
        # because that IS their legal semantic.
        def _is_usda_organic(cert):
            ctype = (getattr(cert, "certification_type", "") or "").lower()
            # Exact key match against the NOP set. This used to read
            # ("usda_organic", "ccof", "ccof_organic", "ams_organic") — the last two are
            # slugs that appear in NO vocabulary in this codebase, and the CCOF entry was
            # working around a certifier sitting in the TYPE column. A CCOF-issued
            # certificate IS a NOP certificate and now stores `usda_organic`, with "CCOF"
            # in certifier_name, so the § 205.404(d) no-expiry rule reaches it by the
            # front door.
            return ctype in _NOP_CERTIFICATION_TYPES

        def _date_cell_display(cert):
            if _is_usda_organic(cert):
                # NOP 2603: certificates cannot include expiration dates.
                # The stored date is the next annual-update due date. We
                # render it with the "Anniversary:" prefix and never use
                # the word "expiry" / "expires" for USDA Organic rows.
                if cert.expiry_date:
                    return f"Anniversary: {_fmt_date(cert.expiry_date)}"
                return "N/A (does not expire per \u00a7 205.404(d))"
            # Private-label cert — actual expiry semantics.
            if not cert.expiry_date:
                return "—"
            base = _fmt_date(cert.expiry_date)
            days_remaining = (cert.expiry_date - today).days
            if days_remaining < 0:
                return f"Expires: {base} (EXPIRED)"
            if days_remaining <= warning_threshold_days:
                return f"Expires: {base} (in {days_remaining}d)"
            return f"Expires: {base}"

        def _build_table(certs):
            data = [[self._hdr(h) for h in headers]]
            for cert in certs:
                data.append(
                    [
                        self._cell(cert.get_certification_type_display()),
                        self._cell(cert.certifier_name),
                        self._cell(cert.certification_number),
                        self._cell(_fmt_date(cert.effective_date)),
                        self._cell(_date_cell_display(cert)),
                        self._cell(_verification_label(cert)),
                    ]
                )
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            return t

        # --- Active certifications ----------------------------------------
        elements.append(self._section_header("Active Certification Summary"))
        if active_certs:
            elements.append(_build_table(active_certs))
            # NOP 2603 element 5/7 — the USDA-registered operation name and the
            # products covered by each certificate. Rendered as a scope sub-line
            # (not a table column) to avoid crowding the summary grid.
            scope_lines = []
            for cert in active_certs:
                items = cert.certified_items or []
                if isinstance(items, dict):
                    items = list(items.values())
                item_names = [str(i) for i in items if i]
                op_name = (cert.usda_operation_name or "").strip()
                if not op_name and not item_names:
                    continue
                parts = []
                if op_name:
                    parts.append(f"Operation: {op_name}")
                if item_names:
                    parts.append("Certified products: " + ", ".join(item_names))
                scope_lines.append(
                    f"<b>{self._safe_narrative(cert.certifier_name or 'Certificate')}:</b> "
                    + " · ".join(self._safe_narrative(p) for p in parts)
                )
            if scope_lines:
                elements.append(self._spacer(0.05))
                elements.append(self._body("<b>Certificate Scope (NOP 2603)</b>"))
                for line in scope_lines:
                    elements.append(self._body(line))
        else:
            elements.append(
                Paragraph(
                    "<b>NO ACTIVE CERTIFICATIONS.</b> For a USDA Organic audit "
                    "export, at least one active verified organic certification "
                    "is expected.",
                    self._warning_style(),
                )
            )
        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "Verification status reflects cross-reference against the USDA "
                "Organic Integrity Database for USDA Organic certifications. All "
                "other certifications are self-reported unless independently "
                "audited. <b>USDA Organic certificates do not expire</b> per "
                "7 CFR \u00a7 205.404(d) \u2014 the date shown for those rows is "
                "the next annual update / anniversary, not a regulatory expiry. "
                "Private-label certifications (ROC, GlobalG.A.P., SCS, etc.) "
                "do expire; expiry warnings shown for those expiring within "
                "90 days.",
                self._styles["footer_note"],
            )
        )

        # --- Historical / Expired certifications --------------------------
        # Claim-defensibility window: an expired cert is "relevant" to this
        # production if and only if it was ACTIVE AT SOME POINT during the
        # production period (effective_date <= production_end AND expiry_date
        # >= production_start). That's the regulatory question an inspector
        # asks when reviewing claims made on this lot. A cert that expired
        # months before production started was never backing the claim; a
        # cert with no effective_date on file is treated as "unknown — err
        # toward inclusion" so the inspector sees it. Everything else is
        # summarised to a single line with a dossier referral.
        if historical_certs:
            production_start = self.production.start_date.date() if self.production.start_date else today
            production_end = self.production.finish_date.date() if self.production.finish_date else today

            def _was_active_during_production(cert):
                """True when the cert's validity window overlaps the production
                period. Null effective_date → err toward showing (unknown
                start is not grounds to hide a cert the inspector may care
                about). Null expiry_date → the cert is still active today,
                wouldn't be in historical_certs in the first place, but be
                defensive."""
                expiry_ok = cert.expiry_date is None or cert.expiry_date >= production_start
                effective_ok = cert.effective_date is None or cert.effective_date <= production_end
                return expiry_ok and effective_ok

            relevant_historical = [c for c in historical_certs if _was_active_during_production(c)]
            hidden_count = len(historical_certs) - len(relevant_historical)

            if relevant_historical:
                elements.append(self._spacer(0.15))
                elements.append(
                    self._section_header("Historical / Expired Certifications (active during this production)")
                )
                elements.append(_build_table(relevant_historical))
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        "These certifications were active at some point during the "
                        f"production period ({production_start.isoformat()} to "
                        f"{production_end.isoformat()}) and may have supported claims "
                        "made on this lot. They are no longer active and do NOT "
                        "support current organic claims.",
                        self._styles["footer_note"],
                    )
                )
                if hidden_count:
                    elements.append(self._spacer(0.04))
                    elements.append(
                        Paragraph(
                            f"{hidden_count} additional historical certification"
                            f"{'s' if hidden_count != 1 else ''} (never active during "
                            "this production period) available in the farm "
                            "dossier; omitted here to keep the audit focus on the "
                            "production under review.",
                            self._styles["footer_note"],
                        )
                    )
            elif hidden_count:
                # None of the historical certs overlapped production. Provide
                # continuity context so "expired" does not imply a gap in
                # certification. An inspector reviewing a long-certified
                # operation expects to see the chain: earliest effective date
                # on record → current active certificate, with no gap.
                earliest_historical_effective = None
                for hc in historical_certs:
                    if hc.effective_date is None:
                        continue
                    if earliest_historical_effective is None or hc.effective_date < earliest_historical_effective:
                        earliest_historical_effective = hc.effective_date
                current_active_effective = None
                for ac in active_certs:
                    if ac.effective_date is None:
                        continue
                    if current_active_effective is None or ac.effective_date < current_active_effective:
                        current_active_effective = ac.effective_date
                elements.append(self._spacer(0.05))
                if earliest_historical_effective and current_active_effective:
                    elements.append(
                        Paragraph(
                            f"Note: this farm has {hidden_count} historical "
                            f"certification{'s' if hidden_count != 1 else ''} on file "
                            f"pre-dating the current active certificate. Certification "
                            f"continuity: first certified "
                            f"{earliest_historical_effective.isoformat()}; current "
                            f"certificate effective "
                            f"{current_active_effective.isoformat()}. None overlap "
                            "this production period, so they do not back the "
                            "organic claim on this lot directly; full history "
                            "available in the farm dossier on request.",
                            self._styles["footer_note"],
                        )
                    )
                else:
                    elements.append(
                        Paragraph(
                            f"Note: this farm has {hidden_count} historical / "
                            f"expired certification{'s' if hidden_count != 1 else ''} "
                            "on file from earlier periods; none overlap this "
                            "production period. This is a historical record for "
                            "the operation and does not imply a gap in the "
                            "current certification. Full history available in the "
                            "farm dossier on request.",
                            self._styles["footer_note"],
                        )
                    )

        return elements

    # ------------------------------------------------------------------
    # Section 12b: Inspection & Compliance Event History
    # ------------------------------------------------------------------

    def _build_business_events_section(self):
        """
        Chronological log of certification, compliance, and inspection events
        (BusinessEvent rows) tied to this production.

        The Active Certification Summary above lists current certifications held
        by the establishment. This section documents the *events* — annual
        inspections, compliance checks, third-party audits — that the farmer
        logged during this production cycle. NOP auditors rely on this trail
        (inspector name, certificate reference, verification status) to trace
        the path from farm practices back to the certifying body.
        """
        elements = [self._section_header("Inspection & Compliance Event History")]

        events = related_events(self.production, "history_businessevent_events")

        if not events:
            elements.append(
                self._body("No certification, inspection, or compliance events were logged for this production.")
            )
            return elements

        # Label maps mirror history.models.BusinessEvent choices. Kept inline so
        # PDF labels stay accurate if model choices change behind us; update
        # both together.
        business_type_labels = {
            "certification": "Certification",
            "verification": "Third-Party Verification",
            "sustainability_audit": "Sustainability Audit",
            "transparency": "Transparency Initiative",
            "carbon_credits": "Carbon Credits",
            "compliance": "Regulatory Compliance",
        }
        sustainability_labels = {
            "cover_cropping": "Cover Cropping",
            "no_till": "No-Till Farming",
            "integrated_pest": "Integrated Pest Management",
            "water_conservation": "Water Conservation",
            "renewable_energy": "Renewable Energy",
            "composting": "On-Farm Composting",
            "biodiversity": "Biodiversity Conservation",
            "soil_health": "Soil Health Improvement",
        }

        headers = [
            "Date",
            "Activity",
            "Certification",
            "Certifier / Auditor",
            "Certificate #",
            # Two people, two columns (OSP alignment audit T29, 2026-10-01). `performed_by` is who
            # did the work as entered; it was printed under "Recorded By" with a comment calling it
            # the person who logged the event, which merged the two. "Recorded by" is the account
            # that saved the record. Neither is a third-party inspector.
            "Performed By",
            "Recorded By",
            "Status",
        ]
        header_row = [self._hdr(h) for h in headers]
        data = [header_row]

        # Events that carry supplemental detail (practice / credits / observation)
        # drive a follow-up sub-table so the primary row stays compact.
        supplemental_rows = []

        for ev in events:
            activity_label = business_type_labels.get(
                ev.business_type or "",
                _val(ev.business_type),
            )

            cert_display = None
            if ev.certification_type:
                try:
                    cert_display = ev.get_certification_type_display()
                except Exception:
                    cert_display = ev.certification_type

            status_display = None
            if ev.verification_status:
                try:
                    status_display = ev.get_verification_status_display()
                except Exception:
                    status_display = ev.verification_status

            # 🔴 2026-08-19: this column printed a bare "Verified" for a row the farmer typed
            # themselves — directly above the note saying these events "are self-reported by
            # the farmer ... and are not independently verified by Trazo". The table asserted
            # the opposite of its own footnote, and this PDF is the artifact a grower hands to
            # a certifier and (via the buyer documentation request) to a buyer.
            #
            # The status is still shown, because what the OPERATOR recorded is itself a fact an
            # inspector wants. It is just no longer allowed to read as Trazo's verdict:
            # "Verified" becomes "Verified (self-reported)". Establishment-level verification —
            # the USDA Organic Integrity Database cross-reference — lives in the Active
            # Certification Summary, which is the one place entitled to say a claim was checked.
            if status_display and status_display.strip().lower() == "verified":
                status_display = "Verified (self-reported)"

            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(activity_label),
                    self._cell(cert_display),
                    self._cell(ev.verified_certifier_name),
                    self._cell(ev.certificate_number),
                    self._cell(ev.performed_by),
                    self._cell(
                        ((ev.created_by.get_full_name() or "").strip() or ev.created_by.email)
                        if getattr(ev, "created_by", None)
                        else None
                    ),
                    self._cell(status_display),
                ]
            )

            if ev.sustainability_practice or ev.observation:
                supplemental_rows.append(ev)

        col_widths = [
            0.7 * inch,  # Date
            0.95 * inch,  # Activity
            0.95 * inch,  # Certification        — prose, wraps
            1.0 * inch,  # Certifier / Auditor — prose, wraps
            # 🔴 2026-08-19: 0.80in against "CCOF-2025-11947", which needs 0.91in. The packet
            # printed the certificate number as "CCOF-2025-11" over "947" — a different
            # certificate, with nothing marking the break. Same class as the invoice and lot
            # columns; this one is the number a certifier looks up.
            0.95 * inch,  # Certificate #
            0.95 * inch,  # Performed by
            0.75 * inch,  # Recorded by (the saving account); 7.00in total
            0.75 * inch,  # Status              — "(self-reported)" wraps under "Verified"
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        if supplemental_rows:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Supporting Detail</b>"))
            elements.append(self._spacer(0.05))

            # Carbon credits are NOT in this table. A carbon credit is a market instrument
            # with no standing in 7 CFR 205 — it appears in no clause, no Common OSP section
            # and none of the four USDA workbooks — and Trazo sells no carbon-credit product.
            # Printing "Carbon credits earned: 12 tCO2e" into an organic compliance dossier
            # invites a certifier to ask what claim it represents, and there is no good answer.
            # The field still exists on the model and the form; it just does not belong here.
            detail_headers = ["Date", "Sustainability Practice", "Observations"]
            detail_header_row = [self._hdr(h) for h in detail_headers]
            detail_data = [detail_header_row]

            for ev in supplemental_rows:
                practice_display = None
                if ev.sustainability_practice:
                    practice_display = sustainability_labels.get(
                        ev.sustainability_practice,
                        _humanize_enum(ev.sustainability_practice),
                    )

                detail_data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(practice_display),
                        self._cell(self._event_note_or_description(ev)),
                    ]
                )

            # Three columns: 0.75 + 1.5 + 4.4 = 6.65in, inside the 7.00in frame.
            detail_widths = [0.75 * inch, 1.5 * inch, 4.4 * inch]
            dt = Table(detail_data, colWidths=detail_widths, repeatRows=1)
            dt.setStyle(self._base_table_style())
            elements.append(dt)

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Inspection and certification events are self-reported by the farmer. "
                "Certificate numbers and inspector names are recorded at the time of the event "
                "and are not independently verified by Trazo. Cross-reference with the Active "
                "Certification Summary above for farm-level verification status.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section 13: Yield-to-Sales Reconciliation (renamed off "Mass-Balance Audit Summary"
    # on 2026-09-24; see the note at the section header for why)
    # ------------------------------------------------------------------

    # Crop-specific default box / carton weights (pounds) and reconciliation
    # tolerances, used when History.box_weight_lb is not explicitly set.
    # Sources:
    #   * Avocado 25 lb — USDA-AMS Marketing Order 915 (standard Hass carton).
    #   * Avocado 10 lb lug — USDA-AMS retail-packout standard.
    #   * Citrus 38 lb — USDA-AMS navel carton (California Navel Marketing).
    #   * Blueberry 12 lb flat — USDA-AMS shipping point inspection standards.
    # Tolerance default is 10% because specialty-crop post-harvest shrink
    # (moisture, cull-out, grade-down) typically runs 8–12% between field
    # weight and pack-out weight — a tighter threshold produces false
    # non-conformances that do not reflect packing-house reality.
    CROP_DEFAULT_BOX_WEIGHTS = {
        # crop_type_lower: (lb_per_box, tolerance_fraction)
        "avocado": (25.0, 0.10),
        "avocados": (25.0, 0.10),
        "citrus": (38.0, 0.10),
        "orange": (38.0, 0.10),
        "oranges": (38.0, 0.10),
        "lemon": (38.0, 0.10),
        "lemons": (38.0, 0.10),
        "lime": (38.0, 0.10),
        "grapefruit": (38.0, 0.10),
        "mandarin": (25.0, 0.10),
        "blueberry": (12.0, 0.10),
        "blueberries": (12.0, 0.10),
        "strawberry": (11.0, 0.10),
        "strawberries": (11.0, 0.10),
        "apple": (42.0, 0.10),
        "apples": (42.0, 0.10),
    }
    DEFAULT_BOX_WEIGHT_TOLERANCE = 0.10

    # Harvest yields and sale quantities are typed in two different vocabularies. MEASURED on
    # real records: `yield_unit` holds kg / lbs / tons / t / lb / bins, while a SalesRecord's
    # `quantity_unit` is restricted to kg / lb / boxes / crates / tons / bushels / units. So a
    # grower whose picks say "lbs" and whose invoice says "lb" wrote the same unit twice and
    # got NO balance line, because the reconciliation only prints when the two strings match.
    #
    # Only unambiguous synonyms are folded. "t" is NOT mapped to "tons": a metric tonne and a
    # US short ton differ by ~10%, and guessing which one a grower meant would produce a
    # confident wrong balance — worse than the [REVIEW] line that prints when units disagree.
    UNIT_SYNONYMS = {
        "lbs": "lb",
        "pound": "lb",
        "pounds": "lb",
        "kgs": "kg",
        "kilo": "kg",
        "kilos": "kg",
        "kilogram": "kg",
        "kilograms": "kg",
        "ton": "tons",
        "box": "boxes",
        "crate": "crates",
        "bushel": "bushels",
        "unit": "units",
    }

    @classmethod
    def _canonical_unit(cls, unit):
        """Fold a unit onto the sale vocabulary so the two halves can be compared."""
        cleaned = (unit or "").strip().lower()
        return cls.UNIT_SYNONYMS.get(cleaned, cleaned)

    def _resolve_harvest_total(self):
        """Return (amount, unit, basis) for the mass balance, preferring the harvest RECORDS.

        🔴 2026-08-15. `production_amount` is one number typed on the season header; the
        harvest passes each carry a structured `yield_quantity`. Reconciling sales against the
        header meant the packet's mass balance never touched the records it was auditing — and
        a separate consistency check in this file regexes pound values out of free-text
        descriptions while the structured field sits on the same row. Three yield numbers, no
        source of truth.

        Summing only when the picks AGREE on a unit is deliberate: adding pounds to bins would
        produce a confident fabricated total, which is worse for an inspector than falling back
        to the header number the operator typed and saying so. `basis` is printed, so whichever
        number wins, the packet states where it came from.

        Both the PDF and the CSV call this. They previously each read the header separately,
        which is how the two exports of one production came to disagree about the buyer.
        """
        events = [
            ev
            for ev in related_events(self.production, "history_productionevent_events", type="HA")
            if ev.yield_quantity
        ]
        units = {(_val(ev.yield_unit, "") or "").strip().lower() for ev in events}
        if events and len(units) == 1:
            return (
                sum(ev.yield_quantity for ev in events),
                _val(events[0].yield_unit, ""),
                f"sum of {len(events)} harvest record(s)",
            )
        return (
            self.production.production_amount,
            _val(self.production.production_unit, ""),
            (
                "production total (harvest records use mixed units)"
                if events
                else "production total (no harvest records with a yield on file)"
            ),
        )

    def _harvest_header_divergence(self):
        """Do the harvest RECORDS still add up to the season header? Returns None or the gap.

        🔴 2026-08-20 — `_resolve_harvest_total` deliberately prefers the sum of the harvest
        passes over `production_amount`, and prints which basis it used. What it never did was
        NOTICE when the two disagree, so the losing number simply vanished from the packet.

        The two can drift apart by design, and post-submission editing is exactly how:
        `production_amount` is frozen by the closed-record guard once a season is finished,
        while the harvest events underneath it stay correctable through the amendment trail.
        So a farmer who legitimately corrects a pick from 558,000 to 560,000 lb leaves the lot
        header reading 971,100 against records that now total 973,100 — and the packet
        reported the new sum with no hint that the header it was filed under says otherwise.

        A certifier reconciles this by hand; the WA reviewer named the closing mass balance as
        the most trustworthy thing in the packet. A silent 2,000 lb gap in the one section
        they trust is worth more than a loud one. State it, and point at the corrections table
        that usually explains it.
        """
        # An OPEN season has no header to reconcile against. `production_amount` is written
        # when the operator FINISHES the production; until then it sits at its 0.0 default,
        # so this guard read "the harvest records total 348,000 lb but this season's header
        # records 0 lb" and told the operator to reconcile a gap that is simply the season
        # still being in progress — on the same page that prints "Production finalized: No".
        # Three open seasons on one operation meant three § 205.103(b)(2) REVIEW flags in the
        # packet a certifier reads. Found 2026-08-21 on the Calapooia Bend renewal.
        if self.production.finish_date is None:
            return None

        events = [
            ev
            for ev in related_events(self.production, "history_productionevent_events", type="HA")
            if ev.yield_quantity
        ]
        if not events:
            return None
        units = {(_val(ev.yield_unit, "") or "").strip().lower() for ev in events}
        header_amount = self.production.production_amount
        if len(units) != 1 or header_amount is None:
            return None
        # `_canonical_unit`, not a string compare: the season header is written "lb" and the
        # harvest events "lbs" on this very operation, so a literal comparison bails out on
        # the most common shape there is and the check never fires. (Caught while testing it
        # — the first version of this guard silently disabled itself on real data.)
        header_unit = self._canonical_unit(_val(self.production.production_unit, ""))
        event_unit = self._canonical_unit(_val(events[0].yield_unit, ""))
        if header_unit and event_unit and header_unit != event_unit:
            # Genuinely different units is a separate problem; `_resolve_harvest_total`
            # already falls back and says so. Comparing across them would fabricate a gap.
            return None
        try:
            recorded = float(sum(ev.yield_quantity for ev in events))
            header = float(header_amount)
        except (TypeError, ValueError):
            return None
        gap = recorded - header
        # A hair of float noise is not a finding.
        if abs(gap) < 0.01:
            return None
        return {"recorded": recorded, "header": header, "gap": gap, "unit": _val(events[0].yield_unit, "")}

    def _box_weight_for_production(self):
        """
        Resolve (lb_per_box, tolerance) for the current production.

        Priority:
          1. ``self.production.box_weight_lb`` — explicit farmer / certifier value.
          2. ``CROP_DEFAULT_BOX_WEIGHTS[product.crop_type]`` — industry default.
          3. ``(None, DEFAULT_BOX_WEIGHT_TOLERANCE)`` — unknown; caller handles.
        """
        explicit = getattr(self.production, "box_weight_lb", None)
        if explicit is not None:
            try:
                return (float(explicit), self.DEFAULT_BOX_WEIGHT_TOLERANCE)
            except (TypeError, ValueError):
                pass
        crop_type = ""
        try:
            product = getattr(self.production, "product", None)
            if product is not None:
                crop_type = (getattr(product, "crop_type", "") or getattr(product, "name", "") or "").strip().lower()
        except Exception:
            crop_type = ""
        if crop_type and crop_type in self.CROP_DEFAULT_BOX_WEIGHTS:
            return self.CROP_DEFAULT_BOX_WEIGHTS[crop_type]
        return (None, self.DEFAULT_BOX_WEIGHT_TOLERANCE)

    def _build_mass_balance_section(self):
        elements = [self._section_header("Yield-to-Sales Reconciliation (§ 205.103(b)(2) / § 205.2)")]
        # 🔴 2026-09-24 — RENAMED from "Mass-Balance Audit Summary", and the line further down
        # that read "Net inventory reconciliation" went with it.
        #
        # This section reconciles ONE production's harvest records against that production's own
        # sales records, whatever date those sales carry. It models no inventory: there is no
        # opening balance, no closing balance and no carryover, and Trazo holds no data from
        # which to compute one. The words "mass balance" and "net inventory" promise exactly
        # that model — and this section prints inside the operation dossier, whose cover is
        # stamped with a PERIOD WINDOW, so a reader had every reason to read a period inventory
        # balance into it.
        #
        # The scope is stated in the document rather than left to the title, because a reader
        # who takes a lot-level check for a period one draws a false conclusion in the
        # operation's favour.
        elements.append(
            self._body(
                "<b>Scope.</b> This reconciles the harvest records of this production against "
                "the sales records of this production, whatever date those sales carry. Fruit "
                "harvested in one calendar year and invoiced in the next reconciles here in "
                "full. This is <b>not</b> a period mass balance: no opening or closing "
                "inventory is modelled, and Trazo holds no inventory positions."
            )
        )
        elements.append(self._spacer(0.06))

        p = self.production

        # --- Input side: purchases across BOTH input models ---
        #
        # 🔴 2026-08-16. This read ChemicalEvent alone, so an operation whose main purchased
        # input is compost had an empty table and an unclearable
        # "[REVIEW] Mass balance cannot be reconciled" — for records that were complete.
        # Soil amendments are purchases too, and CCOF's checklist names them in the same
        # breath as fertiliser.
        chemical_events = related_events(p, "history_chemicalevent_events")
        soil_events = related_events(p, "history_soilmanagementevent_events")

        purchase_rows, purchase_totals = _purchase_rows(chemical_events, soil_events)
        missing_purchase_count = sum(1 for ev in chemical_events if ev.quantity_purchased is None)
        purchased_rows = [
            [
                self._cell(_fmt_date(row.first.purchase_date) if row.first.purchase_date else "not recorded"),
                self._cell(row.first.product + _purchase_row_note(row)),
                self._cell(row.first.type_label),
                self._cell(row.first.supplier or None),
                self._cell(row.first.invoice or None),
                self._cell(row.first.lot or None),
                self._cell(_fmt_float(row.first.quantity)),
                self._cell(row.first.unit),
            ]
            for row in purchase_rows
        ]

        # One chronological table (by purchase date), not two blocks; `_purchase_rows` orders it.

        # --- Output side: harvest yield + quantity sold ---
        # Precedence (SalesRecord rows win, legacy History fields are the fallback) lives in
        # resolve_sales_disclosure(). It used to be inline here, which is exactly how the
        # compliance snapshot on page 1 ended up disagreeing with this table on page 12.
        harvest_amount, harvest_unit, harvest_basis = self._resolve_harvest_total()
        _sales_disclosure = resolve_sales_disclosure(p)
        # ⛔ `.live()`. Every total, mass-balance figure and [REVIEW] flag below is computed
        # from `sales`, and a sale the operation retracted must not move any of them. The
        # voided rows are collected separately and printed under their own heading — § 205.103
        # (b)(4) is why they were kept instead of deleted, so hiding them here would re-create
        # the deletion the void replaced.
        sales = list(p.sales_records.live()) if _sales_disclosure.source == "sales_records" else []
        voided_sales = list(p.sales_records.voided())
        quantity_sold = _sales_disclosure.quantity
        sold_unit = _val(_sales_disclosure.quantity_unit, harvest_unit)
        sold_to_display = _sales_disclosure.buyer
        sale_date_display = _sales_disclosure.sale_date
        organic_on_invoice_display = _sales_disclosure.organic_on_invoice

        # --- Render input table ---
        elements.append(self._body("<b>Inputs Purchased (chemical inputs + soil amendments)</b>"))
        elements.append(self._spacer(0.05))

        if purchased_rows:
            # From the constant the column-fit guard measures, so the headers and the widths
            # cannot drift apart — a header list that grows a column while the width list
            # does not is how a table silently squeezes every other column.
            input_headers = TABLE_HEADERS["MASS_BALANCE_PURCHASE_WIDTHS"]
            input_header_row = [self._hdr(h) for h in input_headers]
            input_data = [input_header_row] + purchased_rows
            # MEASURED, same rule as the Input Application Log below:
            # `stringWidth(longest_atomic_token) + 6pt padding`.
            #
            # 🔴 The Invoice # and Lot # columns were starved by a hair, and an identifier
            # column that is one point too narrow does not wrap gracefully — ReportLab splits
            # the long unbroken token mid-value, so "YAS-2025-4417" rendered as "YAS-2025-441"
            # with a stray "7" beneath it. A certifier cross-referencing that against the
            # supplier's records reads the WRONG invoice number, in the one table whose entire
            # purpose is cross-referencing identifiers. Truncation was made opt-in on
            # 2026-08-01 for exactly this reason; silent mid-token wrapping is the same defect
            # wearing a different hat.
            #
            # At 7pt: "YAS-2025-4417" = 0.69in, "NH2025-04127" = 0.66in. Frame is 7.00in
            # (letter less 0.75in margins), so the 6.20in this table used left 0.80in unspent
            # while two columns overflowed.
            col_widths = MASS_BALANCE_PURCHASE_WIDTHS
            t = Table(input_data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

            # Subtotals per unit
            elements.append(self._spacer(0.08))
            for unit, total in sorted(purchase_totals.items()):
                elements.append(self._label_value(f"Total Purchased ({unit})", _purchase_total_text(total, unit)))
        else:
            # Mass balance is the exercise an inspector actually runs, and this
            # document itself calls input purchase traceability "the #1
            # non-compliance finding in organic audits". Reporting the absence as a
            # flat statement of fact buried it (2026-08-03 dossier review) — it is a
            # REVIEW item and has to read like one.
            elements.append(
                Paragraph(
                    "<b>[REVIEW] Mass balance cannot be reconciled.</b> No purchase quantity is "
                    "recorded on any chemical input or soil amendment, so inputs purchased cannot "
                    "be reconciled against inputs applied. 7 CFR 205.103(b)(2) requires records "
                    "that fully disclose all activities and transactions in sufficient detail to "
                    "be readily audited, and the input-to-output trace is how a certifier "
                    "verifies it. Record supplier, purchase date, invoice number and quantity "
                    "purchased on each input — including compost and other amendments.",
                    self._warning_style(),
                )
            )

        if missing_purchase_count > 0:
            elements.append(
                Paragraph(
                    f"Note: {missing_purchase_count} chemical event(s) have no purchase quantity "
                    "recorded and are excluded from totals.",
                    self._styles["footer_note"],
                )
            )

        # --- Render output reconciliation ---
        elements.append(self._spacer(0.12))
        elements.append(self._body("<b>Output Reconciliation</b>"))
        elements.append(self._spacer(0.05))

        # The harvest records and the season header are two homes for one fact, and a
        # post-submission correction moves only one of them. Say so rather than silently
        # printing whichever the basis rule picked.
        divergence = self._harvest_header_divergence()

        output_rows = [
            (
                "Harvest Yield",
                _fmt_mass(harvest_amount, harvest_unit) if harvest_amount else None,
            ),
            ("Harvest basis", harvest_basis),
            (
                "Quantity Sold",
                _fmt_mass(quantity_sold, sold_unit) if quantity_sold else None,
            ),
            ("Sold To", sold_to_display),
            ("Sale Date", _fmt_date(sale_date_display) if sale_date_display else None),
            (
                # 🔴 2026-08-19 — this printed a flat "No" for a season with NO SALES AT ALL.
                # "No" is a statement that the operator shipped organic product on documents
                # that did not identify it as organic — a § 205.307(a) / SOE non-conformance
                # the packet was asserting about a crop still on the tree. The absence of an
                # attestation is not a denial; when nothing has been sold there is nothing to
                # answer yet, and the row says so.
                "Organic Identified on Invoice",
                (
                    ("Yes" if organic_on_invoice_display else "No")
                    if (sales or sold_to_display or quantity_sold)
                    else "Not applicable yet — no sales recorded for this production"
                ),
            ),
            # § 205.103(b)(3): records must identify the product by its § 205.301 labeling
            # category, not merely as "organic". Never inferred — blank prints the ask.
            (
                "Labeling Category (§ 205.301)",
                _label_category_display(_sales_disclosure),
            ),
        ]
        if sales:
            output_rows.insert(2, ("Sales Records on File (§ 205.307(a))", str(len(sales))))

        # Direct same-unit comparison only when it is actually meaningful —
        # not for boxes-vs-pounds where the units are explicitly incomparable
        # without a conversion. Boxes→lb reconciliation follows below.
        #
        # 🔴 2026-09-24 — ZERO IS NOT MISSING.
        #
        # This row was emitted only when `quantity_sold` was truthy, so a lot harvested and not
        # yet invoiced — the normal state of a crop picked in October and settled in January —
        # printed NO balance line at all. Silence in a reconciliation section reads as "nothing
        # to reconcile", when the fact is "all of it is still uninvoiced". The dossier also
        # selects productions with `finish_date IS NULL`, so an open production recurs in every
        # period report, each time saying nothing.
        #
        # An uninvoiced remainder is a normal, honest state. It is stated with the date it was
        # measured, because it changes the moment the operator records the sale.
        _as_of = _fmt_generated_date()
        if harvest_amount and self._canonical_unit(harvest_unit) == self._canonical_unit(sold_unit) and quantity_sold:
            balance = float(harvest_amount) - float(quantity_sold)
            output_rows.append(
                (
                    "Balance (Yield \u2212 Sold, same unit)",
                    _fmt_mass(balance, harvest_unit),
                )
            )
            if balance > 0:
                output_rows.append(
                    (
                        "Harvest minus sales recorded",
                        # Run 7 (R7-07a): the difference was called "uninvoiced", which asserts it is
                        # unsold product; the records do not say what it is.
                        f"{_fmt_mass(balance, harvest_unit)} as at {_as_of}, not reconciled: shrink, culls, "
                        "unsold product and unrecorded sales are not distinguished",
                    )
                )
        elif harvest_amount and not quantity_sold:
            # 🔴 `not quantity_sold` IS NOT "no sales". `resolve_sales_disclosure` deliberately
            # returns `quantity=None` when live SalesRecord rows disagree on unit and therefore
            # cannot be summed honestly (see its docstring), and the legacy
            # `History.quantity_sold` column is nullable even with a buyer on file. The first
            # cut of this row read the absent quantity as an absent SALE, so a production with
            # itemised sales printed "harvested with no sales recorded for this production"
            # three rows under "Sold To: Sample Valley Packing Co." — a contradiction inside one
            # section, in the section whose whole job is reconciling the two.
            #
            # Same presence test as the Organic-on-Invoice row above, so the two agree.
            _has_sales = bool(sales or sold_to_display or quantity_sold)
            output_rows.append(
                (
                    "Harvest minus sales recorded",
                    (
                        f"Not calculable as at {_as_of} \u2014 sales are recorded for this "
                        "production but their quantities cannot be summed (the sales records "
                        "disagree on unit, or the quantity is not stated). Reconcile from the "
                        "itemised sales above."
                        if _has_sales
                        else f"{_fmt_mass(harvest_amount, harvest_unit)} harvested with no sales "
                        f"recorded for this production as at {_as_of}"
                    ),
                )
            )

        for label, value in output_rows:
            elements.append(self._label_value(label, value))

        # --- Mass-balance integrity guardrails (§ 205.103(b)(2)) ---
        # A mass-balance section must CATCH an impossible balance, not print it
        # silently. Two physical impossibilities an inspector would immediately
        # flag: selling more than was harvested, and a sale dated before harvest.
        mb_flags = []
        if divergence:
            # Not phrased as a violation: the header and the records disagreeing is usually a
            # DOCUMENTED correction, which is the system working. It still has to be visible,
            # because the reconciliation a certifier runs by hand will not close without it.
            mb_flags.append(
                f"The harvest records total {_fmt_mass(divergence['recorded'], divergence['unit'])} "
                f"but this season's header records {_fmt_mass(divergence['header'], divergence['unit'])} "
                f"— a difference of {_fmt_mass(abs(divergence['gap']), divergence['unit'])}. "
                "The header is frozen once a season is finished while the harvest records stay "
                "correctable, so a documented correction explains most gaps: check Documented "
                "Corrections in the Record Change History below. Reconcile the two before "
                "certifier submission."
            )
        if harvest_amount and quantity_sold and self._canonical_unit(harvest_unit) == self._canonical_unit(sold_unit):
            # 2% tolerance absorbs rounding / unit-precision noise.
            if float(quantity_sold) > float(harvest_amount) * 1.02:
                mb_flags.append(
                    f"Quantity sold ({_fmt_mass(quantity_sold, sold_unit)}) EXCEEDS harvest yield "
                    f"({_fmt_mass(harvest_amount, harvest_unit)}) — a mass-balance impossibility. "
                    f"Reconcile the harvest and sales records before certifier submission."
                )
        # Sale dated before harvest — resolve the harvest date from the earliest
        # harvest (HA) event, falling back to the production finish date.
        harvest_dt = None
        try:
            _ha_rows = related_events(self.production, "history_productionevent_events", type="HA", date__isnull=False)
            _ha = _ha_rows[0] if _ha_rows else None
            if _ha and _ha.date:
                harvest_dt = _ha.date.date()
            elif getattr(self.production, "finish_date", None):
                _fd = self.production.finish_date
                harvest_dt = _fd.date() if hasattr(_fd, "date") else _fd
        except Exception:  # noqa: BLE001 — best-effort date resolution
            harvest_dt = None
        if harvest_dt and sales:
            early = [s for s in sales if s.sale_date and s.sale_date < harvest_dt]
            if early:
                mb_flags.append(
                    f"{len(early)} sale(s) are dated BEFORE the harvest date ({_fmt_date(harvest_dt)}) — "
                    f"product cannot be sold before it is harvested. Correct the sale dates."
                )
        for _msg in mb_flags:
            elements.append(self._spacer(0.05))
            elements.append(Paragraph(f"<b>[REVIEW] 7 CFR 205.103(b)(2): {_msg}</b>", self._warning_style()))

        # Itemized SOE sales records (§ 205.307(a)) — buyer, date, quantity, invoice.
        if sales:
            elements.append(self._spacer(0.08))
            elements.append(self._body("<b>Itemized Sales Records (7 CFR 205.307(a))</b>"))
            # "Lot(s)" closes the trace: the harvest table above lists a lot per pick, this
            # column says which of those picks each buyer received. Without it the packet shows
            # harvests and sales side by side and cannot answer the § 205.103(b)(2) question an
            # inspector actually asks of a block picked more than once — which pick went where.
            sales_headers = [
                "Sale Date",
                "Buyer",
                "Lot(s)",
                "Quantity",
                "Unit",
                # CCOF's grower checklist asks for "how much money you received"; the packet
                # could show volume and buyer but never consideration (added 2026-08-16).
                "Amount",
                "Invoice #",
                "Organic on Invoice",
            ]
            sales_data = [[self._hdr(h) for h in sales_headers]]
            linked_harvest_ids = set()
            for s in sorted(sales, key=lambda r: (r.sale_date is None, r.sale_date or date.min)):
                _sale_harvests = list(s.harvest_events.all())
                linked_harvest_ids.update(ev.pk for ev in _sale_harvests)
                lot_codes = [ev.harvest_lot_code for ev in _sale_harvests if ev.harvest_lot_code]
                sales_data.append(
                    [
                        self._cell(_fmt_date(s.sale_date) if s.sale_date else None),
                        self._cell(s.buyer_name),
                        # Not truncated, for the same reason as the invoice number below: a
                        # lot code cut to a stub is a lot code nobody can match to a bin tag.
                        self._cell(", ".join(lot_codes) if lot_codes else None),
                        # Thousands separator, and no forced decimals on a whole number.
                        # `_fmt_float` printed the season's headline quantity as "52500.00"
                        # in this table while every other appearance of the same number in the
                        # document reads "52,500 lb". A certifier reconciling the two should
                        # not have to check whether they are looking at the same figure.
                        self._cell(_fmt_qty(s.quantity)),
                        self._cell(s.quantity_unit or sold_unit),
                        # `is not None`, not truthiness: a recorded 0.00 (donation, rejected
                        # load taken at no charge) is a fact, and printing an em-dash for it
                        # would report the record as missing when it is not.
                        self._cell(f"${float(s.sale_amount):,.2f}" if s.sale_amount is not None else None),
                        # Invoice numbers are audit-trail identifiers — never
                        # truncate them to an unreadable stub (e.g. "LOEWEN-20…").
                        self._cell(s.invoice_number or None),
                        self._cell("Yes" if s.organic_on_invoice else "No"),
                    ]
                )
            # Eight columns, 7.00in.
            #
            # 🔴 CORRECTED 2026-08-17, same defect as ha_widths above: "inside the 7.5in text
            # block" was false. Letter with 0.75in margins gives a 7.00in frame, so this was
            # 0.45in over and the organic-on-invoice column printed into the right margin.
            # The Amount column is still paid for out of Invoice #, which wraps cleanly.
            sales_widths = [
                0.75 * inch,  # Date
                1.2 * inch,  # Buyer
                1.15 * inch,  # Lot(s)
                0.7 * inch,  # Quantity
                0.45 * inch,  # Unit
                0.85 * inch,  # Amount
                1.2 * inch,  # Invoice #
                0.7 * inch,  # Organic on invoice
            ]
            st = Table(sales_data, colWidths=sales_widths, repeatRows=1)
            st.setStyle(self._base_table_style())
            elements.append(st)

            # Run 7 (R7-07b): a harvest lot that no sale names was invisible; the sale cell simply
            # omitted it. Named here, with no allocation inferred.
            harvests = list(related_events(self.production, "history_productionevent_events", type__in=("HA",)))
            if linked_harvest_ids:
                unlinked = [ev for ev in harvests if ev.pk not in linked_harvest_ids]
                if unlinked:
                    named = ", ".join(
                        ev.harvest_lot_code or f"harvest of {_fmt_date(ev.date)}"
                        for ev in sorted(unlinked, key=lambda e: e.date)
                    )
                    elements.append(self._spacer(0.05))
                    elements.append(
                        Paragraph(
                            f"[REVIEW] {len(unlinked)} harvest record(s) of this production are on no sales "
                            f"record: {_esc(named)}. Where that product went is not shown by these records.",
                            self._warning_style(),
                        )
                    )
            elif harvests:
                elements.append(
                    Paragraph(
                        "The sales records name no harvest lot, so which harvest each sale came from is not "
                        "shown by these records.",
                        self._styles["footer_note"],
                    )
                )

            # Sales total — CCOF's "sales summaries", and the figure the CDFA $5,000
            # registration threshold turns on. Printed only when every row carries an amount:
            # a total over a partially-filled column is a smaller number than the truth, and a
            # certifier reading it against the $5,000 line would be reading a wrong answer.
            _amounts = [s.sale_amount for s in sales]
            _priced = [a for a in _amounts if a is not None]
            if _priced:
                elements.append(self._spacer(0.05))
                if len(_priced) == len(_amounts):
                    elements.append(
                        self._label_value(
                            "Total Sales Recorded (this production)",
                            f"${sum(float(a) for a in _priced):,.2f}",
                        )
                    )
                else:
                    elements.append(
                        Paragraph(
                            f"{len(_amounts) - len(_priced)} of {len(_amounts)} sales have no amount "
                            "recorded, so no total is shown — a partial total would understate this "
                            "production's sales.",
                            self._styles["footer_note"],
                        )
                    )

        # --- Voided sales (kept under § 205.103(b)(4), excluded from every total above) ---
        if voided_sales:
            elements.append(self._spacer(0.08))
            elements.append(self._body("<b>Voided Sales</b>"))
            elements.append(
                Paragraph(
                    "These rows were recorded and then voided by the operation. They are kept "
                    "because 7 CFR 205.103(b)(4) requires records to be maintained for five "
                    "years, and they are excluded from every total above. The reason is the "
                    "operation's own.",
                    self._styles["footer_note"],
                )
            )
            void_headers = ["Sale Date", "Buyer", "Quantity", "Invoice #", "Voided", "Reason"]
            void_data = [[self._hdr(h) for h in void_headers]]
            for s_row in sorted(voided_sales, key=lambda r: (r.sale_date is None, r.sale_date or date.min)):
                void_data.append(
                    [
                        self._cell(_fmt_date(s_row.sale_date) if s_row.sale_date else None),
                        self._cell(s_row.buyer_name),
                        self._cell(f"{_fmt_float(s_row.quantity)} {s_row.quantity_unit}".strip()),
                        self._cell(s_row.invoice_number or None),
                        self._cell(_fmt_date(s_row.voided_at.date()) if s_row.voided_at else None),
                        self._cell(s_row.void_reason or None),
                    ]
                )
            vt = Table(void_data, repeatRows=1)
            vt.setStyle(self._base_table_style())
            elements.append(vt)

        # --- Per-shipment transport (§ 205.272(a) / § 205.103(b)(2)) ---
        # Wholesale lots move in many loads; each SalesRecord row can carry its own
        # BOL / carrier / clean-transport documentation. Render only rows that have
        # any shipment data, and flag shipped rows with no clean-transport method —
        # that is the § 205.272 question an inspector asks per load, not per lot.
        from history.models import SalesRecord

        _clean_labels = dict(SalesRecord.CLEAN_TRANSPORT_CHOICES)
        # The USDA form #22 answers below (cleaning method, prior load, inspection findings,
        # notes) count as transport detail in their own right. Gating them on the BOL/carrier
        # block meant a grower who answered the affidavit but left the shipping identifiers
        # blank got NOTHING on paper — including the notes the "Other" labels promise — and the
        # two [REVIEW] flags at the end of this section could never fire for those rows either.
        shipment_rows = [
            s
            for s in sales
            if any(
                [
                    s.bill_of_lading,
                    s.carrier_name,
                    s.vehicle_id,
                    s.destination,
                    s.clean_transport_method,
                    s.transport_cleaning_method,
                    s.prior_products_transported,
                    s.transport_inspected_free_of,
                    s.transport_notes,
                ]
            )
        ]
        if shipment_rows:
            elements.append(self._spacer(0.08))
            elements.append(self._body("<b>Per-Shipment Transport (7 CFR 205.272 / 205.103(b)(2))</b>"))
            ship_headers = ["Sale Date", "BOL #", "Carrier", "Vehicle", "Destination", "Clean Transport"]
            ship_data = [[self._hdr(h) for h in ship_headers]]
            for s in sorted(shipment_rows, key=lambda r: (r.sale_date is None, r.sale_date or date.min)):
                ship_data.append(
                    [
                        self._cell(_fmt_date(s.sale_date) if s.sale_date else None),
                        # BOL numbers are audit-trail identifiers — same no-truncation
                        # rule as invoice numbers above.
                        self._cell(s.bill_of_lading or None),
                        self._cell(s.carrier_name or None),
                        self._cell(s.vehicle_id or None),
                        self._cell(s.destination or None),
                        self._cell(_clean_labels.get(s.clean_transport_method) or None),
                    ]
                )
            ship_widths = [0.85 * inch, 1.1 * inch, 1.15 * inch, 0.8 * inch, 1.2 * inch, 1.5 * inch]
            sht = Table(ship_data, colWidths=ship_widths, repeatRows=1)
            sht.setStyle(self._base_table_style())
            elements.append(sht)

            # USDA's Clean Transport Affidavit content — what the unit carried before, how it
            # was cleaned, what the pre-load inspection found. The table above is 6.6in of the
            # portrait budget, so these ride as per-shipment detail lines (same treatment as
            # manure, buffer and field-history materials).
            _clean_method_labels = dict(SalesRecord.TRANSPORT_CLEANING_CHOICES)
            transport_detail_lines = []
            for s in sorted(shipment_rows, key=lambda r: (r.sale_date is None, r.sale_date or date.min)):
                bits = []
                if s.prior_products_transported:
                    bits.append("previously carried: " + _esc(s.prior_products_transported))
                if s.transport_cleaning_method:
                    bits.append(
                        "cleaning: "
                        + _esc(_clean_method_labels.get(s.transport_cleaning_method, s.transport_cleaning_method))
                    )
                inspection = s.transport_inspection_display()
                if inspection:
                    bits.append("inspected: " + _esc(inspection))
                # Both "Other" labels above end in "see notes" / "described in the notes".
                # Printing them without this line pointed a certifier at a description that
                # had nowhere to live (SalesRecord.transport_notes did not exist until then).
                if s.transport_notes:
                    bits.append("notes: " + _esc(s.transport_notes))
                if not bits:
                    continue
                label = _esc(_fmt_date(s.sale_date) if s.sale_date else None)
                transport_detail_lines.append(f"<b>{label}:</b> " + "; ".join(bits))
            if transport_detail_lines:
                elements.append(self._spacer(0.06))
                elements.append(self._body("Transport unit history, cleaning and pre-load inspection:"))
                for line in transport_detail_lines:
                    elements.append(Paragraph("&bull; " + line, self._styles["footer_note"]))

            # A non-dedicated unit with no record of what it carried before is the gap
            # § 205.272 actually cares about — "swept" means little without knowing swept of
            # what. Flagged separately from the missing-method check below.
            _no_prior = [
                s
                for s in shipment_rows
                if s.clean_transport_method in ("affidavit", "inspected") and not s.prior_products_transported
            ]
            if _no_prior:
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] 7 CFR 205.272:</b> {len(_no_prior)} shipment(s) used a non-dedicated "
                        "transport unit without recording what it carried immediately before the organic "
                        "load. USDA's Clean Transport Affidavit asks for it, and contamination risk cannot "
                        "be judged without it.",
                        self._warning_style(),
                    )
                )

            _undocumented = [s for s in shipment_rows if not s.clean_transport_method]
            if _undocumented:
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] 7 CFR 205.272:</b> {len(_undocumented)} shipment(s) carry transport "
                        "details but no clean-transport documentation (affidavit, pre-load inspection, "
                        "or dedicated organic vehicle). Record how each load's organic integrity was protected.",
                        self._warning_style(),
                    )
                )

        # --- Off-farm transport / clean-transport record (Common OSP G6.1 / § 205.272 / 205.307) ---
        # transport_method + destination are farmer-entered but were previously never
        # rendered, so the truck identity + receiving destination never reached the
        # certifier. Surface them, plus the clean-transport affidavit status, and flag a
        # transfer that has no affidavit on file.
        if any([p.destination, p.transport_method, p.transport_vehicle_id]):
            elements.append(self._spacer(0.1))
            elements.append(self._body("<b>Off-Farm Transport (Common OSP G6.1 / 7 CFR 205.272 / 205.307)</b>"))
            _shipments_documented = bool(shipment_rows) and all(s.clean_transport_method for s in shipment_rows)
            _legacy_rows = [
                ("Destination", p.destination),
                ("Transport Method", p.transport_method),
                ("Vehicle / Container ID", p.transport_vehicle_id),
            ]
            # The legacy lot-level "affidavit on file" flag is only meaningful while it is the
            # ONLY transport record. Once every load carries its own clean-transport method,
            # printing "Clean-Transport Affidavit on File: No" beside "documented on all 14
            # shipments" states two opposite things about the same lot.
            if not _shipments_documented:
                _legacy_rows.append(
                    ("Clean-Transport Affidavit on File", "Yes" if p.transport_affidavit_on_file else "No")
                )
            for label, value in _legacy_rows:
                elements.append(self._label_value(label, value))
            # This block and the per-shipment table above describe the SAME fact from two
            # editors: `transport_affidavit_on_file` is the legacy single-shipment flag, and
            # SalesRecord.clean_transport_method is the per-load record that replaced it. When
            # every load is documented, firing the legacy warning made the packet contradict
            # itself on the same page — a table of 14 documented shipments followed by "no
            # clean-transport affidavit is recorded". Ask the newer editor first.
            _undocumented_loads = [s for s in shipment_rows if not s.clean_transport_method]
            if shipment_rows and not _undocumented_loads:
                elements.append(
                    self._label_value(
                        "Per-Shipment Clean Transport",
                        f"Documented on all {len(shipment_rows)} shipment(s) — see the table above",
                    )
                )
            elif not p.transport_affidavit_on_file:
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] 7 CFR 205.272 / Common OSP G6.1:</b> organic product was moved off-farm "
                        "but no clean-transport affidavit is recorded. Attach the affidavit confirming "
                        "the shared vehicle/container carried no prohibited substances.",
                        self._warning_style(),
                    )
                )

        # --- Harvest reconciliation (§ 205.103(b)(2) / § 205.2 one-step audit) ---
        # Convert boxes → pounds using box_weight_lb (or the crop-default
        # fallback) and compare to the harvest yield. ±10% is the default
        # tolerance because packing-house shrink is typically 8–12% on
        # specialty crops. A larger delta warrants inspector review but is
        # not itself a regulatory violation.
        elements.append(self._spacer(0.12))
        elements.append(self._body("<b>Harvest Reconciliation (boxes to pounds)</b>"))
        elements.append(self._spacer(0.04))

        box_weight, tolerance = self._box_weight_for_production()
        box_weight_source = (
            "explicit production.box_weight_lb"
            if getattr(self.production, "box_weight_lb", None) is not None
            else "crop-default lookup"
        )

        harvest_lb = None
        if harvest_amount and self._canonical_unit(harvest_unit) == "lb":
            try:
                harvest_lb = float(harvest_amount)
            except (TypeError, ValueError):
                harvest_lb = None

        sold_is_boxes = _is_box_unit(sold_unit)

        if not harvest_amount or not quantity_sold:
            elements.append(
                Paragraph(
                    "<b>[REVIEW] Output reconciliation incomplete.</b> Harvest yield and quantity "
                    "sold are both required to close the boxes-to-pounds trace from field to "
                    "sale. Without them the § 205.2 audit trail stops at the farm gate.",
                    self._warning_style(),
                )
            )
        elif not sold_is_boxes:
            elements.append(
                self._body(
                    f"Quantity sold is expressed in \u201c{sold_unit}\u201d, not boxes/"
                    "cartons/lugs. Boxes-to-pounds reconciliation is skipped — confirm "
                    "directly that harvest yield and quantity sold are in the same unit."
                )
            )
        elif box_weight is None:
            elements.append(
                self._body(
                    f"Box weight is not configured for this production (product "
                    f"crop-type \u201c{getattr(self.production.product, 'crop_type', '') or getattr(self.production.product, 'name', '') or '-'}\u201d). "
                    "Set the <b>box_weight_lb</b> field on the production record to enable "
                    "the boxes-to-pounds reconciliation, or consult the USDA-AMS "
                    "Marketing Order for the crop-specific standard."
                )
            )
        elif harvest_lb is None:
            elements.append(
                self._body(
                    f"Harvest yield is expressed in \u201c{harvest_unit}\u201d, not "
                    "pounds. Boxes-to-pounds reconciliation requires harvest yield in "
                    "pounds; convert before re-exporting."
                )
            )
        else:
            boxes = float(quantity_sold)
            estimated_lb = boxes * box_weight
            delta_lb = harvest_lb - estimated_lb
            if harvest_lb > 0:
                delta_pct = (delta_lb / harvest_lb) * 100.0
            else:
                delta_pct = 0.0
            within_tolerance = abs(delta_pct) <= (tolerance * 100.0)
            status_label = "PASS" if within_tolerance else "REVIEW"
            elements.append(
                self._label_value(
                    "Boxes \u00d7 lb/box",
                    f"{boxes:.0f} \u00d7 {box_weight:g} = {estimated_lb:,.0f} lb estimated "
                    f"(source: {box_weight_source})",
                )
            )
            elements.append(
                self._label_value(
                    "Harvest yield",
                    f"{harvest_lb:,.0f} lb",
                )
            )
            # "Calculated Shrinkage" is the packing-house term inspectors use
            # for the field-to-pack weight difference (moisture loss, culls,
            # grade-down). "Delta" reads like an unexplained discrepancy —
            # shrinkage is the domain-correct framing.
            #
            # Sign convention: ``delta_lb = harvest_lb - estimated_lb`` is
            # ALREADY shrinkage in the correct direction. Harvest > packed
            # means weight was lost between field and pack-out — the
            # normal, positive shrinkage case. A negative shrinkage
            # ("packed more than harvested") is physically implausible and
            # signals a data-entry error; we preserve the sign so an
            # inspector sees that state immediately rather than its
            # absolute value.
            shrink_lb = delta_lb
            shrink_pct = delta_pct
            elements.append(
                self._label_value(
                    # Not "Calculated Shrinkage": the number is harvest minus sold, and nothing on
                    # record says the difference is shrink (audit 2026-10, T22).
                    "Harvest minus sold",
                    f"{shrink_lb:+,.0f} lb ({shrink_pct:+.1f}%) vs \u00b1{tolerance * 100.0:.0f}% tolerance",
                )
            )
            elements.append(
                self._label_value(
                    "Yield-to-sales reconciliation",
                    status_label,
                )
            )
            if not within_tolerance:
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW]</b> Harvest minus sold is {shrink_pct:+.1f}%, "
                        f"outside the \u00b1{tolerance * 100.0:.0f}% tolerance configured for this "
                        "crop. No record in Trazo states what the difference was; a difference "
                        "this size warrants an inspector review of pack-out documentation "
                        "(pack-out weights, shrink logs, grade-down allocations).",
                        self._warning_style(),
                    )
                )

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Yield-to-sales reconciliation supports the § 205.2 audit-trail definition "
                "and the § 205.103(b)(2) SOE enhanced-traceability requirement by "
                "connecting inputs purchased and harvest yield to the sales quantity shipped. "
                "Box weight defaults are industry standards drawn from USDA-AMS packing-house "
                "references; set the box weight on the production record to override it for a "
                "given season. The \u00b110% tolerance reflects typical specialty-"
                "crop pack-out shrink and is advisory \u2014 larger deltas warrant review, "
                "not an automatic non-conformance.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section: Field Map — schematic parcel boundary + adjoining land
    # ------------------------------------------------------------------

    def _build_field_map_section(self):
        """
        Schematic parcel-boundary map drawn from the stored GeoJSON polygon, with
        compass-direction labels carrying adjoining land use (from Parcel.buffer_zones).
        Every real CCOF inspection packet includes a field map; this is a not-to-scale
        schematic, not a survey. Degrades to a REVIEW note when geometry is absent and
        never crashes PDF generation.
        """
        from reportlab.graphics.shapes import Drawing, Line, Polygon, String

        elements = [self._section_header("Field Map — Parcel Boundary & Adjoining Land")]

        try:
            parcel = self.production.parcel
        except AttributeError:
            parcel = None

        # Parcel identity (Common OSP Parcel Application keys records to APN + S-T-R) and the
        # treated-lumber contamination source (7 CFR 205.272).
        if parcel is not None:
            id_rows = [
                ("Assessor's Parcel Number (APN)", getattr(parcel, "apn", None)),
                ("Section-Township-Range", getattr(parcel, "section_township_range", None)),
                (
                    "Date Began Managing",
                    parcel.date_began_managing.isoformat() if getattr(parcel, "date_began_managing", None) else None,
                ),
            ]
            if any(v for _, v in id_rows):
                id_data = [[self._hdr("Field"), self._hdr("Value")]]
                for label, value in id_rows:
                    id_data.append([self._cell(label, 32), self._cell(_val(value))])
                t_id = Table(id_data, colWidths=[2.4 * inch, 3.6 * inch], repeatRows=1)
                t_id.setStyle(self._base_table_style())
                elements.append(t_id)
                elements.append(self._spacer(0.1))
            if getattr(parcel, "treated_lumber_present", False):
                _desc = (getattr(parcel, "treated_lumber_description", "") or "").strip()
                _installed = (
                    parcel.treated_lumber_install_date.isoformat()
                    if getattr(parcel, "treated_lumber_install_date", None)
                    else None
                )
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] 7 CFR 205.272 — Treated lumber present:</b> "
                        + (_desc or "treated lumber recorded on parcel")
                        + (f" (installed {_installed})" if _installed else "")
                        + ". Confirm it does not contact the organic crop or soil.",
                        self._warning_style(),
                    )
                )
                elements.append(self._spacer(0.1))

        # The drawing itself lives in `certifications.services.parcel_map`, shared with the OSP
        # Parcel Application (2026-08-28). It was a private method here, so the one document that
        # most needs a map — the §205.202 parcel page a certifier reviews before inspecting a new
        # parcel — could not call it and printed a sentence instead. Two renderings of one
        # parcel is how two documents come to disagree about the same field.
        from certifications.services.parcel_map import parcel_map_caption, parcel_map_drawing

        drawing = parcel_map_drawing(parcel) if parcel else None
        if drawing is None:
            elements.append(
                self._body(
                    "No usable field-boundary geometry is on file for this parcel. A parcel map "
                    "showing field boundaries, buffer zones, and adjoining land use is a "
                    "standard certifier expectation (the Common OSP Parcel Application). Add the "
                    "parcel polygon in the producer dashboard so this map renders."
                )
            )
            elements.append(
                Paragraph(
                    "<b>[REVIEW] Field map:</b> parcel boundary geometry missing.",
                    self._warning_style(),
                )
            )
            return elements

        elements.append(drawing)
        elements.append(self._label_value("Parcel", parcel_map_caption(parcel)))
        elements.append(
            Paragraph(
                "Schematic parcel boundary drawn from the recorded field geometry — "
                "not a surveyed plat and not to scale. Compass labels show adjoining land "
                "use per boundary (detail in the Buffer Zones section). Provide the "
                "certifier's official parcel map / plat at the on-site inspection.",
                self._styles["footer_note"],
            )
        )
        return elements

    # ------------------------------------------------------------------
    # Section: Buffer Zones & Adjoining Land Use (7 CFR 205.202(c))
    # ------------------------------------------------------------------

    def _build_buffer_zone_section(self):
        """
        Structured buffer-zone / adjoining-land-use / drift-prevention record per
        parcel boundary (7 CFR 205.202(c)). Orchards in intensive-ag counties sit
        beside conventional aerially-sprayed blocks, so buffers are the primary
        contamination control an inspector probes. Empty record -> REVIEW flag.
        """
        elements = [self._section_header("Buffer Zones & Adjoining Land Use (7 CFR 205.202(c))")]

        try:
            parcel = self.production.parcel
        except AttributeError:
            parcel = None

        buffers = getattr(parcel, "buffer_zones", None) if parcel else None
        rows = [b for b in buffers if isinstance(b, dict)] if isinstance(buffers, list) else []

        if not rows:
            elements.append(
                self._body(
                    "No structured buffer-zone or adjoining-land-use record is on file for "
                    "this parcel. Under 7 CFR 205.202(c) the operation must maintain buffer "
                    "zones sufficient to prevent contact with prohibited substances applied "
                    "to adjoining land, and document drift-prevention measures."
                )
            )
            elements.append(
                Paragraph(
                    "<b>[REVIEW] 7 CFR 205.202(c):</b> add a buffer-zone / adjoining-land-use "
                    "record per parcel boundary (land use, buffer width, drift risk, prevention "
                    "measure) so the inspector has a concrete drift-control record to verify.",
                    self._warning_style(),
                )
            )
            # A missing BOUNDARY record does not excuse the DISPOSITION record — if anything a
            # buffer harvest logged against an undocumented boundary is the more urgent thing
            # for an inspector to see. Appending only on the has-rows path put the disposition
            # table behind this early return, which is the same defect shape as the seed
            # exemption ground that shipped inside `if search_attempts:`.
            return elements + self._buffer_zone_section_tail()

        headers = ["Boundary", "Adjoining Land Use", "Buffer Width", "Drift Risk", "Prevention Measure"]
        data = [[self._hdr(h) for h in headers]]
        for b in rows:
            # Feet first, metres kept.
            #
            # The value is STORED in metres (`buffer_width_m`) and was printed as "15.0 m" on
            # a document that states farm size in acres, yield in pounds and rates per acre.
            # A CCOF or OTCO inspector pacing a buffer works in feet; a bare metric distance
            # in an otherwise US-unit dossier is one more number the reader has to convert,
            # and § 205.202(c) buffers are argued in feet in every US certifier's own
            # paperwork. Same treatment already applied to parcel area and total acreage:
            # lead with the unit the reader uses, keep the stored value in parentheses so
            # nothing is lost.
            width_raw = b.get("buffer_width_m")
            if isinstance(width_raw, (int, float)):
                width_txt = f"{float(width_raw) * 3.28084:.0f} ft ({_fmt_float(width_raw, 1)} m)"
            else:
                width_txt = _val(width_raw)
            data.append(
                [
                    self._cell(_val(b.get("direction"))),
                    self._cell(_val(b.get("adjoining_land_use"))),
                    self._cell(width_txt),
                    self._cell(_val(b.get("drift_risk"))),
                    self._cell(_val(b.get("prevention"))),
                ]
            )
        # Buffer Width widened for the "49 ft (15.0 m)" form; taken from Prevention, which
        # is prose and wraps on word boundaries.
        widths = [0.8 * inch, 1.85 * inch, 1.15 * inch, 0.7 * inch, 1.90 * inch]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # CCOF OSP Sections D & E supplementary descriptors. Rendered as per-boundary
        # detail lines (not extra table columns) to keep the main table inside the page
        # width. Only boundaries that carry any D&E data appear here.
        de_lines = []
        for b in rows:
            # Rows are normalized onto one vocabulary by product.services.buffer_zones
            # (canonical: adjacent_is_organic / crop_grown_in_buffer) and migration
            # product.0023 rewrote the stored ones. The legacy spellings are still read as a
            # fallback for any row that predates that migration — e.g. a database restored
            # from an older backup. Do NOT take this as licence to add a third spelling:
            # reading both was the 2026-08 patch that fixed this PDF while leaving the two
            # writers free to keep destroying each other's data.
            # _esc, not _val: these are interpolated into a raw Paragraph below, and
            # ReportLab parses markup there. Unescaped, "Bob & Sons <b>x" raised ValueError
            # and failed the whole export; "<north lot>" was silently swallowed.
            # `fallback=""`, NOT the default em-dash.
            #
            # 🔴 `_esc(None)` returns "\u2014", which is TRUTHY. Every presence check below —
            # the `continue` that skips a direction with nothing recorded, and each `if` that
            # decides whether to emit a clause — was therefore always true, so an operation
            # with no buffer detail at all still printed four bullets reading
            # "buffer type: \u2014; crop grown in buffer: \u2014; adjoining land last received a
            # prohibited material: \u2014" under a heading that names CCOF OSP Sections D & E.
            #
            # That is worse than printing nothing. Against a specific regulatory question a
            # dash is ambiguous — an inspector cannot tell "no buffer crop" from "not
            # recorded" — and the section looks answered when it is empty. Blank means NOT
            # DOCUMENTED, and the way to say that here is to omit the clause so the
            # already-populated table above stands alone.
            adjacent_organic = bool(b.get("adjacent_is_organic") or b.get("adjacent_organic"))
            buffer_type = _esc(b.get("buffer_type"), fallback="")
            crop_in_buffer = _esc(b.get("crop_grown_in_buffer") or b.get("crop_in_buffer"), fallback="")
            neighbor_notified = bool(b.get("neighbor_notified"))
            notify_date = _esc(b.get("neighbor_notification_date"), fallback="")
            prohibited_last = _esc(b.get("prohibited_use_last_date"), fallback="")
            if not (adjacent_organic or buffer_type or crop_in_buffer or neighbor_notified or prohibited_last):
                continue
            parts = []
            if buffer_type:
                parts.append(f"buffer type: {buffer_type}")
            if crop_in_buffer:
                # State the crop, NOT its organic status. The old text read "crop in buffer
                # (not sold as organic)" — the packet asserting the exact fact § 205.202(c)
                # asks the operator to PROVE, on the strength of a free-text parcel field.
                # What actually happened to the crop is evidenced by the buffer-crop
                # disposition record below; this line only names it.
                parts.append(f"crop grown in buffer: {crop_in_buffer}")
            if adjacent_organic:
                parts.append("adjoining land is also certified organic — no buffer required")
            if prohibited_last:
                parts.append(f"adjoining land last received a prohibited material: {prohibited_last}")
            if neighbor_notified:
                notify_txt = "drift-notification letter on file (§ 205.400(f)(1))"
                if notify_date:
                    notify_txt += f", dated {notify_date}"
                parts.append(notify_txt)
            de_lines.append(f"<b>{_esc(b.get('direction'))}:</b> " + "; ".join(parts))
        if de_lines:
            elements.append(self._spacer(0.08))
            elements.append(self._body("Adjoining-land &amp; buffer detail (Common OSP Sections D &amp; E):"))
            for line in de_lines:
                elements.append(Paragraph("&bull; " + line, self._styles["footer_note"]))

        return elements + self._buffer_zone_section_tail()

    def _buffer_zone_section_tail(self):
        """Everything that closes the land-requirements section, on BOTH exit paths.

        This function returns early when the parcel has no structured buffer-zone record, and
        THREE separate additions have now been appended to the has-rows path only — the buffer
        crop disposition record, the § 205.202(c) footnote, and the neighbour attestation. Each
        time the content silently vanished for exactly the operations with the thinnest
        boundary documentation, which are the ones an inspector looks at hardest.

        One tail, called from both returns, so a fourth addition cannot repeat it.
        """
        return (
            self._buffer_crop_disposition_rows()
            + self._adjoining_land_affidavit_rows()
            + [self._spacer(0.1), self._buffer_zone_footnote()]
        )

    def _adjoining_land_affidavit_rows(self):
        """USDA's Adjoining Land Use Verification (form #25) — signed BY THE NEIGHBOUR.

        Kept visually and structurally apart from the buffer-zone table above because the two
        have different authors. The buffer table is the operation's own account of its
        boundary; this is a third party attesting to their own practices. Presenting them as
        one record would let an operator's entry read as an independent attestation.

        Unsigned rows are rendered and marked as unsigned rather than hidden: the operation
        having sought the attestation is itself worth showing, but it is not yet third-party
        evidence.
        """
        from certifications.models import AdjoiningLandAffidavit

        try:
            parcel = self.production.parcel
        except AttributeError:
            parcel = None
        if parcel is None:
            return []

        affidavits = list(AdjoiningLandAffidavit.objects.filter(parcel=parcel).order_by("border_side", "-created_at"))
        if not affidavits:
            return []

        elements = [
            self._spacer(0.12),
            self._body("<b>Adjoining Land Use Verification — neighbour attestation (7 CFR 205.202(c))</b>"),
        ]
        headers = ["Neighbour", "Side", "Materials Used", "Distance", "Notify?", "Signed"]
        data = [[self._hdr(h) for h in headers]]
        unsigned = []
        for a in affidavits:
            # Three states again: an affirmative "none of the above", a list, or silence.
            if a.declares_no_materials is True:
                materials = "None of the listed materials (declared)"
            elif a.materials_display():
                materials = a.materials_display()
                if a.not_used_on_adjoining_fields is True:
                    materials += " — not on adjoining fields"
            else:
                materials = "Not answered"

            distance = (
                f"{a.distance_to_organic_property_ft} ft" if a.distance_to_organic_property_ft is not None else "—"
            )
            # A neighbour who did not answer has not refused; say so rather than printing "No".
            notify = {True: "Yes", False: "No", None: "Not answered"}[a.agrees_to_notify]
            if a.is_signed():
                signed = _fmt_date(a.neighbor_signed_date) if a.neighbor_signed_date else "Document on file"
            else:
                signed = "UNSIGNED"
                unsigned.append(a)
            data.append(
                [
                    self._cell(a.neighbor_name or "—"),
                    self._cell(a.get_border_side_display() if a.border_side else "—"),
                    self._cell(materials),
                    self._cell(distance),
                    self._cell(notify),
                    self._cell(signed),
                ]
            )
        t = Table(
            data, colWidths=[1.3 * inch, 0.7 * inch, 2.0 * inch, 0.7 * inch, 0.8 * inch, 0.9 * inch], repeatRows=1
        )
        t.setStyle(self._base_table_style())
        elements.append(t)

        if unsigned:
            elements.append(
                Paragraph(
                    f"<b>[REVIEW] 7 CFR 205.202(c):</b> {len(unsigned)} adjoining-land attestation(s) are "
                    "recorded but not signed by the neighbour. Until signed they are the operation's own "
                    "account of a neighbour's practices, not third-party verification of them.",
                    self._warning_style(),
                )
            )
        return elements

    def _buffer_zone_footnote(self):
        """The § 205.202(c) closing note.

        Extracted because this section has TWO exit paths and the early one (no structured
        buffer-zone record on file) used to return without it — so the section simply ended
        mid-air, and anything keying off the footnote as a section boundary ran past it into
        the rest of the document. Copy-pasting the text into both paths would have made it
        two writers of one string; a single method keeps it one.
        """
        return Paragraph(
            "7 CFR 205.202(c): certified land must have distinct, defined boundaries and "
            "buffer zones to prevent unintended contact with prohibited substances from "
            "adjoining land. Under § 205.671, a residue above 5% of the EPA tolerance means "
            "the PRODUCT may not be sold, labeled or represented as organic; it does not by "
            "itself revoke the operation's certification. "
            # 🔴 2026-08-20 — read "can cause loss of organic status", which conflates the
            # product and the operation. This is the sentence an operator acts on in the hours
            # after a drift event, when the difference between "this block's crop is out" and
            # "we have lost certification" decides whether they call the certifier or panic.
            "Operator maintains the drift-prevention measures above and, "
            "where a neighbor applies prohibited substances, an annual neighbor-"
            "notification letter on file (§ 205.400(f)(1) drift-notification readiness).",
            self._styles["footer_note"],
        )

    def _buffer_crop_disposition_rows(self):
        """USDA's Buffer Crop Disposition Record, per harvest event (7 CFR 205.202(c)).

        The buffer-zone table above documents the drift CONTROL; this documents what became
        of the crop grown inside that buffer. USDA publishes them as one record because a
        certifier asks both questions in the same breath, and until now the packet answered
        only the first.

        Silence is deliberate where the regulation is silent: a harvest with no disposition
        recorded produces no row (the question was not asked of pre-2026-08 events, and
        NULL means unanswered, not "no buffer"), and only commerce-entering dispositions
        draw a missing-evidence flag.
        """
        from history.models import ProductionEvent

        events = list(
            # HA *and* BU. Buffer Use exists as its own activity precisely to record this
            # disposition when it is not part of a harvest — filtering to HA meant the
            # dedicated activity was the one case this § 205.202(c) table could not see.
            # Matches RECORDS_BUFFER in ProductionTab; the render, the payload, this table and
            # the Harvest/Transport/Buffer table are four copies of one decision.
            ProductionEvent.objects.filter(
                history_id=self.production.id,
                type__in=["HA", "BU"],
                buffer_disposition__isnull=False,
            )
            .exclude(buffer_disposition="")
            .order_by("date")
        )
        if not events:
            return []

        labels = dict(ProductionEvent._meta.get_field("buffer_disposition").choices or [])

        elements = [
            self._spacer(0.12),
            self._body("<b>Buffer Crop Disposition Record (7 CFR 205.202(c))</b>"),
        ]
        # Lot added 2026-08-19. A Buffer Use event carries a lot code, and without it here the
        # only way to see which lot the buffer crop came off was a row in the harvest table
        # whose other ten columns were all dashes. An inspector should not have to cross-read
        # two tables for one fact.
        headers = ["Date", "Lot", "Disposition", "Quantity Removed", "Documentation (type and location)"]
        data = [[self._hdr(h) for h in headers]]
        missing_evidence = []
        for e in events:
            entered = e.buffer_disposition_entered_commerce()
            # Evidence is only owed once the crop left the operation. A bare dash in both
            # cases would read as one gap to a certifier skimming the column, so name the
            # two states apart: nothing owed vs owed and absent.
            # `entered` is checked FIRST, deliberately. Evidence recorded against an earlier
            # commerce disposition can survive a correction to "left in field" (the field is
            # nullable and older clients omitted the key rather than clearing it), and
            # printing a delivery tag beside a crop that never left the farm would be the
            # packet contradicting itself.
            if not entered:
                evidence = "Not required — crop did not leave the operation"
            elif e.buffer_disposition_evidence:
                evidence = str(e.buffer_disposition_evidence)
            else:
                evidence = "Not recorded"
                missing_evidence.append(e)
            data.append(
                [
                    self._cell(_val(e.date.date() if e.date else None)),
                    self._cell(getattr(e, "harvest_lot_code", None)),
                    self._cell(labels.get(e.buffer_disposition, _val(e.buffer_disposition))),
                    self._cell(_val(e.buffer_disposition_quantity)),
                    self._cell(evidence),
                ]
            )
        # 0.85 + 1.15 + 1.5 + 1.0 + 2.5 = 7.00in, the printable frame. ReportLab does not
        # raise when a table runs past it — it draws off the page.
        t = Table(
            data,
            colWidths=[0.85 * inch, 1.15 * inch, 1.5 * inch, 1.0 * inch, 2.5 * inch],
            repeatRows=1,
        )
        t.setStyle(self._base_table_style())
        elements.append(t)

        if missing_evidence:
            elements.append(
                Paragraph(
                    "<b>[REVIEW] 7 CFR 205.202(c):</b> "
                    f"{len(missing_evidence)} buffer harvest(s) left the operation with no "
                    "documentation recorded. USDA's Buffer Crop Disposition Record asks for "
                    "delivery tags and nonorganic sales records showing the buffer crop was not "
                    "represented as organic — record the document type and where it is filed.",
                    self._warning_style(),
                )
            )
        return elements

    # ------------------------------------------------------------------
    # Section: State Organic Program Registration (CDFA SOP producer registration)
    # ------------------------------------------------------------------

    def _build_state_organic_registration_section(self):
        """State Organic Program (CDFA SOP) producer-registration record.

        CA producers selling > $5,000/yr organic must register annually with the
        CDFA State Organic Program before their first organic sale (CA Food & Ag
        Code §§ 46000-46029) — distinct from CDFA OIM input-material registration.
        A missing or expired registration for the operation is a REVIEW item.
        """
        from certifications.models import StateOrganicRegistration

        elements = [self._section_header("State Organic Program Registration")]

        try:
            est = self.production.parcel.establishment
        except AttributeError:
            est = None

        reg = None
        if est is not None:
            reg = StateOrganicRegistration.objects.filter(establishment=est).order_by("-registration_date").first()

        # The producer-registration requirement is California state law (CA Food & Ag
        # Code §§ 46000-46029). Only fire the missing-registration REVIEW flag for a CA
        # operation (or when the operation's state is unrecorded — better to prompt than
        # silently miss it); for a known non-CA operation a CDFA registration does not
        # apply, so surface an informational note instead of a false-positive inspector flag.
        est_state = resolve_establishment_state(est)
        ca_requirement_applies = est_state in ("CA", None)

        if reg is None:
            if ca_requirement_applies:
                elements.append(
                    self._body(
                        "No State Organic Program registration is on file for this operation. "
                        "Under California Food & Agricultural Code §§ 46000-46029, a producer "
                        "selling more than $5,000/yr of organic product must register with the "
                        "CDFA State Organic Program before the first organic sale and renew "
                        "annually (this is separate from CDFA OIM input-material registration)."
                    )
                )
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] CDFA State Organic Program:</b> add the operation's state "
                        "registration (registration number, county, operation type, prior-year "
                        "organic gross sales, registration and renewal dates) so the inspector "
                        "can confirm the CA pre-sale registration requirement is met.",
                        self._warning_style(),
                    )
                )
            else:
                elements.append(
                    self._body(
                        "No State Organic Program registration is on file. The CDFA State "
                        "Organic Program producer-registration requirement is California state "
                        f"law; this operation is recorded in {_val(getattr(est, 'state', None))}, "
                        "where a state organic program may not apply. Verify the operation's "
                        "state requirements with the certifier."
                    )
                )
            return elements

        commodities = reg.commodities if isinstance(reg.commodities, list) else []
        gross = reg.prior_year_organic_gross_sales
        rows = [
            ("Program", reg.program_name),
            ("State", reg.state),
            ("Operation Type", reg.get_operation_type_display()),
            ("Status", reg.get_status_display()),
            ("Registration #", reg.registration_number),
            ("County", reg.county),
            ("Registration Date", reg.registration_date.isoformat() if reg.registration_date else None),
            ("Renewal Date", reg.renewal_date.isoformat() if reg.renewal_date else None),
            ("Prior-Year Organic Gross Sales", f"${gross:,.2f}" if gross is not None else None),
            ("Commodities", ", ".join(str(c) for c in commodities) if commodities else None),
        ]
        data = [[self._hdr("Field"), self._hdr("Value")]]
        for label, value in rows:
            data.append([self._cell(label, 32), self._cell(_val(value))])
        t = Table(data, colWidths=[2.0 * inch, 4.0 * inch], repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        if not reg.is_current:
            elements.append(self._spacer(0.1))
            elements.append(
                Paragraph(
                    "<b>[REVIEW] CDFA State Organic Program:</b> the registration on file is "
                    "not current (status is not 'registered', or the renewal date has passed). "
                    "Confirm the operation renewed before its first organic sale of the cycle.",
                    self._warning_style(),
                )
            )

        # $5,000 threshold: the "exempt" status only holds below $5,000/yr organic
        # sales. If the recorded prior-year organic gross sales exceed $5,000 while the
        # operation is still marked exempt, the exemption no longer applies — the
        # operation must register with the CDFA SOP and be certified (7 CFR 205.101 /
        # CA Food & Ag Code §§ 46000-46029). Passive audit flag, not a reminder system.
        try:
            over_threshold = gross is not None and gross > Decimal("5000")
        except (TypeError, InvalidOperation):
            over_threshold = False
        if reg.status == "exempt" and over_threshold:
            elements.append(self._spacer(0.1))
            elements.append(
                Paragraph(
                    "<b>[REVIEW] $5,000 exemption exceeded:</b> prior-year organic gross sales "
                    f"of ${gross:,.2f} are above the $5,000 exemption, but the registration is "
                    "still marked 'Exempt (&lt; $5,000 organic sales)'. Above $5,000 the operation "
                    "must hold a current CDFA State Organic Program registration and USDA organic "
                    "certification. Update the registration status.",
                    self._warning_style(),
                )
            )
        return elements

    # ------------------------------------------------------------------
    # Section: Post-Harvest Handling & Storage (7 CFR 205.272 / 205.270)
    # ------------------------------------------------------------------

    def _facility_cert_block(self, facility):
        """
        Off-farm handler / facility organic-certificate block (Common OSP G6.1 / 7 CFR
        205.272). Renders the handler's identity + organic certificate and flags
        the 15-month freshness rule as DOCUMENTED / GAP / REVIEW. This is the
        load-bearing tree-nut record: a wholesale nut grower ships in-shell to a
        shared huller, the classic commingling point.
        """
        elements = [self._body("<b>Off-Farm Handler / Facility Certificate (7 CFR 205.272 · Common OSP G6.1)</b>")]
        elements.append(self._spacer(0.04))

        vstatus = (facility.verification_status or "").lower()
        if vstatus == "verified":
            verif = "Verified via USDA Organic Integrity Database"
        elif vstatus == "self_reported":
            verif = "Self-reported (operator-provided; not independently verified)"
        else:
            verif = facility.get_verification_status_display() if facility.verification_status else "Not verified"

        location = ", ".join([x for x in [facility.city, facility.state] if x]) or None
        rows = [
            ("Handler / Facility", facility.name),
            ("Facility Type", facility.get_facility_type_display() if facility.facility_type else None),
            ("Location", location),
            ("Organic Certificate #", facility.certification_number),
            ("Certifier", facility.certifier_name),
            ("Cert Effective", _fmt_date(facility.effective_date) if facility.effective_date else None),
            ("Cert Expiry", _fmt_date(facility.expiry_date) if facility.expiry_date else None),
            ("Verification", verif),
        ]
        for label, value in rows:
            elements.append(self._label_value(label, value))

        # Run 7 (R7-01): dates, the copy and verification are three facts, printed apart. A date
        # inside the 15-month window used to print "DOCUMENTED ... on file and current" for a
        # self-reported handler with no copy held anywhere. A date alone establishes neither.
        if facility.cert_document:
            copy_line = "A copy of the certificate is held in Trazo; it is not included in this export."
        else:
            copy_line = "No copy of the certificate is held in Trazo."
        elements.append(self._label_value("Certificate copy", copy_line))

        current = facility.cert_is_current
        if current is True:
            elements.append(
                self._body(
                    "Certificate dates as entered fall within the ~15-month window Common OSP G6.1 uses "
                    "(7 CFR 205.272). Dates alone do not establish the handler's certification status."
                )
            )
        elif current is False:
            elements.append(
                Paragraph(
                    # ⛔ "expired" is wrong under § 205.404(d) — a NOP organic certificate does
                    # NOT expire; it continues until surrendered, suspended or revoked. This
                    # document says exactly that two pages earlier, in the Active Certification
                    # Summary footnote, so the two statements contradicted each other. What is
                    # actually true is narrower and still worth flagging: the copy ON FILE is
                    # stale, because CCOF issues an updated certificate after each § 205.406
                    # annual update. [GAP] was also the only use of a fourth flag word in a
                    # document that otherwise uses REVIEW / WARNING / NON-CONFORMANCE.
                    "<b>[REVIEW] 7 CFR 205.272 / Common OSP G6.1:</b> the certificate dates as entered are more than "
                    "15 months old. A NOP certificate does not expire (§ 205.404(d)), but the certifier "
                    "reissues it after each annual update — request a current copy so the certificate "
                    "travelling with the lot matches the handler's present status.",
                    self._warning_style(),
                )
            )
        else:
            elements.append(
                Paragraph(
                    "<b>[REVIEW] Common OSP G6.1:</b> no certificate effective date on file for this handler — confirm "
                    "the handler's current organic certificate (issued within 15 months) is attached to the lot records.",
                    self._warning_style(),
                )
            )

        if not facility.cert_document:
            elements.append(
                Paragraph(
                    "Attach a copy of the handler's organic certificate to the lot records (7 CFR 205.272).",
                    self._styles["footer_note"],
                )
            )
        elements.append(self._spacer(0.12))
        return elements

    def _build_handler_round_trip_subtable(self):
        """What went to the handler and what came back — CCOF grower checklist item 6.

        The checklist asks for four facts about crop sent to another certified operation:
        "what you sent, where you sent it, when you sent it, and what you received as the
        outcome." Before 2026-08-16 the packet could answer only *where* (the facility block
        above); the outcome existed nowhere except as inferred shrinkage in the mass-balance
        section, which is a plausibility check rather than a record.

        Deliberately prints a per-load table rather than a single production-level figure: a
        multi-pick season sends several loads to the same huller on different dates, and the
        pack-out comes back per load.
        """
        try:
            events = [
                ev
                for ev in self.production.history_productionevent_events.all()
                if any(
                    [
                        getattr(ev, "sent_to_handler_date", None),
                        getattr(ev, "quantity_sent_to_handler", None) is not None,
                        getattr(ev, "quantity_returned_from_handler", None) is not None,
                        getattr(ev, "handler_document_reference", None),
                    ]
                )
            ]
        except AttributeError:
            events = []

        if not events:
            return []

        elements = [self._body("<b>Crop Sent for Off-Farm Handling (7 CFR 205.272 · Common OSP G6.1)</b>")]
        elements.append(self._spacer(0.04))

        # Run 7 (R7-11): the first column read "Harvest Date" over whatever event carried the
        # handler fields, so a transport record's date printed as a harvest. It now names the
        # record's own date and kind.
        headers = ["Record (date, kind)", "Lot", "Sent On", "Quantity Sent", "Received Back", "Handler Document"]
        data = [[self._hdr(h) for h in headers]]

        for ev in sorted(events, key=lambda e: (e.sent_to_handler_date or date.min)):
            # Grouped thousands, not `_fmt_float`. These are load weights — 42000 vs 42,000 —
            # and every other large figure in this packet groups (nitrogen totals, shrinkage,
            # gross sales). `_fmt_float` is the outlier and is left alone: it is used on
            # hundreds of small values whose snapshots would all churn.
            sent = None
            if ev.quantity_sent_to_handler is not None:
                sent = f"{float(ev.quantity_sent_to_handler):,.2f} {_val(ev.handler_quantity_unit, '')}".strip()
            back = None
            if ev.quantity_returned_from_handler is not None:
                back = f"{float(ev.quantity_returned_from_handler):,.2f} {_val(ev.handler_return_unit, '')}".strip()
            kind = PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type)).lower()
            data.append(
                [
                    self._cell(f"{_fmt_date(ev.date)} ({kind})"),
                    self._cell(getattr(ev, "harvest_lot_code", None)),
                    self._cell(_fmt_date(ev.sent_to_handler_date) if ev.sent_to_handler_date else None),
                    self._cell(sent),
                    self._cell(back),
                    # A settlement / pack-out reference is an audit-trail identifier — not
                    # truncated, for the same reason invoice and lot numbers are not.
                    self._cell(getattr(ev, "handler_document_reference", None)),
                ]
            )

        widths = [0.85 * inch, 1.1 * inch, 0.85 * inch, 1.15 * inch, 1.15 * inch, 1.6 * inch]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # Flag loads that went out and never came back on paper. Stated as a REVIEW, not a
        # finding: the crop may still be at the handler, which is normal mid-season — but it is
        # the open end of the § 205.103(b)(2) trace and the certifier should see it.
        open_loads = [
            ev for ev in events if ev.quantity_sent_to_handler is not None and ev.quantity_returned_from_handler is None
        ]
        if open_loads:
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    f"<b>[REVIEW] 7 CFR 205.103(b)(2):</b> {len(open_loads)} load(s) were sent for "
                    "off-farm handling with no returned quantity recorded. Record the pack-out or "
                    "settlement figure once the handler reports it, so the lot traces from field "
                    "to finished product.",
                    self._warning_style(),
                )
            )

        elements.append(self._spacer(0.12))
        return elements

    def _build_post_harvest_section(self):
        """
        Post-harvest handling & storage. Surfaces Post-Harvest Processing (PH) events
        — hulling, shelling, washing, sorting, packing — plus storage location /
        temperature recorded on harvest or PH events. For tree nuts this is where
        organic integrity is most at risk (often a shared off-farm huller / dryer),
        so the section also states the off-farm-handler certificate expectation.
        """
        elements = [
            self._section_header("Post-Harvest Handling & Storage (7 CFR 205.272 / 205.270 · Common OSP G6.2 / G6.4)")
        ]

        # 🔴 2026-08-21 — MANY, not one. This read a single FK, so a lot that shipped its
        # fresh grade to one certified handler and its process grade to another could only
        # ever name one of them, and the "no handler certificate on file" REVIEW below
        # cleared the moment that one was linked — the second handler's certificate silently
        # stopped being asked for. Five of Calapooia Bend's nine shipped lots were exactly
        # that shape.
        try:
            facilities = sorted(self.production.post_harvest_facilities.all(), key=lambda f: (f.name or "").lower())
        except AttributeError:
            # Same defensiveness as `all_events` below, and for the same reason the FK read
            # this replaced used `getattr(..., None)`: a cross-check must never take the
            # packet down.
            facilities = []

        try:
            all_events = list(self.production.history_productionevent_events.all())
        except AttributeError:
            all_events = []

        ph_events = [ev for ev in all_events if ev.type == "PH"]
        storage_events = [
            ev
            for ev in all_events
            if ev.type != "PH"
            and (getattr(ev, "storage_location", None) or getattr(ev, "storage_temperature_f", None) is not None)
        ]

        # The off-farm handler certificates are the load-bearing record — render them
        # first, whether or not on-farm PH/storage events exist. One block per handler:
        # each carries its own certificate number, certifier and 15-month freshness verdict,
        # and merging two handlers into one block would attach one certificate to both.
        if len(facilities) > 1:
            # Say so before the blocks. Two identical "Off-Farm Handler / Facility
            # Certificate" headings in a row read as a duplicated section unless the reader
            # is told the lot genuinely went to more than one certified operation.
            elements.append(
                self._body(
                    f"This lot was handled by {len(facilities)} certified operations; each "
                    "certificate is recorded separately below."
                )
            )
            elements.append(self._spacer(0.04))
        for facility in facilities:
            elements += self._facility_cert_block(facility)

        # ABOVE the early return, deliberately. A grower who ships field-run to a huller logs
        # no PH event and no storage location — the two things that used to be the only way
        # into this section — so gating the round trip behind them hid CCOF item 6 in exactly
        # the case item 6 is about. (Found by test, 2026-08-16: the subtable sat below the
        # return and rendered for nobody.)
        round_trip = self._build_handler_round_trip_subtable()
        elements += round_trip

        # A load went out and no handler is named. This is the one state where the § 205.272
        # certificate expectation is not a general reminder but a specific, answerable gap:
        # the operation has recorded that crop LEFT for handling and not recorded WHO handled
        # it, so their certificate cannot travel with the lot.
        if round_trip and not facilities:
            # 🔴 2026-08-20 — this used to read "no handler is recorded for this production",
            # printed directly beneath a table naming the packinghouse, its receiving-tag
            # numbers and the storage room. Both certifier reviewers flagged it independently
            # and both said the same thing: the sentence is false on its face, so they would
            # discount the finding — which is the worst outcome, because the underlying gap is
            # REAL. The handler's NAME is on file as free text; what is missing is the
            # certificate-bearing handler record, and that is the § 205.272 requirement.
            #
            # A warning that misdescribes the gap spends the reviewer's trust and fixes
            # nothing. Name what is on file, then say precisely what is not.
            # 🔴 2026-08-21 — `storage_location` came FIRST and the sentence below asserted
            # every name in this list was an off-farm handler. On an operation that cools and
            # packs its own fruit, the first values are its own buildings, so the packet read
            # "this lot was sent for off-farm handling to Farm cooler" — false on its face
            # about the farm's own cooler, and false in the same way the 2026-08-20 fix above
            # was written to prevent. Where the lot actually WENT is the transport destination
            # and the buyer; storage locations are the last resort, and the wording no longer
            # claims each name is a handler.
            named = []

            def _add(value):
                text = (value or "").strip()
                if text and text not in named:
                    named.append(text)

            for ev in all_events:
                if getattr(ev, "type", None) == "TP":
                    _add(getattr(ev, "transport_destination_address", None))
            try:
                for sale in self.production.sales_records.live():
                    _add(getattr(sale, "sold_to", None) or getattr(sale, "buyer_name", None))
            except AttributeError:
                pass
            if not named:
                for ev in all_events:
                    _add(getattr(ev, "storage_location", None))

            if named:
                # ⚠️ `storage_location` and `sold_to` are OPERATOR FREE TEXT going into a
                # ReportLab Paragraph, which parses a mini-HTML dialect. "Bob & Sons" raises
                # ValueError and takes the whole packet down; "Stemilt <north dock>" is
                # silently swallowed. Same trap `_esc` was written for on 2026-08-12 — every
                # hand-built Paragraph that interpolates a farmer's words needs it.
                known = "; ".join(_esc(name) for name in named[:3])
                message = (
                    "<b>[REVIEW] 7 CFR 205.272 / Common OSP G6.1:</b> this lot left the "
                    "operation for handling. The destinations recorded against it are free "
                    f"text — {known} — and none is a handler record carrying an organic "
                    "certificate. Add each off-farm handler with its current certificate "
                    "(issued within ~15 months) so the certificate travels with the lot."
                )
            else:
                message = (
                    "<b>[REVIEW] 7 CFR 205.272 / Common OSP G6.1:</b> this lot was sent for "
                    "off-farm handling, but no handler is recorded for this production. Add "
                    "the handler and its current organic certificate (issued within ~15 "
                    "months) so the certificate travels with the lot."
                )
            elements.append(Paragraph(message, self._warning_style()))
            elements.append(self._spacer(0.08))

        if not ph_events and not storage_events:
            if not facilities and not round_trip:
                elements.append(
                    self._body(
                        "No post-harvest processing or storage events are recorded for this "
                        f"production. {self._post_harvest_steps_phrase()} If any of these steps "
                        "occur off-farm, that facility must be a certified organic handler "
                        "and its organic certificate must accompany the lot (7 CFR 205.272 "
                        "commingling prevention). Record post-harvest handling events and storage "
                        "locations so the audit trail is unbroken from field to sale."
                    )
                )
            return elements

        if ph_events:
            elements.append(self._body("<b>Post-Harvest Processing Events</b>"))
            elements.append(self._spacer(0.04))
            headers = ["Date", "Activity", "Description", "Storage Location", "Storage Temp", "Operator"]
            data = [[self._hdr(h) for h in headers]]
            for ev in sorted(ph_events, key=lambda e: (e.date or date.min)):
                temp = f"{_fmt_float(ev.storage_temperature_f)}°F" if ev.storage_temperature_f is not None else None
                data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.description),
                        # Storage location carries the bin / lot ID — the traceback key —
                        # so it must not be truncated short of the identifier.
                        self._cell(ev.storage_location),
                        self._cell(temp),
                        self._cell(ev.performed_by),
                    ]
                )
            widths = [0.7 * inch, 1.0 * inch, 1.95 * inch, 1.6 * inch, 0.6 * inch, 0.85 * inch]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

        if storage_events:
            elements.append(self._spacer(0.12))
            elements.append(self._body("<b>Storage Records (lot traceback — § 205.272 / FSMA 204 KDE)</b>"))
            elements.append(self._spacer(0.04))
            headers = ["Date", "Event", "Storage Location", "Storage Temp", "Operator"]
            data = [[self._hdr(h) for h in headers]]
            for ev in sorted(storage_events, key=lambda e: (e.date or date.min)):
                temp = f"{_fmt_float(ev.storage_temperature_f)}°F" if ev.storage_temperature_f is not None else None
                data.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type))),
                        self._cell(ev.storage_location),
                        self._cell(temp),
                        self._cell(ev.performed_by),
                    ]
                )
            widths = [0.75 * inch, 1.2 * inch, 2.4 * inch, 0.85 * inch, 1.0 * inch]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "Off-farm post-harvest handling (custom hulling, drying, cold storage) must "
                "be performed by a certified organic handler (7 CFR 205.272). Retain the handler's "
                "organic certificate with the lot records for inspection. Whether Trazo holds a copy "
                "is stated in the handler's certificate block. Dedicated organic "
                "equipment / bins or documented clean-out "
                "between conventional and organic lots prevents commingling.",
                self._styles["footer_note"],
            )
        )
        # CDFA vs CDPH scope: the PH events above (hull/shell/wash/sort/pack) keep the
        # crop a RAW agricultural commodity under CDFA. Turning it into a PROCESSED
        # organic product (roasting, grinding to butter/flour, oil pressing, blanching,
        # adding ingredients) crosses into the California Department of Public Health
        # (CDPH) "processed product" domain and requires a SEPARATE CDPH organic
        # registration in addition to the CDFA producer/handler registration.
        # 🔴 2026-08-20 — printed on every operation in every state. CDFA and CDPH are
        # California agencies; on a Washington packet this reads as Trazo not knowing which
        # state its user farms in, and a WSDA reviewer flagged it as a credibility problem
        # before they flagged it as an error. The distinction it draws is real and useful —
        # for a CA operation. Gate it the same way the registration section above is gated.
        try:
            note_state = resolve_establishment_state(self.production.parcel.establishment)
        except AttributeError:
            note_state = None
        if note_state in ("CA", None):
            elements.append(self._spacer(0.06))
            elements.append(
                Paragraph(
                    "<b>Scope note (CDFA vs CDPH):</b> the post-harvest steps above are raw-ag "
                    "handling under CDFA. If this operation instead makes a <i>processed</i> organic "
                    "product on-farm (roasting, grinding to butter/flour, oil pressing, blanching, or "
                    "adding ingredients), that product requires a separate CDPH organic registration "
                    "distinct from the CDFA producer/handler registration Trazo records.",
                    self._styles["footer_note"],
                )
            )
        return elements

    # ------------------------------------------------------------------
    # Section 14: 3-Year Field / Crop Rotation History
    # ------------------------------------------------------------------

    def _build_field_history_section(self):
        from product.models import ParcelCropHistory

        elements = [self._section_header("Field History & Previous Land Use — 3-Year Crop Rotation (7 CFR 205.202(b))")]

        parcel = None
        try:
            parcel = self.production.parcel
        except AttributeError:
            pass

        if parcel is None:
            elements.append(self._body("Parcel data not available for this production."))
            return elements

        elements.append(self._label_value("Parcel", parcel.name))

        # NOP 7 CFR 205.202 — computed transition status (Sprint 2.2)
        try:
            from product.services.transition_status_service import compute_transition_status, transition_verdict

            ts = compute_transition_status(parcel)
            # "Eligible" is a determination the CERTIFYING AGENT makes, and
            # compute_transition_status reaches it "by absence of contrary evidence" (its own
            # comment). With no field history on file at all, that absence evidences nothing:
            # a parcel with three documented clean years and a parcel with zero records both
            # produce findings=[], because the service only queries rows that carry a
            # date_last_prohibited. Printing the favourable verdict for the second case puts a
            # self-assigned eligibility call into a document the certifier reads — the same
            # absence-is-not-a-pass rule applied to the snapshot marks.
            # One definition of this sentence, shared with the OSP packet's parcel page — it was
            # corrected here first and the packet went on printing "Eligible: Yes" from the same
            # status object for months. See product/services/transition_status_service.py.
            has_field_history = ParcelCropHistory.objects.filter(parcel=parcel).exists()
            elements.append(
                self._label_value(
                    "Organic Transition Status",
                    transition_verdict(ts, has_field_history=has_field_history),
                )
            )
            # The operator's own statements, as statements (audit 2026-10, T21). Same helper as
            # the packet's parcel page, so the two documents cannot say different things.
            from product.services.transition_status_service import operator_statement_lines

            for line in operator_statement_lines(parcel):
                elements.append(self._body(_esc(line)))
            if ts.last_prohibited_date:
                elements.append(self._label_value("Last Prohibited Substance Date", str(ts.last_prohibited_date)))
            if ts.note:
                # _esc: as of 2026-08-19 this note NAMES the unclassified applications
                # ("Entrust SC (2026-06-24)") so the grower knows which records to open, and
                # a commercial name is operator free text going into a markup-parsing
                # Paragraph. `_body` does not escape. Before the note carried product names it
                # held only counts and dates, which is why this line was safe until then.
                elements.append(self._body(_esc(ts.note)))
        except Exception:  # noqa: BLE001 — non-fatal; export should still render
            pass

        # --- Primary: typed ParcelCropHistory years MERGED with years derived from the seasons
        # logged on this parcel. Reading the typed table alone left the two most recent, best
        # documented years off every renewal's § 205.202(b) section — see
        # product/services/land_history.py. Capped at the audited production's own year so a
        # 2026 packet does not list 2027 plantings; a spanning season caps at its finish year.
        from product.services.land_history import land_history_rows

        _span_end = self.production.finish_date or self.production.expected_harvest or self.production.start_date
        _through = (
            max(
                (self.production.start_date.year if self.production.start_date else 0),
                (_span_end.year if _span_end else 0),
            )
            or None
        )
        crop_history = land_history_rows(parcel, limit=10, through_year=_through)

        if crop_history:
            headers = [
                "Year",
                "Crop Grown",
                "Production Method",
                "Substances Applied",
                # Was "Last Prohibited Substance" over a cell rendering only the DATE, so a
                # certifier read "Last Prohibited Substance: 2019-05-12". Worse, the model
                # carries the substance NAME in `last_prohibited_substance` — the very
                # "Name and Application Date of Last Prohibited Input" USDA asks for on every
                # field — and the packet never printed it. Both now render.
                "Last Prohibited Input",
                "Notes",
            ]
            header_row = [self._hdr(h) for h in headers]
            data = [header_row]

            for entry in crop_history:
                data.append(
                    [
                        # A derived year is marked in the cell, not only in Notes, so the
                        # provenance survives a reader who scans the first column.
                        self._cell(f"{entry.year}{' *' if entry.is_derived else ''}"),
                        # Fold the block into the crop cell rather than adding a column: this
                        # table is already against the portrait width budget, and the Input
                        # Application Log uses the same technique for its Area cell.
                        #
                        # Without it a SPLIT FIELD renders as two rows both reading "2011" with
                        # different crops and nothing saying which ground each was on — the exact
                        # question 7 CFR 205.202 land history exists to answer.
                        # Cover crop folds into the same cell for the same width-budget
                        # reason — "Walnuts + cover: bell beans" is one land-use fact.
                        self._cell(
                            (f"{entry.crop_grown} ({entry.block_id})" if entry.block_id else entry.crop_grown)
                            + (f" + cover: {entry.cover_crop}" if entry.cover_crop else "")
                        ),
                        self._cell(entry.production_method_display or None),
                        self._cell(entry.substances_applied),
                        self._cell(_last_prohibited_input(entry)),
                        self._cell(entry.notes),
                    ]
                )

            col_widths = [
                0.45 * inch,  # Year
                1.1 * inch,  # Crop Grown
                0.9 * inch,  # Production Method
                1.8 * inch,  # Substances Applied
                1.0 * inch,  # Last Prohibited Substance
                1.5 * inch,  # Notes
            ]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)
            if any(e.is_derived for e in crop_history):
                elements.append(
                    Paragraph(
                        "* Compiled from the productions and inputs logged on this parcel in Trazo. "
                        "Unmarked years were entered by the operator as land-use history. A compiled "
                        "year never states a last prohibited input — that remains the operator's "
                        "attestation.",
                        self._styles["footer_note"],
                    )
                )

            # USDA's Field History form asks for "Material / Product Brand Name",
            # "Manufacturer" and "Application Date(s)" as three columns. The table above is
            # already 6.75in of the portrait budget, so per-year detail lines carry them —
            # the same treatment the manure and buffer sections use.
            #
            # Only structured rows appear here. `substances_applied` is prose and is NEVER
            # parsed into a manufacturer: guessing which word is a brand and which is a maker
            # would put a fabricated attribution into an eligibility determination.
            history_material_lines = []
            for entry in crop_history:
                _pch = entry.recorded
                rows = (
                    _pch.substance_applications
                    if _pch is not None and isinstance(getattr(_pch, "substance_applications", None), list)
                    else []
                )
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    material = _esc(row.get("material"), fallback="")
                    manufacturer = _esc(row.get("manufacturer"), fallback="")
                    dates = _esc(row.get("application_dates"), fallback="")
                    if not (material or manufacturer or dates):
                        continue
                    bits = [
                        b
                        for b in (material, manufacturer and f"mfr: {manufacturer}", dates and f"applied: {dates}")
                        if b
                    ]
                    history_material_lines.append(f"<b>{entry.year}:</b> " + "; ".join(bits))
            if history_material_lines:
                elements.append(self._spacer(0.06))
                elements.append(self._body("Materials by year — brand, manufacturer and application date(s):"))
                for line in history_material_lines:
                    elements.append(Paragraph("&bull; " + line, self._styles["footer_note"]))

        else:
            # --- Fallback: derive history from previous History objects on the same parcel ---
            elements.append(
                Paragraph(
                    "No structured crop history records found. Showing previous productions on "
                    "this parcel as a fallback.",
                    self._styles["footer_note"],
                )
            )
            elements.append(self._spacer(0.08))

            from history.models import History

            # PRIOR land use only. Without the published/date filters an unpublished developer
            # scratch production dated AFTER the audited season was printed under a
            # § 205.202 heading as this parcel's field history.
            prev_qs = (
                History.objects.filter(parcel=parcel, published=True)
                .exclude(pk=self.production.pk)
                .select_related("crop_type", "product")
            )
            # `start_date` is nullable. `filter(start_date__lt=None)` raises ValueError, which
            # would crash the whole certifier export for a production that has no start date —
            # so only apply the date bound when there is one to compare against.
            if self.production.start_date:
                prev_qs = prev_qs.filter(start_date__lt=self.production.start_date)
            prev_productions = list(prev_qs.order_by("-start_date")[:15])

            if prev_productions:
                fb_headers = [
                    "Start Date",
                    "Finish Date",
                    "Crop",
                    "Production Method",
                    "Harvest Amount",
                    "Lot ID",
                ]
                fb_header_row = [self._hdr(h) for h in fb_headers]
                fb_data = [fb_header_row]

                for prod in prev_productions:
                    crop_name = ""
                    try:
                        crop_name = (
                            prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                        )
                    except AttributeError:
                        pass

                    harvest = (
                        f"{_fmt_float(prod.production_amount)} {_val(prod.production_unit, '')}".strip()
                        if prod.production_amount
                        else None
                    )

                    fb_data.append(
                        [
                            self._cell(_fmt_date(prod.start_date)),
                            self._cell(_fmt_date(prod.finish_date)),
                            self._cell(crop_name),
                            self._cell(prod.get_production_method_display() if prod.production_method else None),
                            self._cell(harvest),
                            self._cell(prod.lot_id),
                        ]
                    )

                col_widths = [
                    0.75 * inch,
                    0.75 * inch,
                    1.2 * inch,
                    1.0 * inch,
                    1.0 * inch,
                    0.8 * inch,
                ]
                t = Table(fb_data, colWidths=col_widths, repeatRows=1)
                t.setStyle(self._base_table_style())
                elements.append(t)
            else:
                elements.append(self._body("No previous production records found on this parcel."))

        # --- Landowner affidavits (MOFGA FM-2024-20 canonical) — Sprint 5A ---
        # When someone other than the applicant managed the parcel during the
        # transition window, § 205.202(b) proof requires a signed affidavit. Surface
        # any on file here so the inspector doesn't have to hunt for them.
        from certifications.models import LandownerAffidavit

        affidavits = list(
            LandownerAffidavit.objects.filter(parcel=parcel).order_by("-last_prohibited_date", "-created_at")
        )
        if affidavits:
            elements.append(self._spacer(0.15))
            elements.append(self._body("<b>Landowner Affidavits (prior-manager attestation)</b>"))
            # "Last Prohibited Substance" used to head a column rendering
            # `last_prohibited_date`, so a certifier read "Last Prohibited Substance:
            # 2019-05-12". There is no substance NAME on this model \u2014 the affidavit records
            # the date \u2014 so the header is corrected rather than the value.
            #
            # "Management Period" and "Materials Declared" are USDA Land Use History
            # Verification columns. The period matters because without it a signer who
            # managed the land for one of three years reads as covering all three.
            aff_headers = [
                "Previous Manager",
                "Management Period",
                "Last Prohibited Application",
                "Materials Declared",
                "Signed Date",
                "Document",
            ]
            aff_data = [[self._hdr(h) for h in aff_headers]]
            contradictory = []
            for aff in affidavits:
                period_start = _fmt_date(aff.management_period_start) if aff.management_period_start else None
                period_end = _fmt_date(aff.management_period_end) if aff.management_period_end else None
                if period_start or period_end:
                    period = f"{period_start or '?'} \u2013 {period_end or '?'}"
                else:
                    period = "\u2014"
                # Three states, never two. An unanswered checkbox is NOT a declaration that
                # nothing was applied, and rendering it as one would manufacture the
                # \u00a7 205.202(b) attestation the eligibility determination rests on.
                # `yearly_history` is documented as [{year, land_use, inputs, applied_by,
                # manufacturer, date_applied}], but it is an unvalidated JSONField: a caller
                # that stored a prose STRING made `len()` count CHARACTERS, and this table
                # printed "CONTRADICTION — declared none, 56 year(s) listed" on a three-year
                # land-history affidavit. Count rows only when there are rows to count.
                history_rows = aff.yearly_history if isinstance(aff.yearly_history, list) else []
                # A land-use table is not an application record. USDA form #2 asks the signer
                # to tick "no materials applied" AND to fill in the 3-year land-use table, so
                # doing both is the form completed correctly — not a contradiction. It is only
                # a contradiction when a row actually NAMES something applied. Before this,
                # every correctly-filled affidavit on an organic operation drew a § 205.202(b)
                # REVIEW (six of them in one packet, 2026-08-21).
                rows_naming_an_input = [
                    row
                    for row in history_rows
                    if isinstance(row, dict)
                    and any(str(row.get(k) or "").strip() for k in ("inputs", "manufacturer", "date_applied"))
                ]
                if aff.declared_no_materials_applied() and rows_naming_an_input:
                    # The affidavit contradicts itself: a declaration of "none applied" over a
                    # table that lists applications. Printing only the declaration would hide
                    # the very rows a certifier needs, and printing only the rows would hide a
                    # signed statement. Show both and flag it — same treatment as the
                    # page-1/page-12 sales disagreement.
                    declared = f"CONTRADICTION — declared none, {len(rows_naming_an_input)} application(s) listed"
                    contradictory.append(aff)
                elif aff.declared_no_materials_applied():
                    declared = "None applied (declared)"
                elif history_rows:
                    declared = f"{len(history_rows)} year(s) listed"
                else:
                    declared = "Not answered"
                aff_data.append(
                    [
                        self._cell(aff.previous_manager_name or "\u2014"),
                        self._cell(period),
                        self._cell(_fmt_date(aff.last_prohibited_date)),
                        self._cell(declared),
                        self._cell(_fmt_date(aff.previous_manager_signed_date)),
                        self._cell("Attached" if aff.signed_document else "Not attached"),
                    ]
                )
            aff_t = Table(
                aff_data,
                colWidths=[1.4 * inch, 1.2 * inch, 1.1 * inch, 1.1 * inch, 0.8 * inch, 0.8 * inch],
                repeatRows=1,
            )
            aff_t.setStyle(self._base_table_style())
            elements.append(aff_t)

            # USDA form #2 asks the signer to describe the land they are attesting for —
            # "assessor's parcel number, county, township/section/range" — and to name the
            # landowner separately from the manager. Both were captured and NEITHER was
            # printed, so the packet showed an attestation without saying what land it covered
            # or who owned it. Rendered as detail lines rather than columns: the table is
            # already six wide, and these vary in length.
            #
            # NOT the same fact as Parcel.apn / section_township_range above. That is the
            # operation's own record of its land; this is what the SIGNER attested it to be,
            # and a mismatch between them is information a reviewer wants, not a duplicate.
            aff_detail_lines = []
            for aff in affidavits:
                bits = []
                if aff.parcel_legal_description:
                    bits.append("land as described by signer: " + _esc(aff.parcel_legal_description))
                if aff.landowner_name:
                    bits.append("landowner: " + _esc(aff.landowner_name))
                if aff.field_acres:
                    bits.append(f"{_esc(aff.field_acres)} acres")
                if not bits:
                    continue
                aff_detail_lines.append(f"<b>{_esc(aff.previous_manager_name)}:</b> " + "; ".join(bits))
            if aff_detail_lines:
                elements.append(self._spacer(0.06))
                for line in aff_detail_lines:
                    elements.append(Paragraph("&bull; " + line, self._styles["footer_note"]))
            if contradictory:
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] 7 CFR 205.202(b):</b> "
                        f"{len(contradictory)} affidavit(s) declare that no materials were applied "
                        "while also listing applications for the same period. A certifier cannot "
                        "rely on either statement until the signer resolves which is correct.",
                        self._warning_style(),
                    )
                )
            elements.append(self._spacer(0.06))
            elements.append(
                Paragraph(
                    "Attestation (standard wording per MOFGA FM-2024-20): "
                    f"\u201c{LandownerAffidavit.ATTESTATION_TEXT}\u201d",
                    self._styles["footer_note"],
                )
            )

        elements.append(self._spacer(0.1))
        elements.append(
            Paragraph(
                "USDA Organic (7 CFR 205.202) requires 36-month field history showing crops grown and "
                "substances applied. Add structured entries via the Parcel History section in the "
                "producer dashboard for a complete inspector-ready record.",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # SOE Compliance Status
    # ------------------------------------------------------------------

    # Module-level OSP_NARRATIVE_MATERIAL_FLOOR (= 400) is the single source of
    # truth; this class attribute aliases it for in-method convenience and
    # backward-compat with any external callers reading the class constant.
    OSP_NARRATIVE_MATERIAL_FLOOR = OSP_NARRATIVE_MATERIAL_FLOOR

    # Below this completeness ratio the PDF is stamped DRAFT — per CCOF/OEFFA practice,
    # an OSP with < 50% of required sections substantively filled is a Notice-of-Noncompliance
    # item, not a certification artifact.
    OSP_DRAFT_COMPLETENESS_THRESHOLD = 0.5

    # A ceiling that only a pathological paste can reach, not a real OSP section.
    #
    # 🔴 2026-08-19: this was 2400 characters, and the OSP section that a certifier reads is
    # printed under the heading "Section narratives — VERBATIM content filed with the
    # certifier". A perfectly ordinary plan blew straight through it: four of six sections on
    # a walnut orchard were cut mid-word ("Owl or raptor boxes …", "under §…", "district o…").
    # The code's own note says real per-section narratives run 150-500 words; the compiled
    # module answers alone exceed 2400 characters before the operator writes a line.
    #
    # The DoS concern behind the cap is real — a 500 KB paste would hang the renderer — so the
    # cap stays, at a size no genuine narrative reaches. And when it DOES fire the reader is
    # told, because a bare ellipsis in a compliance document reads as the end of the sentence
    # rather than the end of what was printed.
    NARRATIVE_RENDER_CEILING = 50_000

    # Certification types that put an operation under 7 CFR Part 205. Only these carry the
    # § 205.406 annual-continuation duty — a Non-GMO or GlobalG.A.P. certificate does not.
    # The members live in certifications.constants; this alias keeps the class attribute
    # that existing call sites read.
    NOP_CERTIFICATION_TYPES = _NOP_CERTIFICATION_TYPES

    def _safe_narrative(self, text: str, max_chars: int | None = None) -> str:
        """
        Escape narrative text for ReportLab Paragraph rendering.

        ReportLab's Paragraph parses XML-like markup (<b>, <br/>, <font>, ...). A
        farmer pasting `<script>`, `<onclick>`, or a stray `<` would either inject
        markup or crash PDF generation with a ParaFrag parse error. We escape all
        XML specials, then preserve paragraph breaks by converting `\n` -> `<br/>`.
        """
        import xml.sax.saxutils

        if not text:
            return ""
        limit = self.NARRATIVE_RENDER_CEILING if max_chars is None else max_chars
        if len(text) <= limit:
            body = text
        else:
            body = text[:limit] + (
                f"\n\n[TRUNCATED FOR PRINT — {len(text):,} characters filed, {limit:,} shown. "
                "The complete narrative is in the operation's Organic System Plan in Trazo.]"
            )
        escaped = xml.sax.saxutils.escape(body)
        return escaped.replace("\n", "<br/>")

    def _osp_section_status(self, narrative: str) -> str:
        """
        Three-tier status label for the summary table. Matches the validator
        thresholds used on Submit (views.py) so farmers see the same bar an
        inspector applies: EMPTY / BRIEF (insufficient) / COMPLETE.
        """
        length = len(narrative.strip())
        if length == 0:
            return "EMPTY"
        # "chars" is machine vocabulary in a column an inspector reads; the FIGURE is worth
        # keeping (it is what distinguishes a filled section from a one-line answer) but it
        # should read as prose and carry a thousands separator like every other number here.
        if length < self.OSP_NARRATIVE_MATERIAL_FLOOR:
            return f"BRIEF — {length:,} characters (insufficient)"
        return f"Complete — {length:,} characters"

    # Crops where the edible portion does NOT contact the soil. § 205.203(c)(1)(iii)
    # applies (90-day pre-harvest interval). Everything else falls back to (c)(1)(ii)
    # with 120 days (root crops, leafy greens, cucurbits, strawberries, melons).
    # Note: (c)(1)(i) covers land used for a crop not intended for human
    # consumption — out of scope for any Trazo production record.
    _NON_SOIL_CONTACT_CROP_KEYWORDS = (
        "avocado",
        "citrus",
        "orange",
        "lemon",
        "lime",
        "grapefruit",
        "mandarin",
        "tangerine",
        "apple",
        "pear",
        "cherry",
        "peach",
        "nectarine",
        "plum",
        "apricot",
        "mango",
        "papaya",
        "almond",
        "walnut",
        "pistachio",
        "pecan",
        "hazelnut",
        "grape",
        "wine",
        "olive",
        "fig",
        "pomegranate",
        "date",
        "persimmon",
    )

    def _manure_interval_rule_for_crop(self) -> dict:
        """
        Return the § 205.203(c)(1) sub-rule that applies to this production.

        Per eCFR 7 CFR 205.203(c)(1):
        (i)   land used for a crop not intended for human consumption.
        (ii)  120 days when the edible portion has direct contact with soil
              surface or soil particles (root crops, leafy greens, fruits
              growing on the ground).
        (iii) 90 days when the edible portion does NOT have direct contact
              with soil (tree fruits, tree nuts, elevated vine fruits).

        Defaults to (c)(1)(ii) / 120 days when crop type is unknown — the
        stricter human-consumption rule is always regulation-safe.
        """
        non_soil_contact = False
        try:
            crop = self.production.crop_type
            has_soil_contact_flag = getattr(crop, "has_soil_contact", None) if crop else None
            if has_soil_contact_flag is False:
                non_soil_contact = True
            else:
                crop_name = (crop.name if crop else "").lower()
                if any(k in crop_name for k in self._NON_SOIL_CONTACT_CROP_KEYWORDS):
                    non_soil_contact = True
        except Exception:
            non_soil_contact = False
        if non_soil_contact:
            return {"cite": "§ 205.203(c)(1)(iii)", "label": "90-day", "days": 90}
        return {"cite": "§ 205.203(c)(1)(ii)", "label": "120-day", "days": 120}

    # Regex patterns for narrative lint hints. Module-level-ish constants kept
    # inline so `_osp_narrative_lint_hints()` stays self-contained and fast to
    # audit for regulatory accuracy.
    _LINT_PRACTICE_CHANGE_KEYWORDS = (
        "material change",
        "activity change",
        "practice change",
        "procedure change",
        "change request",
        "change-request",
        "material/activity",
    )

    def _osp_narrative_lint_hints(self, narrative: str) -> list:
        """
        Scan farmer-authored OSP narrative for common regulatory miscitations.

        Returns a list of human-readable hints to render directly beneath the
        narrative in the PDF. Never rewrites the farmer's filing — verbatim
        content is preserved per § 205.201 filing practice — but inspectors
        and Trazo-side reviewers both benefit from Trazo flagging what a
        careful certifier-side reviewer would question.

        Three lint classes currently detected:
          1. § 205.400(f)(1) used in a "practice/activity change" context.
             (f)(1) governs application of a prohibited substance; (f)(2)
             governs operation changes. Very common miscitation.
          2. Self-imposed numeric SLA ("within 24 hours") against the
             regulation's "immediately" standard — creates a
             self-manufactured non-compliance trap.
          3. § 205.504 cited in producer-facing text. § 205.504 is
             certifier-side AMS accreditation evidence; producer duty under
             SOE is § 205.501(a)(21) (cooperation) + § 205.201(a)(3)
             (fraud-prevention / supplier-verification procedures).
        """
        import re

        if not narrative:
            return []
        hints = []
        lower = narrative.lower()

        if "205.400(f)(1)" in narrative and any(keyword in lower for keyword in self._LINT_PRACTICE_CHANGE_KEYWORDS):
            hints.append(
                "Regulatory hint: § 205.400(f)(1) governs the application of a "
                "prohibited substance. Changes in practices, procedures, or "
                "approved materials are governed by § 205.400(f)(2). Consider "
                "updating the citation in this section."
            )

        # Only flag "within N hours/days" SLAs that appear in proximity (~120
        # chars) to a certifier-notification / § 205.400(f) context — the
        # narrative often legitimately uses "within N days" to describe past
        # corrective-action windows ("corrected within 10 days") that carry
        # no regulatory SLA.
        sla_pattern = re.compile(
            r"(?:certifier|certifying agent|205\.400|notif(?:y|ied|ication))"
            r"[^\.]{0,120}?within\s+\d+\s+(?:hour|hr|day|business day|week)",
            re.IGNORECASE,
        )
        if sla_pattern.search(narrative):
            hints.append(
                "Regulatory hint: § 205.400(f) requires certifier notification "
                '"immediately." A self-imposed numeric SLA (e.g. "within 24 '
                'hours") in the OSP narrative can create an accidental '
                "non-compliance trap if notification slips past that deadline. "
                "The regulation defers to a reasonableness standard."
            )

        if "205.504" in narrative:
            hints.append(
                "Regulatory hint: § 205.504 describes evidence that certifying "
                "agents must submit to AMS for accreditation — it is not a "
                "producer duty. The producer-side supply-chain traceability "
                "audit duty is § 205.501(a)(21) (producer cooperation) in "
                "conjunction with § 205.201(a)(3) (fraud-prevention / "
                "supplier-verification procedures)."
            )

        return hints

    def _build_osp_reference_section(self):
        """
        Organic System Plan reference — 7 CFR 205.201.

        Shows the active OSP version for the establishment this production belongs
        to. Certifiers expect the audit export to cite the OSP it is supporting so
        they can cross-reference practices in the plan against the evidence in the
        report. If no OSP exists, we print a prominent "NOT ON FILE" warning —
        required per § 205.201.

        Renders each required § 205.201(a)(1)-(6) section's narrative verbatim
        after the summary table so inspectors can review substance, not just
        char counts (agent-2025 finding: summary-only presentation hides
        trivially short narratives).
        """
        from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan

        elements = [self._section_header("Organic System Plan (7 CFR 205.201)")]

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            elements.append(self._body("Farm data not available."))
            return elements

        active_osp = (
            OrganicSystemPlan.objects.filter(establishment=establishment, status="active")
            .order_by("-version_number")
            .first()
        )
        # Fall back to the most recent draft/submitted version if no active one — gives
        # inspectors something to review even for operations mid-certification.
        osp = active_osp or (
            OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
        )

        if osp is None:
            elements.append(
                Paragraph(
                    "<b>NO ORGANIC SYSTEM PLAN ON FILE.</b> "
                    "7 CFR 205.201 requires an OSP for every certified organic operation. "
                    "This operation has not yet filed one in Trazo. Evidence below is "
                    "audit-ready but cannot be cross-referenced to a master plan.",
                    self._warning_style(),
                )
            )
            return elements

        status_label = _osp_status_label(osp)
        effective = _fmt_date(osp.effective_date)
        submitted = _fmt_date(osp.submitted_at)
        approved = _fmt_date(osp.approved_at)
        template = osp.certifier_template_name or "\u2014"

        elements.append(self._label_value("Active Version", f"v{osp.version_number} ({status_label})"))
        elements.append(self._label_value("Effective Date", effective))
        elements.append(self._label_value("Submitted", submitted))
        elements.append(
            self._label_value("Approved by Certifier", approved if osp.approved_at else "Not recorded in Trazo")
        )
        elements.append(self._label_value("Certifier Template", template))

        # Recompute completion using the material floor (400 chars), not the model's
        # "any non-empty" check. This matches how an inspector reads the PDF.
        sections_data = osp.sections or {}

        def _section_is_material(key):
            narrative = (sections_data.get(key) or {}).get("narrative", "").strip()
            if len(narrative) < self.OSP_NARRATIVE_MATERIAL_FLOOR:
                return False
            # Length alone was gameable — see looks_like_padding above.
            return not looks_like_padding(narrative)

        material_section_hits = {k: _section_is_material(k) for k in OSP_SECTION_KEYS}

        # Registry Sync gate — narrative char-count alone is not enough. If the
        # § 205.201(a)(2) inputs narrative is long but the OSP's structured
        # approved-inputs registry has entries that are not referenced in the
        # narrative, the (a)(2) section reads as incomplete to an inspector
        # (Page-4 Registry Sync diff contradicts a "100% substantively filled"
        # Page-3 row otherwise). Demote (a)(2) to "incomplete" when there are
        # unreferenced registry entries; the detail table below will still
        # surface the actual gap count so the farmer knows what to reconcile.
        #
        # Load approved-inputs M2Ms ONCE here with order_by — the detail
        # tables below (~150 lines further down) reuse these same lists via
        # the alias names ``omri_products`` / ``nl_substances`` /
        # ``wsda_materials`` to avoid a second round of queries.
        omri_products = list(osp.approved_omri_products.all().order_by("product_name"))
        nl_substances = list(osp.approved_national_list_substances.all().order_by("substance_name"))
        wsda_materials = list(osp.approved_wsda_materials.all().order_by("brand_name"))
        inputs_narrative_text = (sections_data.get("inputs_list") or {}).get("narrative", "") or ""
        from certifications.services.plan_materials import plan_materials

        registry_sync_diff = _compute_registry_sync_diff(
            inputs_narrative=inputs_narrative_text,
            plan_rows=plan_materials(osp),
        )
        unreferenced_count = sum(1 for r in registry_sync_diff["registry_entries"] if not r["in_narrative"])
        if unreferenced_count > 0:
            material_section_hits["inputs_list"] = False

        material_completion = sum(1 for hit in material_section_hits.values() if hit) / len(OSP_SECTION_KEYS)
        completion_detail = f"{int(material_completion * 100)}% of § 205.201(a)(1)-(6) substantively filled"
        if unreferenced_count > 0:
            completion_detail += (
                f" — (a)(2) demoted: {unreferenced_count} registry entr"
                f"{'y' if unreferenced_count == 1 else 'ies'} not referenced in narrative"
            )
        elements.append(
            self._label_value(
                "Section Completion (material)",
                completion_detail,
            )
        )

        # DRAFT warning when the OSP is materially incomplete — per CCOF/OEFFA
        # Notice-of-Noncompliance templates (7 CFR 205.662(c)).
        if material_completion < self.OSP_DRAFT_COMPLETENESS_THRESHOLD:
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    "<b>DRAFT — NOT FOR CERTIFIER SUBMISSION.</b> "
                    "This OSP is materially incomplete and would not be accepted by an "
                    "accredited certifier. Per 7 CFR 205.662(c), an OSP missing required "
                    "§ 205.201(a) sections is grounds for a Notice of Noncompliance with "
                    "a 30-day cure window before proposed suspension.",
                    self._warning_style(),
                )
            )
        elements.append(self._spacer(0.12))

        # Section-by-section summary: shows inspectors that all six required
        # § 205.201(a) sections exist and how recently they were updated.
        headers = ["§ 205.201(a)", "Section", "Status", "Last Updated"]
        data = [[self._hdr(h) for h in headers]]
        section_labels = {
            "practices_procedures": ("(a)(1)", "Practices & Procedures"),
            "inputs_list": ("(a)(2)", "Inputs / Materials List"),
            "monitoring_plan": ("(a)(3)", "Monitoring & Fraud Prevention"),
            "recordkeeping_description": ("(a)(4)", "Recordkeeping System"),
            "commingling_barriers": ("(a)(5)", "Commingling Prevention"),
            "additional_certifier_info": ("(a)(6)", "Additional Certifier Info"),
        }
        for key in OSP_SECTION_KEYS:
            section = sections_data.get(key, {}) or {}
            narrative = (section.get("narrative") or "").strip()
            # `last_updated` is written by two different authors — the module compiler stamps a
            # full ISO-8601 datetime, the section editor stamps a plain date — and this printed
            # whichever it found, raw. The result in a certifier document was a column mixing
            # "2026-08-19" with "2026-08-20T00:47:01.9185" wrapped onto a second line as
            # "56+00:00". A date is what the reader needs; the microseconds are noise.
            last_updated = _osp_section_date(section.get("last_updated")) or "\u2014"
            cfr, label = section_labels.get(key, ("\u2014", key))

            # Status cell: char-count suffices UNLESS an additional signal
            # demotes the section (e.g. Registry Sync gate → (a)(2) gap).
            # Mirror the demotion inline so the table cell matches the
            # header and page-1 snapshot (avoid "Complete — 870 chars"
            # vs "(a)(2) demoted" contradiction).
            status_text = self._osp_section_status(narrative)
            if key == "inputs_list" and unreferenced_count > 0:
                status_text = (
                    f"{status_text} \u26a0 {unreferenced_count} registry "
                    f"entr{'y' if unreferenced_count == 1 else 'ies'} unreferenced"
                )
            data.append(
                [
                    self._cell(cfr),
                    self._cell(label),
                    self._cell(status_text),
                    self._cell(str(last_updated)),
                ]
            )

        t = Table(
            data,
            colWidths=[0.8 * inch, 2.4 * inch, 2.0 * inch, 1.3 * inch],
            repeatRows=1,
        )
        t.setStyle(self._base_table_style())
        elements.append(t)
        elements.append(self._spacer(0.15))

        # --- Full narratives per section (rendered verbatim) ------------------
        # Inspectors need to read the substance, not a char-count summary. We
        # XML-escape to protect against ReportLab Paragraph markup injection.
        # "Filed with the certifier" is only true of a submitted or active plan. The fallback
        # above prints the newest DRAFT when no plan has been filed, and this line said "filed"
        # about it — a claim the packet cannot support, on the one page a reviewer reads first.
        # Run 7 (R7-02c): "verbatim content filed with the certifier" was chosen by status alone.
        # Trazo holds no comparison between these narratives and what was filed, so it says what
        # the text is (held for this version) and names the submitted copy, if any, by hash.
        if osp.status in ("submitted", "active", "superseded"):
            narratives_lead = (
                f"<b>Section narratives</b> — as held in Trazo for v{osp.version_number}. This export does "
                "not compare them with the copy filed with the certifier."
            )
            submitted_copy = _stored_file_sha256(osp.submission_pdf)
            if submitted_copy is None:
                narratives_lead += (
                    " A copy generated when the plan was marked submitted is recorded in Trazo but could not "
                    "be read for this export."
                )
            elif submitted_copy:
                narratives_lead += (
                    f" The copy generated when the plan was marked submitted is held in Trazo "
                    f"(sha256 {submitted_copy}); it is not included in this export."
                )
            else:
                narratives_lead += " Trazo holds no copy generated at submission for this version."
        else:
            narratives_lead = (
                "<b>Section narratives</b> — as held in Trazo for the current draft (not yet filed with the "
                "certifier)."
            )
        elements.append(Paragraph(narratives_lead, self._styles["body"]))
        elements.append(self._spacer(0.08))

        for key in OSP_SECTION_KEYS:
            section = sections_data.get(key, {}) or {}
            narrative = (section.get("narrative") or "").strip()
            cfr, label = section_labels.get(key, ("\u2014", key))
            elements.append(
                Paragraph(
                    f"<b>{cfr} — {label}</b>",
                    self._styles["body"],
                )
            )
            if narrative:
                elements.append(Paragraph(self._safe_narrative(narrative), self._styles["body"]))
                # Lint hints surface regulatory-citation issues in the farmer's
                # verbatim text without rewriting it. Inspectors see the
                # farmer's filing AND Trazo's cautionary note — both are useful
                # signals. Lint is additive: absence = no detected issue, not
                # "this narrative is perfect."
                for hint in self._osp_narrative_lint_hints(narrative):
                    elements.append(
                        Paragraph(
                            f"<i>{hint}</i>",
                            self._styles["footer_note"],
                        )
                    )
            else:
                elements.append(
                    Paragraph(
                        "<i>(Section empty — will be flagged as non-compliant by certifier.)</i>",
                        self._styles["footer_note"],
                    )
                )
            elements.append(self._spacer(0.08))

        # --- Input materials on the plan. NOT "the scope the certifier approved":
        # nothing here records a certifier decision. Trazo resolves names against
        # OMRI / WSDA / the National List; approval is the agent's act. ------------
        # Inspectors reviewing the Inputs Not Matched to the Plan's Approved Inputs section (if
        # present) need to know what WAS approved so they can cross-reference
        # "this event references X, X is not in the approved list" against
        # the concrete list. Without this, an unapproved-input finding is
        # unfalsifiable.
        # NOTE: ``omri_products`` / ``nl_substances`` / ``wsda_materials`` were
        # loaded above for the Registry Sync gate — reused here to avoid a
        # second set of queries.
        elements.append(self._spacer(0.12))
        elements.append(
            Paragraph(
                "<b>Input materials on this plan (§ 205.201(a)(2))</b>",
                self._styles["body"],
            )
        )
        if not omri_products and not nl_substances and not wsda_materials:
            elements.append(
                Paragraph(
                    "<i>No structured inputs recorded on this OSP. Drift findings "
                    "(if any) are measured against the narrative § 205.201(a)(2) "
                    "text only.</i>",
                    self._styles["footer_note"],
                )
            )
        else:
            if omri_products:
                elements.append(
                    Paragraph(
                        f"<b>OMRI-listed products ({len(omri_products)})</b>",
                        self._styles["body"],
                    )
                )
                for p in omri_products:
                    omri_id = f" (OMRI #{p.omri_id})" if p.omri_id else ""
                    mfr = f" — {p.manufacturer}" if p.manufacturer else ""
                    elements.append(
                        Paragraph(
                            f"• {self._safe_narrative(p.product_name + omri_id + mfr)}",
                            self._styles["body"],
                        )
                    )
            if wsda_materials:
                elements.append(
                    Paragraph(
                        f"<b>WSDA Materials List ({len(wsda_materials)})</b>",
                        self._styles["body"],
                    )
                )
                for m in wsda_materials:
                    # Only a real WSDA Product # (a bare integer) is printable — see
                    # certifications.services.registry_identifiers. A fabricated
                    # `WSDA-REG-…` string used to print here as "(WSDA #…)", which a
                    # certifier can look up and will not find.
                    label = wsda_identifier_label(m.wsda_id)
                    wsda_id = f" ({label})" if label else ""
                    mfr = f" — {m.manufacturer}" if m.manufacturer else ""
                    cat = f" [{m.category}]" if m.category else ""
                    elements.append(
                        Paragraph(
                            f"• {self._safe_narrative(m.brand_name + wsda_id + mfr + cat)}",
                            self._styles["body"],
                        )
                    )
            if nl_substances:
                elements.append(
                    Paragraph(
                        f"<b>National List substances ({len(nl_substances)})</b>",
                        self._styles["body"],
                    )
                )
                for s in nl_substances:
                    if not s.is_national_list_entry:
                        cfr = " (nonsynthetic — no National List entry)"
                    else:
                        cfr = f" ({s.cfr_section})" if s.cfr_section else ""
                    elements.append(
                        Paragraph(
                            f"• {self._safe_narrative(s.substance_name + cfr)}",
                            self._styles["body"],
                        )
                    )

        # --- Registry Sync Status — narrative ↔ registry diff (P0-5) ----------
        # CCOF inspector will treat "narrative mentions 6 inputs but registry has 2"
        # as an incomplete § 205.201(a)(2) filing. Surface the diff inline so the
        # farmer can reconcile before the audit. The diff was already computed
        # above for the Registry Sync completeness gate — reuse it here.
        inputs_narrative = inputs_narrative_text
        sync = registry_sync_diff
        elements.append(self._spacer(0.12))
        elements.append(
            Paragraph(
                "<b>Registry Sync Status — narrative ↔ structured inputs</b>",
                self._styles["body"],
            )
        )
        if sync["registry_total"] == 0 and not inputs_narrative.strip():
            elements.append(
                Paragraph(
                    "<i>No inputs filed — neither narrative nor registry populated.</i>",
                    self._styles["footer_note"],
                )
            )
        elif sync["registry_total"] == 0:
            elements.append(
                Paragraph(
                    "<b>⚠ REVIEW:</b> § 205.201(a)(2) narrative is populated but no "
                    "structured inputs are on the OSP registry. Inspector may read "
                    "this as an incomplete filing. Add each input mentioned in the "
                    "narrative to the OSP page so drift detection has a concrete "
                    "baseline to check against.",
                    self._warning_style(),
                )
            )
        else:
            # Build a table: each registry entry × whether its name appears in narrative.
            sync_header = [
                self._hdr("Source"),
                self._hdr("Name"),
                self._hdr("In (a)(2) narrative?"),
            ]
            sync_rows = [sync_header]
            for row in sync["registry_entries"]:
                sync_rows.append(
                    [
                        self._cell(row["source"]),
                        self._cell(row["name"]),
                        self._cell("Yes" if row["in_narrative"] else "No — add to narrative"),
                    ]
                )
            sync_table = Table(
                sync_rows,
                colWidths=[1.0 * inch, 3.4 * inch, 2.1 * inch],
                repeatRows=1,
            )
            sync_table.setStyle(self._base_table_style())
            elements.append(sync_table)
            # Inline note if any registry entries are missing from narrative OR
            # narrative is long (>400 chars) yet registry is thin (<3 entries).
            missing_from_narrative = sum(1 for r in sync["registry_entries"] if not r["in_narrative"])
            if missing_from_narrative:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>⚠ {missing_from_narrative} registry entr"
                        f"{'y' if missing_from_narrative == 1 else 'ies'} "
                        "not referenced in the § 205.201(a)(2) narrative.</b> "
                        "Inspectors cross-check the narrative against the registry. "
                        "Update the narrative to describe every structured input.",
                        self._warning_style(),
                    )
                )
            elif (
                len(inputs_narrative.strip()) >= OSP_NARRATIVE_MATERIAL_FLOOR
                and sync["registry_total"] < REGISTRY_THIN_THRESHOLD
            ):
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        "<b>⚠ REVIEW:</b> § 205.201(a)(2) narrative is substantial "
                        f"({len(inputs_narrative.strip())} chars) but only "
                        f"{sync['registry_total']} structured input"
                        f"{'s' if sync['registry_total'] != 1 else ''} registered. "
                        "Verify every input mentioned in the narrative has a "
                        "corresponding OMRI / WSDA / National List entry on the OSP page.",
                        self._warning_style(),
                    )
                )

        # --- Approved inputs change log — § 205.400(f)(2) paper trail ----------
        # Adding/removing an approved input is a "change in a certified operation"
        # and falls under § 205.400(f)(2), not (f)(1). (f)(1) is the drift /
        # prohibited-substance-application notification; (f)(2) is the practice /
        # operation-change notification. Inspectors ask "when did you add Copper
        # hydroxide, and which certifier letter backs it?" — this table answers that.
        elements.append(self._spacer(0.12))
        elements.append(
            Paragraph(
                "<b>Change log — approved-inputs history (§ 205.400(f)(2))</b>",
                self._styles["body"],
            )
        )
        from certifications.models import ApprovedInputChangeLog

        change_logs = list(osp.approved_input_changes.all().select_related("changed_by"))
        if not change_logs:
            elements.append(
                Paragraph(
                    "<i>No recorded changes.</i>",
                    self._styles["footer_note"],
                )
            )
        else:
            # Wrap every cell in a Paragraph so long cert refs / product names
            # word-wrap inside the column width (ReportLab Tables do NOT wrap
            # raw-string cells — WORDWRAP is not a valid TableStyle command,
            # it's silently ignored. Only Paragraph/XPreformatted flowables
            # actually wrap inside a Table cell.) Also gives us free XML
            # escaping via _safe_narrative for any <, >, & in user input.
            cell_style = ParagraphStyle(
                "ChangeLogCell",
                parent=self._styles["body"],
                fontSize=7,
                leading=9,
            )
            header_style = ParagraphStyle(
                "ChangeLogHeader",
                parent=cell_style,
                fontName="Helvetica-Bold",
            )
            col_labels = ["Date", "Action", "Input", "Cert-notification ref", "By"]
            table_data = [[Paragraph(h, header_style) for h in col_labels]]
            for entry in change_logs:
                date_str = entry.changed_at.strftime("%Y-%m-%d") if entry.changed_at else "-"
                action_str = entry.get_action_display()
                input_name = entry.target_name_at_change or "-"
                cert_ref = (entry.change_notification_reference or "").strip() or "-"
                by_user = "-"
                if entry.changed_by is not None:
                    u = entry.changed_by
                    full = (f"{u.first_name} {u.last_name}").strip()
                    by_user = full or getattr(u, "email", "-")
                table_data.append(
                    [
                        Paragraph(date_str, cell_style),
                        Paragraph(self._safe_narrative(action_str), cell_style),
                        Paragraph(self._safe_narrative(input_name), cell_style),
                        Paragraph(self._safe_narrative(cert_ref), cell_style),
                        Paragraph(self._safe_narrative(by_user), cell_style),
                    ]
                )

            # Expressed in inches like every other table in this file, not in bare points.
            # These were [62, 48, 120, 160, 90] points (= 6.67in) — legal ReportLab, but the
            # width guard measures `* inch` and skipped this list, so it was outside the 7.00in
            # budget check entirely. Same totals, now verifiable.
            col_widths = [0.86 * inch, 0.67 * inch, 1.67 * inch, 2.22 * inch, 1.25 * inch]
            tbl = Table(table_data, colWidths=col_widths, repeatRows=1)
            tbl.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F5E9")),
                        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BDBDBD")),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                        ("LEFTPADDING", (0, 0), (-1, -1), 4),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            elements.append(tbl)

        # --- Notification of Changes (7 CFR 205.400(f) / NOP 2615 §3.4) ---
        # The ApprovedInputChangeLog above covers only input add/remove ((f)(2)).
        # NOP 2615 §3.4 requires notifying the certifier of six change categories,
        # including the (f)(1) IMMEDIATE prohibited-substance application. Surface
        # the full notification trail here so the certifier sees every reported change.
        from certifications.services.osp_module_pdf import lineage_change_notifications

        change_notifications = lineage_change_notifications(osp)
        elements.append(self._spacer(0.15))
        elements.append(self._body("<b>Notification of Changes (7 CFR 205.400(f) / NOP 2615)</b>"))
        elements.append(self._spacer(0.05))
        if not change_notifications:
            elements.append(
                self._body(
                    "No change notifications are on file for this plan or its earlier versions. If the "
                    "operation added/removed acreage, changed "
                    "a practice/input, applied or was contacted by a prohibited substance, or added a "
                    "new label/handling step, § 205.400(f) requires prior (or, for a prohibited-substance "
                    "application, immediate) notification to the certifier."
                )
            )
        else:
            cn_headers = ["Date", "Category", "CFR", "Description", "Method", "Certifier Ack."]
            cn_data = [[self._hdr(h) for h in cn_headers]]
            for cn in change_notifications:
                cn_data.append(
                    [
                        self._cell(_fmt_date(cn.date_notified) if cn.date_notified else None),
                        self._cell(
                            cn.get_change_category_display()
                            + ("" if cn.osp_id == osp.pk else f" (filed against v{cn.osp.version_number})")
                        ),
                        self._cell(cn.cfr_reference),
                        self._cell(cn.description),
                        self._cell(cn.get_method_display() if cn.method else None),
                        self._cell(
                            _fmt_date(cn.certifier_acknowledged_at) if cn.certifier_acknowledged_at else "Pending"
                        ),
                    ]
                )
            cn_widths = [0.7 * inch, 1.5 * inch, 0.85 * inch, 1.9 * inch, 0.6 * inch, 0.85 * inch]
            cn_tbl = Table(cn_data, colWidths=cn_widths, repeatRows=1)
            cn_tbl.setStyle(self._base_table_style())
            elements.append(cn_tbl)

            # § 205.400(f)(2) lets supporting documentation follow at the annual update rather
            # than accompany the notice, so WHICH of the two the operation chose is part of the
            # record. The panel collected `documentation_timing` and this table never printed
            # it — a compliance question the grower answered that reached no certifier. Ride it
            # as a detail line rather than a seventh column: the table is already 6.4in of the
            # portrait budget, and widening it would mean truncating Description, which is the
            # operator's own words.
            doc_lines = []
            for cn in change_notifications:
                bits = []
                if cn.documentation_timing:
                    bits.append(_esc(cn.get_documentation_timing_display()))
                if cn.supporting_document:
                    bits.append("document on file")
                if not bits:
                    continue
                label = _esc(_fmt_date(cn.date_notified) if cn.date_notified else None)
                doc_lines.append(f"<b>{label}:</b> " + "; ".join(bits))
            if doc_lines:
                elements.append(self._spacer(0.06))
                elements.append(self._body("Supporting documentation:"))
                for line in doc_lines:
                    elements.append(Paragraph("&bull; " + line, self._styles["footer_note"]))
            # Flag any (f)(1) prohibited-substance notification — the immediate-report category.
            immediate = [cn for cn in change_notifications if cn.is_immediate]
            if immediate:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] 7 CFR 205.400(f)(1): {len(immediate)} prohibited-substance "
                        f"application/drift notification(s) on file. These require IMMEDIATE certifier "
                        f"notification and may trigger a loss of organic status for the affected product.</b>",
                        self._warning_style(),
                    )
                )
                # The date is the only evidence the report WAS immediate. Recording the event
                # without it is deliberately allowed — a grower must be able to log drift before
                # they have phoned the certifier — so the gap is named HERE rather than refused
                # at entry, which would make the most urgent category the hardest to record.
                undated = [cn for cn in immediate if not cn.date_notified]
                if undated:
                    elements.append(self._spacer(0.05))
                    elements.append(
                        Paragraph(
                            f"<b>[REVIEW] 7 CFR 205.400(f)(1): {len(undated)} of those record no "
                            f"notification date. § 205.400(f)(1) requires the report to be made "
                            f"immediately, and the date is the only evidence of when it was. Record "
                            f"the date the certifier was notified for each.</b>",
                            self._warning_style(),
                        )
                    )

        # --- Annual Continuation / Update (7 CFR 205.406) ---
        # The annual update is a record distinct from the OSP version. Surface the most
        # recent one for this establishment so the certifier sees it was filed (previously
        # the OSP section queried OrganicSystemPlan only and never showed the update).
        from certifications.models import OSP_SECTION_KEYS, OSPAnnualUpdate

        # The update that matters to an inspector is the one covering the year under
        # review, not simply the newest on file. Showing a 2027 filing on a 2025
        # production report would misrepresent which year was actually reaffirmed.
        target_year = self.production.start_date.year if self.production.start_date else date.today().year
        # Run 7 (R7-02c): the newest `submitted_at` was taken with no regard to supersession or
        # withdrawal, so a superseded revision could be summarised as the year's filing. The
        # selection is now the packet's own (`packet_filing`): the current filed revision, else
        # the newest not yet filed; superseded and withdrawn revisions are listed, never chosen.
        from django.db.models import Q

        from certifications.services.annual_update_filing import (
            packet_filing,
            packet_revision_filename,
            renewal_packet_filing,
            year_revisions,
        )
        from certifications.services.osp_module_pdf import _agent_requested_sentence, _application_info_sentence

        est_updates = OSPAnnualUpdate.objects.filter(
            Q(establishment=establishment) | Q(prior_osp__establishment=establishment)
        ).distinct()

        def _year_filing(year):
            return packet_filing(est_updates.filter(reporting_year=year))

        annual = _year_filing(target_year)
        target_year_revisions = list(est_updates.filter(reporting_year=target_year).order_by("revision_number"))
        annual_is_fallback = False
        if annual is None and not target_year_revisions:
            for year in sorted(set(est_updates.values_list("reporting_year", flat=True)), reverse=True):
                annual = _year_filing(year)
                if annual is not None:
                    annual_is_fallback = True
                    break

        # A production cycle is not a calendar year. An overwintered crop — alliums, brassicas,
        # winter grain, strawberries — starts in October and finishes the following June, and
        # every record it made after 1 January was made under the NEXT year's reaffirmed plan.
        #
        # Selecting on `start_date.year` alone showed a certifier a packet of records running to
        # June 2026 under a § 205.406 section reaffirming only 2025, and said nothing about it.
        # It was silent precisely BECAUSE the start year had a filing: the fallback REVIEW below
        # only fires when nothing at all is on file. So the well-handled case hid the other one.
        end_year = self._last_covered_year(target_year)
        extra_year_rows = []
        for year in range(target_year + 1, end_year + 1):
            filed = _year_filing(year)
            extra_year_rows.append((year, filed))

        elements.append(self._spacer(0.15))
        elements.append(self._body("<b>Annual Continuation / Update (7 CFR 205.406)</b>"))
        elements.append(self._spacer(0.05))

        def _render_extra_years():
            # Spanning production: state the other calendar years it covers and whether each was
            # reaffirmed. A filing that exists is named with its date so the inspector can ask
            # for it; one that does not is a REVIEW, in the same words as the single-year case.
            for year, filed in extra_year_rows:
                if filed is not None:
                    elements.append(self._spacer(0.05))
                    elements.append(
                        self._body(
                            f"This production also covers {year}. The {year} annual update "
                            f"(§ 205.406) is on file"
                            + (f", submitted {filed.submitted_at.date().isoformat()}." if filed.submitted_at else ".")
                        )
                    )
                else:
                    elements.append(self._spacer(0.05))
                    elements.append(
                        Paragraph(
                            f"<b>[REVIEW] 7 CFR 205.406:</b> this production runs into {year}, "
                            f"but no annual update is on file for {year}. Records made after "
                            f"1 January {year} were kept under a plan that has not been "
                            "reaffirmed for that year.",
                            self._warning_style(),
                        )
                    )

        if annual is None and target_year_revisions:
            states = "; ".join(_revision_state(rev) for rev in target_year_revisions)
            elements.append(
                self._body(
                    f"No current {target_year} annual update (§ 205.406): every revision on file is withdrawn or "
                    f"superseded ({states})."
                )
            )
            # Review of back #111: this state used to fall through to the filing branch, which
            # carried the REVIEW and the spanning-year lines; it keeps both.
            elements.append(
                Paragraph(
                    f"<b>[REVIEW] 7 CFR 205.406:</b> no current annual update reaffirms the OSP for {target_year}.",
                    self._warning_style(),
                )
            )
            _render_extra_years()
        elif annual is None:
            # § 205.406(a) binds a CERTIFIED operation, and its first continuation is due on
            # the anniversary of the initial certification. An applicant who has never been
            # certified owes a § 205.401 application, not a continuation; a first-year
            # operation is not late until its first anniversary arrives. Firing REVIEW at
            # either of them is the cry-wolf pattern — amber is for something the grower can
            # act on today.
            from certifications.models import Certification as _NopCert

            nop_certs = list(
                _NopCert.objects.filter(
                    establishment=establishment,
                    certification_type__in=self.NOP_CERTIFICATION_TYPES,
                )
            )
            # A revoked or suspended operation is not a certified operation, so § 205.406
            # attaches to none of it. The DUTY is measured from the active certificates; the
            # prose below still distinguishes "never certified" from "certification not
            # currently active", because those are different things to tell a reader.
            active_certs = [c for c in nop_certs if c.is_active]
            first_effective = min(
                (c.effective_date for c in active_certs if c.effective_date),
                default=None,
            )
            first_due = None
            if first_effective is not None:
                try:
                    first_due = first_effective.replace(year=first_effective.year + 1)
                except ValueError:  # 29 Feb
                    first_due = first_effective.replace(month=3, day=1, year=first_effective.year + 1)

            if not nop_certs:
                elements.append(
                    self._body(
                        "No annual OSP update (§ 205.406) is on file, and no NOP certification is "
                        "recorded for this operation. § 205.406 binds a certified operation; an "
                        "operation seeking initial certification files the § 205.401 application "
                        "and its Organic System Plan, not a continuation. Once certified, an "
                        "annual update is due on each anniversary of the initial certification."
                    )
                )
            elif not active_certs:
                elements.append(
                    self._body(
                        "No annual OSP update (§ 205.406) is on file. No NOP certification is "
                        "currently active for this operation — see the Active Certification "
                        "Summary — and the annual continuation is a duty of a certified "
                        "operation."
                    )
                )
            elif first_due is not None and first_due > date.today():
                elements.append(
                    self._body(
                        f"No annual OSP update (§ 205.406) is on file. None is yet due: initial "
                        f"certification is effective {first_effective.isoformat()}, so the first "
                        f"annual continuation falls due on {first_due.isoformat()}."
                    )
                )
            else:
                elements.append(
                    self._body(
                        "No annual OSP update (§ 205.406) is on file. A certified operation must "
                        "submit an annual update each year reaffirming the OSP or describing changes."
                    )
                )
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] 7 CFR 205.406:</b> file the annual update / continuation so the "
                        "certifier can confirm the OSP was reviewed for the reporting year.",
                        self._warning_style(),
                    )
                )
        else:
            additions = annual.additions if isinstance(annual.additions, list) else []
            deletions = annual.deletions if isinstance(annual.deletions, list) else []

            # Per-section attestation (§ 205.201(a)(1)-(6) sections reaffirmed as unchanged).
            # Rendered explicitly so the inspector sees which sections the operator stands
            # behind rather than inferring it from a free-text summary.
            #
            # An un-attested section means "the operator did not affirm this section is
            # unchanged" — NOT "this section changed". Those are different claims and only
            # the first is supported by the data: a farmer who never opened the widget
            # leaves every section un-ticked. Labelling that as "changed" would put a
            # statement on a compliance document the operator never made.
            attestation = annual.sections_unchanged_attestation
            if not isinstance(attestation, dict):
                attestation = {}
            unchanged = [k for k in OSP_SECTION_KEYS if attestation.get(k)]
            not_attested = [k for k in OSP_SECTION_KEYS if not attestation.get(k)]

            def _fmt_sections(keys):
                return "; ".join(k.replace("_", " ").title() for k in keys) if keys else None

            if annual.submitted_at:
                elements.append(
                    self._body(
                        f"Summary of revision {annual.revision_number} of the {annual.reporting_year} annual update, "
                        "the current filed revision for that year. The complete filing is the document named in "
                        "the table."
                    )
                )
            else:
                # Review of back #111: `packet_filing` falls back to the newest unfiled revision,
                # which is a draft, not a filing.
                elements.append(
                    self._body(
                        f"Revision {annual.revision_number} of the {annual.reporting_year} annual update is a draft: "
                        "it has not been filed with the certifying agent."
                    )
                )
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] 7 CFR 205.406:</b> the {annual.reporting_year} annual update is not filed.",
                        self._warning_style(),
                    )
                )
            _in_packet = renewal_packet_filing(osp)
            if annual.filed_pdf is None:
                filed_document = "No frozen copy of this revision is held in Trazo."
            elif _in_packet is not None and _in_packet.reporting_year == annual.reporting_year:
                filed_document = (
                    f"{packet_revision_filename(annual)}, sha256 {annual.filed_sha256}. Not included in this "
                    f"dossier; it is in the renewal packet for v{osp.version_number}."
                )
            else:
                # Review of back #111: the renewal packet ships one year's revisions only.
                filed_document = (
                    f"{packet_revision_filename(annual)}, sha256 {annual.filed_sha256}. Not included in this "
                    "dossier, and not in the current renewal packet"
                    + (f", which carries the {_in_packet.reporting_year} filing" if _in_packet is not None else "")
                    + "; request it from the operation."
                )
            revision_label = str(annual.revision_number)
            if annual.corrects_id:
                revision_label += f", corrects revision {annual.corrects.revision_number}"
            annual_rows = [
                ("Reporting Year", str(annual.reporting_year) if annual.reporting_year else None),
                ("Revision", revision_label),
                ("Changes Summary", annual.changes_summary or "No changes — OSP reaffirmed"),
            ]
            # Both attestation rows are omitted entirely when the operator attested
            # nothing. Rendering "Sections Not Attested: <all six>" against a filing where
            # the question was never posed reads to an inspector as a finding, and an
            # empty "—" row is just noise.
            if unchanged:
                annual_rows.append(("Sections Attested Unchanged", _fmt_sections(unchanged)))
                annual_rows.append(("Sections Not Attested", _fmt_sections(not_attested)))
            annual_rows += [
                ("Additions", _fmt_change_entries(additions)),
                ("Deletions", _fmt_change_entries(deletions)),
                # The packet's own sentences (run 7b: "—" here while the filed revision stated no
                # changes to the application information).
                ("(a)(3) Application changes", _application_info_sentence(annual)),
                ("(a)(4) Agent-requested info", _agent_requested_sentence(annual)),
                (
                    "Signed",
                    (
                        (
                            f"{annual.signer_name or 'signer not named'}"
                            + (f", {annual.signer_title}" if annual.signer_title else "")
                            + f", {_fmt_date(annual.signed_at)}"
                        )
                        if annual.signed_at
                        else "Not signed in Trazo"
                    ),
                ),
                ("Signed content sha256", annual.signed_content_sha256 or None),
                ("Content held in Trazo", _held_content_hash_note(annual)),
                ("Filed document", filed_document),
                ("Submitted", annual.submitted_at.isoformat() if annual.submitted_at else None),
                (
                    "Certifier Acknowledged",
                    annual.certifier_acknowledged_at.isoformat() if annual.certifier_acknowledged_at else None,
                ),
            ]
            annual_data = [[self._hdr("Field"), self._hdr("Value")]]
            for label, value in annual_rows:
                annual_data.append([self._cell(label, 28), self._cell(_val(value))])
            annual_tbl = Table(annual_data, colWidths=[1.8 * inch, 4.2 * inch], repeatRows=1)
            annual_tbl.setStyle(self._base_table_style())
            elements.append(annual_tbl)
            others = [rev for rev in year_revisions(annual) if rev.pk != annual.pk]
            if others:
                elements.append(self._spacer(0.04))
                elements.append(
                    Paragraph(
                        f"Other revisions of the {annual.reporting_year} annual update: "
                        + "; ".join(_revision_state(rev) for rev in others)
                        + ".",
                        self._styles["footer_note"],
                    )
                )

            if annual_is_fallback:
                elements.append(self._spacer(0.05))
                elements.append(
                    Paragraph(
                        f"<b>[REVIEW] 7 CFR 205.406:</b> no annual update is on file for {target_year}, "
                        f"the year this production covers. The {annual.reporting_year} filing is shown "
                        "above for reference only and does not reaffirm the OSP for the year under review.",
                        self._warning_style(),
                    )
                )

            _render_extra_years()

        # This is the OSP section's CLOSING footnote — it annotates everything above it, and on
        # a live packet it landed alone at the top of page 8 while the § 205.406 block it
        # follows ended on page 7. A footnote separated from what it annotates says nothing.
        #
        # Bound to the preceding flowable only when that flowable is a Paragraph. Binding it to
        # a Table would be worse than the problem: KeepTogether would push the WHOLE table to
        # the next page to keep one line with it, turning a stranded footnote into half a blank
        # page. A table that runs long already splits itself sensibly.
        source_note = Paragraph(
            "Source: 7 CFR 205.201 (eCFR). Each evidence section of this report relates to practices "
            "described in the OSP above; whether the records meet them is for the certifier.",
            # spaceBefore replaces the Spacer that used to sit here: keepWithNext binds a
            # paragraph to the flowable IMMEDIATELY after it, and a Spacer in between would be
            # what gets kept, leaving the note free to break onto the next page anyway.
            ParagraphStyle("OspSourceNote", parent=self._styles["footer_note"], spaceBefore=0.1 * inch),
        )
        if elements and isinstance(elements[-1], Paragraph):
            # `keepWithNext` on the preceding paragraph, NOT a KeepTogether wrapper.
            #
            # KeepTogether would do the same job but it NESTS the flowables, and every helper
            # that walks a section's elements reading `.text` — the packet's own tests, and
            # anything future — silently stops seeing what is inside. That is worse than a
            # stranded footnote: a negative assertion ("this warning must NOT appear") would
            # start passing because the text became invisible rather than because it was
            # absent. Keeping the list flat keeps those readers honest.
            #
            # The style is CLONED: `_warning_style()` is cached and shared, and setting
            # keepWithNext on it would quietly bind every warning in the document to whatever
            # happens to follow it.
            previous = elements[-1]
            elements[-1] = Paragraph(
                previous.text,
                ParagraphStyle("OspTailKeepWithNext", parent=previous.style, keepWithNext=1),
            )
            elements.append(source_note)
        else:
            elements.append(self._spacer(0.1))
            elements.append(source_note)
        return elements

    def _build_drift_findings_section(self):
        """
        OSP ↔ events drift — 7 CFR 205.400(f)(2).

        Lists every ChemicalEvent and SoilManagementEvent on this production
        whose input is not in the establishment's active OSP approved_inputs
        set. An input used that is not on the OSP approved-inputs list is a
        *change in a certified operation* under § 205.400(f)(2), triggering
        the producer's change-notification obligation. (f)(1) is reserved for
        the actual application of a prohibited substance — a distinct and
        more severe finding this section does not represent.)

        Sprint 5.1 (drift detector): post_save signals on ChemicalEvent /
        SoilManagementEvent populate `drift_warning` JSONB on the event; this
        section materializes that data at audit-export time.
        """
        from history.models import ChemicalEvent, ProductionEvent, SoilManagementEvent

        # Section name deliberately avoids the word "Drift" in isolation. In
        # NOP usage "drift" is the term of art for external contamination
        # from adjacent land (governed by § 205.400(f)(1)). Internal
        # application of an input not on the OSP approved-inputs list is a
        # *practice change* under § 205.400(f)(2) — a distinct finding.
        # Labeling internal unapproved-material use as "Drift" confuses the
        # audit trail; we call it what the rule calls it.
        history_id = getattr(self.production, "id", None)

        # Branch wording on OSP presence so the prose never claims cross-
        # reference against an "active OSP" when none is on file. Drift
        # signal still resolves against the establishment-level approved-
        # inputs registry; the OSP-narrative master plan is what's missing.
        from certifications.models import OrganicSystemPlan

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            establishment = None
        # NOT "does an OSP row exist" — "is there an approved-inputs set to match
        # against". A draft OSP with zero structured inputs made every comparison
        # vacuously true, and this section then reported "No drift findings. Every
        # chemical input ... matched an entry on the establishment's active OSP
        # approved-inputs list" while page 2 of the same PDF said the OSP was 0%
        # filled and the OMRI table said an input was "Listed — not on OSP".
        # An empty set cannot clear anything.
        #
        # 🔴 2026-09-06 — the variable was named `active_osp` and had NO status filter, so a
        # DRAFT plan with approved inputs satisfied `osp_on_file` and this section printed
        # "No drift findings … matched an entry on the establishment's active OSP
        # approved-inputs list". The detector never ran against that plan:
        # `_active_osp_for_establishment` requires status="active" and `_evaluate` CLEARS any
        # existing drift_warning when there is none. Zero findings meant zero comparisons, and
        # the packet named an active OSP that did not exist. Do not loosen the detector's gate
        # to match — filter here, and say plainly when the check could not run.
        #
        # 🔴 2026-09-07 — this now asks the DETECTOR which plan it used, instead of repeating
        # the rule. `_osp_for_drift` falls back to the newest DRAFT when no plan is active, so
        # a first-renewal farm — the cohort that cannot have an active plan until AFTER the
        # renewal it is preparing — gets a real comparison, reported as PROVISIONAL. Two
        # copies of "which plan counts" is how page 1 and this body diverged before; there is
        # one copy now, and it is the one that wrote the findings.
        from certifications.services.drift_detector import _osp_for_drift

        active_osp = None
        provisional_plan = False
        inactive_osp_count = 0
        osp_on_file = False
        if establishment is not None:
            active_osp, provisional_plan = _osp_for_drift(establishment.id)
            if active_osp is None:
                inactive_osp_count = OrganicSystemPlan.objects.filter(establishment=establishment).count()
            if active_osp is not None:
                # All four sources, through the one reader — a WSDA-only or operator-entered
                # list is a list.
                from certifications.services.plan_materials import plan_materials

                osp_on_file = bool(plan_materials(active_osp))

        # 🔴 The heading is part of the claim, and it was hardcoded to § 205.400(f)(2). For a
        # PROVISIONAL result that is the wrong regulation in the most prominent position on the
        # section — the body can be scrupulous underneath and a certifier still reads the title.
        # Built here rather than at the top of the function because it has to know which plan
        # the comparison used.
        if provisional_plan:
            elements = [
                self._section_header(
                    "Unlisted Inputs \u2014 Draft Plan Completeness (7 CFR 205.201(a)(2)) \u2014 PROVISIONAL"
                )
            ]
        else:
            elements = [
                self._section_header(
                    "Inputs Not Matched to the Plan's Approved Inputs \u2014 OSP Practice Change (7 CFR 205.400(f)(2))"
                )
            ]

        if history_id is None:
            elements.append(self._body("Production data not available."))
            return elements

        # `self.production` is the History row (naming is historical). Events
        # link to it via CommonEvent.history, so a single-hop filter covers
        # every ChemicalEvent / SoilManagementEvent / planting ProductionEvent
        # on this production cycle. ProductionEvent drift_warning is populated
        # only on Planting (type='PL') subtypes per § 205.204.
        chem_drift = list(
            ChemicalEvent.objects.filter(history_id=history_id, drift_warning__isnull=False).order_by("date")
        )
        soil_drift = list(
            SoilManagementEvent.objects.filter(history_id=history_id, drift_warning__isnull=False).order_by("date")
        )
        seed_drift = list(
            ProductionEvent.objects.filter(history_id=history_id, type="PL", drift_warning__isnull=False).order_by(
                "date"
            )
        )

        # § 205.105 prohibited-input check, independent of the drift detector.
        # The detector matches against the approved-inputs registry; it says nothing
        # about an input the FARMER already labelled conventional-only. Those were
        # rendering in the input log as "Not Organic Approved - Conventional use
        # only" while this section reported no findings on the same production.
        prohibited_inputs = []
        if str(getattr(self.production, "production_method", "") or "").lower() == "organic":
            # Soil amendments carry the same ORGANIC_APPROVED choices as chemicals
            # (7 CFR 205.203(b)); checking only ChemicalEvent let a prohibited
            # amendment through untouched.
            prohibited_inputs = list(
                ChemicalEvent.objects.filter(
                    history_id=history_id, organic_approved__in=("not_organic", "no")
                ).order_by("date")
            ) + list(
                SoilManagementEvent.objects.filter(
                    history_id=history_id, amendment_organic_approved__in=("not_organic", "no")
                ).order_by("date")
            )

        if prohibited_inputs:
            elements.append(
                Paragraph(
                    "<b>[NON-CONFORMANCE] Conventional-only inputs applied to an organic "
                    f"production.</b> {len(prohibited_inputs)} input(s) below are recorded by the "
                    "operator as not approved for organic use. Under 7 CFR 205.105 an organic crop "
                    "may not be produced with a prohibited substance, and § 205.202(b) requires the "
                    "land to have had no prohibited substance applied for 36 months before harvest. "
                    "Resolve with the certifier before submission.",
                    self._warning_style(),
                )
            )
            rows = [[self._hdr(h) for h in ("Date", "Product", "Type", "Recorded Organic Status")]]
            for ev in prohibited_inputs:
                is_soil = isinstance(ev, SoilManagementEvent)
                product = getattr(ev, "amendment_type", None) if is_soil else ev.commercial_name
                kind = "Soil amendment" if is_soil else (ev.get_type_display() if ev.type else None)
                status_field = "amendment_organic_approved" if is_soil else "organic_approved"
                status = None
                if getattr(ev, status_field, None):
                    status = getattr(ev, f"get_{status_field}_display")()
                rows.append(
                    [
                        self._cell(_fmt_date(ev.date)),
                        self._cell(product),
                        self._cell(kind),
                        self._cell(status),
                    ]
                )
            t = Table(rows, colWidths=[0.9 * inch, 2.6 * inch, 1.2 * inch, 2.3 * inch], repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)
            elements.append(self._spacer(0.1))

        if not chem_drift and not soil_drift and not seed_drift:
            if prohibited_inputs:
                # Never print "no findings" on a production that just failed § 205.105.
                summary_body = (
                    "<b>No additional approved-inputs-registry findings.</b> Beyond the "
                    "non-conformance above, no further input resolved outside the "
                    "approved-inputs registry or \u00a7 205.204 seed documentation."
                )
                summary_note = (
                    "The prohibited-input non-conformance above is assessed under 7 CFR "
                    "205.105 from the operator's own recorded organic status, independently "
                    "of the approved-inputs registry comparison."
                )
            elif osp_on_file and provisional_plan:
                # PROVISIONAL: measured against a DRAFT plan, which is what a first-renewal
                # operation has. Real comparison, real result — but nothing has been filed, so
                # it must not be spoken as conformance with an approved plan, and § 205.400(f)(2)
                # (notify your certifier of a change) does not apply to a plan no certifier
                # has seen.
                summary_body = (
                    "<b>No unlisted inputs — measured against a DRAFT plan.</b> Every chemical "
                    "input, soil amendment, and planting-event seed source logged during this "
                    "production cycle matched an entry on the operation's draft OSP "
                    "approved-inputs list and § 205.204 seed documentation requirements."
                )
                summary_note = (
                    "This operation has no ACTIVE Organic System Plan, so the comparison was "
                    "made against its most recent draft. That is a provisional result about "
                    "the completeness of the plan's own input list under 7 CFR 205.201(a)(2), "
                    "not a statement of conformance with a certifier-approved plan. Once the "
                    "plan is approved and activated, every event is re-evaluated against it."
                )
            elif osp_on_file:
                summary_body = (
                    "<b>No drift findings.</b> Every chemical input, soil amendment, "
                    "and planting-event seed source logged during this production "
                    "cycle matched an entry on the farm's active OSP "
                    "approved-inputs list and § 205.204 seed documentation requirements."
                )
                summary_note = (
                    "Inputs are cross-checked against the approved National List substances "
                    "and approved OMRI products on the active OSP, at the moment each event "
                    "is saved. 7 CFR 205.400(f)(2) requires producers "
                    "to notify their certifying agent of any change in practices or "
                    "procedures that may affect the organic status of the operation."
                )
            elif active_osp is None:
                # Distinct from the empty-list case below: there we HAVE a plan and it
                # names nothing; here the comparison never ran at all, because the
                # detector only evaluates against an ACTIVE plan.
                draft_clause = (
                    f" ({inactive_osp_count} plan version(s) are on file in draft, " "submitted or superseded state)"
                    if inactive_osp_count
                    else " (no Organic System Plan of any status is on file)"
                )
                summary_body = (
                    "<b>[REVIEW] Approved-input conformance was NOT CHECKED.</b> "
                    "This operation has no ACTIVE Organic System Plan"
                    + draft_clause
                    + ", and the approved-inputs comparison runs only against an active "
                    "plan. No chemical input, soil amendment or seed source logged during "
                    "this production cycle was compared against anything, so this section "
                    "reports no verdict — clean or otherwise. This is an absence of "
                    "evidence, NOT a clean result. Activate the operation's OSP so the "
                    "check can run."
                )
                summary_note = (
                    "Inputs are cross-checked against the approved National List substances, "
                    "OMRI products and WSDA materials on the ACTIVE OSP, at the moment each "
                    "event is saved. With no active plan the detector records nothing, and "
                    "clears any finding it had written against a plan that is no longer "
                    "active — which is why an empty findings table here means unchecked, not "
                    "clear. 7 CFR 205.400(f)(2) requires producers to notify their certifying "
                    "agent of any change in practices or procedures that may affect the "
                    "organic status of the operation."
                )
            else:
                summary_body = (
                    "<b>[REVIEW] Approved-input conformance could not be evaluated.</b> "
                    "No approved-inputs list is on file for this operation — neither the "
                    "OSP § 205.201(a)(2) material list nor the farm registry "
                    "contains any entry — so there is nothing for the inputs used on this "
                    "production to be checked against. This is an absence of evidence, "
                    "NOT a clean result. File the OSP material list so this section can "
                    "report a real conformance verdict."
                )
                summary_note = (
                    "Inputs are cross-checked against the approved National List substances "
                    "and approved OMRI products on the OSP, at the moment each event is saved. "
                    "With both lists empty "
                    "every comparison passes vacuously, which is why no verdict is "
                    "reported here. 7 CFR 205.400(f)(2) requires producers to notify "
                    "their certifying agent of any change in practices or procedures that "
                    "may affect the organic status of the operation."
                )
            elements.append(Paragraph(summary_body, self._styles["body"]))
            elements.append(self._spacer(0.05))
            elements.append(Paragraph(summary_note, self._styles["footer_note"]))
            # 🔴 2026-09-06 — this branch used to `return` here, BEFORE the OMRI
            # reference-subset disclaimer and the catalog-freshness stamp. The clean
            # verdict — the one a certifier most readily accepts — was the only one
            # that carried no statement of what it had been measured against.
            elements.extend(self._drift_reference_scope_notes(has_findings_table=False))
            return elements

        if osp_on_file and provisional_plan:
            # The same detection, a different regulation and a different instruction. Telling a
            # first-renewal grower to file a § 205.400(f)(2) change notice about a plan their
            # certifier has never seen would be an instruction they cannot carry out.
            findings_warning = (
                "<b>PROVISIONAL — the events listed below reference inputs that are not yet on "
                "this operation's DRAFT approved-inputs list.</b> No plan has been filed, so "
                "this is not a § 205.400(f)(2) change notification. Under 7 CFR 205.201(a)(2) "
                "the Organic System Plan must list each substance used as a production input: "
                "add each input below to the plan before submitting it, or remove the practice. "
                "These findings are re-evaluated automatically once the plan is approved and "
                "activated."
            )
        elif osp_on_file:
            findings_warning = (
                "<b>The events listed below reference inputs not present on the "
                "active OSP's approved-inputs registry at event save-time.</b> "
                "Per 7 CFR 205.400(f)(2), the producer must notify the certifier "
                "of any change in practices or procedures that may affect the "
                "organic status of the operation. Add the input to the OSP "
                "(if approved), or document the change-notification filing "
                "submitted to the certifier."
            )
        else:
            findings_warning = (
                "<b>The events listed below reference inputs not present on the "
                "farm's approved-inputs registry at event save-time, "
                "and no ACTIVE Organic System Plan is on file to cross-reference "
                "(a draft or superseded plan is not evaluated).</b> "
                "Per 7 CFR 205.400(f)(2), the producer must notify the certifier "
                "of any change in practices or procedures that may affect the "
                "organic status of the operation. File the OSP and add each "
                "input below to the OSP approved-inputs list, or document the "
                "change-notification filing submitted to the certifier."
            )
        elements.append(Paragraph(findings_warning, self._warning_style()))
        elements.append(self._spacer(0.05))

        headers = ["Event Date", "Event Type", "Input", "Reason", "Resolution", "Looked up (local copy)"]
        # 7.00in exactly — was 7.05in, five hundredths into the right margin.
        col_widths = [0.75 * inch, 0.95 * inch, 1.4 * inch, 1.9 * inch, 1.15 * inch, 0.85 * inch]

        def _format_verified_cell(dw):
            """Render per-catalog lookup timestamps as a compact string.

            ReportLab's ``Paragraph`` treats raw ``\\n`` as whitespace, and
            ``_cell`` XML-escapes ``<`` / ``>`` (so ``<br/>`` would leak
            through as literal text). Fall back to a ``' · '`` separator
            which wraps naturally inside the column.

            Legacy drift findings (written before per-finding timestamping)
            lack these keys and render as ``—`` so we never fabricate a
            verification date the system does not actually have on file.
            """
            labels = [
                ("omri_verified_at", "OMRI"),
                ("wsda_verified_at", "WSDA"),
                ("national_list_verified_at", "NL"),
                ("cdfa_oim_verified_at", "CDFA"),
            ]
            parts = []
            for key, label in labels:
                stamp = dw.get(key)
                if not stamp:
                    continue
                try:
                    # "2026-04-16T14:02:11.123456+00:00" → "2026-04-16 14:02Z"
                    date_part, time_part = stamp.split("T", 1)
                    hhmm = time_part[:5]
                    parts.append(f"{label} {date_part} {hhmm}Z")
                except Exception:
                    parts.append(f"{label} {stamp[:16]}")
            if not parts:
                return "\u2014"
            return " \u00b7 ".join(parts)

        def _row_from(event, event_type_label):
            dw = event.drift_warning or {}
            resolution = dw.get("resolved_via") or "\u2014"
            resolution_label = {
                "omri": "OMRI lookup",
                "wsda": "WSDA Materials List",
                "national_list": "National List lookup",
                "unresolved": "Name match only (unresolved)",
                # Phase 2 — seed source findings (§ 205.204).
                "seed_certification_missing": "Seed certification not documented",
                "seed_search_incomplete": "Commercial-availability search incomplete",
                "seed_treated_prohibited": "Treated seed — confirm with certifier",
            }.get(resolution, resolution)

            # Phase 1 additive fields — inline " · " separators (not "\n")
            # because _cell escapes <br/> and a raw "\n" inside a ReportLab
            # Paragraph does not produce a line break. Single-line renders
            # cleanly and Paragraph will word-wrap naturally.
            extras = []
            cdfa = dw.get("cdfa_oim_status") or {}
            cdfa_status = cdfa.get("status")
            if cdfa_status == "registered":
                # No number, ever. CDFA's published Registered OIM Products list has
                # three columns — Firm, Product Name, Annotations — and no identifier,
                # so the `[CA: CDFA OIM CDFA-OIM-DTE-FM]` this used to print was a
                # Trazo invention presented as a state registration number.
                extras.append(f"[CA: {CDFA_OIM_REGISTERED_LABEL}]")
            elif cdfa_status in ("unknown", "missing"):
                # "missing" is a LEGACY value: until 2026-09-06 it was the default for
                # any product simply absent from Trazo's 17-row CDFA reference set, and
                # it printed as "[CA: CDFA OIM missing]" — an assertion that the operator
                # broke California law, from a file that covers a fraction of the list.
                # Both values render as what we actually know: nothing.
                extras.append("[CA: CDFA OIM not checked — not in Trazo's reference set]")
            dpr = dw.get("ca_dpr_permit_status") or {}
            if dpr.get("status") == "missing":
                extras.append("[CA DPR permit missing]")
            elif dpr.get("status") == "expired":
                extras.append(f"[CA DPR permit #{dpr.get('permit_number')} expired {dpr.get('expires')}]")
            elif dpr.get("status") == "present" and dpr.get("permit_number"):
                county_part = f" ({dpr['county']})" if dpr.get("county") else ""
                extras.append(f"[CA DPR permit #{dpr['permit_number']}{county_part}]")
            if resolution == "unresolved" and dw.get("omri_search_url"):
                extras.append(f"Search: {dw['omri_search_url']}")
            resolution_cell = resolution_label
            if extras:
                resolution_cell = resolution_label + " · " + " · ".join(extras)

            return [
                self._cell(_fmt_date(event.date)),
                self._cell(event_type_label),
                self._cell(dw.get("input_label") or "(unknown)"),
                self._cell(dw.get("reason") or "\u2014"),
                self._cell(resolution_cell),
                # "Verified" column — up to 4 catalog timestamps joined with
                # " · " so a 120-char cap is right-sized (allows word-wrap
                # without truncating any individual stamp).
                self._cell(_format_verified_cell(dw)),
            ]

        data = [[self._hdr(h) for h in headers]]
        for e in chem_drift:
            data.append(_row_from(e, f"Chemical / {e.get_type_display() or ''}"))
        for e in soil_drift:
            data.append(_row_from(e, f"Soil / {e.get_type_display() or ''}"))
        for e in seed_drift:
            data.append(_row_from(e, f"Planting / {e.get_type_display() or ''}"))

        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        # Legend for the "Verified" column — the abbreviations ("OMRI", "WSDA",
        # "NL", "CDFA") and the timestamp format are cryptic otherwise. Placing
        # the legend immediately beneath the table keeps it paired with the
        # column whether or not the table breaks across pages.
        elements.append(self._spacer(0.04))
        elements.append(
            Paragraph(
                "<b>Looked up column legend.</b> When each catalog was looked up in "
                "Trazo's local copy for this finding, at event save-time. It is not a "
                "check that a listing is current: see the catalog freshness line below. "
                "Sanitizers are not checked against the plan in this section; the OSP "
                "Materials List workbook shows their identity status. Abbreviations: "
                "<b>OMRI</b> = OMRI product catalog; <b>WSDA</b> = Washington "
                "State Department of Agriculture Organic Materials List; "
                "<b>NL</b> = USDA National List of Allowed and Prohibited "
                "Substances (7 CFR 205.600-606); <b>CDFA</b> = California "
                "Department of Food and Agriculture Organic Input Materials "
                "(CA-only). Timestamps render as "
                "<i>CATALOG YYYY-MM-DD HH:MMZ</i> in UTC. A dash ("
                "\u2014) means the finding pre-dates per-lookup timestamping.",
                self._styles["footer_note"],
            )
        )

        elements.append(self._spacer(0.06))
        elements.append(
            Paragraph(
                "Drift detector compares event inputs against the active OSP's "
                "approved_national_list_substances, approved_omri_products, and "
                "approved_wsda_materials sets. An empty resolution column means "
                "the input name could not be matched to any local catalog; in "
                "that case Trazo provides a deep-link into omri.org so the "
                "farmer can verify manually. California farms also get "
                "an inline CDFA OIM registration check on fertilizer / amendment "
                "inputs — a product Trazo holds as registered is marked "
                "“CDFA OIM registered” (CDFA publishes no registration number, so "
                "none is shown), and a product absent from Trazo’s CDFA reference "
                "set is reported as not checked rather than as unregistered. The "
                "farmer should reconcile with the certifier before "
                "the next annual update (§ 205.406).",
                self._styles["footer_note"],
            )
        )

        elements.extend(self._drift_reference_scope_notes(has_findings_table=True))

        return elements

    def _drift_reference_scope_notes(self, *, has_findings_table):
        """The two statements that must accompany EITHER drift verdict.

        The OMRI reference-subset disclaimer and the catalog-freshness stamp say what
        the comparison was made against. That matters MORE on a no-findings verdict
        than on a findings one: "nothing was found" reads as "nothing is there" unless
        the reader is told how much of the reference material Trazo actually holds.
        Both branches of the section call this; neither may skip it.
        """
        out = [self._spacer(0.08)]
        if has_findings_table:
            disclaimer = (
                "<b>OMRI reference subset — read before relying on findings above.</b> "
                "This report cross-references inputs against a curated OMRI reference "
                "subset maintained by Trazo. <b>OMRI (omri.org) is the authoritative "
                "database of record.</b> For any input shown as \u201cunresolved\u201d in the "
                "table above, use the embedded OMRI search link to verify against the "
                "full OMRI listing before approving or rejecting. A full-coverage OMRI "
                "Certifier Subscription is on the Trazo roadmap."
            )
        else:
            disclaimer = (
                "<b>OMRI reference subset — read before relying on the result above.</b> "
                "This report cross-references inputs against a curated OMRI reference "
                "subset maintained by Trazo, not the full OMRI listing, and against a "
                "partial copy of the WSDA Organic Input Material List and the CDFA "
                "Registered OIM list. <b>OMRI (omri.org), WSDA and CDFA are the "
                "authoritative databases of record.</b> A result of no findings means no "
                "input resolved outside the reference material Trazo holds; it is not a "
                "statement about the full listings. A full-coverage OMRI Certifier "
                "Subscription is on the Trazo roadmap."
            )
        out.append(Paragraph(disclaimer, self._warning_style()))

        # Catalog freshness stamp — says when the reference material above was last
        # refreshed, and names any catalog whose last sync attempt failed or never ran.
        freshness_line = self._catalog_freshness_line()
        if freshness_line:
            out.append(self._spacer(0.05))
            out.append(Paragraph(freshness_line, self._styles["footer_note"]))
        return out

    # An IngestionRun status that means the catalog actually loaded. "error" and
    # "skipped" do not, and until 2026-09-06 this line filtered on NOTHING — a
    # failed run printed as a sync, so a 404 from eCFR read as "National List
    # (eCFR) 2026-09-05" on the packet.
    _CATALOG_SYNC_OK_STATUSES = ("ok", "changed", "unchanged")

    def _catalog_freshness_line(self):
        """One-line summary of when each input catalog was last SUCCESSFULLY refreshed.

        Auditor-facing: proves Trazo checks the live regulation on a schedule rather
        than relying on a stale seed. A catalog whose last attempt failed, or that has
        never been synced, is NAMED — dropping it silently would leave the reader to
        assume the ones listed are the whole story.
        """
        try:
            from certifications.models import IngestionRun
        except ImportError:  # pragma: no cover — defensive
            return ""

        labels = {
            "omri": "OMRI",
            "wsda": "WSDA",
            "cdfa_oim": "CDFA OIM",
            "national_list_ecfr": "National List (eCFR)",
        }
        synced = []
        problems = []
        for source, label in labels.items():
            runs = IngestionRun.objects.filter(source=source).order_by("-ran_at")
            latest = runs.first()
            latest_ok = runs.filter(status__in=self._CATALOG_SYNC_OK_STATUSES).first()
            if latest_ok is not None:
                synced.append(f"{label} {latest_ok.ran_at.date().isoformat()}")
                if latest is not None and latest.pk != latest_ok.pk:
                    problems.append(
                        f"{label} — last attempt {latest.ran_at.date().isoformat()} "
                        f"{latest.get_status_display().lower()}; the date above is the "
                        "last attempt that succeeded"
                    )
            elif latest is not None:
                problems.append(
                    f"{label} — last attempt {latest.ran_at.date().isoformat()} "
                    f"{latest.get_status_display().lower()}, no successful sync on record"
                )
            else:
                problems.append(f"{label} — never synced")

        line = ""
        if synced:
            line = "Input catalogs last synced: " + ", ".join(synced) + "."
        if problems:
            prefix = " " if line else ""
            line += (
                prefix
                + "Not confirmed current: "
                + "; ".join(problems)
                + ". Those comparisons were made against whatever rows are currently "
                "loaded, which may pre-date the published list."
            )
        return line

    def _build_producer_attestation_section(self):
        """
        Signed producer attestation — 7 CFR 205.401 / 205.400(a).

        A certifier-acceptable submission requires a dated statement from the
        producer affirming the truth of the submitted information. Trazo can't
        produce a wet signature from a PDF generator, but we CAN surface a
        typed attestation + attribution. The statement language mirrors the
        canonical § 205.401 certification used by CCOF, Oregon Tilth, and
        MOFGA.
        """
        elements = [self._section_header("Producer Attestation (7 CFR 205.401 / 205.400(a))")]

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            establishment = None

        operator = None
        try:
            operator = self.production.operator
        except AttributeError:
            pass

        def _person(user):
            if not user:
                return ""
            return (user.get_full_name() or "").strip() or (user.email or "").strip()

        # § 205.401 / § 205.400(a) attest for the OPERATION, not for one season, so the name
        # cannot come from a single production's `operator` alone.
        #
        # 🔴 2026-08-19: it did, and the attestation page — the one carrying "under penalty of
        # law" above a signature line — printed "Producer / Operator: (operator not set)" for a
        # farm with a named producer on file, simply because the newest production row had a
        # null operator. A certifier reads an unnamed attestation as unsigned.
        #
        # Fallback order, most specific first, every step a defensible answer to "who is the
        # producer here": the season's operator, the establishment's named contact, then whoever
        # authored the Organic System Plan under § 205.201(a). Only if the operation names
        # nobody at all does the placeholder stand.
        operator_name = _person(operator)

        if not operator_name and establishment is not None:
            operator_name = (getattr(establishment, "contact_person", "") or "").strip()

        if not operator_name and establishment is not None:
            try:
                from certifications.models import OrganicSystemPlan

                plan = OrganicSystemPlan.objects.filter(establishment=establishment).order_by("-version_number").first()
                operator_name = _person(getattr(plan, "created_by", None))
            except Exception:  # noqa: BLE001 — attribution must never break the export
                operator_name = ""

        operator_name = operator_name or "(operator not set)"
        farm_name = establishment.name if establishment else "(farm not set)"

        # Canonical producer attestation wording (7 CFR 205.401 application +
        # 205.400(a) duty to comply; 205.400(f) change-notification) — do NOT alter
        # without regulatory review; this is the language every major certifier
        # accepts. (§ 205.401(d) is a catch-all "other information" subsection and
        # is NOT itself an attestation mandate, so it is not cited in the body.)
        attestation_text = (
            "I, the undersigned, hereby certify under penalty of law that the "
            "information contained in this document is true, complete, and "
            "accurate to the best of my knowledge and belief, and that all "
            "organic production practices described herein comply with the "
            "requirements of the USDA National Organic Program (7 CFR Part 205). "
            "I agree to promptly notify my certifying agent of any changes to "
            "the production, handling, or management practices that may affect "
            "the organic status of the operation (7 CFR 205.400(f))."
        )

        elements.append(Paragraph(attestation_text, self._styles["body"]))
        elements.append(self._spacer(0.15))

        # Attribution block — operator, farm, date. In a real signed submission
        # the producer signs below; this PDF records the equivalent digital
        # attribution. Legal validity of the electronic attestation rests on the
        # federal ESIGN Act (15 U.S.C. 7001) and state UETA, not on FDA's
        # 21 CFR Part 11 (which governs FDA-regulated records, not USDA NOP
        # 7 CFR 205 organic records).
        elements.append(self._label_value("Farm / Operation", farm_name))
        elements.append(self._label_value("Producer / Operator", operator_name))
        elements.append(self._label_value("Export Date", date.today().isoformat()))
        elements.append(
            self._label_value(
                "Signature",
                # Run 7: this called itself a "typed electronic attestation" though Trazo records no
                # signature for an export. The signed annual update is its own document.
                "Not signed in Trazo. The operation's signed annual update, if any, is a separate "
                "document (see the Organic System Plan reference section).",
            )
        )
        elements.append(self._spacer(0.1))

        # Signature block (physical review fallback).
        elements.append(
            Paragraph(
                "<b>Signature</b>: ____________________________________________ "
                "&nbsp;&nbsp;&nbsp; <b>Date</b>: _______________",
                self._styles["body"],
            )
        )
        elements.append(self._spacer(0.05))
        elements.append(
            Paragraph(
                "If your certifier requires this statement signed, print this section and sign above "
                "before submitting it.",
                self._styles["footer_note"],
            )
        )

        elements.extend(self._build_supervisor_signoff_subtable())
        return elements

    # Event sources scanned for supervisor sign-offs. `reviewed` / `reviewer_name` /
    # `review_date` live on CommonEvent, so EVERY event model inherits them — this tuple
    # must stay exhaustive. Equipment in particular: § 112.161(b) names "equipment and tool
    # cleaning" as a review-required record, so omitting EquipmentEvent would drop exactly
    # the sign-offs the rule asks about.
    _SIGNOFF_EVENT_SOURCES = (
        ("Field Operations", "history_productionevent_events"),
        ("Chemical", "history_chemicalevent_events"),
        ("Soil Management", "history_soilmanagementevent_events"),
        ("Pest Management", "history_pestmanagementevent_events"),
        ("Equipment", "history_equipmentevent_events"),
        ("Weather", "history_weatherevent_events"),
        ("Training / Other", "history_generalevent_events"),
        ("Business", "history_businessevent_events"),
    )

    def _scope_productions(self):
        """The productions an operation-wide section speaks for.

        A season export is bound to ONE production and every builder reads `self.production`.
        The operation dossier reuses the same builders for its operation-wide sections but
        constructs the service from `productions[0]`, so anything production-scoped inside an
        establishment-level section — reviewed records, contamination incidents, lot / retention
        / sales status — silently described the first season only. The operation service sets
        `scope_productions` to every production in the export; a season export leaves it unset.
        """
        scope = getattr(self, "scope_productions", None) or [self.production]
        return [production for production in scope if production is not None]

    def _build_supervisor_signoff_subtable(self):
        """Records a supervisor has reviewed — FSMA PSR § 112.161(b).

        CommonEvent has carried `reviewed` / `reviewer_name` / `review_date` since F21, and
        the model comment on those fields states that "the certifier PDF surfaces it". It
        did not: nothing outside the serializers and one unit test ever read them, so a
        farmer who diligently signed off records had no way to show it. This makes the
        comment true.

        § 112.161(b) asks for the reviewer's name and the review date on review-required
        records (training, agricultural water, biological soil amendments, equipment and
        tool cleaning). Rendered only when at least one sign-off exists — an operation that
        does not use sign-offs should not be shown an empty table implying it should.
        """
        # 🔴 2026-09-06 — the operation dossier builds this section ONCE, operation-wide, from
        # a service bound to whichever production happened to come first, so every other
        # season's sign-offs were absent from the 400-page document while the single-season
        # export printed them. `scope_productions` lets that caller name every production in
        # scope; a season export leaves it unset and prints its own. See `_scope_productions`.
        productions = self._scope_productions()
        multi = len(productions) > 1
        rows = []
        for production in productions:
            for label, accessor in self._SIGNOFF_EVENT_SOURCES:
                manager = getattr(production, accessor, None)
                if manager is None:
                    continue
                for ev in related_events(production, accessor, reviewed=True):
                    record = getattr(ev, "name", None) or ev.description
                    if multi:
                        record = f"{_val(record)} — {_val(getattr(production, 'name', None))}"
                    rows.append(
                        [
                            self._cell(_fmt_date(ev.date)),
                            self._cell(label),
                            self._cell(record),
                            self._cell(_val(ev.reviewer_name)),
                            self._cell(_fmt_date(ev.review_date) if ev.review_date else "—"),
                        ]
                    )

        if not rows:
            return []

        rows.sort(key=lambda row: row[0].text if hasattr(row[0], "text") else "")

        elements = [
            self._spacer(0.15),
            Paragraph(
                "<b>Supervisor Record Review (FSMA PSR § 112.161(b))</b>",
                self._sub_header_style(),
            ),
        ]
        table = Table(
            [[self._hdr(h) for h in ("Date", "Record Type", "Record", "Reviewed By", "Review Date")]] + rows,
            colWidths=[0.75 * inch, 1.05 * inch, 2.6 * inch, 1.3 * inch, 0.85 * inch],
            repeatRows=1,
        )
        table.setStyle(self._base_table_style())
        elements.append(table)
        return elements

    def _build_regulatory_scope_section(self):
        """
        Regulatory scope declarations — explicit N/A statements for regulations
        an auditor will ask about. Inspector-review finding (2025): silence on
        FSMA 204 / FSMA PSR / § 205.201(c) ICS creates an information gap;
        one-line affirmative statements close the question pre-emptively.
        """
        from certifications.models import OrganicSystemPlan

        elements = [self._section_header("Regulatory Scope Declarations")]

        try:
            establishment = self.production.parcel.establishment
        except AttributeError:
            establishment = None

        # --- FSMA 204 Food Traceability Rule (21 CFR 1.1300) ---
        # FTL membership resolved by the single-source-of-truth helper so this
        # declaration and the Traceability-section footer can never contradict.
        #
        # 🔴 2026-08-29 — this said the KDEs were required "by 2028-07-20" and the comment called
        # the rule "effective 2028-07-20". A COMPLIANCE DATE and an ENFORCEMENT MORATORIUM are not
        # the same thing, and conflating them told a certifier an obligation was not yet in force
        # when it was. The rule's own compliance date (January 20, 2026) has passed; what defers
        # 2028-07-20 is an appropriations rider barring FDA from SPENDING to enforce, which
        # expires with the fiscal year and must be renewed — not a finalised extension (the
        # 30-month extension published 2025-08-07 was a PROPOSED rule; no final rule followed).
        #
        # Trazo does not track FDA's enforcement calendar and must not appear to. The statement
        # now reports what Trazo actually knows — whether the crop is on the list — and sends the
        # operator to the authority for dates. Anything else is a regulatory claim on a document
        # a certifier reads.
        coverage = self._fsma_ftl_coverage()
        if coverage == "covered":
            fsma_204_status = (
                "COVERED. Crop is on the FDA Food Traceability List (21 CFR 1.1300), so the rule's "
                "recordkeeping obligations apply to it. Note that the growing of a listed food has "
                "no Key Data Elements of its own — KDEs attach from initial packing onward, and the "
                "initial packer assigns the traceability lot code. Trazo's lot records carry the "
                "harvest-side identifiers a packer needs; Trazo does not produce a FSMA 204 "
                "traceability plan or a sortable KDE file. Confirm the current compliance and "
                "enforcement dates with FDA or your buyer — they have been subject to change and "
                "Trazo does not track them."
            )
        elif coverage == "not_covered":
            fsma_204_status = (
                "NOT COVERED. Crop is not on the FDA Food Traceability List "
                "(21 CFR 1.1300). No FSMA 204 KDE/CTE tracking required. Lot "
                "tracking still maintained voluntarily."
            )
        else:
            fsma_204_status = (
                "STATUS UNKNOWN for this crop. Operator to confirm with "
                "certifier whether the crop appears on the FDA Food Traceability "
                "List (21 CFR 1.1300)."
            )
        elements.append(self._label_value("FSMA 204 (Food Traceability Rule)", fsma_204_status))

        # --- FSMA Produce Safety Rule water testing (21 CFR 112.44) ---------
        # PSR applies to covered produce farms >$25k revenue. Avocados are
        # NOT "rarely consumed raw" for FDA purposes; they ARE covered.
        elements.append(
            self._label_value(
                "FSMA Produce Safety Rule (21 CFR 112)",
                (
                    "Agricultural water testing records (if required for this "
                    "operation's size and crop classification) are maintained "
                    "outside the NOP scope of this export. Operator to provide "
                    "annual water test results to the certifier on request. If the "
                    "crop receives a commercial processing step that adequately "
                    "reduces pathogens (e.g., off-farm hulling/drying/pasteurization), "
                    "the operation may qualify for the 21 CFR 112.2(b) eligible-"
                    "exemption with the required disclosure and records — operator "
                    "confirms applicability with the certifier."
                ),
            )
        )

        # --- Producer Group ICS (§ 205.201(c)) ----------------------------
        # Producer groups require an Internal Control System per SOE. Single-
        # operation farms skip it. The OSP's additional_certifier_info section
        # also declares this; the scope section repeats for inspector clarity.
        # 🔴 2026-08-15 — this printed a REGULATORY DETERMINATION from a constant.
        #
        # `is_producer_group` was hard-coded False inside an `if establishment:` block that
        # re-assigned it False, and the packet then asserted "§ 205.201(c) Internal Control
        # System requirements do not apply." True for a single farm; a stated falsehood the
        # day a co-op is onboarded — and § 205.201(c) is a ten-part requirement including
        # (c)(9) "traceability and mass-balance audits".
        #
        # There is still no `is_group` flag on Establishment. The honest output is therefore
        # not a determination at all: state the basis and let the certifier judge, exactly as
        # this file does elsewhere for water testing.
        is_producer_group = getattr(establishment, "is_producer_group", None) if establishment else None
        if is_producer_group is True:
            ics_status = (
                "APPLICABLE — producer group. Internal Control System required per "
                "§ 205.201(c); see OSP additional_certifier_info section."
            )
        elif is_producer_group is False:
            ics_status = (
                "NOT APPLICABLE — recorded as a single operation. § 205.201(c) Internal "
                "Control System requirements apply to producer groups only."
            )
        else:
            ics_status = (
                "NOT RECORDED — Trazo does not capture producer-group status. § 205.201(c) "
                "Internal Control System requirements apply to producer group operations; "
                "the operator confirms whether they apply."
            )
        elements.append(self._label_value("§ 205.201(c) Internal Control System", ics_status))

        # --- SOE Fraud Prevention (§ 205.201(a)(3)) — cross-reference -----
        elements.append(
            self._label_value(
                "SOE Fraud Prevention Plan",
                (
                    "Described in OSP § 205.201(a)(3) Monitoring & Fraud "
                    "Prevention section. Farm-level OFPP status "
                    "summarized under 'SOE Compliance Status' below."
                ),
            )
        )

        # --- NOP Import Certificates (handlers only) -----------------------
        elements.append(
            self._label_value(
                "NOP Import Certificates (SOE)",
                "Not applicable — this operation is a producer, not a handler/importer.",
            )
        )

        # --- Labeling review (§ 205.303-311) -------------------------------
        elements.append(
            self._label_value(
                "Labeling Review (§ 205.303-311)",
                (
                    "Product labels must be certifier-approved before use. Label "
                    "artifacts (product label image, PLU sticker, bin tag) are "
                    "maintained separately and submitted to the certifier at "
                    "OSP filing. Not embedded in this export."
                ),
            )
        )

        # --- Rootstock / commercial-availability (§ 205.204, perennial) ----
        # For perennial crops, § 205.204(a)(1) requires a commercial-availability
        # search when non-organic planting stock is used. Trazo does not yet
        # maintain a structured rootstock dossier; the honest disclosure is that
        # the documentation lives in the parcel dossier and must be provided
        # directly to the inspector on request.
        # 2026-08-15: rootstock, plant count and spacing now have columns on ProductionEvent
        # and print in the Planting Event Details table above, so the blanket "Trazo does not
        # yet structure rootstock records" disclosure is no longer true and has been removed —
        # a disclosure that overstates a gap is as wrong as one that hides it.
        #
        # What remains genuinely out of scope is the SUPPLIER-side paperwork: the nursery's own
        # organic certificate for the stock, and the (a)(1) affidavit where the stock is
        # non-organic. Those are documents the operator holds, not records Trazo generates, so
        # the honest line is narrower now.
        elements.append(
            self._label_value(
                "Rootstock certification documents (§ 205.204)",
                (
                    "Rootstock, plant count and spacing are recorded per planting event and "
                    "printed above. The nursery's organic certificate for the planting stock, "
                    "and for non-organic stock the § 205.204(a)(1) commercial-availability "
                    "affidavit, are documents the operator holds; they are maintained in the "
                    "parcel dossier and provided to the inspector on request."
                ),
            )
        )

        # --- Residue testing (§ 205.670(c)-(d)) ----------------------------
        # Certifier-directed sampling. The farm does not proactively log residue
        # tests; attachments are added to the production record when sampled.
        elements.append(
            self._label_value(
                "Residue testing (§ 205.670(c)-(d))",
                (
                    "Periodic residue testing is certifier-directed sampling under "
                    "§ 205.670(c)-(d) (risk-based, minimum ~5% of operations "
                    "annually). The producer-side duty is limited to making the "
                    "product, site, and records accessible for sampling "
                    "(§ 205.670(a)); the producer attaches lab results to the Trazo "
                    "production record when sampling occurs. Absent sampling, this "
                    "section is intentionally empty."
                ),
            )
        )

        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "Sources: FDA FSMA 204 Final Rule (21 CFR 1.1300), FDA FSMA "
                "Produce Safety Rule (21 CFR 112), USDA NOP 7 CFR 205.201(c), "
                "205.204, 205.303-311, 205.670, SOE Final Rule (88 FR 3622).",
                self._styles["footer_note"],
            )
        )
        return elements

    # ------------------------------------------------------------------
    # Section: General Documentation (non-contamination notes)
    # ------------------------------------------------------------------

    def _build_general_events_section(self):
        """
        General farm documentation notes — § 205.103(b)(1) "adapted to the
        particular business" recordkeeping. These are the season-summary,
        training, certification-prep, and ad-hoc notes farmers log under the
        General event type. Contamination incidents are intentionally excluded
        — they render in the SOE Compliance section's own Contamination Log.
        """

        elements = [self._section_header("Training, Maintenance & Other Farm Records")]

        events = related_events(self.production, "history_generalevent_events", is_contamination_incident=False)

        # Pointer to the excluded incidents — an inspector scanning this
        # section must not conclude contamination went undocumented just
        # because the rows live in the SOE Compliance Status section.
        contamination_count = len(
            related_events(self.production, "history_generalevent_events", is_contamination_incident=True)
        )
        contamination_pointer = None
        if contamination_count > 0:
            contamination_pointer = Paragraph(
                f"<i>{contamination_count} contamination incident(s) recorded — "
                "see SOE Compliance Status section (§ 205.272).</i>",
                self._styles["footer_note"],
            )

        headers = ["Date", "Activity Type", "Name", "People", "Duration", "Notes", "By"]

        if not events:
            elements.append(self._empty_table(headers))
            if contamination_pointer is not None:
                elements.append(contamination_pointer)
            return elements

        header_row = [self._hdr(h) for h in headers]
        data = [header_row]
        for ev in events:
            data.append(
                [
                    self._cell(_fmt_date(ev.date)),
                    self._cell(_general_activity_label(ev.activity_type)),
                    self._cell(ev.activity_name or ev.name),
                    self._cell(str(ev.people_involved) if ev.people_involved is not None else None),
                    self._cell(ev.duration),
                    # Notes can run long — season summaries, training logs,
                    # certification-prep narratives. Let ReportLab word-wrap
                    # inside the column instead of cutting mid-sentence.
                    # Same cap as the Production Events description column.
                    self._cell(ev.observation),
                    self._cell(ev.performed_by),
                ]
            )

        col_widths = [
            0.7 * inch,  # Date
            1.0 * inch,  # Activity Type
            1.0 * inch,  # Name
            0.5 * inch,  # People
            0.7 * inch,  # Duration
            2.3 * inch,  # Notes
            0.8 * inch,  # By
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)
        if contamination_pointer is not None:
            elements.append(contamination_pointer)
        return elements

    # OFPP filename heuristic — surfaces misfiled receipts/invoices uploaded
    # in place of an actual Organic Fraud Prevention Plan. The filename check
    # is a first-pass integrity signal; the inspector still has to open the
    # file to confirm content.
    _OFPP_SUSPICIOUS_FILENAME_PATTERNS = ("factura", "invoice", "receipt", "comprobante", "recibo")

    def _ofpp_flags(self, compute_hash=True):
        """
        Compute OFPP state in ONE place so both the SOE section and the
        page-1 Compliance Snapshot can consult the same verdict.

        ``compute_hash=False`` skips reading the OFPP document. Hashing it means a blocking
        S3 GET of the whole file, which is the single slowest step in building the snapshot —
        acceptable when producing a PDF, not on a dashboard request that only needs the
        PASS/REVIEW/FAIL rows. ``doc_hash`` is then reported as "not computed".

        Returns dict::

            {
                "establishment": <Establishment | None>,
                "uploaded": bool,
                "doc_name": str,                 # basename or "—"
                "doc_hash": str,                 # sha256 prefix or ""
                "date_str": str,
                "responsible": str,
                "filename_suspicious": bool,     # TRUE => hard-FAIL, inspector non-conformance
            }
        """
        establishment = None
        if self.production.parcel and self.production.parcel.establishment:
            establishment = self.production.parcel.establishment
        result = {
            "establishment": establishment,
            "uploaded": False,
            "doc_name": "—",
            "doc_hash": "",
            "date_str": "Not set",
            "responsible": "Not assigned",
            "filename_suspicious": False,
            # The plan can arrive two ways and the packet must not conflate them: a file the
            # operator uploaded, or OSP module G2.0 answered inside Trazo. Saying "uploaded"
            # of the second one asserts a file that does not exist.
            "authored_in_trazo": False,
        }
        if not establishment:
            return result
        result["uploaded"] = bool(establishment.fraud_prevention_plan_uploaded)
        if not result["uploaded"]:
            # Second legitimate route (2026-08-10, mirroring
            # OperationReadinessService._ofpp_module_completed): OSP module G2.0's
            # questions ARE the fraud-prevention plan. Accepting the module here
            # keeps this gate consistent with the readiness card — before this,
            # a farmer whose farm home said "OFPP on file" still hit the 422 on
            # the organic audit export because the two services disagreed.
            try:
                from certifications.models import OrganicSystemPlan

                for plan in OrganicSystemPlan.objects.filter(establishment=establishment):
                    entry = ((plan.module_responses or {}).get("modules") or {}).get("g2_0_fraud_prevention") or {}
                    if entry.get("completed_at"):
                        result["uploaded"] = True
                        result["authored_in_trazo"] = True
                        result["doc_name"] = (
                            "authored in Trazo (OSP module G2.0 — Monitoring & Organic Fraud Prevention)"
                        )
                        completed = str(entry.get("completed_at"))[:10]
                        if completed:
                            result["date_str"] = completed
                        return result
            except Exception:  # noqa: BLE001 — G2.0 acceptance must never break the gate
                pass
        if establishment.fraud_prevention_plan_date:
            result["date_str"] = establishment.fraud_prevention_plan_date.strftime("%Y-%m-%d")
        result["responsible"] = establishment.ofpp_responsible_person or "Not assigned"
        doc = establishment.fraud_prevention_plan_document
        if doc and doc.name:
            try:
                result["doc_name"] = os.path.basename(doc.name)
            except Exception:
                result["doc_name"] = "—"
            if compute_hash:
                try:
                    import hashlib

                    with doc.open("rb") as f:
                        result["doc_hash"] = hashlib.sha256(f.read()).hexdigest()[:16]
                except Exception:
                    result["doc_hash"] = "unavailable"
            else:
                result["doc_hash"] = "not computed"
            lowered = result["doc_name"].lower()
            result["filename_suspicious"] = any(p in lowered for p in self._OFPP_SUSPICIOUS_FILENAME_PATTERNS)
        elif result["uploaded"]:
            # OFPP attested as on file but no document object is attached to this
            # record (e.g. filed directly with the certifier). Render an explicit
            # phrase instead of a bare "—" that reads as a broken/missing file.
            result["doc_name"] = "on file with certifier (not embedded in this export)"
        return result

    def _label_images_block(self):
        """
        Container Labeling figure block (Common OSP G7.0 / NOPB34 / 7 CFR 205.307).
        Embeds the actual nonretail / retail label artifacts the operation submits
        for CCOF pre-approval, with the lot/traceback element each carries. Reuses
        the photo-embed helper (_fetch_image_for_pdf, incl. its dev-skip behavior).
        Renders nothing when no labels are on file.
        """
        try:
            labels = list(self.production.label_images.select_related("gallery_image").all())
        except Exception:  # noqa: BLE001 — never break the PDF over labels
            labels = []
        labels = [lb for lb in labels if getattr(lb, "gallery_image_id", None)]
        if not labels:
            return []

        elements = [self._spacer(0.08)]
        elements.append(self._body("<b>Container Labeling — label artifacts (Common OSP G7.0 / 7 CFR 205.307)</b>"))
        elements.append(self._spacer(0.04))
        for lb in labels:
            ltype = lb.get_label_type_display() if lb.label_type else "Label"
            ctype = lb.get_container_type_display() if lb.container_type else ""
            caption = f"{ltype}{(' · ' + ctype) if ctype else ''}"
            if lb.lot_link_note:
                caption += f" — {_truncate(lb.lot_link_note, 120)}"
            elements.append(self._body(caption))
            buf = self._fetch_image_for_pdf(lb.gallery_image)
            if buf is not None:
                img = RLImage(buf, width=2.7 * inch, height=2.1 * inch, kind="proportional")
                img.hAlign = "LEFT"
                elements.append(img)
            else:
                elements.append(
                    Paragraph(
                        "[Label image on file; not embedded in this environment — "
                        "originals retained in the producer dashboard.]",
                        self._styles["footer_note"],
                    )
                )
            elements.append(self._spacer(0.06))
        return elements

    def _build_soe_compliance_section(self):
        """SOE compliance status: OFPP, record retention, traceability."""
        elements = [self._section_header("SOE Compliance Status")]

        ofpp = self._ofpp_flags()
        establishment = ofpp["establishment"]
        ofpp_doc_name = ofpp["doc_name"]
        ofpp_doc_hash = ofpp["doc_hash"]
        ofpp_date = ofpp["date_str"]
        ofpp_person = ofpp["responsible"]

        if establishment:
            # OFPP Status — filename heuristic promotes "Uploaded" to an
            # explicit [NON-CONFORMANCE] status when the filename matches a
            # misfiled-invoice/receipt pattern. An empty-upload remains a
            # NOT UPLOADED non-conformance.
            if not ofpp["uploaded"]:
                ofpp_status = "NOT UPLOADED"
            elif ofpp["filename_suspicious"]:
                ofpp_status = "[NON-CONFORMANCE] filename suggests misfile"
            elif ofpp["authored_in_trazo"]:
                ofpp_status = "On file"
            else:
                ofpp_status = "Uploaded"
            ofpp_filename_warning = (
                " [NON-CONFORMANCE: filename matches misfiled invoice/receipt pattern"
                " — inspector must open the document to verify it actually implements"
                " § 205.201(a)(3) OFPP requirements; if not, the operation is"
                " non-compliant regardless of the upload flag]"
                if ofpp["filename_suspicious"]
                else ""
            )

            # A crop GROWN IN A BUFFER is the textbook parallel-production situation: it is
            # the same species on the same ranch that may not be sold as organic. Buffer rows
            # are structured (`crop_grown_in_buffer` on the parcel), so this is a fact check,
            # not a reading of prose.
            buffer_crop_parcels = self._parcels_with_a_crop_grown_in_buffer(establishment)

            # 🔴 2026-08-21 — split status has TWO editors: `Establishment.has_split_operation`
            # (the farm-profile checkbox) and the OSP's own G6.0 `split_operation` answer, with
            # nothing binding them. This table read the checkbox, so a farm that answered "yes,
            # we sell the buffer rows conventional" in the OSP wizard still filed a packet whose
            # SOE table said "Split Operation (7 CFR 205.272): No" — and then a REVIEW below it
            # telling the operator the two statements in their packet disagree, which they had
            # already resolved in the place the regulation cares about. The OSP is the § 205.201
            # plan of record; when it answers this question, it wins.
            _osp_split = self._osp_declares_split_operation(establishment)
            declares_split = establishment.has_split_operation if _osp_split is None else _osp_split

            if establishment.split_operation_plan:
                split_plan_text = establishment.split_operation_plan
            elif declares_split:
                split_plan_text = "Commingling prevention plan required (7 CFR 205.272)"
            else:
                # ⚠️ "No commingling plan required" is a REGULATORY CONCLUSION, and this
                # document was drawing it from one operator checkbox. § 205.272(a) binds any
                # operation that produces both organic and non-organic product — including a
                # harvested buffer crop — so the packet must report the declaration, not
                # ratify it. Blue Oak's own OSP § 205.201(a)(6) describes selling the buffer
                # rows conventional two pages above this cell reading "No".
                split_plan_text = (
                    "Operator declares a wholly organic operation — no parallel or split "
                    "production. § 205.272 applies to any operation producing both organic "
                    "and non-organic product; the inspector confirms this declaration on site."
                )

            # Wrap every cell in a Paragraph so long values word-wrap inside the
            # column (ReportLab Table does NOT wrap raw-string cells — same
            # WORDWRAP gotcha we hit in the change-log table). Also gives XML
            # escaping for '<', '>', '&' in user-supplied text.
            cell_style = ParagraphStyle(
                "SOECell",
                parent=self._styles["body"],
                fontSize=8,
                leading=10,
            )
            header_style = ParagraphStyle(
                "SOEHeader",
                parent=cell_style,
                fontName="Helvetica-Bold",
            )

            def P(text):
                return Paragraph(self._safe_narrative(str(text)), cell_style)

            # SOE (§ 205.307(a)) itemized sales — prefer the dedicated SalesRecord
            # rows over the single legacy sold_to/organic_on_invoice fields.
            scope = self._scope_productions()
            multi = len(scope) > 1
            _soe_sales = []
            for _prod in scope:
                try:
                    _soe_sales += list(_prod.sales_records.live())
                except Exception:  # noqa: BLE001 — relation always present in practice
                    pass
            _sold_to_any = any(getattr(_prod, "sold_to", None) for _prod in scope)
            _retained = [_prod for _prod in scope if _prod.retention_until]
            _with_lot = [_prod for _prod in scope if _prod.lot_id]
            _soe_sales_buyers = ", ".join(sorted({(s.buyer_name or "").strip() for s in _soe_sales if s.buyer_name}))
            _soe_organic_on_invoice = (
                all(s.organic_on_invoice for s in _soe_sales)
                if _soe_sales
                else any(bool(_prod.organic_on_invoice) for _prod in scope)
            )

            rows = [
                [Paragraph(h, header_style) for h in ("Requirement", "Status", "Details")],
                [
                    P("Organic Fraud Prevention Plan"),
                    P(ofpp_status),
                    P(
                        f"Date: {ofpp_date} · Responsible: {ofpp_person} · "
                        f"Document: {ofpp_doc_name}"
                        + (f" · SHA-256: {ofpp_doc_hash}" if ofpp_doc_hash else "")
                        + ofpp_filename_warning
                    ),
                ],
                # "Not set" here read as "this operation does not retain records
                # for 5 years" — the opposite of true, and flatly contradicted by
                # the § 205.103(b)(4) paragraph two blocks below on the same page.
                # `retention_until` is only the computed END-DATE, stamped when the
                # production finishes; the 5-year clock runs from record creation
                # either way. Describe the clock, not the empty column.
                [
                    P("Record Retention (5 years)"),
                    P(
                        "Active"
                        if len(_retained) == len(scope)
                        else (f"{len(_retained)}/{len(scope)} finished" if multi else "Running")
                    ),
                    P(_retention_detail(scope, _retained)),
                ],
                [
                    P("Lot Traceability"),
                    P(
                        ("Assigned" if _with_lot else "Missing")
                        if not multi
                        else f"{len(_with_lot)}/{len(scope)} assigned"
                    ),
                    P(
                        "Lot ID" + ("s: " if multi else ": ") + ", ".join(_val(_prod.lot_id) for _prod in _with_lot)
                        if _with_lot
                        else "Assign lot ID at production finish"
                    ),
                ],
                [
                    P("Post-Harvest Sales Record"),
                    P("Recorded" if (_soe_sales or _sold_to_any) else "Not recorded"),
                    P(
                        f"{len(_soe_sales)} itemized sales record(s) on file (§ 205.307(a)); "
                        f"buyers: {_soe_sales_buyers}"
                        if _soe_sales
                        else (
                            "Sold to: " + ", ".join(sorted({_val(_prod.sold_to) for _prod in scope if _prod.sold_to}))
                            if _sold_to_any
                            else "Add sales data after harvest"
                        )
                    ),
                ],
                [
                    P("Organic on Invoice"),
                    # "No / Not set" fused a non-conformance with an unanswered question. When
                    # nothing has been sold there is no invoice to identify — see the matching
                    # Output Reconciliation row.
                    P(
                        ("Yes" if _soe_organic_on_invoice else "No / Not set")
                        if (_soe_sales or _sold_to_any)
                        else "No sales yet"
                    ),
                    P("SOE requires organic identification on sales documents"),
                ],
                [
                    P("Split Operation (7 CFR 205.272)"),
                    P("Yes" if declares_split else "No"),
                    P(split_plan_text),
                ],
            ]

            col_widths = [2.0 * inch, 1.2 * inch, 3.5 * inch]
            t = Table(rows, colWidths=col_widths, repeatRows=1)
            t.setStyle(self._base_table_style())
            elements.append(t)

            if buffer_crop_parcels and not declares_split:
                elements.append(
                    Paragraph(
                        "<b>[REVIEW] 7 CFR 205.272:</b> the operation is declared wholly organic, "
                        f"but a crop is recorded as grown in the buffer on {buffer_crop_parcels}. "
                        "A harvested buffer crop may not be sold or represented as organic "
                        "(§ 205.202(c)), which makes the operation split for § 205.272 purposes. "
                        "Either record how the buffer crop is kept separate and identified, or "
                        "state that it is not harvested — an inspector will ask, and the two "
                        "statements in this packet currently disagree.",
                        self._warning_style(),
                    )
                )

            # Split operation warning.
            #
            # 🔴 2026-08-21 — reads `declares_split` (resolved above), NOT the raw column. It
            # used to read `establishment.has_split_operation` directly, so it could contradict
            # the SOE table 140 lines above it: an operation whose OSP answers "yes" while the
            # column still says False got no warning, and one with a stale True column got a
            # WARNING asserting a split operation the plan denies. That is the F25 defect
            # itself — two readers of one fact disagreeing inside one document — surviving one
            # block below the place it was fixed.
            if declares_split and not establishment.split_operation_plan:
                elements.append(
                    Paragraph(
                        "<b>[WARNING] NOP 7 CFR 205.272:</b> This is a split operation (organic + conventional) "
                        "but no commingling prevention plan is documented. "
                        "Document labeling, storage separation, and equipment cleaning protocols.",
                        self._warning_style(),
                    )
                )
        else:
            elements.append(self._body("No farm linked to this production."))

        # Contamination Incident Log — § 205.272 is the correct cite for
        # commingling / contact-with-prohibited-substance prevention. § 205.201(b)
        # is the OSP-substitution clause and does not govern contamination logs.
        contamination_events = [
            ev
            for _prod in self._scope_productions()
            for ev in related_events(_prod, "history_generalevent_events", is_contamination_incident=True)
        ]
        if contamination_events:
            elements.append(self._spacer(0.1))
            elements.append(
                Paragraph(
                    "<b>Contamination Incident Log (7 CFR 205.272)</b>",
                    self._sub_header_style(),
                )
            )
            cont_headers = [
                "Date",
                "Source",
                "Area (ac)",
                "Corrective Action",
                "Action Date",
                "Certifier Notified",
            ]
            cont_data = [[self._hdr(h) for h in cont_headers]]
            for cev in contamination_events:
                source_display = ""
                if cev.contamination_source:
                    source_display = cev.get_contamination_source_display()
                cont_data.append(
                    [
                        self._cell(_fmt_date(cev.date)),
                        self._cell(source_display),
                        self._cell(str(cev.contamination_affected_area) if cev.contamination_affected_area else "—"),
                        # Raise corrective-action cell cap so the action
                        # narrative wraps in-column instead of truncating
                        # mid-sentence ("Notified CCOF inspector within
                        # 24…" kind of cutoff). Same pattern as the
                        # Production Events / General Documentation fix.
                        # A corrective action is what the certifier came to read.
                        self._cell(cev.corrective_action_taken),
                        self._cell(_fmt_date(cev.corrective_action_date) if cev.corrective_action_date else None),
                        self._cell(
                            f"Yes ({_fmt_date(cev.certifier_notification_date)})"
                            if cev.certifier_notified and cev.certifier_notification_date
                            else ("Yes" if cev.certifier_notified else "No")
                        ),
                    ]
                )
            cont_widths = [0.65 * inch, 0.9 * inch, 0.6 * inch, 2.4 * inch, 0.75 * inch, 1.0 * inch]
            ct = Table(cont_data, colWidths=cont_widths, repeatRows=1)
            ct.setStyle(self._base_table_style())
            elements.append(ct)

            # 🔴 2026-08-31 — the grower's own account of the incident reached NEITHER table.
            #
            # `_build_general_events_section` deliberately excludes contamination events and
            # points here instead, which is right: an incident belongs under § 205.272, not in
            # ad-hoc documentation. But this table carries only the STRUCTURED fields, so the
            # observation went out the gap between the two — the one event class in the whole
            # packet whose field notes were missing, and the class where "what did the operator
            # say happened" is most of what an inspector is reading for.
            #
            # Same sub-table helper every other section uses (Application Notes, Soil Notes,
            # Pest Notes), so the Source column keeps a farmer's words apart from a
            # template-generated description exactly as it does elsewhere.
            elements.extend(
                self._build_event_notes_subtable(
                    contamination_events,
                    "Contamination Incident Notes",
                    {},
                )
            )

        # ----------------------------------------------------------------
        # SOE 2024 Compliance Items (88 FR 3622, effective 2024-03-19)
        # Inspectors look for these items during the annual inspection.
        # The block surfaces what Trazo CAN verify from data on file plus the
        # operator's standing attestations — not blanket Trazo guarantees.
        # Phrasing matters: claiming the operation "maintains X" when the
        # underlying field is empty would be a fraudulent attestation under
        # FTC Green Guides and § 205.401(d). Each item below either reads from
        # actual establishment / production state or is phrased as the operator's
        # own declaration.
        # ----------------------------------------------------------------
        elements.append(self._spacer(0.18))
        elements.append(
            Paragraph(
                "<b>SOE 2024 Compliance Items (88 FR 3622)</b>",
                self._sub_header_style(),
            )
        )

        # 1. Fraud Prevention Plan — REPORT actual state, never assert one exists
        # when it doesn't. Status comes from the establishment row. A suspicious
        # filename pattern promotes the item to an explicit [NON-CONFORMANCE]
        # with equal severity to "not uploaded" — uploading a PDF labelled
        # "ComprobanteFactura.pdf" is worse than honest non-compliance because
        # it looks compliant at a glance.
        if establishment is not None and ofpp["uploaded"] and not ofpp["filename_suspicious"]:
            _held = (
                "Operator has a written Organic Fraud Prevention Plan on file"
                if ofpp["authored_in_trazo"]
                else "Operator has uploaded a written Organic Fraud Prevention Plan"
            )
            _where = "source" if ofpp["authored_in_trazo"] else "file"
            ofpp_text = (
                "<b>Fraud Prevention Plan (7 CFR 205.201(a)(3)):</b> "
                f"{_held} "
                f"({_where}: {ofpp_doc_name}; effective {ofpp_date}; responsible: {ofpp_person}). "
                "Inspector should review the plan for documented monitoring procedures, "
                "supplier verification, and deviation/corrective-action protocols."
            )
        elif establishment is not None and ofpp["uploaded"] and ofpp["filename_suspicious"]:
            ofpp_text = (
                "<b>[NON-CONFORMANCE \u2014 treat as missing OFPP] "
                "Fraud Prevention Plan (7 CFR 205.201(a)(3)):</b> "
                f"An OFPP file is uploaded (<code>{ofpp_doc_name}</code>) but its "
                "filename matches the pattern of a misfiled invoice/receipt. Trazo "
                "treats this upload as a missing OFPP for compliance-snapshot "
                "purposes: \u00a7 205.201(a)(3) (SOE, effective 2024-03-19) requires "
                "a substantive plan with a vulnerability assessment, supplier "
                "verification, monitoring procedures, and deviation / corrective-"
                "action protocols. An operation without a valid OFPP is ineligible "
                "for certification. The operator must upload a real OFPP before the "
                "next inspection; inspectors should not be asked to discover that "
                "the file is an invoice during the audit."
            )
        else:
            ofpp_text = (
                "<b>[NON-CONFORMANCE] Fraud Prevention Plan (7 CFR 205.201(a)(3)):</b> "
                "No Organic Fraud Prevention Plan is on file for this operation. "
                "SOE (effective 2024-03-19) requires every certified operation to "
                "maintain a written OFPP. Upload the plan via the Farm "
                "settings before the next inspection."
            )
        elements.append(Paragraph(ofpp_text, self._styles["body"]))

        # 2. Record retention — Trazo describes its OWN durability promise; the
        # 5-year retention is a regulatory requirement the operator is responsible
        # for. We attest to the platform behavior, not the operator's compliance.
        elements.append(
            Paragraph(
                "<b>Record retention (7 CFR 205.103(b)(4)):</b> "
                "records must be kept not less than five years beyond their creation. Trazo "
                "calculates each season's date as five years after it finished or after its "
                "newest record was created, whichever is later, and refuses deletion of a "
                "finished season's records before that date. Records of a season still running "
                "are not deletion-protected by Trazo. The operator is responsible for retaining "
                "any paper or off-platform records to the same standard.",
                self._styles["body"],
            )
        )

        # 3. Unannounced inspection — describe the data availability Trazo provides
        # rather than asserting staff are trained. CFR cite is § 205.403 (On-site
        # inspections); subsection (b) requires certifying agents to conduct
        # unannounced on-site inspections of at least 5% of certified operations
        # annually. § 205.661 ("Investigation") was the prior cite and is WRONG —
        # it governs complaint-of-noncompliance investigations, not inspections.
        elements.append(
            Paragraph(
                # 🔴 2026-08-20 — said "are maintained in real time … no advance preparation
                # required". Both certifier reviewers quoted it back against the same
                # document's change history, which showed the entire record set written by a
                # background task the night the packet was generated. Whether an operation's
                # records are contemporaneous is a FINDING about the operation, made by the
                # inspector from the record dates — Trazo cannot assert it, and asserting it
                # falsely is worse than saying nothing, because it invites the reviewer to
                # distrust every other statement in the packet. What Trazo can honestly speak
                # to is its own export capability.
                "<b>Unannounced inspection readiness (7 CFR 205.403(b)):</b> "
                "Every event log, OSP narrative, input purchase and sales record held for "
                "this production can be exported (this report) within minutes of a certifier "
                "or USDA request, with no advance preparation. Whether those records were "
                "entered contemporaneously is shown by the Record Change History in this "
                "report, and is the inspector's determination — not Trazo's.",
                self._styles["body"],
            )
        )

        # 4. Non-retail container labeling — § 205.307 is the correct cite.
        # § 205.273 covers Imports and is NOT about non-retail labeling. Under
        # the post-SOE rule (88 FR 3622, effective 2024-03-19), § 205.307(a)
        # requires ONLY two items on a non-retail container: (1) identification
        # of the product as organic, and (2) the production lot number /
        # shipping ID / other unique identifier linking the container to audit
        # trail documentation. Operation name and certifying-agent name are
        # NOT mandatory on non-retail containers (they are mandatory on retail
        # under § 205.303 but § 205.307 was deliberately narrowed by AMS to
        # reduce burden on bulk shipping / harvest bins). Flagging their
        # absence invents a regulatory hurdle the rule does not impose.
        _lot_scope = self._scope_productions()
        _lot_ids = [_esc(_val(_prod.lot_id)) for _prod in _lot_scope if _prod.lot_id]
        if _lot_ids:
            _lot_phrase = (
                f"Lot ID <b>{_lot_ids[0]}</b> is assigned to this production "
                if len(_lot_scope) == 1
                else f"Lot IDs <b>{', '.join(_lot_ids)}</b> are assigned to the productions in this report "
            )
            label_text = (
                "<b>Non-retail container labeling (7 CFR 205.307):</b> "
                # _esc: operator-assigned identity string on a markup-parsing Paragraph.
                + _lot_phrase + "and links every harvest container to the events recorded in this "
                "report. Under the post-SOE § 205.307(a), each non-retail container "
                "must display only: (1) identification of the product as organic "
                "(e.g., the word \u201corganic\u201d or \u201cORG\u201d), and (2) a "
                "unique identifier \u2014 typically this lot / shipping ID \u2014 "
                "linking the container to audit-trail documentation. Operation name, "
                "certifying-agent name, and USDA seal are permitted but not required "
                "on non-retail containers. Operator attests that every non-retail "
                "container leaving the farm bears both the organic identity mark and "
                "this lot / shipping ID."
            )
        else:
            label_text = (
                "<b>[REVIEW] Non-retail container labeling (7 CFR 205.307):</b> "
                "No lot ID has been assigned to this production yet. Under post-SOE "
                "\u00a7 205.307(a), each non-retail container must bear (1) "
                "identification of the product as organic, and (2) a unique "
                "identifier (lot / shipping ID) that links it to audit-trail "
                "documentation. Assign a lot ID at production finish so every "
                "non-retail container can be traced back to the harvest events "
                "recorded in this report."
            )
        elements.append(Paragraph(label_text, self._styles["body"]))

        # Embed the actual label artifacts (G7.0) right after the non-retail
        # container labeling discussion they support.
        elements += self._label_images_block()

        # 5. Import certificate — neutral statement; we don't track imports yet.
        elements.append(
            Paragraph(
                "<b>NOP Import Certificate (SOE 2024):</b> "
                "Trazo does not currently track imported organic inputs. If any "
                "imported organic input was used in this production period, the "
                "NOP Import Certificate issued by the foreign certifier must "
                "accompany the shipment and be retained for 5 years; provide it "
                "directly to the inspector during the on-site visit.",
                self._styles["body"],
            )
        )

        # 6. Supply-chain traceability audit readiness — producer-side cites.
        # § 205.501(a)(21) authorises certifiers to conduct risk-based supply-
        # chain traceability audits; § 205.201(a)(3) is the producer-side duty
        # to maintain supplier-verification / fraud-prevention procedures.
        # § 205.504(b)(7) is deliberately NOT cited here — it addresses the
        # evidence certifiers must submit to AMS for accreditation, which is
        # not a producer duty. "SOE 24-hour response window" is likewise not a
        # regulatory deadline — Trazo exposes rapid-retrieval as a capability,
        # not as a self-imposed non-compliance trap.
        elements.append(
            Paragraph(
                # 🔴 2026-08-20 — the heading cited § 205.501(a)(21) beside a producer
                # attestation. § 205.501 lists the requirements a CERTIFYING AGENT must meet
                # to be accredited; (a)(21) is the agent's duty to conduct traceability
                # audits. Citing it as the producer's obligation misstates who is bound, in a
                # document whose value rests on getting citations right. The producer's own
                # duties here are § 205.201(a)(3) and § 205.103(b).
                "<b>Supply-chain traceability audit readiness "
                "(7 CFR 205.201(a)(3) / 205.103(b); the certifying agent's own audit duty is "
                "§ 205.501(a)(21)):</b> "
                "Producer attests that all event logs, OSP narratives, input "
                "purchases, drift-detector findings, mass-balance aggregates, "
                "and sales records in this report are the same records that "
                "would be pulled for a certifier-initiated supply-chain "
                "traceability audit. Trazo infrastructure supports rapid "
                "retrieval (target: 24-hour response) of the full farm-to-QR "
                "trail via API or direct dashboard access, and producer will "
                "cooperate with traceability audits initiated by the "
                "certifying agent, AMS, or downstream certified operations.",
                self._styles["body"],
            )
        )

        elements.append(self._spacer(0.08))
        elements.append(
            Paragraph(
                "SOE (Strengthening Organic Enforcement) rule effective March 19, 2024 requires "
                "fraud prevention plans (7 CFR 205.201(a)(3)), enhanced traceability "
                "(7 CFR 205.103(b)(2)), 5-year record retention (7 CFR 205.103(b)(4)), "
                "and supply-chain traceability audits (7 CFR 205.501(a)(21)).",
                self._styles["footer_note"],
            )
        )

        return elements

    # ------------------------------------------------------------------
    # Section: Record Change History (Sprint 2.1 — django-auditlog)
    # ------------------------------------------------------------------

    # The relations whose edits the trail prints. Equipment is deliberately absent — see the
    # note inside the builder.
    _CHANGE_HISTORY_EVENT_SOURCES = (
        "history_productionevent_events",
        "history_chemicalevent_events",
        "history_soilmanagementevent_events",
        "history_pestmanagementevent_events",
        "history_businessevent_events",
        "history_weatherevent_events",
        "history_generalevent_events",
    )

    def _build_change_history_section(self):
        """
        Per-record edit log from django-auditlog.

        Inspector uses this to verify NOP digital-recordkeeping trustworthiness
        (7 CFR 205.103; ALCOA+ principles): every modification has a user, timestamp,
        and field-level diff. Records edited after production finish_date are flagged.
        """
        from auditlog.models import LogEntry

        elements = [self._section_header("Record Change History (Common OSP G8.0)")]
        elements.append(
            self._body(
                "Edit attribution and field-level diffs for this production and its events. "
                "Every change is timestamped and attributed to the user who made it "
                "(NOP digital recordkeeping trustworthiness, per 7 CFR 205.103)."
            )
        )

        # One query for the whole trail. This called `LogEntry.get_for_object()` once per
        # record — the production and every one of its events — and then read `.actor` and
        # `.content_type` off every entry: three N+1s deep, ~1,600 of the ~2,750 queries a
        # 12-production operation dossier ran (measured 2026-09-05) and the single largest
        # reason the production export took a minute. Same rows, same order; only the number
        # of round-trips changed. Seven relations, not eight: EquipmentEvent is retired in the
        # UI (equipment work is logged as Production EM/PH records), so nothing can edit one and
        # its legacy rows have no trail worth printing.
        from django.contrib.auth import get_user_model
        from django.contrib.contenttypes.models import ContentType
        from django.db.models import Q

        records = [self.production]
        for related_name in self._CHANGE_HISTORY_EVENT_SOURCES:
            records.extend(related_events(self.production, related_name))
        by_model = {}
        for record in records:
            by_model.setdefault(type(record), []).append(record)
        content_types = ContentType.objects.get_for_models(*by_model)
        trail_filter = Q()
        author_id_by_record = {}
        for model, rows in by_model.items():
            ct = content_types[model]
            trail_filter |= Q(content_type=ct, object_pk__in=[str(r.pk) for r in rows])
            for r in rows:
                author_id_by_record[(ct.pk, str(r.pk))] = getattr(r, "created_by_id", None)
        all_entries = list(LogEntry.objects.filter(trail_filter).select_related("actor", "content_type"))
        # Fallback attribution (the record's author when the log carries no actor) used to
        # resolve one user per entry; every author the trail can need comes back in one query.
        author_ids = {uid for uid in author_id_by_record.values() if uid}
        authors = get_user_model().objects.in_bulk(author_ids) if author_ids else {}

        if not all_entries:
            elements.append(self._spacer(0.1))
            elements.append(
                self._body(
                    "No edit history recorded yet. (Audit-trail capture began on Sprint 2.1 "
                    "rollout — earlier records are reported as 'unmodified since creation'.)"
                )
            )
            return elements

        all_entries.sort(key=lambda le: le.timestamp, reverse=True)

        finalize_date = self.production.finish_date.date() if self.production.finish_date else None

        # When the season was CLOSED IN TRAZO, which is not the same date as the season's end.
        #
        # 🔴 2026-08-19: this compared every audit timestamp against `finish_date` — a date the
        # GROWER types on the finish form. A pilot entering last season's records (the whole
        # October use case) sets finish_date to last autumn and does the data entry today, so
        # every single edit landed after it and the packet told the inspector to review all of
        # them for "corrective-action context". A flag that fires on every well-kept backfilled
        # season trains an inspector to ignore it, which is worse than not having it.
        #
        # The honest comparison is against the moment the record was actually closed: the log
        # entry that first wrote `finish_date`. If that entry cannot be found — pre-audit-log
        # rows — no claim is made rather than a wrong one.
        ordered = sorted(all_entries, key=lambda e: e.timestamp)
        finalized_at = None
        for le in ordered:
            if le.action != LogEntry.Action.UPDATE:
                continue
            changes = le.changes_dict or {}
            if "finish_date" in changes:
                finalized_at = le.timestamp
                break

        # Closing a season is one operation but more than one row: the request that writes
        # finish_date also writes extra_data, landing microseconds later. Counting that second
        # row as an edit "after finalization" would put a [REVIEW] flag on every correctly
        # closed season — the same cry-wolf failure as the finish_date comparison this
        # replaced, just smaller. The boundary is therefore the end of the closing second,
        # not the first row of it.
        if finalized_at is not None:
            close_second = finalized_at.replace(microsecond=0)
            for le in ordered:
                if le.timestamp.replace(microsecond=0) == close_second and le.timestamp > finalized_at:
                    finalized_at = le.timestamp

        post_finalize_count = (
            sum(1 for le in all_entries if le.action == LogEntry.Action.UPDATE and le.timestamp > finalized_at)
            if finalized_at
            else 0
        )

        elements.append(self._spacer(0.1))
        summary_text = (
            f"Total recorded changes: {len(all_entries)}. "
            f"Production finalized: {finalize_date.isoformat() if finalize_date else 'No (in progress)'}."
        )
        elements.append(self._body(summary_text))

        if post_finalize_count:
            from history.models import EventAmendment

            # Scoped to AFTER the close, matching `post_finalize_count` above. Counting every
            # amendment on the season would include corrections made while it was still open —
            # a number a reviewer would try to reconcile against the edit count and could not.
            documented = EventAmendment.objects.filter(history=self.production, created_at__gt=finalized_at).count()
            documented_clause = (
                (
                    f" Of these, at least {documented} "
                    + ("is a documented correction " if documented == 1 else "are documented corrections ")
                    + "carrying the original value and the reason given at the time — see "
                    "Documented Corrections below."
                )
                if documented
                else ""
            )
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    # Two dates, and a reader will assume they are one event unless told
                    # otherwise: the line directly above reads "Production finalized:
                    # 2025-10-15" (the season's own finish date, which the operator sets and
                    # may backdate) while this one reads 2026-08-19 (when the close was
                    # actually recorded in Trazo). "After close" can only be measured against
                    # the second — an edit cannot postdate a backdated finish date — so the
                    # sentence names which is which rather than leaving the reader to guess.
                    f"<b>[REVIEW] {post_finalize_count} edit(s) recorded after this season's records were "
                    f"closed in Trazo on {finalized_at.date().isoformat()}"
                    + (
                        f" (the season's own finish date is {finalize_date.isoformat()})"
                        if finalize_date and finalize_date != finalized_at.date()
                        else ""
                    )
                    + ". Inspector should review these changes for corrective-action context.</b>"
                    # F7 (2026-08-21) — say how many of those edits are ACCOUNTED FOR. A
                    # correction made the sanctioned way writes an audit row like any other
                    # edit, so a season whose operator did everything right read here as
                    # unexplained drift. Naming the documented ones points the inspector at
                    # the table that explains them instead of at a bare count. The number is
                    # "At least", not "N of them": a correction writes one audit row today,
                    # but a save-triggered signal (the carbon recalculation on a
                    # ProductionEvent, say) can write a second, and this document must not
                    # assert an arithmetic it cannot guarantee. A floor is still useful and
                    # is never wrong.
                    + documented_clause,
                    self._warning_style(),
                )
            )

        elements.append(self._spacer(0.1))

        action_map = {
            LogEntry.Action.CREATE: "Created",
            LogEntry.Action.UPDATE: "Updated",
            LogEntry.Action.DELETE: "Deleted",
            LogEntry.Action.ACCESS: "Accessed",
        }
        headers = ["Timestamp", "Actor", "Action", "Record", "Fields Changed"]
        data = [[self._hdr(h) for h in headers]]

        for le in all_entries[:200]:  # cap to avoid runaway PDFs
            # Actor attribution, per ALCOA+ recordkeeping principles: prefer the logged-in
            # user recorded by AuditlogMiddleware; fall back to the underlying
            # record's created_by; last-resort is an explicit "system (background
            # task)" label so an inspector can distinguish a signal/migration
            # side-effect from a user-initiated change. Never render bare "system".
            actor = None
            if le.actor:
                try:
                    actor = le.actor.email or str(le.actor)
                except Exception:
                    actor = str(le.actor)
            if not actor:
                author = authors.get(author_id_by_record.get((le.content_type_id, str(le.object_pk))))
                if author is not None:
                    actor = getattr(author, "email", None) or str(author)
            if not actor:
                actor = "system (background task)"
            model_name = le.content_type.model_class().__name__ if le.content_type else "Unknown"
            record_label = f"{model_name} #{le.object_pk}"
            changed_fields = self._inspector_field_list(le.changes_dict)
            data.append(
                [
                    self._cell(le.timestamp.strftime("%Y-%m-%d %H:%M")),
                    self._actor_cell(actor),
                    self._cell(action_map.get(le.action, "?")),
                    self._cell(record_label),
                    self._cell(changed_fields),
                ]
            )

        # Actor widened 1.40 -> 1.55 and emails wrapped at the "@" (see _actor_cell): an
        # address is the ATTRIBUTION this table exists to record under § 205.103, and
        # ReportLab was splitting it as "paula.reyes@blueoakwalnut.e" / "xample" — a different
        # address, with nothing signalling that a character moved. The 0.15in came off
        # "Fields Changed", which is prose and wraps on word boundaries.
        col_widths = [1.2 * inch, 1.55 * inch, 0.7 * inch, 1.3 * inch, 1.85 * inch]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)

        if len(all_entries) > 200:
            elements.append(self._spacer(0.05))
            elements.append(
                Paragraph(
                    f"Note: showing the most recent 200 of {len(all_entries)} total entries. "
                    f"Full audit trail available via the audit-trail API endpoint.",
                    self._styles["footer_note"],
                )
            )

        # --- Documented corrections -------------------------------------------
        #
        # The table above lists WHICH fields changed; it deliberately does not print
        # values, because an auditlog diff spans every field on every model and would
        # bury the page. But "application rate changed" answers nothing an inspector
        # asked. A correction to a FILED record is the case where the values are the
        # whole point, so those get their own table, in the shape a paper record uses:
        # the original, the correction, and the reason, on one line.
        #
        # 7 CFR 205.103(b)(3) requires records to "include audit trail documentation";
        # (b)(2) requires them to be "readily understood and audited". A trail an
        # inspector cannot read the values of satisfies neither.
        elements.extend(self._amendments_table())
        elements.extend(self._crew_message_provenance_section())

        return elements

    def _write_crew_message_csv(self, writer):
        """One row per record confirmed from a crew message: three roles, three times, the words."""
        from history.services.crew_note_provenance import event_type_of, provenance_for

        events = []
        for production in self._scope_productions():
            for _label, accessor in self._SIGNOFF_EVENT_SOURCES:
                if getattr(production, accessor, None) is not None:
                    events.extend(related_events(production, accessor))
        found = provenance_for(events)
        if not found:
            return
        writer.writerow([])
        writer.writerow(["=== RECORDS CONFIRMED FROM CREW MESSAGES ==="])
        writer.writerow(
            [
                "Stated Occurrence",
                "Record Type",
                "Record",
                "Sender",
                "Sender Number (last 4)",
                "Message Kind",
                "Message Received",
                "Message As Received",
                "Message Is Machine Transcript",
                "Message Language",
                "Performer (as entered)",
                "Confirmed By",
                "Confirmed At",
                "Reviewed By",
                "Review Date",
                "Machine Values Applied",
            ]
        )

        def _safe(value):
            # The message text comes from outside the operation (a crew member's phone). A cell
            # starting with = + - @ is read as a formula by spreadsheet apps; quote it.
            text = "" if value is None else str(value)
            return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

        for ev in sorted(events, key=lambda e: str(getattr(e, "date", "") or "")):
            prov = found.get((event_type_of(ev), ev.pk))
            if prov is None:
                continue
            writer.writerow(
                [
                    _fmt_date(getattr(ev, "date", None)),
                    self._AMENDMENT_RECORD_KINDS.get(prov.event_type, "Record"),
                    _safe(getattr(ev, "name", None) or ev.description or ""),
                    _safe(prov.sender_name),
                    prov.sender_last4,
                    prov.kind,
                    prov.received_at or "",
                    _safe(prov.words),
                    "yes" if prov.words_are_transcript else "no",
                    _safe(prov.language),
                    _safe((getattr(ev, "performed_by", "") or "").strip() or "not recorded"),
                    _safe(prov.confirmer_name),
                    prov.confirmed_at or "",
                    (getattr(ev, "reviewer_name", "") or "") if getattr(ev, "reviewed", False) else "",
                    _fmt_date(getattr(ev, "review_date", None)) if getattr(ev, "reviewed", False) else "",
                    _safe("; ".join(prov.proposal_applied)),
                ]
            )

    def _crew_message_provenance_section(self):
        """Records confirmed from crew messages: sender, performer and confirmer kept apart.

        OSP alignment audit 2026-10, T29. These records carried only the confirming user, and the
        message, its sender and its receipt time were nowhere in the dossier. Per record: the message
        as received, three times (stated occurrence, received, confirmed), the performer as entered
        (never inferred from the sender), what this record carries for 21 CFR 112.161(a)(2), (a)(4)
        and (b), what the machine proposed and what was applied, and anything changed since. Facts
        about each record, never a verdict. Rendered only when such records exist.
        """
        from history.services.crew_note_provenance import lines, provenance_for

        events = []
        for production in self._scope_productions():
            for _label, accessor in self._SIGNOFF_EVENT_SOURCES:
                if getattr(production, accessor, None) is None:
                    continue
                events.extend(related_events(production, accessor))
        found = provenance_for(events)
        if not found:
            return []
        elements = [
            self._spacer(0.15),
            self._section_header("Records Confirmed From Crew Messages"),
            Paragraph(
                "Each record below was confirmed by a supervisor from a message a crew member sent. The "
                "sender, the person who performed the work and the person who confirmed the record are "
                "listed separately, as are the time the work is stated to have happened, the time the "
                "message arrived and the time it was confirmed.",
                self._styles["footer_note"],
            ),
        ]
        from history.services.crew_note_provenance import event_type_of

        by_id = {(event_type_of(ev), ev.pk): ev for ev in events}
        by_id = {k: ev for k, ev in by_id.items() if k in found}
        for key in sorted(by_id, key=lambda k: str(getattr(by_id[k], "date", "") or "")):
            ev = by_id[key]
            record = getattr(ev, "name", None) or ev.description or "Record"
            kind = self._AMENDMENT_RECORD_KINDS.get(key[0], "Record")
            elements.append(self._spacer(0.06))
            elements.append(Paragraph(f"<b>{_esc(kind)}: {_esc(str(record))}</b>", self._styles["body"]))
            for line in lines(found[key], ev):
                elements.append(Paragraph(_esc(line), self._styles["body"]))
        return elements

    # Event-type keys (history.constants) to the words this document already uses for a
    # record elsewhere. "Event #423" is a primary key: it tells an inspector nothing and
    # cannot be cross-referenced against the rest of the packet, which identifies records
    # by kind and date.
    _AMENDMENT_RECORD_KINDS = {
        0: "Weather",
        1: "Production",
        2: "Input application",
        3: "General",
        4: "Equipment",
        5: "Soil management",
        6: "Pest management",
        7: "Sales & compliance",
    }

    def _amended_record_label(self, amendment):
        """Which record was corrected, in terms an inspector can look up.

        Resolved at render time rather than denormalised onto the amendment: the event is
        locked and undeletable for the retention period, so it is still there, and reading
        it live means a later correction to the event's own date is reflected here too.
        Falls back to the id if the row is somehow gone — an unlabelled correction is
        still better than a missing one.

        Plain text with a comma, NOT a "<br/>": `_cell` runs values through `_esc`, so
        markup injected here prints literally ("Sales & compliance<br/>2025-10-17" — seen
        in a rendered proof). That escaping is deliberate operator-input protection and is
        not something this label should be routed around; the column wraps on its own.
        """
        # F7 (2026-08-21) — an amendment with NO event target corrects the SEASON HEADER.
        # It prints in this same table on purpose: a certifier reading "Documented
        # Corrections" wants one chronological list, not a header table beside an event one.
        if amendment.event_type is None and amendment.event_id is None:
            lot = (getattr(self.production, "lot_id", "") or "").strip()
            return f"Season header, lot {lot}" if lot else "Season header"

        kind = self._AMENDMENT_RECORD_KINDS.get(amendment.event_type, "Record")
        try:
            from history.constants import EVENT_TYPE_TO_MODEL

            model = EVENT_TYPE_TO_MODEL.get(amendment.event_type)
            event = model.objects.filter(pk=amendment.event_id).only("date").first() if model else None
            if event is not None and getattr(event, "date", None):
                return f"{kind}, {event.date.strftime('%Y-%m-%d')}"
        except Exception:  # noqa: BLE001 - a label must never break the dossier
            pass
        return f"{kind}, #{amendment.event_id}"

    def _amendments_table(self):
        """Corrections made to this season's events after it was filed.

        Renders nothing when there are none — an empty "Corrections" heading invites the
        question "why is this here?", and the answer ("nothing was corrected") is better
        told by the section's absence than by an empty table.
        """
        from history.models import EventAmendment

        amendments = list(
            EventAmendment.objects.filter(history=self.production).select_related("amended_by").order_by("created_at")
        )
        if not amendments:
            return []

        elements = [
            self._spacer(0.15),
            self._section_header("Documented Corrections"),
            Paragraph(
                "Corrections made to this season's records after it was finished — including to "
                "the lot header itself. The original entry is retained beside each correction, "
                "with the reason given at the time.",
                self._styles["footer_note"],
            ),
            self._spacer(0.05),
        ]

        headers = ["Corrected", "Record corrected", "Field", "Originally recorded", "Corrected to", "Reason", "By"]
        data = [[self._hdr(h) for h in headers]]
        for a in amendments:
            data.append(
                [
                    self._cell(a.created_at.strftime("%Y-%m-%d")),
                    self._cell(self._amended_record_label(a)),
                    self._cell(a.field_label or a.field_name),
                    # An empty original means the field was blank before. Say so, rather
                    # than leaving a cell an inspector has to interpret.
                    self._cell(a.original_value or "(blank)"),
                    self._cell(a.corrected_value or "(blank)"),
                    self._cell(a.reason),
                    self._cell((a.amended_by_name or "").strip() or "-"),
                ]
            )

        # Seven columns, 7.00in — the frame is letter minus 0.75in margins each side
        # (SimpleDocTemplate above). This first shipped summing to 7.30in, overflowing
        # 0.30in into the right margin so the "By" column printed outside the printable
        # area: the same wrong premise corrected elsewhere in this file on 2026-08-17.
        # Budget goes to Reason (a sentence, and the thing that makes a correction
        # legible to an inspector) and to the two value columns; Date, Record and By are
        # short and predictable.
        col_widths = [
            0.70 * inch,  # Corrected (date; rows are ordered oldest-first)
            1.30 * inch,  # Record corrected (kind + the record's own date)
            0.80 * inch,  # Field
            0.95 * inch,  # Originally recorded
            0.95 * inch,  # Corrected to
            1.45 * inch,  # Reason
            0.85 * inch,  # By
        ]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(self._base_table_style())
        elements.append(t)
        return elements

    def _photo_reuse_findings(self, category_events):
        """Flag the same image attached to more than one event.

        An inspector reading two different spray dates backed by the identical
        photograph treats it as fabricated evidence, and under SOE 7 CFR
        205.201(a)(3) fraud prevention that is exactly the pattern to surface.
        The existing photo checks look at file size, format, blankness and
        timestamp — none of them notice reuse. Found on 2026-08-03: one dossier
        backed a trunk-injection event and an airblast event with the same two
        images, across three different crops.

        Identity is the storage key (s3_key / image_url), which is what actually
        proves two events point at one file.
        """
        seen = {}
        for category_label, events in category_events:
            for ev in events:
                album = getattr(ev, "album", None)
                if album is None:
                    continue
                try:
                    images = list(album.images.all())
                except Exception:  # noqa: BLE001 — never break the PDF over photos
                    continue
                for img in images:
                    key = (img.s3_key or "").strip() or (img.image_url or "").strip()
                    if not key:
                        continue
                    # Dedup on the EVENT, never on the rendered label: two distinct
                    # events in one category on one date share a label, and keying
                    # on that hid real reuse between them.
                    event_key = (type(ev).__name__, getattr(ev, "pk", id(ev)))
                    label = f"{category_label} · {_fmt_date(ev.date)}"
                    seen.setdefault(key, {})
                    seen[key][event_key] = label

        reused = {k: list(v.values()) for k, v in seen.items() if len(v) > 1}
        if not reused:
            return []

        elements = [self._spacer(0.08)]
        elements.append(
            Paragraph(
                f"<b>[REVIEW] Photo evidence reuse: {len(reused)} image(s) are attached to more "
                "than one event.</b> The same photograph cannot document two separate operations. "
                "Replace the duplicates with photographs taken at each operation, or remove them — "
                "an inspector assessing SOE fraud-prevention (7 CFR 205.201(a)(3)) will read "
                "repeated evidence as fabricated.",
                self._warning_style(),
            )
        )
        rows = [[self._hdr(h) for h in ("Image", "Attached to")]]
        for idx, (key, labels) in enumerate(sorted(reused.items(), key=lambda kv: -len(kv[1]))[:15], start=1):
            rows.append([self._cell(f"Image {idx}"), self._cell("; ".join(labels))])
        table = Table(rows, colWidths=[1.0 * inch, 6.0 * inch], repeatRows=1)
        table.setStyle(self._base_table_style())
        elements.append(table)
        return elements

    # Reverse-relation accessors, internal plumbing and consumer/CRM columns that
    # auditlog records but which mean nothing to a certifier. Printing
    # `history_pestmanagementevent_events`, `favorited_by` or `buyer_doc_requests`
    # in a regulatory document leaks the ORM schema and reads as unprofessional
    # (2026-08-03 dossier review).
    _CHANGE_LOG_HIDDEN_FIELDS = frozenset(
        {
            "id",
            "index",
            "public_id",
            "album",
            "history",
            "reviews",
            "favorited_by",
            "buyer_doc_requests",
            "cover_image_url",
            "history_scans",
            "sales_records",
            "updated_at",
            "extra_data",
        }
    )

    @classmethod
    def _inspector_field_list(cls, changes_dict):
        """Human-readable field names for the certifier, ORM noise removed."""
        if not changes_dict:
            return "—"
        names = [
            f
            for f in changes_dict.keys()
            if f not in cls._CHANGE_LOG_HIDDEN_FIELDS and not f.startswith("history_") and not f.endswith("_events")
        ]
        if not names:
            return "(internal fields only)"
        return ", ".join(n.replace("_", " ") for n in sorted(names))

    # Post-harvest handling differs by crop; the old text asserted tree-nut steps
    # (hulling, drying) on every dossier, including avocados and citrus.
    _POST_HARVEST_STEPS = {
        "tree_nut": "Tree-nut crops are typically hulled, dried, and cold-stored after harvest.",
        "tree_fruit": "Tree fruit is typically washed, graded, packed, and cold-stored after harvest.",
        "berry": "Berries are typically field-packed and moved straight into cold storage.",
        "vegetable": "Vegetables are typically washed, cooled, graded, and packed after harvest.",
        "grain": "Grain is typically dried, cleaned, and binned after harvest.",
        "oilseed": "Oilseed is typically dried, cleaned, and binned after harvest.",
        "legume": "Legumes are typically dried, cleaned, and binned after harvest.",
    }
    _POST_HARVEST_DEFAULT = "Post-harvest handling and storage steps vary by crop."

    def _post_harvest_steps_phrase(self):
        category = None
        try:
            crop = self.production.crop_type
            category = getattr(crop, "category", None)
        except Exception:  # noqa: BLE001 — never break the PDF over a label
            category = None
        return self._POST_HARVEST_STEPS.get(category, self._POST_HARVEST_DEFAULT)

    # ------------------------------------------------------------------
    # CSV generation — public entry point
    # ------------------------------------------------------------------

    def generate_csv(self):
        """
        Return a BytesIO containing a UTF-8 BOM CSV with all events
        in chronological order.
        """
        buffer = io.BytesIO()
        # UTF-8 BOM for Excel compatibility
        buffer.write(b"\xef\xbb\xbf")

        wrapper = io.TextIOWrapper(buffer, encoding="utf-8", newline="", write_through=True)
        writer = csv.writer(wrapper)

        headers = [
            "Date",
            "Event Category",
            "Event Type",
            "Description",
            "Product / Input",
            "Amount",
            "Unit",
            # Derived per-area rate, mirroring the PDF's "Amount / Rate" column (2026-08-01).
            # A spreadsheet gets its own column rather than the PDF's parenthetical so it can
            # be sorted and filtered.
            "Rate",
            "Method",
            "Operator",
            "Photos Count",
            "Carbon (kg CO2e)",
            "Notes",
            "Supplier",
            "Purchase Date",
            "Invoice #",
            "Concentration / NPK",
            "Organic Status",
            "REI (hrs)",
            "PHI (days)",
        ]

        # Drop the carbon column ONCE, here, rather than in each of the seven per-event-type
        # row builders below. Editing seven parallel lists to stay index-aligned with one
        # header is exactly how a CSV desynchronises; projecting at write time cannot.
        # `carbon_col` is None when the column stays.
        carbon_col = None if self.carbon_in_scope else headers.index("Carbon (kg CO2e)")

        def _project(row):
            """Row as written: identical unless the carbon column is out of scope."""
            if carbon_col is None:
                return row
            return [v for i, v in enumerate(row) if i != carbon_col]

        if carbon_col is not None:
            headers = _project(headers)

        # The PDF's specimen marking, in the one form a CSV can carry. Written ABOVE the
        # header row so it cannot be scrolled past, and so a reader who opens only this file
        # sees it — the packet's two formats travel separately, and the documented failure in
        # this codebase is a rule enforced on the PDF that "the CSV never got".
        #
        # It costs the strict-parser contract (headers are no longer row 1) and that is the
        # right trade for a fabricated record: this file is read by people in Excel, and a
        # machine parser hitting an unexpected first row fails loudly, which for a synthetic
        # compliance record is the outcome we want.
        if self._is_specimen():
            writer.writerow([SPECIMEN_LINE])

        writer.writerow(headers)

        all_rows = []

        # 7 extra columns for NOP traceability (chemical-only, others padded with "")
        nop_pad = ["", "", "", "", "", "", ""]

        # --- Production Events ---
        # CSV-specific harvest_method labels (mirrors the PDF table above and
        # the frontend HARVEST_METHOD_LABELS registry for consistency).
        _CSV_HARVEST_METHOD_LABELS = {
            "hand_picking": "Hand Picking",
            "selective_hand_picking": "Selective Hand Picking",
            "mechanical": "Mechanical Harvester",
            "shake_and_catch": "Shake and Catch",
            "strip_picking": "Strip Picking",
            "manual": "Manual Harvest",
            "mixed": "Mixed (Manual + Mechanical)",
        }

        for ev in self.production.history_productionevent_events.all():
            extra = ev.extra_data or {}

            # HA-specific columns: yield takes precedence over fuel, variety fills
            # Product/Input, harvest_method fills Method. Non-HA events keep the
            # fuel-centric default layout so existing exports don't change shape.
            if ev.type == "HA":
                if ev.yield_quantity:
                    amount = _fmt_float(ev.yield_quantity)
                    unit = _val(ev.yield_unit, "")
                else:
                    amount = _fmt_float(ev.fuel_consumed) if ev.fuel_consumed else ""
                    unit = _val(ev.fuel_unit, "") if ev.fuel_consumed else ""
                product_input = _val(ev.variety) or ""
                csv_rate = _rate_per_area(ev.yield_quantity, ev.area_covered, ev.yield_unit, ev.area_unit) or ""
                method_raw = getattr(ev, "harvest_method", None) or extra.get("harvest_method") or ""
                structured_method = (
                    _CSV_HARVEST_METHOD_LABELS.get(method_raw, _humanize_enum(method_raw) or "") if method_raw else ""
                )
                # Combine structured dropdown + free-text production_method so the CSV
                # carries the same hand-labor narrative the PDF Harvest Records table
                # surfaces (and the consumer QR card shows). Avoids duplicating when
                # the two strings are identical (case-insensitive).
                freetext_method = (extra.get("method") or extra.get("production_method") or "").strip()
                if structured_method and freetext_method and freetext_method.lower() != structured_method.lower():
                    method_val = f"{structured_method} ({freetext_method})"
                elif structured_method:
                    method_val = structured_method
                else:
                    method_val = freetext_method
            else:
                amount = _fmt_float(ev.fuel_consumed) if ev.fuel_consumed else ""
                unit = _val(ev.fuel_unit, "") if ev.fuel_consumed else ""
                product_input = ""
                csv_rate = ""
                # Non-HA: free-text production_method from extra_data (manual-labor
                # documentation for thinning/pruning/etc.)
                method_val = _val(extra.get("method") or extra.get("production_method"), "")

            # A partial pick is the one harvest row whose yield cannot be read against the
            # block's full acreage, and the per-area Rate column is computed from
            # area_covered regardless. The PDF gets a Partial-Area Harvests table; the CSV
            # carries the same locator in Notes.
            # Build from a parts list, NOT by seeding with _val(). _val() returns an em-dash for
            # an empty value and an em-dash is TRUTHY, so seeding shipped "— | Applied scope: …"
            # in every Notes cell that had a scope but no field note. _val() at the end still
            # supplies the em-dash when the cell is genuinely empty.
            prod_note_parts = []
            if ev.observation:
                prod_note_parts.append(str(ev.observation))
            prod_scope = self._applied_scope_display(ev)
            if prod_scope:
                prod_note_parts.append(f"Applied scope: {prod_scope}")
            prod_notes = _val(" | ".join(prod_note_parts))

            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Production",
                        PRODUCTION_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        product_input,
                        amount,
                        unit,
                        csv_rate,
                        method_val,
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        prod_notes,
                    ]
                    + nop_pad,
                )
            )

        # --- Chemical Events ---
        for ev in self.production.history_chemicalevent_events.all():
            amount = _fmt_float(ev.volume_numeric) if ev.volume_numeric else _val(ev.volume, "")
            # Show the unit whether the amount came from volume_numeric or the
            # free-text volume string — a unitless amount is uninterpretable.
            unit = _val(ev.volume_unit, "") if (ev.volume_numeric or ev.volume) else ""
            # Same rate the PDF prints, in its own column so a spreadsheet can sort and filter
            # on it: the RECORDED label rate first, the derived one only for rows written before
            # `application_rate` existed.
            csv_rate = (
                _recorded_rate_text(ev)
                or _rate_per_area(ev.volume_numeric, ev.area_numeric, ev.volume_unit, ev.area_unit)
                or ""
            )
            # Same label map as the PDF's Input Application Log: the CSV is read by the same
            # certifier, so it must not be the one that says "air_blast".
            method = _method_label(ev.application_method_structured or ev.way_of_application)
            # Same § 205.103(b)(2) locator the PDF's Application Context table prints. Appended
            # to Notes rather than given a column so the CSV header stays stable for anyone
            # who already has a saved import mapping.
            # Parts list, not an _val() seed — see the Applied-scope note in the production
            # block above for why (em-dash is truthy).
            chem_note_parts = []
            if ev.observation:
                chem_note_parts.append(str(ev.observation))
            chem_scope = self._applied_scope_display(ev)
            if chem_scope:
                chem_note_parts.append(f"Treated scope: {chem_scope}")
            # The PDF's unreconciled-amount finding, on its sibling surface (2026-09-03). Six of
            # nine defects in the 2026-08-20 certifier sweep were "fixed on the audited surface,
            # alive on its sibling", and this CSV is read by the same certifier as the packet.
            #
            # It lands in Notes rather than replacing the Amount cell: Amount is a NUMBER column
            # a reviewer sorts and subtracts against purchase records, and prose in it would
            # break the mass balance this export exists to support. The PDF can say it in the
            # cell because that cell is prose already.
            if _amount_reconciles_with_rate(ev) is False:
                chem_note_parts.append(f"Amount {amount} {unit}".strip() + " does not reconcile to the recorded rate")
            chem_notes = _val(" | ".join(chem_note_parts))
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Chemical",
                        CHEMICAL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        _val(ev.commercial_name),
                        amount,
                        unit,
                        csv_rate,
                        _val(method),
                        _val(_applied_by(ev)),
                        str(_photo_count(ev)),
                        "",
                        chem_notes,
                        # NOP traceability columns
                        _val(ev.supplier_name),
                        _fmt_date(ev.purchase_date) if ev.purchase_date else "",
                        _val(ev.purchase_invoice),
                        _val(ev.concentration),
                        # Display label, not the raw enum. The PDF renders this field via
                        # get_organic_approved_display() (see _build_chemical_events), and the
                        # SOIL rows of this same CSV already use the display form — so a raw
                        # "omri_listed" here was inconsistent with both the sibling format and
                        # the neighbouring rows of its own file.
                        _val(_organic_basis_cell(ev)),
                        str(ev.rei_hours) if ev.rei_hours is not None else "",
                        str(ev.phi_days) if ev.phi_days is not None else "",
                    ],
                )
            )

        # --- Soil Management Events ---
        for ev in self.production.history_soilmanagementevent_events.all():
            amount = (
                _fmt_float(ev.amendment_amount_numeric)
                if ev.amendment_amount_numeric
                else _val(ev.amendment_amount, "")
            )
            unit = _val(ev.amendment_amount_unit, "") if ev.amendment_amount_numeric else ""
            # NOP: include organic approval and compost data in notes
            notes = ""
            if ev.amendment_organic_approved:
                notes = f"Organic: {_organic_basis_cell(ev, ev.amendment_organic_approved)}"
            # Nitrogen applied via the amendment. California's Irrigated Lands Regulatory
            # Program requires an annual Irrigation & Nitrogen Management Plan summary of
            # total nitrogen applied FROM ALL SOURCES — compost and manure included — so the
            # kg of N has to be readable off the packet, not just implied by a tonnage.
            _n_kg = _amendment_nitrogen_kg(ev)
            if _n_kg is not None:
                notes = (notes + " | " if notes else "") + (
                    f"N: {ev.amendment_nitrogen_percentage}% as-received = {_n_kg:,.0f} kg N"
                )
            if ev.type == "CO":
                compost_parts = []
                if ev.compost_peak_temp_f is not None:
                    compost_parts.append(f"Peak: {ev.compost_peak_temp_f}°F")
                if ev.compost_duration_days_at_temp is not None:
                    compost_parts.append(f"Days: {ev.compost_duration_days_at_temp}")
                if ev.compost_turning_count is not None:
                    compost_parts.append(f"Turns: {ev.compost_turning_count}")
                if compost_parts:
                    notes = (notes + " | " if notes else "") + ", ".join(compost_parts)
            if ev.manure_harvest_interval and ev.manure_harvest_interval != "na":
                manure_info = f"Manure interval: {ev.manure_harvest_interval} days"
                if ev.manure_application_date:
                    manure_info += f" (applied: {_fmt_date(ev.manure_application_date)})"
                # The PDF's manure table gained a "Planned Harvest" column (USDA's
                # "Date of Harvest — Estimated"); carry it here too. A field that reaches one
                # export and not the other is how the same production came to give two answers
                # about its buyer — see resolve_sales_disclosure().
                if ev.manure_harvest_date_planned:
                    manure_info += f" (planned harvest: {_fmt_date(ev.manure_harvest_date_planned)})"
                notes = (notes + " | " if notes else "") + manure_info
            # USDA form #9's "Manure Type, Form and Source" and "How Applied / Incorporated",
            # kept in step with the PDF's per-row detail lines for the same reason as above.
            #
            # Deliberately OUTSIDE the `manure_harvest_interval` guard the block above sits in:
            # composted and NOP 5006 manure carry interval "na", and an operation that records
            # "Chicken, dry, on farm" on a composted amendment would otherwise have it silently
            # dropped from the CSV while the PDF printed it.
            _manure_tfs = ev.manure_type_form_source_display()
            _manure_applied = ev.get_manure_application_method_display() if ev.manure_application_method else ""
            if _manure_tfs or _manure_applied:
                _bits = [b for b in (_manure_tfs, _manure_applied and f"applied: {_manure_applied}") if b]
                notes = (notes + " | " if notes else "") + "Manure: " + ", ".join(_bits)

            # Cover-crop species lives in extra_data, not amendment_type — surface it in the
            # Amendment column so the CSV matches the PDF (and doesn't drop the planted mix).
            _soil_ed = ev.extra_data if isinstance(ev.extra_data, dict) else {}
            amendment_label = _amendment_type_label(ev.amendment_type)
            if not ev.amendment_type and ev.type == "CC" and _soil_ed.get("cover_crop_species"):
                amendment_label = _soil_ed["cover_crop_species"]

            # Grazing detail (animal/count/days/purpose + rotation) has no dedicated columns —
            # fold it into notes so integrated grazing isn't dropped from the CSV dossier.
            if ev.type == "GR":
                _is_summary = _soil_ed.get("is_summary") in (True, "true")
                g_parts = []
                if ev.animal_type:
                    g_parts.append(f"{ev.animal_type}" + (f" x{ev.animal_count}" if ev.animal_count else ""))
                _g_days = _soil_ed.get("total_grazing_days") if _is_summary else ev.grazing_duration_days
                if _g_days not in (None, ""):
                    g_parts.append(f"{_g_days} grazing days")
                if _is_summary and _soil_ed.get("event_count"):
                    g_parts.append(f"{_soil_ed['event_count']} passes")
                if _is_summary and _soil_ed.get("date_start") and _soil_ed.get("date_end"):
                    g_parts.append(f"{_soil_ed['date_start']}–{_soil_ed['date_end']}")
                if ev.grazing_purpose:
                    g_parts.append(GRAZING_PURPOSE_LABELS.get(ev.grazing_purpose, ev.grazing_purpose))
                if g_parts:
                    notes = (notes + " | " if notes else "") + "Grazing: " + ", ".join(g_parts)

            # NOP pad: organic status goes in column index 16 (Organic Status).
            # Use get_<field>_display() so the inspector sees "OMRI Listed", not raw
            # "omri_listed" codes — matches the other two render sites in this file.
            soil_nop = [
                "",
                "",
                "",
                "",
                _organic_basis_cell(ev, ev.amendment_organic_approved) or "",
                "",
                "",
            ]
            csv_rate = (
                _rate_per_area(ev.amendment_amount_numeric, ev.area_covered, ev.amendment_amount_unit, ev.area_unit)
                or ""
            )
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Soil Management",
                        SOIL_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        amendment_label,
                        amount,
                        unit,
                        csv_rate,
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        notes,
                    ]
                    + soil_nop,
                )
            )

        # --- Pest Management Events ---
        for ev in self.production.history_pestmanagementevent_events.all():
            # NOP: include identification and threshold data in notes.
            # Parts list, not an _val() seed — em-dash is truthy, so seeding prefixed every
            # composed Notes cell with "— | ". Predates the trap columns; same defect.
            note_parts = []
            if ev.pest_pressure_level:
                note_parts.append(str(ev.pest_pressure_level))
            if ev.identified_by:
                note_parts.append(f"ID by: {ev.get_identified_by_display()}")
            if ev.threshold_rationale:
                note_parts.append(f"Rationale: {ev.threshold_rationale[:60]}")
            # The PDF's Beneficial-Release & Trap Detail table carries the trap triple; the CSV
            # is read by the same certifier, so it must not be the surface where the monitoring
            # evidence disappears. A catch is meaningless without the trap count beside it.
            trap_bits = []
            if ev.trap_type:
                trap_bits.append(ev.get_trap_type_display())
            if ev.trap_count is not None:
                trap_bits.append(f"{ev.trap_count} traps")
            if ev.pest_catch_count is not None:
                trap_bits.append(f"{ev.pest_catch_count} caught")
            if trap_bits:
                note_parts.append("Traps: " + ", ".join(trap_bits))
            notes = _val(" | ".join(note_parts))
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Pest Management",
                        PEST_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        _val(ev.pest_species),
                        "",
                        "",
                        "",  # Rate (no area on this event type)
                        _val(ev.ipm_strategy),
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        notes,
                    ]
                    + nop_pad,
                )
            )

        # --- Equipment Events ---
        for ev in self.production.history_equipmentevent_events.all():
            fuel = ev.fuel_consumed or ev.fuel_amount
            amount = _fmt_float(fuel) if fuel else ""
            unit = _val(ev.fuel_unit, "") if fuel else ""
            hours = ev.hours_operated or ev.hours_used
            csv_rate = ""  # EquipmentEvent carries no treated area to derive a rate from
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Equipment",
                        EQUIPMENT_TYPE_LABELS.get(ev.type, _val(ev.type)),
                        _val(ev.description),
                        _val(ev.equipment_name),
                        amount,
                        unit,
                        csv_rate,
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        _val(str(hours) if hours else None),
                    ]
                    + nop_pad,
                )
            )

        # --- General Events ---
        for ev in self.production.history_generalevent_events.all():
            # NOP: flag contamination incidents in category and notes
            category = "Contamination Incident" if ev.is_contamination_incident else "General"
            notes = _val(ev.observation)
            if ev.is_contamination_incident:
                parts = []
                if ev.contamination_source:
                    parts.append(f"Source: {ev.get_contamination_source_display()}")
                if ev.corrective_action_taken:
                    parts.append(f"Action: {ev.corrective_action_taken[:60]}")
                if ev.certifier_notified:
                    date_str = (
                        _fmt_date(ev.certifier_notification_date) if ev.certifier_notification_date else "date not set"
                    )
                    parts.append(f"Certifier notified: {date_str}")
                notes = " | ".join(parts) if parts else notes
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        category,
                        _val(ev.activity_type),
                        _val(ev.description),
                        "",
                        "",
                        "",
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        notes,
                    ]
                    + nop_pad,
                )
            )

        # --- Weather Events ---
        for ev in self.production.history_weatherevent_events.all():
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Weather",
                        _val(ev.type),
                        _val(ev.description),
                        "",
                        "",
                        "",  # Rate (no area on this event type)
                        "",
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        _val(ev.observation),
                    ]
                    + nop_pad,
                )
            )

        # --- Business Events ---
        for ev in self.production.history_businessevent_events.all():
            all_rows.append(
                (
                    ev.date,
                    [
                        _fmt_date(ev.date),
                        "Business",
                        _val(ev.type),
                        _val(ev.description),
                        "",
                        "",
                        "",  # Rate (no area on this event type)
                        "",
                        "",
                        _val(ev.performed_by),
                        str(_photo_count(ev)),
                        "",
                        "",
                    ]
                    + nop_pad,
                )
            )

        # Sort all rows chronologically; None dates sort to the end
        all_rows.sort(key=lambda r: (r[0] is None, r[0]))

        for _, row in all_rows:
            writer.writerow(_project(row))

        # --- Custom Fields section ---
        if "custom_data" in self.sections:
            from history.custom_fields import extract_custom_fields_for_display

            writer.writerow([])
            writer.writerow(["=== ADDITIONAL FARMER-RECORDED DATA (Custom Fields) ==="])
            writer.writerow(["Event Date", "Event Category", "Event Description", "Field Name", "Field Value", "Type"])

            event_querysets = [
                ("Production", self.production.history_productionevent_events.all()),
                ("Chemical", self.production.history_chemicalevent_events.all()),
                ("Soil Management", self.production.history_soilmanagementevent_events.all()),
                ("Pest Management", self.production.history_pestmanagementevent_events.all()),
                ("Equipment", self.production.history_equipmentevent_events.all()),
                ("General", self.production.history_generalevent_events.all()),
                ("Weather", self.production.history_weatherevent_events.all()),
                ("Business", self.production.history_businessevent_events.all()),
            ]

            for category_label, qs in event_querysets:
                for ev in qs:
                    extra = getattr(ev, "extra_data", None)
                    if not extra or not isinstance(extra, dict):
                        continue
                    custom_fields = extract_custom_fields_for_display(
                        extra, visibility_filter="all", include_empty=False
                    )
                    for cf in custom_fields:
                        writer.writerow(
                            [
                                _fmt_date(ev.date),
                                category_label,
                                _val(ev.description),
                                cf.get("label", ""),
                                cf.get("value", ""),
                                cf.get("field_type", "text"),
                            ]
                        )

        # --- Records confirmed from crew messages (OSP alignment audit T29) ---
        # Always written when such records exist, whatever sections were asked for: it is the
        # provenance of rows already in this file, not a separate topic.
        self._write_crew_message_csv(writer)

        # --- Certifications section ---
        if "certifications" in self.sections:
            writer.writerow([])
            writer.writerow(["=== ACTIVE CERTIFICATIONS ==="])
            writer.writerow(
                [
                    "Certification Type",
                    "Certifier",
                    "Certificate #",
                    "Effective Date",
                    "Expiry Date",
                    "Active",
                    "Verification Status",
                ]
            )
            try:
                from certifications.models import Certification

                establishment = self.production.parcel.establishment
                today = date.today()
                for cert in Certification.objects.filter(establishment=establishment).order_by("certification_type"):
                    expiry_display = _fmt_date(cert.expiry_date)
                    if cert.expiry_date:
                        days_remaining = (cert.expiry_date - today).days
                        if days_remaining < 0:
                            expiry_display = f"{expiry_display} (EXPIRED)"
                        elif days_remaining <= 90:
                            expiry_display = f"{expiry_display} (expires in {days_remaining}d)"
                    writer.writerow(
                        [
                            cert.get_certification_type_display(),
                            _val(cert.certifier_name),
                            _val(cert.certification_number),
                            _fmt_date(cert.effective_date),
                            expiry_display,
                            "Yes" if cert.is_active else "No",
                            cert.get_verification_status_display(),
                        ]
                    )
            except Exception as exc:
                logger.warning("CSV certifications section error: %s", exc)
                writer.writerow(["Error loading certification data"])

        # --- State Organic Program Registration section ---
        # Mirrors the PDF _build_state_organic_registration_section so a CSV-only
        # certifier handoff also carries the CDFA SOP producer-registration status
        # (CA Food & Ag Code §§ 46000-46029), not just the OSP + events.
        if "state_organic_registration" in self.sections:
            writer.writerow([])
            writer.writerow(["=== STATE ORGANIC PROGRAM REGISTRATION ==="])
            try:
                from certifications.models import StateOrganicRegistration

                establishment = self.production.parcel.establishment
                reg = (
                    StateOrganicRegistration.objects.filter(establishment=establishment)
                    .order_by("-registration_date")
                    .first()
                )
                if reg is None:
                    # 🔴 2026-08-20 — this row asserted the California requirement flatly, for
                    # every operation in every state. The PDF sibling
                    # (_build_state_organic_registration_section) has gated on the operation's
                    # state since it was written; the CSV copy never did, so a Washington
                    # apple grower's machine-readable export told their WSDA reviewer they
                    # were in breach of the California Food & Agricultural Code. A [REVIEW]
                    # flag naming a statute that does not apply is worse than no flag: it
                    # spends the reviewer's attention and Trazo's credibility at once.
                    est_state = resolve_establishment_state(establishment)
                    writer.writerow(["Field", "Value"])
                    if est_state in ("CA", None):
                        writer.writerow(
                            [
                                "Registration on file",
                                "None — CA producers selling > $5,000/yr organic must register with the "
                                "CDFA State Organic Program before first sale "
                                "(CA Food & Ag Code §§ 46000-46029). [REVIEW]",
                            ]
                        )
                    else:
                        writer.writerow(
                            [
                                "Registration on file",
                                "None. The CDFA State Organic Program producer-registration requirement is "
                                f"California state law; this operation is recorded in {est_state}, where a "
                                "state organic program may not apply. Verify state requirements with the "
                                "certifier.",
                            ]
                        )
                else:
                    gross = reg.prior_year_organic_gross_sales
                    commodities = reg.commodities if isinstance(reg.commodities, list) else []
                    writer.writerow(["Field", "Value"])
                    for label, value in [
                        ("Program", reg.program_name),
                        ("State", reg.state),
                        ("Operation Type", reg.get_operation_type_display()),
                        ("Status", reg.get_status_display()),
                        ("Registration #", reg.registration_number),
                        ("County", reg.county),
                        ("Registration Date", _fmt_date(reg.registration_date)),
                        ("Renewal Date", _fmt_date(reg.renewal_date)),
                        ("Prior-Year Organic Gross Sales", f"${gross:,.2f}" if gross is not None else ""),
                        ("Commodities", ", ".join(str(c) for c in commodities) if commodities else ""),
                    ]:
                        writer.writerow([label, _val(value)])
                    if not reg.is_current:
                        writer.writerow(
                            ["[REVIEW]", "Registration not current (status not 'registered' or renewal date passed)."]
                        )
                    try:
                        over_threshold = gross is not None and gross > Decimal("5000")
                    except (TypeError, InvalidOperation):
                        over_threshold = False
                    if reg.status == "exempt" and over_threshold:
                        writer.writerow(
                            [
                                "[REVIEW]",
                                f"$5,000 exemption exceeded (${gross:,.2f}) but status still 'exempt' — "
                                "operation must register with CDFA SOP and be certified.",
                            ]
                        )
            except Exception as exc:
                logger.warning("CSV state organic registration section error: %s", exc)
                writer.writerow(["Error loading state organic registration data"])

        # --- Inspection & Compliance Event History section ---
        # Mirrors the PDF _build_business_events_section so CSV consumers (auditors
        # parsing structured data) get the same cert #, inspector, and status
        # traceability that the PDF presents visually.
        if "business_events" in self.sections:
            business_events = related_events(self.production, "history_businessevent_events")
            if business_events:
                writer.writerow([])
                writer.writerow(["=== INSPECTION & COMPLIANCE EVENT HISTORY ==="])
                writer.writerow(
                    [
                        "Date",
                        "Activity",
                        "Certification",
                        "Certifier / Auditor",
                        "Certificate #",
                        "Performed By",
                        "Recorded By",
                        "Status",
                        "Sustainability Practice",
                        "Observations",
                    ]
                )
                for ev in business_events:
                    try:
                        cert_display = ev.get_certification_type_display() if ev.certification_type else ""
                    except Exception:
                        cert_display = _val(ev.certification_type)
                    try:
                        status_display = ev.get_verification_status_display() if ev.verification_status else ""
                    except Exception:
                        status_display = _val(ev.verification_status)
                    # Run 7 (R7-04): mirror the PDF. The performer is not an inspector, and a
                    # "Verified" the operator selected is self-reported.
                    if status_display and status_display.strip().lower() == "verified":
                        status_display = "Verified (self-reported)"
                    recorder = getattr(ev, "created_by", None)
                    recorded_by = ((recorder.get_full_name() or "").strip() or recorder.email) if recorder else ""
                    try:
                        biz_display = ev.get_business_type_display() if ev.business_type else ""
                    except Exception:
                        biz_display = _val(ev.business_type)

                    practice_display = ""
                    if ev.sustainability_practice:
                        try:
                            practice_display = ev.get_sustainability_practice_display()
                        except Exception:
                            practice_display = _humanize_enum(ev.sustainability_practice)

                    writer.writerow(
                        [
                            _fmt_date(ev.date),
                            biz_display,
                            cert_display,
                            _val(ev.verified_certifier_name),
                            _val(ev.certificate_number),
                            _val(ev.performed_by),
                            recorded_by,
                            status_display,
                            practice_display,
                            _val(ev.observation),
                        ]
                    )

        # --- Yield-to-sales reconciliation ---
        #
        # 🔴 2026-09-24 — THE SIBLING, again. The PDF section was renamed off "Mass-Balance
        # Audit Summary" and scoped in the same change, and this CSV twin kept the old header.
        # The section key stays `mass_balance` because it is a stored `sections` selector that
        # callers and saved exports already carry; only what a READER sees changes.
        if "mass_balance" in self.sections:
            writer.writerow([])
            writer.writerow(["=== YIELD-TO-SALES RECONCILIATION ==="])
            writer.writerow(
                [
                    "Scope: this production's harvest records against this production's own "
                    "sales records, whatever date those sales carry. Not a period inventory "
                    "balance; no opening or closing inventory is modelled."
                ]
            )
            writer.writerow(["Field", "Value"])
            p = self.production
            harvest_amount, harvest_unit, harvest_basis = self._resolve_harvest_total()
            # The CSV export had NO SalesRecord fallback at all, so for any operation
            # recording sales the SOE-supported way it reported "Sold To: —" while the PDF
            # of the same production itemised the buyer. Same production, two exports, two
            # answers — the defect this sweep exists to close.
            _csv_sales = resolve_sales_disclosure(p)
            quantity_sold = _csv_sales.quantity
            sold_unit = _val(_csv_sales.quantity_unit, harvest_unit)
            writer.writerow(
                [
                    "Harvest Yield",
                    f"{_fmt_float(harvest_amount)} {harvest_unit}".strip() if harvest_amount else "\u2014",
                ]
            )
            writer.writerow(["Harvest basis", harvest_basis])
            writer.writerow(
                [
                    "Quantity Sold",
                    f"{_fmt_float(quantity_sold)} {sold_unit}".strip() if quantity_sold else "\u2014",
                ]
            )
            writer.writerow(["Sold To", _val(_csv_sales.buyer)])
            writer.writerow(["Sale Date", _fmt_date(_csv_sales.sale_date) if _csv_sales.sale_date else "\u2014"])
            # 🔴 2026-09-24 — the absence of an attestation is not a denial.
            #
            # A flat "No" here states that the operation shipped organic product on documents
            # that did not identify it as organic: a § 205.307(a) / SOE non-conformance, asserted
            # about a crop that may still be on the tree. The PDF branch was corrected on
            # 2026-08-19 and this CSV twin was not — same production, two exports, two answers.
            writer.writerow(
                [
                    "Organic on Invoice",
                    (
                        ("Yes" if _csv_sales.organic_on_invoice else "No")
                        if (_csv_sales.buyer or quantity_sold or _csv_sales.sale_date)
                        else "Not applicable yet \u2014 no sales recorded for this production"
                    ),
                ]
            )
            # Zero is not missing: an uninvoiced remainder is a normal state and is stated as
            # one, with the date it was measured. Mirrors the PDF's Output Reconciliation.
            #
            # ⚠️ The unit-match guard is NOT the outer condition. `resolve_sales_disclosure`
            # reports `quantity_unit` as the FIRST row's unit, so a lot sold partly in lb and
            # partly in boxes fails this comparison and, with the guard outermost, the whole
            # block was skipped and the section printed nothing at all — the same silence this
            # row was added to remove, one branch over. Sales that exist but cannot be summed
            # are stated as such; the unit comparison only decides whether a BALANCE is
            # arithmetically meaningful.
            _csv_has_sales = bool(_csv_sales.buyer or _csv_sales.sale_date or quantity_sold)
            _csv_units_match = self._canonical_unit(harvest_unit) == self._canonical_unit(sold_unit)
            if harvest_amount and not _csv_units_match and _csv_has_sales:
                writer.writerow(
                    [
                        "Harvest minus sales recorded",
                        f"Not calculable as at {_fmt_generated_date()} \u2014 the sales records "
                        "for this production are not in one unit and cannot be summed. "
                        "Reconcile from the itemised sales.",
                    ]
                )
            elif harvest_amount and _csv_units_match:
                if quantity_sold:
                    _bal = float(harvest_amount) - float(quantity_sold)
                    writer.writerow(
                        ["Balance (Yield \u2212 Sold, same unit)", f"{_fmt_float(_bal)} {harvest_unit}".strip()]
                    )
                    if _bal > 0:
                        writer.writerow(
                            [
                                "Harvest minus sales recorded",
                                f"{_fmt_float(_bal)} {harvest_unit} as at {_fmt_generated_date()}, not reconciled: "
                                "shrink, culls, unsold product and unrecorded sales are not distinguished",
                            ]
                        )
                else:
                    # Same correction as the PDF branch: an unsummable or unstated quantity is
                    # not an absent sale. The legacy `History.quantity_sold` column is nullable
                    # even with a buyer on file.
                    writer.writerow(
                        [
                            "Harvest minus sales recorded",
                            (
                                f"Not calculable as at {_fmt_generated_date()} \u2014 sales are "
                                "recorded for this production but their quantities cannot be "
                                "summed. Reconcile from the itemised sales."
                                if _csv_has_sales
                                else f"{_fmt_float(harvest_amount)} {harvest_unit} harvested with "
                                f"no sales recorded for this production as at "
                                f"{_fmt_generated_date()}".strip()
                            ),
                        ]
                    )
            # Same source and same renderer as the PDF — the two exports of one production
            # disagreeing on a sales fact is the defect this resolver was extracted to end.
            writer.writerow(["Labeling Category (§ 205.301)", _label_category_display(_csv_sales)])
            # Inputs purchased sub-table
            writer.writerow([])
            # Same rows and totals as the PDF (run 7, R7-06), soil amendments included.
            _csv_rows, _csv_totals = _purchase_rows(
                related_events(p, "history_chemicalevent_events"),
                related_events(p, "history_soilmanagementevent_events"),
            )
            writer.writerow(
                ["Purchase Date", "Product", "Type", "Supplier", "Invoice #", "Lot #", "Qty Purchased", "Unit", "Note"]
            )
            for row in _csv_rows:
                ln = row.first
                writer.writerow(
                    [
                        _fmt_date(ln.purchase_date) if ln.purchase_date else "not recorded",
                        ln.product,
                        ln.type_label,
                        ln.supplier,
                        ln.invoice,
                        ln.lot,
                        _fmt_float(ln.quantity),
                        ln.unit,
                        _purchase_row_note(row).strip(" ()"),
                    ]
                )
            for unit, total in sorted(_csv_totals.items()):
                writer.writerow([f"Total Purchased ({unit})", _purchase_total_text(total, unit)])

        # --- Drift findings and input classifications (run 7, R7-08) ---
        # The PDF carried both; the CSV twin carried neither, so the structured export lost every
        # warning and every classification basis.
        if "drift_findings" in self.sections:
            drift_rows = []
            for family, relation, filters in (
                ("Chemical", "history_chemicalevent_events", {}),
                ("Soil", "history_soilmanagementevent_events", {}),
                ("Planting", "history_productionevent_events", {"type": "PL"}),
            ):
                for ev in related_events(self.production, relation, **filters):
                    dw = ev.drift_warning
                    if not dw:
                        continue
                    name = (
                        getattr(ev, "commercial_name", None)
                        or getattr(ev, "amendment_product_name", None)
                        or getattr(ev, "variety", None)
                    )
                    drift_rows.append(
                        [
                            _fmt_date(ev.date),
                            family,
                            _val(name),
                            _val(dw.get("reason_code")) if isinstance(dw, dict) else "",
                            _val(dw.get("reason")) if isinstance(dw, dict) else _val(dw),
                        ]
                    )
            writer.writerow([])
            writer.writerow(["=== INPUTS NOT MATCHED TO THE PLAN'S APPROVED INPUTS (drift findings) ==="])
            writer.writerow(["Date", "Record", "Input", "Reason code", "Reason (full)"])
            for row in drift_rows:
                writer.writerow(row)
            if not drift_rows:
                writer.writerow(["No drift finding is stored for this production's records."])
            writer.writerow([])
            writer.writerow(["=== NATIONAL LIST CLASSIFICATION OF CHEMICAL INPUTS ==="])
            writer.writerow(
                ["Date", "Input", "Classification (citable)", "Basis", "Unconfirmed listing", "Why unconfirmed"]
            )
            # Read through `national_list_basis`, the one rule for turning the stored field into a
            # statement: only a confirmed classification is citable; a legacy match or a partial
            # name suggestion is listed with its note, never as a classification.
            from history.services.national_list_basis import (
                confirmed_national_list_substance,
                unconfirmed_national_list,
            )

            for ev in related_events(self.production, "history_chemicalevent_events"):
                confirmed = confirmed_national_list_substance(ev)
                unconfirmed, note = unconfirmed_national_list(ev)
                writer.writerow(
                    [
                        _fmt_date(ev.date),
                        _val(ev.commercial_name),
                        _val(getattr(confirmed, "substance_name", None)) if confirmed else "not classified",
                        ev.get_national_list_basis_display() if confirmed else "",
                        _val(getattr(unconfirmed, "substance_name", None)) if unconfirmed else "",
                        note,
                    ]
                )

        # --- Field history section ---
        if "field_history" in self.sections:
            from product.models import ParcelCropHistory

            writer.writerow([])
            writer.writerow(["=== 3-YEAR FIELD & CROP ROTATION HISTORY ==="])
            try:
                parcel = self.production.parcel
                crop_history = list(ParcelCropHistory.objects.filter(parcel=parcel).order_by("-year")[:10])
                if crop_history:
                    writer.writerow(
                        [
                            "Year",
                            "Crop Grown",
                            "Production Method",
                            "Substances Applied",
                            "Last Prohibited Substance Date",
                            "Notes",
                        ]
                    )
                    for entry in crop_history:
                        writer.writerow(
                            [
                                str(entry.year),
                                # Same reasoning as the PDF table: a split field is two rows for
                                # one year, and the block is what tells them apart.
                                _val(f"{entry.crop_grown} ({entry.block_id})" if entry.block_id else entry.crop_grown),
                                entry.get_production_method_display() if entry.production_method else "\u2014",
                                _val(entry.substances_applied),
                                _fmt_date(entry.date_last_prohibited),
                                _val(entry.notes),
                            ]
                        )
                else:
                    writer.writerow(["No structured crop history. Showing previous productions on this parcel."])
                    from history.models import History

                    writer.writerow(
                        [
                            "Start Date",
                            "Finish Date",
                            "Crop",
                            "Production Method",
                            "Harvest Amount",
                            "Lot ID",
                        ]
                    )
                    prev_productions = list(
                        History.objects.filter(parcel=parcel)
                        .exclude(pk=self.production.pk)
                        .select_related("crop_type", "product")
                        .order_by("-start_date")[:15]
                    )
                    for prod in prev_productions:
                        crop_name = ""
                        try:
                            crop_name = (
                                prod.crop_type.name if prod.crop_type else (prod.product.name if prod.product else "")
                            )
                        except AttributeError:
                            pass
                        harvest = (
                            f"{_fmt_float(prod.production_amount)} {_val(prod.production_unit, '')}".strip()
                            if prod.production_amount
                            else "\u2014"
                        )
                        writer.writerow(
                            [
                                _fmt_date(prod.start_date),
                                _fmt_date(prod.finish_date),
                                _val(crop_name),
                                _val(prod.get_production_method_display() if prod.production_method else None),
                                harvest,
                                _val(prod.lot_id),
                            ]
                        )
            except AttributeError as exc:
                logger.warning("CSV field_history section error: %s", exc)
                writer.writerow(["Parcel data not available"])

        wrapper.flush()
        # Detach the TextIOWrapper from the BytesIO before returning. Without this, the wrapper is
        # garbage-collected when this frame exits and its __del__ CLOSES the underlying buffer — so
        # the caller (FileResponse / .getvalue()) receives a closed buffer ("I/O operation on closed
        # file"). detach() flushes and severs the link, leaving the BytesIO open and complete.
        wrapper.detach()
        buffer.seek(0)
        return buffer
