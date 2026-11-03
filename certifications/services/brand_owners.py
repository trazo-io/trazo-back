"""The brand owners a farm packs into, each with what the plan can show for it (G7.0 page C).

CCOF G7.0 C, OTCO C8 8.3 and WSDA AGR 2121 N 6-7 ask the same thing three ways: who owns each brand
the crop is packed into, whether that company is certified, and the copy that shows it. A certified
brand owner's certificate; for an uncertified one, the certifying agent's own agreement (CCOF's
Co-Packer Application, OTCO's Private Label Agreement). The module PDF, the packet ZIP and the
coverage page all read `brand_owner_rows`, so they cannot name different copies or disagree about
which owner is still open.

Every state is the operation's record. A copy is the operation's own; whether an old one still
proves the owner's status is the certifier's call (205.404(d)), so it prints for review.
"""

from __future__ import annotations

from datetime import date, timedelta

#: About 15 months, the window `supplier_certificates` and `PostHarvestFacility` use.
CERTIFICATE_FRESH_DAYS = 456

#: Row states. Only `on_file` closes the row on the coverage page.
ON_FILE = "on_file"
CERTIFICATE_MISSING = "certificate_missing"
CERTIFICATE_OLD = "certificate_old"
AGREEMENT_MISSING = "agreement_missing"
STATUS_UNKNOWN = "status_unknown"

#: The agent's own agreement for packing into an uncertified owner's brand, by register slug.
_AGREEMENT_NAMES = {
    "ccof": "Co-Packer Application (ORGB26)",
    "otco": "Private Label Agreement (PLA)",
}


def agreement_name(osp) -> str:
    """The agreement the plan's own agent asks for. A generic name for any other agent: another
    agent's form name would send the operation to paperwork its agent never sent."""
    from certifications.services.packet_coverage import packet_agent

    slug = packet_agent(osp).slug or ""
    return _AGREEMENT_NAMES.get(slug, "certifying agent's private-label or co-packer agreement")


def brand_owners_shown(osp) -> bool:
    """Whether G7.0 prints the brand-owner page: some crop leaves under a buyer's label, and the
    module is not attested not applicable."""
    from certifications.osp_modules.conditions import answer_value

    entry = ((osp.module_responses or {}).get("modules") or {}).get("g7_0_labeling") or {}
    if entry.get("not_applicable"):
        return False
    leaves = answer_value(entry.get("answers") or {}, "product_leaves_as")
    return "buyer_label" in (leaves if isinstance(leaves, (list, tuple)) else [leaves])


def brand_owner_rows(establishment, today: date | None = None) -> list[dict]:
    """One row per brand owner: {owner, state, document (the copy to show, or None)}.

    A certified owner shows its certificate; an uncertified one shows the agreement. An owner
    whose status nobody stated shows neither: Trazo cannot say which copy it owes.
    """
    if establishment is None:
        return []
    today = today or date.today()
    owners = establishment.brand_owners.select_related("certificate_document", "agreement_document").order_by(
        "name", "pk"
    )
    return [dict(owner=owner, **dict(zip(("state", "document"), owner_state(owner, today)))) for owner in owners]


def owner_state(owner, today: date | None = None) -> tuple[str, object]:
    """(state, the copy to show or None) for one brand owner. The register's API, the plan's page C
    and the coverage page all read this, so the app cannot flag an owner the plan does not."""
    today = today or date.today()
    farm = owner.establishment_id
    # A copy counts only when its file is this farm's. The write path checks it; this read does not
    # trust that alone (same rule as the supplier register).
    cert = owner.certificate_document if owner.certificate_document_id else None
    if cert is not None and cert.establishment_id != farm:
        cert = None
    agreement = owner.agreement_document if owner.agreement_document_id else None
    if agreement is not None and agreement.establishment_id != farm:
        agreement = None
    if owner.certification_status == "certified":
        if cert is None:
            return CERTIFICATE_MISSING, None
        if owner.certificate_issued_on is None or today - owner.certificate_issued_on > timedelta(
            days=CERTIFICATE_FRESH_DAYS
        ):
            return CERTIFICATE_OLD, cert
        return ON_FILE, cert
    if owner.certification_status == "not_certified":
        return (ON_FILE, agreement) if agreement is not None else (AGREEMENT_MISSING, None)
    return STATUS_UNKNOWN, None


def document_source(document) -> str:
    """The packet key of a copy: the document, as every other upload of that file uses."""
    return f"doc:{document.pk}"
