"""Oregon Tilth's renewal form asks which OSP sections changed; the packet answers from the versions.

WHY THIS EXISTS
---------------
OTCO's OSP Update Form (Rev. 2024/09/20) Step 4: "The OSP for my operation needs to be updated.
Please list updated OSP sections and attach (i.e., pest control, sanitation, labels, farm
practices, field and crop information, new land, etc.)". The register row for it was `partial`:
02 listed the year's changes in Trazo's own section keys, and the packet attached every module, so
a reviewer mapped keys and sifted the ZIP.

The register's first proposed fix, a form code beside each § 205.406(a)(2) entry, had nothing to
read: the annual-update card stores additions and deletions as free-text lines. The two plan
versions the update moved between do say what changed, so 02s compares them and names each
changed section by OTCO's form code.

The list prints only for OTCO. CCOF's Annual Renewal Contract Step 2 is a two-way election, and
WSDA's AGR 2516 asks per site about crops and acreage; neither asks for a list of sections.
"""

import io
import zipfile
from datetime import date, datetime
from datetime import timezone as dt_tz

from django.test import TestCase

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate, PlanMaterialEntry
from certifications.services.annual_update_filing import file_filing, sign_filing
from certifications.services.certifier_register import load_forms
from certifications.services.osp_fork import fork_plan
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_coverage import changed_sections
from certifications.services.plan_version_changes import changed_module_keys, changed_section_keys
from company.models import Company, Establishment
from product.models import Parcel
from users.models import User

from .test_renewal_packet_contents import _pdf_text

OTCO = "Oregon Tilth Certified Organic"
HEADING = "OSP Update Form Step 4: plan sections whose answers changed"


def _answer(osp, module_key, question, value, at="2026-01-05T10:00:00Z"):
    responses = osp.module_responses or {"schema_version": 1, "modules": {}, "parcel_modules": {}}
    module = responses.setdefault("modules", {}).setdefault(module_key, {"status": "in_progress", "answers": {}})
    module.setdefault("answers", {})[question] = {"value": value, "at": at}
    osp.module_responses = responses
    osp.save(update_fields=["module_responses"])


class _Renewal(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="step4@test.com", password="x", first_name="Ana", last_name="Diaz")
        company = Company.objects.create(name="Step Four Orchards LLC")
        self.est = Establishment.objects.create(name="Step Four Orchard", company=company)

    def _versions(self, certifier=OTCO):
        v1 = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name=certifier,
            submitted_at=datetime(2026, 1, 10, tzinfo=dt_tz.utc),
        )
        _answer(v1, "g5_0_pest", "pest_prevention", "Hedgerows and owl boxes")
        v2 = fork_plan(v1, self.user)
        OSPAnnualUpdate.objects.create(
            prior_osp=v1,
            new_osp=v2,
            reporting_year=2027,
            changes_summary="Pest plan.",
            prior_plan_basis=OSPAnnualUpdate.PRIOR_BASIS_TRAZO_VERSION,
        )
        return v1, v2

    def _supplement(self, osp) -> str:
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp)))
        return _pdf_text(zf.read("02s-renewal-status-and-routing.pdf"))


def _stored(*plans):
    """The versions as stored. `fork_plan` hands the clone the source's own `module_responses` dict,
    so an in-memory edit of one would show on both; the packet always reads them from the database."""
    return [OrganicSystemPlan.objects.get(pk=p.pk) for p in plans]


