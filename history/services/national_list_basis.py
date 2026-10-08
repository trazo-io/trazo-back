"""The one rule for reading a ChemicalEvent's National List classification.

OSP alignment audit, Phase 5 slice 1 (2026-10-02). `ChemicalEvent.national_list_substance` held every
match, from an exact name to a substring guess, and every reader cited a § listing for it: the buyer
page's input chip, the lot's organic gate, the certifier packet, the materials workbook and the drift
detector. A classification is now one of three things:

    confirmed      exact name, curated alias, or set by the operator: a document may cite it
    legacy         stored before the basis was kept; its method is unknown and not inferred
    suggestion     a partial-name match (`national_list_suggestion`): never a classification

Every reader that turns the classification into a statement calls `confirmed_national_list_substance`.
`test_national_list_basis` fails if a new reader reads the field directly.
"""

from __future__ import annotations

CONFIRMED_BASES = frozenset({"exact", "alias", "operator"})
LEGACY_BASIS = "legacy_unverified"

LEGACY_NOTE = "recorded before Trazo kept how it was matched; not verified"
SUGGESTION_NOTE = "possible listing from a partial name match, not confirmed"


def confirmed_national_list_substance(event):
    """The classification a document or claim may use, or None."""
    if event is None:
        return None
    substance = getattr(event, "national_list_substance", None)
    if substance is None:
        return None
    return substance if getattr(event, "national_list_basis", None) in CONFIRMED_BASES else None


def legacy_linked_national_list(event):
    """The substance LINKED to the record on an unconfirmed (legacy) basis, else None. Never the
    suggestion: a suggestion is a substring hit nobody linked (review of back #133)."""
    if event is None:
        return None
    substance = getattr(event, "national_list_substance", None)
    if substance is not None and getattr(event, "national_list_basis", None) not in CONFIRMED_BASES:
        return substance
    return None


def unconfirmed_national_list(event):
    """(substance, note) for a legacy classification or a suggestion, else (None, "")."""
    if event is None:
        return None, ""
    substance = getattr(event, "national_list_substance", None)
    if substance is not None and getattr(event, "national_list_basis", None) not in CONFIRMED_BASES:
        return substance, LEGACY_NOTE
    suggestion = getattr(event, "national_list_suggestion", None)
    if suggestion is not None:
        return suggestion, SUGGESTION_NOTE
    return None, ""
