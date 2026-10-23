"""The operator copies onto the agent's renewal form from one sheet, and 02 counts sales over their period.

WHY THIS EXISTS
---------------
A real renewal packet (Calapooia Bend, v3 to v4, 2026-10-23) read against Oregon Tilth's OSP Update
Form left about eight questions partly answered or not answered by the packet. The packet disclosed
each one, but in 02s, a reviewer's crosswalk inside the ZIP. The operator fills the agent's form
themselves and needs the same facts in the form's order: a value to copy, or plainly "yours".

Step 6 was the one place the packet could mislead. 02 printed a calendar-year subtotal beside a
form that asks for a 12-month period the operation chooses and keeps the same each year. The
operator now states the period on the annual update and 02 counts sales inside it.

Red lines pinned here: the sheet never ticks a box or answers an election (a "yours" row carries no
value), it exists only for an agent whose form is mapped, the figure it gives is the figure 02
printed, and it sits behind the same plan gate as the packet.
"""

import io
import zipfile
from datetime import date, datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APITestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate
from certifications.serializers import OSPAnnualUpdateSerializer
from certifications.services.agent_form_sheet import agent_form_sheet
from certifications.services.annual_update_filing import correct_filing, sign_filing
from certifications.services.osp_fork import fork_plan
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment
from history.models import History, SalesRecord
from product.models import Parcel
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text

OTCO = "Oregon Tilth Certified Organic"


class _Farm(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sheet@test.com", password="x", first_name="Ana", last_name="Diaz")
        self.company = Company.objects.create(name="Sheet Orchards LLC", tradename="Sheet Hill Fruit")
        self.est = Establishment.objects.create(
            name="Sheet Orchard",
            company=self.company,
            contact_person="Ana Diaz",
            contact_email="ana@sheet.example",
            phone="(541) 555-0100",
        )
        self.parcel = Parcel.objects.create(name="Home Block", establishment=self.est, area=10.0)
        self.season = History.objects.create(
            name="2026 apples",
            parcel=self.parcel,
            start_date=datetime(2025, 3, 15, tzinfo=dt_tz.utc),
            finish_date=datetime(2025, 9, 24, tzinfo=dt_tz.utc),
            lot_id="SO-2025",
        )

    def _plan(self, certifier=OTCO):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name=certifier,
            submitted_at=datetime(2026, 1, 10, tzinfo=dt_tz.utc),
        )

    def _filing(self, osp, **kw):
        return OSPAnnualUpdate.objects.create(
            prior_osp=osp, reporting_year=2027, changes_summary="No changes to the plan this year.", **kw
        )

    def _sale(self, when, amount, organic=True):
        return SalesRecord.objects.create(
            production=self.season,
            sale_date=when,
            buyer_name="Sample Packer",
            quantity=Decimal("1000"),
            quantity_unit="lb",
            sale_amount=None if amount is None else Decimal(amount),
            organic_on_invoice=organic,
        )

    def _packet_text(self, osp, name):
        return " ".join(_pdf_text(zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp))).read(name)).split())

    def _rows(self, osp):
        return {row["item"]: row for row in agent_form_sheet(osp)["rows"]}


