"""
Backfill the NEW audit-export fields onto the EXISTING Loewen finished production.

Leonard Loewen already has the consumer link for his published production, so we
do NOT create a new production or change his consumer page — we only add the
authentic certifier-facing data the new audit sections read (none of these fields
surface on the consumer card; all are modal/form/certifier-only):

  * NOP 5012 nitrogen source = "organic" on his OMRI fish/seaweed fertilizer event
  * SOE (§ 205.307(a)) itemized SalesRecords — his real wholesale channel
  * A benign § 205.400(f)(2) OSP change notification (added acreage) — NOP 2615

DELIBERATELY OMITTED (not authentic to a regenerative organic walnut operation):
  * processed animal manure (NOP 5006) — his nitrogen is grazing/cover/compost
  * chlorine post-harvest sanitizer (NOP 5026) — walnuts are dry-hulled, not washed
Injecting those would fabricate practices on a real lead's audit record, which is
the opposite of Trazo's "real vs fake" promise. Use the Solana Verde demo fixture
(backfill_solana_demo_audit_fields) for a kitchen-sink PDF instead.

The actual writes live in ``apply_loewen_audit_fields`` (shared with the seed
command) so the seed and this backfill stay identical. Idempotent — safe to run
more than once and on production.

Usage:
    poetry run python manage.py backfill_loewen_audit_fields
    poetry run python manage.py backfill_loewen_audit_fields samples+loewen@trazo.io
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from company.models import Company
from history.models import Production
from users.models import User

from ._loewen_base import COMPANY_NAME
from ._loewen_events import apply_loewen_audit_fields

DEFAULT_EMAIL = "samples+loewen@trazo.io"


class Command(BaseCommand):
    help = "Backfill NEW audit-export fields on the EXISTING Loewen finished production (no new production)."

    def add_arguments(self, parser):
        parser.add_argument(
            "email",
            type=str,
            nargs="?",
            default=DEFAULT_EMAIL,
            help=f"Sample account email (default: {DEFAULT_EMAIL}).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        email = options["email"]

        user = User.objects.filter(email=email).first()
        if user is None:
            self.stderr.write(self.style.ERROR(f"No user found for {email}. Run create_loewen_farm first."))
            return

        company = Company.objects.filter(name=COMPANY_NAME, company_workers__user=user).first()
        if company is None:
            self.stderr.write(
                self.style.ERROR(f"No '{COMPANY_NAME}' company for {email}. Run create_loewen_farm first.")
            )
            return

        prod = (
            Production.objects.filter(parcel__establishment__company=company, published=True)
            .order_by("-finish_date", "-id")
            .first()
        )
        if prod is None:
            self.stderr.write(self.style.ERROR("No published Loewen production found. Run create_loewen_farm first."))
            return

        self.stdout.write(f"  Production: {prod.name} (#{prod.id}, public_id={prod.public_id})")

        apply_loewen_audit_fields(prod)

        try:
            prod.update_trust_metrics()
        except Exception as e:  # noqa: BLE001 — non-fatal
            self.stdout.write(self.style.WARNING(f"  Trust metrics update failed (non-fatal): {e}"))

        self.stdout.write(
            f"  NOP 5012 nitrogen source, {prod.sales_records.count()} SOE sales record(s), "
            "and NOP 2615 change notification applied."
        )
        self.stdout.write(self.style.SUCCESS("Loewen audit fields backfilled (authentic subset)."))
        self.stdout.write(f"  Consumer page (unchanged): https://consumer.trazo.io/production/{prod.public_id}")
