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
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from company.models import Company, Establishment
from history.models import ChemicalEvent, PestManagementEvent, Production, ProductionEvent
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
        self.history = Production.objects.create(
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
            # 137/180 rather than 24/12: the flattened section contains the rendered event
            # DATE, so a one- or two-digit count passes vacuously on the matching day of the
            # month (and "12" passes for all of December). A three-digit count cannot occur in
            # a rendered date.
            trap_count=137,
            pest_catch_count=180,
        )
        txt = _flowable_text(self._service()._build_pest_section())
        self.assertIn("Traps", txt, "the trap-count COLUMN is missing from the detail table")
        self.assertIn("137", txt, "the trap count itself never printed")
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
            trap_count=143,  # 3-digit: cannot collide with the rendered date (see above)
        )
        txt = _flowable_text(self._service()._build_pest_section())
        # `_flowable_text` strips tags but not entities, so the header arrives as "&amp;".
        self.assertIn("Beneficial-Release", txt)
        self.assertIn("Trap Detail (7 CFR 205.206)", txt)
        self.assertIn("143", txt)

    def test_zero_traps_and_zero_catch_still_print(self):
        """0 is a real answer: traps were checked and nothing was caught.

        Every guard here is `is not None`, so this passes today. It exists because the obvious
        "simplification" to `if ev.trap_count:` in the row filter, the PDF cell or the CSV
        would drop the record and leave every other test in this file green.
        """
        PestManagementEvent.objects.create(
            history=self.history,
            type="TM",
            date=timezone.now(),
            description="Trap check, clean",
            trap_type="sticky",
            trap_count=0,
            pest_catch_count=0,
        )
        txt = _flowable_text(self._service()._build_pest_section())
        self.assertIn("Trap Detail (7 CFR 205.206)", txt, "a zero-count trap check opened no table")
        self.assertIn("Sticky card", txt, "the trap TYPE vanished alongside the zeroes")
        csv_text = self._service().generate_csv().getvalue().decode("utf-8-sig")
        self.assertIn("0 traps", csv_text, "zero traps rendered as an em-dash in the CSV")
        self.assertIn("0 caught", csv_text, "zero catch rendered as an em-dash in the CSV")

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
            area_covered=Decimal("11.5"),
            area_unit="acres",
            applied_scope="part",
            applied_scope_detail="south half only",
        )
        txt = _flowable_text(self._service()._build_production_events())
        self.assertIn("Partial-Area Operations", txt)
        self.assertIn("south half only", txt)
        # The HEADERS, not just the values. The locator shipped under an "Area Covered" header
        # while the acreage was absent entirely, so an inspector read
        # "Area Covered: Part — south half only". No test asserted the header row, which is
        # exactly why it went unnoticed.
        self.assertIn("Applied Scope", txt, "the locator column lost its own header")
        self.assertIn("Area Covered", txt, "the acreage column is missing")
        self.assertIn("11.5", txt, "the acreage itself never printed next to the locator")

    def test_partial_planting_is_in_the_same_table(self):
        """ProductionTab collects the scope on Planting too, and it has the same consequence.

        Trees-per-acre computed against the whole block is wrong by whatever fraction went
        unplanted, so a partial planting cannot be filtered out as a harvest-only concern.
        """
        ProductionEvent.objects.create(
            history=self.history,
            type="PL",
            date=timezone.now(),
            description="Replant of frost losses",
            applied_scope="part",
            applied_scope_detail="rows 1-4 replanted only",
        )
        txt = _flowable_text(self._service()._build_production_events())
        self.assertIn("Partial-Area Operations", txt)
        # NOT assertIn("Planting"): the main Production Events table already prints that label
        # for this same event, so the assertion passed even with the Operation column deleted.
        # The locator is unique to this table.
        self.assertIn("rows 1-4 replanted only", txt)

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
        # Read-proof FIRST. A bare assertNotIn passes when the event was never created or the
        # section short-circuited — the failure mode this project's own rule names: a negative
        # assertion must prove it read something.
        self.assertIn("First shake", txt, "the harvest event never rendered — the assertNotIn below is vacuous")
        self.assertNotIn("Partial-Area Operations", txt)

    # ---- CSV: the sibling surface the same certifier reads ----

    def test_csv_carries_the_trap_triple_and_the_scope_locator(self):
        """A fix on the PDF that skips the CSV is the "alive on its sibling" failure again."""
        PestManagementEvent.objects.create(
            history=self.history,
            type="TM",
            date=timezone.now(),
            description="Weekly NOW trap check",
            trap_type="pheromone",
            trap_count=24,
            pest_catch_count=180,
        )
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.PESTICIDE,
            commercial_name="Entrust SC",
            date=timezone.now(),
            applied_scope="part",
            applied_scope_detail="rows 12-18",
        )
        ProductionEvent.objects.create(
            history=self.history,
            type="HA",
            date=timezone.now(),
            description="First shake",
            applied_scope="part",
            applied_scope_detail="south half only",
        )
        csv_text = self._service().generate_csv().getvalue().decode("utf-8-sig")
        self.assertIn("Traps: Pheromone lure, 24 traps, 180 caught", csv_text)
        self.assertIn("Treated scope: Part — rows 12-18", csv_text)
        self.assertIn("Applied scope: Part — south half only", csv_text)
