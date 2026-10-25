"""Where a record came from, when a person typed it in from a document.

An operator setting a farm up transcribes the grower's own spray sheet, binder page or label photo
into records. The grower is still the author (7 CFR 205.201(a)); the operator is the typist, and
`created_by` says so. What was missing until 2026-10 is the OTHER half of that trace: which document
the record was read from, and where on it. A record transcribed from "spray log, sheet row 7"
printed into the audit dossier exactly like one the grower logged from the block that morning, so
an inspector following § 205.103(b)(2) back to the source had nothing to follow.

The pointer lives in `extra_data["source"]`, the same place the COG Pro importer has kept its
`cogpro_import.source_line` since 2026-08, and both importers write it through `write_record`
below. It is never a column on the event: eight concrete event models share `extra_data`, the
dossier already reads it, and the buyer page drops any key that is not allow-listed
(`history/serializers.py`, ALLOWED_EXTRA_DATA_KEYS), so a transcription note never reaches a
shopper.

Shape:

    {"kind": "transcription" | "cogpro_export",
     "doc": "<GeneratedDocument.public_id>" | None,   # the filed source document
     "doc_title": "Spray and field log 2026",         # its title at import time
     "locator": "sheet row 7",                        # where on it
     "batch": "3f9c0a1b2c3d" | None,                  # one import run
     "imported_at": "2026-10-27"}

No person inside it: `created_by` is the author column, and a second copy of a name is a second
place for it to be wrong.
"""

from __future__ import annotations

from datetime import date

SOURCE_KEY = "source"
KIND_TRANSCRIPTION = "transcription"
KIND_COGPRO = "cogpro_export"


def source_ref(kind, *, locator, doc=None, doc_title="", batch=None, imported_at=None) -> dict:
    return {
        "kind": kind,
        "doc": str(doc) if doc else None,
        "doc_title": doc_title or "",
        "locator": locator,
        "batch": batch,
        "imported_at": (imported_at or date.today()).isoformat(),
    }


def source_of(event):
    """The source pointer on a record, or None when it was not transcribed or imported."""
    extra = getattr(event, "extra_data", None)
    if not isinstance(extra, dict):
        return None
    src = extra.get(SOURCE_KEY)
    if not isinstance(src, dict) or not src.get("locator"):
        return None
    return src


def _person(event) -> str:
    user = getattr(event, "created_by", None)
    if user is None:
        return ""
    name = " ".join(p for p in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if p).strip()
    return name or (getattr(user, "email", "") or "")


def source_line(event) -> str:
    """One sentence for a document: who typed the record in, from which document, where on it.

    "Transcribed by Oscar Munoz (Trazo setup) from Spray and field log 2026, sheet row 7". The
    setup suffix comes with the operator's own last name (`subscriptions.pilot_operator`), so the
    role is stated without a second field saying it. `performed_by` (who did the work) stays its own
    column; the typist and the performer are never one line.
    """
    src = source_of(event)
    if src is None:
        return ""
    where = ", ".join(p for p in (src.get("doc_title") or "", src.get("locator") or "") if p)
    if src.get("kind") == KIND_COGPRO:
        head = "Imported"
        where = f"COG Pro export {where}".strip()
    else:
        head = "Transcribed"
    who = _person(event)
    by = f" by {who}" if who else ""
    return f"{head}{by} from {where}"


def write_record(model, *, history, fields, extra, created_by, application_group=None):
    """Create one event record the way the API does, minus the request.

    Shared by the COG Pro importer and the intake importer so neither grows its own `create`:
    `index` is the season's next slot (the API's own counter), `created_by` is the person who
    ran the import, and `application_group` links the records of one row logged on several
    parcels (`history/services/multi_target.py`). Model signals run on the save as on any other:
    block_id normalisation, the National List classification of a chemical, carbon, the retention
    floor, the drift detector. Deliberately NOT called: `History.update_trust_metrics`, which
    writes the retired transparency score.
    """
    from history.views import EventViewSet

    return model.objects.create(
        history=history,
        index=EventViewSet._next_event_index(history),
        created_by=created_by,
        application_group=application_group,
        extra_data=extra,
        **fields,
    )
