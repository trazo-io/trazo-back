"""
Prefill resolution — evidence → suggestion, never an answer.

The invariants under test:
  1. Resolvers map real event evidence to valid option values with a basis string.
  2. A suggestion never contains a value the question doesn't offer.
  3. Non-organic seed with NO documented search yields silence, not a suggestion —
     suggesting "documented_search" there would put words in the operator's mouth
     that the records refute.
  4. The module GET returns suggestions but never writes them: after a GET, the
     stored module_responses are unchanged.
  5. A raising resolver is contained (module GET still succeeds).
"""

from types import SimpleNamespace

from django.test import TestCase

from rest_framework.test import APITestCase

from certifications.osp_modules import MODULES_BY_KEY
from certifications.services import osp_prefill
from certifications.services.osp_prefill import PREFILL_RESOLVERS, resolve_suggestions


class _Bundle:
    """Duck-typed EvidenceBundle: just the helpers the resolvers call."""

    def __init__(self, soils=(), chem=(), prod=(), pests=()):
        self._soils = list(soils)
        self._chem = list(chem)
        self._prod = list(prod)
        self._pests = list(pests)

    def soils(self, *types):
        return [e for e in self._soils if e.type in types]

    def chem(self, *types):
        return [e for e in self._chem if e.type in types]

    def prod(self, *types):
        return [e for e in self._prod if e.type in types]

    def pests(self, *types):
        return [e for e in self._pests if e.type in types]

    def with_field(self, events, *field_names):
        return [e for e in events if any(getattr(e, f, None) for f in field_names)]


def _ev(type_code, **fields):
    fields.setdefault("date", None)
    return SimpleNamespace(type=type_code, **fields)


def _question(module_key, question_key):
    module = MODULES_BY_KEY[module_key]
    for page in module.pages:
        for q in page.questions:
            if q.key == question_key:
                return q
    raise AssertionError(f"{module_key} has no question {question_key}")


class ResolverTests(TestCase):
    def test_cover_crop_evidence_suggests_only_declared_options(self):
        q = _question("g4_0_rotation_soil", "in_lieu_practices")
        out = PREFILL_RESOLVERS["cover_crop_evidence"](_Bundle(soils=[_ev("CC"), _ev("CC"), _ev("HD")]), q)
        self.assertEqual(out["value"], ["cover_crops", "hedgerows"])
        self.assertIn("2 cover-crop events", out["basis"])
        declared = {o.value for o in q.options}
        self.assertTrue(set(out["value"]) <= declared)

    def test_soil_amendment_evidence(self):
        q = _question("g4_0_rotation_soil", "fertility_components")
        out = PREFILL_RESOLVERS["soil_amendment_evidence"](_Bundle(soils=[_ev("CO")], chem=[_ev("FE"), _ev("FE")]), q)
        self.assertEqual(out["value"], ["compost", "blended_fertilizers"])
        self.assertIn("1 composting event", out["basis"])
        self.assertIn("2 fertilizer applications", out["basis"])

    def test_no_evidence_returns_none(self):
        q = _question("g4_0_rotation_soil", "in_lieu_practices")
        self.assertIsNone(PREFILL_RESOLVERS["cover_crop_evidence"](_Bundle(), q))

    def test_seed_status_treatment_upgrades_to_treated(self):
        q = _question("g3_0_seeds", "seeds_used")
        bundle = _Bundle(
            prod=[
                _ev("PL", seed_certification_status="certified_organic", seed_treatment=None),
                _ev("PL", seed_certification_status="certified_organic", seed_treatment="clay pelleting"),
                _ev("PL", seed_certification_status="non_organic_untreated", seed_treatment=None),
            ]
        )
        out = PREFILL_RESOLVERS["seed_status"](bundle, q)
        self.assertEqual(out["value"], ["organic_untreated", "organic_treated", "non_organic_untreated"])

    def test_seed_search_suggests_nothing_when_all_seed_is_organic(self):
        # "all_organic" is a retired answer (2026.11.25): the question shows only once non-organic seed
        # or stock is declared, so all-organic plantings suggest nothing.
        q = _question("g3_0_seeds", "ca_search_before_use")
        bundle = _Bundle(prod=[_ev("PL", seed_certification_status="certified_organic", seed_treatment=None)])
        self.assertIsNone(PREFILL_RESOLVERS["seed_search_evidence"](bundle, q))

    def test_seed_search_silent_when_records_refute(self):
        # Non-organic seed, zero documented searches: a § 205.204(a)(1) gap.
        # Suggesting "documented_search" here would fabricate compliance.
        q = _question("g3_0_seeds", "ca_search_before_use")
        bundle = _Bundle(prod=[_ev("PL", seed_certification_status="non_organic_untreated", seed_search_attempts=[])])
        self.assertIsNone(PREFILL_RESOLVERS["seed_search_evidence"](bundle, q))

    def test_seed_search_documented(self):
        q = _question("g3_0_seeds", "ca_search_before_use")
        bundle = _Bundle(
            prod=[
                _ev(
                    "PL",
                    seed_certification_status="non_organic_untreated",
                    seed_search_attempts=[{"supplier_name": "A"}, {"supplier_name": "B"}, {"supplier_name": "C"}],
                )
            ]
        )
        out = PREFILL_RESOLVERS["seed_search_evidence"](bundle, q)
        self.assertEqual(out["value"], "documented_search")
        self.assertIn("3 documented supplier contacts", out["basis"])

    def test_tillage_textarea_draft_states_only_the_log(self):
        q = _question("g4_0_rotation_soil", "tillage_practices")
        out = PREFILL_RESOLVERS["tillage_evidence"](_Bundle(soils=[_ev("TI")], prod=[_ev("CU")]), q)
        self.assertIn("2 tillage/cultivation passes", out["value"])
        self.assertNotIn("None", out["value"])


