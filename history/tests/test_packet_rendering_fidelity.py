"""What the packet prints must be what the operator recorded — and only what Trazo can back.

Four defects found 2026-08-20 by two senior certifier reviewers reading the same generated
packets independently. Both led with the same ones, which is why they are guarded together:
each is a case of the renderer changing, overstating, or misdescribing the operator's record
on the one document a certifier makes a decision from.
"""

from types import SimpleNamespace

from django.test import TestCase

from history.services.audit_export_service import _humanize_enum, _organic_basis_cell


class GradeCasingTests(TestCase):
    """`.title()` over operator free text destroyed every acronym in a US farm record."""

    def test_a_recorded_grade_is_reproduced_exactly(self):
        # Both reviewers quoted these. Neither "Wa Extra Fancy" nor "Us No. 1" is a grade,
        # and a reviewer matching a lot against a packing record looks the grade up in a
        # controlled vocabulary that contains neither.
        self.assertEqual(_humanize_enum("WA Extra Fancy"), "WA Extra Fancy")
        self.assertEqual(_humanize_enum("US No. 1"), "US No. 1")
        self.assertEqual(_humanize_enum("US Fancy"), "US Fancy")

    def test_a_slug_is_still_humanized(self):
        """The behaviour worth keeping: an enum value is not shown to a human as a slug."""
        self.assertEqual(_humanize_enum("shake_and_catch"), "Shake And Catch")
        self.assertEqual(_humanize_enum("cover_cropping"), "Cover Cropping")
        self.assertEqual(_humanize_enum("manual"), "Manual")

    def test_blank_and_none_are_none(self):
        self.assertIsNone(_humanize_enum(None))
        self.assertIsNone(_humanize_enum("   "))


class OrganicBasisAttributionTests(TestCase):
    """An "OMRI Listed" cell with no OMRI ID is an unearned certification-mark claim."""

    class _Event:
        def __init__(self, organic_approved, omri_product_id=None):
            self.organic_approved = organic_approved
            self.omri_product_id = omri_product_id
            # `claim_authority` reads `delisted_on` off the related row: an OMRI FK earns the
            # claim only while OMRI still lists the product. A real event always resolves it.
            self.omri_product = SimpleNamespace(delisted_on=None) if omri_product_id else None

    def test_a_grower_selected_listing_says_so(self):
        """The defect: the Input Log asserted the listing, the verification table denied it.

        OMRI and WSDA run real listing programmes, so an unbacked claim here is not puffery.
        The packet must not hide the grower's answer either — a reviewer needs to know what
        the operator believes — so the cell carries the selection AND its evidence state.
        """
        cell = _organic_basis_cell(self._Event("omri_listed"))
        self.assertIn("OMRI Listed", cell)
        self.assertIn("grower-selected", cell)
        self.assertIn("no listing on file", cell)

    def test_a_real_catalog_match_is_not_qualified(self):
        cell = _organic_basis_cell(self._Event("omri_listed", omri_product_id=42))
        self.assertEqual(cell, "OMRI Listed")

    def test_wsda_and_certifier_review_are_qualified_too(self):
        """All four bases USDA's own form names a third party for, not just OMRI."""
        for value in ("wsda_listed", "nop_seal_on_label", "certifier_approved"):
            with self.subTest(value=value):
                self.assertIn("grower-selected", _organic_basis_cell(self._Event(value)))

    def test_a_first_party_answer_is_left_alone(self):
        """ "Not Organic" names no third party — qualifying it would be noise."""
        cell = _organic_basis_cell(self._Event("not_organic"))
        self.assertNotIn("grower-selected", cell)

    def test_an_unrecognised_value_still_reports_itself(self):
        cell = _organic_basis_cell(self._Event("True"))
        self.assertIn("NOT SPECIFIED", cell)
        self.assertIn("True", cell)


