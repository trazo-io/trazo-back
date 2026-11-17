"""
Phase 4 / §E-2 + §E-3 — lab analysis and micronutrients, shipped as one unit.

They ship together because 7 CFR 205.601(j)(7) permits synthetic micronutrients ONLY where a
soil or plant-tissue deficiency is documented. Shipping the micronutrient fields alone would let
a farmer produce a zinc application with nowhere to record the analysis that justifies it — a
document that reads as unsupported at inspection. Shipping the lab fields alone leaves the
UC Davis 2024 organic-almond operations (zinc sulfate 10 lb/ac, 20% boron at 2 lb/ac foliar
post-harvest) with no home.

The second defect fixed here is quieter: the soil form has always WRITTEN lab results into the
`test_results` JSONField, but nothing read them back by name. The display registry resolves a
field from the top level or from `extra_data` only, so every lab value a farmer ever typed was
write-only — collected, stored, and shown on no surface. The read serializer now flattens the
JSON into `lab_*` fields.
"""

from pathlib import Path

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, Production, SoilManagementEvent
from history.serializers import SoilManagementEventSerializer
from product.models import Parcel, Product
from users.models import User


class LabAnalysisBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="lab@test.com", password="x")
        company = Company.objects.create(name="Lab Farm")
        establishment = Establishment.objects.create(name="LF1", company=company, state="CA")
        parcel = Parcel.objects.create(name="lab-parcel", establishment=establishment, area=44.5)
        product = Product.objects.create(name="Almond")
        self.history = Production.objects.create(
            name="Lab Production",
            start_date=timezone.now(),
            product=product,
            parcel=parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )

    def _lab_event(self, matrix="leaf", when=None, **results):
        return SoilManagementEvent.objects.create(
            history=self.history,
            type="LA",
            date=when or timezone.now(),
            description="July leaf sample",
            area_covered=44.5,
            area_unit="acres",
            sample_matrix=matrix,
            test_results=results or None,
        )


class LabAnalysisModelTests(LabAnalysisBase):
    def test_la_is_a_real_subtype(self):
        codes = dict(SoilManagementEvent._meta.get_field("type").choices)
        self.assertIn("LA", codes)

    def test_every_uc_davis_matrix_is_selectable(self):
        """Leaf in July, hull at harvest, compost per delivery, water for irrigation testing."""
        codes = dict(SoilManagementEvent._meta.get_field("sample_matrix").choices)
        for matrix in ("soil", "leaf", "petiole", "hull", "compost", "water"):
            self.assertIn(matrix, codes)

    def test_a_lab_analysis_without_a_matrix_is_rejected(self):
        event = SoilManagementEvent(
            history=self.history,
            type="LA",
            date=timezone.now(),
            description="Sample sent",
            area_covered=10.0,
        )
        with self.assertRaises(ValidationError) as ctx:
            event.clean()
        self.assertIn("sample_matrix", ctx.exception.message_dict)

    def test_other_subtypes_do_not_require_a_matrix(self):
        event = SoilManagementEvent(
            history=self.history,
            type="TI",
            date=timezone.now(),
            description="Tillage pass",
            area_covered=10.0,
        )
        event.clean()  # must not raise

    def test_results_may_arrive_after_the_sample_is_logged(self):
        """A farmer logs the sample the day it ships; the report comes back weeks later."""
        event = self._lab_event()
        event.clean()
        self.assertIsNone(event.test_results)


