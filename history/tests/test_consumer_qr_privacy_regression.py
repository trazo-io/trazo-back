"""
Phase 3 privacy regression tests for the public consumer QR payload.

Two consent-gated surfaces:
1. Worker names — performed_by is masked to "Farm team (A.T.)" unless the
   establishment opted in (Establishment.show_full_performer_names). Full
   name + farm geolocation on a public page is a CCPA exposure and a doxing
   vector.
2. Parcel geodata — polygon/map_metadata gated by
   Parcel.location_disclosure_level (exact | approximate | hidden). A public
   field polygon is a theft/scouting exposure.
"""

import json
import re

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, PestManagementEvent, ProductionEvent, SoilManagementEvent
from history.serializers import PublicHistorySerializer
from history.services.privacy import public_parcel_geo
from product.models import Parcel, Product
from users.models import User, WorksIn


def _flatten_reportlab_text(elements):
    """Extract plain text from a list of reportlab flowables (Paragraphs + Tables) so tests can
    assert on rendered audit-PDF content without a PDF parser."""
    out = []
    for el in elements:
        if hasattr(el, "getPlainText"):
            out.append(el.getPlainText())
        for row in getattr(el, "_cellvalues", None) or []:
            for cell in row:
                if hasattr(cell, "getPlainText"):
                    out.append(cell.getPlainText())
                elif isinstance(cell, str):
                    out.append(cell)
    return " ".join(out)


