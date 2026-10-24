"""The coverage page says a form is answered only when this plan answers it.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10 (documentation/audits/OSP-ALIGNMENT-2026-10/LEDGER.md, T15, T16, T19,
T20, T23). Page 04 headed its list "Forms generated in this packet" and put a form there the moment
a module mapped to it. It never read an answer. An operation that had answered nothing received a
page telling its certifier every form was in the packet, including CCOF's six-page contract for a
three-question profile and the agents' renewal applications with nothing filed.

The rules pinned here:

  * a row closes only on evidence: an answer, or a trigger answer that makes the question not
    apply, or a module N/A that carries its attestation;
  * a hidden question whose trigger is unanswered is OPEN ("unresolved"), not "does not apply";
  * a file uploaded to a section does not satisfy a named attachment, because uploads are linked
    to the section, not the question;
  * a form whose rows were checked against nothing is never "answered";
  * a form the operation files with its agent is never "answered", filed update or not;
  * an agent with no register gets no other agent's numbering.
"""

import datetime
import io
import zipfile
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.services.certifier_register import Form, Item
from certifications.services.osp_module_pdf import _coverage_pdf, generate_osp_packet
from certifications.services.packet_answers import (
    RowState,
    _Answers,
    form_answer_states,
    form_is_answered,
    row_answer_state,
)
from certifications.services.packet_coverage import form_coverage
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from product.models import Parcel

from .test_renewal_packet_contents import _pdf_text

_AT = "2026-09-30T00:00:00Z"


def _item(ref, *questions, status="covered"):
    return Item(ref=ref, asks=f"asks {ref}", status=status, questions=tuple(questions))


