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


def default_signer_name(filing, user) -> str:
    """Who signs by default: the operation's responsible person (the farm profile's contact
    person, the name the packet cover prints under "Responsible person"), else the account.

    Recordkeeping review S7 (F-23, 2026-10-07): the signature line printed the ACCOUNT's name
    ("Signed in Trazo by Pass Owner") under a cover that named Laurel Brandt as the responsible
    person. The signer is the operation's statement; the account is the recorder, kept apart in
    `signed_by`."""
    osp = getattr(filing, "prior_osp", None)
    est = getattr(osp, "establishment", None)
    responsible = (getattr(est, "contact_person", None) or "").strip()
    if responsible:
        return responsible
    # Same fallback as the packet cover's "Responsible person" (`_renewal_context`): the plan's
    # author, then the signing account (review of back #135), so the two never disagree.
    # A setup operator authored the plan as a recorder; the grower signing is the signer, never
    # the operator (rehearsal 2026-10-18). Same rule as the cover.
    from subscriptions.pilot_operator import is_setup_operator

    author = getattr(osp, "created_by", None)
    if author is not None and not is_setup_operator(author) and _signer_name(author):
        return _signer_name(author)
    return _signer_name(user)


@transaction.atomic
def sign_filing(filing, user, signer_title: str = ""):
    from certifications.models import OSPAnnualUpdate
    from subscriptions.pilot_operator import refuse_setup_operator

    # First, before any name is chosen: `default_signer_name` falls back to the signing account,
    # so a setup operator reaching it would sign in its own name or the grower's (back #176).
    refusal = refuse_setup_operator(user, "signing the annual update")
    if refusal:
        raise FilingStateError(refusal, status_code=403)

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
    filing.signer_name = default_signer_name(filing, user)[:255]
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
    if filing.superseded_at is not None or OSPAnnualUpdate.objects.filter(corrects=filing).exists():
        # Only the newest revision of a year is filed. Without this, a revision signed, then
        # corrected, could be filed after its correction and collide with it as a second current
        # filing for the year (a 500 from the constraint; review of back #79).
        raise FilingStateError(
            f"Revision {filing.revision_number} has a correction. File the newest revision of the "
            f"{filing.reporting_year} update instead."
        )
    current = (
        OSPAnnualUpdate.objects.filter(
            establishment_id=filing.establishment_id,
            reporting_year=filing.reporting_year,
            submitted_at__isnull=False,
            superseded_at__isnull=True,
            withdrawn_at__isnull=True,
        )
        .exclude(pk=filing.pk)
        .exclude(pk=filing.corrects_id)
        .first()
    )
    if current is not None:
        raise FilingStateError(
            f"Revision {current.revision_number} is already the filed {filing.reporting_year} update. "
            "Correct it rather than filing another."
        )
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
    # By calendar day: a date-only filing date is stored at midday, which is "later" than a
    # morning request on the same day (review of back #79).
    if timezone.localdate(when) > timezone.localdate(now):
        raise FilingStateError("The filing date cannot be in the future.", status_code=400)

    previous = filing.corrects
    if previous is not None and previous.superseded_at is None:
        # Filed or only signed, the revision this one corrects is replaced now, before this one
        # becomes current, so the year never holds two current filings and the older one can no
        # longer be filed.
        # Replaced on the day its successor was FILED, not the moment the filing was recorded: a
        # filing entered later with its real date otherwise moved the history (run 4, R4-02, where
        # revision 1 read "replaced 2026-10-02" beside a revision 2 filed 2026-10-01). Never before
        # the replaced revision's own filing.
        floor = previous.submitted_at or when
        previous.superseded_at = max(when, floor)
        previous.save(update_fields=["superseded_at", "updated_at"])

    filing.submitted_at = when
    filing.filing_method = filing_method or ""
    filing.save(update_fields=["submitted_at", "filing_method", "updated_at"])
    data = render_filing_pdf(filing, freezing=True)
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


def renewal_packet_filing(osp):
    """The filing a renewal packet built from `osp` carries; its year's revisions ship under
    `annual-update/`. One definition for the packet and for anything that points into it."""
    from certifications.models import OSPAnnualUpdate

    return packet_filing(OSPAnnualUpdate.objects.filter(new_osp=osp)) or packet_filing(
        OSPAnnualUpdate.objects.filter(prior_osp=osp)
    )


def packet_filing(queryset):
    """The revision a packet carries from `queryset`: the newest year, and within it the
    current filed revision, else the newest revision not yet filed. Superseded and withdrawn
    revisions are never the packet's filing; the 02s supplement reports them."""
    candidates = list(
        queryset.filter(superseded_at__isnull=True, withdrawn_at__isnull=True).select_related(
            "prior_osp", "new_osp", "corrects"
        )
    )
    # The year is chosen from EVERY revision. A year whose only filing was withdrawn is still the
    # newest year; choosing it from the live candidates fell back to an older clean year and
    # dropped the withdrawn one from 02 and 02s alike (review of back #79).
    years = list(queryset.values_list("reporting_year", flat=True))
    if not years:
        return None
    year = max(years)
    in_year = [c for c in candidates if c.reporting_year == year]
    if not in_year:
        return None
    filed = [c for c in in_year if c.submitted_at is not None]
    if filed:
        return max(filed, key=lambda c: c.revision_number)
    return max(in_year, key=lambda c: c.revision_number)
