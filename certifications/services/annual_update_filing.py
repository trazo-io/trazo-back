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
  changes only by correction; the viewset refuses edits with 409. Signing is refused while the
  update attests a § 205.201(a) section unchanged that differs between the two plan versions
  (`attested_sections_that_differ`); saving a draft never is, and neither is filing, which
  records what was already sent.
* **File** needs a signature, sets the filing date and method once, and freezes the document as
  rendered at that moment (`filed_pdf`, `filed_sha256`). Document 02 is those bytes from then on.
  The same bytes are filed to the farm's Documents (`organic_system_plan`, source
  `annual_update`) in the same transaction, so a filing never exists without its shelf copy or
  the other way round. Unlike a download, where `file_document` failing must not stop the file
  the farmer asked for, a filing whose copy cannot be stored is refused and nothing is recorded:
  the operator tries again. (A storage write cannot be rolled back with the database, so a
  failure after the object was written can leave an unreferenced object in storage; it is never
  listed, because the row that would list it was rolled back.)
* **Correct** opens revision N+1 as an unsigned copy. Revision N keeps its bytes. Filing N+1
  marks N superseded; the year never has two current filings.
* **Withdraw** is a status with a reason. The row and its bytes stay.

Supporting documents (§ 205.406(a)(1) "supported by documentation") are links to files on the
Documents shelf. They are signed with the rest once any is attached, carried into a correction,
printed on 02 and shipped in the renewal packet under `annual-update/supporting/`.

Revisions filed before 2026-11-02 have no Documents copy and are not given one: a document
appearing on the shelf that nobody filed is what documents/models.py forbids.

