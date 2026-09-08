"""A catalog row an Organic System Plan cites is a regulatory record, not cache.

🔴 2026-09-07 — `seed_omri_minimal --reset` and `seed_wsda_materials --reset` did
``Model.objects.all().delete()``. The approved-inputs M2Ms cascade, so replacing a catalog
silently emptied every OSP's materials list: on the pilot farm, four OMRI products and two
WSDA materials vanished from plans that had cited them since January, and the only surviving
evidence was the append-only ``ApprovedInputChangeLog`` rows saying they had once been added.

The plan is the operator's § 205.201(a)(2) filing. A material leaving it is a change the
operator is required to notify their certifier about under § 205.400(f)(2) — so a seeder
removing one by side effect is not a data-refresh detail, it is the tool editing a regulatory
document without telling anyone. `repair_input_catalogs` already refuses to delete a cited
row; the seeders bypassed that guard entirely because they never consulted it.

⛔ Deleting a cited row is still POSSIBLE — `--force` exists because a genuinely fabricated
row sometimes has to go. What may not happen is deleting one SILENTLY.
"""

from __future__ import annotations

from django.db.models import Q

#: The reverse accessor from a catalog row back to the plans citing it. All three
#: approved-input M2Ms on `OrganicSystemPlan` declare `related_name="approving_osps"`,
#: so one name covers every catalog — verified against `models.py:1041-1060`, not assumed.
CITING_RELATION = "approving_osps"

#: 🔴 2026-09-07 — THE SECOND CITING RELATION. A plan cites a catalog row two ways, and this
#: module knew one of them. `PlanMaterialEntry.{omri_product,wsda_material,
#: national_list_substance}` are the materials-LIST citations — the rows that print into
#: `modules/materials_application.pdf`, the § 205.201(a)(2) narrative and the workbook — and
#: every one declares `related_name="+"`, so there is no reverse accessor for
#: `CITING_RELATION`-style filtering to find. The guard was blind to them, `SET_NULL` cleared
#: them on reset, and the entry went on printing "OMRI listed" with no OMRI row behind it.
#: Knowing three catalogs but one of two citing relations is the same off-by-one on the other
#: axis. A fourth registry means adding it to BOTH maps.
ENTRY_CITING_FIELD = {
    "OMRIProduct": "omri_product",
    "WSDAMaterial": "wsda_material",
    "NationalListSubstance": "national_list_substance",
}

#: Catalogs an OSP can cite. A fourth registry means adding it here; a guard that knows
#: about two of three is the same off-by-one this module exists to stop.
CITABLE_MODELS = ("OMRIProduct", "WSDAMaterial", "NationalListSubstance")


def _entry_citations(model):
    """`PlanMaterialEntry` rows whose catalog FK points at `model` — the second citing relation.

    Returns a queryset, so callers can use it as a subquery rather than pulling every primary
    key through Python.
    """
    field = ENTRY_CITING_FIELD.get(model.__name__)
    if not field:
        return None
    from certifications.models import PlanMaterialEntry

    return PlanMaterialEntry.objects.filter(**{f"{field}__isnull": False})


def entries_citing(row):
    """The materials-list entries whose catalog FK points at this specific catalog row.

    The per-ROW counterpart of `cited_rows`. Anything deciding whether one row may be deleted,
    merged or remapped has to consult this as well as `row.approving_osps` — those are the two
    citing relations, and `approving_osps` alone is what let `--reset` strand an entry.
    """
    entries = _entry_citations(type(row))
    if entries is None:
        return None
    return entries.filter(**{ENTRY_CITING_FIELD[type(row).__name__]: row.pk})


def cited_rows(model):
    """Every row of `model` cited by a plan — via the approved-inputs M2M OR a materials-list entry.

    Returns a queryset — empty, not an error, when the model is not one an OSP can cite.
    """
    if model.__name__ not in CITABLE_MODELS:
        return model.objects.none()
    entries = _entry_citations(model)
    cited = Q(**{f"{CITING_RELATION}__isnull": False})
    if entries is not None:
        cited |= Q(pk__in=entries.values(f"{ENTRY_CITING_FIELD[model.__name__]}_id"))
    return model.objects.filter(cited).distinct()


def describe_citations(model) -> list[str]:
    """One human line per cited row: what it is, and which plans hold it, and how.

    A refusal that does not say WHICH rows and WHOSE plans is one the operator cannot act
    on, so they reach for --force and learn nothing. Both citation kinds are named because
    they fail differently: losing an M2M row empties the approved-inputs list, while losing a
    materials-list FK leaves the entry in place still asserting a listing behind it.
    """
    lines = []
    field = ENTRY_CITING_FIELD.get(model.__name__)
    rows = list(cited_rows(model).prefetch_related(f"{CITING_RELATION}__establishment"))
    entries_by_row: dict = {}
    entries = _entry_citations(model)
    if entries is not None:
        for entry in entries.filter(**{f"{field}__in": [r.pk for r in rows]}).select_related("osp__establishment"):
            entries_by_row.setdefault(getattr(entry, f"{field}_id"), []).append(entry)
    for row in rows:
        where = [
            f"OSP #{p.id} v{p.version_number} ({p.establishment.name}, {p.status}) approved-inputs list"
            for p in getattr(row, CITING_RELATION).all()
        ]
        for entry in entries_by_row.get(row.pk, []):
            osp = entry.osp
            where.append(
                f"OSP #{osp.id} v{osp.version_number} ({osp.establishment.name}, {osp.status}) "
                f"materials list — {entry.product_name!r} claims {entry.get_listing_basis_display()}"
            )
        lines.append(f"{row} — cited by {len(where)} plan reference(s): {', '.join(where)}")
    return lines


def assert_safe_to_reset(model, *, force: bool) -> list[str]:
    """Raise unless every row of `model` is safe to delete.

    Returns the (possibly empty) list of citation lines so the caller can report them when
    `force` is set — forcing should be loud, not quiet.
    """
    lines = describe_citations(model)
    if lines and not force:
        raise CitedCatalogRowsError(model, lines)
    return lines


class CitedCatalogRowsError(RuntimeError):
    def __init__(self, model, lines: list[str]):
        self.model = model
        self.lines = lines
        listed = "\n  ".join(lines[:20])
        more = f"\n  …and {len(lines) - 20} more" if len(lines) > 20 else ""
        super().__init__(
            f"Refusing to reset {model.__name__}: {len(lines)} row(s) are cited by an Organic "
            f"System Plan — on its approved-inputs list, on its materials list, or both. "
            f"Deleting them would edit those plans without a § 205.400(f)(2) change "
            f"notification: an approved-inputs citation would vanish, and a materials-list "
            f"citation would leave the entry in place still claiming a listing nothing can "
            f"produce.\n  "
            f"{listed}{more}\n"
            f"Re-run without --reset to update rows in place, or pass --force if you have "
            f"decided these plans should lose these citations."
        )
