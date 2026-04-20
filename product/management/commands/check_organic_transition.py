"""
NOP 7 CFR 205.202 — Organic transition status CLI (Sprint 2.2).

Usage:
    poetry run python manage.py check_organic_transition <parcel_id>
    poetry run python manage.py check_organic_transition --establishment <est_id>
    poetry run python manage.py check_organic_transition --all
"""

from django.core.management.base import BaseCommand, CommandError

from product.models import Parcel
from product.services.transition_status_service import compute_transition_status


class Command(BaseCommand):
    help = "Compute NOP organic transition status for one or more parcels (7 CFR 205.202)."

    def add_arguments(self, parser):
        parser.add_argument("parcel_id", nargs="?", type=int, help="Single parcel ID to check.")
        parser.add_argument("--establishment", type=int, help="Check all parcels in establishment.")
        parser.add_argument("--all", action="store_true", help="Check all parcels.")

    def handle(self, *args, **opts):
        if opts.get("all"):
            parcels = Parcel.objects.all()
        elif opts.get("establishment"):
            parcels = Parcel.objects.filter(establishment_id=opts["establishment"])
        elif opts.get("parcel_id"):
            parcels = Parcel.objects.filter(pk=opts["parcel_id"])
            if not parcels.exists():
                raise CommandError(f"Parcel {opts['parcel_id']} not found")
        else:
            raise CommandError("Provide a parcel_id, --establishment, or --all")

        for parcel in parcels.iterator():
            status_obj = compute_transition_status(parcel)
            self.stdout.write(
                self.style.MIGRATE_HEADING(f"\nParcel: {status_obj.parcel_name} (id={status_obj.parcel_id})")
            )
            if status_obj.is_eligible:
                self.stdout.write(self.style.SUCCESS("  Eligible: YES"))
            else:
                self.stdout.write(self.style.WARNING(f"  Eligible: NO ({status_obj.days_remaining} days remaining)"))
            if status_obj.last_prohibited_date:
                self.stdout.write(f"  Last prohibited: {status_obj.last_prohibited_date}")
                self.stdout.write(f"  Transition completes: {status_obj.transition_complete_date}")
            self.stdout.write(f"  Findings: {len(status_obj.findings)}")
            for f in status_obj.findings[:5]:
                self.stdout.write(f"    - [{f.source}] {f.date_observed}: {f.description}")
            if status_obj.note:
                self.stdout.write(self.style.NOTICE(f"  Note: {status_obj.note}"))
