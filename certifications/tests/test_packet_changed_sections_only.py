"""A renewal packet with only the changed sections, built on request and saying what it left out.

WHY THIS EXISTS
---------------
Oregon Tilth's OSP Update Form Step 4 asks the operation to "list updated OSP sections and attach"
them. The full packet attaches every module PDF, so the reviewer who asked for the updated sections
sifts the whole ZIP for them. `?scope=changed` builds the packet with only the module PDFs whose
answers changed between the two versions the year's annual update moved between.

What must hold, each pinned below by reading the built artifact back:

  * the default packet is unchanged: every module PDF, no changed-sections wording;
  * the changed-sections packet carries exactly the changed module PDFs plus every other document
    the full packet carries (cover, 01, 02, 02s, 03-06, every Parcel Application, the workbooks),
    because land, workbooks and operator files are not part of the comparison;
  * the cover says the packet carries only changed sections, names every module left out, and says
    land is not compared; 04 and 06 never point at a left-out file without saying it is absent;
  * a plan the comparison cannot read (no annual update, a reaffirmation, the earlier side of the
    update, nothing changed) is refused with the reason, and nothing is filed;
  * the plan gate is the packet's own, on the option and on its preview;
  * the two packets are filed as two documents with titles that tell them apart.
"""

import hashlib
import io
import zipfile
from datetime import datetime
from datetime import timezone as dt_tz

from django.test import TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan, OSPAnnualUpdate, PlanMaterialEntry
from certifications.osp_modules import MODULE_REGISTRY, MODULES_BY_KEY
from certifications.services.osp_fork import fork_plan
from certifications.services.osp_module_pdf import generate_osp_packet
from certifications.services.packet_coverage import module_file_stem
from certifications.services.packet_scope import PacketScopeUnavailable, changed_only_scope, scope_preview
from company.models import Company, Establishment
from documents.models import GeneratedDocument
from product.models import Parcel
from users.models import User, WorksIn

from .test_otco_step4_changed_sections import _answer
from .test_renewal_packet_contents import _pdf_text

OTCO = "Oregon Tilth Certified Organic"
NOTE = "unchanged since plan v1, not in this packet"


def _path(key):
    return f"modules/{module_file_stem(MODULES_BY_KEY[key])}.pdf"


def _module_files(zf):
    return {n for n in zf.namelist() if n.startswith("modules/")}


class _Renewal(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="changed@test.com", password="x", first_name="Ana")
        self.company = Company.objects.create(name="Changed Only Orchards LLC")
        self.est = Establishment.objects.create(name="Changed Only Orchard", company=self.company)
        self.parcel = Parcel.objects.create(name="Home Block", establishment=self.est, area=4.0)

    def _versions(self, certifier=OTCO, change=True):
        v1 = OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="active",
            certifier_name=certifier,
            submitted_at=datetime(2026, 1, 10, tzinfo=dt_tz.utc),
        )
        _answer(v1, "g5_0_pest", "pest_prevention", "Hedgerows and owl boxes")
        # OTCO OFPP 1-1 maps this question, so 06 cites it while its module is left out.
        _answer(v1, "g2_0_fraud_prevention", "osp_accuracy_process", "The plan is reviewed every winter.")
        v2 = fork_plan(v1, self.user)
        OSPAnnualUpdate.objects.create(prior_osp=v1, new_osp=v2, reporting_year=2027, changes_summary="Pest plan.")
        if change:
            _answer(v2, "g5_0_pest", "pest_prevention", "Hedgerows, owl boxes and kaolin clay")
            PlanMaterialEntry.objects.create(
                osp=v2, product_name="Gypsum", reason_for_use="Calcium", created_by=self.user
            )
        return OrganicSystemPlan.objects.get(pk=v1.pk), OrganicSystemPlan.objects.get(pk=v2.pk)

    def _changed_packet(self, osp):
        return zipfile.ZipFile(io.BytesIO(generate_osp_packet(osp, scope=changed_only_scope(osp))))


