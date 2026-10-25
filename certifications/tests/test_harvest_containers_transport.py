"""Harvest containers, bins and transport: what WSDA, CCOF and OTCO ask, answered once (2026.10.25).

An inspector of a WA apple orchard asks whether the bins are stamped organic, whether wooden bins
from the packer also carry conventional fruit and what happens to them in the packer's dump tank,
whether organic fruit shares a truck with conventional, and where the crop stops before the buyer.
WSDA AGR 2121 §J asks all of it; CCOF G6.1 and OTCO C9 ask parts. Each fact is asked once, gated on
the farm's own answers (never on its certifier), and printed in the module PDF. What the grower
cannot vouch for prints a [REVIEW] line instead of a claim.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase

import pdfplumber

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.schema import Module, ModulePage, Option, Question, text, validate_module
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import _Answers, row_answer_state
from company.models import Company, Establishment
from documents.models import GeneratedDocument

G61 = "g6_1_harvest_transport"
G60 = "g6_0_production"


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Wenatchee Orchards")
        self.est = Establishment.objects.create(name="Wenatchee Orchard", company=self.company, state="WA")
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

    def visible(self, module=G61):
        self.osp.refresh_from_db()
        answers = self.osp.module_responses["modules"][module]["answers"]
        return {q.key for _p, q in visible_questions(MODULES_BY_KEY[module], answers)}

    def pdf_text(self, module=G61):
        self.osp.refresh_from_db()
        with pdfplumber.open(io.BytesIO(generate_module_pdf(self.osp, module))) as doc:
            return " ".join(" ".join((p.extract_text() or "") for p in doc.pages).split())


class WoodBinTests(_Plan):
    def test_the_wood_bin_questions_follow_wooden_bins_only(self):
        self.answer(G61, container_types=["plastic_bins"])
        self.assertNotIn("receives_nondedicated_wood_bins", self.visible())
        self.answer(G61, container_types=["wooden_bins"], receives_nondedicated_wood_bins=True)
        self.assertTrue(
            {"receives_nondedicated_wood_bins", "handler_bin_practice", "handler_bin_documentation_upload"}
            <= self.visible()
        )

    def test_an_unconfirmed_packer_practice_prints_for_review_and_a_confirmed_one_does_not(self):
        self.answer(
            G61,
            container_types=["wooden_bins"],
            receives_nondedicated_wood_bins=True,
            handler_bin_practice="unconfirmed",
        )
        text_ = self.pdf_text()
        self.assertIn("We believe so, but it is not confirmed in writing", text_)
        self.assertIn("[REVIEW] The operator believes these non-dedicated wooden bins", text_)
        self.answer(G61, handler_bin_practice="confirmed")
        self.assertNotIn("[REVIEW] The operator believes", self.pdf_text())


class AttachedMeansAttachedTests(_Plan):
    def test_a_procedure_said_to_be_attached_must_be_attached(self):
        self.answer(G61, container_safeguards=["cleaned_prior"], container_cleaning_records=["sop_attached"])
        self.assertIn("but no file is attached to this plan for it", self.pdf_text())
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="uploads",
            source="upload",
            title="Bin cleaning SOP",
            file=SimpleUploadedFile("sop.pdf", b"%PDF-1.4 sop"),
            requirement=f"{G61}.container_cleaning_sop_upload",
        )
        self.assertNotIn("but no file is attached to this plan for it", self.pdf_text())

    def test_requires_upload_must_name_an_upload_question_of_the_module(self):
        bad = Module(
            key="x",
            code="X",
            title=text("X", "X"),
            nop_cites=("§ 205.272",),
            default_section_key="commingling_barriers",
            pages=(
                ModulePage(
                    key="a",
                    title=text("A", "A"),
                    questions=(
                        Question(
                            key="q",
                            kind="radio",
                            label=text("Q", "Q"),
                            options=(Option("a", text("A", "A"), requires_upload="nowhere"),),
                        ),
                    ),
                ),
            ),
        )
        from certifications.models import OSP_SECTION_KEYS

        self.assertTrue(any("requires_upload 'nowhere'" in e for e in validate_module(bad, OSP_SECTION_KEYS)))


class TransportTests(_Plan):
    def test_shared_trucks_ask_how_organic_is_kept_apart(self):
        self.answer(G61, transport_shared_with_noncertified=False)
        self.assertNotIn("shared_transport_segregation", self.visible())
        self.answer(G61, transport_shared_with_noncertified=True, shared_transport_segregation=["separate_pallets"])
        self.assertIn("shared_transport_segregation", self.visible())
        self.assertIn("Separate, labeled pallets", self.pdf_text())

    def test_a_carrier_is_asked_whether_it_does_more_than_move_the_load(self):
        self.answer(G61, who_transports=["own_vehicles"])
        self.assertNotIn("carrier_handles_beyond_transport", self.visible())
        self.answer(G61, who_transports=["commercial_carrier"])
        self.assertIn("carrier_handles_beyond_transport", self.visible())

    def test_the_first_stop_before_the_buyer_prints(self):
        self.answer(G61, first_stop_before_buyer=["hydrocooler"])
        self.assertIn("A hydrocooler or cooling facility", self.pdf_text())


class ContainerTests(_Plan):
    def test_unstamped_containers_ask_for_safeguards_and_stamped_ones_do_not(self):
        self.answer(G61, harvest_containers_stamped_organic="all")
        self.assertNotIn("unstamped_container_safeguards", self.visible())
        self.answer(G61, harvest_containers_stamped_organic="some")
        self.assertIn("unstamped_container_safeguards", self.visible())

    def test_a_reused_container_answer_keeps_its_meaning(self):
        """The new safeguards question is separate: the § 205.272(b)(2) question keeps its own words,
        so a stored No still answers exactly what it answered."""
        self.answer(G61, containers_reused_from_prohibited=False)
        text_ = self.pdf_text()
        self.assertIn("previously held a prohibited substance", text_)
        self.assertNotIn("non-organic product", text_.split("previously held a prohibited substance", 1)[1][:200])

    def test_old_field_bins_reads_as_given_and_asks_which_kind(self):
        self.answer(G61, container_types=["field_bins"])
        text_ = self.pdf_text()
        self.assertIn("Field bins", text_)
        self.assertIn("[REVIEW] Answered with an option this question no longer offers", text_)


class SplitOperationTests(_Plan):
    def test_separation_at_harvest_is_asked_of_a_split_operation(self):
        self.answer(G60, split_operation=False)
        self.assertNotIn("harvest_transport_separation", self.visible(G60))
        self.answer(G60, split_operation=True, harvest_transport_separation=["separate_vehicles"])
        self.assertIn("harvest_transport_separation", self.visible(G60))


class EachAgentsRowIsAnsweredTests(_Plan):
    """The coverage page reads each agent's own rows: the same answers close WSDA §J and CCOF G6.1."""

    def _state(self, agent, code, ref):
        form = next(f for f in load_forms(agent) if f.code == code)
        item = next(i for i in form.items if i.ref == ref)
        self.osp.refresh_from_db()
        return row_answer_state(_Answers(self.osp), item).state

    def test_wsda_and_ccof_rows_close_from_one_set_of_answers(self):
        self.answer(
            G61,
            who_harvests=["own_crew"],
            harvest_method=["by_hand"],
            container_types=["wooden_bins"],
            harvest_containers_stamped_organic="none",
            unstamped_container_safeguards=["wood_fully_lined"],
            containers_reused_from_prohibited=False,
            receives_nondedicated_wood_bins=True,
            handler_bin_practice="unconfirmed",
            who_transports=["commercial_carrier"],
            carrier_handles_beyond_transport=False,
            harvest_transport_records_source=["contractor_provides"],
            non_own_transport_records="Carrier sends a clean-truck affidavit and the bill of lading with each load.",
            transport_container_types=["bins_totes"],
            transport_shared_with_noncertified=True,
            shared_transport_segregation=["separate_pallets"],
        )
        for ref in ("3", "7", "7a", "8", "8a", "9", "12", "12a"):
            with self.subTest(wsda=ref):
                self.assertEqual(self._state("wsda", "J", ref), "answered")
        for ref in ("A2", "A3"):
            with self.subTest(ccof=ref):
                self.assertEqual(self._state("ccof", "G6.1", ref), "answered")


class EveryNewQuestionIsBilingualTests(SimpleTestCase):
    def test_labels_and_options_carry_both_languages(self):
        new = {
            "harvest_method",
            "harvest_records_kept",
            "harvest_transport_records_source",
            "third_party_activities",
            "third_party_equipment_controls",
            "third_party_cleaning_documentation",
            "harvest_container_material",
            "container_cleaning_records",
            "container_cleaning_sop_upload",
            "harvest_containers_stamped_organic",
            "unstamped_container_safeguards",
            "receives_nondedicated_wood_bins",
            "handler_bin_practice",
            "handler_bin_documentation_upload",
            "empty_bin_storage",
            "carrier_handles_beyond_transport",
            "transport_container_types",
            "transport_unit_cleaning_documentation",
            "transport_shared_with_noncertified",
            "shared_transport_segregation",
            "first_stop_before_buyer",
        }
        seen = set()
        for page in MODULES_BY_KEY[G61].pages:
            for q in page.questions:
                if q.key in new:
                    seen.add(q.key)
                    self.assertTrue(q.label["en"] and q.label["es"], q.key)
                    for o in q.options:
                        self.assertTrue(o.label["en"] and o.label["es"], f"{q.key}.{o.value}")
        self.assertEqual(seen, new)