def _answer(value):
    return {"value": value, "at": _AT}


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Answers Co")
        self.est = Establishment.objects.create(name="Answers Farm", company=self.company, state="OR")
        Parcel.objects.create(name="North Block", establishment=self.est, area=3.0)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name="CCOF"
        )

    def _set(self, module_key, answers=None, **entry):
        responses = self.osp.module_responses or {"modules": {}}
        responses.setdefault("modules", {})[module_key] = {
            "answers": {k: _answer(v) for k, v in (answers or {}).items()},
            **entry,
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _state(self, item) -> RowState:
        return row_answer_state(_Answers(self.osp), item)

    def _upload(self, section):
        return GeneratedDocument.objects.create(
            establishment=self.est,
            folder="organic_system_plan",
            source="upload",
            title="unrelated.pdf",
            file=ContentFile(b"%PDF-1.4 x", name="unrelated.pdf"),
            linked_section=section,
        )


class RowStateTests(_Plan):
    """One test per state. Each asserts the state AND that the evidence behind it is recorded."""

    def test_a_visible_question_with_no_answer_is_open(self):
        state = self._state(_item("A0", "g7_0_labeling.product_leaves_as"))
        self.assertEqual(state.state, "unanswered")
        self.assertTrue(state.is_open)

    def test_an_answered_question_on_a_covered_row_closes_it(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["bulk_bins_marked"]})
        state = self._state(_item("A0", "g7_0_labeling.product_leaves_as"))
        self.assertEqual(state.state, "answered")
        self.assertFalse(state.is_open)

    def test_a_partial_row_stays_open_even_when_answered(self):
        """The register says Trazo collects only part of what the form asks. An answer to that
        part does not answer the rest."""
        self._set("g7_0_labeling", {"product_leaves_as": ["bulk_bins_marked"]})
        state = self._state(_item("A0", "g7_0_labeling.product_leaves_as", status="partial"))
        self.assertEqual(state.state, "partial")
        self.assertTrue(state.is_open)

    def test_a_hidden_question_whose_trigger_is_unanswered_is_unresolved(self):
        """Nobody has said the labels question does not apply. It is hidden only because the
        question that decides it has not been answered."""
        state = self._state(_item("A1", "g7_0_labeling.label_files_upload"))
        self.assertEqual(state.state, "unresolved")
        self.assertIn("product_leaves_as", state.detail)
        self.assertTrue(state.is_open)

    def test_a_hidden_question_whose_trigger_is_answered_does_not_apply_and_says_why(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["bulk_bins_marked"]})
        state = self._state(_item("A1", "g7_0_labeling.label_files_upload"))
        self.assertEqual(state.state, "not_applicable")
        self.assertIn("product_leaves_as", state.detail)
        self.assertIn("bulk_bins_marked", state.detail)
        self.assertFalse(state.is_open)

    def test_a_required_attachment_with_nothing_uploaded_is_missing(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["consumer_packaging"]})
        state = self._state(_item("A1", "g7_0_labeling.label_files_upload"))
        self.assertEqual(state.state, "attachment_missing")
        self.assertIn("label files", state.detail)

    def test_an_unrelated_upload_in_the_same_section_does_not_satisfy_the_attachment(self):
        """Uploads are linked to a module, not to a question. A file in the labeling section is
        not identified as a label sample, and it does not ride in the packet either."""
        self._set("g7_0_labeling", {"product_leaves_as": ["consumer_packaging"]})
        self._upload("g7_0_labeling")
        state = self._state(_item("A1", "g7_0_labeling.label_files_upload"))
        self.assertEqual(state.state, "attachment_not_identified")
        self.assertTrue(state.is_open)

    def test_an_upload_in_another_section_changes_nothing(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["consumer_packaging"]})
        self._upload("g8_0_record_keeping")
        self.assertEqual(self._state(_item("A1", "g7_0_labeling.label_files_upload")).state, "attachment_missing")

    def test_a_module_marked_not_applicable_without_the_attestation_does_not_close_its_rows(self):
        self._set("g7_0_labeling", not_applicable=True, na_attestation=None)
        self.assertEqual(self._state(_item("A0", "g7_0_labeling.product_leaves_as")).state, "unanswered")

    def test_a_module_attested_not_applicable_closes_its_rows(self):
        self._set("g7_0_labeling", not_applicable=True, na_attestation={"by": 1, "at": _AT})
        state = self._state(_item("A0", "g7_0_labeling.product_leaves_as"))
        self.assertEqual(state.state, "not_applicable")
        self.assertIn("attested", state.detail)

    def test_a_question_the_registry_does_not_have_is_never_answered(self):
        self.assertEqual(self._state(_item("X", "g7_0_labeling.no_such_question")).state, "unknown_reference")
        self.assertEqual(self._state(_item("X", "no_such_module.anything")).state, "unknown_reference")
        self.assertEqual(self._state(_item("X", "no_dot_at_all")).state, "unknown_reference")

    def test_register_verdicts_that_answer_nothing_stay_open(self):
        self.assertEqual(self._state(_item("N", status="not_covered")).state, "not_collected")
        self.assertEqual(self._state(_item("M")).state, "not_assessed")
        self.assertIsNone(self._state(_item("O", status="out_of_scope")))

    def test_the_worst_question_decides_a_row_that_cites_several(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["consumer_packaging"]})
        item = _item("A", "g7_0_labeling.product_leaves_as", "g7_0_labeling.label_files_upload")
        self.assertEqual(self._state(item).state, "attachment_missing")

    def test_a_parcel_question_is_answered_only_when_every_parcel_answers_it(self):
        item = _item("F2", "parcel_application.currently_certified")
        self.assertEqual(self._state(item).state, "unanswered")
        Parcel.objects.filter(establishment=self.est).update(application_answers={"currently_certified": "yes"})
        self.assertEqual(self._state(item).state, "answered")
        Parcel.objects.create(name="South Block", establishment=self.est, area=1.0)
        self.assertEqual(self._state(item).state, "unanswered")


class FormAnsweredTests(TestCase):
    def test_a_form_checked_against_nothing_is_never_answered(self):
        self.assertFalse(form_is_answered([]))
        self.assertFalse(form_is_answered([RowState("A", "not_assessed"), RowState("B", "not_assessed")]))

    def test_one_open_row_keeps_the_form_open(self):
        self.assertTrue(form_is_answered([RowState("A", "answered"), RowState("B", "not_applicable")]))
        self.assertFalse(form_is_answered([RowState("A", "answered"), RowState("B", "unresolved")]))


def _synthetic_form(*items, document_id="SYN-1", **meta):
    from pathlib import Path

    return Form(
        path=Path("synthetic.yaml"),
        code="S1.0",
        title="Synthetic Labels",
        document_id=document_id,
        revision="r1",
        url="https://example.invalid",
        retrieved="2026-09-30",
        trazo_modules=("g7_0_labeling",),
        certifier="ccof",
        items=list(items),
        **meta,
    )


