"""A lot-level reconciliation must not read as a period inventory statement.

WHAT WAS WRONG (2026-09-24)
---------------------------
The operation dossier carried a section headed "Mass-Balance Audit Summary" whose verdict line
read "Net inventory reconciliation: PASS", and whose footer said it connected "inputs purchased
and harvest yield to the sales quantity shipped". It models no inventory at all: no opening
balance, no closing balance, no carryover, and Trazo holds no data from which to compute one.

It is a single production's harvest records against that production's own sales records. That
is the RIGHT computation — it is what makes an October harvest invoiced the following January
reconcile in full — but the document that contains it is stamped with a period window on its
cover, so "net inventory reconciliation" invited a reader to take a lot-level check for a
period one, in the operation's favour.

Two further defects sat underneath the naming:

  * the balance row was emitted only when `quantity_sold` was truthy, so a lot harvested and not
    yet invoiced printed NOTHING. Silence in a reconciliation section reads as "nothing to
    reconcile" when the fact is "all of it is still uninvoiced". Zero is not missing.
  * the CSV twin of the section kept the old header, had no balance row of any kind, and still
    answered "Organic on Invoice: No" for a season with no sales — a § 205.307(a) claim about a
    crop that may still be on the tree. The PDF branch was corrected on 2026-08-19; its sibling
    was not, which is the recurring class these suites exist to catch.

⛔ Both exports are asserted here. Fixing one of two rendering paths is what produced the defect.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, ProductionEvent, SalesRecord
from product.models import Parcel, Product
from users.models import User


class YieldToSalesScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="yts@test.com", password="x")
        cls.company = Company.objects.create(name="YTS Co")
        cls.establishment = Establishment.objects.create(name="YTS Farm", company=cls.company, state="WA")
        cls.parcel = Parcel.objects.create(name="Bench", establishment=cls.establishment, area=6.0)
        cls.product = Product.objects.create(name="Apples")

    def _production(self, name, *, harvested_lb, sold_lb=None, sale_date=None):
        """A season with a harvest record, and optionally a sale dated AFTER the harvest year."""
        history = History.objects.create(
            name=name,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=harvested_lb,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        ProductionEvent.objects.create(
            history=history,
            type="HA",
            date=timezone.now() - timedelta(days=40),
            created_by=self.user,
            yield_quantity=harvested_lb,
            yield_unit="lb",
        )
        if sold_lb is not None:
            SalesRecord.objects.create(
                production=history,
                sale_date=sale_date or (timezone.now().date()),
                buyer_name="Sample Valley Packing Co.",
                quantity=sold_lb,
                quantity_unit="lb",
                organic_on_invoice=True,
                sale_amount=1000,
            )
        return history

    def _pdf_text(self, history):
        from history.services.audit_export_service import AuditExportService

        service = AuditExportService(history, certification_type="all")
        elements = service._build_mass_balance_section()
        out = []
        for el in elements:
            text = getattr(el, "text", None)
            if text:
                out.append(str(text))
            for attr in ("_cellvalues", "_argW"):
                if hasattr(el, attr) and attr == "_cellvalues":
                    out.append(str(getattr(el, attr)))
        return " || ".join(out)

    def _boxed_production(self):
        """A lot that reaches the boxes-to-pounds branch, where the verdict label is printed.

        ⛔ WHY THIS EXISTS. The naming assertion below passed vacuously without it. That branch
        needs harvest in POUNDS, quantity sold in BOXES, and a box weight; every other fixture in
        this file sells in lb, so the label was never rendered and restoring the old
        "Net inventory reconciliation" wording broke nothing. Found by mutation, 2026-09-24.
        """
        history = self._production("Boxed", harvested_lb=10000, sold_lb=None)
        history.box_weight_lb = 40
        history.save(update_fields=["box_weight_lb"])
        SalesRecord.objects.create(
            production=history,
            sale_date=timezone.now().date(),
            buyer_name="Sample Valley Packing Co.",
            quantity=240,
            quantity_unit="boxes",
            organic_on_invoice=True,
            sale_amount=5000,
        )
        return history

    def _csv_text(self, history):
        """`generate_csv` returns a BytesIO, not bytes — read it, do not `isinstance` it."""
        from history.services.audit_export_service import AuditExportService

        buf = AuditExportService(history, certification_type="all").generate_csv()
        raw = buf.getvalue() if hasattr(buf, "getvalue") else buf
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    # -- naming -----------------------------------------------------------------------------

    def test_the_pdf_section_never_promises_an_inventory_balance(self):
        # The BOXED fixture, deliberately: the verdict label only renders on that branch.
        text = self._pdf_text(self._boxed_production())
        self.assertIn(
            "Yield-to-sales reconciliation",
            text,
            "premise: this fixture must reach the branch that prints the verdict label, or "
            "the negative assertion below proves nothing",
        )
        self.assertNotIn("Net inventory", text)

        history = self._production("Closed season", harvested_lb=1000, sold_lb=900)
        text = self._pdf_text(history)
        self.assertNotIn("Net inventory", text)
        self.assertNotRegex(
            text.replace("not a period mass balance", ""),
            r"(?i)mass-balance audit summary",
        )
        self.assertIn("Yield-to-Sales Reconciliation", text)

    def test_the_pdf_section_states_that_it_is_not_a_period_balance(self):
        history = self._production("Closed season 2", harvested_lb=1000, sold_lb=900)
        text = self._pdf_text(history)
        self.assertIn("not", text)
        self.assertIn("opening", text)
        self.assertIn("inventory", text)

    # -- zero is not missing ----------------------------------------------------------------

    def test_an_unsold_lot_states_its_harvest_minus_sales_rather_than_printing_nothing(self):
        """The October-harvest-January-sale case, caught mid-window."""
        history = self._production("Harvested not yet sold", harvested_lb=702900, sold_lb=None)
        text = self._pdf_text(history)
        self.assertIn("Harvest minus sales recorded", text)

    def test_a_partly_sold_lot_states_the_remainder_too(self):
        history = self._production("Partly sold", harvested_lb=1000, sold_lb=600)
        text = self._pdf_text(history)
        self.assertIn("Harvest minus sales recorded", text)

    def test_a_fully_sold_lot_states_no_remainder(self):
        history = self._production("Fully sold", harvested_lb=1000, sold_lb=1000)
        text = self._pdf_text(history)
        self.assertNotIn("Harvest minus sales recorded", text)

    # -- an unsummable quantity is not an absent sale -----------------------------------------

    def test_mixed_unit_sales_do_not_print_as_no_sales_recorded(self):
        """⛔ `not quantity_sold` IS NOT "no sales".

        `resolve_sales_disclosure` returns quantity=None when live SalesRecord rows disagree on
        unit and cannot be summed honestly. The first cut of the remainder row read that absent
        quantity as an absent SALE, so a production with itemised sales printed "harvested with
        no sales recorded for this production" three rows under "Sold To: <buyer>".

        Missed by every other case in this file because they all use one unit. Flagged in review
        on PR #44, not by this guard.
        """
        history = self._production("Mixed units", harvested_lb=10000, sold_lb=4000)
        SalesRecord.objects.create(
            production=history,
            sale_date=timezone.now().date(),
            buyer_name="Second Buyer Co.",
            quantity=120,
            quantity_unit="boxes",  # a DIFFERENT unit — the sum is now dishonest
            organic_on_invoice=True,
            sale_amount=2000,
        )
        text = self._pdf_text(history)

        self.assertIn(
            "Sold To",
            text,
            "premise: the section must be naming a buyer, or the contradiction cannot arise",
        )
        self.assertNotIn("no sales recorded for this production", text)
        self.assertIn("Not calculable", text)

    def test_the_csv_twin_says_the_same(self):
        history = self._production("Mixed units csv", harvested_lb=10000, sold_lb=4000)
        SalesRecord.objects.create(
            production=history,
            sale_date=timezone.now().date(),
            buyer_name="Second Buyer Co.",
            quantity=120,
            quantity_unit="boxes",
            organic_on_invoice=True,
            sale_amount=2000,
        )
        csv_text = self._csv_text(history)
        self.assertNotIn("no sales recorded for this production", csv_text)
        self.assertIn("Not calculable", csv_text)

    # -- the sibling export ------------------------------------------------------------------

    def test_the_csv_twin_carries_the_same_heading_scope_and_remainder(self):
        history = self._production("CSV unsold", harvested_lb=5000, sold_lb=None)
        csv_text = self._csv_text(history)

        self.assertIn("YIELD-TO-SALES RECONCILIATION", csv_text)
        self.assertNotIn("MASS-BALANCE AUDIT SUMMARY", csv_text)
        self.assertIn("Not a period inventory balance", csv_text)
        self.assertIn("Harvest minus sales recorded", csv_text)

    def test_the_csv_twin_does_not_answer_no_when_there_are_no_sales(self):
        """An absent attestation is not a denial — § 205.307(a) is not asserted against a crop
        that has not been sold."""
        history = self._production("CSV no sales", harvested_lb=5000, sold_lb=None)
        csv_text = self._csv_text(history)

        # ⛔ PARSE the CSV; do not substring it. The first cut asserted
        # `assertNotIn("Organic on Invoice,No", ...)` and failed against the CORRECT output,
        # because "Organic on Invoice,Not applicable yet …" contains that string — "Not"
        # begins with "No". A substring assertion over delimited data tests the delimiter as
        # much as the value.
        import csv as _csv
        import io as _io

        rows = list(_csv.reader(_io.StringIO(csv_text)))
        values = [r[1] for r in rows if len(r) >= 2 and r[0] == "Organic on Invoice"]
        self.assertTrue(values, "the reconciliation section printed no Organic on Invoice row")
        for value in values:
            self.assertNotEqual(
                value,
                "No",
                "a flat No asserts a § 205.307(a) non-conformance about a crop with no sales",
            )
            self.assertIn("Not applicable yet", value)


# ---------------------------------------------------------------------------------------------
# Run 7 (2026-10-03): the dossier read as an inspector. Folded into this CI-listed module so CI
# runs them (adding a module to ci.yml needs a token scope this repo's automation lacks).
# Each test asserts the printed string and its condition, both branches where there are two.
# ---------------------------------------------------------------------------------------------
import hashlib  # noqa: E402

from django.core.files.base import ContentFile  # noqa: E402

from certifications.models import OrganicSystemPlan, PostHarvestFacility  # noqa: E402
from history.models import BusinessEvent, ChemicalEvent, SoilManagementEvent  # noqa: E402
from history.services.audit_export_service import (  # noqa: E402
    AuditExportService,
    _organic_basis_cell,
    _weather_magnitudes,
)
from history.tests.test_pdf_field_coverage import flowable_text  # noqa: E402


class Run7DossierWordingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="r7@test.com", password="x", first_name="Laurel", last_name="B")
        self.company = Company.objects.create(name="R7 Co")
        self.establishment = Establishment.objects.create(name="R7 Farm", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="River", establishment=self.establishment, area=6.0)
        self.history = History.objects.create(
            name="Liberty 2026",
            start_date=timezone.now() - timedelta(days=200),
            product=Product.objects.create(name="Blueberries"),
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _svc(self, cert="organic"):
        return AuditExportService(self.history, certification_type=cert)

    def _csv(self):
        return self._svc().generate_csv().getvalue().decode("utf-8")

    # R7-01 ----------------------------------------------------------------------------------
    def _facility(self, **kw):
        data = dict(
            establishment=self.establishment,
            name="Marion Bend Fruit Co.",
            certification_number="OTCO-0042",
            certifier_name="Oregon Tilth",
            effective_date=timezone.now().date() - timedelta(days=60),
            verification_status="self_reported",
        )
        data.update(kw)
        return PostHarvestFacility.objects.create(**data)

    def test_handler_with_current_dates_no_copy_and_self_reported_claims_nothing(self):
        text = flowable_text(self._svc()._facility_cert_block(self._facility()))
        for word in ("DOCUMENTED", "on file", "current"):
            self.assertNotIn(word, text)
        self.assertIn("No copy of the certificate is held in Trazo.", text)
        self.assertIn("Self-reported (operator-provided; not independently verified)", text)
        self.assertIn("Dates alone do not establish the handler's certification status.", text)

    def test_handler_with_stale_dates_and_no_copy_never_implies_a_certificate_on_file(self):
        facility = self._facility(effective_date=timezone.now().date() - timedelta(days=600))
        text = flowable_text(self._svc()._facility_cert_block(facility))
        self.assertIn("No copy of the certificate is held in Trazo.", text)
        self.assertIn("the certificate dates as entered are more than 15 months old", text)
        self.assertNotIn("on file", text)

    def test_handler_with_a_copy_states_the_copy_and_the_verification_apart(self):
        facility = self._facility(verification_status="verified")
        facility.cert_document.save("cert.pdf", ContentFile(b"%PDF-1.4 cert"), save=True)
        text = flowable_text(self._svc()._facility_cert_block(facility))
        self.assertIn("A copy of the certificate is held in Trazo; it is not included in this export.", text)
        self.assertIn("Verified via USDA Organic Integrity Database", text)
        self.assertNotIn("DOCUMENTED", text)

    # R7-02b, R7-02c ---------------------------------------------------------------------------
    def _plan(self, **kw):
        return OrganicSystemPlan.objects.create(
            establishment=self.establishment, version_number=3, status="active", **kw
        )

    def test_an_active_plan_with_no_approval_date_is_never_called_approved(self):
        self._plan()
        text = flowable_text(self._svc()._build_osp_reference_section())
        self.assertIn("v3 (Active (approval date not recorded in Trazo))", text)
        self.assertNotIn("Active / Approved", text)
        self.assertIn("Not recorded in Trazo", text)

    def test_an_approval_date_is_stated_when_recorded(self):
        self._plan(approved_at=timezone.now())
        text = flowable_text(self._svc()._build_osp_reference_section())
        self.assertIn("Active, approved", text)

    def test_narratives_never_read_as_verbatim_filed_and_name_the_submitted_copy_by_hash(self):
        plan = self._plan()
        text = flowable_text(self._svc()._build_osp_reference_section())
        self.assertNotIn("verbatim", text)
        self.assertIn("as held in Trazo for v3", text)
        self.assertIn("Trazo holds no copy generated at submission for this version.", text)
        body = b"%PDF-1.4 submitted v3"
        plan.submission_pdf.save("v3.pdf", ContentFile(body), save=True)
        text = flowable_text(self._svc()._build_osp_reference_section())
        self.assertIn(f"sha256 {hashlib.sha256(body).hexdigest()}", text)
        self.assertNotIn("verbatim", text)

    def test_a_recorded_but_unreadable_submitted_copy_is_not_called_absent(self):
        from unittest import mock

        plan = self._plan()
        plan.submission_pdf.save("v3.pdf", ContentFile(b"%PDF-1.4"), save=True)
        with mock.patch.object(type(plan.submission_pdf), "open", side_effect=FileNotFoundError("gone")):
            text = flowable_text(self._svc()._build_osp_reference_section())
        self.assertIn("is recorded in Trazo but could not be read for this export", text)
        self.assertNotIn("Trazo holds no copy generated at submission", text)

    def test_the_footer_no_longer_says_the_evidence_satisfies_the_plan(self):
        self._plan()
        text = flowable_text(self._svc()._build_osp_reference_section())
        self.assertNotIn("satisfies one or more practices", text)
        self.assertIn("whether the records meet them is for the certifier", text)

    # R7-03a/b, sanitizer disclosure ----------------------------------------------------------
    def test_a_long_drift_reason_prints_whole_and_the_lookup_column_says_what_it_is(self):
        self._plan()
        event = ChemicalEvent.objects.create(
            history=self.history, date=timezone.now(), description="spray", commercial_name="Rex Lime Sulfur"
        )
        reason = (
            "Input 'Rex Lime Sulfur' not matched to any approved OSP input. " + "Possible match, not confirmed: X. " * 6
        )
        ChemicalEvent.objects.filter(pk=event.pk).update(
            drift_warning={"reason": reason.strip(), "reason_code": "unresolved", "osp_id": 1}
        )
        text = flowable_text(self._svc()._build_drift_findings_section())
        tail = reason.strip()[-80:]
        self.assertGreater(len(reason.strip()), 120)
        self.assertIn(tail, text, "the reason was cut off")
        self.assertIn("Looked up (local copy)", text)
        self.assertIn("It is not a check that a listing is current", text)
        self.assertIn("Sanitizers are not checked against the plan in this section", text)
        self.assertNotIn("Unapproved-Input", text)

    # R7-04 -------------------------------------------------------------------------------------
    def test_a_legacy_yes_is_qualified_like_every_other_selection(self):
        from types import SimpleNamespace

        self.assertEqual(
            _organic_basis_cell(SimpleNamespace(), "yes"),
            "Yes - Organic Approved — grower-selected, basis not recorded",
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="compost",
            amendment_product_name="Rexius Organic Compost",
            amendment_organic_approved="yes",
        )
        csv_text = self._csv()
        # Two CSV cells carry it: the event row's notes and the Organic Status column.
        self.assertGreaterEqual(csv_text.count("grower-selected, basis not recorded"), 2, csv_text)
        self.assertNotIn("Organic: Yes - Organic Approved\n", csv_text)

    def test_the_csv_inspection_history_mirrors_the_pdf_roles_and_status(self):
        BusinessEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="Annual inspection",
            business_type="inspection",
            performed_by="Laurel Brandt",
            verification_status="verified",
            created_by=self.user,
        )
        csv_text = self._csv()
        section = csv_text.split("=== INSPECTION & COMPLIANCE EVENT HISTORY ===", 1)[1]
        header = section.strip().splitlines()[0]
        self.assertIn("Performed By", header)
        self.assertIn("Recorded By", header)
        self.assertNotIn("Inspector", header)
        self.assertIn("Verified (self-reported)", section)
        self.assertIn("Laurel B", section)

    def test_the_nitrogen_line_states_the_operators_selection_and_concludes_nothing(self):
        ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now(),
            description="fish",
            commercial_name="Neptune's Harvest",
            nitrogen_source="organic",
        )
        text = flowable_text(self._svc()._build_chemical_log())
        self.assertIn("the operator recorded the nitrogen source as organic or mined-natural for 1", text)
        self.assertNotIn("no prohibited synthetic nitrogen", text)

    # R7-05 -------------------------------------------------------------------------------------
    def test_sanitation_prints_the_event_date_no_pass_and_names_a_crop_production_citation(self):
        when = timezone.now() - timedelta(days=3)
        ProductionEvent.objects.create(
            history=self.history,
            type="PH",
            date=when,
            created_by=self.user,
            sanitizer_name="SaniDate 5.0 (peracetic acid)",
            sanitizer_ppm=80,
            sanitizer_residual_ppm_at_discharge="4.00",
            rinse_step_documented=False,
            sanitizer_nop_reference="§ 205.601(a)(6) / OMRI",
        )
        text = flowable_text(self._svc()._build_equipment_section())
        self.assertIn(when.date().isoformat(), text)
        self.assertIn("4.00 ppm (no limit assessed in Trazo)", text)
        self.assertNotIn("PASS", text)
        self.assertIn("[REVIEW] 1 post-harvest sanitation record(s) cite § 205.601", text)
        self.assertIn("not recorded: rinse step", text)
        self.assertNotIn("requires a potable-water rinse", text)
        self.assertIn("it does not set one rinse rule for every sanitizer", text)

    def test_a_section_605_reference_draws_no_review_line(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="PH",
            date=timezone.now(),
            created_by=self.user,
            sanitizer_name="Sodium hypochlorite",
            sanitizer_ppm=50,
            rinse_step_documented=True,
            sanitizer_nop_reference="§ 205.605(b) - Chlorine materials",
        )
        text = flowable_text(self._svc()._build_equipment_section())
        self.assertNotIn("cite § 205.601", text)

    # R7-13 -------------------------------------------------------------------------------------
    def test_a_temperature_without_a_unit_never_prints_celsius(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="FP",
            date=timezone.now(),
            created_by=self.user,
            extra_data={"protection_method": "wind_machine", "low_temperature": 30},
        )
        text = flowable_text(self._svc()._build_production_events())
        self.assertIn("30 (unit not recorded)", text)
        self.assertNotIn("30°C", text)
        self.assertEqual(_weather_magnitudes({"highest_temperature": 101}), ["max 101 (unit not recorded)"])
        self.assertEqual(_weather_magnitudes({"highest_temperature": 101, "temperature_unit": "F"}), ["max 101°F"])

    def test_a_frost_temperature_with_its_unit_prints_it(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="FP",
            date=timezone.now(),
            created_by=self.user,
            extra_data={"protection_method": "wind_machine", "low_temperature": 30, "temperature_unit": "F"},
        )
        self.assertIn("30°F", flowable_text(self._svc()._build_production_events()))

    # Attestation ------------------------------------------------------------------------------
    def test_the_attestation_page_says_it_is_not_signed(self):
        text = flowable_text(self._svc()._build_producer_attestation_section())
        self.assertIn("Not signed in Trazo.", text)
        self.assertNotIn("typed electronic attestation", text)


class WorkbookOrderTests(TestCase):
    """Housekeeping (not a reviewer finding): the same records build the same workbook, in date
    order, with the earliest spelling of a name, whatever order the rows were inserted in."""

    def test_rows_follow_record_dates_not_insertion_order(self):
        from certifications.services.common_osp_workbooks import _material_rows

        user = User.objects.create_user(email="wb@test.com", password="x")
        company = Company.objects.create(name="WB Co")
        est = Establishment.objects.create(name="WB Farm", company=company, state="OR")
        parcel = Parcel.objects.create(name="P", establishment=est, area=1.0)
        history = History.objects.create(name="H", start_date=timezone.now(), parcel=parcel, operator=user)
        now = timezone.now()
        # Inserted out of date order, so neither insertion order nor its reverse is date order.
        for name, days in (("Bravo", 9), ("Charlie", 1), ("Alpha", 20), ("ALPHA", 25)):
            ChemicalEvent.objects.create(
                history=history, date=now - timedelta(days=days), description="x", commercial_name=name
            )
        names = [r.name for r in _material_rows(est, None)]
        self.assertEqual(names, ["ALPHA", "Bravo", "Charlie"])
        self.assertEqual(names, [r.name for r in _material_rows(est, None)])


class Run7PlanRecordsTests(TestCase):
    """Run 7 slice 2: the dossier reads change notices across plan versions and summarises the
    current annual-update revision, naming the exact filed document and whether it accompanies the
    dossier. Superseded and withdrawn revisions are listed, never summarised as current."""

    def setUp(self):
        from certifications.models import OSPChangeNotification

        self.notification_model = OSPChangeNotification
        user = User.objects.create_user(email="r7b@test.com", password="x")
        company = Company.objects.create(name="R7B Co")
        self.est = Establishment.objects.create(name="R7B Farm", company=company, state="OR")
        parcel = Parcel.objects.create(name="Bottom", establishment=self.est, area=6.0)
        self.history = History.objects.create(
            name="Carrots 2026",
            start_date=timezone.now().replace(year=2026, month=4, day=1),
            parcel=parcel,
            operator=user,
        )
        self.v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="superseded")
        self.v3 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=3, status="active", previous_version=self.v1
        )

    def _text(self):
        return flowable_text(
            AuditExportService(self.history, certification_type="organic")._build_osp_reference_section()
        )

    def _revision(self, number, **kw):
        from certifications.models import OSPAnnualUpdate

        return OSPAnnualUpdate.objects.create(
            establishment=self.est, prior_osp=self.v3, reporting_year=2026, revision_number=number, **kw
        )

    def test_a_notice_filed_on_v1_appears_in_the_v3_dossier(self):
        self.notification_model.objects.create(
            osp=self.v1,
            change_category=self.notification_model.CATEGORY_ACREAGE_FIELD_ADDITION,
            description="Added Upper Terrace to organic acreage.",
        )
        text = self._text()
        self.assertIn("Added Upper Terrace to organic acreage.", text)
        self.assertIn("(filed against v1)", text)
        self.assertNotIn("No change notifications are on file", text)

    def test_with_no_notice_on_any_version_the_empty_state_says_so(self):
        self.assertIn("No change notifications are on file for this plan or its earlier versions.", self._text())

    def test_the_current_revision_is_summarised_with_its_exact_document_and_the_rest_listed(self):
        r1 = self._revision(1, submitted_at=timezone.now(), superseded_at=timezone.now())
        r2 = self._revision(
            2,
            corrects=r1,
            submitted_at=timezone.now(),
            signer_name="Laurel Brandt",
            signer_title="Member-manager",
            signed_at=timezone.now(),
            signed_content_sha256="a" * 64,
            filed_pdf=b"%PDF-1.4 rev2",
            filed_sha256="b" * 64,
            application_info_changes="Added the Upper Terrace parcel.",
            agent_requested_info_none=True,
        )
        self._revision(3, submitted_at=timezone.now(), withdrawn_at=timezone.now(), withdrawal_reason="filed twice")
        text = self._text()
        self.assertIn("Summary of revision 2 of the 2026 annual update", text)
        self.assertIn("2, corrects revision 1", text)
        self.assertIn("Laurel Brandt, Member-manager", text)
        self.assertIn("a" * 64, text)
        self.assertIn(f"annual-update/2026-revision-{r2.revision_number}.pdf, sha256 {'b' * 64}", text)
        self.assertIn("Not included in this dossier; it is in the renewal packet.", text)
        self.assertIn("Added the Upper Terrace parcel.", text)
        self.assertIn("Nothing further, as stated by the operator", text)
        self.assertIn("revision 1: superseded", text)
        self.assertIn("revision 3: withdrawn", text)
        self.assertNotIn("Summary of revision 3", text)
        self.assertNotIn("Summary of revision 1", text)

    def test_a_revision_with_no_frozen_copy_says_so_and_an_unsigned_one_says_unsigned(self):
        self._revision(1)
        text = self._text()
        self.assertIn("No frozen copy of this revision is held in Trazo.", text)
        self.assertIn("Not signed in Trazo", text)

    def test_a_year_whose_revisions_are_all_superseded_or_withdrawn_has_no_current_filing(self):
        self._revision(1, submitted_at=timezone.now(), withdrawn_at=timezone.now(), withdrawal_reason="error")
        text = self._text()
        self.assertIn("No current 2026 annual update (§ 205.406): every revision on file is withdrawn", text)
        self.assertNotIn("Summary of revision", text)
