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
