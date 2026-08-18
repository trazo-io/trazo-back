"""
A3 — chemical/foliar/oil/pesticide input LOT number (2026-06 NOP-alignment audit).

Lot # is an explicitly required NOP purchase-record field (CCOF G8.0, Oregon Tilth).
Seeds and beneficial-insect releases each had a structured lot field; ChemicalEvent did
not, so spray-input lot numbers were uncapturable and dropped from the input-traceability
and mass-balance audit tables. These tests confirm the field reaches both certifier tables
and never leaks to the consumer payload.
"""

import json
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.serializers import PublicHistorySerializer
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _all_table_text(elements):
    out = []
    for el in elements:
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                text = getattr(cell, "text", None)
                if text:
                    out.append(text)
    return " ".join(out)


class ChemicalLotNumberTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="lot@test.com", password="x")
        self.company = Company.objects.create(name="Lot Farm")
        self.establishment = Establishment.objects.create(name="LE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="LP", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = History.objects.create(
            name="Lot Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=1000.0,
            production_unit="kg",
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            supplier_name="Wilbur-Ellis",
            purchase_invoice="INV-2026-77",
            chemical_lot_number="LOT-ENT-4471",
            quantity_purchased=Decimal("2.5"),
            quantity_purchased_unit="L",
            date=timezone.now(),
        )

    def _svc(self):
        return AuditExportService(self.history, certification_type="organic")

    def test_lot_number_in_input_traceability_table(self):
        text = _all_table_text(self._svc()._build_chemical_log())
        self.assertIn("Lot #", text)
        self.assertIn("LOT-ENT-4471", text)

    def test_lot_number_in_mass_balance_inputs(self):
        text = _all_table_text(self._svc()._build_mass_balance_section())
        self.assertIn("LOT-ENT-4471", text)

    def test_lot_number_not_leaked_to_consumer(self):
        data = PublicHistorySerializer(self.history).data
        chem = [e for e in (data.get("events") or []) if e.get("type") == "chemical"]
        self.assertEqual(len(chem), 1)
        self.assertNotIn("chemical_lot_number", chem[0])
        blob = json.dumps(data, default=str)
        self.assertNotIn("LOT-ENT-4471", blob, "input lot number leaked to consumer payload")

    def test_block_id_folded_into_application_log(self):
        # Table 1 is at the 7.0" width budget, so block rides the Area cell rather than a
        # separate column (Production/Pest/Irrigation keep dedicated Block columns).
        #
        # This asserted "Blk Block A" until 2026-08-18. The blind "Blk " prefix was removed
        # from the service deliberately — growers name their blocks "Block 1", so prefixing
        # unconditionally printed "Blk Block 1" on the live export. The prefix now applies
        # only to a BARE designator that would otherwise read as a stray number. The test was
        # asserting the bug.
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Horticultural oil",
            block_id="Block A",
            date=timezone.now(),
        )
        text = _all_table_text(self._svc()._build_chemical_log())
        self.assertIn("Block A", text)
        self.assertNotIn("Blk Block A", text)

    def test_a_bare_block_designator_still_gets_the_prefix(self):
        """The other half of the rule — without this the fix above could silently regress
        into never prefixing anything, and a lone "7" in the Area cell reads as a quantity."""
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Horticultural oil",
            block_id="B-7",
            date=timezone.now(),
        )
        text = _all_table_text(self._svc()._build_chemical_log())
        self.assertIn("Blk B-7", text)

    def test_active_ingredient_and_manufacturer_in_traceability(self):
        # NOP input identity: the traceability table must name the material, not just the brand.
        # active_ingredient lives in extra_data; manufacturer is a model column.
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            manufacturer="Corteva",
            supplier_name="Wilbur-Ellis",
            extra_data={"active_ingredient": "spinosad"},
            date=timezone.now(),
        )
        text = _all_table_text(self._svc()._build_chemical_log())
        self.assertIn("spinosad", text)  # active ingredient
        self.assertIn("Corteva", text)  # manufacturer
