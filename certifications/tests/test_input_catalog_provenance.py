"""
Guards on the three organic-input catalogs — written to be NON-CIRCULAR.

`test_omri_seeder.py` seeds the committed CSV and then asserts the CSV's own contents
are in the database. That passes whatever the CSV says, so it could not detect the
defects found on 2026-09-06: 42 WSDA rows under identifiers WSDA does not issue, 17
invented CDFA registration numbers, 5 lapsed OMRI listings and 45 wrong name/company
strings. A round-trip test cannot tell a right row from a wrong one.

These guards instead assert properties the PUBLISHERS define, which a hand-typed row
fails:

  * a WSDA identifier is the list's own Product #, a bare integer;
  * an OMRI identifier is OMRI's published code shape;
  * CDFA publishes no identifier at all, so nothing may write one;
  * a row must say which document and edition it came from;
  * the demo fixture's plan wiring must resolve to rows that exist.
"""

import csv
import json
import os
import re
import tempfile
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from certifications.models import OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.services.omri_verifier import looks_like_omri_code
from certifications.services.registry_identifiers import is_real_wsda_product_number
from company.models import Company, Establishment

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_FIXTURE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "history",
    "management",
    "commands",
    "_calapooia_bend_data.json",
)


def _rows(name):
    with open(os.path.join(_DATA, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class CommittedSeedShapeTests(TestCase):
    """The committed CSVs must carry only identifiers the publishers actually issue."""

    def test_every_wsda_id_is_a_bare_product_number(self):
        bad = [r["wsda_id"] for r in _rows("wsda_seed.csv") if not re.fullmatch(r"\d+", r["wsda_id"])]
        self.assertEqual(
            bad,
            [],
            "WSDA's key column is the 'WSDA Product #', a bare integer. Anything else is a "
            "Trazo invention and `registry_identifiers` withholds it from every reader, so "
            "the row can never be cited in a packet.",
        )

    def test_every_omri_id_matches_omris_published_code_shape(self):
        bad = [r["omri_id"] for r in _rows("omri_seed.csv") if not looks_like_omri_code(r["omri_id"])]
        self.assertEqual(
            bad,
            [],
            "OMRI publishes company letters + hyphen + product number (dow-2900), documented "
            "at https://www.omri.org/using-omri-search. Shape is defined once, in "
            "certifications.services.omri_verifier.",
        )

    def test_no_seed_carries_a_cdfa_registration_number(self):
        """CDFA's published list has three columns and none of them is an identifier."""
        for name in ("cdfa_oim_seed.csv", "omri_seed.csv", "wsda_seed.csv"):
            with self.subTest(csv=name):
                columns = set(_rows(name)[0].keys())
                offenders = {c for c in columns if "reg_number" in c or "reg-number" in c}
                self.assertEqual(
                    offenders,
                    set(),
                    f"{name} declares {offenders}. CDFA publishes no registration number, so "
                    "there is nothing to put in such a column and every value would be invented.",
                )

    def test_cdfa_seed_is_keyed_on_firm_and_product_name(self):
        rows = _rows("cdfa_oim_seed.csv")
        self.assertGreater(len(rows), 1000)
        self.assertEqual(set(rows[0]), {"firm", "product_name", "annotations", "list_edition_date", "source_url"})
        self.assertFalse([r for r in rows if not r["firm"] or not r["product_name"]])

    def test_every_catalog_row_names_its_source_document_and_edition(self):
        for name, edition_col in (
            ("omri_seed.csv", "list_edition_date"),
            ("wsda_seed.csv", "list_effective_date"),
            ("cdfa_oim_seed.csv", "list_edition_date"),
        ):
            with self.subTest(csv=name):
                rows = _rows(name)
                self.assertTrue(all(r["source_url"].startswith("https://") for r in rows))
                self.assertTrue(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[edition_col]) for r in rows))

    def test_no_fabricated_identifier_pattern_survives_anywhere_in_the_seeds(self):
        """The exact shapes the audit found invented, as literals, so they cannot return."""
        for name in ("omri_seed.csv", "wsda_seed.csv", "cdfa_oim_seed.csv"):
            with self.subTest(csv=name):
                blob = open(os.path.join(_DATA, name), encoding="utf-8").read()
                for shape in ("WSDA-REG-", "CDFA-OIM-", "OMRI-SVR-"):
                    self.assertNotIn(shape, blob)


