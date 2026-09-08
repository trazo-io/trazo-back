"""No fixture may stamp the USDA Organic Integrity Database as a verification source.

`Certification.verification_source == "usda_organic_integrity_db"` is what
`consumer_display_status` requires before a consumer surface may say "Verified via USDA Organic
Integrity Database". It is written by exactly one legitimate author:
`VerificationManager.verify_certification`, from `USDAOrganicVerifier.source_identifier`, after
a match against Trazo's mirror of the USDA monthly export.

On 2026-09-06 two demo fixtures wrote it directly — `_calapooia_bend_data.json` with a
fabricated `nopid` in the source URL, and `_loewen_base.py` on an establishment it had just
marked `is_demo = True`. A seeded farm therefore satisfied the substantiation gate honestly,
and the audit found the green verified card on invented records.

The runtime now refuses the claim for any specimen operation
(`test_specimen_claim_neutralised`). This test is the other half: a fixture should not write a
value its own reader has to override. Together they mean the claim needs BOTH a real match and
a real operation.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

COMMANDS_DIR = Path(__file__).resolve().parent.parent / "management" / "commands"

#: The literal, as an ASSIGNED VALUE — Python kwarg or JSON member. Prose that merely names the
#: constant (a comment explaining why it was removed) is not a stamp, and a guard that forbade
#: naming the thing it removed would make the removal undocumentable.
STAMP_PATTERNS = (
    re.compile(r'verification_source\s*=\s*["\']usda_organic_integrity_db["\']'),
    re.compile(r'"verification_source"\s*:\s*"usda_organic_integrity_db"'),
)


class SeedersNeverStampOidTests(SimpleTestCase):
    def test_no_seeder_or_fixture_writes_the_oid_verification_source(self):
        offenders = []
        for path in sorted(COMMANDS_DIR.rglob("*")):
            if path.suffix not in {".py", ".json"} or not path.is_file():
                continue
            text = path.read_text(errors="ignore")
            for pattern in STAMP_PATTERNS:
                for match in pattern.finditer(text):
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line}")
        self.assertEqual(
            offenders,
            [],
            "a fixture stamps the OID verification source, which lets invented records satisfy "
            f"the 'Verified via USDA Organic Integrity Database' gate: {offenders}",
        )

    def test_the_pattern_would_actually_catch_the_old_fixture_shapes(self):
        """Mutation check: a guard that matches nothing passes forever."""
        py_shape = '        verification_source="usda_organic_integrity_db",'
        json_shape = '   "verification_source": "usda_organic_integrity_db",'
        self.assertTrue(any(p.search(py_shape) for p in STAMP_PATTERNS))
        self.assertTrue(any(p.search(json_shape) for p in STAMP_PATTERNS))

    def test_plain_prose_naming_the_database_is_allowed(self):
        """Documentation must stay possible, or the removal becomes unexplainable.

        The patterns match an ASSIGNMENT, so a comment may say what was removed as long as it
        does not quote the assignment syntax — which is exactly what this guard made us do to
        `_loewen_base.py` when it first ran and flagged the explanatory comment there.
        """
        prose = "    # Seeded as verified against the USDA Organic Integrity Database until 2026-09-08."
        self.assertFalse(any(p.search(prose) for p in STAMP_PATTERNS))
