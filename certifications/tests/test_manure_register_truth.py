"""Compost and raw manure rows, read against the code as it stands (2026-11-18).

CCOF G4.1 B2, OTCO C4 4.3-4 and WSDA AGR 2121 D 13a were partial for one reason: blueberries, caneberries, kiwi and
hops sat on the 120-day floor, so the records refused 90 days and the packet cited § 205.203(c)(1)(ii) where (iii)
applies. Back PR 452 states the class per crop (seeder plus carbon 0056); the floor and the citation follow it.

CCOF G4.1 A1 ("are all of these materials on your Grower Materials Application?") was partial because the fertilizer
listing read only fertilizer applications, never the soil amendments where compost and manure are logged; the gate
reads them now. Its other half, the two ways G4.1 says "none of these are used" (the module's not-applicable and the
`none` option), each now print a [REVIEW] line when the soil records name compost, manure, composting or grazing.
"""

import io
from datetime import date, timedelta
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import yaml
from pdfminer.high_level import extract_text

from carbon.models import CropType
from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.attestation_gates import blocked_attestations
from certifications.services.compost_manure_review import none_used_lines
from certifications.services.osp_module_pdf import generate_module_pdf
from company.models import Company, Establishment
from history.models import Production, SoilManagementEvent
from history.services.manure_interval import minimum_interval_cite, minimum_interval_days
from product.models import Parcel
from users.models import User

G40 = MODULES_BY_KEY["g4_0_rotation_soil"]


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="manure@test.com", password="x", is_verified=True)
        company = Company.objects.create(name="Yakima Ridge LLC")
        self.est = Establishment.objects.create(name="Yakima Ridge", company=company, state="WA")
        parcel = Parcel.objects.create(name="Gala Block", establishment=self.est, area=8.0)
        self.history = Production.objects.create(
            name="Gala 2026", start_date=timezone.now(), parcel=parcel, operator=self.user
        )
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")

    def _soil(self, type_code, when=None, **fields):
        with self.captureOnCommitCallbacks(execute=True):
            return SoilManagementEvent.objects.create(
                history=self.history, type=type_code, date=when or timezone.now(), **fields
            )

    def _g41(self, **entry):
        self.osp.module_responses = {"schema_version": 1, "modules": {"g4_1_compost_manure": entry}}
        self.osp.save(update_fields=["module_responses"])
        return _text(generate_module_pdf(self.osp, "g4_1_compost_manure"))


class NoneUsedIsReadAgainstTheSoilRecords(_Farm):
    def test_a_not_applicable_over_a_compost_record_prints_a_review_naming_it(self):
        day = timezone.now() - timedelta(days=30)
        self._soil(
            "OM", when=day, amendment_type="Organic matter", amendment_product_name="Composted Poultry Manure 3-2-2"
        )
        text = self._g41(not_applicable=True, na_attestation={"by": self.user.pk, "at": "2026-11-18T10:00:00Z"})
        self.assertIn(
            f"[REVIEW] G4.1 is marked not applicable, but 1 soil record ({day.date().isoformat()}) names compost, "
            "manure or grazing: Composted Poultry Manure 3-2-2.",
            text,
        )

    def test_the_none_option_over_a_raw_manure_record_prints_a_review(self):
        self._soil("OM", manure_harvest_interval="120", manure_application_date=date(2026, 3, 2))
        self._soil("GR")
        text = self._g41(answers={"materials_applied": {"value": ["none"]}})
        self.assertIn("[REVIEW] G4.1 answers that none of these materials are used, but 2 soil records", text)
        self.assertIn("name compost, manure or grazing: grazing record, raw manure record.", text)

    def test_records_that_are_not_g4_1_material_print_nothing(self):
        self._soil("PA", amendment_type="Gypsum", amendment_product_name="Gypsum 22% Ca")
        self._soil("CC", amendment_type="Cover crop")
        self.assertEqual(none_used_lines(self.osp, "not_applicable"), [])
        text = self._g41(answers={"materials_applied": {"value": ["none"]}})
        self.assertNotIn("[REVIEW] G4.1", text)

    def test_a_plan_that_names_the_compost_it_uses_prints_nothing(self):
        self._soil("CO", amendment_product_name="On-farm windrow compost")
        text = self._g41(answers={"materials_applied": {"value": ["on_farm_compost"]}})
        self.assertNotIn("[REVIEW] G4.1", text)


class TheFertilityListingReadsSoilAmendments(_Farm):
    def test_a_yes_is_refused_while_a_logged_compost_is_not_on_the_materials_list(self):
        self._soil("OM", amendment_type="Compost", amendment_product_name="Rexius Organic Compost")
        blocked = blocked_attestations(G40, {"fertility_inputs_listed": True}, self.osp)
        self.assertIn("fertility_inputs_listed", blocked)
        self.assertIn("Rexius Organic Compost", blocked["fertility_inputs_listed"])


class TheFloorFollowsTheCropsClass(TestCase):
    def test_berries_and_hops_held_off_the_ground_take_90_days_and_cite_iii(self):
        call_command("populate_usda_crop_types", "--crops-only", verbosity=0)
        for slug in ("blueberries", "hops"):
            crop = CropType.objects.get(slug=slug)
            self.assertEqual(minimum_interval_days(crop), 90, slug)
            self.assertEqual(minimum_interval_cite(crop), "§ 205.203(c)(1)(iii)", slug)
        strawberries = CropType.objects.get(slug="strawberries")
        self.assertEqual(minimum_interval_cite(strawberries), "§ 205.203(c)(1)(ii)")


class TheRegisterRowsAreClosed(SimpleTestCase):
    ROWS = {
        "ccof/forms/G4.1-compost-manure.yaml": ("A1", "B2"),
        "otco/forms/C4-soil-crop-fertility-management.yaml": ("4.3-4",),
        "wsda/forms/2121-D-soil-fertility.yaml": ("13a",),
    }

    def test_every_row_is_covered_and_cites_questions_that_exist(self):
        root = Path(__file__).resolve().parents[2] / "documentation/compliance/certifiers"
        keys = {f"{m.key}.{q.key}" for m in MODULES_BY_KEY.values() for page in m.pages for q in page.questions}
        for path, refs in self.ROWS.items():
            items = yaml.safe_load((root / path).read_text())["items"]
            for ref in refs:
                row = next(i for i in items if str(i["ref"]) == ref)
                self.assertEqual(row["status"], "covered", f"{path} {ref}")
                for cited in row["trazo"]["questions"]:
                    self.assertIn(cited, keys, f"{path} {ref}")