Rows filed before this existed have no frozen copy and no signer. They are `legacy_none`, and the
packet says so rather than presenting today's rendering as what was filed (migration 0044).
"""

from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone


class FilingStateError(Exception):
    """An action that the filing's current state does not allow. Carries the HTTP status the
    viewset answers with, a sentence the operator can act on and, where the app shows more than
    the sentence, the structured fields it reads (`extra`, merged into the response body)."""

    def __init__(self, detail: str, status_code: int = 409, extra: dict | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.extra = extra or {}


#: The refusal code on a signing refused by `attested_sections_that_differ`. The app reads it
#: and the `sections` beside it to name each section in the reader's language.
ATTESTED_UNCHANGED_BUT_DIFFERS = "attested_unchanged_but_differs"

#: The refusal code on a signing refused by `_refuse_unstated_basis`.
PRIOR_PLAN_BASIS_REQUIRED = "prior_plan_basis_required"


def is_first_version(osp) -> bool:
    """`osp` is the operation's first plan version in Trazo: no version came before it, so no filing
    produced it (a fork always sets `previous_version`)."""
    return osp is not None and osp.previous_version_id is None


def basis_question_applies(osp) -> bool:
    """Whether a filing continuing `osp` must say what the certifier holds (`prior_plan_basis`).

    Only for a first version that has left draft. A draft was never submitted, so the certifier
    cannot hold it and the answer is `agent_file` without asking (the serializer sets it). A later
    version came from an earlier one in Trazo, so the comparison between versions stands.
    """
    return is_first_version(osp) and osp.status != "draft"


#: How the English sentence names each kind of difference (`plan_version_changes.DIFFERS_*`).
_DIFFERS_WORDS = {
    "answers": "answers",
    "materials": "the materials list",
    "narrative": "your own narrative",
    "record_types": "the record types confirmed",
}


def attested_sections_that_differ(filing) -> list[dict]:
    """The § 205.201(a) sections `filing` attests unchanged whose content differs between the plan
    it continues (`prior_osp`) and the version it produced (`new_osp`), in regulation order.

    Overall review 2026-11, OV-PK-O01: "Mark all unchanged" set every section in one click and
    nothing compared the two versions at signing, so a filed update could attest a section
    unchanged while the same packet's 02s printed that its answers differ. "Differs" is
    `plan_version_changes.section_differences`, the comparison 02s prints: a module answer or a
    not-applicable election compiled into the section, the materials list for (a)(2), the
    operator's own narrative, and which record types were confirmed. Write times, status and
    carried-forward stamps are not compared, so a section only re-saved is not a change.

    Empty when there is no second version to compare: an update that produced no new version (a
    first year in Trazo, or a plan continued as it is) is the operator's statement alone. The
    application information (§ 205.406(a)(3)) is not a plan section and is not checked here.
    """
    from certifications.models import OSP_SECTION_KEYS
    from certifications.services.osp_pdf_snapshot import SECTION_LABELS
    from certifications.services.plan_version_changes import section_differences

    attestation = filing.sections_unchanged_attestation
    if not isinstance(attestation, dict):
        return []
    attested = [key for key in OSP_SECTION_KEYS if attestation.get(key) is True]
    prior, new = filing.prior_osp, filing.new_osp
    if not attested or prior is None or new is None or new.pk == prior.pk:
        return []
    differences = section_differences(prior, new)
    rows = []
    for key in attested:
        if key not in differences:
            continue
        clause, label = SECTION_LABELS.get(key, ("", key))
        rows.append(
            {
                "section": key,
                "clause": clause,
                "label": label,
                "differs": list(differences[key]["differs"]),
                "modules": [
                    {"key": module.key, "code": module.code, "title": dict(module.title)}
                    for module in differences[key]["modules"]
                ],
            }
        )
    return rows


def _what_differs(row: dict) -> str:
    words = []
    for kind in row["differs"]:
        word = _DIFFERS_WORDS.get(kind, kind)
        if kind == "answers" and row["modules"]:
            word += " in " + ", ".join(f"{m['code']} {m['title'].get('en', '')}".strip() for m in row["modules"])
        words.append(word)
    return ", ".join(words)


def _refuse_attestation_that_differs(filing):
    """Raise when `filing` attests a section unchanged that differs between its plan versions."""
    rows = attested_sections_that_differ(filing)
    if not rows:
        return
    prior, new = filing.prior_osp.version_number, filing.new_osp.version_number
    listed = "; ".join(f"§ 205.201{row['clause']} {row['label']} ({_what_differs(row)})" for row in rows)
    them = "that section" if len(rows) == 1 else "those sections"
    said = (
        f"says {'this section is' if len(rows) == 1 else 'these sections are'} unchanged since plan v{prior}, "
        f"but plan v{new} differs there: {listed}."
    )
    detail = f"Not signed. This update {said} Untick {them} and describe the change in the summary, then sign."
    raise FilingStateError(
        detail,
        status_code=400,
        extra={
            "code": ATTESTED_UNCHANGED_BUT_DIFFERS,
            "action": "sign",
            "prior_osp_version": prior,
            "new_osp_version": new,
            "sections": rows,
        },
    )


def _refuse_unstated_basis(filing):
    """Raise when `filing` continues a first plan version and does not say what the certifier holds.

    Asked at signing, not at saving: a draft may be saved half done, but a signed filing names the
    plan its changes are measured against, and on a first version only the operation knows whether
    that is this version or the plan it filed before Trazo (overall review 2026-11, OV-PK-C01).
    """
    if filing.prior_plan_basis or not basis_question_applies(filing.prior_osp):
        return
    version = filing.prior_osp.version_number
    raise FilingStateError(
        f"Not signed. Plan v{version} is the first plan version in Trazo. Say whether your certifier received "
        "this version from Trazo or holds the plan you filed with it before Trazo, then sign.",
        status_code=400,
        extra={"code": PRIOR_PLAN_BASIS_REQUIRED, "action": "sign", "prior_osp_version": version},
    )


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
def sign_filing(filing, user, signer_title: str = "", *, compare_plan_versions: bool = True):
    """Sign `filing` as `user`.

    `compare_plan_versions=False` is for one caller only: `seed_calapooia_bend`, which replays
    revisions filed on 2026-10-01 and 2026-10-02, before signing compared the plan versions or asked
    what the certifier holds (`prior_plan_basis`, 2026-11-14), and restores their committed frozen
    bytes. Those bytes are records and print the attestation as it was signed. The viewset never
    passes it, and no request field reaches it.
    """
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
    if compare_plan_versions:
        _refuse_unstated_basis(filing)
        _refuse_attestation_that_differs(filing)
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


def filed_document_title(filing) -> str:
    return f"Annual update {filing.reporting_year}, revision {filing.revision_number}"


def filed_document_filename(filing) -> str:
    return f"annual-update-{filing.reporting_year}-revision-{filing.revision_number}.pdf"


def _file_to_documents(filing, data: bytes, user):
    """File the frozen bytes on the farm's Documents shelf, or raise so the filing rolls back."""
    from documents.services.filing import file_document

    # A savepoint of its own: `file_document` logs and swallows its errors, and a database error
    # inside it leaves the transaction unusable. Raising inside the savepoint rolls it back
    # cleanly before the outer transaction unwinds the filing itself.
    with transaction.atomic():
        doc = file_document(
            establishment=filing.establishment or filing.prior_osp.establishment,
            source="annual_update",
            folder="organic_system_plan",
            title=filed_document_title(filing),
            filename=filed_document_filename(filing),
            content=data,
            content_type="application/pdf",
            created_by=user,
        )
        if doc is None:
            raise FilingStateError(
                "The filed document could not be saved to Documents, so the filing was not recorded. "
                "Nothing changed; try again.",
                status_code=503,
            )
    return doc


@transaction.atomic
def file_filing(filing, filing_method: str = "", submitted_at=None, user=None):
    """Record that the signed revision reached the agent, freeze what it said, and file that
    frozen copy to the farm's Documents. All of it or none of it.

    Never refused over the unchanged-section attestation: signing is where that is checked, and
    filing records what was sent. Refusing it would leave Trazo saying "not filed" about a revision
    the agent already holds. If the plan version moves after signing, 02s sets the attestation
    beside the comparison ("Sections attested unchanged that changed")."""
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
    # Exactly the frozen bytes, never a second render.
    filing.filed_document = _file_to_documents(filing, data, user)
    filing.save(update_fields=["filed_pdf", "filed_sha256", "snapshot_state", "filed_document", "updated_at"])
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
    correction = OSPAnnualUpdate.objects.create(
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
        sales_period_start=filing.sales_period_start,
        sales_period_end=filing.sales_period_end,
        prior_plan_basis=filing.prior_plan_basis,
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    # The evidence travels with the statement it supports; the operator edits the list on the
    # unsigned correction like any other field.
    correction.replace_supporting_documents(
        link.document for link in filing.supporting_links.select_related("document")
    )
    return correction


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
