"""
Equipment cleaning-log rinse handling (2026-06 NOP-alignment audit, P2).

A water-only equipment purge (rinse documented, NO sanitizer) is a COMPLIANT record,
not a sanitation event. Previously rinse_step_documented pulled it into the Post-Harvest
Sanitation subsection, where the per-event gap check then false-flagged it as
"missing sanitizer name / ppm / § 205.605 reference". Fix: the sanitation subsection
triggers only on real sanitizer detail; rinse surfaces via the cleaning-log Rinse column.
"""

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _section_text(elements):
    out = []
    for el in elements:
        text = getattr(el, "text", None)
        if text:
            out.append(text)
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                ctext = getattr(cell, "text", None)
                if ctext:
                    out.append(ctext)
    return " ".join(out)


class EquipmentRinseFalseFlagTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rinse@test.com", password="x")
        self.company = Company.objects.create(name="Rinse Farm")
        self.establishment = Establishment.objects.create(name="RE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="RP", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Rinse Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _em(self, **kw):
        return ProductionEvent.objects.create(history=self.history, type="EM", date=timezone.now(), **kw)

    def _text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        return _section_text(svc._build_equipment_section())

    def test_water_only_purge_not_false_flagged(self):
        # Airblast sprayer purge: rinse documented, NO sanitizer used.
        self._em(
            equipment_type="sprayer",
            equipment_operation_type="CL",
            cleaning_date=timezone.now().date(),
            cleaning_method="Potable-water purge",
            rinse_step_documented=True,
        )
        text = self._text()
        self.assertIn("Rinse", text)  # new cleaning-log column header
        self.assertNotIn("missing sanitizer name", text)
        self.assertNotIn("Inspector flag", text)

    def test_real_incomplete_sanitizer_event_still_flagged(self):
        # Sanitizer used but ppm + § 205.605 ref + rinse missing → legitimately flagged.
        self._em(
            equipment_type="sprayer",
            equipment_operation_type="CL",
            cleaning_date=timezone.now().date(),
            sanitizer_name="Quaternary ammonia",
            rinse_step_documented=False,
        )
        self.assertIn("Inspector flag", self._text())
