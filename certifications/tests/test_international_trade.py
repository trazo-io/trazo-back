"""International trade across WSDA AGR 2121 §Q and OTCO C8 8.4-4 (content 2026.12.17).

What the registers held open:

* A farm importing seed for its own planting had no true box on G8.0's first question (seed is neither a
  product nor an ingredient), so the import questions never opened (§Q 1, 5), and the countries and
  standards of the seed were not asked (§Q 2, 3). The import documents kept per shipment lacked four of
  WSDA's six (§Q 4).
* A direct exporter was not asked its export packages or the documents that travel with each shipment
  (§Q 8, 9), nor how products meet the destination's equivalency arrangement (OTCO 8.4-4).
* Canada's critical variance was not asked: may crops reach Canada, is sodium nitrate used, and how are
  the two kept apart (§Q Critical Variances: Canada 1, 2, 2a). Sodium nitrate is § 205.602(h), now a class
  of `restricted_materials`, so a No the plan's list or the records contradict is printed and listed.
"""

import io
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import yaml

from certifications.models import NationalListSubstance, OrganicSystemPlan, WSDAMaterial
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.services.common_osp_records import EvidenceBundle
from certifications.services.international_trade_review import mined_nitrogen_records
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.osp_prefill import resolve_suggestions
from certifications.services.parcel_application_lines import operation_export_lines
from certifications.services.plan_review import plan_review
from certifications.services.restricted_materials import SODIUM_NITRATE, module_lines, substance_class, wsda_class
from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, SoilManagementEvent
from product.models import Parcel

G4 = MODULES_BY_KEY["g4_0_rotation_soil"]
G8 = MODULES_BY_KEY["g8_0_record_keeping"]
TRADE = "import_export_activity"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


def _question(module, key):
    return next(q for page in module.pages for q in page.questions if q.key == key)


def _visible(answers) -> set:
    return {q.key for _page, q in visible_questions(G8, answers)}


IMPORT_QUESTIONS = {
    "import_seed_countries",
    "import_seed_standards",
    "import_documentation",
    "import_integrity_verification",
    "port_integrity_measures",
    "import_export_records",
}
EXPORT_QUESTIONS = {"export_package_types", "export_shipment_documents", "equivalency_compliance_method"}


class TheQuestionsOpenWhereTheFormsAskThem(SimpleTestCase):
    def test_seed_imported_for_the_farm_opens_the_import_questions_and_no_export_ones(self):
        visible = _visible({TRADE: ["import_seed"]})
        self.assertEqual(IMPORT_QUESTIONS - visible, set())
        self.assertEqual(EXPORT_QUESTIONS & visible, set())

    def test_a_product_importer_is_not_asked_where_its_seed_comes_from(self):
        visible = _visible({TRADE: ["import"]})
        self.assertIn("import_documentation", visible)
        self.assertNotIn("import_seed_countries", visible)
        self.assertNotIn("import_seed_standards", visible)

    def test_canada_is_asked_of_every_answer_and_sodium_nitrate_only_where_crops_may_reach_it(self):
        self.assertIn("canada_export_possible", _visible({TRADE: ["none_no_known_export"]}))
        self.assertNotIn("canada_export_possible", _visible({}))
        self.assertNotIn("sodium_nitrate_used", _visible({TRADE: ["export"], "canada_export_possible": False}))
        answers = {TRADE: ["none_no_known_export"], "canada_export_possible": True, "sodium_nitrate_used": True}
        self.assertIn("sodium_nitrate_canada_separation", _visible(answers))
        self.assertIn("sodium_nitrate_canada_separation", missing_required(G8, answers))

    def test_new_questions_on_pages_already_answered_do_not_reopen_them(self):
        # A plan filed before 2026.12.17 has none of these, and must not read as incomplete for them.
        missing = set(missing_required(G8, {TRADE: ["export"], "export_destinations": "Canada"}))
        self.assertEqual(missing & (EXPORT_QUESTIONS | {"canada_export_possible"}), set())
        self.assertIn("export_certificate_types", missing)

    def test_a_direct_exporter_is_asked_packages_documents_and_the_arrangement_and_a_buyer_export_is_not(self):
        self.assertEqual(EXPORT_QUESTIONS - _visible({TRADE: ["export"]}), set())
        self.assertEqual(EXPORT_QUESTIONS & _visible({TRADE: ["indirect_export"]}), set())

    def test_the_import_documents_kept_name_wsda_q4s_list(self):
        offered = {o.value for o in _question(G8, "import_documentation").options}
        for value in (
            "nop_import_certificate",
            "bill_of_lading",
            "certificate_of_analysis",
            "invoice",
            "phytosanitary_certificate",
            "transaction_certificate",
            "other",
        ):
            self.assertIn(value, offered)


