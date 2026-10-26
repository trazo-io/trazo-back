"""Storage and nonretail containers: what WSDA, CCOF and OTCO ask, answered once (2026.10.26).

WSDA AGR 2121 §K asks whether stored product is all in sealed, impermeable packages and, if not, how it
is kept organic and what records show where it is and how the area was cleaned. §N, CCOF G7.0 A1-A3 and
OTCO C8 8.1 ask which bins, totes and trailers carry the crop, how each one shows the product is organic,
which identifier it carries and how that identifier leads back to the lot. Each fact is asked once,
gated on the farm's own answers, printed in the module PDF, and read by each agent's coverage row.

Unlabeled bulk stays answerable: it can be true. Choosing it shows a notice and prints a [REVIEW] line
citing § 205.307(a)(1), never a refusal.
"""

import io
from datetime import datetime
from datetime import timezone as dt_tz

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import pdfplumber

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import _Answers, row_answer_state
from company.models import Company, Establishment
from history.models import History, ProductionEvent
from product.models import Parcel

G62 = "g6_2_storage"
G70 = "g7_0_labeling"

NEW_QUESTIONS = {
    G62: {
        "stored_in_sealed_packaging",
        "unsealed_storage_controls",
        "unsealed_storage_controls_other",
        "storage_location_records",
        "storage_location_records_other",
        "organic_storage_area_identification",
    },
    G70: {
        "unlabeled_bulk_notice",
        "nonretail_container_types",
        "nonretail_organic_identification",
        "nonretail_identification_other",
        "nonretail_label_upload",
        "container_lot_identifier_types",
        "container_lot_linkage_description",
    },
}


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Yakima Orchards")
        self.est = Establishment.objects.create(name="Yakima Orchard", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def answer(self, module, **values):
        responses = dict(self.osp.module_responses or {})
        modules = dict(responses.get("modules") or {})
        entry = dict(modules.get(module) or {})
        entry["answers"] = {**(entry.get("answers") or {}), **values}
        modules[module] = entry
        responses["modules"] = modules
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def visible(self, module):
        self.osp.refresh_from_db()
        answers = self.osp.module_responses["modules"][module]["answers"]
        return {q.key for _p, q in visible_questions(MODULES_BY_KEY[module], answers)}

    def pdf_text(self, module):
        self.osp.refresh_from_db()
        with pdfplumber.open(io.BytesIO(generate_module_pdf(self.osp, module))) as doc:
            return " ".join(" ".join((p.extract_text() or "") for p in doc.pages).split())

    def state(self, agent, code, ref):
        form = next(f for f in load_forms(agent) if f.code == code)
        item = next(i for i in form.items if i.ref == ref)
        self.osp.refresh_from_db()
        return row_answer_state(_Answers(self.osp), item).state


class SealedStorageTests(_Plan):
    def test_unsealed_questions_wait_for_a_no_and_an_unanswered_plan_hides_them(self):
        self.answer(G62, storage_locations=["on_farm_cold"])
        self.assertTrue({"unsealed_storage_controls", "storage_location_records"}.isdisjoint(self.visible(G62)))
        self.answer(G62, stored_in_sealed_packaging=True)
        self.assertNotIn("unsealed_storage_controls", self.visible(G62))
        self.answer(G62, stored_in_sealed_packaging=False)
        self.assertTrue({"unsealed_storage_controls", "storage_location_records"} <= self.visible(G62))

    def test_wsdas_options_print_as_given(self):
        self.answer(
            G62,
            storage_locations=["on_farm_cold"],
            stored_in_sealed_packaging=False,
            unsealed_storage_controls=["rooms_dedicated_for_season", "areas_with_organic_signage"],
        )
        text_ = self.pdf_text(G62)
        self.assertIn("It is stored in rooms cleaned and dedicated to organic product for the whole season", text_)
        self.assertIn("It is stored in areas or on shelves marked with organic signage", text_)

    def test_a_shared_room_is_asked_how_its_organic_area_is_marked(self):
        self.answer(G62, storage_shared_with_nonorganic=False)
        self.assertNotIn("organic_storage_area_identification", self.visible(G62))
        self.answer(
            G62,
            storage_shared_with_nonorganic=True,
            organic_storage_area_identification="Green ORGANIC sign on rooms 2 and 3.",
        )
        self.assertIn("Green ORGANIC sign on rooms 2 and 3.", self.pdf_text(G62))


class StorageRecordCountTests(_Plan):
    def setUp(self):
        super().setUp()
        parcel = Parcel.objects.create(name="Block 4", establishment=self.est, area=12.0)
        self.season = History.objects.create(
            name="2026 pears",
            parcel=parcel,
            start_date=datetime(2026, 3, 1, tzinfo=dt_tz.utc),
            finish_date=datetime(2026, 10, 1, tzinfo=dt_tz.utc),
        )

    def event(self, type_, **kw):
        # A harvest covers ground; a cleanout does not (chk_area_covered_valid).
        area = 1.0 if type_ == "HA" else 0.0
        return ProductionEvent.objects.create(
            history=self.season, type=type_, date=timezone.now(), area_covered=area, **kw
        )

    def test_the_records_named_print_what_is_logged_in_trazo(self):
        self.event("HA", storage_location="Cooler 3")
        self.event("HA", storage_location="")  # names no location
        self.event("EM", cleaning_asset_class="storage", cleaning_date=timezone.now().date(), cleaning_method="Swept")
        self.event(
            "EM", cleaning_asset_class="harvest_bins", cleaning_date=timezone.now().date(), cleaning_method="Washed"
        )
        self.answer(
            G62,
            storage_locations=["on_farm_cold"],
            stored_in_sealed_packaging=False,
            storage_location_records=["storage_location_on_harvest_records", "storage_cleaning_log"],
        )
        text_ = self.pdf_text(G62)
        self.assertIn("In Trazo: 1 harvest or post-harvest record naming a storage location.", text_)
        self.assertIn("In Trazo: 1 cleaning record for a storage area or cooler logged.", text_)

    def test_none_logged_says_so(self):
        self.answer(
            G62,
            storage_locations=["on_farm_cold"],
            stored_in_sealed_packaging=False,
            storage_location_records=["storage_cleaning_log"],
        )
        self.assertIn(
            "In Trazo: no cleaning records for storage areas or coolers logged. Records kept outside Trazo are not "
            "counted here.",
            self.pdf_text(G62),
        )


class UnlabeledBulkTests(_Plan):
    def test_unlabeled_bulk_is_answerable_shows_a_notice_and_prints_for_review(self):
        self.answer(G70, product_leaves_as=["unlabeled_bulk_documents"])
        self.assertIn("unlabeled_bulk_notice", self.visible(G70))
        text_ = self.pdf_text(G70)
        self.assertIn("Unlabeled bulk", text_)
        self.assertIn("[REVIEW] Some organic product leaves in nonretail containers that carry no organic", text_)
        self.assertIn("§ 205.307(a)(1)", text_)

    def test_marked_bins_print_no_such_line(self):
        self.answer(G70, product_leaves_as=["bulk_bins_marked"])
        self.assertNotIn("unlabeled_bulk_notice", self.visible(G70))
        self.assertNotIn("[REVIEW] Some organic product leaves", self.pdf_text(G70))


class ContainerIdentifierTests(_Plan):
    def test_identifier_questions_follow_the_existing_answer_which_keeps_its_meaning(self):
        self.answer(G70, container_markings_tie_to_lot=False)
        self.assertTrue(
            {"container_lot_identifier_types", "container_lot_linkage_description"}.isdisjoint(self.visible(G70))
        )
        self.answer(
            G70,
            container_markings_tie_to_lot=True,
            container_lot_identifier_types=["lot_number"],
            container_lot_linkage_description="Bin tag lot = harvest lot (block and pick date), also on the invoice.",
        )
        text_ = self.pdf_text(G70)
        self.assertIn("Do any container markings", text_)
        self.assertIn("A lot number", text_)
        self.assertIn("Bin tag lot = harvest lot (block and pick date), also on the invoice.", text_)

    def test_a_label_example_is_asked_only_when_containers_carry_a_marking(self):
        self.answer(G70, nonretail_organic_identification=["visible_through_container"])
        self.assertNotIn("nonretail_label_upload", self.visible(G70))
        self.answer(G70, nonretail_organic_identification=["container_label_or_tag"])
        self.assertIn("nonretail_label_upload", self.visible(G70))


class EachAgentsRowIsAnsweredTests(_Plan):
    """One set of answers closes WSDA §K and §N, CCOF G6.2 B2b and G7.0 A2/A3, and OTCO C8 8.1-1/8.1-1a."""

    def test_one_set_of_answers_closes_each_agents_rows(self):
        self.answer(
            G62,
            storage_locations=["on_farm_cold"],
            stored_in_sealed_packaging=False,
            unsealed_storage_controls=["rooms_permanently_dedicated"],
            storage_location_records=["storage_location_on_harvest_records"],
            storage_shared_with_nonorganic=True,
            storage_shared_separation="Organic in rooms 2 and 3 only.",
            organic_storage_area_identification="Signs on the doors.",
            storage_cleaned_before_organic=True,
            storage_cleaning_method="Swept and washed in July.",
            lot_identity_maintained=True,
        )
        self.answer(
            G70,
            product_leaves_as=["bulk_bins_marked"],
            nonretail_container_types=["harvest_crates_bins", "bulk_trailers_tanks"],
            nonretail_organic_identification=["container_label_or_tag", "temporary_signage"],
            container_markings_tie_to_lot=True,
            container_lot_identifier_types=["lot_number"],
            container_lot_linkage_description="The bin tag carries the harvest lot.",
        )
        for code, ref in (("K", "3"), ("K", "3a"), ("K", "3b"), ("N", "1"), ("N", "2"), ("N", "3")):
            with self.subTest(wsda=f"{code}{ref}"):
                self.assertEqual(self.state("wsda", code, ref), "answered")
        for code, ref in (("G6.2", "B2b"), ("G7.0", "A2"), ("G7.0", "A3")):
            with self.subTest(ccof=f"{code} {ref}"):
                self.assertEqual(self.state("ccof", code, ref), "answered")
        for ref in ("8.1-1", "8.1-1a"):
            with self.subTest(otco=ref):
                self.assertEqual(self.state("otco", "C8", ref), "answered")


class EveryNewQuestionIsBilingualTests(SimpleTestCase):
    def test_labels_and_options_carry_both_languages(self):
        for module, keys in NEW_QUESTIONS.items():
            seen = set()
            for page in MODULES_BY_KEY[module].pages:
                for q in page.questions:
                    if q.key in keys:
                        seen.add(q.key)
                        self.assertTrue(q.label["en"] and q.label["es"], q.key)
                        for o in q.options:
                            self.assertTrue(o.label["en"] and o.label["es"], f"{q.key}.{o.value}")
            self.assertEqual(seen, keys)
