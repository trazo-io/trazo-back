"""Is the compliance reference data present, and is it fresh?

Two datasets underpin claims Trazo makes to certifiers and shoppers, and both fail SILENTLY
when absent or stale:

* **National List** (7 CFR 205.601/.602) — `history/signals.py` classifies every `ChemicalEvent`
  against it. When the table is empty the classifier returns early, so events are saved with no
  CFR classification and the certifier-facing findings come back empty. Nothing logs, nothing
  warns; the feature simply does not happen.

* **USDA Organic Integrity snapshot** — the organic badge is gated on a match against a LOCAL
  mirror (the USDA REST API was retired in 2025). A stale mirror produces two opposite errors,
  both bad: a farm certified after the snapshot reads as "Pending Verification" and is publicly
  labelled *not independently verified*, while a farm that SURRENDERED certification keeps its
  green badge, restamped as freshly verified on every re-run.

Before 2026-08-07 nothing could report either condition. `data_snapshot_date` was written once and
reached no UI, `health_check()` only asked `count() == 0` (so a five-year-old mirror reported
healthy), and `IngestionRun` — the model that exists precisely to answer "last synced when?" — had
no source for it.

This module is the single place that answers both questions, consumed by `/health/` and by the
management commands.
"""

from __future__ import annotations

import time
from datetime import date

from django.utils import timezone

# USDA publishes the Integrity export monthly. Missing one cycle is survivable; missing two means
# the mirror predates a whole certification month and badge decisions are being made on it.
USDA_SNAPSHOT_STALE_DAYS = 60
USDA_SNAPSHOT_CRITICAL_DAYS = 120


def _today() -> date:
    return timezone.now().date()


#: National List sections that list HANDLING substances. Migration 0038 seeds the § 205.605(b)
#: post-harvest sanitizers into every database, so "any row exists" stopped meaning "the seeder
#: ran": a production database that never ran it would report the list as seeded while every
#: ChemicalEvent was saved unclassified (caught by this module's tests, 2026-09-10). What the
#: seeder provides, and what classification of crop inputs needs, is everything else.
HANDLING_SECTIONS = ("205.605", "205.606")


def national_list_crop_rows():
    """The rows that make the crop-input classification possible — the seeder's, never 0038's."""
    from certifications.models import NationalListSubstance

    return NationalListSubstance.objects.exclude(cfr_section__in=HANDLING_SECTIONS)


def national_list_status() -> dict:
    """Presence of the National List substances used to classify chemical inputs."""
    count = national_list_crop_rows().count()
    seeded = count > 0
    return {
        "dataset": "national_list",
        "seeded": seeded,
        "count": count,
        "status": "ok" if seeded else "missing",
        "detail": (
            f"{count} substances loaded."
            if seeded
            else (
                "National List is not seeded — every ChemicalEvent is being saved without a "
                "CFR classification and certifier findings will be empty. "
                "Run `manage.py seed_national_list`."
            )
        ),
        "remediation": None if seeded else "manage.py seed_national_list",
    }