class SalesPeriodTests(_Farm):
    def test_a_stated_period_counts_only_the_sales_inside_it(self):
        osp = self._plan()
        self._filing(osp, sales_period_start=date(2025, 10, 1), sales_period_end=date(2026, 9, 30))
        self._sale(date(2025, 9, 30), "100.00")  # the day before
        self._sale(date(2025, 10, 1), "1000.00")  # first day
        self._sale(date(2026, 9, 30), "2000.00")  # last day
        self._sale(date(2026, 10, 1), "400.00")  # the day after
        self._sale(date(2026, 3, 1), "50.00", organic=False)
        text = self._packet_text(osp, "02-annual-update.pdf")
        self.assertIn("Sales records subtotal, 2025-10-01 to 2026-09-30 (not reconciled)", text)
        self.assertIn("$3,000.00 across 2 sales", text)
        self.assertIn("the sales period stated on this update", text)
        # Never the agent's fee figure, whatever the period.
        self.assertIn("it is not any certifying agent's fee figure", text)

    def test_with_no_period_02_still_reports_the_prior_calendar_year(self):
        osp = self._plan()
        self._filing(osp)
        self._sale(date(2026, 2, 1), "700.00")
        self._sale(date(2025, 12, 31), "1.00")
        text = self._packet_text(osp, "02-annual-update.pdf")
        self.assertIn("Sales records subtotal, 2026 (not reconciled)", text)
        self.assertIn("$700.00 across 1 sale invoiced as organic and dated in calendar 2026", text)

    def _validate(self, osp, start, end):
        data = {
            "prior_osp": osp.pk,
            "reporting_year": 2027,
            "changes_summary": "No changes to the plan this year.",
            "sales_period_start": start,
            "sales_period_end": end,
        }
        serializer = OSPAnnualUpdateSerializer(data=data)
        return serializer.is_valid(), serializer.errors

    def test_the_period_is_both_ends_in_order_at_most_a_year_and_over(self):
        osp = self._plan()
        today = timezone.localdate()
        cases = {
            "half": ("2025-10-01", None),
            "reversed": ("2026-09-30", "2025-10-01"),
            "thirteen months": ("2025-09-01", "2026-09-30"),
            "still running": ((today - timedelta(days=30)).isoformat(), (today + timedelta(days=1)).isoformat()),
        }
        for label, (start, end) in cases.items():
            with self.subTest(label):
                ok, errors = self._validate(osp, start, end)
                self.assertFalse(ok, label)
                self.assertTrue({"sales_period_start", "sales_period_end"} & set(errors), errors)
        ok, errors = self._validate(osp, "2025-10-01", "2026-09-30")
        self.assertTrue(ok, errors)

    def test_the_period_is_part_of_what_is_signed(self):
        osp = self._plan()
        filing = self._filing(osp)
        unsigned_hash = filing.content_sha256()
        # A filing with no period hashes exactly as before the field existed.
        self.assertNotIn("sales_period", filing.signed_content())
        filing = sign_filing(filing, self.user)
        self.assertEqual(filing.signed_content_sha256, unsigned_hash)
        filing.sales_period_start, filing.sales_period_end = date(2025, 10, 1), date(2026, 9, 30)
        self.assertNotEqual(filing.content_sha256(), filing.signed_content_sha256)

    def test_a_correction_carries_the_period(self):
        osp = self._plan()
        filing = sign_filing(
            self._filing(osp, sales_period_start=date(2025, 10, 1), sales_period_end=date(2026, 9, 30)), self.user
        )
        nxt = correct_filing(filing, self.user)
        self.assertEqual((nxt.sales_period_start, nxt.sales_period_end), (date(2025, 10, 1), date(2026, 9, 30)))


