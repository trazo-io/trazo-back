"""Every OSP statement that asserts a record exists must declare how it is evidenced.

The OSP is a producer attestation under § 205.201(a) and the first document a certifier reads.
Two statements were found in August 2026 asserting artifacts the record layer could not
produce — storage bin cards/pallet tags, and container markings tying to a lot while the tag
printed `LOT —`. Both were invisible to code review and only surfaced when the packet was
rendered and read.

This test makes the class impossible to reintroduce silently: a new record-asserting statement
in any OSP module fails the build until someone records, in `osp_evidence_map.py`, whether
Trazo can back it. It does not require that every statement BE evidenced — NOT_EVIDENCED is a
legitimate, documented answer — only that the question was asked and answered.
"""

import re

from django.apps import apps
from django.test import SimpleTestCase

from certifications.osp_modules import MODULE_REGISTRY
from certifications.services.osp_evidence_map import (
    EVIDENCED,
    NOT_EVIDENCED,
    OSP_EVIDENCE_MAP,
    OUT_OF_SCOPE,
    unevidenced_statements,
)

#: Language that asserts an ARTIFACT exists, as opposed to describing a practice.
#: Deliberately broad — a false positive costs one map entry, a false negative costs a
#: statement the packet cannot back.
ASSERTS_RECORD = re.compile(
    r"\b(record(s|ed|ing)?|log(s|ged)?|document(s|ed|ation)?|maintain(ed|s)?|retain(ed|s)?|"
    r"on file|tag(s|ged)?|label(s|led|ed)?|invoice|receipt|tracked|traceab|identif(y|ied|ication)|"
    r"audit trail|bin card|pallet|certificat(e|es|ed|ion))\b",
    re.I,
)


def _record_asserting_questions():
    for module in MODULE_REGISTRY:
        for page in module.pages:
            for question in page.questions:
                rule = question.compiles_to
                if rule and ASSERTS_RECORD.search(rule.template):
                    yield module.code, question


class OspEvidenceMapTests(SimpleTestCase):
    def test_every_record_asserting_statement_is_declared(self):
        undeclared = [
            f"{code}.{q.key} — {q.compiles_to.template[:70]}"
            for code, q in _record_asserting_questions()
            if q.key not in OSP_EVIDENCE_MAP
        ]
        self.assertEqual(
            undeclared,
            [],
            "These OSP statements assert that a record exists but do not say what backs them. "
            "Add an entry to certifications/services/osp_evidence_map.py — EVIDENCED with a "
            "model field, or NOT_EVIDENCED with the reason. Undeclared:\n  " + "\n  ".join(undeclared),
        )

    def test_evidenced_entries_point_at_fields_that_exist(self):
        # Catches drift: a renamed or deleted field silently orphans the claim that cited it.
        broken = []
        for key, entry in OSP_EVIDENCE_MAP.items():
            if entry.status != EVIDENCED:
                continue
            if not entry.source:
                broken.append(f"{key}: EVIDENCED with no source")
                continue
            try:
                app_label, model_name, field_name = entry.source.split(".")
                apps.get_model(f"{app_label}.{model_name}")._meta.get_field(field_name)
            except Exception as exc:  # noqa: BLE001 — any resolution failure is the finding
                broken.append(f"{key}: {entry.source} -> {type(exc).__name__}")
        self.assertEqual(broken, [], "evidence sources no longer resolve:\n  " + "\n  ".join(broken))

    def test_non_evidenced_entries_explain_themselves(self):
        # An undocumented gap is indistinguishable from an oversight six months later.
        for key, entry in OSP_EVIDENCE_MAP.items():
            if entry.status in (NOT_EVIDENCED, OUT_OF_SCOPE):
                with self.subTest(key=key):
                    self.assertTrue(entry.note.strip(), f"{key}: {entry.status} with no explanation")

    def test_map_has_no_entries_for_statements_that_no_longer_exist(self):
        # Keeps the map honest in the other direction: a stale entry reads as coverage.
        live = {q.key for _, q in _record_asserting_questions()}
        stale = sorted(set(OSP_EVIDENCE_MAP) - live)
        self.assertEqual(stale, [], f"map entries for statements no longer in any module: {stale}")

    def test_known_gap_is_still_reported(self):
        # Storage lot identity is the open one. When the storage ledger ships (ship-list Tier 2
        # item 8) this flips to EVIDENCED and this assertion should be updated deliberately,
        # not deleted quietly.
        self.assertIn("lot_identity_maintained", unevidenced_statements())
