"""
NOP 2615 §3.4 / 7 CFR 205.400(f) — OSPChangeNotification tests.

Covers:
  - cfr_reference resolves to (f)(1) for prohibited-substance, (f)(2) otherwise
  - is_immediate flag
  - serializer exposes the derived fields
"""

import datetime

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, OSPChangeNotification
from certifications.serializers import OSPChangeNotificationSerializer
from company.models import Company, Establishment


def _make_osp():
    company = Company.objects.create(name="CN Test Farm")
    establishment = Establishment.objects.create(name="Main", company=company)
    return OrganicSystemPlan.objects.create(
        establishment=establishment,
        version_number=1,
        status="active",
        effective_date=timezone.now().date(),
    )


class OSPChangeNotificationTests(TestCase):
    def setUp(self):
        self.osp = _make_osp()

    def test_prohibited_substance_is_f1_and_immediate(self):
        cn = OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category=OSPChangeNotification.CATEGORY_PROHIBITED_SUBSTANCE,
            description="Drift from neighbor's glyphosate application onto Block A.",
        )
        self.assertEqual(cn.cfr_reference, "7 CFR 205.400(f)(1)")
        self.assertTrue(cn.is_immediate)

    def test_practice_change_is_f2_and_not_immediate(self):
        cn = OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category=OSPChangeNotification.CATEGORY_ACREAGE_FIELD_ADDITION,
            description="Added 12-acre Block C to organic acreage.",
        )
        self.assertEqual(cn.cfr_reference, "7 CFR 205.400(f)(2)")
        self.assertFalse(cn.is_immediate)

    def test_serializer_exposes_derived_fields(self):
        cn = OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category=OSPChangeNotification.CATEGORY_PROHIBITED_SUBSTANCE,
            description="Immediate report.",
            method=OSPChangeNotification.METHOD_WRITTEN,
        )
        data = OSPChangeNotificationSerializer(cn).data
        self.assertEqual(data["cfr_reference"], "7 CFR 205.400(f)(1)")
        self.assertTrue(data["is_immediate"])
        self.assertEqual(data["method_display"], "Written")
        self.assertIn("205.400(f)(1)", data["change_category_display"])

    def test_ordering_newest_first(self):
        older = OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category=OSPChangeNotification.CATEGORY_FIELD_REMOVAL,
            description="Older",
            date_notified=timezone.now().date().replace(month=1, day=1),
        )
        newer = OSPChangeNotification.objects.create(
            osp=self.osp,
            change_category=OSPChangeNotification.CATEGORY_NEW_RETAIL_LABEL,
            description="Newer",
            date_notified=timezone.now().date(),
        )
        ordered = list(self.osp.change_notifications.all())
        self.assertEqual(ordered[0], newer)
        self.assertEqual(ordered[-1], older)


class ChangeNotificationDateGuardTests(TestCase):
    """Only the impossible is refused.

    A blank `date_notified` stays legal for EVERY category, including the § 205.400(f)(1)
    immediate one. Requiring it there was tried and reverted: a grower who discovers drift this
    morning must be able to record it before they have phoned the certifier, and a hard
    requirement makes the most urgent category the only one that cannot be entered promptly.
    `test_prohibited_substance_is_f1_immediate_over_api` encodes that decision. The packet names
    the missing date as a [REVIEW] finding instead — surfacing the gap without refusing a record.
    """

    def setUp(self):
        company = Company.objects.create(name="CN Co")
        establishment = Establishment.objects.create(name="CN1", company=company)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )

    def _cn(self, **kwargs):
        defaults = dict(osp=self.osp, description="A change.")
        defaults.update(kwargs)
        return OSPChangeNotification(**defaults)

    def test_a_blank_date_is_allowed_for_every_category(self):
        """Including (f)(1) — recording the event must never wait on having phoned anyone."""
        for category, _label in OSPChangeNotification.CATEGORY_CHOICES:
            with self.subTest(category=category):
                self._cn(change_category=category).clean()

    def test_a_future_date_is_refused_for_every_category(self):
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        for category, _label in OSPChangeNotification.CATEGORY_CHOICES:
            with self.subTest(category=category):
                with self.assertRaises(DjangoValidationError) as ctx:
                    self._cn(change_category=category, date_notified=tomorrow).clean()
                self.assertIn("date_notified", ctx.exception.message_dict)

    def test_today_is_accepted(self):
        """The boundary matters: an event reported the same day is the normal (f)(1) case."""
        self._cn(
            change_category=OSPChangeNotification.CATEGORY_PROHIBITED_SUBSTANCE,
            date_notified=timezone.localdate(),
        ).clean()

    def test_the_serializer_enforces_the_same_rule(self):
        """DRF never calls Model.clean(); without this the API was the unguarded path."""
        future = OSPChangeNotificationSerializer(
            data={
                "change_category": OSPChangeNotification.CATEGORY_FIELD_REMOVAL,
                "description": "Removed Block D.",
                "date_notified": (timezone.localdate() + datetime.timedelta(days=1)).isoformat(),
            }
        )
        self.assertFalse(future.is_valid())
        self.assertIn("date_notified", future.errors)

    def test_the_serializer_still_accepts_an_undated_immediate_notification(self):
        blank = OSPChangeNotificationSerializer(
            data={
                "change_category": OSPChangeNotification.CATEGORY_PROHIBITED_SUBSTANCE,
                "description": "Neighbour drift onto the north buffer.",
            }
        )
        self.assertTrue(blank.is_valid(), blank.errors)
