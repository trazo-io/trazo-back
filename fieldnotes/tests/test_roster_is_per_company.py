"""The roster is unique per company, and one number has one spelling (2026-09-26).

Two defects are pinned here and the first one matters because its fix LOOKS like a tidy-up.

1. `unique=True` on `phone_e164` would read as an obvious cleanup in review and is a cross-tenant
   defect: WA packing houses and custom harvest crews work for several growers on one handset, so a
   global key either refuses the second grower who tries to register a number, or routes that crew's
   notes to whichever farm registered first. Nothing on screen would say which.

2. Providers disagree about a number's shape. Twilio sends `whatsapp:+14155551234`, Meta sends bare
   digits, and a supervisor types `(415) 555-1234`. Comparing raw strings means the webhook cannot
   find a number that is visibly on the roster, and the crew member is told they are not registered.
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from company.models import Company
from fieldnotes.models import CrewSender
from fieldnotes.services.phone import normalise_phone


class RosterScopeTests(TestCase):
    def setUp(self):
        self.a = Company.objects.create(name="Grower A")
        self.b = Company.objects.create(name="Grower B")

    def test_two_companies_may_roster_the_same_number(self):
        CrewSender.objects.create(company=self.a, phone_e164="+14155551234")
        CrewSender.objects.create(company=self.b, phone_e164="+14155551234")
        self.assertEqual(CrewSender.objects.filter(phone_e164="+14155551234").count(), 2)

    def test_one_company_may_not_roster_the_same_number_twice(self):
        CrewSender.objects.create(company=self.a, phone_e164="+14155551234")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CrewSender.objects.create(company=self.a, phone_e164="+14155551234")

    def test_a_number_is_not_active_until_consent_is_attested(self):
        sender = CrewSender.objects.create(company=self.a, phone_e164="+14155551234")
        self.assertTrue(sender.is_active)
        self.assertFalse(sender.may_send, "active is not enough; somebody must have told this person")

        user = get_user_model().objects.create_user(email="sup@example.com", password="pw-for-tests-only")
        from django.utils import timezone

        sender.consent_attested_at = timezone.now()
        sender.consent_attested_by = user
        sender.save(update_fields=["consent_attested_at", "consent_attested_by"])
        self.assertTrue(sender.may_send)


class TheMaySendRuleHasOneMeaning(TestCase):
    """The queryset the webhook runs and the property a caller reads must agree, always.

    The webhook used to spell the rule inline and the model spelled it again as a property. Two gates
    that must agree while spelling it differently is exactly how the event-create tenancy gate
    drifted from its read-path sibling: one covered read, update and delete, the other covered
    nothing, and the docstring claimed both. Breaking edit: change either definition alone.
    """

    def setUp(self):
        self.company = Company.objects.create(name="Agreement Co")
        self.user = get_user_model().objects.create_user(email="agree@example.com", password="pw-for-tests-only")

    def test_the_query_and_the_property_agree_on_every_combination(self):
        from django.utils import timezone

        combinations = [
            (True, timezone.now()),
            (True, None),
            (False, timezone.now()),
            (False, None),
        ]
        for index, (active, attested) in enumerate(combinations):
            sender = CrewSender.objects.create(
                company=self.company,
                phone_e164=f"+1415555{index:04d}",
                is_active=active,
                consent_attested_at=attested,
            )
            in_query = CrewSender.objects.may_send().filter(pk=sender.pk).exists()
            self.assertEqual(
                in_query,
                sender.may_send,
                f"query and property disagree for is_active={active}, attested={bool(attested)}",
            )

    def test_only_the_fully_permitted_row_is_returned(self):
        from django.utils import timezone

        allowed = CrewSender.objects.create(
            company=self.company, phone_e164="+14155551111", consent_attested_at=timezone.now()
        )
        CrewSender.objects.create(company=self.company, phone_e164="+14155552222")
        CrewSender.objects.create(
            company=self.company, phone_e164="+14155553333", is_active=False, consent_attested_at=timezone.now()
        )
        self.assertEqual(list(CrewSender.objects.may_send()), [allowed])


class AFarmMustBelongToTheRostersCompany(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Owner Co")
        self.other = Company.objects.create(name="Neighbour Co")

    def test_filing_establishment_refuses_a_farm_from_another_company(self):
        from product.models import Establishment

        foreign = Establishment.objects.create(name="Neighbour Farm", company=self.other)
        sender = CrewSender.objects.create(company=self.company, phone_e164="+14155554444", establishment=foreign)
        # Refused rather than trusted: a CHECK constraint cannot span two tables and `full_clean`
        # does not run on `objects.create`, so the gate has to sit at the point of use.
        self.assertIsNone(sender.filing_establishment)

    def test_filing_establishment_returns_the_farm_when_it_does_belong(self):
        from product.models import Establishment

        mine = Establishment.objects.create(name="Home Farm", company=self.company)
        sender = CrewSender.objects.create(company=self.company, phone_e164="+14155555555", establishment=mine)
        self.assertEqual(sender.filing_establishment, mine)

    def test_clean_refuses_a_farm_from_another_company(self):
        from django.core.exceptions import ValidationError

        from product.models import Establishment

        foreign = Establishment.objects.create(name="Neighbour Farm 2", company=self.other)
        sender = CrewSender(company=self.company, phone_e164="+14155556666", establishment=foreign)
        with self.assertRaises(ValidationError):
            sender.full_clean()


class PhoneNormalisationTests(TestCase):
    def test_every_shape_a_provider_or_a_human_sends_reduces_to_one_string(self):
        for raw in (
            "whatsapp:+14155551234",
            "+14155551234",
            "+1 (415) 555-1234",
            "+1-415-555-1234",
            "  +1 415 555 1234  ",
        ):
            self.assertEqual(normalise_phone(raw.replace("whatsapp:", "")), "+14155551234", raw)

    def test_a_bare_number_is_refused_rather_than_assumed_to_be_american(self):
        # Completing `4155551234` to `+14155551234` would silently route a Mexican crew's number to
        # a US one. The caller must refuse the message instead of guessing a country.
        self.assertIsNone(normalise_phone("4155551234"))
        self.assertEqual(normalise_phone("4155551234", default_country_code="1"), "+14155551234")

    def test_nonsense_is_refused(self):
        for raw in ("", None, "abc", "+", "+0123456789", "+1"):
            self.assertIsNone(normalise_phone(raw), repr(raw))

    def test_a_non_us_number_survives_untouched(self):
        self.assertEqual(normalise_phone("+52 55 1234 5678"), "+525512345678")


class RosterLanguagesMatchThePrompts(TestCase):
    def test_every_roster_language_has_a_prompt_behind_it(self):
        """Adding a language here without a prompt hands that crew an English parse, silently.

        `prompt_key_for` maps by FAMILY and falls back to English for anything unknown, returning
        plausible values from an English prompt with an English numeral table. The failure reads as
        a bad note rather than a misconfiguration, which is the worst shape a defect can have in a
        compliance record. Breaking edit: add ("fr-FR", "French") to LANGUAGE_CHOICES.
        """
        from carbon.services.ai_voice_processor import _PROMPT_KEY_BY_FAMILY

        roster_families = {tag.split("-")[0].lower() for tag, _label in CrewSender.LANGUAGE_CHOICES}
        self.assertTrue(roster_families, "guard-the-guard: the choices list is empty")
        self.assertEqual(
            roster_families,
            set(_PROMPT_KEY_BY_FAMILY),
            "a roster language has no extraction prompt, so those notes would be read as English",
        )
