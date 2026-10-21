"""One reading of `Parcel.polygon`, whichever of its two stored shapes it holds.

`Parcel.polygon` is an untyped JSONField with two shapes on file:

* `[{"lat": ..., "lng": ...}, ...]`: what the parcel form writes, i.e. every boundary a grower drew.
* GeoJSON `{"type": "Polygon", "coordinates": [[[lng, lat], ...]]}`: what the demo seeders and
  the audit fixture farms write.

The backend readers (the packet's parcel map and the parcel-application map status) parsed GeoJSON
only, so every boundary a grower actually drew was treated as "no geometry": absent from the
certifier packet's map and reported as `none` by the application status. The frontend already
normalises both shapes (`trazo-app/src/utils/parcelPolygon.ts`, `toLatLngPath`); this is the same
rule on the server, and every server reader goes through it.

Anything unrecognised is None (no boundary on file), never a guess.
"""

import math


def _finite(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def outer_ring_lnglat(polygon) -> list[list[float]] | None:
    """The outer ring as `[[lng, lat], ...]`, open (no repeated closing point), or None.

    None when the value is neither shape, or when fewer than 3 points with finite coordinates
    remain: two points are not an area.
    """
    points: list[list[float]] = []
    if isinstance(polygon, list):
        for point in polygon:
            if not isinstance(point, dict):
                continue
            lat, lng = _finite(point.get("lat")), _finite(point.get("lng"))
            if lat is not None and lng is not None:
                points.append([lng, lat])
    elif isinstance(polygon, dict) and polygon.get("type") == "Polygon":
        coordinates = polygon.get("coordinates")
        ring = coordinates[0] if isinstance(coordinates, list) and coordinates else None
        if isinstance(ring, list):
            for position in ring:
                if isinstance(position, (list, tuple)) and len(position) >= 2:
                    lng, lat = _finite(position[0]), _finite(position[1])
                    if lat is not None and lng is not None:
                        points.append([lng, lat])
    else:
        return None

    # GeoJSON closes the ring by repeating its first position; the drawing form does not.
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points if len(points) >= 3 else None


def latlng_path(polygon) -> list[dict] | None:
    """The outer ring as `[{"lat": ..., "lng": ...}, ...]` (the shape the map components draw)."""
    ring = outer_ring_lnglat(polygon)
    if ring is None:
        return None
    return [{"lat": lat, "lng": lng} for lng, lat in ring]


def map_center(map_metadata) -> dict | None:
    """`map_metadata["center"]` as `{"lat", "lng"}` with finite numbers, or None.

    `map_metadata` is free-form JSON. `float("Infinity")` does not raise, and a non-finite number
    in a response body makes DRF's strict JSON renderer fail, so one bad value would break the
    response for every parcel listed beside it. Same finite rule as the boundary points.
    """
    center = map_metadata.get("center") if isinstance(map_metadata, dict) else None
    if not isinstance(center, dict):
        return None
    lat, lng = _finite(center.get("lat")), _finite(center.get("lng"))
    if lat is None or lng is None:
        return None
    return {"lat": lat, "lng": lng}
