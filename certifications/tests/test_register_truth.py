"""The register states what the agents' forms ask, and nothing in it can stand in for an answer.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, Phase 2 (documentation/audits/OSP-ALIGNMENT-2026-10/LEDGER.md, T17,
T26, T27). Phase 1 made page 04 read the register row by row, so the packet is now exactly as
honest as the register. The audit and our re-read of the official forms found:

  * CCOF's contract asks for markets exported to "directly or indirectly"; Trazo could only say
    "Neither: all product is sold within the United States", which a grower whose buyer exports
    had to tick. The old answer is kept as the operator gave it, but it no longer counts as an
    answer to the question asked now: the module reads as unconfirmed until the operator answers.
  * WSDA AGR 2264's "no input materials at all" N/A was mapped to a declaration that no
    PROHIBITED material was applied, a different statement.
  * Rows a certifier can never be asked about (instructions, Trazo's own readings), optional
    items and requirements that apply only to some operations need kinds and conditions that
    cannot hide an applicable requirement or make a form read as complete.

Each test here failed against the code before this change (re-applied once to confirm).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import missing_required, visible_questions
from certifications.services import certifier_register
from certifications.services.certifier_register import Item, load_forms
from certifications.services.osp_module_pdf import _coverage_pdf, generate_module_pdf
from certifications.services.packet_answers import RowState, _Answers, form_is_answered, row_answer_state
from company.models import Company, Establishment
from product.models import Parcel
from users.models import User, WorksIn

from .test_renewal_packet_contents import _pdf_text

G8 = "g8_0_record_keeping"
TRADE = "import_export_activity"


def _row(agent, stem, ref):
    form = next(f for f in load_forms(agent) if f.path.stem == stem)
    return next(i for i in form.items if i.ref == ref)


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Register Truth Co")
        self.est = Establishment.objects.create(name="Truth Farm", company=self.company, state="WA")
        self.parcel = Parcel.objects.create(name="North Block", establishment=self.est, area=3.0)
        self.osp = OrganicSystemPlan.objects.create(
            establishment=self.est, version_number=1, status="draft", certifier_name="WSDA"
        )

    def _set(self, module_key, **answers):
        responses = self.osp.module_responses or {"modules": {}}
        responses.setdefault("modules", {})[module_key] = {
            "answers": {k: {"value": v, "at": "2026-09-30T00:00:00Z"} for k, v in answers.items()}
        }
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _state(self, item) -> RowState:
        return row_answer_state(_Answers(self.osp), item)


# ---------------------------------------------------------------------------
# CCOF Contract D2: indirect and planned export
# ---------------------------------------------------------------------------


class IndirectExportIsAskedTests(SimpleTestCase):
    def setUp(self):
        self.module = MODULES_BY_KEY[G8]
        self.question = next(q for p in self.module.pages for q in p.questions if q.key == TRADE)

    def test_the_question_offers_indirect_export_and_the_contract_row_cites_it(self):
        current = {o.value for o in self.question.options if not o.retired}
        self.assertIn("indirect_export", current)
        self.assertIn(f"{G8}.{TRADE}", _row("ccof", "Certification-Contract", "D2").questions)

    def test_an_indirect_exporter_is_asked_where_to_and_not_for_export_certificates(self):
        visible = {q.key for _p, q in visible_questions(self.module, {TRADE: ["indirect_export"]})}
        self.assertIn("export_destinations", visible)
        # The certificates are the direct exporter's to request, not the grower whose buyer ships.
        self.assertNotIn("export_certificate_types", visible)

    def test_the_old_none_alone_is_no_answer_and_the_new_one_is(self):
        self.assertIn(TRADE, missing_required(self.module, {TRADE: ["none"]}))
        self.assertNotIn(TRADE, missing_required(self.module, {TRADE: ["none_no_known_export"]}))

    def test_the_old_option_keeps_its_wording_so_a_stored_answer_reads_as_given(self):
        retired = next(o for o in self.question.options if o.value == "none")
        self.assertTrue(retired.retired)
        self.assertIn("all product is sold within the United States", retired.label["en"])


class LegacyNoneNeedsConfirmationTests(_Plan):
    def test_page_04_lists_contract_d2_as_unconfirmed_not_answered(self):
        self._set(G8, **{TRADE: ["none"]})
        state = self._state(_row("ccof", "Certification-Contract", "D2"))
        self.assertEqual(state.state, "unconfirmed")
        self.assertTrue(state.is_open)

        self._set(G8, **{TRADE: ["none_no_known_export"]})
        self.assertEqual(self._state(_row("ccof", "Certification-Contract", "D2")).state, "answered")

    def test_the_module_pdf_prints_the_old_answer_with_a_review_line(self):
        self._set(G8, **{TRADE: ["none"]})
        text = _pdf_text(generate_module_pdf(self.osp, G8))
        self.assertIn("all product is sold within the United States", text)
        self.assertIn("no longer offers", text)

        self._set(G8, **{TRADE: ["none_no_known_export"]})
        self.assertNotIn("no longer offers", _pdf_text(generate_module_pdf(self.osp, G8)))


class RetiredOptionWritePathTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Write Path Co")
        self.user = User.objects.create_user(email="d2@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Write Farm", company=self.company, state="CA")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)

    def _put(self, payload):
        url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/modules/{G8}/"
        return self.client.put(url, payload, format="json")

    def test_a_new_answer_cannot_choose_the_retired_option(self):
        response = self._put({"answers": {TRADE: ["none"]}})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(TRADE, response.data["answers"])

    def test_resending_a_stored_retired_answer_unchanged_is_accepted(self):
        self.osp.module_responses = {"modules": {G8: {"answers": {TRADE: {"value": ["none"], "at": "2026-01-01"}}}}}
        self.osp.save(update_fields=["module_responses"])
        response = self._put({"answers": {TRADE: ["none"]}})
        self.assertEqual(response.status_code, 200, response.data)

    def test_completion_is_refused_while_only_the_retired_option_is_stored(self):
        self.osp.module_responses = {"modules": {G8: {"answers": {TRADE: {"value": ["none"], "at": "2026-01-01"}}}}}
        self.osp.save(update_fields=["module_responses"])
        response = self._put({"complete": True})
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(TRADE, response.data.get("missing", []))


# ---------------------------------------------------------------------------
# WSDA AGR 2264 13 and the wash-water citations
# ---------------------------------------------------------------------------


class MappingsSayWhatTheFormAsksTests(_Plan):
    def test_a_no_prohibited_material_declaration_does_not_answer_no_inputs_at_all(self):
        row = _row("wsda", "2264-site-application", "13")
        self.assertNotIn("parcel_application.dlpm_none_within_tenure", row.questions)
        # Whatever the plan holds, this row stays open: Trazo has no "no inputs at all" statement.
        self.parcel.application_answers = {"dlpm_none_within_tenure": True, "currently_certified": "no"}
        self.parcel.save()
        self.assertTrue(self._state(row).is_open)

    def test_equipment_sanitizer_rows_do_not_cite_the_wash_water_questions(self):
        wash = {"g6_4_handling.uses_water", "g6_4_handling.water_source_sanitizer"}
        for agent, stem, ref in (
            ("ccof", "G6.4-onfarm-postharvest", "B1"),
            ("ccof", "G6.4-onfarm-postharvest", "B1a"),
            ("ccof", "G6.4-onfarm-postharvest", "B1b"),
            ("wsda", "2121-L-post-harvest", "5"),
            ("wsda", "2121-L-post-harvest", "5a"),
        ):
            self.assertFalse(wash & set(_row(agent, stem, ref).questions), f"{stem} {ref}")


# ---------------------------------------------------------------------------
# Kinds, optional items and conditions cannot hide a requirement or fake completeness
# ---------------------------------------------------------------------------


def _q(ref, status="not_covered", **kw):
    return Item(ref=ref, asks=f"asks {ref}", status=status, **kw)


LIVESTOCK = (("certification_contract.contract_scopes", "includes", "livestock"),)


class ConditionalRequirementTests(_Plan):
    def test_an_unanswered_trigger_leaves_the_requirement_open(self):
        state = self._state(_q("C1", severity="P3", applies_when=LIVESTOCK))
        self.assertEqual(state.state, "unresolved")
        self.assertTrue(state.is_open)

    def test_an_answered_trigger_that_excludes_it_closes_it_with_the_evidence(self):
        self._set("certification_contract", contract_scopes=["crops"])
        state = self._state(_q("C1", severity="P3", applies_when=LIVESTOCK))
        self.assertEqual(state.state, "not_applicable")
        self.assertIn("contract_scopes", state.detail)

    def test_an_answered_trigger_that_includes_it_leaves_it_to_the_row(self):
        self._set("certification_contract", contract_scopes=["crops", "livestock"])
        self.assertEqual(self._state(_q("C1", severity="P3", applies_when=LIVESTOCK)).state, "not_collected")


class RowKindTests(_Plan):
    def test_instructions_and_interpretations_are_never_rows_of_the_answer(self):
        self.assertIsNone(self._state(Item(ref="G1", asks="term", status="", kind="instruction")))
        self.assertIsNone(self._state(Item(ref="(reading)", asks="x", status="", kind="interpretation")))

    def test_optional_items_neither_block_nor_make_a_form_answered(self):
        required_closed = RowState("1", "answered")
        optional_open = RowState("14", "not_collected", optional=True)
        self.assertTrue(form_is_answered([required_closed, optional_open]))
        self.assertFalse(form_is_answered([optional_open]))
        self.assertFalse(form_is_answered([RowState("14", "answered", optional=True)]))


class OptionalItemsArePrintedApartTests(_Plan):
    def test_wsda_soil_fertility_names_its_optional_item_beside_the_open_questions(self):
        text = " ".join(_pdf_text(_coverage_pdf(self.osp)).split())
        self.assertIn("Optional items not answered: 14", text)
        self.assertNotIn(", 14 not", text)


class LoaderRefusesUnsafeClassificationsTests(SimpleTestCase):
    def _load(self, item_yaml: str):
        form = (
            "form:\n  title: T\n  document_id: X\n  revision: R\n  url: https://x\n  retrieved: 2026-09-30\n"
            "  register_status: draft\nitems:\n" + item_yaml
        )
        with tempfile.TemporaryDirectory() as tmp:
            forms = Path(tmp) / "zz" / "forms"
            forms.mkdir(parents=True)
            (forms / "T.yaml").write_text(form)
            with patch.object(certifier_register, "REGISTER_DIR", Path(tmp)):
                return certifier_register.load_forms("zz")

    def test_out_of_scope_needs_a_basis_from_the_closed_set(self):
        with self.assertRaisesRegex(ValueError, "scope_basis"):
            self._load("- ref: '1'\n  asks: a\n  status: out_of_scope\n  reason: the ICP never does this\n")
        with self.assertRaisesRegex(ValueError, "scope_basis"):
            self._load("- ref: '1'\n  asks: a\n  status: out_of_scope\n  scope_basis: rarely_applies\n  reason: r\n")
        self.assertEqual(
            self._load(
                "- ref: '1'\n  asks: a\n  status: out_of_scope\n  scope_basis: payment_data\n  reason: card details\n"
            )[0]
            .items[0]
            .scope_basis,
            "payment_data",
        )

    def test_a_conditional_requirement_is_not_out_of_scope(self):
        with self.assertRaisesRegex(ValueError, "conditional"):
            self._load(
                "- ref: '1'\n  asks: a\n  status: out_of_scope\n  scope_basis: payment_data\n  reason: r\n"
                "  applies_when:\n  - {question: certification_contract.contract_scopes, op: includes, value: livestock}\n"
            )

    def test_an_interpretation_needs_a_reason_and_no_row_but_a_question_carries_a_status(self):
        with self.assertRaisesRegex(ValueError, "reason"):
            self._load("- ref: x\n  kind: interpretation\n  asks: a\n")
        with self.assertRaisesRegex(ValueError, "no status"):
            self._load("- ref: x\n  kind: instruction\n  asks: a\n  status: covered\n")

    def test_a_condition_cannot_read_a_per_parcel_answer(self):
        with self.assertRaisesRegex(ValueError, "per-parcel"):
            self._load(
                "- ref: '1'\n  asks: a\n  status: not_covered\n  severity: P3\n  gap: g\n  fix: f\n"
                "  applies_when:\n  - {question: parcel_application.livestock_present, op: truthy}\n"
            )


class RetiredTriggerDecidesNothingTests(_Plan):
    """Review on #72: a trigger holding only the retired option must not close what it gates."""

    def test_a_question_gated_on_export_stays_open_while_only_the_old_answer_is_stored(self):
        from certifications.services.packet_answers import question_state

        module = MODULES_BY_KEY[G8]
        state, _detail = question_state(
            module, "export_destinations", {TRADE: ["none"]}, na_attested=False, section_uploads=0
        )
        self.assertEqual(state, "unresolved")
        state, detail = question_state(
            module, "export_destinations", {TRADE: ["none_no_known_export"]}, na_attested=False, section_uploads=0
        )
        self.assertEqual(state, "not_applicable")
        self.assertIn("none_no_known_export", detail)

    def test_a_condition_on_a_retired_only_trigger_is_unresolved(self):
        self._set(G8, **{TRADE: ["none"]})
        cond = ((f"{G8}.{TRADE}", "includes", "export"),)
        self.assertEqual(self._state(_q("X1", severity="P3", applies_when=cond)).state, "unresolved")


