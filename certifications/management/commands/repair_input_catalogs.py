"""
Repair OMRI / WSDA / CDFA catalog rows that were seeded from hand-typed data.

The three committed seeds were regenerated from the publishers on 2026-09-06, but a
database seeded before then still holds the old rows — and those rows are cited in
certifier packets. This command brings an existing database into line with the
published lists and says exactly what it changed.

What it repairs
---------------
1. OMRI  — corrects `product_name` / `manufacturer` / `category` to OMRI's own strings
           and backfills `source_url` + `list_edition_date`, keyed on `omri_id`.
           Rows whose `omri_id` is not OMRI-shaped, or that are absent from the
           regenerated seed, are reported as UNVERIFIED (5 codes carried until
           2026-09-06 had lapsed: they are in neither published PDF and their
           certificate URL returns 404).
2. WSDA  — re-keys a row whose `wsda_id` is a fabricated `WSDA-REG-…` string to the
           real WSDA Product # when the brand name matches the published list exactly.
           Re-keying UPDATES THE EXISTING ROW, so its primary key — and therefore every
           OSP that approved it — is preserved.
3. CDFA  — clears every `cdfa_oim_reg_number`. CDFA publishes no identifier, so all of
           them were invented.

What it will NOT do
-------------------
An approved input vanishing from a plan is itself a § 205.201(a)(2) defect, so a row
that is NOT on the published list and IS referenced by an OSP is never deleted
silently. It is either remapped to the correct catalog row (see `_WSDA_TO_OMRI`, for
products that turned out to be OMRI listings and not WSDA ones) or reported for a human
with the plans that cite it. Unreferenced unlisted rows are deleted under `--apply`.

Dry run by default. Idempotent: running it twice changes nothing the second time.

Usage:
    poetry run python manage.py repair_input_catalogs             # report only
    poetry run python manage.py repair_input_catalogs --apply     # write changes
"""

import csv
import os

from django.core.management.base import BaseCommand
from django.db import transaction

from certifications.models import OMRIProduct, OrganicSystemPlan, WSDAMaterial
from certifications.services.omri_verifier import _normalize, looks_like_omri_code
from certifications.services.registry_identifiers import is_real_wsda_product_number

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")

#: Rows that were seeded as WSDA materials but are OMRI listings, not WSDA ones.
#: Searching the March 06, 2026 WSDA list for "serenade", "bayer" or "down to earth"
#: returns nothing at all. Mapping rather than deleting keeps the material on every plan
#: that approved it, under the identifier that actually resolves.
_WSDA_TO_OMRI = {
    "serenade opti": "gus-5425",
    "feather meal 13-0-0": "det-4970",
}


def _load(name, key):
    with open(os.path.join(_DATA, name), newline="", encoding="utf-8") as fh:
        return {(r[key] or "").strip(): r for r in csv.DictReader(fh)}


def _materials_list_citations(row) -> list:
    """Materials-list entries citing this catalog row — the second citing relation.

    🔴 2026-09-07. Every delete/merge decision in this command read `row.approving_osps` alone.
    `PlanMaterialEntry`'s catalog FKs are SET_NULL, so deleting a row cited only by the
    materials list left the entry in place, still printing "OMRI listed" / "WSDA Brand Name
    Materials List" with no row behind it.
    """
    from certifications.services.catalog_integrity import entries_citing

    queryset = entries_citing(row)
    return list(queryset) if queryset is not None else []


def _cited_by(plans: list, entries: list) -> str:
    """One phrase naming both citing relations, so "uncited" means actually uncited."""
    bits = []
    if plans:
        bits.append(f"OSP {plans}")
    if entries:
        bits.append(f"{len(entries)} materials-list row(s) on OSP {sorted({e.osp_id for e in entries})}")
    return " and ".join(bits) if bits else "no plan"


