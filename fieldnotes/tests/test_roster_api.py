"""The roster API: which numbers may file notes, and who is allowed to say so.

WHY THIS EXISTS AT ALL. The webhook shipped before any roster API, so the only way to register a
number was `manage.py shell` and later a staff-only Django admin page, which `fieldnotes/admin.py`
itself calls a stopgap. Meanwhile the inbox's empty state told a first-time user that messages would
appear when someone on their crew sent one, which no grower could make happen. The channel was
reachable and unusable at the same time.

WHAT EACH RULE IS FOR:

  * THE NUMBER IS NORMALISED on the way in. The webhook looks numbers up by exact E.164 string
    equality, so a row holding "(415) 555-1234" can never match an inbound message, and the failure
    is the most confusing possible one: the crew member is told they are not registered while their
    number is visibly on the list. A number that cannot be normalised is REFUSED rather than stored.
  * CONSENT IS ASSERTED, AND STAMPED SERVER-SIDE. A crew member is not a Trazo user and cannot agree
    here themselves, so a person at the farm asserts it under their own name. A client that could
    send the timestamp or the attester could manufacture that assertion.
  * TENANCY ON THE WRITE PATH. A serializer field for a ForeignKey accepts any primary key in the
    table, so without an explicit check a caller could add a sender to a company they have nothing
    to do with. This viewset has no company in its URL, so nothing in the routing layer can help.
  * PER COMPANY, NEVER GLOBAL. Shared handsets are normal: a custom harvest crew works for several
    growers. A global uniqueness key would refuse the second grower or route that crew's notes to
    whoever registered first.
  * DEACTIVATE, NEVER DELETE. A roster row is the provenance of every note it accepted, and
    `FieldNote.sender` is SET_NULL, so deleting it leaves notes standing with no entry explaining
    where they came from.
"""

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from rest_framework import status
from rest_framework.test import APITestCase

from company.models import Company
from fieldnotes.models import CrewSender, FieldNote
from product.models import Establishment
from users.models import WorksIn


def rows_of(response):
    """The list, whether or not pagination is switched on (see test_inbox.rows_of)."""
    data = response.data
    return data["results"] if isinstance(data, dict) and "results" in data else data


class CrewSenderRosterTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(email="roster-admin@example.com", password="pw-for-tests-only")
        self.company = Company.objects.create(name="Roster Co")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.admin.companies.add(self.company)
        self.farm = Establishment.objects.create(name="Roster Farm", company=self.company)

        self.stranger = User.objects.create_user(email="roster-str@example.com", password="pw-for-tests-only")
        self.other_company = Company.objects.create(name="Other Roster Co")
        WorksIn.objects.create(user=self.stranger, company=self.other_company, role=WorksIn.COMPANY_ADMIN)
        self.stranger.companies.add(self.other_company)
        self.other_farm = Establishment.objects.create(name="Other Roster Farm", company=self.other_company)

        self.list_url = reverse("crew-sender-list")

    def payload(self, **extra):
        body = {
            "company": self.company.pk,
            "establishment": self.farm.pk,
            "phone_e164": "+14155551234",
            "display_name": "Miguel",
            "language": CrewSender.ES,
            "consent_attested": True,
        }
        body.update(extra)
        return body

    def detail_url(self, sender):
        return reverse("crew-sender-detail", args=[sender.pk])

    # ---------------------------------------------------------------- the number has one spelling

    def test_a_human_typed_number_is_stored_normalised(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.list_url, self.payload(phone_e164="+1 (415) 555-1234 "), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        sender = CrewSender.objects.get(pk=response.data["id"])
        # The exact string the webhook will compare against.
        self.assertEqual(sender.phone_e164, "+14155551234")

    def test_a_number_that_cannot_be_normalised_is_refused_and_not_stored(self):
        self.client.force_authenticate(user=self.admin)
        # No country code, so `normalise_phone` refuses rather than assuming +1 and routing a
        # Mexican crew's number to a US one.
        response = self.client.post(self.list_url, self.payload(phone_e164="555-1234"), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("phone_e164", response.data)
        self.assertFalse(CrewSender.objects.exists(), "an unusable number was stored anyway")

    # -------------------------------------------------------------------------------- consent

    def test_a_sender_cannot_be_added_without_asserting_consent(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.list_url, self.payload(consent_attested=False), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("consent_attested", response.data)
        self.assertFalse(CrewSender.objects.exists())

    def test_the_consent_stamp_is_the_server_s_and_names_the_person_who_asserted_it(self):
        self.client.force_authenticate(user=self.admin)
        # A client trying to backdate the assertion, or to attribute it to somebody else.
        response = self.client.post(
            self.list_url,
            self.payload(consent_attested_at="2020-01-01T00:00:00Z", consent_attested_by=self.stranger.pk),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        sender = CrewSender.objects.get(pk=response.data["id"])
        self.assertEqual(sender.consent_attested_by, self.admin)
        self.assertGreater(sender.consent_attested_at.year, 2020, "a client-supplied timestamp was stored")
        self.assertEqual(sender.added_by, self.admin)

    def test_a_sender_added_this_way_may_actually_send(self):
        """The whole point. `may_send` reads three columns, so a row that looks right and refuses
        every message is a real failure mode: that is what the admin stopgap produced before it
        learned to stamp consent."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.list_url, self.payload(), format="json")
        sender = CrewSender.objects.get(pk=response.data["id"])

        self.assertTrue(sender.may_send)
        self.assertTrue(response.data["may_send"], "the roster would not show the supervisor it works")

    def test_editing_a_sender_does_not_refresh_the_consent_stamp(self):
        self.client.force_authenticate(user=self.admin)
        sender = CrewSender.objects.get(pk=self.client.post(self.list_url, self.payload(), format="json").data["id"])
        first = sender.consent_attested_at

        response = self.client.patch(
            self.detail_url(sender), {"display_name": "Miguel R.", "consent_attested": True}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        sender.refresh_from_db()
        self.assertEqual(sender.display_name, "Miguel R.")
        # Consent was asserted once, by a named person, at a recorded time. An edit must not make
        # the record claim that assertion is newer than it is.
        self.assertEqual(sender.consent_attested_at, first)

    # -------------------------------------------------------------------------------- tenancy

    def test_a_caller_cannot_add_a_sender_to_a_company_they_do_not_belong_to(self):
        self.client.force_authenticate(user=self.stranger)
        response = self.client.post(self.list_url, self.payload(), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(CrewSender.objects.exists())

    def test_a_roster_row_cannot_name_another_company_s_farm(self):
        """The write-time half of what `CrewSender.filing_establishment` refuses at read time.
        Refusing here means the row never has to be second-guessed later."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(self.list_url, self.payload(establishment=self.other_farm.pk), format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("establishment", response.data)
        self.assertFalse(CrewSender.objects.exists())

    def test_the_list_shows_only_the_caller_s_own_companies(self):
        mine = CrewSender.objects.create(
            company=self.company, phone_e164="+14155550001", consent_attested_at=timezone.now()
        )
        theirs = CrewSender.objects.create(
            company=self.other_company, phone_e164="+14155550002", consent_attested_at=timezone.now()
        )

        self.client.force_authenticate(user=self.admin)
        rows = rows_of(self.client.get(self.list_url))
        ids = {row["id"] for row in rows}

        self.assertIn(mine.pk, ids)
        self.assertNotIn(theirs.pk, ids, "another operation's roster was visible")

    def test_a_foreign_sender_cannot_be_edited_or_deactivated(self):
        theirs = CrewSender.objects.create(
            company=self.other_company, phone_e164="+14155550002", consent_attested_at=timezone.now()
        )
        self.client.force_authenticate(user=self.admin)

        self.assertEqual(
            self.client.patch(self.detail_url(theirs), {"display_name": "x"}, format="json").status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(self.client.delete(self.detail_url(theirs)).status_code, status.HTTP_404_NOT_FOUND)
        theirs.refresh_from_db()
        self.assertTrue(theirs.is_active)

    def test_a_viewer_may_read_the_roster_and_not_change_it(self):
        viewer = get_user_model().objects.create_user(email="roster-view@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        viewer.companies.add(self.company)

        self.client.force_authenticate(user=viewer)
        self.assertEqual(self.client.get(self.list_url).status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.client.post(self.list_url, self.payload(), format="json").status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertFalse(CrewSender.objects.exists())

    def test_an_anonymous_caller_sees_nothing(self):
        self.assertIn(
            self.client.get(self.list_url).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    # ------------------------------------------------------------------- one number, several growers

    def test_two_growers_may_register_the_same_number(self):
        """A custom harvest crew on one handset works for several operations. Refusing the second
        grower, or routing that crew's notes to whoever registered first, are both wrong by
        construction."""
        self.client.force_authenticate(user=self.admin)
        mine = self.client.post(self.list_url, self.payload(), format="json")
        self.assertEqual(mine.status_code, status.HTTP_201_CREATED, mine.data)

        self.client.force_authenticate(user=self.stranger)
        theirs = self.client.post(
            self.list_url,
            {
                "company": self.other_company.pk,
                "establishment": self.other_farm.pk,
                "phone_e164": "+14155551234",
                "consent_attested": True,
            },
            format="json",
        )
        self.assertEqual(theirs.status_code, status.HTTP_201_CREATED, theirs.data)
        self.assertEqual(CrewSender.objects.filter(phone_e164="+14155551234").count(), 2)

    def test_the_same_company_cannot_register_one_number_twice(self):
        self.client.force_authenticate(user=self.admin)
        self.client.post(self.list_url, self.payload(), format="json")
        # Typed differently, normalised to the same string, so the constraint has to catch it.
        again = self.client.post(
            self.list_url, self.payload(phone_e164="+1 415-555-1234", display_name="Ana"), format="json"
        )

        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(CrewSender.objects.filter(company=self.company).count(), 1)

    # --------------------------------------------------------------------- deactivate, never delete

    def test_deleting_a_sender_deactivates_it_and_keeps_its_notes_readable(self):
        self.client.force_authenticate(user=self.admin)
        sender = CrewSender.objects.get(pk=self.client.post(self.list_url, self.payload(), format="json").data["id"])
        note = FieldNote.objects.create(
            company=self.company,
            establishment=self.farm,
            sender=sender,
            sender_phone=sender.phone_e164,
            sender_display_name="Miguel",
            provider=FieldNote.TWILIO,
            provider_message_id="SM-roster-1",
            kind=FieldNote.TEXT,
            body_text="regamos el bloque 4",
        )

        response = self.client.delete(self.detail_url(sender))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        sender.refresh_from_db()
        self.assertTrue(CrewSender.objects.filter(pk=sender.pk).exists(), "the roster row was destroyed")
        self.assertFalse(sender.is_active)
        self.assertFalse(sender.may_send, "a deactivated number can still file notes")

        # The provenance of what it already sent is untouched.
        note.refresh_from_db()
        self.assertEqual(note.sender_id, sender.pk)
        self.assertEqual(note.sender_phone, "+14155551234")

    def test_a_deactivated_sender_can_be_switched_back_on(self):
        self.client.force_authenticate(user=self.admin)
        sender = CrewSender.objects.get(pk=self.client.post(self.list_url, self.payload(), format="json").data["id"])
        self.client.delete(self.detail_url(sender))

        response = self.client.patch(self.detail_url(sender), {"is_active": True}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        sender.refresh_from_db()
        self.assertTrue(sender.may_send, "consent survived the round trip, so it should send again")


class CrewSenderAuthorizationTests(APITestCase):
    """Three holes found in review of #50, each one a different axis being confused for another.

    They share a shape worth naming: every one of them passes a check that looks like the right
    check. Membership is not a write role. A field-level validator is not the same as `validate()`.
    Attesting consent for one number is not attesting it for the next one.
    """

    def setUp(self):
        User = get_user_model()
        self.company = Company.objects.create(name="Auth Co")
        self.farm = Establishment.objects.create(name="Auth Farm", company=self.company)

        self.other_company = Company.objects.create(name="Auth Other Co")

        # A VIEWER here, and a FARM MANAGER somewhere else entirely. `user.companies` is a
        # role-agnostic M2M through WorksIn, and `ReadOnlyForViewersGlobal` asks only whether an
        # elevated role exists in ANY company, so the two checks pass on different axes.
        self.two_hat = User.objects.create_user(email="twohat@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.two_hat, company=self.company, role=WorksIn.VIEWER)
        WorksIn.objects.create(user=self.two_hat, company=self.other_company, role=WorksIn.FARM_MANAGER)
        self.two_hat.companies.add(self.company)
        self.two_hat.companies.add(self.other_company)

        self.outsider = User.objects.create_user(email="outsider@example.com", password="pw-for-tests-only")
        self.outsider_company = Company.objects.create(name="Outsider Co")
        WorksIn.objects.create(user=self.outsider, company=self.outsider_company, role=WorksIn.COMPANY_ADMIN)
        self.outsider.companies.add(self.outsider_company)

        self.admin = User.objects.create_user(email="auth-admin@example.com", password="pw-for-tests-only")
        WorksIn.objects.create(user=self.admin, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.admin.companies.add(self.company)

        self.list_url = reverse("crew-sender-list")

    def detail_url(self, sender):
        return reverse("crew-sender-detail", args=[sender.pk])

    def existing(self, **extra):
        fields = {
            "company": self.company,
            "establishment": self.farm,
            "phone_e164": "+14155551234",
            "display_name": "Miguel",
            "consent_attested_at": timezone.now(),
            "consent_attested_by": self.admin,
        }
        fields.update(extra)
        return CrewSender.objects.create(**fields)

    # ---------------------------------------------------- a read role in THIS company is not a write

    def test_a_viewer_here_cannot_write_by_holding_a_manager_role_elsewhere(self):
        self.client.force_authenticate(user=self.two_hat)
        response = self.client.post(
            self.list_url,
            {
                "company": self.company.pk,
                "phone_e164": "+14155559999",
                "consent_attested": True,
            },
            format="json",
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_400_BAD_REQUEST), response.data)
        self.assertFalse(CrewSender.objects.filter(company=self.company).exists())

    def test_a_viewer_here_cannot_deactivate_a_number_by_holding_a_role_elsewhere(self):
        """`destroy` never reaches the serializer, so a check that lives only in `validate()` does
        not apply to it at all. This is the worst of the three: it turns a number off."""
        sender = self.existing()
        self.client.force_authenticate(user=self.two_hat)

        response = self.client.delete(self.detail_url(sender))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

        sender.refresh_from_db()
        self.assertTrue(sender.is_active, "a read-only member turned a crew number off")

    def test_a_viewer_here_cannot_edit_a_number_by_holding_a_role_elsewhere(self):
        sender = self.existing()
        self.client.force_authenticate(user=self.two_hat)

        response = self.client.patch(self.detail_url(sender), {"display_name": "changed"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

        sender.refresh_from_db()
        self.assertEqual(sender.display_name, "Miguel")

    # -------------------------------------------- the roster of a foreign company is not an oracle

    def test_a_foreign_company_answers_the_same_whether_or_not_the_number_is_registered(self):
        """The leak the membership check was written to prevent, and did not.

        `UniqueConstraint(company, phone_e164)` makes DRF generate a `UniqueTogetherValidator`, and
        class-level validators run in `run_validators()`, which `run_validation()` calls BEFORE
        `self.validate(attrs)`. So a check living in `validate()` never gets to speak first: a number
        already on the foreign roster answered "must make a unique set" and an unregistered one
        answered "No matching company found", which is a working probe for whether any given phone
        number is on another operation's roster.
        """
        self.existing(phone_e164="+14155550001")

        self.client.force_authenticate(user=self.outsider)
        registered = self.client.post(
            self.list_url,
            {"company": self.company.pk, "phone_e164": "+14155550001", "consent_attested": True},
            format="json",
        )
        unregistered = self.client.post(
            self.list_url,
            {"company": self.company.pk, "phone_e164": "+14155550002", "consent_attested": True},
            format="json",
        )

        self.assertEqual(registered.status_code, unregistered.status_code)
        # Same body too: a different error KEY is as good an oracle as a different status.
        self.assertEqual(
            set(registered.data.keys()),
            set(unregistered.data.keys()),
            f"the response tells a stranger whether a number is registered: {registered.data} vs {unregistered.data}",
        )
        self.assertEqual(CrewSender.objects.filter(company=self.company).count(), 1)

    # ------------------------------------- consent is for a NUMBER, not for a row that can change

    def test_the_number_cannot_be_repointed_without_attesting_consent_again(self):
        """Consent was asserted about a person reachable at one number. Moving the row to a different
        number carries that assertion to somebody who never gave it, while `may_send` stays True
        because it only reads `is_active`, the consent stamp and `stopped_at`.

        `fieldnotes/admin.py` already re-requires consent on edit. This path had no equivalent.
        """
        sender = self.existing(phone_e164="+14155550001")
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(self.detail_url(sender), {"phone_e164": "+14155550999"}, format="json")

        sender.refresh_from_db()
        if response.status_code == status.HTTP_200_OK:
            # If the edit is allowed at all, the row must not still claim consent for the new number.
            self.assertIsNone(
                sender.consent_attested_at,
                "the row claims consent for a number nobody attested to",
            )
            self.assertFalse(sender.may_send)
        else:
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
            self.assertEqual(sender.phone_e164, "+14155550001")

    def test_repointing_the_number_is_allowed_when_consent_is_attested_again(self):
        sender = self.existing(phone_e164="+14155550001")
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            self.detail_url(sender),
            {"phone_e164": "+1 415 555 0999", "consent_attested": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        sender.refresh_from_db()
        self.assertEqual(sender.phone_e164, "+14155550999")
        self.assertTrue(sender.may_send)
        # Re-attested, so the stamp names the person who did it and the moment they did.
        self.assertEqual(sender.consent_attested_by, self.admin)

    def test_an_unrelated_edit_keeps_the_original_consent_stamp(self):
        sender = self.existing(phone_e164="+14155550001")
        first = sender.consent_attested_at
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(self.detail_url(sender), {"display_name": "Miguel R."}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        sender.refresh_from_db()
        self.assertEqual(sender.display_name, "Miguel R.")
        self.assertEqual(sender.consent_attested_at, first, "an unrelated edit disturbed the consent record")
