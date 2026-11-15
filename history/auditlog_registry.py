"""
NOP audit-trail model registration (Sprint 2.1).

Registers history models with django-auditlog so every create/update/delete is captured
with user attribution + JSON diff. Mirrors 21 CFR Part 11 trustworthy-records principles
that USDA-accredited certifiers use to evaluate digital recordkeeping systems.

Sensitive fields are excluded (auth tokens, internal scoring fields). Computed/timestamp
fields are excluded so the diff only shows meaningful business changes.
"""

from auditlog.registry import auditlog

from history.models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    Production,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)

# History (production header)
# Excludes auto-computed / engagement counters whose diffs are noise to inspectors.
# (Field names verified against history/models.py — qr_code_url and carbon_score do
# NOT exist on this model; previous draft listed them in error.)
# `transparency_score` left this list on 2026-09-30 with the column itself. An
# exclude_fields entry naming a field that does not exist is not an error django-auditlog
# raises, so it would have sat here indefinitely looking like a decision.
auditlog.register(
    Production,
    exclude_fields=[
        "public_views",
        "unique_visitors",
        "reputation",
        "confidence_score",
        "qr_code",  # generated image, not user-edited content
    ],
)

# Common-event subclasses — all fields tracked
auditlog.register(ProductionEvent)
auditlog.register(ChemicalEvent)
auditlog.register(SoilManagementEvent)
auditlog.register(PestManagementEvent)
auditlog.register(BusinessEvent)
auditlog.register(WeatherEvent)
auditlog.register(GeneralEvent)
auditlog.register(EquipmentEvent)