class ComparisonTests(_Renewal):
    def test_a_fork_with_no_edits_changes_nothing(self):
        v1, v2 = self._versions()
        self.assertEqual(changed_module_keys(*_stored(v1, v2)), [])

    def test_a_changed_answer_is_a_change(self):
        v1, v2 = self._versions()
        _answer(v2, "g5_0_pest", "pest_prevention", "Hedgerows, owl boxes and kaolin clay")
        self.assertEqual(changed_module_keys(*_stored(v1, v2)), ["g5_0_pest"])

    def test_resaving_the_same_value_is_not_a_change(self):
        """Every answer carries its write time; a re-save moves it and leaves the plan as it was."""
        v1, v2 = self._versions()
        _answer(v2, "g5_0_pest", "pest_prevention", "Hedgerows and owl boxes", at="2026-11-02T08:00:00Z")
        self.assertEqual(changed_module_keys(*_stored(v1, v2)), [])

    def test_a_materials_row_added_on_the_new_version_changes_the_materials_section(self):
        v1, v2 = self._versions()
        PlanMaterialEntry.objects.create(osp=v2, product_name="Gypsum", reason_for_use="Calcium", created_by=self.user)
        self.assertEqual(changed_module_keys(*_stored(v1, v2)), ["materials_application"])

    def test_carried_materials_rows_are_not_a_change(self):
        """Fork copies the rows with new ids and a new author; the plan says the same thing."""
        v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        PlanMaterialEntry.objects.create(osp=v1, product_name="Gypsum", reason_for_use="Calcium", created_by=self.user)
        other = User.objects.create_user(email="other@test.com", password="x")
        v2 = fork_plan(v1, other)
        self.assertEqual(changed_module_keys(*_stored(v1, v2)), [])


def _section(osp, key, **fields):
    sections = dict(osp.sections or {})
    section = dict(sections.get(key) or {})
    section.update(fields)
    sections[key] = section
    osp.sections = sections
    osp.save(update_fields=["sections"])


class SectionComparisonTests(_Renewal):
    """Review of back #216: the § 205.201(a) narratives and § 11 confirmations are edited without
    any module answer moving, so a module-only comparison printed "no change" beside a rewritten 01."""

    def test_a_rewritten_manual_narrative_is_a_change(self):
        v1, v2 = self._versions()
        _section(v2, "recordkeeping_description", narrative_manual="Paper field logs moved to Trazo in 2026.")
        self.assertEqual(changed_section_keys(*_stored(v1, v2)), ["recordkeeping_description"])
        text = " ".join(self._supplement(v2).split())
        self.assertIn("§ 205.201(a)(4) Recordkeeping System", text)
        self.assertIn("01-organic-system-plan.pdf", text.split(HEADING)[1])
        self.assertNotIn("No section's answers differ", text)

    def test_carried_confirmations_are_not_a_change_and_an_untick_is(self):
        v1 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=OTCO
        )
        tick = {"confirmed": True, "confirmed_at": "2026-01-05T10:00:00Z", "confirmed_by": self.user.id}
        _section(v1, "recordkeeping_description", common_osp_records={"invoices": tick, "harvest": dict(tick)})
        v2 = fork_plan(v1, self.user)
        # The fork marks each tick `carried_from_version`; the plan still says the same thing.
        self.assertEqual(changed_section_keys(*_stored(v1, v2)), [])
        v2 = OrganicSystemPlan.objects.get(pk=v2.pk)
        confirmations = dict(v2.sections["recordkeeping_description"]["common_osp_records"])
        confirmations.pop("harvest")
        _section(v2, "recordkeeping_description", common_osp_records=confirmations)
        self.assertEqual(changed_section_keys(*_stored(v1, v2)), ["recordkeeping_description"])


