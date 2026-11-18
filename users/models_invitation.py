import secrets
import string
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from company.models import Company, Establishment

User = get_user_model()


class SoleAdminTransferError(ValueError):
    """Accepting would leave a company with farms and no Company Admin."""

    def __init__(self, companies):
        self.companies = list(companies)
        names = ", ".join(self.companies)
        super().__init__(
            f"You are the only Company Admin of {names}. Accepting this invitation moves you out of it, and its "
            "records would be left with no one who can manage them. Make another member Company Admin there, "
            "or close that company, then accept this invitation."
        )


class CompanyInvitation(models.Model):
    """
    Model to manage company invitations for users
    """

    COMPANY_ADMIN = "CA"
    FARM_MANAGER = "FM"
    VIEWER = "VW"

    USER_ROLES = [
        (COMPANY_ADMIN, _("Company Admin")),
        (FARM_MANAGER, _("Farm Manager")),
        (VIEWER, _("Viewer")),
    ]

    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DECLINED = "declined"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_ACCEPTED, _("Accepted")),
        (STATUS_DECLINED, _("Declined")),
        (STATUS_EXPIRED, _("Expired")),
    ]

    # Invitation details
    email = models.EmailField(help_text="Email address of the invitee")
    invitee_name = models.CharField(max_length=100, blank=True, null=True, help_text="Name of the person being invited")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="invitations")
    role = models.CharField(choices=USER_ROLES, max_length=5, help_text="Role to assign to the invited user")
    establishments = models.ManyToManyField(
        Establishment, blank=True, help_text="Establishments the invited user will work in"
    )

    # Invitation metadata
    inviter = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_invitations")
    invitation_code = models.CharField(max_length=32, unique=True, help_text="Unique invitation code")
    invitation_message = models.TextField(blank=True, null=True, help_text="Optional message from the inviter")
    status = models.CharField(choices=STATUS_CHOICES, max_length=20, default=STATUS_PENDING)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(help_text="When the invitation expires")
    accepted_at = models.DateTimeField(null=True, blank=True)

    # User who accepted (in case email doesn't match exactly)
    accepted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="accepted_invitations"
    )

    class Meta:
        unique_together = [["email", "company", "status"]]  # Prevent duplicate pending invitations
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invitation for {self.email} to join {self.company.name}"

    def save(self, *args, **kwargs):
        # Generate invitation code if not provided
        if not self.invitation_code:
            self.invitation_code = self.generate_invitation_code()

        # Set expiration date if not provided (7 days from now)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)

        super().save(*args, **kwargs)

    def generate_invitation_code(self):
        """Generate a unique invitation code"""
        while True:
            code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(16))
            if not CompanyInvitation.objects.filter(invitation_code=code).exists():
                return code

    def is_expired(self):
        """Check if invitation has expired"""
        return timezone.now() > self.expires_at

    def can_be_accepted(self):
        """Check if invitation can be accepted"""
        return self.status == self.STATUS_PENDING and not self.is_expired()

    def transfer_effect(self, user) -> dict:
        """What accepting would do to the user's other memberships (overall review 2026-11, OV-SEC-C11).

        Accepting moves the user out of every other company (one company per user). `leaves` names those
        companies; `sole_admin_of` names the ones where the user is the only Company Admin and the company
        still holds a farm, which accepting would leave with records and no one who can manage them.
        A company with no farm is not counted: nothing is stranded there."""
        from company.models import Establishment
        from users.models import WorksIn

        others = list(WorksIn.objects.filter(user=user).exclude(company=self.company).select_related("company"))
        sole = []
        for membership in others:
            if membership.role != WorksIn.COMPANY_ADMIN:
                continue
            another_admin = (
                WorksIn.objects.filter(company=membership.company, role=WorksIn.COMPANY_ADMIN)
                .exclude(user=user)
                .exists()
            )
            if not another_admin and Establishment.objects.filter(company=membership.company).exists():
                sole.append(membership.company.name)
        return {"leaves": [m.company.name for m in others], "sole_admin_of": sole}

    def accept(self, user):
        """Accept the invitation and add user to company (handles company transfers)"""
        if not self.can_be_accepted():
            raise ValueError("Invitation cannot be accepted")

        from users.models import WorksIn

        # A sole Company Admin of a company with farms cannot transfer out of it by accepting: the company
        # would keep its records with nobody who can manage them (OV-SEC-C11; reproduced 2026-11-10, a
        # company left with 0 members). They make another member Company Admin, or close it, first.
        effect = self.transfer_effect(user)
        if effect["sole_admin_of"]:
            raise SoleAdminTransferError(effect["sole_admin_of"])

        # Handle company transfer: remove user from any existing companies
        existing_memberships = WorksIn.objects.filter(user=user).exclude(company=self.company)
        if existing_memberships.exists():
            # Log company transfer for audit trail
            import logging

            logger = logging.getLogger(__name__)
            old_companies = [membership.company.name for membership in existing_memberships]
            logger.info(
                f"Company transfer: User {user.email} moving from {', '.join(old_companies)} to {self.company.name}"
            )

            # Remove existing memberships (company transfer)
            existing_memberships.delete()

        # Create new WorksIn relationship
        works_in, created = WorksIn.objects.get_or_create(user=user, company=self.company, defaults={"role": self.role})

        # If WorksIn already existed, update the role
        if not created and works_in.role != self.role:
            works_in.role = self.role
            works_in.save()

        # Assign establishments to the user
        if self.establishments.exists():
            works_in.establishments_in_charge.set(self.establishments.all())

        # Update invitation status
        self.status = self.STATUS_ACCEPTED
        self.accepted_at = timezone.now()
        self.accepted_by = user
        self.save()

        return works_in

    def decline(self):
        """Decline the invitation"""
        if self.status != self.STATUS_PENDING:
            raise ValueError("Only pending invitations can be declined")

        self.status = self.STATUS_DECLINED
        self.save()

    def get_invitation_link(self):
        """Generate the invitation acceptance link"""
        from django.urls import reverse

        return reverse("accept_invitation", kwargs={"invitation_code": self.invitation_code})

    def is_company_transfer(self):
        """Check if this invitation involves transferring an existing user to a new company"""
        try:
            from users.models import WorksIn

            User = get_user_model()

            existing_user = User.objects.filter(email=self.email).first()
            if existing_user:
                # Check if user has membership in another company
                other_membership = WorksIn.objects.filter(user=existing_user).exclude(company=self.company).exists()
                return other_membership
            return False
        except Exception:
            return False

    @classmethod
    def expire_old_invitations(cls):
        """Mark expired invitations as expired"""
        expired_invitations = cls.objects.filter(status=cls.STATUS_PENDING, expires_at__lt=timezone.now())
        expired_invitations.update(status=cls.STATUS_EXPIRED)
        return expired_invitations.count()
