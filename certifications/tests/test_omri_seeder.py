"""
Tests for seed_omri_minimal and seed_omri_from_csv management commands.
"""

import csv
import os
import tempfile

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from certifications.models import OMRIProduct
from certifications.services.omri_verifier import _resolve_omri_by_name


class ResolveOMRIByNameTests(TestCase):
    """Unit tests for the fuzzy farmer-input → OMRIProduct resolver.

    These guard against regressions in the name-matching heuristic that the
    /verify-input/ typeahead AND the drift detector both depend on.
    """

    def setUp(self):
        OMRIProduct.objects.bulk_create(
            [
                OMRIProduct(
                    omri_id="dow-2900",
                    product_name="Entrust SC Naturalyte Insect Control",
                ),
                OMRIProduct(
                    omri_id="mgk-9643",
                    product_name="PyGanic Crop Protection EC 1.4 II",
                ),
                OMRIProduct(
                    omri_id="ttc-17486",
                    product_name="Kocide 3000-O Fungicide Bactericide Dry Flowable",
                ),
                OMRIProduct(
                    omri_id="ttc-17485",
                    product_name="Kocide 2000-O Fungicide Bactericide Dry Flowable",
                ),
                OMRIProduct(
                    omri_id="ttc-09999",
                    product_name="Kocide 50DF",
                ),
                OMRIProduct(
                    omri_id="sip-9019",
                    product_name="Avenger AG Optima Burndown Herbicide",
                ),
                OMRIProduct(
                    omri_id="nhf-0644",
                    product_name="Neptune's Harvest Organic Fish Fertilizer 2-4-1",
                ),
                OMRIProduct(
                    omri_id="nhf-0645",
                    product_name="Neptune's Harvest Organic Fish and Seaweed Fertilizer 2-3-1",
                ),
                OMRIProduct(
                    omri_id="bay-1234",
                    product_name="Serenade ASO",
                ),
            ]
        )

    def test_exact_match(self):
        m = _resolve_omri_by_name("Serenade ASO")
        self.assertIsNotNone(m)
        self.assertEqual(m.product_name, "Serenade ASO")

    def test_strips_parenthetical_descriptor(self):
        """Farmer pasted 'Kocide 3000 (Copper Hydroxide 46.1%)' from the bottle."""
        m = _resolve_omri_by_name("Kocide 3000 (Copper Hydroxide 46.1%)")
        self.assertIsNotNone(m)
        self.assertEqual(m.omri_id, "ttc-17486")

    def test_possessive_apostrophe_s(self):
        """'Neptune Harvest' (no apostrophe) must match the possessive catalog entry."""
        m = _resolve_omri_by_name("Neptune Harvest")
        self.assertIsNotNone(m)
        self.assertIn("Neptune", m.product_name)

    def test_ampersand_normalized_to_and(self):
        m = _resolve_omri_by_name("Neptune's Harvest Fish & Seaweed (2-3-1)")
        self.assertIsNotNone(m)
        self.assertEqual(m.omri_id, "nhf-0645")

    def test_handles_catalog_marketing_middle_tokens(self):
        """Farmer 'PyGanic EC 1.4' vs catalog 'PyGanic Crop Protection EC 1.4 II'."""
        m = _resolve_omri_by_name("PyGanic EC 1.4")
        self.assertIsNotNone(m)
        self.assertEqual(m.omri_id, "mgk-9643")

    def test_single_token_returns_a_brand_match(self):
        """Typing just 'Kocide' returns a Kocide product (which variant is tiebreak)."""
        m = _resolve_omri_by_name("Kocide")
        self.assertIsNotNone(m)
        self.assertTrue(m.product_name.startswith("Kocide"))

    def test_rejects_generic_words(self):
        """'organic fertilizer' must not match Neptune's fertilizer — it's too generic."""
        self.assertIsNone(_resolve_omri_by_name("organic fertilizer"))

    def test_no_match_returns_none(self):
        self.assertIsNone(_resolve_omri_by_name("random unknown product xyz"))

    def test_empty_input_returns_none(self):
        self.assertIsNone(_resolve_omri_by_name(""))
        self.assertIsNone(_resolve_omri_by_name(None))


