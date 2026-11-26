"""
A2 + A6 (2026-06 NOP-alignment audit).

A2 — non-organic seed/planting-stock commercial-availability search (NOP 5029 /
     7 CFR 205.204(a)(1)) is enforced on the API save path (UpdateProductionEventSerializer
     handles both create + update). Re-enabled now that the planting form ships the
     seed-search widget so the farmer can satisfy it.
A6 — frost-protection (FP) events no longer silently drop their technique
     (extra_data.protection_method) and trigger temperature (low_temperature) from the
     certifier PDF, and "FP" renders as a human label, not the raw code.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from rest_framework import serializers as drf_serializers

from carbon.models import CropType
from company.models import Company, Establishment
from history.models import Production, ProductionEvent
from history.serializers import UpdateProductionEventSerializer
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


class SeedSearchValidationTests(TestCase):
    """A2 — the >= 3-supplier search rule on the API write path (create + update)."""

    def _validate(self, **data):
        # Object-level validate() directly, isolating the seed rule.
        return UpdateProductionEventSerializer().validate(data)

    def test_non_organic_pl_without_three_attempts_rejected(self):
        with self.assertRaises(drf_serializers.ValidationError) as ctx:
            self._validate(
                type="PL",
                seed_certification_status="non_organic_untreated",
                seed_search_attempts=[],
            )
        self.assertIn("seed_search_attempts", ctx.exception.detail)

    def test_non_organic_pl_with_two_attempts_accepted(self):
        """Changed 2026-08-15: 205.204 sets no supplier COUNT.

        Three is a certifier expectation from USDA's optional Guide, not rule text. Zero
        documented suppliers is still rejected (the test above) because that leaves the
        exemption with no ground at all.
        """
        attempts = [{"supplier": "A"}, {"supplier": "B"}]
        out = self._validate(
            type="PL",
            seed_certification_status="non_organic_treated",
            seed_search_attempts=attempts,
        )
        self.assertEqual(out["seed_search_attempts"], attempts)

    def test_non_organic_tr_without_attempts_rejected(self):
        """Transplanting was exempt from this rule until 2026-08-15."""
        with self.assertRaises(drf_serializers.ValidationError) as ctx:
            self._validate(
                type="TR",
                seed_certification_status="non_organic_untreated",
                seed_search_attempts=[],
            )
        self.assertIn("seed_search_attempts", ctx.exception.detail)

    def test_non_organic_pl_with_three_attempts_ok(self):
        attempts = [{"supplier": "A"}, {"supplier": "B"}, {"supplier": "C"}]
        out = self._validate(
            type="PL",
            seed_certification_status="non_organic_treated",
            seed_search_attempts=attempts,
        )
        self.assertEqual(out["seed_search_attempts"], attempts)

    def test_organic_pl_without_attempts_ok(self):
        out = self._validate(
            type="PL",
            seed_certification_status="certified_organic",
            seed_search_attempts=[],
        )
        self.assertEqual(out["type"], "PL")

    def test_a_count_instead_of_a_supplier_list_is_a_field_error_not_a_500(self):
        """`seed_search_attempts` is a JSONField, so any JSON shape reaches this rule.

        A bare count is exactly what an operator would think to put in a field called
        "search attempts" — and `for a in attempts` then raised
        `TypeError: 'int' object is not iterable`, which DRF does not catch: an unhandled
        500 on the save button instead of a field error telling them what to write.
        Found 2026-08-22 in a pilot fixture that stored `3`.

        The right answer is not to accept the count. It is to reach the message below, which
        says what § 205.204(a)(1) actually wants: the suppliers, not how many there were.
        """
        for bad in (3, "3", {"count": 3}, None):
            with self.subTest(value=bad):
                with self.assertRaises(drf_serializers.ValidationError) as ctx:
                    self._validate(
                        type="PL",
                        seed_certification_status="non_organic_untreated",
                        seed_search_attempts=bad,
                    )
                self.assertIn("seed_search_attempts", ctx.exception.detail)

    def test_non_pl_event_not_subject_to_seed_rule(self):
        out = self._validate(
            type="HA",
            seed_certification_status="non_organic_untreated",
            seed_search_attempts=[],
        )
        self.assertEqual(out["type"], "HA")


class FrostProtectionExportTests(TestCase):
    """A6 — FP technique + trigger temperature must reach the certifier PDF, and the
    type code must render as a human label."""

    def setUp(self):
        self.user = User.objects.create_user(email="frost@test.com", password="x")
        self.company = Company.objects.create(name="Frost Farm")
        self.establishment = Establishment.objects.create(name="FE1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="FP-parcel", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Navel Orange")
        self.history = Production.objects.create(
            name="Frost Production",
            start_date=timezone.now(),
            product=self.product,
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
        ProductionEvent.objects.create(
            history=self.history,
            type="FP",
            date=timezone.now(),
            description="Frost protection night",
            extra_data={"protection_method": "wind_machine", "low_temperature": -2},
        )

    def _production_events_text(self):
        svc = AuditExportService(self.history, certification_type="organic")
        elements = svc._build_production_events()
        out = []
        for el in elements:
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    text = getattr(cell, "text", None)
                    if text:
                        out.append(text)
        return " ".join(out)

    def test_frost_method_label_and_temp_render(self):
        text = self._production_events_text()
        # Type label (previously rendered the raw code "FP").
        self.assertIn("Frost Protection", text)
        # Technique from extra_data.protection_method (previously blank Method cell).
        self.assertIn("Wind machine", text)
        # Trigger temperature from extra_data.low_temperature.
        self.assertIn("-2", text)


def _crop(name, category):
    return CropType.objects.create(
        name=name,
        slug=name.lower().replace(" ", "_"),
        category=category,
        description=name,
        typical_farm_size="1-5 ha",
        growing_season="90 days",
        harvest_season="summer",
        emissions_per_hectare=0.0,
        industry_average=0.0,
        best_practice=0.0,
        carbon_credit_potential=0.0,
        typical_cost_per_hectare=0.0,
    )


class SeedRecordsFixture(TestCase):
    """Shared fixture: one parcel, an annual production (carrots) and a perennial one (avocados)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="m7seed@test.com", password="x")
        cls.company = Company.objects.create(name="M7 Seed Farm")
        cls.establishment = Establishment.objects.create(name="M7", company=cls.company, state="CA")
        cls.parcel = Parcel.objects.create(name="Bed", establishment=cls.establishment, area=2.0)
        cls.annual_crop = _crop("Carrots", "vegetable")
        cls.perennial_crop = _crop("Hass Avocado", "tree_fruit")
        cls.annual = cls._production("Carrots", cls.annual_crop)
        cls.perennial = cls._production("Avocados", cls.perennial_crop)
        # Not annual seedling crops although their category is (or is not) an annual one: planted
        # from rhizomes or crowns, so planting stock under 7 CFR 205.2.
        cls.hops = cls._production("Hops", _crop("Hops", "other"))
        cls.asparagus = cls._production("Asparagus", _crop("Asparagus", "vegetable"))

    @classmethod
    def _production(cls, name, crop):
        return Production.objects.create(
            name=f"{name} season",
            start_date=timezone.now() - timedelta(days=100),
            product=Product.objects.create(name=name),
            parcel=cls.parcel,
            operator=cls.user,
            crop_type=crop,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _seed_text(self, production):
        out = []
        for el in AuditExportService(production, certification_type="organic")._build_seed_stock_section():
            text = getattr(el, "text", None)
            if text:
                out.append(str(text))
            for row in getattr(el, "_cellvalues", None) or []:
                out.extend(str(c.text) for c in row if getattr(c, "text", None))
        return " || ".join(out)


class AnnualSeedlingTransplantTests(SeedRecordsFixture):
    """M7-S3: 7 CFR 205.2 excludes annual seedlings from "planting stock"; 205.204(a)(3) allows a
    nonorganic one only under a 205.290(a)(2) temporary variance, so (a)(1) supplier searches are
    not its ground and not a condition of saving the record. "Annual" is a positive test on the
    crop (`crop_is_annual_seedling_crop`), because Trazo records no such fact."""

    def _tr(self, production, **extra):
        return ProductionEvent(
            history=production,
            created_by=self.user,
            date=timezone.now(),
            type="TR",
            description="Transplanted seedlings",
            area_covered=1.0,
            variety="Nantes",
            seed_certification_status="non_organic_untreated",
            seed_search_attempts=[],
            **extra,
        )

    def _validate(self, production, **extra):
        return UpdateProductionEventSerializer().validate(
            dict(
                type="TR",
                history=production,
                seed_certification_status="non_organic_untreated",
                seed_search_attempts=[],
                **extra,
            )
        )

    def test_a_nonorganic_annual_transplant_owes_no_supplier_search_on_the_api_save(self):
        self.assertEqual(self._validate(self.annual)["type"], "TR")

    def test_a_nonorganic_annual_transplant_owes_no_supplier_search_on_model_clean(self):
        self._tr(self.annual).full_clean()  # must not raise

    def test_a_rootstock_does_not_make_an_annual_crop_planting_stock(self):
        """A grafted tomato is still an annual seedling."""
        self._tr(self.annual, rootstock="Maxifort").full_clean()  # must not raise
        self.assertEqual(self._validate(self.annual, rootstock="Maxifort")["type"], "TR")

    def test_stock_and_perennial_crops_keep_the_supplier_search_on_both_paths(self):
        for production in (self.perennial, self.hops, self.asparagus):
            with self.subTest(crop=production.name):
                with self.assertRaises(drf_serializers.ValidationError) as ctx:
                    self._validate(production)
                self.assertIn("seed_search_attempts", ctx.exception.detail)
                with self.assertRaises(ValidationError) as ctx2:
                    self._tr(production).full_clean()
                self.assertIn("seed_search_attempts", ctx2.exception.message_dict)

    def test_the_classification_is_positive_and_names_what_it_excludes(self):
        from history.models.production_event import crop_is_annual_seedling_crop

        self.assertTrue(crop_is_annual_seedling_crop(self.annual_crop))
        for name, category in (
            ("Hops", "other"),
            ("Hay/Alfalfa", "forage"),
            ("Garlic", "vegetable"),
            ("Sweet Potatoes", "vegetable"),
            ("Rhubarb", "vegetable"),
            ("Mixed Vegetables", "vegetable"),
            ("Mint", "herb"),
            ("Blueberries", "berry"),
        ):
            with self.subTest(crop=name):
                crop = CropType(name=name, slug=name.lower().replace(" ", "_"), category=category)
                self.assertFalse(crop_is_annual_seedling_crop(crop))
        self.assertFalse(crop_is_annual_seedling_crop(None))

    def test_a_planting_of_seed_keeps_the_supplier_search(self):
        with self.assertRaises(drf_serializers.ValidationError):
            UpdateProductionEventSerializer().validate(
                dict(
                    type="PL",
                    history=self.annual,
                    seed_certification_status="non_organic_untreated",
                    seed_search_attempts=[],
                )
            )

    def test_the_dossier_words_the_annual_reading_as_conditional_and_cites_the_variance(self):
        self._tr(self.annual).save()
        text = self._seed_text(self.annual)
        self.assertIn("recorded as a transplant of an annual crop", text)
        self.assertIn("If it is an annual seedling", text)
        self.assertIn("205.204(a)(3)", text)
        self.assertIn("205.290(a)(2)", text)
        self.assertIn("no variance is recorded in Trazo", text)
        self.assertIn("If it is planting stock", text)
        self.assertNotIn("Ground for the exemption", text)
        self.assertNotIn("this transplant is a nonorganic annual seedling", text)

    def test_the_dossier_keeps_the_exemption_ground_for_stock_crops_and_never_calls_them_seedlings(self):
        for production in (self.perennial, self.hops):
            with self.subTest(crop=production.name):
                self._tr(production).save()
                text = self._seed_text(production)
                self.assertIn("Ground for the exemption", text)
                self.assertNotIn("annual", text)

    def test_the_readiness_card_does_not_ask_an_annual_transplant_for_the_a1_ground_or_searches(self):
        from history.services.record_completeness import completeness_gap_keys

        annual = self._tr(self.annual)
        annual.save()
        stock = self._tr(self.hops)
        stock.save()
        self.assertNotIn("seed_nonavailability_reason", completeness_gap_keys(annual))
        self.assertNotIn("seed_search_attempts", completeness_gap_keys(annual))
        self.assertIn("seed_nonavailability_reason", completeness_gap_keys(stock))
        self.assertIn("seed_search_attempts", completeness_gap_keys(stock))


class TheActivityFormAnnualSeedlingTests(SeedRecordsFixture):
    """The activity form creates with `parcels` and no `history`, so the serializer cannot see the
    season: the rule is judged where the season is resolved (`EventViewSet._refuse_stock_without_search`)."""

    def setUp(self):
        from rest_framework.test import APIClient

        from users.models import WorksIn

        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _only_open(self, season):
        # One open production per parcel, as on a farm: several make the season ambiguous.
        Production.objects.filter(parcel=self.parcel).exclude(pk=season.pk).update(finish_date=timezone.now())
        Production.objects.filter(pk=season.pk).update(finish_date=None)
        Parcel.objects.filter(pk=self.parcel.pk).update(current_history=season)

    def _post(self, season):
        self._only_open(season)
        return self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.establishment.pk}/events/",
            {
                "event_type": 1,
                "type": "TR",
                "date": timezone.now().isoformat(),
                "description": "Transplanted seedlings",
                "area_covered": "1",
                "area_unit": "ha",
                "variety": "Nantes",
                "seed_certification_status": "non_organic_untreated",
                "seed_search_attempts": [],
                "parcels": [self.parcel.pk],
            },
            format="json",
        )

    def test_an_annual_transplant_saves_from_the_form_without_a_supplier_search(self):
        response = self._post(self.annual)
        self.assertEqual(response.status_code, 201, response.content)

    def test_a_stock_transplant_is_still_refused_from_the_form_with_the_same_message(self):
        for season in (self.perennial, self.hops):
            with self.subTest(crop=season.name):
                response = self._post(season)
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("205.204(a)(1)", str(response.json()["seed_search_attempts"]))
                self.assertFalse(ProductionEvent.objects.filter(history=season, type="TR").exists())

    def test_a_stock_transplant_with_a_search_saves_from_the_form(self):
        self._only_open(self.hops)
        response = self.client.post(
            f"/api/companies/{self.company.pk}/establishments/{self.establishment.pk}/events/",
            {
                "event_type": 1,
                "type": "TR",
                "date": timezone.now().isoformat(),
                "description": "Transplanted rhizomes",
                "area_covered": "1",
                "area_unit": "ha",
                "seed_certification_status": "non_organic_untreated",
                "seed_search_attempts": [{"supplier_name": "Hop Nursery Co", "result": "none"}],
                "parcels": [self.parcel.pk],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)


class SeedBlockPerRecordTests(SeedRecordsFixture):
    """M7-S1: every seed record prints its own origin, non-GMO answer, exemption ground and
    searches, in date order, headed by date, type and variety."""

    def _planting(self, days_ago, variety, **extra):
        return ProductionEvent.objects.create(
            history=self.annual,
            created_by=self.user,
            date=timezone.now() - timedelta(days=days_ago),
            type="PL",
            area_covered=1.0,
            variety=variety,
            **extra,
        )

    def test_a_second_planting_prints_its_own_answers_in_date_order(self):
        # Created newest first, so an unordered query would not give date order either.
        self._planting(
            10,
            "Napoli",
            seeds_source="commercial",
            seed_certification_status="non_organic_untreated",
            seed_non_gmo_status="seed_label",
            seed_nonavailability_reason="quantity",
            seed_search_attempts=[{"supplier_name": "Second Seed Co", "result": "quantity"}],
        )
        self._planting(
            60,
            "Bolero",
            seeds_source="commercial",
            seed_certification_status="certified_organic",
            seed_non_gmo_status="organic_certified",
        )
        text = self._seed_text(self.annual)
        self.assertIn("Bolero", text)
        self.assertIn("Napoli", text)
        self.assertLess(text.index("Bolero"), text.index("Napoli"))
        # The non-organic second planting's exemption ground and search print, under its own head.
        second = text[text.index("Napoli") :]
        self.assertIn("Ground for the exemption", second)
        self.assertIn("Second Seed Co", second)
        # The organic first planting claims no exemption, and the block is not shared.
        first = text[text.index("Bolero") : text.index("Napoli")]
        self.assertNotIn("Ground for the exemption", first)
        self.assertNotIn("Second Seed Co", first)
        self.assertEqual(text.count("Excluded methods"), 2)

    def test_a_seed_search_record_has_no_block_and_no_not_recorded_lines(self):
        self._planting(
            60,
            "Bolero",
            seeds_source="commercial",
            seed_certification_status="certified_organic",
            seed_non_gmo_status="organic_certified",
        )
        ProductionEvent.objects.create(
            history=self.annual,
            created_by=self.user,
            date=timezone.now() - timedelta(days=70),
            type="SS",
            description="Seed search",
            area_covered=1.0,
            variety="Bolero",
            seed_search_attempts=[{"supplier_name": "Search Seed Co", "result": "sold out"}],
        )
        text = self._seed_text(self.annual)
        self.assertEqual(text.count("Excluded methods"), 1)
        self.assertNotIn("Not recorded", text)
        self.assertIn("Seed searches", text)
        self.assertIn("Search Seed Co", text)

    def test_a_supplier_only_record_of_another_type_gets_no_block(self):
        ProductionEvent.objects.create(
            history=self.annual,
            created_by=self.user,
            date=timezone.now() - timedelta(days=30),
            type="IR",
            description="Irrigation",
            area_covered=1.0,
            seed_supplier_name="Stray Supplier",
        )
        self._planting(60, "Bolero", seeds_source="commercial")
        text = self._seed_text(self.annual)
        self.assertEqual(text.count("Excluded methods"), 1)

    def test_each_block_is_headed_by_date_type_and_variety(self):
        self._planting(60, "Bolero", seeds_source="commercial")
        text = self._seed_text(self.annual)
        self.assertIn("Planting, Bolero", text)


class SeedTreatmentBasisTests(TestCase):
    """M7-S4: the seed-treatment basis cell uses the Input Log's wording (back #500)."""

    def _cell(self, **fields):
        from history.services.audit_export_service import _seed_treatment_basis_display

        return _seed_treatment_basis_display(ProductionEvent(type="PL", **fields))

    def test_omri_listed_is_the_growers_selection_with_no_catalog_entry_claimed(self):
        cell = self._cell(seed_treatment="Rhizobium inoculant", seed_treatment_allowed_basis="omri_listed")
        self.assertEqual(cell, "OMRI Listed \u2014 grower-selected, no listing on file")
        self.assertNotIn("catalog entry on file", cell)

    def test_certifier_approved_reads_as_the_growers_selection(self):
        cell = self._cell(seed_treatment="Pelleting clay", seed_treatment_allowed_basis="certifier_approved")
        self.assertEqual(cell, "Reviewed and approved by my certifier \u2014 grower-selected")

    def test_the_basis_is_the_same_string_the_input_log_prints(self):
        from history.services.audit_export_service import _organic_basis_cell

        event = ProductionEvent(type="PL", seed_treatment="Pelleting clay", seed_treatment_allowed_basis="omri_listed")
        self.assertEqual(
            self._cell(seed_treatment=event.seed_treatment, seed_treatment_allowed_basis="omri_listed"),
            _organic_basis_cell(event, raw="omri_listed"),
        )

    def test_national_list_keeps_its_own_wording(self):
        cell = self._cell(seed_treatment="Seaweed coat", seed_treatment_allowed_basis="national_list")
        self.assertEqual(cell, "Allowed under National List \u00a7 205.601")

    def test_a_no_treatment_answer_prints_no_allowed_basis(self):
        for answer in ("None", "None \u2014 raw, untreated organic seed", "N/A", "no coating", "ninguno"):
            for basis in ("organic_seed", "national_list", "omri_listed", "not_documented"):
                with self.subTest(answer=answer, basis=basis):
                    self.assertIsNone(self._cell(seed_treatment=answer, seed_treatment_allowed_basis=basis))

    def test_a_no_treatment_answer_keeps_the_untreated_basis_that_agrees_with_it(self):
        cell = self._cell(seed_treatment="None", seed_treatment_allowed_basis="untreated")
        self.assertTrue(cell.startswith("Untreated"))

    def test_a_named_treatment_with_no_basis_still_asks_for_one(self):
        cell = self._cell(seed_treatment="Rhizobium inoculant")
        self.assertIn("asks why the treatment is allowed", cell)
