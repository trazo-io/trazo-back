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

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History, PestManagementEvent, ProductionEvent, SoilManagementEvent
from history.serializers import PublicHistorySerializer
from history.services.privacy import public_parcel_geo
from product.models import Parcel, Product
from users.models import User


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
        self.establishment = Establishment.objects.create(name="P1", company=self.company)
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
