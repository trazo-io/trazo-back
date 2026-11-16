"""
White-glove COG Pro import.

COG Pro stops service 2026-12-31, so its subscribers must migrate during Oct–Dec 2026. The
migration page (`/cog-pro-migration`) promises "send us your export and we will set it up for you"
— this command is how that promise is kept. It is deliberately an operator tool, not a self-serve
upload: a human looks at the farm's records while deciding which production each file belongs to.

Usage:

    # See what a file contains — writes nothing.
    poetry run python manage.py import_cogpro --file cogpro_my_fertility_input_data.csv

    # Import it onto a production.
    poetry run python manage.py import_cogpro --file fertility.csv --production 528 --commit

    # A whole export folder, one production.
    poetry run python manage.py import_cogpro --dir ./acme-export/ --production 528 --commit
"""

from contextlib import ExitStack
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from history.models import Production
from history.services.cogpro_import import analyze, build_plan, execute


class Command(BaseCommand):
    help = "Import a COG Pro CSV export into Trazo events (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--file", help="A single COG Pro CSV export")
        parser.add_argument("--dir", help="A folder of COG Pro CSV exports")
        parser.add_argument("--production", type=int, help="Target production (History) id")
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually write. Without this the command only reports what it would do.",
        )
        parser.add_argument("--limit", type=int, default=8, help="Rows to show per file in the preview (default 8)")
        parser.add_argument(
            "--created-by",
            help=(
                "Email of the operator running the import; written to every record's created_by. "
                "Required with --commit: a migrated record with no author is the pilot rehearsal's "
                "misattribution with the name left blank instead of wrong."
            ),
        )
        parser.add_argument(
            "--analyze",
            action="store_true",
            help=(
                "Report the SHAPE of the export — which fields, crops and years it covers, and "
                "how many Trazo productions it implies. Run this FIRST: COG Pro activity rows "
                "carry no production column, so the operator decides the grouping."
            ),
        )

    def handle(self, *args, **options):
        paths = self._collect_paths(options)
        if not paths:
            raise CommandError("Nothing to do — pass --file or --dir.")

        if options["analyze"]:
            return self._analyze(paths)

        production = None
        self.created_by = None
        if options["commit"]:
            if not options["production"]:
                raise CommandError("--commit requires --production <id>.")
            if not options.get("created_by"):
                raise CommandError("--commit requires --created-by <operator email>.")
            from django.contrib.auth import get_user_model

            self.created_by = get_user_model().objects.filter(email__iexact=options["created_by"]).first()
            if self.created_by is None:
                raise CommandError(f"No account with email {options['created_by']!r}.")
            try:
                production = Production.objects.select_related("parcel__establishment__company").get(
                    id=options["production"]
                )
            except Production.DoesNotExist:
                raise CommandError(f"No production with id {options['production']}.")
            # The author must belong to the operation, as `import_records` requires: a migrated
            # record attributed to an outsider is the misattribution `created_by` exists to
            # prevent, printed in the dossier's "Imported by" line (review of back #233).
            from users.models import WorksIn

            company = production.parcel.establishment.company
            if not WorksIn.objects.filter(user=self.created_by, company=company).exists():
                raise CommandError(
                    f"{self.created_by.email} is not a member of {company.name}; records need an author who is."
                )
            # A hand-created target without a crop/product is how the "timeline
            # renders but the app thinks there is no production" state used to
            # ship to COG Pro migrants. Create the production through the app
            # (Start production), which sets crop, product, and current_history —
            # then import onto it.
            if production.crop_type_id is None or production.product_id is None:
                raise CommandError(
                    f"Production {production.id} has no crop/product set. Create the target "
                    "production through the app (Start production on the parcel) so crop, "
                    "product, and current-production wiring are all in place, then re-run. "
                    "(An existing crop-less production can be repaired once via Edit production.)"
                )
            self.stdout.write(
                self.style.WARNING(f"Importing into: {production.name} " f"({production.parcel.establishment.name})")
            )

        totals = {"import": 0, "skip": 0, "unrecognised": 0}

        # One transaction for the WHOLE export, not one per file.
        #
        # Per-file atomicity meant a failure on file 6 of 7 left files 1-5 committed: the farm is
        # half-migrated, nothing says which half, and re-running duplicates everything that
        # already landed. A migration has to be all-or-nothing so the operator can simply fix the
        # cause and run it again.
        with ExitStack() as stack:
            if options["commit"]:
                stack.enter_context(transaction.atomic())
            self._run(paths, options, production, totals)

        self._report(options, totals)

    def _run(self, paths, options, production, totals):
        for path in paths:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(path.name))
            with open(path, "rb") as fh:
                plan = build_plan(fh)

            if plan.area is None:
                totals["unrecognised"] += 1
                self.stdout.write(self.style.ERROR(f"  {plan.error}"))
                continue

            self.stdout.write(
                f"  Detected: {plan.area.label}  →  {plan.area.target}   "
                f"({len(plan.importable)} importable, {len(plan.skipped)} skipped)"
            )
            for row in plan.importable[: options["limit"]]:
                self.stdout.write(f"    + line {row.line}: {row.summary}")
            if len(plan.importable) > options["limit"]:
                self.stdout.write(f"    … {len(plan.importable) - options['limit']} more")

            # Skips are printed in full, never summarised away: each one is a record the farmer
            # had in COG Pro that will NOT arrive in Trazo, and the operator has to decide about
            # it. Silently dropping rows during a migration is how records disappear.
            for row in plan.skipped:
                self.stdout.write(self.style.WARNING(f"    - line {row.line}: {row.reason}"))

            totals["import"] += len(plan.importable)
            totals["skip"] += len(plan.skipped)

            if options["commit"]:
                result = execute(plan, production, created_by=self.created_by, source_title=path.name)
                self.stdout.write(self.style.SUCCESS(f"  Imported {result['created']} events."))

    def _report(self, options, totals):
        self.stdout.write("")
        if options["commit"]:
            self.stdout.write(
                self.style.SUCCESS(f"Done. {totals['import']} events imported, {totals['skip']} rows skipped.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — nothing written. {totals['import']} rows would import, "
                    f"{totals['skip']} would be skipped. Re-run with --production <id> --commit."
                )
            )
        if totals["unrecognised"]:
            self.stdout.write(self.style.ERROR(f"{totals['unrecognised']} file(s) were not recognised."))

    def _collect_paths(self, options):
        paths = []
        if options.get("file"):
            p = Path(options["file"])
            if not p.exists():
                raise CommandError(f"No such file: {p}")
            paths.append(p)
        if options.get("dir"):
            d = Path(options["dir"])
            if not d.is_dir():
                raise CommandError(f"Not a directory: {d}")
            paths.extend(sorted(d.glob("*.csv")))
        return paths

    def _analyze(self, paths):
        """Structural report. COG Pro is field-centric and flat; Trazo is production-centric,
        so the operator has to decide how a decade of flat activity rows becomes parcels and
        productions. This shows them what they are dealing with before anything is written."""
        all_fields, all_crops, all_years, total_groups = set(), set(), set(), 0
        total_unscoped = 0

        for path in paths:
            with open(path, "rb") as fh:
                report = analyze(fh)
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(path.name))
            if report.get("error"):
                self.stdout.write(self.style.ERROR(f"  {report['error']}"))
                continue

            all_fields |= set(report["fields"])
            all_crops |= set(report["crops"])
            all_years |= set(report["years"])
            total_groups += len(report["groups"])
            total_unscoped += report.get("unscoped_rows", 0)

            years = report["years"]
            self.stdout.write(
                f"  {report['label']}: {report['rows']} rows · "
                f"{len(report['fields'])} field(s) · {len(report['crops'])} crop(s) · "
                f"{years[0] if years else '?'}–{years[-1] if years else '?'}"
            )
            self.stdout.write(f"  Implies {len(report['groups'])} Trazo production(s) (Field + Crop + Year):")
            for g in report["groups"]:
                self.stdout.write(f"    {g['field_id']:22} {g['crop']:22} {g['year']}   {g['events']} event(s)")

        self.stdout.write("")
        self.stdout.write(self.style.WARNING("STRUCTURE SUMMARY"))
        self.stdout.write(f"  Parcels to create in Trazo : {len(all_fields)}  {sorted(all_fields)}")
        if total_unscoped:
            self.stdout.write(
                f"  Rows with no Field ID      : {total_unscoped}  "
                f"(equipment-scoped work, e.g. sprayer cleanout under 205.272 — NOT a parcel)"
            )
        self.stdout.write(f"  Crops seen                 : {len(all_crops)}")
        self.stdout.write(
            f"  Years covered              : "
            f"{min(all_years) if all_years else '?'}–{max(all_years) if all_years else '?'}"
        )
        self.stdout.write(f"  Productions implied        : {total_groups}")
        self.stdout.write("")
        self.stdout.write(
            "  COG Pro activity rows carry no production/batch column — only Field Plan and "
            "Harvest do. Create the parcels and productions above first, then import each group "
            "with --production <id>."
        )
