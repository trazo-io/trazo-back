"""
WSDA's Input Material List (AGR 2196, R 01/21), drafted from the plan in the form's own shape.

The form (live PDF read 2026-11-04, sha256 335707e6...): "Business Name", "Cert No", then "Your
input material list should be a complete list of all materials you plan to use in the coming year.
List materials you intend to use below, renewing operations do not need to list materials approved
for them in the previous year", a four-column table, and "alternative records may be used provided
they include all applicable information." Until now the WSDA packet carried the USDA Materials List
workbook, every product every year, in columns that are not WSDA's.

Pinned here:
  * the sheet ships only in a WSDA packet;
  * it leaves off a material no longer used, and one whose WSDA approval the operator recorded dated
    within the twelve months before the sheet; an undated approval, an older one or another agent's
    is listed;
  * every material it leaves off is named under the table, with why;
  * the Cert No is printed only from a certificate WSDA issued;
  * the purpose column speaks the form's words; the restriction column holds only what the operator
    stated.
"""

import io
import zipfile
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

import openpyxl

from certifications.models import OrganicSystemPlan, PlanMaterialEntry
from certifications.services.common_osp_workbooks import build_workbook, workbook_summary
from certifications.services.osp_module_pdf import generate_osp_packet
from company.models import Company, Establishment

WSDA = "Washington State Department of Agriculture"
CCOF = "CCOF Certification Services, LLC"
SHEET = "workbooks/Input Material List - WSDA AGR 2196.xlsx"
PURPOSE = "Intended purpose of the material (fertilizer, sanitizer, etc.)"


def _cells(data: bytes) -> list[list]:
    ws = openpyxl.load_workbook(io.BytesIO(data)).active
    return [[c for c in row] for row in ws.iter_rows(values_only=True)]


class _Farm(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Cascade Pear Co.")
        self.est = Establishment.objects.create(name="Wenatchee Block", company=self.company, state="WA")
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name=WSDA
        )
        self.today = timezone.localdate()

    def _entry(self, name, **fields):
        return PlanMaterialEntry.objects.create(osp=self.osp, product_name=name, **fields)

    def _sheet(self):
        return _cells(build_workbook(self.est, "wsda_agr_2196", osp=self.osp).getvalue())

    def _listed(self, cells):
        header = next(i for i, row in enumerate(cells) if row[0] == "Complete input name")
        out = []
        for row in cells[header + 1 :]:
            if row[0] is None:
                break
            out.append(row[0])
        return out

    def _footer(self, cells):
        return {row[0]: row[1] for row in cells if isinstance(row[0], str) and row[0].startswith("Not listed: ")}


class WhatTheSheetListsTests(_Farm):
    def test_the_form_lets_a_renewing_operation_leave_off_only_what_wsda_approved_last_year(self):
        recent = self.today - timedelta(days=200)
        self._entry(
            "Recent WSDA approval",
            agent_review="approved",
            agent_review_agent="wsda",
            agent_review_date=recent,
            agent_review_reference="2026 approved list",
        )
        self._entry(
            "Old WSDA approval",
            agent_review="approved",
            agent_review_agent="wsda",
            agent_review_date=self.today - timedelta(days=500),
        )
        self._entry(
            "Undated WSDA approval", agent_review="approved", agent_review_agent="wsda", agent_review_reference="x"
        )
        self._entry("CCOF approval", agent_review="approved", agent_review_agent="ccof", agent_review_date=recent)
        self._entry("Requested only", agent_review="requested", agent_review_agent="wsda")
        self._entry("Stopped using", status="discontinued")

        cells = self._sheet()
        self.assertEqual(
            sorted(self._listed(cells)),
            ["CCOF approval", "Old WSDA approval", "Requested only", "Undated WSDA approval"],
        )
        self.assertEqual(
            self._footer(cells),
            {
                "Not listed: Recent WSDA approval": (
                    f"approved by WSDA on {recent.isoformat()}, 2026 approved list, as recorded by the operator"
                ),
                "Not listed: Stopped using": "no longer used",
            },
        )

    def test_the_purpose_column_speaks_the_forms_words_and_restrictions_hold_only_a_statement(self):
        self._entry("SaniDate 5.0", category="post_harvest")
        self._entry("Kelp meal", category="other")
        cells = self._sheet()
        header = next(row for row in cells if row[0] == "Complete input name")
        purpose = header.index(PURPOSE)
        rows = {row[0]: row for row in cells if row[0] in ("SaniDate 5.0", "Kelp meal")}
        self.assertEqual(rows["SaniDate 5.0"][purpose], "Post-harvest sanitizer or wash-water additive")
        self.assertIsNone(rows["Kelp meal"][purpose], '"Other" tells a reviewer nothing; the cell stays blank')
        self.assertIsNone(rows["SaniDate 5.0"][3], "no restriction statement, so nothing is claimed")

    def test_the_restriction_column_counts_as_the_operators_to_answer(self):
        self._entry("SaniDate 5.0", category="post_harvest")
        summary = next(w for w in workbook_summary(self.est, osp=self.osp) if w["key"] == "wsda_agr_2196")
        kinds = {b["header"][:22]: b["kind"] for b in summary["blanks"]}
        self.assertEqual(kinds.get("How you ensure this ma"), "operator")


class HeaderTests(_Farm):
    def _header(self):
        cells = self._sheet()
        return {row[0]: row[1] for row in cells if row[0] in ("Business Name:", "Cert No:")}

    def test_a_wsda_certificate_number_is_printed(self):
        self.osp.approval_certificate_number, self.osp.approval_certifier_name = "WSDA-1234", WSDA
        self.osp.save(update_fields=["approval_certificate_number", "approval_certifier_name"])
        self.assertEqual(self._header(), {"Business Name:": "Cascade Pear Co.", "Cert No:": "WSDA-1234"})

    def test_another_agents_number_is_never_printed_as_the_wsda_cert_no(self):
        self.osp.approval_certificate_number, self.osp.approval_certifier_name = "CCOF-77", CCOF
        self.osp.save(update_fields=["approval_certificate_number", "approval_certifier_name"])
        self.assertEqual(self._header(), {"Business Name:": "Cascade Pear Co.", "Cert No:": None})


class WhichPacketCarriesItTests(_Farm):
    def test_only_a_wsda_packet_carries_the_sheet(self):
        for agent, expected in ((WSDA, True), (CCOF, False)):
            with self.subTest(agent=agent):
                self.osp.certifier_name = agent
                self.osp.save(update_fields=["certifier_name"])
                with zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp))) as zf:
                    self.assertEqual(SHEET in zf.namelist(), expected)
