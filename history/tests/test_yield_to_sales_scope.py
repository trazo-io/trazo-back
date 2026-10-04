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
        self.assertIn("Not included in this dossier; it is in the renewal packet for v3.", text)
        self.assertIn("the current filed revision for that year", text)
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

    def test_an_unfiled_draft_is_called_a_draft_and_flagged(self):
        """Review of back #111: the newest unfiled revision is a draft, not the year's filing."""
        self._revision(1)
        text = self._text()
        self.assertIn("Revision 1 of the 2026 annual update is a draft: it has not been filed", text)
        self.assertIn("[REVIEW] 7 CFR 205.406:</b> the 2026 annual update is not filed.", text)
        self.assertNotIn("the current filed revision", text)

    def test_a_filing_outside_the_packets_year_is_not_said_to_be_in_the_packet(self):
        """Review of back #111: the renewal packet ships its newest year's revisions only."""
        from certifications.models import OSPAnnualUpdate

        self.history.start_date = self.history.start_date.replace(year=2025)
        self.history.save(update_fields=["start_date"])
        OSPAnnualUpdate.objects.create(
            establishment=self.est,
            prior_osp=self.v3,
            reporting_year=2025,
            revision_number=1,
            submitted_at=timezone.now(),
            filed_pdf=b"%PDF-1.4 2025",
            filed_sha256="c" * 64,
        )
        self._revision(1, submitted_at=timezone.now(), filed_pdf=b"%PDF-1.4 2026", filed_sha256="d" * 64)
        text = self._text()
        self.assertIn("annual-update/2025-revision-1.pdf", text)
        self.assertIn("not in the current renewal packet, which carries the 2026 filing", text)
        self.assertNotIn("it is in the renewal packet", text)

    def test_a_year_whose_revisions_are_all_superseded_or_withdrawn_has_no_current_filing(self):
        self._revision(1, submitted_at=timezone.now(), withdrawn_at=timezone.now(), withdrawal_reason="error")
        text = self._text()
        self.assertIn("No current 2026 annual update (§ 205.406): every revision on file is withdrawn", text)
        self.assertNotIn("Summary of revision", text)
        # Review of back #111: the REVIEW and the spanning-year lines are kept in this state.
        self.assertIn("no current annual update reaffirms the OSP for 2026", text)

    def test_a_withdrawn_only_year_still_discloses_the_years_the_production_runs_into(self):
        self.history.finish_date = self.history.start_date.replace(year=2027, month=6)
        self.history.save(update_fields=["finish_date"])
        self._revision(1, submitted_at=timezone.now(), withdrawn_at=timezone.now(), withdrawal_reason="error")
        self.assertIn("this production runs into 2027", self._text())


