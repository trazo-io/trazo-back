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
  certification_status
                `currently_certified` answered (yes / no / previously). Added
                2026-09-09: CCOF F2, OTCO C2 2.1-7 and WSDA AGR 2264 ref 6 all
                open the land-history section with it, and it decides which
                evidence the parcel page prints (certificate vs 36-month table).
                An unanswered question is not "no".

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


def parcel_application_status(parcel, osp=None) -> dict:
    """Both axes for one parcel. `osp`: the plan a packet is built for; None outside a packet."""
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

    # 🔴 2026-09-24 — THE MAP CHECK LEFT THIS AXIS.
    #
    # It read `bool(parcel.polygon) or bool(parcel_map_documents(parcel))`, so RECORDED GEOMETRY
    # ALONE satisfied it. A parcel with a drawn boundary and no uploaded map therefore reported
    # "complete" — and the packet printed "Parcel application: complete" one page above its own
    # "[REVIEW] No operator-supplied map is attached". One document, two verdicts.
    #
    # A map is EVIDENCE, not an answer. It now lives on the evidence axis below, graded rather
    # than boolean, so the two axes never contradict and the attachment requirement appears in
    # exactly one of them.

    crop_rows = []
    if parcel.container_production:
        has_history = True
    else:
        # `.all()` reads the prefetch cache when the caller loaded `crop_history` /
        # `landowner_affidavits` (the company payload does, for every parcel at once); the
        # `.count()` / `.exists()` forms always went back to the database, once per parcel.
        crop_rows = list(parcel.crop_history.all())
        years = len({row.year for row in crop_rows})
        has_history = years >= 3 or bool(list(parcel.landowner_affidavits.all()))
    if not has_history:
        missing.append("land_history")

    if answers.get("currently_certified") not in ("yes", "no", "previously"):
        missing.append("certification_status")

    if not missing:
        state = "complete"
    else:
        any_signal = (
            has_identity
            or bool(parcel.date_began_managing)
            or has_buffers
            or bool(parcel.polygon)
            or bool(answers)
            or bool(crop_rows)
        )
        state = "in_progress" if any_signal else "not_started"

    evidence = parcel_evidence_status(parcel, osp=osp)
    return {
        # `state` / `missing` keep their meaning and their readers: they answer "are the
        # QUESTIONS answered". They are aliased explicitly below so a new reader does not have
        # to know that history.
        "state": state,
        "missing": missing,
        "answers_state": state,
        "answers_missing": missing,
        # ⛔ Every surface that renders `state` must render this beside it. A completion mark
        # on its own is the claim this split exists to stop.
        "evidence_state": evidence["state"],
        "evidence_missing": evidence["missing"],
        "evidence_detail": evidence["detail"],
    }


#: Tolerance on the geometry-vs-stated-area agreement check. Wide on purpose: a hand-drawn
#: boundary traced off a satellite tile is not a survey, and flagging every parcel whose
#: polygon is 10% out would make the signal worthless. This is looking for a placeholder or a
#: boundary drawn on the wrong field, not for surveying error.
GEOMETRY_AREA_TOLERANCE = 0.35


def _ring_area_hectares(ring) -> float | None:
    """Planar area of a lon/lat ring, in hectares, via the shoelace formula.

    Good enough for the question being asked ("is this geometry roughly the parcel it claims to
    be"), and deliberately not a geodesic area: the latitude correction below keeps a mid-latitude
    field within a few percent, which is far inside GEOMETRY_AREA_TOLERANCE.
    """
    import math

    try:
        pts = [(float(pt[0]), float(pt[1])) for pt in ring]
    except (TypeError, ValueError, IndexError):
        return None
    if len(pts) < 3:
        return None
    lat_mean = sum(p[1] for p in pts) / len(pts)
    # Degrees → metres. Longitude degrees shrink with latitude; latitude degrees barely move.
    m_per_deg_lat = 111_132.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat_mean))
    xs = [p[0] * m_per_deg_lon for p in pts]
    ys = [p[1] * m_per_deg_lat for p in pts]
    total = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        total += xs[i] * ys[j] - xs[j] * ys[i]
    area_m2 = abs(total) / 2.0
    return area_m2 / 10_000.0 if area_m2 > 0 else None


