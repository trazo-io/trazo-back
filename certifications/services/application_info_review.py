"""The § 205.406(a)(3) step: the operation reviews the § 205.401(b) details Trazo holds.

WHY THIS MODULE EXISTS
----------------------
§ 205.406(a)(3) asks an annual update for "any additions to or deletions from the information
required pursuant to § 205.401(b)": the person responsible, the business name, address and
telephone number. Until 2026-11-02 the filing answered it with a free-text box and an
"unchanged" tick, and nothing read the company record, so an operator could tick "unchanged"
over a phone number that had been wrong in Trazo for a year, or type a new address into the
filing while the farm profile (and so the packet cover) kept the old one.

Here every detail Trazo holds is shown with the record it comes from. The operator answers each
one, and only then does anything change:

* ``correct``: the detail stands. A detail Trazo does not hold can only be "correct" when the
  operator types it (the certifying agent already has it; Trazo did not). An optional detail
  (trade name, email) may be confirmed empty.
* ``changed``: the new value is written to the Company or Establishment record through that
  record's own update serializer, and a dated line saying old -> new is appended to
  ``OSPAnnualUpdate.application_info_changes``, so the filing states the change.

Every detail answered ``correct`` with no change lines on the filing sets the existing
"unchanged" attestation. NEVER: infer "unchanged" from a detail nobody answered; a request that
leaves one out is refused.

A signed or filed revision refuses the step (the content is the record and changes only by
correction), and nothing here reads the company record when a filing is rendered: what the
filing says about (a)(3) is the signed text and attestation, so a later edit to the farm does
not alter it.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from rest_framework import serializers

#: Mirrors `osp_module_pdf.APPLICATION_INFO_KEY`; imported from there so the two never drift.
from certifications.services.osp_module_pdf import APPLICATION_INFO_KEY

COMPANY = "company"
ESTABLISHMENT = "establishment"

CORRECT = "correct"
CHANGED = "changed"


@dataclass(frozen=True)
class Detail:
    key: str
    #: English label: the change line prints on the filing, which is an English document.
    label: str
    #: Where an edit is written. The packet cover reads this field first, so writing here is
    #: what makes the cover print the new value.
    record: str
    field: str
    #: § 205.401(b) asks for it, so "correct" over an empty value is refused.
    required: bool
    #: The cover's own read order, (record, field) pairs; the first non-empty one is shown.
    reads: tuple = ()

    def read_order(self):
        return self.reads or ((self.record, self.field),)


#: The order and the read rules follow the packet cover (`osp_module_pdf._renewal_context`), so
#: the step shows exactly what the cover prints. The address is the farm's, as on the cover.
DETAILS: tuple[Detail, ...] = (
    Detail("legal_name", "Business name", COMPANY, "name", True),
    Detail("trade_name", "Trade name (DBA)", COMPANY, "tradename", False),
    Detail("responsible_person", "Responsible person", ESTABLISHMENT, "contact_person", True),
    Detail("address", "Street address", ESTABLISHMENT, "address", True),
    Detail("city", "City", ESTABLISHMENT, "city", True),
    Detail("state", "State", ESTABLISHMENT, "state", True),
    Detail("zip_code", "ZIP code", ESTABLISHMENT, "zip_code", True),
    Detail(
        "phone",
        "Phone",
        ESTABLISHMENT,
        "phone",
        True,
        reads=((ESTABLISHMENT, "phone"), (ESTABLISHMENT, "contact_phone"), (COMPANY, "contact_phone")),
    ),
    Detail(
        "email",
        "Email",
        ESTABLISHMENT,
        "contact_email",
        False,
        reads=((ESTABLISHMENT, "contact_email"), (ESTABLISHMENT, "email"), (COMPANY, "contact_email")),
    ),
)
DETAIL_BY_KEY = {d.key: d for d in DETAILS}


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def held_value(detail: Detail, establishment) -> tuple[str, str]:
    """(value, "record.field" it came from), or ("", "") when Trazo holds none."""
    records = {ESTABLISHMENT: establishment, COMPANY: establishment.company}
    for record, field in detail.read_order():
        value = _clean(getattr(records[record], field, None))
        if value:
            return value, f"{record}.{field}"
    return "", ""


def review_payload(filing, establishment, *, can_answer: bool, can_edit_company: bool) -> dict:
    """What the step shows: each detail as held, and the filing's current (a)(3) answer."""
    attestation = filing.sections_unchanged_attestation
    details = []
    for d in DETAILS:
        value, source = held_value(d, establishment)
        details.append(
            {
                "key": d.key,
                "label": d.label,
                "record": d.record,
                "field": d.field,
                "required": d.required,
                "value": value,
                "held": bool(value),
                "source": source,
                "editable": can_answer and (d.record != COMPANY or can_edit_company),
            }
        )
    return {
        "filing": filing.pk,
        "locked": filing.is_locked,
        "attested_unchanged": isinstance(attestation, dict) and attestation.get(APPLICATION_INFO_KEY) is True,
        "application_info_changes": filing.application_info_changes or "",
        "can_answer": can_answer and not filing.is_locked,
        "can_edit_company": can_edit_company,
        "details": details,
    }


class AnswerSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[CORRECT, CHANGED])
    value = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True, max_length=254)


