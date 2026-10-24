"""CCOF's Crop Update and WSDA's Site Update read off the land as it is, so 02s prints that land.

WHY THIS EXISTS
---------------
The OTCO renewal work (back #216-#220) left edits to existing parcels as "not compared": parcels are
kept with the operation, not with a plan version, so there is no earlier state to compare against.
Reading the two forms that need it showed neither asks for a comparison. ORGB88 is a table of each
certified parcel's crops (current or planned within 12 months) and acres; AGR 2516 accepts
production or planting records that show the site number and name. Both are answerable from the
parcel, its crop history for this year and next, and the certificate's number for it.

Red lines pinned here: only parcels the parcel application routes to these forms are rows; a parcel
filed elsewhere is named with the form it is filed on; a missing number or a year with no crop says
so; WSDA's page never says which site changed; no other agent's packet prints the table.
"""

import io
import zipfile
from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.renewal_land_table import land_table
from company.models import Company, Establishment
from history.models import History
from product.models import Parcel, ParcelCropHistory, Product

from .test_renewal_packet_contents import _pdf_text


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Land Table Orchards LLC")
        self.est = Establishment.objects.create(name="Land Table Orchard", company=self.company)
        self.year = timezone.localdate().year

    def _plan(self, certifier):
        return OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", approval_certifier_name=certifier
        )

    def _parcel(self, name, hectares=5.0, **answers):
        return Parcel.objects.create(name=name, establishment=self.est, area=hectares, application_answers=answers)

    def _crop(self, parcel, year, crop, method="organic", **extra):
        ParcelCropHistory.objects.create(parcel=parcel, year=year, crop_grown=crop, production_method=method, **extra)

    def _supplement(self, osp) -> str:
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        return _pdf_text(zf.read("02s-renewal-status-and-routing.pdf"))


class CcofCropUpdateTests(_Farm):
    def setUp(self):
        super().setUp()
        home = self._parcel(
            "Home Ranch",
            currently_certified="yes",
            prior_certifier_name="CCOF",
            prior_certificate_site_number="#01",
        )
        self._crop(home, self.year, "Apples", cover_crop="clover")
        self._crop(home, self.year + 1, "Apples")
        self._crop(home, self.year - 1, "Pears")
        self._parcel("Bought Block", currently_certified="yes", prior_certifier_name="WSDA")
        self._parcel("Transition Field", currently_certified="no")
        self.osp = self._plan("CCOF")

    def test_a_parcel_on_ccofs_certificate_is_a_row_with_its_number_crops_and_acres(self):
        table = land_table(self.osp)
        self.assertEqual([row.name for row in table.rows], ["Home Ranch"])
        row = table.rows[0]
        self.assertEqual(row.number, "#01")
        self.assertAlmostEqual(row.acres, 5.0 * Parcel.HECTARES_TO_ACRES)
        # Last year's crop is not "current or planned within the next 12 months".
        self.assertEqual(
            row.crops,
            ((self.year, "Apples (organic); cover: clover"), (self.year + 1, "Apples (organic)")),
        )
        text = self._supplement(self.osp)
        self.assertIn("Crop Update (ORGB88): parcels, crops and acres", text)
        self.assertIn(
            f"Home Ranch, CCOF parcel # #01, 12.4 acres: {self.year} Apples (organic); cover: clover; "
            f"{self.year + 1} Apples (organic).",
            text,
        )
        self.assertNotIn("Pears", text)

    def test_a_parcel_filed_elsewhere_is_named_with_the_form_it_is_filed_on(self):
        excluded = dict(land_table(self.osp).excluded)
        self.assertIn("Parcel Application (ORGB49)", excluded["Bought Block"])
        self.assertIn("does not state it is currently certified", excluded["Transition Field"])
        text = self._supplement(self.osp)
        self.assertIn("Not in this table: Bought Block, new to the operation's CCOF file", text)

    def test_acres_are_said_to_be_the_parcels_total_not_per_crop(self):
        self.assertIn("Trazo does not record acreage per crop", self._supplement(self.osp))


