"""
USDA Manure Application / Food Crop Harvest Interval Record — the last two columns.

WHY (2026-08-12): the packet already carried date applied, interval, amendment type, earliest
safe harvest and planned harvest. USDA's published form asks for two more:

    "How Applied / Incorporated"    e.g. "Manure spreader disk in"
    "Manure Type, Form and Source"  e.g. "Chicken, dry, on farm"

USDA writes the second as ONE free-text column. Three enums store the same fact and stay
queryable — safe here in a way it was not for `buffer_disposition_quantity` (deliberately free
text, because a bin count has no closed vocabulary) since animal, form and on/off-farm all do.

None of this is added to `record_completeness`. The forms are OPTIONAL under § 205.103 and no
CFR paragraph enumerates these facets, so requiring them would be Trazo inventing a rule — the
same call already made for #7 `application_purpose`.

⚠️ These columns do NOT affect the 90/120-day interval. That turns on whether the edible
portion contacts the soil (§ 205.203(c)(1)(ii)-(iii)), not on incorporation. A test that let
"incorporated" shorten an interval would encode a compliance error.
"""

import csv
import io
import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import Production, SoilManagementEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class ManureTypeFormSourceDisplayTests(TestCase):
    """The helper that rebuilds USDA's single column from the three facets."""

    def test_renders_usdas_own_example(self):
        event = SoilManagementEvent(manure_animal_source="poultry", manure_form="dry", manure_origin="on_farm")
        self.assertEqual(
            event.manure_type_form_source_display(),
            "Poultry (chicken, turkey, duck), Dry / solid, Produced on this operation",
        )

    def test_omits_facets_the_grower_did_not_record(self):
        event = SoilManagementEvent(manure_animal_source="cattle")
        self.assertEqual(event.manure_type_form_source_display(), "Cattle / dairy")

    def test_returns_empty_when_nothing_is_recorded(self):
        """Empty, not a dash. The caller decides whether absence is a gap — and here it is
        not one, because these facets are form parity rather than a § 205.103 requirement."""
        self.assertEqual(SoilManagementEvent().manure_type_form_source_display(), "")


class ManureColumnsReachBothExportsTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="manure@test.com", password="x")
        company = Company.objects.create(name="Manure Co")
        establishment = Establishment.objects.create(name="MC1", company=company)
        parcel = Parcel.objects.create(name="Block 1", establishment=establishment, area=10)
        product = Product.objects.create(name="Walnuts")
        self.history = Production.objects.create(
            name="Manure Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _event(self, **kwargs):
        defaults = dict(
            history=self.history,
            type="OM",
            date=timezone.now(),
            amendment_type="manure",
            manure_application_date=timezone.now().date(),
            manure_harvest_interval="120",
        )
        defaults.update(kwargs)
        return SoilManagementEvent.objects.create(**defaults)

    def _pdf_text(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def _csv_text(self):
        buf = AuditExportService(self.history, certification_type="organic").generate_csv()
        raw = buf.getvalue().decode("utf-8-sig")
        return "\n".join(",".join(row) for row in csv.reader(io.StringIO(raw)))

    def test_pdf_carries_type_form_source_and_method(self):
        self._event(
            manure_animal_source="poultry",
            manure_form="dry",
            manure_origin="on_farm",
            manure_application_method="broadcast_incorporated",
        )
        text = self._pdf_text()
        self.assertIn("Poultry (chicken, turkey, duck), Dry / solid, Produced on this operation", text)
        self.assertIn("applied: Broadcast, incorporated (disked or tilled in)", text)

    def test_csv_carries_the_same_facts(self):
        """A field reaching one export and not the other is how one production came to give
        two different answers about its buyer — see resolve_sales_disclosure()."""
        self._event(
            manure_animal_source="poultry",
            manure_form="dry",
            manure_origin="on_farm",
            manure_application_method="broadcast_incorporated",
        )
        text = self._csv_text()
        self.assertIn("Poultry (chicken, turkey, duck), Dry / solid, Produced on this operation", text)
        self.assertIn("applied: Broadcast, incorporated (disked or tilled in)", text)

    def test_csv_still_carries_them_when_the_interval_is_not_applicable(self):
        """Composted / NOP 5006 manure carries interval "na".

        The CSV's existing manure block sits inside an `if manure_harvest_interval != "na"`
        guard, so writing these facts inside it would drop them for exactly those events while
        the PDF kept printing them — a divergence bug identical to the one this file exists to
        prevent.
        """
        self._event(
            manure_harvest_interval="na",
            manure_treatment="composted",
            manure_animal_source="cattle",
            manure_form="bedded_pack",
        )
        self.assertIn("Cattle / dairy, Bedded pack (manure with bedding)", self._csv_text())

    def test_nothing_is_printed_when_nothing_is_recorded(self):
        """Silence where the grower recorded nothing — an empty label would read as a gap."""
        self._event()
        self.assertNotIn("Manure type, form, source and application method", self._pdf_text())

    def test_incorporation_does_not_alter_the_harvest_interval(self):
        """§ 205.203(c)(1)(ii)-(iii) turns on edible-portion soil contact, NOT incorporation.

        Pinned because "we disked it in, so the interval is shorter" is a plausible-sounding
        misreading, and encoding it would be a compliance error rather than a display bug.
        """
        event = self._event(manure_application_method="broadcast_incorporated")
        self.assertEqual(event.manure_harvest_interval, "120")
        event.manure_application_method = "broadcast_surface"
        event.save()
        event.refresh_from_db()
        self.assertEqual(event.manure_harvest_interval, "120")


class PlannedHarvestInsideIntervalTests(TestCase):
    """The plan itself, not the label on it (§ 205.203(c)(1)).

    Two independent checks live on this data and only one existed. The crop-rule check asks
    whether the farmer picked the interval their crop requires — it validates the LABEL. It
    says nothing about the dates. A soil-contact crop with the correct 120 days selected
    clears that check and still violates the rule if harvest is planned 60 days after
    application, and the packet printed both dates side by side in black without comparing
    them. The field's own help text promised otherwise: "so the 90/120-day interval can be
    checked against your plan".

    The negative case matters as much as the positive one here: a check that fires on a
    compliant plan would train farmers to ignore it.
    """

    def setUp(self):
        user = User.objects.create_user(email="interval@test.com", password="x")
        company = Company.objects.create(name="Interval Co")
        establishment = Establishment.objects.create(name="IC1", company=company)
        parcel = Parcel.objects.create(name="Block 9", establishment=establishment, area=10)
        product = Product.objects.create(name="Walnuts")
        self.history = Production.objects.create(
            name="Interval Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _event(self, applied, planned, interval="120"):
        import datetime

        return SoilManagementEvent.objects.create(
            history=self.history,
            type="OM",
            date=timezone.now(),
            amendment_type="manure",
            manure_application_date=datetime.date.fromisoformat(applied),
            manure_harvest_date_planned=datetime.date.fromisoformat(planned),
            manure_harvest_interval=interval,
        )

    def _pdf_text(self):
        from pdfminer.high_level import extract_text

        buf = AuditExportService(self.history, certification_type="organic").generate_pdf(strict_ofpp=False)
        return re.sub(r"\s+", " ", extract_text(io.BytesIO(buf.getvalue())))

    def test_flags_a_plan_that_lands_inside_the_interval_it_declares(self):
        # 2026-06-01 + 120 days = 2026-09-29. Planned 2026-07-31 is 60 days short.
        self._event("2026-06-01", "2026-07-31")
        text = self._pdf_text()
        self.assertIn("60 days", text, "the shortfall was not quantified anywhere in the packet")
        self.assertIn(
            "205.203(c)(1)",
            text,
            "the finding must cite the clause the inspector will look up",
        )

    def test_stays_silent_when_the_plan_clears_the_interval(self):
        # 2026-06-01 + 120 days = 2026-09-29; planning 2026-10-15 is compliant.
        self._event("2026-06-01", "2026-10-15")
        text = self._pdf_text()
        self.assertNotIn(
            "days short",
            text,
            "a compliant plan was flagged — a check that cries wolf gets ignored",
        )

    def test_a_correct_label_does_not_excuse_a_short_plan(self):
        """The regression this exists for: crop-rule check passes, dates do not."""
        self._event("2026-06-01", "2026-07-31", interval="120")
        text = self._pdf_text()
        # 120 is the right label for a soil-contact crop, so the LABEL check has nothing to
        # say. The finding must come from the dates regardless.
        self.assertIn("days short", text)

    def test_reports_reversed_dates_as_a_typo_not_a_shortfall(self):
        """Harvest planned BEFORE the manure went on.

        `actual_gap` goes negative, which the first cut of this check reported as
        "N days short" — sending the farmer to widen an interval when the real fault is one of
        the two dates. The two cases need different words because they need different fixes.
        """
        self._event("2026-07-01", "2026-06-01")
        text = self._pdf_text()
        self.assertIn("out of order", text)
        self.assertIn("30 days EARLIER", text)
        self.assertNotIn("days short", text, "a reversed pair was reported as an interval shortfall")

    def test_an_unparseable_date_costs_the_finding_not_the_export(self):
        """A date column holding an ISO string is a real shape in this codebase.

        `str - date` raises TypeError, and the idiom around this code catches only
        (ValueError, AttributeError) — so the export died rather than skipping one row.
        """
        ev = self._event("2026-06-01", "2026-07-31")
        # Bypass the ORM's date coercion the way a raw write would.
        SoilManagementEvent.objects.filter(pk=ev.pk).update(manure_harvest_date_planned=None)
        ev.refresh_from_db()
        text = self._pdf_text()  # must not raise
        self.assertIn("Manure Handling Records", text, "the manure section vanished entirely")
