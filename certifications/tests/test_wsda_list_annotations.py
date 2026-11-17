"""WSDA's own annotation for each product on its Organic Input Material List (2026-11-17).

WSDA prints an Annotation column, and the list's header states that registered products must be used
in accordance with all noted annotations: "Deficiency must be documented." (140 products),
"Preventative practices must be implemented prior to use." (85), "Contains raw manure, must be used in
compliance with NOP 205.203 (c)(1)." (9). Trazo transcribed every other column of the March 06, 2026
edition and left this one out, so the lookup showed an annotated product as plainly listed and WSDA
AGR 2196's question, how each material's restrictions are met, had nothing to point the grower at.

Pinned here:
  * the seed CSV and the migration carry the same 782 annotations, NONE as "";
  * the seeder writes the column, maps NONE to "", and leaves stored text alone when a CSV has no
    such column; the migration writes only a row whose number, name and edition all match;
  * the annotation is a held restriction: offered in the restrictions view, printed where the
    workbook and the packet print restrictions, stated against like regulation wording, and put back
    to "needs review" when a new edition rewords it;
  * WSDA's NONE is never printed as "no restrictions" and is never offered as a restriction;
  * the input lookup returns the annotation with the edition it was read from.
"""

import csv
import datetime
import importlib
import os
import tempfile
from unittest import mock

from django.apps import apps as django_apps
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.models import PlanMaterialRestrictionStatement as PRS
from certifications.models import WSDAMaterial
from certifications.services.material_restrictions import (
    NEEDS_REVIEW,
    NOT_DOCUMENTED,
    RestrictionError,
    material_restriction_text,
    record_statement,
    restrictions_view,
    statement_state,
    withdraw_statement,
    withdrawn_statement_lines,
    wsda_list_restriction,
)
from company.models import Company, Establishment
from users.models import User

MIGRATION = importlib.import_module("certifications.migrations.0086_wsda_list_annotations")
SEED_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "wsda_seed.csv")
EDITION = datetime.date(2026, 3, 6)
DEFICIENCY = "Deficiency must be documented."


