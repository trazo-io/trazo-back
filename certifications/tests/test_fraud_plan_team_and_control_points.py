"""The fraud prevention plan's team, reporting, training, audits, supply chain and control points (2026-11-14).

OTCO's Organic Fraud Prevention Plan (rev 2025/08/27) asks a team of name, role and contact (1-1), where suspected
fraud is reported (1-2), whether a separate plan exists, No or Yes attached (1-4), the supply chain as a map or a
simple description (2-1), a table of critical control points with each one's strategies and monitoring (3-1), and
when staff are trained on the plan (4-1). WSDA AGR 2121 §P asks written SOPs (1), how often beside each way the plan
is kept in practice (2), internal audits and their scope (3, 3a), what would be reported (6) and a notes space (7).
OTCO C12 12.3-1 asks how often records are checked; CCOF's Contract B2 the plan review cadence, which was answerable
already and read open.

Every new question is optional: plans filed before them stay complete.
"""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress, visible_questions
from certifications.osp_modules.g2_0_fraud_prevention import CONTROL_POINTS
from certifications.services.osp_module_compiler import compile_module_contributions
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from documents.models import GeneratedDocument

MODULE = MODULES_BY_KEY["g2_0_fraud_prevention"]
OTCO = "Oregon Tilth Certified Organic (OTCO)"
CCOF = "California Certified Organic Farmers (CCOF)"
WSDA = "Washington State Department of Agriculture (WSDA)"

NEW_KEYS = (
    "fraud_reporting_channels",
    "fraud_reporting_channels_other",
    "fraud_reporting_triggers",
    "fraud_reporting_triggers_other",
    "fraud_plan_kept_separately",
    "ofpp_team",
    "record_review_frequency",
    "employee_evaluation_frequency",
    "ofpp_training_cadence",
    "ofpp_training_cadence_other",
    "internal_audits_conducted",
    "internal_audit_scope",
    "written_sops_kept",
    "sop_upload",
    "fraud_additional_notes",
    "supply_chain_shown_as",
    "supply_chain_map_upload",
    "supply_chain_description",
    "critical_control_points",
    "ccp_other_name",
    *(f"ccp_{key}_{column}" for key, _label, _name in CONTROL_POINTS for column in ("strategy", "monitoring")),
)

#: What a plan answered before 2026.12.10: the four required questions.
FILED = {
    "fraud_risk_areas": ["custom_operators"],
    "fraud_mitigation_practices": ["verify_certificates", "report_suspected"],
    "fraud_review_process": "The owner reviews certificates every January.",
    "osp_review_frequency": ["quarterly"],
    "osp_accuracy_process": "The owner keeps the plan accurate.",
    "osp_implementation_monitoring": ["record_review"],
}

ANSWERS = {
    **FILED,
    "fraud_reporting_channels": ["own_certifier", "suppliers_certifier", "usda_nop"],
    "fraud_reporting_triggers": ["positive_sample_results", "quantity_exceeds_capacity", "other"],
    "fraud_reporting_triggers_other": "A carrier that cannot show a clean truck affidavit",
    "fraud_plan_kept_separately": False,
    "ofpp_team": "Ann Vos, managing member, 541-555-0101: approves and monitors the plan. "
    "Rafael Ortiz, crew lead, rafael@example.com: trains the crew.",
    "osp_implementation_monitoring": ["record_review", "employee_evaluations", "corrective_actions_documented"],
    "record_review_frequency": "Weekly during harvest",
    "employee_evaluation_frequency": "At the end of each harvest",
    "ofpp_training_cadence": ["onboarding", "within_month_of_change"],
    "internal_audits_conducted": True,
    "internal_audit_scope": "Each February, inputs, cleanouts and sales against the plan",
    "written_sops_kept": False,
    "fraud_additional_notes": "The crew lead keeps the clean truck affidavits in the shop binder.",
    "supply_chain_shown_as": "described",
    "supply_chain_description": "Trees from Willow Drive Nursery, certified. Hood River Packers takes the bins.",
    "critical_control_points": ["transport", "other"],
    "ccp_other_name": "Bins borrowed from the packer",
    "ccp_transport_strategy": "The packer's clean truck affidavit is filed with each load's record.",
    "ccp_transport_monitoring": "Checked for every load before the bins are loaded.",
    "ccp_other_strategy": "Borrowed bins are lined and tagged organic before picking.",
    "ccp_other_monitoring": "The crew lead checks each borrowed bin at the orchard gate, every load.",
}

