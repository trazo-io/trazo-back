"""Give every company a new join code.

Run once after the 2026-09-28 tenancy fix deploys: until then any signed-in account could list
every company WITH its join code, so every code issued before that date has to be treated as
known to outsiders. People who already joined keep their access; a new code only stops new
joins with the old one.

    python manage.py rotate_company_codes            # dry run: counts only
    python manage.py rotate_company_codes --apply    # write the new codes
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from company.models import Company


class Command(BaseCommand):
    help = "Replace every company's join code (invitation_code). Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write the new codes.")

    def handle(self, *args, apply=False, **options):
        companies = Company.objects.order_by("id")
        total = companies.count()
        if not apply:
            self.stdout.write(f"Dry run: {total} companies would get a new join code. Re-run with --apply.")
            return
        with transaction.atomic():
            for company in companies.select_for_update():
                company.invitation_code = company.generate_invitation_code()
                company.save(update_fields=["invitation_code"])
        self.stdout.write(self.style.SUCCESS(f"Rotated the join code of {total} companies."))
