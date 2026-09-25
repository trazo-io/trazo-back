"""The OMRI catalogue speaks a third party's product names, so a parse artifact is a claim.

228 of 9,230 rows shipped with the list's printed PAGE NUMBER glued to the front of the
product name ("150 Neptune's Harvest Soluble Seaweed Powder", "100 Genera"). Those names
render on the grower's attach shortlist beside "OMRI #nhf-5923", print into the certifier
packet, and were about to be shown to OMRI itself. A wrong product name under an OMRI code
is the same class of defect as an unearned listing claim: it puts words in OMRI's mouth.

Four were checked against the certificates themselves on 2026-09-18
(omri.org/mfg/<letters>/certificate/<number>), which is the only authority for a name.
"""

import csv
import os
import re
import tempfile

from django.test import SimpleTestCase

from certifications.management.commands.build_omri_seed_csv import _entries

_SEED = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "omri_seed.csv",
)

_LEADING_NUMBER_RE = re.compile(r"^\d{1,4}\s+\S")

#: Names that genuinely BEGIN with a number, each read off its own OMRI certificate.
#: Anything else matching `_LEADING_NUMBER_RE` is the page-number artifact coming back.
_NUMBER_IS_PART_OF_THE_NAME = {
    "baj-13570": "480 g/L Spinosad SC",
    "usb-9851": "20 Mule Team Borax™ Fertibor® Sodium Borate 15% B",
    "usb-9853": "20 Mule Team Borax Solubor Sodium Borate 20.5% B",
    "usb-10149": "20 Mule Team Borax Granubor Sodium Borate 15% B",
    "usb-4591": "20 Mule Team Borax Optibor TG Boric Acid",
}

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
 <body>
  <page width="612" height="792">
   <block xMin="50" yMin="700">
    <line><word>150</word></line>
   </block>
   <block xMin="50" yMin="720">
    <line><word>Neptune's</word><word>Harvest</word><word>Soluble</word><word>Seaweed</word></line>
    <line><word>Powder</word><word>(nhf-5923)</word><word>Ocean</word><word>Crest</word><word>Seafoods</word><word>(CF)</word></line>
   </block>
  </page>
 </body>
</html>
"""


class OMRISeedNameTests(SimpleTestCase):
    def test_no_product_name_carries_the_lists_page_number(self):
        with open(_SEED, encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        self.assertGreater(len(rows), 9000, "seed looks truncated")
        offenders = [
            (row["omri_id"], row["product_name"])
            for row in rows
            if _LEADING_NUMBER_RE.match(row["product_name"]) and row["omri_id"] not in _NUMBER_IS_PART_OF_THE_NAME
        ]
        self.assertEqual(
            offenders,
            [],
            "product names begin with the printed page number; re-run build_omri_seed_csv",
        )

    def test_the_verified_numeric_names_are_left_alone(self):
        """The fix must not over-reach: these five names really do start with a number."""
        with open(_SEED, encoding="utf-8") as handle:
            names = {row["omri_id"]: row["product_name"] for row in csv.DictReader(handle)}

        for omri_id, expected_prefix in _NUMBER_IS_PART_OF_THE_NAME.items():
            self.assertIn(omri_id, names)
            self.assertTrue(
                names[omri_id].startswith(expected_prefix),
                f"{omri_id} should still read {expected_prefix!r}, got {names[omri_id]!r}",
            )

    def test_a_page_number_line_never_starts_an_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "list.xml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(_XML)
            entries = list(_entries(path))

        self.assertEqual(len(entries), 1)
        self.assertFalse(
            entries[0][0].startswith("150"),
            f"page number leaked into the entry: {entries[0]!r}",
        )
        self.assertTrue(entries[0][0].startswith("Neptune's Harvest"))