class Run7AggregationTests(TestCase):
    """Run 7 slice 3: purchases grouped only on identical details and labelled provisional;
    conflicts kept unresolved beside the total; an unsold harvest lot named; compost assessed
    from feedstock, C:N basis and interval, never "N/A" after the question is raised; handler rows
    say what record they are."""

    def setUp(self):
        self.user = User.objects.create_user(email="r7c@test.com", password="x")
        company = Company.objects.create(name="R7C Co")
        self.est = Establishment.objects.create(name="R7C Farm", company=company, state="OR")
        parcel = Parcel.objects.create(name="Home Field East", establishment=self.est, area=6.0)
        self.history = History.objects.create(
            name="Duke 2026", start_date=timezone.now() - timedelta(days=200), parcel=parcel, operator=self.user
        )
        self.when = timezone.now() - timedelta(days=100)

    def _svc(self):
        return AuditExportService(self.history, certification_type="all")

    def _chem(self, name, qty, unit="oz", invoice="WILCO-2026-20411", lot="ENT-26-0288", days=100, bought=None, **kw):
        return ChemicalEvent.objects.create(
            history=self.history,
            date=timezone.now() - timedelta(days=days),
            description="spray",
            commercial_name=name,
            supplier_name="Wilco Ag",
            purchase_invoice=invoice,
            chemical_lot_number=lot,
            purchase_date=bought or (timezone.now() - timedelta(days=110)).date(),
            quantity_purchased=qty,
            quantity_purchased_unit=unit,
            **kw,
        )

    def _mass_balance(self):
        return flowable_text(self._svc()._build_mass_balance_section())

    # R7-06 ---------------------------------------------------------------------------------------
    def test_one_invoice_carried_by_two_sprays_is_counted_once_and_labelled_provisional(self):
        bought = (timezone.now() - timedelta(days=110)).date()
        self._chem("Entrust SC", 128, days=100, bought=bought)
        self._chem("Entrust SC", 128, days=90, bought=bought)
        self._chem("Serenade Opti", 232, invoice="WILCO-2026-04991", lot="SER-1", bought=bought)
        text = self._mass_balance()
        self.assertIn("carried by 2 applications", text)
        self.assertIn("provisional grouping: Trazo holds no purchase-line identifier", text)
        self.assertIn("360.00 (provisional", text)
        self.assertNotIn("488", text)
        self.assertIn(bought.isoformat(), text)

    def test_the_same_lot_with_a_different_quantity_stays_unresolved_beside_the_total(self):
        self._chem("Entrust SC", 128)
        self._chem("Entrust SC", 64)
        text = self._mass_balance()
        self.assertEqual(text.count("unresolved: same invoice or lot"), 2)
        self.assertIn("no line counted; 2 unresolved line(s) totalling 192.00 oz are not included", text)

    def test_an_invoice_typed_in_another_case_is_the_same_invoice(self):
        """Review of back #112: identifiers are compared without case or spacing differences."""
        bought = (timezone.now() - timedelta(days=110)).date()
        self._chem("Entrust SC", 128, invoice="WILCO-2026-20411", lot="", bought=bought)
        self._chem("Entrust SC", 128, invoice="wilco-2026-20411 ", lot="", days=90, bought=bought)
        text = self._mass_balance()
        self.assertIn("carried by 2 applications", text)
        self.assertIn("128.00 (provisional", text)

    def test_a_proven_duplicate_stays_together_when_another_line_conflicts(self):
        """Review of back #112: 128/128/64 on one lot is two purchases in conflict, not three."""
        bought = (timezone.now() - timedelta(days=110)).date()
        self._chem("Entrust SC", 128, bought=bought)
        self._chem("Entrust SC", 128, days=90, bought=bought)
        self._chem("Entrust SC", 64, days=80, bought=bought)
        text = self._mass_balance()
        self.assertIn("no line counted; 2 unresolved line(s) totalling 192.00 oz are not included", text)
        self.assertIn("carried by 2 applications; unresolved", text)

    def test_the_same_lot_on_two_invoices_is_never_merged(self):
        self._chem("Entrust SC", 128, invoice="A-1")
        self._chem("Entrust SC", 128, invoice="A-2")
        rows, totals = __import__("history.services.audit_export_service", fromlist=["_purchase_rows"])._purchase_rows(
            ChemicalEvent.objects.filter(history=self.history), []
        )
        self.assertEqual([r.state for r in rows], ["unresolved", "unresolved"])
        self.assertEqual(totals["oz"]["counted"], 0)

    def test_two_products_on_one_invoice_are_two_purchases(self):
        self._chem("Entrust SC", 128, lot="L1")
        self._chem("Grandevo WDG", 6, unit="lb", lot="L2")
        text = self._mass_balance()
        self.assertNotIn("unresolved", text)
        self.assertIn("Total Purchased (lb)", text)
        self.assertIn("Total Purchased (oz)", text)

    def test_a_line_with_no_invoice_or_lot_is_counted_and_labelled(self):
        self._chem("Feather Meal", 50, unit="lb", invoice="", lot="")
        self.assertIn("(no invoice or lot recorded)", self._mass_balance())

    def test_soil_purchases_reach_the_csv(self):
        SoilManagementEvent.objects.create(
            history=self.history,
            date=self.when,
            description="sulfur",
            amendment_product_name="Tiger 90CR",
            amendment_quantity_purchased=4000,
            amendment_quantity_purchased_unit="lb",
        )
        csv_text = self._svc().generate_csv().getvalue().decode("utf-8")
        self.assertIn("Tiger 90CR", csv_text.split("Qty Purchased", 1)[1])
        self.assertIn("Total Purchased (lb)", csv_text)

    # R7-07b ----------------------------------------------------------------------------------
    def test_a_harvest_lot_on_no_sale_is_named(self):
        picks = [
            ProductionEvent.objects.create(
                history=self.history,
                type="HA",
                date=timezone.now() - timedelta(days=d),
                created_by=self.user,
                yield_quantity=1000,
                yield_unit="lb",
                harvest_lot_code=code,
            )
            for d, code in ((60, "CBF-26-HFE-P1"), (50, "CBF-26-HFE-02"))
        ]
        sale = SalesRecord.objects.create(
            production=self.history,
            sale_date=timezone.now().date(),
            buyer_name="Cascade Organic",
            quantity=900,
            quantity_unit="lb",
            organic_on_invoice=True,
        )
        sale.harvest_events.add(picks[1])
        text = self._mass_balance()
        self.assertIn("[REVIEW] 1 harvest record(s) of this production are on no sales record: CBF-26-HFE-P1", text)

    # R7-09 -----------------------------------------------------------------------------------
    def _compost(self, feedstock, *, purchased=False, saved=False, cn=18):
        ev = SoilManagementEvent(
            history=self.history,
            date=self.when,
            description="compost",
            type="OM" if purchased else "CO",
            amendment_type="compost",
            amendment_product_name="Rexius Organic Compost" if purchased else "",
            compost_feedstock=feedstock,
            compost_initial_cn_ratio=cn,
        )
        if saved:
            ev.save()
        return ev

    def test_compost_branches_never_print_na_and_name_what_is_missing(self):
        from history.services.audit_export_service import _compost_out_of_range_assessment as assess

        harvest = [(self.when + timedelta(days=130)).date()]
        cases = {
            "manure_interval": (self._compost("horse manure + straw"), harvest),
            "manure_no_interval": (self._compost("horse manure + straw"), []),
            "plant_only": (self._compost("Carrot trim and prunings, plant material only, no manure"), harvest),
            "unresolved_purchased": (self._compost("yard debris, manure", purchased=True), harvest),
            "unresolved_not_stated": (self._compost("yard debris, food waste"), harvest),
            "unresolved_not_recorded": (self._compost(""), harvest),
            # Review of back #112: an exclusion phrase must not hide a named manure ingredient.
            "unresolved_contradictory": (self._compost("straw and plant material only, plus chicken litter"), harvest),
        }
        out = {name: assess(ev, dates, 120) for name, (ev, dates) in cases.items()}
        self.assertEqual(out["manure_interval"][0], "manure_interval")
        self.assertIn("recorded application to first harvest: 130 days", out["manure_interval"][1])
        self.assertIn("(120 days for this crop)", out["manure_interval"][1])
        self.assertEqual(out["manure_no_interval"][0], "manure_no_interval")
        self.assertIn("interval not recorded", out["manure_no_interval"][1])
        self.assertEqual(out["plant_only"][0], "plant_only")
        self.assertIn("not raw manure", out["plant_only"][1])
        self.assertIn("finished-product analysis", out["unresolved_purchased"][1])
        self.assertIn("whether the feedstock contained manure", out["unresolved_not_stated"][1])
        self.assertIn("missing: the feedstock", out["unresolved_not_recorded"][1])
        self.assertIn("whether the feedstock contained manure", out["unresolved_contradictory"][1])
        for name in (
            "unresolved_purchased",
            "unresolved_not_stated",
            "unresolved_not_recorded",
            "unresolved_contradictory",
        ):
            self.assertEqual(out[name][0], "unresolved", name)
            self.assertIn("Manure interval assessment unresolved", out[name][1], name)
        for _, text in out.values():
            self.assertNotIn("N/A", text)

    def test_the_snapshot_raw_manure_row_is_not_na_after_the_compost_row_raised_it(self):
        self._compost("yard debris, food waste, manure (Rexius)", purchased=True, saved=True)
        rows = {r["label"]: r for r in self._svc().compliance_snapshot_rows()}
        manure = next(r for label, r in rows.items() if label.startswith("Raw manure interval"))
        self.assertEqual(manure["status"], "REVIEW")
        self.assertIn("Manure interval assessment unresolved", manure["detail"])
        compost = rows["Compost (§ 205.203(c)(2))"]
        self.assertNotIn("must be handled as raw manure", compost["detail"])

    def test_purchased_compost_reaches_the_soil_compost_table_with_its_assessment(self):
        self._compost("yard debris, food waste, manure (Rexius)", purchased=True, saved=True)
        text = flowable_text(self._svc()._build_soil_section())
        self.assertIn("Compost Temperature Records", text)
        self.assertIn("18:1", text)
        self.assertIn("No (C:N)", text)
        self.assertIn("Manure interval assessment unresolved", text)

    # R7-11 -----------------------------------------------------------------------------------
    def test_a_transport_record_is_never_labelled_a_harvest(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="TP",
            date=self.when,
            created_by=self.user,
            sent_to_handler_date=self.when.date(),
            quantity_sent_to_handler=30000,
        )
        text = flowable_text(self._svc()._build_handler_round_trip_subtable())
        self.assertNotIn("Harvest Date", text)
        self.assertIn(f"{self.when.date().isoformat()} (", text)
        self.assertNotIn("(harvesting)", text)

    # R7-09, operation dossier -----------------------------------------------------------------
    def test_the_operation_dossier_prints_each_productions_snapshot(self):
        from unittest import mock

        from history.services.operation_audit_export_service import OperationAuditExportService

        with mock.patch.object(AuditExportService, "_build_compliance_snapshot", return_value=[]) as snapshot:
            OperationAuditExportService(self.est, "organic").generate_pdf()
        self.assertGreaterEqual(snapshot.call_count, 1)