class LabResultFlatteningTests(LabAnalysisBase):
    """The write-only defect: results were stored but no surface could read them."""

    def _serialized(self, event):
        return SoilManagementEventSerializer(event).data

    def test_lab_values_are_readable_by_name(self):
        event = self._lab_event(
            lab_name="A&L Western Labs",
            sample_id="25-04812",
            report_date="2026-07-18",
            nitrogen=18,
            phosphorus=32,
            potassium=210,
            cec=14.5,
        )
        data = self._serialized(event)
        self.assertEqual(data["lab_name"], "A&L Western Labs")
        self.assertEqual(data["lab_sample_id"], "25-04812")
        self.assertEqual(data["lab_report_date"], "2026-07-18")
        self.assertEqual(data["lab_nitrogen"], 18)
        self.assertEqual(data["lab_phosphorus"], 32)
        self.assertEqual(data["lab_potassium"], 210)
        self.assertEqual(data["lab_cec"], 14.5)

    def test_micronutrient_results_are_readable_by_name(self):
        data = self._serialized(self._lab_event(zinc_ppm=0.8, boron_ppm=0.4, manganese_ppm=6.5, iron_ppm=12))
        self.assertEqual(data["lab_zinc_ppm"], 0.8)
        self.assertEqual(data["lab_boron_ppm"], 0.4)
        self.assertEqual(data["lab_manganese_ppm"], 6.5)
        self.assertEqual(data["lab_iron_ppm"], 12)

    def test_historical_soil_tests_flatten_too(self):
        """ST rows written before §E-2 carry the same JSON keys and must read back."""
        legacy = SoilManagementEvent.objects.create(
            history=self.history,
            type="ST",
            date=timezone.now(),
            description="Soil test, three depths",
            area_covered=44.5,
            test_results={"lab_name": "Dellavalle Laboratory", "nitrogen": 22},
        )
        data = self._serialized(legacy)
        self.assertEqual(data["lab_name"], "Dellavalle Laboratory")
        self.assertEqual(data["lab_nitrogen"], 22)

    def test_absent_results_read_as_none_not_an_error(self):
        data = self._serialized(self._lab_event())
        self.assertIsNone(data["lab_name"])
        self.assertIsNone(data["lab_zinc_ppm"])

    def test_a_non_dict_test_results_does_not_raise(self):
        """Defensive: the JSONField accepts any JSON, including a list from an old import."""
        event = self._lab_event()
        SoilManagementEvent.objects.filter(pk=event.pk).update(test_results=["legacy", "rows"])
        event.refresh_from_db()
        self.assertIsNone(self._serialized(event)["lab_name"])

    def test_sample_matrix_round_trips(self):
        self.assertEqual(self._serialized(self._lab_event(matrix="hull"))["sample_matrix"], "hull")


class MicronutrientModelTests(LabAnalysisBase):
    def test_uc_davis_micronutrients_are_selectable(self):
        codes = dict(ChemicalEvent._meta.get_field("micronutrient_type").choices)
        for nutrient in ("zinc", "boron", "manganese", "iron", "copper", "calcium", "magnesium", "sulfur"):
            self.assertIn(nutrient, codes)

    def test_a_zinc_application_stores_its_rate(self):
        event = ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=timezone.now(),
            description="Zinc sulfate, post-harvest foliar",
            commercial_name="Zinc Sulfate 36%",
            micronutrient_type="zinc",
            micronutrient_rate=10,
            micronutrient_rate_unit="lb/ac",
        )
        event.refresh_from_db()
        self.assertEqual(event.get_micronutrient_type_display(), "Zinc (Zn)")
        self.assertEqual(float(event.micronutrient_rate), 10.0)


