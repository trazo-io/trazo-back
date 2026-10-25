"""Who harvests and who transports are "all that apply" questions (2026.10.25).

WSDA AGR 2121 §J1/§J10 and CCOF G6.1 A1/A2 both ask for every party that harvests or transports the
crop. A single choice made an orchard with its own crew AND a custom harvester pick one, and the
custom harvester's cleanout and records questions then never appeared. Stored answers are wrapped
in a one-item list by migration 0058 on every plan, so nothing the operator said is lost or
re-read, and the questions that hang off them still show.
"""

import importlib
import io

from django.apps import apps as django_apps
from django.test import TestCase

import pdfplumber

from certifications.models import OrganicSystemPlan
from certifications.osp_modules import MODULES_BY_KEY
from certifications.osp_modules.conditions import exclusive_conflicts, invalid_choice_answers, visible_questions
from certifications.services.osp_module_pdf import generate_module_pdf
from certifications.services.required_records import required_records
from company.models import Company, Establishment

G61 = "g6_1_harvest_transport"
MIGRATION = importlib.import_module("certifications.migrations.0058_harvest_who_multichoice")


def _envelope(value):
    return {"at": "2026-08-21T11:28:46+00:00", "value": value}


class _Plan(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Harvest Who Co")
        self.est = Establishment.objects.create(name="Harvest Who Orchard", company=self.company, state="WA")

    def plan(self, status="draft", **answers):
        self._version = getattr(self, "_version", 0) + 1
        osp = OrganicSystemPlan.objects.create(establishment=self.est, version_number=self._version, status=status)
        osp.module_responses = {
            "modules": {G61: {"answers": {k: _envelope(v) for k, v in answers.items()}}},
        }
        osp.save(update_fields=["module_responses"])
        return osp

    def answers(self, osp):
        osp.refresh_from_db()
        return osp.module_responses["modules"][G61]["answers"]

    def visible(self, osp):
        return {q.key for _page, q in visible_questions(MODULES_BY_KEY[G61], self.answers(osp))}


class MigrationTests(_Plan):
    def test_every_status_is_wrapped_and_nothing_else_moves(self):
        plans = [
            self.plan(
                status,
                who_harvests="custom_harvester",
                who_transports="commercial_carrier",
                lot_identification_on_every_load=True,
            )
            for status in ("draft", "submitted", "active", "superseded")
        ]
        MIGRATION.wrap_scalars(django_apps, None)
        for osp in plans:
            answers = self.answers(osp)
            self.assertEqual(answers["who_harvests"]["value"], ["custom_harvester"], osp.status)
            self.assertEqual(answers["who_transports"]["value"], ["commercial_carrier"], osp.status)
            self.assertIs(answers["lot_identification_on_every_load"]["value"], True)
            self.assertEqual(answers["who_harvests"]["at"], "2026-08-21T11:28:46+00:00")

    def test_a_list_is_left_alone_and_the_reverse_unwraps_only_one_item(self):
        several = self.plan(who_harvests=["own_crew", "custom_harvester"])
        one = self.plan(who_harvests="own_crew")
        MIGRATION.wrap_scalars(django_apps, None)
        self.assertEqual(self.answers(several)["who_harvests"]["value"], ["own_crew", "custom_harvester"])
        MIGRATION.unwrap_single(django_apps, None)
        self.assertEqual(self.answers(one)["who_harvests"]["value"], "own_crew")
        self.assertEqual(self.answers(several)["who_harvests"]["value"], ["own_crew", "custom_harvester"])


class GatesTests(_Plan):
    def test_a_migrated_custom_harvester_still_opens_its_questions(self):
        osp = self.plan(status="submitted", who_harvests="custom_harvester", who_transports="buyer_pickup")
        MIGRATION.wrap_scalars(django_apps, None)
        visible = self.visible(osp)
        self.assertIn("custom_harvester_instructions", visible)
        self.assertIn("custom_harvester_records", visible)
        self.assertIn("non_own_transport_records", visible)

    def test_own_crew_and_custom_harvester_together(self):
        osp = self.plan(who_harvests=["own_crew", "custom_harvester"])
        self.assertIn("custom_harvester_cleanout_verified", self.visible(osp))

    def test_sold_standing_cannot_be_combined_with_a_harvester(self):
        """Exclusive: the save refuses the combination (the wizard unchecks the others)."""
        conflicts = exclusive_conflicts(
            MODULES_BY_KEY[G61], {"who_harvests": _envelope(["sold_standing", "custom_harvester"])}
        )
        self.assertEqual(conflicts.get("who_harvests"), "sold_standing")

    def test_every_party_that_is_not_ours_asks_for_its_records(self):
        for party in ("broker", "warehouse_packer", "other_transporter"):
            with self.subTest(party):
                self.assertIn("non_own_transport_records", self.visible(self.plan(who_transports=[party])))
        self.assertNotIn("non_own_transport_records", self.visible(self.plan(who_transports=["own_vehicles"])))

    def test_other_asks_who(self):
        osp = self.plan(who_harvests=["other_harvester"], who_transports=["other_transporter"])
        self.assertTrue({"who_harvests_other", "who_transports_other"} <= self.visible(osp))

    def test_a_single_value_sent_by_an_old_client_is_refused_not_saved(self):
        bad = invalid_choice_answers(MODULES_BY_KEY[G61], {"who_harvests": _envelope("own_crew")})
        self.assertIn("who_harvests", bad)


class PrintsAndRecordsTests(_Plan):
    def _text(self, osp):
        pdf = generate_module_pdf(osp, G61)
        with pdfplumber.open(io.BytesIO(pdf)) as doc:
            return " ".join(" ".join((p.extract_text() or "") for p in doc.pages).split())

    def test_both_harvesters_and_their_answers_print(self):
        osp = self.plan(
            who_harvests=["own_crew", "custom_harvester"],
            custom_harvester_instructions="Harvester blows down the shaker before entering block 7.",
        )
        text = self._text(osp)
        self.assertIn("Our own crew", text)
        self.assertIn("Custom-hired harvester", text)
        self.assertIn("blows down the shaker", text)

    def test_a_crop_sold_standing_requires_no_harvest_records(self):
        def harvest_record(osp):
            return next((r for r in required_records(osp) if r.key == "harvest_records"), None)

        self.assertIsNone(harvest_record(self.plan(who_harvests=["sold_standing"])))
        self.assertIsNotNone(harvest_record(self.plan(who_harvests=["own_crew"])))