class WsdaSiteUpdateTests(_Farm):
    def setUp(self):
        super().setUp()
        north = self._parcel("North Block", currently_certified="yes", prior_certifier_name="WSDA")
        self._crop(north, self.year, "Cherries")
        self._crop(north, self.year + 1, "Cherries", method="conventional")
        self._parcel("Unnamed Cert", currently_certified="yes")
        self.osp = self._plan("Washington State Department of Agriculture")

    def test_a_missing_number_and_a_year_without_a_crop_say_so(self):
        south = self._parcel(
            "South Block",
            currently_certified="yes",
            prior_certifier_name="WSDA",
            prior_certificate_site_number="S-112",
        )
        self._crop(south, self.year, "Pears")
        text = self._supplement(self.osp)
        self.assertIn("North Block, WSDA site no. not recorded (add it on the parcel's application", text)
        self.assertIn(
            f"South Block, WSDA site no. S-112, 12.4 acres: {self.year} Pears (organic); "
            f"{self.year + 1} no crop recorded.",
            text,
        )

    def test_a_year_marked_conventional_is_flagged_as_acreage_that_may_leave(self):
        row = land_table(self.osp).rows[0]
        self.assertEqual(row.conventional_years, (self.year + 1,))
        self.assertIn(f"Marked conventional for {self.year + 1}", self._supplement(self.osp))

    def test_the_page_never_says_which_site_changed(self):
        text = self._supplement(self.osp)
        self.assertIn("Site Update Information (AGR 2516): sites, crops and acres", text)
        self.assertIn("Trazo does not hold WSDA's profile, so it does not say which sites changed", text)

    def test_a_parcel_naming_no_certifier_is_left_out_and_said_why(self):
        self.assertIn("Unnamed Cert", dict(land_table(self.osp).excluded))


class SameLandHistoryAsTheParcelPageTests(_Farm):
    def test_a_logged_season_with_no_typed_row_is_not_no_crop(self):
        """Review of back #221: the table read the typed rows only, so a year with a logged season
        printed "no crop recorded" while the parcel's own page in the same packet showed the crop."""
        parcel = self._parcel("Season Block", currently_certified="yes", prior_certifier_name="CCOF")
        History.objects.create(
            name=f"{self.year} apples",
            parcel=parcel,
            product=Product.objects.create(name="Apples"),
            start_date=timezone.make_aware(datetime(self.year, 3, 1, 9, 0)),
            finish_date=timezone.make_aware(datetime(self.year, 9, 30, 9, 0)),
        )
        row = land_table(self._plan("CCOF")).rows[0]
        self.assertEqual(row.years_without_crop, (self.year + 1,))
        self.assertEqual(len(row.crops), 1)
        self.assertEqual(row.crops[0][0], self.year)
        self.assertIn("Apples", row.crops[0][1])
        self.assertTrue(row.crops[0][1].endswith("(from logged seasons)"))

    def test_the_page_says_the_name_is_trazos_and_next_year_is_what_is_recorded(self):
        self._parcel("Home Ranch", currently_certified="yes", prior_certifier_name="CCOF")
        text = self._supplement(self._plan("CCOF"))
        self.assertIn("The name is the parcel's name in Trazo; the form wants the name as on the certificate.", text)
        self.assertIn("crops planned but not recorded are the operation's to add", text)


class OnlyTheseAgentsTests(_Farm):
    def test_no_other_agent_prints_the_table(self):
        self._parcel("Home Ranch", currently_certified="yes", prior_certifier_name="Oregon Tilth")
        for certifier in ("Oregon Tilth Certified Organic", "Organic Certifiers, Inc."):
            with self.subTest(certifier):
                OrganicSystemPlan.objects.filter(establishment=self.est).delete()
                osp = self._plan(certifier)
                self.assertIsNone(land_table(osp))
                text = self._supplement(osp)
                self.assertNotIn("parcels, crops and acres", text)
                self.assertNotIn("sites, crops and acres", text)
