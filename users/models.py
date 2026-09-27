from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from company.models import Company, Establishment

from .constants import CONSUMER, TERMS_VERSION, USER_TYPE_CHOICES
from .managers import UserManager


class User(AbstractUser):
    username = None  # remove username field, we will use email as unique identifier
    email = models.EmailField(unique=True, null=True, db_index=True)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    phone = models.CharField(max_length=255, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    company_verified = models.BooleanField(default=False, help_text="User was invited via company invitation code")
    companies = models.ManyToManyField(
        Company,
        related_name="company_users",
        through="WorksIn",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    user_type = models.PositiveSmallIntegerField(choices=USER_TYPE_CHOICES, default=CONSUMER)
    image = models.ImageField(upload_to="user_images/", blank=True, null=True)

    # Social authentication fields
    social_auth_provider = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        choices=[
            ("google", "Google"),
            ("facebook", "Facebook"),
            ("apple", "Apple"),
        ],
    )
    social_auth_id = models.CharField(max_length=255, blank=True, null=True)

    # Evidence of clickwrap acceptance. The sign-up checkbox was enforced only in the browser
    # and never sent, so until 2026-09-27 nothing on the server showed who agreed to which
    # Terms. Null means not recorded: every account created before then, and any sign-up
    # whose client did not send `accept_terms`.
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.CharField(max_length=20, blank=True, default="")

    REQUIRED_FIELDS = []
    USERNAME_FIELD = "email"

    objects = UserManager()

    def __str__(self):
        return self.get_full_name()

    def record_terms_acceptance(self, accepted):
        """Stamp the current Terms version when the client sent `accept_terms` as true.

        Takes the raw request value (JSON true or a form string). Never overwrites an earlier
        acceptance: the first one on record is the evidence.
        """
        if str(accepted).lower() != "true" or self.terms_accepted_at:
            return
        self.terms_accepted_at = timezone.now()
        self.terms_version = TERMS_VERSION
        self.save(update_fields=["terms_accepted_at", "terms_version"])

    def get_full_name(self):
        return self.first_name + " " + self.last_name

    def get_active_company(self):
        """The company this user is currently working in.

        THE SECOND LOCKOUT PATH (fixed 2026-08-22). This filtered on
        `subscription__status__in=["active", "trialing"]`, the same two-status list that used to
        gate `Company.subscription_plan` — so the moment a card was declined the company stopped
        existing as far as this method was concerned, and it returned None. That is worse than
        losing the plan: `get_active_company()` is the fallback that resolves the company for
        photo and document uploads, voice recording, support tickets and three creation
        permissions, so a single failed charge left a still-contracted customer with no company
        at all. Fixing `subscription_plan` alone would have left this one live.

        Companies are ordered so the answer is DETERMINISTIC and so it prefers the one that is
        being paid for: a user working in a paying company and a free one must not get whichever
        row Postgres returns from the heap. That defect has already been measured once on the
        billing dashboard, where a farm's plan came from one company and its usage counts from
        another.

        Falls back to any company the user works in rather than None. A company whose
        subscription has lapsed now resolves to Starter and is fully usable, and one with no
        subscription row at all still fails closed at the plan gate — which is the right place
        for that decision, and produces an error a farmer can act on instead of the app behaving
        as though they belong to nobody.
        """
        from django.db.models import Case, IntegerField, Value, When

        from company.models import PAID_PLAN_STATUSES

        return (
            self.companies.annotate(
                _billing_rank=Case(
                    When(subscription__status__in=PAID_PLAN_STATUSES, then=Value(0)),
                    When(subscription__isnull=False, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            )
            .order_by("_billing_rank", "id")
            .first()
        )

    def get_trial_company(self):
        return self.companies.filter(subscription__status="trialing").first()


class WorksIn(models.Model):
    COMPANY_ADMIN = "CA"
    FARM_MANAGER = "FM"
    VIEWER = "VW"

    USER_ROLES = [
        (COMPANY_ADMIN, _("Company Admin")),
        (FARM_MANAGER, _("Farm Manager")),
        (VIEWER, _("Viewer")),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="company_workers")
    role = models.CharField(choices=USER_ROLES, max_length=5)
    establishments_in_charge = models.ManyToManyField(Establishment, related_name="workers", blank=True, null=True)
    role_group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)


class VerificationCode(models.Model):
    """Single-use email-verification code with a bounded lifetime.

    ⛔ `created_at` was written on every row and read by NOTHING, so a code stayed valid
    forever. A code that never expires is a permanent bearer credential sitting in a mailbox:
    it survives the mailbox being resold, a shared laptop, or a forwarded signup email, and
    the address it proves control of is the one the account is recovered through. The sibling
    `PasswordResetToken` below has carried `expires_at` + `is_expired()` since it was written,
    so the pattern was already here — verification just never adopted it.

    The lifetime is computed from `created_at` rather than stored, deliberately: there is no
    stored value to backfill, and the column that was dead is now the load-bearing one.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="verification_code")
    code = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "code")

    def __str__(self):
        return f"{self.user.email} - {self.code}"

    @property
    def expires_at(self):
        """When this code stops being accepted.

        Named to match `PasswordResetToken.expires_at` so both credentials read the same way
        at a call site, even though this one is derived and that one is stored.
        """
        return self.created_at + timedelta(minutes=settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES)

    def is_expired(self):
        """Check if code has expired.

        An unsaved row has no `created_at` yet; treat it as fresh rather than raising, so a
        caller that builds a code and checks it in the same breath does not blow up.
        """
        if self.created_at is None:
            return False
        return timezone.now() > self.expires_at


class PasswordResetToken(models.Model):
    """
    Secure password reset token with 15-minute expiration
    Following 2025 security best practices
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    token = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["token"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"Password reset for {self.user.email} - {self.token[:8]}..."

    def is_expired(self):
        """Check if token has expired"""
        return timezone.now() > self.expires_at

    def is_used(self):
        """Check if token has been used"""
        return self.used_at is not None

    def is_valid(self):
        """Check if token is valid (not expired and not used)"""
        return not self.is_expired() and not self.is_used()

    def mark_as_used(self):
        """Mark token as used"""
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def cleanup_expired_tokens(cls):
        """Remove expired tokens - call this periodically"""
        expired_tokens = cls.objects.filter(expires_at__lt=timezone.now())
        count = expired_tokens.count()
        expired_tokens.delete()
        return count


# Import invitation model
