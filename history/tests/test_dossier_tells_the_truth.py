"""The audit dossier states what the records hold, as counts and facts.

Recordkeeping review, 2026-10-07 (F-03, F-04, F-05), read on the Duke 2026 dossier of the
Calapooia specimen:
- page 2 reported "Yield reconciliation — header 121,250 lb · narrative 36,500 lb · delta 69.9%"
  while page 49 summed the four harvest records to 121,250 lb, and named the certifying agent
  ("COC, Cascadia Organic Certifiers") as an undeclared handler;
- page 1 printed "100% materially complete" and page 3 "Complete — 11,238 characters";
- page 52 printed "Producer attests that … Trazo infrastructure supports rapid retrieval
  (target: 24-hour response)", unsigned.

Each test here went red on the code before the fix, on an assertion.
"""

import io
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

import pdfplumber

from certifications.models import Certification, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import History, ProductionEvent, SalesRecord, SoilManagementEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

PARAGRAPHS = {
    "practices_procedures": (
        "Cover crops of cereal rye and hairy vetch are drilled behind the harvester each October and "
        "flailed at rye boot stage in March. The vegetable ground is disced in two passes, rototilled to "
        "six inches and levelled before seeding. Blueberry row middles are permanent sod, mown five "
        "times a season, with the under-row strip mulched in Douglas-fir sawdust. Pruning is done in "
        "February by a crew of six with loppers and hand saws, removing the oldest canes per bush."
    ),
    "inputs_list": (
        "Fertility comes from purchased compost at four tons per acre before the last disc pass, "
        "feather meal banded under the drip line at bud break, and fish fertilizer through the tape at "
        "fruit set. Disease pressure on the blueberries is covered by lime sulfur at dormancy and a "
        "biological fungicide at bloom. Spotted wing drosophila is managed with spinosad and a "
        "biological insecticide in rotation at pick intervals, applied at dusk after bee flight."
    ),
    "monitoring_plan": (
        "Every input purchase is matched to an invoice and a lot number before it is applied, and the "
        "application is logged the same day with the rate, the area and the equipment. Weekly scouting "
        "walks are recorded with the pest, the count and the decision. The packing shed keeps a "
        "run log per day with the lot codes received, the flats packed and the destination. "
        "Supplier organic certificates are checked at the start of each season and kept on file."
    ),
    "recordkeeping_description": (
        "Records are kept in Trazo as dated activity records per parcel and season: planting, "
        "inputs, scouting, harvest, cleaning, storage, transport and sales, each with the person who "
        "performed it. Weigh tickets, invoices and bills of lading are kept in the farm office and "
        "linked to the sale they belong to. Records are retained for at least five years after the "
        "season they belong to is finished, and are made available at inspection on request."
    ),
    "commingling_barriers": (
        "The west-edge rows of two blueberry blocks are buffer rows against a conventional neighbour. "
        "They are staked orange, picked last on their own day into red-tagged lugs, kept out of the "
        "organic cooler and pack line, and sold as conventional process fruit on a separate bill of "
        "lading under a lot code ending in BUF. No other non-organic product exists on the operation, "
        "and no prohibited material is stored on the farm. Shared equipment is cleaned and logged."
    ),
    "additional_certifier_info": (
        "The operation sells wholesale through a certified distributor for fresh fruit and a certified "
        "processor for process-grade berries. Both handler certificates are kept with the lot records. "
        "The operation is a split operation only in the sense of its buffer rows, as described in the "
        "commingling section. No wild crops are harvested and no livestock is kept. The farm has an "
        "NRCS conservation contract for a native hedgerow along the north edge of one parcel."
    ),
}


class DossierTellsTheTruthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="dossier-truth@test.com", password="x")
        cls.company = Company.objects.create(name="Truth Co")
        cls.establishment = Establishment.objects.create(name="Truth Farm", company=cls.company, state="OR")
        cls.parcel = Parcel.objects.create(name="Home Field East", establishment=cls.establishment, area=5.0)
        cls.product = Product.objects.create(name="Blueberries")

    def _production(self, header_lb, picks, buyer="Cascade Organic Distributors, Portland OR"):
        history = History.objects.create(
            name="Duke 2026",
            start_date=timezone.now() - timedelta(days=220),
            finish_date=timezone.now() - timedelta(days=10),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=header_lb,
            production_unit="lb",
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        for i, (qty, note) in enumerate(picks):
            ProductionEvent.objects.create(
                history=history,
                type="HA",
                date=timezone.now() - timedelta(days=60 - i * 4),
                created_by=self.user,
                yield_quantity=qty,
                yield_unit="lb",
                description=note,
            )
        SalesRecord.objects.create(
            production=history,
            sale_date=timezone.now().date(),
            buyer_name=buyer,
            quantity=sum(q for q, _ in picks if q) or header_lb,
            quantity_unit="lb",
            organic_on_invoice=True,
            sale_amount=1000,
        )
        return history

    @staticmethod
    def _findings(history):
        service = AuditExportService(history, certification_type="organic")
        titles = []
        for el in service._build_consistency_findings():
            data = getattr(el, "_cellvalues", None)
            if data:
                for row in data:
                    titles.append(" ".join(str(getattr(c, "text", c)) for c in row))
        return "\n".join(titles)

    # -- F-03: the yield check reads the harvest records --------------------

    def test_recorded_harvest_yields_that_sum_to_the_header_raise_no_yield_finding(self):
        picks = [
            (36500, "Pick 1 on Duke: 36,500 lb field weight over the scale, 12.4 Brix."),
            (36200, "Pick 2, 4,022 flats, 36,200 lb on the shed scale."),
            (30300, "Pick 3, 30,300 lb."),
            (18250, "Pick 4, machine, process grade, 18,250 lb."),
        ]
        history = self._production(121250, picks)
        self.assertNotIn("Yield reconciliation", self._findings(history))

    def test_recorded_harvest_yields_that_do_not_match_the_header_are_reported_as_records(self):
        # Anti-vacuity: the check still fires, and names the records, not a note.
        history = self._production(200000, [(36500, "Pick 1, 36,500 lb."), (36200, "Pick 2, 36,200 lb.")])
        findings = self._findings(history)
        self.assertIn("Yield reconciliation", findings)
        self.assertIn("Harvest records (2): 72,700 lb", findings)
        self.assertNotIn("narrative", findings)

    def test_a_season_whose_harvest_records_carry_no_quantity_falls_back_to_the_notes(self):
        history = self._production(200000, [(None, "First pick, 36,500 lb over the scale.")])
        findings = self._findings(history)
        self.assertIn("Yield reconciliation", findings)
        self.assertIn("narrative value(s): 36,500 lb", findings)

    def test_a_season_with_one_unquantified_pick_is_not_summed_against_the_header(self):
        # Review of back #130: a partial sum of the quantified picks reproduced the false gap.
        # One pick without a quantity means the records cannot be summed; fall back to the notes.
        picks = [
            (36500, "Pick 1 on Duke: 36,500 lb field weight over the scale."),
            (None, "Pick 2, 36,200 lb on the shed scale."),
            (None, "Pick 3, 30,300 lb."),
            (None, "Pick 4, 18,250 lb."),
        ]
        history = self._production(121250, picks)
        findings = self._findings(history)
        self.assertNotIn("Harvest records (", findings)

    # -- F-03: the certifying agent is not a handler -------------------------

    def test_the_certifying_agent_named_in_notes_is_not_an_undeclared_handler(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="Cascadia Organic Certifiers (COC)",
            certification_number="COC-1463",
        )
        ProductionEvent.objects.create(
            history=history,
            type="PH",
            date=timezone.now() - timedelta(days=30),
            created_by=self.user,
            description=(
                "Packed 4,000 flats. Materials-list notice shipped to Cascadia Organic Certifiers on the "
                "12th; a copy goes to COC with the renewal. Fresh fruit delivery to COD tomorrow."
            ),
        )
        findings = self._findings(history)
        self.assertNotIn("Handler chain", findings)

    def test_a_short_certifier_acronym_does_not_hide_a_real_handler(self):
        # Review of back #130: "Americert International" gives the form "ai", which is inside
        # "fairviewpackingco"; containment on a 2-letter form hid an undeclared handler.
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        Certification.objects.create(
            establishment=self.establishment,
            certification_type="usda_organic",
            certifier_name="Americert International",
            certification_number="AI-1",
        )
        ProductionEvent.objects.create(
            history=history,
            type="PH",
            date=timezone.now() - timedelta(days=30),
            created_by=self.user,
            description="Delivery to Fairview Packing Co in the morning; the rest shipped to Raintree Foods.",
        )
        findings = self._findings(history)
        self.assertIn("Handler chain", findings)
        self.assertIn("Fairview Packing Co", findings)

    def test_two_unexplained_handlers_still_raise_the_handler_finding(self):
        # Anti-vacuity for the test above.
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        ProductionEvent.objects.create(
            history=history,
            type="PH",
            date=timezone.now() - timedelta(days=30),
            created_by=self.user,
            description="Delivery to Mission Produce in the morning; the rest shipped to Whole Foods Market.",
        )
        findings = self._findings(history)
        self.assertIn("Handler chain", findings)
        self.assertIn("Mission Produce", findings)

    # -- F-04 and F-05: the whole PDF ------------------------------------------

    def _full_text(self, history):
        # The organic dossier refuses to build without an OFPP on file; the gate is not under test.
        self.establishment.fraud_prevention_plan_uploaded = True
        self.establishment.fraud_prevention_plan_date = timezone.now().date()
        self.establishment.save(update_fields=["fraud_prevention_plan_uploaded", "fraud_prevention_plan_date"])
        pdf = AuditExportService(history, certification_type="organic").generate_pdf()
        with pdfplumber.open(io.BytesIO(pdf.getvalue())) as doc:
            return " ".join((page.extract_text() or "") for page in doc.pages).replace("\n", " ")

    def test_the_dossier_prints_counts_not_percentages_for_the_plan(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=3,
            status="active",
            created_by=self.user,
            sections={k: {"narrative": v, "last_updated": "2026-08-21"} for k, v in PARAGRAPHS.items()},
        )
        text = self._full_text(history)
        self.assertIn("6 of 6 sections", text)
        self.assertIn("above the narrative floor", text)
        self.assertIn("6 of 6 § 205.201(a)(1)-(6) sections substantively filled", text)
        self.assertIn("Written — ", text)
        self.assertNotIn("materially complete", text)
        self.assertNotIn("% of § 205.201", text)
        self.assertNotIn("Complete — ", text)

    def test_the_readiness_statement_is_factual_and_unsigned(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        text = self._full_text(history)
        self.assertNotIn("24-hour", text)
        self.assertNotIn("Producer attests that all event logs", text)
        self.assertNotIn("value-add", text)
        self.assertIn("not signed by the producer", text)
        self.assertIn("at least five years after the season", text)

    # -- Orchard batch 2b: what the dossier asks of the operator -----------------------------
    def _snapshot_detail(self, history, label_part):
        rows = AuditExportService(history, certification_type="organic").compliance_snapshot_rows()
        return next(r for r in rows if label_part in r["label"])["detail"]

    def _compost(self, history, **fields):
        fields.setdefault("type", "OM")
        return SoilManagementEvent.objects.create(
            history=history,
            date=timezone.now() - timedelta(days=100),
            description="compost",
            amendment_type="compost",
            created_by=self.user,
            **fields,
        )

    def test_a_purchased_compost_asks_for_the_suppliers_documentation_not_the_operators_figures(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        self._compost(
            history,
            amendment_product_name="Compost from the county yard",
            amendment_quantity_purchased=240,
            amendment_quantity_purchased_unit="tons",
        )
        detail = self._snapshot_detail(history, "Compost")
        self.assertNotIn("missing C:N", detail)
        self.assertNotIn("add before inspection", detail)
        self.assertIn("supplier's process documentation (C:N, temperatures, turnings) not on file", detail)
        text = self._full_text(history)
        self.assertNotIn("Composting must document peak temperature", text)
        self.assertIn("supplier's process documentation (C:N, temperatures, turnings) not on file", text)

    def test_a_compost_bought_by_quantity_alone_is_read_as_bought_everywhere(self):
        """Local review of back #436: page 1 and the soil table read one record two ways when only a
        purchase quantity said it was bought."""
        from history.services.audit_export_service import _compost_cn_is_initial, _compost_is_purchased

        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        compost = self._compost(
            history, type="CO", amendment_quantity_purchased=240, amendment_quantity_purchased_unit="tons"
        )
        self.assertTrue(_compost_is_purchased(compost))
        self.assertFalse(_compost_cn_is_initial(compost))

    def test_a_bought_compost_with_temperatures_but_no_c_n_gets_the_soil_note_too(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        self._compost(
            history,
            amendment_product_name="Compost from the county yard",
            compost_peak_temp_f=150,
            compost_duration_days_at_temp=15,
            compost_method="windrow",
        )
        self.assertIn("supplier's process documentation", self._snapshot_detail(history, "Compost"))
        self.assertIn("Purchased compost: supplier's process documentation", self._full_text(history))

    def test_an_on_farm_compost_still_asks_the_operator_for_the_figures(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        self._compost(history, type="CO")
        detail = self._snapshot_detail(history, "Compost")
        self.assertIn("1 missing C:N", detail)
        self.assertNotIn("supplier's process documentation", detail)

    def test_a_fraud_prevention_plan_written_in_trazo_is_not_called_an_upload(self):
        history = self._production(100000, [(100000, "One pick, 100,000 lb.")])
        OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            created_by=self.user,
            module_responses={"modules": {"g2_0_fraud_prevention": {"completed_at": "2026-11-15T10:00:00Z"}}},
        )
        detail = self._snapshot_detail(history, "OFPP")
        self.assertEqual(detail, "Written in Trazo 2026-11-15 (OSP module G2.0)")
