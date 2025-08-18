from django.contrib.auth.models import AbstractUser, Group
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from company.models import Company, Establishment

from .constants import CONSUMER, USER_TYPE_CHOICES
from .managers import UserManager


class User(AbstractUser):
    username = None  # remove username field, we will use email as unique identifier
    email = models.EmailField(unique=True, null=True, db_index=True)
    is_active = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    phone = models.CharField(max_length=255, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
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

    REQUIRED_FIELDS = []
    USERNAME_FIELD = "email"

    objects = UserManager()

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return self.first_name + " " + self.last_name

    def get_active_company(self):
        # Check for active or trialing subscriptions
        return self.companies.filter(subscription__status__in=["active", "trialing"]).first()

    def get_trial_company(self):
        return self.companies.filter(subscription__status="trialing").first()


class WorksIn(models.Model):
    COMPANY_ADMIN = "CA"
    DOMAIN_SUPERVISOR = "DS"
    DOMAIN_WORKER = "DW"
    DEALER = "DE"

    USER_ROLES = [
        (COMPANY_ADMIN, _("Company Admin")),
        (DOMAIN_SUPERVISOR, _("Domain Supervisor")),
        (DOMAIN_WORKER, _("Domain Worker")),
        (DEALER, _("Dealer")),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="company_workers")
    role = models.CharField(choices=USER_ROLES, max_length=5)
    establishments_in_charge = models.ManyToManyField(Establishment, related_name="workers", blank=True, null=True)
    role_group = models.ForeignKey(Group, on_delete=models.CASCADE, null=True, blank=True)


class VerificationCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="verification_code")
    code = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "code")

    def __str__(self):
        return f"{self.user.email} - {self.code}"


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
from .models_invitation import CompanyInvitation
