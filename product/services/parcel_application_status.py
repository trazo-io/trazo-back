"""
Parcel Application completion status (WS-5, plan Appendix A §f).

Completion reads LIVE model state — never the module answers alone — so a
crop-history row added anywhere in the app, or a boundary drawn on the map,
moves the application forward without re-entry.

Checks (each returns a missing-key when unsatisfied):
  identity      APN or Section-Township-Range present
  transition    date_began_managing set
  buffers       buffer_zones rows exist OR the no-adjoining attestation is set
  map           polygon drawn OR a map upload is attested in answers
  land_history  >= 3 distinct ParcelCropHistory years OR a landowner affidavit
                exists for the parcel (container production skips this check —
                container media is not land)

State: "complete" (all pass) / "in_progress" (any signal present) /
"not_started" (nothing beyond quick-add).
"""

from __future__ import annotations

# Question key → Parcel column for the parcel_field-bound questions. ONE map —
# the application endpoint and the module PDF both read it, so they can never
# disagree about where evidence lives.
PARCEL_FIELD_QUESTIONS = (
    ("parcel_name", "name"),
    ("apn", "apn"),
    ("section_township_range", "section_township_range"),
    ("address", "address"),
    ("container_production", "container_production"),
    ("treated_lumber_present", "treated_lumber_present"),
    ("treated_lumber_description", "treated_lumber_description"),
    ("treated_lumber_install_date", "treated_lumber_install_date"),
    ("date_began_managing", "date_began_managing"),
)


def parcel_application_values(parcel) -> dict:
    """Answers dict for the Parcel Application: bound columns + stored answers."""
    values: dict = {}
    for question_key, field in PARCEL_FIELD_QUESTIONS:
        value = getattr(parcel, field)
        values[question_key] = str(value) if hasattr(value, "isoformat") else value
    values.update(parcel.application_answers or {})
    return values


def parcel_application_status(parcel) -> dict:
    answers = parcel.application_answers or {}
    missing: list = []

    has_identity = bool(parcel.apn) or bool(parcel.section_township_range)
    if not has_identity:
        missing.append("identity")

    if not parcel.date_began_managing:
        missing.append("transition")

    has_buffers = bool(parcel.buffer_zones) or answers.get("no_adjoining_prohibited") is True
    if not has_buffers:
        missing.append("buffers")

    # ⚠️ ONE OF TWO definitions of "does this parcel have a map". The other is the `parcel_map`
    # embed in `certifications/services/osp_module_pdf.py`, which decides what the packet PRINTS.
    # They were allowed to diverge only while nothing could upload a map; the upload question
    # shipped 2026-08-28, so both now read the same two sources and must keep doing so.
    #
    # A drawn boundary OR an uploaded map counts. Neither alone is what CCOF ultimately asks for
    # — its §E lists eleven elements a schematic cannot carry — but either one means the parcel
    # is no longer map-less, and the packet says which of the two the reviewer is holding.
    from certifications.services.osp_module_pdf import parcel_map_documents

    has_map = bool(parcel.polygon) or bool(parcel_map_documents(parcel))
    if not has_map:
        missing.append("map")

    if parcel.container_production:
        has_history = True
    else:
        years = parcel.crop_history.values_list("year", flat=True).distinct().count()
        has_history = years >= 3 or parcel.landowner_affidavits.exists()
    if not has_history:
        missing.append("land_history")

    if not missing:
        state = "complete"
    else:
        any_signal = (
            has_identity
            or bool(parcel.date_began_managing)
            or has_buffers
            or has_map
            or bool(answers)
            or parcel.crop_history.exists()
        )
        state = "in_progress" if any_signal else "not_started"

    return {"state": state, "missing": missing}
