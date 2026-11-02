"""
Orchestrator: refresh all organic-input catalogs Trazo drift-checks against.

Runs in sequence (never in parallel — catalog order matters so CDFA tags land
on freshly-loaded WSDA/OMRI rows):

    1. seed_omri_minimal        — committed OMRI reference subset, transcribed from the
                                  free Crop Products List PDF (September 5, 2026 edition)
    2. seed_wsda_materials      — the full published WSDA Organic Input Material List
                                  (782 rows, March 06, 2026 edition)
    3. seed_cdfa_oim            — flags OMRI + WSDA rows that are also CDFA OIM registered,
                                  by EXACT name match. CDFA publishes no registration
                                  number, so none is written.
    4. sync_national_list_ecfr  — hash-compare § 205.601/602 vs eCFR API v1

Order matters: CDFA flags land on freshly-loaded WSDA/OMRI rows. To bring an
already-seeded database into line with the published lists (rather than just re-running
the seeds), use `repair_input_catalogs`, which re-keys fabricated identifiers in place
so no OSP loses an approved input.

Each step writes a `IngestionRun` row so the admin surface (and audit PDF
footer) can show "last synced: N days ago" per source.

Cadence (triaged 2026-11-02, see `certifications/services/national_list_check.py`):

    - This command is NOT scheduled. Run it by hand after a deploy that changes one of the
      committed CSVs (`certifications/data/*_seed.csv`). Deploys run only `migrate`, so
      nothing runs it automatically.
    - Step 4 alone, the eCFR check, IS scheduled: monthly, through
      `run_due_maintenance --cadence monthly` (`backend/scheduled_work.py`,
      "check-national-list-ecfr"). It is the only step that reads anything outside the
      repository.

Why the seeds are not on a cron: their input changes only on deploy, so a scheduled run
re-applies the same file and writes an `IngestionRun(status="ok")` that the certifier packet
prints as a "last synced" date for an edition that has not changed. Re-running them against a
seeded database is stable (no duplicates, no deleted or re-keyed row, OSP citations intact:
`certifications/tests/test_catalog_refresh_rerun.py`), so running this by hand is safe.

Exit code is 0 even if a network fetch fails (eCFR) so a transient network
issue doesn't tank a deploy. A failed step is recorded as
`IngestionRun(status="error")` — never as a sync — because the certifier packet's
catalog-freshness line reads those rows and must not print a failure as a refresh.

Usage:
    poetry run python manage.py refresh_organic_input_catalogs
    poetry run python manage.py refresh_organic_input_catalogs --skip-ecfr
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand

from certifications.models import IngestionRun, OMRIProduct, WSDAMaterial
from certifications.services.national_list_check import record_national_list_check


class Command(BaseCommand):
    help = "Refresh all organic-input catalogs in order (OMRI, WSDA, CDFA OIM, National List eCFR)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-ecfr",
            action="store_true",
            help="Skip the eCFR network fetch (useful in offline dev environments).",
        )

    def handle(self, *args, **opts):
        self.stdout.write(self.style.NOTICE("Refreshing organic-input catalogs…"))

        # 1. OMRI (idempotent, committed CSV)
        self._run("omri", lambda: call_command("seed_omri_minimal"), before_count=OMRIProduct.objects.count)

        # 2. WSDA (idempotent, committed CSV)
        self._run(
            "wsda",
            lambda: call_command("seed_wsda_materials"),
            before_count=WSDAMaterial.objects.count,
        )

        # 3. CDFA OIM tagging (no "count" — just tags existing rows)
        try:
            buf = StringIO()
            call_command("seed_cdfa_oim", stdout=buf)
            IngestionRun.objects.create(
                source="cdfa_oim",
                status="ok",
                rows_updated=0,
                message=buf.getvalue().strip(),
            )
            self.stdout.write(self.style.SUCCESS(f"  ✓ cdfa_oim — {buf.getvalue().strip()}"))
        except Exception as e:  # pragma: no cover — defensive
            IngestionRun.objects.create(source="cdfa_oim", status="error", message=str(e))
            self.stderr.write(self.style.ERROR(f"  ✗ cdfa_oim failed: {e}"))

        # 4. eCFR snapshot (network)
        if opts.get("skip_ecfr"):
            IngestionRun.objects.create(
                source="national_list_ecfr",
                status="skipped",
                message="--skip-ecfr flag",
            )
            self.stdout.write(self.style.WARNING("  ⊘ national_list_ecfr skipped"))
        else:
            # 2026-09-06: success used to be inferred from `"CHANGED" in output`, so a 404
            # was recorded as status="unchanged" and printed on the certifier packet as a catalog
            # synced today. The sync command now raises on failure and returns its outcome.
            # 2026-11-02: the recording moved to `record_national_list_check`, shared with the
            # monthly scheduled check, so "changed" means "changed since the last review" on both
            # paths instead of "changed since the previous fetch", which lasted one run.
            try:
                run = record_national_list_check()
                self.stdout.write(self.style.SUCCESS(f"  ✓ national_list_ecfr — {run.status}"))
                if run.status == "changed":
                    summary = run.message.split("\n\n", 1)[0]
                    self.stdout.write(self.style.WARNING(f"  {summary}"))
            except Exception as e:
                # record_national_list_check writes the error row for any failure before the
                # outcome is known, fetch or otherwise, so none is written here.
                self.stderr.write(self.style.ERROR(f"  ✗ national_list_ecfr failed: {e}"))

        self.stdout.write(self.style.SUCCESS("Refresh complete."))

    def _run(self, source: str, action, *, before_count):
        """Run a seed step and record an IngestionRun row with create/update counts.

        Delta is computed from the catalog's row count before/after the step
        (not from scraped stdout), so it is robust against seed commands that
        change their summary format. Sub-command stdout is allowed to flow to
        the orchestrator's stdout so operators running this manually still
        see the familiar per-step summaries.
        """
        try:
            before = before_count() if callable(before_count) else 0
            action()
            after = before_count() if callable(before_count) else 0
            delta = max(0, after - before)
            IngestionRun.objects.create(
                source=source,
                status="ok",
                rows_created=delta,
                message=f"before={before} after={after}",
            )
            self.stdout.write(self.style.SUCCESS(f"  ✓ {source} — {before} → {after} rows"))
        except Exception as e:  # pragma: no cover — defensive
            IngestionRun.objects.create(source=source, status="error", message=str(e))
            self.stderr.write(self.style.ERROR(f"  ✗ {source} failed: {e}"))
