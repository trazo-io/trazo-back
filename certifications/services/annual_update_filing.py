"""A § 205.406(a) filing is signed, filed and corrected, never edited after the fact.

WHY THIS MODULE EXISTS
----------------------
Until 2026-10-01 a filed annual update stayed editable until the certifier acknowledged it, and
nothing in the product ever wrote the acknowledgement. Document 02 was rendered from the live row
on every download, so the update an operation filed in August could read differently in
October, and the packet had no way to show what was actually sent. The audit (OSP alignment
2026-10, T20) asked for a renewal tied to its year and its submitted snapshot, where a new draft
can never erase an earlier filing.

The rules, in the order they bite:

* **Sign** hashes every signed field (`OSPAnnualUpdate.SIGNED_FIELDS`). From then on the content
  changes only by correction; the viewset refuses edits with 409.
* **File** needs a signature, sets the filing date and method once, and freezes the document as
  rendered at that moment (`filed_pdf`, `filed_sha256`). Document 02 is those bytes from then on.
* **Correct** opens revision N+1 as an unsigned copy. Revision N keeps its bytes. Filing N+1
  marks N superseded; the year never has two current filings.
* **Withdraw** is a status with a reason. The row and its bytes stay.

Rows filed before this existed have no frozen copy and no signer. They are `legacy_none`, and the
packet says so rather than presenting today's rendering as what was filed (migration 0044).
"""

from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone


class FilingStateError(Exception):
    """An action that the filing's current state does not allow. Carries the HTTP status the
    viewset answers with and a sentence the operator can act on."""

    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _signer_name(user) -> str:
    name = (user.get_full_name() or "").strip() if hasattr(user, "get_full_name") else ""
    return name or (getattr(user, "email", "") or "")


@transaction.atomic
def sign_filing(filing, user, signer_title: str = ""):
    from certifications.models import OSPAnnualUpdate

    filing = OSPAnnualUpdate.objects.select_for_update().get(pk=filing.pk)
    if filing.signed_at is not None:
        raise FilingStateError(
            f"Revision {filing.revision_number} of the {filing.reporting_year} update was signed on "
            f"{filing.signed_at.date().isoformat()}. To change it, create a correction."
        )
    if filing.submitted_at is not None:
        raise FilingStateError(
            f"The {filing.reporting_year} update was filed on {filing.submitted_at.date().isoformat()} "
            "without a signature in Trazo. It stays as filed; create a correction to sign a new revision."
        )
    if filing.withdrawn_at is not None:
        raise FilingStateError("A withdrawn revision cannot be signed.")
    filing.signed_by = user
    filing.signer_name = _signer_name(user)
    filing.signer_title = (signer_title or "").strip()[:255]
    filing.signed_at = timezone.now()
    filing.signed_content_sha256 = filing.content_sha256()
    filing.save(
        update_fields=[
            "signed_by",
            "signer_name",
            "signer_title",
            "signed_at",
            "signed_content_sha256",
            "updated_at",
        ]
    )
    return filing


@transaction.atomic
def file_filing(filing, filing_method: str = "", submitted_at=None):
    """Record that the signed revision reached the agent, and freeze what it said."""
    from certifications.models import OSPAnnualUpdate
    from certifications.services.osp_module_pdf import render_filing_pdf

    filing = OSPAnnualUpdate.objects.select_for_update().get(pk=filing.pk)
    if filing.submitted_at is not None:
        raise FilingStateError(
            f"Revision {filing.revision_number} of the {filing.reporting_year} update was already filed on "
            f"{filing.submitted_at.date().isoformat()}. The filing date cannot be changed."
        )
    if filing.signed_at is None:
        raise FilingStateError("Sign this revision before recording that it was filed.", status_code=400)
    if filing.withdrawn_at is not None:
        raise FilingStateError("A withdrawn revision cannot be filed.")
    if filing.content_sha256() != filing.signed_content_sha256:
        # Only reachable by a write that went around the viewset. Refusing beats freezing a
        # document whose content nobody signed.
        raise FilingStateError(
            "This revision's content no longer matches what was signed. Create a correction and sign it."
        )
    valid_methods = {key for key, _label in OSPAnnualUpdate.FILING_METHOD_CHOICES}
    if filing_method and filing_method not in valid_methods:
        raise FilingStateError(
            "Filing method must be one of: " + ", ".join(sorted(valid_methods)) + ".", status_code=400
        )
    now = timezone.now()
    when = submitted_at or now
    if when > now:
        raise FilingStateError("The filing date cannot be in the future.", status_code=400)

    previous = filing.corrects
    if previous is not None and previous.submitted_at is not None and previous.superseded_at is None:
        # Before this revision becomes current, so the year never holds two current filings.
        previous.superseded_at = now
        previous.save(update_fields=["superseded_at", "updated_at"])

    filing.submitted_at = when
    filing.filing_method = filing_method or ""
    filing.save(update_fields=["submitted_at", "filing_method", "updated_at"])
    data = render_filing_pdf(filing)
    filing.filed_pdf = data
    filing.filed_sha256 = hashlib.sha256(data).hexdigest()
    filing.snapshot_state = OSPAnnualUpdate.SNAPSHOT_FROZEN
    filing.save(update_fields=["filed_pdf", "filed_sha256", "snapshot_state", "updated_at"])
    return filing


