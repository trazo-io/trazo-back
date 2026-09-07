"""No invented identifier is ever presented as a government registration.

Three catalogues, three different answers, and only one of them gives Trazo a number
it may print (2026-09-06):

    OMRI      REAL. `dow-2900` is OMRI's own published format and deep-links to a live
              certificate. Printed, and pinned here so a cleanup does not remove it.
    WSDA      The real key is the list's `WSDA Product #` column — a BARE INTEGER.
              Trazo's seeded `WSDA-REG-BIOAG-2025-001` strings are fabricated; a
              certifier who searches for one finds nothing.
    CDFA OIM  The published Registered OIM Products list has three columns — Firm,
              Product Name, Annotations — and NO identifier. Every `CDFA-OIM-*` value
              was invented, so a registered row says "registered" and stops there.

Plus the two IngestionRun-status defects that let a failed catalog sync print on the
certifier packet as a refresh.
"""

from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

import requests

from certifications.models import IngestionRun, OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.serializers import _ApprovedOMRIInline, _ApprovedWSDAInline
from certifications.services.drift_detector import CDFA_OIM_REGISTERED, CDFA_OIM_UNKNOWN, _resolved_input_cdfa_status
from certifications.services.plan_materials import plan_materials
from certifications.services.registry_identifiers import wsda_identifier_label, wsda_product_number
from company.models import Company, Establishment

FABRICATED_WSDA_IDS = (
    "WSDA-REG-BIOAG-2025-001",
    "WSDA-REG-FERT-2025-016",
    "WSDA-ENT-1",
    "wsda-1123",
    "1123-A",
    "",
    None,
)


class WSDAIdentifierRuleTests(TestCase):
    """One helper decides, so a new render site cannot invent its own rule."""

    def test_a_bare_integer_is_the_only_printable_wsda_identifier(self):
        for real in ("1123", "2948", "3376", " 1123 "):
            self.assertEqual(wsda_product_number(real), real.strip())
            self.assertEqual(wsda_identifier_label(real), f"WSDA Product #{real.strip()}")

    def test_a_fabricated_wsda_id_renders_as_nothing_at_all(self):
        for fake in FABRICATED_WSDA_IDS:
            self.assertEqual(wsda_product_number(fake), "")
            # Not a placeholder, not a dash — a placeholder still tells the reader a
            # number exists somewhere for them to look up.
            self.assertEqual(wsda_identifier_label(fake), "")


class WSDAMaterialRenderTests(TestCase):
    def test_str_drops_a_fabricated_id_and_keeps_a_real_one(self):
        fake = WSDAMaterial.objects.create(wsda_id="WSDA-REG-BIOAG-2025-001", brand_name="Feather Meal 13-0-0")
        real = WSDAMaterial.objects.create(wsda_id="1123", brand_name="Kaligreen")
        self.assertEqual(str(fake), "Feather Meal 13-0-0")
        self.assertEqual(str(real), "Kaligreen (WSDA Product #1123)")

    def test_the_osp_inline_serializer_never_ships_a_fabricated_id(self):
        fake = WSDAMaterial.objects.create(wsda_id="WSDA-REG-FERT-2025-016", brand_name="Mystery Fish 4-4-1")
        real = WSDAMaterial.objects.create(wsda_id="2948", brand_name="AzaMax")
        self.assertIsNone(_ApprovedWSDAInline(fake).data["wsda_id"])
        self.assertEqual(_ApprovedWSDAInline(real).data["wsda_id"], "2948")

    def test_no_serializer_ships_a_cdfa_registration_number(self):
        """CDFA publishes none, so any number on the wire is a Trazo invention."""
        wsda = WSDAMaterial.objects.create(
            wsda_id="3376",
            brand_name="Neptune's Harvest 2-3-1",
            is_cdfa_oim_registered=True,
            cdfa_oim_reg_number="CDFA-OIM-NH-231",
        )
        omri = OMRIProduct.objects.create(
            omri_id="nhf-0644",
            product_name="Neptune's Harvest Fish 2-4-1",
            is_cdfa_oim_registered=True,
            cdfa_oim_reg_number="CDFA-OIM-NH-244",
        )
        wsda_data = _ApprovedWSDAInline(wsda).data
        omri_data = _ApprovedOMRIInline(omri).data
        self.assertNotIn("cdfa_oim_reg_number", wsda_data)
        self.assertNotIn("cdfa_oim_reg_number", omri_data)
        # The boolean survives — "CDFA OIM registered" is the whole claim, and OMRI's
        # own real code survives too.
        self.assertTrue(wsda_data["is_cdfa_oim_registered"])
        self.assertEqual(omri_data["omri_id"], "nhf-0644")


class PlanMaterialsIdentifierTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Blue Oak Orchards")
        self.establishment = Establishment.objects.create(name="Home Ranch", company=company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.establishment, status="active", version_number=1)

    def _identifiers(self):
        return {row.source: row.identifier for row in plan_materials(self.osp)}

    def test_a_fabricated_wsda_id_never_reaches_the_materials_list(self):
        self.osp.approved_wsda_materials.add(
            WSDAMaterial.objects.create(
                wsda_id="WSDA-REG-BIOAG-2025-001",
                brand_name="Feather Meal 13-0-0",
                manufacturer="BioAg",
            )
        )
        rows = plan_materials(self.osp)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identifier, "")
        self.assertNotIn("WSDA-REG", rows[0].display())
        # The name and manufacturer still print — the row is not suppressed, only the
        # identifier we cannot stand behind.
        self.assertEqual(rows[0].display(), "Feather Meal 13-0-0 — BioAg")

    def test_a_real_wsda_product_number_is_labelled_as_one(self):
        self.osp.approved_wsda_materials.add(
            WSDAMaterial.objects.create(wsda_id="1123", brand_name="Kaligreen", manufacturer="OHP")
        )
        self.assertEqual(self._identifiers()["WSDA"], "WSDA Product #1123")

    def test_omri_codes_are_real_and_stay(self):
        self.osp.approved_omri_products.add(
            OMRIProduct.objects.create(omri_id="dow-2900", product_name="Entrust SC", manufacturer="Corteva")
        )
        self.assertEqual(self._identifiers()["OMRI"], "OMRI #dow-2900")


class CDFAThirdStateTests(TestCase):
    """Absence from a 17-row reference file is not evidence of non-registration."""

    def test_a_registered_row_carries_no_number(self):
        product = OMRIProduct.objects.create(
            omri_id="ttc-17486",
            product_name="Tiger 90CR",
            is_cdfa_oim_registered=True,
            cdfa_oim_reg_number="CDFA-OIM-DTE-FM",
        )
        status = _resolved_input_cdfa_status(product)
        self.assertEqual(status, {"status": CDFA_OIM_REGISTERED})

    def test_an_unlisted_row_is_unknown_not_missing(self):
        product = OMRIProduct.objects.create(omri_id="moi-2794", product_name="Mystery Brand")
        self.assertEqual(_resolved_input_cdfa_status(product), {"status": CDFA_OIM_UNKNOWN})


class CatalogSyncFailureSignallingTests(TestCase):
    """A failed sync must be RECORDED as a failure, not as a refresh.

    The eCFR command reported network failure and non-200 by writing to stderr and
    returning; the orchestrator captures stdout only and inferred success from
    `"CHANGED" in output`, so a 404 was stored as `status="unchanged", ran_at=now` and
    printed on the certifier packet as a catalog synced today.
    """

    def test_a_non_200_raises_instead_of_returning_quietly(self):
        response = mock.Mock(status_code=404, text="")
        with mock.patch("requests.get", return_value=response):
            with self.assertRaises(CommandError):
                call_command("sync_national_list_ecfr")

    def test_a_network_error_raises_instead_of_returning_quietly(self):
        with mock.patch("requests.get", side_effect=requests.ConnectionError("boom")):
            with self.assertRaises(CommandError):
                call_command("sync_national_list_ecfr")

    def test_the_orchestrator_records_a_failed_ecfr_fetch_as_an_error(self):
        response = mock.Mock(status_code=503, text="")
        with mock.patch("requests.get", return_value=response):
            call_command("refresh_organic_input_catalogs")
        run = IngestionRun.objects.filter(source="national_list_ecfr").order_by("-ran_at").first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "error")

    def test_the_orchestrator_reads_the_return_value_not_the_stdout_prose(self):
        # A successful fetch whose text happens to contain the word CHANGED must not be
        # mistaken for a regulation change — and must not be mistaken for a failure.
        response = mock.Mock(status_code=200, text='<DIV8 N="205.601">CHANGED</DIV8>')
        with mock.patch("requests.get", return_value=response):
            call_command("refresh_organic_input_catalogs")
        run = IngestionRun.objects.filter(source="national_list_ecfr").order_by("-ran_at").first()
        self.assertEqual(run.status, "unchanged")
