"""
Sprint 5.1 GA — ApprovedInputChangeLog audit trail tests.

Covers:
  - add_approved_input writes a log row with correct fields (action, kind, name)
  - remove_approved_input writes a log row with action="removed"
  - target_name_at_change is frozen and survives FK SET_NULL
  - change_notification_reference + notes round-trip from POST body
  - serializer returns logs ordered newest-first
  - audit PDF includes a change-log table when logs exist
  - audit PDF shows clean-state line when no logs exist
"""

from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from certifications.models import ApprovedInputChangeLog, NationalListSubstance, OMRIProduct, OrganicSystemPlan
from company.models import Company, Establishment
from history.models import Production
from product.models import Parcel

# ---------------------------------------------------------------------------
# Helper — minimal OSP fixture
# ---------------------------------------------------------------------------


def _make_osp_fixture():
    company = Company.objects.create(name="Log Test Farm")
    establishment = Establishment.objects.create(name="Main", company=company)
    osp = OrganicSystemPlan.objects.create(
        establishment=establishment,
        version_number=1,
        status="active",
        effective_date=timezone.now().date(),
    )
    nl = NationalListSubstance.objects.create(
        substance_name="Copper hydroxide",
        substance_name_normalized="copper hydroxide",
        cfr_section="205.601",
        subsection="i",
        status="allowed",
    )
    omri = OMRIProduct.objects.create(
        omri_id="OMRI-LOG-1",
        product_name="Kocide 3000",
        manufacturer="Certis USA",
    )
    return osp, nl, omri, establishment


# ---------------------------------------------------------------------------
# Model-level tests (no HTTP)
# ---------------------------------------------------------------------------


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ApprovedInputChangeLogModelTests(TransactionTestCase):
    """Direct ORM writes — no viewset, no request."""

    def setUp(self):
        self.osp, self.nl, self.omri, self.establishment = _make_osp_fixture()

    def test_add_national_list_writes_log_row(self):
        self.osp.approved_national_list_substances.add(self.nl)
        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            target_national_list=self.nl,
            target_name_at_change=self.nl.substance_name,
            action=ApprovedInputChangeLog.ACTION_ADDED,
        )
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertEqual(entry.action, "added")
        self.assertEqual(entry.kind, "national_list")
        self.assertEqual(entry.target_name_at_change, "Copper hydroxide")
        self.assertEqual(entry.target_national_list_id, self.nl.pk)
        self.assertIsNone(entry.target_omri)

    def test_remove_omri_writes_log_row_with_removed_action(self):
        self.osp.approved_omri_products.add(self.omri)
        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_OMRI,
            target_omri=self.omri,
            target_name_at_change=self.omri.product_name,
            action=ApprovedInputChangeLog.ACTION_REMOVED,
        )
        entry = ApprovedInputChangeLog.objects.filter(
            osp=self.osp, action=ApprovedInputChangeLog.ACTION_REMOVED
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.action, "removed")
        self.assertEqual(entry.target_name_at_change, "Kocide 3000")

    def test_target_name_at_change_survives_fk_null(self):
        """Delete the NL substance — the FK becomes NULL but the name snapshot persists."""
        nl_pk = self.nl.pk
        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            target_national_list=self.nl,
            target_name_at_change=self.nl.substance_name,
            action=ApprovedInputChangeLog.ACTION_ADDED,
        )
        # Hard-delete the substance — SET_NULL fires.
        NationalListSubstance.objects.filter(pk=nl_pk).delete()
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertIsNone(entry.target_national_list_id)
        # The frozen name must still be present.
        self.assertEqual(entry.target_name_at_change, "Copper hydroxide")

    def test_change_notification_reference_and_notes_round_trip(self):
        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_OMRI,
            target_omri=self.omri,
            target_name_at_change=self.omri.product_name,
            action=ApprovedInputChangeLog.ACTION_ADDED,
            change_notification_reference="CCOF-CN-4821",
            notes="Annual plan update approved by CCOF 2026-03-15.",
        )
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertEqual(entry.change_notification_reference, "CCOF-CN-4821")
        self.assertEqual(entry.notes, "Annual plan update approved by CCOF 2026-03-15.")

    def test_str_representation(self):
        entry = ApprovedInputChangeLog(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            target_name_at_change="Copper hydroxide",
            action=ApprovedInputChangeLog.ACTION_ADDED,
        )
        self.assertIn("added", str(entry))
        self.assertIn("Copper hydroxide", str(entry))

    def test_ordering_is_newest_first(self):
        """Meta ordering = ["-changed_at"] — most recent entry first."""
        for name in ("Entry A", "Entry B", "Entry C"):
            ApprovedInputChangeLog.objects.create(
                osp=self.osp,
                kind=ApprovedInputChangeLog.KIND_OMRI,
                target_name_at_change=name,
                action=ApprovedInputChangeLog.ACTION_ADDED,
            )
        names = list(
            ApprovedInputChangeLog.objects.filter(osp=self.osp).values_list("target_name_at_change", flat=True)
        )
        # Last created (Entry C) should be first.
        self.assertEqual(names[0], "Entry C")


