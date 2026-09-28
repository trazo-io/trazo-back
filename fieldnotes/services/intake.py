"""The job that turns an inbound voice note into words a supervisor can review.

Same three runners as `documents/services/export_jobs.py`, for the same reasons: `thread` starts a
daemon thread AFTER the enqueue commits (a thread that starts inside the request's transaction cannot
see the row it was asked to run), `worker` leaves the row for a separate component, `eager` runs
inline so tests are synchronous. An unknown value raises rather than silently doing nothing.

METERED BEFORE ANYTHING IS SPENT. `consume_voice_session` had exactly two callers, both in
`carbon/views.py`, and neither was reachable from a background job, so a server-side transcription
path would have been free on the one deployment shape where audio actually costs money. One unit per
voice note, charged before the fetch, and a refusal when the day's budget is gone. Voice is on every
plan, so this is an anti-abuse valve rather than something a plan sells.

⛔ NO PARSE IS STORED. The extractor is not called here. At arrival nobody has chosen an activity, so
a parse would run with `known_activity=""` and no field list and be strictly worse than the one the
wizard performs at confirm time, when the supervisor has picked the activity and the form's real
fields are known. Storing the worse answer costs an OpenAI call per note and invites the
`ProductionPlanItem.prefill` mistake. The words are the product; the parse is an accelerator the
wizard already runs.
"""

import logging
import threading

from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from fieldnotes.models import FieldNote
from fieldnotes.services.transcribe import TranscriptionRefused, fetch_media, transcribe

logger = logging.getLogger(__name__)


def runner_mode():
    return getattr(settings, "FIELD_NOTE_RUNNER", "thread")


def dispatch(note):
    """Run, or arrange to run, the transcription for this note.

    Call inside the request that created it; the `thread` mode defers to commit itself.
    """
    mode = runner_mode()
    if mode == "eager":
        return run(note.pk)
    if mode == "thread":
        transaction.on_commit(lambda: _start_thread(note.pk))
        return None
    if mode == "worker":
        return None  # a worker command claims TRANSCRIBING rows
    raise ValueError(f"Unknown FIELD_NOTE_RUNNER {mode!r} (thread | worker | eager)")


def _start_thread(note_id):
    thread = threading.Thread(target=_thread_main, args=(note_id,), name=f"field-note-{note_id}", daemon=True)
    thread.start()
    return thread


def _thread_main(note_id):
    try:
        run(note_id)
    finally:
        # Django opens one connection per thread, and a daemon thread that ends without closing it
        # leaks a server-side connection until GC. CONN_MAX_AGE makes that worse, not better.
        connections.close_all()


def _refuse(note, reason):
    """Park the note with a reason a farmer can read. The row is KEPT.

    That somebody tried to file something at 14:02 is itself a record-keeping fact, and the inbox
    shows refusals precisely so "we could not read it" and "nothing arrived" stay different answers.
    """
    FieldNote.objects.filter(pk=note.pk).update(
        status=FieldNote.REFUSED,
        refusal_reason=reason[:64],
        updated_at=timezone.now(),
    )
    logger.info("field-notes: note %s refused (%s)", note.public_id, reason)


def run(note_id):
    """Transcribe one note. Never raises.

    The caller is either a daemon thread with nobody watching or the commit hook of an anonymous
    webhook, so an exception escaping here is either a silently dead thread or a 500 that makes the
    provider redeliver a message already stored.
    """
    try:
        note = FieldNote.objects.select_related("company").filter(pk=note_id).first()
        if note is None:
            return None
        # Anything but TRANSCRIBING means somebody already handled it: a second runner, a retry, or a
        # supervisor who discarded it while the job was queued. Their decision wins.
        if note.status != FieldNote.TRANSCRIBING:
            logger.info("field-notes: note %s is %s, not transcribing; leaving it alone", note.public_id, note.status)
            return None
        if not note.provider_media_ref:
            _refuse(note, "media_unavailable")
            return None

        # METER FIRST, before a byte is fetched or a cent is spent.
        from carbon.services.voice_budget import consume_voice_session

        allowed, used, ceiling = consume_voice_session(note.company)
        if not allowed:
            logger.warning("field-notes: company %s is over its voice budget (%s/%s)", note.company_id, used, ceiling)
            _refuse(note, "voice_daily_limit")
            return None

        audio = fetch_media(note.provider_media_ref)
        text, locale = transcribe(audio, content_type=note.media_content_type or "audio/ogg")

        FieldNote.objects.filter(pk=note.pk, status=FieldNote.TRANSCRIBING).update(
            transcript=text,
            transcript_language=locale,
            status=FieldNote.PENDING,
            updated_at=timezone.now(),
        )
        logger.info("field-notes: note %s transcribed (%s)", note.public_id, locale)

        # Announced only now. A ping when the audio arrived would have told a supervisor to go and
        # read something that did not exist yet.
        from fieldnotes.services.arrival import notify_field_note_arrived

        note.refresh_from_db()
        notify_field_note_arrived(note)
        return note
    except TranscriptionRefused as refused:
        note = FieldNote.objects.filter(pk=note_id).first()
        if note is not None:
            _refuse(note, refused.reason)
            # A refusal is announced too: that a voice note could not be read is the single most
            # useful thing this channel can say, and the one outcome the sender cannot discover.
            from fieldnotes.services.arrival import notify_field_note_arrived

            note.refresh_from_db()
            notify_field_note_arrived(note)
        return None
    except Exception:
        logger.exception("field-notes: transcription failed for note %s", note_id)
        note = FieldNote.objects.filter(pk=note_id).first()
        if note is not None and note.status == FieldNote.TRANSCRIBING:
            # Parked rather than left spinning. A note stuck on "being read" forever is worse than
            # one that says it could not be read, because nobody knows whether to wait.
            _refuse(note, "transcription_failed")
        return None