class MicronutrientPdfTests(LabAnalysisBase):
    """The application and the analysis must land on the same page."""

    def _chemicals_text(self):
        from history.services.audit_export_service import AuditExportService

        out = []
        for el in AuditExportService(self.history, certification_type="organic")._build_chemical_log():
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    if getattr(cell, "text", None):
                        out.append(cell.text)
            if getattr(el, "text", None):
                out.append(el.text)
        return " ".join(out)

    def _soil_text(self):
        from history.services.audit_export_service import AuditExportService

        out = []
        for el in AuditExportService(self.history, certification_type="organic")._build_soil_section():
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    if getattr(cell, "text", None):
                        out.append(cell.text)
            if getattr(el, "text", None):
                out.append(el.text)
        return " ".join(out)

    def _zinc_application(self, when=None):
        return ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=when or timezone.now(),
            description="Zinc sulfate, post-harvest foliar",
            commercial_name="Zinc Sulfate 36%",
            micronutrient_type="zinc",
            micronutrient_rate=10,
            micronutrient_rate_unit="lb/ac",
        )

    def test_an_unsupported_application_is_flagged_for_review(self):
        self._zinc_application()
        text = self._chemicals_text()
        self.assertIn("Zinc (Zn)", text)
        self.assertIn("REVIEW", text)
        self.assertIn("205.601(j)(7)", text)

    def test_a_prior_lab_result_documents_the_application(self):
        now = timezone.now()
        self._lab_event(matrix="leaf", when=now - timezone.timedelta(days=30), zinc_ppm=0.8)
        self._zinc_application(when=now)
        text = self._chemicals_text()
        # A value on file, not a finding that the crop was short: "Result on file", never "DOCUMENTED".
        self.assertIn("Result on file: 0.8 ppm, leaf", text)
        self.assertNotIn("DOCUMENTED", text)
        self.assertNotIn("REVIEW — no prior lab result on file", text)

    def test_a_later_lab_result_does_not_justify_an_earlier_application(self):
        """Evidence measured after the fact is not the basis the rule asks for."""
        now = timezone.now()
        self._zinc_application(when=now - timezone.timedelta(days=30))
        self._lab_event(matrix="leaf", when=now, zinc_ppm=0.8)
        self.assertIn("REVIEW — no prior lab result on file", self._chemicals_text())

    def test_a_boron_result_does_not_justify_a_zinc_application(self):
        now = timezone.now()
        self._lab_event(matrix="leaf", when=now - timezone.timedelta(days=30), boron_ppm=0.4)
        self._zinc_application(when=now)
        self.assertIn("REVIEW — no prior lab result on file", self._chemicals_text())

    def test_a_secondary_macronutrient_is_not_flagged_under_j6(self):
        """Calcium, magnesium and sulfur are not § 205.601(j)(7) micronutrients.

        (j)(7)(i) covers soluble boron; (j)(7)(ii) covers the sulfates/carbonates/oxides/
        silicates of zinc, copper, iron, manganese, molybdenum, selenium and cobalt. Gypsum and
        elemental sulfur are permitted on other grounds. Flagging them REVIEW under (j)(7) would
        cite the wrong rule at an inspector — and a document that cries wolf on a compliant
        application devalues every real flag beside it.
        """
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=timezone.now(),
            description="Gypsum, soil applied",
            commercial_name="Agricultural Gypsum",
            micronutrient_type="calcium",
            micronutrient_rate=500,
            micronutrient_rate_unit="lb/ac",
        )
        text = self._chemicals_text()
        self.assertIn("Calcium (Ca)", text, "the application should still be listed")
        self.assertNotIn("REVIEW — no prior lab result on file", text)
        self.assertIn("not a § 205.601(j)(7) micronutrient", text)

    def test_an_out_of_scope_application_is_left_out_of_the_counts(self):
        """A gypsum row must not pad the "all supported" tally either."""
        now = timezone.now()
        self._lab_event(matrix="leaf", when=now - timezone.timedelta(days=30), zinc_ppm=0.8)
        self._zinc_application(when=now)
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=now,
            description="Gypsum",
            commercial_name="Agricultural Gypsum",
            micronutrient_type="calcium",
        )
        # Two applications on file, but only the zinc one is governed by (j)(7).
        self.assertIn("All 1 § 205.601(j)(7) micronutrient application(s) are supported", self._chemicals_text())

    def test_an_unrecognised_micronutrient_stays_in_scope(self):
        """ "Other" may be molybdenum, selenium or cobalt — all named in (j)(7)(ii)."""
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=timezone.now(),
            description="Sodium molybdate",
            commercial_name="Sodium Molybdate",
            micronutrient_type="other",
        )
        self.assertIn("REVIEW — no prior lab result on file", self._chemicals_text())

    def test_the_table_is_absent_when_no_micronutrient_was_applied(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type="FE",
            date=timezone.now(),
            description="Compost tea",
            commercial_name="Compost Tea",
        )
        self.assertNotIn("Micronutrient Applications", self._chemicals_text())

    def test_lab_analysis_renders_in_the_soil_section(self):
        self._lab_event(
            matrix="hull",
            lab_name="A&L Western Labs",
            sample_id="25-04812",
            nitrogen=18,
        )
        text = self._soil_text()
        self.assertIn("Laboratory Analysis Results", text)
        self.assertIn("A&amp;L Western Labs", text)
        self.assertIn("Hull", text)

    def test_micronutrient_results_render_in_the_soil_section(self):
        self._lab_event(matrix="leaf", lab_name="A&L Western Labs", zinc_ppm=0.8)
        text = self._soil_text()
        self.assertIn("Micronutrient Results", text)
        self.assertIn("0.8", text)

    def test_a_soil_test_with_no_micronutrients_skips_that_table(self):
        SoilManagementEvent.objects.create(
            history=self.history,
            type="ST",
            date=timezone.now(),
            description="Routine soil test",
            area_covered=44.5,
            test_results={"lab_name": "Dellavalle Laboratory", "nitrogen": 22},
        )
        text = self._soil_text()
        self.assertIn("Laboratory Analysis Results", text)
        self.assertNotIn("Micronutrient Results", text)

    def test_the_consumer_payload_keeps_the_certifier_split(self):
        """Plain language reaches the shopper; application detail stays with the certifier.

        "Zinc" is a word a consumer follows, and an outside laboratory is genuine third-party
        evidence — both belong on the consumer surface. An application RATE is the same class of
        detail as the NPK percentages, which _CERTIFIER_ONLY_EVENT_FIELDS already strips.
        """
        from history.serializers import PublicHistorySerializer

        self._lab_event(matrix="leaf", lab_name="A&L Western Labs", report_date="2026-07-18", zinc_ppm=0.8)
        self._zinc_application()

        events = PublicHistorySerializer(self.history, context={}).data.get("events") or []
        soil = next(e for e in events if e.get("sample_matrix"))
        chemical = next(e for e in events if e.get("micronutrient_type"))

        self.assertEqual(soil["sample_matrix"], "leaf")
        self.assertEqual(soil["lab_name"], "A&L Western Labs")
        self.assertEqual(soil["lab_report_date"], "2026-07-18")

        self.assertEqual(chemical["micronutrient_type"], "zinc")
        # The strip drops the key outright rather than nulling it, same as nitrogen_percentage.
        self.assertNotIn("micronutrient_rate", chemical, "an application rate leaked to the consumer payload")
        self.assertNotIn("micronutrient_rate_unit", chemical)
        self.assertNotIn("nitrogen_percentage", chemical, "the existing NPK strip stopped working")

    def test_the_lab_record_rides_with_the_organic_packet(self):
        """It is a § 205.601 record, so it must be in the packet a certifier receives."""
        from history.services.audit_export_service import AuditExportService

        self.assertIn("soil", AuditExportService.CERTIFICATION_SECTIONS["organic"])
        self.assertIn("chemicals", AuditExportService.CERTIFICATION_SECTIONS["organic"])