class CoveragePageTests(_Plan):
    def _page(self):
        return _pdf_text(_coverage_pdf(self.osp))

    def test_an_empty_plan_answers_no_form(self):
        forms = form_coverage(self.osp, "ccof")
        self.assertTrue(forms)
        self.assertEqual([f.form for f in forms if f.standing == "answered"], [])
        text = self._page()
        self.assertIn("Forms this packet answers in part", text)
        # The only occurrence of the heading is the "in part" one.
        self.assertEqual(text.count("Forms this packet answers"), text.count("Forms this packet answers in part"))
        self.assertNotIn("Forms generated in this packet", text)

    def test_a_form_moves_to_answered_when_its_questions_are_answered(self):
        """Proof the check reads answers: the same form, before and after answering."""
        form = _synthetic_form(_item("A", "g7_0_labeling.product_leaves_as"))
        with patch("certifications.services.packet_coverage._load_forms", return_value=([form], True)):
            before = form_coverage(self.osp, "ccof")
            self.assertEqual(before[0].standing, "in_part")
            self.assertEqual([r.ref for r in before[0].open_rows], ["A"])
            self._set("g7_0_labeling", {"product_leaves_as": ["bulk_bins_marked"]})
            after = form_coverage(self.osp, "ccof")
            self.assertEqual(after[0].standing, "answered")
            text = self._page()
        self.assertIn("Forms this packet answers S1.0 Synthetic Labels (SYN-1)", text)

    def test_the_open_questions_are_named_by_number_never_as_a_ratio(self):
        text = self._page()
        self.assertIn("Still open:", text)
        self.assertNotRegex(text, r"\d+ of \d+ questions")
        self.assertNotIn("%", text)

    def test_missing_label_files_are_named_on_the_labeling_line(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["consumer_packaging"]})
        text = self._page()
        self.assertIn("A1 (your current label files)", text)
        self.assertIn("attachment not uploaded", text)

    def test_an_unrelated_upload_is_not_reported_as_the_label_sample(self):
        self._set("g7_0_labeling", {"product_leaves_as": ["consumer_packaging"]})
        self._upload("g7_0_labeling")
        text = self._page()
        self.assertIn("none is identified as this attachment", text)
        self.assertNotIn("A1 (your current label files) attachment not uploaded", text)

    def test_the_contract_is_filed_with_the_agent_not_answered_by_the_packet(self):
        text = self._page()
        self.assertIn("Forms the operation files with CCOF", text)
        self.assertIn(
            "CCOF Certification Contract (ORGB06): supporting material in modules/operation_profile.pdf", text
        )
        self.assertIn("It carries the operation's signature.", text)
        self.assertNotIn("certification_contract.pdf", text)

    def test_a_filed_annual_update_does_not_turn_the_agents_renewal_form_into_an_answered_one(self):
        otco = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", certifier_name="Oregon Tilth Certified Organic"
        )
        OSPAnnualUpdate.objects.create(
            prior_osp=otco, reporting_year=2026, submitted_at=timezone.make_aware(datetime.datetime(2026, 9, 1))
        )
        standing = {f.document_id: f.standing for f in form_coverage(otco, "otco")}
        self.assertEqual(standing["OSP Update Form"], "filed_with_agent")
        self.assertEqual(standing["O1"], "filed_with_agent")
        text = _pdf_text(_coverage_pdf(otco))
        self.assertIn("Forms the operation files with Oregon Tilth", text)
        self.assertIn("2026 annual update was filed in Trazo on September 1, 2026", text)
        self.assertIn("not this form", text)

    def test_a_filed_update_page_says_it_supports_the_agents_form(self):
        wsda = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=3,
            status="draft",
            certifier_name="Washington State Department of Agriculture",
        )
        OSPAnnualUpdate.objects.create(prior_osp=wsda, reporting_year=2026, submitted_at=timezone.now())
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(wsda)))
        update = _pdf_text(zf.read("02-annual-update.pdf"))
        self.assertIn("It supports, and does not replace, Washington State Department of Agriculture's own", update)
        page = _pdf_text(zf.read("04-coverage-and-scope.pdf"))
        self.assertIn("accepts the operation's own records in place of this form", page)
        # No signature line is registered for AGR 2516, so none is claimed.
        line = page[page.index("Site Update Information (AGR 2516)") :][:400]
        self.assertNotIn("signature", line)


