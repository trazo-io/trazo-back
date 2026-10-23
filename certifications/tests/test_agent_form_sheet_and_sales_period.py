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

    def test_twelve_months_is_counted_by_calendar_with_both_ends_included(self):
        """Review of back #217: a day count let a 366-day period through and would refuse a leap year."""
        osp = self._plan()
        for start, end, ok in (
            ("2025-01-01", "2025-12-31", True),
            ("2025-01-01", "2026-01-01", False),  # 366 days, one more than a year
            ("2024-01-01", "2024-12-31", True),  # a leap year is still one year
            ("2023-03-01", "2024-02-29", True),
            ("2023-03-01", "2024-03-01", False),
        ):
            with self.subTest(start=start, end=end):
                self.assertEqual(self._validate(osp, start, end)[0], ok)

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
        # OTCO's Client ID is not the certificate number. Until the operator records it, the row
        # says where to find it and names the field to fill.
        self.assertEqual(rows["client_id"]["kind"], "not_recorded")
        self.assertEqual(rows["client_id"]["extra"]["where"], "agent_certificate_and_letters")
        self.assertEqual(
            rows["client_id"]["extra"]["edit"],
            {"target": "establishment", "field": "certifier_client_id", "agent": "otco"},
        )
        self.assertIsNone(rows["client_id"]["value"])

    def test_the_sheet_answers_no_election_and_ticks_no_box(self):
        """An election, a commitment or a signature on the agent's form is the operator's; an
        instruction is the agent's. Neither ever carries a value Trazo filled in."""
        osp = self._plan()
        self._filing(osp)
        rows = agent_form_sheet(osp)["rows"]
        for row in rows:
            if row["kind"] in ("yours", "note"):
                self.assertIsNone(row["value"], row["item"])
        yours = {row["item"] for row in rows if row["kind"] == "yours"}
        for item in (
            "continue_or_withdraw",
            "services",
            "production_partners",
            "attest_true",
            "authority_to_bind",
            "agent_manuals",
            "standards_and_policies",
            "terms_and_conditions",
            "electronic_signature",
            "payment",
            "billing_contact",
            "comments",
        ):
            self.assertIn(item, yours)

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


class EveryLineOfTheFormTests(_Farm):
    """The sheet answers every item of OTCO's form, as the register's inventory lists them."""

    def _compared(self):
        v1 = self._plan()
        v2 = fork_plan(v1, self.user)
        OSPAnnualUpdate.objects.create(prior_osp=v1, new_osp=v2, reporting_year=2027, changes_summary="Pests.")
        return OrganicSystemPlan.objects.get(pk=v2.pk)

    def test_every_line_of_the_form_has_a_row(self):
        from certifications.services.agent_form_sheet import FORM_ITEM_ROWS
        from certifications.services.form_inventory import inventory_dir, load_inventory

        inventory = load_inventory(inventory_dir("otco") / "OSP-Update-Form.yaml")
        refs = {item.ref for item in inventory.items}
        mapped = FORM_ITEM_ROWS["otco"]
        # Both ways: a new item on a revised form fails until it has rows; a mapped ref the form no
        # longer prints fails too.
        self.assertEqual(refs, set(mapped) - {"header"})
        sheet_items = [row["item"] for row in agent_form_sheet(self._compared())["rows"]]
        expected = [item for ref_items in mapped.values() for item in ref_items]
        self.assertEqual(sorted(sheet_items), sorted(expected))
        self.assertEqual(len(sheet_items), len(set(sheet_items)))

    def test_every_line_has_a_row_whatever_the_years_filing_state(self):
        """Review of back #218: new_land was dropped outside the "compared" state."""
        from certifications.services.agent_form_sheet import FORM_ITEM_ROWS

        expected = sorted(item for items in FORM_ITEM_ROWS["otco"].values() for item in items)

        def items(osp):
            return sorted(row["item"] for row in agent_form_sheet(osp)["rows"])

        v1 = self._plan()
        with self.subTest("no filing"):
            self.assertEqual(items(v1), expected)
        reaffirmed = OSPAnnualUpdate.objects.create(prior_osp=v1, reporting_year=2027, changes_summary="No changes.")
        with self.subTest("no new version"):
            self.assertEqual(items(v1), expected)
        reaffirmed.delete()
        v2 = fork_plan(v1, self.user)
        OSPAnnualUpdate.objects.create(prior_osp=v1, new_osp=v2, reporting_year=2027, changes_summary="Pests.")
        with self.subTest("packet built from the prior version"):
            self.assertEqual(items(OrganicSystemPlan.objects.get(pk=v1.pk)), expected)
            row = {r["item"]: r for r in agent_form_sheet(OrganicSystemPlan.objects.get(pk=v1.pk))["rows"]}
            self.assertEqual(row["new_land"]["extra"]["reason"], "newer_version")

    def test_rows_follow_the_forms_step_order(self):
        steps = [row["step"] for row in agent_form_sheet(self._compared())["rows"]]
        self.assertEqual(steps, sorted(steps))


