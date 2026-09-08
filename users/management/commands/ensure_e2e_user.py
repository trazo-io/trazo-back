"""Idempotently create the account the Playwright E2E suite signs in as.

WHY A COMMAND AND NOT A FIXTURE
-------------------------------
The E2E suite needs a real user with a known password, and the dev database has 94 users
none of whose passwords are knowable. Hardcoding a guess into the suite makes it fail for
reasons that have nothing to do with the code under test; seeding through the ORM here makes
the suite self-sufficient and repeatable.

SAFETY
------
This creates an account whose password is written down in a repository. That is acceptable
in a dev database and unacceptable anywhere else, so there are TWO guards:

1. `settings.DEBUG` must be true. This one is ABSOLUTE — nothing overrides it, including
   `--force`. An E2E convenience that can be pointed at production is a backdoor with a
   friendly name.
2. The database NAME must contain a disposable-looking token (see `_looks_disposable`).
   This is the softer guard, for the case where DEBUG is deliberately true against a
   database that is nonetheless real. `--force` overrides THIS one and only this one — it
   exists for a CI container whose database is named something unrecognisable.

Usage:
    poetry run python manage.py ensure_e2e_user
    poetry run python manage.py ensure_e2e_user --company 0
    poetry run python manage.py ensure_e2e_user --email other@trazo.test --password '...'
"""

import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from users.constants import PRODUCER

DEFAULT_EMAIL = "e2e@trazo.test"
DEFAULT_PASSWORD = "E2Epass!2026"

# A database is "disposable" if its name says so — matched as whole, delimiter-separated
# TOKENS, never as substrings.
#
# ⚠️ The first version used `any(m in db_name.lower() for m in ...)`. MEASURED: that let
# `trazo_pacific`, `trazo_precision`, `specific_db` and `trazo_decide` all through on the
# substring "ci", and `trazo_isolated` on "iso". A guard whose job is to refuse a production
# database must not be defeated by a company name that happens to contain "ci".
_DISPOSABLE_NAME_TOKENS = frozenset({"test", "ci", "iso", "e2e", "dev", "local"})

#: Also accept a numbered isolation database (`trazo_iso52`, `trazo_iso_omri3`), which is the
#: per-session convention the test suites use.
_DISPOSABLE_TOKEN_RE = re.compile(r"^(?:iso|test|ci|e2e|dev)[0-9_]*$")


def _looks_disposable(db_name: str) -> bool:
    """True when a token of the database name marks it as a throwaway.

    Splits on any non-alphanumeric run, so `trazo_iso52` -> {"trazo", "iso52"} and
    `trazo_pacific` -> {"trazo", "pacific"} — the latter matching nothing.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", db_name.lower()) if t]
    return any(t in _DISPOSABLE_NAME_TOKENS or _DISPOSABLE_TOKEN_RE.match(t) for t in tokens)


class Command(BaseCommand):
    help = "Create or reset the E2E test user (dev/CI only; refuses when DEBUG is False)."

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, default=DEFAULT_EMAIL)
        parser.add_argument("--password", type=str, default=DEFAULT_PASSWORD)
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Skip the database-NAME check, for a CI container whose database is not "
                "named recognisably. Does NOT skip the DEBUG=False refusal, which is absolute."
            ),
        )
        parser.add_argument(
            "--company",
            type=int,
            default=None,
            help=(
                "Attach the user to this company id as Company Admin. Without it the user has "
                "no company and every farm-scoped route redirects to company selection, which "
                "makes data-dependent specs fail for a reason that is not the code under test. "
                "Pass 0 to auto-pick the first company that owns at least one farm."
            ),
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Refusing to run with DEBUG=False. This command creates an account whose "
                "password is committed to the repository; it is a dev/CI fixture, never a "
                "production account."
            )

        db_name = str(settings.DATABASES["default"].get("NAME", ""))
        looks_disposable = _looks_disposable(db_name)
        if not looks_disposable and not options["force"]:
            raise CommandError(
                f'Database "{db_name}" does not look like a dev/test database '
                f"(expected one of {sorted(_DISPOSABLE_NAME_TOKENS)} as a token in the name). "
                "Re-run with --force only if you are certain this database is disposable."
            )

        email = options["email"]
        password = options["password"]
        user_model = get_user_model()

        with transaction.atomic():
            user, created = user_model.objects.get_or_create(email=email)
            user.set_password(password)
            # is_active defaults to False on this model and verification is a separate flag;
            # an E2E user that has to walk the email-verification flow before every run would
            # test MailDev, not the product.
            user.is_active = True
            user.is_verified = True
            user.user_type = PRODUCER
            if not user.first_name:
                user.first_name = "E2E"
            if not user.last_name:
                user.last_name = "Runner"
            user.save()

        verb = "Created" if created else "Reset"
        self.stdout.write(self.style.SUCCESS(f"{verb} E2E user {email} on database {db_name}"))
        self.stdout.write(f"  is_active={user.is_active} is_verified={user.is_verified} user_type={user.user_type}")

        if options["company"] is not None:
            self._attach_company(user, options["company"])

    def _attach_company(self, user, company_id):
        from company.models import Company, Establishment
        from users.models import WorksIn

        if company_id == 0:
            company = Company.objects.filter(establishment__isnull=False).distinct().first()
            if company is None:
                raise CommandError("No company owns a farm on this database; seed demo data first.")
        else:
            try:
                company = Company.objects.get(pk=company_id)
            except Company.DoesNotExist:
                raise CommandError(f"Company {company_id} does not exist.")

        works_in, _ = WorksIn.objects.get_or_create(
            user=user,
            company=company,
            defaults={"role": WorksIn.COMPANY_ADMIN},
        )
        if works_in.role != WorksIn.COMPANY_ADMIN:
            works_in.role = WorksIn.COMPANY_ADMIN
            works_in.save(update_fields=["role"])

        farms = list(Establishment.objects.filter(company=company))
        works_in.establishments_in_charge.set(farms)

        self.stdout.write(f"  attached to company {company.pk} ({company.name}) as Company Admin")
        self.stdout.write(f"  farms in charge: {[f.pk for f in farms]}")
