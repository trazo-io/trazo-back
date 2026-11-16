"""The lot number key, what else traces a sale to the field, and what container records show.

CCOF G8.0 B2: "describe the system as a Code / Signifies table (example: Lot Number 23123O10 — Code
23 / 123 / O / 10, Signifies Year 2023 / Julian harvest date / Organic / Parcel ID)".
OTCO C12 12.2-3: "Lot numbers · Field numbers or names · Julian date codes · Farm name (if the
operation is all organic with only one field) · Other (describe)".
WSDA AGR 2121 §N 4: storage and shipping records include "the certification status of the crop on
every record; the unique identifier displayed on the container; and the name of your certified
business".
"""

import io
from datetime import datetime
from datetime import timezone as dt_tz

from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.services.certifier_register import load_forms
from certifications.services.lot_code_key import key_rows, recorded_lot_ids
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from company.models import Company, Establishment
from history.models import Production
from product.models import Parcel

AT = "2026-11-07T12:00:00Z"
CCOF = "California Certified Organic Farmers (CCOF)"
OTCO = "Oregon Tilth Certified Organic (OTCO)"
WSDA = "Washington State Department of Agriculture (WSDA)"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class KeyRows(SimpleTestCase):
    def test_each_line_becomes_a_row(self):
        self.assertEqual(
            key_rows("26 = harvest year\nHFE = block (Home Field East)\n07: picking day"),
            [("26", "harvest year"), ("HFE", "block (Home Field East)"), ("07", "picking day")],
        )

    def test_a_spaced_dash_separates_but_a_hyphen_inside_a_code_does_not(self):
        self.assertEqual(
            key_rows("CBF-26 - farm and year\nHFE - block"), [("CBF-26", "farm and year"), ("HFE", "block")]
        )
        self.assertIsNone(key_rows("CBF-26-HFE"))

    def test_one_line_reads_as_a_table_only_with_an_equals_sign(self):
        self.assertEqual(key_rows("26 = harvest year"), [("26", "harvest year")])
        self.assertIsNone(key_rows("26: harvest year"))
        self.assertIsNone(key_rows("CBF-26 - farm and year"))

    def test_prose_with_an_incidental_colon_is_not_a_table(self):
        """Review of back #331: half a sentence printed under "Code"."""
        self.assertIsNone(key_rows("Lot codes are built like this: farm initials, crop year, block"))
        self.assertIsNone(key_rows("26 = year\nThe last part of the code is: the block name, written in capitals"))

    def test_bullets_and_blank_lines_are_ignored(self):
        self.assertEqual(key_rows("- 26 = year\n\n• O = organic"), [("26", "year"), ("O", "organic")])

    def test_one_line_that_does_not_split_keeps_the_whole_answer_as_prose(self):
        self.assertIsNone(key_rows("26 = year\nthe rest is the parcel"))

    def test_nothing_or_not_text_is_no_table(self):
        self.assertIsNone(key_rows(""))
        self.assertIsNone(key_rows(None))


class _Plan(TestCase):
    def plan(self, g8_0=None, g7_0=None, certifier=CCOF, g6_1=None):
        self.est = Establishment.objects.create(
            name="Key Farm", company=Company.objects.create(name="Key Farm LLC"), state="WA"
        )
        modules = {}
        for key, answers in (("g8_0_record_keeping", g8_0), ("g7_0_labeling", g7_0), ("g6_1_harvest_transport", g6_1)):
            if answers is not None:
                modules[key] = {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )

    def season(self, lot_id, finished):
        parcel, _ = Parcel.objects.get_or_create(name="Home Block", establishment=self.est, defaults={"area": 5.0})
        return Production.objects.create(
            name=f"Season {lot_id}",
            parcel=parcel,
            start_date=datetime(finished.year, 3, 1, tzinfo=dt_tz.utc),
            finish_date=finished,
            lot_id=lot_id,
        )

    def row(self, osp, agent, document_id, ref):
        # WSDA's sections share one document id (AGR 2121); they are told apart by their section code.
        form = next(f for f in load_forms(agent) if document_id in (f.document_id, f"AGR 2121 {f.code}"))
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class LotKeyOnTheModulePage(_Plan):
    def test_the_key_prints_as_a_code_signifies_table_beside_recorded_lots(self):
        osp = self.plan(
            g8_0={
                "lot_numbering": "own_system",
                "lot_code_key": "26 = harvest year\nHFE = block (Home Field East)",
            }
        )
        self.season("KF-25-HFE", datetime(2025, 9, 20, tzinfo=dt_tz.utc))
        self.season("KF-26-HFE", datetime(2026, 9, 18, tzinfo=dt_tz.utc))
        self.season("KF-26-HFE", datetime(2026, 9, 1, tzinfo=dt_tz.utc))
        page = _text(generate_module_pdf(osp, "g8_0_record_keeping"))
        # pdfminer reads the table a column at a time.
        self.assertIn("Code 26 HFE Signifies harvest year block (Home Field East)", page)
        self.assertIn(
            "Lot numbers on this operation's production records, most recent first: KF-26-HFE, KF-25-HFE.", page
        )
        self.assertNotIn("26 = harvest year", page)

    def test_a_key_that_does_not_split_prints_as_written(self):
        osp = self.plan(g8_0={"lot_numbering": "own_system", "lot_code_key": "Year then block then pick"})
        page = _text(generate_module_pdf(osp, "g8_0_record_keeping"))
        self.assertIn("Year then block then pick", page)
        self.assertNotIn("Code Signifies", page)
        self.assertIn("No lot number is recorded on this operation's production records yet.", page)

    def test_a_key_left_from_before_numbering_changed_to_none_does_not_print(self):
        osp = self.plan(g8_0={"lot_numbering": "none", "lot_code_key": "26 = harvest year"})
        self.assertNotIn("harvest year", _text(generate_module_pdf(osp, "g8_0_record_keeping")))

    def test_recorded_lots_are_distinct_newest_first_and_capped(self):
        self.plan()
        for i, lot in enumerate(["A", "B", "C", "D"]):
            self.season(lot, datetime(2022 + i, 9, 1, tzinfo=dt_tz.utc))
        self.assertEqual(recorded_lot_ids(self.est), ["D", "C", "B"])


