"""The recording is kept only while the note is waiting.

A QUEUE, NOT AN ARCHIVE. The audio exists so a supervisor can check a transcript against what was
actually said, because ASR dropping a negation is undetectable by anyone who was not the speaker and
on this channel the speaker is never the person who confirms. Once the record is written, or the note
is discarded, that job is done and keeping the recording is only exposure.

TRAZO IS NOT WHERE IT IS DELETED FROM. The file lives at the provider, behind Basic auth, and this
calls the provider's delete endpoint. Twilio keeps media until it is deleted through the API, so a
note that is confirmed and never cleaned up leaves a crew member's voice recording there
indefinitely. `audio_deleted_at` records that Trazo asked, so "we removed it" and "it was never
there" stay different answers.

THE SWEEP IS REAL. This module used to defer the rest to "a later sweep" that was never written,
which made the promise above false for a refused note (released nowhere), a note stuck being read
(released nowhere), and a release that failed at the provider (never retried). It is
`manage.py release_stale_field_note_audio`.

NEVER RAISES. Every caller is finishing something that already succeeded: a record has been written,
or a supervisor has discarded a note. Failing their action because a cleanup call failed would undo
work for no benefit, and the row keeps its reference so a later sweep can retry.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def release_note_audio(note):
    """Delete this note's recording at the provider and stamp when. True when it is gone."""
    if note is None:
        return False
    if not getattr(note, "provider_media_ref", ""):
        return False
    if note.audio_deleted_at:
        return True

    try:
        from fieldnotes.services.transcribe import delete_media

        if not delete_media(note.provider_media_ref):
            # Left for a retry, and said out loud. The reference is deliberately NOT cleared: without
            # it nothing could ever finish the job, and the row would claim an audio-free state it
            # had not reached.
            logger.warning("field-notes: could not release audio for note %s", note.public_id)
            return False

        type(note).objects.filter(pk=note.pk).update(audio_deleted_at=timezone.now(), updated_at=timezone.now())
        note.audio_deleted_at = timezone.now()
        logger.info("field-notes: released audio for note %s", note.public_id)
        return True
    except Exception:
        logger.exception("field-notes: releasing audio raised for note %s", getattr(note, "public_id", "?"))
        return False
