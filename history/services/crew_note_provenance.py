"""Where a record came from when it came from a crew message: sender, performer, confirmer, kept apart.

OSP alignment audit 2026-10, T29. A record confirmed from a WhatsApp crew note carried only the
confirming user; the sender, the receipt time and the worker's words stayed on the note, and nothing
in the dossier, the CSV or the dashboard read them. An inspector asks: who did it, when did they do
it, when was it recorded, what did the worker say, what changed in review, who attested, and where is
the retained record.

The rules (Oscar, 2026-10-01):
  * three people, never merged: the SENDER (who sent the message), the PERFORMER (as the confirmer
    entered it, or "not recorded"; never inferred from the sender) and the CONFIRMER (who saved it);
  * three times, never merged: the stated OCCURRENCE (the record's date), the message RECEIVED time and
    the CONFIRMATION time;
  * record-specific statements only: what this record carries for 21 CFR 112.161(a)(2) timing,
    (a)(4) signature and (b) review, never a blanket verdict;
  * private surfaces only. Nothing here reaches the buyer page.

Read from the append-only `FieldNoteConfirmation` history; a record confirmed before that history
existed falls back to the note's own link and says so.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from fieldnotes.models import FieldNote, FieldNoteConfirmation


@dataclass
class CrewNoteProvenance:
    event_type: int
    event_id: int
    sender_name: str
    sender_last4: str
    kind: str
    received_at: Optional[str]
    words: str
    words_are_transcript: bool
    language: str
    confirmer_name: str
    confirmed_at: Optional[str]
    proposal_applied: List[str] = field(default_factory=list)
    proposal_offered: int = 0
    negation: str = ""
    confirmed_values: Dict = field(default_factory=dict)
    earlier_confirmations: List[Dict] = field(default_factory=list)
    from_history: bool = True

    def as_json(self) -> dict:
        return {
            "sender": {"display_name": self.sender_name, "phone_last4": self.sender_last4},
            "kind": self.kind,
            "received_at": self.received_at,
            "words": self.words,
            "words_are_transcript": self.words_are_transcript,
            "language": self.language,
            "confirmed_by": self.confirmer_name,
            "confirmed_at": self.confirmed_at,
            "machine_values_applied": list(self.proposal_applied),
            "machine_values_offered": self.proposal_offered,
            "negation": self.negation,
            "earlier_confirmations": list(self.earlier_confirmations),
        }


def event_type_of(event) -> Optional[int]:
    from history.constants import EVENT_TYPE_TO_MODEL

    for code, model in EVENT_TYPE_TO_MODEL.items():
        if isinstance(event, model):
            return code
    return None


def _company_of(event) -> Optional[int]:
    history = getattr(event, "history", None)
    parcel = getattr(history, "parcel", None) if history is not None else None
    establishment = getattr(parcel, "establishment", None) if parcel is not None else None
    return getattr(establishment, "company_id", None)


def provenance_for(events: Iterable) -> Dict[Tuple[int, int], CrewNoteProvenance]:
    """Crew-message provenance for each event that has one, keyed by (event type, event id).

    Scoped by the event's own company: a confirmation row or note of another company is never read.
    """
    keyed = {}
    for ev in events:
        code = event_type_of(ev)
        if code is not None and ev.pk is not None:
            keyed[(code, ev.pk)] = ev
    if not keyed:
        return {}
    company_by_key = {k: _company_of(ev) for k, ev in keyed.items()}
    out: Dict[Tuple[int, int], CrewNoteProvenance] = {}

    rows = FieldNoteConfirmation.objects.filter(
        event_id__in={k[1] for k in keyed}, event_type__in={k[0] for k in keyed}
    ).order_by("confirmed_at", "id")
    by_key: Dict[Tuple[int, int], List[FieldNoteConfirmation]] = {}
    for row in rows:
        key = (row.event_type, row.event_id)
        if key in keyed and row.company_id == company_by_key.get(key):
            by_key.setdefault(key, []).append(row)

    for key, rows_for_event in by_key.items():
        current = [r for r in rows_for_event if r.voided_at is None]
        if not current:
            continue
        row = current[-1]
        src = row.source or {}
        proposal = row.proposal or {}
        earlier = [
            {
                "confirmed_at": r.confirmed_at.isoformat(),
                "confirmed_by": r.confirmed_by_name,
                "voided_at": r.voided_at.isoformat() if r.voided_at else None,
                "void_reason": r.void_reason,
            }
            for r in FieldNoteConfirmation.objects.filter(note_id=row.note_id, voided_at__isnull=False).order_by(
                "confirmed_at"
            )
        ]
        out[key] = CrewNoteProvenance(
            event_type=key[0],
            event_id=key[1],
            sender_name=src.get("sender_display_name", ""),
            sender_last4=src.get("sender_phone_last4", ""),
            kind=src.get("kind", ""),
            received_at=src.get("received_at"),
            words=src.get("words", ""),
            words_are_transcript=bool(src.get("words_are_transcript")),
            language=src.get("transcript_language", ""),
            confirmer_name=row.confirmed_by_name,
            confirmed_at=row.confirmed_at.isoformat(),
            proposal_applied=list(proposal.get("applied") or []),
            proposal_offered=len(proposal.get("offered") or {}),
            negation=proposal.get("negation", ""),
            confirmed_values=row.confirmed_values or {},
            earlier_confirmations=earlier,
            from_history=True,
        )

    # Records confirmed before the history existed: the note's own link, labelled as such.
    missing = [k for k in keyed if k not in out]
    if missing:
        notes = FieldNote.objects.filter(
            status=FieldNote.CONFIRMED,
            fulfilled_by_id__in={k[1] for k in missing},
            fulfilled_by_event_type__in={k[0] for k in missing},
        ).select_related("confirmed_by")
        for note in notes:
            key = (note.fulfilled_by_event_type, note.fulfilled_by_id)
            if key not in missing or note.company_id != company_by_key.get(key):
                continue
            who = note.confirmed_by
            name = ((who.get_full_name() or "").strip() or who.email) if who else ""
            out[key] = CrewNoteProvenance(
                event_type=key[0],
                event_id=key[1],
                sender_name=note.sender_display_name or "",
                sender_last4=(note.sender_phone or "")[-4:],
                kind=note.kind,
                received_at=note.received_at.isoformat() if note.received_at else None,
                words=note.words or "",
                words_are_transcript=note.kind == FieldNote.VOICE,
                language=note.transcript_language or "",
                confirmer_name=name,
                confirmed_at=note.confirmed_at.isoformat() if note.confirmed_at else None,
                from_history=False,
            )
    return out


def _fmt(value) -> str:
    if not value:
        return "not recorded"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def lines(prov: CrewNoteProvenance, event) -> List[str]:
    """What the dossier prints for one record, in order. Facts about THIS record only."""
    who = prov.sender_name or "a rostered number"
    phone = f" (number ending {prov.sender_last4})" if prov.sender_last4 else ""
    kind = "voice message" if prov.kind == FieldNote.VOICE else "text message"
    out = [f"From a crew {kind} sent by {who}{phone}, received {_fmt(prov.received_at)}."]
    source = "machine transcript" if prov.words_are_transcript else "typed by the sender"
    if prov.language:
        source += f", language {prov.language}"
    out.append(f"The sender's message as received ({source}; this is the message, not the record): “{prov.words}”")

    occurred = getattr(event, "date", None)
    out.append(
        f"Stated occurrence: {_fmt(occurred)}. Message received: {_fmt(prov.received_at)}. "
        f"Confirmed into this record: {_fmt(prov.confirmed_at)} by {prov.confirmer_name or 'an account no longer on file'}."
    )
    try:
        confirmed = datetime.fromisoformat(prov.confirmed_at) if prov.confirmed_at else None
    except ValueError:
        confirmed = None
    if occurred and confirmed:
        days = (confirmed.date() - occurred.date()).days
        out.append(
            f"Timing (§ 112.161(a)(2)): this record was confirmed {days} day(s) after the stated occurrence."
            if days >= 0
            else "Timing (§ 112.161(a)(2)): the stated occurrence is after the confirmation time."
        )

    performer = (getattr(event, "performed_by", "") or "").strip()
    applicator = (getattr(event, "applicator_name", "") or "").strip()
    out.append(
        f"Performer: {performer} (as entered by the confirmer; not inferred from the sender)."
        if performer
        else "Performer: not recorded. The sender is not assumed to be the performer."
    )
    if applicator:
        out.append(f"Applicator: {applicator} (as entered by the confirmer).")
    out.append(
        "Signature (§ 112.161(a)(4)): Trazo stores no signature or initials from the performer for this record; "
        "the confirmation is the confirmer's."
    )
    if getattr(event, "reviewed", False):
        reviewer = (getattr(event, "reviewer_name", "") or "").strip() or "a reviewer not named"
        out.append(f"Review (§ 112.161(b)): reviewed by {reviewer} on {_fmt(getattr(event, 'review_date', None))}.")
    else:
        out.append("Review (§ 112.161(b)): no review recorded.")

    if not prov.from_history:
        out.append(
            "Confirmed before Trazo kept a confirmation history: the machine proposal and the values as first "
            "saved were not recorded."
        )
    elif prov.proposal_applied:
        out.append(
            f"Machine reading of the message: {prov.proposal_offered} value(s) offered; the confirmer applied "
            f"{', '.join(prov.proposal_applied)}."
        )
    else:
        out.append("Machine reading of the message: no values from it were applied to this record.")
    if prov.negation in ("all", "mixed"):
        out.append("The message was flagged for manual review because it negates some or all of what it describes.")

    if prov.from_history:
        from fieldnotes.services.confirmation import snapshot_values

        now = snapshot_values(event)
        changed = sorted(
            k
            for k, v in prov.confirmed_values.items()
            if k in now and now[k] != v and k not in {"updated_at", "index", "album_id"}
        )
        if changed:
            out.append("Changed since confirmation: " + ", ".join(changed) + " (see Documented Corrections).")
    for earlier in prov.earlier_confirmations:
        out.append(
            f"This message was earlier confirmed into a record by {earlier['confirmed_by'] or 'an account'} on "
            f"{_fmt(earlier['confirmed_at'])}; that confirmation was voided on {_fmt(earlier['voided_at'])} "
            f"({earlier['void_reason'] or 'no reason recorded'})."
        )
    return out