@transaction.atomic
def correct_filing(filing, user):
    """Open the next revision as an unsigned copy of this one. This one is not touched."""
    from certifications.models import OSPAnnualUpdate

    filing = OSPAnnualUpdate.objects.select_for_update().get(pk=filing.pk)
    if not filing.is_locked:
        raise FilingStateError(
            "This revision has not been signed or filed. Edit it directly; a correction is for a "
            "revision that is already part of the record.",
            status_code=400,
        )
    if OSPAnnualUpdate.objects.filter(corrects=filing).exists():
        raise FilingStateError(
            f"Revision {filing.revision_number} already has a correction. Work on the newest revision."
        )
    if filing.withdrawn_at is not None:
        raise FilingStateError("A withdrawn revision is not corrected. Start the year's update again.")
    return OSPAnnualUpdate.objects.create(
        prior_osp=filing.prior_osp,
        new_osp=filing.new_osp,
        establishment_id=filing.establishment_id,
        reporting_year=filing.reporting_year,
        revision_number=filing.revision_number + 1,
        corrects=filing,
        changes_summary=filing.changes_summary,
        additions=list(filing.additions or []),
        deletions=list(filing.deletions or []),
        sections_unchanged_attestation=dict(filing.sections_unchanged_attestation or {}),
        application_info_changes=filing.application_info_changes,
        agent_requested_info=filing.agent_requested_info,
        agent_requested_info_none=filing.agent_requested_info_none,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )


@transaction.atomic
def withdraw_filing(filing, reason: str):
    from certifications.models import OSPAnnualUpdate

    filing = OSPAnnualUpdate.objects.select_for_update().get(pk=filing.pk)
    reason = (reason or "").strip()
    if not reason:
        raise FilingStateError("Say why this revision is withdrawn.", status_code=400)
    if filing.submitted_at is None:
        raise FilingStateError(
            "Only a filed revision is withdrawn. A revision that was never filed can be deleted.",
            status_code=400,
        )
    if filing.withdrawn_at is not None:
        raise FilingStateError(f"Already withdrawn on {filing.withdrawn_at.date().isoformat()}.")
    filing.withdrawn_at = timezone.now()
    filing.withdrawal_reason = reason
    filing.save(update_fields=["withdrawn_at", "withdrawal_reason", "updated_at"])
    return filing


def year_revisions(filing):
    """Every revision of `filing`'s year for its establishment, oldest first."""
    from certifications.models import OSPAnnualUpdate

    if filing is None:
        return []
    return list(
        OSPAnnualUpdate.objects.filter(establishment_id=filing.establishment_id, reporting_year=filing.reporting_year)
        .select_related("prior_osp", "new_osp", "corrects")
        .order_by("revision_number")
    )


def packet_revision_filename(filing) -> str:
    return f"annual-update/{filing.reporting_year}-revision-{filing.revision_number}.pdf"


def filed_bytes(filing):
    """The frozen document as bytes, or None when the revision has no frozen copy."""
    if filing is None or filing.filed_pdf is None:
        return None
    return bytes(filing.filed_pdf)


def packet_filing(queryset):
    """The revision a packet carries from `queryset`: the newest year, and within it the
    current filed revision, else the newest revision not yet filed. Superseded and withdrawn
    revisions are never the packet's filing; the 02s supplement reports them."""
    candidates = list(
        queryset.filter(superseded_at__isnull=True, withdrawn_at__isnull=True).select_related(
            "prior_osp", "new_osp", "corrects"
        )
    )
    if not candidates:
        return None
    year = max(c.reporting_year for c in candidates)
    in_year = [c for c in candidates if c.reporting_year == year]
    filed = [c for c in in_year if c.submitted_at is not None]
    if filed:
        return max(filed, key=lambda c: c.revision_number)
    return max(in_year, key=lambda c: c.revision_number)
