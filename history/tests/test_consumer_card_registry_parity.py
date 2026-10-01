"""
A `consumer_card` tier in the display registry must be a field the public payload can carry.

WHY (2026-09-06 review). The registry (trazo-app/src/config/events/*Event.ts) decides which
fields a buyer card SHOWS; PublicHistorySerializer decides which fields the anonymous payload
CARRIES. Nothing tied the two together, and three declarations had drifted: the chemical
`volume_applied` and `nitrogen_percentage` tiers and the business `verification_status` tier all
pointed at keys `_CERTIFIER_ONLY_EVENT_FIELDS` strips — so each read, in the registry, as "this is
on the buyer card" while the card never rendered it. A declaration that does nothing is worse
than none: the next reviewer takes it as the answer.

The check is empirical, not a list: one event per model is written with every consumer_card
name populated (as a column where one exists, otherwise in extra_data / test_results), the
public payload is serialized, and every declared name — or its wire alias — must come back.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from django.db import models
from django.test import TestCase
from django.utils import timezone

from certifications.models import Certification
from company.models import Company, Establishment
from history.models import (
    BusinessEvent,
    ChemicalEvent,
    GeneralEvent,
    History,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)
from history.serializers import PublicHistorySerializer, SoilManagementEventSerializer
from history.services.claim_authority import DATABASE_VERIFICATION_SOURCE
from product.models import Parcel, Product
from users.models import User

REGISTRY_DIR = Path(__file__).resolve().parent.parent.parent.parent / "trazo-app" / "src" / "config" / "events"

REGISTRIES = {
    "weatherEvent.ts": ("weather", WeatherEvent),
    "productionEvent.ts": ("production", ProductionEvent),
    "chemicalEvent.ts": ("chemical", ChemicalEvent),
    "generalEvent.ts": ("general", GeneralEvent),
    "soilEvent.ts": ("soil_management", SoilManagementEvent),
    "pestEvent.ts": ("pest_management", PestManagementEvent),
    "businessEvent.ts": ("business", BusinessEvent),
}

#: Registry name → key the public payload actually uses.
WIRE_ALIASES = {
    "volume_applied": "volume",
    "area_treated": "area",
    "application_method": "way_of_application",
}

#: Registry names that are not payload keys at all: the card reads them from the event's own
#: envelope (title / notes), not from a field.
RENDERED_FROM_THE_ENVELOPE = {"name", "observation", "commercial_name"}

#: Soil lab results live inside the `test_results` JSON column under their own key names; both
#: the read serializers and the public serializer lift them to the registry names.
SOIL_TEST_RESULT_KEYS = dict(SoilManagementEventSerializer.LAB_RESULT_FIELDS)

#: Published only when the operation holds a database-verified certification of that type
#: (claim_authority.public_certifier_name) — the fixture grants one, so the intended path is
#: what gets tested.
BUSINESS_FIXTURE = {"business_type": "certification", "certification_type": "organic_usda"}


def _consumer_card_names(source: str) -> set[str]:
    """Names of every FieldConfig in one registry file that declares a consumer_card tier."""
    names = set()
    # Each field is an object literal; `name:` comes first, `surfaces:` later in the same block.
    for block in re.split(r"\n  \{\n", source):
        m = re.search(r"^\s*name: '([a-z_0-9]+)'", block, re.M)
        if not m:
            continue
        surfaces = re.search(r"surfaces:\s*\{([^}]*)\}", block)
        if surfaces and re.search(r"consumer_card:\s*'(hero|immediate|secondary)'", surfaces.group(1)):
            names.add(m.group(1))
    return names


def _sample_value(field):
    if isinstance(field, models.BooleanField):
        return True
    if isinstance(field, (models.DateTimeField,)):
        return timezone.now()
    if isinstance(field, models.DateField):
        return date(2026, 5, 1)
    if isinstance(field, models.DecimalField):
        return Decimal("2.5")
    if isinstance(field, (models.IntegerField, models.FloatField)):
        return 3
    if isinstance(field, models.JSONField):
        return {}
    if field.choices:
        for value, _label in field.choices:
            if value:
                return value
    return "sample"


class ConsumerCardRegistryParityTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="parity@test.com", password="x")
        company = Company.objects.create(name="Parity Farm")
        establishment = Establishment.objects.create(name="P1", company=company, state="OR")
        parcel = Parcel.objects.create(name="PP1", establishment=establishment, area=5.0)
        self.history = History.objects.create(
            name="Parity Production",
            start_date=timezone.now() - timedelta(days=30),
            product=Product.objects.create(name="Blueberries"),
            parcel=parcel,
            operator=user,
            earning=0.0,
            production_amount=0.0,
            reputation=0.0,
            confidence_score=0.0,
            public_views=0,
            unique_visitors=0,
            is_outdoor=True,
            published=True,
        )
        # Opens the certifier-attestation gate for the business event (see BUSINESS_FIXTURE).
        Certification.objects.create(
            establishment=establishment,
            certification_type="usda_organic",
            certifier_name="Oregon Tilth",
            certification_number="OT-1",
            verification_status="verified",
            verification_source=DATABASE_VERIFICATION_SOURCE,
        )

    def test_registry_files_are_readable(self):
        self.assertTrue(REGISTRY_DIR.exists(), REGISTRY_DIR)
        total = sum(len(_consumer_card_names((REGISTRY_DIR / f).read_text())) for f in REGISTRIES)
        self.assertGreater(total, 60, "the parser found too few consumer_card declarations to be trusted")

    def test_every_consumer_card_declaration_reaches_the_public_payload(self):
        missing: dict[str, list[str]] = {}
        for filename, (wire_type, model) in REGISTRIES.items():
            declared = _consumer_card_names((REGISTRY_DIR / filename).read_text()) - RENDERED_FROM_THE_ENVELOPE
            columns = {f.name: f for f in model._meta.get_fields() if getattr(f, "concrete", False)}
            kwargs = {"history": self.history, "date": timezone.now(), "description": "parity"}
            # Required columns with no default (the subtype `type`, `business_type`, …) get a
            # valid sample so the row can be written at all.
            for column in columns.values():
                if column.is_relation or column.auto_created or column.name in kwargs:
                    continue
                if not column.null and not column.blank and not column.has_default():
                    kwargs[column.name] = _sample_value(column)
            extra = {}
            test_results = {}
            for name in declared:
                wire = WIRE_ALIASES.get(name, name)
                if wire in columns and not columns[wire].is_relation:
                    kwargs[wire] = _sample_value(columns[wire])
                elif name in columns and not columns[name].is_relation:
                    kwargs[name] = _sample_value(columns[name])
                elif model is SoilManagementEvent and name in SOIL_TEST_RESULT_KEYS:
                    test_results[SOIL_TEST_RESULT_KEYS[name]] = "2026-05-01" if name.endswith("date") else "sample"
                else:
                    extra[name] = "sample"
            if extra:
                kwargs["extra_data"] = extra
            if test_results and "test_results" in columns:
                kwargs["test_results"] = test_results
            # Chemical: the public serializer keys the family on `type`.
            if model is ChemicalEvent:
                kwargs.setdefault("type", "FE")
                kwargs["commercial_name"] = "Parity Product"
            if model is BusinessEvent:
                kwargs.update(BUSINESS_FIXTURE)
                kwargs["verified_certifier_name"] = "Oregon Tilth"
            event = model.objects.create(**kwargs)

            payload = PublicHistorySerializer(self.history).data
            # The fixture holds exactly this one event, so the payload's event list IS it.
            events = payload.get("events") or []
            self.assertEqual(len(events), 1, f"{wire_type}: expected the one fixture event in the public payload")
            keys = set()
            for e in events:
                keys.update(k for k, v in e.items() if v not in (None, "", [], {}))
                keys.update(k for k, v in (e.get("extra_data") or {}).items() if v not in (None, "", [], {}))
            absent = sorted(n for n in declared if n not in keys and WIRE_ALIASES.get(n, n) not in keys)
            if absent:
                missing[filename] = absent
            event.delete()

        self.assertEqual(
            missing,
            {},
            "these registry fields declare a consumer_card tier the public payload never carries — "
            "the card cannot render them, and the declaration reads as if it does. Either lift the "
            "key in PublicHistorySerializer (a publishing decision) or drop the tier:\n"
            + "\n".join(f"  {f}: {', '.join(names)}" for f, names in missing.items()),
        )
