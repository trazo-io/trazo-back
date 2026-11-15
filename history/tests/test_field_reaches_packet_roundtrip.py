"""Save it on the form, find it in the PDF.

Every fix in this batch shares one failure mode: a field the farmer fills that does not
arrive where it was promised. Checking the code path is not enough — the whole point of the
`applied_scope` defect was that the render gate and the payload gate were the same decision
written twice, and they disagreed. So these tests write the value through the SERIALIZER the
client actually posts to, then read the rendered PDF text back.

Covered here:
  * `applied_scope` on a POST-HARVEST event. The Yield & Output section renders for HA, PL and
    PH; the payload gate listed only HA and PL, so a PH event showed the farmer the input and
    posted nothing. The packet prints it in the Partial-Area table.
  * `cleaning_asset_class` for the three classes added for Quick Organics parity. § 205.272
    turns on WHICH surface the product touched, so "Processing equipment or line" must be
    distinguishable from generic equipment in the record an inspector reads.
  * `custom_fields` on a soil event, which the client used to post as the string
    "[object Object]".
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import Production, ProductionEvent, SoilManagementEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class FieldReachesPacketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="roundtrip@test.com", password="x")
        company = Company.objects.create(name="Round Trip Co")
        establishment = Establishment.objects.create(name="RT1", company=company, state="California")
        self.parcel = Parcel.objects.create(name="Block 7", establishment=establishment, area=6)
        product = Product.objects.create(name="Walnuts")
        self.history = Production.objects.create(
            name="Round Trip Production",
            start_date=timezone.now(),
            product=product,
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

    def _pdf_text(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def test_applied_scope_on_a_post_harvest_event_reaches_the_pdf(self):
        """The PH gap. Written through the serializer, so the payload shape is under test too."""
        from history.serializers import UpdateProductionEventSerializer

        payload = {
            "history": self.history.id,
            "type": "PH",
            "description": "Washing and packing",
            "date": timezone.now().isoformat(),
            "area_covered": "3.0",
            "area_unit": "acres",
            "applied_scope": "part",
            "applied_scope_detail": "North packing line only",
        }
        serializer = UpdateProductionEventSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save(created_by=self.user)
        self.assertEqual(event.applied_scope, "part", "the serializer dropped applied_scope for PH")
        self.assertEqual(event.applied_scope_detail, "North packing line only")

        text = self._pdf_text()
        self.assertIn(
            "North packing line only",
            text,
            "the scope locator was saved but never printed — the certifier cannot tell which "
            "part of the lot this covered",
        )

    def test_each_cleanout_asset_class_is_distinguishable_in_the_pdf(self):
        """Parity with Quick Organics is only real if the class survives to the record.

        Asserted per class rather than in aggregate: a display map missing ONE entry renders
        the raw key, and an aggregate count would still pass.
        """
        classes = {
            "processing_line": "Processing equipment or line",
            "livestock_housing": "Livestock housing",
            "other": "Other",
        }
        for value, label in classes.items():
            with self.subTest(asset_class=value):
                ProductionEvent.objects.all().delete()
                ProductionEvent.objects.create(
                    history=self.history,
                    type="EM",
                    date=timezone.now(),
                    description=f"Cleanout of {label}",
                    equipment_operation_type="CL",
                    cleaning_asset_class=value,
                    cleaned_by="A. Reyes",
                    cleaning_method="Pressure wash",
                    created_by=self.user,
                )
                text = self._pdf_text()
                self.assertIn(
                    label,
                    text,
                    f"cleaning_asset_class={value!r} did not render its label in the packet",
                )

    def test_a_soil_custom_field_reaches_the_pdf(self):
        """The "[object Object]" defect, checked at the far end rather than at the serializer."""
        SoilManagementEvent.objects.create(
            history=self.history,
            type="ST",
            date=timezone.now(),
            description="Soil test",
            area_covered=2,
            area_unit="acres",
            extra_data={
                "custom_fields": [{"label": "Hardpan depth", "value": "18 in", "field_type": "text", "id": "cf-1"}]
            },
            created_by=self.user,
        )
        text = self._pdf_text()
        self.assertIn("Hardpan depth", text, "the farmer's custom field never reached the packet")
        self.assertIn("18 in", text)