def usda_snapshot_status() -> dict:
    """Presence AND freshness of the local USDA Organic Integrity mirror."""
    from certifications.models import USDAOrganicOperation

    count = USDAOrganicOperation.objects.count()
    if count == 0:
        return {
            "dataset": "usda_organic_snapshot",
            "loaded": False,
            "count": 0,
            "snapshot_date": None,
            "age_days": None,
            "status": "missing",
            "detail": (
                "USDA Organic mirror is empty — no farm can earn a verified organic badge. "
                "Run `manage.py import_usda_organic_data`."
            ),
            "remediation": "manage.py import_usda_organic_data",
        }

    # The importer stamps every row in a run with the same date, so the newest is the snapshot.
    #
    # The isnull filter is not redundant even though the column is currently NOT NULL: Postgres
    # sorts NULLs FIRST on a DESC order, so were the field ever made nullable, a single undated
    # row would win this query and report a fresh mirror as undated.
    snapshot_date = (
        USDAOrganicOperation.objects.filter(data_snapshot_date__isnull=False)
        .order_by("-data_snapshot_date")
        .values_list("data_snapshot_date", flat=True)
        .first()
    )

    if snapshot_date is None:
        # Unreachable while the column stays NOT NULL, kept so that relaxing the field degrades
        # to "we cannot tell" rather than to a TypeError inside a health check.
        return {
            "dataset": "usda_organic_snapshot",
            "loaded": True,
            "count": count,
            "snapshot_date": None,
            "age_days": None,
            "status": "unknown",
            "detail": (
                f"{count} operations loaded but none carry a data_snapshot_date, so freshness "
                "cannot be determined. Re-import to stamp one."
            ),
            "remediation": "manage.py import_usda_organic_data",
        }

    age_days = (_today() - snapshot_date).days
    if age_days >= USDA_SNAPSHOT_CRITICAL_DAYS:
        status = "critical"
    elif age_days >= USDA_SNAPSHOT_STALE_DAYS:
        status = "stale"
    else:
        status = "ok"

    detail = f"{count} operations, snapshot {snapshot_date} ({age_days} days old)."
    if status != "ok":
        detail += (
            " Farms certified since this snapshot read as 'Pending Verification' and are "
            "publicly labelled not independently verified; farms that surrendered certification "
            "still show a verified badge. Re-import, then run "
            "`manage.py reverify_certifications --all`."
        )

    return {
        "dataset": "usda_organic_snapshot",
        "loaded": True,
        "count": count,
        "snapshot_date": snapshot_date.isoformat(),
        "age_days": age_days,
        "status": status,
        "detail": detail,
        "remediation": None if status == "ok" else "manage.py import_usda_organic_data",
    }


def _build_report() -> dict:
    datasets = [national_list_status(), usda_snapshot_status()]
    severity = {"ok": 0, "unknown": 1, "stale": 2, "critical": 3, "missing": 3}
    overall = max(datasets, key=lambda d: severity.get(d["status"], 0))["status"]
    return {
        "overall": overall,
        "datasets": {d["dataset"]: d for d in datasets},
        "action_required": [d["remediation"] for d in datasets if d["remediation"]],
    }


# This report is served from /health/, which container orchestration polls continuously. Computing
# it costs a COUNT(*) over ~37k rows plus an ORDER BY on an UNINDEXED column (measured: ~7.4 ms,
# 3 queries) — cheap once, wasteful several times a minute forever on a liveness path.
#
# Reference data changes at most monthly, so a few minutes of staleness in the STATUS REPORT is
# meaningless. In-process rather than django.core.cache deliberately: production falls back to
# DummyCache whenever REDIS_URL is unset (prod.py), which would silently make a cache-based fix a
# no-op — exactly the class of silent degradation this module exists to expose.
_CACHE_TTL_SECONDS = 300
_cache: dict = {"computed_at": None, "report": None}


def reset_reference_data_cache() -> None:
    """Drop the memoised report. For tests, and for callers that just changed the data."""
    _cache["computed_at"] = None
    _cache["report"] = None


def reference_data_report(use_cache: bool = True) -> dict:
    """Combined status for both datasets, plus the worst status across them.

    `overall` is deliberately NOT wired to the container's 200/503 decision: stale reference data
    is a correctness problem for claims, not a reason to pull a serving instance out of rotation.
    It is meant to be read — by /health/, by an operator, by a deploy check.

    Pass ``use_cache=False`` for a guaranteed-fresh read.
    """
    if use_cache and _cache["report"] is not None:
        if time.monotonic() - _cache["computed_at"] < _CACHE_TTL_SECONDS:
            return _cache["report"]

    report = _build_report()
    _cache["computed_at"] = time.monotonic()
    _cache["report"] = report
    return report
