"""One field-map drawing, shared by every document that has to show a parcel.

WHY THIS EXISTS
---------------
🔴 Certifier register `map-absent-from-packet` (CCOF NOPB49 §E, WSDA AGR 2264 Map). Both
certifiers require a map as a MANDATORY ATTACHMENT — CCOF's own text says it "must be reviewed by
CCOF prior to inspection of a new parcel", WSDA's that "a map … must be submitted with each site
application" — and no map image reached the OSP packet at all. The Parcel Application PDF printed
one sentence, "Field map on file (boundary recorded in Trazo)", which is worse than printing
nothing: it tells a reviewer the map exists somewhere they are not looking.

The drawing already existed. It was a private method on the per-production audit-export builder
(`_build_field_map_section`), welded to that class's styles and to `self.production.parcel`, so
the one document that most needs it could not call it. This module is that drawing, taking a
parcel and returning flowables — the audit export and the Parcel Application now render the same
schematic from the same code, which is also the only way they cannot drift.

WHAT THIS IS AND IS NOT
-----------------------
A not-to-scale schematic drawn from the recorded boundary geometry, with compass labels carrying
adjoining land use. It is NOT a survey, NOT satellite imagery, and NOT a substitute for the
operator's own map where the certifier asks for imagery. Every caller prints that caveat, and an
operator-uploaded map ships alongside it — see the `map_upload` question on the Parcel
Application.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import inch

TRAZO_GREEN = colors.HexColor("#2E7D32")

#: What CCOF NOPB49 §E lists as required map elements. Stated to the operator rather than
#: silently omitted, because a schematic cannot carry most of them and a reviewer checking the
#: list needs to know which half they are looking at.
CCOF_MAP_ELEMENTS = (
    "a directional arrow",
    "parcel boundaries",
    "total acreage notation",
    "permanent identifiers (blocks, lots, greenhouses)",
    "nearest public roads or landmarks",
    "other operation areas (seedling production, storage, post-harvest handling)",
    "adjacent land uses, labeled",
    "location and width of buffer zones, with any crop grown in the buffer noted",
    "natural resources (waterways, woodlands, windbreaks)",
    "livestock needs",
    "existing treated-lumber installations",
)


def parcel_boundary_ring(parcel) -> list | None:
    """The outer ring of the parcel's GeoJSON polygon, or None when it cannot be drawn."""
    polygon = getattr(parcel, "polygon", None)
    if not isinstance(polygon, dict):
        return None
    coords = polygon.get("coordinates") or []
    if not (coords and isinstance(coords[0], list)):
        return None
    ring = coords[0]
    if not (isinstance(ring, list) and len(ring) >= 3):
        return None
    if not all(isinstance(pt, (list, tuple)) and len(pt) >= 2 for pt in ring):
        return None
    return ring


def adjoining_land_by_direction(parcel) -> dict:
    """Compass direction -> adjoining land use, from `Parcel.buffer_zones`."""
    buffers = getattr(parcel, "buffer_zones", None)
    out: dict = {}
    if isinstance(buffers, list):
        for entry in buffers:
            if isinstance(entry, dict) and entry.get("direction"):
                out[str(entry["direction"]).strip().lower()] = entry.get("adjoining_land_use") or ""
    return out


def parcel_map_drawing(parcel, width: float = 4.9 * inch, height: float = 3.1 * inch):
    """A ReportLab `Drawing` of the parcel boundary, or None when geometry is unusable.

    Returns None rather than raising or drawing an empty box: a caller that has no map must say
    so in its own words, and a blank frame reads as a map that failed to load.
    """
    from reportlab.graphics.shapes import Drawing, Line, Polygon, String

    ring = parcel_boundary_ring(parcel)
    if ring is None:
        return None
    try:
        lngs = [float(pt[0]) for pt in ring]
        lats = [float(pt[1]) for pt in ring]
    except (TypeError, ValueError):
        return None

    min_lng, max_lng = min(lngs), max(lngs)
    min_lat, max_lat = min(lats), max(lats)
    geo_w = max_lng - min_lng
    geo_h = max_lat - min_lat
    if geo_w <= 0 or geo_h <= 0:
        return None

    margin_x = 70.0
    margin_y = 26.0
    box_x1, box_x2 = margin_x, width - margin_x
    box_y1, box_y2 = margin_y, height - margin_y
    box_w = box_x2 - box_x1
    box_h = box_y2 - box_y1
    if box_w <= 0 or box_h <= 0:
        return None

    # Preserve aspect ratio so the schematic is not distorted; center it in the box.
    scale = min(box_w / geo_w, box_h / geo_h)
    off_x = box_x1 + (box_w - geo_w * scale) / 2.0
    off_y = box_y1 + (box_h - geo_h * scale) / 2.0

    # Higher latitude = north = higher y, so no vertical flip is needed.
    pts: list = []
    for lng, lat in zip(lngs, lats):
        pts.extend([off_x + (lng - min_lng) * scale, off_y + (lat - min_lat) * scale])

    drawing = Drawing(width, height)
    drawing.hAlign = "CENTER"
    drawing.add(
        Polygon(
            points=pts,
            fillColor=colors.HexColor("#E8F5E9"),
            strokeColor=TRAZO_GREEN,
            strokeWidth=1.4,
        )
    )

    adjoining = adjoining_land_by_direction(parcel)
    cx = (box_x1 + box_x2) / 2.0
    cy = (box_y1 + box_y2) / 2.0

    def _label(direction: str, x: float, y: float, anchor: str) -> None:
        land = (adjoining.get(direction.lower()) or "").strip()
        if len(land) > 32:
            land = land[:31] + "…"
        text = f"{direction.upper()} · {land}" if land else direction.upper()
        drawing.add(String(x, y, text, fontSize=6.5, fillColor=colors.HexColor("#555555"), textAnchor=anchor))

    _label("North", cx, height - 12, "middle")
    _label("South", cx, 6, "middle")
    _label("East", width - 4, cy, "end")
    _label("West", 4, cy, "start")

    # North arrow — CCOF §E's first required element.
    ax = width - 16
    ay = height - 44
    drawing.add(Line(ax, ay, ax, ay + 16, strokeColor=colors.HexColor("#333333"), strokeWidth=1))
    drawing.add(String(ax, ay + 18, "N", fontSize=7, fillColor=colors.HexColor("#333333"), textAnchor="middle"))
    return drawing


def parcel_map_caption(parcel) -> str:
    """The one-line fact row printed under the drawing: name, area, center point."""
    ring = parcel_boundary_ring(parcel)
    name = (getattr(parcel, "name", "") or "—").strip()
    # `Parcel.area` is HECTARES; `area_display()` is the only correct way to print it. Printing
    # the raw number beside the word "acres" is a real incident on this page (2026-08-20).
    area = parcel.area_display() if hasattr(parcel, "area_display") and getattr(parcel, "area", None) else "—"
    if not ring:
        return f"{name} · {area}"
    try:
        lngs = [float(pt[0]) for pt in ring]
        lats = [float(pt[1]) for pt in ring]
    except (TypeError, ValueError):
        return f"{name} · {area}"
    # Bounding-box center — robust to the repeated GeoJSON closing vertex and to uneven vertex
    # spacing, both of which bias a plain vertex average.
    cen_lng = (min(lngs) + max(lngs)) / 2.0
    cen_lat = (min(lats) + max(lats)) / 2.0
    return f"{name} · {area} · center {cen_lat:.6f}, {cen_lng:.6f}"
