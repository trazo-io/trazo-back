"""The public response CONTRACT: what each audience may receive, asserted as a key set.

Three audiences, three contracts — not one universal denylist:

  1. ANONYMOUS   — the QR page. `/api/transparency/<uuid>/` and the non-owner view of
                   `/histories/<uuid>/public_history/`.
  2. BUYER TOKEN — a wholesale buyer holding a `review_token` for an UNPUBLISHED season. Sees
                   the same event-level fields as a shopper; the token widens WHICH seasons
                   resolve, never WHICH fields.
  3. CERTIFIER LINK — `/api/certifier-review/<token>/`. A certifier may legitimately receive
                   things a shopper must not, so this one has its own allow-list. Its metadata
                   endpoint is asserted here to be operation identity only, with no records.

⚠️ WHY THE FIXTURE IS PUBLISHED. The 2026-09-06 audit checked an UNPUBLISHED season, got a 404
and read it as evidence that field filtering worked. It is not: a 404 proves access control and
says nothing about the payload. Every assertion in this file runs against a season that returns
200 with content. Unpublished-anonymous-is-404 is a separate test, below, and claims only what
it tests.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from rest_framework.test import APIRequestFactory

from company.models import Company, Establishment
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    PestManagementEvent,
    Production,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from history.serializers import PublicHistorySerializer
from product.models import Parcel, Product
from users.models import User, WorksIn

#: Substrings that may never appear in ANY key, at ANY depth, of an anonymous or buyer payload.
#: Shape-matched rather than key-listed: the allow-list is 443 entries and the next family to
#: add a supplier column would not be noticed by an enumeration.
FORBIDDEN_KEY_SUBSTRINGS = (
    "supplier",
    "invoice",
    "purchase_order",
    "bill_of_lading",
    # A SUPPLIER's batch id, always prefixed by its family: seed_lot_number,
    # chemical_lot_number, amendment_lot_number, beneficial_lot_number. Matched WITH the
    # underscore on purpose — `harvestDetails.lot_number` is a server-built key holding the
    # operation's OWN `History.lot_id`, which is the § 205.103(b)(2) forward-trace anchor and
    # is deliberately public. (The extra_data guard in the serializer matches bare
    # `lot_number` instead, which is correct in ITS scope: that blob is free-form JSON written
    # by templates and imports, and no legitimate allow-listed key there contains the word.)
    "_lot_number",
    "buyer_",
    "_cost",
    # `CommonEvent.private_note` and anything later named like it. Matched as a SHAPE because the
    # point of the field is that a grower can write anything there — a neighbour's name, a price,
    # a worker's opinion — on the promise that no buyer surface will render it. Verified against
    # the whole public serializer: no legitimate public key contains "private".
    "private",
)

#: Values planted in the fixture that must never surface anywhere in an anonymous payload.
LEAKY_VALUES = (
    "Called Dwyer about drift",
    "Saticoy Grove Nursery",
    "Hydra-Gardens Inc.",
    "BN-2024-GEM-0892",
    "INV-HG-2026-0142",
)


def walk_keys(node, out=None):
    """Every key name in a nested payload."""
    out = out if out is not None else set()
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(str(k))
            walk_keys(v, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            walk_keys(item, out)
    return out


def flatten_values(node, out=None):
    """Every scalar rendered anywhere in a payload, as strings."""
    out = out if out is not None else []
    if isinstance(node, dict):
        for v in node.values():
            flatten_values(v, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            flatten_values(item, out)
    elif node is not None:
        out.append(str(node))
    return out


class PublicPayloadFixtureMixin:
    """A PUBLISHED season carrying one event of every family, each with something to leak."""

    def build_fixture(self, *, published=True, is_demo=False):
        self.user = User.objects.create_user(email="schema@test.com", password="x")
        self.company = Company.objects.create(name="Schema Farm Co")
        self.establishment = Establishment.objects.create(
            name="Schema Farm", company=self.company, state="OR", is_demo=is_demo
        )
        WorksIn.objects.create(user=self.user, company=self.company, role=WorksIn.COMPANY_ADMIN)
        self.parcel = Parcel.objects.create(name="Schema Block", establishment=self.establishment, area=5.0)
        self.product = Product.objects.create(name="Blueberries")
        self.history = Production.objects.create(
            name="Schema Season",
            start_date=timezone.now() - timedelta(days=90),
            product=self.product,
            parcel=self.parcel,
            operator=self.user,
            earning=0.0,
            production_amount=1000.0,
            production_unit="lb",
            lot_id="SCHEMA-LOT-1",
            quality_grade="US Fancy",
            harvest_method="hand",
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=published,
        )
        now = timezone.now()
        ChemicalEvent.objects.create(
            history=self.history,
            type=ChemicalEvent.FUNGICIDE,
            date=now,
            commercial_name="Bordeaux Mix",
            description="Sprayed the north rows after the rain, product from Hydra-Gardens Inc.",
            observation="Bought this batch from Hydra-Gardens Inc. last spring.",
            supplier_name="Hydra-Gardens Inc.",
            purchase_invoice="INV-HG-2026-0142",
            chemical_lot_number="HG-LOT-77",
        )
        # The planting event is the measured leak: the vendor exists ONLY in extra_data, and
        # the supplier's batch id rides the same blob.
        ProductionEvent.objects.create(
            history=self.history,
            type="PL",
            date=now,
            description="Replanted 28 trees with stock from Saticoy Grove Nursery.",
            observation="Stock came from Saticoy Grove Nursery.",
            private_note="Called Dwyer about drift off the county road; he denies it. Not for buyers.",
            extra_data={
                "nursery": "Saticoy Grove Nursery, Saticoy CA",
                "seed_supplier": "Saticoy Grove Nursery",
                "seed_lot_number": "BN-2024-GEM-0892",
            },
        )
        WeatherEvent.objects.create(
            history=self.history,
            type="FR",
            date=now,
            description="Cold night",
            # The weather family sources its public `name` from extra_data, not the column.
            extra_data={"event_name": "Frost watch called by Hydra-Gardens Inc."},
        )
        SoilManagementEvent.objects.create(
            history=self.history,
            type="CC",
            date=now,
            description="Cover crop in",
            name="Seed drilled, supplied by Hydra-Gardens Inc.",
        )
        PestManagementEvent.objects.create(history=self.history, type="SC", date=now, description="Walked the block")
        GeneralEvent.objects.create(
            history=self.history,
            date=now,
            name="Fence repair by Hydra-Gardens Inc.",
            activity_type="Farm Maintenance",
            activity_name="Repaired the east fence with Hydra-Gardens Inc. materials",
            description="Fence work",
        )
        BusinessEvent.objects.create(
            history=self.history, type="CE", date=now, description="Annual inspection", name="Inspection visit"
        )

    #: `type` is NOT a stable family key on this payload — chemical events carry
    #: `type: "chemical"` while production carries `type: "PL"` and weather `type: "FR"`. The
    #: numeric `event_type` is the API's own family vocabulary and is uniform.
    FAMILY_BY_EVENT_TYPE = {
        0: "weather",
        1: "production",
        2: "chemical",
        3: "general",
        5: "soil_management",
        6: "pest_management",
        7: "business",
    }

    def events_by_family(self, payload):
        out = {}
        for event in payload["events"]:
            family = self.FAMILY_BY_EVENT_TYPE.get(event.get("event_type"))
            if family:
                out[family] = event
        return out

    def anonymous_payload(self):
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = type("Anon", (), {"is_authenticated": False, "is_superuser": False})()
        return PublicHistorySerializer(self.history, context={"request": request}).data


class AnonymousContractTests(PublicPayloadFixtureMixin, TestCase):
    """Audience 1 — a shopper with a QR code."""

    def setUp(self):
        self.build_fixture(published=True)
        self.payload = self.anonymous_payload()

    def test_the_fixture_actually_returns_content(self):
        """Guard against a vacuous pass: every assertion below is worthless on an empty payload."""
        self.assertTrue(self.payload.get("events"), "fixture produced no events — assertions would be vacuous")
        self.assertGreaterEqual(len(self.payload["events"]), 7)

    def test_no_forbidden_key_at_any_depth(self):
        keys = walk_keys(self.payload)
        offenders = sorted(k for k in keys if any(sub in k.lower() for sub in FORBIDDEN_KEY_SUBSTRINGS))
        self.assertEqual(offenders, [], f"commercially sensitive keys on the anonymous payload: {offenders}")

    def test_no_planted_value_survives_anywhere(self):
        rendered = " || ".join(flatten_values(self.payload))
        for value in LEAKY_VALUES:
            self.assertNotIn(value, rendered, f"{value!r} reached the anonymous payload")

    def test_season_note_is_withheld(self):
        self.assertNotIn("description", self.payload)

    def test_farm_own_lot_identity_is_still_public(self):
        """The counter-test. Withholding a supplier's batch id must not take the farm's own
        lot number with it — that is the § 205.103(b)(2) forward-trace anchor a buyer needs."""
        self.assertEqual(self.payload.get("lot_id"), "SCHEMA-LOT-1")


class EventTitleIsAControlledLabelTests(PublicPayloadFixtureMixin, TestCase):
    """The `description` KEY stays for older SPA builds; its VALUE is a subtype label.

    Asserting the permitted value, not merely the absence of prose — an empty string would
    satisfy "no prose" and break every deployed card heading.
    """

    def setUp(self):
        self.build_fixture(published=True)
        self.events = self.events_by_family(self.anonymous_payload())

    def test_every_family_still_carries_a_description_key(self):
        for family, event in self.events.items():
            self.assertIn("description", event, f"{family} lost the description key older clients read")
            self.assertTrue(str(event["description"]).strip(), f"{family} description is empty")

    def test_the_value_is_the_subtype_label_not_the_stored_prose(self):
        expected = {
            "chemical": "Fungicide",
            "production": "Planting",
            "weather": "Frost",
            "soil_management": "Cover Crop",
            "pest_management": "Scouting",
            "business": "Certification",
        }
        for family, label in expected.items():
            self.assertIn(family, self.events, f"{family} missing from payload")
            self.assertEqual(self.events[family]["description"], label)

    def test_a_family_without_choices_falls_back_to_its_family_default(self):
        """GeneralEvent's `activity_type` is free text with no choices, so there is no label to
        derive — it must fall back, never to the farmer's `name`."""
        self.assertEqual(self.events["general"]["description"], "General Event")

    def test_the_owner_still_sees_the_stored_description(self):
        """The narrowing is aimed at anonymous readers, not at the operation's own staff.

        `ProfileProduction` — the producer's own season page — reads this same endpoint, so
        replacing the title for everyone would have degraded the grower's view of their own
        timeline as a side effect of a consumer privacy fix. The stored text is machine-authored
        ("Fungicide Application: Bordeaux Mix"), and its extra specificity is useful there.
        """
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        owner_payload = PublicHistorySerializer(self.history, context={"request": request}).data
        owner_events = self.events_by_family(owner_payload)
        self.assertIn("Sprayed the north rows", owner_events["chemical"]["description"])

    def test_the_owner_preview_of_the_consumer_view_gets_the_label(self):
        """`force_public_view` is how a producer previews what a shopper sees; it must show the
        shopper's title, not theirs, or the preview would not be a preview."""
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        preview = PublicHistorySerializer(self.history, context={"request": request, "force_public_view": True}).data
        preview_events = self.events_by_family(preview)
        self.assertEqual(preview_events["chemical"]["description"], "Fungicide")

    def test_the_label_still_feeds_the_frontend_keyword_branches(self):
        """`eventDescriptions.ts` keyword-matches this string. The labels ARE those keywords."""
        self.assertIn("frost", self.events["weather"]["description"].lower())
        self.assertIn("fungicide", self.events["chemical"]["description"].lower())
        self.assertIn("plant", self.events["production"]["description"].lower())


