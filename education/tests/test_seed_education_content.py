"""Guards for the FAQ seeder — the only education content the product serves.

Fails on the old behaviour in four ways:
- the pre-pivot course/lesson catalogue survived in the DB (it taught the
  retired transparency score and the withdrawn blockchain add-on);
- the renewal-deadlines FAQ said "MOSA: early February" (it is April 1) and
  never named WSDA, the certifier for most of Washington's organic tree fruit;
- the COG Pro FAQ cited 7 CFR 205.103(b)(4) for the 5-year retention duty
  (it is (b)(3));
- FAQ copy claimed the packet and OSP modules "draft themselves"
  (§ 205.201(a): the producer authors the plan; Trazo assembles and suggests).
"""

from django.core.management import call_command
from django.test import TestCase

from education.models import EducationCategory, EducationCourse, EducationLesson, FarmerQuestionAnswer


class SeedEducationContentTests(TestCase):
    def _seed(self, **kwargs):
        call_command("seed_education_content", verbosity=0, **kwargs)

    def test_purges_retired_course_catalogue(self):
        category = EducationCategory.objects.create(
            name="Getting Started with Transparency",
            category_type="getting_started",
            description="pre-pivot copy",
            icon="FaRocket",
            order=1,
        )
        course = EducationCourse.objects.create(
            category=category,
            title="Transparency Score Mastery",
            description="Earn 0-100% transparency score",
            difficulty="beginner",
            estimated_duration=10,
        )
        EducationLesson.objects.create(
            course=course,
            title="Blockchain add-on",
            content_type="text",
            content="Consider blockchain verification add-on",
            duration=5,
            order=1,
        )

        self._seed()

        self.assertEqual(EducationCourse.objects.count(), 0)
        self.assertEqual(EducationLesson.objects.count(), 0)
        self.assertEqual(EducationCategory.objects.count(), 0)
        # ...while the FAQ content it also seeds is present.
        self.assertGreater(FarmerQuestionAnswer.objects.count(), 0)

    def test_renewal_deadlines_are_current(self):
        self._seed()
        faq = FarmerQuestionAnswer.objects.get(question="What deadlines matter for renewal season?")
        self.assertIn("WSDA", faq.answer)
        self.assertIn("March 1", faq.answer)
        self.assertIn("**MOSA**: April 1", faq.answer)
        self.assertIn("OEFFA", faq.answer)
        self.assertIn("NOFA-NY", faq.answer)
        self.assertNotIn("early February", faq.answer)

    def test_retention_cite_is_b4(self):
        """Five-year retention is 7 CFR 205.103(b)(4) since the SOE rule (88 FR 3621, 2023)
        inserted today's (b)(3), audit trail and labeling category. This test pinned (b)(3) until
        2026-09-30, the pre-2023 numbering."""
        self._seed()
        migrating = FarmerQuestionAnswer.objects.get(question="I'm coming from COG Pro — how do I move my records?")
        self.assertIn("205.103(b)(4)", migrating.answer)
        for faq in FarmerQuestionAnswer.objects.all():
            self.assertNotIn("205.103(b)(3)", faq.answer, faq.question)

    def test_plan_review_faq_exists_and_never_verdicts(self):
        self._seed()
        faq = FarmerQuestionAnswer.objects.get(question="What is the review list under my Organic System Plan?")
        self.assertIn("never a verdict", faq.answer)
        self.assertIn("never blocks the Submit button", faq.answer)
        self.assertTrue(faq.is_featured)

    def test_no_retired_claims_in_any_faq(self):
        self._seed()
        for faq in FarmerQuestionAnswer.objects.all():
            text = faq.answer.lower()
            self.assertNotIn("transparency score", text, faq.question)
            self.assertNotIn("blockchain", text, faq.question)
            # § 205.201(a): Trazo assembles/suggests; it never drafts the plan.
            self.assertNotIn("draft themselves", text, faq.question)
            self.assertNotIn("drafts your", text, faq.question)
            # Sales are a transaction against a finished lot, not an activity tile.
            self.assertNotIn("sales & compliance", text, faq.question)

    def test_refresh_rewrites_existing_rows(self):
        self._seed()
        faq = FarmerQuestionAnswer.objects.get(question="What deadlines matter for renewal season?")
        FarmerQuestionAnswer.objects.filter(pk=faq.pk).update(answer="stale copy")

        self._seed()  # create-only: must NOT touch the edited row
        faq.refresh_from_db()
        self.assertEqual(faq.answer, "stale copy")

        self._seed(refresh=True)
        faq.refresh_from_db()
        self.assertIn("WSDA", faq.answer)

    def test_idempotent(self):
        self._seed()
        first = FarmerQuestionAnswer.objects.count()
        self._seed()
        self.assertEqual(FarmerQuestionAnswer.objects.count(), first)
