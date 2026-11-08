"""What a certifying agent's notice stands at, derived from what the operation recorded.

Never stored: a status column would be one more thing to keep in step with the dates and files it is
read from. The words are about the RECORD, never a verdict on the farm: no state here says
"compliant", "fixed" or "closed".

- `resolved`: the agent's § 205.662(b) resolution notice is attached.
- `resolution_stated_no_copy`: a resolution date is recorded but the notice itself is not on file.
  Only an attached notice answers; a date typed alone is the operator's statement.
- `respond_by_passed_no_response`: the § 205.662(a)(3) date has passed and no response is recorded.
- `response_sent`: a response is recorded (with or without its date) and no resolution yet.
- `open`: nothing past the notice itself is recorded.
"""

from datetime import date

RESOLVED = "resolved"
RESOLUTION_STATED_NO_COPY = "resolution_stated_no_copy"
RESPOND_BY_PASSED_NO_RESPONSE = "respond_by_passed_no_response"
RESPONSE_SENT = "response_sent"
OPEN = "open"

STATUSES = (RESOLVED, RESOLUTION_STATED_NO_COPY, RESPOND_BY_PASSED_NO_RESPONSE, RESPONSE_SENT, OPEN)


def _has_response(notice) -> bool:
    return bool(notice.response_kind or (notice.response_text or "").strip() or notice.response_sent_on)


def notice_status(notice, today: date | None = None) -> str:
    today = today or date.today()
    if notice.resolution_document_id:
        return RESOLVED
    if notice.resolution_received_on:
        return RESOLUTION_STATED_NO_COPY
    if _has_response(notice):
        return RESPONSE_SENT
    if notice.respond_by and notice.respond_by < today:
        return RESPOND_BY_PASSED_NO_RESPONSE
    return OPEN


def unresolved(notices, today: date | None = None) -> list:
    """The notices with no resolution notice attached, in the order given."""
    return [n for n in notices if notice_status(n, today) != RESOLVED]


#: How far back a RESOLVED item is still listed in the packet. An open item is listed at any age.
RESOLVED_LISTED_FOR_DAYS = 365


def packet_records(establishment, today: date | None = None):
    """What document 02s lists: (latest inspection or None, inspections listed, notices listed).

    - Every item with no resolution notice attached, at any age: it is still outstanding as far
      as the record shows (OTCO O1 D-1E asks for outstanding noncompliances).
    - Items resolved in the last `RESOLVED_LISTED_FOR_DAYS` days, by the resolution date or, when
      none is typed, by the date the row was last changed.
    - The most recent inspection (WSDA AGR 2262 5a(i) asks its date) and every inspection a listed
      item came from, newest first.
    """
    from datetime import timedelta

    from certifications.models import CertifierInspection, CertifierNotice

    today = today or date.today()
    cutoff = today - timedelta(days=RESOLVED_LISTED_FOR_DAYS)
    notices = []
    for notice in (
        CertifierNotice.objects.filter(establishment=establishment)
        .select_related("inspection", "notice_document", "resolution_document")
        .prefetch_related("response_links__document")
        .order_by("received_on", "pk")
    ):
        if notice_status(notice, today) != RESOLVED:
            notices.append(notice)
            continue
        resolved_on = notice.resolution_received_on or notice.updated_at.date()
        if resolved_on >= cutoff:
            notices.append(notice)
    inspections = list(
        CertifierInspection.objects.filter(establishment=establishment)
        .select_related("report_document")
        .order_by("-inspected_on", "-pk")
    )
    latest = inspections[0] if inspections else None
    wanted = {n.inspection_id for n in notices if n.inspection_id}
    if latest is not None:
        wanted.add(latest.pk)
    listed = [i for i in inspections if i.pk in wanted]
    return latest, listed, notices
