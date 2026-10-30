"""A module PDF names the questions it has not answered, and the cover names every document.

WHY THIS EXISTS
---------------
Read back from the production specimen packet on 2026-10-29:

  * the module PDF printed answered questions only, so G6.1 read as complete while document 04
    listed "Harvest & Transport" as a section still to finish. For an agent Trazo holds no question
    register for (the specimen's, and any WFCF or OCI grower's), 06 lists no rows either, so nothing
    in the packet said which question was open;
  * the N/A stamp printed the raw user id and ISO timestamp: "attested by 163 on
    2026-08-21T11:28:47.145805+00:00";
  * the cover's contents skipped 02s and 06, the two pages that say where each answer is.
"""

import io
import zipfile
from datetime import date

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import Certification, OrganicSystemPlan
from certifications.services.osp_module_pdf import _packet_cover_pdf, generate_module_pdf, generate_osp_packet
from company.models import Company, Establishment
from users.models import User

AT = "2026-08-21T11:28:47.145805+00:00"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Plan(TestCase):
    certifier = "Cascadia Organic Certifiers"

    def setUp(self):
        self.user = User.objects.create_user(
            email="open-questions@test.com", password="x", first_name="Laurel", last_name="Brandt"
        )
        company = Company.objects.create(name="Brandt Family Farms LLC")
        self.est = Establishment.objects.create(name="Open Questions Farm", company=company, state="OR")
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="X-1",
            certifier_name=self.certifier,
            effective_date=date(2020, 1, 1),
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            created_by=self.user,
            certifier_name=self.certifier,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {
                    "g6_1_harvest_transport": {
                        "status": "in_progress",
                        "answers": {
                            "who_harvests": {"at": AT, "value": ["own_crew"]},
                            "who_transports": {"at": AT, "value": ["commercial_carrier"]},
                        },
                    },
                    "w2_0_wild_crop": {
                        "status": "not_applicable",
                        "not_applicable": True,
                        "na_attestation": {"by": self.user.pk, "at": AT},
                        "answers": {},
                    },
                },
            },
        )


class ModulePdfNamesOpenQuestionsTests(_Plan):
    def test_an_unanswered_required_question_is_named_as_not_yet_answered(self):
        text = _text(generate_module_pdf(self.osp, "g6_1_harvest_transport"))
        self.assertIn("Is your organic crop handled off the farm by another operation? Not yet answered.", text)

    def test_unanswered_optional_questions_are_listed_under_their_own_heading(self):
        text = _text(generate_module_pdf(self.osp, "g6_1_harvest_transport"))
        # In place, under its own page, so no page heading goes missing (production specimen packet,
        # 2026-10-29: a list at the end left section letters skipped and a heading orphaned).
        self.assertIn("How is the crop harvested? Check all that apply. Not answered (optional).", text)

    def test_an_answered_question_is_not_listed_as_open(self):
        text = _text(generate_module_pdf(self.osp, "g6_1_harvest_transport"))
        self.assertIn("Our own crew", text)
        self.assertNotIn("Who harvests this crop? Check all that apply. Not yet answered.", text)

    def test_a_module_with_no_answers_says_so_before_naming_its_open_questions(self):
        # Review of back #249: the summary line used to follow the list it summarises.
        text = _text(generate_module_pdf(self.osp, "g4_0_rotation_soil"))
        self.assertEqual(text.count("No answers recorded for this module yet."), 1)
        self.assertLess(text.index("No answers recorded for this module yet."), text.index("Not yet answered."))

    def test_inside_a_packet_an_upload_with_no_file_is_named(self):
        # Review of back #249: upload questions never reached the open-question branch.
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))
        g2 = _text(packet.read("modules/G2_0.pdf"))
        self.assertIn("Attach a written fraud prevention plan, if you keep one separately No file attached (optional).", g2)
        g8 = _text(packet.read("modules/G8_0.pdf"))
        self.assertIn("Generated in this packet as 05-audit-trail-exhibit.pdf", g8)
        self.assertNotIn("Sample audit trail exhibit No file attached", g8)

    def test_a_module_pdf_downloaded_alone_says_nothing_about_files(self):
        # Outside a packet build nothing is shipped, so no file can be said to be missing.
        self.assertNotIn("No file attached", _text(generate_module_pdf(self.osp, "g2_0_fraud_prevention")))

    def test_a_page_that_does_not_apply_keeps_its_heading_and_says_why(self):
        # G3.0 printed C then E: page D (seed treatments) was hidden by the answer and dropped silently.
        self.osp.module_responses["modules"]["g3_0_seeds"] = {
            "status": "in_progress",
            "answers": {
                "seeds_used": {"at": AT, "value": ["organic_untreated"]},
                "planting_stock_used": {"at": AT, "value": ["organic"]},
            },
        }
        self.osp.save(update_fields=["module_responses"])
        text = _text(generate_module_pdf(self.osp, "g3_0_seeds"))
        for heading in ("B. Commercial availability", "C. Excluded methods (GMO)", "D. Seed treatments"):
            self.assertIn(heading, text)
        self.assertLess(text.index("C. Excluded methods"), text.index("D. Seed treatments"))
        self.assertLess(text.index("D. Seed treatments"), text.index("E. Grafting"))
        self.assertIn("Does not apply: asked only when the answer to “", text)

    def test_a_page_hidden_by_an_open_question_says_it_is_not_shown_yet(self):
        text = _text(generate_module_pdf(self.osp, "g3_0_seeds"))
        self.assertIn("Not shown until “", text)
        self.assertNotIn("Does not apply: asked only when", text)

    def test_the_na_stamp_names_the_attester_and_the_day(self):
        text = _text(generate_module_pdf(self.osp, "w2_0_wild_crop"))
        self.assertIn("attested by Laurel Brandt on 2026-08-21", text)
        self.assertNotIn(f"attested by {self.user.pk} ", text)
        self.assertNotIn("11:28:47", text)

    def test_an_na_stamp_whose_account_is_gone_says_the_operator(self):
        modules = self.osp.module_responses["modules"]
        modules["w2_0_wild_crop"]["na_attestation"]["by"] = self.user.pk + 9999
        self.osp.save(update_fields=["module_responses"])
        text = _text(generate_module_pdf(self.osp, "w2_0_wild_crop"))
        self.assertIn("attested by the operator on 2026-08-21", text)


class CoverContentsNameEveryDocumentTests(_Plan):
    def test_an_unregistered_agent_is_told_06_lists_no_questions_and_where_open_ones_are(self):
        text = _text(_packet_cover_pdf(self.osp))
        self.assertIn("02s. Renewal status", text)
        self.assertIn("06. Question index: Trazo holds no question register for this certifying agent", text)
        self.assertIn("each module PDF names its own unanswered questions", text)


class CoverContentsForARegisteredAgentTests(_Plan):
    certifier = "Oregon Tilth Certified Organic"

    def test_a_registered_agent_is_told_06_covers_every_question_on_its_forms(self):
        text = _text(_packet_cover_pdf(self.osp))
        self.assertIn("06. Question index: every question on the certifying agent's forms", text)
        self.assertIn("renewal forms, question by question", text)
        self.assertNotIn("holds no question register", text)
