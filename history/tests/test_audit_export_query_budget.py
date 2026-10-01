"""
The audit export must read what the view prefetched — not go back to the database per row.

Measured 2026-09-05 on a 12-production operation dossier: 2,755 queries, of which ~1,600 were
the change-history section (auditlog `get_for_object()` per event, then `.actor` and
`.content_type` per entry) and ~350 were section builders calling `.order_by()` / `.filter()`
on relations the view had already prefetched. In production every query costs a network
round-trip, so this was the difference between a 15-second build and a minute.

These tests pin the two properties that make that fix stick:
  * the change-history query count does not grow with the number of events;
  * `related_events()` and `album_images()` serve prefetched data with zero queries and
    order exactly as the query they replaced.
"""

import io
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from certifications.models import OrganicSystemPlan
from common.models import Gallery, GalleryImage
from company.models import Company, Establishment
from history.models import ChemicalEvent, History, ProductionEvent
from history.services.audit_export_service import AuditExportService, _photo_count, album_images, related_events
from history.services.operation_audit_export_service import OperationAuditExportService
from product.models import Parcel, Product
from users.models import User


def _png_bytes(size=(40, 30), mode="RGBA"):
    from PIL import Image

    out = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


class _Base(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="budget@test.com", password="x")
        self.company = Company.objects.create(name="Budget Farm")
        self.establishment = Establishment.objects.create(name="Budget Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.establishment, area=10.0)
        self.product = Product.objects.create(name="Almonds")
        self.production = History.objects.create(
            name="2026 Almonds",
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
            published=True,
        )

    def _events(self, n, offset_days=0):
        for i in range(n):
            when = timezone.now() - timezone.timedelta(days=offset_days + i)
            ChemicalEvent.objects.create(
                history=self.production,
                type=ChemicalEvent.PESTICIDE,
                commercial_name=f"Product {i}",
                date=when,
                created_by=self.user,
            )
            ProductionEvent.objects.create(history=self.production, type="HA", date=when, created_by=self.user)

    def _prefetched(self):
        """The production exactly as the export views load it."""
        return OperationAuditExportService(self.establishment)._productions()[0]


class ChangeHistoryQueryBudgetTests(_Base):
    def _count(self):
        production = self._prefetched()
        service = AuditExportService(production, certification_type="organic")
        with CaptureQueriesContext(connection) as ctx:
            flowables = service._build_change_history_section()
        self.assertTrue(flowables)
        return len(ctx.captured_queries)

    def test_query_count_does_not_grow_with_events(self):
        from auditlog.models import LogEntry

        self._events(2)
        self.assertTrue(LogEntry.objects.exists(), "auditlog is not capturing writes — the section has nothing to read")
        small = self._count()
        self._events(15, offset_days=10)
        large = self._count()
        self.assertEqual(
            small,
            large,
            f"change history ran {small} queries for 4 events and {large} for 34 — it is back to one per record",
        )
        self.assertLessEqual(large, 10)

    def test_retired_equipment_model_stays_out_of_the_trail(self):
        """EquipmentEvent is retired in the UI (equipment work is a Production EM/PH record);
        a legacy row must not resurface as an auditable record in a certifier document."""
        from history.models import EquipmentEvent

        EquipmentEvent.objects.create(history=self.production, date=timezone.now(), created_by=self.user)
        service = AuditExportService(self._prefetched(), certification_type="organic")
        tables = [f for f in service._build_change_history_section() if f.__class__.__name__ == "Table"]
        cells = " ".join(
            getattr(c, "text", str(c))
            for t in tables
            for row in t._cellvalues
            for c in (row if isinstance(row, list) else [row])
        )
        self.assertNotIn("EquipmentEvent", cells)

    def test_fallback_author_comes_from_one_bulk_lookup(self):
        """Entries with no actor (created outside a request) still name the record's author."""
        self._events(1)
        service = AuditExportService(self._prefetched(), certification_type="organic")
        tables = [f for f in service._build_change_history_section() if f.__class__.__name__ == "Table"]
        cells = " ".join(
            getattr(c, "text", str(c))
            for t in tables
            for row in t._cellvalues
            for c in (row if isinstance(row, list) else [row])
        )
        self.assertIn("budget", cells)  # budget@test.com, wrapped at the "@" by _actor_cell


class RelatedEventsTests(_Base):
    def test_prefetched_read_costs_zero_queries_and_orders_like_the_database(self):
        self._events(5)
        production = self._prefetched()
        expected = list(
            ChemicalEvent.objects.filter(history=self.production).order_by("date").values_list("pk", flat=True)
        )
        with self.assertNumQueries(0):
            rows = related_events(production, "history_chemicalevent_events")
            reverse = related_events(production, "history_chemicalevent_events", order="-date")
            harvests = related_events(production, "history_productionevent_events", type="HA")
            none = related_events(production, "history_productionevent_events", type="PL")
        self.assertEqual([r.pk for r in rows], expected)
        self.assertEqual([r.pk for r in reverse], list(reversed(expected)))
        self.assertEqual(len(harvests), 5)
        self.assertEqual(none, [])

    def test_lookups_in_and_isnull_match_the_orm(self):
        self._events(3)
        production = self._prefetched()
        via_orm = set(
            ProductionEvent.objects.filter(
                history=self.production, type__in=("HA", "PL"), date__isnull=False
            ).values_list("pk", flat=True)
        )
        with self.assertNumQueries(0):
            rows = related_events(
                production, "history_productionevent_events", type__in=("HA", "PL"), date__isnull=False
            )
        self.assertEqual({r.pk for r in rows}, via_orm)

    def test_unsupported_lookup_raises_instead_of_returning_wrong_rows(self):
        self._events(1)
        with self.assertRaises(ValueError):
            related_events(self._prefetched(), "history_chemicalevent_events", date__gte=timezone.now())

    def test_falls_back_to_a_query_when_not_prefetched(self):
        self._events(2)
        plain = History.objects.get(pk=self.production.pk)
        rows = related_events(plain, "history_chemicalevent_events", type=ChemicalEvent.PESTICIDE)
        self.assertEqual(len(rows), 2)


class PhotoHelpersTests(_Base):
    def _event_with_photos(self, n=2):
        gallery = Gallery.objects.create()
        for i in range(n):
            GalleryImage.objects.create(
                gallery=gallery, image_url=f"https://photos.example.test/{i}.png", file_size=4096
            )
        return ChemicalEvent.objects.create(
            history=self.production,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            album=gallery,
        )

    def test_album_images_and_photo_count_read_the_prefetch(self):
        self._event_with_photos(3)
        production = self._prefetched()
        event = related_events(production, "history_chemicalevent_events")[0]
        with self.assertNumQueries(0):
            images = album_images(event.album)
            count = _photo_count(event)
        self.assertEqual(count, 3)
        self.assertEqual([i.pk for i in images], sorted(i.pk for i in images))

    def test_photos_are_fetched_once_concurrently_then_served_from_cache(self):
        self._event_with_photos(2)
        production = self._prefetched()
        service = AuditExportService(production, certification_type="organic")
        event = related_events(production, "history_chemicalevent_events")[0]

        response = mock.Mock(status_code=200, content=_png_bytes())
        with mock.patch("requests.get", return_value=response) as get:
            service._prefetch_photo_images([("Chemical", [event])])
            self.assertEqual(get.call_count, 2)
            self.assertEqual(len(service._image_cache), 2)
            for image in album_images(event.album):
                buf = service._fetch_image_for_pdf(image)
                self.assertIsNotNone(buf)
                self.assertTrue(buf.getvalue().startswith(b"\xff\xd8"), "cache must hold JPEG bytes for ReportLab")
            self.assertEqual(get.call_count, 2, "the gallery loop must not hit the network again")

    def test_http_failures_are_classified_as_before(self):
        buf, failure = AuditExportService._download_image_bytes("https://photos.example.test/x.png", 2, 800)
        self.assertIsNone(buf)
        self.assertEqual(failure[0], "error")
        with mock.patch("requests.get", return_value=mock.Mock(status_code=404, content=b"")):
            buf, failure = AuditExportService._download_image_bytes("https://photos.example.test/x.png", 2, 800)
        self.assertEqual((buf, failure), (None, ("http", "HTTP 404")))

    def test_rgba_is_flattened_and_oversize_is_resized(self):
        response = mock.Mock(status_code=200, content=_png_bytes(size=(3000, 1000)))
        with mock.patch("requests.get", return_value=response):
            buf, failure = AuditExportService._download_image_bytes("https://photos.example.test/x.png", 2, 1400)
        self.assertIsNone(failure)
        from PIL import Image

        img = Image.open(buf)
        self.assertEqual(img.mode, "RGB")
        self.assertLessEqual(max(img.size), 1400)


class OspNarrativesLeadTests(_Base):
    SECTIONS = {
        key: {"narrative": "x" * 450, "last_updated": None}
        for key in (
            "practices_procedures",
            "inputs_list",
            "monitoring_plan",
            "recordkeeping_description",
            "commingling_barriers",
            "additional_certifier_info",
        )
    }

    def _lead_text(self):
        service = AuditExportService(self._prefetched(), certification_type="organic")
        texts = [getattr(f, "text", "") for f in service._build_osp_reference_section()]
        leads = [t for t in texts if "Section narratives" in t]
        self.assertEqual(len(leads), 1)
        return leads[0]

    def test_a_draft_is_not_called_filed(self):
        OrganicSystemPlan.objects.create(
            establishment=self.establishment, status="draft", version_number=1, sections=self.SECTIONS
        )
        self.assertIn("not yet filed", self._lead_text())
        self.assertNotIn("filed with the certifier.", self._lead_text())

    def test_an_active_plan_is(self):
        OrganicSystemPlan.objects.create(
            establishment=self.establishment, status="active", version_number=1, sections=self.SECTIONS
        )
        self.assertIn("filed with the certifier", self._lead_text())
        self.assertNotIn("not yet filed", self._lead_text())
