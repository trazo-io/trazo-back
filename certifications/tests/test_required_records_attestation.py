"""The records attestation covers every record the plan's own activities require.

WHY THIS EXISTS
---------------
OSP alignment audit 2026-10, T17-F1 (CCOF G8.0 A1). CCOF asks whether the operation maintains ALL
records needed "based on the activities described in your OSP". Trazo's statement said "the records
confirmed above" and its gate refused only an EMPTY list, so a plan that applies inputs and harvests
could attest with harvest records alone.

Rules held here (Oscar's Phase 3 corrections):
  * Yes only when every required record type is confirmed;
  * "not kept" is no way out of a required record: it is a missing record, named with its reason;
  * an unanswered question that decides a requirement keeps it unresolved, which also blocks Yes;
  * a Yes given before the statement covered every required record stays as given, prints with a
    [REVIEW] line naming what is missing, and counts as unanswered on the coverage page.
"""

import io

from django.test import TestCase

import pdfplumber
from rest_framework.test import APIClient

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.services.attestation_gates import blocked_attestations
from certifications.services.certifier_register import Item
from certifications.services.common_osp_records import confirm, mark_not_kept
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.packet_answers import _Answers, row_answer_state
from certifications.services.required_records import NOT_KEPT, UNRESOLVED, required_records
from company.models import Company, Establishment
from users.models import User, WorksIn

G8 = "g8_0_record_keeping"
ATTESTATION = "records_retention_attestation"


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Required Records Co")
        self.est = Establishment.objects.create(name="Required Records Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.module = MODULES_BY_KEY[G8]

    def _answer(self, module, **values):
        responses = dict(self.osp.module_responses or {})
        modules = dict(responses.get("modules") or {})
        entry = dict(modules.get(module) or {})
        entry["answers"] = {**(entry.get("answers") or {}), **values}
        modules[module] = entry
        responses["modules"] = modules
        self.osp.module_responses = responses
        self.osp.save(update_fields=["module_responses"])

    def _applies_inputs_and_harvests(self, *, leave_unanswered=None):
        answers = {
            ("materials_application", "no_materials_used"): False,
            ("g5_0_pest", "applies_pest_weed_disease_inputs"): False,
            ("g6_1_harvest_transport", "who_harvests"): ["own_crew"],
            ("g4_1_compost_manure", "materials_applied"): ["purchased_compost"],
            ("g6_2_storage", "storage_shared_with_nonorganic"): False,
            # 2026-11-18, CCOF G8.0 A1: storage named (storage records), not sold as organic, a buyer picks up.
            ("g6_2_storage", "storage_locations"): ["on_farm_cold"],
            ("g8_0_record_keeping", "sells_as_organic"): False,
            ("g6_1_harvest_transport", "who_transports"): ["buyer_pickup"],
            ("g6_5_sales_soe", "sales_soe_supplier_verification"): "no",
            ("g3_0_seeds", "seeds_used"): ["organic_untreated"],
            # Since 2026.11.25 commercial availability also applies to non-organic planting stock, so
            # the stock answer decides it too.
            ("g3_0_seeds", "planting_stock_used"): ["organic"],
        }
        for (module, question), value in answers.items():
            if (module, question) == leave_unanswered:
                continue
            self._answer(module, **{question: value})

    def _blocked(self):
        self.osp.refresh_from_db()
        return blocked_attestations(self.module, {ATTESTATION: True}, self.osp)

    def _g8_text(self):
        pdf = generate_module_pdf(self.osp, G8)
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            return " ".join(" ".join((page.extract_text() or "") for page in doc.pages).split())


class MissingRequiredRecordsTests(_Plan):
    def test_inputs_and_harvest_with_only_harvest_confirmed_is_refused_and_named(self):
        self._applies_inputs_and_harvests()
        confirm(self.osp, ["harvest_records"], user=None)
        blocked = self._blocked()
        self.assertIn(ATTESTATION, blocked)
        self.assertIn("Input/material application", blocked[ATTESTATION])
        text = self._g8_text()
        self.assertIn("Records this plan's activities require that are not confirmed above", text)
        self.assertIn("Input/material application: not confirmed; required because the materials list says", text)

    def test_not_kept_is_not_a_way_out(self):
        self._applies_inputs_and_harvests()
        confirm(self.osp, ["harvest_records"], user=None)
        mark_not_kept(self.osp, "input_material_application", "we buy only OMRI inputs and keep no log")
        states = {r.key: r.state for r in required_records(self.osp)}
        self.assertEqual(states.get("input_material_application"), NOT_KEPT)
        self.assertIn(ATTESTATION, self._blocked())
        text = self._g8_text()
        self.assertIn("does not keep this record (we buy only OMRI inputs and keep no log)", text)

    def test_an_unanswered_deciding_question_keeps_it_unresolved_and_blocks(self):
        self._applies_inputs_and_harvests(leave_unanswered=("g6_2_storage", "storage_shared_with_nonorganic"))
        confirm(self.osp, ["harvest_records", "input_material_application", "storage_records"], user=None)
        states = {r.key: r.state for r in required_records(self.osp)}
        self.assertEqual(states.get("clean_out_records"), UNRESOLVED)
        self.assertIn(ATTESTATION, self._blocked())

    def test_every_required_record_confirmed_is_accepted(self):
        self._applies_inputs_and_harvests()
        confirm(self.osp, ["harvest_records", "input_material_application", "storage_records"], user=None)
        self.assertEqual(self._blocked(), {})

    def test_a_question_hidden_by_an_answered_trigger_requires_nothing(self):
        """A farm that makes no compost is never asked its compost method; that is not unresolved."""
        self._applies_inputs_and_harvests()
        keys = {r.key for r in required_records(self.osp)}
        self.assertNotIn("compost_production", keys)


class ALegacyYesTests(_Plan):
    def test_a_stored_yes_over_missing_records_is_printed_with_review_and_counts_as_unanswered(self):
        self._applies_inputs_and_harvests()
        confirm(self.osp, ["harvest_records"], user=None)
        # Stored the way a plan attested before the gate covered required records.
        self._answer(G8, **{ATTESTATION: True})
        self.osp.refresh_from_db()
        item = Item(ref="A1", asks="All records maintained?", status="partial", questions=(f"{G8}.{ATTESTATION}",))
        self.assertEqual(row_answer_state(_Answers(self.osp), item).state, "unconfirmed")
        text = self._g8_text()
        self.assertIn("[REVIEW] This Yes was given before the statement covered every record", text)
        self.assertIn("Input/material application (not confirmed)", text)


class NotKeptThroughTheAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Not Kept Co")
        self.user = User.objects.create_user(email="notkept@test.com", password="x")
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.est = Establishment.objects.create(name="Not Kept Farm", company=self.company, state="OR")
        self.osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=1, status="draft")
        self.client.force_authenticate(user=self.user)
        self.url = f"/api/companies/{self.company.id}/establishments/{self.est.id}/osps/{self.osp.id}/record-types/"

    def test_a_record_is_stated_not_kept_with_a_reason(self):
        res = self.client.post(
            self.url, {"keys": ["compost_production"], "not_kept": True, "reason": "No compost made"}, format="json"
        )
        self.assertEqual(res.status_code, 200, res.content[:300])
        row = next(r for r in res.json()["record_types"] if r["key"] == "compost_production")
        self.assertTrue(row["not_kept"])
        self.assertFalse(row["confirmed"])
        self.assertEqual(row["not_kept_reason"], "No compost made")

    def test_not_kept_needs_a_reason(self):
        res = self.client.post(self.url, {"keys": ["compost_production"], "not_kept": True}, format="json")
        self.assertEqual(res.status_code, 400)


