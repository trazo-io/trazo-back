"""
Soil amendment product identity (2026-06 NOP-alignment audit, P1).

amendment_type is only a generic category; the NOP/CCOF input record (7 CFR 205.203)
needs the specific product + manufacturer. These are certifier/producer-only — the export
prefers them over the category, and they never leak to the consumer payload.
"""

import json

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, SoilManagementEvent
from history.serializers import PublicHistorySerializer
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


class SoilAmendmentProductTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="amend@test.com", password="x")
        self.company = Company.objects.create(name="Amend Farm")
        self.establishment = Establishment.objects.create(name="AE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="AP", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Amend Production",
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
            published=True,
        )

    def _svc(self):
        return AuditExportService(self.history, certification_type="organic")

    def test_product_and_manufacturer_render_in_amendment_cell(self):
        SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            date=timezone.now(),
            amendment_type="compost",
            amendment_product_name="Malibu Compost Bu's Blend",
            amendment_manufacturer="Malibu Compost",
        )
        text = _section_text(self._svc()._build_soil_section())
        self.assertIn("Malibu Compost Bu's Blend", text)  # specific product (was only "Compost")
        self.assertIn("Malibu Compost", text)  # manufacturer

    def test_amendment_product_not_leaked_to_consumer(self):
        SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            date=timezone.now(),
            amendment_product_name="SecretBrand XYZ",
            amendment_manufacturer="SecretMaker Inc",
        )
        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("SecretBrand XYZ", blob, "amendment product leaked to consumer payload")
        self.assertNotIn("SecretMaker Inc", blob, "amendment manufacturer leaked to consumer payload")

    def test_cover_crop_species_renders_in_export(self):
        # CC subtype cover-crop species persists in extra_data (NOP §205.203). The audit
        # export reads it back for the cover-crop record.
        SoilManagementEvent.objects.create(
            history=self.history,
            type="CC",
            date=timezone.now(),
            extra_data={"cover_crop_species": "Vetch / bell beans / oats"},
        )
        text = _section_text(self._svc()._build_soil_section())
        self.assertIn("Vetch / bell beans / oats", text)

    def test_buffer_de_descriptors_render_in_export(self):
        # CCOF OSP Sections D & E descriptors (adjacent_organic / buffer_type /
        # crop_in_buffer) render as per-boundary detail under the buffer-zone table.
        self.parcel.buffer_zones = [
            {
                "direction": "North",
                "adjoining_land_use": "Conventional walnut orchard",
                "buffer_width_m": 8.0,
                "drift_risk": "Medium",
                "prevention": "Hedgerow",
                "adjacent_organic": False,
                "buffer_type": "Vegetative hedgerow",
                "crop_in_buffer": "Unharvested native cover",
                "neighbor_notified": True,
                "neighbor_notification_date": "2026-02-15",
            },
            {
                "direction": "East",
                "adjoining_land_use": "Certified-organic neighbor",
                "buffer_width_m": None,
                "drift_risk": "Low",
                "prevention": None,
                "adjacent_organic": True,
                "buffer_type": None,
                "crop_in_buffer": None,
            },
        ]
        self.parcel.save(update_fields=["buffer_zones"])
        text = _section_text(self._svc()._build_buffer_zone_section())
        self.assertIn("Vegetative hedgerow", text)
        self.assertIn("Unharvested native cover", text)
        self.assertIn("also certified organic", text)  # adjacent_organic=True boundary
        self.assertIn("drift-notification letter on file", text)  # § 205.400(f)(1)
        self.assertIn("2026-02-15", text)  # notification date