class ClientIdTests(_Farm):
    def test_a_recorded_client_id_is_copied_and_printed_for_its_own_agent_only(self):
        osp = self._plan()
        self._filing(osp)
        self.est.certifier_client_id, self.est.certifier_client_id_agent = "OT-4471", "otco"
        self.est.save()
        self.assertEqual(self._rows(osp)["client_id"]["value"], "OT-4471")
        self.assertIn("Client ID: OT-4471", self._packet_text(osp, "00-cover.pdf"))
        # Recorded against another agent: never shown as this agent's.
        self.est.certifier_client_id_agent = "ccof"
        self.est.save()
        self.assertEqual(self._rows(osp)["client_id"]["kind"], "not_recorded")
        self.assertNotIn("OT-4471", self._packet_text(osp, "00-cover.pdf"))

    def test_the_cover_names_the_dba(self):
        osp = self._plan()
        self.assertIn("Trade name (DBA): Sheet Hill Fruit", self._packet_text(osp, "00-cover.pdf"))


class SheetMatchesThePacketTests(_Farm):
    def test_the_contact_is_the_person_the_cover_names_including_the_plan_author_fallback(self):
        self.est.contact_person = ""
        self.est.save()
        osp = self._plan()
        osp.created_by = self.user
        osp.save()
        self._filing(osp)
        row = self._rows(osp)["contact_name"]
        self.assertEqual((row["value"], row["source"]), ("Ana Diaz", "plan_author"))
        self.assertIn("Responsible person: Ana Diaz", self._packet_text(osp, "00-cover.pdf"))

    def test_notices_already_sent_are_listed_for_step_4s_first_option(self):
        from certifications.models import OSPChangeNotification

        osp = self._plan()
        self._filing(osp)
        OSPChangeNotification.objects.create(
            osp=osp,
            change_category=OSPChangeNotification.CATEGORY_CHOICES[0][0],
            description="Added a hedgerow on the north edge.",
            date_notified=date(2026, 5, 4),
        )
        OSPChangeNotification.objects.create(
            osp=osp,
            change_category=OSPChangeNotification.CATEGORY_CHOICES[0][0],
            description="Before the plan was submitted.",
            date_notified=date(2025, 12, 1),
        )
        row = self._rows(osp)["notices_sent"]
        self.assertEqual(row["kind"], "value")
        self.assertEqual([n["date"] for n in row["value"]], ["2026-05-04"])

    def test_stated_contact_changes_point_to_the_contact_change_form(self):
        osp = self._plan()
        self._filing(osp, application_info_changes="New farm manager: Luis Ortega.")
        self.assertTrue(self._rows(osp)["contact_change_form"]["extra"]["application_info_changes"])


class ClientIdEndpointTests(APITestCase):
    """The grower records the Client ID from the copy sheet through the farm's own PATCH."""

    def setUp(self):
        self.user = User.objects.create_user(email="client-id@test.com", password="x", is_verified=True)
        self.company = Company.objects.create(name="Client ID Co")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Client ID Farm", company=self.company)
        self.client.force_authenticate(user=self.user)
        self.url = f"/api/companies/{self.company.pk}/establishments/{self.est.pk}/"

    def test_a_client_id_is_saved_with_a_known_agent_or_not_at_all(self):
        res = self.client.patch(
            self.url, {"certifier_client_id": "OT-4471", "certifier_client_id_agent": "nobody"}, format="json"
        )
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("certifier_client_id_agent", res.json())
        res = self.client.patch(
            self.url, {"certifier_client_id": " OT-4471 ", "certifier_client_id_agent": "otco"}, format="json"
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.est.refresh_from_db()
        self.assertEqual((self.est.certifier_client_id, self.est.certifier_client_id_agent), ("OT-4471", "otco"))
        self.assertEqual(self.client.get(self.url).json()["certifier_client_id"], "OT-4471")
        # An agent alone, with no Client ID on file, is refused rather than dropped (review of back #218).
        self.client.patch(self.url, {"certifier_client_id": ""}, format="json")
        res = self.client.patch(self.url, {"certifier_client_id_agent": "otco"}, format="json")
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn("certifier_client_id", res.json())
        res = self.client.patch(self.url, {"certifier_client_id": ""}, format="json")
        self.assertEqual(res.status_code, 200, res.content)
        self.est.refresh_from_db()
        self.assertEqual((self.est.certifier_client_id, self.est.certifier_client_id_agent), ("", ""))
