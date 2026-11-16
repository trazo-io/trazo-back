"""Every row the farm card shows carries its sentence as a code and the data behind it.

Oscar, 2026-10-08, on the Spanish farm-home readiness card: "there are some issues with
translations". The card names each row in the reader's language, but the DETAIL under it was
the packet's English sentence ("3/5 inputs have supplier — fill before audit"), because 55 of
the 56 rows sent nothing a client could write the sentence from. The English stays the packet's
text; each REVIEW or FAIL row now also says `said(code, **params)`, and the card writes it.

Two halves:
- structural: every `snapshot_rows.append` whose status can be REVIEW or FAIL passes a fourth
  element, so a new row cannot ship English-only without this test naming it;
- served: on a season with real findings, every finding on the card's endpoint has a
  `detail_code`, and its params hold data (numbers, dates, keys, the farm's own names), not an
  English phrase.
Red on main with AssertionError.

The certifier page reads the same rows anonymously and must not get the grower's sentence
code: `certifier_detail` keeps the grower's instructions off that page, and a code a client can
turn back into "Add the missing suppliers before the audit" would undo it (review of back #144).
"""

import ast
import re
from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from rest_framework.test import APIClient

from company.models import Company, Establishment
from history.models import ChemicalEvent, PestManagementEvent, Production
from history.services.operation_audit_export_service import OperationAuditExportService
from product.models import Parcel, Product
from users.models import User

SOURCE = Path(__file__).resolve().parents[1] / "services" / "audit_export_service.py"
ACTIONABLE = {"REVIEW", "FAIL"}


def _appends_in_snapshot():
    tree = ast.parse(SOURCE.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "compliance_snapshot_rows")
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "snapshot_rows"
        ):
            yield node


def _possible_statuses(expr):
    """What a status expression can be: a literal, or either branch of a conditional between
    literals ("PASS" if ... else "INFO"). None when it is a variable, which can be anything."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return {expr.value}
    if isinstance(expr, ast.IfExp):
        body, orelse = _possible_statuses(expr.body), _possible_statuses(expr.orelse)
        return None if body is None or orelse is None else body | orelse
    return None


class EveryActionableRowSaysItsSentence(TestCase):
    def test_every_review_or_fail_append_passes_its_code(self):
        missing = []
        seen = 0
        for node in _appends_in_snapshot():
            row = node.args[0]
            if not isinstance(row, ast.Tuple):
                continue
            status = row.elts[1]
            statuses = _possible_statuses(row.elts[1])
            if statuses is not None and not (statuses & ACTIONABLE):
                continue
            seen += 1
            if len(row.elts) < 4:
                missing.append(f"line {node.lineno}: {ast.unparse(row.elts[0])}")
        self.assertGreater(seen, 20, "the walk found too few rows to be reading the real function")
        self.assertEqual(missing, [], "rows the card can show with no sentence code:\n" + "\n".join(missing))


ENGLISH_PHRASE = re.compile(r"\b(the|have|has|missing|records?|before|inputs?)\b\s+\w+", re.IGNORECASE)


class TheCardIsServedTheData(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(email="said@test.com", password="x")
        self.company = Company.objects.create(name="Said Farm")
        self.establishment = Establishment.objects.create(name="S1", company=self.company, state="OR")
        self.parcel = Parcel.objects.create(name="SP1", establishment=self.establishment, area=5.0)
        self.user.companies.add(self.company)
        self.history = Production.objects.create(
            name="Liberty 2026",
            start_date=timezone.now() - timezone.timedelta(days=120),
            product=Product.objects.create(name="Blueberries"),
            parcel=self.parcel,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
        )
        # A blank spray record (fields missing, no supplier) and a pest record with no IPM.
        ChemicalEvent.objects.create(history=self.history, type="PE", date=timezone.now())
        PestManagementEvent.objects.create(history=self.history, type="SC", date=timezone.now())
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _findings(self):
        resp = self.client.get(
            "/api/companies/%s/establishments/%s/certifier-readiness/" % (self.company.id, self.establishment.id)
        )
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return resp.json()["findings"]

    def test_every_finding_has_a_code_and_data_not_english(self):
        findings = self._findings()
        self.assertGreaterEqual(len(findings), 4, [f["label"] for f in findings])
        for f in findings:
            self.assertTrue(f.get("detail_code"), f"no sentence code on {f['label']!r}: {f['detail']!r}")
            for name, value in (f.get("params") or {}).items():
                for text in value if isinstance(value, list) else [value]:
                    if isinstance(text, str):
                        self.assertIsNone(
                            ENGLISH_PHRASE.search(text),
                            f"{f['detail_code']}.{name} carries an English phrase: {text!r}",
                        )

    def test_missing_fields_travel_as_keys(self):
        row = next(f for f in self._findings() if f["row_key"] == "record_completeness_chemical")
        self.assertEqual(row.get("detail_code"), "record_completeness_chemical.fields_missing")
        self.assertEqual(row["params"]["incomplete"], 1)
        self.assertEqual(row["params"]["total"], 1)
        fields = {f["field"] for f in row["params"]["fields"]}
        self.assertTrue({"product_name", "amount_applied", "area_treated"} <= fields, fields)

    def test_the_english_packet_text_is_unchanged(self):
        row = next(f for f in self._findings() if f["row_key"] == "input_traceability")
        self.assertEqual(row["detail"], "0/1 inputs have supplier — fill before audit")
        self.assertEqual(row.get("detail_code"), "input_traceability.supplier_missing")
        self.assertEqual(row["params"], {"recorded": 0, "total": 1})


class TheCertifierPageGetsNoGrowerSentence(SimpleTestCase):
    def test_certifier_findings_carry_no_sentence_code(self):
        row = {
            "label": "Input traceability (§ 205.103)",
            "row_key": "input_traceability",
            "status": "FAIL",
            "detail": "3/5 inputs have supplier — fill before audit",
            "section_hint": "Input Material Application Records section",
            "detail_code": "input_traceability.supplier_missing",
            "params": {"recorded": 3, "total": 5},
        }
        entry = {"production_id": 1, "production_name": "Liberty 2026", "finish_date": None, "findings": [row]}
        service = OperationAuditExportService(establishment=None)
        with mock.patch.object(OperationAuditExportService, "readiness_rows", return_value=[entry]):
            finding = service.readiness_rows_for_certifier()[0]["findings"][0]
        self.assertNotIn("detail_code", finding)
        self.assertNotIn("params", finding)
        self.assertEqual(finding["detail"], "3/5 inputs have supplier")
        self.assertEqual(finding["section_hint"], "Input Material Application Records section")
