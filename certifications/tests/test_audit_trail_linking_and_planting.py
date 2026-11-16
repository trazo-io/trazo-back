"""The audit trail exhibit's last two gaps for OTCO C12 12.2-6 and 12.2-6a (2026-11-16).

OTCO C12 (rev. 2023/12/18, source hash re-checked 2026-11-16) asks a table of documents with the
"Linking element to next and previous document in chain" (12.2-6), and sample documents including
"planting records" (12.2-6a). The exhibit stated the link for every record Trazo holds and left the
cell blank for one it cannot hold (a weigh ticket, a delivery slip, the operation's own form); the
sample trail began at the harvest.

Pinned here:
  * the operator states the link once, in G8.0 §A, for a confirmed record type whose link only they
    can state; the exhibit prints it as theirs, and a renewal carries it;
  * a link is refused for a record type Trazo states itself, and for a row not confirmed;
  * Part B begins at the planting records on the season, and says so when there are none.
"""

import io
import zipfile
from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.services import common_osp_records
from certifications.services.audit_trail_exhibit import document_table, sample_trail
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment
from history.models import Production, ProductionEvent, SalesRecord
from product.models import Parcel, Product
from users.models import User, WorksIn

LINK = "Ticket number written on the bin tag and copied onto the packer's receiving sheet"


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return " ".join(" ".join((page.extract_text() or "").split()) for page in doc.pages)


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Hood River Pears LLC")
        self.user = User.objects.create_user(email="c12trail@test.com", password="x", is_verified=True)
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Hood River Pears", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=6.0)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def exhibit(self) -> str:
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(OrganicSystemPlan.objects.get(pk=self.osp.pk))))
        return _pdf_text(zf.read("05-audit-trail-exhibit.pdf"))

    def post(self, **body):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/record-types/"
        return self.client.post(url, body, format="json")

    def rows(self):
        return {
            r["key"]: r
            for r in common_osp_records.derive_record_types(self.est, osp=OrganicSystemPlan.objects.get(pk=self.osp.pk))
        }


class TheOperatorStatesTheLink(_Farm):
    def test_a_confirmed_weigh_ticket_takes_its_link_and_the_exhibit_prints_it_as_theirs(self):
        common_osp_records.confirm(self.osp, ["weigh_tickets"], user=self.user)
        res = self.post(keys=["weigh_tickets"], linking_element=f"  {LINK}  ")
        self.assertEqual(res.status_code, 200, res.content[:300])
        row = next(r for r in res.json()["record_types"] if r["key"] == "weigh_tickets")
        self.assertEqual((row["operator_states_link"], row["linking_element"]), (True, LINK))
        [doc_row] = document_table(self.est, OrganicSystemPlan.objects.get(pk=self.osp.pk))
        self.assertEqual((doc_row.linking_element, doc_row.stated_by_operator), (LINK, True))
        text = self.exhibit()
        self.assertIn("(as stated by the operator)", text)
        self.assertIn("Ticket number written on the bin tag", text)
        # Nothing is left for the operator to fill on the page, so the note about such rows is gone.
        self.assertNotIn("state the linking element", text)

    def test_empty_text_clears_it(self):
        common_osp_records.confirm(self.osp, ["weigh_tickets"], user=self.user)
        self.post(keys=["weigh_tickets"], linking_element=LINK)
        self.post(keys=["weigh_tickets"], linking_element="")
        self.assertEqual(self.rows()["weigh_tickets"]["linking_element"], "")
        [doc_row] = document_table(self.est, OrganicSystemPlan.objects.get(pk=self.osp.pk))
        self.assertIsNone(doc_row.linking_element)

    def test_a_record_trazo_links_itself_and_an_unconfirmed_one_are_refused(self):
        common_osp_records.confirm(self.osp, ["harvest_records"], user=self.user)
        for key, words in (("harvest_records", "from its own records"), ("delivery_slips", "Confirm")):
            with self.subTest(key=key):
                res = self.post(keys=[key], linking_element=LINK)
                self.assertEqual(res.status_code, 400, res.content[:300])
                self.assertIn(words, str(res.json()["linking_element"]))
        self.assertEqual(self.rows()["harvest_records"]["operator_states_link"], False)
        res = self.post(keys=["weigh_tickets", "delivery_slips"], linking_element=LINK)
        self.assertEqual(res.status_code, 400, res.content[:300])

    def test_the_link_survives_a_rename_and_goes_with_an_unconfirm(self):
        common_osp_records.confirm(self.osp, ["other_records"], user=self.user, label="Cooler log")
        common_osp_records.set_linking_element(self.osp, "other_records", LINK, user=self.user)
        common_osp_records.confirm(self.osp, ["other_records"], user=self.user, label="Cooler temperature log")
        self.assertEqual(self.rows()["other_records"]["linking_element"], LINK)
        common_osp_records.confirm(self.osp, ["other_records"], user=self.user, confirmed=False)
        self.assertEqual(self.rows()["other_records"]["linking_element"], "")

    def test_a_renewal_carries_it(self):
        from certifications.services.osp_fork import fork_plan

        common_osp_records.confirm(self.osp, ["weigh_tickets"], user=self.user)
        common_osp_records.set_linking_element(self.osp, "weigh_tickets", LINK, user=self.user)
        draft = fork_plan(OrganicSystemPlan.objects.get(pk=self.osp.pk), self.user)
        [doc_row] = document_table(self.est, draft)
        self.assertEqual(doc_row.linking_element, LINK)


