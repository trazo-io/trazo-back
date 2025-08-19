import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.urls import reverse

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from company.models import Company
from users.constants import PRODUCER
from users.models import WorksIn

from .models_invitation import CompanyInvitation
from .serializers import CompanyInvitationSerializer
from .utils import send_invitation_email, send_invited_user_welcome_email, send_welcome_email

logger = logging.getLogger(__name__)
User = get_user_model()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_invitation(request):
    """
    Create and send a company invitation
    """
    try:
        # Get user's company (must be Company Admin)
        user_company = request.user.companies.filter(
            company_workers__user=request.user, company_workers__role="CA"
        ).first()

        if not user_company:
            return Response(
                {"error": "You must be a Company Admin to send invitations"}, status=status.HTTP_403_FORBIDDEN
            )

        # Extract invitation data
        email = request.data.get("email")
        invitee_name = request.data.get("invitee_name", "")
        role = request.data.get("role", "DW")
        invitation_message = request.data.get("message", "")
        establishments = request.data.get("establishments", [])

        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate establishments belong to the company
        if establishments:
            from company.models import Establishment

            valid_establishments = Establishment.objects.filter(id__in=establishments, company=user_company)
            if len(valid_establishments) != len(establishments):
                return Response({"error": "Invalid establishments provided"}, status=status.HTTP_400_BAD_REQUEST)

        if not establishments:
            return Response({"error": "At least one establishment is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Check if user already exists and is part of this company
        existing_user = User.objects.filter(email=email).first()
        if existing_user:
            existing_membership = WorksIn.objects.filter(user=existing_user, company=user_company).first()
            if existing_membership:
                return Response(
                    {"error": "User is already a member of this company"}, status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if user has membership in another company
            other_membership = WorksIn.objects.filter(user=existing_user).exclude(company=user_company).first()
            if other_membership:
                # This will be a company transfer invitation
                logger.info(f"Creating company transfer invitation for {email} from {other_membership.company.name} to {user_company.name}")

        # Check for existing pending invitation
        existing_invitation = CompanyInvitation.objects.filter(
            email=email, company=user_company, status=CompanyInvitation.STATUS_PENDING
        ).first()

        if existing_invitation and not existing_invitation.is_expired():
            return Response(
                {"error": "A pending invitation already exists for this email"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Create invitation
        with transaction.atomic():
            invitation = CompanyInvitation.objects.create(
                email=email,
                invitee_name=invitee_name,
                company=user_company,
                role=role,
                inviter=request.user,
                invitation_message=invitation_message,
            )

            # Assign establishments to invitation
            if establishments:
                invitation.establishments.set(establishments)

            # Generate invitation link
            if settings.DEBUG:
                # Use local frontend URL for development
                invitation_link = f"{settings.BASE_APP_URL}invitation/{invitation.invitation_code}"
            elif hasattr(settings, "ENVIRONMENT") and settings.ENVIRONMENT == "staging":
                # Use staging frontend URL
                invitation_link = f"{settings.BASE_APP_URL}invitation/{invitation.invitation_code}"
            else:
                # Use production domain
                domain = Site.objects.get_current().domain
                invitation_link = f"https://{domain}/invitation/{invitation.invitation_code}"

            # Send invitation email
            email_sent = send_invitation_email(
                invitee_email=email,
                invitee_name=invitee_name,
                inviter=request.user,
                company=user_company,
                role=role,
                invitation_link=invitation_link,
                invitation_message=invitation_message,
            )

            if not email_sent:
                logger.warning(f"Failed to send invitation email to {email}")

            serializer = CompanyInvitationSerializer(invitation)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creating invitation: {str(e)}")
        return Response(
            {"error": "An error occurred while creating the invitation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_invitations(request):
    """
    List all invitations for the user's company
    """
    try:
        user_company = request.user.companies.filter(
            company_workers__user=request.user, company_workers__role="CA"
        ).first()

        if not user_company:
            return Response(
                {"error": "You must be a Company Admin to view invitations"}, status=status.HTTP_403_FORBIDDEN
            )

        invitations = CompanyInvitation.objects.filter(company=user_company)
        serializer = CompanyInvitationSerializer(invitations, many=True)
        return Response(serializer.data)

    except Exception as e:
        logger.error(f"Error listing invitations: {str(e)}")
        return Response(
            {"error": "An error occurred while retrieving invitations"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["GET"])
@permission_classes([AllowAny])
def get_invitation_details(request, invitation_code):
    """
    Get invitation details for the invitation acceptance page
    """
    try:
        invitation = get_object_or_404(CompanyInvitation, invitation_code=invitation_code)

        if not invitation.can_be_accepted():
            return Response(
                {"error": "This invitation has expired or cannot be accepted"}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "invitation_code": invitation.invitation_code,
                "company_name": invitation.company.name,
                "role": invitation.get_role_display(),
                "inviter_name": f"{invitation.inviter.first_name} {invitation.inviter.last_name}",
                "expires_at": invitation.expires_at,
                "invitation_message": invitation.invitation_message,
            }
        )

    except Exception as e:
        logger.error(f"Error getting invitation details: {str(e)}")
        return Response({"error": "Invitation not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(["POST"])
@permission_classes([AllowAny])
def accept_invitation(request, invitation_code):
    """
    Accept a company invitation (can be used by authenticated or unauthenticated users)
    Enhanced with rate limiting and security measures
    """
    # Rate limiting for invitation acceptance attempts
    from django.core.cache import cache
    
    client_ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
    rate_limit_key = f"invitation_accept_attempts:{client_ip}"
    attempts = cache.get(rate_limit_key, 0)
    
    if attempts >= 5:  # Max 5 attempts per hour per IP
        logger.warning(f"Rate limit exceeded for invitation acceptance from IP: {client_ip}")
        return Response(
            {"error": "Too many invitation attempts. Please try again later."}, 
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    
    # Increment attempt counter
    cache.set(rate_limit_key, attempts + 1, timeout=3600)  # 1 hour timeout
    
    try:
        invitation = get_object_or_404(CompanyInvitation, invitation_code=invitation_code)

        if not invitation.can_be_accepted():
            return Response(
                {"error": "This invitation has expired or cannot be accepted"}, status=status.HTTP_400_BAD_REQUEST
            )

        # If user is authenticated, accept invitation directly
        if request.user.is_authenticated:
            # Verify that the authenticated user's email matches the invitation email
            if request.user.email.lower() != invitation.email.lower():
                return Response(
                    {
                        "error": "This invitation is for a different email address. Please log in with the correct account or sign up with the invited email."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            with transaction.atomic():
                works_in = invitation.accept(request.user)

                # Get company subscription information
                from subscriptions.models import Subscription

                try:
                    company_subscription = Subscription.objects.get(company=invitation.company)
                    has_subscription = company_subscription.is_active()
                    subscription_data = {
                        "id": company_subscription.id,
                        "status": company_subscription.status,
                        "is_active": company_subscription.is_active(),
                        "plan_name": company_subscription.plan.name,
                    }
                except Subscription.DoesNotExist:
                    has_subscription = False
                    subscription_data = None

                serializer = CompanyInvitationSerializer(invitation)
                return Response(
                    {
                        "message": "Invitation accepted successfully",
                        "invitation": serializer.data,
                        "company": {
                            "id": invitation.company.id,
                            "name": invitation.company.name,
                            "has_subscription": has_subscription,
                            "subscription": subscription_data,
                        },
                        "role": invitation.get_role_display(),
                        "redirect_to": "/admin/dashboard" if has_subscription else "/admin/dashboard/pricing",
                    }
                )

        # If user is not authenticated, return info for frontend to handle signup redirect
        else:
            return Response(
                {
                    "message": "Please log in or sign up to accept this invitation",
                    "invitation_code": invitation_code,
                    "company_name": invitation.company.name,
                    "role": invitation.get_role_display(),
                    "login_url": "/login/",
                    "signup_url": "/signup/",
                    "requires_signup": True,
                },
                status=status.HTTP_200_OK,
            )

    except Exception as e:
        logger.error(f"Error accepting invitation: {str(e)}")
        return Response(
            {"error": "An error occurred while accepting the invitation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def decline_invitation(request, invitation_code):
    """
    Decline a company invitation
    """
    try:
        invitation = get_object_or_404(CompanyInvitation, invitation_code=invitation_code)

        if invitation.status != CompanyInvitation.STATUS_PENDING:
            return Response({"error": "This invitation cannot be declined"}, status=status.HTTP_400_BAD_REQUEST)

        invitation.decline()

        return Response({"message": "Invitation declined successfully"})

    except Exception as e:
        logger.error(f"Error declining invitation: {str(e)}")
        return Response(
            {"error": "An error occurred while declining the invitation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def resend_invitation(request, invitation_id):
    """
    Resend an invitation email
    """
    try:
        invitation = get_object_or_404(CompanyInvitation, id=invitation_id)

        # Check if user has permission to resend this invitation
        if invitation.inviter != request.user:
            user_company = request.user.companies.filter(
                company_workers__user=request.user, company_workers__role="CA"
            ).first()

            if not user_company or invitation.company != user_company:
                return Response(
                    {"error": "You do not have permission to resend this invitation"}, status=status.HTTP_403_FORBIDDEN
                )

        if invitation.status != CompanyInvitation.STATUS_PENDING:
            return Response({"error": "Only pending invitations can be resent"}, status=status.HTTP_400_BAD_REQUEST)

        # Generate invitation link
        if settings.DEBUG:
            # Use local frontend URL for development
            invitation_link = f"{settings.BASE_APP_URL}invitation/{invitation.invitation_code}"
        elif hasattr(settings, "ENVIRONMENT") and settings.ENVIRONMENT == "staging":
            # Use staging frontend URL
            invitation_link = f"{settings.BASE_APP_URL}invitation/{invitation.invitation_code}"
        else:
            # Use production domain
            domain = Site.objects.get_current().domain
            invitation_link = f"https://{domain}/invitation/{invitation.invitation_code}"

        # Send invitation email
        email_sent = send_invitation_email(
            invitee_email=invitation.email,
            invitee_name=invitation.invitee_name,
            inviter=invitation.inviter,
            company=invitation.company,
            role=invitation.role,
            invitation_link=invitation_link,
            invitation_message=invitation.invitation_message,
        )

        if email_sent:
            return Response({"message": "Invitation resent successfully"})
        else:
            return Response({"error": "Failed to send invitation email"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    except Exception as e:
        logger.error(f"Error resending invitation: {str(e)}")
        return Response(
            {"error": "An error occurred while resending the invitation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def cancel_invitation(request, invitation_id):
    """
    Cancel a pending invitation
    """
    try:
        invitation = get_object_or_404(CompanyInvitation, id=invitation_id)

        # Check if user has permission to cancel this invitation
        if invitation.inviter != request.user:
            user_company = request.user.companies.filter(
                company_workers__user=request.user, company_workers__role="CA"
            ).first()

            if not user_company or invitation.company != user_company:
                return Response(
                    {"error": "You do not have permission to cancel this invitation"}, status=status.HTTP_403_FORBIDDEN
                )

        if invitation.status != CompanyInvitation.STATUS_PENDING:
            return Response({"error": "Only pending invitations can be cancelled"}, status=status.HTTP_400_BAD_REQUEST)

        invitation.delete()

        return Response({"message": "Invitation cancelled successfully"})

    except Exception as e:
        logger.error(f"Error cancelling invitation: {str(e)}")
        return Response(
            {"error": "An error occurred while cancelling the invitation"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(["POST"])
@permission_classes([AllowAny])
def signup_with_invitation(request):
    """
    Create a new user account and accept invitation in one step
    """
    try:
        # Extract data
        first_name = request.data.get("first_name")
        last_name = request.data.get("last_name")
        password = request.data.get("password")
        invitation_code = request.data.get("invitation_code")

        # Validate required fields
        if not all([first_name, last_name, password, invitation_code]):
            return Response({"error": "All fields are required"}, status=status.HTTP_400_BAD_REQUEST)

        # Get invitation
        try:
            invitation = CompanyInvitation.objects.get(invitation_code=invitation_code)
        except CompanyInvitation.DoesNotExist:
            return Response({"error": "Invalid invitation code"}, status=status.HTTP_400_BAD_REQUEST)

        if not invitation.can_be_accepted():
            return Response(
                {"error": "This invitation has expired or cannot be accepted"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Check if user already exists with this email
        if User.objects.filter(email=invitation.email).exists():
            return Response({"error": "An account with this email already exists"}, status=status.HTTP_400_BAD_REQUEST)

        # Create user account
        with transaction.atomic():
            user = User.objects.create_user(
                email=invitation.email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                user_type=PRODUCER,  # All invited users are producers
                is_verified=True,  # Skip email verification for invited users
                is_active=True,
            )

            # Accept the invitation
            works_in = invitation.accept(user)

            # Send specialized welcome email for invited users
            try:
                send_invited_user_welcome_email(
                    user=user, company=invitation.company, inviter=invitation.inviter, role=invitation.role
                )
                logger.info(f"Invited user welcome email sent to {user.email}")
            except Exception as e:
                logger.warning(f"Failed to send welcome email to invited user {user.email}: {str(e)}")
                # Don't fail the entire process if email fails

            # Generate JWT tokens for automatic sign-in
            refresh = RefreshToken.for_user(user)
            access_token = refresh.access_token

            # Get company subscription information
            from subscriptions.models import Subscription

            try:
                company_subscription = Subscription.objects.get(company=invitation.company)
                has_subscription = company_subscription.is_active()
                subscription_data = {
                    "id": company_subscription.id,
                    "status": company_subscription.status,
                    "is_active": company_subscription.is_active(),
                    "plan_name": company_subscription.plan.name,
                }
            except Subscription.DoesNotExist:
                has_subscription = False
                subscription_data = None

            response = Response(
                {
                    "message": "Account created and invitation accepted successfully",
                    "access": str(access_token),
                    "refresh": str(refresh),
                    "user": {
                        "id": user.id,
                        "email": user.email,
                        "first_name": user.first_name,
                        "last_name": user.last_name,
                        "user_type": user.user_type,
                        "is_verified": user.is_verified,
                    },
                    "company": {
                        "id": invitation.company.id,
                        "name": invitation.company.name,
                        "has_subscription": has_subscription,
                        "subscription": subscription_data,
                    },
                    "role": works_in.role,
                    "redirect_to": "/admin/dashboard" if has_subscription else "/admin/dashboard/pricing",
                },
                status=status.HTTP_201_CREATED,
            )

            # Set secure HTTP-only cookies for automatic authentication
            cookie_options = {
                "secure": settings.SIMPLE_JWT["AUTH_COOKIE_SECURE"],
                "httponly": settings.SIMPLE_JWT["AUTH_COOKIE_HTTP_ONLY"],
                "samesite": settings.SIMPLE_JWT["AUTH_COOKIE_SAMESITE"],
            }

            # Only set domain in production, not in development (localhost)
            if not settings.DEBUG and hasattr(settings, "CSRF_COOKIE_DOMAIN") and settings.CSRF_COOKIE_DOMAIN:
                cookie_options["domain"] = settings.CSRF_COOKIE_DOMAIN

            # Set cookies with improved security
            response.set_cookie(
                key="access",
                value=str(access_token),
                max_age=settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds(),
                **cookie_options,
            )
            response.set_cookie(
                key="refresh",
                value=str(refresh),
                max_age=settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds(),
                **cookie_options,
            )

            return response

    except Exception as e:
        logger.error(f"Error in signup with invitation: {str(e)}")
        return Response(
            {"error": "An error occurred while creating your account"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def process_pending_invitation(user):
    """
    Process any pending invitation for a user after login/signup
    """
    try:
        # This would be called from login/signup views
        from django.contrib.sessions.models import Session

        # Implementation depends on how sessions are handled
        pass
    except Exception as e:
        logger.error(f"Error processing pending invitation: {str(e)}")
        return None
