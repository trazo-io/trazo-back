"""CCOF Materials Application §C and G4.0 A3, read against the records (content 2026.11.26).

§C ("Crop Management Tools and Production Aids") asks for seed treatments (coatings, pelleting materials,
inoculants), growing media (substrate, planting mix, potting soil) and adjuvants. The plan's two statements
asked about adjuvants and wetting agents only, and the seed treatment a planting record names and the tank-mix
partners an application record names were on neither the Materials List nor its reconciliation.

G4.0 A3 ("List all fertility materials planned for use on your Grower Materials Application") is the
Materials Application's fertilizer statement asked on G4.0; it was a plain Yes the records could contradict.
"""

import io

from django.test import TestCase
from django.utils import timezone

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import NationalListSubstance, OrganicSystemPlan, PlanMaterialEntry
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.common_osp_workbooks import (
    _material_listing,
    _material_manufacturer,
    _material_reason,
    _material_rows,
)
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_materials import none_used_contradictions, unmatched_logged_materials
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent, SoilManagementEvent
from product.models import Parcel
from users.models import User, WorksIn

MATERIALS = MODULES_BY_KEY["materials_application"]
G4 = MODULES_BY_KEY["g4_0_rotation_soil"]


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Aids Orchards LLC")
        self.user = User.objects.create_user(email="aids@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Aids Orchard", company=self.company, state="CA")
        parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=4.0)
        self.history = History.objects.create(name="Almonds 2026", start_date=timezone.now(), parcel=parcel)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def plant(self, treatment, basis="omri_listed"):
        return ProductionEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="planting",
            type="PL",
            seed_treatment=treatment,
            seed_treatment_allowed_basis=basis,
        )

    def spray(self, name="Entrust SC", partners=(), **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return ChemicalEvent.objects.create(
                history=self.history,
                date=timezone.now(),
                description="spray",
                type="PE",
                commercial_name=name,
                tank_mix_partners=list(partners),
                **fields,
            )

    def list_it(self, name, category="production_aid"):
        return PlanMaterialEntry.objects.create(osp=self.osp, product_name=name, category=category)

    def rows(self):
        return {r.name: r for r in _material_rows(self.est, osp=self.osp)}

    def put(self, module_key, answers):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/modules/{module_key}/"
        return self.client.put(url, {"answers": answers}, format="json")

    def store(self, module_key, answers):
        responses = self.osp.module_responses or {"schema_version": 1, "modules": {}}
        responses.setdefault("modules", {})[module_key] = {
            "answers": {k: {"at": "2026-11-09T10:00:00Z", "value": v} for k, v in answers.items()}
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])


class RecordsJoinTheListTests(_Farm):
    def test_a_seed_treatment_and_a_tank_mix_partner_are_rows_with_their_reason_and_maker(self):
        self.plant("Rhizobium inoculant XL")
        self.spray(partners=[{"commercial_name": "Nu-Film P", "manufacturer": "Miller Chemical"}])
        rows = self.rows()
        self.assertEqual(_material_reason(rows["Rhizobium inoculant XL"]), "Seed treatment")
        self.assertEqual(_material_reason(rows["Nu-Film P"]), "Adjuvant (tank-mix partner)")
        self.assertEqual(_material_manufacturer(rows["Nu-Film P"]), "Miller Chemical")
        self.assertIsNone(_material_manufacturer(rows["Rhizobium inoculant XL"]))

    def test_untreated_seed_names_no_product(self):
        # The specimen farm's own wording, from its planting records.
        for words in ("None", "None — raw, untreated organic seed", "N/A", "no coating"):
            self.plant(words, basis="organic_seed")
        self.plant("Some coating", basis="untreated")
        self.plant("No-Till Inoculant")
        rows = set(self.rows())
        self.assertFalse(
            {"None", "None — raw, untreated organic seed", "N/A", "no coating", "Some coating"} & rows, rows
        )
        self.assertIn("No-Till Inoculant", rows)

    def test_a_partner_never_borrows_the_primary_products_listing_or_maker(self):
        spinosad = NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section="205.601",
            subsection="e",
            category="insecticide",
            status="allowed",
        )
        self.spray(
            manufacturer="Corteva",
            national_list_substance=spinosad,
            national_list_basis=ChemicalEvent.NL_BASIS_OPERATOR,
            partners=[{"commercial_name": "Nu-Film P"}],
        )
        partner = self.rows()["Nu-Film P"]
        self.assertIsNone(_material_listing(partner))
        self.assertIsNone(_material_manufacturer(partner))

    def test_they_are_unmatched_until_listed(self):
        self.plant("Rhizobium inoculant XL")
        self.spray(partners=[{"commercial_name": "Nu-Film P"}])
        self.assertTrue({"Rhizobium inoculant XL", "Nu-Film P"} <= set(unmatched_logged_materials(self.osp)))
        self.list_it("Nu-Film P")
        self.assertNotIn("Nu-Film P", unmatched_logged_materials(self.osp))