class ChangedOnlyContentsTests(_Renewal):
    def test_exactly_the_changed_modules_and_every_other_document(self):
        _v1, v2 = self._versions()
        full = zipfile.ZipFile(io.BytesIO(generate_osp_packet(v2)))
        changed = self._changed_packet(v2)

        self.assertEqual(_module_files(changed), {_path("g5_0_pest"), _path("materials_application")})
        # Everything that is not a module PDF is the same set of files as the full packet carries.
        self.assertEqual(
            set(changed.namelist()) - _module_files(changed),
            set(full.namelist()) - _module_files(full),
        )
        for required in (
            "00-cover.pdf",
            "01-organic-system-plan.pdf",
            "02-annual-update.pdf",
            "02s-renewal-status-and-routing.pdf",
            "03-change-notifications.pdf",
            "04-coverage-and-scope.pdf",
            "05-audit-trail-exhibit.pdf",
            "06-question-index.pdf",
            "parcels/parcel-application-Home Block.pdf",
        ):
            self.assertIn(required, changed.namelist())
        self.assertTrue(any(n.startswith("workbooks/") for n in changed.namelist()))

    def test_the_cover_says_so_and_names_every_module_left_out(self):
        _v1, v2 = self._versions()
        cover = _pdf_text(self._changed_packet(v2).read("00-cover.pdf"))
        self.assertIn("Changed sections only", cover)
        self.assertIn("only the plan sections whose answers changed between plan v1 and plan v2", cover)
        self.assertIn("is the agent's decision", cover)
        scope = changed_only_scope(v2)
        self.assertEqual(len(scope.omitted), len(MODULE_REGISTRY) - 2)
        left_out = cover.split("left out because their answers are the same")[1]
        for module in scope.omitted:
            self.assertIn(module.path, left_out)
            self.assertIn(module.label.split(" ")[0], left_out)
        # Land is stated as outside the comparison, and the parcels travel for that reason.
        self.assertIn("new land and edits to an existing parcel", cover)
        self.assertIn("are not compared", cover)
        self.assertIn("Every Parcel Application is included", cover)

    def test_no_page_points_at_a_left_out_file_without_saying_it_is_absent(self):
        """04 and 06 cite module files. A citation of a file the ZIP does not carry, unmarked, is the
        false statement the coverage page exists to prevent."""
        _v1, v2 = self._versions()
        zf = self._changed_packet(v2)
        omitted = [m.path for m in changed_only_scope(v2).omitted]
        for name in zf.namelist():
            if not name.endswith(".pdf") or name == "00-cover.pdf" or name.startswith("modules/"):
                continue
            text = _pdf_text(zf.read(name))
            for path in omitted:
                for chunk in text.split(path)[1:]:
                    with self.subTest(document=name, path=path):
                        # The note closes the same citation: before the next bullet, which pdfminer
                        # reads as "(cid:127)". 06 prints the question label between file and note.
                        self.assertIn(f"({NOTE})", chunk.split("(cid:127)")[0][:300], chunk[:200])

    def test_the_question_index_names_an_answer_in_a_left_out_module(self):
        """06 read the recorder for an answer's page. A module that was never drawn left the row with
        no location at all, as if nothing in the plan answered it."""
        _v1, v2 = self._versions()
        index = _pdf_text(self._changed_packet(v2).read("06-question-index.pdf"))
        self.assertIn(f"{_path('g2_0_fraud_prevention')}", index)
        cited = index.split("OFPP")[1].split(_path("g2_0_fraud_prevention"))[1]
        self.assertTrue(cited.lstrip().startswith(", "), cited[:160])
        self.assertIn(NOTE, cited[:400])

    def test_works_for_an_agent_that_does_not_ask_for_the_list(self):
        """Offered for every certifier; only the wording of 02s is OTCO's."""
        _v1, v2 = self._versions(certifier="CCOF")
        changed = self._changed_packet(v2)
        self.assertEqual(_module_files(changed), {_path("g5_0_pest"), _path("materials_application")})
        self.assertIn("Changed sections only", _pdf_text(changed.read("00-cover.pdf")))

    def test_a_narrative_only_change_carries_no_module_and_says_where_the_change_is(self):
        v1, v2 = self._versions(change=False)
        sections = dict(v2.sections or {})
        sections["recordkeeping_description"] = {"narrative_manual": "Paper logs moved to Trazo in 2026."}
        v2.sections = sections
        v2.save(update_fields=["sections"])
        zf = self._changed_packet(OrganicSystemPlan.objects.get(pk=v2.pk))
        self.assertEqual(_module_files(zf), set())
        cover = _pdf_text(zf.read("00-cover.pdf"))
        self.assertIn("No module's answers changed", cover)
        self.assertIn("Recordkeeping", cover)


class DefaultPacketUnchangedTests(_Renewal):
    def test_the_default_packet_carries_every_module_and_no_scope_wording(self):
        _v1, v2 = self._versions()
        zf = zipfile.ZipFile(io.BytesIO(generate_osp_packet(v2)))
        self.assertEqual(len(_module_files(zf)), len(MODULE_REGISTRY))
        cover = _pdf_text(zf.read("00-cover.pdf"))
        self.assertNotIn("Changed sections only", cover)
        self.assertIn("one PDF per guided module", cover)
        self.assertNotIn(NOTE, _pdf_text(zf.read("04-coverage-and-scope.pdf")))
        self.assertNotIn(NOTE, _pdf_text(zf.read("06-question-index.pdf")))


