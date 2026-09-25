"""A lot-level reconciliation must not read as a period inventory statement.

WHAT WAS WRONG (2026-09-24)
---------------------------
The operation dossier carried a section headed "Mass-Balance Audit Summary" whose verdict line
read "Net inventory reconciliation: PASS", and whose footer said it connected "inputs purchased
and harvest yield to the sales quantity shipped". It models no inventory at all: no opening
balance, no closing balance, no carryover, and Trazo holds no data from which to compute one.

It is a single production's harvest records against that production's own sales records. That
is the RIGHT computation — it is what makes an October harvest invoiced the following January
reconcile in full — but the document that contains it is stamped with a period window on its
cover, so "net inventory reconciliation" invited a reader to take a lot-level check for a
period one, in the operation's favour.

Two further defects sat underneath the naming:

  * the balance row was emitted only when `quantity_sold` was truthy, so a lot harvested and not
    yet invoiced printed NOTHING. Silence in a reconciliation section reads as "nothing to
    reconcile" when the fact is "all of it is still uninvoiced". Zero is not missing.
  * the CSV twin of the section kept the old header, had no balance row of any kind, and still
    answered "Organic on Invoice: No" for a season with no sales — a § 205.307(a) claim about a
    crop that may still be on the tree. The PDF branch was corrected on 2026-08-19; its sibling
    was not, which is the recurring class these suites exist to catch.

⛔ Both exports are asserted here. Fixing one of two rendering paths is what produced the defect.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent, SalesRecord
from product.models import Parcel, Product
from users.models import User


class YieldToSalesScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="yts@test.com", password="x")
        cls.company = Company.objects.create(name="YTS Co")
        cls.establishment = Establishment.objects.create(name="YTS Farm", company=cls.company, state="WA")
        cls.parcel = Parcel.objects.create(name="Bench", establishment=cls.establishment, area=6.0)
        cls.product = Product.objects.create(name="Apples")

    def _production(self, name, *, harvested_lb, sold_lb=None, sale_date=None):
        """A season with a harvest record, and optionally a sale dated AFTER the harvest year."""
        history = History.objects.create(
            name=name,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=harvested_lb,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ProductionEvent.objects.create(
            history=history,
            type="HA",
            date=timezone.now() - timedelta(days=40),
            created_by=self.user,
            yield_quantity=harvested_lb,
            yield_unit="lb",
        )
        if sold_lb is not None:
            SalesRecord.objects.create(
                production=history,
                sale_date=sale_date or (timezone.now().date()),
                buyer_name="Sample Valley Packing Co.",
                quantity=sold_lb,
                quantity_unit="lb",
                organic_on_invoice=True,
                sale_amount=1000,
            )
        return history

    def _pdf_text(self, history):
        from history.services.audit_export_service import AuditExportService

        service = AuditExportService(history, certification_type="all")
        elements = service._build_mass_balance_section()
        out = []
        for el in elements:
            text = getattr(el, "text", None)
            if text:
                out.append(str(text))
            for attr in ("_cellvalues", "_argW"):
                if hasattr(el, attr) and attr == "_cellvalues":
                    out.append(str(getattr(el, attr)))
        return " || ".join(out)

    def _boxed_production(self):
        """A lot that reaches the boxes-to-pounds branch, where the verdict label is printed.

        ⛔ WHY THIS EXISTS. The naming assertion below passed vacuously without it. That branch
        needs harvest in POUNDS, quantity sold in BOXES, and a box weight; every other fixture in
        this file sells in lb, so the label was never rendered and restoring the old
        "Net inventory reconciliation" wording broke nothing. Found by mutation, 2026-09-24.
        """
        history = self._production("Boxed", harvested_lb=10000, sold_lb=None)
        history.box_weight_lb = 40
        history.save(update_fields=["box_weight_lb"])
        SalesRecord.objects.create(
            production=history,
            sale_date=timezone.now().date(),
            buyer_name="Sample Valley Packing Co.",
            quantity=240,
            quantity_unit="boxes",
            organic_on_invoice=True,
            sale_amount=5000,
        )
        return history

    def _csv_text(self, history):
        """`generate_csv` returns a BytesIO, not bytes — read it, do not `isinstance` it."""
        from history.services.audit_export_service import AuditExportService

        buf = AuditExportService(history, certification_type="all").generate_csv()
        raw = buf.getvalue() if hasattr(buf, "getvalue") else buf
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    # -- naming -----------------------------------------------------------------------------

    def test_the_pdf_section_never_promises_an_inventory_balance(self):
        # The BOXED fixture, deliberately: the verdict label only renders on that branch.
        text = self._pdf_text(self._boxed_production())
        self.assertIn(
            "Yield-to-sales reconciliation",
            text,
            "premise: this fixture must reach the branch that prints the verdict label, or "
            "the negative assertion below proves nothing",
        )
        self.assertNotIn("Net inventory", text)

        history = self._production("Closed season", harvested_lb=1000, sold_lb=900)
        text = self._pdf_text(history)
        self.assertNotIn("Net inventory", text)
        self.assertNotRegex(
            text.replace("not a period mass balance", ""),
            r"(?i)mass-balance audit summary",
        )
        self.assertIn("Yield-to-Sales Reconciliation", text)

    def test_the_pdf_section_states_that_it_is_not_a_period_balance(self):
        history = self._production("Closed season 2", harvested_lb=1000, sold_lb=900)
        text = self._pdf_text(history)
        self.assertIn("not", text)
        self.assertIn("opening", text)
        self.assertIn("inventory", text)

    # -- zero is not missing ----------------------------------------------------------------

    def test_an_unsold_lot_states_its_uninvoiced_remainder_rather_than_printing_nothing(self):
        """The October-harvest-January-sale case, caught mid-window."""
        history = self._production("Harvested not yet sold", harvested_lb=702900, sold_lb=None)
        text = self._pdf_text(history)
        self.assertIn("Uninvoiced remainder", text)

    def test_a_partly_sold_lot_states_the_remainder_too(self):
        history = self._production("Partly sold", harvested_lb=1000, sold_lb=600)
        text = self._pdf_text(history)
        self.assertIn("Uninvoiced remainder", text)

    def test_a_fully_sold_lot_states_no_remainder(self):
        history = self._production("Fully sold", harvested_lb=1000, sold_lb=1000)
        text = self._pdf_text(history)
        self.assertNotIn("Uninvoiced remainder", text)

    # -- the sibling export ------------------------------------------------------------------

    def test_the_csv_twin_carries_the_same_heading_scope_and_remainder(self):
        history = self._production("CSV unsold", harvested_lb=5000, sold_lb=None)
        csv_text = self._csv_text(history)

        self.assertIn("YIELD-TO-SALES RECONCILIATION", csv_text)
        self.assertNotIn("MASS-BALANCE AUDIT SUMMARY", csv_text)
        self.assertIn("Not a period inventory balance", csv_text)
        self.assertIn("Uninvoiced remainder", csv_text)

    def test_the_csv_twin_does_not_answer_no_when_there_are_no_sales(self):
        """An absent attestation is not a denial — § 205.307(a) is not asserted against a crop
        that has not been sold."""
        history = self._production("CSV no sales", harvested_lb=5000, sold_lb=None)
        csv_text = self._csv_text(history)

        # ⛔ PARSE the CSV; do not substring it. The first cut asserted
        # `assertNotIn("Organic on Invoice,No", ...)` and failed against the CORRECT output,
        # because "Organic on Invoice,Not applicable yet …" contains that string — "Not"
        # begins with "No". A substring assertion over delimited data tests the delimiter as
        # much as the value.
        import csv as _csv
        import io as _io

        rows = list(_csv.reader(_io.StringIO(csv_text)))
        values = [r[1] for r in rows if len(r) >= 2 and r[0] == "Organic on Invoice"]
        self.assertTrue(values, "the reconciliation section printed no Organic on Invoice row")
        for value in values:
            self.assertNotEqual(
                value,
                "No",
                "a flat No asserts a § 205.307(a) non-conformance about a crop with no sales",
            )
            self.assertIn("Not applicable yet", value)