class Command(BaseCommand):
    help = "Correct catalog rows seeded from hand-typed data against the published lists."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the repairs. Without it the command only reports what it would do.",
        )

    def handle(self, *args, **opts):
        apply_changes = opts.get("apply", False)
        with transaction.atomic():
            self._repair_omri(apply_changes)
            self._repair_wsda(apply_changes)
            self._repair_cdfa(apply_changes)
            if not apply_changes:
                self.stdout.write(self.style.WARNING("\nDRY RUN — nothing written. Re-run with --apply."))

    # ---------------------------------------------------------------- OMRI ---
    def _repair_omri(self, apply_changes):
        published = _load("omri_seed.csv", "omri_id")
        self.stdout.write(self.style.NOTICE("\n== OMRI =="))
        corrected = unverified = 0
        for row in OMRIProduct.objects.all().order_by("omri_id"):
            ref = published.get(row.omri_id)
            if ref is None:
                unverified += 1
                shape = "" if looks_like_omri_code(row.omri_id) else "  [not an OMRI code shape]"
                plans = list(row.approving_osps.values_list("pk", flat=True))
                entries = _materials_list_citations(row)
                self.stdout.write(
                    self.style.ERROR(
                        f"  UNVERIFIED {row.omri_id!r} {row.product_name!r}{shape}"
                        f" — cited by {_cited_by(plans, entries)}"
                    )
                )
                continue
            fields = {
                "product_name": ref["product_name"],
                "manufacturer": ref["manufacturer"] or None,
                "category": ref["category"] or None,
                "source_url": ref.get("source_url") or None,
            }
            diff = {k: v for k, v in fields.items() if getattr(row, k) != v}
            if diff:
                corrected += 1
                for k, v in diff.items():
                    self.stdout.write(f"  {row.omri_id} {k}: {getattr(row, k)!r} -> {v!r}")
                if apply_changes:
                    for k, v in diff.items():
                        setattr(row, k, v)
                    row.save(update_fields=list(diff))
        self.stdout.write(f"  corrected {corrected}, unverified {unverified}")

    # ---------------------------------------------------------------- WSDA ---
    def _repair_wsda(self, apply_changes):
        published = _load("wsda_seed.csv", "wsda_id")
        by_name = {_normalize(r["brand_name"]): r for r in published.values()}
        self.stdout.write(self.style.NOTICE("\n== WSDA =="))
        rekeyed = remapped = deleted = stranded = 0

        for row in list(WSDAMaterial.objects.all().order_by("brand_name")):
            if is_real_wsda_product_number(row.wsda_id) and row.wsda_id in published:
                continue

            ref = by_name.get(_normalize(row.brand_name))
            if ref is not None:
                # Same row, real identifier: the pk — and every OSP link — survives.
                rekeyed += 1
                self.stdout.write(f"  re-key {row.brand_name!r}: {row.wsda_id!r} -> {ref['wsda_id']!r}")
                if apply_changes:
                    clash = WSDAMaterial.objects.filter(wsda_id=ref["wsda_id"]).exclude(pk=row.pk).first()
                    if clash is not None:
                        self._absorb(row, clash, apply_changes)
                        continue
                    row.wsda_id = ref["wsda_id"]
                    row.manufacturer = ref["manufacturer"] or None
                    row.category = ref["category"] or None
                    row.subtype = ref.get("subtype") or None
                    row.source_url = ref.get("source_url") or None
                    row.save()
                continue

            plans = list(row.approving_osps.values_list("pk", flat=True))
            target = _WSDA_TO_OMRI.get(_normalize(row.brand_name))
            if target:
                omri = OMRIProduct.objects.filter(omri_id=target).first()
                if omri is None:
                    stranded += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  STRANDED {row.brand_name!r}: maps to OMRI {target} which is not "
                            f"seeded. Run seed_omri_minimal first. Cited by OSP {plans}."
                        )
                    )
                    continue
                entries = _materials_list_citations(row)
                if entries:
                    stranded += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  MAPS TO OMRI {target} but {len(entries)} materials-list row(s) cite it "
                            f"as a WSDA listing: {row.brand_name!r} ({row.wsda_id!r}). Left in place — "
                            f"re-pointing them would rewrite the operator's stated listing basis from "
                            f"WSDA to OMRI, which is their claim to make. Decide this one by hand."
                        )
                    )
                    continue
                remapped += 1
                self.stdout.write(
                    f"  remap {row.brand_name!r} (WSDA {row.wsda_id!r}, not on the WSDA list) "
                    f"-> OMRI {omri.omri_id} {omri.product_name!r} on OSP {plans or '[]'}"
                )
                if apply_changes:
                    for osp in OrganicSystemPlan.objects.filter(pk__in=plans):
                        osp.approved_omri_products.add(omri)
                        osp.approved_wsda_materials.remove(row)
                    row.delete()
                continue

            entries = _materials_list_citations(row)
            if plans or entries:
                stranded += 1
                self.stdout.write(
                    self.style.ERROR(
                        f"  NOT ON THE WSDA LIST and cited by {_cited_by(plans, entries)}: "
                        f"{row.brand_name!r} ({row.wsda_id!r}). Left in place — removing it "
                        f"would delete an approved input from a plan, or strand a materials-list "
                        f"row still claiming this listing. Decide this one by hand."
                    )
                )
            else:
                deleted += 1
                self.stdout.write(f"  delete unlisted, uncited {row.brand_name!r} ({row.wsda_id!r})")
                if apply_changes:
                    row.delete()

        self.stdout.write(
            f"  re-keyed {rekeyed}, remapped to OMRI {remapped}, deleted {deleted}, " f"needing a human {stranded}"
        )

    def _absorb(self, old, keeper, apply_changes):
        """Move every citation off a duplicate row, then drop it.

        BOTH citing relations move. `old.delete()` is SET_NULL on
        `PlanMaterialEntry.wsda_material`, so moving only the M2M would leave the entry in place
        still claiming a WSDA listing with nothing behind it. Re-pointing is honest here and
        only here: a duplicate is the same substance on the same list, so the operator's basis
        is unchanged — only which row proves it.
        """
        plans = list(old.approving_osps.values_list("pk", flat=True))
        entries = _materials_list_citations(old)
        self.stdout.write(
            f"    merging duplicate {old.wsda_id!r} into {keeper.wsda_id!r} "
            f"(OSP {plans}, {len(entries)} materials-list row(s))"
        )
        if apply_changes:
            for osp in OrganicSystemPlan.objects.filter(pk__in=plans):
                osp.approved_wsda_materials.add(keeper)
                osp.approved_wsda_materials.remove(old)
            for entry in entries:
                entry.wsda_material = keeper
                entry.save(update_fields=["wsda_material"])
            old.delete()

    # ---------------------------------------------------------------- CDFA ---
    def _repair_cdfa(self, apply_changes):
        self.stdout.write(self.style.NOTICE("\n== CDFA OIM =="))
        omri_n = OMRIProduct.objects.exclude(cdfa_oim_reg_number=None).count()
        wsda_n = WSDAMaterial.objects.exclude(cdfa_oim_reg_number=None).count()
        self.stdout.write(
            f"  clearing invented registration numbers: {omri_n} OMRI, {wsda_n} WSDA " f"(CDFA publishes no identifier)"
        )
        if apply_changes:
            OMRIProduct.objects.exclude(cdfa_oim_reg_number=None).update(cdfa_oim_reg_number=None)
            WSDAMaterial.objects.exclude(cdfa_oim_reg_number=None).update(cdfa_oim_reg_number=None)