class TraceMechanisms(_Plan):
    def test_the_mechanisms_print_with_the_other_text(self):
        osp = self.plan(
            g8_0={
                "lot_numbering": "none",
                "trace_mechanisms": ["field_names", "other"],
                "trace_mechanisms_other": "Pick tickets name the row",
            }
        )
        page = _text(generate_module_pdf(osp, "g8_0_record_keeping"))
        self.assertIn("Field or block numbers or names", page)
        self.assertIn("Pick tickets name the row", page)
        self.assertNotIn("[REVIEW] The plan says no lot numbering", page)

    def test_no_lot_numbering_and_lot_numbers_only_is_flagged(self):
        osp = self.plan(g8_0={"lot_numbering": "none", "trace_mechanisms": ["lot_numbers_only"]})
        self.assertIn(
            "[REVIEW] The plan says no lot numbering is used and nothing besides lot numbers traces a sale",
            _text(generate_module_pdf(osp, "g8_0_record_keeping")),
        )

    def test_lot_numbers_only_with_own_numbering_is_not_flagged(self):
        osp = self.plan(g8_0={"lot_numbering": "own_system", "trace_mechanisms": ["lot_numbers_only"]})
        self.assertNotIn(
            "[REVIEW] The plan says no lot numbering", _text(generate_module_pdf(osp, "g8_0_record_keeping"))
        )


class ContainerRecordElements(_Plan):
    def test_the_elements_print(self):
        osp = self.plan(
            g7_0={
                "nonretail_container_types": ["harvest_crates_bins"],
                "container_record_elements": ["organic_status", "certified_business_name"],
            }
        )
        page = _text(generate_module_pdf(osp, "g7_0_labeling"))
        self.assertIn("What do your storage and shipping records show for each organic lot?", page)
        self.assertIn("That the crop is organic", page)
        self.assertIn("Our certified business name", page)

    def test_none_of_these_prints_a_review(self):
        osp = self.plan(
            g7_0={"nonretail_container_types": ["harvest_crates_bins"], "container_record_elements": ["none_of_these"]}
        )
        self.assertIn(
            "[REVIEW] Storage and shipping records show none of: the crop's organic status",
            _text(generate_module_pdf(osp, "g7_0_labeling")),
        )

    def test_hidden_when_no_nonretail_containers_are_used(self):
        osp = self.plan(g7_0={"nonretail_container_types": ["none"], "container_record_elements": ["organic_status"]})
        self.assertNotIn("That the crop is organic", _text(generate_module_pdf(osp, "g7_0_labeling")))

    def test_the_new_questions_are_optional(self):
        from certifications.osp_modules.g7_0_labeling import G7_0_LABELING
        from certifications.osp_modules.g8_0_record_keeping import G8_0_RECORD_KEEPING

        questions = {q.key: q for m in (G7_0_LABELING, G8_0_RECORD_KEEPING) for p in m.pages for q in p.questions}
        for key in ("lot_code_key", "trace_mechanisms", "trace_mechanisms_other", "container_record_elements"):
            self.assertFalse(questions[key].required, key)


class RegisterRows(_Plan):
    """Each row cites the new questions with the ones it already cited; answering all of them answers the row."""

    def test_ccof_b2(self):
        osp = self.plan(
            g8_0={
                "lot_numbering": "own_system",
                "lot_numbering_description": "Year, block, pick",
                "lot_code_key": "26 = year",
            }
        )
        self.assertEqual(self.row(osp, "ccof", "ORGB33", "B2").state, "answered")

    def test_otco_12_2_3(self):
        osp = self.plan(
            g8_0={"lot_numbering": "none", "trace_mechanisms": ["field_names"]},
            g6_1={"lot_identification_on_every_load": True},
            g7_0={"container_markings_tie_to_lot": True},
            certifier=OTCO,
        )
        self.assertEqual(self.row(osp, "otco", "C12", "12.2-3").state, "answered")

    def test_wsda_n_4(self):
        osp = self.plan(
            g7_0={
                "nonretail_container_types": ["harvest_crates_bins"],
                "container_record_elements": ["organic_status"],
                "container_lot_identifier_types": ["lot_number"],
                "container_lot_linkage_description": "Bin tag lot is the harvest lot",
                "invoices_identify_lot": True,
            },
            certifier=WSDA,
        )
        self.assertEqual(self.row(osp, "wsda", "AGR 2121 N", "4").state, "answered")