class VendorProseRedactionTests(PublicPayloadFixtureMixin, TestCase):
    """A vendor named only in `extra_data`, and one named on a DIFFERENT event."""

    def setUp(self):
        self.build_fixture(published=True)
        self.events = self.events_by_family(self.anonymous_payload())

    def test_extra_data_only_vendor_is_redacted_from_prose(self):
        """The measured 2026-09-08 gap: `seed_supplier_name` was unset, the nursery lived in
        `extra_data`, so the redactor had zero candidates and published the name verbatim."""
        planting = self.events["production"]
        self.assertNotIn("Saticoy Grove", str(planting.get("observation") or ""))
        self.assertIn("[supplier withheld]", str(planting.get("observation") or ""))

    def test_a_supplier_from_another_event_is_redacted_too(self):
        """The general event names a supplier that is structured data on the CHEMICAL event."""
        general = self.events["general"]
        rendered = " ".join(str(general.get(k) or "") for k in ("name", "activity_name", "observation"))
        self.assertNotIn("Hydra-Gardens", rendered)

    def test_supplier_batch_id_is_gone_from_extra_data(self):
        planting = self.events["production"]
        self.assertNotIn("seed_lot_number", planting.get("extra_data") or {})


class SeasonNoteDestinationTests(PublicPayloadFixtureMixin, TestCase):
    """Where the finish form's Observations box actually lands, and who may read it.

    `History.finish()` aliases the finish dialog's Observations onto `History.description`
    ("Finalization NOTES are aliased onto `description`"), and the form's own section label
    tells the farmer it is not shown to buyers. Until 2026-09-08 that field shipped raw on the
    anonymous payload, so the label was false. A label is not a privacy control; this test is.
    """

    DISTINCTIVE = "Rain split the late fruit and we dumped two bins behind the packhouse."

    def setUp(self):
        self.build_fixture(published=True)
        self.history.finish(
            {
                "observation": self.DISTINCTIVE,
                "production_amount": 1000.0,
                "lot_id": "SCHEMA-LOT-1",
                "production_unit": "lb",
                "finish_date": timezone.now(),
                "published": "true",
            },
            [],
        )
        self.history.refresh_from_db()

    def test_the_finish_form_note_really_lands_on_history_description(self):
        """Trace, not assumption: assert the destination before asserting who can read it."""
        self.assertEqual(self.history.description, self.DISTINCTIVE)

    def test_it_is_absent_from_the_anonymous_payload(self):
        rendered = " || ".join(flatten_values(self.anonymous_payload()))
        self.assertNotIn("dumped two bins", rendered)

    def test_the_owner_still_reads_it(self):
        """Withheld from buyers, not lost. The producer's own view keeps it."""
        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        payload = PublicHistorySerializer(self.history, context={"request": request}).data
        self.assertEqual(payload.get("description"), self.DISTINCTIVE)

    def test_it_survives_in_the_free_records_export(self):
        """The farmer's own copy must still contain it — § 205.103 records are theirs."""
        import csv
        import io
        import zipfile

        from history.services.records_export import export_establishment_records_zip

        blob = export_establishment_records_zip(self.establishment)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            rows = list(csv.DictReader(io.StringIO(zf.read("productions.csv").decode())))
        self.assertTrue(any(self.DISTINCTIVE in (r.get("description") or "") for r in rows))