class OtcoSupplementTests(_Renewal):
    def test_a_changed_section_is_named_by_otcos_form_code_and_its_packet_file(self):
        _v1, v2 = self._versions()
        _answer(v2, "g5_0_pest", "pest_prevention", "Hedgerows, owl boxes and kaolin clay")
        PlanMaterialEntry.objects.create(osp=v2, product_name="Gypsum", reason_for_use="Calcium", created_by=self.user)
        text = self._supplement(v2)
        self.assertIn(HEADING, text)
        self.assertIn("Compared from plan v1 to v2", text)
        self.assertIn("C5 ", text)
        self.assertIn("C11 ", text)
        self.assertIn("modules/G5_0.pdf", text)
        # Numeric order, as OTCO numbers its forms: C5 before C11.
        self.assertLess(text.index("C5 "), text.index("C11 "))
        # A section with no change is not listed.
        self.assertNotIn("C12 ", text.split(HEADING)[1])

    def test_each_listed_form_maps_a_changed_module_in_the_register(self):
        """The list is the register read in reverse; a form appears only for a module it claims."""
        _v1, v2 = self._versions()
        _answer(v2, "g5_0_pest", "pest_prevention", "Kaolin clay")
        result = changed_sections(v2)
        otco = {f"{f.code} {f.title}": f.trazo_modules for f in load_forms("otco") if f.code}
        self.assertTrue(result.forms)
        for label, _files in result.forms:
            self.assertIn("g5_0_pest", otco[label], label)

    def test_no_change_says_so(self):
        _v1, v2 = self._versions()
        self.assertIn("No section's answers differ between v1 and v2", self._supplement(v2))

    def test_a_reaffirmation_has_no_second_version_to_compare(self):
        v1 = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="active", certifier_name=OTCO
        )
        OSPAnnualUpdate.objects.create(prior_osp=v1, reporting_year=2027, changes_summary="No changes.")
        text = self._supplement(v1)
        self.assertIn(HEADING, text)
        self.assertIn("did not create a new plan version", text)

    def test_land_is_stated_as_outside_the_comparison_with_the_operators_own_dates(self):
        _v1, v2 = self._versions()
        Parcel.objects.create(
            name="North Block", establishment=self.est, area=4.0, date_began_managing=date(2026, 3, 1)
        )
        Parcel.objects.create(name="Home Block", establishment=self.est, area=9.0, date_began_managing=date(2019, 5, 1))
        Parcel.objects.create(name="River Block", establishment=self.est, area=2.0)
        text = " ".join(self._supplement(v2).split())
        self.assertIn("does not show new land", text)
        # Edits to a parcel already on the plan are stated too, by the forms that ask for them.
        self.assertIn("edits to an existing parcel's application (C2, FACT-04)", text)
        self.assertIn("on or after 2026-01-10", text)
        begun = text.split("on or after 2026-01-10")[1].split("Management start date not stated")[0]
        self.assertIn("North Block", begun)
        self.assertNotIn("Home Block", begun)
        # No date is "not stated", never "not new".
        self.assertIn("Management start date not stated: River Block", text)

    def test_a_packet_for_the_prior_version_points_to_the_newer_one(self):
        """Review of back #216: the filing matched through `prior_osp`, so the list would name module
        files rendered from v1 as holding v2's changes."""
        v1, v2 = self._versions()
        _answer(v2, "g5_0_pest", "pest_prevention", "Kaolin clay")
        self.assertEqual(changed_sections(v1).state, "newer_version")
        text = " ".join(self._supplement(v1).split())
        self.assertIn("The section comparison is printed in the packet built from plan v2", text)
        self.assertNotIn("C5 ", text.split(HEADING)[1])


class OnlyOtcoAsksForTheListTests(_Renewal):
    def test_ccof_and_wsda_packets_carry_no_section_list(self):
        for agent in ("CCOF", "Washington State Department of Agriculture"):
            with self.subTest(agent=agent):
                _v1, v2 = self._versions(certifier=agent)
                _answer(v2, "g5_0_pest", "pest_prevention", "Kaolin clay")
                self.assertIsNone(changed_sections(v2))
                self.assertNotIn(HEADING, self._supplement(v2))
                OSPAnnualUpdate.objects.all().delete()
                OrganicSystemPlan.objects.all().delete()

    def test_an_agent_without_a_register_carries_no_section_list(self):
        _v1, v2 = self._versions(certifier="Organic Certifiers, Inc.")
        self.assertIsNone(changed_sections(v2))


class FiledUpdateIsUntouchedTests(_Renewal):
    def test_the_filed_02_is_the_bytes_that_were_filed(self):
        """The list is computed when the packet is built; it lives in 02s and never in the filing."""
        v1, v2 = self._versions()
        filing = OSPAnnualUpdate.objects.get(new_osp=v2)
        filing = file_filing(sign_filing(filing, self.user), "agent_web_form", datetime(2026, 10, 20, tzinfo=dt_tz.utc))
        frozen = bytes(filing.filed_pdf)
        _answer(v2, "g5_0_pest", "pest_prevention", "Kaolin clay")
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(v2)))
        self.assertEqual(zf.read("02-annual-update.pdf"), frozen)
        self.assertIn("C5 ", _pdf_text(zf.read("02s-renewal-status-and-routing.pdf")))