class _Base(TestCase):
    def setUp(self):
        # The test settings use a shared (Redis) cache, so DRF per-IP throttle counters accumulate
        # across tests and across runs — making these public-endpoint tests order/run-count
        # dependent (429 Throttled). Reset the cache before each test for a clean throttle budget.
        from django.core.cache import cache

        cache.clear()
        self.user = User.objects.create_user(email="priv@test.com", password="x")
        self.company = Company.objects.create(name="Privacy Farm")
        # `state` is required downstream, not here: saving an event fires the carbon signal,
        # which builds a USDAComplianceRecord whose `state` column is NOT NULL with no
        # default. A stateless establishment raised IntegrityError inside the test's atomic
        # block, and every later query in the same test then failed with
        # TransactionManagementError — which is why this suite reported cascading errors and
        # 500s that had nothing to do with the privacy assertions being made.
        self.establishment = Establishment.objects.create(name="P1", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(
            name="PP1",
            establishment=self.establishment,
            area=5.0,
            polygon=[[34.3414, -119.1795], [34.3420, -119.1790], [34.3418, -119.1801]],
            map_metadata={"center": {"lat": 34.3414, "lng": -119.1795}, "zoom": 16},
        )
        self.product = Product.objects.create(name="Citrus")
        self.history = History.objects.create(
            name="Privacy Test Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def _payload(self):
        return PublicHistorySerializer(self.history).data


class PerformerMaskingTests(_Base):
    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(
            history=self.history,
            type="PL",
            performed_by="Ana Torres",
            date=timezone.now(),
        )

    def _planting_event(self):
        events = self._payload().get("events") or []
        planting = [e for e in events if e.get("type") == "PL"]
        self.assertEqual(len(planting), 1)
        return planting[0]

    def test_full_name_masked_by_default(self):
        ev = self._planting_event()
        self.assertEqual(ev.get("performed_by"), "Farm team (A.T.)")

    def test_full_name_absent_from_entire_payload(self):
        blob = json.dumps(self._payload(), default=str)
        self.assertNotIn("Ana Torres", blob, "worker full name leaked into public payload")

    def test_opt_in_shows_full_name(self):
        self.establishment.show_full_performer_names = True
        self.establishment.save()
        ev = self._planting_event()
        self.assertEqual(ev.get("performed_by"), "Ana Torres")

    def test_empty_performer_stays_empty(self):
        ProductionEvent.objects.all().update(performed_by=None)
        ev = self._planting_event()
        self.assertIsNone(ev.get("performed_by"))

    def test_single_word_name_masks_to_one_initial(self):
        ProductionEvent.objects.all().update(performed_by="Roberto")
        ev = self._planting_event()
        self.assertEqual(ev.get("performed_by"), "Farm team (R.)")


class ParcelDisclosureTests(_Base):
    def test_exact_exposes_polygon(self):
        self.parcel.location_disclosure_level = "exact"
        self.parcel.save()
        parcel = self._payload().get("parcel") or {}
        self.assertTrue(parcel.get("polygon"))
        self.assertEqual(parcel.get("map_metadata", {}).get("zoom"), 16)

    def test_approximate_strips_polygon_and_rounds_center(self):
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.save()
        parcel = self._payload().get("parcel") or {}
        self.assertIsNone(parcel.get("polygon"), "polygon must not leak at approximate level")
        meta = parcel.get("map_metadata") or {}
        self.assertEqual(meta.get("center"), {"lat": 34.34, "lng": -119.18})
        self.assertTrue(meta.get("approximate"))
        self.assertLessEqual(meta.get("zoom"), 13, "zoom must be capped so the field can't be located")

    def test_hidden_strips_all_geo(self):
        self.parcel.location_disclosure_level = "hidden"
        self.parcel.save()
        parcel = self._payload().get("parcel") or {}
        self.assertIsNone(parcel.get("polygon"))
        self.assertIsNone(parcel.get("map_metadata"))

    def test_exact_coordinates_absent_from_blob_when_approximate(self):
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.save()
        blob = json.dumps(self._payload(), default=str)
        self.assertNotIn("34.3414", blob, "exact latitude leaked at approximate disclosure level")

    def test_helper_handles_missing_metadata(self):
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.map_metadata = None
        self.parcel.save()
        geo = public_parcel_geo(self.parcel)
        self.assertIsNone(geo["polygon"])
        self.assertIsNone(geo["map_metadata"])

    def test_helper_survives_malformed_metadata(self):
        # map_metadata is free-form JSON — garbage must degrade to "no map"
        # on the public endpoint, never to a 500.
        self.parcel.location_disclosure_level = "approximate"
        self.parcel.map_metadata = {"center": {"lat": "garbage", "lng": -119.0}, "zoom": "huge"}
        self.parcel.save()
        geo = public_parcel_geo(self.parcel)
        self.assertIsNone(geo["map_metadata"])


class FarmerLocationPIITests(_Base):
    """P1 (2026-06): the public transparency endpoint must not leak the farm's
    street address, exact GPS coordinates, or zip. The consumer UI shows only
    city/state and the map uses the parcel's location_disclosure_level-gated
    geo; exposing establishment/company address + coords here bypassed that
    privacy control and handed any anonymous API caller the farm's exact spot.
    """

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        self.establishment.address = "2847 Orchard Valley Road"
        self.establishment.city = "Fallbrook"
        self.establishment.state = "California"
        self.establishment.latitude = 33.3764
        self.establishment.longitude = -117.251
        self.establishment.zip_code = "92028"
        self.establishment.save()
        self.company.address = "2847 Orchard Valley Road"
        self.company.save()

    def _get(self):
        url = reverse("production-transparency-detail", kwargs={"production_public_id": str(self.history.public_id)})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp

    def test_location_pii_stripped(self):
        farmer = self._get().json()["farmer"]
        self.assertIsNone(farmer.get("address"))
        self.assertIsNone(farmer.get("latitude"))
        self.assertIsNone(farmer.get("longitude"))
        self.assertIsNone(farmer.get("zip_code"))
        self.assertIsNone((farmer.get("company") or {}).get("address"))

    def test_city_state_retained(self):
        # Coarse location is intended consumer transparency — must NOT be over-stripped.
        farmer = self._get().json()["farmer"]
        self.assertEqual(farmer.get("city"), "Fallbrook")
        self.assertEqual(farmer.get("state"), "California")
        self.assertEqual(farmer.get("location"), "Fallbrook, California")

    def test_exact_address_and_coords_absent_from_blob(self):
        blob = self._get().content.decode()
        self.assertNotIn("2847 Orchard Valley Road", blob, "street address leaked")
        self.assertNotIn("33.3764", blob, "exact latitude leaked")
        self.assertNotIn("-117.251", blob, "exact longitude leaked")
        self.assertNotIn("92028", blob, "zip leaked")


class TransparencyScoreGatingTests(_Base):
    """Claim-safety (2026-06): the self-assigned transparency SCORE is a
    farmer-dashboard engagement KPI, NOT a consumer claim. A self-created
    "% documented / data-quality grade" served to anonymous shoppers is the
    self-declared sustainability-label class banned by EU ECGT 2024/825 and an
    FTC 16 CFR 260.6 risk — and is scrapable from JSON even when the UI hides it.

    The graded headline must be withheld from the public payload while the
    authenticated OWNER (the producer dashboard) still receives it, and the
    EVIDENCE the score is built from must stay (event counts, category breakdown).
    """

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        # A CLASSIFIED input, so the organic-input evidence assertions below actually run.
        # `omri_listed` here is the grower's dropdown pick with no OMRI catalog row behind it
        # — precisely the case P4-F6 is about, and the one a fixture without inputs would let
        # skip silently. A skipped test is not a passing test.
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=timezone.now(),
            commercial_name="Grower-Picked Copper",
            organic_approved="omri_listed",
        )
        # `_build_organic_summary` returns None for a non-organic operation, which made the
        # assertion above skip rather than run.
        self.history.production_method = "organic"
        self.history.save(update_fields=["production_method"])

    def _url(self):
        return reverse(
            "production-transparency-detail",
            kwargs={"production_public_id": str(self.history.public_id)},
        )

    def _anon_payload(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    def test_graded_score_gated_for_anonymous(self):
        payload = self._anon_payload()
        self.assertNotIn(
            "transparency_score",
            payload.get("quick_view") or {},
            "self-graded transparency score served to an anonymous consumer",
        )
        transparency_block = payload.get("transparency") or {}
        for graded_key in (
            "completeness_percentage",
            "documentation_score",
            "data_quality_grade",
            "verification_status",
        ):
            self.assertNotIn(graded_key, transparency_block, f"graded field '{graded_key}' leaked to anonymous")
        details = (payload.get("standard_view") or {}).get("transparency_details") or {}
        self.assertNotIn("completeness_score", details, "rolled-up grade leaked to anonymous")
        # Per-category graded "% complete" + status verdict stripped.
        for name, category in (details.get("category_breakdown") or {}).items():
            self.assertNotIn("completeness_percentage", category, f"category '{name}' grade leaked to anonymous")
            self.assertNotIn("status", category, f"category '{name}' status verdict leaked to anonymous")
        # The "30s deep insights" block (raw current_score + benchmark grade) is
        # farmer-only and must not reach an anonymous caller at all.
        self.assertNotIn("detailed_view", payload, "farmer-only detailed_view (raw score/grade) leaked to anonymous")

    def test_no_graded_number_anywhere_in_anonymous_blob(self):
        # Belt-and-suspenders: no graded score key may survive ANYWHERE in the
        # tree, even nested — the score is scrapable from raw JSON if it does.
        import json as _json

        blob = self._anon_payload()

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("current_score", "transparency_percentage", "benchmark_level", "documentation_score"):
                        raise AssertionError(
                            f"graded key '{k}' survived in anonymous payload: {_json.dumps(node)[:200]}"
                        )
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(blob)

    def test_evidence_kept_for_anonymous(self):
        # The factual evidence the score is built from is intended consumer
        # transparency — it must NOT be over-stripped along with the grade.
        details = (self._anon_payload().get("standard_view") or {}).get("transparency_details") or {}
        self.assertIn("actual_events", details, "event count (evidence) over-stripped")
        self.assertIn("category_breakdown", details, "category breakdown (evidence) over-stripped")
        # Factual per-category counts survive even though the grade was stripped.
        for name, category in (details.get("category_breakdown") or {}).items():
            self.assertIn("actual_count", category, f"category '{name}' factual count over-stripped")

    # ---- authored-baseline gating (2026-08-10 USDA audit, P4-F1) -------------
    #
    # `test_no_graded_number_anywhere_in_anonymous_blob` above pins four key NAMES.
    # A name denylist only ever encodes the last incident, which is how the grade
    # survived this long: the quotient was stripped and its DIVISOR shipped, so
    # `actual_events: 12` + `expected_events: 13` still published 92% to anyone
    # willing to divide. The tests below assert the RULE instead of the names —
    #
    #   publish facts about the FARM; never publish Trazo's authored BASELINE
    #   or the scoring machinery that applies it
    #
    # — so a baseline key invented next year fails here without anyone
    # remembering to add it to a list. EU ECGT 2024/825 (live 2026-09-27).

    #: Key shapes that describe a Trazo-authored standard rather than the farm.
    _BASELINE_KEY_RE = re.compile(r"(^|_)(expected|target|should|requires?|required)(_|$)")
    #: Scoring internals that are neither farm facts nor obviously "baseline"-named.
    _MACHINERY_KEYS = frozenset({"anti_gaming_applied", "photo_tier_summary"})

    def test_no_authored_baseline_key_anywhere_in_anonymous_blob(self):
        blob = self._anon_payload()
        offenders = []

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if self._BASELINE_KEY_RE.search(k) or k in self._MACHINERY_KEYS:
                        offenders.append(f"{path}{k}={v!r}")
                    walk(v, f"{path}{k}.")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}].")

        walk(blob)
        self.assertEqual(
            offenders,
            [],
            "anonymous payload published a Trazo-authored baseline or scoring internal. "
            "The farm's own counts are evidence and belong here; a baseline the farm is "
            "measured AGAINST is a self-created standard (ECGT 2024/825). Offenders: " + "; ".join(offenders),
        )

    def test_grade_is_not_reconstructable_from_anonymous_counts(self):
        # The specific arithmetic that made the removal a rename: a numerator with
        # its denominator alongside. Pinned concretely so a regression is legible
        # even if the shape rule above is ever relaxed.
        details = (self._anon_payload().get("standard_view") or {}).get("transparency_details") or {}
        self.assertIn("actual_events", details, "event count (evidence) over-stripped")
        self.assertNotIn("expected_events", details, "denominator republished — the grade is 12/13 again")
        for name, category in (details.get("category_breakdown") or {}).items():
            self.assertIn("actual_count", category, f"category '{name}' factual count over-stripped")
            self.assertNotIn("expected_count", category, f"category '{name}' republished its denominator")

    def test_owner_still_receives_the_baseline(self):
        # The mirror of the gate: `expected_events` is the producer dashboard's KPI
        # input. Stripping it for the OWNER too would be over-correction — the score
        # is a legitimate engagement metric on the farmer's own surface.
        from rest_framework.test import APIClient

        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)
        details = ((client.get(self._url()).json().get("standard_view") or {}).get("transparency_details")) or {}
        self.assertIn("expected_events", details, "owner (producer dashboard) lost its baseline — over-stripped")

    # ---- P4-F5 / P4-F6: word choice and evidence basis (2026-08-11) -----------

    def test_photo_counts_are_documented_not_verified(self):
        """Farmer-uploaded photographs were checked by nobody.

        "Verified" is the word this project reserves for a USDA Organic Integrity Database
        match and enforces through claim_authority. A key name travels on the wire and is
        scrapable whatever the UI renders, so the key IS the claim.
        """
        blob = json.dumps(self._anon_payload())
        self.assertNotIn("photo_verified_count", blob)
        self.assertNotIn("photo_verification_rate", blob)

        details = (self._anon_payload().get("standard_view") or {}).get("transparency_details") or {}
        for name, category in (details.get("category_breakdown") or {}).items():
            with self.subTest(category=name):
                self.assertIn("photo_documented_count", category, "the factual count was dropped, not renamed")

    def test_organic_input_numbers_never_travel_without_their_basis(self):
        """P4-F6, and the seventh instance of one defect class.

        `organic_approved` is a grower DROPDOWN whose values include "omri_listed" — the grower
        picking that label, not a catalog match. `may_claim_input_listing()` already tiers this
        per input, after an anonymous payload asserted "OMRI Listed" for an input with no OMRI
        row (2026-08-09). That fix landed on the per-input chip and not on this aggregate, so
        one number spoke for evidence the authority refuses to speak for individually.
        """
        summary = (self._anon_payload().get("standard_view") or {}).get("organic_summary") or {}
        if not summary.get("has_input_data"):
            self.skipTest("fixture has no classified inputs")

        self.assertIn("organic_input_basis", summary, "the percentage shipped with no evidence tier")
        self.assertIn("organic_input_evidence", summary)
        self.assertIn(
            summary["organic_input_basis"],
            {"grower_reported", "national_list", "catalog_matched"},
        )

    def test_basis_reports_the_weakest_tier_present(self):
        # An aggregate is only as strong as its weakest member: one catalog match does not
        # license speaking for the inputs that have none.
        from history.transparency_views import _organic_input_evidence

        class _Ev:
            organic_approved = "omri_listed"
            omri_product_id = None
            national_list_substance_id = None
            extra_data = None

        matched = _Ev()
        matched.omri_product_id = 7

        result = _organic_input_evidence([matched, _Ev()])
        self.assertEqual(result["organic_input_evidence"]["catalog_matched"], 1)
        self.assertEqual(result["organic_input_evidence"]["grower_reported"], 1)
        self.assertEqual(result["organic_input_basis"], "grower_reported")

    def test_score_present_for_authenticated_owner(self):
        # The producer dashboard hits this same endpoint authenticated; the owner
        # must still receive their KPI score AND the deep-insights block. Gating is
        # anonymous-only.
        from rest_framework.test import APIClient

        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)
        resp = client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        body = resp.json()
        score = (body.get("quick_view") or {}).get("transparency_score") or {}
        self.assertIn("percentage", score, "owner (producer dashboard) lost its transparency score")
        self.assertIn("detailed_view", body, "owner (producer dashboard) lost its deep-insights block")