class HarvestGradeIsNotPublishedTests(PublicPayloadFixtureMixin, TestCase):
    """The close form says grade and method are not shown to consumers. Now true."""

    def setUp(self):
        self.build_fixture(published=True)

    def test_grade_and_method_are_absent_from_the_transparency_harvest_block(self):
        resp = self.client.get(
            f"/api/transparency/{self.history.public_id}/",
            HTTP_USER_AGENT="Mozilla/5.0 (schema-test)",
        )
        self.assertEqual(resp.status_code, 200)
        harvest = resp.json().get("harvestDetails") or {}
        self.assertNotIn("quality_grade", harvest)
        self.assertNotIn("harvest_method", harvest)
        self.assertEqual(harvest.get("lot_number"), "SCHEMA-LOT-1")


class UnpublishedAccessTests(PublicPayloadFixtureMixin, TestCase):
    """Access control, asserted separately from field filtering — and claiming only that."""

    def setUp(self):
        self.build_fixture(published=False)

    def test_unpublished_season_is_404_anonymously(self):
        resp = self.client.get(
            f"/api/transparency/{self.history.public_id}/",
            HTTP_USER_AGENT="Mozilla/5.0 (schema-test)",
        )
        self.assertEqual(resp.status_code, 404)


class BuyerTokenContractTests(PublicPayloadFixtureMixin, TestCase):
    """Audience 2 — a buyer link widens WHICH seasons resolve, never WHICH fields."""

    def setUp(self):
        from certifications.models import CertifierAccessLink

        self.build_fixture(published=False)
        self.link = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            label="Buyer diligence",
            audience="buyer",
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_the_token_opens_the_unpublished_season(self):
        resp = self.client.get(
            f"/api/transparency/{self.history.public_id}/?review_token={self.link.token}",
            HTTP_USER_AGENT="Mozilla/5.0 (schema-test)",
        )
        self.assertEqual(resp.status_code, 200, "fixture is vacuous if the token does not open the season")

    def test_the_buyer_gets_the_same_field_contract_as_a_shopper(self):
        resp = self.client.get(
            f"/api/transparency/{self.history.public_id}/?review_token={self.link.token}",
            HTTP_USER_AGENT="Mozilla/5.0 (schema-test)",
        )
        body = resp.json()
        offenders = sorted(k for k in walk_keys(body) if any(s in k.lower() for s in FORBIDDEN_KEY_SUBSTRINGS))
        self.assertEqual(offenders, [], f"buyer token widened the FIELD contract: {offenders}")
        rendered = " || ".join(flatten_values(body))
        for value in LEAKY_VALUES:
            self.assertNotIn(value, rendered)