class SeederRefusesUnpublishableIdentifiersTests(TestCase):
    """A seeder must refuse a row it could not have read off a published list."""

    def _run_with(self, command, module, rows, fieldnames):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        fh.close()
        with mock.patch(f"certifications.management.commands.{module}._DATA_FILE", fh.name):
            call_command(command, verbosity=0)
        os.unlink(fh.name)

    def test_wsda_seeder_refuses_a_fabricated_registration_string(self):
        self._run_with(
            "seed_wsda_materials",
            "seed_wsda_materials",
            [
                {"wsda_id": "WSDA-REG-BIOAG-2025-003", "brand_name": "Serenade Opti"},
                {"wsda_id": "2072", "brand_name": "Entrust SC"},
            ],
            ["wsda_id", "brand_name"],
        )
        self.assertFalse(WSDAMaterial.objects.filter(wsda_id="WSDA-REG-BIOAG-2025-003").exists())
        self.assertTrue(WSDAMaterial.objects.filter(wsda_id="2072").exists())

    def test_omri_seeder_refuses_an_id_that_is_not_an_omri_code(self):
        self._run_with(
            "seed_omri_minimal",
            "seed_omri_minimal",
            [
                {"omri_id": "OMRI-SVR-ENTRUST", "product_name": "Entrust SC Naturalyte Insect Control"},
                {"omri_id": "dow-2900", "product_name": "Entrust SC Naturalyte Insect Control"},
            ],
            ["omri_id", "product_name"],
        )
        self.assertFalse(OMRIProduct.objects.filter(omri_id="OMRI-SVR-ENTRUST").exists())
        self.assertTrue(OMRIProduct.objects.filter(omri_id="dow-2900").exists())


class CdfaTaggingIsExactNotFuzzyTests(TestCase):
    """The regression that made this task necessary.

    `seed_cdfa_oim` used to call the token-subsequence matcher and PERSIST the winner, so
    a CDFA row for *Kelp Meal 1-0.2-2* stamped a registration onto OMRI's *Kelp Meal
    1-0.1-2* — a different registered product. The fuzzy matcher is right for search and
    wrong as a persisted claim.
    """

    @classmethod
    def setUpTestData(cls):
        cls.near_miss = OMRIProduct.objects.create(
            omri_id="det-21293",
            product_name="Down To Earth All Natural Kelp Meal 1-0.1-2",
        )
        cls.exact = OMRIProduct.objects.create(
            omri_id="det-2187",
            product_name="Down To Earth All Natural Fertilizer Crab Meal 4-3-0",
        )

    def _seed(self, rows):
        fh = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8")
        writer = csv.DictWriter(fh, fieldnames=["firm", "product_name", "annotations"])
        writer.writeheader()
        writer.writerows(rows)
        fh.close()
        with mock.patch("certifications.management.commands.seed_cdfa_oim._DATA_FILE", fh.name):
            call_command("seed_cdfa_oim", verbosity=0)
        os.unlink(fh.name)

    def test_a_near_miss_brand_name_does_not_tag_a_different_product(self):
        self._seed(
            [
                {
                    "firm": "DOWN TO EARTH DISTRIBUTORS INC",
                    "product_name": "Down To Earth All Natural Kelp Meal 1-0.2-2",
                    "annotations": "",
                }
            ]
        )
        self.near_miss.refresh_from_db()
        self.assertFalse(
            self.near_miss.is_cdfa_oim_registered,
            "1-0.2-2 and 1-0.1-2 are different registered products; a guessed match must "
            "never be written as a registration claim.",
        )

    def test_an_exactly_matching_name_tags_and_writes_no_number(self):
        self._seed(
            [
                {
                    "firm": "DOWN TO EARTH DISTRIBUTORS INC",
                    "product_name": "down to earth all natural fertilizer crab meal 4-3-0",
                    "annotations": "",
                }
            ]
        )
        self.exact.refresh_from_db()
        self.assertTrue(self.exact.is_cdfa_oim_registered)
        self.assertIsNone(
            self.exact.cdfa_oim_reg_number,
            "CDFA publishes no registration number, so the seeder may not invent one.",
        )

    def test_an_ambiguous_name_tags_nothing(self):
        OMRIProduct.objects.create(omri_id="det-9999", product_name="Duplicate Name Product")
        OMRIProduct.objects.create(omri_id="det-9998", product_name="Duplicate Name Product")
        self._seed([{"firm": "ANY FIRM", "product_name": "Duplicate Name Product", "annotations": ""}])
        self.assertFalse(
            OMRIProduct.objects.filter(product_name="Duplicate Name Product", is_cdfa_oim_registered=True).exists()
        )


