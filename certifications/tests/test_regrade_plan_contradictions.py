"""Answers the blind re-grade of 2026-11-19 found contradicted elsewhere in the same packet, with nothing saying so.

  CCOF G6.2 A1 (and OTCO C7, WSDA K): Coldwater Bench attested G6.2 "product is never stored" while its G6.1 sends
  the crop to cold storage before the buyer and its packer, on file, stores the crop.

  CCOF contract D4, OTCO O1 D-1A: "no other agency certifies the operation today" beside parcels recorded as
  certified by WSDA under this operation, in a packet addressed to another agent.

Each check is tested on the fact that triggers it and on the fact that must not (premise first).
"""

import io

from django.test import TestCase

from pdfminer.high_level import extract_text

from certifications.models import OrganicSystemPlan, PostHarvestFacility
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.plan_contradictions import history_answer_lines, storage_na_contradictions
from company.models import Company, Establishment
from product.models import Parcel

AT = "2026-11-19T10:00:00Z"
WSDA = "Washington State Department of Agriculture"
OTCO = "Oregon Tilth Certified Organic"


def _text(data: bytes) -> str:
    return " ".join(extract_text(io.BytesIO(data)).split())


def _answered(answers):
    return {"answers": {k: {"at": AT, "value": v} for k, v in answers.items()}}


def _na():
    return {"answers": {}, "not_applicable": True, "na_attestation": {"by": None, "at": AT}}


class _Plan(TestCase):
    def setUp(self):
        self.est = Establishment.objects.create(
            name="Bench Orchard", company=Company.objects.create(name="Bench Orchard LLC"), state="WA"
        )

    def plan(self, modules, certifier=OTCO):
        return OrganicSystemPlan.objects.create(
            establishment=self.est,
            version_number=OrganicSystemPlan.objects.count() + 1,
            status="draft",
            certifier_name=certifier,
            module_responses={"schema_version": 1, "parcel_modules": {}, "modules": modules},
        )


class StorageNotApplicableTests(_Plan):
    def test_cold_storage_before_the_buyer_contradicts_never_stored(self):
        quiet = self.plan(
            {"g6_2_storage": _na(), "g6_1_harvest_transport": _answered({"first_stop_before_buyer": ["none"]})}
        )
        self.assertEqual(storage_na_contradictions(quiet), [], "premise: straight to the buyer is no contradiction")
        osp = self.plan(
            {"g6_2_storage": _na(), "g6_1_harvest_transport": _answered({"first_stop_before_buyer": ["cold_storage"]})}
        )
        line = "[REVIEW] G6.2 is marked not applicable, but G6.1 states the crop goes to cold storage before the buyer."
        self.assertEqual(storage_na_contradictions(osp), [line])
        page = _text(generate_module_pdf(osp, "g6_2_storage"))
        self.assertIn("Not applicable", page, "premise: the attestation is what the page prints")
        self.assertIn(line, page)

    def test_a_facility_that_stores_the_crop_contradicts_it_until_ownership_transfers(self):
        PostHarvestFacility.objects.create(establishment=self.est, name="Packing Co.", role="both")
        PostHarvestFacility.objects.create(establishment=self.est, name="Huller", role="handling")
        osp = self.plan({"g6_2_storage": _na()})
        self.assertEqual(
            storage_na_contradictions(osp),
            ["[REVIEW] G6.2 is marked not applicable, but these facilities on file store the crop: Packing Co."],
        )
        sold = self.plan(
            {
                "g6_2_storage": _na(),
                "g6_1_harvest_transport": _answered({"handled_by_another_operation": "yes_ownership_transfers"}),
            }
        )
        self.assertEqual(storage_na_contradictions(sold), [], "the handler stores its own crop, not this operation's")


class CertificationHistoryTests(_Plan):
    def _parcel(self, name, **answers):
        return Parcel.objects.create(
            name=name,
            establishment=self.est,
            area=4.0,
            application_answers={"currently_certified": "yes", "prior_certifier_name": WSDA, **answers},
        )

    def test_parcels_certified_by_another_agent_contradict_no_other_agency(self):
        self._parcel("Block 1")
        self._parcel("Block 2")
        self._parcel("Bought block", certified_operation_name="Ridge Orchard Co")
        same_agent = self.plan({}, certifier=WSDA)
        self.assertEqual(
            history_answer_lines(same_agent, "history_certified_elsewhere_now", False),
            [],
            "premise: under WSDA itself the parcels' agent is the plan's",
        )
        osp = self.plan({}, certifier=OTCO)
        self.assertEqual(
            history_answer_lines(osp, "history_certified_elsewhere_now", False),
            [
                "[REVIEW] The plan states no other agency certifies the operation today, but these parcels are "
                f"recorded as certified by {WSDA}: Block 1, Block 2."
            ],
        )
        self.assertEqual(history_answer_lines(osp, "history_certified_elsewhere_now", True), [])

    def test_never_certified_beside_certified_parcels(self):
        self._parcel("Block 1")
        osp = self.plan({}, certifier=OTCO)
        self.assertEqual(
            history_answer_lines(osp, "history_ever_certified", False),
            ["[REVIEW] The plan states the operation has never been certified, but parcels are recorded as certified."],
        )

    def test_the_module_pdf_prints_it_under_the_answer(self):
        self._parcel("Block 1")
        osp = self.plan(
            {
                "certification_contract": _answered(
                    {"history_ever_certified": True, "history_certified_elsewhere_now": False}
                )
            },
            certifier=OTCO,
        )
        page = _text(generate_module_pdf(osp, "certification_contract"))
        self.assertIn("certified organic today by another certifying agency", page, "premise: the question prints")
        self.assertIn(f"recorded as certified by {WSDA}: Block 1.", page)
