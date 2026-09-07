"""One invariant, written down once: an open § 205.406(a) filing points at the draft the
renewal is producing — whichever of the two the operator did first.

WHY THIS MODULE EXISTS
----------------------
`OSPAnnualUpdate.new_osp` ("the version this update produced") was never written by the
product. The annual update card posts `prior_osp` only, and `new-version` cloned everything
about a plan except the filing it was being made under. `_renewal_context` looks for the
filing whose `new_osp` IS the plan being exported, then the one whose `prior_osp` is — so on a
forked version it found neither, and `02-annual-update.pdf` in the packet the operator sends
printed "no annual update is on file" over a filing made weeks earlier.

There are two orders in which a renewal happens, and both have to end in the same record:

    file the update, then fork      -> carry_open_filing(source, clone)
    fork, then file the update      -> link_filing_to_open_draft(filing)

Fixing only the first would have opened the second: moving `prior_osp` off the working draft
and onto the plan on file (which § 205.406(a)(1) requires — the changes are "to the previous
plan") means a filing made AFTER the fork no longer names the draft at all.

⛔ Neither function ever REPOINTS a link. A filing whose `new_osp` is set is the hinge between
two versions and rewriting it would move history — which version that year's update produced
is a fact about the past, not a cache.
"""

import logging

logger = logging.getLogger(__name__)


def carry_open_filing(source, clone) -> bool:
    """Fork side: the open filing against `source` produced `clone`.

    Only a filing that has not already produced a version is carried. An acknowledged filing
    IS still linked — `new_osp` is the backlink to the version this fork created, not content
    the certifier received and confirmed.
    """
    from certifications.models import OSPAnnualUpdate

    filing = (
        OSPAnnualUpdate.objects.filter(prior_osp=source, new_osp__isnull=True)
        .order_by("-reporting_year", "-submitted_at", "-id")
        .first()
    )
    if filing is None:
        return False
    filing.new_osp = clone
    filing.save(update_fields=["new_osp", "updated_at"])
    return True


def link_filing_to_open_draft(filing) -> bool:
    """Filing side: an update filed while a newer draft is open produced that draft.

    "Newer" is by version number, not by lineage walk: a draft below `prior_osp` is an older
    abandoned fork, and one at the same number cannot exist. If the operator abandons the
    draft, deleting it nulls this link (`new_osp` is SET_NULL) — which is the honest outcome,
    not a stale claim.
    """
    from certifications.models import OrganicSystemPlan

    if filing is None or filing.new_osp_id is not None or filing.prior_osp_id is None:
        return False
    draft = (
        OrganicSystemPlan.objects.filter(
            establishment_id=filing.prior_osp.establishment_id,
            status="draft",
            version_number__gt=filing.prior_osp.version_number,
        )
        .order_by("-version_number")
        .first()
    )
    if draft is None:
        return False
    filing.new_osp = draft
    filing.save(update_fields=["new_osp", "updated_at"])
    return True
