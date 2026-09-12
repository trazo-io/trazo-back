"""The parcel map must be IN the packet, not described by it.

WHY THIS EXISTS
---------------
Certifier register `map-absent-from-packet` — CCOF NOPB49 §E and WSDA AGR 2264, the last blocker
that stops a filing rather than merely overstating one. Both certifiers treat the map as a
MANDATORY ATTACHMENT: CCOF's own text says it "must be reviewed by CCOF prior to inspection of a
new parcel", WSDA's that "a map … must be submitted with each site application".

Trazo printed one sentence — "Field map on file (boundary recorded in Trazo)" — and no map, on
the page whose entire job is to prove land eligibility. That is worse than printing nothing: it
tells a reviewer the map exists somewhere they are not looking.

The drawing already existed as a private method on the per-production audit-export builder, so
the document that most needed it could not call it. It now lives in
`certifications.services.parcel_map` and BOTH documents render from it — which is also the only
way they cannot draw the same parcel two different ways.

WHAT THE PAGE MAY CLAIM. A boundary schematic is not satellite imagery and cannot carry most of
CCOF's eleven required elements (roads and landmarks, block identifiers, other operation areas).
So the page says which of the two the reviewer is holding, and asks for the operator's own map
when none is attached — rather than letting a schematic pass as the required attachment.
"""

import zipfile

from django.test import TestCase

from certifications.models import OrganicSystemPlan
from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
from certifications.services.osp_module_pdf import PARCEL_MAP_SECTION, generate_module_pdf
from certifications.services.parcel_map import parcel_map_caption, parcel_map_drawing
from company.models import Company, Establishment
from product.models import Parcel

# A small square, closed as GeoJSON rings are.
RING = [[-123.11, 44.54], [-123.10, 44.54], [-123.10, 44.55], [-123.11, 44.55], [-123.11, 44.54]]


class ParcelMapDrawingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Map Co")
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.parcel = Parcel.objects.create(
            name="Home Field East",
            establishment=self.est,
            area=5.06,
            polygon={"type": "Polygon", "coordinates": [RING]},
            buffer_zones=[
                {"direction": "west", "adjoining_land_use": "Conventional ryegrass"},
                {"direction": "south", "adjoining_land_use": "County road"},
            ],
        )

    def test_a_parcel_with_geometry_produces_a_drawing(self):
        self.assertIsNotNone(parcel_map_drawing(self.parcel))

    def test_a_parcel_without_geometry_produces_none_not_an_empty_box(self):
        # None, so the caller says "no map" in its own words. An empty frame reads as a map
        # that failed to load.
        self.parcel.polygon = None
        self.assertIsNone(parcel_map_drawing(self.parcel))

    def test_degenerate_geometry_does_not_raise(self):
        # A zero-area polygon would divide by zero when scaling.
        self.parcel.polygon = {"type": "Polygon", "coordinates": [[[1.0, 2.0]] * 4]}
        self.assertIsNone(parcel_map_drawing(self.parcel))

    def _parts(self, drawing):
        from reportlab.graphics.shapes import Polygon, String

        poly = next(s for s in drawing.contents if isinstance(s, Polygon))
        xs, ys = poly.points[0::2], poly.points[1::2]
        labels = [s for s in drawing.contents if isinstance(s, String) and s.text != "N"]
        return (min(xs), max(xs), min(ys), max(ys)), labels

    def test_the_block_fill_lets_a_watermark_read_through(self):
        """The SPECIMEN wash is drawn under the flowables, so an opaque block hides it.

        On the WSDA specimen the fill blanked the middle of the word on every parcel page, and a
        page printed on its own then carried a fabricated field map with no mark (2026-09-11).
        """
        from reportlab.graphics.shapes import Polygon

        poly = next(s for s in parcel_map_drawing(self.parcel).contents if isinstance(s, Polygon))
        self.assertLess(poly.fillColor.alpha, 1.0)

    def test_a_long_neighbour_is_wrapped_never_cut(self):
        """🔴 2026-09-11 — the specimen packet printed "EAST · Bureau of Land Management shrub…":
        the cut removed the adjoining land use, the one thing the certifier asks the map to label."""
        long_east = "Bureau of Land Management shrub-steppe, unmanaged, no applications of record"
        long_south = "Ridge Block — our own certified organic apples, same management, no buffer needed"
        self.parcel.buffer_zones = [
            {"direction": "east", "adjoining_land_use": long_east},
            {"direction": "south", "adjoining_land_use": long_south},
        ]
        _box, labels = self._parts(parcel_map_drawing(self.parcel))
        text = " ".join(s.text for s in labels)
        self.assertNotIn("…", text)
        for word in (long_east + " " + long_south).split():
            self.assertIn(word, text)

    def test_no_label_crosses_the_field_boundary(self):
        """The EAST label was anchored at the page edge and ran back across the boundary box."""
        self.parcel.buffer_zones = [
            {"direction": d, "adjoining_land_use": "Conventional orchard under a long lease, sprayed weekly"}
            for d in ("north", "south", "east", "west")
        ]
        from reportlab.pdfbase.pdfmetrics import stringWidth

        (x1, x2, y1, y2), labels = self._parts(parcel_map_drawing(self.parcel))
        for s in labels:
            w = stringWidth(s.text, s.fontName, s.fontSize)
            left = s.x - w if s.textAnchor == "end" else s.x - w / 2 if s.textAnchor == "middle" else s.x
            right = left + w
            beside = right <= x1 or left >= x2
            above_or_below = s.y >= y2 or s.y + s.fontSize <= y1
            self.assertTrue(beside or above_or_below, f"label {s.text!r} overlaps the boundary")

    def test_no_two_labels_overlap_even_when_every_side_is_long(self):
        long = "Conventional orchard under a long lease, sprayed weekly with synthetic fungicide " * 3
        self.parcel.buffer_zones = [
            {"direction": d, "adjoining_land_use": long} for d in ("north", "south", "east", "west")
        ]
        from reportlab.pdfbase.pdfmetrics import stringWidth

        _box, labels = self._parts(parcel_map_drawing(self.parcel))
        boxes = []
        for s in labels:
            w = stringWidth(s.text, s.fontName, s.fontSize)
            left = s.x - w if s.textAnchor == "end" else s.x - w / 2 if s.textAnchor == "middle" else s.x
            boxes.append((left, left + w, s.y, s.y + s.fontSize, s.text))
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                apart = a[1] <= b[0] or b[1] <= a[0] or a[3] <= b[2] or b[3] <= a[2]
                self.assertTrue(apart, f"{a[4]!r} overlaps {b[4]!r}")

    def test_the_caption_prints_acres_not_the_raw_hectare_number(self):
        # 🔴 2026-08-20: this page printed `Parcel.area` (HECTARES) beside the word "acres", so a
        # reviewer read a 28.4-acre block as 11.49 acres. `area_display()` is the only correct
        # way to print it and the caption must go through it.
        caption = parcel_map_caption(self.parcel)
        self.assertIn("acres", caption)
        self.assertNotIn("5.06 acres", caption)


class ParcelMapReachesTheDocumentsTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Map Co")
        self.est = Establishment.objects.create(name="Home Ranch", company=self.company)
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.parcel = Parcel.objects.create(
            name="Home Field East",
            establishment=self.est,
            area=5.06,
            polygon={"type": "Polygon", "coordinates": [RING]},
        )

    def _pdf(self):
        data = generate_module_pdf(self.osp, PARCEL_APPLICATION.key, parcel=self.parcel)
        return data.getvalue() if hasattr(data, "getvalue") else data

    def test_the_parcel_application_no_longer_only_describes_the_map(self):
        # The exact sentence the defect consisted of.
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(self._pdf())) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            shapes = sum(len(page.curves) + len(page.lines) + len(page.rects) for page in pdf.pages)
        self.assertNotIn("Field map on file (boundary recorded in Trazo)", text)
        self.assertGreater(shapes, 0, "the parcel page must carry drawn geometry, not only prose")

    def test_it_asks_for_the_operators_own_map_when_none_is_attached(self):
        # A schematic must not pass as the required attachment.
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(self._pdf())) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        self.assertIn("No operator-supplied map", text.replace("\n", " "))

    def test_a_parcel_with_no_boundary_still_shows_its_identity_and_area(self):
        """Caught by `product/tests/test_parcel_area_units.py` while shipping this.

        The first cut printed the parcel identity line only beside a drawing, so a parcel whose
        boundary is not yet recorded lost its ACREAGE from §E — the one number CCOF asks to see
        annotated on the map, and the subject of the acres-vs-hectares regression this page
        already carries a test for. Absence of geometry must not take the facts with it.
        """
        import io

        import pdfplumber

        self.parcel.polygon = None
        self.parcel.save(update_fields=["polygon"])
        with pdfplumber.open(io.BytesIO(self._pdf())) as pdf:
            text = " ".join(page.extract_text() or "" for page in pdf.pages)
        self.assertIn("Home Field East", text)
        self.assertIn("acres", text)
        self.assertIn("No field-boundary geometry", text.replace("\n", " "))

    def test_the_module_offers_an_upload(self):
        keys = {q.key for page in PARCEL_APPLICATION.pages for q in page.questions}
        self.assertIn("map_upload", keys)

    def test_the_packet_ships_an_uploaded_map(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from certifications.services.osp_module_pdf import generate_osp_packet
        from documents.models import GeneratedDocument

        GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=self.parcel,
            folder="organic_system_plan",
            source="upload",
            title="Home Field East map",
            file=SimpleUploadedFile("map.png", b"not-a-real-png", content_type="image/png"),
            linked_section=PARCEL_MAP_SECTION,
        )
        with zipfile.ZipFile(__import__("io").BytesIO(generate_osp_packet(self.osp))) as zf:
            names = zf.namelist()
        maps = [n for n in names if n.startswith("parcels/maps/")]
        self.assertTrue(maps, f"the packet must carry the uploaded map; got {names}")

    def test_a_parcel_with_an_uploaded_map_counts_as_mapped(self):
        # The SECOND definition of "has a map" — the module-completion service. Both read the
        # same two sources, so a module cannot report complete while the packet says no map.
        from django.core.files.uploadedfile import SimpleUploadedFile

        from documents.models import GeneratedDocument
        from product.services.parcel_application_status import parcel_application_status

        self.parcel.polygon = None
        self.parcel.save(update_fields=["polygon"])
        self.assertIn("map", parcel_application_status(self.parcel)["missing"])

        GeneratedDocument.objects.create(
            establishment=self.est,
            parcel=self.parcel,
            folder="organic_system_plan",
            source="upload",
            title="map",
            file=SimpleUploadedFile("map.png", b"x", content_type="image/png"),
            linked_section=PARCEL_MAP_SECTION,
        )
        self.assertNotIn("map", parcel_application_status(self.parcel)["missing"])
