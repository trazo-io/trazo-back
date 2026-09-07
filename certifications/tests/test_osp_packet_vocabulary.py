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
from certifications.services.packet_coverage import COVERAGE_PAGE_CERTIFIER, coverage_rows, exclusion_rows
from company.models import Company, Establishment
from product.models import Parcel


class PacketCoverageScopeTests(TestCase):
    """The coverage page speaks ONE certifier's form numbering — the one it says it speaks."""

    def _other_certifier_docs(self):
        from certifications.services.certifier_register import load_forms

        return {f.document_id for f in load_forms() if f.certifier != COVERAGE_PAGE_CERTIFIER and f.document_id}

    def test_a_second_certifier_is_registered(self):
        """Non-vacuity: with one certifier registered, the leak checks below prove nothing."""
        self.assertTrue(self._other_certifier_docs())

    def test_coverage_rows_carry_only_the_scoped_certifiers_forms(self):
        from certifications.services.certifier_register import load_forms

        scoped = {f.document_id for f in load_forms(COVERAGE_PAGE_CERTIFIER)}
        listed = {row.document_id for row in coverage_rows()}
        leaked = sorted(listed & (self._other_certifier_docs() - scoped))
        self.assertEqual(
            leaked,
            [],
            "the coverage page files every row under "
            f"{COVERAGE_PAGE_CERTIFIER.upper()}'s headings, so another agent's forms must not "
            f"appear in it: {', '.join(leaked)}",
        )

    def test_exclusions_stay_scoped_too(self):
        listed = {row.document_id for row in exclusion_rows()}
        self.assertEqual(sorted(listed & self._other_certifier_docs()), [])


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
            if row.location not in names:
                missing.append(f"{row.form} → {row.location}")
        self.assertEqual(
            missing,
            [],
            "the coverage page points at files this packet does not contain:\n  " + "\n  ".join(missing),
        )
