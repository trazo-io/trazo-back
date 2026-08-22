"""A packet built from FABRICATED records must say so, on every page and in every format.

WHAT WENT WRONG
---------------
Until 2026-08-21 nothing Trazo exported carried any marking of its own provenance. A
certifier packet generated from Calapooia Bend Farm — an operation invented for a pilot
rehearsal — was not merely similar to a real grower's organic records. It was the same kind
of document: same cover, same CFR citations, same handler certificates, same § 205.103
audit trail, no watermark, no notice, nothing.

WHY IT MATTERED
---------------
These artifacts are made to be handed over. The plan from October is to put them in front of
independent inspectors and certifier reviewers, and § 5 of the October kit calls the packet
itself the pitch. Compliance documents get forwarded, excerpted, printed a section at a time
and filed. An unmarked synthetic packet is a document that can be mistaken for a real
operation's legal records — and for the PUR export, for a pesticide-use report filed with a
county agricultural commissioner.

THE TWO DIRECTIONS ARE NOT SYMMETRIC
------------------------------------
`test_real_farm_packet_is_untouched` is the more important of the first two tests. Failing to
mark a synthetic packet restores the old status quo; marking a REAL one tells a certifier
that a legitimate operation's records are a demonstration, which invites them to reject the
farmer's filing. `Establishment.is_demo` therefore defaults to False and `is_specimen()`
resolves anything unreadable to False.

AND WHY THE LAST TEST WALKS THE TREE
------------------------------------
The dominant defect class in this codebase is "fixed on the audited surface, alive on its
sibling" — 6 of the 9 defects in the two-farm certifier sweep, the annotation rule that had
to be repeated in five places, the CSV that never got the PDF's state gate. A hand-typed
list of export surfaces is the same mistake one level up: the blockchain-copy guard was a
hand-typed six-name tuple and so never saw `subscriptions/templates`, where three live
emails still sold a withdrawn add-on. So `test_every_export_surface_consults_the_authority`
DISCOVERS surfaces by looking for what actually builds a document, and a new exporter fails
it until it is wired.
"""

import ast
import io
import re
from datetime import timedelta
from pathlib import Path

from django.test import TestCase
from django.utils import timezone

from carbon.models import CropType
from common.specimen import SPECIMEN_TITLE, is_specimen
from company.models import Company, Establishment
from history.models import History
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _page_texts(pdf_bytes):
    """Text of each page, in order. Empty list if pdfminer is unavailable."""
    from pdfminer.high_level import extract_text

    buf = io.BytesIO(pdf_bytes)
    pages = []
    for index in range(200):
        buf.seek(0)
        try:
            text = extract_text(buf, page_numbers=[index])
        except Exception:
            break
        if not text:
            break
        pages.append(text)
    return pages


