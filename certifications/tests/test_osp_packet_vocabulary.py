"""
The OSP packet must name things the way the certifying agent does, and its coverage page must
describe the ZIP it actually ships.

WHY (2026-09-07), from a vocabulary audit of a real generated packet:

1. `coverage_rows()` called `load_forms()` with no argument, returning EVERY registered
   certifier's forms, while the coverage page files them under CCOF headings. Once WSDA was
   registered, five Washington State forms (AGR 2121 Crop Producer OSP, 2196 Input Material List,
   2262 Previous Land Use, 2264 Site Application, 2516 Site Update) printed under
   "Compared against, but not generated — file CCOF's own form". Telling an operation to file a
   WSDA form with CCOF is worse than saying nothing. The module has always documented its scope
   as `COVERAGE_PAGE_CERTIFIER`; `exclusion_rows()` honoured it and `coverage_rows()` did not.

2. The four Common OSP workbooks shipped as `workbooks/{spec.key}.xlsx` —
   `field_and_crop_information.xlsx`, `crop_livestock_product_list.xlsx`. Every other document in
   the packet is named for what it is; these were named for our identifiers, in the one place a
   reader has nothing else to go on.

3. The workbooks were absent from a page titled "What this packet covers".

The invariant behind all three: a reader opening this ZIP navigates by their own form names, and
the contents page must agree with the contents.
"""

import io
import zipfile

from django.test import TestCase
from django.utils import timezone

from certifications.models import OrganicSystemPlan
from certifications.services.common_osp_workbooks import WORKBOOKS
from certifications.services.osp_module_pdf import _workbook_filename, generate_osp_packet
from certifications.services.packet_coverage import FALLBACK_CERTIFIER, coverage_rows, exclusion_rows
from company.models import Company, Establishment
from product.models import Parcel


class PacketCoverageScopeTests(TestCase):
    """The coverage page speaks ONE certifier's form numbering — the one it says it speaks.

    🔴 2026-09-07 — that certifier is now the OPERATION'S, resolved from its records, rather than
    the hardcoded `COVERAGE_PAGE_CERTIFIER = "ccof"` this file was written against. The invariant
    did not change and is now checked for every registered agent instead of one: whichever
    numbering a packet speaks, no other agent's document ids may appear in it.
    """

    def _docs_of_others(self, certifier):
        from certifications.services.certifier_register import load_forms

        return {f.document_id for f in load_forms() if f.certifier != certifier and f.document_id}

    def _registered(self):
        from certifications.services.certifier_register import certifiers

        return certifiers()

    def test_a_second_certifier_is_registered(self):
        """Non-vacuity: with one certifier registered, the leak checks below prove nothing."""
        self.assertGreater(len(self._registered()), 1)
        self.assertTrue(self._docs_of_others(FALLBACK_CERTIFIER))

    def test_coverage_rows_carry_only_the_scoped_certifiers_forms(self):
        from certifications.services.certifier_register import load_forms

        for certifier in self._registered():
            scoped = {f.document_id for f in load_forms(certifier)}
            listed = {row.document_id for row in coverage_rows(certifier)}
            leaked = sorted(listed & (self._docs_of_others(certifier) - scoped))
            self.assertEqual(
                leaked,
                [],
                f"the coverage page files every row under {certifier.upper()}'s headings, so "
                f"another agent's forms must not appear in it: {', '.join(leaked)}",
            )

    def test_exclusions_stay_scoped_too(self):
        for certifier in self._registered():
            listed = {row.document_id for row in exclusion_rows(certifier)}
            self.assertEqual(sorted(listed & self._docs_of_others(certifier)), [], certifier)


class WorkbookNamingTests(TestCase):
    def test_every_workbook_is_named_for_its_form_not_its_key(self):
        for spec in WORKBOOKS:
            name = _workbook_filename(spec)
            self.assertTrue(name.endswith(".xlsx"))
            self.assertNotIn(spec.key, name, f"{name} is the code key, not the form name")
            self.assertNotIn("/", name, "a slash would nest the workbook in a phantom folder")
            self.assertTrue(
                name.startswith(spec.title.replace("/", "-")[:12]),
                f"{name} does not lead with the form title {spec.title!r}",
            )

    def test_the_slash_in_a_title_is_hyphenated_not_nested(self):
        spec = next(w for w in WORKBOOKS if "/" in w.title)
        self.assertEqual(_workbook_filename(spec), "Crop-Livestock Product List.xlsx")


class PacketContentsMatchTheCoveragePageTests(TestCase):
    """ "What this packet covers" must describe the packet it ships with."""

    def setUp(self):
        company = Company.objects.create(name="Vocabulary Farm Co")
        self.establishment = Establishment.objects.create(name="Vocab Ranch", company=company, state="WA")
        Parcel.objects.create(name="North Block", establishment=self.establishment, area=8.0)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.establishment,
            version_number=1,
            status="active",
            submitted_at=timezone.now(),
        )

    def _packet(self):
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(self.osp)))

    def test_every_workbook_ships_under_its_form_name(self):
        names = set(self._packet().namelist())
        for spec in WORKBOOKS:
            entry = f"workbooks/{_workbook_filename(spec)}"
            self.assertIn(entry, names, "the packet does not contain the workbook it is named for")

    def test_the_coverage_page_names_files_that_exist_in_the_zip(self):
        names = set(self._packet().namelist())
        missing = []
        for row in coverage_rows():
            if not row.generated or not row.location:
                continue
            # One row deliberately describes a per-parcel family rather than a single file.
            if "<parcel>" in row.location:
                self.assertTrue(
                    any(n.startswith("parcels/parcel-application-") for n in names),
                    "the coverage page promises parcel applications and the packet has none",
                )
                continue
            # A form answered by more than one module carries its locations joined by "; ".
            for location in row.location.split("; "):
                if location not in names:
                    missing.append(f"{row.form} → {location}")
        self.assertEqual(
            missing,
            [],
            "the coverage page points at files this packet does not contain:\n  " + "\n  ".join(missing),
        )
