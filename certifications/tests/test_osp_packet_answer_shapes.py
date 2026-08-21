"""The OSP packet must build from the answer shape the app actually writes.

Module answers exist in TWO shapes:
  * the ENVELOPE `{"value": ..., "at": ...}` written by the REST module endpoint
    (certifications/views.py), and
  * the BARE value written by the module wizard — `"split_operation": "yes"`,
    `"drift_safeguards": ["a", "b"]`.

`answer_value()` exists precisely to tolerate both, and the narrative compiler and the
visibility evaluator both use it. `osp_module_pdf` did not: it read
`(answers.get(key) or {}).get("value")`, which raises on a str or a list.

So any module a farmer had actually answered raised
`AttributeError: 'list' object has no attribute 'get'` and took down the whole § 205.406
renewal packet — cover, all 19 module PDFs, both parcel applications and the four workbooks —
along with the per-module download. Found 2026-08-20 building a real farm's packet.
"""

from django.test import TestCase

from certifications.models import OrganicSystemPlan
from certifications.services.osp_module_pdf import generate_module_pdf, generate_osp_packet
from company.models import Company, Establishment


class OspPacketAnswerShapeTests(TestCase):
    def setUp(self):
        company = Company.objects.create(name="Shape Co")
        self.est = Establishment.objects.create(name="Shape Farm", company=company)

    def _osp(self, answers):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            status="draft",
            module_responses={"modules": {"g6_0_production": {"answers": answers}}},
        )

    def test_bare_answers_render(self):
        """The shape the module wizard writes."""
        osp = self._osp(
            {
                "split_operation": "yes",
                "drift_safeguards": ["written_notification", "no_spray_agreements"],
                "split_operation_separation": "Buffer rows are picked separately and sold conventional.",
            }
        )
        pdf = generate_module_pdf(osp, "g6_0_production")
        data = pdf.getvalue() if hasattr(pdf, "getvalue") else pdf
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)

    def test_envelope_answers_still_render(self):
        """The shape the REST endpoint writes — must keep working."""
        osp = self._osp(
            {
                "split_operation": {"value": "yes", "at": "2026-08-20T00:00:00Z"},
                "drift_safeguards": {"value": ["written_notification"], "at": "2026-08-20T00:00:00Z"},
            }
        )
        pdf = generate_module_pdf(osp, "g6_0_production")
        data = pdf.getvalue() if hasattr(pdf, "getvalue") else pdf
        self.assertTrue(data.startswith(b"%PDF"))

    def test_a_list_answer_does_not_crash_the_packet(self):
        """The exact crash: a checkbox_group answer is a list, and `.get` is not a list method."""
        osp = self._osp({"drift_safeguards": ["written_notification", "boundary_signage"]})
        packet = generate_osp_packet(osp)
        data = packet.getvalue() if hasattr(packet, "getvalue") else packet
        self.assertTrue(data[:2] == b"PK", "the packet must be a zip, not an exception")

    def test_the_packet_carries_every_expected_part(self):
        osp = self._osp({"split_operation": "yes"})
        import io as _io
        import zipfile

        packet = generate_osp_packet(osp)
        data = packet.getvalue() if hasattr(packet, "getvalue") else packet
        names = zipfile.ZipFile(_io.BytesIO(data)).namelist()
        self.assertIn("00-cover.pdf", names)
        self.assertIn("01-narrative-snapshot.pdf", names)
        self.assertTrue(any(n.startswith("modules/") for n in names), names[:5])
        self.assertTrue(any(n.startswith("workbooks/") for n in names), names[:5])

    def test_mixed_shapes_in_one_module_render(self):
        """A module edited through both paths ends up mixed — it must still build."""
        osp = self._osp(
            {
                "split_operation": "yes",
                "parallel_production": {"value": "no", "at": "2026-08-20T00:00:00Z"},
                "drift_safeguards": ["boundary_signage"],
            }
        )
        pdf = generate_module_pdf(osp, "g6_0_production")
        data = pdf.getvalue() if hasattr(pdf, "getvalue") else pdf
        self.assertTrue(data.startswith(b"%PDF"))


class ReadinessAnswerShapeTests(TestCase):
    """Third site of the two-answer-shapes class — and the swallow that hid it.

    `OperationReadinessService._check_attestation_support` read
    `(entry.get(key) or {}).get("value")`, which raises AttributeError on the bare-value shape
    the module wizard writes. The evaluation loop caught it and `continue`d, so a check that
    CRASHED and a check that PASSED rendered identically to the operator: the attestation
    warning simply never appeared.
    """

    def setUp(self):
        from company.models import Company, Establishment

        self.company = Company.objects.create(name="Shape Co")
        self.est = Establishment.objects.create(
            name="Shape Farm",
            company=self.company,
            farming_method="organic",
        )

    def _plan(self, answers):
        from certifications.models import OrganicSystemPlan

        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=1,
            module_responses={"modules": {"materials_application": {"answers": answers}}},
        )

    def test_bare_value_answers_do_not_crash_the_readiness_evaluation(self):
        from history.services.operation_readiness_service import OperationReadinessService

        # The module-wizard shape: bare values, no envelope.
        self._plan({"materials_list_complete": True, "fertilizers_listed": True})

        result = OperationReadinessService(self.est).evaluate()

        unavailable = [c for c in result["checked_items"] if c["key"].endswith("_unavailable")]
        self.assertEqual(
            unavailable,
            [],
            f"a readiness check crashed on the bare-value answer shape: {unavailable}",
        )

    def test_envelope_answers_still_work(self):
        from history.services.operation_readiness_service import OperationReadinessService

        self._plan({"materials_list_complete": {"value": True, "at": "2026-08-20T00:00:00Z"}})

        result = OperationReadinessService(self.est).evaluate()
        unavailable = [c for c in result["checked_items"] if c["key"].endswith("_unavailable")]
        self.assertEqual(unavailable, [])

    def test_a_crashed_check_is_reported_not_dropped(self):
        """The swallow itself. A check that raises must produce a visible warning."""
        from unittest.mock import patch

        from history.services.operation_readiness_service import OperationReadinessService

        svc = OperationReadinessService(self.est)
        with patch.object(
            OperationReadinessService,
            "_check_osp",
            side_effect=RuntimeError("boom"),
        ):
            result = svc.evaluate()

        unavailable = [c for c in result["checked_items"] if c["key"].endswith("_unavailable")]
        self.assertEqual(len(unavailable), 1, "a crashed check vanished from the readiness list")
        self.assertEqual(unavailable[0]["status"], "warning")
        # It must not read as a finding about the farm.
        self.assertIn("problem with Trazo", unavailable[0]["detail"])
        # And it must not block submission — Trazo's own bug is not the operation's failure.
        self.assertNotIn(unavailable[0], result["blockers"])