class Run7RetentionPlantingTests(TestCase):
    """Run 7 slice 4: the retention date is never earlier than five years after any covered
    record's creation, moves forward when a record arrives after close, is calculated for open
    seasons, and is described with only the enforcement Trazo performs. Planting-stock
    applicability is read from the records, never from the crop's name."""

    def setUp(self):
        self.user = User.objects.create_user(email="r7d@test.com", password="x")
        company = Company.objects.create(name="R7D Co")
        self.est = Establishment.objects.create(name="R7D Farm", company=company, state="OR")
        self.parcel = Parcel.objects.create(name="River Block", establishment=self.est, area=6.0)

    def _production(self, crop="Blueberries", finished=True, start=None):
        start = start or timezone.now().replace(year=2026, month=3, day=1)
        history = History.objects.create(
            name=f"{crop} 2026",
            start_date=start,
            product=Product.objects.get_or_create(name=crop)[0],
            parcel=self.parcel,
            operator=self.user,
        )
        if finished:
            finish = start.replace(month=8, day=12)
            from history.models import compute_retention_until

            History.objects.filter(pk=history.pk).update(
                finish_date=finish, retention_until=compute_retention_until(finish)
            )
            history.refresh_from_db()
        return history

    # R7-10 ----------------------------------------------------------------------------------
    def test_a_sale_recorded_after_close_moves_the_date_to_its_creation_plus_five_years(self):
        from history.models import compute_retention_until

        history = self._production()
        before = history.retention_until
        SalesRecord.objects.create(production=history, sale_date=timezone.now().date(), buyer_name="B", quantity=1)
        history.refresh_from_db()
        self.assertEqual(history.retention_until, max(before, compute_retention_until(timezone.now().date())))
        self.assertGreater(history.retention_until, before)

    def test_the_stored_date_is_never_shortened(self):
        history = self._production()
        far = history.retention_until.replace(year=2040)
        History.objects.filter(pk=history.pk).update(retention_until=far)
        SalesRecord.objects.create(production=history, sale_date=timezone.now().date(), buyer_name="B", quantity=1)
        history.refresh_from_db()
        self.assertEqual(history.retention_until, far)

    def test_the_floor_is_never_earlier_than_any_records_creation(self):
        from history.models import compute_retention_until
        from history.retention import retention_floor

        history = self._production()
        ChemicalEvent.objects.create(history=history, date=timezone.now(), description="late entry")
        self.assertGreaterEqual(retention_floor(history), compute_retention_until(timezone.now().date()))

    def test_an_event_the_audit_log_does_not_cover_still_counts_by_its_date(self):
        """A seeded or imported event has no audit-log creation entry; its own date is the floor."""
        from auditlog.models import LogEntry

        from history.models import compute_retention_until
        from history.retention import retention_floor

        history = self._production()
        later = timezone.now() + timedelta(days=40)
        event = ChemicalEvent.objects.create(history=history, date=later, description="imported")
        LogEntry.objects.filter(object_pk=str(event.pk)).delete()
        self.assertGreaterEqual(retention_floor(history), compute_retention_until(later.date()))

    def test_an_open_season_gets_a_calculated_date_and_is_not_called_protected(self):
        from history.services.audit_export_service import _retention_detail

        history = self._production(finished=False)
        ChemicalEvent.objects.create(history=history, date=timezone.now(), description="x")
        text = _retention_detail([history], [])
        self.assertIn("1 season(s) still running: calculated date at least", text)
        self.assertIn("not deletion-protected by Trazo until finished", text)

    def test_the_dossier_states_the_date_and_no_unverified_durability_claim(self):
        history = self._production()
        text = flowable_text(AuditExportService(history, certification_type="organic")._build_soe_compliance_section())
        self.assertIn("Kept until at least", text)
        self.assertIn("Deletion is refused before that date.", text)
        self.assertNotIn("point-in-time recovery", text)
        self.assertNotIn("Records remain accessible", text)

    def test_the_migration_moves_dates_forward_only(self):
        import importlib

        from django.apps import apps

        history = self._production()
        SalesRecord.objects.create(production=history, sale_date=timezone.now().date(), buyer_name="B", quantity=1)
        History.objects.filter(pk=history.pk).update(retention_until=history.finish_date.date())
        importlib.import_module("history.migrations.0242_retention_floor").forward(apps, None)
        history.refresh_from_db()
        self.assertGreaterEqual(history.retention_until.year, timezone.now().year + 5)
        far = history.retention_until.replace(year=2040)
        History.objects.filter(pk=history.pk).update(retention_until=far)
        importlib.import_module("history.migrations.0242_retention_floor").forward(apps, None)
        history.refresh_from_db()
        self.assertEqual(history.retention_until, far)

    # R7-14 ----------------------------------------------------------------------------------
    def _seed_text(self, history):
        return flowable_text(AuditExportService(history, certification_type="organic")._build_seed_stock_section())

    def test_an_established_blueberry_block_with_no_new_planting_says_when_it_was_there(self):
        from product.models import ParcelCropHistory

        ParcelCropHistory.objects.create(parcel=self.parcel, year=2023, crop_grown="Blueberries ('Duke')")
        text = self._seed_text(self._production())
        self.assertIn("since at least 2023", text)
        self.assertNotIn("standard inspection finding", text)
        self.assertNotIn("[REVIEW]", text)

    def test_a_replacement_planting_on_the_established_block_is_assessed(self):
        from product.models import ParcelCropHistory

        ParcelCropHistory.objects.create(parcel=self.parcel, year=2023, crop_grown="Blueberries ('Duke')")
        history = self._production()
        ProductionEvent.objects.create(
            history=history, type="PL", date=timezone.now(), created_by=self.user, seeds_source="commercial"
        )
        text = self._seed_text(history)
        self.assertNotIn("No planting event is recorded", text)
        self.assertNotIn("since at least", text)

    def test_annual_strawberries_without_a_planting_record_are_a_question_not_a_finding(self):
        text = self._seed_text(self._production(crop="Strawberries"))
        self.assertIn("[REVIEW] 7 CFR 205.204:</b> no planting record for this season", text)
        self.assertNotIn("standard inspection finding", text)
        self.assertNotIn("3+", text)

    def test_annual_strawberries_with_a_planting_record_are_assessed(self):
        history = self._production(crop="Strawberries")
        ProductionEvent.objects.create(
            history=history, type="PL", date=timezone.now(), created_by=self.user, seeds_source="commercial"
        )
        text = self._seed_text(history)
        self.assertNotIn("no planting record for this season", text)
