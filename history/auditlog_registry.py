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
    SalesRecord,
    SoilManagementEvent,
    WeatherEvent,
)

# History (production header)
# Excludes auto-computed / engagement counters whose diffs are noise to inspectors.
# (Field names verified against history/models/: qr_code_url and carbon_score do
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

# Sales (overall review 2026-11, M7-P10). An open season's sale can be hard-deleted (the correction
# path for a typo; a closed season is refused with 423 and voids instead), and until now nothing
# recorded that it had existed: an invoiced sale vanished without a trace. Registered like the events:
# create, update and delete each leave a LogEntry, and a delete keeps the row's last values (the
# invoice number included) in its `changes`.
#
# NEVER register `harvest_events` as an `m2m_fields` entry (checked against django-auditlog 3.4.1):
# its `post_clear` handler logs `model.objects.all()`, so one `.clear()` or `.set(..., clear=True)`
# would write every ProductionEvent in the database, other companies' included, into this sale's
# entry; and every add or remove stringifies each pick through `CommonEvent.__str__` (history, parcel,
# establishment: about 3 queries per pick).
#
# NOTE: the dossier's Record Change History and the production's audit-trail endpoint read the log
# per live record, so a deleted sale appears in neither. The entry exists in `auditlog.LogEntry`
# (content type SalesRecord, action delete) for anyone who queries the log.
auditlog.register(SalesRecord)
