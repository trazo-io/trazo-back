"""The buyer page states the record (recordkeeping review S6, 2026-10-07: F-09, F-11, F-25).

F-09: the chip for a grower's own dropdown pick read "Organic-approved · grower-reported", a
verdict word leading an answer nobody but the grower had given; and for two inputs that carried
a National List substance on an unconfirmed basis the tooltip said Trazo had found nothing.
F-11: a checkbox ticked at company sign-up ("Soil Health Focus", "Clean Energy Use") was served
as `farm_context.company_sustainability.goals` and printed as a public "Sustainability
Commitment" list. F-25: "Purchased OMRI compost ([supplier withheld])" on the farm profile, and
"Tangent, -" for a location with no country.

Each test here went red on the code before the fix, on an assertion.
"""

import io
import json
from datetime import timedelta

from django.utils import timezone

from rest_framework.test import APITestCase

from certifications.models import NationalListSubstance
from common.location import city_state_label, joined_parts
from company.models import Company, Establishment
from history.models import ChemicalEvent, History
from history.services.claim_authority import LABEL_INPUT_GROWER_REPORTED
from history.services.claim_resolver import resolve_input_status
from history.services.privacy import redact_supplier_names
from product.models import Parcel, Product
from users.models import User


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class BuyerPageStatesTheRecordTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(email="states-record@test.com", password="x")
        cls.company = Company.objects.create(
            name="Record Co",
            sustainability_metadata={"sustainability_goals": ["soil_health", "renewable_energy"]},
        )
        cls.establishment = Establishment.objects.create(
            name="Record Farm", company=cls.company, city="Tangent", state="OR", country=None
        )
        cls.parcel = Parcel.objects.create(name="Home Field", establishment=cls.establishment, area=5.0)
        cls.product = Product.objects.create(name="Blueberries")
        cls.history = History.objects.create(
            name="Blueberries 2026",
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
            product=cls.product,
            parcel=cls.parcel,
            operator=cls.user,
            earning=0.0,
            production_amount=1000,
            production_unit="lb",
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        cls.lime_sulfur = NationalListSubstance.objects.create(
            substance_name="Lime sulfur",
            substance_name_normalized="lime sulfur",
            cfr_section="205.601",
            subsection="e",
            status="allowed",
        )

    def _event(self, **kwargs):
        return ChemicalEvent.objects.create(
            history=self.history, created_by=self.user, description="spray", date=timezone.now(), **kwargs
        )

    # -- F-09: the chip is a record, not a verdict ---------------------------------------

    def test_the_grower_chip_is_worded_as_a_record(self):
        self.assertEqual(LABEL_INPUT_GROWER_REPORTED, "Recorded by the farm as allowed for organic use")
        status = resolve_input_status(
            self._event(commercial_name="Rex Lime Sulfur", organic_approved="certifier_approved")
        )
        self.assertEqual(status["status"], "organic_approved")
        self.assertFalse(status["label"].lower().startswith("organic-approved"), status["label"])

    def test_an_unconfirmed_national_list_link_is_named_in_the_status(self):
        event = self._event(commercial_name="Rex Lime Sulfur", organic_approved="certifier_approved")
        ChemicalEvent.objects.filter(pk=event.pk).update(
            national_list_substance=self.lime_sulfur, national_list_basis="legacy_unverified"
        )
        event.refresh_from_db()
        status = resolve_input_status(event)
        self.assertEqual(status["status"], "organic_approved", "an unconfirmed basis is not evidence for the chip")
        link = status.get("national_list_link") or {}
        self.assertEqual(link.get("basis"), "not_confirmed")
        self.assertEqual(link.get("substance"), "Lime sulfur")
        # Run 8b R5: the model's citation, never the raw section code (a nonsynthetic row's code
        # is "nonsyn", and the card printed "7 CFR § nonsyn"). Lime sulfur is listed in § 205.601(e)
        # and (i), so the section is cited, never the insecticide paragraph alone (2026-11-04).
        self.assertEqual(link.get("citation"), "§ 205.601")
        self.assertNotIn("cfr_section", link)

    def test_a_name_suggestion_or_a_prohibited_substance_is_never_named_on_the_chip(self):
        # Review of back #133: a substring suggestion is a guess nobody linked; a prohibited
        # substance beside an "allowed" chip would contradict it with nothing to disambiguate.
        copper = NationalListSubstance.objects.create(
            substance_name="Copper sulfate",
            substance_name_normalized="copper sulfate",
            cfr_section="205.601",
            status="allowed",
        )
        event = self._event(commercial_name="Copper Sulfate 25%", organic_approved="certifier_approved")
        ChemicalEvent.objects.filter(pk=event.pk).update(national_list_substance=None, national_list_suggestion=copper)
        event.refresh_from_db()
        self.assertNotIn("national_list_link", resolve_input_status(event))
        strychnine = NationalListSubstance.objects.create(
            substance_name="Strychnine",
            substance_name_normalized="strychnine",
            cfr_section="205.602",
            status="prohibited",
        )
        ChemicalEvent.objects.filter(pk=event.pk).update(
            national_list_substance=strychnine, national_list_suggestion=None, national_list_basis="legacy_unverified"
        )
        event.refresh_from_db()
        self.assertNotIn("national_list_link", resolve_input_status(event))

    def test_a_record_with_no_link_carries_none(self):
        status = resolve_input_status(self._event(commercial_name="Entrust SC", organic_approved="certifier_approved"))
        self.assertNotIn("national_list_link", status)

    # -- F-11: sign-up goals are not a public claim --------------------------------------

    def test_the_public_payload_carries_no_sign_up_goals(self):
        response = self.client.get(f"/api/transparency/{self.history.public_id}/")
        self.assertEqual(response.status_code, 200, response.content[:300])
        payload = response.json()
        sustainability = (payload.get("farm_context") or {}).get("company_sustainability") or {}
        self.assertNotIn("goals", sustainability)
        text = response.content.decode()
        for label in ("Soil Health Focus", "Renewable Energy Use", "soil_health", "renewable_energy"):
            self.assertNotIn(label, text)

    # -- F-25: the profile list and the location line ------------------------------------

    def test_a_supplier_aside_is_dropped_from_a_profile_list_entry(self):
        result = redact_supplier_names(
            ["Purchased OMRI compost (Rexius)", "Seed came from Rexius this year", "Winter cover crops"],
            {"Rexius"},
        )
        self.assertEqual(result[0], "Purchased OMRI compost")
        self.assertEqual(result[1], "Seed came from [supplier withheld] this year", "prose keeps the placeholder")
        self.assertEqual(result[2], "Winter cover crops")
        # Review of back #133: prose that ENDS with the supplier keeps the placeholder; only a
        # parenthetical aside, "(from X)" or "(X)", is dropped.
        prose = redact_supplier_names(["Seed came from Rexius", "Compost (from Rexius)"], {"Rexius"})
        self.assertEqual(prose[0], "Seed came from [supplier withheld]")
        self.assertEqual(prose[1], "Compost")
        # The live column holds the list JSON-encoded; the same rule applies to that string.
        encoded = redact_supplier_names('["Purchased OMRI compost (Rexius)", "Winter cover crops"]', {"Rexius"})
        self.assertEqual(json.loads(encoded), ["Purchased OMRI compost", "Winter cover crops"])

    def test_the_location_line_prints_only_recorded_parts(self):
        self.assertEqual(self.establishment.get_location(), "Tangent, OR")
        self.assertEqual(city_state_label(_Obj(city="Tangent", state="-")), "Tangent")
        self.assertEqual(city_state_label(_Obj(city="", state="OR")), "OR")
        self.assertIsNone(city_state_label(_Obj(city="", state="")))
        self.assertEqual(
            joined_parts(_Obj(city="Tangent", state="OR", country="US"), ("city", "state", "country")),
            "Tangent, OR, US",
        )

    def test_the_public_location_has_no_placeholder(self):
        Establishment.objects.filter(pk=self.establishment.pk).update(state="-")
        try:
            response = self.client.get(f"/api/transparency/{self.history.public_id}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["farmer"]["location"], "Tangent")
        finally:
            Establishment.objects.filter(pk=self.establishment.pk).update(state="OR")


class NationalListCitationFromProvenanceTests(APITestCase):
    """Run 8b R5 (2026-10-15): "7 CFR § nonsyn" on the buyer page.

    Spinosad's catalogue row has `cfr_section="nonsyn"` (migration 0040): a nonsynthetic substance is
    allowed without any National List entry. A record linked to it on a legacy basis was served as
    `national_list_link = {cfr_section: "nonsyn"}` and the card printed "A National List entry
    (Spinosad, 7 CFR § nonsyn)", false twice. Citation validity and match confirmation are separate
    facts: a citation comes only from `NationalListSubstance.citation` for a real entry, and the
    `basis: not_confirmed` disclosure travels with every legacy link.
    """

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(email="r5-owner@test.com", password="x")
        cls.stranger = User.objects.create_user(email="r5-stranger@test.com", password="x")
        company = Company.objects.create(name="R5 Co")
        establishment = Establishment.objects.create(name="R5 Farm", company=company, city="Tangent", state="OR")
        parcel = Parcel.objects.create(name="Block 4", establishment=establishment, area=5.0)
        cls.history = History.objects.create(
            name="Blueberries R5",
            start_date=timezone.now() - timedelta(days=200),
            finish_date=timezone.now() - timedelta(days=10),
            product=Product.objects.create(name="Blueberries"),
            parcel=parcel,
            operator=cls.owner,
            earning=0.0,
            production_amount=1000,
            production_unit="lb",
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        cls.spinosad = NationalListSubstance.objects.create(
            substance_name="Spinosad",
            substance_name_normalized="spinosad",
            cfr_section=NationalListSubstance.NONSYNTHETIC,
            status="allowed",
        )
        cls.lime_sulfur = NationalListSubstance.objects.create(
            substance_name="Lime sulfur",
            substance_name_normalized="lime sulfur",
            cfr_section="205.601",
            subsection="e",
            status="allowed",
        )

    def _linked(self, name, substance, basis):
        event = ChemicalEvent.objects.create(
            history=self.history,
            created_by=self.owner,
            description="spray",
            date=timezone.now(),
            commercial_name=name,
            organic_approved="certifier_approved",
        )
        ChemicalEvent.objects.filter(pk=event.pk).update(national_list_substance=substance, national_list_basis=basis)
        event.refresh_from_db()
        return event

    def _payload(self, user=None):
        if user is not None:
            self.client.force_authenticate(user=user)
        try:
            response = self.client.get(f"/api/transparency/{self.history.public_id}/")
        finally:
            self.client.force_authenticate(user=None)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    @staticmethod
    def _served_events(payload):
        """Every served event dict that carries an input status, keyed by its commercial name."""
        found = {}

        def walk(node):
            if isinstance(node, dict):
                if "input_status" in node and node.get("commercial_name"):
                    found[node["commercial_name"]] = node
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
        return found

    def test_a_legacy_link_to_a_nonsynthetic_row_is_not_a_national_list_entry(self):
        event = self._linked("Entrust SC", self.spinosad, "legacy_unverified")
        status = resolve_input_status(event)
        self.assertEqual(status["status"], "organic_approved")
        self.assertNotIn("national_list_link", status, "a nonsynthetic row was named as a National List entry")
        for label, user in (("anonymous", None), ("signed-in", self.stranger)):
            with self.subTest(payload=label):
                served = self._served_events(self._payload(user))
                self.assertIn("Entrust SC", served, "the request read no event: the assertion below would be vacuous")
                card = served["Entrust SC"]
                self.assertNotIn("national_list_link", card["input_status"])
                self.assertIsNone(card.get("national_list_citation"))

    def test_a_legacy_link_to_a_real_entry_carries_the_citation_and_its_disclosure(self):
        self._linked("Rex Lime Sulfur", self.lime_sulfur, "legacy_unverified")
        for label, user in (("anonymous", None), ("signed-in", self.stranger)):
            with self.subTest(payload=label):
                card = self._served_events(self._payload(user))["Rex Lime Sulfur"]
                self.assertEqual(
                    card["input_status"].get("national_list_link"),
                    {"substance": "Lime sulfur", "citation": "§ 205.601", "basis": "not_confirmed"},
                )
                # Unconfirmed: no confirmed citation on the record itself.
                self.assertIsNone(card.get("national_list_citation"))

    def test_a_confirmed_link_to_a_real_entry_prints_the_section_citation(self):
        self._linked("Lime Sulfur Exact", self.lime_sulfur, "exact")
        card = self._served_events(self._payload())["Lime Sulfur Exact"]
        # Listed in (e) and (i): the section, not one paragraph letter (2026-11-04).
        self.assertEqual(card.get("national_list_citation"), "§ 205.601")
        self.assertEqual(card["input_status"]["status"], "national_list_allowed")
        self.assertNotIn("national_list_link", card["input_status"], "a confirmed basis needs no disclosure link")

    def test_the_anonymous_payload_never_carries_the_nonsynthetic_code(self):
        self._linked("Entrust SC", self.spinosad, "legacy_unverified")
        self._linked("Entrust Operator", self.spinosad, "operator")
        payload = self._payload()
        served = self._served_events(payload)
        self.assertIn("Entrust Operator", served, "the request read no event: the walk below would be vacuous")
        hits = []

        def walk(node, path):
            if isinstance(node, dict):
                for key, value in node.items():
                    if NationalListSubstance.NONSYNTHETIC in str(key):
                        hits.append(f"{path}.{key} (key)")
                    walk(value, f"{path}.{key}")
            elif isinstance(node, list):
                for i, value in enumerate(node):
                    walk(value, f"{path}[{i}]")
            elif isinstance(node, str) and node.strip().lower() in {"nonsyn", "§ nonsyn"}:
                hits.append(f"{path} = {node!r}")
            elif isinstance(node, str) and "§ nonsyn" in node.lower():
                hits.append(f"{path} = {node!r}")

        walk(payload, "$")
        self.assertEqual(hits, [], "the raw nonsynthetic code reached the anonymous payload")

    def test_every_guard_module_national_list_basis_names_exists(self):
        """Its docstring named a `test_national_list_basis` guard that never existed (Run 8b R5)."""
        import re
        from pathlib import Path

        from history.services import national_list_basis

        root = Path(__file__).resolve().parents[2]
        named = set(re.findall(r"\b(test_[a-z0-9_]+)\b", national_list_basis.__doc__ or ""))
        self.assertTrue(named, "the module no longer names its guards")
        missing = sorted(name for name in named if not list(root.glob(f"*/tests/{name}.py")))
        self.assertEqual(missing, [], "national_list_basis.py names a guard module that does not exist")


# Every citation `NationalListSubstance.citation` can produce from the seeded catalogue, plus the bare
# section form it produces for a row with no subsection. The buyer page accepts ONLY these strings
# (trazo-app `src/components/Events/nationalListCitations.ts`, NATIONAL_LIST_CITATIONS). Listed in both
# repos on purpose: a change to the catalogue's sections or subsections fails here first, and the
# frontend's own test (`nationalListCitations.test.ts`) re-derives the same set from this repo's seed
# and model source.
NATIONAL_LIST_CITATIONS = frozenset(
    ["§ 205.105", "§ 205.601", "§ 205.602", "§ 205.603", "§ 205.605", "§ 205.606"]
    + [f"§ 205.105({s})" for s in "aefg"]
    + [f"§ 205.601({s})" for s in "abcdefghijklmno"]
    + [f"§ 205.602({s})" for s in "abcdefghij"]
    + ["§ 205.605(b)"]
)


class NationalListCitationFormsTests(APITestCase):
    def test_the_citation_forms_the_catalogue_produces_are_the_listed_set(self):
        from django.core.management import call_command

        call_command("seed_national_list", stdout=io.StringIO())
        rows = list(NationalListSubstance.objects.all())
        self.assertGreater(len(rows), 50, "the catalogue did not seed: the comparison below would be vacuous")
        produced = {row.citation for row in rows if row.is_national_list_entry}
        produced |= {
            NationalListSubstance(cfr_section=code).citation
            for code, _ in NationalListSubstance.CFR_SECTION_CHOICES
            if code != NationalListSubstance.NONSYNTHETIC
        }
        self.assertEqual(produced, set(NATIONAL_LIST_CITATIONS))
        nonsynthetic = [row for row in rows if not row.is_national_list_entry]
        self.assertTrue(nonsynthetic, "no nonsynthetic row was seeded")
        self.assertEqual({row.citation for row in nonsynthetic}, {""}, "a nonsynthetic row produced a citation")