OFPP_ROWS = ("1-1", "1-2", "1-4", "2-1", "2-1b", "2-1c", "2-1d", "2-1 (simple supply chain description)")
OFPP_TABLE_ROWS = ("3-1", "3-1a", "3-1b", "3-1c", "4-1")
WSDA_ROWS = ("1", "2", "3", "3a", "6", "7")


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _visible(answers) -> set:
    return {q.key for _page, q in visible_questions(MODULE, answers)}


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Vos Orchards LLC")
        self.est = Establishment.objects.create(name="Vos Orchards", company=company, state="OR")

    def plan(self, answers, certifier=OTCO):
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.filter(establishment=self.est).count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "modules": {
                    "g2_0_fraud_prevention": {
                        "answers": {key: {"value": value} for key, value in answers.items()},
                        "definition_version": "2026.12.10",
                    },
                },
            },
        )
        return self.osp

    def upload(self, question_key, title=None):
        GeneratedDocument.objects.create(
            establishment=self.est,
            folder="uploads",
            source="upload",
            title=title or question_key,
            file=SimpleUploadedFile("file.pdf", b"%PDF-1.4 file"),
            requirement=f"g2_0_fraud_prevention.{question_key}",
        )

    def row(self, agent, stem, ref):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms(agent) if f.path.stem == stem)
        return next(r for r in form_answer_states(self.osp, [form])[id(form)] if r.ref == ref)

    def ofpp(self, ref):
        return self.row("otco", "OFPP-organic-fraud-prevention-plan", ref)

    def wsda(self, ref):
        return self.row("wsda", "2121-P-quality-assurance", ref)


class EveryNewQuestionIsOptional(TestCase):
    def test_a_plan_filed_before_them_stays_complete(self):
        questions = {q.key: q for page in MODULE.pages for q in page.questions}
        for key in NEW_KEYS:
            with self.subTest(question=key):
                self.assertFalse(questions[key].required)
        self.assertEqual(progress(MODULE, FILED)["missing"], [])


class TheOldAnswersKeepTheirMeaning(TestCase):
    def test_the_monitoring_options_keep_their_place(self):
        """Stored answers name options by value: the new ways go in before "other", the rest stay where they were."""
        question = next(q for page in MODULE.pages for q in page.questions if q.key == "osp_implementation_monitoring")
        self.assertEqual(
            [o.value for o in question.options],
            [
                "record_review",
                "internal_review",
                "staff_training",
                "staff_checkins",
                "dual_signoff",
                "procedures_in_activity_records",
                "employee_evaluations",
                "corrective_actions_documented",
                "other",
            ],
        )

    def test_reporting_does_not_wait_on_the_report_tick(self):
        """Both agents ask every operation where and what it reports; the old tick keeps the meaning it was given."""
        shown = _visible({"fraud_mitigation_practices": ["verify_certificates"]})
        self.assertIn("fraud_reporting_channels", shown)
        self.assertIn("fraud_reporting_triggers", shown)


