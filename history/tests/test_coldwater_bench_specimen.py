"""The orchard specimen, Coldwater Bench, holds what an orchard's packet and spray export are read from.

WHY THIS EXISTS
---------------
The overall review of 2026-11 found that no seeded farm looked like the grower Trazo sells to: no
orchard packet had ever been read. `seed_coldwater_bench` builds a Washington apple and pear farm
from the rehearsal kit's paper records, writes its sprays through the API's serializer and the
tank-mix service, and answers every plan module for the WSDA path. These tests hold the properties
a reader of its documents relies on:

* reseeding replaces the farm and never leaves two;
* every document it produces is stamped a specimen;
* the tank is one tank of full records, one per product and per block;
* the blanks the paper sheet has stay blank, and the Washington export names them;
* the WSDA packet builds.

COST
----
The farm is seeded once per class (`setUpTestData`), as in `test_calapooia_renewal_specimen`, and
the packet is built once, in the one test that reads it. The only second seed is the rebuild test's.
"""

import io
import zipfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULE_REGISTRY
from certifications.services.osp_module_pdf import generate_osp_packet
from common.specimen import SPECIMEN_TITLE, is_specimen
from company.models import Applicator, Company, Establishment
from history.management.commands.seed_coldwater_bench import (
    AGENT_NAME,
    BLOCKS,
    COMPANY_NAME,
    FARM_NAME,
    OSP_ANSWERS_PATH,
)
from history.management.commands.seed_showcase_walnut_farm import _load_osp_answers
from history.models import ChemicalEvent, GeneralEvent, History, ProductionEvent, SalesRecord, SoilManagementEvent
from history.services.tank_mix import tank_cell_text
from history.services.wa_spray_record_service import NOT_RECORDED, WASprayRecordService
from product.models import Parcel
from users.models import User

OWNER = "coldwater-specimen@test.com"

#: Real organisations the fictional farm's plan answers must not credit with anything. The plan is
#: filed with WSDA (the `certifier_name` field), but the operator's own answers never name an agent.
REAL_NAMES = ("CCOF", "Oregon Tilth", "OTCO", "WSDA", "Washington State Department", "Stemilt", "Chelan Fruit")


def _seed(rebuild=False):
    call_command("seed_coldwater_bench", owner_email=OWNER, rebuild=rebuild, stdout=io.StringIO())


class ColdwaterBenchAnswersTests(SimpleTestCase):
    """No database: the answers are compared with the module registry, which is code."""

    def test_every_module_is_answered_against_the_current_questionnaire(self):
        fixture = _load_osp_answers(OSP_ANSWERS_PATH)  # raises naming module.question when out of step
        self.assertEqual({module.key for module in MODULE_REGISTRY} - set(fixture), set())

    def test_the_answers_name_no_real_organisation(self):
        with open(OSP_ANSWERS_PATH, encoding="utf-8") as fh:
            text = fh.read().lower()
        self.assertEqual([name for name in REAL_NAMES if name.lower() in text], [])


class ColdwaterBenchSpecimenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        quiet = io.StringIO()
        call_command("populate_usda_crop_types", crops_only=True, stdout=quiet)
        call_command("seed_national_list", stdout=quiet)
        call_command("create_plans", stdout=quiet)
        User.objects.create_user(email=OWNER, password="unused-Pw-2026", first_name="Seed", last_name="Runner")
        _seed()

    def setUp(self):
        self.est = Establishment.objects.get(name=FARM_NAME)

    def _sprays(self):
        return ChemicalEvent.objects.filter(history__parcel__establishment=self.est)

    def _counts(self):
        on_farm = {"history__parcel__establishment__name": FARM_NAME}
        return {
            "parcels": Parcel.objects.filter(establishment__name=FARM_NAME).count(),
            "seasons": History.objects.filter(parcel__establishment__name=FARM_NAME).count(),
            "sprays": ChemicalEvent.objects.filter(**on_farm).count(),
            "soil": SoilManagementEvent.objects.filter(**on_farm).count(),
            "production": ProductionEvent.objects.filter(**on_farm).count(),
            "general": GeneralEvent.objects.filter(**on_farm).count(),
            "sales": SalesRecord.objects.filter(production__parcel__establishment__name=FARM_NAME).count(),
            "plans": OrganicSystemPlan.objects.filter(establishment__name=FARM_NAME).count(),
        }

    # -- Idempotence --------------------------------------------------------------------------
    def test_seeding_again_refuses_or_replaces_and_never_duplicates(self):
        before = self._counts()
        self.assertEqual(before["parcels"], len(BLOCKS))
        with self.assertRaises(CommandError):
            _seed()
        self.assertEqual(Establishment.objects.filter(name=FARM_NAME).count(), 1)

        _seed(rebuild=True)
        self.assertEqual(Establishment.objects.filter(name=FARM_NAME).count(), 1)
        self.assertNotEqual(Establishment.objects.get(name=FARM_NAME).pk, self.est.pk)
        self.assertEqual(self._counts(), before)
        # The company is found by name and reused; its applicator profiles are replaced, not added.
        self.assertEqual(Company.objects.filter(name=COMPANY_NAME).count(), 1)
        self.assertEqual(Applicator.objects.filter(company__name=COMPANY_NAME).count(), 2)

    # -- Specimen marking ---------------------------------------------------------------------
    def test_the_farm_is_marked_a_specimen_and_its_exports_say_so(self):
        self.assertTrue(self.est.is_demo)
        self.assertTrue(is_specimen(self.est))
        export = WASprayRecordService.for_year(self.est, 2026)
        self.assertIn(SPECIMEN_TITLE, export.to_csv().decode("utf-8-sig").splitlines()[0])
        first_page = extract_text(io.BytesIO(export.to_pdf()), page_numbers=[0])
        self.assertIn(SPECIMEN_TITLE, " ".join(first_page.split()))

    # -- The tank -----------------------------------------------------------------------------
    def test_the_tank_mix_is_one_tank_of_full_records(self):
        tank = list(self._sprays().filter(tank_mix_group__isnull=False).order_by("tank_mix_line", "history__name"))
        self.assertEqual(len({event.tank_mix_group for event in tank}), 1, "one tank")
        # Two products on two blocks: four full records, one per product and per block.
        self.assertEqual(len(tank), 4)
        self.assertEqual({event.history.parcel.name for event in tank}, {"Block 1 Gala", "Block 2 Gala"})
        self.assertEqual(
            sorted((e.tank_mix_line, e.tank_mix_role) for e in tank),
            [
                (1, "product"),
                (1, "product"),
                (2, "adjuvant"),
                (2, "adjuvant"),
            ],
        )
        for event in tank:
            with self.subTest(line=event.tank_mix_line, block=event.block_id):
                # Each line is a full record of its own: product, basis and listing, and the pass's
                # shared facts copied onto it.
                self.assertTrue(event.commercial_name)
                self.assertIn(event.organic_approved, ("wsda_listed", "omri_listed"))
                self.assertTrue(event.wsda_material_id or event.omri_product_id)
                self.assertEqual(event.date.date().isoformat(), "2026-06-12")
                self.assertEqual((event.wind_from, event.carrier_volume), ("NW", Decimal("100")))
                self.assertEqual(event.applicator_name, "Dan Tollefsen")
                self.assertTrue(tank_cell_text(event).startswith(f"line {event.tank_mix_line} of 2"))
        line_one = [e for e in tank if e.tank_mix_line == 1]
        self.assertEqual({e.commercial_name for e in line_one}, {"Entrust SC"})
        self.assertEqual({e.application_rate for e in line_one}, {Decimal("6")})
        # Each line has its own application group across the two blocks; the tank is not one.
        groups = {line: {e.application_group for e in tank if e.tank_mix_line == line} for line in (1, 2)}
        self.assertEqual([len(g) for g in groups.values()], [1, 1])
        self.assertNotEqual(groups[1], groups[2])

    # -- The paper sheet's blanks -------------------------------------------------------------
    def test_the_paper_sheets_blanks_stay_blank(self):
        cyd_x = list(self._sprays().filter(commercial_name="Cyd-X"))
        # "mid May" has no date and is not recorded; the May 29 cover is, on all four bearing blocks.
        self.assertEqual({e.date.date().isoformat() for e in cyd_x}, {"2026-05-29"})
        self.assertEqual(len(cyd_x), 4)
        for event in cyd_x:
            self.assertTrue(event.time_not_recorded)
            self.assertTrue(event.concentration_not_recorded)
            self.assertFalse(event.concentration)
            self.assertIsNone(event.application_rate, "'3oz' has no basis on the sheet")
        # The duplicated June 3 Surround row is one application.
        self.assertEqual(self._sprays().filter(commercial_name="Surround WP").count(), 1)
        # The neighbor's Roundup is a possible drift incident, never this farm's input.
        self.assertFalse(self._sprays().filter(commercial_name__icontains="roundup").exists())
        incident = GeneralEvent.objects.get(history__parcel__establishment=self.est, is_contamination_incident=True)
        self.assertEqual(incident.contamination_source, "spray_drift")
        # The sheet gives no EPA number, REI, PHI or total amount for any spray.
        self.assertFalse(self._sprays().filter(epa_registration_number__gt="").exists())
        self.assertFalse(self._sprays().filter(volume_numeric__isnull=False).exists())
        # Honeycrisp is still picking: no harvest record, and its season stays open.
        block_3 = History.objects.get(parcel__establishment=self.est, parcel__name="Block 3 Honeycrisp")
        self.assertIsNone(block_3.finish_date)
        self.assertFalse(ProductionEvent.objects.filter(history=block_3, type="HA").exists())

    def test_the_washington_export_builds_and_names_its_blank_items(self):
        export = WASprayRecordService.for_year(self.est, 2026)
        passes = export.build()
        # A tank prints once per block with both of its products.
        tanks = [p for p in passes if p.is_tank]
        self.assertEqual(len(tanks), 2)
        self.assertTrue(all(len(p.products) == 2 for p in tanks))
        # No spray on the sheet carries an EPA number, and the export says so on every pass.
        self.assertTrue(all("d" in p.blank_items() for p in passes))
        cover = [p for p in passes if p.events[0].commercial_name == "Cyd-X"]
        self.assertEqual(len(cover), 4)
        for application in cover:
            # No time, no concentration and no carrier on the source: (c) and (h) are named.
            self.assertIn("c", application.blank_items())
            self.assertIn("h", application.blank_items())
            self.assertIn("Items not on this record:", application.blank_line())
        csv_text = export.to_csv().decode("utf-8-sig")
        self.assertIn("Not on the source record", csv_text)
        self.assertIn(NOT_RECORDED, csv_text)
        self.assertTrue(export.to_pdf().startswith(b"%PDF"))

    # -- The packet ---------------------------------------------------------------------------
    def test_the_wsda_packet_builds(self):
        osp = OrganicSystemPlan.objects.get(establishment=self.est)
        self.assertEqual(osp.certifier_name, AGENT_NAME)
        packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        names = set(packet.namelist())
        for expected in (
            "00-cover.pdf",
            "02s-renewal-status-and-routing.pdf",
            "06-question-index.pdf",
            "workbooks/Input Material List - WSDA AGR 2196.xlsx",
            "parcels/parcel-application-Block 5 Honeycrisp _transition_.pdf",
        ):
            self.assertIn(expected, names)
        self.assertEqual(len([n for n in names if n.startswith("parcels/parcel-application-")]), len(BLOCKS))
        routing = " ".join(extract_text(io.BytesIO(packet.read("02s-renewal-status-and-routing.pdf"))).split())
        self.assertIn("renews certification on its own forms", routing)