class AgentFilingMetadataTests(TestCase):
    def test_a_signature_or_format_claim_needs_its_source(self):
        from certifications.services.certifier_register import _filing_meta

        with self.assertRaisesRegex(ValueError, "format_source"):
            _filing_meta({"filed_with_agent": True, "requires_signature": True}, "x.yaml")
        with self.assertRaisesRegex(ValueError, "accepted_format must be one of"):
            _filing_meta({"filed_with_agent": True, "accepted_format": "fax", "format_source": "s"}, "x.yaml")
        with self.assertRaisesRegex(ValueError, "filed with the agent"):
            _filing_meta({"requires_signature": True, "format_source": "s"}, "x.yaml")

    def test_agreements_contracts_and_updates_are_filed_with_the_agent(self):
        """A form whose title says it is an agreement, a contract or an update is the agent's own
        paperwork. It must say so, or the page lists it as a form the packet answers."""
        from certifications.services.certifier_register import load_forms

        unflagged = [
            f"{form.certifier}: {form.label}"
            for certifier in ("ccof", "otco", "wsda")
            for form in load_forms(certifier)
            if any(word in form.title for word in ("Agreement", "Contract", "Update")) and not form.filed_with_agent
        ]
        self.assertEqual(unflagged, [])


class StatesAreComputedPerPlanTests(_Plan):
    def test_states_for_one_plan_do_not_read_another_plans_answers(self):
        other = OrganicSystemPlan.objects.create(establishment=self.est, version_number=9, status="draft")
        other.module_responses = {
            "modules": {"g7_0_labeling": {"answers": {"product_leaves_as": _answer(["bulk_bins_marked"])}}}
        }
        other.save()
        form = _synthetic_form(_item("A", "g7_0_labeling.product_leaves_as"))
        states = form_answer_states(self.osp, [form])[id(form)]
        self.assertEqual(states[0].state, "unanswered")


class TriggerEvidenceTests(SimpleTestCase):
    """Review of #64: only the conditions that FAIL decide whether a hidden question applies."""

    def _module(self, *conditions):
        from certifications.osp_modules.schema import Module, ModulePage, Question, text

        question = Question(key="q", kind="text", label=text("Q", "Q"), visible_when=tuple(conditions))
        return Module(
            key="m", code="", title=text("M", "M"), nop_cites=(), pages=(ModulePage(key="p", questions=(question,)),)
        )

    def test_an_answered_failing_condition_decides_whatever_a_passing_one_holds(self):
        from certifications.osp_modules.schema import Condition
        from certifications.services.packet_answers import question_state

        # `a` is answered and fails; `b` is unanswered but `falsy` passes on a missing value.
        module = self._module(Condition("a", "eq", "x"), Condition("b", "falsy"))
        state, detail = question_state(module, "q", {"a": "y"}, na_attested=False, section_uploads=0)
        self.assertEqual(state, "not_applicable")
        self.assertIn("a = 'y'", detail)
        self.assertNotIn("b", detail)

    def test_a_question_hidden_only_by_unanswered_triggers_is_unresolved(self):
        from certifications.osp_modules.schema import Condition
        from certifications.services.packet_answers import question_state

        module = self._module(Condition("a", "eq", "x"), Condition("b", "falsy"))
        state, detail = question_state(module, "q", {}, na_attested=False, section_uploads=0)
        self.assertEqual(state, "unresolved")
        self.assertEqual(detail, "a")


class ParcelMapTests(_Plan):
    """Review of #64: a parcel map is uploaded against that parcel's own map requirement and rides
    in the packet under parcels/maps/, so it answers the map attachment."""

    def test_an_uploaded_parcel_map_answers_the_map_requirement(self):
        from certifications.services.osp_module_pdf import PARCEL_MAP_SECTION

        item = _item("E", "parcel_application.map_upload")
        self.assertEqual(self._state(item).state, "attachment_missing")
        parcel = Parcel.objects.get(establishment=self.est, name="North Block")
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="organic_system_plan",
            source="upload",
            title="north-map.pdf",
            file=ContentFile(b"%PDF-1.4 x", name="north-map.pdf"),
            linked_section=PARCEL_MAP_SECTION,
            parcel=parcel,
        )
        self.assertEqual(self._state(item).state, "answered")

    def test_every_parcel_needs_its_own_map(self):
        from certifications.services.osp_module_pdf import PARCEL_MAP_SECTION

        north = Parcel.objects.get(establishment=self.est, name="North Block")
        Parcel.objects.create(name="South Block", establishment=self.est, area=1.0)
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="organic_system_plan",
            source="upload",
            title="north-map.pdf",
            file=ContentFile(b"%PDF-1.4 x", name="north-map.pdf"),
            linked_section=PARCEL_MAP_SECTION,
            parcel=north,
        )
        self.assertEqual(self._state(_item("E", "parcel_application.map_upload")).state, "attachment_missing")