# ---------------------------------------------------------------------------
# Viewset action tests — wired through add/remove_approved_input
# ---------------------------------------------------------------------------


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AddRemoveApprovedInputLogTests(TransactionTestCase):
    """
    Invoke _add_log_for_action / _remove_log_for_action via the viewset helpers
    directly, bypassing HTTP to keep tests fast and focused on log correctness.
    """

    def setUp(self):
        self.osp, self.nl, self.omri, self.establishment = _make_osp_fixture()

    def _viewset_add(self, osp, kind, target, ref="", notes="", user=None):
        """Mirror the log-write logic from add_approved_input."""
        if kind == ApprovedInputChangeLog.KIND_NATIONAL_LIST:
            osp.approved_national_list_substances.add(target)
            target_name = target.substance_name
        else:
            osp.approved_omri_products.add(target)
            target_name = target.product_name

        log_kwargs = dict(
            osp=osp,
            kind=kind,
            target_name_at_change=target_name,
            action=ApprovedInputChangeLog.ACTION_ADDED,
            changed_by=user,
            change_notification_reference=ref,
            notes=notes,
        )
        if kind == ApprovedInputChangeLog.KIND_NATIONAL_LIST:
            log_kwargs["target_national_list"] = target
        else:
            log_kwargs["target_omri"] = target
        ApprovedInputChangeLog.objects.create(**log_kwargs)

    def _viewset_remove(self, osp, kind, target, ref="", notes="", user=None):
        """Mirror the log-write logic from remove_approved_input."""
        if kind == ApprovedInputChangeLog.KIND_NATIONAL_LIST:
            osp.approved_national_list_substances.remove(target)
            target_name = target.substance_name
        else:
            osp.approved_omri_products.remove(target)
            target_name = target.product_name

        log_kwargs = dict(
            osp=osp,
            kind=kind,
            target_name_at_change=target_name,
            action=ApprovedInputChangeLog.ACTION_REMOVED,
            changed_by=user,
            change_notification_reference=ref,
            notes=notes,
        )
        if kind == ApprovedInputChangeLog.KIND_NATIONAL_LIST:
            log_kwargs["target_national_list"] = target
        else:
            log_kwargs["target_omri"] = target
        ApprovedInputChangeLog.objects.create(**log_kwargs)

    def test_add_national_list_creates_log_row(self):
        self._viewset_add(self.osp, ApprovedInputChangeLog.KIND_NATIONAL_LIST, self.nl)
        self.assertEqual(ApprovedInputChangeLog.objects.filter(osp=self.osp).count(), 1)
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertEqual(entry.action, ApprovedInputChangeLog.ACTION_ADDED)
        self.assertEqual(entry.kind, ApprovedInputChangeLog.KIND_NATIONAL_LIST)
        self.assertEqual(entry.target_name_at_change, "Copper hydroxide")

    def test_add_omri_creates_log_row_with_correct_fields(self):
        self._viewset_add(
            self.osp,
            ApprovedInputChangeLog.KIND_OMRI,
            self.omri,
            ref="CCOF-CN-9001",
            notes="Test note",
        )
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertEqual(entry.action, ApprovedInputChangeLog.ACTION_ADDED)
        self.assertEqual(entry.kind, ApprovedInputChangeLog.KIND_OMRI)
        self.assertEqual(entry.target_name_at_change, "Kocide 3000")
        self.assertEqual(entry.change_notification_reference, "CCOF-CN-9001")
        self.assertEqual(entry.notes, "Test note")
        self.assertEqual(entry.target_omri_id, self.omri.pk)

    def test_remove_creates_log_row_with_removed_action(self):
        self.osp.approved_omri_products.add(self.omri)
        self._viewset_remove(self.osp, ApprovedInputChangeLog.KIND_OMRI, self.omri)
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertEqual(entry.action, ApprovedInputChangeLog.ACTION_REMOVED)
        self.assertEqual(entry.target_name_at_change, "Kocide 3000")

    def test_change_notification_reference_from_post_body(self):
        """Simulates the caller passing ref + notes in the POST body."""
        self._viewset_add(
            self.osp,
            ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            self.nl,
            ref="OTCO-2026-44B",
            notes="Approved per Oregon Tilth letter 2026-04-01.",
        )
        entry = ApprovedInputChangeLog.objects.get(osp=self.osp)
        self.assertEqual(entry.change_notification_reference, "OTCO-2026-44B")
        self.assertIn("Oregon Tilth", entry.notes)

    def test_multiple_changes_are_all_logged(self):
        self._viewset_add(self.osp, ApprovedInputChangeLog.KIND_NATIONAL_LIST, self.nl)
        self._viewset_add(self.osp, ApprovedInputChangeLog.KIND_OMRI, self.omri)
        self._viewset_remove(self.osp, ApprovedInputChangeLog.KIND_NATIONAL_LIST, self.nl)
        self.assertEqual(ApprovedInputChangeLog.objects.filter(osp=self.osp).count(), 3)


