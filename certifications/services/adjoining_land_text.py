"""One reading of a neighbour's adjoining-land affidavit, for every document that prints it.

The OSP packet and the audit dossier both print an `AdjoiningLandAffidavit`. The dossier read the
affidavit's three-state answers; the packet read only `neighbor_signed_date`, so an affidavit with a
signed scan and no date printed "signed unsigned", and the neighbour's signed "none of these
materials", "not on adjoining fields", distance and organic certification never reached the packet
(overall review 2026-11, M7-S8). The states are stated here once.

Three states, never two (`attestation_absence_is_not_denial`): True is an affirmative answer, False
a negative one, None is silence. Silence is printed as "not answered", never as "no".
"""

from typing import Optional

MATERIALS_NONE_DECLARED = "None of the listed materials (declared)"
MATERIALS_NOT_ANSWERED = "Not answered"
NOT_ON_ADJOINING_FIELDS = "not on adjoining fields"
DOCUMENT_ON_FILE = "Document on file"
UNSIGNED = "UNSIGNED"


def materials_statement(affidavit) -> str:
    """What the neighbour declared about materials: a declared none, a list, or silence."""
    if affidavit.declares_no_materials is True:
        return MATERIALS_NONE_DECLARED
    listed = affidavit.materials_display()
    if listed:
        if affidavit.not_used_on_adjoining_fields is True:
            return f"{listed} ({NOT_ON_ADJOINING_FIELDS})"
        return listed
    return MATERIALS_NOT_ANSWERED


def distance_statement(affidavit) -> str:
    """The distance, in feet as the neighbour states it, or an empty string when none is recorded."""
    ft = affidavit.distance_to_organic_property_ft
    return f"{ft} ft" if ft is not None else ""


def notify_statement(affidavit) -> str:
    """Whether the neighbour agreed to notify; a neighbour who did not answer has not refused."""
    return {True: "Yes", False: "No", None: "Not answered"}[affidavit.agrees_to_notify]


def certification_statement(affidavit) -> str:
    """The neighbour's own declaration of organic status, with the certifier they named."""
    declared = affidavit.neighbor_is_certified_organic
    certifier = (affidavit.neighbor_certifier_name or "").strip()
    if declared is True:
        text = "declares certified organic (or exempt)"
        return f"{text}; certifier: {certifier}" if certifier else text
    if declared is False:
        return "declares not certified organic"
    if certifier:
        return f"certifier named: {certifier}"
    return "organic status not answered"


def signed_statement(affidavit, fmt_date=None) -> Optional[str]:
    """When the neighbour signed, "Document on file" for a signed scan with no date, None if unsigned.

    Uses `AdjoiningLandAffidavit.is_signed()`: a signed scan is a signature even when nobody typed the
    date, and a date alone is one too.
    """
    if not affidavit.is_signed():
        return None
    if affidavit.neighbor_signed_date:
        fmt = fmt_date or (lambda d: d.isoformat())
        return fmt(affidavit.neighbor_signed_date)
    return DOCUMENT_ON_FILE


def packet_line(affidavit) -> str:
    """The packet's one-line reading of an affidavit; says what the dossier's table row says."""
    side = affidavit.get_border_side_display() if affidavit.border_side else "Side not stated"
    head = f"{side}: {affidavit.neighbor_name}"
    if affidavit.neighbor_farm_name:
        head += f" ({affidavit.neighbor_farm_name})"
    signed = signed_statement(affidavit)
    if signed == DOCUMENT_ON_FILE:
        signed_bit = "signed (signed copy on file, no date typed)"
    elif signed:
        signed_bit = f"signed {signed}"
    else:
        signed_bit = "not signed by the neighbour"
    bits = [
        signed_bit,
        f"materials: {materials_statement(affidavit)}",
    ]
    distance = distance_statement(affidavit)
    if distance:
        bits.append(f"distance to the organic property: {distance}")
    bits.append(f"neighbour's organic status: {certification_statement(affidavit)}")
    bits.append(f"agrees to notify before application: {notify_statement(affidavit)}")
    # The head and the signature clause keep the packet's long-standing "West: Name (Farm) \u2014 signed
    # 2027-01-20" shape; what follows is the neighbour's own answers.
    return head + " \u2014 " + "; ".join(bits)