class StatementsTests(_Farm):
    def test_the_adjuvant_only_statements_are_retired_for_ccofs_whole_list(self):
        questions = {q.key: q for p in MATERIALS.pages for q in p.questions}
        self.assertTrue(questions["production_aids_listed"].retired)
        self.assertTrue(questions["production_aids_none_used"].retired)
        label = questions["crop_production_aids_listed"].label["en"]
        for words in ("seed treatments", "growing media", "adjuvants"):
            self.assertIn(words, label)
        self.assertFalse(questions["crop_production_aids_listed"].required)

    def test_listed_is_refused_while_the_records_name_an_unlisted_aid(self):
        self.spray(partners=[{"commercial_name": "Nu-Film P"}])
        r = self.put("materials_application", {"crop_production_aids_listed": True})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("Nu-Film P", str(r.json()["answers"]["crop_production_aids_listed"]))
        self.list_it("Nu-Film P")
        r = self.put("materials_application", {"crop_production_aids_listed": True})
        self.assertEqual(r.status_code, 200, r.content)

    def test_none_used_is_flagged_when_the_records_name_one(self):
        self.plant("Rhizobium inoculant XL")
        lines = none_used_contradictions(self.osp, {"crop_production_aids_none_used": True})
        self.assertTrue(any("Rhizobium inoculant XL" in line and line.startswith("[REVIEW]") for line in lines))

    def test_the_listed_rows_print_under_their_own_heading(self):
        self.list_it("Sunshine Mix #4")
        page = _text(generate_module_pdf(self.osp, "materials_application"))
        self.assertIn("Crop production aids: seed treatments, growing media, adjuvants", page)
        self.assertIn("Sunshine Mix #4", page[page.index("Crop production aids:") :])


class FertilityAttestationTests(_Farm):
    def amend(self, name):
        return SoilManagementEvent.objects.create(
            history=self.history, date=timezone.now(), description="compost", amendment_product_name=name
        )

    def test_a_yes_is_refused_while_a_logged_fertility_product_is_not_listed(self):
        self.amend("Grow More Compost")
        r = self.put("g4_0_rotation_soil", {"fertility_inputs_listed": True})
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("Grow More Compost", str(r.json()["answers"]["fertility_inputs_listed"]))
        self.list_it("Grow More Compost", category="fertilizer_amendment")
        r = self.put("g4_0_rotation_soil", {"fertility_inputs_listed": True})
        self.assertEqual(r.status_code, 200, r.content)

    def test_a_stored_yes_prints_qualified_with_the_products(self):
        self.store("g4_0_rotation_soil", {"fertility_inputs_listed": True})
        self.amend("Grow More Compost")
        page = _text(generate_module_pdf(self.osp, "g4_0_rotation_soil"))
        self.assertIn("as answered before the records showed otherwise", page)
        self.assertIn("[REVIEW] The records name 1 soil-fertility product(s)", page)
        self.assertIn("Grow More Compost", page)


class RegisterRowsTests(TestCase):
    def test_the_rows_are_covered(self):
        from certifications.services.certifier_register import load_forms

        for code, ref in (("ORGB41", "C"), ("G4.0", "A3")):
            form = next(f for f in load_forms("ccof") if code in (f.code, f.document_id))
            row = next(i for i in form.items if i.ref == ref)
            self.assertEqual(row.status, "covered", ref)
