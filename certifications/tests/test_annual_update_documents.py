"""A filed § 205.406(a) update lands on the farm's Documents shelf, and its summary carries its evidence.

WHY THIS EXISTS
---------------
Two gaps a certification assistant closes and Trazo did not (2026-11-02):

  * Filing an update froze its document in the row (`filed_pdf`) and nowhere else. The farm's
    Documents shelf, "everything lands in one organized place", never showed the one document
    a renewal is. Filing now files exactly those bytes there, in the same transaction.
  * § 205.406(a)(1) asks for the summary "supported by documentation", and the filing had no way
    to name any (binding-clause register note). It now links files from the shelf, same farm
    only, signed with the filing, printed on 02 and shipped in the packet.
"""

import importlib
import io
import zipfile
from unittest import mock

from django.db import DatabaseError
from django.db import migrations as dj_migrations

from rest_framework import status

from certifications.models import OSPAnnualUpdate, OSPAnnualUpdateSupportingDocument
from certifications.services.osp_module_pdf import generate_osp_packet, render_filing_pdf
from certifications.services.packet_attachments import annual_update_document_path
from certifications.tests.test_annual_update_revisions import _pdf_text, _Renewal
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from documents.services.filing import file_document


def _upload(est, title="Hedgerow planting invoice", content=b"%PDF-1.4 hedgerow invoice", user=None):
    doc = file_document(
        establishment=est,
        source="upload",
        folder="uploads",
        title=title,
        filename=f"{title.lower().replace(' ', '-')}.pdf",
        content=content,
        content_type="application/pdf",
        created_by=user,
    )
    assert doc is not None
    return doc


def _read(doc) -> bytes:
    with doc.file.open("rb") as fh:
        return fh.read()