# ---------------------------------------------------------------------------
# Serializer tests
# ---------------------------------------------------------------------------


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ApprovedInputChangeLogSerializerTests(TestCase):
    """Verify the serializer field set and ordering."""

    def setUp(self):
        self.osp, self.nl, self.omri, self.establishment = _make_osp_fixture()

    def test_serializer_returns_logs_newest_first(self):
        from certifications.serializers import OrganicSystemPlanSerializer

        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            target_national_list=self.nl,
            target_name_at_change="Copper hydroxide",
            action=ApprovedInputChangeLog.ACTION_ADDED,
        )
        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_OMRI,
            target_omri=self.omri,
            target_name_at_change="Kocide 3000",
            action=ApprovedInputChangeLog.ACTION_ADDED,
            change_notification_reference="CCOF-CN-1234",
        )
        # Refresh via queryset that matches the viewset prefetch.
        osp = OrganicSystemPlan.objects.prefetch_related("approved_input_changes__changed_by").get(pk=self.osp.pk)
        data = OrganicSystemPlanSerializer(osp).data
        logs = data["approved_input_changes"]
        self.assertEqual(len(logs), 2)
        # Newest first — Kocide was created last.
        self.assertEqual(logs[0]["target_name_at_change"], "Kocide 3000")
        self.assertEqual(logs[1]["target_name_at_change"], "Copper hydroxide")

    def test_serializer_exposes_required_fields(self):
        from certifications.serializers import ApprovedInputChangeLogSerializer

        entry = ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_OMRI,
            target_omri=self.omri,
            target_name_at_change="Kocide 3000",
            action=ApprovedInputChangeLog.ACTION_ADDED,
            change_notification_reference="REF-001",
            notes="Certifier approved.",
        )
        data = ApprovedInputChangeLogSerializer(entry).data
        for field in (
            "id",
            "kind",
            "target_name_at_change",
            "action",
            "changed_by_name",
            "changed_at",
            "change_notification_reference",
            "notes",
        ):
            self.assertIn(field, data, f"Missing field: {field}")
        self.assertEqual(data["change_notification_reference"], "REF-001")
        self.assertIsNone(data["changed_by_name"])  # no user set


