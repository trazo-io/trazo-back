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

Two people, two ways in. Each account belongs to this pilot company and to nothing else.

  * THE ONE-COMPANY RULE (2026-10-17). The app loads `user.companies[0]` after sign-in and has no
    company switcher, and `CompanyInvitation.accept()` is a company transfer. An account that
    belongs to two companies can never open one of them. From 2026-10-01 to 2026-10-17 this
    command added the operator's own account (oscar@trazo.io) to each pilot as a second
    membership, and a production rehearsal found the operator could not open the pilot at all.
    So the command refuses any account (operator or grower) that already belongs to another
    company. `remove_pilot_operator` takes a stale operator membership off a pilot.

  * The OPERATOR (`--operator-email`) gets an account of its own for THIS pilot, e.g.
    oscar+sierranut@trazo.io. Setup records are typed by the operator, and `created_by` is the
    author an audit trail shows; the rehearsal typed every record under the grower's login, so
    every record said the grower wrote it. If the account does not exist the command creates it:
    "<first name> <last name> (Trazo setup)", producer, no usable password, no mail sent, and a
    Company Admin membership in this company. It prints an OPERATOR SETUP LINK (a
    `/auth/reset-password` token as long-lived as the grower's invitation) where the operator sets
    the password. Not an invitation: the grower's invitation names the operator as its inviter,
    so the operator account has to exist first, and `signup_with_invitation` refuses an email
    that already has an account. An existing account is accepted only if it belongs to no other
    company and can sign in (or is still waiting on its own setup link, which is then renewed).
    `add_pilot_operator` does the same for a pilot that is already provisioned.

  * The GROWER gets an invitation link, not a password. The command used to create the grower
    with a temporary password, which skipped the Terms: `terms_accepted_at` is only stamped on
    account creation by a sign-up path that sends `accept_terms`, and this command was not one.
    The invitation's setup page (`/invitation/<code>/setup`) has the grower choose their own
    password and requires the Terms box; `signup_with_invitation` stamps the acceptance and sets
    the two login gates above. No password travels by email.
    If the grower already has an account, they are added directly and the command says so: their
    Terms record is whatever their own sign-up captured. That account must belong to no other
    company, by the same rule.

Usage:

    # Show what would be created. Writes nothing.
    poetry run python manage.py provision_pilot \\
        --company "Sierra Nut Co" --email maria@sierranut.test --farm "Home Ranch" \\
        --state CA --renewal-date 2027-01-01 --operator-email oscar+sierranut@trazo.io

    # Create it.
    poetry run python manage.py provision_pilot ... --commit

Both setup links are printed once. The operator opens their own link first, and sends the grower's
at the handoff, in their own words.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from subscriptions import pilot_operator

# Long enough for the operator to load the records before the handoff call, which is when the
# grower is meant to use the link. The invitation model's own default (7 days) is sized for a
# colleague invite, not for a setup that waits on a grower mid-harvest.
DEFAULT_INVITE_DAYS = 30


class Command(BaseCommand):
    help = "Provision a pilot company, farm, operator account and grower invitation (dry-run unless --commit)."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Company name")
        parser.add_argument("--email", required=True, help="Grower's login email (gets the invitation)")
        parser.add_argument("--farm", required=True, help="Farm (establishment) name")
        parser.add_argument("--state", default="CA", help="Two-letter state (default CA)")
        parser.add_argument("--country", default="US", help="Country code (default US)")
        parser.add_argument("--first-name", default="", help="Grower's first name (for the invitation)")
        parser.add_argument("--last-name", default="", help="Grower's last name (for the invitation)")
        parser.add_argument(
            "--operator-email",
            required=True,
            help=(
                "The setup account for THIS pilot (e.g. oscar+<farm>@trazo.io), so the records it "
                "types are attributed to it, not to the grower. Created if it does not exist; "
                "refused if it already belongs to any other company."
            ),
        )
        parser.add_argument(
            "--operator-first-name",
            default=pilot_operator.DEFAULT_FIRST_NAME,
            help=f"First name for a NEW operator account (default {pilot_operator.DEFAULT_FIRST_NAME}).",
        )
        parser.add_argument(
            "--operator-last-name",
            default=pilot_operator.DEFAULT_LAST_NAME,
            help=(
                f"Last name for a NEW operator account (default {pilot_operator.DEFAULT_LAST_NAME}); "
                f"'{pilot_operator.SETUP_SUFFIX}' is appended."
            ),
        )
        parser.add_argument(
            "--invite-days",
            type=int,
            default=DEFAULT_INVITE_DAYS,
            help=f"Days the grower's and the operator's setup links stay valid (default {DEFAULT_INVITE_DAYS}).",
        )
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
        from subscriptions.models import Plan, Subscription
        from users.models import User, WorksIn
        from users.models_invitation import CompanyInvitation

        try:
            pilot_plan = Plan.objects.get(slug="pilot")
        except Plan.DoesNotExist:
            raise CommandError(
                "No `pilot` plan exists. Run `manage.py migrate subscriptions` (migration 0008 "
                "creates it) or `manage.py create_plans`, then retry."
            )

        comp_ends = self._parse_renewal_date(options["renewal_date"])
        if options["invite_days"] < 1:
            raise CommandError("--invite-days must be at least 1.")

        email = options["email"].strip().lower()
        operator_email = options["operator_email"].strip().lower()
        if email == operator_email:
            raise CommandError(
                "--email and --operator-email are the same account. The operator needs their own "
                "login, or every record they type is attributed to the grower."
            )

        # The company this run would reuse (get_or_create by name): a re-run finds both accounts
        # already in it, which is not "another company".
        existing_company = Company.objects.filter(name=options["company"]).first()

        operator = User.objects.filter(email__iexact=operator_email).first()
        if operator is not None:
            problems = pilot_operator.existing_operator_problems(operator)
            if problems:
                raise CommandError(
                    f"--operator-email {operator_email} has an account that cannot be the operator: "
                    + "; ".join(problems)
                    + f". Use a dedicated address such as {pilot_operator.suggested_email(options['company'])}."
                )
            pilot_operator.refuse_other_companies(operator, existing_company, options["company"])
        operator_needs_link = operator is None or pilot_operator.needs_setup_link(operator)
        operator_name = (
            f"{options['operator_first_name'].strip()} "
            f"{pilot_operator.operator_last_name(options['operator_last_name'])}"
        ).strip()

        existing_grower = User.objects.filter(email__iexact=email).first()
        if existing_grower is not None:
            # An existing account skips the invitation, and with it the two login gates that
            # `signup_with_invitation` sets. Refuse it here rather than add it and print PASS:
            # `user_type` defaults to CONSUMER, so a consumer sign-up on the same email would
            # become a company admin who gets "Access denied" at first login (back#82 review).
            # Refuse, never fix: silently turning someone's account into a producer one, or
            # verifying an email nobody verified, is not this command's call.
            problems = self._login_gate_problems(existing_grower)
            if problems:
                raise CommandError(
                    f"{email} already has an account that cannot sign in to the app: "
                    + "; ".join(problems)
                    + ". Sort the account out first (or use a different email for the grower), then re-run."
                )
            pilot_operator.refuse_other_companies(existing_grower, existing_company, options["company"], role="--email")

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
        if operator is None:
            self.stdout.write(
                f"  Operator    : {operator_email}  [NEW ACCOUNT '{operator_name}', no password until its setup "
                "link is opened; belongs to this pilot only]"
            )
        elif operator_needs_link:
            self.stdout.write(f"  Operator    : {operator.email}  [existing account waiting on setup; link renewed]")
        else:
            self.stdout.write(f"  Operator    : {operator.email}  [existing account, belongs to no other company]")
        if existing_grower:
            self.stdout.write(f"  Grower      : {email}  [EXISTING ACCOUNT, added directly, no invitation]")
        else:
            self.stdout.write(
                f"  Grower      : {email}  [invitation link, valid {options['invite_days']} days; "
                "they set their own password and accept the Terms]"
            )
        self.stdout.write(f"  Limits      : {limits}  (identical to Compliance — conversion loses nothing)")
        self.stdout.write(f"  Comp ends   : {comp_ends:%d %b %Y}  — their certifier renewal deadline")

        if not options["commit"]:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("DRY RUN — nothing written. Re-run with --commit."))
            return

        invitation = None
        setup_token = setup_link = None
        with transaction.atomic():
            company, _ = Company.objects.get_or_create(name=options["company"])

            if operator is None:
                operator = pilot_operator.create_operator_account(
                    operator_email, options["operator_first_name"], options["operator_last_name"]
                )
            else:
                # Re-read under a lock so a membership added while this ran is still refused.
                operator = User.objects.select_for_update().get(pk=operator.pk)
                pilot_operator.refuse_other_companies(operator, company, options["company"])

            # Replace any prior subscription: a company on Starter/trialing is exactly the state
            # this command exists to prevent, and leaving it would re-arm the 14-day fuse.
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

            membership, _ = WorksIn.objects.get_or_create(
                user=operator, company=company, defaults={"role": WorksIn.COMPANY_ADMIN}
            )
            pilot_operator.mark_setup_operator(membership)
            membership.establishments_in_charge.add(farm)
            if operator_needs_link:
                setup_token, setup_link = pilot_operator.issue_setup_link(operator, options["invite_days"])

            if existing_grower:
                WorksIn.objects.get_or_create(
                    user=existing_grower, company=company, defaults={"role": WorksIn.COMPANY_ADMIN}
                )
            else:
                invitation = self._invite(CompanyInvitation, company, farm, email, operator, options)

        company.refresh_from_db()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Pilot provisioned."))
        self.stdout.write(f"  company id  : {company.id}")
        self.stdout.write(f"  farm id     : {farm.id}")
        self.stdout.write(f"  plan        : {company.subscription_plan.slug}")
        self.stdout.write(f"  comp ends   : {comp_ends:%d %b %Y}")
        if setup_link is not None:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"  OPERATOR SETUP LINK: {setup_link}"))
            self.stdout.write(
                f"  Valid until {setup_token.expires_at:%d %b %Y}. Open it yourself: it sets the password for "
                f"{operator.email}. Nothing was emailed."
            )
        if invitation is not None:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING(f"  GROWER SETUP LINK: {self._setup_link(invitation)}"))
            self.stdout.write(
                f"  Valid until {invitation.expires_at:%d %b %Y}. Send it at the handoff, in your own words. "
                "The grower picks a password and accepts the Terms there."
            )
        else:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"  {email} already had an account and was added directly. Their Terms record is "
                    "whatever their own sign-up captured; check `terms_accepted_at`."
                )
            )
        self.stdout.write("")
        self.stdout.write(
            f"  Next: {'open the operator setup link, then ' if setup_link else ''}sign in as {operator.email} "
            f"(it opens {company.name}, its only company) and enter the records there. "
            f"`manage.py import_parcels --farm {farm.id} --from-cogpro <dir>` for a COG Pro farm."
        )

        # Prove the setup can actually do the things a pilot needs, rather than assuming.
        self._verify(company, farm, operator, existing_grower, invitation, setup_token)

    def _invite(self, CompanyInvitation, company, farm, email, operator, options):
        """One pending invitation per grower and company: re-running refreshes it, never duplicates.

        `(email, company, status)` is unique, so a second pending row would raise. A re-run is the
        normal case (the first link expired, or the operator re-ran after a typo), so it renews the
        existing one instead.
        """
        expires_at = timezone.now() + timedelta(days=options["invite_days"])
        name = " ".join(p for p in (options["first_name"], options["last_name"]) if p) or None
        invitation = CompanyInvitation.objects.filter(
            email__iexact=email, company=company, status=CompanyInvitation.STATUS_PENDING
        ).first()
        if invitation is None:
            invitation = CompanyInvitation(
                email=email,
                company=company,
                role=CompanyInvitation.COMPANY_ADMIN,
                inviter=operator,
                invitee_name=name,
                expires_at=expires_at,
            )
        else:
            invitation.expires_at = expires_at
            invitation.invitee_name = name or invitation.invitee_name
        invitation.save()
        invitation.establishments.add(farm)
        return invitation

    @staticmethod
    def _setup_link(invitation):
        return f"{settings.BASE_APP_URL.rstrip('/')}/invitation/{invitation.invitation_code}/setup"

    @staticmethod
    def _login_gate_problems(user):
        """What stops this account at the app's login: the gates the old temp-password flow forced."""
        return pilot_operator.login_gate_problems(user)

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

    def _verify(self, company, farm, operator, existing_grower, invitation, setup_token):
        """Assert the provisioned setup is actually usable. Cheap, and the whole point."""
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

        if invitation is not None:
            grower_checks = [("grower setup link can be accepted", invitation.can_be_accepted())]
        else:
            # Membership alone is vacuous here (this command just created it); the login gates
            # are what decide whether the grower can actually get in.
            grower_checks = [
                (
                    "existing grower belongs to exactly one company (this one)",
                    list(existing_grower.companies.values_list("pk", flat=True).distinct()) == [company.pk],
                ),
                (
                    "existing grower can sign in (active, verified, producer)",
                    not self._login_gate_problems(existing_grower),
                ),
            ]

        checks = [
            *pilot_operator.operator_checks(operator, company, setup_token),
            *grower_checks,
            ("subscription resolves", company.subscription_plan is not None),
            ("can create a parcel", company.can_create_parcel(farm)),
            ("can create a production", company.can_create_production()),
            # NOT "can create a farm". Pilot mirrors Compliance at 1 farm, and this command has
            # just created it, so that check is expected to be False and asserting it would fail
            # every run. What matters is that converting costs the grower nothing:
            ("entitlements match Compliance (conversion loses nothing)", matches_compliance),
        ]
        pilot_operator.print_checks(self.stdout, checks, "Provisioning completed but the setup is not usable")
