"""
The readiness row "National List conditions (§ 205.601(j)(6), (j)(7); § 205.602(c))": what a season's
records show about the National List conditions a record CAN show.

  * § 205.602(c): calcium chloride "except as a foliar spray". Foliar, air-blast and aerial are
    foliar; broadcast, banding, drip, injection and soil incorporation are not; a record with no
    method, or one that can be either (ground spray, chemigation), is its own count, never guessed.
  * § 205.601(j)(7): a micronutrient needs a soil or tissue result on file on or before its date,
    carrying that nutrient's value where Trazo records one; a water or compost result is no basis.
    A purpose of weed management or plant growth regulation is counted against "not to be used as
    a defoliant, herbicide, or desiccant".
  * § 205.601(j)(6): magnesium sulfate needs a SOIL result; a leaf result does not count.

Counts only. The row says "a result on file", never "deficiency documented", and the chemical log's
micronutrient table counts exactly what the row counts.
"""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from certifications.models import NationalListSubstance
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, SoilManagementEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel

LABEL = "National List conditions (§ 205.601(j)(6), (j)(7); § 205.602(c))"


class _Season(TestCase):
    def setUp(self):
        call_command("seed_national_list", stdout=StringIO(), stderr=StringIO())
        company = Company.objects.create(name="Wenatchee Heights Orchards LLC")
        est = Establishment.objects.create(name="Wenatchee Heights", company=company, state="WA")
        parcel = Parcel.objects.create(name="Honeycrisp Block", establishment=est, area=12.0)
        self.history = History.objects.create(name="Honeycrisp 2026", start_date=timezone.now(), parcel=parcel)
        self.now = timezone.now()

    def _chem(self, name, when=None, substance=None, **fields):
        with self.captureOnCommitCallbacks(execute=True):
            event = ChemicalEvent.objects.create(
                history=self.history,
                date=when or self.now,
                description="application",
                type="FE",
                commercial_name=name,
                **fields,
            )
        if substance:
            # The operator's own confirmation of the listing: a confirmed basis, as the wizard saves it.
            ChemicalEvent.objects.filter(pk=event.pk).update(
                national_list_substance=NationalListSubstance.objects.get(substance_name=substance),
                national_list_basis="operator",
            )
        return event

    def _calcium_chloride(self, method):
        return self._chem(
            "Calcium chloride flakes",
            substance="Calcium chloride (brine process)",
            application_method_structured=method,
        )

    def _lab(self, matrix, days_before, type_code="LA", **results):
        return SoilManagementEvent.objects.create(
            history=self.history,
            type=type_code,
            date=self.now - timedelta(days=days_before),
            description="sample",
            sample_matrix=matrix,
            test_results=results or {"report_date": "2026-06-01"},
        )

    def _row(self):
        rows = AuditExportService(self.history, certification_type="organic").compliance_snapshot_rows()
        matching = [r for r in rows if r["label"] == LABEL]
        self.assertEqual(len(matching), 1, [r["label"] for r in rows])
        return matching[0]


class CalciumChlorideIsCountedByMethod(_Season):
    def test_air_blast_is_foliar_drip_is_not_and_no_method_is_its_own_count(self):
        self._calcium_chloride("air_blast")
        self._calcium_chloride("drip")
        self._calcium_chloride(None)
        self._calcium_chloride("chemigation")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["params"]["calcium_soil"], 1)
        self.assertEqual(row["params"]["calcium_method_unknown"], 2)
        self.assertIn(
            "1 calcium chloride record(s) applied to the soil (§ 205.602(c) allows a foliar spray only)", row["detail"]
        )
        self.assertIn("2 calcium chloride record(s) whose method does not show a foliar spray", row["detail"])
        self.assertEqual(row["detail_code"], "national_list_conditions.records")
        self.assertEqual(row["row_key"], "national_list_conditions")
        self.assertEqual(row["section_hint"], "Input Material Application Records section")

    def test_every_foliar_method_reads_as_the_record_on_file(self):
        for method in ("foliar", "air_blast", "aerial"):
            self._calcium_chloride(method)
        row = self._row()
        self.assertEqual(row["status"], "PASS", row["detail"])
        self.assertEqual(row["detail"], "3 calcium chloride application(s), each by a foliar method")

    def test_a_substring_suggestion_is_not_counted(self):
        """Only a confirmed listing classifies: a name that merely contains "calcium chloride" does not."""
        self._chem("Calcium chloride flakes", application_method_structured="drip")
        self.assertEqual(self._row()["status"], "NA")


