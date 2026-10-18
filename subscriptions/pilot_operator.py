"""The pilot operator account: one company per account, created and set up from the console.

Shared by `provision_pilot`, `add_pilot_operator` and `remove_pilot_operator`.

THE ONE-COMPANY RULE. The app loads `user.companies[0]` after sign-in (trazo-app
`src/store/api/authApi.js`) and has no company switcher, and `CompanyInvitation.accept()` treats
acceptance as a transfer. An account that belongs to two companies can therefore never open one of
them. Until 2026-10-17 `provision_pilot` added the operator's own account (oscar@trazo.io) to every
pilot as a second membership, and a pilot rehearsal on production found the operator could not open
the pilot at all. So every pilot gets its own operator account (oscar+<farm>@trazo.io), and that
account belongs to that pilot and nothing else.

THE SETUP LINK. A new operator account is created with no usable password and gets a one-off link
to `/auth/reset-password`, backed by a `PasswordResetToken` that lives as long as the grower's
invitation. Not the invitation flow: the grower's invitation needs an inviter, which is the
operator, so the operator account must exist before any invitation does, and
`signup_with_invitation` refuses an email that already has an account. Opening the link is what
sets the password and the `is_verified` gate (`confirm_password_reset`). No password is printed or
emailed, and creating the account sends no mail at all.
"""

import re
from datetime import timedelta
from urllib.parse import quote

from django.apps import apps
from django.conf import settings
from django.core.management.base import CommandError
from django.db.models import Q
from django.utils import timezone

SETUP_SUFFIX = "(Trazo setup)"
DEFAULT_FIRST_NAME = "Oscar"
DEFAULT_LAST_NAME = "Munoz"
SETUP_LINK_USER_AGENT = "pilot operator setup link (management command)"

ONE_COMPANY_RULE = (
    "An account opens exactly one company: the app loads the first company an account belongs to "
    "and has no company switcher, so an account in two companies can never reach one of them."
)

# Every lookup from a model to the Company that owns it. A model may match several (a document
# hangs off a farm, a parcel or a production); all that resolve are OR-ed, so a row that fills only
# one of its nullable links is still found.
COMPANY_PATHS = (
    "company",
    "establishment__company",
    "parcel__establishment__company",
    "history__parcel__establishment__company",
    "production__parcel__establishment__company",
    "osp__establishment__company",
    "note__company",
    # Carbon audit rows hang off a carbon entry, which hangs off a farm or a production.
    "carbon_entry__establishment__company",
    "carbon_entry__production__parcel__establishment__company",
)

# User links that reach a company but do not mean the user wrote a record there. Everything else
# that reaches a company counts as authorship, so a new model is counted by default.
NOT_AUTHORSHIP = {
    ("users.WorksIn", "user"): "the membership being removed",
    ("users.CompanyInvitation", "inviter"): "provisioning metadata: the operator invites the grower",
    ("users.CompanyInvitation", "accepted_by"): "provisioning metadata",
    ("history.HistoryScan", "user"): "a shopper scanning the QR code",
    ("reviews.Review", "user"): "a shopper's review",
    ("carbon.MicroOffset", "user"): "a shopper's purchase",
    ("support.SupportTicket", "user"): "a support conversation, not a farm record",
    ("support.SupportTicket", "assigned_to"): "Trazo support staff",
}


def operator_last_name(last_name):
    """The last name an operator account carries, always marked as setup in the audit trail."""
    last = (last_name or "").strip()
    if last.endswith(SETUP_SUFFIX):
        return last
    return f"{last} {SETUP_SUFFIX}".strip()


def is_setup_operator(user):
    """True for a pilot operator account: the one Trazo types a grower's records in with.

    Such an account RECORDS. It is never the producer, the person responsible for the operation
    or the default signer (§ 205.201(a) makes the producer the author), so every place that
    names one of those skips it. The certifier handoff rehearsal of 2026-10-18 found the dossier
    attestation printing "Producer / Operator: Oscar Munoz (Trazo setup)".

    NOTE: the setup suffix is the only marker these accounts carry, and it is NOT on every one:
    `operator_last_name` is applied only when `create_operator_account` makes a NEW account. When
    `add_pilot_operator --email` or `provision_pilot` attach an account that already exists, its
    name is left as it was, and this returns False for it (review of back #176). A flag on the
    membership, set by both commands, is the fix; this keeps the check in one place until then.
    """
    if user is None:
        return False
    full_name = (user.get_full_name() or "") if hasattr(user, "get_full_name") else ""
    return full_name.strip().endswith(SETUP_SUFFIX)


