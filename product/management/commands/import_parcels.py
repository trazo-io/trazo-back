"""White-glove bulk parcel creation for migration onboarding.

Trazo has exactly one parcel-creation path in the UI: a four-step wizard, one parcel at a time.
For the ICP that is a real problem — a mid-size California orchard maps one block to one Parcel,
so 15-25 parcels is normal, and a COG Pro migration means running that wizard 15-25 times while
the farmer waits on the call.

The COG Pro importer does not help: `history/services/cogpro_import.py` writes EVENTS onto an
existing production and creates zero parcels. The parcels have to exist first.

Deliberately an operator tool rather than a self-serve upload, matching `import_cogpro`:
deciding what counts as a parcel on a given farm is a judgement about that farm's records, and
getting it wrong shapes every downstream export.

Usage:

    # See what would be created — writes nothing.
    poetry run python manage.py import_parcels --farm 148 --file blocks.csv

    # Create them.
    poetry run python manage.py import_parcels --farm 148 --file blocks.csv --commit

    # Straight from a COG Pro export, using its distinct Field IDs.
    poetry run python manage.py import_parcels --farm 148 --from-cogpro ./acme-export/ --commit

CSV columns: `name` (required), `area` (optional), `area_unit` (optional: ac/acre/acres or
ha/hectare/hectares), `description` (optional).
"""

import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# `Parcel.area` is stored in HECTARES (product/models.py). The column carries no unit of its own,
# so a value entered as acres is silently 2.47x wrong everywhere downstream — this has shipped as
# a live bug twice. Accept a unit explicitly and convert; refuse anything ambiguous.
HECTARES_PER_ACRE = 0.40468564224

_ACRE_UNITS = {"ac", "acre", "acres"}
_HECTARE_UNITS = {"ha", "hectare", "hectares"}