class TheGates(TestCase):
    def test_the_sop_upload_shows_on_its_yes(self):
        self.assertNotIn("sop_upload", _visible({}))
        self.assertNotIn("sop_upload", _visible({"written_sops_kept": False}))
        self.assertIn("sop_upload", _visible({"written_sops_kept": True}))

    def test_the_older_plan_upload_hides_only_on_a_no(self):
        """It was shown to every plan before the question existed, and a file may already be filed to it."""
        self.assertIn("fraud_plan_upload", _visible({}))
        self.assertIn("fraud_plan_upload", _visible({"fraud_plan_kept_separately": True}))
        self.assertNotIn("fraud_plan_upload", _visible({"fraud_plan_kept_separately": False}))

    def test_the_map_or_the_description(self):
        self.assertEqual(
            {"supply_chain_map_upload"} & _visible({"supply_chain_shown_as": "map"}), {"supply_chain_map_upload"}
        )
        self.assertNotIn("supply_chain_description", _visible({"supply_chain_shown_as": "map"}))
        self.assertIn("supply_chain_description", _visible({"supply_chain_shown_as": "described"}))
        self.assertNotIn("supply_chain_map_upload", _visible({"supply_chain_shown_as": "described"}))

    def test_only_the_picked_points_ask_their_columns(self):
        shown = _visible({"critical_control_points": ["transport"]})
        self.assertTrue({"ccp_transport_strategy", "ccp_transport_monitoring"} <= shown)
        self.assertFalse({"ccp_sales_strategy", "ccp_sales_monitoring", "ccp_other_name"} & shown)

    def test_the_frequencies_show_on_their_ways(self):
        self.assertNotIn("record_review_frequency", _visible({"osp_implementation_monitoring": ["internal_review"]}))
        shown = _visible({"osp_implementation_monitoring": ["record_review", "employee_evaluations"]})
        self.assertTrue({"record_review_frequency", "employee_evaluation_frequency"} <= shown)
        self.assertNotIn("internal_audit_scope", _visible({"internal_audits_conducted": False}))
        self.assertIn("internal_audit_scope", _visible({"internal_audits_conducted": True}))


class TheModulePdfPrintsThem(_Plan):
    def test_every_answer_prints(self):
        text = _text(generate_module_pdf(self.plan(ANSWERS), "g2_0_fraud_prevention"))
        for words in (
            "Rafael Ortiz, crew lead, rafael@example.com: trains the crew.",
            "The supplier's certifying agent",
            "A supplier delivering more organic product than it is known to produce",
            "A carrier that cannot show a clean truck affidavit",
            "Staff observations and evaluations include organic practices",
            "Weekly during harvest",
            "At the end of each harvest",
            "Staff are trained on a change to the plan within a month of it",
            "Each February, inputs, cleanouts and sales against the plan",
            "The crew lead keeps the clean truck affidavits in the shop binder.",
            "D. Supply chain and critical control points",
            "Hood River Packers takes the bins.",
            "Transport: how do you prevent fraud at this point?",
            "The packer's clean truck affidavit is filed with each load's record.",
            "Transport: how do you check that this works, and how often?",
            "Bins borrowed from the packer",
            "Other control point: how do you check that this works, and how often?",
            "The crew lead checks each borrowed bin at the orchard gate, every load.",
        ):
            with self.subTest(words=words):
                self.assertIn(words, text)

    def test_a_map_said_attached_with_no_file_is_flagged(self):
        text = _text(generate_module_pdf(self.plan({"supply_chain_shown_as": "map"}), "g2_0_fraud_prevention"))
        self.assertIn("[REVIEW] The answer says it is attached (We attach a map or flow chart)", text)
        self.upload("supply_chain_map_upload")
        text = _text(generate_module_pdf(self.osp, "g2_0_fraud_prevention"))
        self.assertNotIn("[REVIEW] The answer says it is attached", text)

    def test_a_no_compiles_to_what_was_said(self):
        sections = compile_module_contributions(self.plan(ANSWERS))
        narrative = " ".join(" ".join(paragraphs) for paragraphs in sections.values())
        self.assertIn("The operation keeps no separate fraud prevention plan; the answers in this section", narrative)
        self.assertIn("The operation keeps no written standard operating procedures beyond this plan.", narrative)
        self.assertIn("The operation conducts internal audits (Yes).", narrative)


