"""
NOP audit-trail model registration for certifications app (Sprint 5A).

Registers OSP, AnnualUpdate, Certification, Affidavit, and NationalListSubstance with
django-auditlog. Mirrors the pattern established in history/auditlog_registry.py:
every create/update/delete captured with user attribution + JSON diff.

Certifier review criteria — 21 CFR Part 11 trustworthy electronic records — require
immutable audit trails on compliance-critical records. These five models hold the
regulatory content an inspector will cross-check.
"""

from auditlog.registry import auditlog

from certifications.models import (
    Certification,
    CertifierInspection,
    CertifierNotice,
    LandownerAffidavit,
    NationalListSubstance,
    OMRIProduct,
    OrganicSystemPlan,
    OSPAnnualUpdate,
)

# OSP + Annual Update — every field tracked. These are the master regulatory records.
auditlog.register(OrganicSystemPlan)
# The frozen filing document is bytes; its change is recorded as `filed_sha256`, which is tracked.
# Supporting documents are a many-to-many with its own table; `m2m_fields` records each attach
# and detach on the filing's own log.
auditlog.register(OSPAnnualUpdate, exclude_fields=["filed_pdf"], m2m_fields={"supporting_documents"})

# Landowner affidavit — signed document, all fields tracked.
auditlog.register(LandownerAffidavit)

# Certification record — exclude raw_api_response (large, noisy) and last_verified_at
# (timestamp churn from background verification jobs).
auditlog.register(
    Certification,
    exclude_fields=["raw_api_response", "last_verified_at", "updated_at"],
)

# National List / OMRI — reference data, tracked for provenance when admins edit.
auditlog.register(NationalListSubstance, exclude_fields=["updated_at"])
auditlog.register(OMRIProduct, exclude_fields=["updated_at"])

# The farm's record of its certifier's inspections and the agent's items (§ 205.662): who changed a
# response or a resolution date, and when, is part of what an inspector may ask about.
auditlog.register(CertifierInspection, exclude_fields=["updated_at"])
auditlog.register(CertifierNotice, exclude_fields=["updated_at"], m2m_fields={"response_documents"})