class ReviewOfBack84Tests(_Plan):
    """Defects the review of back #84 found."""

    def test_with_nothing_confirmed_the_missing_records_are_still_named(self):
        self._applies_inputs_and_harvests()
        text = self._g8_text()
        self.assertIn("No record types have been confirmed", text)
        self.assertIn("Input/material application: not confirmed", text)
        self.assertIn("Harvest records: not confirmed", text)

    def test_a_not_kept_reason_prints_when_nothing_else_is_confirmed(self):
        self._applies_inputs_and_harvests()
        mark_not_kept(self.osp, "input_material_application", "inputs logged by the custom applicator")
        self.assertIn("does not keep this record (inputs logged by the custom applicator)", self._g8_text())

    def test_a_malformed_module_entry_reads_as_unanswered_not_a_crash(self):
        self.osp.module_responses = {"modules": {"materials_application": ["not", "a", "dict"]}}
        self.osp.save(update_fields=["module_responses"])
        try:
            states = {r.key: r.state for r in required_records(self.osp)}
            pdf = generate_module_pdf(self.osp, G8)
        except Exception as exc:  # noqa: BLE001 — the crash IS the defect; fail as an assertion
            self.fail(f"a malformed entry crashed the derivation: {exc!r}")
        self.assertEqual(states.get("input_material_application"), UNRESOLVED)
        self.assertTrue(pdf.startswith(b"%PDF"))


class NotKeptReasonTypeTests(NotKeptThroughTheAPITests):
    def test_a_non_string_reason_is_a_400_not_a_500(self):
        self.client.raise_request_exception = False
        res = self.client.post(
            self.url, {"keys": ["compost_production"], "not_kept": True, "reason": {"a": 1}}, format="json"
        )
        self.assertEqual(res.status_code, 400, res.content[:300])
