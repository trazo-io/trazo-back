"""A retired certification type is refused on WRITE and still readable on the RECORD.

WHY IT WAS RETIRED
------------------
`BusinessEvent` offered "Carbon Neutral Certification" and "Sustainable Agriculture
Standard". Both name a claim with no issuing body behind it, and
`claim_authority._WITHHELD_CERTIFICATION_TYPES` already refused to publish either — so the
product was inviting the farmer to make a claim it then silently declined to show. "Carbon
neutral" is a general environmental benefit claim under 16 CFR 260.4 that also contradicts
Trazo's own direct-operational-emissions methodology, and an unattributed "Sustainable
Agriculture Standard" is the self-created sustainability label ECGT 2024/825 bans outright
from 2026-09-27.

TWO HALVES, AND WHY BOTH ARE HERE
---------------------------------
Retiring a value is a WRITE decision. The READ path still has to explain what is already on
file: a § 205.103(b)(2) record has to survive an inspector's trace-back, so a farmer who
logged one of these keeps the record AND its label. Deleting the choice outright would make
`get_certification_type_display()` print the raw slug into a certifier packet.

⛔ THE MISS THIS FILE EXISTS FOR: the guard first landed on `BusinessEventSerializer` alone,
which `EventViewSet.get_serializer_class` returns only for READS —
`UpdateBusinessEventSerializer` handles every mutation. A validator on the serializer that
never validates anything is the same class of defect as a gate flag no control reads. The
first test below fails if either serializer loses the mixin.
"""

from django.test import TestCase

from history.models import BusinessEvent
from history.serializers import BusinessEventSerializer, UpdateBusinessEventSerializer


class BothSerializersRefuseARetiredTypeTests(TestCase):
    SERIALIZERS = (BusinessEventSerializer, UpdateBusinessEventSerializer)

    def test_the_write_serializer_is_covered(self):
        """Named explicitly, because it is the one that was missed.

        `get_serializer_class` returns UpdateBusinessEventSerializer for `is_mutation`. If
        this class ever stops carrying the guard, nothing else in this file would notice —
        the read serializer would keep passing every case below on its own.
        """
        self.assertTrue(
            hasattr(UpdateBusinessEventSerializer, "validate_certification_type"),
            "UpdateBusinessEventSerializer handles every BusinessEvent mutation. Without the "
            "guard, retired certification types are writable through the API no matter what "
            "the form offers.",
        )

    def test_every_retired_type_is_refused_by_every_serializer(self):
        self.assertTrue(BusinessEvent.DEPRECATED_CERTIFICATION_TYPES, "nothing is retired")
        for serializer_class in self.SERIALIZERS:
            for retired in sorted(BusinessEvent.DEPRECATED_CERTIFICATION_TYPES):
                with self.subTest(serializer=serializer_class.__name__, value=retired):
                    serializer = serializer_class(data={"certification_type": retired}, partial=True)
                    serializer.is_valid()
                    self.assertIn(
                        "certification_type",
                        serializer.errors,
                        f"{serializer_class.__name__} accepted the retired type {retired!r}",
                    )

    def test_an_offered_type_still_passes_the_same_field(self):
        """The mirror. Refusing everything would pass the test above.

        `partial=True` with a single field isolates the certification_type validator from the
        rest of the payload, so a failure here is about this field and nothing else.
        """
        for serializer_class in self.SERIALIZERS:
            with self.subTest(serializer=serializer_class.__name__):
                serializer = serializer_class(data={"certification_type": "organic_usda"}, partial=True)
                serializer.is_valid()
                self.assertNotIn("certification_type", serializer.errors)

    def test_an_empty_value_is_not_treated_as_retired(self):
        """`certification_type` is blank on every non-certification business event."""
        for serializer_class in self.SERIALIZERS:
            with self.subTest(serializer=serializer_class.__name__):
                serializer = serializer_class(data={"certification_type": ""}, partial=True)
                serializer.is_valid()
                self.assertNotIn("certification_type", serializer.errors)


class RetiredTypesStayReadableTests(TestCase):
    def test_a_retired_type_still_renders_its_label(self):
        """Not a raw slug. This is what a certifier packet prints for an existing record."""
        for retired, label in BusinessEvent.DEPRECATED_CERTIFICATION_TYPE_CHOICES:
            with self.subTest(value=retired):
                event = BusinessEvent(certification_type=retired)
                self.assertEqual(event.get_certification_type_display(), label)
                self.assertNotEqual(event.get_certification_type_display(), retired)

    def test_the_display_vocabulary_is_the_union(self):
        offered = {k for k, _ in BusinessEvent.OFFERED_CERTIFICATION_TYPE_CHOICES}
        retired = {k for k, _ in BusinessEvent.DEPRECATED_CERTIFICATION_TYPE_CHOICES}
        declared = {k for k, _ in BusinessEvent.CERTIFICATION_TYPE_CHOICES}
        self.assertEqual(declared, offered | retired)
        self.assertEqual(offered & retired, set(), "a type cannot be both offered and retired")


class RetiredTypesStayWithheldFromShoppersTests(TestCase):
    """The reason they were retired must not depend on their having been retired.

    `claim_authority` classified both as withheld long before this change, and the records
    already on file still reach the public serializer. Retiring the OPTION must not quietly
    reopen the CLAIM for the rows that already exist.
    """

    def test_claim_authority_still_withholds_every_retired_type(self):
        from history.services.claim_authority import may_publish_certification_type

        for retired in sorted(BusinessEvent.DEPRECATED_CERTIFICATION_TYPES):
            with self.subTest(value=retired):
                self.assertFalse(may_publish_certification_type(retired).allowed)

    def test_every_type_still_offered_is_publishable(self):
        """The point of retiring exactly these two.

        Once no offered type is withheld, the form owes the farmer no "this will not reach a
        buyer" caveat on this field — every choice left is one a shopper may see.
        """
        from history.services.claim_authority import may_publish_certification_type

        for offered, _ in BusinessEvent.OFFERED_CERTIFICATION_TYPE_CHOICES:
            with self.subTest(value=offered):
                self.assertTrue(
                    may_publish_certification_type(offered).allowed,
                    f"{offered!r} is offered on the form but withheld from consumers — either "
                    "retire it or classify it as publishable, but do not ask a farmer to "
                    "record a claim the product declines to show.",
                )