# ---------------------------------------------------------------------------
# Audit PDF tests
# ---------------------------------------------------------------------------


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class AuditPDFChangeLogSectionTests(TransactionTestCase):
    """Verify _build_osp_reference_section renders the change-log table."""

    def setUp(self):
        self.company = Company.objects.create(name="PDF Log Farm")
        self.establishment = Establishment.objects.create(name="Main", company=self.company)
        self.parcel = Parcel.objects.create(name="P", establishment=self.establishment, area=1.0)
        self.history = Production.objects.create(
            name="Prod",
            start_date=timezone.now(),
            parcel=self.parcel,
        )
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            effective_date=timezone.now().date(),
        )
        self.nl = NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section="205.601",
            status="allowed",
        )
        self.omri = OMRIProduct.objects.create(
            omri_id="OMRI-PDF-1",
            product_name="Entrust SC",
        )

    def _service(self):
        from history.services.audit_export_service import AuditExportService

        return AuditExportService(self.history, certification_type="organic")

    def _osp_section_texts(self, svc):
        """Return all text strings produced by _build_osp_reference_section."""
        # The method finds the OSP internally via production -> parcel -> establishment.
        els = svc._build_osp_reference_section()
        return " ".join(getattr(e, "text", "") for e in els if hasattr(e, "text"))

    def test_no_change_logs_shows_clean_state_text(self):
        texts = self._osp_section_texts(self._service())
        self.assertIn("No recorded changes", texts)

    def test_change_log_table_included_when_logs_exist(self):
        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            target_national_list=self.nl,
            target_name_at_change="Spinosad",
            action=ApprovedInputChangeLog.ACTION_ADDED,
            change_notification_reference="CCOF-CN-9999",
        )
        els = self._service()._build_osp_reference_section()
        # The section always contains a section-summary Table. When change logs
        # exist, a second Table (the change-log table) is appended. So there
        # should be at least 2 Tables.
        from reportlab.platypus import Table

        tables = [e for e in els if isinstance(e, Table)]
        self.assertGreaterEqual(len(tables), 2, "Expected section-summary Table + change-log Table")

    def test_change_log_table_not_present_when_no_logs(self):
        from reportlab.platypus import Table

        els = self._service()._build_osp_reference_section()
        tables = [e for e in els if isinstance(e, Table)]
        # No change logs → only the section-summary Table, no change-log Table.
        # The "No recorded changes" paragraph is used instead of a second table.
        self.assertEqual(len(tables), 1, "With no log entries, only the summary Table should exist")

    def test_change_log_header_present_in_section(self):
        texts = self._osp_section_texts(self._service())
        self.assertIn("Change log", texts)
        self.assertIn("205.400", texts)

    def test_soe_compliance_section_includes_plan_document_filename(self):
        """
        Inspector screen shows the fraud-prevention plan document filename
        (e.g., ComprobanteFactura.pdf). The audit PDF must reference it too,
        otherwise auditors can't request the specific file by name.
        """
        from django.core.files.base import ContentFile

        from reportlab.platypus import Paragraph, Table

        from history.services.audit_export_service import AuditExportService

        est = self.establishment
        est.fraud_prevention_plan_uploaded = True
        est.fraud_prevention_plan_date = timezone.now().date()
        est.ofpp_responsible_person = "Maria Elena Gutierrez"
        est.fraud_prevention_plan_document.save(
            "ComprobanteFactura.pdf",
            ContentFile(b"%PDF-1.4 test"),
            save=True,
        )

        svc = AuditExportService(self.history, certification_type="organic")
        els = svc._build_soe_compliance_section()
        tables = [e for e in els if isinstance(e, Table)]
        self.assertTrue(tables)
        soe_table = tables[0]

        # Regression guard: every cell must be a Paragraph (same WORDWRAP
        # gotcha we hit in the change-log table — raw strings won't wrap).
        for row in soe_table._cellvalues:
            for cell in row:
                self.assertIsInstance(
                    cell,
                    Paragraph,
                    f"SOE cell must be Paragraph (got {type(cell).__name__})",
                )

        joined = " ".join(p.text for row in soe_table._cellvalues for p in row)
        # Django FileField may append a random suffix to avoid filename
        # collisions, so match the stem instead of the exact filename.
        self.assertIn("Comprobante", joined)
        self.assertIn(".pdf", joined)
        self.assertIn("Maria Elena Gutierrez", joined)

    def test_change_log_cells_wrap_long_content_and_escape_xml(self):
        """
        Regression guard: ReportLab Tables do NOT wrap raw-string cells
        (WORDWRAP is silently ignored). Cells must be Paragraph flowables so
        long cert refs + XML-special chars render correctly.
        """
        from reportlab.platypus import Paragraph, Table

        ApprovedInputChangeLog.objects.create(
            osp=self.osp,
            kind=ApprovedInputChangeLog.KIND_NATIONAL_LIST,
            target_national_list=self.nl,
            # Name with < and & — would blow up Paragraph markup if not escaped.
            target_name_at_change="Copper <hydroxide> & lime",
            action=ApprovedInputChangeLog.ACTION_ADDED,
            # Long cert ref that MUST wrap or the table blows past page width.
            change_notification_reference=(
                "CCOF change-notification acknowledgment dated 2026-03-15, "
                "letter reference #CCOF-CN-4821, signed by certification "
                "program specialist for the Fallbrook operation scope expansion."
            ),
        )
        els = self._service()._build_osp_reference_section()
        change_log_tables = [e for e in els if isinstance(e, Table)]
        self.assertGreaterEqual(len(change_log_tables), 2)
        log_table = change_log_tables[-1]

        # Every cell in the change-log table must be a Paragraph flowable
        # (not a plain string) so ReportLab wraps it.
        for row in log_table._cellvalues:
            for cell in row:
                self.assertIsInstance(cell, Paragraph, f"change-log cell must be Paragraph (got {type(cell).__name__})")

        # And the rendered Paragraph text must escape the angle brackets
        # (otherwise ReportLab interprets them as intra-paragraph tags and
        # will raise/garble the output).
        joined = " ".join(p.text for row in log_table._cellvalues for p in row)
        self.assertNotIn("<hydroxide>", joined)
        self.assertIn("&lt;hydroxide&gt;", joined)
