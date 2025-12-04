import logging

from django.conf import settings
from django.contrib.auth.models import update_last_login
from django.core.exceptions import ObjectDoesNotExist

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.settings import api_settings

from .models import User, WorksIn

logger = logging.getLogger(__name__)


class WorksInSerializer(serializers.ModelSerializer):
    """
    Serializer for WorksIn.
    """

    id = serializers.ReadOnlyField(source="company.id")
    user = serializers.SerializerMethodField()
    establishments_in_charge = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()

    class Meta:
        model = WorksIn
        fields = (
            "id",
            "user",
            "role",
            "establishments_in_charge",
        )

    def get_picture(self, obj):
        return obj.company.picture.url if obj.company.picture else None

    def get_establishments_in_charge(self, obj):
        from company.serializers import BasicEstablishmentSerializer

        return BasicEstablishmentSerializer(obj.establishments_in_charge.all(), many=True).data

    def get_user(self, obj):
        return obj.user.get_full_name()

    def get_role(self, obj):
        return obj.get_role_display()


class BasicUserSerializer(serializers.ModelSerializer):
    """
    Serializer for User.
    """

    companies = WorksInSerializer(source="worksin_set", many=True)
    full_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone",
            "full_name",
            "is_superuser",
            "companies",
            "first_name",
            "last_name",
            "user_type",
            "image",
        ]
        read_only_field = [
            "is_active",
        ]

    def get_full_name(self, user):
        return user.get_full_name()


class MeSerializer(BasicUserSerializer):
    """
    Serializer for User to get their profile.
    """

    class Meta:
        model = User
        fields = BasicUserSerializer.Meta.fields + ["username", "user_type"]
        read_only_fields = ["username"]


class LoginSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)

        refresh = self.get_token(self.user)

        data["user"] = BasicUserSerializer(self.user).data
        data["refresh"] = str(refresh)
        data["access"] = str(refresh.access_token)
        data["user_type"] = self.user.user_type

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)

        return data


