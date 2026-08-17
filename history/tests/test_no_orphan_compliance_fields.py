"""
Every field the certifier packet PRINTS must be answerable in the editor that owns it.

WHY (2026-08-13): three fields were found in one day that the packet rendered and no UI could
write — `ParcelCropHistory.last_prohibited_substance` (the "Name and Application Date of Last
Prohibited Input" USDA requires for every field), `SalesRecord.organic_label_category` (§ 205.301,
shipped as migration 0195 and marked "shipped" on the ship list), and
`ParcelCropHistory.block_id` (the split-field column whose unique constraint depends on it).

Each printed a row a grower could never answer. A certifier reading the packet sees a blank
where an operator would swear there is nothing to enter.

## Why no existing test caught them

All four frontend registry guards run **registry-outbound**: they start from what
`src/config/events/*.ts` declares and check downstream into the form source, the rendered DOM
and the i18n catalogues. None enumerates a Django model, a serializer, or the audit export and
asks "who collects this?" The inbound direction did not exist.

Worse, `ParcelCropHistory`, `LandownerAffidavit` and `AdjoiningLandAffidavit` have **no registry
representation at all** — the registry is keyed by the eight event types and structurally cannot
express a non-event model. Every field on those three is invisible to every guard.

## Why this checks the OWNING FILE, not the whole tree

The first version of this guard grepped all of `trazo-app/src` for the bare field name. That is
too loose to do its job: `block_id` also exists on `CommonEvent` and appears in six event
registry files, so **the orphaned `ParcelCropHistory.block_id` would have passed.** Same trap for
`manufacturer` (14 files), `destination` (18), `notes` (54).

So each model is pinned to the editor that owns it, and the field must appear THERE. That also
enforces the repo's one-editor-per-fact rule as a side effect.

⚠️ Still coarse: a name inside a comment in the right file passes. It distinguishes "nobody can
enter this" from "somebody wired it" — the failure that actually happened three times — and is
NOT a substitute for `formRenderConformance`, which proves the input renders.
"""

import subprocess
from pathlib import Path

from django.test import SimpleTestCase

APP_SRC = Path(__file__).resolve().parents[3] / "trazo-app" / "src"

#: model -> (owning editor relative to trazo-app/src, [fields the packet prints])
#: The editor is the SINGLE place that fact is entered; see the one-editor-per-fact rule.
PACKET_FIELDS_BY_OWNING_EDITOR = {
    "ParcelCropHistory": (
        "views/Dashboard/Dashboard/Parcel/FieldHistorySection.tsx",
        [
            "crop_grown",
            "cover_crop",
            "production_method",
            "substances_applied",
            "substance_applications",
            "last_prohibited_substance",
            "date_last_prohibited",
            # Split-field column. Constraint is (parcel, year, crop_grown, block_id), so with
            # no writer a second crop in the same year could not be recorded at all.
            "block_id",
        ],
    ),
    "SalesRecord": (
        "views/Dashboard/Dashboard/Production/SalesRecordsSection.tsx",
        [
            "buyer_name",
            "invoice_number",
            "organic_on_invoice",
            # § 205.301 labeling category. § 205.103(b)(3) requires records to identify product
            # by it, and the organic_on_invoice boolean cannot express it.
            "organic_label_category",
            "bill_of_lading",
            "carrier_name",
            "vehicle_id",
            "destination",
            "clean_transport_method",
            "transport_cleaning_method",
            "prior_products_transported",
            "transport_inspected_free_of",
            # The description both "Other" options promise. The packet printed "Other —
            # described in the notes" for a year with no notes column anywhere in the model,
            # which is this guard's exact failure mode pointed the other way: the packet
            # promised a field rather than asked for one.
            "transport_notes",
        ],
    ),
    "LandownerAffidavit": (
        "views/Dashboard/Dashboard/Parcel/LandownerAffidavitSection.tsx",
        [
            "previous_manager_name",
            "previous_manager_signed_date",
            "no_materials_applied",
            "management_period_start",
            "management_period_end",
            "parcel_legal_description",
            # USDA form #2 asks for the landowner separately from the manager; they are often
            # different people and the affidavit is incomplete without both.
            "landowner_name",
            "field_acres",
        ],
    ),
    "AdjoiningLandAffidavit": (
        "views/Dashboard/Dashboard/Parcel/AdjoiningLandSection.tsx",
        [
            "neighbor_name",
            "border_side",
            "materials_used",
            "declares_no_materials",
            "not_used_on_adjoining_fields",
            "distance_to_organic_property_ft",
            "agrees_to_notify",
            "neighbor_signed_date",
        ],
    ),
    "SoilManagementEvent": (
        "views/Dashboard/Dashboard/components/forms/SoilManagementTab.jsx",
        [
            "manure_application_method",
            "manure_animal_source",
            "manure_form",
            "manure_origin",
            "compost_unit_id",
            "compost_temp_reading_method",
            "manure_harvest_date_planned",
        ],
    ),
    "ProductionEvent": (
        "views/Dashboard/Dashboard/components/forms/ProductionTab.jsx",
        [
            "buffer_disposition",
            "buffer_disposition_quantity",
            "buffer_disposition_evidence",
            "seed_treatment_allowed_basis",
            "seed_nonavailability_reason",
        ],
    ),
    "ChemicalEvent": (
        "views/Dashboard/Dashboard/components/forms/ChemicalTab-ENHANCED.jsx",
        ["application_purpose"],
    ),
}


