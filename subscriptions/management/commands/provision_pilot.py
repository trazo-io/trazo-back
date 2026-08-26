"""Provision an October pilot farm correctly, in one command.

Hand-provisioning a pilot through Django admin looks like it works and then fails at the first
login, for two reasons that are invisible from the admin screens:

  * `User.is_verified` defaults False, and the login view rejects unverified users.
  * `User.user_type` must be PRODUCER (or SUPERUSER); the login view returns
    ``403 {"error": "Access denied"}`` otherwise.

Both surface to the farmer as the same generic **"Invalid email or password"**, so the operator
sees a password problem that is not a password problem. October is entirely white-glove
provisioning, so every pilot would hit this.

The subscription has its own traps, all load-bearing (see `subscriptions/0008`):
  * plan slug must be `pilot` — `expire_trials` filters `plan__slug="starter"` and would cancel a
    Starter-based pilot on day 14. (That was the behaviour until 2026-08-22; a lapsed subscription now falls back to Starter rather than resolving to nothing, so the blast radius
    of the same mistake today is the loss of the certifier outputs rather than a lockout — but
    a comped pilot silently dropping to the free tier mid-season is still wrong.)
  * status must be `active`/`trialing` — `subscription_plan` resolves for nothing else.
  * price is 0, so `mrr_for()` books zero. Putting a pilot on Enterprise/active instead would
    report $299/mo of revenue that does not exist.

`--renewal-date` is REQUIRED, and it is the grower's own certifier renewal deadline rather than a
count of days. A farmer does not care that a 90-day trial expires; they care that CCOF renewal is
Jan 1, PCO Jan 15, MOSA Feb 1. Anchoring the comp to their real deadline puts the conversion
conversation in the week they have just filed — when the value is most concrete — instead of on an
arbitrary date that means nothing to them. Requiring it also forces the question "when does your
certification renew?" to be asked before provisioning, which is the qualifying question anyway.

The date is recorded, not enforced: nothing in the codebase gates access on `current_period_end`,
so it will not lock a grower out mid-season. It is a conversation trigger, not a kill switch.

Usage:

    # Show what would be created — writes nothing.
    poetry run python manage.py provision_pilot \\
        --company "Sierra Nut Co" --email maria@sierranut.test --farm "Home Ranch" \\
        --state CA --renewal-date 2027-01-01

    # Create it.
    poetry run python manage.py provision_pilot ... --commit

A temporary password is generated and printed once. The operator sends it to the grower over
whatever channel they already use; it is not stored anywhere else.
"""

import secrets
import string
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


def _temp_password(length: int = 16) -> str:
    """A readable one-time password. Excludes characters that are ambiguous when read aloud."""
    alphabet = "".join(c for c in (string.ascii_letters + string.digits) if c not in "0OIl1")
    return "".join(secrets.choice(alphabet) for _ in range(length)) + "!"