class RegisterSerializer(BasicUserSerializer):
    password = serializers.CharField(max_length=128, min_length=8, write_only=True, required=True)
    email = serializers.EmailField(required=True, write_only=True, max_length=128)
    first_name = serializers.CharField(required=True, write_only=True, max_length=128)
    last_name = serializers.CharField(required=True, write_only=True, max_length=128)
    user_type = serializers.CharField(required=True, write_only=True, max_length=128)
    company_code = serializers.CharField(required=False, write_only=True, max_length=50, allow_blank=True)

    def validate_company_code(self, value):
        """Validate company code exists with enhanced security"""
        if value:  # Only validate if code is provided
            import logging

            from django.core.cache import cache

            from company.models import Company

            logger = logging.getLogger(__name__)

            # Normalize the code (uppercase, strip whitespace)
            value = value.upper().strip()

            # Basic format validation (6-8 characters, alphanumeric)
            if not value.isalnum() or len(value) < 6 or len(value) > 8:
                logger.warning(f"Invalid company code format attempted: {value}")
                raise serializers.ValidationError("Company code must be 6-8 alphanumeric characters")

            # Rate limiting for code validation attempts
            request = self.context.get("request")
            if request:
                client_ip = request.META.get("HTTP_X_FORWARDED_FOR", request.META.get("REMOTE_ADDR", ""))
                rate_limit_key = f"company_code_attempts:{client_ip}"
                attempts = cache.get(rate_limit_key, 0)

                if attempts >= 10:  # Max 10 attempts per hour per IP
                    logger.warning(f"Rate limit exceeded for company code validation from IP: {client_ip}")
                    raise serializers.ValidationError("Too many validation attempts. Please try again later.")

                # Increment attempt counter
                cache.set(rate_limit_key, attempts + 1, timeout=3600)  # 1 hour timeout

            # Check if company exists
            try:
                company = Company.objects.filter(invitation_code=value).first()
                if not company:
                    logger.warning(
                        f"Invalid company code attempted: {value} from IP: {client_ip if request else 'Unknown'}"
                    )
                    raise serializers.ValidationError("Invalid company code")

                # Check if company is active (additional security)
                if not getattr(company, "is_active", True):
                    logger.warning(f"Inactive company code attempted: {value} for company: {company.name}")
                    raise serializers.ValidationError("Company code is no longer valid")

                logger.info(f"Valid company code used: {value} for company: {company.name}")

            except Exception as e:
                if "Invalid company code" in str(e) or "Company code is no longer valid" in str(e):
                    raise  # Re-raise validation errors
                else:
                    logger.error(f"Unexpected error during company code validation: {str(e)}")
                    raise serializers.ValidationError("Unable to validate company code. Please try again.")

        return value

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "password",
            "is_active",
            "user_type",
            "company_code",
        ]

    def validate_email(self, value):
        """
        Validate email uniqueness - critical security validation
        Following 2025 security best practices
        """
        if User.objects.filter(email=value.lower()).exists():
            raise serializers.ValidationError("A user with this email address already exists. Please sign in instead.")
        return value.lower()

    def create(self, validated_data):
        from django.db import transaction

        # Extract company code before creating user
        company_code = validated_data.pop("company_code", None)

        # Convert user_type string to integer if needed
        user_type = validated_data.get("user_type")
        if isinstance(user_type, str):
            # Create a mapping from string values to integer values
            user_type_mapping = {"SUPERUSER": 1, "STAFF": 2, "CONSUMER": 3, "PRODUCER": 4, "CERTIFIER": 5}
            validated_data["user_type"] = user_type_mapping.get(
                user_type.upper(), 3
            )  # Default to CONSUMER if not found

        # 🚀 2025 Security Fix: Always create new user - email uniqueness validated above
        # No more dangerous account access for existing users
        with transaction.atomic():
            try:
                user = User.objects.create_user(**validated_data)

                # Handle company code joining after user creation
                if company_code:
                    self._join_company_with_code(user, company_code)
                    # 🚀 2025 Best Practice: Mark for company verification, but still require email verification
                    user.company_verified = True
                    user.save()
                    logger.info(
                        f"User {user.email} joined company via code {company_code}, awaiting email verification"
                    )
                else:
                    logger.info(f"New user {user.email} created, awaiting email verification")

            except Exception as e:
                logger.error(f"Error creating user {validated_data.get('email', 'unknown')}: {str(e)}")
                raise serializers.ValidationError(
                    "Unable to create account. Please try again or contact support if the problem persists."
                )

        return user

    def _join_company_with_code(self, user, company_code):
        """Join user to company using company invitation code"""
        from company.models import Company

        try:
            # Find company by invitation code
            company = Company.objects.filter(invitation_code=company_code).first()

            if not company:
                raise serializers.ValidationError({"company_code": "Invalid company code"})

            # Check if user already belongs to this company
            existing_membership = WorksIn.objects.filter(user=user, company=company).first()
            if existing_membership:
                logger.warning(f"User {user.email} already belongs to company {company.name}")
                return  # User already in company, nothing to do

            # Check if user belongs to another company (should we transfer?)
            other_membership = WorksIn.objects.filter(user=user).exclude(company=company).first()
            if other_membership:
                # For company code joins, we don't auto-transfer - require explicit invitation
                logger.warning(
                    f"User {user.email} attempted company code join but already belongs to {other_membership.company.name}"
                )
                raise serializers.ValidationError(
                    {
                        "company_code": f"You already belong to {other_membership.company.name}. Contact your admin for a company transfer invitation."
                    }
                )

            # Create WorksIn relationship with default role (Domain Worker)
            works_in = WorksIn.objects.create(
                user=user, company=company, role=WorksIn.DOMAIN_WORKER  # Default role for code-based joins
            )

            # 🚀 2025 Best Practice: Auto-assign Domain Workers to all company establishments
            # This ensures they can immediately access existing operations
            from company.models import Establishment

            company_establishments = Establishment.objects.filter(company=company)
            if company_establishments.exists():
                works_in.establishments_in_charge.set(company_establishments)
                logger.info(f"Auto-assigned {company_establishments.count()} establishments to {user.email}")
            else:
                logger.info(f"No establishments to assign for {user.email} in {company.name}")

            # Send combined welcome+verification email for company join
            # 🚀 2025 Best Practice: Single email with welcome + verification
            try:
                from urllib.parse import quote

                from .models import VerificationCode
                from .signals import generate_verification_code
                from .utils import send_company_welcome_verification_email

                # Generate verification code and link for company code users
                verification_code = generate_verification_code()
                VerificationCode.objects.create(user=user, code=verification_code)

                # Properly encode the email for URLs
                encoded_email = quote(user.email)

                # Generate verification link based on user type
                verification_link = ""
                from .constants import CONSUMER, PRODUCER

                user_type = int(user.user_type)
                if user_type == PRODUCER:
                    verification_link = (
                        f"{settings.BASE_APP_URL}auth/verifyemail?email={encoded_email}&code={verification_code}"
                    )
                elif user_type == CONSUMER:
                    verification_link = (
                        f"{settings.BASE_CONSUMER_URL}auth/verifyemail?email={encoded_email}&code={verification_code}"
                    )

                # Send single combined email
                send_company_welcome_verification_email(
                    user=user,
                    company=company,
                    role=works_in.role,
                    verification_code=verification_code,
                    verification_link=verification_link,
                )
                logger.info(f"Combined welcome+verification email sent to {user.email} for {company.name}")

            except Exception as email_error:
                # Log email error but don't fail user creation
                logger.warning(
                    f"Failed to send combined welcome+verification email to {user.email}: {str(email_error)}"
                )

        except serializers.ValidationError:
            # Re-raise validation errors to prevent user creation with invalid codes
            raise
        except Exception as e:
            # Log unexpected errors and prevent user creation
            logger.error(f"Failed to join user {user.email} to company with code {company_code}: {str(e)}")
            # Prevent user creation if company join fails to avoid orphaned accounts
            raise serializers.ValidationError(
                {"company_code": "Unable to join company. Please verify the code and try again."}
            )