class InventoryOverridesAreCheckedTests(SimpleTestCase):
    def test_a_rename_needs_a_target_that_no_other_item_has(self):
        from certifications.services.form_inventory import InventoryItem, apply_overrides

        items = [InventoryItem("1", "a"), InventoryItem("2", "b")]
        with self.assertRaisesRegex(ValueError, "names no `to`"):
            apply_overrides(items, [{"op": "rename", "ref": "1", "reason": "r"}], "t")
        with self.assertRaisesRegex(ValueError, "already has"):
            apply_overrides(items, [{"op": "rename", "ref": "1", "to": "2", "reason": "r"}], "t")


class OtcoNumberedExtractionTests(SimpleTestCase):
    """Review on #75: a subsection that letters its items with no numbered question kept none."""

    def test_lettered_items_without_a_number_are_kept(self):
        from certifications.services.form_inventory import extract_otco_numbered

        items = extract_otco_numbered(
            [
                ("7.7", "STORAGE"),
                ("a)", "Facility name"),
                ("b)", "Documentation"),
                ("7.8", "TRANSPORT"),
                ("1)", "Who hauls?"),
                ("a)", "Clean truck affidavit"),
            ]
        )
        self.assertEqual([i.ref for i in items], ["7.7-a", "7.7-b", "7.8-1", "7.8-1a"])


