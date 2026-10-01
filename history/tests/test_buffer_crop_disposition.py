"""
USDA's Buffer Crop Disposition Record in the certifier packet (7 CFR 205.202(c)).

WHY (2026-08-12): the packet documented the buffer-zone drift CONTROL — boundary, width,
adjoining land use — and said nothing about what became of the crop grown inside that buffer.
USDA publishes both on one record because a certifier asks both questions in the same breath.

Worse, the section asserted the answer. It printed "crop in buffer (not sold as organic):
Almonds" off a free-text parcel field — the packet stating the exact fact § 205.202(c) asks
the operator to PROVE, with nothing behind it. Same shape as the storage-narrative finding in
P3: a claim the record layer could not evidence.

Pinned here:
  1. The proof obligation attaches to commerce-entering dispositions ONLY. A crop disked
     under cannot be mis-sold, and flagging it would be Trazo inventing a requirement.
  2. The two evidence-absent states read differently on paper. "Not recorded" (owed, missing)
     and "Not required" (nothing owed) were both a bare dash in the first draft — one gap to
     any certifier skimming the column.
  3. The packet no longer asserts the buffer crop was not sold as organic.
"""

import io
import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class BufferDispositionCommerceTests(TestCase):
    """The frozenset that decides who owes proof — asserted per value, not as a set literal."""

    def test_dispositions_that_put_the_crop_in_someone_elses_hands_owe_proof(self):
        for value in ("sold_conventional", "fed_nonorganic_livestock", "given_away", "harvested_conventional"):
            with self.subTest(value=value):
                self.assertTrue(ProductionEvent(buffer_disposition=value).buffer_disposition_entered_commerce())

    def test_a_crop_that_never_left_the_farm_owes_nothing(self):
        for value in ("not_harvested", "left_in_field", "disposed"):
            with self.subTest(value=value):
                self.assertFalse(ProductionEvent(buffer_disposition=value).buffer_disposition_entered_commerce())

    def test_every_member_of_the_frozenset_is_a_real_choice_value(self):
        """Rename an enum value and the frozenset entry goes dead SILENTLY.

        Nothing would raise: the renamed disposition simply stops matching, the packet stops
        asking for § 205.202(c) proof, and the failure is invisible until a certifier asks
        where the delivery tags went. The frozenset must be a subset of the choices.
        """
        values = {v for v, _ in ProductionEvent._meta.get_field("buffer_disposition").choices}
        orphaned = ProductionEvent.BUFFER_DISPOSITIONS_ENTERING_COMMERCE - values
        self.assertEqual(orphaned, set(), f"frozenset references non-existent choice(s): {orphaned}")

    def test_every_choice_is_classified_one_way_or_the_other(self):
        """A new disposition added to the enum must be a deliberate call, not a default.

        Anything not in the frozenset silently means "owes no proof" — the permissive side.
        This fails when someone adds a choice without deciding, so the decision gets made.
        """
        values = {v for v, _ in ProductionEvent._meta.get_field("buffer_disposition").choices}
        self.assertEqual(
            values,
            {"not_harvested", "left_in_field", "disposed"} | ProductionEvent.BUFFER_DISPOSITIONS_ENTERING_COMMERCE,
            "buffer disposition choices changed — classify the new value as entering commerce or not",
        )

    def test_unanswered_is_not_treated_as_a_commerce_event(self):
        """NULL means the question was not asked, NOT that the crop entered commerce."""
        self.assertFalse(ProductionEvent(buffer_disposition=None).buffer_disposition_entered_commerce())
        self.assertFalse(ProductionEvent(buffer_disposition="").buffer_disposition_entered_commerce())


class BufferDispositionPacketTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="buffer@test.com", password="x")
        company = Company.objects.create(name="Buffer Farm")
        establishment = Establishment.objects.create(name="BF1", company=company)
        self.parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=42.5)
        product = Product.objects.create(name="Walnuts")
        self.history = History.objects.create(
            name="Buffer Production",
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

    def _harvest(self, **kwargs):
        return ProductionEvent.objects.create(history=self.history, type="HA", date=timezone.now(), **kwargs)

    def _pdf_text(self):
        from pdfminer.high_level import extract_text

        # strict_ofpp=False is the service's documented diagnostic-preview opt-out. The
        # SOE OFPP gate is orthogonal to buffer disposition and would otherwise block the
        # build before any section is rendered.
        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def _buffer_section_text(self):
        """Just the disposition table, sliced out of the packet.

        "Not recorded" and "Not required" are generic enough that other sections use them,
        so a whole-document assertIn can pass while the buffer table renders nothing. Slice
        first, assert second.
        """
        text = self._pdf_text()
        start = text.find("Buffer Crop Disposition Record")
        self.assertNotEqual(start, -1, "buffer disposition section did not render")
        end = text.find("7 CFR 205.202(c): certified land", start)
        # The first version of this helper fell back to len(text) when the end anchor was
        # missing — and the anchor WAS missing on the no-buffer-zone-rows path, which is the
        # path five of these six tests take. The "section" was 56% of the whole document, so
        # every assertIn below could have matched text from an unrelated page. Demand the
        # anchor instead of degrading silently.
        self.assertNotEqual(end, -1, "section footnote missing — slice would span the document")
        section = text[start:end]
        self.assertLess(len(section), 2000, f"slice too large to be one table ({len(section)} chars)")
        return section

    def test_records_the_disposition_quantity_and_documentation(self):
        self._harvest(
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity="1 4x4 bin",
            buffer_disposition_evidence="Delivery tag and sales record, buffer-crop folder",
        )
        text = self._pdf_text()
        self.assertIn("Buffer Crop Disposition Record", text)
        self.assertIn("1 4x4 bin", text)
        self.assertIn("Delivery tag and sales record, buffer-crop folder", text)
        # Scoped to the § 205.202(c) flag, not the bare words "Not recorded" — other
        # sections of the packet use that phrase for their own missing fields.
        self.assertNotIn("left the operation with no documentation", text)

    def test_flags_a_crop_that_entered_commerce_with_no_documentation(self):
        self._harvest(buffer_disposition="sold_conventional", buffer_disposition_quantity="1 4x4 bin")
        text = self._pdf_text()
        self.assertIn("Not recorded", self._buffer_section_text())
        self.assertIn("1 buffer harvest(s) left the operation with no documentation", text)

    def test_does_not_demand_paperwork_for_a_crop_that_never_left_the_farm(self):
        """§ 205.202(c) attaches proof to commerce. Disked under, nothing is owed."""
        self._harvest(buffer_disposition="left_in_field")
        section = self._buffer_section_text()
        self.assertIn("Not required", section)
        self.assertNotIn("left the operation with no documentation", self._pdf_text())

    def test_the_two_evidence_absent_states_read_differently(self):
        """Both were a bare dash in the first draft — indistinguishable to a certifier."""
        self._harvest(buffer_disposition="sold_conventional")
        self._harvest(buffer_disposition="left_in_field")
        section = self._buffer_section_text()
        self.assertIn("Not recorded", section)
        self.assertIn("Not required", section)

    def test_stays_silent_when_no_harvest_answered_the_question(self):
        """NULL is unanswered, not "no buffer" — an empty table would imply a finding."""
        self._harvest()
        self.assertNotIn("Buffer Crop Disposition Record", self._pdf_text())

    def test_stale_evidence_from_a_corrected_disposition_is_not_printed(self):
        """Evidence can outlive the disposition it was recorded against.

        A grower records "sold as conventional" with a delivery tag, then corrects the entry
        to "left in field". The evidence column is nullable and older clients omitted the key
        instead of clearing it, so the string survives. Printing a delivery tag beside a crop
        that never left the farm is the packet contradicting itself — the same defect class
        as the page-1/page-12 sales disagreement P3 found.
        """
        self._harvest(
            buffer_disposition="left_in_field",
            buffer_disposition_evidence="Delivery tag and sales record, buffer-crop folder",
        )
        section = self._buffer_section_text()
        self.assertIn("Not required", section)
        self.assertNotIn("Delivery tag", section)

    def test_buffer_disposition_never_reaches_the_public_payload(self):
        """`buffer_disposition_evidence` is free text that will routinely name a BUYER.

        USDA's own example for the column is "Delivery tag and sales record, Apple Bob's" —
        so the field is supplier-chain data by construction, and it additionally says the
        operation sold product as conventional, which is nobody's business on a QR page.
        Certifier-facing only. Asserted on the serialized bytes, not on the key list: a
        nested serializer can carry the value under a different key.
        """
        import json

        from history.serializers import PublicHistorySerializer

        self._harvest(
            buffer_disposition="sold_conventional",
            buffer_disposition_quantity="1 4x4 bin",
            buffer_disposition_evidence="Delivery tag and sales record, Apple Bob's Packing",
        )
        blob = json.dumps(PublicHistorySerializer(self.history).data, default=str)
        for probe in ("buffer_disposition", "Apple Bob", "4x4 bin", "Delivery tag", "sold_conventional"):
            self.assertNotIn(probe, blob, f"buffer disposition data leaked to the public payload: {probe!r}")

    def test_the_packet_no_longer_asserts_the_buffer_crop_was_not_sold_as_organic(self):
        self.parcel.buffer_zones = [
            {"direction": "North", "adjoining_land_use": "Conventional almonds", "crop_grown_in_buffer": "Walnuts"}
        ]
        self.parcel.save()
        text = self._pdf_text()
        self.assertIn("crop grown in buffer: Walnuts", text)
        self.assertNotIn("not sold as organic", text)


class SplitOperationDeclarationTests(TestCase):
    """The § 205.272 split declaration in the packet must be the operator's OWN answer.

    🔴 2026-08-21 — split status has two independent editors: the farm-profile checkbox
    `Establishment.has_split_operation` and the OSP's G6.0 `split_operation` answer, with
    nothing binding them. The SOE table read the checkbox, so a farm that answered "yes, we
    sell the buffer rows conventional" in the OSP wizard filed a packet asserting
    "Split Operation (7 CFR 205.272): No" — followed by a REVIEW telling the operator that
    the two statements in their packet disagree, about a question they had already answered.
    """

    def setUp(self):
        from certifications.models import OrganicSystemPlan

        self.user = User.objects.create_user(email="split@test.com", password="x")
        company = Company.objects.create(name="Split Farm")
        self.establishment = Establishment.objects.create(name="SF1", company=company)
        self.parcel = Parcel.objects.create(name="Block 9", establishment=self.establishment, area=10.0)
        self.history = History.objects.create(
            name="Split Production",
            start_date=timezone.now(),
            product=Product.objects.create(name="Blueberries"),
            parcel=self.parcel,
            operator=self.user,
        )
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, version_number=1, status="draft")

    def _service(self):
        return AuditExportService(self.history, certification_type="organic")

    def _set_answer(self, value):
        self.osp.module_responses = {"modules": {"g6_0_production": {"answers": {"split_operation": {"value": value}}}}}
        self.osp.save(update_fields=["module_responses"])

    def test_the_osp_answer_is_read(self):
        self._set_answer(True)
        self.assertIs(self._service()._osp_declares_split_operation(self.establishment), True)
        self._set_answer(False)
        self.assertIs(self._service()._osp_declares_split_operation(self.establishment), False)

    def test_an_unanswered_question_leaves_the_profile_checkbox_in_charge(self):
        """Three states, not two — an unanswered question must not become a declaration."""
        self.assertIsNone(self._service()._osp_declares_split_operation(self.establishment))

    def test_a_bare_value_and_an_enveloped_value_both_read(self):
        self.osp.module_responses = {"modules": {"g6_0_production": {"answers": {"split_operation": True}}}}
        self.osp.save(update_fields=["module_responses"])
        self.assertIs(self._service()._osp_declares_split_operation(self.establishment), True)