class MicronutrientCitationIsCurrentTests(SimpleTestCase):
    """🔴 2026-09-07 — the micronutrient listing had MOVED and every cite was one paragraph stale.

    Magnesium oxide was inserted at § 205.601(j)(5), pushing micronutrients from (j)(6) to
    **(j)(7)**; its subparagraphs are (i) soluble boron and (ii) the sulfates/carbonates/
    oxides/silicates. `(j)(6)` is now Magnesium sulfate, and `(j)(6)(iii)` — which four call
    sites cited — has never existed in any edition.

    A stale cite reached a PDF *section heading* in the certifier dossier, and the assertions
    in this very file pinned it there. Verified against the repo's frozen corpus
    `documentation/reference/usda-recordkeeping/cfr/title-7-part-205_2026-08-05.xml`, which is
    byte-identical to the live eCFR pull.
    """

    #: Files that state the citation to a certifier, an operator, or a reviewer.
    _CITING_FILES = (
        "history/models/",  # every module of the package
        "history/serializers.py",
        "history/services/audit_export_service.py",
        "certifications/services/national_list_aliases.py",
    )

    def _sources(self):
        root = Path(__file__).resolve().parents[2]
        for rel in self._CITING_FILES:
            paths = sorted((root / rel).glob("*.py")) if rel.endswith("/") else [root / rel]
            self.assertTrue(paths, f"{rel} holds no source: this sweep would pass by reading nothing")
            for path in paths:
                yield path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")

    def test_no_source_still_cites_the_pre_2016_micronutrient_paragraph(self):
        """(j)(6) is cited now, for what it is (magnesium sulfate, the readiness row and the
        aliases). What stays banned is (j)(6) cited FOR micronutrients: a line naming
        micronutrients beside (j)(6) and not magnesium, and any (j)(6) subparagraph."""
        stale = []
        for rel, text in self._sources():
            for line in text.splitlines():
                lowered = line.lower()
                if "(j)(6)(" in line or (
                    "205.601(j)(6)" in line and "micronutrient" in lowered and "magnesium" not in lowered
                ):
                    stale.append(f"{rel}: {line.strip()}")
        self.assertEqual(
            stale,
            [],
            "§ 205.601(j)(6) is Magnesium sulfate. Micronutrients are (j)(7). Stale in: " f"{stale}",
        )

    def test_no_source_invents_a_third_micronutrient_subparagraph(self):
        invented = [rel for rel, text in self._sources() if "(j)(7)(iii)" in text]
        self.assertEqual(
            invented,
            [],
            f"§ 205.601(j)(7) has (i) and (ii) only — molybdenum, selenium and cobalt sit inside (ii): {invented}",
        )

    def test_the_deficiency_basis_is_not_narrowed_to_soil_testing(self):
        """The current text allows soil OR TISSUE testing, or another verifiable method the
        certifying agent approves. Coaching soil-only is coaching a superseded, stricter rule."""
        root = Path(__file__).resolve().parents[2]
        text = (root / "history/services/audit_export_service.py").read_text(encoding="utf-8")
        i = text.find("micronutrients only where a deficiency is documented")
        self.assertGreater(i, -1, "the micronutrient finding text moved — re-point this guard")
        window = text[i : i + 400]
        self.assertIn("TISSUE", window.upper())
        self.assertIn("certifying agent", window)
