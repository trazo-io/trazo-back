"""Two collected-but-unprinted facts, pinned to the certifier packet that reads them.

Both were found on 2026-08-17 by walking every model field of every event type against the
export services, and both are the same shape: the field exists, the form renders it, the
serializer accepts it, and the PDF a certifier reads never mentions it.

  * ``trap_count`` — the Beneficial-Release & Trap Detail table printed the trap KIND and the
    CATCH and omitted the denominator. 180 moths across 3 traps and 180 across 40 traps are
    opposite findings, and UC IPM thresholds are written per trap.
  * ``applied_scope`` / ``applied_scope_detail`` — added for § 205.103(b)(2) ("records that
    permit the input to be traced to WHERE it went") and reaching only the in-app detail
    modal, so a spray covering rows 12-18 printed identically to one covering the block.

The third rule pinned here is the one that keeps the fix honest: an UNANSWERED scope must not
render as "Entire planting". Absence of an answer is not an attestation of full coverage.
"""

import re

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, History, PestManagementEvent, ProductionEvent
from history.services.audit_export_service import AuditExportService
from product.models import Parcel, Product
from users.models import User


def _flowable_text(flowables):
    """Flatten Paragraph + Table flowables to a single searchable string."""
    out = []
    for f in flowables:
        if hasattr(f, "text"):
            out.append(re.sub(r"<[^>]+>", "", f.text))
        elif hasattr(f, "_cellvalues"):
            for row in f._cellvalues:
                for cell in row:
                    if hasattr(cell, "text"):
                        out.append(re.sub(r"<[^>]+>", "", cell.text))
    return " ".join(out)


class PacketScopeAndTrapColumnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="scope@test.com", password="x")
        self.company = Company.objects.create(name="Scope Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company, state="California")
        self.parcel = Parcel.objects.create(name="SP1", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Almond")
        self.history = History.objects.create(
            name="SH1",
            start_date=timezone.now(),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=0.0,
            is_outdoor=True,
        )

    def _service(self):
        return AuditExportService(self.history, certification_type="organic")

    # ---- trap_count (7 CFR 205.206(b) monitoring evidence) ----

    def test_trap_count_reaches_the_packet(self):
        PestManagementEvent.objects.create(
            history=self.history,
            type="TM",
            date=timezone.now(),
            description="Weekly NOW trap check",
            pest_species="Navel orangeworm",
            trap_type="pheromone",
            trap_count=24,
            pest_catch_count=180,
        )
        txt = _flowable_text(self._service()._build_pest_section())
        self.assertIn("Traps", txt, "the trap-count COLUMN is missing from the detail table")
        self.assertIn("24", txt, "the trap count itself never printed")
        # The two figures it sits between must still be there.
        self.assertIn("Pheromone lure", txt)
        self.assertIn("180", txt)

    def test_trap_count_alone_still_opens_the_detail_table(self):
        """A grower who counts traps but not catch must not vanish from the table.

        The row filter listed trap_type and pest_catch_count and not trap_count, so an event
        carrying only the denominator produced no detail row at all.
        """
        PestManagementEvent.objects.create(
            history=self.history,
            type="TM",
            date=timezone.now(),
            description="Trap deployment",
            trap_count=12,
        )
        txt = _flowable_text(self._service()._build_pest_section())
        # `_flowable_text` strips tags but not entities, so the header arrives as "&amp;".
        self.assertIn("Beneficial-Release", txt)
        self.assertIn("Trap Detail (7 CFR 205.206)", txt)
        self.assertIn("12", txt)

    # ---- applied_scope on inputs (7 CFR 205.103(b)(2)) ----

    def test_partial_application_locator_reaches_the_packet(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            applied_scope="part",
            applied_scope_detail="rows 12-18, north end",
        )
        txt = _flowable_text(self._service()._build_chemical_log())
        self.assertIn("Treated Scope", txt)
        self.assertIn("rows 12-18, north end", txt)

    def test_partial_application_without_a_locator_is_flagged_not_hidden(self):
        """ "Part of planting" with no locator does not satisfy (b)(2) — say so on the page."""
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            applied_scope="part",
        )
        txt = _flowable_text(self._service()._build_chemical_log())
        self.assertIn("[REVIEW] area not specified", txt)

    def test_unanswered_scope_is_not_rendered_as_full_coverage(self):
        """Absence of an answer is not an attestation that the whole planting was treated."""
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            growth_stage="bloom",
        )
        txt = _flowable_text(self._service()._build_chemical_log())
        self.assertIn("Treated Scope", txt, "the column should still render for the other context fields")
        self.assertNotIn("Entire planting", txt)
        self.assertNotIn("[REVIEW] area not specified", txt)

    def test_entire_planting_answer_prints_its_own_label(self):
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            applied_scope="all",
        )
        txt = _flowable_text(self._service()._build_chemical_log())
        self.assertIn("Entire planting", txt)

    # ---- applied_scope on harvests ----

    def test_partial_harvest_gets_its_own_table(self):
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            block_id="Block 2",
            applied_scope="part",
            applied_scope_detail="south half only",
        )
        txt = _flowable_text(self._service()._build_production_events())
        self.assertIn("Partial-Area Harvests", txt)
        self.assertIn("south half only", txt)

    def test_whole_planting_harvest_does_not_open_the_partial_table(self):
        """Listing every full harvest would bury the exception the table exists to surface."""
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            applied_scope="all",
        )
        txt = _flowable_text(self._service()._build_production_events())
        self.assertNotIn("Partial-Area Harvests", txt)