def parcel_evidence_status(parcel, osp=None) -> dict:
    """Is the SUPPORTING EVIDENCE for this parcel application on file?

    Separate from `parcel_application_status` because answering a question and holding the
    document that backs it are different facts, and a parcel can be complete on one and empty on
    the other. Keeping them in one verdict is what let "complete" print above "[REVIEW] No
    operator-supplied map is attached".

    ⛔ THIS FUNCTION NEVER ASSERTS ADEQUACY. It reports WHAT the map is and where it came from.
    Whether that satisfies WSDA, CCOF or OTCO is the certifying agent's determination — CCOF
    NOPB49 §E alone lists eleven elements a schematic cannot carry — and Trazo has not run that
    check. `CCOF_MAP_ELEMENTS` stays a statement of what is missing from a schematic, not a
    checklist Trazo claims to have passed.

    Map states, most to least evidential:
      operator_map       an uploaded document exists
      schematic          usable geometry whose derived area agrees with the stated parcel area
      geometry_unverified usable geometry that DISAGREES with the stated area — a placeholder or
                         a boundary drawn on the wrong field looks exactly like a real one
      none               no geometry, no upload
    """
    from certifications.services.osp_module_pdf import parcel_map_documents

    missing: list = []
    detail: dict = {}

    uploads = list(parcel_map_documents(parcel) or [])
    ring = None
    polygon = getattr(parcel, "polygon", None)
    if isinstance(polygon, dict):
        coords = polygon.get("coordinates") or []
        if coords and isinstance(coords[0], list) and len(coords[0]) >= 3:
            ring = coords[0]

    if uploads:
        detail["map"] = "operator_map"
    elif ring is not None:
        derived_ha = _ring_area_hectares(ring)
        stated_ha = float(parcel.area) if parcel.area else None
        if derived_ha and stated_ha and stated_ha > 0:
            drift = abs(derived_ha - stated_ha) / stated_ha
            if drift > GEOMETRY_AREA_TOLERANCE:
                detail["map"] = "geometry_unverified"
                detail["map_area_derived_ha"] = round(derived_ha, 2)
                detail["map_area_stated_ha"] = round(stated_ha, 2)
                missing.append("map_geometry_disagrees_with_area")
            else:
                detail["map"] = "schematic"
        else:
            # Geometry present but nothing to check it against. Not a finding, and not an
            # operator map either.
            detail["map"] = "schematic"
        missing.append("operator_map")
    else:
        detail["map"] = "none"
        missing.append("map")

    # Land history resting on an affidavit needs the signed document, not just the row.
    if not parcel.container_production:
        affidavits = list(parcel.landowner_affidavits.all())
        if affidavits and not any(getattr(a, "signed_document", None) for a in affidavits):
            missing.append("affidavit_document")
            detail["affidavit"] = "row_without_signed_document"

    # T21-F1: on a certified parcel, what the agent's route asks for and is not on file. Asked items
    # only; an item shown for reference does not make the parcel outstanding.
    from certifications.services import certified_parcel_branch as cpb

    # Run 3, R3-05: in a packet, the packet's plan; this read the newest plan in the database, so an
    # active-plan packet counted another plan's route.
    certified = cpb.assess_for_wizard(parcel) if osp is None else cpb.assess_for_plan(parcel, osp)
    if certified is not None:
        detail["certified_route"] = certified.route
        # Run 4, R4-01: an undetermined route means the count below is not the full set of what the
        # agent asks; the summary says so instead of reading as complete.
        detail["certified_route_undetermined"] = certified.land_history_asked is None
        for key in certified.missing:
            missing.append(f"certified_{key}")

    state = "complete" if not missing else "outstanding"
    return {"state": state, "missing": missing, "detail": detail}
