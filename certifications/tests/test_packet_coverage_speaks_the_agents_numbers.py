"""The coverage page names the operation's OWN certifying agent's forms, and real files.

WHY THIS EXISTS
---------------
Found 2026-09-07 by walking a WSDA-certified Washington orchard end to end and reading the packet
it produced. `04-coverage-and-scope.pdf` — the page whose entire premise is "a reviewer navigates
by their own form numbers" — was numbered to CCOF for every operation, because `_PACKET_LOCATION`
was a hand-written dict of 16 CCOF document ids and `COVERAGE_PAGE_CERTIFIER` was a constant.

The register already held WSDA's 24 forms with their AGR numbers and the `trazo_module` that
answers each, checked against `MODULE_REGISTRY` by CI. The page was a duplicate of data we already
guarded, pinned to the wrong agent for the primary market.

Two classes of defect this file exists to prevent:

  * a location string that names a file the ZIP does not contain — the coverage page and
    `generate_osp_packet` must agree, and the only way they can drift is if one hardcodes what the
    other computes;
  * a form stated as absent when the packet answers it. Three rules guard that (DRAFT, UMBRELLA,
    PRESENT — see `packet_coverage`), and each one is here because the register's raw shape would
    otherwise print a false sentence to a certifier.
"""

import io
import zipfile

from django.test import TestCase

from certifications.models import Certification, OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_coverage import (
    coverage_rows,
    exclusion_rows,
    packet_certifier,
    resolve_certifier,
    unreviewed_form_count,
)
from company.models import Company, Establishment
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text


class _AgentFarm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Cascade Ridge Orchards LLC")
        self.user = User.objects.create_user(email="agent@test.com", password="x", first_name="Dale")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Squilchuck Home Ranch", company=self.company)

    def _plan(self, *, certifier="", version=1, status="active"):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=version,
            status=status,
            approval_certifier_name=certifier,
            approval_certificate_number="WA-ORG-2026-4471" if certifier else "",
        )


class ResolvingTheAgentTests(_AgentFarm):
    def test_the_name_typed_at_the_activation_gate_resolves(self):
        osp = self._plan(certifier="Washington State Department of Agriculture")
        self.assertEqual(resolve_certifier(osp), "wsda")

    def test_resolution_ignores_case_and_punctuation(self):
        osp = self._plan(certifier="  WSDA Organic Program.  ")
        self.assertEqual(resolve_certifier(osp), "wsda")

    def test_a_farm_profile_certification_row_resolves_when_no_plan_names_one(self):
        osp = self._plan()
        Certification.objects.create(
            establishment=self.est,
            certification_type="usda_organic",
            certification_number="CCOF-2026-1234",
            certifier_name="CCOF",
        )
        self.assertEqual(resolve_certifier(osp), "ccof")

    def test_an_unregistered_agent_resolves_to_nothing_rather_than_a_guess(self):
        """⛔ never fuzzy. A near-match that renumbers a packet for the wrong agent is worse
        than falling back and saying so."""
        osp = self._plan(certifier="Organic Certifiers, Inc.")
        self.assertIsNone(resolve_certifier(osp))

    def test_the_newest_version_of_the_lineage_wins(self):
        self._plan(certifier="CCOF", version=1, status="superseded")
        v2 = self._plan(certifier="WSDA", version=2)
        self.assertEqual(resolve_certifier(v2), "wsda")

    def test_an_unresolved_agent_falls_back_and_says_it_is_a_fallback(self):
        osp = self._plan(certifier="Organic Certifiers, Inc.")
        certifier, is_own = packet_certifier(osp)
        self.assertEqual(certifier, "ccof")
        self.assertFalse(is_own)

    def test_a_resolved_agent_is_reported_as_the_operations_own(self):
        osp = self._plan(certifier="WSDA")
        self.assertEqual(packet_certifier(osp), ("wsda", True))


class EveryLocationNamesARealFileTests(_AgentFarm):
    """The coverage page and the ZIP must agree — this is the drift the old dict invited."""

    def _names_in_packet(self):
        osp = self._plan(certifier="WSDA")
        data = generate_osp_packet(osp)
        return set(zipfile.ZipFile(io.BytesIO(data)).namelist())

    def test_every_generated_location_is_an_entry_in_the_zip(self):
        names = self._names_in_packet()
        for certifier in ("ccof", "wsda", "otco"):
            for row in coverage_rows(certifier):
                if not row.generated:
                    continue
                for location in row.location.split("; "):
                    if location.startswith("parcels/"):
                        # Parcel applications are named per parcel; this farm has none, so the
                        # pattern is asserted rather than the file.
                        self.assertIn("<parcel>", location, f"{certifier}: {row.form}")
                        continue
                    self.assertIn(location, names, f"{certifier}: {row.form} -> {location}")

    def test_every_module_pdf_in_the_zip_is_named_on_the_page(self):
        """A file a reviewer is holding that the coverage page never mentions is its own defect."""
        names = {n for n in self._names_in_packet() if n.startswith("modules/")}
        listed = {location for row in coverage_rows("wsda") if row.generated for location in row.location.split("; ")}
        self.assertEqual(names - listed, set())


