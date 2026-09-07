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

#: The reverse accessor from a catalog row back to the plans citing it. All three
#: approved-input M2Ms on `OrganicSystemPlan` declare `related_name="approving_osps"`,
#: so one name covers every catalog — verified against `models.py:1041-1060`, not assumed.
CITING_RELATION = "approving_osps"

#: Catalogs an OSP can cite. A fourth registry means adding it here; a guard that knows
#: about two of three is the same off-by-one this module exists to stop.
CITABLE_MODELS = ("OMRIProduct", "WSDAMaterial", "NationalListSubstance")


def cited_rows(model):
    """Every row of `model` that at least one OSP holds on its approved-inputs list.

    Returns a queryset — empty, not an error, when the model is not one an OSP can cite.
    """
    if model.__name__ not in CITABLE_MODELS:
        return model.objects.none()
    return model.objects.filter(**{f"{CITING_RELATION}__isnull": False}).distinct()


def describe_citations(model) -> list[str]:
    """One human line per cited row: what it is, and which plans hold it.

    A refusal that does not say WHICH rows and WHOSE plans is one the operator cannot act
    on, so they reach for --force and learn nothing.
    """
    lines = []
    rows = cited_rows(model).prefetch_related(f"{CITING_RELATION}__establishment")
    for row in rows:
        plans = list(getattr(row, CITING_RELATION).all())
        where = ", ".join(f"OSP #{p.id} v{p.version_number} ({p.establishment.name}, {p.status})" for p in plans)
        lines.append(f"{row} — cited by {len(plans)} plan(s): {where}")
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
            f"Refusing to reset {model.__name__}: {len(lines)} row(s) are on an Organic System "
            f"Plan's approved-inputs list, and deleting them would remove those materials from "
            f"the plan without a § 205.400(f)(2) change notification.\n  "
            f"{listed}{more}\n"
            f"Re-run without --reset to update rows in place, or pass --force if you have "
            f"decided these plans should lose these materials."
        )
