"""Container parcels: what the containers stand on, and the signed container statement (2026-11-12).

CCOF ORGB49 (R11 3/14/2022) F3: "Is all production at this parcel in containers AND on permanent, solid,
impermeable flooring?" Only that answer skips the land history; containers on land or a permeable surface
complete it. §G "For container systems": a statement signed and dated by an authorized representative listing
the planting date of the current container crops and the full names of all materials used since, growing media
included; on impermeable flooring, also a description of the removal of contamination sources before
transition. Until this slice ANY container parcel skipped the land history, and none of the statement was asked.
"""

import io
from datetime import date

from django.core.files.base import ContentFile
from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.conditions import visible_questions
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import CONTAINER_STATEMENT_SECTION, generate_module_pdf
from certifications.services.packet_attachments import _candidates
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from product.models import Parcel
from product.services.parcel_application_status import parcel_application_status, parcel_application_values


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Parcel(TestCase):
    def setUp(self):
        self.est = Establishment.objects.create(
            name="Seedhouse Farm", company=Company.objects.create(name="Seedhouse LLC"), state="CA"
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name="California Certified Organic Farmers (CCOF)",
        )
        self.parcel = Parcel.objects.create(
            name="House 2",
            establishment=self.est,
            area=0.5,
            container_production=True,
            application_answers={"currently_certified": "no"},
        )

    def answer(self, **answers):
        self.parcel.application_answers = {**self.parcel.application_answers, **answers}
        self.parcel.save(update_fields=["application_answers"])

    def missing(self):
        return parcel_application_status(self.parcel)["answers_missing"]

    def shown(self, **answers):
        values = {**parcel_application_values(self.parcel), **answers}
        return {q.key for _p, q in visible_questions(PARCEL_APPLICATION, values)}

    def page(self) -> str:
        return _text(generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel))

    def statement(self):
        return GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=self.parcel,
            title="House 2 container statement",
            linked_section=CONTAINER_STATEMENT_SECTION,
            source="upload",
            file=ContentFile(b"%PDF-1.4 signed statement", name="statement.pdf"),
        )


class WhatTheContainersStandOn(_Parcel):
    def test_containers_on_land_still_need_the_land_history(self):
        self.answer(container_surface="on_land")
        self.assertIn("land_history", self.missing())

    def test_impermeable_flooring_skips_it(self):
        self.answer(container_surface="impermeable")
        self.assertNotIn("land_history", self.missing())

    def test_an_unstated_surface_keeps_the_earlier_reading_and_says_so(self):
        self.assertNotIn("land_history", self.missing())
        self.assertIn("[REVIEW] What the containers stand on is not stated", self.page())

    def test_the_questions_follow_container_production(self):
        container = {"container_surface", "container_planting_date", "container_materials", "container_statement"}
        self.assertEqual(container & self.shown(), container)
        self.assertNotIn("contamination_removal", self.shown(container_surface="on_land"))
        self.assertIn("contamination_removal", self.shown(container_surface="impermeable"))
        self.parcel.container_production = False
        self.parcel.save(update_fields=["container_production"])
        self.assertFalse((container | {"contamination_removal"}) & self.shown(container_surface="impermeable"))


class TheContainerStatement(_Parcel):
    def test_its_contents_print(self):
        self.answer(
            container_surface="impermeable",
            container_planting_date="2026-03-02",
            container_materials="Sunshine Mix #4 (Sun Gro), Pacific Gro Oceanic Fish & Kelp",
            contamination_removal="Old benches and treated pallets removed; floor pressure-washed in January 2026.",
        )
        page = self.page()
        self.assertIn("2026-03-02", page)
        self.assertIn("Sunshine Mix #4 (Sun Gro)", page)
        self.assertIn("treated pallets removed", page)

    def test_a_missing_signed_copy_is_a_review_line(self):
        self.assertIn("[REVIEW] No signed container statement is on file for this parcel.", self.page())

    def test_a_signed_copy_is_named_and_ships_with_the_parcel(self):
        doc = self.statement()
        self.assertIn("Signed container statement on file: House 2 container statement.", self.page())
        paths = [a.zip_path for a, _open in _candidates(self.osp)]
        self.assertIn(f"parcels/container-statements/{doc.pk}-", " ".join(paths))

    def test_a_parcel_that_is_not_container_ships_no_statement(self):
        self.statement()
        self.parcel.container_production = False
        self.parcel.save(update_fields=["container_production"])
        self.assertFalse([a for a, _open in _candidates(self.osp) if a.kind == "container_statement"])
        self.assertNotIn("container statement", self.page())


class RegisterRows(_Parcel):
    def test_ccof_f3_and_g_container_cite_the_new_questions(self):
        from certifications.services.certifier_register import load_forms

        form = next(f for f in load_forms("ccof") if f.document_id == "ORGB49")
        rows = {r.ref: r for r in form.items}
        self.assertIn("parcel_application.container_surface", rows["F3"].questions)
        self.assertIn("parcel_application.container_statement", rows["G (container)"].questions)
        self.assertEqual((rows["F3"].status, rows["G (container)"].status), ("covered", "covered"))
        self.assertTrue(date.today())


class ReviewFindingsOn402(_Parcel):
    def test_the_statement_is_spent_last_so_it_never_pushes_out_a_file_that_rode_before(self):
        doc = self.statement()
        GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=self.parcel,
            title="House 2 map",
            linked_section="parcel_application_map",
            source="upload",
            file=ContentFile(b"%PDF-1.4 map", name="map.pdf"),
        )
        entries = [a for a, _open in _candidates(self.osp)]
        self.assertEqual(entries[-1].source_id, f"doc:{doc.pk}")
        self.assertLess(
            next(i for i, a in enumerate(entries) if a.kind == "parcel_map"),
            next(i for i, a in enumerate(entries) if a.kind == "container_statement"),
        )

    def test_a_statement_held_outside_the_packet_is_not_called_attached(self):
        from certifications.services.packet_attachments import build_manifest, building

        self.statement()
        manifest = build_manifest(self.osp, budget=1)
        with building(manifest):
            page = self.page()
        self.assertNotIn("Signed container statement attached", page)
        self.assertIn("[REVIEW] The signed container statement is uploaded to Trazo but not in this packet", page)
