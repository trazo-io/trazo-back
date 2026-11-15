"""
Management command to regenerate QR codes with branded Trazo styling.

Regenerates QR codes for existing productions using the new branded format:
- Green rounded modules
- Trazo leaf logo in center
- CTA frame: "Scan to see your food's journey"

Usage:
    poetry run python manage.py regenerate_qr_codes              # All productions
    poetry run python manage.py regenerate_qr_codes --dry-run    # Preview only
    poetry run python manage.py regenerate_qr_codes --id 123     # Single production
"""

from io import BytesIO

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from history.models import Production


class Command(BaseCommand):
    help = "Regenerate QR codes with branded Trazo styling (green, logo, CTA frame)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview which productions would be regenerated without making changes",
        )
        parser.add_argument(
            "--id",
            type=int,
            help="Regenerate QR code for a specific production ID only",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        production_id = options["id"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no changes will be made"))

        # Build queryset
        queryset = Production.objects.select_related("product", "parcel__establishment")
        if production_id:
            queryset = queryset.filter(id=production_id)

        total = queryset.count()
        self.stdout.write(f"Found {total} production(s) to process")

        if total == 0:
            self.stdout.write(self.style.WARNING("No productions found"))
            return

        regenerated = 0
        skipped = 0
        errors = 0

        for history in queryset.iterator():
            product_name = history.product.name if history.product else "Unknown"
            label = f"[{history.id}] {product_name}"

            if not history.public_id:
                self.stdout.write(self.style.WARNING(f"  SKIP {label} - no public_id"))
                skipped += 1
                continue

            if dry_run:
                has_qr = "has QR" if history.qr_code else "no QR"
                self.stdout.write(f"  WOULD regenerate: {label} ({has_qr})")
                regenerated += 1
                continue

            try:
                from django.conf import settings

                consumer_url = f"{settings.BASE_CONSUMER_URL}production/{history.public_id}"

                qr_image = Production._generate_branded_qr(consumer_url)

                buf = BytesIO()
                qr_image.save(buf, format="PNG")

                history.qr_code.save(
                    f"{history.name}-{history.start_date}.png",
                    ContentFile(buf.getvalue()),
                    save=False,
                )
                Production.objects.filter(pk=history.pk).update(qr_code=history.qr_code.name)

                regenerated += 1
                self.stdout.write(self.style.SUCCESS(f"  OK {label}"))
            except Exception as e:
                errors += 1
                self.stdout.write(self.style.ERROR(f"  FAIL {label}: {e}"))

        self.stdout.write("")
        self.stdout.write(f"Processed: {regenerated + skipped + errors}/{total}")
        self.stdout.write(self.style.SUCCESS(f"  Regenerated: {regenerated}"))
        if skipped:
            self.stdout.write(self.style.WARNING(f"  Skipped: {skipped}"))
        if errors:
            self.stdout.write(self.style.ERROR(f"  Errors: {errors}"))
