"""No table in the certifier packet may be wider than the page it prints on.

🔴 Why this exists. Two tables shipped 0.44-0.45in over the frame — Harvest Records and
Itemized Sales — because a comment asserted a "7.5in text block" that does not exist. The
document is letter (8.5in) with 0.75in margins on both sides, so the frame is 7.00in. Both
tables were drawing their last column into the right margin, and two more were fractionally
over. The premise was wrong in a COMMENT, so every later edit that "kept it inside 7.5" made
it worse while looking careful.

The check is arithmetic on the source, not a render: ReportLab does not raise on an
over-wide Table, it just draws past the frame, so a rendering test would pass while the
inspector's copy loses a column. Reading the widths is the only thing that catches it.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

SERVICE = Path(__file__).resolve().parents[1] / "services" / "audit_export_service.py"

_INCHES = re.compile(r"([0-9.]+)\s*\*\s*inch")
# Inline `colWidths=[...]` and named `*widths* = [...]` / `col_widths = [...]` lists.
_WIDTH_LISTS = (
    re.compile(r"colWidths=\[([^\]]*)\]", re.S),
    re.compile(r"(?:\w*widths\w*|col_widths)\s*=\s*\[([^\]]*)\]", re.S),
)


def _frame_width_inches():
    """Derive the budget from the document itself, never from a remembered number."""
    source = SERVICE.read_text()
    margins = [float(m) for m in re.findall(r"(?:left|right)Margin=([0-9.]+)\s*\*\s*inch", source)]
    assert len(margins) == 2, f"expected one left and one right margin, found {margins}"
    return letter[0] / inch - sum(margins)


class PacketTableWidthTests(SimpleTestCase):
    def test_no_table_exceeds_the_printable_frame(self):
        budget = _frame_width_inches()
        self.assertAlmostEqual(budget, 7.0, places=4, msg="page geometry changed — update the tables, not this test")

        source = SERVICE.read_text()
        offenders = []
        for pattern in _WIDTH_LISTS:
            for match in pattern.finditer(source):
                widths = [float(x) for x in _INCHES.findall(match.group(1))]
                if not widths:
                    continue
                total = round(sum(widths), 4)
                if total > budget + 1e-4:
                    line = source[: match.start()].count("\n") + 1
                    offenders.append(
                        f"  line {line}: {len(widths)} cols = {total:.2f}in (over by {total - budget:.2f})"
                    )

        self.assertEqual(
            offenders,
            [],
            "These tables print past the right margin of an inspector-facing PDF:\n" + "\n".join(offenders),
        )