def _docx(paragraphs, numbering):
    """A minimal .docx: paragraphs are (text, numId or None)."""
    import io
    import zipfile

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def num_pr(num):
        if num is None:
            return ""
        return '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="%s"/></w:numPr></w:pPr>' % num

    body = "".join("<w:p>%s<w:r><w:t>%s</w:t></w:r></w:p>" % (num_pr(num), text) for text, num in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {w}><w:body>{body}</w:body></w:document>")
        z.writestr("word/numbering.xml", f"<w:numbering {w}>{numbering}</w:numbering>")
    buf.seek(0)
    return buf


class DocxNumberingTests(SimpleTestCase):
    """OTCO pass: Word list restarts and forms with no subsection number."""

    LIST = (
        '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
        '<w:numFmt w:val="decimal"/><w:lvlText w:val="%1)"/></w:lvl></w:abstractNum>'
        '<w:num w:numId="10"><w:abstractNumId w:val="1"/></w:num>'
        '<w:num w:numId="11"><w:abstractNumId w:val="1"/>'
        '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
    )

    def test_a_start_override_restarts_the_shared_list(self):
        from certifications.services.form_inventory import docx_paragraphs

        labels = [
            label
            for label, _t in docx_paragraphs(
                _docx([("first", 10), ("second", 10), ("restarted", 11), ("next", 11)], self.LIST)
            )
        ]
        self.assertEqual(labels, ["1)", "2)", "1)", "2)"])

    def test_a_form_with_no_subsection_number_gets_bare_refs(self):
        from certifications.services.form_inventory import extract_otco_numbered

        items = extract_otco_numbered(
            [("", "biodiversity heading"), ("1)", "Plan?"), ("a)", "Agency"), ("", "b)Share water")], bare=True
        )
        self.assertEqual([i.ref for i in items], ["1", "1a", "1b"])


# ---------------------------------------------------------------------------------------------
# Run 8 (2026-10-05): "verified" means a confirmed Organic Integrity Database entry and nothing
# else. A fuzzy name match is a candidate; an unrecognised database status is not certification;
# an OMRI, WSDA or National List hit describes a material. Each test below was red against the
# code before the change.
# ---------------------------------------------------------------------------------------------


class _Oid(TestCase):
    def setUp(self):
        from datetime import date

        from certifications.models import USDAOrganicOperation

        def op(name, normalized, status="Certified", certifier="Oregon Tilth", state="Oregon"):
            return USDAOrganicOperation.objects.create(
                op_name=name,
                op_name_normalized=normalized,
                state=state,
                status=status,
                certifier_name=certifier,
                certified_products="Blueberries",
                scope_crops="Yes",
                status_effective_date="2024-01-15",
                data_snapshot_date=date(2026, 9, 1),
            )

        self.op = op
        op("Green Vally Orchards", "green vally")  # one letter off "Green Valley Orchards"
        op("Riverbend Farm LLC", "riverbend")
        op("Twin Oaks Farm", "twin oaks")
        op("Twin Oaks Ranch", "twin oaks")  # two operations normalize to the same name
        op("Hollow Creek Farm", "hollow creek", status="Pending Review")

    def verify(self, name, certifier=None):
        from certifications.services.usda_organic_verifier import USDAOrganicVerifier

        return USDAOrganicVerifier().verify(name, "OR", certifier_name=certifier)


class OidVerifiedNeedsAConfirmedEntryTests(_Oid):
    def test_a_similar_name_is_a_possible_match_never_verified(self):
        result = self.verify("Green Valley Orchards")
        self.assertEqual(result.status, "possible_match")
        self.assertIn("not confirmed", result.notes)

    def test_the_exact_unique_name_with_the_same_agent_is_verified(self):
        self.assertEqual(self.verify("Riverbend Farm", certifier="Oregon Tilth Certified Organic").status, "verified")
        self.assertEqual(self.verify("Riverbend Farm").status, "verified")

    def test_two_operations_with_the_name_cannot_confirm_either(self):
        self.assertEqual(self.verify("Twin Oaks Orchards").status, "possible_match")

    def test_a_different_certifying_agent_is_not_confirmed(self):
        self.assertEqual(self.verify("Riverbend Farm", certifier="WSDA Organic Program").status, "possible_match")

    def test_an_unrecognised_database_status_is_not_certification(self):
        self.assertEqual(self.verify("Hollow Creek Farm").status, "self_reported")


class OidManagerCopiesOnlyConfirmedEntriesTests(_Oid):
    def _cert(self, est_name, **extra):
        from certifications.models import Certification

        company = Company.objects.create(name=f"{est_name} Co")
        est = Establishment.objects.create(name=est_name, company=company, state="OR")
        return Certification.objects.create(establishment=est, certification_type="usda_organic", **extra)

    def test_a_possible_match_leaves_the_farms_certificate_details_alone(self):
        from certifications.services.verification_manager import VerificationManager

        cert = self._cert("Green Valley Orchards")
        VerificationManager().verify_certification(cert)
        cert.refresh_from_db()
        self.assertEqual(cert.verification_status, "possible_match")
        self.assertFalse(cert.certifier_name)
        self.assertIsNone(cert.effective_date)
        self.assertFalse(cert.certified_items)
        self.assertEqual(cert.consumer_display_status, "self_reported")

    def test_a_confirmed_entry_still_fills_them(self):
        from certifications.services.verification_manager import VerificationManager

        cert = self._cert("Riverbend Farm")
        VerificationManager().verify_certification(cert)
        cert.refresh_from_db()
        self.assertEqual(cert.verification_status, "verified")
        self.assertEqual(cert.certifier_name, "Oregon Tilth")

    def test_a_handler_with_only_a_similar_name_stays_self_reported(self):
        from certifications.models import PostHarvestFacility

        company = Company.objects.create(name="Handler Co")
        est = Establishment.objects.create(name="Some Farm", company=company, state="OR")
        fac = PostHarvestFacility.objects.create(establishment=est, name="Green Valley Orchards", state="OR")
        fac.verify()
        self.assertEqual(fac.verification_status, "self_reported")


class MaterialListingsNeverVerifyTests(TestCase):
    def setUp(self):
        from certifications.models import NationalListSubstance, OMRIProduct

        NationalListSubstance.objects.create(
            substance_name="Copper hydroxide",
            substance_name_normalized="copper hydroxide",
            cfr_section="205.601",
            subsection="i",
            category="disease_control",
            status="allowed",
        )
        OMRIProduct.objects.create(omri_id="OMRI-99999", product_name="Example Organic Fungicide", manufacturer="T")

    def test_omri_id_catalog_and_national_list_hits_are_listing_matches(self):
        from certifications.services.omri_verifier import OMRIProductVerifier

        v = OMRIProductVerifier()
        for result in (
            v.verify(operation_name="", certification_number="OMRI-99999"),
            v.verify(operation_name="Example Organic Fungicide"),
            v.verify(operation_name="Copper hydroxide"),
        ):
            self.assertTrue(result.found)
            self.assertEqual(result.status, "listing_match")


class ReevaluateVerificationCommandTests(_Oid):
    """The production safety rule: dry run, apply, idempotent, restore, each one logged."""

    def setUp(self):
        super().setUp()
        from certifications.models import Certification

        company = Company.objects.create(name="Old Rule Co")
        est = Establishment.objects.create(name="Green Valley Orchards", company=company, state="OR")
        # What the old fuzzy rule stored.
        self.cert = Certification.objects.create(
            establishment=est,
            certification_type="usda_organic",
            verification_status="verified",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )

    def _run(self, path, *flags):
        import io

        from django.core.management import call_command

        out = io.StringIO()
        args = ["reevaluate_certification_verification", *flags]
        if "--restore" not in flags:
            args += ["--report", path]
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_dry_run_apply_rerun_and_restore(self):
        import json
        import os

        from certifications.models import CertificationVerificationLog
        from common.models import DataOperationLog

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "report.json")
            self._run(path)
            self.cert.refresh_from_db()
            self.assertEqual(self.cert.verification_status, "verified", "a dry run saved")
            report = json.loads(Path(path).read_text())
            self.assertEqual([c["after"]["verification_status"] for c in report["changes"]], ["possible_match"])
            self.assertFalse(DataOperationLog.objects.exists())

            self._run(path, "--apply")
            self.cert.refresh_from_db()
            self.assertEqual(self.cert.verification_status, "possible_match")
            log = DataOperationLog.objects.get(action="apply")
            self.assertEqual(log.counts["rows"], 1)
            self.assertTrue(CertificationVerificationLog.objects.filter(certification=self.cert).exists())

            again = os.path.join(tmp, "again.json")
            self._run(again)
            self.assertEqual(json.loads(Path(again).read_text())["changes"], [], "not idempotent")

            self._run(path, "--restore", path)
            self.cert.refresh_from_db()
            self.assertEqual(self.cert.verification_status, "verified")
            self.assertTrue(DataOperationLog.objects.filter(action="restore").exists())


