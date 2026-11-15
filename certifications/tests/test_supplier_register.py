"""The supplier register: who sold the seed or stock, and the organic certificate that covered it.

A planting recorded as "certified organic transplants from X" is a claim; X's organic certificate,
current at the purchase, is its evidence (CCOF G3.0, OTCO C3, WSDA 2121-B; 205.201(a)(3) supplier
verification). Until the register Trazo printed the claim and held no evidence.

A record resolves to a supplier only by a spelling the grower confirmed, exactly (trim, casefold,
single spaces). Never by a near match, and never by writing to the record, so a finished season's
locked records resolve too.
"""

from datetime import date, datetime, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import Supplier, SupplierCertificate, SupplierName
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from history.models import Production, ProductionEvent, SalesRecord
from history.services import supplier_certificates as sc
from history.services.privacy import establishment_supplier_names
from history.services.traceback import trace_sale
from product.models import Parcel
from subscriptions.testing import grant_compliance_exports
from users.models import User, WorksIn

GAP = "supplier_certificate_missing"


def _aware(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 9, 0))


class _Base(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Columbia Basin Orchards")
        self.user = User.objects.create_user(email="admin@suppliers.test", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        grant_compliance_exports(self.company)
        self.est = Establishment.objects.create(name="Home", company=self.company, state="WA")
        self.other_est = Establishment.objects.create(name="North ranch", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="Block 7", establishment=self.est, area=10.0)
        self.season = Production.objects.create(name="Honeycrisp 2025", start_date=timezone.now(), parcel=self.parcel)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, est=None, suffix=""):
        est = est or self.est
        return f"/api/companies/{self.company.id}/establishments/{est.id}/suppliers/{suffix}"

    def upload(self, est=None, title="Columbia Nursery certificate"):
        est = est or self.est
        r = self.client.post(
            f"/api/companies/{self.company.id}/establishments/{est.id}/documents/",
            {
                "file": SimpleUploadedFile("cert.pdf", b"%PDF-1.4 certificate", content_type="application/pdf"),
                "title": title,
                "folder": "certifications",
            },
        )
        self.assertEqual(r.status_code, 201, r.content)
        return GeneratedDocument.objects.get(pk=r.json()["id"])

    def planting(self, supplier="Columbia Nursery", status="certified_organic", on=date(2025, 4, 2), **kw):
        fields = dict(
            history=self.season,
            type=ProductionEvent.TRANSPLANTING,
            description="replant",
            date=_aware(on),
            variety="Honeycrisp on G.41",
            seeds_source="commercial",
            seed_supplier_name=supplier,
            seed_purchase_invoice="CN-25-118",
            seed_purchase_date=on,
            seed_certification_status=status,
        )
        fields.update(kw)
        return ProductionEvent.objects.create(**fields)

    def supplier(self, name="Columbia Nursery", **kw):
        r = self.client.post(self.url(), {"name": name, "organic_status": "certified", **kw}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return Supplier.objects.get(pk=r.json()["id"])

    def certificate(self, supplier, issued_on, est=None):
        doc = self.upload(est)
        r = self.client.post(
            self.url(suffix=f"{supplier.id}/certificates/"),
            {"document": doc.id, "issued_on": issued_on.isoformat()},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        return SupplierCertificate.objects.get(pk=r.json()["id"])

    def gaps(self):
        sale = SalesRecord.objects.filter(production=self.season).first() or SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        return {(g["code"], g["ref"]) for g in trace_sale(sale).as_dict()["gaps"] if g["code"] == GAP}


class SupplierTenancyTests(_Base):
    def test_another_company_reaches_nothing(self):
        supplier = self.supplier()
        outsider = User.objects.create_user(email="other@suppliers.test", password="x")
        other_co = Company.objects.create(name="Elsewhere")
        WorksIn.objects.create(user=outsider, company=other_co, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.get(self.url(suffix=f"{supplier.id}/")).status_code, (403, 404))
        r = self.client.patch(self.url(suffix=f"{supplier.id}/"), {"name": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        supplier.refresh_from_db()
        self.assertEqual(supplier.name, "Columbia Nursery")

    def test_a_viewer_reads_no_supplier(self):
        """A supplier list is commercial relationship data, owner-gated like seed-suppliers."""
        self.supplier()
        viewer = User.objects.create_user(email="viewer@suppliers.test", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_another_farms_document_fails_like_a_missing_one(self):
        supplier = self.supplier()
        foreign = self.upload(est=self.other_est)
        bodies = []
        for doc_id in (foreign.id, 999999):
            r = self.client.post(
                self.url(suffix=f"{supplier.id}/certificates/"),
                {"document": doc_id, "issued_on": "2025-02-10"},
                format="json",
            )
            self.assertEqual(r.status_code, 400, r.content)
            bodies.append((sorted(r.json()), r.json()["document"][0].replace(str(doc_id), "ID")))
        self.assertEqual(bodies[0], bodies[1])
        self.assertFalse(SupplierCertificate.objects.exists())

    def test_a_certificate_file_cannot_be_deleted_from_documents(self):
        """The copy is PROTECTed; the documents route refuses before touching the stored file."""
        cert = self.certificate(self.supplier(), date(2025, 2, 10))
        self.client.raise_request_exception = False
        r = self.client.delete(
            f"/api/companies/{self.company.id}/establishments/{self.est.id}/documents/{cert.document_id}/"
        )
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(r.json()["code"], "supplier_certificate_in_use")
        cert.document.refresh_from_db()
        self.assertTrue(cert.document.file.storage.exists(cert.document.file.name))


class SupplierSpellingTests(_Base):
    def test_a_new_supplier_holds_its_own_spelling_and_no_one_elses(self):
        supplier = self.supplier()
        self.assertEqual(list(supplier.names.values_list("normalized", flat=True)), ["columbia nursery"])
        r = self.client.post(self.url(), {"name": "  COLUMBIA   nursery "}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(Supplier.objects.count(), 1)

    def test_unconfirmed_spellings_list_what_records_write(self):
        self.planting("Columbia Nursery")
        self.planting("Willow Drive Nursery")
        self.planting("Willow Drive Nursery", on=date(2025, 5, 1))
        ProductionEvent.objects.create(
            history=self.season,
            type=ProductionEvent.SEED_SEARCH,
            description="search",
            date=timezone.now(),
            seed_supplier_name="Searched Only Seeds",
        )
        self.supplier("Columbia Nursery")
        rows = self.client.get(self.url(suffix="unconfirmed-spellings/")).json()
        self.assertEqual(rows, [{"name": "Willow Drive Nursery", "records": 2}])

    def test_a_spelling_held_by_another_supplier_is_refused(self):
        self.supplier("Columbia Nursery")
        other = self.supplier("Willow Drive Nursery")
        self.client.raise_request_exception = False
        r = self.client.post(self.url(suffix=f"{other.id}/names/"), {"name": "columbia nursery"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_a_renamed_supplier_is_known_by_its_new_name_and_keeps_the_old(self):
        old = self.planting("Columbia Nursery")
        new = self.planting("Columbia Nursery LLC")
        supplier = self.supplier("Columbia Nursery")
        r = self.client.patch(self.url(suffix=f"{supplier.id}/"), {"name": "Columbia Nursery LLC"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        out = sc.resolve(self.est.id, {ev.pk: (ev.seed_supplier_name, date(2025, 4, 2)) for ev in (old, new)})
        self.assertEqual((out[old.pk]["supplier"] or {}).get("id"), supplier.id)
        self.assertEqual((out[new.pk]["supplier"] or {}).get("id"), supplier.id)

    def test_a_rename_onto_another_suppliers_spelling_is_refused(self):
        self.supplier("Columbia Nursery")
        other = self.supplier("Willow Drive Nursery")
        r = self.client.patch(self.url(suffix=f"{other.id}/"), {"name": "columbia nursery"}, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        other.refresh_from_db()
        self.assertEqual(other.name, "Willow Drive Nursery")

    def test_a_supplier_records_name_is_archived_not_deleted(self):
        self.planting()
        supplier = self.supplier()
        self.assertEqual(self.client.get(self.url()).json()[0]["records_count"], 1)
        self.assertEqual(self.client.delete(self.url(suffix=f"{supplier.id}/")).status_code, 400)
        r = self.client.patch(self.url(suffix=f"{supplier.id}/"), {"archived": True}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["archived"])
        unused = self.supplier("Never Bought From")
        self.assertEqual(self.client.delete(self.url(suffix=f"{unused.id}/")).status_code, 204)


class CertificateStatusTests(TestCase):
    """`certificate_status_at` on plain objects: the rule, apart from the database."""

    class C:
        def __init__(self, issued_on, pk):
            self.issued_on, self.pk = issued_on, pk

    def test_each_status(self):
        c25, c26 = self.C(date(2025, 2, 10), 1), self.C(date(2026, 2, 12), 2)
        purchase = date(2025, 4, 2)
        self.assertEqual(sc.certificate_status_at([c25], purchase)[0], sc.COVERING)
        self.assertEqual(sc.certificate_status_at([c25], date(2026, 6, 1))[0], sc.STALE)
        self.assertEqual(sc.certificate_status_at([c26], purchase)[0], sc.POSTDATES_PURCHASE)
        self.assertEqual(sc.certificate_status_at([], purchase)[0], sc.NONE_ON_FILE)
        self.assertEqual(sc.certificate_status_at([c25], purchase, "not_certified")[0], sc.NOT_CERTIFIED)

    def test_next_years_copy_does_not_rejudge_last_years_purchase(self):
        c25, c26 = self.C(date(2025, 2, 10), 1), self.C(date(2026, 2, 12), 2)
        status, cert = sc.certificate_status_at([c26, c25], date(2025, 4, 2))
        self.assertEqual((status, cert.pk), (sc.COVERING, 1))

    def test_fifteen_months_runs_from_the_issue_date(self):
        issued = self.C(date(2025, 1, 1), 1)
        self.assertEqual(sc.certificate_status_at([issued], date(2025, 1, 1) + timedelta(days=456))[0], sc.COVERING)
        self.assertEqual(sc.certificate_status_at([issued], date(2025, 1, 1) + timedelta(days=457))[0], sc.STALE)


class ResolutionTests(_Base):
    def test_exact_spelling_resolves_and_a_near_one_does_not(self):
        exact = self.planting("  columbia   NURSERY ")
        near = self.planting("Columbia Nurseries")
        self.supplier("Columbia Nursery")
        out = sc.resolve(
            self.est.id,
            {ev.pk: (ev.seed_supplier_name, sc.purchase_date_of(ev)) for ev in (exact, near)},
        )
        self.assertIsNotNone(out[exact.pk]["supplier"])
        self.assertIsNone(out[near.pk]["supplier"])
        self.assertEqual(out[near.pk]["status"], sc.UNRESOLVED)

    def test_another_farms_supplier_never_resolves_here(self):
        ev = self.planting()
        Supplier.objects.create(establishment=self.other_est, name="Columbia Nursery")
        SupplierName.objects.create(supplier=Supplier.objects.get(), name="Columbia Nursery")
        self.assertIsNone(sc.resolve(self.est.id, {1: (ev.seed_supplier_name, date(2025, 4, 2))})[1]["supplier"])

    def test_a_copy_filed_on_another_farm_never_counts(self):
        """The write path refuses it; the read does not trust that alone."""
        ev = self.planting()
        supplier = self.supplier()
        SupplierCertificate.objects.create(
            supplier=supplier, document=self.upload(est=self.other_est), issued_on=date(2025, 2, 10)
        )
        out = sc.resolve(self.est.id, {1: (ev.seed_supplier_name, date(2025, 4, 2))})[1]
        self.assertEqual(out["status"], sc.NONE_ON_FILE)

    def test_a_finished_seasons_record_resolves_without_being_touched(self):
        ev = self.planting()
        self.season.finish_date = timezone.now()
        self.season.save()
        before = ProductionEvent.objects.filter(pk=ev.pk).values().get()
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 2, 10))
        self.assertNotIn((GAP, ev.pk), self.gaps())
        after = ProductionEvent.objects.filter(pk=ev.pk).values().get()
        self.assertEqual(before, after)


class TraceGapTests(_Base):
    def test_a_certified_organic_purchase_asks_for_the_certificate_until_one_covers_it(self):
        ev = self.planting()
        self.assertIn((GAP, ev.pk), self.gaps())
        supplier = self.supplier()
        self.assertIn((GAP, ev.pk), self.gaps(), "a supplier with no copy closes nothing")
        self.certificate(supplier, date(2026, 2, 12))
        self.assertIn((GAP, ev.pk), self.gaps(), "a copy issued after the purchase does not close it")
        self.certificate(supplier, date(2025, 2, 10))
        self.assertNotIn((GAP, ev.pk), self.gaps())

    def test_the_seed_row_carries_the_certificate(self):
        ev = self.planting()
        supplier = self.supplier(
            certifier_name="Washington State Department of Agriculture", nop_operation_id="8150001234"
        )
        cert = self.certificate(supplier, date(2025, 2, 10))
        sale = SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        row = next(r for r in trace_sale(sale).as_dict()["inputs"] if r["event_id"] == ev.pk)
        self.assertEqual(row["supplier_certificate"]["status"], sc.COVERING)
        self.assertEqual(row["supplier_certificate"]["certificate"]["document"]["id"], cert.document_id)
        self.assertEqual(row["supplier_certificate"]["supplier"]["nop_operation_id"], "8150001234")
        self.assertNotIn("_supplier_query", row)

    def test_no_gap_where_no_organic_claim_is_made(self):
        untreated = self.planting(status="non_organic_untreated")
        saved = self.planting(seeds_source="farm_saved")
        search = ProductionEvent.objects.create(
            history=self.season,
            type=ProductionEvent.SEED_SEARCH,
            description="search",
            date=timezone.now(),
            seed_supplier_name="Columbia Nursery",
            seed_certification_status="certified_organic",
        )
        gaps = self.gaps()
        for ev in (untreated, saved, search):
            self.assertNotIn((GAP, ev.pk), gaps)

    def test_queries_do_not_grow_with_seed_rows(self):
        supplier = self.supplier()
        self.certificate(supplier, date(2025, 2, 10))
        self.planting()
        sale = SalesRecord.objects.create(
            production=self.season, sale_date=timezone.now().date(), buyer_name="Cascade", quantity=10
        )
        with CaptureQueriesContext(connection) as one:
            trace_sale(sale)
        for i in range(4):
            self.planting(supplier="Columbia Nursery" if i % 2 else "Willow Drive Nursery")
        with CaptureQueriesContext(connection) as five:
            trace_sale(sale)
        self.assertEqual(len(one), len(five))


class DossierAndConsumerTests(_Base):
    def _seed_text(self):
        import re

        from history.services.audit_export_service import AuditExportService

        out = []
        for f in AuditExportService(self.season, certification_type="all")._build_seed_stock_section():
            if hasattr(f, "text"):
                out.append(re.sub(r"<[^>]+>", "", f.text))
            for row in getattr(f, "_cellvalues", []):
                for cell in row:
                    out.append(re.sub(r"<[^>]+>", "", getattr(cell, "text", str(cell))))
        return " ".join(out)

    def test_the_seed_table_prints_the_certificate_and_says_whose_record_it_is(self):
        self.planting()
        self.assertIn("Columbia Nursery. No supplier organic certificate on file.", self._seed_text())
        supplier = self.supplier(
            certifier_name="Washington State Department of Agriculture", nop_operation_id="8150001234"
        )
        self.certificate(supplier, date(2025, 2, 10))
        text = self._seed_text()
        self.assertIn(
            "Organic certificate issued 2025-02-10 (Washington State Department of Agriculture, NOP ID 8150001234); "
            "copy held in Trazo.",
            text,
        )
        self.assertIn("not a check against the USDA Organic Integrity Database", text)
        self.assertNotIn("erified", text.replace("not a check", ""))

    def test_farm_saved_organic_stock_is_not_asked_for_a_supplier_certificate(self):
        """The dossier asks what the trace asks: farm-saved stock has no supplier to certify it."""
        ev = self.planting(seeds_source="farm_saved", seed_lot_number="HB-SAVED-24")
        self.assertNotIn((GAP, ev.pk), self.gaps())
        self.assertNotIn("No supplier organic certificate on file", self._seed_text())

    def test_a_register_only_spelling_is_scrubbed_from_consumer_prose(self):
        supplier = self.supplier("Columbia Nursery LLC")
        SupplierName.objects.create(supplier=supplier, name="CNL Wenatchee")
        names = establishment_supplier_names(self.est)
        self.assertIn("Columbia Nursery LLC", names)
        self.assertIn("CNL Wenatchee", names)


class PlantingFormPickerTests(_Base):
    def test_the_planting_forms_supplier_list_offers_the_register_first(self):
        """A new record spelled the way the register holds the supplier resolves to it exactly."""
        self.planting("Willow Drive Nursery")
        self.planting("columbia nursery")
        self.supplier("Columbia Nursery")
        archived = self.supplier("Old Nursery")
        archived.archived_at = timezone.now()
        archived.save()
        rows = self.client.get(f"/api/productions/seed-suppliers/?establishment_id={self.est.id}").json()
        self.assertEqual(rows[0]["supplier_name"], "Columbia Nursery")
        self.assertEqual(rows[0]["sources"], ["register", "purchase"])
        self.assertEqual([r["supplier_name"] for r in rows].count("columbia nursery"), 0)
        self.assertNotIn("Old Nursery", [r["supplier_name"] for r in rows])
        self.assertIn("Willow Drive Nursery", [r["supplier_name"] for r in rows])
