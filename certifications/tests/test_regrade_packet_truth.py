"""What the blind re-grade of 2026-11-19 found the packet saying that a reviewer could not rely on.

Three graders, each given only an agent's official forms and two generated packets, re-graded 108 register rows
closed since the overall review (audit note: documentation/audits/OVERALL-REVIEW-2026-11/regrade-2026-11-19 in the
workspace repo). Four of the failures were the packet's own words:

  CCOF G6.0 D3   "Not yet confirmed with the district" closed the coverage row: page 04 listed D3 as answered and
                 the module printed no [REVIEW] line.
  Parcel G       The header said the affidavit was "recorded but not signed" beside the table's signing date; the
                 fact the code holds is that no signed copy is attached.
  Parcel G       The header said "Supporting evidence: on file" above the body's "[REVIEW] not accounted for".
  WSDA 2264 8    The crop table printed last season's expected harvest as if it were the coming one.

Every negative assertion here is paired with a premise that the code under test was reached.
"""

from datetime import date, timedelta

from django.test import SimpleTestCase, TestCase

from certifications.osp_modules import MODULE_REGISTRY, MODULES_BY_KEY
from certifications.osp_modules.schema import Module, ModulePage, Option, Question, text, validate_module
from certifications.services.packet_answers import CLOSED_STATES, RowState, _worst, question_state


def _district_answers(value):
    return {
        "irrigation_source_types": {"value": ["irrigation_district"]},
        "water_from_irrigation_district": {"value": True},
        "irrigation_district_additives": {"value": value},
    }


class PendingAnswerTests(SimpleTestCase):
    """An answer the operator marks as not yet known is stated, but it does not answer the form."""

    def _state(self, value):
        return question_state(
            MODULES_BY_KEY["g4_2_natural_resources"],
            "irrigation_district_additives",
            _district_answers(value),
            na_attested=False,
            section_uploads=0,
        )

    def test_not_yet_confirmed_holds_the_row_open(self):
        self.assertEqual(self._state("no_confirmed"), ("answered", ""), "premise: a real answer closes the row")
        state, detail = self._state("unknown")
        self.assertEqual(state, "pending")
        self.assertEqual(detail, "Not yet confirmed with the district")
        self.assertNotIn(state, CLOSED_STATES)
        self.assertTrue(RowState("D3", state, detail).is_open)

    def test_pending_is_worse_than_answered_and_milder_than_unanswered(self):
        self.assertEqual(_worst([("answered", ""), ("pending", "x")]), ("pending", "x"))
        self.assertEqual(_worst([("pending", "x"), ("unanswered", "")]), ("unanswered", ""))

    def test_the_coverage_page_words_it(self):
        from certifications.services.osp_module_pdf import _open_rows_sentence

        sentence = _open_rows_sentence([RowState("D3", "pending", "Not yet confirmed with the district")])
        self.assertIn("D3 answered as not yet known by the operation", sentence)

    def test_every_pending_option_prints_a_review_line(self):
        pending = [
            (m.key, q.key, o)
            for m in MODULE_REGISTRY
            for p in m.pages
            for q in p.questions
            for o in q.options
            if o.pending
        ]
        self.assertGreaterEqual(len(pending), 5, "premise: the five not-yet-known options are marked")
        for module, question, option in pending:
            self.assertTrue(option.review, f"{module}.{question}={option.value} is pending with no [REVIEW] line")

    def test_the_registry_refuses_pending_without_a_review(self):
        module = Module(
            key="probe",
            code="P1",
            title=text("Probe", "Prueba"),
            nop_cites=("§ 205.201",),
            pages=(
                ModulePage(
                    key="a",
                    title=text("A", "A"),
                    questions=(
                        Question(
                            key="q",
                            kind="radio",
                            label=text("Q?", "¿Q?"),
                            options=(
                                Option("yes", text("Yes", "Sí")),
                                Option("unknown", text("Not known yet", "Aún no se sabe"), pending=True),
                            ),
                        ),
                    ),
                ),
            ),
        )
        errors = validate_module(module, ("practices_procedures",))
        self.assertTrue(
            any("pending without a review line" in e for e in errors),
            errors,
        )


class PendingOptionPayloadTests(SimpleTestCase):
    """The wizard learns which options are pending from the module-definitions payload, so it can say under the
    answer that the packet keeps the agent's question open. Until 2026-11-21 only the packet said so."""

    def test_the_payload_marks_exactly_the_pending_options(self):
        from certifications.osp_modules import serialize_registry

        marked, unmarked = set(), 0
        for module in serialize_registry()["modules"]:
            for page in module["pages"]:
                for question in page["questions"]:
                    for option in question["options"]:
                        if "pending" in option:
                            self.assertIs(option["pending"], True)
                            marked.add((module["key"], question["key"], option["value"]))
                        else:
                            unmarked += 1
        declared = {
            (m.key, q.key, o.value)
            for m in MODULE_REGISTRY
            for p in m.pages
            for q in p.questions
            for o in q.options
            if o.pending
        }
        self.assertGreaterEqual(len(declared), 5, "premise: the five not-yet-known options are declared")
        self.assertEqual(marked, declared)
        self.assertGreater(unmarked, 100, "premise: options that are not pending were read, and carry no key")


class ParcelEvidenceHeaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from company.models import Company, Establishment

        cls.company = Company.objects.create(name="Regrade Co")
        cls.establishment = Establishment.objects.create(name="Regrade Farm", company=cls.company, state="WA")

    def _parcel(self, name, answers):
        from product.models import Parcel

        return Parcel.objects.create(
            name=name,
            establishment=self.establishment,
            area=4.0,
            apn="000000-00002",
            date_began_managing=date(2011, 3, 1),
            application_answers={"currently_certified": "no", "livestock_present": "none", **answers},
        )

    def test_the_affidavit_label_states_the_missing_copy_not_a_missing_signature(self):
        from certifications.services.osp_module_pdf import EVIDENCE_LABELS

        label = EVIDENCE_LABELS["affidavit_document"]
        self.assertIn("no signed copy attached", label)
        self.assertNotIn("not signed", label)

    def test_an_unaccounted_window_is_missing_evidence(self):
        from certifications.services.parcel_land_history import coverage, prior_manager_rows
        from product.services.parcel_application_status import parcel_evidence_status

        parcel = self._parcel("No declaration", {})
        self.assertIs(
            coverage(parcel, prior_manager_rows(parcel)).complete,
            False,
            "premise: no declaration leaves the operation's own period unaccounted",
        )
        status = parcel_evidence_status(parcel)
        self.assertIn("land_history_window", status["missing"])
        self.assertTrue(status["detail"]["land_history_gaps"])

    def test_a_declared_window_is_not_missing_evidence(self):
        from certifications.services.parcel_land_history import coverage, prior_manager_rows
        from product.services.parcel_application_status import parcel_evidence_status

        parcel = self._parcel("Declared", {"no_inputs_within_tenure": True})
        self.assertIs(coverage(parcel, prior_manager_rows(parcel)).complete, True, "premise: the declaration covers it")
        self.assertNotIn("land_history_window", parcel_evidence_status(parcel)["missing"])

    def test_the_label_exists_for_the_new_key(self):
        from certifications.services.osp_module_pdf import EVIDENCE_LABELS

        self.assertIn("36-month window", EVIDENCE_LABELS["land_history_window"])


class PassedHarvestDateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from company.models import Company, Establishment
        from product.models import Parcel

        company = Company.objects.create(name="Harvest Co")
        establishment = Establishment.objects.create(name="Harvest Farm", company=company, state="WA")
        cls.parcel = Parcel.objects.create(name="Block 9", establishment=establishment, area=4.0)
        cls.parcel.planned_crops.create(
            crop="Apples", block_name="9", expected_harvest=date.today() - timedelta(days=60), acres=5
        )
        cls.parcel.planned_crops.create(crop="Pears", expected_harvest=date.today() + timedelta(days=200), acres=4)

    def test_a_passed_date_is_marked_and_named(self):
        from certifications.services.parcel_application_lines import planned_crop_lines, planned_crop_table

        _header, _widths, rows = planned_crop_table(self.parcel)
        cells = [" ".join(cell[0] for cell in row[0]) for row in rows]
        self.assertEqual(len(cells), 2, "premise: both crops reach the table")
        self.assertIn("(passed)", cells[0])
        self.assertNotIn("(passed)", cells[1])
        lines = " ".join(planned_crop_lines(self.parcel, {}))
        self.assertIn("Expected harvest dates already passed: Apples (9).", lines)
        self.assertNotIn("[REVIEW] Expected harvest", lines)
        self.assertNotIn("Pears", lines.split("already passed:")[1])


class RenewalRowStandingTests(SimpleTestCase):
    def test_a_pending_renewal_row_is_stated_not_unanswered(self):
        from certifications.services.packet_coverage import plan_standing

        register_words = "answered in this packet"
        self.assertEqual(plan_standing(None, register_words), register_words, "premise: no state keeps the words")
        self.assertEqual(
            plan_standing(RowState("1", "unanswered"), register_words), "not yet answered in this plan (unanswered)"
        )
        self.assertEqual(
            plan_standing(RowState("1", "pending", "Not known yet"), register_words),
            "answered in this plan as not yet known",
        )
        self.assertEqual(plan_standing(RowState("1", "answered"), register_words), register_words)