class PartBBeginsAtThePlanting(_Farm):
    def season(self):
        season = Production.objects.create(
            name="2026 pears",
            parcel=self.parcel,
            product=Product.objects.create(name="Pears"),
            start_date=timezone.make_aware(datetime(2026, 3, 1)),
            finish_date=timezone.make_aware(datetime(2026, 9, 20)),
            lot_id="HRP-26-NB-01",
        )
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.HARVESTING,
            description="pick",
            date=timezone.make_aware(datetime(2026, 8, 30)),
            yield_quantity=40,
            yield_unit="bins",
        )
        SalesRecord.objects.create(
            production=season,
            sale_date=date(2026, 9, 10),
            buyer_name="Diamond Fruit Growers",
            quantity=40,
            quantity_unit="bins",
            invoice_number="DF-2291",
            organic_on_invoice=True,
        )
        return season

    def test_the_seasons_planting_records_are_listed_first(self):
        season = self.season()
        ProductionEvent.objects.create(
            history=season,
            type=ProductionEvent.TRANSPLANTING,
            description="replant",
            date=timezone.make_aware(datetime(2026, 3, 20)),
            block_id="NB-4",
            rootstock="OHxF 87",
            seed_supplier_name="Willamette Nurseries",
            seed_lot_number="WN-26-114",
        )
        trail = sample_trail(self.est)
        self.assertEqual(len(trail.plantings), 1)
        self.assertEqual(
            {k: trail.plantings[0][k] for k in ("date", "block", "rootstock", "supplier", "lot")},
            {
                "date": "2026-03-20",
                "block": "NB-4",
                "rootstock": "OHxF 87",
                "supplier": "Willamette Nurseries",
                "lot": "WN-26-114",
            },
        )
        text = self.exhibit()
        self.assertIn("1. Planting records", text)
        self.assertIn("2026-03-20 · Transplanting · block NB-4 · rootstock OHxF 87", text)
        self.assertIn("lot WN-26-114", text)
        self.assertLess(text.index("1. Planting records"), text.index("2. Harvest records"))
        self.assertIn("5. Balance", text)

    def test_a_season_with_no_planting_says_so(self):
        self.season()
        self.assertEqual(sample_trail(self.est).plantings, [])
        self.assertIn("No planting or transplanting record is on this season.", self.exhibit())
