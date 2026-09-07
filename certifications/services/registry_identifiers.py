"""Which catalog identifiers Trazo is allowed to PRINT, and in what words.

An identifier printed beside a product name in a certifier packet reads as a
government registration the reader can look up. Two of the three catalogues
Trazo cross-references do not give us one:

    OMRI      REAL. ``dow-2900`` / ``moi-2794`` is OMRI's own published format
              (company letters + number) and deep-links to a live certificate at
              https://www.omri.org/mfg/<letters>/certificate/<number>. Print it.

    WSDA      The real key is the ``WSDA Product #`` column of the WSDA Organic
              Input Material List, and it holds a BARE INTEGER (1123, 2948,
              3376). Trazo's seeded ``WSDAMaterial.wsda_id`` values of the shape
              ``WSDA-REG-BIOAG-2025-001`` are FABRICATED — WSDA issues nothing
              of that shape, so a certifier who searches for one finds nothing.
              Print the identifier only when it is a real product number.

    CDFA OIM  The published Registered Organic Input Material Products list has
              THREE columns — Firm | Product Name | Annotations. There is no
              identifier at all. Every ``CDFA-OIM-*`` string in this codebase was
              invented. A registered row says it is registered and stops there.

This module is the ONE place those rules are decided, so a new render site
cannot quietly reintroduce a fabricated string. The frontend mirrors the same
``^\\d+$`` test locally (``src/components/Compliance/InputVerifyHelper.tsx``);
keep the two in step.
"""

from __future__ import annotations

import re

# A real WSDA Product # is a bare integer. Anything else in `WSDAMaterial.wsda_id`
# is a Trazo-invented placeholder and must never reach a reader.
WSDA_PRODUCT_NUMBER_RE = re.compile(r"^\d+$")

# CDFA publishes no registration identifier, so "registered" is the entire claim
# a registered row is allowed to make.
CDFA_OIM_REGISTERED_LABEL = "CDFA OIM registered"


def wsda_product_number(raw) -> str:
    """The WSDA Product # if `raw` is one, else "" (the fabricated case).

    Never raises — callers pass raw model values, including None.
    """
    value = str(raw or "").strip()
    return value if WSDA_PRODUCT_NUMBER_RE.match(value) else ""


def is_real_wsda_product_number(raw) -> bool:
    return bool(wsda_product_number(raw))


def wsda_identifier_label(raw) -> str:
    """``"WSDA Product #1123"`` for a real number, ``""`` for anything else.

    The empty string is deliberate: a product whose identifier we cannot stand
    behind renders as its name and manufacturer with NO identifier and no
    placeholder — a placeholder would still tell the reader a number exists.
    """
    number = wsda_product_number(raw)
    return f"WSDA Product #{number}" if number else ""