class ReviewOfBack507Tests(TestCase):
    """What the review of back #507 found: a missing document counted twice, five status reads per parcel, open
    renewal rows still worded as answered, a pending answer the index did not point at, and CCOF G6.4's all-organic
    condition."""

    @classmethod
    def setUpTestData(cls):
        from company.models import Company, Establishment

        cls.company = Company.objects.create(name="Review Co")
        cls.establishment = Establishment.objects.create(name="Review Farm", company=cls.company, state="WA")

    def test_a_certified_parcel_counts_its_window_once(self):
        from certifications.services.parcel_land_history import coverage, prior_manager_rows
        from product.models import Parcel
        from product.services.parcel_application_status import parcel_evidence_status

        parcel = Parcel.objects.create(
            name="Certified block",
            establishment=self.establishment,
            area=4.0,
            date_began_managing=date(2025, 3, 1),
            application_answers={"currently_certified": "yes", "livestock_present": "none"},
        )
        self.assertIs(coverage(parcel, prior_manager_rows(parcel)).complete, False, "premise: the window has a gap")
        self.assertNotIn("land_history_window", parcel_evidence_status(parcel)["missing"])

    def test_the_parcel_serializer_reads_the_status_once(self):
        from unittest import mock

        from product.models import Parcel
        from product.serializers import RetrieveParcelSerializer
        from product.services import parcel_application_status as service

        parcel = Parcel.objects.create(name="Once", establishment=self.establishment, area=4.0)
        with mock.patch.object(service, "parcel_application_status", wraps=service.parcel_application_status) as spy:
            data = RetrieveParcelSerializer(parcel).data
        self.assertIn("evidence_missing", data, "premise: the evidence fields are serialized")
        self.assertEqual(spy.call_count, 1)

    def test_every_open_renewal_row_reads_open(self):
        from certifications.services.packet_coverage import plan_standing

        self.assertEqual(
            plan_standing(RowState("1", "attachment_missing", "Upload x"), "answered in this packet"),
            "open in this plan: attachment not uploaded",
        )

    def test_the_index_points_at_a_pending_answer(self):
        from unittest import mock

        from certifications.services import question_index

        state = RowState(
            "D3",
            "pending",
            "Not yet confirmed with the district",
            parts=(("g4_2_natural_resources.irrigation_district_additives", "", "pending", "Not yet confirmed"),),
        )
        with mock.patch.object(question_index, "_question_locations", return_value=["G4_2 p. 2"]) as where:
            row = question_index.index_row(state, object(), None, None, {})
        self.assertEqual(where.call_count, 1)
        self.assertEqual(row.locations, ["G4_2 p. 2"])
        self.assertEqual([p.state for p in row.open_parts], ["pending"], "still listed open")

    def test_ccof_g6_4_names_its_all_organic_condition(self):
        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_pdf import g6_4_all_organic_lines

        def plan(certifier, split):
            return OrganicSystemPlan.objects.create(
                establishment=self.establishment,
                version_number=OrganicSystemPlan.objects.count() + 1,
                status="draft",
                certifier_name=certifier,
                module_responses={
                    "schema_version": 1,
                    "parcel_modules": {},
                    "modules": {"g6_0_production": {"answers": {"split_operation": {"value": split}}}},
                },
            )

        ccof = "CCOF Certification Services, LLC"
        self.assertEqual(g6_4_all_organic_lines(plan(ccof, False)), [], "premise: an all-organic operation")
        self.assertEqual(g6_4_all_organic_lines(plan("Washington State Department of Agriculture", True)), [])
        lines = g6_4_all_organic_lines(plan(ccof, True))
        self.assertEqual(len(lines), 1)
        self.assertIn("all-organic operation", lines[0])

    def test_the_g6_4_page_prints_it_under_the_disqualifiers(self):
        import io

        from pdfminer.high_level import extract_text

        from certifications.models import OrganicSystemPlan
        from certifications.services.osp_module_pdf import generate_module_pdf

        answered = {"value": ["none"]}
        osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name="CCOF Certification Services, LLC",
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "g6_0_production": {"answers": {"split_operation": {"value": True}}},
                    "g6_4_handling": {
                        "answers": {
                            "handling_activities": {"value": ["washing"]},
                            "simple_handling_disqualifiers": answered,
                        }
                    },
                },
            },
        )
        page = " ".join(extract_text(io.BytesIO(generate_module_pdf(osp, "g6_4_handling"))).split())
        self.assertIn("Does any of this apply to your on-farm handling?", page, "premise: the question prints")
        self.assertIn("is for an all-organic operation handling only its own organic product", page)

    def test_a_partial_row_keeps_the_registers_words(self):
        from certifications.services.packet_coverage import plan_standing

        words = "answered in part in this packet"
        self.assertEqual(plan_standing(RowState("1", "partial"), words), words)