class ProductionsFlatScoreGatingTests(_Base):
    """Companion gate to TransparencyScoreGatingTests (2026-08-02).

    `/api/carbon/productions-flat/` served the same self-graded `transparency_score`
    that the consumer QR payload deliberately withholds — but anonymously, unscoped,
    and for EVERY tenant, unpublished drafts included. Its permission class guarded
    `obj.is_public` / `obj.company`, neither of which exists on `History`, so both
    checks short-circuited to True; DRF never invokes `has_object_permission` on a
    list route regardless.

    Gating the QR page while leaving a machine-readable score list open defeats the
    entire 2026-06 demotion, so this endpoint stays authenticated and company-scoped.
    """

    def _url(self):
        return "/api/carbon/productions-flat/"

    def _other_tenant_history(self):
        other_company = Company.objects.create(name="Other Farm")
        other_est = Establishment.objects.create(name="O1", company=other_company, state="CA")
        other_parcel = Parcel.objects.create(name="OP1", establishment=other_est, area=3.0)
        return History.objects.create(
            name="Other Tenant Production",
            start_date=timezone.now(),
            product=self.product,
            parcel=other_parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            transparency_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )

    def test_anonymous_is_rejected(self):
        resp = self.client.get(self._url())
        self.assertIn(
            resp.status_code,
            (401, 403),
            f"anonymous caller reached the self-graded production list (got {resp.status_code})",
        )

    def test_no_graded_score_in_anonymous_response(self):
        # Belt-and-suspenders: even if the status code regresses, no score may ship.
        resp = self.client.get(self._url())
        self.assertNotIn(
            "transparency_score",
            resp.content.decode(),
            "self-graded transparency score served to an anonymous caller",
        )

    def test_owner_sees_only_own_company_productions(self):
        from rest_framework.test import APIClient

        foreign = self._other_tenant_history()
        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)

        resp = client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        returned_ids = {row["id"] for row in resp.json()}
        self.assertIn(self.history.id, returned_ids, "owner lost their own production")
        self.assertNotIn(foreign.id, returned_ids, "cross-tenant production leaked to an authenticated user")

    def test_owner_keeps_score_on_own_productions(self):
        # The producer dashboard and the onboarding checklist both read this field;
        # locking the endpoint down must not strip the owner's own KPI.
        from rest_framework.test import APIClient

        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)

        resp = client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        rows = [row for row in resp.json() if row["id"] == self.history.id]
        self.assertTrue(rows, "owner lost their own production")
        self.assertIn("transparency_score", rows[0], "owner (producer dashboard) lost its transparency score")

    def test_events_count_covers_every_event_relation(self):
        # events_count is what the dashboard shows for a season with no score yet
        # ("In progress — N events logged"), so a relation missing from the tuple would
        # silently undercount a farmer's work rather than fail.
        from rest_framework.test import APIClient

        from history.models import BusinessEvent, ChemicalEvent, WeatherEvent

        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        ChemicalEvent.objects.create(history=self.history, type="FE", date=timezone.now())
        SoilManagementEvent.objects.create(history=self.history, type="CC", date=timezone.now())
        PestManagementEvent.objects.create(history=self.history, type="IP", date=timezone.now())
        WeatherEvent.objects.create(history=self.history, type="FR", date=timezone.now())
        BusinessEvent.objects.create(history=self.history, type="HA", date=timezone.now())

        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)

        resp = client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        row = next(r for r in resp.json() if r["id"] == self.history.id)
        self.assertEqual(row["events_count"], 6, "events_count missed a relation")

    def test_establishment_filter_cannot_cross_tenants(self):
        # The `establishment` query param must narrow within the user's own scope,
        # never widen it to someone else's farm.
        from rest_framework.test import APIClient

        foreign = self._other_tenant_history()
        self.user.companies.add(self.company)
        client = APIClient()
        client.force_authenticate(self.user)

        resp = client.get(self._url(), {"establishment": foreign.parcel.establishment_id})
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertEqual(resp.json(), [], "establishment filter widened scope to another tenant's farm")


