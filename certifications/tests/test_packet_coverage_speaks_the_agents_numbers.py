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
from unittest.mock import patch

from django.test import TestCase

from certifications.models import Certification, OrganicSystemPlan
from certifications.services.certifier_register import PACKET_DOCUMENTS, _packet_documents, load_forms
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

    def test_an_agent_with_no_register_is_known_but_still_falls_back(self):
        """OCI is a real agent the picker offers, with no form register. It resolves to its own
        slug (so the page can name it), and the packet still falls back to CCOF numbering."""
        osp = self._plan(certifier="Organic Certifiers, Inc.")
        self.assertEqual(resolve_certifier(osp), "oci")
        self.assertEqual(packet_certifier(osp), ("ccof", False))

    def test_a_near_miss_resolves_to_nothing_rather_than_a_guess(self):
        """⛔ never fuzzy. A near-match that renumbers a packet for the wrong agent is worse
        than falling back and saying so."""
        osp = self._plan(certifier="Organic Certifier")
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
        # Each agent's page against that agent's OWN packet (2026-09-10). An agent's own sheet —
        # OTCO FACT-04 — ships only in that agent's ZIP, so one WSDA packet cannot vouch for the
        # locations OTCO's coverage page prints.
        osp = self._plan(certifier="WSDA")
        for certifier, agent in (("ccof", "CCOF"), ("wsda", "WSDA"), ("otco", "Oregon Tilth Certified Organic")):
            osp.approval_certifier_name = agent
            osp.save(update_fields=["approval_certifier_name"])
            names = set(zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp))).namelist())
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
        # it. What remained was AGR 2516, which maps to no module — and since 2026-09-10 is
        # answered by the packet's update pages through `packet_documents`, so nothing remains.
        self.assertEqual(unreviewed_form_count("wsda"), 0)
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
        self.assertNotIn("ORGB26", wsda_docs)
        self.assertNotIn("ORGB32", wsda_docs)

    def test_neither_ccof_nor_wsda_scope_leaks_into_an_otco_packet(self):
        otco_docs = {row.document_id for row in exclusion_rows("otco")} | {
            row.document_id for row in coverage_rows("otco")
        }
        self.assertEqual([d for d in otco_docs if "NOPB" in d or "ORGB" in d or d.startswith("AGR 2")], [])


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
        deliberately — "same reasoning as CCOF's Handler/Processor OSP forms (H-series, ORGB32)"
        is the register author explaining a decision, not an instruction to file ORGB32. What
        must never happen is a CCOF document id appearing where this page names a form."""
        osp = self._plan(certifier="WSDA")
        certifier, _ = packet_certifier(osp)
        ids = {row.document_id for row in coverage_rows(certifier)}
        ids |= {row.document_id for row in exclusion_rows(certifier)}
        self.assertEqual([i for i in ids if "NOPB" in i or "ORGB" in i], [])

    def test_a_ccof_operation_still_reads_ccof_form_numbers(self):
        text = self._coverage_text("CCOF")
        self.assertIn("ORGB49", text)
        self.assertIn("CCOF's own form numbering", text)

    def test_an_otco_operation_reads_otco_form_numbers(self):
        """The third agent. Registered 2026-09-09 as a folder plus three one-line code touches
        (alias table, page label, marker row) — this test is what makes "a folder, not a code
        change" a checked claim rather than a docstring."""
        text = self._coverage_text("Oregon Tilth Certified Organic")
        self.assertIn("FACT-04", text)
        self.assertIn("Oregon Tilth's own form numbering", text)
        self.assertNotIn("Otco", text)  # the slug must never print as a title-cased word

    def test_the_fact_04_sheet_ships_only_in_an_otco_packet(self):
        """OTCO's own form travels with OTCO's packet and nowhere else — a CCOF or WSDA reviewer
        handed an Oregon Tilth table would read it as a misfiled document. Listed on the coverage
        page under the same filter, so the page never names a sheet the ZIP lacks or vice versa."""
        fact = "workbooks/Field Acreage Crop Table - Form FACT-04.xlsx"
        for agent, expected in (("Oregon Tilth Certified Organic", True), ("WSDA", False), ("CCOF", False)):
            osp = self._plan(certifier=agent, version=1)
            data = generate_osp_packet(osp)
            zf = zipfile.ZipFile(io.BytesIO(data))
            self.assertEqual(fact in zf.namelist(), expected, agent)
            page = _pdf_text(zf.read("04-coverage-and-scope.pdf"))
            self.assertEqual("Form FACT-04.xlsx" in page, expected, agent)
            osp.delete()

    def test_the_integrity_db_spelling_of_oregon_tilth_resolves(self):
        osp = self._plan(certifier="Oregon Tilth Certified Organic")
        self.assertEqual(resolve_certifier(osp), "otco")
        self.assertEqual(packet_certifier(osp), ("otco", True))

    def test_an_unregistered_agent_reads_no_other_agents_numbering(self):
        """🔴 Rewritten 2026-09-30 (OSP alignment audit, T23).

        This test used to REQUIRE "only the numbering differs": an OCI packet was numbered against
        CCOF's forms under that sentence, and the page repeated CCOF's own scope reasons ("file the
        affidavit with CCOF directly"). The sentence was never checked (OCI's annual update is its
        own form with its own scope, sales and declaration sections) and the reasons sent the
        operation to the wrong agent. A packet for an agent Trazo holds no register for now lists
        its documents in Trazo's own words and borrows no agent's numbering.
        """
        for agent in ("Organic Certifiers, Inc.", "Midwest Organic Services Association, Inc.", "Blue Heron Organic"):
            with self.subTest(agent=agent):
                text = self._coverage_text(agent)
                # The reviewer is told whose packet this is, not left to guess which agent was meant.
                self.assertIn(f"Trazo does not hold {agent}'s form list", text)
                self.assertIn("supporting material", text)
                self.assertNotIn("CCOF", text)
                self.assertNotIn("only the numbering differs", text)
                self.assertNotIn("NOPB", text)
                self.assertNotIn("ORGB", text)
                self.assertNotIn("Forms Trazo does not generate", text)
                OrganicSystemPlan.objects.filter(establishment=self.est).delete()

    def test_a_plan_naming_no_agent_reads_no_agents_numbering_either(self):
        text = self._coverage_text("")
        self.assertIn("No certifying agent is named on this operation's records", text)
        self.assertNotIn("CCOF", text)