class VerifiedReviewOf119Tests(_Oid):
    """Review of back #119: four ways the stricter rule could still mislead."""

    def test_the_command_refuses_to_run_against_an_empty_oid_copy(self):
        import io

        from django.core.management import call_command
        from django.core.management.base import CommandError

        from certifications.models import Certification, USDAOrganicOperation

        company = Company.objects.create(name="Empty Copy Co")
        est = Establishment.objects.create(name="Riverbend Farm", company=company, state="OR")
        cert = Certification.objects.create(
            establishment=est,
            certification_type="usda_organic",
            verification_status="verified",
            verification_source=Certification.DATABASE_VERIFICATION_SOURCE,
        )
        USDAOrganicOperation.objects.all().delete()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                call_command(
                    "reevaluate_certification_verification",
                    "--report",
                    f"{tmp}/r.json",
                    "--apply",
                    stdout=io.StringIO(),
                )
        cert.refresh_from_db()
        self.assertEqual(cert.verification_status, "verified")

    def test_an_agent_acronym_confirms_against_its_full_name(self):
        self.op(
            "Cascade Ridge Orchards",
            "cascade ridge",
            certifier="Washington State Department of Agriculture",
            state="Washington",
        )
        from certifications.services.usda_organic_verifier import USDAOrganicVerifier

        v = USDAOrganicVerifier()
        self.assertEqual(v.verify("Cascade Ridge Orchards", "WA", certifier_name="WSDA").status, "verified")
        self.assertEqual(v.verify("Cascade Ridge Orchards", "WA", certifier_name="CCOF").status, "possible_match")

    def test_the_restore_log_counts_the_transition_it_made(self):
        from common.models import DataOperationLog
        from common.services import data_operations as ops

        written = []
        change = ops.RowChange(
            model="x.Y",
            pk=1,
            before={"verification_status": "verified", "_label": "verified"},
            after={"verification_status": "possible_match", "_label": "possible_match"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/r.json"
            ops.run(
                operation="t", plan=lambda: [change], write=lambda *a: written.append(a), report_path=path, apply=True
            )
            ops.restore(report_path=path, write=lambda *a: written.append(a))
        log = DataOperationLog.objects.get(action="restore")
        self.assertIn("x.Y:possible_match->verified", log.counts)
        self.assertNotIn("x.Y:verified->possible_match", log.counts)

    def test_the_applied_report_cannot_be_overwritten_and_only_it_restores(self):
        """Review of back #123: the documented sequence reused one report path, so the
        verification dry run after an apply erased the only record of what the apply changed,
        and --restore then restored nothing."""
        import json

        from common.models import DataOperationLog
        from common.services import data_operations as ops

        written = []
        write = lambda *a: written.append(a)  # noqa: E731
        change = ops.RowChange(model="x.Y", pk=1, before={"v": "a"}, after={"v": "b"})
        with tempfile.TemporaryDirectory() as tmp:
            path, dry = f"{tmp}/applied.json", f"{tmp}/dry.json"
            ops.run(operation="t", plan=lambda: [change], write=write, report_path=path)
            ops.run(operation="t", plan=lambda: [change], write=write, report_path=path, apply=True)
            applied = Path(path).read_text()
            with self.assertRaises(ops.ReportError):
                ops.run(operation="t", plan=lambda: [], write=write, report_path=path)
            self.assertEqual(Path(path).read_text(), applied, "the applied report was overwritten")

            # The verification dry run after the apply (it plans nothing) is not a restore source.
            ops.run(operation="t", plan=lambda: [], write=write, report_path=dry)
            with self.assertRaises(ops.ReportError):
                ops.restore(report_path=dry, write=write)
            edited = json.loads(applied)
            edited["changes"][0]["before"]["v"] = "z"
            Path(dry).write_text(json.dumps(edited))
            with self.assertRaises(ops.ReportError):
                ops.restore(report_path=dry, write=write)
            self.assertFalse(DataOperationLog.objects.filter(action="restore").exists())

            written.clear()
            ops.restore(report_path=path, write=write)
            self.assertEqual(written, [("x.Y", 1, {"v": "a"})])

    def test_consumer_surfaces_list_rechecked_certifications_as_self_reported(self):
        from pathlib import Path as _P

        from certifications.constants import CONSUMER_LISTED_STATUSES

        self.assertIn("possible_match", CONSUMER_LISTED_STATUSES)
        self.assertIn("listing_match", CONSUMER_LISTED_STATUSES)
        root = _P(__file__).resolve().parents[2]
        for rel in ("history/views_consumer.py", "history/serializers_consumer.py", "history/transparency_views.py"):
            src = (root / rel).read_text()
            self.assertNotIn('verification_status__in=["verified", "self_reported"]', src, rel)
            self.assertIn("CONSUMER_LISTED_STATUSES", src, rel)