class TheNotGeneratedListMakesNoFalseStatementsTests(_AgentFarm):
    def test_a_draft_register_entry_is_never_listed_as_absent(self):
        """WSDA §F Weed Management is a draft entry with no module. The packet answers weed
        management in G5.0, so printing it as not generated would be false."""
        absent = {row.form for row in coverage_rows("wsda") if not row.generated}
        self.assertNotIn("F Weed Management", absent)
        self.assertNotIn("H Disease Management", absent)

    def test_the_umbrella_osp_form_is_never_listed_as_absent(self):
        """AGR 2121 'Crop Producer Organic System Plan' IS this packet, section by section."""
        absent = {row.form for row in coverage_rows("wsda") if not row.generated}
        self.assertNotIn("Crop Producer Organic System Plan", absent)

    def test_a_complete_entry_with_no_module_is_stated_as_absent(self):
        absent = {row.form for row in coverage_rows("wsda") if not row.generated}
        self.assertIn("S Fungi / Mushroom Production", absent)

    def test_the_unreviewed_count_excludes_forms_already_listed(self):
        """It printed "20 further WSDA forms have not yet been compared" on a page that had just
        listed 20 of them by name — most WSDA entries are drafts that DO carry a module."""
        listed = {row.form for row in coverage_rows("wsda")}
        self.assertGreater(len(listed), unreviewed_form_count("wsda"))
        # 🔴 2026-09-07 — this asserted 4, and three of those four (§F Weed, §H Disease,
        # §I Farm Equipment) were forms the register HAD compared, in 22 rows the packet
        # answers inside G5.0 / G6.0 / G6.1. They counted as unreviewed only because they
        # declared no `trazo_module`. The test pinned the defect; declaring the modules fixed
        # it. What remains is AGR 2516, which genuinely maps to no module.
        self.assertEqual(unreviewed_form_count("wsda"), 1)
        for compared in ("F Weed", "H Disease", "I Farm Equipment"):
            self.assertTrue(
                any(compared in row.form for row in coverage_rows("wsda")),
                f"{compared} was compared question by question — it must not read as unreviewed",
            )

    def test_an_exclusion_is_never_named_for_a_form_the_packet_contains(self):
        for certifier in ("ccof", "wsda", "otco"):
            present = {row.document_id for row in coverage_rows(certifier) if row.generated and row.document_id}
            excluded = {row.document_id for row in exclusion_rows(certifier)}
            self.assertEqual(present & excluded, set(), certifier)

    def test_ccof_scope_never_leaks_into_a_wsda_packet(self):
        wsda_docs = {row.document_id for row in exclusion_rows("wsda")}
        self.assertNotIn("NOPB26", wsda_docs)
        self.assertNotIn("NOPB32", wsda_docs)

    def test_neither_ccof_nor_wsda_scope_leaks_into_an_otco_packet(self):
        otco_docs = {row.document_id for row in exclusion_rows("otco")} | {
            row.document_id for row in coverage_rows("otco")
        }
        self.assertEqual([d for d in otco_docs if "NOPB" in d or d.startswith("AGR 2")], [])


class ThePageSaysWhoseNumbersItSpeaksTests(_AgentFarm):
    def _coverage_text(self, certifier):
        osp = self._plan(certifier=certifier)
        data = generate_osp_packet(osp)
        return _pdf_text(zipfile.ZipFile(io.BytesIO(data)).read("04-coverage-and-scope.pdf"))

    def test_a_wsda_operation_reads_wsda_form_numbers(self):
        text = self._coverage_text("Washington State Department of Agriculture")
        self.assertIn("AGR 2264", text)
        self.assertIn("AGR 2196", text)
        self.assertIn("WSDA's own form numbering", text)

    def test_a_wsda_operation_is_not_told_to_file_ccof_paperwork(self):
        """Asserted on the ROWS, not the prose. WSDA's own scope file cross-references CCOF
        deliberately — "same reasoning as CCOF's Handler/Processor OSP forms (H-series, NOPB32)"
        is the register author explaining a decision, not an instruction to file NOPB32. What
        must never happen is a CCOF document id appearing where this page names a form."""
        osp = self._plan(certifier="WSDA")
        certifier, _ = packet_certifier(osp)
        ids = {row.document_id for row in coverage_rows(certifier)}
        ids |= {row.document_id for row in exclusion_rows(certifier)}
        self.assertEqual([i for i in ids if "NOPB" in i], [])

    def test_a_ccof_operation_still_reads_ccof_form_numbers(self):
        text = self._coverage_text("CCOF")
        self.assertIn("NOPB49", text)
        self.assertIn("CCOF's own form numbering", text)

    def test_an_otco_operation_reads_otco_form_numbers(self):
        """The third agent. Registered 2026-09-09 as a folder plus three one-line code touches
        (alias table, page label, marker row) — this test is what makes "a folder, not a code
        change" a checked claim rather than a docstring."""
        text = self._coverage_text("Oregon Tilth Certified Organic")
        self.assertIn("FACT-04", text)
        self.assertIn("Oregon Tilth's own form numbering", text)
        self.assertNotIn("Otco", text)  # the slug must never print as a title-cased word

    def test_the_integrity_db_spelling_of_oregon_tilth_resolves(self):
        osp = self._plan(certifier="Oregon Tilth Certified Organic")
        self.assertEqual(resolve_certifier(osp), "otco")
        self.assertEqual(packet_certifier(osp), ("otco", True))

    def test_an_unrecognised_agent_is_told_which_numbering_it_is_reading(self):
        text = self._coverage_text("Organic Certifiers, Inc.")
        self.assertIn("not one Trazo holds a form register for", text)
        self.assertIn("only the numbering differs", text)
