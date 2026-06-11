"""
Consumer-page privacy helpers (Phase 3).

Single source of truth for parcel-location disclosure gating, used by both
the transparency endpoint (_build_public_parcel) and PublicParcelSerializer —
one policy, two payload shapes.
"""


def public_parcel_geo(parcel) -> dict:
    """
    Geo fields a public payload may carry for this parcel, per the farmer's
    Parcel.location_disclosure_level:
      exact       — full polygon + map metadata
      approximate — no boundary; center rounded to 2 decimals (~1 km), zoom
                    capped so the map can't be zoomed onto the field
      hidden      — nothing

    Returns {"polygon": ..., "map_metadata": ..., "level": str}.
    """
    level = getattr(parcel, "location_disclosure_level", "exact") or "exact"

    if level == "exact":
        return {"polygon": parcel.polygon, "map_metadata": parcel.map_metadata, "level": level}

    if level == "approximate":
        meta = parcel.map_metadata if isinstance(parcel.map_metadata, dict) else {}
        center = meta.get("center") if isinstance(meta.get("center"), dict) else None
        approx_meta = None
        # map_metadata is free-form JSON; malformed values must degrade to
        # "no map" on the public endpoint, never to a 500.
        try:
            if center and center.get("lat") is not None and center.get("lng") is not None:
                approx_meta = {
                    "center": {
                        "lat": round(float(center["lat"]), 2),
                        "lng": round(float(center["lng"]), 2),
                    },
                    "zoom": min(int(float(meta.get("zoom") or 13)), 13),
                    "approximate": True,
                }
        except (TypeError, ValueError):
            approx_meta = None
        return {"polygon": None, "map_metadata": approx_meta, "level": level}

    return {"polygon": None, "map_metadata": None, "level": level}