class FilingFilesToDocumentsTests(_Renewal):
    def test_filing_files_the_frozen_bytes_to_documents(self):
        filing = self._filed()
        doc = filing.filed_document
        self.assertIsNotNone(doc)
        self.assertEqual(doc.source, "annual_update")
        self.assertEqual(doc.get_source_display(), "Annual update filing")
        self.assertEqual(doc.folder, "organic_system_plan")
        self.assertEqual(doc.title, "Annual update 2026, revision 1")
        self.assertEqual(doc.establishment_id, self.est.pk)
        self.assertEqual(doc.created_by_id, self.user.pk)
        self.assertEqual(doc.content_type, "application/pdf")
        # The same bytes, never a second render.
        self.assertEqual(_read(doc), bytes(filing.filed_pdf))
        self.assertEqual(doc.size_bytes, len(bytes(filing.filed_pdf)))
        self.assertFalse(doc.is_deletable)

        listed = self.client.get(f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/documents/")
        self.assertEqual(listed.status_code, status.HTTP_200_OK)
        rows = listed.json()
        rows = rows["results"] if isinstance(rows, dict) else rows
        self.assertIn(doc.pk, [r["id"] for r in rows])

        res = self.client.delete(f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/documents/{doc.pk}/")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(GeneratedDocument.objects.filter(pk=doc.pk).exists())

    def test_the_serializer_names_the_documents_copy(self):
        filing = self._filed()
        res = self.client.get(f"{self._base()}{filing.pk}/")
        self.assertEqual(res.json()["filed_document"], filing.filed_document_id)

    def test_a_correction_files_its_own_row_and_leaves_the_first_alone(self):
        first = self._filed()
        first_doc = first.filed_document
        first_bytes = _read(first_doc)
        res = self.client.post(f"{self._base()}{first.pk}/correct/", {}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED, res.content[:300])
        second = OSPAnnualUpdate.objects.get(pk=res.json()["id"])
        self.client.patch(f"{self._base()}{second.pk}/", {"correction_note": "Acreage fixed."}, format="json")
        second = self._file(self._sign(second), when="2026-08-25")

        self.assertNotEqual(second.filed_document_id, first_doc.pk)
        self.assertEqual(second.filed_document.title, "Annual update 2026, revision 2")
        self.assertEqual(_read(second.filed_document), bytes(second.filed_pdf))
        first_doc.refresh_from_db()
        self.assertEqual(first_doc.title, "Annual update 2026, revision 1")
        self.assertEqual(_read(first_doc), first_bytes)
        self.assertEqual(GeneratedDocument.objects.filter(source="annual_update").count(), 2)

    def test_a_failed_documents_copy_records_no_filing(self):
        """All or nothing: the filing, the supersession of the revision it corrects and the shelf
        copy commit together, or none of them does."""
        first = self._filed()
        res = self.client.post(f"{self._base()}{first.pk}/correct/", {}, format="json")
        second = self._sign(OSPAnnualUpdate.objects.get(pk=res.json()["id"]))
        before = GeneratedDocument.objects.count()
        with mock.patch("documents.services.filing.file_document", return_value=None):
            res = self.client.post(
                f"{self._base()}{second.pk}/file/",
                {"filing_method": "email", "submitted_at": "2026-08-25"},
                format="json",
            )
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE, res.content[:300])
        self.assertIn("not recorded", res.json()["detail"])
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertIsNone(second.submitted_at)
        self.assertIsNone(second.filed_pdf)
        self.assertEqual(second.filed_sha256, "")
        self.assertIsNone(second.filed_document_id)
        self.assertIsNone(first.superseded_at, "the corrected revision was superseded by a filing that did not happen")
        self.assertEqual(GeneratedDocument.objects.count(), before)

        # And the next attempt goes through.
        second = self._file(second, method="email", when="2026-08-25")
        self.assertIsNotNone(second.filed_document_id)

    def test_a_database_error_inside_the_copy_rolls_back_cleanly(self):
        """`file_document` swallows its own errors; a database error inside it must not leave
        the transaction broken for the rest of the filing."""
        filing = self._sign(self._create())

        def broken_save(self_doc, *args, **kwargs):
            from django.db import connection

            with connection.cursor() as cur:
                cur.execute("SELECT * FROM no_such_table_for_this_test")

        with mock.patch.object(GeneratedDocument, "save", broken_save):
            res = self.client.post(
                f"{self._base()}{filing.pk}/file/",
                {"filing_method": "email", "submitted_at": "2026-08-21"},
                format="json",
            )
        self.assertEqual(res.status_code, status.HTTP_503_SERVICE_UNAVAILABLE, res.content[:300])
        filing.refresh_from_db()
        self.assertIsNone(filing.submitted_at)

    def test_revisions_filed_before_this_are_not_given_a_copy(self):
        """No backfill: the schema migration writes no data."""
        module = importlib.import_module("certifications.migrations.0062_annual_update_documents")
        self.assertFalse(
            [op for op in module.Migration.operations if isinstance(op, dj_migrations.RunPython)],
            "0062 must not create Documents rows for revisions filed before it",
        )
        module = importlib.import_module("documents.migrations.0008_annual_update_source")
        self.assertFalse([op for op in module.Migration.operations if isinstance(op, dj_migrations.RunPython)])


class SupportingDocumentsTests(_Renewal):
    def setUp(self):
        super().setUp()
        self.invoice = _upload(self.est, user=self.user)
        self.map = _upload(self.est, title="North line hedgerow map", content=b"%PDF-1.4 map")

    def _attach(self, filing, *docs, expect=status.HTTP_200_OK):
        res = self.client.patch(
            f"{self._base()}{filing.pk}/",
            {"supporting_document_ids": [str(d.public_id) if hasattr(d, "public_id") else d for d in docs]},
            format="json",
        )
        self.assertEqual(res.status_code, expect, res.content[:400])
        return res

    def test_attach_and_read_back_in_order(self):
        filing = self._create()
        res = self._attach(filing, self.invoice, self.map, self.invoice)
        listed = res.json()["supporting_documents"]
        self.assertEqual([d["id"] for d in listed], [self.invoice.pk, self.map.pk])
        self.assertEqual(listed[0]["title"], "Hedgerow planting invoice")
        self.assertNotIn("supporting_document_ids", res.json())

        res = self._attach(filing, self.map)
        self.assertEqual([d["id"] for d in res.json()["supporting_documents"]], [self.map.pk])

    def test_attach_on_create(self):
        filing = self._create(supporting_document_ids=[str(self.invoice.public_id)])
        self.assertEqual(list(filing.supporting_documents.all()), [self.invoice])

    def test_another_farms_file_fails_like_a_file_that_does_not_exist(self):
        filing = self._create()
        other_company = Company.objects.create(name="Elsewhere Co")
        other_est = Establishment.objects.create(name="Elsewhere Farm", company=other_company)
        foreign = _upload(other_est, title="Foreign invoice")
        sibling_est = Establishment.objects.create(name="Second Farm", company=self.company)
        sibling = _upload(sibling_est, title="Sibling invoice")
        missing = "00000000-0000-4000-8000-000000000000"

        bodies = {}
        for label, doc in (("foreign", foreign), ("sibling", sibling), ("missing", missing)):
            res = self._attach(filing, doc, expect=status.HTTP_400_BAD_REQUEST)
            body = res.json()["supporting_document_ids"]
            bodies[label] = [str(m).replace(str(getattr(doc, "public_id", doc)), "<id>") for m in body]
        self.assertEqual(bodies["foreign"], bodies["missing"])
        self.assertEqual(bodies["sibling"], bodies["missing"])
        self.assertFalse(filing.supporting_documents.exists())

    def test_the_list_is_signed(self):
        filing = self._create()
        unsigned_content = filing.signed_content()
        self.assertNotIn("supporting_documents", unsigned_content, "an empty list must not change older hashes")
        self._attach(filing, self.invoice)
        filing.refresh_from_db()
        self.assertEqual(filing.signed_content()["supporting_documents"], [str(self.invoice.public_id)])
        filing = self._sign(filing)
        self.assertEqual(filing.signed_content_sha256, filing.content_sha256())

        # Through the API: refused like any other signed field.
        self._attach(filing, self.invoice, self.map, expect=status.HTTP_409_CONFLICT)
        # Around the API: the signature no longer matches, so the revision cannot be filed.
        filing.supporting_documents.add(self.map)
        self.assertNotEqual(filing.content_sha256(), filing.signed_content_sha256)
        res = self.client.post(f"{self._base()}{filing.pk}/file/", {"filing_method": "email"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT, res.content[:300])

    def test_a_named_file_cannot_be_deleted_until_it_is_removed(self):
        filing = self._create()
        self._attach(filing, self.invoice)
        url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/documents/{self.invoice.pk}/"
        res = self.client.delete(url)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.json()["code"], "annual_update_attachment_in_use")
        self.assertTrue(GeneratedDocument.objects.filter(pk=self.invoice.pk).exists())

        self._attach(filing)  # an empty list detaches on the draft
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)

    def test_a_correction_carries_the_list(self):
        filing = self._create()
        self._attach(filing, self.invoice, self.map)
        filing = self._file(self._sign(filing))
        res = self.client.post(f"{self._base()}{filing.pk}/correct/", {}, format="json")
        correction = OSPAnnualUpdate.objects.get(pk=res.json()["id"])
        self.assertEqual(set(correction.supporting_documents.all()), {self.invoice, self.map})
        # Editing the correction's list leaves the filed revision's alone.
        self._attach(correction, self.map)
        self.assertEqual(set(filing.supporting_documents.all()), {self.invoice, self.map})

    def test_attach_order_holds_for_ids_a_python_set_reorders(self):
        """The ids here are chosen so a set yields them in the opposite order to the attach order.

        `test_attach_and_read_back_in_order` only failed when the database's sequence happened to
        hand out such ids (CI, 2026-11-02: [144, 143] != [143, 144]); this pins the case on every run.
        """

        def repk(doc, new_pk):
            GeneratedDocument.objects.filter(pk=doc.pk).update(id=new_pk)
            return GeneratedDocument.objects.get(pk=new_pk)

        first, second = repk(self.invoice, 9_000_002), repk(self.map, 9_000_009)
        self.assertEqual(list({first.pk, second.pk}), [second.pk, first.pk], "precondition: a set reorders these ids")

        filing = self._create()
        res = self._attach(filing, first, second)
        self.assertEqual([d["id"] for d in res.json()["supporting_documents"]], [first.pk, second.pk])

        res = self._attach(filing, second, first)
        self.assertEqual([d["id"] for d in res.json()["supporting_documents"]], [second.pk, first.pk])

        filing = self._file(self._sign(filing))
        res = self.client.post(f"{self._base()}{filing.pk}/correct/", {}, format="json")
        correction = OSPAnnualUpdate.objects.get(pk=res.json()["id"])
        self.assertEqual([link.document_id for link in correction.supporting_links.all()], [second.pk, first.pk])

    def test_a_failed_rewrite_keeps_the_old_list(self):
        filing = self._create()
        self._attach(filing, self.invoice, self.map)
        with mock.patch.object(
            OSPAnnualUpdateSupportingDocument.objects, "bulk_create", side_effect=DatabaseError("insert failed")
        ):
            with self.assertRaises(DatabaseError):
                filing.replace_supporting_documents([self.map])
        self.assertEqual([link.document_id for link in filing.supporting_links.all()], [self.invoice.pk, self.map.pk])

    def test_02_prints_the_list_and_the_packet_ships_the_files(self):
        filing = self._create()
        none_text = _pdf_text(render_filing_pdf(filing))
        self.assertIn("No supporting documents are attached to this filing in Trazo.", none_text)

        self._attach(filing, self.invoice)
        filing = self._file(self._sign(filing))
        path = annual_update_document_path(self.invoice)
        self.assertTrue(path.startswith("annual-update/supporting/"), path)
        frozen = _pdf_text(bytes(filing.filed_pdf))
        self.assertIn("Supporting documentation for (a)(1)", frozen)
        self.assertIn("Hedgerow planting invoice", frozen)
        self.assertIn(path, frozen)

        # A rename after filing does not move the file away from the path the signed 02 cites.
        res = self.client.patch(
            f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/documents/{self.invoice.pk}/",
            {"title": "Invoice, renamed after filing"},
            format="json",
        )
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.content[:300])
        self.invoice.refresh_from_db()
        self.assertEqual(annual_update_document_path(self.invoice), path)

        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.v1)))
        self.assertIn(path, packet.namelist())
        self.assertEqual(packet.read(path), b"%PDF-1.4 hedgerow invoice")
        # The shelf copy of the filing itself is not a packet attachment: 02 already is that document.
        self.assertFalse([n for n in packet.namelist() if "annual-update-2026-revision" in n])
