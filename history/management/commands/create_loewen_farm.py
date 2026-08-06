"""
Create the Loewen Family Farm sample fixture (build-first GTM conversion move).

Leonard Loewen is our #1 GTM lead. He replied wanting "a system that divides
between real and fake" organic, then went quiet. Rather than ask him to send
data, we build his farm from real public data + the practices he described, so
he reacts to a live consumer page instead of doing work.

Creates a CLEAN regenerative organic walnut operation under a dedicated sample
account, publishes the finished production, and prints the consumer URL to share.

Usage:
    poetry run python manage.py create_loewen_farm
    poetry run python manage.py create_loewen_farm samples+loewen@trazo.io --reset

Photos: fill LOEWEN_IMAGES in _loewen_base.py with public image URLs first
(hero = sheep grazing under walnut trees) for an eye-catching page.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from company.models import Company
from users.constants import PRODUCER
from users.models import User

from ._loewen_base import COMPANY_NAME, create_loewen_base
from ._loewen_events import create_loewen_current_events, create_loewen_finished_events

DEFAULT_EMAIL = "samples+loewen@trazo.io"


class Command(BaseCommand):
    help = "Seed the Loewen Family Farm regenerative organic walnut sample fixture."

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            type=str,
            nargs="?",
            default=DEFAULT_EMAIL,
            help=f"Sample account email (default: {DEFAULT_EMAIL}).",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing Loewen fixture for this user and recreate.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"]
        reset = options["reset"]

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": "Leonard",
                "last_name": "Loewen",
                "user_type": PRODUCER,
                "is_active": True,
                "is_verified": True,
            },
        )
        if created:
            user.set_password("LoewenSample2026")
            user.save()
            self.stdout.write(self.style.SUCCESS(f"  User created: {email} (password: LoewenSample2026)"))
        else:
            self.stdout.write(f"  User found: {email}")

        existing = Company.objects.filter(name=COMPANY_NAME, company_workers__user=user).first()
        if existing and not reset:
            self.stdout.write(
                self.style.WARNING(f"Loewen fixture already exists for {email} (Company #{existing.id}). Use --reset.")
            )
            return
        if existing and reset:
            self.stdout.write("  Deleting existing Loewen fixture...")
            self._cascade_delete(existing)
            self.stdout.write(self.style.SUCCESS("  Deleted."))

        (
            company,
            establishment,
            parcel,
            product,
            crop_type,
            production_finished,
            production_current,
        ) = create_loewen_base(user)

        self.stdout.write(f"  Company:        {company.name} (#{company.id})")
        self.stdout.write(f"  Establishment:  {establishment.name} (#{establishment.id})")
        self.stdout.write(f"  Parcel:         {parcel.name} ({parcel.area} ha)")

        finished_count = create_loewen_finished_events(production_finished, user)
        current_count = create_loewen_current_events(production_current, user)

        try:
            production_finished.update_trust_metrics()
            production_current.update_trust_metrics()
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"  Trust metrics update failed (non-fatal): {e}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Loewen Family Farm sample seeded successfully!"))
        self.stdout.write(f"  Finished prod:  #{production_finished.id} — {finished_count} events (PUBLISHED)")
        self.stdout.write(f"  Current prod:   #{production_current.id} — {current_count} events")
        self.stdout.write("")
        self.stdout.write("  Consumer page (share this with Leonard):")
        self.stdout.write(f"    https://consumer.trazo.io/production/{production_finished.public_id}")
        self.stdout.write("")
        hero = bool(getattr(production_finished, "cover_image_url", ""))
        if not hero:
            self.stdout.write(
                self.style.WARNING(
                    "  NOTE: no hero photo set. Fill LOEWEN_IMAGES in _loewen_base.py with real "
                    "public image URLs and re-run with --reset for an eye-catching page."
                )
            )

    def _cascade_delete(self, company):
        """Delete fixture in dependency order (raw event delete bypasses auditlog signals)."""
        from django.db import connection

        from history.models import (
            BusinessEvent,
            ChemicalEvent,
            EquipmentEvent,
            GeneralEvent,
            History,
            PestManagementEvent,
            ProductionEvent,
            SoilManagementEvent,
            WeatherEvent,
        )

        history_ids = list(History.objects.filter(parcel__establishment__company=company).values_list("id", flat=True))
        if history_ids:
            event_models = [
                BusinessEvent,
                ChemicalEvent,
                EquipmentEvent,
                GeneralEvent,
                PestManagementEvent,
                ProductionEvent,
                SoilManagementEvent,
                WeatherEvent,
            ]
            with connection.cursor() as cur:
                for M in event_models:
                    cur.execute(f"DELETE FROM {M._meta.db_table} WHERE history_id = ANY(%s)", [history_ids])
        company.delete()
