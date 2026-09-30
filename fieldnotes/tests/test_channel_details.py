"""Where does the crew send it? The one setup fact the product never stated (2026-09-30).

The roster shipped so a grower could register a number. The consent copy explains what happens to a
message. The inbox explains what to do with one. Nothing anywhere told a supervisor the ADDRESS:
`fieldNotes.emptyHelp` promised that messages sent to "your Trazo number" would appear, and that
number lived only in `FIELD_NOTES_WHATSAPP_FROM` in the deployment's environment. So the single fact
a supervisor had to relay to their crew was the single fact no screen could show them.

The Twilio sandbox makes it worse than a missing label. Every sender must send a join phrase once
before Twilio delivers anything at all, and that phrase is assigned per account, so it cannot be
hardcoded and was nowhere in the product either. A grower could add a number, tell their crew to
message it, and have every message dropped upstream of the webhook with nothing on any screen to say
why.

WHAT THESE GUARD, each one a mistake available here:

  * The literal path resolves to the ACTION, not to a detail lookup for a note whose id is the word
    "channel". Both are registered under `field-notes/` and only router ordering separates them.
  * A boolean, never `unconfigured_reason()`. That string names SETTING NAMES, which is the right
    detail for a log line and exactly the wrong detail to put on a farmer's screen.
  * `configured` requires the SENDER NUMBER, not just the credentials. Inbound needs the auth token
    and the webhook URL; a deployment can accept notes and never reply. But a grower with no number
    to give out cannot get a first message sent, so from this page's point of view it is off.
  * A bad provider slug RAISES. A silent fallback would show a confident number from the wrong
    provider, or a blank one that reads as "not switched on yet", with nothing to say which.
  * A CALLER WITH NO COMPANY IS REFUSED. Found in review of #60. This action does not go through
    `get_queryset`, so nothing narrowed it, and `ReadOnlyForViewersGlobal` lets any authenticated
    caller through on a safe method. A plain self-registration creates a user with no company at
    all: `WorksIn` is written in one place on that path and only when the form carried a valid
    company invitation code. So anybody who could create an account could read the number.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import resolve, reverse

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from fieldnotes.providers.base import OutboundAdapter
from fieldnotes.providers.registry import ADAPTERS, active_adapter
from users.models import WorksIn

# The credentials a configured deployment has. Values are shaped like the real ones and are not real:
# the signature path is tested elsewhere and nothing here signs anything.
CONFIGURED = dict(
    TWILIO_ACCOUNT_SID="ACtest",
    TWILIO_AUTH_TOKEN="token-for-tests-only",
    FIELD_NOTES_WHATSAPP_FROM="+14155238886",
    FIELD_NOTES_PROVIDER="twilio",
)


class ChannelRouteTests(TestCase):
    def test_the_literal_path_resolves_to_the_action_and_not_to_a_note(self):
        """The one collision this endpoint could have, and the reason it is asserted rather than assumed.

        `FieldNoteViewSet` has `lookup_field = "public_id"` with no `lookup_value_regex`, so the
        detail route matches any segment, including the word "channel". Only `SimpleRouter`'s
        ordering (list routes, then dynamic list routes, then detail) keeps them apart, and that is
        library behaviour rather than anything this code states. A reordering, or somebody adding
        `lookup_value_regex`, would silently turn this into a lookup for a note that cannot exist and
        answer 404 to a page that would then report the channel as off.
        """
        match = resolve("/api/field-notes/channel/")
        self.assertEqual(match.func.cls, __import__("fieldnotes.views", fromlist=["x"]).FieldNoteViewSet)
        # `initkwargs["actions"]` is how a router records which method the URL dispatches to.
        # `ViewSetMixin.as_view` records the method-to-action map on the view function itself. Only
        # the GET entry is asserted: the router also maps HEAD onto the same action, which is
        # correct and not this test's subject.
        self.assertEqual(match.func.actions["get"], "channel")
        self.assertNotIn("public_id", match.kwargs)

    def test_reverse_agrees_with_the_path_the_client_calls(self):
        # The frontend slice calls the literal `field-notes/channel/`. If the router ever produced a
        # different path this would be the only thing that noticed.
        self.assertEqual(reverse("field-note-channel"), "/api/field-notes/channel/")


class ChannelAccessTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Channel Co")
        self.admin = get_user_model().objects.create_user(email="ca@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.viewer = get_user_model().objects.create_user(email="vw@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.viewer, company=self.company, role=WorksIn.VIEWER)
        self.url = reverse("field-note-channel")

    def test_an_anonymous_caller_is_refused(self):
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    @override_settings(**CONFIGURED)
    def test_a_supervisor_is_told_the_number(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["configured"])
        self.assertEqual(response.data["number"], "+14155238886")

    @override_settings(**CONFIGURED)
    def test_a_viewer_may_read_it(self):
        """Deliberate. A viewer cannot log the record a note is waiting for, and telling a colleague
        which number to message is not a write."""
        self.client.force_authenticate(user=self.viewer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["number"], "+14155238886")

    @override_settings(**CONFIGURED)
    def test_a_caller_who_belongs_to_no_operation_is_refused(self):
        """FOUND IN REVIEW OF #60, and the premise is the part worth writing down.

        A plain self-registration produces a user with zero companies. `WorksIn` is created in
        exactly one place on that path, `users/serializers.py::_join_company_with_code`, and only
        when the signup carried a valid company invitation code. `ReadOnlyForViewersGlobal` asks only
        whether somebody is authenticated on a GET, so before the floor was added anyone who could
        create an account could read the inbound number and, on the sandbox, the join phrase.
        """
        nobody = get_user_model().objects.create_user(email="nobody@example.com", password="pw-for-tests-only")
        self.client.force_authenticate(user=nobody)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        # NOT a `configured: false` body. That would state the channel is off, which is a claim this
        # endpoint has no basis for when the real answer is "you may not ask".
        self.assertNotIn("number", response.data)
        self.assertNotIn("configured", response.data)

    @override_settings(**CONFIGURED)
    def test_a_superuser_with_no_company_may_still_read_it(self):
        # Same bypass `get_queryset` already grants, so support can answer "which number is this
        # deployment on" without being rostered anywhere.
        staff = get_user_model().objects.create_superuser(email="su@example.com", password="pw-for-tests-only")
        self.client.force_authenticate(user=staff)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

    @override_settings(**CONFIGURED)
    def test_the_floor_is_membership_and_never_a_role(self):
        """A VIEWER of an operation whose crew messages this number has every reason to know it.

        Asserted separately from `test_a_viewer_may_read_it` because the two could pass for different
        reasons: that one would survive the floor being written as "holds CA or FM anywhere", which
        is the mistake `fieldnotes/permissions.py` was written about. This one pins that the gate is
        membership in something, not a role in it.
        """
        self.client.force_authenticate(user=self.viewer)
        self.assertEqual(self.client.get(self.url).status_code, status.HTTP_200_OK)

    @override_settings(**CONFIGURED)
    def test_the_number_carries_no_provider_prefix(self):
        # `send_text` adds `whatsapp:` at the call site, so the stored value is already the form a
        # person reads and dials. A prefix here would be rendered verbatim on the roster page.
        self.client.force_authenticate(user=self.admin)
        self.assertNotIn("whatsapp:", self.client.get(self.url).data["number"])


class ChannelConfigurationTests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Channel Conf Co")
        self.admin = get_user_model().objects.create_user(email="conf@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(user=self.admin)
        self.url = reverse("field-note-channel")

    @override_settings(**{**CONFIGURED, "FIELD_NOTES_WHATSAPP_FROM": ""})
    def test_credentials_without_a_sender_number_is_not_configured(self):
        """THE STATE PRODUCTION IS IN as of 2026-09-30, and the reason `configured` is not just
        "are the credentials set". Notes would arrive and go unanswered, and a grower would have
        nothing to hand their crew, so the page must say the channel is off."""
        response = self.client.get(self.url)
        self.assertFalse(response.data["configured"])
        self.assertEqual(response.data["number"], "")

    @override_settings(**{**CONFIGURED, "TWILIO_AUTH_TOKEN": ""})
    def test_a_number_without_credentials_is_not_configured_either(self):
        # The token is what verifies an inbound signature, so without it nothing arrives however
        # good the number looks.
        self.assertFalse(self.client.get(self.url).data["configured"])

    @override_settings(**CONFIGURED, FIELD_NOTES_JOIN_PHRASE="join pale-tiger")
    def test_the_sandbox_join_phrase_is_served_when_there_is_one(self):
        # Without this a crew member's messages are dropped by Twilio before the webhook ever runs,
        # and no screen in the product could explain the silence.
        self.assertEqual(self.client.get(self.url).data["join_phrase"], "join pale-tiger")

    @override_settings(**CONFIGURED, FIELD_NOTES_JOIN_PHRASE="")
    def test_a_registered_sender_has_no_join_step(self):
        # Empty, not absent: the client branches on the value and a missing key reads as undefined,
        # which is the `audio_deleted_at` class of defect the contract parity guard was written for.
        response = self.client.get(self.url)
        self.assertIn("join_phrase", response.data)
        self.assertEqual(response.data["join_phrase"], "")

    @override_settings(**{**CONFIGURED, "TWILIO_ACCOUNT_SID": "", "TWILIO_AUTH_TOKEN": ""})
    def test_no_setting_name_is_ever_sent_to_a_client(self):
        """`unconfigured_reason()` answers "TWILIO_AUTH_TOKEN is not set", which is the right detail
        for a log line and the wrong detail for a farmer. The boolean is the actionable part."""
        body = str(self.client.get(self.url).data)
        for leak in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "FIELD_NOTES_WHATSAPP_FROM"):
            self.assertNotIn(leak, body)

    @override_settings(**CONFIGURED)
    def test_it_serves_exactly_the_three_keys_the_client_declares(self):
        # A fourth key would be served and read by nothing; a missing one reads as undefined in the
        # client and silently takes the wrong branch.
        self.assertEqual(set(self.client.get(self.url).data), {"configured", "number", "join_phrase"})


class ActiveAdapterTests(TestCase):
    @override_settings(FIELD_NOTES_PROVIDER="twilio")
    def test_it_resolves_through_the_same_table_as_the_webhook(self):
        self.assertIs(active_adapter(), ADAPTERS["twilio"])

    @override_settings(FIELD_NOTES_PROVIDER="meta")
    def test_an_unregistered_slug_raises_instead_of_falling_back(self):
        # "meta" is the slug the second adapter will take, so this is the realistic typo: the setting
        # set before the adapter exists. A fallback would show the Twilio number under Meta's name.
        with self.assertRaises(ImproperlyConfigured) as caught:
            active_adapter()
        # Names the setting, because that is the only thing that can fix it.
        self.assertIn("FIELD_NOTES_PROVIDER", str(caught.exception))

    @override_settings(FIELD_NOTES_PROVIDER="")
    def test_an_empty_slug_raises_too(self):
        with self.assertRaises(ImproperlyConfigured):
            active_adapter()


class SeamTests(TestCase):
    def test_the_seam_requires_every_provider_to_answer_this(self):
        """A second adapter must implement it rather than inherit a blank.

        The base class raises, following `verify` and `parse`. Returning a default here would be the
        worse failure: Meta's adapter would silently report the channel off, which reads to a grower
        as "not switched on yet" rather than as a missing implementation.
        """
        with self.assertRaises(NotImplementedError):
            OutboundAdapter.channel_details()

    def test_the_view_asks_an_adapter_instead_of_reading_the_settings(self):
        """The seam rule in `providers/base.py`, applied to this endpoint.

        `fieldnotes/views.py` must not read a provider's own settings. It names an adapter and asks.
        Checked on the source because the failure is an author reaching for `settings.` rather than a
        function misbehaving, so there is nothing to observe at runtime.
        """
        source = self._views_source()
        self.assertIn("active_adapter().channel_details()", source)
        for reader in (
            'getattr(settings, "FIELD_NOTES_',
            "settings.FIELD_NOTES_WHATSAPP_FROM",
            "settings.FIELD_NOTES_JOIN_PHRASE",
            # The provider's address prefix. `send_text` adds it; nothing above the package knows it.
            '"whatsapp:',
        ):
            self.assertNotIn(reader, source)

    def test_no_setting_name_appears_in_this_module_at_all(self):
        """Because a docstring in this file is API OUTPUT, not a comment.

        FOUND WHILE WRITING THIS FILE. No `DEFAULT_RENDERER_CLASSES` is configured, so DRF's
        `BrowsableAPIRenderer` is active and `SimpleMetadata` copies `get_view_description()` into
        every OPTIONS response. The first version of `channel`'s docstring explained the gap by
        naming `FIELD_NOTES_WHATSAPP_FROM`, which put a deployment's setting name in the endpoint's
        own published description. A setting NAME is not a credential, and it is still a detail about
        how Trazo is deployed that no caller asked for, handed out by the one endpoint whose entire
        job is to answer a question without naming settings.

        Deliberately the whole file rather than the docstrings: a `# comment` is safe today, and
        distinguishing the two would make the guard depend on parsing rather than on the rule.
        """
        source = self._views_source()
        for name in ("FIELD_NOTES_WHATSAPP_FROM", "FIELD_NOTES_JOIN_PHRASE", "FIELD_NOTES_PROVIDER"):
            self.assertNotIn(name, source)

    @staticmethod
    def _views_source():
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / "views.py").read_text()