class NoOrphanComplianceFieldsTests(SimpleTestCase):
    """Inbound guard: packet reads -> does the owning editor collect it?"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._sources = {}

    def _editor_source(self, relative_path):
        if relative_path not in self._sources:
            path = APP_SRC / relative_path
            self._sources[relative_path] = path.read_text(encoding="utf8") if path.is_file() else None
        return self._sources[relative_path]

    def test_every_packet_field_is_collected_by_its_owning_editor(self):
        if not APP_SRC.is_dir():
            # Do NOT silently pass. The one existing cross-repo test is wrapped in
            # `describe.skipIf(!hasBackend)` and no-ops in any checkout without its sibling —
            # which is how a guard becomes decorative. Fail loudly instead.
            self.fail(
                f"trazo-app/src not found at {APP_SRC}. This guard needs both repos checked "
                "out side by side. Skipping silently is how the frontend's own cross-repo "
                "check became a no-op."
            )

        missing_editors = []
        orphans = []
        for model, (editor, fields) in sorted(PACKET_FIELDS_BY_OWNING_EDITOR.items()):
            source = self._editor_source(editor)
            if source is None:
                missing_editors.append(f"{model} -> {editor}")
                continue
            for field in fields:
                if field not in source:
                    orphans.append(f"{model}.{field}  (expected in {editor})")

        self.assertEqual(
            missing_editors,
            [],
            "Owning editor file not found — it was renamed or moved, so this guard silently "
            f"stopped checking those fields:\n  " + "\n  ".join(missing_editors),
        )
        self.assertEqual(
            orphans,
            [],
            "These fields are rendered by the certifier packet but are NOT collected by the "
            "editor that owns them, so no grower can answer them:\n  "
            + "\n  ".join(orphans)
            + "\n\nEither wire an input, or stop printing the field. A packet row nobody can "
            "fill is a blank a certifier reads as missing documentation.",
        )

    def test_the_curated_list_matches_the_models(self):
        """A typo here would silently weaken the guard — the field would 'pass' by never being
        checked against anything real."""
        from django.apps import apps

        unknown = []
        for model_name, (_editor, fields) in PACKET_FIELDS_BY_OWNING_EDITOR.items():
            model = next((m for m in apps.get_models() if m.__name__ == model_name), None)
            self.assertIsNotNone(model, f"{model_name} is not a real model")
            real = {f.name for f in model._meta.get_fields()}
            unknown.extend(f"{model_name}.{f}" for f in fields if f not in real)

        self.assertEqual(unknown, [], f"Listed fields that do not exist on their model: {unknown}")

    def test_the_guard_detects_an_orphan(self):
        """Proves the mechanism fails when it should.

        A guard that only ever passes is indistinguishable from one that checks nothing —
        which is precisely what the first version of this file was, since `block_id` appears
        in six unrelated registry files and would have passed while orphaned.
        """
        editor, _fields = PACKET_FIELDS_BY_OWNING_EDITOR["ParcelCropHistory"]
        source = self._editor_source(editor)
        self.assertIsNotNone(source)
        self.assertNotIn("definitely_not_a_real_field_xyz", source)
        # And the loose form really is loose: block_id exists in files that do NOT own it.
        soil_registry = self._editor_source("config/events/soilEvent.ts")
        if soil_registry is not None:
            self.assertIn(
                "block_id",
                soil_registry,
                "block_id no longer appears outside its owning editor — if that is now true, "
                "the whole-tree grep this guard replaced would be safe again, but the "
                "per-editor check is still the stricter one.",
            )
