"""A note that arrives tells somebody, and tells them nothing it should not.

Before this, the app created no notification and the sidebar had no badge, so the only way to learn a
crew message was waiting was to remember to open the inbox. A note landing at 6am sat unread until
somebody looked, while the person who sent it believed they had filed something.

The four rules under test, each one a mistake that was available to make:

  * ON COMMIT. The duplicate-delivery path raises IntegrityError and rolls the transaction back, so a
    ping fired inside it would announce a row that does not exist.
  * NEVER 500. This is an anonymous webhook and a 500 makes the provider redeliver, so a failing
    notification must not turn a stored note into a retry loop.
  * CA AND FM. The nearest precedent fans out to CA only, and the documented confirmer is "a
    supervisor", who typically holds FARM_MANAGER. A ping addressed to a role the confirmer does not
    hold is the same as no ping.
  * NO PRACTICE, NO PARSE, NO WORDS. A ping saying "Miguel sprayed block 4" would be a machine
    asserting a farming event before a human confirmed it, and would turn the confirm step into a
    rubber stamp. It would also put a crew member's sentence in the notification store and any digest
    built from it.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from notifications.models import Notification
from product.models import Establishment
from users.models import WorksIn

TOKEN = "test-auth-token-not-a-real-secret"
URL = "https://api.trazo.io/api/field-notes/inbound/twilio/"
PATH = "/api/field-notes/inbound/twilio/"

WORDS = "regamos el bloque 4 esta manana"
PARAMS = {
    "MessageSid": "SM-arrival-0001",
    "From": "whatsapp:+14155551234",
    "Body": WORDS,
    "NumMedia": "0",
    "ProfileName": "Miguel",
}


def sign(params):
    import base64
    import hashlib
    import hmac

    payload = URL + "".join(f"{key}{params[key]}" for key in sorted(params))
    return base64.b64encode(hmac.new(TOKEN.encode(), payload.encode(), hashlib.sha1).digest()).decode()


@override_settings(TWILIO_AUTH_TOKEN=TOKEN, FIELD_NOTES_WEBHOOK_URL=URL, FIELD_NOTE_RUNNER="eager")
class FieldNoteArrivalPingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="Ping Co")
        self.farm = Establishment.objects.create(name="Ping Farm", company=self.company)

        self.admin = User.objects.create_user(email="ping-ca@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)

        # The persona the feature is written for. The nearest precedent would have missed them.
        self.manager = User.objects.create_user(email="ping-fm@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.manager, company=self.company, role=WorksIn.FARM_MANAGER)

        self.viewer = User.objects.create_user(email="ping-vw@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.viewer, company=self.company, role=WorksIn.VIEWER)

        self.outsider = User.objects.create_user(email="ping-out@example.com", password="pw-for-tests-only")
        other = Company.objects.create(name="Ping Other Co")
        WorksIn.objects.create(user=self.outsider, company=other, role=WorksIn.COMPANY_ADMIN)

        self.sender = CrewSender.objects.create(
            company=self.company,
            establishment=self.farm,
            phone_e164="+14155551234",
            display_name="Miguel",
            language=CrewSender.ES,
            consent_attested_at=timezone.now(),
            consent_attested_by=self.admin,
        )

    def post(self, params=None):
        params = PARAMS if params is None else params
        # `on_commit` callbacks do not run inside TestCase's transaction, so without this the pings
        # are registered and never fire, and every assertion below would read zero for the wrong
        # reason.
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(PATH, data=params, HTTP_X_TWILIO_SIGNATURE=sign(params))

    # ------------------------------------------------------------------------- who hears about it

    def test_a_waiting_note_reaches_the_admin_and_the_farm_manager(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)

        told = set(Notification.objects.values_list("recipient__email", flat=True))
        self.assertIn("ping-ca@example.com", told)
        self.assertIn("ping-fm@example.com", told, "the supervisor who confirms notes was not told")

    def test_a_viewer_is_not_told_about_work_they_cannot_do(self):
        self.post()
        self.assertNotIn(
            "ping-vw@example.com",
            set(Notification.objects.values_list("recipient__email", flat=True)),
            "a viewer cannot log the record the note is waiting for",
        )

    def test_another_operation_hears_nothing(self):
        self.post()
        self.assertNotIn("ping-out@example.com", set(Notification.objects.values_list("recipient__email", flat=True)))

    # -------------------------------------------------------- what it says, and what it must not say

    def test_the_ping_never_repeats_what_the_crew_member_said(self):
        self.post()
        for title, message, extra in Notification.objects.values_list("title", "message", "extra_data"):
            body = f"{title} {message} {extra}"
            self.assertNotIn(WORDS, body, "the sender's sentence was copied into the notification store")
            # Not even a fragment: a digest built from this later would carry it just as far.
            self.assertNotIn("bloque 4", body)

    def test_the_ping_carries_no_parse(self):
        """A suggested event type in the ping would turn the confirm step into a rubber stamp on a
        draft the supervisor has already read as fact."""
        self.post()
        for extra in Notification.objects.values_list("extra_data", flat=True):
            for forbidden in ("event_type", "product", "rate", "volume", "date", "words", "transcript"):
                self.assertNotIn(forbidden, extra or {}, f"the ping carried a parse: {forbidden}")

    def test_the_ping_routes_by_kind_and_names_the_note(self):
        self.post()
        extra = Notification.objects.first().extra_data
        # `kind` is the discriminator the client already routes on for export_ready.
        self.assertEqual(extra["kind"], "field_note")
        self.assertEqual(extra["note"], str(FieldNote.objects.get().public_id))
        self.assertEqual(extra["status"], FieldNote.PENDING)

    def test_a_note_with_no_farm_still_produces_a_usable_ping(self):
        """A note legitimately arrives with no farm, so the client cannot be made to require one to
        build a link. `establishment_id` is present and null rather than absent."""
        CrewSender.objects.filter(pk=self.sender.pk).update(establishment=None)
        self.post()
        extra = Notification.objects.first().extra_data
        self.assertIn("establishment_id", extra)
        self.assertIsNone(extra["establishment_id"])

    def test_a_refused_note_is_announced_too(self):
        """A refusal is the one outcome the sender cannot discover for themselves.

        This used to use a voice note, because every voice note was refused. Voice is accepted now, so
        the case here is a photo with no caption, which arrives as a text message with an empty body.
        """
        params = dict(
            PARAMS,
            MessageSid="SM-arrival-media",
            Body="",
            NumMedia="1",
            MediaContentType0="image/jpeg",
            MediaUrl0="https://api.twilio.com/media/ME9",
        )
        self.post(params)

        note = FieldNote.objects.get()
        self.assertEqual(note.status, FieldNote.REFUSED)
        self.assertGreater(Notification.objects.count(), 0, "a refused note told nobody")
        self.assertIn("could not be read", Notification.objects.first().title)
        self.assertEqual(Notification.objects.first().extra_data["status"], FieldNote.REFUSED)

    # ------------------------------------------------------- it fires only for a note that exists

    def test_the_ping_is_deferred_to_the_commit_rather_than_sent_inline(self):
        """The mechanism, asserted directly, because no behavioural test here can distinguish it.

        MEASURED: moving the call from `transaction.on_commit(...)` to a plain inline call changed
        NOTHING about the other ten tests. The duplicate-delivery path cannot tell the two apart
        either, because its IntegrityError is raised BY the `create` and the notify line is never
        reached. So the rule has to be checked by observing that the callback is registered and not
        run, or it is not checked at all.

        Why it still matters when nothing today can observe it: `on_commit` is what keeps the rule
        true for the next person who adds a statement after the create inside that atomic block. A
        ping for a row a later failure rolls back is a lie, and this webhook already has a rollback
        path.
        """
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            response = self.client.post(PATH, data=PARAMS, HTTP_X_TWILIO_SIGNATURE=sign(PARAMS))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 1, "the note itself should already be written")
        # AT LEAST ONE, not exactly one. The webhook registers a second callback now: the crew
        # reply (`reply.dispatch_first_contact`), which is deferred for the same reason and must
        # not be sent about a row a later IntegrityError rolls back either. An exact count here
        # would be an assertion about an unrelated feature's existence rather than about this one's
        # mechanism, and the real claim is the two lines below: nothing was announced before the
        # commit, and running the callbacks is what announces it.
        self.assertGreaterEqual(len(callbacks), 1, "the ping was not registered as an on-commit callback")
        self.assertEqual(Notification.objects.count(), 0, "the ping was sent inline, before the commit")

        for callback in callbacks:
            callback()
        self.assertGreater(Notification.objects.count(), 0, "the registered callback announced nothing")

    def test_a_duplicate_delivery_does_not_announce_the_note_twice(self):
        self.post()
        first = Notification.objects.count()
        self.assertGreater(first, 0)

        # Same MessageSid: the unique constraint rejects it, so nothing new is written and nothing new
        # is announced. NOTE: this does not test `on_commit`, and it reads as though it does. The
        # IntegrityError comes from the `create` itself, so the notify line is never reached on this
        # path whether it is deferred or inline. The test above is the one that checks the deferral.
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 1)
        self.assertEqual(Notification.objects.count(), first, "a duplicate delivery announced itself again")

    def test_an_unrostered_number_announces_nothing(self):
        params = dict(PARAMS, From="whatsapp:+14155559999", MessageSid="SM-arrival-unknown")
        response = self.post(params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FieldNote.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)

    # --------------------------------------------------------------- a failed ping is not a 500

    def test_a_notification_failure_keeps_the_note_and_does_not_invite_a_retry(self):
        """The rule that protects the provider contract. A 500 here makes Twilio redeliver a message
        that was already stored, so a broken notification path would become a retry storm."""
        with patch(
            "notifications.services.NotificationService.create_notification",
            side_effect=RuntimeError("notifications are down"),
        ):
            response = self.post()

        self.assertEqual(response.status_code, 200, "a failing notification turned a stored note into a retry")
        self.assertEqual(FieldNote.objects.count(), 1, "the note was lost because the ping failed")
        self.assertEqual(Notification.objects.count(), 0)

    def test_an_import_failure_in_the_notifications_app_is_also_not_a_500(self):
        """From review of #51. The deferred imports used to sit OUTSIDE the try.

        "Never raises" was then true of everything except the two lines most likely to break on a bad
        deploy, and the test above could not see it because it patches
        `NotificationService.create_notification`, which is inside the try. An ImportError here
        propagates out of the on_commit callback, out of the view, and becomes the 500 that makes the
        provider redeliver.

        `None` in `sys.modules` is the documented way to make an import of that name fail.
        """
        import sys

        with patch.dict(sys.modules, {"notifications.services": None}):
            response = self.post()

        self.assertEqual(response.status_code, 200, "an import failure became a provider retry")
        self.assertEqual(FieldNote.objects.count(), 1, "the note was lost because an import failed")
        self.assertEqual(Notification.objects.count(), 0)