class PhotoContentFlagGatingTests(_Base):
    """`photo_content_flag` is the INTERNAL Vision anti-gaming verdict.

    Reproduced live on an anonymous payload 2026-08-03: a published production served
    `timeline[1].photo_content_flag == "not_agricultural"` to unauthenticated callers — Trazo's
    own moderation verdict about a farmer, published on that farmer's public page. Same class
    as `drift_warning`, which the serializer already calls "self-incriminating audit data".

    Owner-gated rather than deleted: the producer's EventDetailsModal shows the farmer a
    "replace this with a real field photo" warning built from exactly this field.
    """

    def setUp(self):
        super().setUp()
        # The flag is derived from the IMAGE's extra_data (via _analyze_event_photos), not the
        # event's, and is only emitted when the event actually has an album with images.
        from common.models import Gallery, GalleryImage

        album = Gallery.objects.create()
        GalleryImage.objects.create(
            gallery=album,
            image_url="https://example.test/flagged.jpg",
            extra_data={"content_validation": "not_agricultural"},
        )
        self.event = ProductionEvent.objects.create(
            history=self.history,
            type="PL",
            date=timezone.now(),
            album=album,
        )

    def test_flag_absent_for_anonymous(self):
        blob = json.dumps(PublicHistorySerializer(self.history).data)
        self.assertNotIn(
            "photo_content_flag",
            blob,
            "internal photo-moderation verdict served to an anonymous consumer",
        )
        self.assertNotIn("not_agricultural", blob, "raw moderation value leaked to an anonymous consumer")

    def test_flag_kept_for_owner(self):
        # The producer must keep it — it drives their own "replace this photo" prompt.
        from rest_framework.test import APIRequestFactory

        self.user.companies.add(self.company)
        # A real request object: the serializer's get_qr_code calls build_absolute_uri.
        request = APIRequestFactory().get("/")
        request.user = self.user
        data = PublicHistorySerializer(self.history, context={"request": request}).data
        events = data.get("events") or []
        self.assertTrue(events, "no events serialized")
        self.assertIn(
            "photo_content_flag",
            events[0],
            "owner lost the photo-moderation flag their dashboard prompt depends on",
        )