class ApplicationInfoReviewSerializer(serializers.Serializer):
    """`{"answers": {"<detail key>": {"status": "correct" | "changed", "value": "..."}}}`.

    The payload carries no record ids: the Company and Establishment written are the filing's
    own, resolved on the server, so a request cannot point an edit at another tenant's record.
    The key check is field-level (`validate_answers`), never `validate()`."""

    answers = serializers.DictField(child=AnswerSerializer())

    def validate_answers(self, answers):
        unknown = sorted(set(answers) - set(DETAIL_BY_KEY))
        if unknown:
            raise serializers.ValidationError(f"Not a § 205.401(b) detail: {', '.join(unknown)}.")
        missing = [d.key for d in DETAILS if d.key not in answers]
        if missing:
            # The rule this step exists for: a detail nobody looked at is not "unchanged".
            raise serializers.ValidationError(
                "Answer every detail, correct or changed. Not answered: " + ", ".join(missing) + "."
            )
        return answers


class ReviewRefused(Exception):
    """Carries the status and body the view answers with."""

    def __init__(self, status_code: int, body: dict):
        super().__init__(body)
        self.status_code = status_code
        self.body = body


def _change_line(day, detail: Detail, old: str, new: str) -> str:
    if not old:
        return f"{day}: {detail.label} added: {new}."
    if not new:
        return f"{day}: {detail.label} removed (was {old})."
    return f"{day}: {detail.label} changed from {old} to {new}."


def apply_review(filing, establishment, answers: dict, request, *, can_edit_company: bool):
    """Write the answers. All or nothing: a refused record write leaves the filing untouched.

    Returns the filing as saved."""
    from certifications.models import OSPAnnualUpdate
    from company.serializers import RetrieveCompanySerializer, UpdateEstablishmentSerializer

    errors: dict[str, list[str]] = {}
    writes = {COMPANY: {}, ESTABLISHMENT: {}}
    changed: list[tuple[Detail, str]] = []  # (detail, value held before)
    for d in DETAILS:
        answer = answers[d.key]
        held, _source = held_value(d, establishment)
        typed = answer.get("value")
        if answer["status"] == CORRECT:
            if held:
                if typed is not None and typed != held:
                    errors[d.key] = [f"{d.label} is answered correct but a different value was sent: answer changed."]
                continue
            if typed:
                # Trazo held nothing; the agent already has this. Recorded, not a change.
                writes[d.record][d.field] = typed
            elif d.required:
                errors[d.key] = [f"Trazo holds no {d.label.lower()}. Type it; it is not filled in for you."]
            continue
        # CHANGED
        if typed is None:
            errors[d.key] = [f"Send the new {d.label.lower()}."]
            continue
        if not typed and d.required:
            errors[d.key] = [f"{d.label} is required by § 205.401(b) and cannot be removed."]
            continue
        if typed == held:
            errors[d.key] = [f"{d.label} is the same as Trazo holds: answer correct."]
            continue
        if d.record == COMPANY and not can_edit_company:
            raise ReviewRefused(
                403,
                {
                    "detail": (
                        f"Only a company admin can change the {d.label.lower()}. Ask one to make the "
                        "change, or answer correct if it has not changed."
                    ),
                    "answers": {d.key: ["Company admin only."]},
                },
            )
        writes[d.record][d.field] = typed
        # The value the record held is the "before"; a fallback read (phone from the company
        # profile) is still what the cover printed, so it is what the operator saw and changed.
        changed.append((d, held))
    if errors:
        raise ReviewRefused(400, {"answers": errors})

    context = {"request": request}
    company = establishment.company
    bound = []
    if writes[COMPANY]:
        bound.append((COMPANY, RetrieveCompanySerializer(company, data=writes[COMPANY], partial=True, context=context)))
    if writes[ESTABLISHMENT]:
        bound.append(
            (
                ESTABLISHMENT,
                UpdateEstablishmentSerializer(establishment, data=writes[ESTABLISHMENT], partial=True, context=context),
            )
        )
    # Each record's own validators (US phone, ZIP, state) run before anything is saved.
    for record, serializer in bound:
        if not serializer.is_valid():
            for field, messages in serializer.errors.items():
                key = next((d.key for d in DETAILS if d.record == record and d.field == field), field)
                errors[key] = [str(m) for m in (messages if isinstance(messages, list) else [messages])]
    if errors:
        raise ReviewRefused(400, {"answers": errors})

    with transaction.atomic():
        locked = OSPAnnualUpdate.objects.select_for_update().get(pk=filing.pk)
        if locked.is_locked:
            raise ReviewRefused(409, {"detail": "This revision is signed or filed; create a correction to change it."})
        for _record, serializer in bound:
            serializer.save()
        establishment.refresh_from_db()
        day = timezone.localdate().isoformat()
        lines = []
        company.refresh_from_db()
        for d, before in changed:
            # The value as SAVED: the state field is canonicalised ("Oregon" -> "OR") on write.
            after = _clean(getattr(company if d.record == COMPANY else establishment, d.field, None))
            lines.append(_change_line(day, d, before, after))
        stored = locked.sections_unchanged_attestation
        attestation = dict(stored) if isinstance(stored, dict) else {}
        text = (locked.application_info_changes or "").rstrip()
        if lines:
            text = "\n".join([text, *lines]) if text else "\n".join(lines)
            # A stated change and "unchanged" contradict each other; the change stands.
            attestation.pop(APPLICATION_INFO_KEY, None)
        elif not text:
            attestation[APPLICATION_INFO_KEY] = True
        # Every detail confirmed over a filing that already lists changes: the changes stand and
        # "unchanged" is not set. The details being right today is not "nothing changed".
        locked.application_info_changes = text
        locked.sections_unchanged_attestation = attestation
        locked.save(update_fields=["application_info_changes", "sections_unchanged_attestation", "updated_at"])
    return locked