class SeedOmriMinimalCommandTests(TestCase):
    """Tests for the seed_omri_minimal management command."""

    def test_command_runs_clean_and_creates_rows(self):
        """Running the command from scratch creates at least one row."""
        self.assertEqual(OMRIProduct.objects.count(), 0)
        call_command("seed_omri_minimal", verbosity=0)
        self.assertGreater(OMRIProduct.objects.count(), 0)

    def test_command_idempotent_on_second_run(self):
        """Running twice must not duplicate rows (upsert semantics)."""
        call_command("seed_omri_minimal", verbosity=0)
        count_after_first = OMRIProduct.objects.count()
        self.assertGreater(count_after_first, 0)

        call_command("seed_omri_minimal", verbosity=0)
        count_after_second = OMRIProduct.objects.count()
        self.assertEqual(count_after_first, count_after_second)

    def test_update_on_second_run(self):
        """
        If a row already exists with a different product_name, the second run
        must update it rather than fail or create a duplicate.
        """
        call_command("seed_omri_minimal", verbosity=0)
        # Mutate one row to simulate stale data.
        obj = OMRIProduct.objects.first()
        original_name = obj.product_name
        obj.product_name = "STALE NAME FOR TESTING"
        obj.save()

        call_command("seed_omri_minimal", verbosity=0)

        obj.refresh_from_db()
        self.assertEqual(obj.product_name, original_name)

    def test_known_products_are_present_after_seed(self):
        """Spot-check a few real product names that must be in the minimal seed."""
        call_command("seed_omri_minimal", verbosity=0)
        # These products appear in the committed CSV.
        expected_names = [
            "Entrust SC Naturalyte Insect Control",
            "Neptune's Harvest Organic Fish Fertilizer 2-4-1",
            "Regalia Biofungicide",
        ]
        for name in expected_names:
            with self.subTest(product_name=name):
                self.assertTrue(
                    OMRIProduct.objects.filter(product_name=name).exists(),
                    f"Expected '{name}' to be present after seed_omri_minimal",
                )

    def test_known_omri_ids_are_present_after_seed(self):
        """Spot-check real OMRI IDs from the April 2026 OMRI Products List PDF."""
        call_command("seed_omri_minimal", verbosity=0)
        expected_ids = [
            "dow-2900",  # Entrust SC
            "mgk-9644",  # PyGanic EC 5.0 II
            "moi-1575",  # Regalia Biofungicide
            "nhf-0644",  # Neptune's Harvest Fish Fertilizer
            "bss-3213",  # OxiDate 2.0
        ]
        for omri_id in expected_ids:
            with self.subTest(omri_id=omri_id):
                self.assertTrue(
                    OMRIProduct.objects.filter(omri_id=omri_id).exists(),
                    f"Expected OMRI ID '{omri_id}' to be present after seed",
                )

    def test_reset_flag_clears_existing_rows(self):
        """--reset must delete all existing rows before re-seeding."""
        call_command("seed_omri_minimal", verbosity=0)
        count_before = OMRIProduct.objects.count()
        self.assertGreater(count_before, 0)

        call_command("seed_omri_minimal", reset=True, verbosity=0)
        # Count must still be equal (same rows, freshly inserted).
        self.assertEqual(OMRIProduct.objects.count(), count_before)


