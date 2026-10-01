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