class TheRegisterReadsThem(_Plan):
    def test_otco_rows_close_with_the_answers(self):
        self.plan(ANSWERS)
        for ref in OFPP_ROWS + OFPP_TABLE_ROWS:
            with self.subTest(ref=ref):
                self.assertEqual(self.ofpp(ref).state, "answered")

    def test_otco_rows_are_open_on_a_plan_filed_before_them(self):
        self.plan(FILED)
        for ref in ("1-1", "1-2", "1-4", "2-1", "3-1", "3-1a", "4-1"):
            with self.subTest(ref=ref):
                self.assertTrue(self.ofpp(ref).is_open)

    def test_a_picked_control_point_needs_both_columns(self):
        self.plan({"critical_control_points": ["transport"], "ccp_transport_monitoring": "Every load."})
        self.assertEqual(self.ofpp("3-1c").state, "answered")
        self.assertTrue(self.ofpp("3-1b").is_open)

    def test_a_separate_plan_said_kept_needs_the_file(self):
        self.plan({"fraud_plan_kept_separately": True})
        self.assertEqual(self.ofpp("1-4").state, "attachment_missing")
        self.upload("fraud_plan_upload")
        self.assertEqual(self.ofpp("1-4").state, "answered")

    def test_a_map_needs_the_file_and_a_description_does_not(self):
        self.plan({"supply_chain_shown_as": "map"})
        self.assertEqual(self.ofpp("2-1").state, "attachment_missing")
        self.upload("supply_chain_map_upload")
        self.assertEqual(self.ofpp("2-1").state, "answered")
        self.plan({"supply_chain_shown_as": "described"})
        self.assertTrue(self.ofpp("2-1").is_open)

    def test_no_staff_answers_training(self):
        self.plan({"ofpp_training_cadence": ["no_staff"]})
        self.assertEqual(self.ofpp("4-1").state, "answered")

    def test_wsda_rows_close_with_the_answers(self):
        self.plan(ANSWERS, certifier=WSDA)
        for ref in WSDA_ROWS:
            with self.subTest(ref=ref):
                self.assertEqual(self.wsda(ref).state, "answered")

    def test_wsda_sops_said_kept_need_the_file(self):
        self.plan({"written_sops_kept": True}, certifier=WSDA)
        self.assertEqual(self.wsda("1").state, "attachment_missing")
        self.upload("sop_upload")
        self.assertEqual(self.wsda("1").state, "answered")

    def test_wsda_audit_scope_does_not_apply_without_audits(self):
        self.plan({"internal_audits_conducted": False}, certifier=WSDA)
        self.assertEqual(self.wsda("3").state, "answered")
        self.assertEqual(self.wsda("3a").state, "not_applicable")

    def test_a_review_with_no_frequency_is_open(self):
        answers = {**ANSWERS}
        del answers["record_review_frequency"]
        self.plan(answers, certifier=WSDA)
        self.assertTrue(self.wsda("2").is_open)
        self.assertTrue(self.row("otco", "C12-crop-record-keeping", "12.3-1").is_open)

    def test_otco_c12_reads_the_record_review_and_how_often(self):
        self.plan(ANSWERS)
        self.assertEqual(self.row("otco", "C12-crop-record-keeping", "12.3-1").state, "answered")

    def test_ccof_b2_reads_a_quarterly_review(self):
        self.plan(FILED, certifier=CCOF)
        self.assertEqual(self.row("ccof", "Certification-Contract", "B2").state, "answered")


class AFileFiledBeforeTheQuestion(_Plan):
    def test_still_rides_in_the_packet_and_is_named(self):
        """A plan document filed before `fraud_plan_kept_separately` existed: the upload is hidden until that is
        answered, but its file still travels, and a page of the packet names where."""
        self.plan(FILED)
        self.upload("fraud_plan_upload", title="Vos fraud plan")
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        carried = [n for n in zf.namelist() if "Vos fraud plan" in n]
        self.assertEqual(len(carried), 1, zf.namelist())
        text = "".join(
            "".join(_text(zf.read(n)).split()) for n in zf.namelist() if n.endswith(".pdf") and n not in carried
        )
        self.assertIn("".join(carried[0].split()), text)
        self.assertTrue(self.ofpp("1-4").is_open)