class CopySheetTests(_Farm):
    def test_values_trazo_holds_are_given_with_their_source(self):
        osp = self._plan()
        self._filing(osp)
        rows = self._rows(osp)
        self.assertEqual(rows["business_name"]["value"], "Sheet Orchards LLC")
        self.assertEqual(rows["dba"]["value"], "Sheet Hill Fruit")
        self.assertEqual(rows["contact_email"]["value"], "ana@sheet.example")
        self.assertEqual(rows["business_name"]["source"], "company")
        # OTCO's Client ID is not the certificate number, and Trazo keeps no Client ID.
        self.assertEqual(rows["client_id"]["kind"], "not_in_trazo")
        self.assertIsNone(rows["client_id"]["value"])

    def test_the_sheet_answers_no_election_and_ticks_no_box(self):
        osp = self._plan()
        self._filing(osp)
        # No new plan version on this filing, so Step 4 has no comparison and is the operator's too.
        yours = [row for row in agent_form_sheet(osp)["rows"] if row["kind"] == "yours"]
        self.assertEqual(
            {row["item"] for row in yours},
            {
                "public_contact",
                "continue_or_withdraw",
                "services",
                "production_partners",
                "osp_changes",
                "agreement_and_signature",
                "payment",
                "billing_contact",
            },
        )
        for row in yours:
            self.assertIsNone(row["value"], row["item"])

    def test_step_6_gives_the_figure_02_printed_over_the_same_period(self):
        osp = self._plan()
        self._filing(osp, sales_period_start=date(2025, 10, 1), sales_period_end=date(2026, 9, 30))
        self._sale(date(2026, 1, 15), "1234.50")
        self._sale(date(2026, 6, 1), "765.50")
        row = self._rows(osp)["gross_sales"]
        self.assertEqual(row["kind"], "value")
        self.assertEqual(Decimal(row["value"]), Decimal("2000.00"))
        self.assertEqual((row["extra"]["period_start"], row["extra"]["period_end"]), ("2025-10-01", "2026-09-30"))
        self.assertTrue(row["extra"]["period_stated"])
        self.assertIn("$2,000.00", self._packet_text(osp, "02-annual-update.pdf"))

    def test_step_6_gives_no_figure_while_a_sale_has_no_amount(self):
        osp = self._plan()
        self._filing(osp)
        self._sale(date(2026, 3, 1), "500.00")
        self._sale(date(2026, 4, 1), None)
        row = self._rows(osp)["gross_sales"]
        self.assertEqual(row["kind"], "not_recorded")
        self.assertIsNone(row["value"])
        self.assertEqual(row["extra"]["n_unpriced"], 1)

    def test_step_4_lists_the_changed_sections_by_form_code(self):
        v1 = self._plan()
        v2 = fork_plan(v1, self.user)
        OSPAnnualUpdate.objects.create(prior_osp=v1, new_osp=v2, reporting_year=2027, changes_summary="Pests.")
        v2 = OrganicSystemPlan.objects.get(pk=v2.pk)
        v2.module_responses = {
            "schema_version": 1,
            "parcel_modules": {},
            "modules": {"g5_0_pest": {"answers": {"prevention_practices": {"value": "Kaolin clay", "at": "x"}}}},
        }
        v2.save(update_fields=["module_responses"])
        row = self._rows(v2)["osp_changes"]
        self.assertEqual(row["kind"], "value")
        self.assertEqual([s["label"] for s in row["value"]], ["C5 Crop Pest, Weed & Disease Management"])
        self.assertEqual(row["value"][0]["files"], ["modules/G5_0.pdf"])

    def test_only_an_agent_whose_form_is_mapped_gets_a_sheet(self):
        for agent in ("CCOF", "Washington State Department of Agriculture", "Organic Certifiers, Inc."):
            with self.subTest(agent=agent):
                osp = self._plan(certifier=agent)
                self.assertIsNone(agent_form_sheet(osp))
                osp.delete()

    def test_the_form_is_named_from_the_register(self):
        sheet = agent_form_sheet(self._plan())
        self.assertEqual(sheet["form"]["document_id"], "OSP Update Form")
        self.assertEqual(sheet["form"]["revision"], "Rev. 2024/09/20")


class CopySheetEndpointTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="sheet-api@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Sheet API Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Sheet API Farm", company=self.company)
        self.client.force_authenticate(user=self.user)

    def _url(self, osp):
        return f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/osps/{osp.pk}/agent-form-sheet/"

    def _plan(self, certifier=OTCO):
        return OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=certifier, created_by=self.user
        )

    def _subscribe(self):
        # Migrations patch an existing row; the slug may already be there.
        plan, _ = Plan.objects.update_or_create(
            slug="compliance-yearly",
            defaults={"name": "Compliance", "description": "", "price": 249, "features": {"compliance_exports": True}},
        )
        Subscription.objects.create(
            company=self.company,
            plan=plan,
            status="active",
            current_period_start=timezone.now() - timedelta(days=5),
            current_period_end=timezone.now() + timedelta(days=25),
        )

    def test_a_starter_farm_is_refused_like_the_packet(self):
        res = self.client.get(self._url(self._plan()))
        self.assertIn(res.status_code, (402, 403), res.content)

    def test_a_paying_farm_gets_the_sheet_and_another_agent_gets_404(self):
        self._subscribe()
        res = self.client.get(self._url(self._plan()))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["agent"], "otco")
        other = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=2, status="draft", certifier_name="CCOF", created_by=self.user
        )
        self.assertEqual(self.client.get(self._url(other)).status_code, 404)
