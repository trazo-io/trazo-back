"""Farm equipment that contacts organic crops: the equipment register and G6.0 page F (2026.11.11).

CCOF G6.0 C1-C3 and G6.1 B1-B2, OTCO C9 9.1-1 to 9.1-2 and WSDA AGR 2121 I 1-2c and 4 ask for one
table (each item, dedicated or not, own / rent / borrow / custom hire, how it is cleaned before
organic use and with what, rinsed) and how cleaning is documented. Until this slice the cleaning facts
lived only on Equipment-Maintenance events, so no plan printed the table.
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, ProductionEquipment
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import visible_questions
from certifications.services.certifier_register import load_forms
from certifications.services.osp_module_pdf import EQUIPMENT_COLUMNS, equipment_cells, generate_module_pdf
from certifications.services.packet_answers import form_answer_states
from certifications.services.production_equipment import COMPLETE, INCOMPLETE, equipment_rows, item_state
from company.models import Company, Establishment
from users.models import User, WorksIn

AT = "2026-11-11T10:00:00+00:00"
CCOF = "CCOF Certification Services, LLC"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _visible(answers):
    return {q.key for _p, q in visible_questions(MODULES_BY_KEY["g6_0_production"], answers)}


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Equipment Orchards")
        self.user = User.objects.create_user(email="equipment@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Home Orchard", company=self.company, state="WA")
        self.other_est = Establishment.objects.create(name="North Orchard", company=self.company, state="WA")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def url(self, suffix="", est=None):
        est = est or self.est
        return f"/api/companies/{self.company.id}/establishments/{est.id}/production-equipment/{suffix}"

    def item(self, **fields):
        data = {"name": "Air-blast sprayer", "use": "input_application", **fields}
        r = self.client.post(self.url(), data, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return ProductionEquipment.objects.get(pk=r.json()["id"])

    def plan(self, answers, certifier=CCOF):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={
                "schema_version": 1,
                "parcel_modules": {},
                "modules": {"g6_0_production": {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}},
            },
        )

    def row(self, osp, agent, code, ref):
        form = next(f for f in load_forms(agent) if f.code == code)
        return next(r for r in form_answer_states(osp, [form])[id(form)] if r.ref == ref)


class EquipmentTenancyTests(_Farm):
    def test_another_company_reaches_nothing(self):
        item = self.item()
        outsider = User.objects.create_user(email="other@equipment.test", password="x")
        other = Company.objects.create(name="Elsewhere")
        WorksIn.objects.create(user=outsider, company=other, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(outsider)
        self.assertIn(self.client.get(self.url()).status_code, (403, 404))
        self.assertIn(self.client.get(self.url(f"{item.id}/")).status_code, (403, 404))
        r = self.client.patch(self.url(f"{item.id}/"), {"name": "Mine now"}, format="json")
        self.assertIn(r.status_code, (403, 404))
        item.refresh_from_db()
        self.assertEqual(item.name, "Air-blast sprayer")

    def test_another_farms_url_does_not_list_or_reach_it(self):
        item = self.item()
        self.assertEqual(self.client.get(self.url(est=self.other_est)).json(), [])
        self.assertEqual(self.client.get(self.url(f"{item.id}/", est=self.other_est)).status_code, 404)

    def test_a_viewer_is_refused(self):
        viewer = User.objects.create_user(email="viewer@equipment.test", password="x")
        WorksIn.objects.create(user=viewer, company=self.company, role=WorksIn.VIEWER)
        self.client.force_authenticate(viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 403)


class ItemStateTests(_Farm):
    def test_a_dedicated_owned_item_owes_no_cleaning_statement(self):
        item = self.item(dedicated_organic=True, ownership="own")
        self.assertEqual(item_state(item), (COMPLETE, []))

    def test_a_shared_item_owes_its_cleaning_and_rinse(self):
        item = self.item(dedicated_organic=False, ownership="own")
        self.assertEqual(
            item_state(item), (INCOMPLETE, ["how it is cleaned before organic use", "whether it is rinsed"])
        )

    def test_a_borrowed_item_owes_its_cleaning_even_when_dedicated(self):
        item = self.item(dedicated_organic=True, ownership="borrow", cleaning_method="Washed", rinsed=None)
        self.assertEqual(item_state(item), (INCOMPLETE, ["whether it is rinsed"]))

    def test_unknown_is_not_no(self):
        state, missing = item_state(self.item())
        self.assertEqual(state, INCOMPLETE)
        self.assertEqual(
            missing,
            [
                "whether it is dedicated to organic production",
                "whether it is owned, rented, borrowed or custom hired",
            ],
        )

    def test_the_api_carries_the_state_and_what_is_missing(self):
        self.item(dedicated_organic=False, ownership="custom_hire")
        row = self.client.get(self.url()).json()[0]
        self.assertEqual(row["state"], "incomplete")
        self.assertEqual(row["missing"], ["cleaning_method", "rinsed"])
        self.assertEqual(row["ownership_display"], "Custom hire")

    def test_a_blank_name_is_refused(self):
        r = self.client.post(self.url(), {"name": "   ", "use": "harvest"}, format="json")
        self.assertEqual(r.status_code, 400)


class GatesTests(TestCase):
    def test_page_f_asks_nothing_more_once_no_equipment_contacts_organic_crops(self):
        stale = {
            "uses_production_equipment": False,
            "equipment_cleaning_documentation": ["sop_followed", "other"],
            "equipment_shared_with_nonorganic": True,
        }
        self.assertEqual(
            _visible(stale)
            & {
                "equipment_inventory_panel",
                "equipment_shared_with_nonorganic",
                "equipment_cleaning_documentation",
                "equipment_cleaning_documentation_other",
                "equipment_cleaning_sop_upload",
                "equipment_cleaning_materials_listed",
                "equipment_notes",
            },
            set(),
        )

    def test_the_procedure_upload_follows_its_option(self):
        answers = {"uses_production_equipment": True, "equipment_cleaning_documentation": ["sop_followed"]}
        self.assertIn("equipment_cleaning_sop_upload", _visible(answers))
        self.assertNotIn("equipment_cleaning_documentation_other", _visible(answers))


class ThePlanPrintsTheTableTests(_Farm):
    def test_each_item_prints_with_what_is_missing_flagged(self):
        self.item(
            name="Custom harvester",
            use="harvest",
            dedicated_organic=False,
            ownership="custom_hire",
            cleaning_method="Blown out and pressure-washed at the field edge.",
            cleaning_materials="Water only",
            rinsed=True,
        )
        self.item(name="Bin trailer", use="transport", dedicated_organic=False, ownership="own")
        osp = self.plan({"uses_production_equipment": True, "equipment_shared_with_nonorganic": True})
        text = _text(generate_module_pdf(osp, "g6_0_production"))
        self.assertIn("F. Production equipment", text)
        for column in EQUIPMENT_COLUMNS:
            self.assertIn(column, text)
        self.assertIn("[REVIEW] How it is cleaned before organic use is not stated.", text)
        self.assertIn("[REVIEW] Whether it is rinsed is not stated.", text)
        # A table's cells interleave in extracted text, so what each cell says is read from its rows.
        cells = {row["item"].name: equipment_cells(row) for row in equipment_rows(self.est)}
        self.assertEqual(
            cells["Custom harvester"],
            [
                ["Custom harvester"],
                ["Harvest"],
                ["No, also non-organic"],
                ["Custom hire"],
                ["Blown out and pressure-washed at the field edge.", "Materials: Water only"],
                ["Yes"],
            ],
        )
        self.assertEqual(cells["Bin trailer"][4:], [["Not stated"], ["Not stated"]])

    def test_an_item_never_splits_across_pages_and_the_header_repeats(self):
        # Before 2026-11-03 the items printed as loose lines and the specimen's first item began at a
        # page foot and finished overleaf with nothing naming it. Each item here carries a notes row
        # under it, so a page break between the two shows as the marker on another page.
        for i in range(40):
            ProductionEquipment.objects.create(
                establishment=self.est,
                name=f"Sprayer {i:02d}",
                use="input_application",
                dedicated_organic=False,
                ownership="rent",
                cleaning_method="Triple-rinsed with potable water, then run empty for five minutes at the field edge.",
                notes=f"marker-{i:02d}-end",
            )
        data = generate_module_pdf(self.plan({"uses_production_equipment": True}), "g6_0_production")
        pages = []
        while True:
            page = " ".join(extract_text(io.BytesIO(data), page_numbers=[len(pages)]).split())
            if not page:
                break
            pages.append(page)
        self.assertGreater(len([p for p in pages if "Sprayer" in p]), 2, "the register must span pages")

        def page_of(text):
            return next(i for i, p in enumerate(pages) if text in p)

        for i in range(40):
            self.assertEqual(page_of(f"Sprayer {i:02d}"), page_of(f"marker-{i:02d}-end"), f"Sprayer {i:02d}")
        for page in pages:
            if "Sprayer" in page:
                self.assertIn("Cleaning before organic use", page)

    def test_an_item_longer_than_a_page_still_prints(self):
        # A table row cannot break across pages, so one item holding a pasted procedure longer than a
        # page made ReportLab raise LayoutError and failed the whole packet (review of #276).
        procedure = " ".join(f"Step {i}: rinse the boom and run water through every nozzle." for i in range(160))
        self.item(
            name="Boom sprayer", dedicated_organic=False, ownership="rent", cleaning_method=procedure, rinsed=True
        )
        self.item(name="Bin trailer", use="transport", dedicated_organic=True, ownership="own")
        text = _text(generate_module_pdf(self.plan({"uses_production_equipment": True}), "g6_0_production"))
        self.assertIn("Step 159: rinse the boom", text)
        self.assertIn("Bin trailer", text)

    def test_an_empty_register_prints_review(self):
        osp = self.plan({"uses_production_equipment": True})
        self.assertIn(
            "[REVIEW] The plan says farm equipment contacts organic crops, and no equipment is recorded",
            _text(generate_module_pdf(osp, "g6_0_production")),
        )

    def test_no_shared_equipment_beside_a_shared_item_prints_review(self):
        self.item(
            name="Bin trailer",
            use="transport",
            dedicated_organic=False,
            ownership="own",
            cleaning_method="Washed",
            rinsed=True,
        )
        osp = self.plan({"uses_production_equipment": True, "equipment_shared_with_nonorganic": False})
        self.assertIn(
            "[REVIEW] The plan says no equipment is also used on non-organic crops or land, and the register "
            "lists Bin trailer as not dedicated to organic production.",
            _text(generate_module_pdf(osp, "g6_0_production")),
        )

    def test_shared_equipment_with_every_item_dedicated_prints_review(self):
        self.item(dedicated_organic=True, ownership="own")
        osp = self.plan({"uses_production_equipment": True, "equipment_shared_with_nonorganic": True})
        self.assertIn(
            "every item in the register is listed as dedicated to organic production",
            _text(generate_module_pdf(osp, "g6_0_production")),
        )

    def test_an_unstated_item_is_not_read_as_dedicated(self):
        self.item(dedicated_organic=None, ownership="own")
        osp = self.plan({"uses_production_equipment": True, "equipment_shared_with_nonorganic": True})
        text = _text(generate_module_pdf(osp, "g6_0_production"))
        self.assertIn("[REVIEW] Whether it is dedicated to organic production is not stated.", text)
        self.assertNotIn("every item in the register is listed as dedicated", text)

    def test_rinse_details_print_when_the_yes_no_is_blank(self):
        self.item(
            dedicated_organic=True,
            ownership="own",
            rinsed=None,
            rinse_detail="Rinsed with potable water after the sanitizer.",
        )
        osp = self.plan({"uses_production_equipment": True})
        self.assertIn(
            "Rinsed with potable water after the sanitizer.", _text(generate_module_pdf(osp, "g6_0_production"))
        )
        # Dedicated and owned, it owes no rinse: the cell says nothing is stated, never "not needed".
        (row,) = equipment_rows(self.est)
        self.assertEqual(equipment_cells(row)[5], ["None stated", "Rinsed with potable water after the sanitizer."])

    def test_a_procedure_said_to_be_attached_and_missing_prints_review(self):
        self.item(dedicated_organic=True, ownership="own")
        osp = self.plan({"uses_production_equipment": True, "equipment_cleaning_documentation": ["sop_followed"]})
        self.assertIn("[REVIEW] The answer says it is attached", _text(generate_module_pdf(osp, "g6_0_production")))

    def test_cleaning_logs_print_their_count(self):
        self.item(dedicated_organic=True, ownership="own")
        osp = self.plan(
            {"uses_production_equipment": True, "equipment_cleaning_documentation": ["cleaning_purge_logs"]}
        )
        self.assertIn(
            "In Trazo: no cleaning records for field or harvest equipment logged.",
            _text(generate_module_pdf(osp, "g6_0_production")),
        )

    def test_a_listed_cleaning_material_missing_from_the_list_prints_review(self):
        self.item(dedicated_organic=True, ownership="own")
        osp = self.plan({"uses_production_equipment": True, "equipment_cleaning_materials_listed": "no"})
        self.assertIn(
            "[REVIEW] A material used to clean equipment is not on the materials list.",
            _text(generate_module_pdf(osp, "g6_0_production")),
        )


class CoverageTests(_Farm):
    def test_ccof_c2_is_answered_only_when_every_item_says_what_the_table_asks(self):
        osp = self.plan({"uses_production_equipment": True})
        empty = self.row(osp, "ccof", "G6.0", "C2")
        self.assertEqual(
            (empty.state, empty.detail), ("unanswered", "no equipment is recorded in the equipment register")
        )
        item = self.item(dedicated_organic=False, ownership="own")
        open_row = self.row(osp, "ccof", "G6.0", "C2")
        self.assertEqual(open_row.state, "unanswered")
        self.assertIn("Air-blast sprayer (how it is cleaned before organic use; whether it is rinsed)", open_row.detail)
        item.cleaning_method, item.rinsed = "Triple-rinsed with water", True
        item.save()
        self.assertEqual(self.row(osp, "ccof", "G6.0", "C2").state, "answered")

    def test_the_table_does_not_apply_when_no_equipment_contacts_organic_crops(self):
        osp = self.plan({"uses_production_equipment": False})
        self.assertEqual(self.row(osp, "ccof", "G6.0", "C1").state, "answered")
        self.assertEqual(self.row(osp, "ccof", "G6.0", "C2").state, "not_applicable")

    def test_wsda_shared_rows_do_not_apply_without_shared_equipment(self):
        self.item(dedicated_organic=True, ownership="own")
        osp = self.plan({"uses_production_equipment": True, "equipment_shared_with_nonorganic": False})
        self.assertEqual(self.row(osp, "wsda", "I", "2").state, "answered")
        self.assertEqual(self.row(osp, "wsda", "I", "2b").state, "not_applicable")

    def test_shared_only_rows_close_for_a_farm_with_no_equipment(self):
        # The shared trigger is never asked once "no equipment" is answered; the rows it gates do not
        # apply, for that reason, rather than waiting on an answer nobody will give.
        osp = self.plan({"uses_production_equipment": False})
        for agent, code, ref in (("wsda", "I", "2b"), ("wsda", "I", "2c"), ("otco", "C9", "9.1-2")):
            row = self.row(osp, agent, code, ref)
            self.assertEqual(row.state, "not_applicable", (agent, ref))
            self.assertIn("uses_production_equipment = False", row.detail)

    def test_shared_only_rows_wait_while_the_gate_is_unanswered(self):
        osp = self.plan({})
        self.assertEqual(self.row(osp, "wsda", "I", "2b").state, "unresolved")

    def test_otco_9_1_1a_reads_the_materials_answer(self):
        self.item(dedicated_organic=False, ownership="own", cleaning_method="Washed", rinsed=True)
        osp = self.plan(
            {
                "uses_production_equipment": True,
                "equipment_shared_with_nonorganic": True,
                "equipment_cleaning_materials_listed": "no_materials",
            }
        )
        self.assertEqual(self.row(osp, "otco", "C9", "9.1-1").state, "answered")
        self.assertEqual(self.row(osp, "otco", "C9", "9.1-1a").state, "answered")