def suggested_email(company_name):
    slug = re.sub(r"[^a-z0-9]", "", (company_name or "").lower())[:24] or "farm"
    return f"oscar+{slug}@trazo.io"


def other_companies(user, company=None):
    from company.models import Company

    queryset = Company.objects.filter(company_workers__user=user)
    if company is not None and company.pk is not None:
        queryset = queryset.exclude(pk=company.pk)
    return list(queryset.order_by("pk").distinct())


def refuse_other_companies(user, company, company_name, role="--operator-email"):
    """CommandError when `user` belongs to any company other than `company` (which may not exist yet)."""
    others = other_companies(user, company)
    if not others:
        return
    names = ", ".join(f"{c.name} (id {c.pk})" for c in others)
    raise CommandError(
        f"{role} {user.email} already belongs to {names}. {ONE_COMPANY_RULE} Use a dedicated address "
        f"for this pilot, such as {suggested_email(company_name)}; the command creates that account. "
        "Nothing written."
    )


def login_gate_problems(user):
    """What stops this account at the app's login (the gates `provision_pilot` has always checked)."""
    from users import constants

    problems = []
    if not user.is_active:
        problems.append("the account is deactivated")
    if not getattr(user, "is_verified", False):
        problems.append("the email is not verified")
    if user.user_type not in (constants.SUPERUSER, constants.PRODUCER):
        problems.append("it is not a producer account (the app login returns 'Access denied')")
    return problems


def needs_setup_link(user):
    """True for an operator account that has never set a password (one this module created)."""
    return user is not None and not user.has_usable_password()


def existing_operator_problems(user):
    """Why an existing account cannot be a pilot operator. Empty means it can.

    An account still waiting on its setup link is fine as long as it is a producer account: the
    link activates and verifies it. Any other account must already pass the login gates.
    """
    from users import constants

    if needs_setup_link(user):
        if user.user_type not in (constants.SUPERUSER, constants.PRODUCER):
            return ["it is not a producer account (the app login returns 'Access denied')"]
        return []
    return login_gate_problems(user)


def create_operator_account(email, first_name, last_name):
    """A producer account with no usable password, created without any sign-up mail."""
    from users.constants import PRODUCER
    from users.models import User
    from users.signals import SKIP_SIGNUP_MAIL_ATTR

    user = User(
        email=email.strip().lower(),
        first_name=(first_name or "").strip(),
        last_name=operator_last_name(last_name),
        user_type=PRODUCER,
        is_active=True,
        # Set by `confirm_password_reset` when the setup link is used. Until then the account has
        # no usable password, so nothing can sign in to it.
        is_verified=False,
    )
    user.set_unusable_password()
    setattr(user, SKIP_SIGNUP_MAIL_ATTR, True)
    user.save()
    return user


def issue_setup_link(user, days):
    """(token row, link). Earlier unused links for the account stop working."""
    from users.models import PasswordResetToken
    from users.utils import generate_password_reset_token

    now = timezone.now()
    PasswordResetToken.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
    token = PasswordResetToken.objects.create(
        user=user,
        token=generate_password_reset_token(),
        expires_at=now + timedelta(days=days),
        user_agent=SETUP_LINK_USER_AGENT,
    )
    link = (
        f"{settings.BASE_APP_URL.rstrip('/')}/auth/reset-password"
        f"?token={quote(token.token, safe='')}&email={quote(user.email, safe='')}"
    )
    return token, link


