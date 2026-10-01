"""
Tests for the SOE traceback sprint backend core:

- SalesRecord CRUD (owner-gated; "crop and quantity sold, date of sale,
  buyer" — the records inspectors verify at every annual inspection).
- Printable lot-tag PDF (§ 205.307 nonretail container identification):
  organic line ONLY when the lot-eligibility resolver passes.
- recent-inputs endpoint (distinct chemical products for form prefill).
"""

import re
from datetime import timedelta
from io import BytesIO

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SalesRecord
from product.models import Parcel, Product
from users.models import User, WorksIn


class _Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(email="owner@sales.test", password="x")
        self.outsider = User.objects.create_user(email="out@sales.test", password="x")
        self.company = Company.objects.create(name="Sales Farm Co")
        self.establishment = Establishment.objects.create(name="SE1", company=self.company)
        WorksIn.objects.create(user=self.owner, company=self.company, role="CA")
        self.parcel = Parcel.objects.create(name="SP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Sales Test Production",
            start_date=timezone.now() - timedelta(days=120),
            finish_date=timezone.now() - timedelta(days=10),
            lot_id="LOT-TEST-001",
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _payload(self, **overrides):
        data = {
            "production_id": str(self.history.public_id),
            "sale_date": "2026-05-01",
            "buyer_name": "Coastal Wholesale",
            "quantity": "1200",
            "quantity_unit": "kg",
            "invoice_number": "INV-2026-001",
            "organic_on_invoice": True,
        }
        data.update(overrides)
        return data


class SalesRecordTests(_Base):
    def test_create_list_delete_roundtrip(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.post("/api/sales_records/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201)
        record_id = resp.json()["id"]

        resp = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}")
        self.assertEqual(resp.status_code, 200)
        rows = resp.json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["buyer_name"], "Coastal Wholesale")
        self.assertTrue(rows[0]["organic_on_invoice"])

        # 🔴 2026-09-07 — this used to assert 204 against a FINISHED, PUBLISHED production,
        # which is the § 205.103(b)(4) hole: the sale is the far end of the (b)(2) audit trail
        # and was freely erasable. The test pinned the defect, so it moves here with the rule.
        resp = self.client.delete(f"/api/sales_records/{record_id}/")
        self.assertEqual(resp.status_code, 423)
        self.assertEqual(SalesRecord.objects.count(), 1)
        self.assertIn("205.103(b)(4)", str(resp.json()))

    def test_a_sale_on_an_open_season_is_still_deletable(self):
        """The floor starts when the season closes. While it is open the operator is still
        writing the record, and a typo must not be permanent from the moment it is typed."""
        open_history = History.objects.create(
            name="Open season",
            start_date=timezone.now() - timedelta(days=20),
            product=self.product,
            parcel=self.parcel,
            operator=self.owner,
            is_outdoor=True,
        )
        self.client.force_authenticate(self.owner)
        resp = self.client.post(
            "/api/sales_records/",
            self._payload(production_id=str(open_history.public_id)),
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        record_id = resp.json()["id"]

        resp = self.client.delete(f"/api/sales_records/{record_id}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(SalesRecord.objects.filter(pk=record_id).exists())

    def test_shipment_fields_roundtrip(self):
        # Per-shipment transport block (§ 205.272(a)): BOL/carrier/vehicle/
        # destination/clean-transport ride the same row as the sale.
        self.client.force_authenticate(self.owner)
        resp = self.client.post(
            "/api/sales_records/",
            self._payload(
                bill_of_lading="BOL-2026-0042",
                carrier_name="Valley Hauling LLC",
                vehicle_id="Truck 12",
                destination="Hughson packer",
                clean_transport_method="affidavit",
            ),
            format="json",
        )
        self.assertEqual(resp.status_code, 201)

        rows = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}").json()
        self.assertEqual(rows[0]["bill_of_lading"], "BOL-2026-0042")
        self.assertEqual(rows[0]["carrier_name"], "Valley Hauling LLC")
        self.assertEqual(rows[0]["clean_transport_method"], "affidavit")

    def test_shipment_rejects_unknown_clean_transport_method(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.post(
            "/api/sales_records/",
            self._payload(clean_transport_method="trust_me"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.post("/api/sales_records/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}")
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_denied(self):
        resp = self.client.get(f"/api/sales_records/?production_id={self.history.public_id}")
        self.assertIn(resp.status_code, (401, 403))

    def test_unknown_production_404(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.post(
            "/api/sales_records/",
            self._payload(production_id="00000000-0000-0000-0000-000000000000"),
            format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_sales_never_in_public_payload(self):
        # Same policy as supplier fields: commercially sensitive, owner-only.
        SalesRecord.objects.create(
            production=self.history,
            sale_date="2026-05-01",
            buyer_name="Secret Buyer Inc",
            quantity=10,
            quantity_unit="kg",
        )
        import json as jsonlib

        from history.serializers import PublicHistorySerializer

        blob = jsonlib.dumps(PublicHistorySerializer(self.history).data, default=str)
        self.assertNotIn("Secret Buyer Inc", blob)
        self.assertNotIn("sales_records", blob)
        self.assertNotIn("bill_of_lading", blob)
        self.assertNotIn("carrier_name", blob)


class HarvestLotsEndpointTests(_Base):
    """`sales_records/harvest_lots/` — the trace-back picker's source.

    The lot code is deliberately absent from the public history payload (it is an owner-side
    identifier under 7 CFR 205.103(b)(2), not a consumer claim), so the sales editor needs its
    own owner-gated source. A second, looser path to the same rows is how a lot list becomes a
    farm directory, hence the gate assertions below.
    """

    def setUp(self):
        super().setUp()
        from history.models import ProductionEvent

        self.pick = ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now() - timedelta(days=20),
            block_id="Block 2",
            description="pick",
            yield_quantity=1200,
            yield_unit="kg",
        )
        # No crop AND no block would produce no code; this one has both, via the fixture's
        # product name ("Citrus") and block.
        self.assertTrue(self.pick.harvest_lot_code)

    def _get(self, production_id=None):
        url = "/api/sales_records/harvest_lots/"
        if production_id is not None:
            url += f"?production_id={production_id}"
        return self.client.get(url)

    def test_owner_sees_the_productions_lots(self):
        self.client.force_authenticate(self.owner)
        resp = self._get(self.history.public_id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([row["id"] for row in resp.data], [self.pick.id])
        self.assertEqual(resp.data[0]["lot_code"], self.pick.harvest_lot_code)

    def test_anonymous_is_refused(self):
        resp = self._get(self.history.public_id)
        self.assertIn(resp.status_code, (401, 403))

    def test_another_companys_user_is_refused(self):
        self.client.force_authenticate(self.outsider)
        resp = self._get(self.history.public_id)
        self.assertEqual(resp.status_code, 403)

    def test_production_id_is_required(self):
        self.client.force_authenticate(self.owner)
        self.assertEqual(self._get().status_code, 400)

    def test_harvests_without_a_code_are_omitted(self):
        """A harvest with no code has neither crop nor block — nothing to trace to."""
        from history.models import ProductionEvent

        ProductionEvent.objects.filter(pk=self.pick.pk).update(harvest_lot_code="")
        self.client.force_authenticate(self.owner)
        resp = self._get(self.history.public_id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, [])


class LotTagTests(_Base):
    def _pdf_text(self, content):
        return extract_text(BytesIO(content))

    def test_owner_gets_tag_pdf_with_lot(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        text = self._pdf_text(resp.content)
        self.assertIn("LOT LOT-TEST-001", text)
        # The tag prints the ESTABLISHMENT name (the farm), not the company name. This
        # asserted "Sales Farm" — the Company — against a tag that has only ever drawn
        # `establishment.name`, so it could not pass. Corrected 2026-08-10.
        self.assertIn(self.establishment.name, text)

    def test_organic_line_only_when_lot_eligible(self):
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            verification_status="verified",
            certification_scope="Crops",
            effective_date=(timezone.now() - timedelta(days=400)).date(),
            expiry_date=(timezone.now() + timedelta(days=200)).date(),
        )
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertIn("Certified organic by CCOF", self._pdf_text(resp.content))

        # Prohibited input on the lot -> organic line must disappear.
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.HERBICIDE,
            commercial_name="Glyphosate Pro",
            organic_approved="not_organic",
            date=timezone.now() - timedelta(days=30),
        )
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertNotIn("Certified organic", self._pdf_text(resp.content))

    def test_long_certifier_and_farm_names_print_in_full(self):
        """A § 205.307 container label may not silently drop characters.

        Regression, 2026-08-15: the tag sliced by CHARACTER COUNT
        (`organic_line[:40]`, `farm_name[:32]`), so a CCOF-certified grower's tag printed
        "Certified organic by California Certifie" — the certifying agent's name cut in
        half on a physical label that CCOF must approve before it is used. The existing
        organic-line test used the 4-character alias "CCOF", which fits inside the slice
        and therefore could never catch this.
        """
        self.establishment.name = "Sierra Foothills Organic Orchards, LLC"
        self.establishment.save(update_fields=["name"])
        agent = "California Certified Organic Farmers"
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name=agent,
            verification_status="verified",
            certification_scope="Crops",
            effective_date=(timezone.now() - timedelta(days=400)).date(),
            expiry_date=(timezone.now() + timedelta(days=200)).date(),
        )
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertEqual(resp.status_code, 200)
        # Collapse whitespace: the agent name legitimately wraps across two printed lines.
        text = re.sub(r"\s+", " ", self._pdf_text(resp.content))

        self.assertIn(self.establishment.name, text, "farm name was truncated on the tag")
        self.assertIn(f"Certified organic by {agent}", text, "certifying agent name was truncated")
        self.assertNotIn("…", text, "tag ellipsised text that fits when wrapped")

    # ---- § 205.307 container labelling (2026-08-10 USDA audit, P4-F2 / P4-F4) ----

    def test_refuses_to_print_a_tag_with_no_lot_id(self):
        # Was: `lot = history.lot_id or "—"`, so the sheet printed the literal string
        # "LOT —". § 205.307(a)(2) requires a lot number, shipping identification, or other
        # unique information linking the container to audit-trail documentation; an em-dash
        # is none of the three. Measured on the live database the day this was found, 63% of
        # published productions had no lot_id, so most tags were non-compliant. A blocked
        # download is recoverable; a printed label on shipped product is not.
        self.history.lot_id = None
        self.history.save(update_fields=["lot_id"])

        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")

        self.assertEqual(resp.status_code, 400, "a tag with no lot ID must not be generated")
        self.assertEqual(resp.json().get("code"), "lot_id_required")
        self.assertIn("205.307", resp.json().get("error", ""), "the blocker must cite the rule it enforces")

    def test_placeholder_lot_never_reaches_the_pdf(self):
        # Belt-and-suspenders on the above: whatever the branch logic does, the em-dash
        # placeholder must never appear on a printed container label.
        self.history.lot_id = ""
        self.history.save(update_fields=["lot_id"])

        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertNotEqual(resp.status_code, 200)
        if resp.status_code == 200:  # pragma: no cover - guard for a future regression
            self.assertNotIn("LOT —", self._pdf_text(resp.content))

    def test_withheld_organic_line_warns_the_grower(self):
        # § 205.307(a)(1) is a POSITIVE requirement: a certified operation's nonretail
        # container must identify the product as organic. Dropping the line on a gate failure
        # is as non-compliant as over-claiming — and it used to leave only a server log the
        # grower never saw. The tag still prints; the reason now rides back with it.
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="CCOF",
            verification_status="verified",
            certification_scope="Crops",
            effective_date=(timezone.now() - timedelta(days=400)).date(),
            expiry_date=(timezone.now() + timedelta(days=200)).date(),
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.HERBICIDE,
            commercial_name="Glyphosate Pro",
            organic_approved="not_organic",
            date=timezone.now() - timedelta(days=30),
        )

        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")

        self.assertEqual(resp.status_code, 200, "the tag must still print — only the organic line is withheld")
        self.assertNotIn("Certified organic", self._pdf_text(resp.content))
        warning = resp.get("X-Trazo-Label-Warning", "")
        self.assertTrue(
            warning, "organic identification was withheld silently — the grower cannot fix what they cannot see"
        )
        self.assertIn("205.307", warning)

    def test_uncertified_operation_prints_without_a_warning(self):
        # No certificate means § 205.307(a)(1) does not bind, so a tag with no organic line
        # is correct and must NOT nag. Over-warning trains growers to ignore warnings.
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("Certified organic", self._pdf_text(resp.content))
        self.assertFalse(
            resp.get("X-Trazo-Label-Warning", ""), "warned about organic identification with no certificate on file"
        )

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/api/histories/{self.history.public_id}/lot-tag/")
        self.assertEqual(resp.status_code, 403)


class RecentInputsTests(_Base):
    def test_distinct_products_most_recent_first(self):
        for days_ago, name, status_value in [
            (40, "Neem Oil Pro", "omri_listed"),
            (20, "UAN-32", "not_organic"),
            (10, "Neem Oil Pro", "omri_listed"),  # duplicate, newer
        ]:
            ChemicalEvent.objects.create(
                history=self.history,
                type=ChemicalEvent.FERTILIZER,
                commercial_name=name,
                organic_approved=status_value,
                # `active_ingredient` is not a ChemicalEvent model field — it lands in
                # extra_data, and the endpoint has read it from there since the F27 fix
                # (2026-06, history/views.py). This test kept passing it to the constructor
                # and had been erroring ever since; corrected 2026-08-10.
                extra_data={"active_ingredient": "azadirachtin" if "Neem" in name else "urea ammonium nitrate"},
                date=timezone.now() - timedelta(days=days_ago),
            )
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/histories/recent-inputs/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 200)
        products = resp.json()
        names = [p["commercial_name"] for p in products]
        self.assertEqual(names, ["Neem Oil Pro", "UAN-32"])
        self.assertEqual(products[0]["organic_approved"], "omri_listed")
        self.assertEqual(products[0]["active_ingredient"], "azadirachtin")

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        resp = self.client.get(f"/api/histories/recent-inputs/?establishment_id={self.establishment.id}")
        self.assertEqual(resp.status_code, 403)


class SalesRecordVoidTests(_Base):
    """Void, not delete — the correction path for a closed season.

    Deleting is refused once the production is finished (§ 205.103(b)(4)) and there is no edit
    path, so without this a sale mistyped after harvest could never be corrected. The rule the
    tests below pin: the row STAYS on the record, and stops counting as a sale.
    """

    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.owner)
        resp = self.client.post("/api/sales_records/", self._payload(), format="json")
        self.assertEqual(resp.status_code, 201)
        self.record_id = resp.json()["id"]

    def test_voiding_keeps_the_row_and_records_who_why_and_when(self):
        resp = self.client.post(
            f"/api/sales_records/{self.record_id}/void/",
            {"void_reason": "Duplicate of INV-2026-004."},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["is_voided"])
        self.assertEqual(body["void_reason"], "Duplicate of INV-2026-004.")
        self.assertIsNotNone(body["voided_at"])

        record = SalesRecord.objects.get(pk=self.record_id)
        self.assertIsNotNone(record.voided_at)
        self.assertEqual(record.voided_by, self.owner)
        self.assertEqual(SalesRecord.objects.count(), 1, "voiding must not delete the row")

    def test_a_void_without_a_reason_is_refused(self):
        """A void with no reason is a deletion with extra steps: the row survives but the
        record no longer says what happened."""
        resp = self.client.post(f"/api/sales_records/{self.record_id}/void/", {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("void_reason", resp.json())
        self.assertIsNone(SalesRecord.objects.get(pk=self.record_id).voided_at)

    def test_voiding_twice_is_refused_rather_than_overwriting_the_first_reason(self):
        self.client.post(f"/api/sales_records/{self.record_id}/void/", {"void_reason": "First reason."}, format="json")
        resp = self.client.post(
            f"/api/sales_records/{self.record_id}/void/", {"void_reason": "Second reason."}, format="json"
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(SalesRecord.objects.get(pk=self.record_id).void_reason, "First reason.")

    def test_a_voided_sale_stops_counting_but_stays_on_the_record(self):
        """The whole point. `live()` is what every total reads; `all()` is what the dossier and
        the records export read."""
        self.client.post(
            f"/api/sales_records/{self.record_id}/void/", {"void_reason": "Order cancelled."}, format="json"
        )
        self.assertEqual(self.history.sales_records.live().count(), 0)
        self.assertEqual(self.history.sales_records.voided().count(), 1)
        self.assertEqual(self.history.sales_records.count(), 1)

    def test_the_disclosure_does_not_report_a_voided_sale(self):
        """`resolve_sales_disclosure` is the single precedence function every surface asks.

        ⛔ The dangerous half is `organic_on_invoice`, which is an `all()` over the rows: a
        voided row with the flag unset would drag the operation's answer to False and print
        "not every invoice identifies the product as organic" about a sale that did not happen.
        """
        from history.services.audit_export_service import resolve_sales_disclosure

        before = resolve_sales_disclosure(self.history)
        self.assertEqual(before.source, "sales_records")
        self.assertEqual(before.buyer, "Coastal Wholesale")

        self.client.post(f"/api/sales_records/{self.record_id}/void/", {"void_reason": "Wrong buyer."}, format="json")
        after = resolve_sales_disclosure(self.history)
        self.assertNotIn("Coastal Wholesale", after.buyer or "")

    def test_a_viewer_may_not_void(self):
        other = User.objects.create_user(email="viewer-void@example.com", password="x")
        self.client.force_authenticate(other)
        resp = self.client.post(f"/api/sales_records/{self.record_id}/void/", {"void_reason": "nope"}, format="json")
        self.assertIn(resp.status_code, (403, 404))
        self.assertIsNone(SalesRecord.objects.get(pk=self.record_id).voided_at)