class ClaimPrecisionTests(TestCase):
    """Three statements the packet made that were not Trazo's to make, or were wrong.

    Asserted against RENDERED text, not source: a string split across adjacent literals is
    still one sentence to the reader, and the reader is who these fixes are for.
    """

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from carbon.models import CropType
        from company.models import Company, Establishment
        from history.models import History
        from product.models import Parcel, Product

        company = Company.objects.create(name="Precision Co")
        est = Establishment.objects.create(name="Precision Farm", company=company, state="WA")
        parcel = Parcel.objects.create(name="Block", establishment=est, area=11.5)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-precision",
            category="tree_fruit",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.history = History.objects.create(
            parcel=parcel,
            product=Product.objects.create(name="Apple"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
        )

    @staticmethod
    def _text(elements):
        out = []
        for el in elements if isinstance(elements, list) else [elements]:
            out.append(getattr(el, "text", "") or "")
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    out.append(getattr(cell, "text", "") or "")
        return " ".join(out)

    def _service(self):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(self.history, certification_type="organic")

    def test_the_drift_note_separates_the_product_from_the_operation(self):
        """§ 205.671 puts the PRODUCT out of organic sale; it does not revoke certification.

        This is the sentence an operator reads in the hours after a drift event, when the
        difference between "this block's crop is out" and "we have lost our certification"
        decides whether they call the certifier or panic.
        """
        text = self._text(self._service()._buffer_zone_footnote())
        self.assertIn("205.671", text)
        self.assertIn("does not by itself revoke", text)
        self.assertNotIn("can cause loss of organic status", text)

    def test_trazo_does_not_assert_records_are_contemporaneous(self):
        """That is a finding about the operation, made by the inspector from the record dates.

        Both certifier reviewers quoted "maintained in real time" back against the same
        document's own change history, which showed every record written by a background task
        the night the packet was generated.
        """
        text = self._text(self._service()._build_soe_compliance_section())
        self.assertNotIn("maintained in real time", text)
        # It must still say what Trazo CAN speak to, and hand the judgement back.
        self.assertIn("inspector's determination", text)

    def test_the_certifying_agents_duty_is_not_cited_as_the_producers(self):
        """§ 205.501 lists what an ACCREDITED CERTIFIER must do, not the producer."""
        text = self._text(self._service()._build_soe_compliance_section())
        self.assertIn("205.501(a)(21)", text)  # still cited, correctly attributed
        self.assertIn("certifying agent's own audit duty", text)


class CertifierNeutralityTests(TestCase):
    """The packet must not address one certifier by name when it means "the certifier"."""

    def test_no_rendered_string_names_ccof_as_the_requirement_setter(self):
        """A WSDA renewal carried 52 references to CCOF and cited California law at a WA farm.

        The G-numbering is the Common OSP standard — published by CCOF, used across
        accredited certifiers — so naming CCOF misstated the provenance as well as the
        recipient. Code comments citing CCOF as the design source are correct and stay; this
        walks only string literals.
        """
        import ast
        import inspect

        from history.services import audit_export_service

        source = inspect.getsource(audit_export_service)
        tree = ast.parse(source)

        # Collect docstring nodes by IDENTITY, not by guessing at their shape: a docstring is
        # documentation for the next maintainer and may cite CCOF as the design source all it
        # likes. Only strings that can reach the page are in scope.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    if isinstance(body[0].value.value, str):
                        docstrings.add(id(body[0].value))

        offenders = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings or "CCOF" not in node.value:
                continue
            offenders.add(node.value.strip()[:100])

        self.assertEqual(
            sorted(offenders),
            [],
            f"rendered strings still name CCOF: {sorted(offenders)}",
        )


class HandlerFlagEscapingTests(TestCase):
    """The § 205.272 handler warning interpolates operator free text into a Paragraph.

    Introduced and caught in the same session (2026-08-20). Rewording the flag to name the
    handler that IS on file meant putting `storage_location` / `sold_to` — both farmer-typed —
    into a hand-built ReportLab Paragraph, which parses a mini-HTML dialect. "Bob & Sons"
    raises ValueError and takes the whole packet down; "Stemilt <north dock>" is silently
    swallowed, destroying the operator's own words in the document whose purpose is to record
    them. `_esc` exists for exactly this and was written after the same trap was found by
    fuzzing the buffer lines on 2026-08-12.
    """

    def test_esc_neutralises_the_markup_characters_reportlab_parses(self):
        from history.services.audit_export_service import _esc

        self.assertEqual(_esc("Bob & Sons"), "Bob &amp; Sons")
        self.assertEqual(_esc("Stemilt <north dock>"), "Stemilt &lt;north dock&gt;")

    def test_the_handler_flag_escapes_the_names_it_prints(self):
        """A packet must still build when the handler's name contains an ampersand."""
        from datetime import timedelta

        from django.utils import timezone

        from reportlab.platypus import Paragraph

        from carbon.models import CropType
        from company.models import Company, Establishment
        from history.models import History, ProductionEvent
        from history.services.audit_export_service import AuditExportService
        from product.models import Parcel, Product

        company = Company.objects.create(name="Escape Co")
        est = Establishment.objects.create(name="Escape Farm", company=company, state="WA")
        parcel = Parcel.objects.create(name="Block", establishment=est, area=11.5)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-escape",
            category="tree_fruit",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        history = History.objects.create(
            parcel=parcel,
            product=Product.objects.create(name="Apple"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
        )
        ProductionEvent.objects.create(
            history=history,
            type="HA",
            date=timezone.now() - timedelta(days=10),
            description="Harvest",
            storage_location="Bob & Sons <north dock>",
            # `sent_to_handler_date` is what makes the round-trip subtable render, which is
            # the precondition for the § 205.272 flag under test.
            sent_to_handler_date=(timezone.now() - timedelta(days=9)).date(),
            quantity_sent_to_handler=1000,
        )

        elements = AuditExportService(history, certification_type="organic")._build_post_harvest_section()

        # Assert on the FRAGS, not on Paragraph construction. Measured 2026-08-20 against this
        # ReportLab build, an unescaped operator name fails in two different ways and only one
        # of them raises:
        #
        #   "Stemilt <north dock>"  -> parses as an unknown tag and is SILENTLY DROPPED;
        #                              p.frags reads "sent to Stemilt ." and nothing errors
        #   "Bob <b>Sons"           -> ValueError at construction
        #
        # A first version of this test called `el.wrap()` and asserted nothing about the text.
        # It passed with the escaping removed — the exact "a test that supplies its own input
        # passes forever" trap. The only assertion that catches the silent case is that the
        # operator's words actually survive into the rendered fragments.
        flag = next(
            # "[REVIEW]", not "205.272": the SECTION HEADER carries the citation too.
            # Both conditions: the section HEADER carries "205.272" too, and there is more
            # than one [REVIEW] paragraph in this section.
            (
                el
                for el in elements
                if isinstance(el, Paragraph)
                and "[REVIEW]" in (getattr(el, "text", "") or "")
                and "205.272" in (getattr(el, "text", "") or "")
            ),
            None,
        )
        self.assertIsNotNone(flag, "the § 205.272 handler flag did not render")
        rendered = "".join(getattr(f, "text", "") for f in (flag.frags or []))
        self.assertIn("Bob & Sons", rendered)
        self.assertIn("north dock", rendered)


class AttachedDocumentIndexTests(TestCase):
    """The document index must not drop rows silently.

    The index exists to tell a certifier WHAT EXISTS so they can ask for it at inspection
    (7 CFR 205.103(b)(1)/(c)) — the files themselves stay in the DMS. A cap that hides older
    uploads with no note is therefore worse than a shorter list: the reviewer reads it as
    complete. Found 2026-08-20; the `[:60]` slice had been silent since the section shipped.
    """

    def setUp(self):
        from datetime import timedelta

        from django.utils import timezone

        from carbon.models import CropType
        from company.models import Company, Establishment
        from history.models import History
        from product.models import Parcel, Product

        self.company = Company.objects.create(name="Docs Co")
        self.est = Establishment.objects.create(name="Docs Farm", company=self.company, state="WA")
        parcel = Parcel.objects.create(name="Block", establishment=self.est, area=11.5)
        crop = CropType.objects.create(
            name="Apple",
            slug="apple-docs",
            category="tree_fruit",
            description="d",
            typical_farm_size="1",
            growing_season="s",
            harvest_season="h",
            emissions_per_hectare=0.0,
            industry_average=0.0,
            best_practice=0.0,
            carbon_credit_potential=0.0,
            typical_cost_per_hectare=0.0,
            has_soil_contact=True,
        )
        self.history = History.objects.create(
            parcel=parcel,
            product=Product.objects.create(name="Apple"),
            crop_type=crop,
            start_date=timezone.now() - timedelta(days=200),
        )

    def _make_documents(self, count):
        from documents.models import GeneratedDocument

        for i in range(count):
            GeneratedDocument.objects.create(
                establishment=self.est,
                source="upload",
                title=f"Receipt {i:03d}",
                size_bytes=1024,
            )

    def _text(self, elements):
        out = []
        for el in elements:
            out.append(getattr(el, "text", "") or "")
            for row in getattr(el, "_cellvalues", None) or []:
                for cell in row:
                    out.append(getattr(cell, "text", "") or "")
        return " ".join(out)

    def _section(self):
        from history.services.audit_export_service import AuditExportService

        svc = AuditExportService(self.history, certification_type="organic")
        svc.documents_scope = "establishment"
        return self._text(svc._build_attached_documents_section())

    def test_an_uncapped_index_says_nothing_about_truncation(self):
        self._make_documents(5)
        text = self._section()
        self.assertIn("Receipt 000", text)
        self.assertNotIn("are not listed above", text)

    def test_a_capped_index_discloses_what_it_omitted(self):
        self._make_documents(65)
        text = self._section()
        self.assertIn("60 most recently uploaded", text)
        self.assertIn("65", text)
        self.assertIn("5 older document(s) are not listed above", text)

    def test_an_empty_index_still_names_what_a_certifier_expects(self):
        text = self._section()
        self.assertIn("No documents have been uploaded", text)
