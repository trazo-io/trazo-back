"""A field the certifier packet PRINTS must be one a grower can actually fill in.

WHY (2026-08-15). The only conformance guard in the codebase ran one direction — registry
declares `form` → does the tab collect it — and it could not see a model column with no
registry entry at all. So the reverse defect went unnoticed for months, and it is the worse
of the two: the packet reads a field, nothing writes it, and every real grower's PDF prints
`—` in that cell forever.

Measured before this test existed:

    quantity_purchased   packet column "Qty Purchased"; readiness card demands it;
                         289 of 289 chemical events blank — because no input existed
    water_test_results   packet column "Results"; row rendered off date+lab, result blank
    cleaning_asset_class packet's answer to USDA's "Equipment or Surface"; zero occurrences
    harvest_destination  the § 205.103(b)(2) "Where Stored or Sold" hinge; zero occurrences

This test asserts the invariant rather than the instances: for every model field the export
service reads, SOMETHING must be able to write it — a form input, or an explicit entry in
SERVER_ASSIGNED below saying why not.

It is deliberately a source-level check. Importing the PDF builder and rendering it would
prove one production's output, not the invariant; and the failure mode here is structural.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parent.parent.parent
FRONTEND = BACKEND.parent / "trazo-app" / "src"
EXPORT_SERVICE = BACKEND / "history" / "services" / "audit_export_service.py"

FORM_TABS = [
    "views/Dashboard/Dashboard/components/forms/ProductionTab.jsx",
    "views/Dashboard/Dashboard/components/forms/ChemicalTab-ENHANCED.jsx",
    "views/Dashboard/Dashboard/components/forms/SoilManagementTab.jsx",
    "views/Dashboard/Dashboard/components/forms/PestManagementTab.jsx",
    "views/Dashboard/Dashboard/components/forms/WeatherTab.jsx",
    "views/Dashboard/Dashboard/components/forms/GeneralTab.jsx",
    "views/Dashboard/Dashboard/components/forms/BusinessTab-SIMPLIFIED.jsx",
    "views/Dashboard/Dashboard/components/forms/NewEvent.jsx",
    "config/quickEventFields.ts",
]

#: Fields the packet reads that NO form should write, each with the reason. Adding a name
#: here is a deliberate statement that a human is not the author of this value.
SERVER_ASSIGNED = {
    "drift_warning": "stamped by a post_save signal against the OSP approved-inputs list",
    "created_at": "auto",
    "updated_at": "auto",
    "created_by": "server-assigned from request.user",
    "index": "server-assigned ordering",
    "id": "pk",
    "lot_id": "assigned by the production, not typed on an event",
    "retention_until": "computed from date + § 205.103(b)(4)",
    "verification_level": "derived from photo/blockchain state",
    "transparency_score": "computed KPI, producer dashboard only",
    "carbon_data": "computed by the carbon service",
    "omri_product": "FK resolved from the OMRI catalog, not typed",
    "national_list_substance": "FK resolved from the National List catalog, not typed",
    "photo_content_flag": "internal Vision anti-gaming verdict",
    "album": "photo upload step, not a text input",
}

#: Model fields whose packet cell is fed by a DIFFERENT writable field. The packet reads the
#: left, the grower fills the right.
FED_BY = {
    "water_test_results": "water_test_summary (parsed into the JSON shape on save)",
    "working_depth": "depth / tillage_depth (remapped in NewEvent.onSubmit)",
    "seed_search_attempts": "the repeating NOP 5029 supplier-search widget",
    "custom_fields": "the Custom Fields editor",
    "extra_data": "container, not a field",
    "test_results": "the ST lab inputs (lab_name, lab_sample_id, lab_* readings), packed on submit",
    # Legacy string twins. The form writes the numeric field; the serializer keeps the old
    # string column in step. The packet reads whichever is populated.
    "volume": "volume_applied → volume_numeric (serializer maintains the legacy string twin)",
    "area": "area_treated → area_numeric (same legacy-twin arrangement)",
    "way_of_application": "application_method (serializer maps it via source=)",
    "application_method_structured": (
        "application_method. ⚠️ Nothing writes the *structured* column today, so the packet's "
        "preference for it never fires — tracked as a follow-up, not a blank cell, because "
        "way_of_application always carries the value."
    ),
    "activity_name": (
        "name. ⚠️ The GeneralTab input is LABELLED 'Activity Name' but binds `name`; the packet "
        "reads `activity_name or name`, so the cell fills — the label is the thing that lies."
    ),
    "description": "the notes box, via applyNotesField() in NewEvent.onSubmit",
}


def _model_field_names() -> set[str]:
    from history import models as m

    names: set[str] = set()
    for model in (
        m.WeatherEvent,
        m.ProductionEvent,
        m.ChemicalEvent,
        m.GeneralEvent,
        m.SoilManagementEvent,
        m.PestManagementEvent,
        m.BusinessEvent,
    ):
        for f in model._meta.get_fields():
            if hasattr(f, "attname"):
                names.add(f.name)
    return names


def _fields_read_by_packet(model_fields: set[str]) -> set[str]:
    """Names the export service reads off an event object.

    Matches `ev.<name>`, `getattr(ev, "<name>"`, and `event.<name>` — the three shapes the
    file actually uses — then intersects with real model fields so local variables and
    helper attributes cannot produce phantom failures.
    """
    src = EXPORT_SERVICE.read_text()
    found: set[str] = set()
    for pattern in (
        r"\bev\.([a-z_][a-z0-9_]*)",
        r"\bevent\.([a-z_][a-z0-9_]*)",
        r"getattr\(\s*(?:ev|event)\s*,\s*[\"']([a-z_][a-z0-9_]*)[\"']",
    ):
        found.update(re.findall(pattern, src))
    return found & model_fields


def _writable_names() -> set[str]:
    """Every name bound to an input, or remapped onto one, anywhere in the form layer."""
    names: set[str] = set()
    for rel in FORM_TABS:
        path = FRONTEND / rel
        if not path.exists():
            continue
        src = path.read_text()
        # strip comments so a mention can never stand in for an input — the exact defect
        # that let soil_moisture pass the sibling guard for months.
        src = re.sub(r"/\*[\s\S]*?\*/", " ", src)
        src = re.sub(r"(^|[^:])//[^\n]*", r"\1 ", src)
        for pattern in (
            r"register\(\s*['\"`]([a-zA-Z_][\w]*)['\"`]",
            r"name=\{?\s*['\"`]([a-zA-Z_][\w]*)['\"`]",
            r"^\s*([a-z_][\w]*)\s*:\s*data\.",  # payload key: data.x
            r"finalKey\s*=\s*['\"]([a-z_][\w]*)['\"]",
            r"cleaned\.([a-z_][\w]*)\s*=",
            r"[{,]\s*name:\s*['\"]([a-z_][\w]*)['\"]",  # quickEventFields / dynamic field maps
            r"\btarget\.([a-z_][\w]*)\s*=",  # applyNotesField(target, …) writes target.x
        ):
            names.update(re.findall(pattern, src, flags=re.M))
    return names


class PacketFieldsHaveWritersTests(SimpleTestCase):
    def test_every_field_the_packet_prints_can_be_written(self):
        model_fields = _model_field_names()
        read = _fields_read_by_packet(model_fields)
        writable = _writable_names()

        orphans = sorted(
            name for name in read if name not in writable and name not in SERVER_ASSIGNED and name not in FED_BY
        )

        self.assertEqual(
            orphans,
            [],
            "The certifier packet reads these model fields and NOTHING in the form layer "
            "writes them, so they print '—' on every real grower's PDF:\n  "
            + "\n  ".join(orphans)
            + "\n\nFix one of three ways: add the input; add the field to SERVER_ASSIGNED "
            "with the reason it is not human-authored; or add it to FED_BY naming the "
            "writable field that feeds it. Do not delete this assertion.",
        )
