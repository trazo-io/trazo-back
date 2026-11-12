"""Delete provider recordings that no longer have a reason to exist.

WHY THIS COMMAND EXISTS. `fieldnotes/services/retention.py` promised that audio is "kept only while
the note is waiting" and deferred the rest to "a later sweep". Review of #54 pointed out that the
sweep was never written, which made the promise false in three ways:

  * a REFUSED note keeps its recording until somebody acknowledges it or this window expires,
    on purpose: the recording is that note's only content, so a supervisor listening and typing
    it out is the whole reason the channel does not silently drop it;
  * a note stuck in TRANSCRIBING, which is every note under `FIELD_NOTE_RUNNER="worker"` since no
    worker command exists yet, keeps it forever too;
  * a release that failed at the provider is never retried, and the note keeps its reference
    precisely so it can be.

A refused note is playable on purpose: Trazo could not read it, so the recording is its only content
and a supervisor listening and typing it out is the whole reason the channel does not drop it
silently. That argues for keeping the audio a while, not for keeping it forever. This is what bounds
it.

    poetry run python manage.py release_stale_field_note_audio --days 14
    poetry run python manage.py release_stale_field_note_audio --dry-run

⚠️ IDEMPOTENT AND SAFE TO RE-RUN. `release_note_audio` no-ops on a note already stamped, treats a
provider 404 as deleted, and never raises. Nothing here deletes a Trazo row: only the recording at
the provider, and only the stamp locally.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from fieldnotes.models import FieldNote
from fieldnotes.services.retention import release_note_audio

# A refused note's recording is the only copy of what somebody reported, so the window is generous
# enough for a supervisor to come back from a weekend and still hear it.
DEFAULT_DAYS = 14

# A note WAITING for review keeps its recording, because listening is how the farm checks the
# transcript. But not forever (Oscar, 2026-11-12, from review of landing #45): a crew member was told
# the recording is deleted after review, and a note nobody opens would otherwise sit at Twilio with
# no end. The privacy policy (2.7, 6) and the inbox promise "never more than 30 days".
# 29, not 30: the sweep runs once a day, so a recording becomes eligible up to a day before the run
# that deletes it. Releasing at 29 days keeps the 30-day promise literal (review of landing #46),
# the same reasoning that makes the policy state a 7-day backup rotation as "within 8 days".
PROMISED_MAX_DAYS = 30
UNREVIEWED_DAYS = PROMISED_MAX_DAYS - 1


class Command(BaseCommand):
    help = "Delete provider audio for field notes that no longer need it."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_DAYS,
            help=f"How old a refused or stuck note must be before its audio is released (default {DEFAULT_DAYS}).",
        )
        parser.add_argument(
            "--unreviewed-days",
            type=int,
            default=UNREVIEWED_DAYS,
            help=f"How old a note still waiting for review must be before its audio is released "
            f"(default {UNREVIEWED_DAYS}).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be released and change nothing.",
        )

    def handle(self, *args, **options):
        days = options["days"]
        dry_run = options["dry_run"]
        cutoff = timezone.now() - timedelta(days=days)
        unreviewed_cutoff = timezone.now() - timedelta(days=options["unreviewed_days"])

        stale = FieldNote.objects.filter(
            kind=FieldNote.VOICE,
            audio_deleted_at__isnull=True,
        ).exclude(provider_media_ref="")

        # Two groups, and they are different facts rather than one cutoff.
        #
        #   * FINISHED: logged or discarded. The release should already have happened on that action,
        #     so anything here is a retry of a call that failed, and it is not time-based: there is no
        #     reason to wait before retrying something that should already be done.
        #   * COOLED OFF: refused, or stuck being read, past the cutoff. These are still playable, so
        #     the window is what makes "kept while it is useful" different from "kept forever".
        #   * NEVER REVIEWED: still waiting after UNREVIEWED_DAYS. The note stays in the queue with its
        #     transcript; only the recording goes.
        candidates = stale.filter(
            Q(status__in=[FieldNote.CONFIRMED, FieldNote.DISCARDED, FieldNote.ACKNOWLEDGED])
            | Q(status__in=[FieldNote.REFUSED, FieldNote.TRANSCRIBING], received_at__lt=cutoff)
            | Q(status=FieldNote.PENDING, received_at__lt=unreviewed_cutoff)
        ).order_by("received_at")

        total = candidates.count()
        if not total:
            self.stdout.write("Nothing to release.")
            return

        released = 0
        failed = 0
        for note in candidates.iterator():
            label = f"{note.public_id} ({note.status}, received {note.received_at:%Y-%m-%d})"
            if dry_run:
                self.stdout.write(f"would release {label}")
                continue
            if release_note_audio(note):
                released += 1
            else:
                # Left for the next run. The reference is deliberately kept, so this is recoverable
                # rather than a row that now claims a state it never reached.
                failed += 1
                self.stderr.write(f"could not release {label}")

        if dry_run:
            self.stdout.write(f"{total} note(s) would be released.")
            return

        self.stdout.write(f"Released {released} of {total}.")
        if failed:
            # Non-zero so a scheduled run surfaces rather than looking clean while nothing happened.
            self.stderr.write(f"{failed} could not be released; they keep their reference for the next run.")