class ModuleGetSuggestionTests(APITestCase):
    """The API surface: suggestions ride the GET, are never stored, and are contained."""

    @classmethod
    def setUpTestData(cls):
        from certifications.models import OrganicSystemPlan
        from company.models import Company, Establishment
        from history.models import History, SoilManagementEvent
        from product.models import Parcel
        from users.models import User, WorksIn

        cls.owner = User.objects.create_user(email="prefill-owner@test.com", password="x")
        cls.company = Company.objects.create(name="Prefill Farm Co")
        cls.establishment = Establishment.objects.create(name="PF1", company=cls.company)
        WorksIn.objects.create(user=cls.owner, company=cls.company, role="CA")
        cls.parcel = Parcel.objects.create(name="PP1", establishment=cls.establishment, area=5.0)
        cls.history = History.objects.create(
            name="Prefill Season", parcel=cls.parcel, start_date="2026-01-01", published=False
        )
        SoilManagementEvent.objects.create(history=cls.history, type="CC", date="2026-02-01", created_by=cls.owner)
        cls.osp = OrganicSystemPlan.objects.create(establishment=cls.establishment, version_number=1, status="draft")

    def _url(self, module_key):
        return (
            f"/api/companies/{self.company.pk}/establishments/{self.establishment.pk}"
            f"/osps/{self.osp.pk}/modules/{module_key}/"
        )

    def test_get_returns_suggestions_and_stores_nothing(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(self._url("g4_0_rotation_soil"))
        self.assertEqual(resp.status_code, 200, resp.data)
        suggestions = resp.data["suggestions"]
        self.assertIn("in_lieu_practices", suggestions)
        self.assertEqual(suggestions["in_lieu_practices"]["value"], ["cover_crops"])
        self.assertIn("basis", suggestions["in_lieu_practices"])

        self.osp.refresh_from_db()
        entry = ((self.osp.module_responses or {}).get("modules") or {}).get("g4_0_rotation_soil") or {}
        self.assertEqual(entry.get("answers") or {}, {})

    def test_broken_resolver_does_not_break_module_get(self):
        def _boom(bundle, question):
            raise RuntimeError("resolver exploded")

        original = dict(PREFILL_RESOLVERS)
        PREFILL_RESOLVERS["cover_crop_evidence"] = _boom
        try:
            self.client.force_authenticate(self.owner)
            resp = self.client.get(self._url("g4_0_rotation_soil"))
            self.assertEqual(resp.status_code, 200)
            self.assertNotIn("in_lieu_practices", resp.data["suggestions"])
        finally:
            PREFILL_RESOLVERS.clear()
            PREFILL_RESOLVERS.update(original)

    def test_unregistered_source_is_a_noop(self):
        module = MODULES_BY_KEY["g4_0_rotation_soil"]
        original = dict(PREFILL_RESOLVERS)
        PREFILL_RESOLVERS.clear()
        try:
            osp_prefill._warned_missing.clear()
            out = resolve_suggestions(module, self.establishment)
            self.assertEqual(out, {})
        finally:
            PREFILL_RESOLVERS.update(original)


class PerennialResolverTests(TestCase):
    """Resolvers for the orchard ICP.

    The original five resolvers were all annual-crop shaped — seed status, seed search,
    tillage — so a mature CCOF walnut operation with a full season logged (114 events,
    39 of them scouting) produced exactly two suggestions. These cover the records a
    perennial operation actually keeps.
    """

    def _scouting(self, n, gap_days):
        from datetime import date, timedelta

        start = date(2026, 4, 6)
        return [_ev("SC", date=start + timedelta(days=i * gap_days)) for i in range(n)]

    def test_monitoring_scope_suggests_only_pest_populations(self):
        """Scouting proves pest monitoring — never disease, weed or beneficial programmes."""
        q = _question("g5_0_pest", "monitoring_scope")
        out = PREFILL_RESOLVERS["pest_monitoring_scope"](_Bundle(pests=self._scouting(12, 7)), q)
        self.assertEqual(out["value"], ["pest_populations"])
        self.assertIn("12 scouting", out["basis"])

    def test_monitoring_frequency_reports_the_median_gap_it_used(self):
        q = _question("g5_0_pest", "monitoring_frequency")
        weekly = PREFILL_RESOLVERS["pest_monitoring_frequency"](_Bundle(pests=self._scouting(10, 7)), q)
        self.assertEqual(weekly["value"], "weekly")
        self.assertIn("7 days apart", weekly["basis"])

        fortnightly = PREFILL_RESOLVERS["pest_monitoring_frequency"](_Bundle(pests=self._scouting(10, 14)), q)
        # 14 days is not weekly; the operator sees the derivation and can correct it.
        self.assertEqual(fortnightly["value"], "monthly")
        self.assertIn("14 days apart", fortnightly["basis"])

    def test_monitoring_frequency_needs_enough_records_to_have_a_cadence(self):
        q = _question("g5_0_pest", "monitoring_frequency")
        self.assertIsNone(PREFILL_RESOLVERS["pest_monitoring_frequency"](_Bundle(pests=self._scouting(2, 7)), q))

    def test_storage_never_infers_off_farm_relationships(self):
        """Trazo sees where the farm stored product, not who else stores it."""
        q = _question("g6_2_storage", "storage_locations")
        out = PREFILL_RESOLVERS["storage_location_evidence"](
            _Bundle(prod=[_ev("HA", storage_location="Home ranch drying shed")]), q
        )
        self.assertEqual(out["value"], ["on_farm_dry"])
        for off_farm in ("commercial_cold_off_farm", "certified_handler", "uncertified_facility"):
            self.assertNotIn(off_farm, out["value"])

    def test_storage_silent_without_a_named_location(self):
        q = _question("g6_2_storage", "storage_locations")
        self.assertIsNone(
            PREFILL_RESOLVERS["storage_location_evidence"](_Bundle(prod=[_ev("HA", storage_location="")]), q)
        )


class InputAndMaterialsResolverTests(TestCase):
    """G5.0 / Materials Application / G4.1 — the modules a real orchard's log should reach.

    Measured 2026-08-09 on a 114-event CCOF walnut fixture: 5 suggestions across 183
    questions. These three resolvers exist because the log plainly contained the answers —
    a logged pesticide, a logged fertilizer, a logged manure amendment — while the modules
    that ask about exactly those things suggested nothing.
    """

    def test_a_logged_application_suggests_that_inputs_are_applied(self):
        bundle = _Bundle(chem=[_ev("PE", commercial_name="Entrust SC"), _ev("FU", commercial_name="Kocide")])
        q = _question("g5_0_pest", "applies_pest_weed_disease_inputs")
        out = osp_prefill._applies_inputs_evidence(bundle, q)
        self.assertEqual(out["value"], True)
        self.assertEqual(out["count"], 2)

    def test_absence_of_an_application_suggests_NOTHING_not_false(self):
        # The asymmetry is the point. An operation that sprayed and did not log it would
        # otherwise have Trazo draft "no" on its behalf — auto-attestation under a rule
        # (§ 205.201(a)) that makes the producer the author.
        q = _question("g5_0_pest", "applies_pest_weed_disease_inputs")
        self.assertIsNone(osp_prefill._applies_inputs_evidence(_Bundle(), q))

    def test_materials_category_suggests_nothing_without_a_plan_to_compare_against(self):
        # Whether a product is on the list is a fact about the plan; a bundle with no plan cannot
        # know it, so it says nothing (the plan-backed cases are in test_listing_and_lot_claims).
        bundle = _Bundle(chem=[_ev("FE", commercial_name="Neptune's Harvest 2-4-1")])
        q = _question("materials_application", "fertilizers_listed")
        self.assertIsNone(osp_prefill._materials_category_evidence(bundle, q))

    def test_materials_category_is_silent_for_a_category_with_no_logged_use(self):
        # Silence, not "yes". No logged pesticide is not evidence the pest-material list is
        # complete — the operator may use materials Trazo never sees.
        bundle = _Bundle(chem=[_ev("FE", commercial_name="Neptune's Harvest 2-4-1")])
        q = _question("materials_application", "pest_disease_weed_listed")
        self.assertIsNone(osp_prefill._materials_category_evidence(bundle, q))

    def test_unambiguous_amendment_wording_maps_to_its_category(self):
        bundle = _Bundle(soils=[_ev("OM", amendment_type="Vermicompost (worm castings)")])
        q = _question("g4_1_compost_manure", "materials_applied")
        out = osp_prefill._manure_compost_evidence(bundle, q)
        self.assertEqual(out["value"], ["vermicompost"])

    def test_ambiguous_amendment_wording_suggests_nothing(self):
        # "Composted Poultry Manure 3-2-2" — the real fixture value. Purchased compost or a
        # processed manure product? Only the operator knows, and the two open different
        # § 205.203(c) question sets, so guessing would change which rules the plan claims.
        bundle = _Bundle(soils=[_ev("OM", amendment_type="Composted Poultry Manure 3-2-2")])
        q = _question("g4_1_compost_manure", "materials_applied")
        self.assertIsNone(osp_prefill._manure_compost_evidence(bundle, q))

    def test_a_recorded_manufacturer_settles_purchased_compost(self):
        bundle = _Bundle(
            soils=[_ev("OM", amendment_type="Composted Poultry Manure 3-2-2", amendment_manufacturer="Acme Compost Co")]
        )
        q = _question("g4_1_compost_manure", "materials_applied")
        out = osp_prefill._manure_compost_evidence(bundle, q)
        self.assertEqual(out["value"], ["purchased_compost"])

    def test_raw_manure_is_never_inferred_from_the_word_manure_alone(self):
        # The costliest wrong guess: raw manure triggers the § 205.203(c)(1) 90/120-day
        # pre-harvest intervals. "Poultry Manure Pellets" is processed, not raw.
        bundle = _Bundle(soils=[_ev("OM", amendment_type="Poultry Manure Pellets, pelleted")])
        q = _question("g4_1_compost_manure", "materials_applied")
        out = osp_prefill._manure_compost_evidence(bundle, q)
        self.assertEqual(out["value"], ["processed_manure"])

    def test_every_declared_prefill_source_has_a_resolver(self):
        from certifications.osp_modules import MODULE_REGISTRY

        declared = {
            q.prefill.source for m in MODULE_REGISTRY for p in m.pages for q in p.questions if q.prefill is not None
        }
        missing = declared - set(PREFILL_RESOLVERS)
        self.assertEqual(missing, set(), f"declared prefill sources with no resolver: {missing}")
