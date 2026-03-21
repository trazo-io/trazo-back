"""
Management command to re-verify all active certifications.

Usage:
    poetry run python manage.py reverify_certifications
    poetry run python manage.py reverify_certifications --days-ahead 60
    poetry run python manage.py reverify_certifications --all
"""

from django.core.management.base import BaseCommand

from certifications.services.verification_manager import VerificationManager


class Command(BaseCommand):
    help = "Re-verify all active certifications against external databases"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=30,
            help="Check certifications expiring within N days (default: 30)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-verify all active certifications, not just expiring ones",
        )

    def handle(self, *args, **options):
        days_ahead = options["days_ahead"]
        verify_all = options["all"]

        self.stdout.write(f"Starting certification re-verification " f"(days_ahead={days_ahead}, all={verify_all})...")

        manager = VerificationManager()

        if verify_all:
            days_ahead = 36500  # ~100 years = effectively all

        result = manager.reverify_all_active(days_ahead=days_ahead)

        self.stdout.write(
            self.style.SUCCESS(
                f"Re-verification complete: " f"{result['total']} checked, {result['changed']} status changes"
            )
        )