class RefusedWhenNotComparableTests(_Renewal):
    def _refused(self, osp):
        with self.assertRaises(PacketScopeUnavailable) as ctx:
            changed_only_scope(osp)
        preview = scope_preview(osp)
        self.assertFalse(preview["available"])
        self.assertEqual(preview["code"], ctx.exception.code)
        return ctx.exception.code

    def test_a_first_plan_with_no_annual_update(self):
        v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        self.assertEqual(self._refused(v1), "no_filing")

    def test_a_reaffirmation_has_no_second_version(self):
        v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        OSPAnnualUpdate.objects.create(prior_osp=v1, reporting_year=2027, changes_summary="No changes.")
        self.assertEqual(self._refused(v1), "no_new_version")

    def test_the_earlier_side_of_the_update(self):
        v1, _v2 = self._versions()
        self.assertEqual(self._refused(v1), "newer_version")

    def test_nothing_changed(self):
        _v1, v2 = self._versions(change=False)
        self.assertEqual(self._refused(v2), "no_changes")


class EndpointTests(_Renewal):
    def setUp(self):
        super().setUp()
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _grant(self):
        from subscriptions.testing import grant_compliance_exports

        grant_compliance_exports(self.company)

    def _url(self, osp, suffix):
        return f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{osp.id}/{suffix}"

    def test_full_and_changed_are_filed_as_two_documents_that_tell_themselves_apart(self):
        """The packet is built inline, not as an ExportJob, so nothing dedupes by fingerprint; the
        two builds must still never be mistaken for each other on the Documents page."""
        self._grant()
        _v1, v2 = self._versions()
        full = self.client.get(self._url(v2, "packet/"))
        changed = self.client.get(self._url(v2, "packet/?scope=changed"))
        self.assertEqual((full.status_code, changed.status_code), (200, 200))
        full_bytes, changed_bytes = b"".join(full.streaming_content), b"".join(changed.streaming_content)
        self.assertNotEqual(hashlib.sha256(full_bytes).digest(), hashlib.sha256(changed_bytes).digest())
        self.assertIn("packet-changed-sections.zip", changed["Content-Disposition"])
        self.assertNotIn("changed-sections", full["Content-Disposition"])
        docs = GeneratedDocument.objects.filter(establishment=self.est, source="packet").order_by("id")
        self.assertEqual(
            [d.title for d in docs],
            ["OSP renewal packet — v2", "OSP renewal packet, changed sections only, v2"],
        )
        self.assertNotEqual(docs[0].file.name, docs[1].file.name)
        self.assertEqual(
            _module_files(zipfile.ZipFile(io.BytesIO(changed_bytes))),
            {_path("g5_0_pest"), _path("materials_application")},
        )

    def test_explicit_full_scope_is_the_default(self):
        self._grant()
        _v1, v2 = self._versions()
        response = self.client.get(self._url(v2, "packet/?scope=full"))
        self.assertEqual(response.status_code, 200)
        zf = zipfile.ZipFile(io.BytesIO(b"".join(response.streaming_content)))
        self.assertEqual(len(_module_files(zf)), len(MODULE_REGISTRY))

    def test_refused_with_the_reason_and_nothing_filed(self):
        self._grant()
        v1 = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="active")
        response = self.client.get(self._url(v1, "packet/?scope=changed"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "no_filing")
        self.assertIn("no two plan versions to compare", str(response.data["scope"]))
        self.assertFalse(GeneratedDocument.objects.filter(establishment=self.est, source="packet").exists())

    def test_unknown_scope_is_refused(self):
        self._grant()
        _v1, v2 = self._versions()
        self.assertEqual(self.client.get(self._url(v2, "packet/?scope=everything")).status_code, 400)

    def test_preview_lists_what_the_packet_would_carry(self):
        self._grant()
        _v1, v2 = self._versions()
        response = self.client.get(self._url(v2, "packet-scope/"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["available"])
        self.assertEqual((response.data["prior_version"], response.data["new_version"]), (1, 2))
        self.assertEqual({row["key"] for row in response.data["included"]}, {"g5_0_pest", "materials_application"})
        self.assertEqual(len(response.data["omitted"]), len(MODULE_REGISTRY) - 2)
        self.assertFalse(GeneratedDocument.objects.filter(establishment=self.est).exists())

    def test_the_plan_gate_is_unchanged_for_the_option_and_its_preview(self):
        """No subscription: refused for the plan, before the scope is read or anything is built."""
        _v1, v2 = self._versions()
        for suffix in ("packet/?scope=changed", "packet/?scope=nonsense", "packet-scope/", "packet/"):
            with self.subTest(suffix=suffix):
                response = self.client.get(self._url(v2, suffix))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.data.get("detail").code, "compliance_exports_required")
        self.assertFalse(GeneratedDocument.objects.filter(establishment=self.est).exists())
