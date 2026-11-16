"""A crop template produces a PLAN. It must never produce a RECORD.

Replaces `test_template_event_field_passthrough.py`, which guarded the mapping layer that
turned template payloads into event rows. That layer is deleted: the bug it patched (167
concrete fields silently dropped by hand-written kwarg lists; 139 of 190 production
templates failing their insert invisibly) was a symptom of the real defect, which is that
the server was authoring records at all.

What the old flow did, end to end:

  * The operator ticked "Winter Pruning" on a crop template.
  * `calculateEventDate("December - February")` in the browser returned **December 15** of
    the season's start year — a day nobody chose, routinely in the past.
  * `_create_template_events` inserted a real `ProductionEvent` on that date, with
    `created_by` set to the grower.
  * `operation_audit_export_service` printed it into the certifier packet, indistinguishable
    from a practice the grower had actually observed. No provenance column existed.

That is the 2026-08-02 Smart Setup incident's defect class (a backdated glyphosate
application in a certified-organic farm's own audit trail). The content fixes —
organic-first ordering, `ORGANIC_OVERRIDES`, `isTemplateEventProhibited` — closed the
instance and left the class open.

7 CFR 205.201(a) makes the PRODUCER the author of the plan. 205.103(b)(2) requires records
that "fully disclose all activities and transactions ... in sufficient detail as to be
readily understood and audited." A row nobody performed fails both, at the trace-back.

These tests pin the class, not the instance.
"""

from django.urls import reverse

from rest_framework.test import APITestCase

from carbon.models import CropType, EventTemplate, ProductionTemplate
from company.models import Company, Establishment
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    Production,
    ProductionEvent,
    ProductionPlanItem,
    SoilManagementEvent,
    WeatherEvent,
)
from history.services import season_plan_service
from product.models import Parcel
from subscriptions.models import Plan, Subscription
from users.models import User, WorksIn

EVENT_MODELS = (
    WeatherEvent,
    ChemicalEvent,
    ProductionEvent,
    GeneralEvent,
    EquipmentEvent,
    SoilManagementEvent,
    PestManagementEvent,
    BusinessEvent,
)


class SeasonPlanFixture(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="grower@trazo.test", password="testpass123", first_name="Ada", last_name="Grower"
        )
        # `max_productions_per_year: -1` is what `create_plans` seeds on every live tier;
        # without it HasProductionCreationPermission 403s before the view is reached.
        self.plan = Plan.objects.create(
            name="Compliance",
            price=249,
            features={"max_productions_per_year": -1},
        )
        self.company = Company.objects.create(name="Blue Oak Orchards")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        Subscription.objects.create(company=self.company, plan=self.plan, status="active")

        self.establishment = Establishment.objects.create(company=self.company, name="Home Ranch")
        self.parcel = Parcel.objects.create(establishment=self.establishment, name="Block A", area=12.0)

        self.crop_type = self._crop_type("Walnuts", "walnuts")
        self.template = ProductionTemplate.objects.create(
            crop_type=self.crop_type,
            name="Walnut Organic Production",
            slug="walnut_organic",
            farming_approach="organic",
            description="Organic walnut programme",
        )

        self.pruning = self._event_template(
            name="Annual Structural Pruning",
            timing="December - February",
            backend_event_type=1,
            fields={"type": "PR", "area_covered": 12.0},
            order_sequence=1,
        )
        self.glyphosate = self._event_template(
            name="Herbicide Application",
            timing="March - April",
            backend_event_type=2,
            fields={
                "type": "HE",
                "commercial_name": "Roundup PowerMax 3 (glyphosate)",
                "organic_approved": "not_organic",
                "chemical_subtype": "synthetic_herbicide",
            },
            order_sequence=2,
        )
        self.client.force_authenticate(user=self.user)

    @staticmethod
    def _crop_type(name, slug):
        """CropType carries a wall of non-null economic columns; none matter here."""
        return CropType.objects.create(
            name=name,
            slug=slug,
            category="tree_nut",
            description="",
            typical_farm_size="",
            growing_season="",
            harvest_season="",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
        )

    def _event_template(self, *, name, timing, backend_event_type, fields, order_sequence):
        return EventTemplate.objects.create(
            production_template=self.template,
            name=name,
            event_type="pruning",
            description=f"{name} description",
            timing=timing,
            frequency="annual",
            typical_duration="1 day",
            order_sequence=order_sequence,
            carbon_impact=0.0,
            carbon_category="low",
            cost_estimate=0.0,
            backend_event_type=backend_event_type,
            backend_event_fields=fields,
        )

    _DEFAULT = object()

    def _start_production(self, *, method="organic", selected=_DEFAULT, name="2026 Walnuts"):
        if selected is self._DEFAULT:
            selected = [self.pruning]
        return self.client.post(
            reverse("productions-start-production"),
            {
                "name": name,
                "parcel_id": self.parcel.id,
                "crop_type": self.crop_type.id,
                "start_date": "2026-03-01T00:00:00Z",
                "production_method": method,
                "template_id": self.template.id,
                "plan_item_ids": [t.id for t in selected],
            },
            format="json",
        )


