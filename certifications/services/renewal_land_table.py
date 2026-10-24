"""The parcels, crops and acres an agent's renewal asks for, per parcel already on its certificate.

WHY THIS EXISTS
---------------
CCOF's Crop Update (NOPB88) and WSDA's Site Update Information (AGR 2516) are the renewal forms for
land already certified. Neither asks for a comparison. NOPB88 is a table: "CCOF Parcel # / Crop(s)
(Current or planned within the next 12 months) / Acres", one row per certified parcel. AGR 2516
asks what changes for each site whose crop production information no longer matches the plan for
the coming year, and accepts production or planting records instead of the form if they show the
site number and site name as on the certificate.

Both read off the operation's current land, which Trazo holds: the parcel, its acreage, its crop
history rows for this year and next, and the number the certificate prints for it
(`prior_certificate_site_number`, stated beside the certifier on the parcel's own application).
Trazo does not hold the agent's profile, so it never says which site CHANGED: that comparison is
the operation's, against the profile the agent issued.

Which parcels: those the parcel's application routes to these forms, `ccof_crop_update` and
`wsda_existing_site` (`certified_parcel_branch.route_for`). A parcel new to the agent is filed on
its parcel or site application instead, and is named with that reason rather than left out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

#: The agents whose renewal asks for a per-parcel land table, with the route that puts a parcel on it.
LAND_TABLE_ROUTES = {
    "ccof": "ccof_crop_update",
    "wsda": "wsda_existing_site",
}

#: Why a parcel on another route is not in the table: the form it is filed on instead.
_OTHER_ROUTE_REASON = {
    "ccof_g": "new to the operation's CCOF file, so it is filed on the Parcel Application (NOPB49)",
    "wsda_new_site": "certified by another agent, so for WSDA it is a new site, filed on the Site Application (AGR 2264)",
    "wsda_transfer": "from another operation, so it is filed on the Site Application (AGR 2264) as a transfer",
    "unresolved": "its application does not name a certifier Trazo recognises",
}


@dataclass(frozen=True)
class LandRow:
    name: str
    #: The number the agent's certificate prints for the parcel, as the operator stated it. "" when not stated.
    number: str
    acres: float
    #: (year, "Apples (organic); cover: clover; block rows 1-40") for each crop history row in the window.
    crops: tuple = ()
    #: Years in the window with no crop history row.
    years_without_crop: tuple = ()
    #: Years in the window with a row marked conventional: acreage that may be leaving organic production.
    conventional_years: tuple = ()


@dataclass(frozen=True)
class LandTable:
    agent: str
    agent_name: str
    as_of: date
    years: tuple
    rows: tuple = ()
    #: (parcel name, why it is not in the table)
    excluded: tuple = ()


def _crop_text(row) -> str:
    text = row.crop_grown.strip()
    if row.production_method:
        text += f" ({row.get_production_method_display().lower()})"
    if (row.cover_crop or "").strip():
        text += f"; cover: {row.cover_crop.strip()}"
    if (row.block_id or "").strip():
        text += f"; block {row.block_id.strip()}"
    return text


def land_table(osp, as_of: date | None = None) -> LandTable | None:
    """The land table for this packet's agent, or None when the agent's renewal does not ask for one."""
    from django.utils import timezone

    from certifications.services.certified_parcel_branch import is_certified, route_for
    from certifications.services.packet_coverage import packet_agent, packet_certifier

    agent, own = packet_certifier(osp)
    if not own or agent not in LAND_TABLE_ROUTES:
        return None
    as_of = as_of or timezone.localdate()
    # "Current or planned within the next 12 months": this calendar year and the next.
    years = (as_of.year, as_of.year + 1)
    rows, excluded = [], []
    for parcel in osp.establishment.parcels.order_by("name", "id"):
        if not is_certified(parcel):
            excluded.append((parcel.name, "its application does not state it is currently certified"))
            continue
        route = route_for(parcel, agent)
        if route != LAND_TABLE_ROUTES[agent]:
            excluded.append((parcel.name, _OTHER_ROUTE_REASON.get(route, "its agent's own form decides")))
            continue
        history = list(parcel.crop_history.filter(year__in=years).order_by("year", "block_id", "id"))
        held = {row.year for row in history}
        rows.append(
            LandRow(
                name=parcel.name,
                number=((parcel.application_answers or {}).get("prior_certificate_site_number") or "").strip(),
                acres=parcel.area_acres,
                crops=tuple((row.year, _crop_text(row)) for row in history),
                years_without_crop=tuple(year for year in years if year not in held),
                conventional_years=tuple(
                    sorted({row.year for row in history if row.production_method == "conventional"})
                ),
            )
        )
    return LandTable(
        agent=agent,
        agent_name=packet_agent(osp).name or agent.upper(),
        as_of=as_of,
        years=years,
        rows=tuple(rows),
        excluded=tuple(excluded),
    )
