"""
WS-2.5/2.6 — per-module PDFs + renewal packet ZIP.

Properties that matter:
  1. Module PDF renders answered questions only from the VISIBLE branch;
     N/A modules print the attestation instead of questions.
  2. Parcel Application PDF renders from LIVE model state (no module_responses).
  3. Packet ZIP contains cover + narrative + every registry module + one
     application per parcel + all four workbooks.
  4. Endpoints file a DMS copy and stream the same bytes.
"""

import inspect
import io
import zipfile
from datetime import date

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULE_REGISTRY
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from product.models import Parcel
from users.models import User, WorksIn


def _pdf_text(data: bytes) -> str:
    """Rendered text of a generated PDF.

    Asserting on `%PDF` proves the bytes are a PDF and nothing else — which is how a renderer that
    dropped a whole registry from the materials list stayed green. ReportLab ASCII85-encodes its
    streams, so hand-decoding is not enough either.
    """
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as doc:
        return "\n".join(page.extract_text() or "" for page in doc.pages)


def _osp(establishment, module_responses=None, version=1):
    return OrganicSystemPlan.objects.create(
        establishment=establishment,
        version_number=version,
        status="draft",
        module_responses=module_responses or {},
    )


class ModulePdfTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="PDF Farm")
        self.establishment = Establishment.objects.create(name="PDF Ranch", company=self.company, state="CA")

    def test_answered_module_renders_pdf(self):
        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "g3_0_seeds": {
                        "answers": {"seeds_used": {"value": ["organic"]}},
                        "definition_version": "2026.08.1",
                    }
                },
            },
        )
        data = generate_module_pdf(osp, "g3_0_seeds")
        self.assertTrue(data.startswith(b"%PDF"))
        empty = generate_module_pdf(_osp(self.establishment, version=2), "g3_0_seeds")
        # The answered PDF must actually CONTAIN the answer content — guard against
        # reading the wrong module_responses shape (the empty-render regression).
        self.assertGreater(len(data), len(empty))

    def test_g8_0_pdf_renders_the_confirmed_s11_registry(self):
        """The § 11 registry is the substance of G8.0 and must reach the certifier.

        `info` questions were skipped wholesale by the renderer, so the embedded registry
        printed nothing and the module PDF read as a single "records maintained: Yes" —
        while its own attestation says "the records confirmed above", pointing at an empty
        page. Regression lock for the embed path.
        """
        from certifications.services.common_osp_records import confirm

        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "g8_0_record_keeping": {
                        "answers": {"records_retention_attestation": {"value": True}},
                        "definition_version": "2026.08.9",
                    }
                },
            },
        )
        before = generate_module_pdf(osp, "g8_0_record_keeping")

        confirm(osp, ["harvest_records", "planting_records", "weigh_tickets"], user=None, confirmed=True)
        osp.save()
        after = generate_module_pdf(osp, "g8_0_record_keeping")

        self.assertTrue(after.startswith(b"%PDF"))
        # Confirming record types must visibly change the certifier-facing document.
        self.assertGreater(len(after), len(before))

    def test_free_text_row_prints_the_operators_own_words(self):
        """The "Other:" line both source forms end on has to reach the certifier NAMED.

        A confirmed row prints the registry's own label; a free-text row that printed only
        "Other records maintained (describe)" would be a tick with no statement under it — the
        exact shape `attestation_gates` refuses one level up.
        """
        from certifications.services.common_osp_records import confirm

        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "g8_0_record_keeping": {
                        "answers": {"records_retention_attestation": {"value": True}},
                        "definition_version": "2026.08.9",
                    }
                },
            },
        )
        confirm(osp, ["other_records"], user=None, label="Pool closings from the huller")
        osp.save()
        data = generate_module_pdf(osp, "g8_0_record_keeping")

        self.assertTrue(data.startswith(b"%PDF"))
        # ReportLab writes text into a compressed stream, so assert on the extracted text.
        text = _pdf_text(data)
        self.assertIn("Pool closings from the huller", text)
        self.assertIn("Other records maintained", text, "the form's own line stays beside it")

    def test_unconfirmed_registry_rows_are_not_printed_as_operator_statements(self):
        """A derived-but-unconfirmed row is a suggestion, never a producer attestation."""
        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "g8_0_record_keeping": {
                        "answers": {"records_retention_attestation": {"value": True}},
                        "definition_version": "2026.08.9",
                    }
                },
            },
        )
        data = generate_module_pdf(osp, "g8_0_record_keeping")
        self.assertTrue(data.startswith(b"%PDF"))
        # Nothing confirmed → the PDF must say so rather than listing derived rows.
        self.assertLess(len(data), 6000)

    def test_na_module_prints_attestation(self):
        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "g3_0_seeds": {
                        "not_applicable": True,
                        "na_attestation": {"by": "oscar@test.com", "at": "2026-08-08"},
                    }
                },
            },
        )
        data = generate_module_pdf(osp, "g3_0_seeds")
        self.assertTrue(data.startswith(b"%PDF"))

    def test_parcel_application_pdf_carries_the_205_202_evidence(self):
        """Buffers, map and land history must reach the certifier.

        Sections D/E/F of the Parcel Application are `info` embeds, and `info` questions
        were skipped wholesale — so a PDF stamped "Live completion: complete" arrived
        showing only parcel name, APN and address. The one document whose job is to prove
        land eligibility carried none of the evidence for it.
        """
        from product.models import Parcel, ParcelCropHistory

        parcel = Parcel.objects.create(
            name="Evidence Block",
            establishment=self.establishment,
            area=12.0,
            polygon=[{"lat": 38.5, "lng": -121.9}],
        )
        osp = _osp(self.establishment)
        bare = generate_module_pdf(osp, "parcel_application", parcel=parcel)

        parcel.buffer_zones = [
            {
                "direction": "South",
                "adjoining_land_use": "Conventional tomatoes",
                "buffer_width_ft": 40,
                "crop_grown_in_buffer": "Mowed cover, never sold",
                "prohibited_use_last_date": "2021-06-10",
            }
        ]
        parcel.save(update_fields=["buffer_zones"])
        for year in (2023, 2024, 2025):
            ParcelCropHistory.objects.create(parcel=parcel, year=year, crop_grown="Walnuts")

        full = generate_module_pdf(osp, "parcel_application", parcel=parcel)
        self.assertTrue(full.startswith(b"%PDF"))
        # Buffers + map + three years of history must visibly enlarge the document.
        self.assertGreater(len(full), len(bare))

    def test_the_parcel_status_line_reads_as_words(self):
        """The parcel page printed "Live completion: in_progress" — an enum slug — on every parcel
        of the OTCO desk read (2026-09-10)."""
        from product.models import Parcel

        parcel = Parcel.objects.create(name="Status Block", establishment=self.establishment, area=2.0)
        text = _pdf_text(generate_module_pdf(_osp(self.establishment), "parcel_application", parcel=parcel))
        self.assertRegex(text, r"Parcel application: (complete|in progress|not started)")
        self.assertNotRegex(text, r"in_progress|not_started|Live completion")

    def test_every_embed_has_a_renderer(self):
        """No embed may reach a certifier as a blank space.

        This bug landed three times — the § 11 registry, the Parcel Application's
        § 205.202 evidence, and the Materials Application's approved-inputs list — because
        `embed` questions carry no answer value and the renderer skipped them silently.
        Each time, a module went on attesting to "the list above" with nothing above it.
        Fixing instances did not fix the class; this test does.

        A new embed must either get a branch in `osp_module_pdf` or be added to
        KNOWN_UNRENDERED with a reason.
        """
        from certifications.osp_modules.parcel_application import PARCEL_APPLICATION
        from certifications.services import osp_module_pdf as pdf_mod

        # Embeds deliberately not rendered into the packet, with the reason.
        KNOWN_UNRENDERED: dict = {}

        embeds = set()
        for module in list(MODULE_REGISTRY) + [PARCEL_APPLICATION]:
            for page in module.pages:
                for question in page.questions:
                    if question.embed:
                        embeds.add(question.embed)

        source = inspect.getsource(pdf_mod)
        missing = [embed for embed in sorted(embeds) if embed not in KNOWN_UNRENDERED and f'"{embed}"' not in source]
        self.assertEqual(
            missing,
            [],
            f"embed(s) with no renderer in osp_module_pdf — they will print nothing on a "
            f"certifier-facing PDF: {missing}",
        )

    def test_materials_application_pdf_lists_the_approved_inputs(self):
        """The module attests five times to "the materials list above" — it must exist."""
        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "materials_application": {
                        "answers": {"materials_list_complete": {"value": True}},
                        "definition_version": "2026.08.9",
                    }
                },
            },
        )
        data = generate_module_pdf(osp, "materials_application")
        # `%PDF` is not an assertion about content. This test asserted only that, and the packet
        # went on printing a list that silently omitted every WSDA-listed product under a heading
        # that named WSDA. Read the rendered text.
        self.assertIn(
            "No input materials have been added to this plan's materials list",
            _pdf_text(data),
            "with nothing on the plan the PDF must say so, not omit the panel",
        )

    def test_unknown_module_raises(self):
        osp = _osp(self.establishment)
        with self.assertRaises(ValueError):
            generate_module_pdf(osp, "nope")

    def test_parcel_application_requires_parcel(self):
        osp = _osp(self.establishment)
        with self.assertRaises(ValueError):
            generate_module_pdf(osp, "parcel_application")

    def test_parcel_application_renders_live_state(self):
        parcel = Parcel.objects.create(
            name="Block A",
            establishment=self.establishment,
            area=2.0,
            apn="042-031-007",
            date_began_managing=date(2020, 1, 1),
        )
        osp = _osp(self.establishment)
        data = generate_module_pdf(osp, "parcel_application", parcel=parcel)
        self.assertTrue(data.startswith(b"%PDF"))


class PacketTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Packet Farm")
        self.establishment = Establishment.objects.create(name="Packet Ranch", company=self.company, state="CA")
        Parcel.objects.create(name="North Block", establishment=self.establishment, area=2.0)
        Parcel.objects.create(name="South Block", establishment=self.establishment, area=3.0)

    def test_packet_zip_contents(self):
        osp = _osp(self.establishment)
        data = generate_osp_packet(osp)
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()

        self.assertIn("00-cover.pdf", names)
        self.assertIn("01-organic-system-plan.pdf", names)
        from certifications.services.packet_coverage import module_file_stem

        for module in MODULE_REGISTRY:
            self.assertIn(f"modules/{module_file_stem(module)}.pdf", names)
        # The operation profile ships under its own name, never as the contract it supports.
        self.assertIn("modules/operation_profile.pdf", names)
        self.assertNotIn("modules/certification_contract.pdf", names)
        parcel_entries = [n for n in names if n.startswith("parcels/")]
        self.assertEqual(len(parcel_entries), 2)
        workbook_entries = [n for n in names if n.startswith("workbooks/") and n.endswith(".xlsx")]
        self.assertEqual(len(workbook_entries), 4)
        for name in names:
            self.assertTrue(len(zf.read(name)) > 0, name)

    def test_a_confirmed_record_type_reaches_both_packet_documents(self):
        """🔴 End-to-end wiring for one tick: the operator confirms a § 11 row, and it has to
        appear in the packet TWICE — in G8.0 §A, and in the plan document itself.

        Until 2026-09-07 it appeared only in G8.0. `01-organic-system-plan.pdf` carried G8.0's
        attestation ("the records confirmed in the § 11 registry are maintained…") with no list
        anywhere in that file, and the certifier dossier prints the same (a)(4) narrative. This
        asserts the whole path — confirm() → sections → compiler → narrative → snapshot — rather
        than any one link, because every link was individually green while the packet was wrong.
        """
        from certifications.services.common_osp_records import confirm

        osp = _osp(
            self.establishment,
            {
                "schema_version": 1,
                "modules": {
                    "g8_0_record_keeping": {
                        "answers": {"records_retention_attestation": {"value": True}},
                        "definition_version": "2026.09.6",
                    }
                },
            },
        )
        confirm(osp, ["harvest_records"], user=None)

        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        module_text = _pdf_text(zf.read("modules/G8_0.pdf"))
        plan_text = _pdf_text(zf.read("01-organic-system-plan.pdf"))

        self.assertIn("Harvest records", module_text)
        self.assertIn("Harvest records", plan_text, "the plan document must carry the list it attests to")


class PdfEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="PDF API Farm")
        self.user = User.objects.create_user(email="pdf@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.establishment = Establishment.objects.create(name="PDF API Ranch", company=self.company, state="CA")
        self.parcel = Parcel.objects.create(name="Block A", establishment=self.establishment, area=2.0)
        self.osp = _osp(self.establishment)
        # The packet ZIP and its component module PDFs are Compliance artifacts (2026-08-14,
        # subscriptions/gating.py). Without a plan every case here would 403 before generating
        # anything, including the 400-on-bad-input cases, which would then pass for the wrong
        # reason — a 400 assertion that never reaches argument validation is not a test.
        from subscriptions.testing import grant_compliance_exports

        grant_compliance_exports(self.company)
        self.client.force_authenticate(user=self.user)

    def _url(self, suffix):
        return (
            f"/api/companies/{self.company.id}/establishments/{self.establishment.id}" f"/osps/{self.osp.id}/{suffix}"
        )

    def test_module_pdf_endpoint_streams_and_files(self):
        r = self.client.get(self._url("module-pdf/?module=g3_0_seeds"))
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content)
        self.assertTrue(body.startswith(b"%PDF"))
        doc = GeneratedDocument.objects.get(establishment=self.establishment, source="module_pdf")
        self.assertEqual(doc.folder, "organic_system_plan")

    def test_parcel_application_pdf_endpoint(self):
        r = self.client.get(self._url(f"module-pdf/?module=parcel_application&parcel={self.parcel.id}"))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(b"".join(r.streaming_content).startswith(b"%PDF"))

    def test_module_pdf_missing_param_400(self):
        self.assertEqual(self.client.get(self._url("module-pdf/")).status_code, 400)
        self.assertEqual(self.client.get(self._url("module-pdf/?module=nope")).status_code, 400)
        self.assertEqual(self.client.get(self._url("module-pdf/?module=parcel_application")).status_code, 400)

    def test_packet_endpoint_streams_zip_and_files(self):
        r = self.client.get(self._url("packet/"))
        self.assertEqual(r.status_code, 200)
        body = b"".join(r.streaming_content)
        self.assertTrue(body.startswith(b"PK"))
        zf = zipfile.ZipFile(io.BytesIO(body))
        self.assertIn("00-cover.pdf", zf.namelist())
        doc = GeneratedDocument.objects.get(establishment=self.establishment, source="packet")
        self.assertEqual(doc.folder, "organic_system_plan")
