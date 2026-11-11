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

#: Headings whose wording is load-bearing, each with the source that fixes it.
#:
#: An entry changes for one of TWO reasons, and the second one is why this guard sat red on
#: main from 2026-09-24 to 2026-09-30:
#:   1. the certifier changed their form. Record the new source here.
#:   2. WE moved off the certifier's wording on purpose, because their name promised
#:      something our data does not support. Then the entry is REMOVED, with the reason, and
#:      a guard is added for the wording we must not go back to. A stale entry of this kind
#:      reads as a regression, so the failure gets looked at and left alone.
CERTIFIER_ANCHORED_HEADINGS = {
    "Input Material Application Records": "CCOF inspection checklist + USDA NOP form C7",
    "Planting, Harvest & Field Operation Records": "USDA NOP form C5 + CCOF production records",
    "Field History & Previous Land Use": "USDA NOP form C1",
    "Seed & Planting Stock Records": "USDA NOP forms C10-C12 / 7 CFR 205.204",
    "Equipment Cleaning & Maintenance": "CCOF cleaning logs / 7 CFR 205.272",
    "Post-Harvest Handling & Storage": "CCOF G6.2 / G6.4",
    "Soil & Water Management": "Common OSP G4.0",
    "Pest Management": "Common OSP G5.0",
    "Organic System Plan": "7 CFR 205.201",
    # No part 205 paragraph prescribes an attestation (2026-11 citation review: § 205.401(d) is
    # "other information"), so the heading carries no cite; the body cites § 205.400(f).
    "Producer Attestation": "certifier attestation wording; body cites 7 CFR 205.400(f)",
}

#: "Mass-Balance Audit Summary" was an anchored heading here until 2026-09-30, sourced to
#: CCOF's "In/Out Mass Balance Audit". It was removed because 5b083eb (2026-09-24) renamed the
#: section to "Yield-to-Sales Reconciliation" ON PURPOSE, and the reason is the opposite of a
#: regression: the section reconciles ONE production's harvest records against that same
#: production's sales records, models no inventory at all (no opening balance, no closing
#: balance, no carryover, and Trazo holds no data to compute one), and prints inside an
#: operation dossier whose cover carries a PERIOD WINDOW. CCOF's own words, in that frame,
#: invited a reader to take a lot-level check for a period inventory balance, which is a false
#: conclusion in the operation's favour.
#:
#: Speaking the certifier's vocabulary is the rule this module enforces. It stops where the
#: certifier's word would claim more than the records support. The replacement guard is
#: INVENTORY_BALANCE_WORDING below.

#: Wording the packet's RENDERED headings must not use, with what it would promise. These are
#: matched against `_section_header(...)` literals only: the phrase "mass balance" is correct
#: and common in this service's comments and keys, where it refers to the § 205.103(b)(2)
#: balance an INSPECTOR runs against purchase records. What must not happen is a packet
#: SECTION TITLE promising that model.
INVENTORY_BALANCE_WORDING = {
    "mass-balance": "promises an in/out inventory model this section does not compute",
    "mass balance": "promises an in/out inventory model this section does not compute",
    "net inventory": "promises opening and closing balances Trazo holds no data for",
    "inventory balance": "promises opening and closing balances Trazo holds no data for",
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

    def test_no_heading_promises_an_inventory_balance(self):
        """Preserves the 5b083eb decision, which the removed dict entry no longer protects.

        A renamed heading with no guard behind it lasts until someone restores the
        certifier's wording "for consistency". This is that guard.
        """
        offenders = []
        for heading in _section_headings(_source()):
            lowered = heading.lower()
            for phrase, promise in INVENTORY_BALANCE_WORDING.items():
                if phrase in lowered:
                    offenders.append(f"{heading!r} contains {phrase!r}, which {promise}")
        self.assertEqual(
            offenders,
            [],
            "a packet section title promises an inventory balance. The dossier cover carries a "
            "PERIOD WINDOW, so a reader takes a lot-level check for a period one and draws a "
            "false conclusion in the operation's favour. See the note above "
            "INVENTORY_BALANCE_WORDING:\n  " + "\n  ".join(offenders),
        )

    def test_the_inventory_wording_check_reads_real_headings(self):
        """The check above is negative, so prove it is matching against real text.

        Two halves: the heading the rename produced is actually present (so the section was
        found at all), and the matcher does fire on the wording it forbids.
        """
        headings = _section_headings(_source())
        self.assertTrue(
            any(h.startswith("Yield-to-Sales Reconciliation") for h in headings),
            "the renamed section is missing; this guard is watching nothing",
        )
        planted = "Mass-Balance Audit Summary (§ 205.103(b)(2))".lower()
        self.assertTrue(
            any(phrase in planted for phrase in INVENTORY_BALANCE_WORDING),
            "the matcher does not fire on the exact heading this guard exists to prevent",
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