class RenewalApplicationIsAnsweredByPacketDocumentsTests(_AgentFarm):
    """OTCO's OSP Update Form and WSDA AGR 2516 — each agent's renewal/update application.

    🔴 2026-09-10, desk read of an OTCO packet. Both forms are answered by 02-annual-update.pdf and
    03-change-notifications.pdf (`OSPAnnualUpdate`, `OSPChangeNotification` — models, not a module),
    so the register could only hold them as drafts, and the coverage page closed with "1 further
    Oregon Tilth form have not yet been compared against this plan" — about the renewal application
    itself, on the page a reviewer navigates by. `packet_documents` is the state that was missing.
    """

    def test_each_update_form_points_at_the_update_pages(self):
        """Where the supporting material is. 🔴 Since 2026-09-30 (audit T20) that is ALL it says:
        the form is the agent's renewal, filed with the agent, and the page lists it under
        "Forms the operation files with", never as a form the packet answers.

        2026-10-01 (Phase 3): every agent's renewal forms, not OTCO's and WSDA 2516 alone. CCOF's
        Annual Renewal Contract and WSDA's AGR 2521 fee form are registered, and each lists the
        packet document that carries the part of it Trazo holds."""
        from certifications.services.packet_coverage import form_coverage

        for certifier, document_id, agent, location in (
            (
                "otco",
                "OSP Update Form",
                "Oregon Tilth Certified Organic",
                "02-annual-update.pdf; 03-change-notifications.pdf",
            ),
            (
                "wsda",
                "AGR 2516",
                "Washington State Department of Agriculture",
                "02-annual-update.pdf; 03-change-notifications.pdf",
            ),
            ("wsda", "AGR 2521", "Washington State Department of Agriculture", "02-annual-update.pdf"),
            ("ccof", "Annual Renewal Contract", "CCOF", "02-annual-update.pdf; 02s-renewal-status-and-routing.pdf"),
        ):
            row = next(r for r in coverage_rows(certifier) if r.document_id == document_id)
            self.assertEqual(row.location, location, (certifier, document_id))
            osp = self._plan(certifier=agent)
            standing = next(f.standing for f in form_coverage(osp, certifier) if f.document_id == document_id)
            self.assertEqual(standing, "filed_with_agent", (certifier, document_id))
            osp.delete()

    def test_no_otco_form_is_left_uncompared(self):
        self.assertEqual(unreviewed_form_count("otco"), 0)

    def test_packet_documents_match_the_zip(self):
        """The loader validates `packet_documents` against PACKET_DOCUMENTS; this pins that tuple to
        the names `generate_osp_packet` writes, so neither can be renamed alone."""
        osp = self._plan(certifier="Oregon Tilth Certified Organic")
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        top_level = {name for name in zf.namelist() if "/" not in name and name.endswith(".pdf")}
        self.assertEqual(top_level, set(PACKET_DOCUMENTS))
        cited = {name for form in load_forms("otco") for name in form.packet_documents if name.startswith("workbooks/")}
        self.assertTrue(cited, "no OTCO form cites a workbook — FACT-04 should")
        self.assertLessEqual(cited, set(zf.namelist()))

    def test_the_loader_refuses_a_document_the_packet_does_not_write(self):
        with self.assertRaisesRegex(ValueError, "names no packet document: 02-annual-update-v2.pdf"):
            _packet_documents({"packet_documents": ["02-annual-update-v2.pdf"]}, "OSP-Update-Form.yaml")
        self.assertEqual(
            _packet_documents({"packet_documents": ["02-annual-update.pdf"]}, "x.yaml"),
            ("02-annual-update.pdf",),
        )

    def test_fact_04_points_at_its_own_workbook_first(self):
        """The desk read (2026-09-10) found FACT-04 routed to the parcel PDFs while the packet
        shipped a FACT-04 workbook that mirrors OTCO's form column for column."""
        row = next(r for r in coverage_rows("otco") if r.document_id == "FACT-04")
        self.assertTrue(
            row.location.startswith("workbooks/Field Acreage Crop Table - Form FACT-04.xlsx; "), row.location
        )

    def test_a_workbook_is_accepted_only_for_an_agent_whose_packet_carries_it(self):
        fact = {"packet_documents": ["workbooks/Field Acreage Crop Table - Form FACT-04.xlsx"]}
        self.assertEqual(_packet_documents(fact, "x.yaml", "otco"), tuple(fact["packet_documents"]))
        with self.assertRaisesRegex(ValueError, "names no packet document"):
            _packet_documents(fact, "x.yaml", "wsda")

    def test_the_uncompared_count_agrees_with_its_number(self):
        """It printed "1 further Oregon Tilth form have not yet been compared" — a plural verb for
        one form, on the page a reviewer reads first."""
        osp = self._plan(certifier="Oregon Tilth Certified Organic")
        cases = (
            (1, "1 further Oregon Tilth form has not yet been compared against this plan, and is not stated"),
            (2, "2 further Oregon Tilth forms have not yet been compared against this plan, and are not stated"),
        )
        for count, expected in cases:
            with (
                self.subTest(count=count),
                patch("certifications.services.packet_coverage.unreviewed_form_count", return_value=count),
            ):
                zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
                page = " ".join(_pdf_text(zf.read("04-coverage-and-scope.pdf")).split())
                self.assertIn(expected, page)