def _seed_rows():
    with open(SEED_CSV, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TheTranscriptionTests(TestCase):
    def test_every_product_carries_the_column_and_none_is_written_as_wsda_prints_it(self):
        rows = _seed_rows()
        self.assertEqual(len(rows), 782)
        self.assertTrue(all(r["annotation"] for r in rows), "an empty cell would read as 'not transcribed'")
        self.assertEqual(sum(1 for r in rows if r["annotation"] == "NONE"), 422)
        self.assertEqual(sum(1 for r in rows if r["annotation"] == DEFICIENCY), 140)

    def test_the_csv_and_the_migration_hold_the_same_annotations(self):
        """Two copies of one transcription (the seeder's and the frozen migration's) must not drift."""
        frozen = {}
        for text, products in MIGRATION.ANNOTATIONS.items():
            for wsda_id, brand_name in products:
                self.assertNotIn(wsda_id, frozen, f"product #{wsda_id} is frozen twice")
                frozen[wsda_id] = (brand_name, text)
        csv_side = {
            r["wsda_id"]: (r["brand_name"], "" if r["annotation"] == "NONE" else r["annotation"]) for r in _seed_rows()
        }
        self.assertEqual(frozen, csv_side)
        self.assertTrue(all(r["list_effective_date"] == EDITION.isoformat() for r in _seed_rows()))


class TheSeederTests(TestCase):
    def test_seeding_writes_the_annotation_and_none_as_empty(self):
        call_command("seed_wsda_materials", stdout=open(os.devnull, "w"))
        self.assertEqual(WSDAMaterial.objects.get(wsda_id="1123").annotation, "Label Use Only.")
        self.assertEqual(WSDAMaterial.objects.get(wsda_id="3376").annotation, "")
        self.assertEqual(WSDAMaterial.objects.exclude(annotation="").count(), 360)
        self.assertFalse(WSDAMaterial.objects.filter(annotation__isnull=True).exists())

    def test_a_csv_without_the_column_leaves_stored_annotations_alone(self):
        WSDAMaterial.objects.create(wsda_id="1123", brand_name="Sprout Torch", annotation="Label Use Only.")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write("wsda_id,brand_name\n1123,Sprout Torch\n")
            path = fh.name
        try:
            with mock.patch("certifications.management.commands.seed_wsda_materials._DATA_FILE", path):
                call_command("seed_wsda_materials", stdout=open(os.devnull, "w"))
        finally:
            os.unlink(path)
        self.assertEqual(WSDAMaterial.objects.get(wsda_id="1123").annotation, "Label Use Only.")


class TheMigrationTests(TestCase):
    def test_only_a_row_whose_number_name_and_edition_match_is_written(self):
        same = WSDAMaterial.objects.create(wsda_id="1123", brand_name="Sprout Torch", list_effective_date=EDITION)
        none = WSDAMaterial.objects.create(
            wsda_id="3376", brand_name="Nurturing Nature Organic Worm Castings", list_effective_date=EDITION
        )
        renamed = WSDAMaterial.objects.create(wsda_id="696", brand_name="Renamed since", list_effective_date=EDITION)
        other_edition = WSDAMaterial.objects.create(
            wsda_id="1174", brand_name="Excite Seaweed SSEP 0.5-0-17", list_effective_date=datetime.date(2025, 6, 1)
        )
        MIGRATION.store(django_apps, None)
        for row in (same, none, renamed, other_edition):
            row.refresh_from_db()
        self.assertEqual(same.annotation, "Label Use Only.")
        self.assertEqual(none.annotation, "")
        self.assertIsNone(renamed.annotation, "another product's annotation on a renamed row")
        self.assertIsNone(other_edition.annotation, "an annotation from another edition")


class _Plan(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Okanogan Pear Co.")
        self.est = Establishment.objects.create(name="Tonasket Block", company=company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            certifier_name="Washington State Department of Agriculture",
        )
        self.user = User.objects.create_user(email="wsda-ann@test.com", password="x", first_name="Rosa")
        self.zinc = WSDAMaterial.objects.create(
            wsda_id="2948",
            brand_name="Zinc Sulfate Test",
            manufacturer="Test Minerals",
            list_effective_date=EDITION,
            annotation=DEFICIENCY,
            source_url="https://cms.agr.wa.gov/WSDAKentico/Documents/FSCS/Organic/Pubs_organic/WSDA_Organic_Input_Material_List.pdf",
        )
        self.castings = WSDAMaterial.objects.create(
            wsda_id="3376", brand_name="Worm Castings Test", list_effective_date=EDITION, annotation=""
        )
        self.untranscribed = WSDAMaterial.objects.create(wsda_id="4001", brand_name="Hand Entered Test")
        self.osp.approved_wsda_materials.add(self.zinc, self.castings, self.untranscribed)

    def _state(self, how_met="Tissue test in July shows zinc below range; report filed with the record."):
        return record_statement(
            self.osp,
            self.user,
            {
                "material_kind": "wsda",
                "material_id": self.zinc.pk,
                "restriction_source": PRS.SOURCE_WSDA_LIST,
                "how_met": how_met,
            },
        )


class HeldRestrictionTests(_Plan):
    def test_an_annotated_listing_is_held_with_its_product_number_and_edition(self):
        held = wsda_list_restriction(self.osp, "wsda", self.zinc.pk)
        self.assertEqual(held["key"], f"wsda:{self.zinc.pk}")
        self.assertEqual(held["text"], DEFICIENCY)
        self.assertEqual(held["citation"], "WSDA Product #2948")
        self.assertEqual(held["effective_date"], EDITION)

    def test_none_and_not_transcribed_are_not_restrictions(self):
        self.assertIsNone(wsda_list_restriction(self.osp, "wsda", self.castings.pk))
        self.assertIsNone(wsda_list_restriction(self.osp, "wsda", self.untranscribed.pk))
        # NONE stays "restriction not documented": the label can still restrict use.
        self.assertEqual(material_restriction_text(self.osp, "wsda", self.castings.pk), NOT_DOCUMENTED)
        self.assertEqual(material_restriction_text(self.osp, "wsda", self.untranscribed.pk), NOT_DOCUMENTED)

    def test_an_operator_entry_linked_to_the_listing_gets_its_annotation(self):
        entry = PlanMaterialEntry.objects.create(osp=self.osp, product_name="Our zinc", wsda_material=self.zinc)
        held = wsda_list_restriction(self.osp, "plan_entry", entry.pk)
        self.assertEqual(held["text"], DEFICIENCY)

    def test_printed_as_wsdas_words_for_that_product_with_no_answer_yet(self):
        printed = material_restriction_text(self.osp, "wsda", self.zinc.pk)
        self.assertIn(
            "WSDA annotation, WSDA Product #2948 (Organic Input Material List of 2026-03-06, "
            f'WSDA\'s words, transcribed by Trazo): "{DEFICIENCY}" How it is met: not stated.',
            printed,
        )
        self.assertNotIn("no restriction", printed.lower())

    def test_the_restrictions_view_offers_it(self):
        row = next(
            m for m in restrictions_view(self.osp) if m["material_kind"] == "wsda" and m["material_id"] == self.zinc.pk
        )
        self.assertEqual(
            row["wsda_list_restriction"],
            {
                "key": f"wsda:{self.zinc.pk}",
                "text": DEFICIENCY,
                "citation": "WSDA Product #2948",
                "edition": "2026-03-06",
                "source_url": self.zinc.source_url,
            },
        )
        castings = next(m for m in restrictions_view(self.osp) if m["material_id"] == self.castings.pk)
        self.assertIsNone(castings["wsda_list_restriction"])


class StatementTests(_Plan):
    def test_a_statement_against_the_annotation_stores_wsdas_words_and_edition(self):
        st = self._state()
        self.assertEqual(st.restriction_source, PRS.SOURCE_WSDA_LIST)
        self.assertEqual(st.restriction_key, f"wsda:{self.zinc.pk}")
        self.assertEqual(st.restriction_text, DEFICIENCY)
        self.assertEqual(st.citation, "WSDA Product #2948")
        self.assertEqual(st.source_effective_date, EDITION)
        printed = material_restriction_text(self.osp, "wsda", self.zinc.pk)
        self.assertIn(
            f'WSDA Product #2948 (Organic Input Material List of 2026-03-06, WSDA\'s words, transcribed by Trazo): "{DEFICIENCY}"',
            printed,
        )
        self.assertIn("How it is met, as stated by Rosa", printed)
        self.assertNotIn("How it is met: not stated.", printed, "the held line repeats once it is answered")

    def test_no_statement_against_an_annotation_trazo_does_not_hold(self):
        with self.assertRaises(RestrictionError) as raised:
            record_statement(
                self.osp,
                self.user,
                {
                    "material_kind": "wsda",
                    "material_id": self.castings.pk,
                    "restriction_source": PRS.SOURCE_WSDA_LIST,
                    "how_met": "n/a",
                },
            )
        self.assertEqual(raised.exception.field, "restriction_source")
        self.assertFalse(PRS.objects.exists())

    def test_a_new_edition_that_rewords_it_puts_the_answer_back_for_review(self):
        st = self._state()
        WSDAMaterial.objects.filter(pk=self.zinc.pk).update(annotation="Zinc deficiency must be documented by testing.")
        self.assertEqual(statement_state(st, self.osp), NEEDS_REVIEW)
        printed = material_restriction_text(self.osp, "wsda", self.zinc.pk)
        self.assertIn("[REVIEW]", printed)
        self.assertIn('"Zinc deficiency must be documented by testing." How it is met: not stated.', printed)

    def _transcribed_from_the_listing(self, text="deficiency must be documented", how_met="Leaf test each July."):
        """How a WSDA restriction had to be recorded before Trazo held the annotation."""
        return record_statement(
            self.osp,
            self.user,
            {
                "material_kind": "wsda",
                "material_id": self.zinc.pk,
                "restriction_source": PRS.SOURCE_TRANSCRIBED,
                "restriction_text": text,
                "source_type": PRS.DOC_WSDA,
                "source_identifier": "WSDA list 2026-03-06",
                "how_met": how_met,
            },
        )

    def test_an_answer_transcribed_from_the_listing_answers_the_annotation(self):
        """Review of back #470: the old way of recording it printed the annotation a second time as
        "not stated" next to the operator's answer."""
        self._transcribed_from_the_listing()
        printed = material_restriction_text(self.osp, "wsda", self.zinc.pk)
        self.assertIn("Leaf test each July.", printed)
        self.assertNotIn("How it is met: not stated.", printed)

    def test_a_transcription_in_other_words_still_leaves_the_annotation_unanswered(self):
        self._transcribed_from_the_listing(text="Apply only after a soil test.")
        printed = material_restriction_text(self.osp, "wsda", self.zinc.pk)
        self.assertIn(f'"{DEFICIENCY}" How it is met: not stated.', printed)

    def test_a_withdrawn_statement_names_wsdas_annotation(self):
        st = self._state()
        withdraw_statement(self.osp, self.user, {"withdraw": st.pk, "reason": "Wrong block"})
        (line,) = withdrawn_statement_lines(self.osp)
        self.assertIn(
            f'(WSDA annotation, WSDA Product #2948): "{DEFICIENCY}" (WSDA\'s words, transcribed by Trazo.)', line
        )


class PacketLineTests(_Plan):
    def _rows(self):
        from certifications.services.plan_materials import plan_materials

        return {r.name: r for r in plan_materials(self.osp)}

    def test_the_materials_page_prints_the_annotation_under_the_row(self):
        from certifications.services.osp_module_pdf import _material_wsda_annotation_lines

        rows = self._rows()
        self.assertEqual(
            _material_wsda_annotation_lines(self.osp, rows["Zinc Sulfate Test"]),
            [
                "WSDA annotation, WSDA Product #2948 (Organic Input Material List of 2026-03-06, WSDA's words, "
                f'transcribed by Trazo): "{DEFICIENCY}" How it is met: not stated.'
            ],
        )
        self.assertEqual(_material_wsda_annotation_lines(self.osp, rows["Worm Castings Test"]), [])
        self.assertEqual(_material_wsda_annotation_lines(self.osp, rows["Hand Entered Test"]), [])

    def test_it_quotes_the_operators_answer_to_that_annotation_only(self):
        from certifications.services.osp_module_pdf import _material_wsda_annotation_lines

        self._state("Tissue test each July.")
        record_statement(
            self.osp,
            self.user,
            {
                "material_kind": "wsda",
                "material_id": self.zinc.pk,
                "restriction_source": PRS.SOURCE_TRANSCRIBED,
                "restriction_text": "Do not exceed 2 lb per acre.",
                "source_type": PRS.DOC_LABEL,
                "how_met": "Rate sheet in the spray log.",
            },
        )
        (line,) = _material_wsda_annotation_lines(self.osp, self._rows()["Zinc Sulfate Test"])
        self.assertTrue(line.endswith('How the operator states it is met: "Tissue test each July.".'), line)

    def test_it_quotes_an_answer_transcribed_from_the_listing(self):
        from certifications.services.osp_module_pdf import _material_wsda_annotation_lines

        record_statement(
            self.osp,
            self.user,
            {
                "material_kind": "wsda",
                "material_id": self.zinc.pk,
                "restriction_source": PRS.SOURCE_TRANSCRIBED,
                "restriction_text": "Deficiency must be documented",
                "source_type": PRS.DOC_WSDA,
                "how_met": "Leaf test each July.",
            },
        )
        (line,) = _material_wsda_annotation_lines(self.osp, self._rows()["Zinc Sulfate Test"])
        self.assertTrue(line.endswith('How the operator states it is met: "Leaf test each July.".'), line)


class LookupTests(_Plan):
    def test_the_lookup_returns_the_annotation_and_its_edition(self):
        client = APIClient()
        client.force_authenticate(self.user)
        body = client.get(reverse("verify_input"), {"name": "Zinc Sulfate Test"}).json()
        self.assertEqual(body["wsda_material_pk"], self.zinc.pk)
        self.assertEqual(body["wsda_material_annotation"], DEFICIENCY)
        self.assertEqual(body["wsda_list_effective_date"], "2026-03-06")
        self.assertEqual(body["wsda_candidates"][0]["annotation"], DEFICIENCY)

    def test_none_comes_back_as_empty_not_as_missing(self):
        client = APIClient()
        client.force_authenticate(self.user)
        body = client.get(reverse("verify_input"), {"name": "Worm Castings Test"}).json()
        self.assertEqual(body["wsda_material_annotation"], "")