class Command(BaseCommand):
    help = "Provision a pilot company, farm and login that actually works (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Company name")
        parser.add_argument("--email", required=True, help="Grower's login email")
        parser.add_argument("--farm", required=True, help="Farm (establishment) name")
        parser.add_argument("--state", default="CA", help="Two-letter state (default CA)")
        parser.add_argument("--country", default="US", help="Country code (default US)")
        parser.add_argument("--first-name", default="", help="Grower's first name")
        parser.add_argument("--last-name", default="", help="Grower's last name")
        parser.add_argument(
            "--renewal-date",
            required=True,
            metavar="YYYY-MM-DD",
            help=(
                "The grower's certifier renewal deadline — when the comp ends and the conversion "
                "conversation happens. Their real date, not a trial length: it is per-operation, "
                "so ask them. Recorded only; nothing locks the account on this date."
            ),
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually write. Without this the command only reports what it would do.",
        )

    def handle(self, *args, **options):
        from company.models import Company, Establishment
        from subscriptions.models import Plan
        from users.models import User

        try:
            pilot_plan = Plan.objects.get(slug="pilot")
        except Plan.DoesNotExist:
            raise CommandError(
                "No `pilot` plan exists. Run `manage.py migrate subscriptions` (migration 0008 "
                "creates it) or `manage.py create_plans`, then retry."
            )

        comp_ends = self._parse_renewal_date(options["renewal_date"])

        email = options["email"].strip().lower()
        existing_user = User.objects.filter(email__iexact=email).first()

        features = pilot_plan.features or {}
        limits = (
            f"{self._render_limit(features.get('max_establishments'))} farm(s), "
            f"{self._render_limit(features.get('max_parcels_per_establishment'))} parcels, "
            f"{self._render_limit(features.get('max_productions_per_year'))} productions/yr, "
            f"{features.get('storage_limit_gb')} GB"
        )

        self.stdout.write(self.style.MIGRATE_HEADING(f"Pilot: {options['company']}"))
        self.stdout.write(f"  Plan        : {pilot_plan.slug} (${pilot_plan.price}/mo — books zero MRR)")
        self.stdout.write(f"  Company     : {options['company']}")
        self.stdout.write(f"  Farm        : {options['farm']} ({options['state']}, {options['country']})")
        self.stdout.write(
            f"  Login       : {email}" + ("  [EXISTING USER — will be updated]" if existing_user else "  [new]")
        )
        self.stdout.write(f"  Limits      : {limits}  (identical to Compliance — conversion loses nothing)")
        self.stdout.write(f"  Comp ends   : {comp_ends:%d %b %Y}  — their certifier renewal deadline")

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written. Re-run with --commit."))
            return

        password = _temp_password()

        with transaction.atomic():
            company, _ = Company.objects.get_or_create(name=options["company"])

            # Replace any prior subscription: a company on Starter/trialing is exactly the state
            # this command exists to prevent, and leaving it would re-arm the 14-day fuse.
            from subscriptions.models import Subscription

            Subscription.objects.filter(company=company).delete()
            Subscription.objects.create(
                company=company,
                plan=pilot_plan,
                status="active",
                current_period_start=timezone.now(),
                # Recorded, never enforced — no code path denies access on current_period_end, and
                # expire_trials only touches plan__slug="starter". This dates the conversion
                # conversation; it does not cut anyone off mid-season.
                current_period_end=comp_ends,
            )

            farm, _ = Establishment.objects.get_or_create(
                name=options["farm"],
                company=company,
                defaults={"country": options["country"], "state": options["state"]},
            )

            user = existing_user or User(email=email)
            user.email = email
            if options["first_name"]:
                user.first_name = options["first_name"]
            if options["last_name"]:
                user.last_name = options["last_name"]
            user.is_active = True
            # THE two gates that silently break a hand-provisioned pilot at first login.
            user.is_verified = True
            user.user_type = self._producer_type()
            user.set_password(password)
            user.save()

            from users.models import WorksIn

            WorksIn.objects.get_or_create(
                user=user,
                company=company,
                defaults={"role": WorksIn.COMPANY_ADMIN},
            )

        company.refresh_from_db()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Pilot provisioned."))
        self.stdout.write(f"  company id  : {company.id}")
        self.stdout.write(f"  farm id     : {farm.id}")
        self.stdout.write(f"  plan        : {company.subscription_plan.slug}")
        self.stdout.write(f"  comp ends   : {comp_ends:%d %b %Y}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING(f"  TEMPORARY PASSWORD: {password}"))
        self.stdout.write("  Shown once and stored nowhere else. Send it to the grower and have them change it.")
        self.stdout.write("")
        self.stdout.write(
            "  Next: `manage.py import_parcels --farm "
            f"{farm.id} --from-cogpro <dir>` if they are migrating from COG Pro."
        )

        # Prove the account can actually do the things a pilot needs, rather than assuming.
        self._verify(company, farm, user, password)

    @staticmethod
    def _producer_type():
        from users import constants

        return constants.PRODUCER

    @staticmethod
    def _render_limit(value):
        return "unlimited" if value == -1 else str(value)

    def _parse_renewal_date(self, raw):
        try:
            parsed = datetime.strptime(raw.strip(), "%Y-%m-%d")
        except (ValueError, AttributeError):
            raise CommandError(f"--renewal-date must be YYYY-MM-DD, got {raw!r} (e.g. 2027-01-01 for a CCOF renewal)")

        aware = timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed
        if aware <= timezone.now():
            raise CommandError(
                f"--renewal-date {raw} is in the past. It is the date the comp ENDS, so a past "
                "date books a pilot that expired before it began."
            )
        return aware

    def _verify(self, company, farm, user, password):
        """Assert the provisioned account is actually usable. Cheap, and the whole point."""
        from subscriptions.models import Plan

        pilot_features = (company.subscription_plan.features or {}) if company.subscription_plan else {}
        compliance = Plan.objects.filter(slug="compliance-yearly").first()
        compliance_features = (compliance.features or {}) if compliance else {}
        # The entitlements a grower would LOSE by converting. Must be empty: a pilot that
        # experiences more than Compliance turns the April conversion into a downgrade.
        entitlement_keys = (
            "max_establishments",
            "max_parcels_per_establishment",
            "max_productions_per_year",
            "storage_limit_gb",
            # Added 2026-08-14. This is now the ONLY entitlement that separates the paid tier from
            # the free one — the capacity limits above are identical on Starter — so a pilot
            # missing it would spend the season unable to produce the certifier packet, the audit
            # exports, the PUR export or a certifier link. That is not a smaller pilot; it is a
            # pilot of a product nobody is being asked to buy, which is exactly what the April
            # conversion verdict must not be measuring.
            "compliance_exports",
        )
        matches_compliance = bool(compliance) and all(
            pilot_features.get(k) == compliance_features.get(k) for k in entitlement_keys
        )

        checks = [
            ("password authenticates", user.check_password(password)),
            ("is_verified (login gate)", bool(getattr(user, "is_verified", False))),
            ("user_type is PRODUCER (login gate)", user.user_type == self._producer_type()),
            ("subscription resolves", company.subscription_plan is not None),
            ("can create a parcel", company.can_create_parcel(farm)),
            ("can create a production", company.can_create_production()),
            # NOT "can create a farm". Pilot mirrors Compliance at 1 farm, and this command has
            # just created it, so that check is expected to be False and asserting it would fail
            # every run. What matters is that converting costs the grower nothing:
            ("entitlements match Compliance (conversion loses nothing)", matches_compliance),
        ]
        self.stdout.write("")
        self.stdout.write("  Post-provision checks:")
        failed = [name for name, ok in checks if not ok]
        for name, ok in checks:
            self.stdout.write(f"    {'PASS' if ok else 'FAIL'}  {name}")
        if failed:
            raise CommandError("Provisioning completed but the account is not usable: " + ", ".join(failed))
