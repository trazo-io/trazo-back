"""Operation profile, B. Certification history and C. What happened (2026-11-09).

CCOF Certification Contract D5 to D6 and OTCO O1 D-1, D-1D, D-1E, D-2 to D-7 ask whether the operation, or anyone
responsibly connected to it, was ever certified, suspended, revoked, surrendered or withdrew with noncompliances
outstanding, or was denied; a yes asks for the letters and the corrective actions.

What these tests hold:
  1. Suspension, revocation, surrender and outstanding noncompliances are asked only of an operation that was
     certified. Denial and withdrawal are asked of every operation: an application can be denied before any
     certificate exists.
  2. Page C opens on ANY single adverse yes, and on none of the no answers.
  3. Every question is optional, so a completed Operation profile stays complete the day this ships.
  4. The operation profile PDF prints the answers, and an unanswered question as "Not answered (optional).",
     never as "No".
"""

import io

from django.test import TestCase

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import progress, visible_pages, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment

MODULE = MODULES_BY_KEY["certification_contract"]

ADVERSE = (
    "history_suspended",
    "history_revoked",
    "history_surrendered_outstanding",
    "history_outstanding_noncompliances",
    "history_denied",
    "history_withdrew_outstanding",
)
ONLY_IF_CERTIFIED = (
    "history_prior_agents",
    "history_suspended",
    "history_revoked",
    "history_surrendered_outstanding",
    "history_outstanding_noncompliances",
)
ALL_HISTORY_KEYS = tuple(
    q.key
    for page in MODULE.pages
    if page.key in ("b_certification_history", "c_adverse_history")
    for q in page.questions
)


def _visible_keys(answers):
    return {q.key for _page, q in visible_questions(MODULE, answers)}


def _page_keys(answers):
    return {page.key for page in visible_pages(MODULE, answers)}


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


class WhoIsAskedWhatTests(TestCase):
    def test_suspension_questions_wait_for_ever_certified(self):
        for answers in ({}, {"history_ever_certified": False}):
            with self.subTest(answers=answers):
                visible = _visible_keys(answers)
                for key in ONLY_IF_CERTIFIED:
                    self.assertNotIn(key, visible)
        visible = _visible_keys({"history_ever_certified": True})
        for key in ONLY_IF_CERTIFIED:
            self.assertIn(key, visible)

    def test_denial_and_withdrawal_are_asked_of_every_operation(self):
        for answers in ({}, {"history_ever_certified": False}, {"history_ever_certified": True}):
            with self.subTest(answers=answers):
                visible = _visible_keys(answers)
                self.assertIn("history_denied", visible)
                self.assertIn("history_withdrew_outstanding", visible)


class WhatHappenedOpensOnAnyYesTests(TestCase):
    def test_each_adverse_yes_alone_opens_page_c(self):
        for key in ADVERSE:
            with self.subTest(yes=key):
                answers = {"history_ever_certified": True, key: True}
                self.assertIn("c_adverse_history", _page_keys(answers))
                visible = _visible_keys(answers)
                self.assertIn("history_adverse_explanation", visible)
                self.assertIn("history_letters_upload", visible)

    def test_no_answers_keep_page_c_closed(self):
        answers = {"history_ever_certified": True, **{key: False for key in ADVERSE}}
        self.assertNotIn("c_adverse_history", _page_keys(answers))
        self.assertNotIn("c_adverse_history", _page_keys({}))

    def test_a_yes_hidden_behind_never_certified_does_not_open_page_c(self):
        """A stale "suspended: yes" left behind after switching to "never certified" is not shown, so it
        must not open page C either."""
        answers = {"history_ever_certified": False, "history_suspended": True}
        self.assertNotIn("c_adverse_history", _page_keys(answers))

    def test_the_affirmations_follow_their_own_event(self):
        suspended = _visible_keys({"history_ever_certified": True, "history_suspended": True})
        self.assertIn("history_not_sold_since_suspension", suspended)
        self.assertIn("history_currently_suspended", suspended)
        self.assertNotIn("history_not_sold_since_revocation", suspended)
        self.assertNotIn("history_request_reinstatement", suspended)

        revoked = _visible_keys({"history_ever_certified": True, "history_revoked": True})
        self.assertIn("history_not_sold_since_revocation", revoked)
        self.assertNotIn("history_not_sold_since_suspension", revoked)

    def test_reinstatement_is_requested_only_by_an_operation_suspended_today(self):
        base = {"history_ever_certified": True, "history_suspended": True}
        self.assertNotIn("history_request_reinstatement", _visible_keys({**base, "history_currently_suspended": False}))
        self.assertIn("history_request_reinstatement", _visible_keys({**base, "history_currently_suspended": True}))


class OptionalQuestionsTests(TestCase):
    def test_every_history_question_is_optional(self):
        self.assertTrue(ALL_HISTORY_KEYS)
        for page in MODULE.pages:
            for q in page.questions:
                if q.key in ALL_HISTORY_KEYS:
                    with self.subTest(question=q.key):
                        self.assertFalse(q.required)

    def test_a_completed_profile_stays_complete(self):
        answers = {"contract_notes": "Calapooia Bend Farm LLC", "contract_scopes": ["crops"]}
        self.assertEqual(progress(MODULE, answers)["missing"], [])
        everything_yes = {**answers, "history_ever_certified": True, **{key: True for key in ADVERSE}}
        self.assertEqual(progress(MODULE, everything_yes)["missing"], [])


class OperationProfilePdfTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="History Farm")
        self.establishment = Establishment.objects.create(name="History Ranch", company=company, state="OR")

    def _pdf(self, answers, version=1):
        osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=version,
            status="draft",
            module_responses={
                "schema_version": 1,
                "modules": {
                    "certification_contract": {
                        "answers": {key: {"value": value} for key, value in answers.items()},
                        "definition_version": "2026.11.28",
                    }
                },
            },
        )
        return " ".join(_pdf_text(generate_module_pdf(osp, "certification_contract")).split())

    def test_answers_print_on_both_pages(self):
        text = self._pdf(
            {
                "history_ever_certified": True,
                "history_prior_agents": "Oregon Tilth, March 2015 to June 2021",
                "history_suspended": True,
                "history_adverse_explanation": "Suspended in 2019 for a missing buffer; buffer planted 2020.",
                "history_not_sold_since_suspension": True,
            }
        )
        self.assertIn("B. Certification history", text)
        self.assertIn("Oregon Tilth, March 2015 to June 2021", text)
        self.assertIn("C. What happened", text)
        self.assertIn("Suspended in 2019 for a missing buffer; buffer planted 2020.", text)

    def test_an_unanswered_question_is_not_printed_as_no(self):
        text = self._pdf({"history_ever_certified": True})
        page_b = text[text.index("B. Certification history") : text.index("C. What happened")]
        self.assertIn("Not answered (optional).", page_b)
        self.assertNotIn(": No", page_b)
        # Page C is closed, and says it is waiting on an answer that could still open it.
        self.assertNotIn("For each yes", text)
        self.assertIn("C. What happened Not shown until", text)

    def test_a_never_certified_operation_is_not_told_to_answer_the_suspension_question(self):
        """The suspension question is hidden for a never-certified operation, so page C must not wait on it."""
        text = self._pdf(
            {"history_ever_certified": False, "history_denied": False, "history_withdrew_outstanding": False}
        )
        page_c = text[text.index("C. What happened") :]
        self.assertNotIn("suspended", page_c.split("Operation profile ·")[0])
        self.assertIn("C. What happened Does not apply", text)
