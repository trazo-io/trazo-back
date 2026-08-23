"""Text that ReportLab's base-14 fonts can actually draw.

WHY THIS EXISTS
---------------
Every Trazo PDF — the certifier packet, the operation dossier, the OSP snapshot, the module
PDFs, the renewal cover — is set in ReportLab's built-in Helvetica, which carries the WinAnsi
(cp1252) repertoire and nothing else. A character outside it is not dropped and is not replaced
with a box: ReportLab writes the byte at that code point in its own encoding, and the viewer
draws whatever Helvetica keeps there. Measured 2026-08-23 by rendering and reading back:

    →  printed as  ﬁ        ←  ‹        ↔  «        ⇒  (a stray glyph)
    ✓  printed as  3        ✔  4        ✗  7
    ≥  printed as  ‡        ≤  £        ≠  „        ★  H        emoji  n

So "≤ 0.5 ac" reached a certifier as "£ 0.5 ac" and "colour break → Entrust" as "colour break ﬁ
Entrust". These are not exotic characters: operators type arrows and check marks into
descriptions, and several of Trazo's own static strings used "→" (those were replaced with
words). The static sites could be fixed one by one; operator free text cannot, so the
substitution lives at the one boundary every string crosses on its way into a Paragraph — the
XML-escape helpers.

WHAT IT DOES
------------
`glyph_safe(text)` maps the symbols that carry MEANING to ASCII that keeps it (→ becomes ->,
≤ becomes <=, ✓ becomes [x]), drops emoji and other pictographs (decoration that has no
equivalent), and turns any remaining character Helvetica cannot draw into "?" — visibly
unknown rather than silently wrong. Everything in cp1252 (é, ñ, –, —, …, •, °, ±, ², ½, €, ™)
passes through untouched.

The real fix — registering a full-Unicode TrueType face — is a layout change (every width
budget in the packet was measured against Helvetica) and is deliberately not attempted here.
"""

from __future__ import annotations

#: Characters with an ASCII rendering that preserves what they mean.
_MEANINGFUL = {
    "→": "->",  # →
    "←": "<-",  # ←
    "↔": "<->",  # ↔
    "⇒": "=>",  # ⇒
    "⇐": "<=",  # ⇐
    "✓": "[x]",  # ✓
    "✔": "[x]",  # ✔
    "✗": "[ ]",  # ✗
    "✘": "[ ]",  # ✘
    "≥": ">=",  # ≥
    "≤": "<=",  # ≤
    "≠": "!=",  # ≠
    "≈": "~",  # ≈
    "−": "-",  # − (minus sign)
    "‐": "-",  # ‐ (hyphen)
    "‑": "-",  # ‑ (non-breaking hyphen)
    "★": "*",  # ★
    "☆": "*",  # ☆
    " ": " ",  # nbsp is in cp1252, but a visible space is what a table cell wants
    " ": " ",  # thin space
    "​": "",  # zero-width space
    "﻿": "",  # BOM
}

_ENCODING = "cp1252"


def _is_pictograph(ch: str) -> bool:
    cp = ord(ch)
    return (
        cp >= 0x1F000  # emoji, pictographs, flags
        or 0x2600 <= cp <= 0x27BF  # misc symbols & dingbats not mapped above
        or 0x2B00 <= cp <= 0x2BFF  # misc symbols and arrows
        or cp in (0xFE0F, 0xFE0E)  # variation selectors
        or 0x200C <= cp <= 0x200D  # zero-width (non-)joiners
    )


def glyph_safe(text) -> str:
    """Return `text` with every character Helvetica cannot draw made legible or removed."""
    if text is None:
        return ""
    text = str(text)
    if text.isascii():
        return text
    out = []
    for ch in text:
        if ch in _MEANINGFUL:
            out.append(_MEANINGFUL[ch])
            continue
        try:
            ch.encode(_ENCODING)
        except UnicodeEncodeError:
            if _is_pictograph(ch):
                continue
            out.append("?")
            continue
        out.append(ch)
    return "".join(out)
