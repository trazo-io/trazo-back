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
