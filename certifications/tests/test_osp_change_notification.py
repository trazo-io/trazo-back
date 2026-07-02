"""
NOP 2615 §3.4 / 7 CFR 205.400(f) — OSPChangeNotification tests.

Covers:
  - cfr_reference resolves to (f)(1) for prohibited-substance, (f)(2) otherwise
  - is_immediate flag
  - serializer exposes the derived fields
"""

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
