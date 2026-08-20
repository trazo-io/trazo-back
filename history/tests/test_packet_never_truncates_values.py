"""No regulatory or farmer-authored value is shortened in the certifier packet.

`_cell`'s contract says it plainly: "Pass `max_len` only where SHORTENING NARRATIVE is the
intent … Never on an identity or regulatory value." The default cap was removed in 2026-08-01
after 128 call sites had quietly destroyed values in a document whose purpose is to record
them.

Seven call sites still passed one. Two were the documented 120-character cap that the sibling
notes table had already had removed for cutting mid-sentence: the grower's field notes
("kept separate from the…", "filed in the OSP…") and the § 205.206(e) threshold rationale —
the justification for applying a material, which is the entire reason that row exists. Three
more passed 600, which the same comment records as still too short for a real 628-character
spinosad justification.

Label cells (the left column of a key/value table) may still cap: those are Trazo's own short
strings, not the operator's evidence.
"""

import re
from pathlib import Path

from django.test import TestCase

SERVICE = Path(__file__).resolve().parent.parent / "services" / "audit_export_service.py"

# Left-hand label cells in two-column key/value tables. Not operator evidence.
ALLOWED_LABEL_CAPS = {"self._cell(label, 32)", "self._cell(label, 28)"}


class PacketValueTruncationTests(TestCase):
    def test_no_value_cell_passes_a_truncation_length(self):
        source = SERVICE.read_text()
        offenders = []
        for lineno, line in enumerate(source.splitlines(), 1):
            for match in re.finditer(r"self\._cell\([^)]+,\s*\d{2,4}\s*\)", line):
                call = match.group(0)
                if call in ALLOWED_LABEL_CAPS:
                    continue
                offenders.append(f"{lineno}: {call}")
        self.assertEqual(
            offenders,
            [],
            "these cells shorten a value in the certifier packet; `_cell`'s contract forbids "
            "it for identity and regulatory values:\n" + "\n".join(offenders),
        )

    def test_the_runaway_ceiling_still_exists(self):
        """Removing the caps must not remove the pathological-input guard."""
        from history.services.audit_export_service import _RUNAWAY_CELL_CHARS

        self.assertGreaterEqual(_RUNAWAY_CELL_CHARS, 2000)