class CompanyInvitationSerializer(serializers.ModelSerializer):
    """
    Serializer for CompanyInvitation
    """

    inviter_name = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    role_display = serializers.SerializerMethodField()
    is_expired = serializers.SerializerMethodField()
    can_be_accepted = serializers.SerializerMethodField()
    accepted_by_name = serializers.SerializerMethodField()

    class Meta:
        from .models_invitation import CompanyInvitation

        model = CompanyInvitation
        fields = [
            "id",
            "email",
            "invitee_name",
            "company_name",
            "role",
            "role_display",
            "inviter_name",
            "invitation_message",
            "status",
            "created_at",
            "updated_at",
            "expires_at",
            "accepted_at",
            "is_expired",
            "can_be_accepted",
            "accepted_by_name",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "accepted_at", "invitation_code"]

    def get_inviter_name(self, obj):
        return obj.inviter.get_full_name() if obj.inviter else None

    def get_company_name(self, obj):
        return obj.company.name if obj.company else None

    def get_role_display(self, obj):
        return obj.get_role_display()

    def get_is_expired(self, obj):
        return obj.is_expired()

    def get_can_be_accepted(self, obj):
        return obj.can_be_accepted()

    def get_accepted_by_name(self, obj):
        return obj.accepted_by.get_full_name() if obj.accepted_by else None


class InvitationCreateSerializer(serializers.Serializer):
    """
    Serializer for creating invitations
    """

    email = serializers.EmailField()
    invitee_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    role = serializers.ChoiceField(
        choices=[("CA", "Company Admin"), ("DS", "Domain Supervisor"), ("DW", "Domain Worker"), ("DE", "Dealer")],
        default="DW",
    )
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_email(self, value):
        """
        Validate that the email is properly formatted
        """
        return value.lower().strip()