class PracticeSummaryTests(_Base):
    """GTM-v3 "real vs. fake organic" differentiator: documented soil PRACTICES
    (integrated grazing, cover crops, on-farm compost) are surfaced to the anonymous consumer
    as FACTS in standard_view.practice_summary — never a grade or regenerative badge. The list
    is full for a practice-based grower and empty for an input-substitution farm.
    """

    def _url(self):
        return reverse(
            "production-transparency-detail",
            kwargs={"production_public_id": str(self.history.public_id)},
        )

    def _practice_summary(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return (resp.json().get("standard_view") or {}).get("practice_summary")

    def test_no_practices_returns_none(self):
        # A farm that logged no soil practices gets no section (hidden, not empty noise).
        self.assertIsNone(self._practice_summary())

    def test_grazing_cover_compost_surfaced_as_facts(self):
        SoilManagementEvent.objects.create(
            history=self.history, type="GR", animal_type="sheep", grazing_duration_days=3, date=timezone.now()
        )
        SoilManagementEvent.objects.create(
            history=self.history, type="CC", extra_data={"cover_crop_species": "winter legume"}, date=timezone.now()
        )
        SoilManagementEvent.objects.create(
            history=self.history, type="CO", compost_method="windrow", date=timezone.now()
        )
        ps = self._practice_summary()
        self.assertIsNotNone(ps, "practice_summary missing despite logged soil practices")
        by_key = {p["key"]: p for p in ps["practices"]}
        self.assertIn("integrated_grazing", by_key)
        self.assertIn("cover_crops", by_key)
        self.assertIn("on_farm_compost", by_key)
        # Facts carried through, no grade/score key.
        self.assertIn("sheep", by_key["integrated_grazing"]["animal_types"])
        self.assertIn("winter legume", by_key["cover_crops"]["species"])
        for p in ps["practices"]:
            for forbidden in ("score", "grade", "percentage", "rating"):
                self.assertNotIn(forbidden, p, f"graded key '{forbidden}' leaked into practice fact")


class GrazingSummaryModeTests(_Base):
    """GTM-v3: grazing rotations can be logged as one summary event (is_summary), mirroring
    pest scouting. The summary companion fields have no model columns, so the serializer must
    route them into extra_data; the event stays type=GR so the consumer practice_summary still
    surfaces it as integrated grazing.
    """

    def test_summary_fields_routed_to_extra_data(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        data = {
            "history": self.history.id,
            "type": "GR",
            "date": timezone.now().date().isoformat(),
            "name": "Spring sheep rotation",
            "description": "Sheep grazed 4 paddocks over 6 weeks",
            "area_covered": "20",
            "area_unit": "ha",
            "animal_type": "sheep",
            "is_summary": "true",
            "date_start": "2026-03-01",
            "date_end": "2026-04-15",
            "event_count": "4",
            "total_grazing_days": "12",
            "area_covered_total": "20",
        }
        serializer = UpdateSoilManagementEventSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save()

        self.assertEqual(event.type, "GR")
        ed = event.extra_data or {}
        self.assertEqual(ed.get("is_summary"), "true")
        self.assertEqual(ed.get("event_count"), "4")
        self.assertEqual(ed.get("total_grazing_days"), "12")
        self.assertEqual(str(ed.get("date_start")), "2026-03-01")
        # None of the summary companions are model columns.
        self.assertFalse(hasattr(event, "event_count") and getattr(event, "event_count", None) == 4)

    def test_summary_grazing_still_surfaced_in_practice_summary(self):
        from history.transparency_views import _build_practice_summary

        SoilManagementEvent.objects.create(
            history=self.history,
            type="GR",
            animal_type="sheep",
            grazing_duration_days=12,
            extra_data={"is_summary": "true", "event_count": "4"},
            date=timezone.now(),
        )
        ps = _build_practice_summary(self.history)
        self.assertIsNotNone(ps)
        self.assertIn("integrated_grazing", {p["key"] for p in ps["practices"]})

    def test_audit_export_soil_section_surfaces_grazing_detail(self):
        # Regression: the NOP audit PDF's soil section is amendment-oriented, so grazing details
        # (animal type/count/days/purpose + rotation period/passes) were dropped — a grazing row
        # showed only date/type/area. The Grazing Management Records sub-table must carry the detail.
        from history.services.audit_export_service import AuditExportService

        SoilManagementEvent.objects.create(
            history=self.history,
            type="GR",
            animal_type="sheep",
            animal_count=60,
            grazing_duration_days=24,
            grazing_purpose="soil_health",
            area_covered=10,
            area_unit="ha",
            extra_data={
                "is_summary": "true",
                "date_start": "2025-01-10",
                "date_end": "2025-03-15",
                "event_count": "4",
                "total_grazing_days": "24",
                "area_covered_total": "10",
            },
            date=timezone.now(),
        )
        svc = AuditExportService(self.history, certification_type="all")
        text = _flatten_reportlab_text(svc._build_soil_section())
        self.assertIn("Grazing Management Records", text)
        self.assertIn("sheep", text)
        self.assertIn("60", text)
        self.assertIn("Soil Health", text)
        self.assertIn("4", text)  # rotation passes (summary)
        self.assertIn("2025-01-10", text)  # rotation period start


class SoilAuditExportRenderTests(_Base):
    """The NOP audit PDF soil section is amendment-oriented; practice events whose detail lives in
    extra_data (cover-crop species) or non-amendment columns were silently dropped. Guard that
    cover-crop species reaches the dossier. (Grazing + compost have their own coverage.)
    """

    def test_cover_crop_species_surfaced(self):
        from history.services.audit_export_service import AuditExportService

        SoilManagementEvent.objects.create(
            history=self.history,
            type="CC",
            name="Winter cover crop",
            area_covered=10,
            area_unit="ha",
            extra_data={"cover_crop_species": "vetch + crimson clover + oats"},
            date=timezone.now(),
        )
        svc = AuditExportService(self.history, certification_type="all")
        text = _flatten_reportlab_text(svc._build_soil_section())
        self.assertIn("Cover Crop", text)
        self.assertIn("vetch", text)
        self.assertIn("oats", text)

    def test_csv_export_surfaces_grazing_and_cover_crop(self):
        # The CSV dossier had the same gap as the PDF — grazing detail and cover-crop species were
        # dropped. They must appear in the CSV (grazing folded into notes; species in Amendment).
        from history.services.audit_export_service import AuditExportService

        SoilManagementEvent.objects.create(
            history=self.history,
            type="GR",
            animal_type="sheep",
            animal_count=60,
            grazing_duration_days=24,
            grazing_purpose="soil_health",
            area_covered=10,
            area_unit="ha",
            extra_data={"is_summary": "true", "event_count": "4", "total_grazing_days": "24"},
            date=timezone.now(),
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type="CC",
            name="Winter cover crop",
            area_covered=10,
            area_unit="ha",
            extra_data={"cover_crop_species": "vetch + crimson clover + oats"},
            date=timezone.now(),
        )
        out = AuditExportService(self.history, certification_type="all").generate_csv()
        raw = out.getvalue()
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        self.assertIn("Grazing:", text)
        self.assertIn("sheep", text)
        self.assertIn("Soil Health", text)
        self.assertIn("vetch", text)


class ManureIntervalEnforcementTests(_Base):
    """NOP raw-manure pre-harvest interval (7 CFR 205.203(c)(1)) must be enforced on the API write
    path. The model.clean() rule is not run by DRF (no full_clean on objects.create), so the soil
    serializer's validate() enforces it. Regression guard for that enforcement.
    """

    def _base_data(self, **overrides):
        data = {
            "history": self.history.id,
            "type": "OM",
            "date": timezone.now().date().isoformat(),
            "name": "Composted manure application",
            "description": "Applied composted poultry manure",
            "area_covered": "5",
            "area_unit": "ha",
            "manure_application_date": "2026-05-01",
        }
        data.update(overrides)
        return data

    def test_manure_date_without_interval_rejected(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        serializer = UpdateSoilManagementEventSerializer(data=self._base_data())
        self.assertFalse(serializer.is_valid())
        self.assertIn("manure_harvest_interval", serializer.errors)

    def test_manure_with_interval_accepted(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        serializer = UpdateSoilManagementEventSerializer(data=self._base_data(manure_harvest_interval="90"))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        event = serializer.save()
        self.assertEqual(event.manure_harvest_interval, "90")


class HabitatCaptureTests(_Base):
    """GTM-v3 biodiversity/habitat (HD/NS subtypes on SoilManagementEvent). Facts only — the
    serializer routes habitat columns + free-text into extra_data, practice_summary surfaces them as
    facts, and NO biodiversity score/index ever appears. Mirrors the grazing/cover pattern.
    """

    def test_hd_serializer_routes_fields(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        data = {
            "history": self.history.id,
            "type": "HD",
            "date": timezone.now().date().isoformat(),
            "name": "Hedgerow planting",
            "description": "Planted a native hedgerow on the field margin",
            "area_covered": "0.5",
            "area_unit": "ha",
            "habitat_type": "hedgerow",
            "species_planted": "coyote brush, ceanothus, yarrow",
            "wildlife_observed": "lady beetles and lacewings; resident hawk",
        }
        serializer = UpdateSoilManagementEventSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save()
        self.assertEqual(event.type, "HD")
        self.assertEqual(event.habitat_type, "hedgerow")
        ed = event.extra_data or {}
        self.assertEqual(ed.get("species_planted"), "coyote brush, ceanothus, yarrow")
        self.assertIn("hawk", ed.get("wildlife_observed", ""))

    def test_ns_serializer_routes_fields(self):
        from history.serializers import UpdateSoilManagementEventSerializer

        data = {
            "history": self.history.id,
            "type": "NS",
            "date": timezone.now().date().isoformat(),
            "name": "Barn-owl boxes",
            "description": "Installed barn-owl boxes for natural rodent control",
            "habitat_type": "barn_owl_box",
            "habitat_structure_count": "6",
            "structure_notes": "12 ft poles on field margins; 4 of 6 occupied",
            # NS has no meaningful area — the form submits an empty string; must coerce to null,
            # not 400 on the DecimalField.
            "area_covered": "",
            "area_unit": "ha",
        }
        serializer = UpdateSoilManagementEventSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save()
        self.assertEqual(event.type, "NS")
        self.assertEqual(event.habitat_type, "barn_owl_box")
        self.assertEqual(event.habitat_structure_count, 6)
        self.assertIsNone(event.area_covered, "blank area must persist as null for NS, not 400 or 0")
        self.assertIn("occupied", (event.extra_data or {}).get("structure_notes", ""))

    def test_practice_summary_surfaces_habitat_as_facts(self):
        from history.transparency_views import _build_practice_summary

        SoilManagementEvent.objects.create(
            history=self.history, type="HD", habitat_type="hedgerow", date=timezone.now()
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type="NS",
            habitat_type="barn_owl_box",
            habitat_structure_count=6,
            date=timezone.now(),
        )
        ps = _build_practice_summary(self.history)
        self.assertIsNotNone(ps)
        by_key = {p["key"]: p for p in ps["practices"]}
        self.assertIn("habitat_development", by_key)
        self.assertIn("nesting_shelter", by_key)
        self.assertIn("hedgerow", by_key["habitat_development"]["habitat_types"])
        self.assertEqual(by_key["nesting_shelter"]["total_structures"], 6)
        # Facts only — no graded number leaked into any habitat fact.
        for p in ps["practices"]:
            for forbidden in ("score", "index", "grade", "richness", "rating"):
                self.assertNotIn(forbidden, p, f"graded key '{forbidden}' leaked into habitat fact")


class CarbonQrSummaryScoreGatingTests(_Base):
    """Claim-safety (V1/V2, 2026-06): the *carbon* anonymous QR endpoint
    (``carbon/public/productions/<pk>/qr-summary/``, PublicProductionViewSet) is a
    second public surface, separate from the transparency-detail endpoint covered above.
    It previously leaked the self-graded ``transparencyScore`` (quick + full payloads) and
    a hardcoded fake ``transparency_score: 95`` in socialProof. The graded score family must
    not appear in this anonymous payload either (EU ECGT 2024/825 / FTC 16 CFR 260.6).
    """

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())

    # PublicQRPermission blocks empty/short user agents as suspected bots; the
    # Django test client sends none, so pass a realistic browser UA.
    _UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"

    def _url(self, quick=False):
        url = reverse("public-production-qr-summary", kwargs={"pk": str(self.history.public_id)})
        return f"{url}?quick=true" if quick else url

    _GRADED_KEYS = {
        "transparencyScore",
        "transparency_score",
        "documentationCompleteness",
        "categoryBreakdown",
    }

    def _assert_no_graded_keys(self, blob):
        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    self.assertNotIn(
                        k,
                        self._GRADED_KEYS,
                        f"self-graded key '{k}' leaked to anonymous carbon qr-summary: {json.dumps(node)[:200]}",
                    )
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(blob)

    def test_quick_mode_has_no_graded_score(self):
        resp = self.client.get(self._url(quick=True), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self._assert_no_graded_keys(resp.json())

    def test_full_mode_has_no_graded_score(self):
        resp = self.client.get(self._url(quick=False), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self._assert_no_graded_keys(resp.json())

    # ---- Grades hidden in VALUES, not keys (2026-07-31) -------------------------------
    # The walker above matches KEY names. Three badges were emitted straight from
    # `transparency_score >= 95 / 85 / 75` and carried the grade in their "name" and
    # "description" VALUES ("Complete Transparency - Avocado"), so they sailed past it.
    # A tiered verdict derived from a self-assigned score IS the score.

    _GRADED_PHRASES = (
        "complete transparency",
        "high transparency",
        "good transparency",
        "complete documentation",
        "fully documented",
        "blockchain verified",  # compliance.md: "recorded", never "verified"
    )

    def _assert_no_graded_phrases(self, blob):
        haystack = json.dumps(blob).lower()
        for phrase in self._GRADED_PHRASES:
            self.assertNotIn(
                phrase,
                haystack,
                f"self-graded verdict or unsafe claim '{phrase}' reached the anonymous "
                f"carbon qr-summary payload (EU ECGT 2024/825 / FTC 16 CFR 260.6; "
                f"see .claude/rules/compliance.md)",
            )

    def test_quick_mode_has_no_graded_verdict_in_values(self):
        resp = self.client.get(self._url(quick=True), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self._assert_no_graded_phrases(resp.json())

    def test_full_mode_has_no_graded_verdict_in_values(self):
        resp = self.client.get(self._url(quick=False), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self._assert_no_graded_phrases(resp.json())

    def test_badge_names_are_factual_not_graded(self):
        """Badges may state facts (EPA/USDA-sourced, blockchain-recorded), never grades."""
        resp = self.client.get(self._url(quick=False), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        for badge in resp.json().get("badges") or []:
            name = str(badge.get("name", "")).lower()
            self.assertNotIn("transparency", name, f"score-derived badge still emitted: {badge}")


class CarbonCompleteSummaryScoreGatingTests(_Base):
    """The `complete/` sibling of qr-summary was never covered by the score gate.

    `carbon/public/productions/<pk>/complete/` served `parcel.transparency_score` — the same
    self-assigned 0-100 grade the transparency endpoint carefully strips. Found 2026-07-31.

    🔒 2026-08-12: the endpoint is now AUTHENTICATED and OWNER-ONLY (it was anonymous and
    integer-pk enumerable). The assertions below still run, against the owner's own request,
    because the scrubbing in the payload is unconditional — it does not consult the caller.
    Keeping them costs nothing and they are the regression net if the endpoint is ever
    re-opened. `CompleteSummaryIsOwnerOnlyTests` below covers the access rule itself.
    """

    _UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")
        # DRF here authenticates ONLY via users.auth.CustomAuthentication (JWT cookie) — there is
        # no SessionAuthentication, so django.test.Client.force_login leaves the request
        # anonymous as far as DRF is concerned and every call 401s.
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _url(self):
        return f"/api/carbon/public/productions/{self.history.id}/complete/"

    def test_no_transparency_score_anywhere_in_payload(self):
        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])

        found = []

        def walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in {"transparency_score", "transparencyScore"}:
                        found.append(f"{path}/{k}")
                    walk(v, f"{path}/{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        walk(resp.json())
        self.assertEqual(
            found,
            [],
            f"self-graded transparency_score leaked on the anonymous complete/ endpoint at: {found}",
        )

    def test_factual_transparency_flags_still_survive(self):
        """`transparency_ready` is a boolean readiness flag, not a grade — it may stay."""
        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        parcel = resp.json().get("parcel")
        if parcel is not None:
            self.assertIn("transparency_ready", parcel)

    # --- P0 (2026-08-07): the same action leaked the whole location-PII set --------------
    #
    # `complete/` hand-built its own establishment, company and parcel blocks, so it never
    # received ANY of the fixes applied to history/transparency_views.py. It shipped, raw:
    # street address, exact lat/lon, ZIP, un-redacted marketing prose, `farming_method`, the
    # company street address, and an ungated parcel polygon + map_metadata. Two hand-built
    # payloads for one resource is how it drifted unnoticed for months.

    def _populate_pii(self):
        """The _Base fixture leaves every PII field blank.

        Without this the assertions below are VACUOUS — `assertFalse(falsy)` passes whether
        or not the endpoint withholds anything. Verified by reintroducing the leak: the test
        still passed until these values were set.
        """
        self.establishment.address = "1234 Very Private Lane"
        self.establishment.latitude = 36.123456
        self.establishment.longitude = -119.654321
        self.establishment.zip_code = "93999"
        self.establishment.farming_method = "sustainable"
        self.establishment.save(update_fields=["address", "latitude", "longitude", "zip_code", "farming_method"])
        self.company.address = "9 Corporate Row"
        self.company.save(update_fields=["address"])

    def _farm_block(self, payload):
        """The establishment block, under the key the payload ACTUALLY uses.

        🔴 These tests read `payload["establishment"]` for months. The action serialises its
        establishment dict as **`farmer`** (`carbon/views.py`: `"farmer": establishment_data`),
        so `.get("establishment")` returned `{}` and every `assertFalse(bool(farm.get(...)))`
        below passed against an empty dict — whatever the endpoint published. The class had
        already been hardened once against VALUE vacuity (`_populate_pii`); the vacuity had
        simply moved to the KEY. Asserting the block exists is what stops it moving again.
        """
        farm = payload.get("farmer")
        self.assertIsInstance(
            farm,
            dict,
            "no `farmer` block in the payload — every PII assertion in this test would be vacuous",
        )
        return farm

    def test_location_pii_is_withheld(self):
        self._populate_pii()
        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        payload = resp.json()
        farm = self._farm_block(payload)

        for field in ("address", "latitude", "longitude", "zip_code"):
            self.assertFalse(
                bool(farm.get(field)),
                f"location PII '{field}' leaked on the anonymous complete/ endpoint: "
                f"{farm.get(field)!r} (2026-06 P1; hard-nulled on the transparency endpoint)",
            )

        company = farm.get("company") or {}
        self.assertFalse(
            bool(company.get("address")),
            f"company street address leaked: {company.get('address')!r}",
        )

        # Belt and braces: the VALUES must be absent from the whole blob, not just from the
        # keys we thought to check.
        blob = json.dumps(payload)
        for secret in ("1234 Very Private Lane", "93999", "36.123456", "-119.654321", "9 Corporate Row"):
            self.assertNotIn(secret, blob, f"{secret!r} reached the anonymous payload")

    def test_farming_method_is_not_published(self):
        """Free-text self-declared claim — FTC 16 CFR 260.6 / EU ECGT 2024/825.

        The transparency endpoint never serialises it; this one published it raw.
        """
        self._populate_pii()
        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        farm = self._farm_block(resp.json())
        self.assertNotIn(
            "farming_method",
            farm,
            "farming_method leaked on the anonymous complete/ endpoint",
        )
        self.assertNotIn("sustainable", json.dumps(resp.json()))

    def test_parcel_agricultural_details_blob_is_not_published(self):
        """The grower's private agronomy must not ship on an anonymous endpoint.

        `agricultural_details` is a free-form JSONField the parcel form writes into — soil
        test results (pH, organic matter, N, P), irrigation efficiency and
        `water_allocation_acre_feet`, which is commercially sensitive in California. It was
        published RAW here and rendered by no consumer surface at all.

        Same defect `map_metadata` had (2026-08-02: soil_health_score, biodiversity_score,
        yield_vs_conventional "+85%"). A blob nobody renders cannot leak if it is not sent.
        """
        self.parcel.agricultural_details = {
            "soil_ph": "6.8",
            "water_allocation_acre_feet": "42.5",
            "consumer_story": "secret narrative",
            "soil_health_score": 92,
        }
        self.parcel.save(update_fields=["agricultural_details"])

        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        parcel = resp.json().get("parcel") or {}

        self.assertNotIn(
            "agricultural_details",
            parcel,
            "raw agricultural_details blob published on the anonymous complete/ endpoint",
        )
        blob = json.dumps(resp.json())
        for secret in ("42.5", "secret narrative", "soil_health_score"):
            self.assertNotIn(secret, blob, f"{secret!r} reached the anonymous payload")

    def test_parcel_consumer_story_is_not_published(self):
        """Removed from the product 2026-08-07 — form, serializer, model getter and payload."""
        self.parcel.agricultural_details = {"consumer_story": "why shoppers should care"}
        self.parcel.save(update_fields=["agricultural_details"])

        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        parcel = resp.json().get("parcel") or {}
        self.assertNotIn("consumer_story", parcel)

    def test_location_string_never_falls_back_to_the_street_address(self):
        """`location` used to read `f"{city}, {state}" or establishment.address`.

        With city/state unset that published the street address through a field whose whole
        purpose is to be the COARSE location.
        """
        self.establishment.city = ""
        self.establishment.state = ""
        self.establishment.address = "1234 Very Private Lane"
        self.establishment.save(update_fields=["city", "state", "address"])

        resp = self.client.get(self._url(), HTTP_USER_AGENT=self._UA)
        blob = json.dumps(resp.json())
        self.assertNotIn(
            "Very Private Lane",
            blob,
            "street address leaked through the `location` fallback",
        )


class CompleteSummaryIsOwnerOnlyTests(_Base):
    """`carbon/public/productions/<pk>/complete/` is authenticated and owner-only (2026-08-12).

    It used to be anonymous and integer-pk enumerable while hand-building its own
    establishment, company and parcel blocks — a second public payload for a resource that
    already has one, which is why the same PII and claim fixes had to be re-applied to it
    repeatedly. Its only caller is the producer's own `ProfileProduction` screen.

    These tests pin the ACCESS rule. The payload-content rules stay in
    `CarbonCompleteSummaryScoreGatingTests` above.
    """

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        WorksIn.objects.create(user=self.user, company=self.company, role="CA")

        # A second, unrelated grower — the "any signed-up account" case.
        self.outsider = User.objects.create_user(email="outsider@test.com", password="x")
        self.outsider_company = Company.objects.create(name="Someone Else Farms")
        WorksIn.objects.create(user=self.outsider, company=self.outsider_company, role="CA")

    def _url(self):
        return f"/api/carbon/public/productions/{self.history.id}/complete/"

    def test_anonymous_is_refused(self):
        resp = self.client.get(self._url())
        self.assertIn(
            resp.status_code,
            (401, 403),
            f"anonymous caller still reached complete/ (HTTP {resp.status_code}) — this endpoint "
            f"emits unqualified certification strings and the grower's own record",
        )

    def _as(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_the_owner_still_gets_it(self):
        """ProfileProduction must keep working — the point is to narrow access, not break it."""
        self.client = self._as(self.user)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        self.assertEqual(resp.json().get("production_id"), self.history.id)

    def test_a_signed_in_stranger_is_refused(self):
        """Authentication alone is not the gate.

        The old visibility clause was `published=True OR mine`, so ANY account could read ANY
        published production here — the anonymous exposure with a free signup in front of it.
        """
        self.client = self._as(self.outsider)
        resp = self.client.get(self._url())
        self.assertEqual(
            resp.status_code,
            404,
            "a grower from another company read this production's complete summary",
        )

    def test_the_owner_can_still_read_an_unpublished_draft(self):
        """ProfileProduction loads before the production is published."""
        self.history.published = False
        self.history.save(update_fields=["published"])

        self.client = self._as(self.user)
        self.assertEqual(self.client.get(self._url()).status_code, 200)

    def test_integer_pk_enumeration_is_closed_to_strangers(self):
        """The docstring that flagged this endpoint called out integer-pk enumeration.

        Ownership is what closes it: guessing the id no longer helps, published or not.
        """
        self.client = self._as(self.outsider)
        for pk in (self.history.id, self.history.id + 1, 1):
            resp = self.client.get(f"/api/carbon/public/productions/{pk}/complete/")
            self.assertIn(resp.status_code, (403, 404), f"pk={pk} returned {resp.status_code}")


class FarmCertificationsAreStructuredOnlyTests(_Base):
    """`farmer.certifications` on the anonymous transparency payload is STRUCTURED or absent.

    Until 2026-08-12 the block read `certification_data or establishment.certifications`, so an
    operation with no `Certification` rows fell back to the free-text field the farmer types
    into — publishing third-party certification names with nothing in the database behind them
    and no verification status attached.

    The `or` also changed the TYPE. Every downstream control (`filter_certifications_for_consumer`,
    `consumer_display_status`, the JSON-LD `verified_via_database` filter) reads a list of cert
    OBJECTS; a bare string satisfies `or` and then passes all of them untouched, because a string
    has no `.status` to test. It was a bypass, not a degraded path.
    """

    _UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1"

    _FREE_TEXT = "Carbon Trust Standard, GlobalGAP, SQF Level 2, Rainforest Alliance"

    def setUp(self):
        super().setUp()
        ProductionEvent.objects.create(history=self.history, type="PL", date=timezone.now())
        self.establishment.certifications = self._FREE_TEXT
        self.establishment.save(update_fields=["certifications"])

    def _payload_json(self):
        resp = self.client.get(f"/api/transparency/{self.history.public_id}/", HTTP_USER_AGENT=self._UA)
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()

    def _farmer_certifications(self, payload):
        for block in (payload, payload.get("standard_view") or {}):
            farmer = block.get("farmer") or block.get("establishment") or {}
            if "certifications" in farmer:
                return farmer["certifications"]
        return None

    def test_free_text_certifications_never_reach_the_consumer_payload(self):
        """No Certification rows exist for this establishment — the field must not stand in."""
        payload = self._payload_json()

        blob = json.dumps(payload)
        for claimed in ("Carbon Trust Standard", "GlobalGAP", "SQF Level 2", "Rainforest Alliance"):
            self.assertNotIn(
                claimed,
                blob,
                f"free-text certification {claimed!r} reached the anonymous consumer payload with "
                f"no Certification row behind it",
            )

    def test_certifications_is_never_a_bare_string(self):
        """A string bypasses every claim-safety control, all of which expect cert objects."""
        certifications = self._farmer_certifications(self._payload_json())
        self.assertNotIsInstance(
            certifications,
            str,
            "certifications published as a free-text string — status-based gating cannot apply",
        )

    def test_real_rows_still_publish_with_their_status(self):
        """Removing the fallback must not remove genuine certifications."""
        from certifications.models import Certification

        Certification.objects.create(
            establishment=self.establishment,
            certification_type="global_gap",
            verification_status="self_reported",
        )

        certifications = self._farmer_certifications(self._payload_json())
        self.assertIsInstance(certifications, list, f"expected a list of cert objects, got {certifications!r}")
        self.assertTrue(certifications, "a real Certification row did not reach the payload")
        for cert in certifications:
            self.assertIn(
                "status",
                cert,
                f"certification published without a verification status: {cert!r} — the consumer "
                f"surface cannot label it, so it reads as third-party verified",
            )
        self.assertEqual(
            {c["status"] for c in certifications},
            {"self_reported"},
            "a self-reported certification was upgraded on the consumer payload",
        )


class ComplianceFieldExposureTests(_Base):
    """New compliance fields (2026-06) must reach the RIGHT output. BR organic-approval, TM trap
    detail and habitat install date are consumer transparency positives; the BR supplier + lot are
    commercially sensitive and must stay AUDIT-ONLY (never in the anonymous QR payload)."""

    def setUp(self):
        super().setUp()
        PestManagementEvent.objects.create(
            history=self.history,
            type="BR",
            beneficial_species="Green lacewings",
            beneficial_supplier="Rincon-Vitova Insectaries",
            beneficial_lot_number="RV-2026-0418",
            beneficial_organic_approved="yes",
            date=timezone.now(),
        )
        PestManagementEvent.objects.create(
            history=self.history,
            type="TM",
            trap_count=8,
            trap_type="pheromone",
            pest_catch_count=22,
            date=timezone.now(),
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type="HD",
            habitat_type="hedgerow",
            habitat_install_date="2019-02-15",
            date=timezone.now(),
        )

    def _events(self):
        return self._payload().get("events") or []

    def test_br_organic_approval_is_consumer_visible(self):
        br = [e for e in self._events() if e.get("beneficial_species")]
        self.assertTrue(br)
        self.assertEqual(br[-1].get("beneficial_organic_approved"), "yes")

    def test_br_supplier_and_lot_are_audit_only(self):
        blob = json.dumps(self._payload(), default=str)
        self.assertNotIn("Rincon-Vitova Insectaries", blob, "beneficial supplier leaked to public payload")
        self.assertNotIn("RV-2026-0418", blob, "beneficial lot number leaked to public payload")

    def test_tm_trap_detail_is_consumer_visible(self):
        tm = [e for e in self._events() if e.get("trap_type")]
        self.assertTrue(tm)
        self.assertEqual(tm[-1].get("trap_type"), "pheromone")
        self.assertEqual(tm[-1].get("pest_catch_count"), 22)

    def test_habitat_install_date_is_consumer_visible(self):
        hd = [e for e in self._events() if e.get("habitat_type") == "hedgerow"]
        self.assertTrue(hd)
        self.assertEqual(hd[-1].get("habitat_install_date"), "2019-02-15")