class StartProductionWritesNoRecords(SeasonPlanFixture):
    def test_ticking_a_suggestion_creates_a_plan_item_and_zero_events(self):
        response = self._start_production()
        self.assertEqual(response.status_code, 201, response.data)

        history = Production.objects.get(id=response.data["id"])
        self.assertEqual(ProductionPlanItem.objects.filter(history=history).count(), 1)

        # The load-bearing assertion. Named per model so a failure says WHICH table gained
        # a row the grower never wrote.
        for model in EVENT_MODELS:
            self.assertEqual(
                model.objects.filter(history=history).count(),
                0,
                f"{model.__name__} rows were created from a template. A suggestion is not a record.",
            )

    def test_untickedsuggestions_do_not_enter_the_plan(self):
        response = self._start_production(selected=[])
        self.assertEqual(response.status_code, 201, response.data)
        history = Production.objects.get(id=response.data["id"])
        self.assertEqual(ProductionPlanItem.objects.filter(history=history).count(), 0)

    def test_a_plan_item_carries_a_window_never_a_day(self):
        self._start_production()
        item = ProductionPlanItem.objects.get(name="Annual Structural Pruning")
        self.assertEqual(item.planned_window, "December - February")
        self.assertEqual(item.planned_month, 12)

    def test_the_model_has_no_field_that_could_hold_an_invented_day(self):
        """Structural tripwire. `calculateEventDate` returned the 15th of the month; the only
        durable defence is that there is nowhere on a plan item to put a day at all.

        The three date columns that ARE allowed are audit metadata about the ROW, not claims
        about the practice: when the suggestion was created, when it was last touched, and
        when the operator logged a real record against it.
        """
        allowed = {"created_at", "updated_at", "fulfilled_at"}
        dated = {
            field.name
            for field in ProductionPlanItem._meta.get_fields()
            if field.get_internal_type() in {"DateField", "DateTimeField"}
        }
        self.assertEqual(
            dated - allowed,
            set(),
            "A date field was added to ProductionPlanItem. A plan has a window, not a day.",
        )

    def test_a_prohibited_input_is_never_suggested_to_an_organic_operation(self):
        """Server-side. The browser check is a UI affordance; this is the rule."""
        response = self._start_production(selected=[self.pruning, self.glyphosate])
        self.assertEqual(response.status_code, 201, response.data)
        history = Production.objects.get(id=response.data["id"])
        names = set(ProductionPlanItem.objects.filter(history=history).values_list("name", flat=True))
        self.assertEqual(names, {"Annual Structural Pruning"})

    def test_a_conventional_operation_still_gets_the_conventional_programme(self):
        response = self._start_production(method="conventional", selected=[self.pruning, self.glyphosate])
        history = Production.objects.get(id=response.data["id"])
        self.assertEqual(ProductionPlanItem.objects.filter(history=history).count(), 2)

    def test_a_payload_cannot_pull_suggestions_from_another_crops_catalogue(self):
        other_crop = self._crop_type("Almonds", "almonds")
        other_template = ProductionTemplate.objects.create(
            crop_type=other_crop,
            name="Almond Conventional",
            slug="almond_conventional",
            farming_approach="conventional",
            description="",
        )
        foreign = EventTemplate.objects.create(
            production_template=other_template,
            name="Almond Hull Split Spray",
            event_type="pest_control",
            description="",
            timing="July",
            frequency="annual",
            typical_duration="1 day",
            order_sequence=1,
            carbon_impact=0.0,
            carbon_category="low",
            cost_estimate=0.0,
            backend_event_type=2,
            backend_event_fields={"type": "PE"},
        )
        response = self._start_production(selected=[self.pruning, foreign])
        history = Production.objects.get(id=response.data["id"])
        names = set(ProductionPlanItem.objects.filter(history=history).values_list("name", flat=True))
        self.assertNotIn("Almond Hull Split Spray", names)


