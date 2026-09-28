"""Telling somebody at the farm that a note arrived.

WHAT WAS WRONG. Nothing in this app created a notification, and `Sidebar.tsx` has no badge
mechanism, so the only way to learn that a crew message was waiting was to remember to open the
inbox. A note that lands at 6am sat unread until somebody happened to look, while the crew member who
sent it believed they had filed something. The queue was the whole feature and it had no doorbell.

FOUR RULES, each one a mistake that was available to make here.

1. `transaction.on_commit`, not merely "after the atomic block". A ping for a row that a later
   IntegrityError rolls back is a lie, and this webhook has a real concurrent-duplicate path that
   raises exactly that (`fieldnotes/views.py`).

2. try/except around everything. This is an ANONYMOUS webhook, and an uncaught exception here is a
   500, and a 500 makes the provider RETRY. A notification that fails must never turn a note that
   was successfully written into a redelivery loop. Losing a ping is recoverable; a retry storm is
   not.

3. CA **and** FM. The nearest precedent (`history/views.py`) fans out to `role="CA"` only, and the
   documented confirmer for this feature is "a supervisor", who typically holds FARM_MANAGER. A ping
   addressed to a role the confirmer does not have is the same as no ping. The repo's own broader
   precedent for farm-operations recipients is `role__in=[COMPANY_ADMIN, FARM_MANAGER]`.

4. THE PING NEVER STATES THE PRACTICE AND CARRIES NO PARSE. It says a message arrived and who from.
   It does not say what they reported, and `extra_data` carries no `event_type`, product or rate.
   Two reasons, and both matter more than the convenience:

     * A notification that said "Miguel sprayed block 4" would be a machine asserting a farming
       event before any human confirmed it, and it would turn the confirm step into a rubber stamp on
       a draft somebody already read as fact. 7 CFR 205.201(a) makes the producer the author.
     * The words would then live in the notification store, and in any future digest or email built
       from it. The same care is already taken to keep a crew member's sentence out of URLs and
       access logs.
"""

import logging

from django.contrib.auth import get_user_model

from users.models import WorksIn

logger = logging.getLogger(__name__)


def recipients_for(company_id):
    """Everyone at this company who could act on a waiting note.

    CA and FM, deliberately, and never VIEWER: a viewer cannot log the record the note is waiting
    for, so telling them is noise they cannot act on.
    """
    return (
        get_user_model()
        .objects.filter(
            worksin__company_id=company_id,
            worksin__role__in=[WorksIn.COMPANY_ADMIN, WorksIn.FARM_MANAGER],
        )
        .distinct()
    )


def notify_field_note_arrived(note):
    """Announce a waiting note. Never raises.

    Call this from inside `transaction.on_commit`, so it runs only if the note is really there.
    """
    # Imported here rather than at module scope: `fieldnotes` must stay importable without pulling
    # the notifications app in, and a guard test asserts this app never reaches for an event model.
    from notifications.models import NotificationType
    from notifications.services import NotificationService

    try:
        who = note.sender_display_name or note.sender_phone[-4:] or "a crew number"

        # A REFUSED note is announced too, and that is the more useful half today: every voice note
        # is refused until ASR is wired, so "we could not read what Miguel sent" is the thing a
        # supervisor most needs to hear and the thing no surface said. A refusal is also the one
        # outcome the sender cannot discover for themselves.
        if note.status == note.REFUSED:
            title = "A field note could not be read"
            message = f"{who} sent a message Trazo could not turn into a suggestion. Open Field notes to see why."
        else:
            title = "New field note"
            message = f"{who} sent a message. Open Field notes to review it and log the record."

        service = NotificationService()
        for user in recipients_for(note.company_id):
            service.create_notification(
                recipient=user,
                notification_type=NotificationType.SYSTEM_ALERT,
                title=title,
                message=message,
                extra_data={
                    # The client routes on `kind`, the way it already does for `export_ready`.
                    "kind": "field_note",
                    "note": str(note.public_id),
                    "status": note.status,
                    # May be None: a note legitimately arrives with no farm, so the client must not
                    # require this to build a link. Never a parse, and never the words.
                    "establishment_id": note.establishment_id,
                },
            )
    except Exception:
        # See rule 2. The note is already written and the caller is an anonymous webhook whose 500
        # becomes a provider retry.
        logger.exception("could not announce field note %s", getattr(note, "public_id", "?"))