class Command(BaseCommand):
    help = "Bulk-create parcels on a farm from a CSV (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--farm", type=int, required=True, help="Establishment (farm) id")
        parser.add_argument("--file", help="CSV with columns: name[,area][,area_unit][,description]")
        parser.add_argument(
            "--from-cogpro",
            help=(
                "Directory of COG Pro CSV exports. Creates one parcel per distinct Field ID, "
                "which is the unit COG Pro's Field maps onto in Trazo."
            ),
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually write. Without this the command only reports what it would create.",
        )

    def handle(self, *args, **options):
        from company.models import Establishment

        if not options.get("file") and not options.get("from_cogpro"):
            raise CommandError("Pass --file or --from-cogpro.")
        if options.get("file") and options.get("from_cogpro"):
            raise CommandError("Pass only one of --file / --from-cogpro.")

        try:
            farm = Establishment.objects.select_related("company").get(id=options["farm"])
        except Establishment.DoesNotExist:
            raise CommandError(f"No farm with id {options['farm']}.")

        rows = (
            self._rows_from_cogpro(options["from_cogpro"])
            if options.get("from_cogpro")
            else self._rows_from_csv(options["file"])
        )
        if not rows:
            raise CommandError("No parcel rows found in the input.")

        existing = {p.name.strip().casefold() for p in farm.parcels.all()}
        to_create, skipped = [], []
        for row in rows:
            if row["name"].strip().casefold() in existing:
                skipped.append((row["name"], "a parcel with this name already exists on the farm"))
                continue
            to_create.append(row)
            # Guard against duplicates WITHIN the input as well as against the database.
            existing.add(row["name"].strip().casefold())

        self.stdout.write(self.style.MIGRATE_HEADING(f"{farm.name} ({farm.company.name})"))
        self.stdout.write(f"  Farm currently has {farm.parcels.count()} parcel(s).")
        for row in to_create:
            area = f"{row['area']} ha" if row["area"] is not None else "area not given"
            self.stdout.write(f"    + {row['name']}  ({area})")

        # Skips are printed in full, never summarised: each is a block the operator expected to
        # create and will not get.
        for name, reason in skipped:
            self.stdout.write(self.style.WARNING(f"    - {name}: {reason}"))

        # `Parcel.area` is a non-null FloatField, so a parcel with no stated area is stored as
        # 0.0 — which reads downstream as "zero hectares", not as "unknown". Say so plainly
        # rather than letting a silent zero reach a carbon figure or an audit export.
        without_area = [row["name"] for row in to_create if row["area"] is None]
        if without_area:
            self.stdout.write(
                self.style.WARNING(
                    f"  {len(without_area)} parcel(s) have no area and will be stored as 0.0 ha, "
                    f"which downstream reads as zero rather than unknown. Set them afterwards: "
                    f"{', '.join(without_area[:5])}{' …' if len(without_area) > 5 else ''}"
                )
            )

        self._report_quota(farm, len(to_create))

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN — nothing written. {len(to_create)} parcel(s) would be created, "
                    f"{len(skipped)} skipped. Re-run with --commit."
                )
            )
            return

        from product.models import Parcel

        with transaction.atomic():
            created = [
                Parcel.objects.create(
                    name=row["name"].strip(),
                    establishment=farm,
                    area=row["area"] if row["area"] is not None else 0.0,
                    description=row.get("description") or "",
                )
                for row in to_create
            ]

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Created {len(created)} parcel(s) on {farm.name}."))

    # -- input parsing --------------------------------------------------------------------

    def _rows_from_csv(self, path):
        p = Path(path)
        if not p.exists():
            raise CommandError(f"File not found: {p}")

        with open(p, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames or "name" not in {f.strip().lower() for f in reader.fieldnames}:
                raise CommandError(f"CSV needs a 'name' column. Found: {reader.fieldnames}")
            rows = []
            for line_no, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
                name = row.get("name", "")
                if not name:
                    continue
                rows.append(
                    {
                        "name": name,
                        "area": self._area_in_hectares(row.get("area"), row.get("area_unit"), line_no),
                        "description": row.get("description", ""),
                    }
                )
        return rows

    def _rows_from_cogpro(self, directory):
        """One parcel per distinct COG Pro Field ID.

        COG Pro's Field is the same unit as a Trazo Parcel (its Row/Section ID maps to
        `CommonEvent.block_id` instead).

        Areas come ONLY from the Field Plan tab. That tab's `Area Planted` is the size of the
        field; every other tab's area column is the area TREATED by one operation, which is a
        different number and often a fraction of the block. Using an activity row's area as the
        parcel size would silently misstate the farm.
        """
        d = Path(directory)
        if not d.is_dir():
            raise CommandError(f"Not a directory: {d}")

        from history.services.cogpro_import import analyze

        names = set()
        for path in sorted(d.glob("*.csv")):
            with open(path, "rb") as fh:
                report = analyze(fh)
            if report.get("error"):
                self.stdout.write(self.style.WARNING(f"  {path.name}: {report['error']}"))
                continue
            names.update(report.get("fields") or [])

        plan_names, areas = self._field_plan_fields(d)
        # Field Plan rows also name fields, and for a perennial orchard they are the ONLY place a
        # field appears at all — the event importer skips every one of their rows, because a mature
        # block has no planting date for the season.
        #
        # Take the NAMES, not just the ones that yielded an area: a field whose area is missing or
        # carries an unusable unit is still a real field, and dropping it would lose a parcel the
        # farm actually has.
        names.update(plan_names)

        missing = sorted(n for n in names if n not in areas)
        if missing:
            self.stdout.write(
                self.style.WARNING(
                    f"  No Field Plan area for {len(missing)} field(s); they will be created with "
                    f"no area: {', '.join(missing[:5])}{' …' if len(missing) > 5 else ''}"
                )
            )

        return [{"name": n, "area": areas.get(n), "description": ""} for n in sorted(names)]

    def _field_plan_fields(self, directory):
        """`(field ids seen, {field id: area in hectares})` from the Field Plan tab.

        Parsed directly rather than through the event importer: that importer skips every Field
        Plan row without a Planting Date, which for a perennial orchard is all of them — a mature
        walnut block is not planted each season. So the one file carrying field SIZE is invisible
        to it, and without this a migrated orchard lands with every parcel at 0.0 ha.
        """
        areas = {}
        seen = set()
        for path in sorted(directory.glob("*.csv")):
            with open(path, newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                headers = {(h or "").strip() for h in (reader.fieldnames or [])}
                # Field Plan's distinctive columns — the same signature the event importer routes
                # on, so the two cannot disagree about which file this is.
                if not {"Planting Date", "Seed Lot #", "Planting Method"} <= headers:
                    continue
                for line_no, raw in enumerate(reader, start=2):
                    row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
                    field_id = row.get("Field ID", "")
                    if not field_id:
                        continue
                    seen.add(field_id)
                    # Warn and skip rather than abort. `_area_in_hectares` RAISES on a missing or
                    # unrecognised unit, which is right for --file (the operator wrote that CSV and
                    # can fix it) but wrong here: one odd row in an exported Field Plan would kill
                    # the whole parcel import for a farm that is otherwise fine. The parcel is
                    # still created, just without an area, and the summary says which ones.
                    try:
                        hectares = self._area_in_hectares(row.get("Area Planted"), row.get("Area Measure"), line_no)
                    except CommandError as exc:
                        self.stdout.write(
                            self.style.WARNING(f"  {path.name}: {exc} Area skipped; the parcel is still created.")
                        )
                        continue
                    if hectares is None:
                        continue
                    # A field can appear once per block; sum them into the field total.
                    areas[field_id] = areas.get(field_id, 0.0) + hectares
        return seen, areas

    def _area_in_hectares(self, value, unit, line_no):
        """Convert an area to hectares, or refuse. Never guesses a unit."""
        if not value:
            return None
        try:
            number = float(value)
        except ValueError:
            raise CommandError(f"Line {line_no}: area {value!r} is not a number.")
        if number < 0:
            raise CommandError(f"Line {line_no}: area {value!r} is negative.")

        normalized = (unit or "").strip().lower()
        if normalized in _HECTARE_UNITS:
            return number
        if normalized in _ACRE_UNITS:
            return number * HECTARES_PER_ACRE
        if not normalized:
            raise CommandError(
                f"Line {line_no}: area {value!r} has no area_unit. Parcel.area is stored in "
                f"hectares and the column carries no unit, so an unlabelled number would be "
                f"2.47x wrong if it was acres. Add an area_unit column (ac or ha)."
            )
        raise CommandError(f"Line {line_no}: unrecognised area_unit {unit!r}. Use ac/acres or ha/hectares.")

    # -- reporting ------------------------------------------------------------------------

    def _report_quota(self, farm, wanted):
        """Say up front whether the plan allows this, rather than 403-ing on parcel #3."""
        company = farm.company
        plan = company.subscription_plan
        if plan is None:
            self.stdout.write(
                self.style.ERROR(
                    "  Company has no active subscription plan, so parcel creation will be "
                    "refused. Assign the 'pilot' plan (status active) before importing."
                )
            )
            return

        limit = (plan.features or {}).get("max_parcels_per_establishment", 0)
        current = farm.parcels.count()
        if limit == -1:
            self.stdout.write(f"  Plan '{plan.slug}': unlimited parcels per farm.")
            return

        # Include purchased add-ons, exactly as `Company.can_create_parcel` does. Reading the base
        # plan alone would report a ceiling the API does not actually enforce, and an operator who
        # believed it would move a company off a plan it did not need to leave.
        subscription = getattr(company, "subscription", None)
        if subscription is not None:
            limit += sum(addon.quantity for addon in subscription.addons.filter(addon__slug="extra-parcel"))

        if current + wanted > limit:
            self.stdout.write(
                self.style.ERROR(
                    f"  Plan '{plan.slug}' allows {limit} parcel(s) per farm; this would need "
                    f"{current + wanted}. The API enforces this with a hard 403 — move the "
                    f"company to the 'pilot' plan, or add extra-parcel add-ons, before committing."
                )
            )
        else:
            self.stdout.write(f"  Plan '{plan.slug}': {current + wanted}/{limit} parcel(s) after import.")
