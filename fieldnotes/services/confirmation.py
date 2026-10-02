"""Confirming a crew note into a record: the boundary, the proposal, and the history kept.

OSP alignment audit 2026-10, T29, with Oscar's Phase 4 rules (2026-10-01):

* An APPLICATION (a chemical application, a soil amendment, a beneficial release) may come from a
  crew note, but only through the application form with the confirmer typing the input details. The
  machine's reading of the message never fills a product, rate, quantity, area or unit on one. The
  rule follows the SELECTED event type and the record's own fields, never a keyword hint.
* What the machine proposed, what the confirmer applied, and the record as first saved are kept on a
  `FieldNoteConfirmation` row that is voided, never edited or deleted.
"""

from __future__ import annotations

import datetime as _dt
import decimal
import re
from typing import Optional

from django.db import models

from fieldnotes.models import FieldNote, FieldNoteConfirmation

CHEMICAL = 2
SOIL = 5
PEST = 6

#: Soil types that are applications of a material.
SOIL_APPLICATION_TYPES = {"PA", "OM"}
#: Pest types that release or apply a material.
PEST_APPLICATION_TYPES = {"BR"}

#: A machine-applied key naming an input detail. Matched on the field name, so a new input field
#: (`*_rate`, `*_quantity`, `*_unit`, ...) is covered without editing this list.
INPUT_FIELD = re.compile(
    r"(product|commercial_name|manufacturer|active_ingredient|epa|lot_number|rate|quantity|amount|volume|"
    r"area|dose|dosage|concentration|npk|species|_numeric|_unit|method)",
    re.IGNORECASE,
)

#: Keys of a proposal the client may send. Anything else is dropped, never stored.
PROPOSAL_KEYS = {"offered", "applied", "model", "language", "negation"}


def is_application(event_type: int, data: dict) -> bool:
    """Is this record an application of a material? From the selected type and the record's fields."""
    if event_type == CHEMICAL:
        return True
    if event_type == SOIL:
        if (data.get("type") or "") in SOIL_APPLICATION_TYPES:
            return True
        return any(str(v or "").strip() for k, v in data.items() if k.startswith("amendment_"))
    if event_type == PEST:
        return (data.get("type") or "") in PEST_APPLICATION_TYPES
    return False


def clean_proposal(raw) -> dict:
    """The client's account of the machine proposal, reduced to known keys and plain JSON."""
    if not isinstance(raw, dict):
        return {}
    out = {k: raw[k] for k in PROPOSAL_KEYS if k in raw}
    applied = out.get("applied")
    out["applied"] = sorted({str(k) for k in applied}) if isinstance(applied, (list, tuple)) else []
    offered = out.get("offered")
    out["offered"] = offered if isinstance(offered, dict) else {}
    for key in ("model", "language", "negation"):
        if key in out:
            out[key] = str(out[key] or "")[:64]
    return out


def machine_values_on_application(event_type: int, data: dict, proposal: dict) -> list[str]:
    """Input keys the machine filled on an application record. Empty when the rule is kept."""
    if not is_application(event_type, data):
        return []
    return [key for key in proposal.get("applied", []) if INPUT_FIELD.search(key)]


def _plain(value):
    if isinstance(value, (_dt.datetime, _dt.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (list, dict, str, int, float, bool)) or value is None:
        return value
    return str(value)


def snapshot_values(event) -> dict:
    """The record's own columns as saved. Relations by id; nothing derived."""
    out = {}
    for field in event._meta.concrete_fields:
        if isinstance(field, models.FileField):
            continue
        out[field.attname] = _plain(getattr(event, field.attname))
    return out


def snapshot_source(note: FieldNote) -> dict:
    phone = note.sender_phone or ""
    return {
        "note_public_id": str(note.public_id),
        "sender_display_name": note.sender_display_name or "",
        "sender_phone_last4": phone[-4:] if phone else "",
        "kind": note.kind,
        "received_at": note.received_at.isoformat() if note.received_at else None,
        "provider": note.provider,
        "provider_message_id": note.provider_message_id,
        "words": note.words or "",
        "words_are_transcript": note.kind == FieldNote.VOICE,
        "transcript_language": note.transcript_language or "",
    }


def _norm(value) -> str:
    text = str(value).strip().lower()
    try:
        number = float(text)
    except ValueError:
        return " ".join(text.split())
    return ("%f" % number).rstrip("0").rstrip(".")


def _offered_values(offered) -> set:
    """Every scalar the machine reading offered, normalised for comparison."""
    out = set()

    def walk(value):
        if isinstance(value, dict):
            for key, inner in value.items():
                if key in ("unit", "category"):
                    continue
                walk(inner)
        elif isinstance(value, (list, tuple)):
            for inner in value:
                walk(inner)
        elif value not in (None, ""):
            out.add(_norm(value))

    walk(offered)
    return out


def server_match(note: FieldNote, values: dict) -> dict:
    """The server's own finding: which input values of the record match its latest reading of the
    note. Not a refusal (a rate typed from the farm's records may equal the number in the message);
    a fact the dossier states as the server's, beside the app's report (review of #88)."""
    from fieldnotes.models import FieldNoteExtraction

    reading = FieldNoteExtraction.objects.filter(note=note).order_by("-created_at", "-id").first()
    if reading is None:
        return {"reading_recorded": False, "matched": []}
    offered = _offered_values(reading.offered)
    matched = sorted(
        key
        for key, value in values.items()
        if INPUT_FIELD.search(key) and value not in (None, "") and _norm(value) in offered
    )
    return {
        "reading_recorded": True,
        "reading_at": reading.created_at.isoformat(),
        "offered_count": len(offered),
        "matched": matched,
    }


def record_confirmation(note: FieldNote, event, event_type: int, user, proposal: dict, when) -> FieldNoteConfirmation:
    name = ""
    if user is not None:
        name = (user.get_full_name() or "").strip() or (getattr(user, "email", "") or "")
    values = snapshot_values(event)
    proposal = {**(proposal or {}), "server": server_match(note, values)}
    return FieldNoteConfirmation.objects.create(
        note=note,
        company_id=note.company_id,
        event_type=event_type,
        event_id=event.id,
        confirmed_by=user,
        confirmed_by_name=name,
        confirmed_at=when,
        source=snapshot_source(note),
        proposal=proposal,
        confirmed_values=values,
    )


def void_confirmations(event_type: int, event_id: int, reason: str, when) -> int:
    """Void the current confirmation(s) of a deleted record. The rows stay."""
    count = 0
    for row in FieldNoteConfirmation.objects.filter(event_type=event_type, event_id=event_id, voided_at__isnull=True):
        row.voided_at = when
        row.void_reason = reason[:500]
        row.save(update_fields=["voided_at", "void_reason"])
        count += 1
    return count


def current_confirmation(event_type: int, event_id: int) -> Optional[FieldNoteConfirmation]:
    return (
        FieldNoteConfirmation.objects.filter(event_type=event_type, event_id=event_id, voided_at__isnull=True)
        .order_by("-confirmed_at")
        .first()
    )