class APlanItemCarriesNoValues(SeasonPlanFixture):
    """A plan item names a practice and a window. It carries no field VALUES, ever.

    A `prefill` JSONField was written first and removed before it shipped: the wizard's
    `cleanEventData` is a passthrough with no allowlist, so anything merged into the form
    reaches the saved record whether the form renders it or not. The catalogue's field sets
    are full of measurements and product identities — `build_soil_event_fields` alone emits
    `soil_ph: 6.5`, `organic_matter_percentage: 3.0`, `fuel_consumed`, `equipment_hours` and
    `amendment_type: "Crimson Clover + White Mustard seed mix"`. Writing those unseen is a
    fabricated measurement and a fabricated input identity — the class this whole model
    exists to close, plus a breach of the mutation-payload rule and of the
    never-auto-populate-a-product rule from the OMRI listing leak.
    """

    def test_the_model_has_no_column_that_could_carry_catalogue_values(self):
        columns = {field.name for field in ProductionPlanItem._meta.get_fields()}
        self.assertNotIn("prefill", columns)
        self.assertEqual(
            [f.name for f in ProductionPlanItem._meta.get_fields() if f.get_internal_type() == "JSONField"],
            [],
            "A JSON blob on a plan item is where catalogue values come back. Keep it off.",
        )

    def test_the_payload_carries_no_values_either(self):
        self._start_production()
        history = Production.objects.get(name="2026 Walnuts")
        response = self.client.get(reverse("productions-season-plan", args=[history.id]))
        self.assertEqual(response.status_code, 200)

        item = response.data["items"][0]
        # What a plan item may say: which practice, roughly when, and whether it is done.
        self.assertEqual(
            set(item),
            {
                "id",
                "name",
                "description",
                "event_type",
                "event_subtype",
                "planned_window",
                "planned_month",
                "order_sequence",
                "status",
                "status_display",
                "fulfilled_by_event_type",
                "fulfilled_by_id",
                "fulfilled_at",
                "skipped_reason",
            },
        )

    def test_the_service_exposes_no_prefill_builder(self):
        """Belt and braces: the helper that built the merged field set is gone, so nothing can
        quietly start calling it again."""
        self.assertFalse(hasattr(season_plan_service, "build_prefill"))


class WindowParsing(SeasonPlanFixture):
    def test_a_span_resolves_to_its_first_month_by_position(self):
        self.assertEqual(season_plan_service.parse_window_month("December - February"), 12)
        self.assertEqual(season_plan_service.parse_window_month("March-April"), 3)
        self.assertEqual(season_plan_service.parse_window_month("Late September"), 9)

    def test_an_unparseable_window_stays_empty_rather_than_guessing(self):
        self.assertIsNone(season_plan_service.parse_window_month("As needed"))
        self.assertIsNone(season_plan_service.parse_window_month(""))
        self.assertIsNone(season_plan_service.parse_window_month(None))