class MicronutrientsNeedAResultOnFileBeforeTheDate(_Season):
    def test_a_prior_leaf_zinc_result_is_on_file_and_a_later_one_is_not(self):
        self._lab("leaf", 30, zinc_ppm=0.8)
        self._chem("Zinc sulfate 36%", micronutrient_type="zinc")
        self.assertEqual(self._row()["status"], "PASS")
        self._chem("Zinc sulfate 36%", when=self.now - timedelta(days=60), micronutrient_type="zinc")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["params"]["micronutrient_no_result"], 1)
        self.assertIn(
            "1 micronutrient application(s) with no soil or tissue result on file on or before the date", row["detail"]
        )

    def test_a_zinc_value_on_an_irrigation_water_test_is_no_basis(self):
        self._lab("water", 30, zinc_ppm=0.8)
        self._chem("Zinc sulfate 36%", micronutrient_type="zinc")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW", row["detail"])
        self.assertEqual(row["params"]["micronutrient_no_result"], 1)

    def test_a_result_logged_later_the_same_day_is_on_file(self):
        """ "On or before the date" is a day; records carry a time of day (review of back #312)."""
        morning = timezone.make_aware(timezone.datetime(2026, 6, 10, 8, 0))
        SoilManagementEvent.objects.create(
            history=self.history,
            type="LA",
            date=morning + timedelta(hours=8),
            description="leaf sample, afternoon",
            sample_matrix="leaf",
            test_results={"zinc_ppm": 0.8},
        )
        self._chem("Zinc sulfate 36%", when=morning, micronutrient_type="zinc")
        row = self._row()
        self.assertEqual(row["status"], "PASS", row["detail"])

    def test_an_unrelated_test_is_no_support_for_a_nutrient_trazo_records_no_value_for(self):
        """Review of back #312: a soil pH test read as support for a copper feed, and the row said PASS."""
        self._lab(None, 30, type_code="ST", ph=6.4)
        self._chem("Copper sulfate fertilizer", micronutrient_type="copper")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW", row["detail"])
        self.assertEqual(row["params"]["micronutrient_no_value"], 1)
        self.assertEqual(row["params"]["micronutrient_no_result"], 0)
        self.assertIn("records no value for the nutrient applied", row["detail"])
        from history.tests.test_lab_analysis_and_micronutrients import MicronutrientPdfTests

        text = MicronutrientPdfTests._chemicals_text(self)
        self.assertIn("REVIEW: result on file (soil,", text)
        self.assertNotIn("are supported by a prior laboratory result", text)

    def test_weed_management_as_the_purpose_is_counted_against_the_defoliant_clause(self):
        self._lab("leaf", 30, zinc_ppm=0.8)
        self._chem("Zinc sulfate 36%", micronutrient_type="zinc", application_purpose="weed_management")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["params"]["micronutrient_purpose"], 1)
        self.assertEqual(row["params"]["micronutrient_no_result"], 0)
        self.assertIn('"not to be used as a defoliant, herbicide, or desiccant"', row["detail"])

    def test_the_chemical_log_table_counts_what_the_row_counts(self):
        """One application with a result, one without, one fed as calcium (not (j)(7))."""
        from history.tests.test_lab_analysis_and_micronutrients import MicronutrientPdfTests

        self._lab("soil", 30, type_code="ST", zinc_ppm=0.8)
        self._chem("Zinc sulfate 36%", micronutrient_type="zinc")
        self._chem("Solubor", micronutrient_type="boron")
        self._chem("Gypsum", micronutrient_type="calcium")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW", row["detail"])
        self.assertEqual(row["params"]["micronutrient_no_result"], 1)
        text = MicronutrientPdfTests._chemicals_text(self)
        self.assertEqual(text.count("REVIEW — no prior lab result on file"), 1, text)
        self.assertIn("1 of 2 § 205.601(j)(7) micronutrient application(s) have no prior laboratory result", text)


class MagnesiumSulfateNeedsASoilResult(_Season):
    def test_a_leaf_result_alone_is_no_soil_result(self):
        self._lab("leaf", 30)
        self._chem("Epsom salt")
        row = self._row()
        self.assertEqual(row["status"], "REVIEW")
        self.assertEqual(row["params"]["magnesium_no_soil_result"], 1)
        self.assertIn(
            "1 magnesium sulfate application(s) with no soil result on file on or before the date", row["detail"]
        )

    def test_a_prior_soil_test_is_on_file(self):
        self._lab(None, 30, type_code="ST")
        self._chem("Epsom salt")
        row = self._row()
        self.assertEqual(row["status"], "PASS", row["detail"])
        self.assertIn("1 magnesium sulfate application(s), each with a soil result on file", row["detail"])


class NothingToCheck(_Season):
    def test_a_season_with_none_of_these_materials_is_not_applicable(self):
        self._chem("Kocide 3000", chemical_subtype="copper_fungicide")
        row = self._row()
        self.assertEqual(row["status"], "NA")
        self.assertIsNone(row["detail_code"])

    def test_no_line_says_a_deficiency_is_documented(self):
        self._lab("leaf", 30, zinc_ppm=0.8)
        self._chem("Zinc sulfate 36%", micronutrient_type="zinc")
        self._chem("Epsom salt")
        for row in (self._row(),):
            self.assertNotIn("deficiency documented", row["detail"].lower())
            self.assertNotIn("compliant", row["detail"].lower())