class _PacketFixture(TestCase):
    """Minimal but real: the exporter is driven end to end, never stubbed."""

    def _make_farm(self, name, is_demo):
        user = User.objects.create_user(email=f"{name.lower().replace(' ', '')}@test.com", password="x")
        company = Company.objects.create(name=f"{name} Co")
        est = Establishment.objects.create(name=name, company=company, is_demo=is_demo)
        parcel = Parcel.objects.create(name="Block A", establishment=est, area=2.0)
        crop = CropType.objects.create(
            name="Blueberries",
            slug=f"blueberries-{name.lower().replace(' ', '-')}",
            category="berry",
            description="Berry",
            typical_farm_size="10-40 ha",
            growing_season="Mar-Aug",
            harvest_season="Jun-Aug",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        product = Product.objects.create(name="Blueberries")
        history = History.objects.create(
            parcel=parcel,
            product=product,
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
        )
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        return est, history


class SpecimenPacketTests(_PacketFixture):
    def test_fabricated_farm_is_marked_on_every_page(self):
        est, history = self._make_farm("Specimen Farm", is_demo=True)
        self.assertTrue(is_specimen(est))

        buffer = AuditExportService(history, certification_type="usda_organic").generate_pdf()
        pdf = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer

        pages = _page_texts(pdf)
        self.assertGreater(len(pages), 1, "fixture produced a single page; the per-page claim is vacuous")

        unmarked = [i for i, text in enumerate(pages, 1) if "SPECIMEN" not in text]
        self.assertEqual(
            unmarked,
            [],
            f"pages {unmarked} of {len(pages)} carry no specimen mark. A cover-only marking is "
            "the failure this test exists for: packets are excerpted and printed a section at "
            "a time, so the mark must survive someone printing one page on its own.",
        )
        self.assertIn(SPECIMEN_TITLE, pages[0], "cover page is missing the written notice")

    def test_real_farm_packet_is_untouched(self):
        """The safety property, and the reason `is_demo` defaults to False.

        Stamping SPECIMEN on a real operation's § 205.103 records would invite a certifier to
        reject a legitimate filing. That is a worse outcome than the bug this whole change
        fixes, so it gets its own test rather than riding along as an assertion above.
        """
        est, history = self._make_farm("Real Farm", is_demo=False)
        self.assertFalse(is_specimen(est))

        buffer = AuditExportService(history, certification_type="usda_organic").generate_pdf()
        pdf = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer

        pages = _page_texts(pdf)
        self.assertGreater(len(pages), 0)
        marked = [i for i, text in enumerate(pages, 1) if "SPECIMEN" in text or "FABRICATED" in text]
        self.assertEqual(marked, [], f"a real farm's packet was marked as a specimen on pages {marked}")

    def test_csv_twin_carries_the_mark(self):
        """The PDF and the CSV travel separately, so the rule has to hold in both.

        This is the documented shape of the bug: on 2026-08-20 the CSV never got the PDF's
        state gate. Marking one format and not the other reproduces it exactly.
        """
        est, history = self._make_farm("Csv Specimen Farm", is_demo=True)
        buffer = AuditExportService(history, certification_type="usda_organic").generate_csv()
        raw = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw

        self.assertIn(SPECIMEN_TITLE, text)
        first_line = text.splitlines()[0]
        self.assertIn(
            SPECIMEN_TITLE,
            first_line,
            "the notice must be the FIRST row — below the header row it can be scrolled past",
        )

    def test_real_farm_csv_is_untouched(self):
        est, history = self._make_farm("Csv Real Farm", is_demo=False)
        buffer = AuditExportService(history, certification_type="usda_organic").generate_csv()
        raw = buffer.getvalue() if hasattr(buffer, "getvalue") else buffer
        text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
        self.assertNotIn("SPECIMEN", text)
        self.assertNotIn("FABRICATED", text)


class SpecimenSurfaceCoverageTests(TestCase):
    """Every module that BUILDS a document must consult `common.specimen`.

    Discovered, never enumerated by hand. Add an exporter and this test fails until it is
    wired — which is the only way to stop the sibling-surface class from reappearing here.
    """

    #: Modules that build a document but legitimately have no operation to mark, with the
    #: reason. Each entry is checked to still EXIST, so a rename cannot leave a stale pass.
    EXEMPT = {
        "carbon/services/certificate.py": (
            "Carbon-offset certificate keyed to a CarbonOffsetPurchase, which reaches no "
            "Establishment. Dormant besides: BLOCKCHAIN_ENABLED is False and the add-on is "
            "withdrawn, so it builds nothing today."
        ),
    }

    #: 2026-08-21 — this started as PDF + CSV markers only, and that blind spot was live for
    #: about ten minutes: the OSP renewal packet is a ZIP whose Common OSP attachments are
    #: openpyxl WORKBOOKS, so the guard would have passed green while an entire document
    #: format exported unmarked. The workbook is also the file a certifier is likeliest to
    #: open and keep, since it is the one they are meant to complete.
    #:
    #: Regexes, not substrings, because the first widening immediately produced a FALSE
    #: positive — `import_usda_organic_data.py` calls `openpyxl.load_workbook(read_only=True)`
    #: to INGEST the USDA Organic Integrity list. A guard that cannot tell reading from
    #: writing cries wolf, and a guard that cries wolf gets an exemption entry, which is how
    #: a real surface eventually hides behind a stale excuse.
    #:
    #: The workbook pattern matches the CONSTRUCTOR (`Workbook(`, `XLWorkbook(`) and misses
    #: `load_workbook(` for free, because openpyxl's reader is lowercase. An earlier draft
    #: wrote `(?<!load_)\bWorkbook\(` and passed — but `\b` refuses to match inside
    #: `XLWorkbook(`, which is exactly how `common_osp_workbooks.py` imports it. That version
    #: was therefore detecting the file by COINCIDENCE, via its own unrelated `Workbook`
    #: dataclass, and would have missed any new module that aliased the import. Checked
    #: against both real files and a synthetic alias before being trusted.
    #:
    #: Add a pattern here the moment the product learns to emit another document format.
    BUILDER_MARKERS = (
        r"SimpleDocTemplate",
        r"BaseDocTemplate",
        r"csv\.writer",
        r"DictWriter",
        r"\w*Workbook\(",
    )

    def _document_builders(self):
        found = []
        for path in sorted(BACKEND_ROOT.rglob("*.py")):
            rel = path.relative_to(BACKEND_ROOT).as_posix()
            if any(part in rel for part in ("/tests/", "/migrations/", ".venv/", "__pycache__")):
                continue
            # Loose scratch scripts at the repo root are dev tooling, not product surfaces.
            if "/" not in rel and rel.startswith("test_"):
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(re.search(marker, source) for marker in self.BUILDER_MARKERS):
                found.append((rel, source))
        return found

    def test_exemptions_still_point_at_real_files(self):
        for rel in self.EXEMPT:
            self.assertTrue(
                (BACKEND_ROOT / rel).exists(),
                f"{rel} is exempted but no longer exists — a rename would otherwise leave a "
                "stale exemption that silently excuses a live surface.",
            )

    def test_every_export_surface_consults_the_authority(self):
        builders = self._document_builders()
        self.assertGreaterEqual(
            len(builders),
            5,
            "discovery found almost nothing; the walk is broken and this guard would pass " "vacuously",
        )

        unwired = []
        for rel, source in builders:
            if rel in self.EXEMPT:
                continue
            if "common.specimen" not in source:
                unwired.append(rel)

        self.assertEqual(
            unwired,
            [],
            "these modules build an exportable document without consulting common.specimen, "
            f"so a fabricated operation's records export unmarked through them: {unwired}",
        )

    def test_the_authority_never_guesses_toward_marking(self):
        """`is_specimen` must resolve the unknown to False, in every branch.

        A real operation's packet stamped SPECIMEN is worse than the bug being fixed, so this
        pins the direction rather than trusting the docstring.
        """
        self.assertFalse(is_specimen(None))
        self.assertFalse(is_specimen(object()))

        class Broken:
            @property
            def is_demo(self):
                raise RuntimeError("database gone")

        self.assertFalse(is_specimen(Broken()))

    def test_watermark_is_drawn_before_content_not_after(self):
        """Regression fence on placement, not just presence.

        The wash is legible only because ReportLab fires page callbacks at page BEGIN, so it
        lands UNDER the flowables. If someone moves the drawing to an afterPage hook the mark
        would cover the very records a reviewer opened the packet to read — still 'present',
        and useless. Assert the wiring that guarantees ordering.
        """
        source = (BACKEND_ROOT / "history/services/audit_export_service.py").read_text()
        tree = ast.parse(source)
        build_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "build"
        ]
        self.assertTrue(build_calls, "no doc.build call found — the file has been restructured")
        kwargs = {kw.arg for call in build_calls for kw in call.keywords}
        self.assertIn("onFirstPage", kwargs)
        self.assertIn("onLaterPages", kwargs)
        self.assertNotIn(
            "onPage",
            re.sub(r"#.*", "", source),
            "afterPage/onPage drawing would put the watermark over the content",
        )