def company_paths(model):
    """Every lookup in COMPANY_PATHS that leads from `model` to Company."""
    from company.models import Company

    found = []
    for path in COMPANY_PATHS:
        current = model
        for part in path.split("__"):
            try:
                field = current._meta.get_field(part)
            except Exception:  # noqa: BLE001 - FieldDoesNotExist: this path does not apply
                current = None
                break
            if not field.concrete or getattr(field, "related_model", None) is None:
                current = None
                break
            current = field.related_model
        if current is Company:
            found.append(path)
    return found


def _in_company(model, company):
    paths = company_paths(model)
    if not paths:
        return None
    condition = Q()
    for path in paths:
        condition |= Q(**{path: company})
    return model.objects.filter(condition)


def authored_records(user, company):
    """{label: count} of rows in `company` that name `user` as their author. Empty means none.

    Two sources. Every concrete link to User on a model that reaches the company (minus
    NOT_AUTHORSHIP), and audit-log entries whose actor is the user, on objects of this company.
    Parcels have no author column and are not audit-logged, so a parcel the user created is
    invisible here unless a record on it names them.
    """
    from django.contrib.auth import get_user_model

    from auditlog.models import LogEntry

    from company.models import Company

    User = get_user_model()
    counts = {}
    for model in apps.get_models():
        if model._meta.abstract or model._meta.proxy:
            continue
        user_fields = [
            f.name
            for f in model._meta.get_fields()
            if (getattr(f, "many_to_one", False) or getattr(f, "one_to_one", False))
            and f.concrete
            and getattr(f, "related_model", None) is User
            and (model._meta.label, f.name) not in NOT_AUTHORSHIP
        ]
        if not user_fields or model is LogEntry:
            continue
        rows = _in_company(model, company)
        if rows is None:
            continue
        for name in user_fields:
            count = rows.filter(**{name: user}).distinct().count()
            if count:
                counts[f"{model._meta.label}.{name}"] = count

    entries = LogEntry.objects.filter(actor=user)
    for content_type_id in entries.values_list("content_type", flat=True).distinct():
        from django.contrib.contenttypes.models import ContentType

        model = ContentType.objects.get_for_id(content_type_id).model_class()
        if model is None:
            continue
        if model is Company:
            pks = [company.pk]
        else:
            rows = _in_company(model, company)
            if rows is None:
                continue
            pks = list(rows.values_list("pk", flat=True))
        if not pks:
            continue
        count = entries.filter(content_type_id=content_type_id, object_pk__in=[str(pk) for pk in pks]).count()
        if count:
            counts[f"audit log on {model._meta.label}"] = count
    return counts


def pilot_subscription_problem(company):
    """Why `company` is not a pilot. None when it is (its subscription row is on plan slug `pilot`)."""
    subscription = getattr(company, "subscription", None)
    if subscription is None:
        return f"company {company.pk} '{company.name}' has no subscription, so it is not a pilot"
    if subscription.plan.slug != "pilot":
        return f"company {company.pk} '{company.name}' is on plan '{subscription.plan.slug}', not 'pilot'"
    return None


def operator_checks(operator, company, setup_token):
    """(name, ok) rows for the post-provision checks every pilot command prints."""
    operator.refresh_from_db()
    memberships = list(operator.companies.values_list("pk", flat=True).distinct())
    checks = [
        ("operator belongs to exactly one company (this one)", memberships == [company.pk]),
        (
            "operator opens this company at sign-in (get_active_company)",
            getattr(operator.get_active_company(), "pk", None) == company.pk,
        ),
    ]
    if setup_token is not None:
        setup_token.refresh_from_db()
        checks.append(
            (
                "operator setup link can be accepted",
                setup_token.is_valid() and not existing_operator_problems(operator),
            )
        )
    else:
        checks.append(
            ("operator can sign in (active, verified, producer, has a password)", not login_gate_problems(operator))
        )
    return checks


def print_checks(stdout, checks, failure_message):
    stdout.write("")
    stdout.write("  Post-provision checks:")
    for name, ok in checks:
        stdout.write(f"    {'PASS' if ok else 'FAIL'}  {name}")
    failed = [name for name, ok in checks if not ok]
    if failed:
        raise CommandError(failure_message + ": " + ", ".join(failed))