class _Orchard(TestCase):
    def setUp(self):
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())
        self.company = Company.objects.create(name="Okanogan Ridge Orchards LLC")
        self.est = Establishment.objects.create(name="Okanogan Ridge", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="Gala Block", establishment=self.est, area=10.0)
        self.history = Production.objects.create(name="Gala 2026", start_date=timezone.now(), parcel=self.parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _store(self, **answers):
        responses = {"schema_version": 1, "modules": {}}
        responses["modules"]["g8_0_record_keeping"] = {
            "answers": {k: {"at": "2026-11-17T10:00:00Z", "value": v} for k, v in answers.items()}
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _chem(self, name, **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=self.history,
                date=timezone.now(),
                description="application",
                type="FE",
                commercial_name=name,
                **fields,
            )

    def _list_sodium_nitrate(self):
        self.osp.approved_national_list_substances.add(
            NationalListSubstance.objects.get(substance_name="Sodium nitrate")
        )

    def _lines(self, key, value, module=G8):
        return module_lines(self.osp, module, _question(module, key), value, {key: value}, {})

    def _pdf(self):
        return _pdf_text(generate_module_pdf(self.osp, "g8_0_record_keeping"))

    def _finding(self):
        findings = {f.code: f for f in plan_review(self.osp, reference=timezone.now()).findings}
        return findings.get("international_trade_answers_disagree")

    def _details(self):
        finding = self._finding()
        self.assertIsNotNone(finding, "no international_trade_answers_disagree finding")
        return finding.details


class SodiumNitrateIsAClassOfItsOwn(_Orchard):
    def test_the_national_list_row_and_wsda_s_subtype_are_sodium_nitrate(self):
        self.assertEqual(
            substance_class(NationalListSubstance.objects.get(substance_name="Sodium nitrate")), SODIUM_NITRATE
        )
        andean = WSDAMaterial.objects.create(
            wsda_id="W-NA1",
            brand_name="Andean 14-0-9 Prilled",
            category="fertilizer-and-soil-amendment",
            subtype="Sodium Nitrate",
        )
        self.assertEqual(wsda_class(andean), SODIUM_NITRATE)

    def test_a_record_suggests_yes_and_no_record_suggests_nothing(self):
        self.assertNotIn("sodium_nitrate_used", resolve_suggestions(G8, self.est, osp=self.osp))
        self._chem("Sodium nitrate")
        suggestions = resolve_suggestions(G8, self.est, osp=self.osp)
        self.assertIn("sodium_nitrate_used", suggestions)
        suggestion = suggestions["sodium_nitrate_used"]
        self.assertIs(suggestion["value"], True)
        self.assertIn("1 record of sodium nitrate", suggestion["basis"])

    def test_a_mined_nitrogen_source_alone_suggests_nothing(self):
        self._chem("Andean 14-0-9", nitrogen_source="mined_natural")
        self.assertNotIn("sodium_nitrate_used", resolve_suggestions(G8, self.est, osp=self.osp))

    def test_a_yes_prints_the_rule_and_a_review_line_when_the_list_holds_none(self):
        lines = " ".join(self._lines("sodium_nitrate_used", True))
        self.assertIn('§ 205.602(h): "Sodium nitrate—unless use is restricted to no more than 20%', lines)
        self.assertIn("[REVIEW] This plan's materials list holds no material classified as sodium nitrate.", lines)

    def test_a_no_prints_the_plans_own_sodium_nitrate_and_the_records(self):
        self._list_sodium_nitrate()
        self._chem("Sodium nitrate")
        lines = " ".join(self._lines("sodium_nitrate_used", False))
        self.assertIn(
            "[REVIEW] This plan's materials list holds 1 material(s) classified as sodium nitrate: Sodium nitrate",
            lines,
        )
        self.assertIn("1 application(s) of products classified as sodium nitrate", lines)

    def test_a_no_to_field_calcium_chloride_is_not_contradicted_by_a_listed_dip(self):
        # The list may hold calcium chloride for a post-harvest dip while no field application is true.
        self.osp.approved_national_list_substances.add(
            NationalListSubstance.objects.get(substance_name="Calcium chloride (brine process)")
        )
        self.assertEqual(self._lines("applies_calcium_chloride", False, module=G4), [])


class TheModulePdfAndThePlanReview(_Orchard):
    def test_the_module_pdf_prints_every_new_answer(self):
        self._store(
            **{
                TRADE: ["export", "import_seed"],
                "export_destinations": "Canada, Taiwan",
                "export_package_types": ["wholesale_shipping"],
                "export_shipment_documents": ["bill_of_lading", "tm11"],
                "equivalency_compliance_method": ["certifier_review"],
                "canada_export_possible": True,
                "sodium_nitrate_used": True,
                "sodium_nitrate_canada_separation": "Only the Fuji block gets it; its lots carry NC.",
                "import_seed_countries": ["new_zealand"],
                "import_seed_standards": ["usda_nop"],
                "import_documentation": ["nop_import_certificate", "bill_of_lading"],
            }
        )
        text = self._pdf()
        for phrase in (
            "Wholesale shipping containers",
            "Bill of lading",
            "USDA TM-11 export certificate",
            "Products are submitted to our certifier for review under the arrangement before export",
            "or as an ingredient in a processed product? Yes",
            "Do you use sodium nitrate (Chilean nitrate) to produce organic crops? Yes",
            "Only the Fuji block gets it; its lots carry NC.",
            "New Zealand",
            "USDA organic regulations, 7 CFR Part 205",
            "A bill of lading is kept for each shipment",
            "[REVIEW] The plan states sodium nitrate is used and that crops or products may reach Canada",
        ):
            self.assertIn(phrase, text)

    def test_a_no_against_a_mined_nitrogen_record_prints_it_and_is_listed(self):
        self._chem("Andean 14-0-9", nitrogen_source="mined_natural")
        self._store(**{TRADE: ["indirect_export"], "canada_export_possible": True, "sodium_nitrate_used": False})
        self.assertIn(
            "[REVIEW] The records in Trazo show 1 fertilizer application(s) whose nitrogen source is recorded as mined "
            "or natural",
            self._pdf(),
        )
        finding = self._finding()
        self.assertIsNotNone(finding)
        self.assertEqual(finding.module_key, "g8_0_record_keeping")
        self.assertIn("Andean 14-0-9", " ".join(finding.details))

    def test_a_soil_amendment_sharing_its_id_does_not_hide_a_mined_nitrogen_record(self):
        # Review of back #471: soil and chemical records number their rows independently.
        mined = self._chem("Andean 14-0-9", nitrogen_source="mined_natural")
        SoilManagementEvent.objects.create(
            pk=mined.pk,
            history=self.history,
            type="OM",
            amendment_type="mineral",
            amendment_product_name="Sodium nitrate",
            date=timezone.now(),
        )
        self.assertEqual(
            [e.pk for e in mined_nitrogen_records(EvidenceBundle(self.est, osp=self.osp))],
            [mined.pk],
        )

    def test_a_no_against_the_plans_list_is_listed(self):
        self._list_sodium_nitrate()
        self._store(**{TRADE: ["export"], "canada_export_possible": True, "sodium_nitrate_used": False})
        self.assertEqual(
            self._details(),
            [
                "G8.0 answers that sodium nitrate is not used, and this plan's materials list holds Sodium nitrate "
                "(National List)."
            ],
        )

    def test_no_canada_beside_the_canada_attestation_disagrees(self):
        self._store(**{TRADE: ["export"], "export_certificate_types": ["canada"], "canada_export_possible": False})
        self.assertIn("The two answers disagree.", " ".join(self._details()))
        self.assertIn("[REVIEW] G8.0 answers that no crops or products are expected to reach Canada", self._pdf())

    def test_a_stored_no_under_a_closed_question_is_not_read(self):
        # Canada answered No hides the sodium nitrate question; its stored No says nothing.
        self._list_sodium_nitrate()
        self._store(**{TRADE: ["export"], "canada_export_possible": False, "sodium_nitrate_used": False})
        self.assertIsNone(self._finding())

    def test_the_parcel_page_prints_the_canada_answer(self):
        self._store(**{TRADE: ["indirect_export"], "canada_export_possible": True})
        self.assertIn(
            "Canada: the operation states its crops or products may be exported to Canada.",
            operation_export_lines(self.osp),
        )


class TheRegisterRowsAreClosed(SimpleTestCase):
    ROOT = Path(__file__).resolve().parents[2] / "documentation/compliance/certifiers"

    def _items(self, path):
        return yaml.safe_load((self.ROOT / path).read_text())["items"]

    def test_every_wsda_q_row_is_covered_and_cites_questions_that_exist(self):
        keys = {q.key for page in G8.pages for q in page.questions}
        for item in self._items("wsda/forms/2121-Q-international-trade.yaml"):
            self.assertEqual(item["status"], "covered", item["ref"])
            for cited in item["trazo"]["questions"]:
                self.assertIn(cited.split(".", 1)[1], keys, item["ref"])

    def test_otco_8_4_4_is_covered(self):
        row = next(i for i in self._items("otco/forms/C8-labeling-sales.yaml") if i["ref"] == "8.4-4")
        self.assertEqual(row["status"], "covered")
        self.assertIn("g8_0_record_keeping.equivalency_compliance_method", row["trazo"]["questions"])