class SeedOmriFromCsvCommandTests(TestCase):
    """Tests for the seed_omri_from_csv management command."""

    def _write_csv(self, rows, fieldnames=None):
        """Write a temporary CSV and return its path."""
        fh = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="", encoding="utf-8")
        if fieldnames is None and rows:
            fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        fh.close()
        return fh.name

    def tearDown(self):
        # Clean up temp files created during tests.
        for attr in ("_tmp_csv",):
            path = getattr(self, attr, None)
            if path and os.path.exists(path):
                os.unlink(path)

    def test_valid_csv_creates_rows(self):
        """A well-formed CSV must create OMRIProduct rows."""
        path = self._write_csv(
            [
                {
                    "omri_id": "tst-00001",
                    "product_name": "Test Organic Spray",
                    "manufacturer": "Test Co",
                    "category": "crop-pest-control",
                },
                {
                    "omri_id": "tst-00002",
                    "product_name": "Test Fertilizer",
                    "manufacturer": "Test Co",
                    "category": "crop-fertilizer",
                },
            ]
        )
        self._tmp_csv = path

        call_command("seed_omri_from_csv", path=path, verbosity=0)
        self.assertEqual(OMRIProduct.objects.count(), 2)
        self.assertTrue(OMRIProduct.objects.filter(omri_id="tst-00001").exists())

    def test_idempotent_on_second_run(self):
        """Running twice on the same CSV must not duplicate rows."""
        path = self._write_csv(
            [
                {
                    "omri_id": "tst-00010",
                    "product_name": "Idempotency Test",
                    "manufacturer": "Test Co",
                    "category": "crop-pest-control",
                }
            ]
        )
        self._tmp_csv = path

        call_command("seed_omri_from_csv", path=path, verbosity=0)
        call_command("seed_omri_from_csv", path=path, verbosity=0)
        self.assertEqual(OMRIProduct.objects.count(), 1)

    def test_dry_run_does_not_write_to_db(self):
        """--dry-run must parse the CSV but make zero DB writes."""
        path = self._write_csv(
            [
                {
                    "omri_id": "tst-00020",
                    "product_name": "Dry Run Product",
                    "manufacturer": "Test Co",
                    "category": "crop-pest-control",
                }
            ]
        )
        self._tmp_csv = path

        call_command("seed_omri_from_csv", path=path, dry_run=True, verbosity=0)
        self.assertEqual(OMRIProduct.objects.count(), 0)

    def test_missing_omri_id_column_raises(self):
        """CSV without 'omri_id' column must raise CommandError immediately."""
        path = self._write_csv(
            [{"product_name": "No ID", "manufacturer": "Test Co", "category": "cp"}],
            fieldnames=["product_name", "manufacturer", "category"],
        )
        self._tmp_csv = path

        with self.assertRaises(CommandError) as ctx:
            call_command("seed_omri_from_csv", path=path, verbosity=0)
        self.assertIn("omri_id", str(ctx.exception))

    def test_nonexistent_file_raises(self):
        """A path that does not exist must raise CommandError."""
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "seed_omri_from_csv",
                path="/tmp/does_not_exist_omri.csv",
                verbosity=0,
            )
        self.assertIn("not found", str(ctx.exception).lower())

    def test_extra_columns_are_ignored(self):
        """Extra columns in the CSV must not cause errors."""
        path = self._write_csv(
            [
                {
                    "omri_id": "tst-00030",
                    "product_name": "Extra Column Product",
                    "manufacturer": "Test Co",
                    "category": "crop-pest-control",
                    "notes": "ignored extra column",
                    "expiry_date": "2027-12-31",
                }
            ]
        )
        self._tmp_csv = path

        call_command("seed_omri_from_csv", path=path, verbosity=0)
        self.assertEqual(OMRIProduct.objects.count(), 1)

    def test_reset_flag_clears_before_import(self):
        """--reset must delete existing rows before importing new ones."""
        # Pre-seed a row that is NOT in the test CSV.
        OMRIProduct.objects.create(
            omri_id="old-99999",
            product_name="Old Product",
        )
        path = self._write_csv(
            [
                {
                    "omri_id": "tst-00040",
                    "product_name": "Fresh Import",
                    "manufacturer": "Test Co",
                    "category": "crop-pest-control",
                }
            ]
        )
        self._tmp_csv = path

        call_command("seed_omri_from_csv", path=path, reset=True, verbosity=0)
        # Old row must be gone; new row must be present.
        self.assertFalse(OMRIProduct.objects.filter(omri_id="old-99999").exists())
        self.assertTrue(OMRIProduct.objects.filter(omri_id="tst-00040").exists())
        self.assertEqual(OMRIProduct.objects.count(), 1)