class SeasonPlanEndpoints(SeasonPlanFixture):
    def setUp(self):
        super().setUp()
        response = self._start_production()
        self.history = Production.objects.get(id=response.data["id"])
        self.item = ProductionPlanItem.objects.get(history=self.history)

    def _plan_url(self):
        return reverse("productions-season-plan", args=[self.history.id])

    def _item_url(self, item_id=None):
        return reverse("productions-season-plan-item", args=[self.history.id, item_id or self.item.id])

    def test_the_plan_reports_completeness_not_a_score(self):
        response = self.client.get(self._plan_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["completeness"], {"total": 1, "logged": 0, "pending": 1, "skipped": 0})
        self.assertEqual(response.data["items"][0]["planned_window"], "December - February")

    def test_the_plan_carries_the_numeric_history_id_even_when_fetched_by_uuid(self):
        """ "Log this" posts `history` explicitly. Without it the event endpoint falls back to
        `parcel.current_history`, so a plan item on any other production would write its record
        to the wrong season AND leave the checklist item open."""
        response = self.client.get(reverse("productions-season-plan", args=[self.history.public_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["history_id"], self.history.id)

    def test_logging_a_plan_item_lands_on_its_own_production_not_the_parcels_current_one(self):
        """The failure this guards: a second production becomes `parcel.current_history`, and a
        record logged from the FIRST production's plan silently lands on the second."""
        later = self._start_production(name="2026 Walnuts (second block)")
        self.parcel.refresh_from_db()
        self.assertEqual(self.parcel.current_history_id, later.data["id"])

        created = self.client.post(
            reverse("events-list"),
            {
                "event_type": 1,
                "type": "PR",
                "name": "Winter pruning",
                "description": "Pruned block A",
                "date": "2026-01-08T08:00",
                "area_covered": "12",
                # What the wizard now sends: the plan's OWN history, not the parcel's current.
                "history": self.history.id,
                "parcels": [self.parcel.id],
                "plan_item_id": self.item.id,
            },
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.data)

        event = ProductionEvent.objects.get(id=created.data["id"])
        self.assertEqual(event.history_id, self.history.id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.LOGGED)

    def test_the_plan_is_producer_only(self):
        """A plan is a list of things that have NOT happened. It is not evidence, so it may
        not reach anyone reading Trazo for evidence."""
        outsider = User.objects.create_user(email="nosy@elsewhere.test", password="testpass123")
        other_company = Company.objects.create(name="Elsewhere Farms")
        WorksIn.objects.create(user=outsider, company=other_company, role=WorksIn.COMPANY_ADMIN)
        self.client.force_authenticate(user=outsider)
        # 404 since 2026-09-28: the season is no longer even FOUND outside its company (the
        # tenancy floor on HistoryViewSet), which also stops confirming that it exists.
        self.assertIn(self.client.get(self._plan_url()).status_code, (403, 404))

        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self._plan_url()).status_code, 401)

    def test_an_operator_can_set_a_practice_aside(self):
        response = self.client.patch(
            self._item_url(),
            {"status": "skipped", "skipped_reason": "No frost risk this year"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.SKIPPED)
        self.assertEqual(self.item.skipped_reason, "No frost risk this year")

    def test_a_client_cannot_declare_a_practice_logged(self):
        """The whole point. An item may only claim to be done by pointing at a record that
        was actually written — see EventViewSet.perform_create."""
        response = self.client.patch(self._item_url(), {"status": "logged"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.PENDING)

    def test_logging_a_record_closes_the_plan_item_and_points_at_it(self):
        response = self.client.post(
            reverse("events-list"),
            {
                "event_type": 1,
                "type": "PR",
                "name": "Winter pruning",
                "description": "Pruned block A",
                "date": "2026-01-08T08:00",
                "area_covered": "12",
                "history": self.history.id,
                "parcels": [self.parcel.id],
                "plan_item_id": self.item.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.LOGGED)
        self.assertEqual(self.item.fulfilled_by_event_type, 1)
        self.assertEqual(self.item.fulfilled_by_id, response.data["id"])
        # The identity is written with the pair (schema remodel plan: FK to history.Activity).
        from history.models import ProductionEvent as _PE

        self.assertEqual(self.item.fulfilled_by_activity_id, _PE.objects.get(pk=response.data["id"]).activity_id)
        self.assertIsNotNone(self.item.fulfilled_at)

        # The record carries the operator's own date, not one derived from the window.
        event = ProductionEvent.objects.get(id=response.data["id"])
        self.assertEqual(event.date.date().isoformat(), "2026-01-08")
        self.assertEqual(event.created_by, self.user)

    def test_a_finished_season_closes_its_plan_too(self):
        """The card hides these controls on a finished production. A gate only the client
        honours is not a gate."""
        Production.objects.filter(id=self.history.id).update(finish_date="2026-11-01T00:00:00Z")
        response = self.client.patch(self._item_url(), {"status": "skipped"}, format="json")
        self.assertEqual(response.status_code, 423, response.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.PENDING)

    def test_a_finished_season_still_shows_its_plan(self):
        Production.objects.filter(id=self.history.id).update(finish_date="2026-11-01T00:00:00Z")
        self.assertEqual(self.client.get(self._plan_url()).status_code, 200)

    def test_a_closed_item_cannot_be_reopened_around_its_record(self):
        ProductionPlanItem.objects.filter(id=self.item.id).update(status=ProductionPlanItem.LOGGED)
        response = self.client.patch(self._item_url(), {"status": "pending"}, format="json")
        self.assertEqual(response.status_code, 409)

    def test_a_plan_item_id_from_another_production_is_ignored_not_honoured(self):
        other = self._start_production(name="2026 Walnuts B")
        other_item = ProductionPlanItem.objects.get(history_id=other.data["id"])
        response = self.client.post(
            reverse("events-list"),
            {
                "event_type": 1,
                "type": "PR",
                "name": "Winter pruning",
                "description": "Pruned block A",
                "date": "2026-01-08T08:00",
                "area_covered": "12",
                "history": self.history.id,
                "parcels": [self.parcel.id],
                "plan_item_id": other_item.id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        other_item.refresh_from_db()
        self.assertEqual(other_item.status, ProductionPlanItem.PENDING)


class ProhibitedInputVocabularyIsOneList(SeasonPlanFixture):
    """The organic-methods list exists in both repos and only one of them decides.

    Same shape as ProductionMethodVocabularyTests: the browser copy is an affordance, the
    server copy is the rule, and they drifted once already — the frontend list omitted
    `biodynamic`, so a Demeter operation (which requires organic certification underneath
    it, § 205.105 in full) was offered the conventional programme's synthetics.
    """

    APP_FILE = "views/Dashboard/Dashboard/Production/QuickStartProduction.tsx"

    def test_both_repos_name_the_same_methods(self):
        import re
        from pathlib import Path

        app_src = Path(__file__).resolve().parents[3] / "trazo-app" / "src"
        if not app_src.is_dir():
            # Do NOT silently pass; a guard that no-ops in half the checkouts is decorative.
            self.fail(f"trazo-app/src not found at {app_src}. This guard needs both repos.")

        source = (app_src / self.APP_FILE).read_text(encoding="utf8")
        match = re.search(r"const ORGANIC_PRODUCTION_METHODS = \[([^\]]*)\]", source)
        self.assertIsNotNone(match, "ORGANIC_PRODUCTION_METHODS not found — did the constant move?")
        app_methods = set(re.findall(r"'([^']+)'", match.group(1)))

        self.assertEqual(
            app_methods,
            set(season_plan_service.ORGANIC_PRODUCTION_METHODS),
            "The browser and the server disagree about which operations are organic. "
            "The server copy decides; bring the TSX to it.",
        )

    def test_every_listed_method_is_a_real_model_choice(self):
        valid = {choice for choice, _ in Production.PRODUCTION_METHOD_CHOICES}
        self.assertTrue(set(season_plan_service.ORGANIC_PRODUCTION_METHODS) <= valid)


class PlanBuildEdgeCases(SeasonPlanFixture):
    """The bugs a second read found. Each one silently produced a wrong plan, not an error."""

    def test_a_missing_template_id_builds_no_plan_rather_than_a_free_for_all(self):
        """FAIL CLOSED. The scope filter used to be applied only when `template_id` parsed, so
        a payload that omitted it pulled arbitrary EventTemplate rows out of the whole
        catalogue by id — every crop's programme, addressable from any production."""
        response = self.client.post(
            reverse("productions-start-production"),
            {
                "name": "2026 Walnuts",
                "parcel_id": self.parcel.id,
                "crop_type": self.crop_type.id,
                "start_date": "2026-03-01T00:00:00Z",
                "production_method": "organic",
                # template_id deliberately absent
                "plan_item_ids": [self.pruning.id],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(ProductionPlanItem.objects.filter(history_id=response.data["id"]).count(), 0)

    def test_a_garbage_template_id_builds_no_plan_either(self):
        response = self._start_production()
        garbage = self.client.post(
            reverse("productions-start-production"),
            {
                "name": "2026 Walnuts C",
                "parcel_id": self.parcel.id,
                "crop_type": self.crop_type.id,
                "start_date": "2026-03-01T00:00:00Z",
                "production_method": "organic",
                "template_id": "not-a-number",
                "plan_item_ids": [self.pruning.id],
            },
            format="json",
        )
        self.assertEqual(garbage.status_code, 201, garbage.data)
        self.assertEqual(ProductionPlanItem.objects.filter(history_id=garbage.data["id"]).count(), 0)
        # The well-formed request in the same fixture still works, so this is scoping and not
        # a blanket refusal.
        self.assertEqual(ProductionPlanItem.objects.filter(history_id=response.data["id"]).count(), 1)

    def test_the_english_word_may_is_not_read_as_the_month(self):
        """`find()` over a lowercased string read the "may" in "may extend into November" as
        the month of May — a window seven months off, and plausible enough that nothing
        downstream would ever flag it. The capital is what separates the two."""
        self.assertEqual(season_plan_service.parse_window_month("Post-harvest; may extend into November"), 11)
        self.assertIsNone(season_plan_service.parse_window_month("Maybe later"))
        self.assertIsNone(season_plan_service.parse_window_month("Timing may vary"))
        # The month itself still reads, and still wins by position.
        self.assertEqual(season_plan_service.parse_window_month("May - August"), 5)

    def test_an_uncapitalised_month_yields_no_month_rather_than_a_guess(self):
        """Deliberate: `planned_window` still shows the operator the text. A missing
        `planned_month` costs ordering; a wrong one would state a fact about the season."""
        self.assertIsNone(season_plan_service.parse_window_month("december - february"))

    def test_order_sequence_zero_survives(self):
        """`template.order_sequence or index` treated a legitimate first position as missing."""
        first = self._event_template(
            name="Dormant Oil",
            timing="January",
            backend_event_type=2,
            fields={"type": "PE", "organic_approved": "organic"},
            order_sequence=0,
        )
        self._start_production(selected=[first])
        self.assertEqual(ProductionPlanItem.objects.get(name="Dormant Oil").order_sequence, 0)


class PlanFollowsTheRecords(SeasonPlanEndpoints):
    def _log_pruning(self, plan_item_id):
        return self.client.post(
            reverse("events-list"),
            {
                "event_type": 1,
                "type": "PR",
                "name": "Winter pruning",
                "description": "Pruned block A",
                "date": "2026-01-08T08:00",
                "area_covered": "12",
                "history": self.history.id,
                "parcels": [self.parcel.id],
                "plan_item_id": plan_item_id,
            },
            format="json",
        )

    def test_deleting_the_record_puts_the_practice_back_on_the_plan(self):
        """An item reading "logged" while the record it names is gone is the
        assertion-with-nothing-behind-it this whole model exists to prevent. The link is a
        loose (event_type, id) pair, so nothing in the database maintains it — the view has to."""
        created = self._log_pruning(self.item.id)
        self.assertEqual(created.status_code, 201, created.data)
        event_id = created.data["id"]
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.LOGGED)

        deleted = self.client.delete(f"{reverse('events-detail', args=[event_id])}?event_type=1")
        self.assertIn(deleted.status_code, (200, 204), getattr(deleted, "data", deleted.status_code))

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.PENDING)
        self.assertIsNone(self.item.fulfilled_by_id)
        self.assertIsNone(self.item.fulfilled_by_event_type)
        self.assertIsNone(self.item.fulfilled_by_activity_id)
        self.assertIsNone(self.item.fulfilled_at)

    def test_logging_a_practice_that_was_set_aside_still_closes_it(self):
        """A record is stronger evidence than an earlier "not this season" decision."""
        ProductionPlanItem.objects.filter(id=self.item.id).update(
            status=ProductionPlanItem.SKIPPED, skipped_reason="No frost risk"
        )
        created = self._log_pruning(self.item.id)
        self.assertEqual(created.status_code, 201, created.data)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ProductionPlanItem.LOGGED)
        self.assertEqual(self.item.skipped_reason, "")

    def test_a_second_record_does_not_repoint_an_already_closed_item(self):
        first = self._log_pruning(self.item.id)
        self.item.refresh_from_db()
        self.assertEqual(self.item.fulfilled_by_id, first.data["id"])

        second = self._log_pruning(self.item.id)
        self.assertEqual(second.status_code, 201, second.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.fulfilled_by_id, first.data["id"])
