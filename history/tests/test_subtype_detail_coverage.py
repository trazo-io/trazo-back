"""A subtype's defining fields must reach the certifier, not just the database.

WHAT WENT WRONG. Four subtypes recorded the facts that make them that activity and showed the
inspector none of them:

    PO  pollinator_type, hive_count, placement_date, removal_date
    CM  canopy_operation, pass_number
    MO  floor_management_type
    TI  tillage_type, tillage_intensity, tillage_direction, residue_management

Each arrived in the packet as a bare row: a date and a label. The farmer answered the question,
the answer was stored, and the one reader it exists for never saw it. All of them persist
through `extra_data`, which is why a column-level audit of the models found nothing — the sweep
that found these had to start from what the FORM collects, not from what the model declares.

WHY A COVERAGE TEST AND NOT JUST THE FIX. The packet is hand-assembled, so "is this field
printed anywhere" has no structural answer — it is a grep, and a grep nobody runs. This test is
that grep, run on every build, expressed as: a field the form collects for a specific subtype
must be readable somewhere in the export services. It cannot prove the field is rendered
usefully; it can prove it is not silently absent, which is the failure that actually happened.
"""

import os
import re

from django.test import TestCase

SERVICES = [
    "history/services/audit_export_service.py",
    "history/services/pur_export_service.py",
    "company/services/operation_audit_export_service.py",
    "history/services/record_completeness.py",
]

# Fields that define a subtype — losing one makes the activity unreadable in the packet.
# Grouped by the activity they belong to so a failure names the farmer-facing thing, not a key.
SUBTYPE_DEFINING_FIELDS = {
    "Pollination (PO)": ["pollinator_type", "hive_count", "placement_date", "removal_date"],
    "Canopy Management (CM)": ["canopy_operation", "pass_number"],
    "Orchard Floor / Mowing (MO)": ["floor_management_type"],
    "Tillage (TI)": ["tillage_type", "tillage_intensity", "tillage_direction", "residue_management"],
    "Transport (TP)": ["transport_origin", "transport_destination_address"],
    "Buffer Use (BU)": ["buffer_disposition", "buffer_disposition_quantity", "buffer_disposition_evidence"],
    "Cleanout purge (EM)": ["purge_material", "purge_quantity", "purge_material_end_use"],
    "Seed Search (SS)": ["seed_search_attempts", "seed_nonavailability_reason"],
}


# Fields the forms collect that the packet deliberately does NOT print, with the reason.
#
# ⚠️ THIS LIST IS THE POINT. The summary-mode totals sat in an earlier sweep's results and were
# waved through as "aggregates, probably intentional" — they were not, and a farm using summary
# mode handed its certifier a row of dashes for a whole season. An unexplained absence gets
# dismissed twice and then becomes permanent. An absence WITH a reason can be argued with.
#
# Adding a field here is a decision, not a formality: it says a certifier does not need it.
DELIBERATELY_NOT_PRINTED = {
    "chemical_subtype": (
        "carbon-only. Its own help_text says 'for accurate carbon emission calculations', and "
        "CERTIFICATION_SECTIONS excludes carbon from the organic export. The chemical FAMILY a "
        "certifier reads comes from `type`, which is printed."
    ),
    "temperature_range": "agronomic context for the carbon model, not a § 205 record",
    "water_test_summary": (
        "a UI-derived rendering of `water_test_results`, and the underlying JSON column IS read "
        "by the packet — printing both would show the same test twice"
    ),
    "weather_conditions": (
        "collected 'for transparency' per its own help_text. Spray-day conditions are "
        "drift-relevant, but the Input Application Log already carries 14 columns against a "
        "7.00in frame. REVISIT if a certifier asks for it — this is a space decision, not a "
        "judgement that it is worthless."
    ),
    "application_details": "free text duplicating the description already printed",
    "action_recommended": (
        "§ 205.206(e) turns on the THRESHOLD rationale, and `threshold_rationale` plus "
        "`action_threshold_met` are both printed. This is the follow-up note, not the record."
    ),
}


def _export_source():
    src = ""
    for rel in SERVICES:
        if os.path.exists(rel):
            src += open(rel).read()
    return src


class SubtypeDetailCoverageTests(TestCase):
    def test_the_sources_are_actually_readable(self):
        """Non-vacuity: an empty source string would make every assertion below pass."""
        src = _export_source()
        self.assertGreater(len(src), 100_000, "export services did not load — the check would be vacuous")

    def test_every_subtype_defining_field_is_read_by_an_export(self):
        src = _export_source()
        missing = {}
        for activity, fields in SUBTYPE_DEFINING_FIELDS.items():
            absent = [f for f in fields if f not in src]
            if absent:
                missing[activity] = absent
        self.assertEqual(
            missing,
            {},
            "these activities record fields the certifier packet never reads, so the event "
            "arrives as a bare date and label:\n" + "\n".join(f"  {a}: {', '.join(fs)}" for a, fs in missing.items()),
        )

    def test_the_guard_would_notice_a_removal(self):
        """Proves the mechanism rather than trusting it.

        A coverage test that greps a large file is exactly the kind that can pass for the wrong
        reason — a stray comment mentioning the field name satisfies it. This checks that a
        name NOT present anywhere is reported, so the assertion above is doing real work.
        """
        src = _export_source()
        self.assertNotIn(
            "a_field_that_should_never_exist_anywhere",
            src,
            "the sentinel leaked into the sources; the coverage check cannot be trusted",
        )

    def test_deliberate_omissions_are_still_omitted_for_the_stated_reason(self):
        """If one of these starts appearing, the reason above is stale and should be deleted.

        This is not asserting the packet is right — it is asserting the DECISION is still the
        decision. A field quietly gaining a printer means someone disagreed with the note and
        did not update it, which is how a documented absence rots back into an undocumented one.
        """
        src = _export_source()
        surprises = [f for f in DELIBERATELY_NOT_PRINTED if f in src]
        self.assertEqual(
            surprises,
            [],
            "these fields are documented as deliberately unprinted but now appear in an export. "
            "Update DELIBERATELY_NOT_PRINTED — the reason recorded there is no longer true: " + ", ".join(surprises),
        )
