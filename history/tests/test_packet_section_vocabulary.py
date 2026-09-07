"""
The certifier packet must speak the CERTIFIER's vocabulary, not Trazo's event-model names.

WHY (2026-09-06). Six section headings were the internal `event_type` family names printed
verbatim as if they were record types an inspector asks for:

    "Production Events"                 → USDA NOP C5 is the "Planting and Harvest Record";
                                          CCOF's checklist asks for planting and harvest records.
                                          "Production Events" is `event_type 1`, our word.
    "Input Application Log"             → CCOF: "Input Material Application Records";
                                          USDA NOP C7: "Input Material Application Record".
    "General Documentation"             → `event_type 3` ("General"). The table holds crew
                                          training, maintenance and contamination notes.
    "Weather Events"                    → `event_type 0`.
    "Equipment & Maintenance"           → `EquipmentEvent`, a model RETIRED from the UI. The
                                          record CCOF asks for is the equipment cleaning log.
    "3-Year Field & Crop Rotation …"    → USDA NOP C1: "Field History / Previous Land Use Record".

An inspector reads a table of contents looking for the record they asked for by name. A heading
that names our database instead costs them the lookup, and it reads as a system that has not met
a certifier. The same defect had already reached the FINDINGS pointers, which sent the reader to
a "Chemical Log section" and a "General Documentation section" that no longer existed.

SOURCES (primary, quoted in documentation/audits/.work/research-ccof-nop.md):
  * USDA AMS NOP, "Documentation Forms for Organic Crop Producers", March 2011 — pages C1
    (Field History / Previous Land Use Record), C5 (Planting and Harvest Record),
    C7 (Input Material Application Record), C8 (Compost Production Record),
    C9 (Manure Application / Food Crop Harvest Interval Record), C10-C12 (Seed Records).
  * CCOF, "Organic Grower Inspection Preparation Checklist", 01/29/25 — "Input Material
    Application Records ... type and brand name of material, date, rate & location";
    cleaning logs; audit trail; in/out mass balance; production verification.
  * WSDA AGR 2121-O (Recordkeeping), R 02/25.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

SERVICE = Path(__file__).resolve().parent.parent / "services" / "audit_export_service.py"

#: Family names that identify a Trazo event MODEL rather than a certifier record. A section
#: heading may not BE one of these, and may not open with one.
EVENT_MODEL_VOCABULARY = (
    "Production Events",
    "Chemical Events",
    "General Documentation",
    "Weather Events",
    "Business Events",
    "Equipment Events",
    "Soil Events",
    "Pest Events",
)

#: Headings whose wording is load-bearing, each with the source that fixes it. Changing one of
#: these means a certifier changed their form — record the new source here when you do.
CERTIFIER_ANCHORED_HEADINGS = {
    "Input Material Application Records": "CCOF inspection checklist + USDA NOP form C7",
    "Planting, Harvest & Field Operation Records": "USDA NOP form C5 + CCOF production records",
    "Field History & Previous Land Use": "USDA NOP form C1",
    "Seed & Planting Stock Records": "USDA NOP forms C10-C12 / 7 CFR 205.204",
    "Equipment Cleaning & Maintenance": "CCOF cleaning logs / 7 CFR 205.272",
    "Mass-Balance Audit Summary": "CCOF In/Out Mass Balance Audit",
    "Post-Harvest Handling & Storage": "CCOF G6.2 / G6.4",
    "Soil & Water Management": "Common OSP G4.0",
    "Pest Management": "Common OSP G5.0",
    "Organic System Plan": "7 CFR 205.201",
    "Producer Attestation": "7 CFR 205.401 / 205.400(a)",
}


def _source():
    return SERVICE.read_text()


def _section_headings(source):
    """Every literal passed to `_section_header(...)`."""
    return re.findall(r'_section_header\(\s*"([^"]+)"', source)


class PacketSectionVocabularyTests(SimpleTestCase):
    def test_the_service_is_readable(self):
        """Non-vacuity: an unreadable file would make every assertion below pass."""
        headings = _section_headings(_source())
        self.assertGreater(len(headings), 20, "found too few section headings to be trusted")

    def test_no_section_is_named_after_a_trazo_event_model(self):
        offenders = []
        for heading in _section_headings(_source()):
            for family in EVENT_MODEL_VOCABULARY:
                if heading == family or heading.startswith(family + " ("):
                    offenders.append(f"{heading!r} is the {family!r} event model, not a certifier record")
        self.assertEqual(
            offenders,
            [],
            "a certifier packet heading names Trazo's database instead of the record an inspector "
            "asks for. See this module's docstring for the USDA/CCOF names:\n  " + "\n  ".join(offenders),
        )

    def test_certifier_anchored_headings_still_use_the_sourced_wording(self):
        source = _source()
        headings = _section_headings(source)
        missing = {
            phrase: why
            for phrase, why in CERTIFIER_ANCHORED_HEADINGS.items()
            if not any(h.startswith(phrase) for h in headings)
        }
        self.assertEqual(
            missing,
            {},
            "these headings are anchored to a certifier's own form name and no longer appear. "
            "If a certifier changed their form, update the source note here deliberately:\n"
            + "\n".join(f"  {p} — {w}" for p, w in missing.items()),
        )

    def test_every_findings_pointer_names_a_section_that_exists(self):
        """A finding's "where to look" line must match a real heading.

        This is what actually broke: the pointer map said "Chemical Log section" and
        "General Documentation section" while the headings read "Input Application Log" and
        (later) "Training, Maintenance & Other Farm Records".
        """
        source = _source()
        headings = _section_headings(source)
        pointers = re.findall(r'"([A-Z][^"]*?) section"', source)
        unknown = sorted({p for p in pointers if not any(h.startswith(p) for h in headings)})
        # Pointers that deliberately name a GROUP of sections rather than one heading.
        allowed_group_pointers = {"Event logs + Photo Evidence", "Traceability"}
        unknown = [p for p in unknown if p not in allowed_group_pointers]
        self.assertEqual(
            unknown,
            [],
            "a finding points the inspector at a section heading that does not exist:\n  " + "\n  ".join(unknown),
        )


class GeneralActivityLabelTests(SimpleTestCase):
    """The Activity Type column must print words, not the select's option value."""

    def test_every_frontend_activity_type_has_a_packet_label(self):
        from history.services.audit_export_service import GENERAL_ACTIVITY_LABELS

        enums = SERVICE.resolve().parent.parent.parent.parent / "trazo-app" / "src" / "config" / "events" / "enums.ts"
        # Anchored on the closing "\n];" at column 0 — a lazy `.*?\]` runs past this array
        # into the next enum and pulls in 76 unrelated option values.
        block = re.search(r"GENERAL_ACTIVITY_TYPES[^=]*=\s*\[(.*?)\n\]\s*(?:as const)?\s*;", enums.read_text(), re.S)
        self.assertIsNotNone(block, "GENERAL_ACTIVITY_TYPES not found — the parity check would be vacuous")
        values = set(re.findall(r"value: '([a-z_]+)'", block.group(1)))
        self.assertGreater(len(values), 5)
        self.assertLess(len(values), 20, "the array capture ran past GENERAL_ACTIVITY_TYPES")
        missing = sorted(values - set(GENERAL_ACTIVITY_LABELS))
        self.assertEqual(
            missing,
            [],
            "the general form offers these activity types and the packet has no label for them, "
            f"so it prints the raw slug: {', '.join(missing)}",
        )

    def test_an_unmapped_value_still_reads_as_words(self):
        from history.services.audit_export_service import _general_activity_label

        self.assertEqual(_general_activity_label("training"), "Training")
        self.assertEqual(_general_activity_label("precision_ag"), "Precision Agriculture")
        self.assertEqual(_general_activity_label("some_new_value"), "Some New Value")
        self.assertIsNone(_general_activity_label(""))
        self.assertIsNone(_general_activity_label(None))
