"""The operation's own handling and storage facilities, in one wording for every surface that prints them.

OTCO C7 7.1 ("ON FARM FACILITY INFORMATION ... Facility Name; Site Address, City, State/Province, Zip/Postal
Code, Country"), 7.2-1 (a facility layout), 7.7-2 (each storage facility with its documentation class, OWN for
the operation's own) and CCOF G6.4 A1 ("Site Name & Location (full address)") ask for these. They are
`PostHarvestFacility` rows with `operated_by="this_operation"`: covered by the operation's own certificate, so
no certificate of their own is looked up, dated or asked for.
"""

from __future__ import annotations

OWN_CLASS = "OWN"
OWN_COVERAGE = "operated by this operation, under its own certificate (OWN)"


def own_facilities(establishment):
    return establishment.post_harvest_facilities.filter(operated_by="this_operation").order_by("name", "pk")


def third_party_facilities(establishment):
    return establishment.post_harvest_facilities.exclude(operated_by="this_operation")


def full_address(facility) -> str:
    """Street, city, state with postal code, country: the parts OTCO 7.1 lists, as many as are recorded."""
    region = " ".join(x for x in (facility.state or "", facility.postal_code or "") if x)
    return ", ".join(
        x.strip()
        for x in (facility.address or "", facility.city or "", region, facility.country or "")
        if x and x.strip()
    )


def own_facility_line(facility) -> str:
    """One own facility, as the plan and the module PDF print it."""
    detail = ", ".join(
        x
        for x in (
            facility.get_facility_type_display(),
            facility.get_role_display() if facility.role else "",
            full_address(facility) or "address not recorded",
        )
        if x
    )
    layout = "layout attached" if facility.layout_document else "no layout attached"
    return f"{(facility.name or '').strip()} — {detail}; {OWN_COVERAGE}; {layout}."