class CertifierLinkContractTests(PublicPayloadFixtureMixin, TestCase):
    """Audience 3 — its own contract. A certifier may receive what a shopper may not.

    Asserted here: the METADATA endpoint is operation identity only. It is not governed by the
    consumer denylist above, and must not be — applying one universal rule across audiences is
    how a certifier ends up unable to see the records they are reviewing.
    """

    ALLOWED_METADATA_KEYS = {
        "operation_name",
        "operation_city",
        "operation_state",
        "certification_type",
        "period_start",
        "period_end",
        "expires_at",
        "label",
    }

    def setUp(self):
        from certifications.models import CertifierAccessLink

        self.build_fixture(published=True)
        self.link = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            label="Inspection 2026",
            audience="certifier",
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_metadata_is_operation_identity_only(self):
        resp = self.client.get(f"/api/certifier-review/{self.link.token}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.json().keys()), self.ALLOWED_METADATA_KEYS)

    def test_metadata_never_carries_the_token_or_internal_ids(self):
        resp = self.client.get(f"/api/certifier-review/{self.link.token}/")
        rendered = " || ".join(flatten_values(resp.json()))
        self.assertNotIn(self.link.token, rendered)
        self.assertNotIn(str(self.establishment.id), rendered.split(" || "))

    def test_a_buyer_token_is_not_a_certifier_token(self):
        from certifications.models import CertifierAccessLink

        buyer = CertifierAccessLink.objects.create(
            establishment=self.establishment,
            token=CertifierAccessLink.generate_token(),
            label="Buyer",
            audience="buyer",
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.assertEqual(self.client.get(f"/api/certifier-review/{buyer.token}/").status_code, 404)


class ProseAliasKeysAreRedactedTests(PublicPayloadFixtureMixin, TestCase):
    """Fixing a key while its ALIAS ships the same string raw is the defect, not the fix.

    🔴 Found reviewing the 2026-09-08 change itself. `name` was routed through vendor redaction
    on all eight families — and three siblings carrying the identical value were missed:

      * `operation_name`      (equipment) — "Frontend compatibility alias" of `name`
      * `soil_management_name` (soil)     — "Compatibility with TimelineService"
      * the weather family's `name`, which is read from `extra_data` rather than the column and
        so did not match the pattern the other seven were fixed by.

    That is precisely the sibling-surface class this whole change exists to close, reproduced
    inside the change that closes it.
    """

    def setUp(self):
        self.build_fixture(published=True)
        self.events = self.events_by_family(self.anonymous_payload())

    def test_the_weather_name_from_extra_data_is_redacted(self):
        name = str(self.events["weather"].get("name") or "")
        self.assertTrue(name, "fixture is vacuous if the weather event has no public name")
        self.assertNotIn("Hydra-Gardens", name)

    def test_the_soil_management_name_alias_is_redacted(self):
        event = self.events["soil_management"]
        for key in ("name", "soil_management_name"):
            self.assertNotIn("Hydra-Gardens", str(event.get(key) or ""), f"{key} leaked a vendor")

    def test_no_alias_disagrees_with_the_key_it_aliases(self):
        """Whatever redaction does, a key and its alias must agree — one of them being raw is
        how the leak survives a fix."""
        event = self.events["soil_management"]
        self.assertEqual(event.get("name"), event.get("soil_management_name"))


class RedactionIsDeterministicTests(TestCase):
    """The same record must redact to the same string on every worker.

    🔴 Found reviewing the 2026-09-08 change. Substitution ran inside the per-name loop, so the
    result depended on the order names arrived in — and the operation-wide registry is a
    frozenset, whose iteration order varies with PYTHONHASHSEED between processes. Measured: the
    same note rendered as

        "Seed came from [supplier withheld] this year."          (some workers)
        "Seed came from [supplier withheld], Wolcott VT this year."  (others)

    because a shorter form had already consumed the text a longer form needed to match,
    stranding the supplier's city and state on a public page.
    """

    NOTE = "Seed came from High Mowing Organic Seeds, Wolcott VT this year."
    REGISTRY = frozenset(
        {
            "High Mowing Organic Seeds, Wolcott VT",
            "High Mowing Organic Seeds; Osborne Quality Seeds",
            "High Mowing Organic Seeds, Wolcott VT; Osborne Quality Seeds",
        }
    )

    def _redact(self, registry):
        from history.services.privacy import VENDOR_REGISTRY_ATTR, redact_own_vendor_names

        event = type("E", (), {"extra_data": None})()
        setattr(event, VENDOR_REGISTRY_ATTR, registry)
        return redact_own_vendor_names(self.NOTE, event)

    def test_the_longest_form_wins_so_no_address_tail_survives(self):
        result = self._redact(self.REGISTRY)
        self.assertNotIn("Wolcott", result)
        self.assertNotIn("VT", result)
        self.assertEqual(result, "Seed came from [supplier withheld] this year.")

    def test_the_result_does_not_depend_on_registry_iteration_order(self):
        """Every permutation of the same names must produce the same string."""
        import itertools

        outputs = {self._redact(tuple(order)) for order in itertools.permutations(self.REGISTRY)}
        self.assertEqual(len(outputs), 1, f"redaction varies with input order: {outputs}")


class EstablishmentFreeTextIsVendorRedactedTests(PublicPayloadFixtureMixin, TestCase):
    """The farm's own profile is a free-text surface too, and it had no vendor scrubber.

    🔴 Found on the LIVE anonymous payload while verifying the 2026-09-08 event-prose fix: the
    events were redacted correctly and the establishment profile published

        farmer.soil_types: [... "Purchased OMRI compost (Rexius)" ...]

    naming a real supplier on the same page. `soil_types`, `water_sources` and
    `irrigation_methods` are farmer-authored JSON lists that reached the wire with no scrubber
    at all, and `about` / `main_activities` / `location_highlights` / `custom_message` went
    through `public_free_text`, which polices claims and has never known a vendor name.
    """

    def setUp(self):
        self.build_fixture(published=True)
        # A supplier that IS structured data on this farm (the chemical event), named inside the
        # profile the way a real operation writes it.
        self.establishment.soil_types = [
            "Winter cover crops",
            "Purchased OMRI compost (Hydra-Gardens Inc.)",
            "Permanent grass alleys",
        ]
        self.establishment.about = "We buy our compost from Hydra-Gardens Inc. every spring."
        self.establishment.save(update_fields=["soil_types", "about"])

    def _farmer_block(self):
        response = self.client.get(
            f"/api/transparency/{self.history.public_id}/",
            HTTP_USER_AGENT="Mozilla/5.0 (schema-test)",
        )
        self.assertEqual(response.status_code, 200)
        return response.json().get("farmer") or {}

    def test_a_supplier_named_in_a_practice_list_is_redacted(self):
        soil_types = self._farmer_block().get("soil_types") or []
        self.assertTrue(soil_types, "fixture is vacuous if the profile list is empty")
        self.assertNotIn("Hydra-Gardens", " || ".join(soil_types))

    def test_the_practice_itself_survives_the_redaction(self):
        """Redact the name, keep the statement. Dropping a farmer's practice from their own
        profile is a worse failure than naming it carefully."""
        soil_types = self._farmer_block().get("soil_types") or []
        self.assertEqual(len(soil_types), 3, "an entry was dropped instead of redacted")
        self.assertTrue(any("Purchased OMRI compost" in entry for entry in soil_types))
        self.assertIn("Winter cover crops", soil_types)

    def test_a_supplier_named_in_the_farm_prose_is_redacted(self):
        about = str(self._farmer_block().get("about") or "")
        self.assertTrue(about, "fixture is vacuous if `about` is empty")
        self.assertNotIn("Hydra-Gardens", about)