class CalapooiaFixtureWiringTests(TestCase):
    """The demo fixture's plan wiring must resolve to catalog rows that exist."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.data = json.load(open(_FIXTURE, encoding="utf-8"))

    def test_every_plan_reference_resolves_to_a_defined_catalog_row(self):
        defined = {
            "approved_omri_products": set(self.data["approved_input_rows"]["OMRIProduct"]),
            "approved_wsda_materials": set(self.data["approved_input_rows"]["WSDAMaterial"]),
            "approved_national_list_substances": set(self.data["approved_input_rows"]["NationalListSubstance"]),
        }
        for osp in self.data["osps"]:
            for m2m, keys in defined.items():
                missing = set(osp.get("~" + m2m, [])) - keys
                self.assertEqual(missing, set(), f"OSP {osp['_id']} {m2m} references undefined rows")

    def test_fixture_catalog_rows_carry_publisher_identifiers(self):
        for name, row in self.data["approved_input_rows"]["OMRIProduct"].items():
            with self.subTest(product=name):
                self.assertTrue(looks_like_omri_code(row["omri_id"]), row["omri_id"])
                self.assertEqual(row["product_name"], name)
        for name, row in self.data["approved_input_rows"]["WSDAMaterial"].items():
            with self.subTest(product=name):
                self.assertTrue(is_real_wsda_product_number(row["wsda_id"]), row["wsda_id"])

    def test_fixture_omri_rows_are_in_the_committed_seed(self):
        seeded = {r["omri_id"]: r["product_name"] for r in _rows("omri_seed.csv")}
        for name, row in self.data["approved_input_rows"]["OMRIProduct"].items():
            with self.subTest(product=name):
                self.assertIn(row["omri_id"], seeded)
                self.assertEqual(seeded[row["omri_id"]], name)

    def test_the_retired_vouching_sentence_is_gone(self):
        blob = open(_FIXTURE, encoding="utf-8").read()
        self.assertNotIn(
            "Each was resolved against OMRI",
            blob,
            "osp_module_compiler removed this sentence on 2026-08-28: it vouched for the whole "
            "list, which became false the moment operator-entered rows shipped.",
        )
        self.assertIn("Each line states the basis on which it appears", blob)


class RepairCommandTests(TestCase):
    """Repairing an already-seeded database must not cost a plan its approved input."""

    def setUp(self):
        company = Company.objects.create(name="Repair Farm")
        establishment = Establishment.objects.create(name="E1", company=company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=establishment, version_number=1, status="active")

    def test_a_fabricated_wsda_id_is_rekeyed_and_the_plan_link_survives(self):
        mat = WSDAMaterial.objects.create(
            wsda_id="WSDA-REG-BIOAG-2025-012",
            brand_name="Entrust SC",  # this one IS on the published list, as #2072
        )
        self.osp.approved_wsda_materials.add(mat)
        call_command("repair_input_catalogs", "--apply", verbosity=0)
        mat.refresh_from_db()
        self.assertEqual(mat.wsda_id, "2072")
        self.assertIn(mat, self.osp.approved_wsda_materials.all())

    def test_a_false_wsda_listing_on_a_plan_is_remapped_to_its_real_omri_row(self):
        call_command("seed_omri_minimal", verbosity=0)
        mat = WSDAMaterial.objects.create(wsda_id="WSDA-REG-BIOAG-2025-003", brand_name="Serenade Opti")
        self.osp.approved_wsda_materials.add(mat)
        call_command("repair_input_catalogs", "--apply", verbosity=0)
        self.assertFalse(self.osp.approved_wsda_materials.exists())
        self.assertEqual(
            [p.omri_id for p in self.osp.approved_omri_products.all()],
            ["gus-5425"],
            "Serenade Opti is an OMRI listing, not a WSDA one. Deleting the row would have "
            "removed an approved input from the plan — itself a § 205.201(a)(2) defect.",
        )

    def test_an_unlisted_row_cited_by_a_plan_is_never_deleted_silently(self):
        mat = WSDAMaterial.objects.create(wsda_id="WSDA-REG-XX-1", brand_name="Not On Any List")
        self.osp.approved_wsda_materials.add(mat)
        call_command("repair_input_catalogs", "--apply", verbosity=0)
        self.assertTrue(WSDAMaterial.objects.filter(pk=mat.pk).exists())
        self.assertIn(mat, self.osp.approved_wsda_materials.all())

    def test_invented_cdfa_numbers_are_cleared(self):
        prod = OMRIProduct.objects.create(
            omri_id="dow-2900",
            product_name="Entrust SC Naturalyte Insect Control",
            is_cdfa_oim_registered=True,
            cdfa_oim_reg_number="CDFA-OIM-DTE-FM",
        )
        call_command("repair_input_catalogs", "--apply", verbosity=0)
        prod.refresh_from_db()
        self.assertIsNone(prod.cdfa_oim_reg_number)

    def test_the_command_is_idempotent(self):
        mat = WSDAMaterial.objects.create(wsda_id="WSDA-REG-BIOAG-2025-012", brand_name="Entrust SC")
        self.osp.approved_wsda_materials.add(mat)
        call_command("repair_input_catalogs", "--apply", verbosity=0)
        before = list(WSDAMaterial.objects.values_list("wsda_id", "brand_name").order_by("wsda_id"))
        call_command("repair_input_catalogs", "--apply", verbosity=0)
        self.assertEqual(list(WSDAMaterial.objects.values_list("wsda_id", "brand_name").order_by("wsda_id")), before)


class FixtureCatalogGuardTests(TestCase):
    """`seed_calapooia_bend` must refuse a fixture row carrying an invented identifier.

    A guard nothing exercises proves nothing, and on a fresh database this seeder CREATES
    the catalog rows it references — so a fixture with a made-up code would define the
    catalogue rather than read it.
    """

    def setUp(self):
        from history.management.commands.seed_calapooia_bend import Command

        self.assert_real = Command._assert_real_catalog_id

    def test_a_fabricated_omri_code_is_refused(self):
        with self.assertRaises(ValueError):
            self.assert_real("OMRIProduct", {"omri_id": "OMRI-SVR-ENTRUST"})

    def test_a_fabricated_wsda_id_is_refused(self):
        with self.assertRaises(ValueError):
            self.assert_real("WSDAMaterial", {"wsda_id": "WSDA-REG-FERT-2025-016"})

    def test_the_real_identifiers_pass(self):
        self.assert_real("OMRIProduct", {"omri_id": "dow-2900"})
        self.assert_real("WSDAMaterial", {"wsda_id": "2072"})

    def test_every_row_in_the_committed_fixture_passes_the_guard(self):
        data = json.load(open(_FIXTURE, encoding="utf-8"))
        for model_name, rows in data["approved_input_rows"].items():
            for name, row in rows.items():
                with self.subTest(model=model_name, product=name):
                    self.assert_real(model_name, row)
