"""
Orchestrator: refresh all organic-input catalogs Trazo drift-checks against.

Runs in sequence (never in parallel — catalog order matters so CDFA tags land
on freshly-loaded WSDA/OMRI rows):

    1. seed_omri_minimal        — committed 58-product OMRI reference subset
    2. seed_wsda_materials      — committed WSDA snapshot
    3. seed_cdfa_oim            — tags OMRI + WSDA rows with CDFA OIM reg numbers
    4. sync_national_list_ecfr  — hash-compare § 205.601/602 vs eCFR API v1

Each step writes a `IngestionRun` row so the admin surface (and audit PDF
footer) can show "last synced: N days ago" per source.

This command is idempotent. It's safe to run on every deploy and on a weekly
cron. Intended production cadence:

    - DO App Platform cron: weekly on Sunday 03:00 UTC
    - Post-deploy hook: run once after every release

Exit code is 0 even if a network fetch fails (eCFR) so a transient network
issue doesn't tank a deploy. Error conditions are logged in IngestionRun.

Usage:
    poetry run python manage.py refresh_organic_input_catalogs
    poetry run python manage.py refresh_organic_input_catalogs --skip-ecfr
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import BaseCommand

from certifications.models import IngestionRun, OMRIProduct, WSDAMaterial


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
            try:
                buf = StringIO()
                call_command("sync_national_list_ecfr", stdout=buf)
                output = buf.getvalue().strip()
                changed = "CHANGED" in output
                IngestionRun.objects.create(
                    source="national_list_ecfr",
                    status=("changed" if changed else "unchanged"),
                    message=output,
                )
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ national_list_ecfr — {'changed' if changed else 'unchanged'}")
                )
            except Exception as e:  # pragma: no cover — defensive
                IngestionRun.objects.create(source="national_list_ecfr", status="error", message=str(e))
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
