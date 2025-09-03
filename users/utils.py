import logging
import secrets
import string

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_welcome_email(user):
    """
    Send welcome email to new user after successful registration
    """
    try:
        from .constants import PRODUCER

        user_type = "producer" if user.user_type == PRODUCER else "consumer"

        context = {
            "user": user,
            "user_type": user_type,
            "BASE_URL": settings.BASE_URL,
        }

        msg_plain = render_to_string("emails/welcome.txt", context)
        msg_html = render_to_string("emails/welcome.html", context)
        subject = f"Welcome to Trazo - Your Carbon Intelligence Platform"

        return send_mail(
            subject,
            msg_plain,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=msg_html,
        )
    except Exception as e:
        logger.error(f"Error sending welcome email to {user.email}: {str(e)}")
        return False


def send_invited_user_welcome_email(user, company, inviter, role):
    """
    Send welcome email to user who joined via company invitation
    """
    try:
        from .constants import PRODUCER

        user_type = "producer" if user.user_type == PRODUCER else "consumer"

        # Role display mapping
        role_display_map = {"CA": "Company Admin", "FM": "Farm Manager", "DW": "Domain Worker", "DE": "Dealer"}

        context = {
            "user": user,
            "user_type": user_type,
            "company": company,
            "inviter": inviter,
            "role": role,
            "role_display": role_display_map.get(role, role),
            "BASE_URL": settings.BASE_URL,
        }

        msg_plain = render_to_string("emails/welcome_invited.txt", context)
        msg_html = render_to_string("emails/welcome_invited.html", context)
        subject = f"Welcome to {company.name} - You're now part of the team!"

        return send_mail(
            subject,
            msg_plain,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=msg_html,
        )
    except Exception as e:
        logger.error(f"Error sending invited user welcome email to {user.email}: {str(e)}")
        return False


def send_verification_email(user, verification_code=None, verification_link=None):
    """
    Send email verification to user with code or link
    """
    try:
        from .constants import PRODUCER

        user_type = "producer" if user.user_type == PRODUCER else "consumer"

        context = {
            "user": user,
            "user_type": user_type,
            "verification_code": verification_code,
            "verification_link": verification_link,
            "BASE_URL": settings.BASE_URL,
        }

        msg_plain = render_to_string("emails/verification.txt", context)
        msg_html = render_to_string("emails/verification.html", context)
        subject = "Verify Your Trazo Account"

        return send_mail(
            subject,
            msg_plain,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=msg_html,
        )
    except Exception as e:
        logger.error(f"Error sending verification email to {user.email}: {str(e)}")
        return False


def generate_password_reset_token():
    """
    Generate cryptographically secure password reset token
    Following OWASP 2025 recommendations for token security
    """
    return secrets.token_urlsafe(32)  # 256 bits of entropy


def send_password_reset_email(user, reset_token, reset_link):
    """
    Send password reset email to user with secure token link
    Following 2025 security and UX best practices
    """
    try:
        from .constants import PRODUCER

        user_type = "producer" if user.user_type == PRODUCER else "consumer"

        # Get user's first name or fallback to email
        display_name = user.first_name if user.first_name else user.email.split("@")[0]

        context = {
            "user": user,
            "user_type": user_type,
            "display_name": display_name,
            "reset_token": reset_token,
            "reset_link": reset_link,
            "BASE_URL": settings.BASE_URL,
            "expiry_minutes": 15,  # Token expires in 15 minutes
        }

        msg_plain = render_to_string("emails/password_reset.txt", context)
        msg_html = render_to_string("emails/password_reset.html", context)
        subject = "Reset Your Trazo Password"

        result = send_mail(
            subject,
            msg_plain,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=msg_html,
        )

        if result:
            logger.info(f"Password reset email sent successfully to {user.email}")
        else:
            logger.warning(f"Password reset email send failed for {user.email}")

        return result

    except Exception as e:
        logger.error(f"Error sending password reset email to {user.email}: {str(e)}")
        return False


def send_company_join_welcome_email(user, company, role):
    """
    Send welcome email to user who joined a company via company code
    """
    try:
        # Role display mapping
        role_display_map = {"CA": "Company Admin", "DS": "Domain Supervisor", "DW": "Domain Worker", "DE": "Dealer"}

        # Determine dashboard URL based on environment
        if hasattr(settings, "BASE_APP_URL"):
            dashboard_url = f"{settings.BASE_APP_URL}admin/dashboard"
        else:
            dashboard_url = f"{settings.BASE_URL}/admin/dashboard"

        context = {
            "user": user,
            "company": company,
            "role": role,
            "role_display": role_display_map.get(role, role),
            "dashboard_url": dashboard_url,
            "BASE_URL": settings.BASE_URL,
        }

        msg_plain = render_to_string("emails/welcome.txt", context)  # Use existing welcome plain text
        msg_html = render_to_string("emails/company_join_welcome.html", context)
        subject = f"Welcome to {company.name} on Trazo"

        return send_mail(
            subject,
            msg_plain,
            "info@trazo.io",
            [user.email],
            html_message=msg_html,
        )
    except Exception as e:
        logger.error(f"Failed to send company join welcome email to {user.email}: {str(e)}")
        return False


def send_company_welcome_verification_email(user, company, role, verification_code=None, verification_link=None):
    """
    Send combined welcome+verification email to user who joined via company code
    Following 2025 best practice: single email for better UX
    """
    try:
        from .constants import PRODUCER

        user_type = "producer" if user.user_type == PRODUCER else "consumer"
        
        # Role display mapping
        role_display_map = {"CA": "Company Admin", "DS": "Domain Supervisor", "DW": "Domain Worker", "DE": "Dealer"}

        context = {
            "user": user,
            "user_type": user_type,
            "company": company,
            "role": role,
            "role_display": role_display_map.get(role, role),
            "verification_code": verification_code,
            "verification_link": verification_link,
            "BASE_URL": settings.BASE_URL,
        }

        msg_plain = render_to_string("emails/company_welcome_verification.txt", context)
        msg_html = render_to_string("emails/company_welcome_verification.html", context)
        subject = f"Welcome to {company.name} - Verify Your Account"

        result = send_mail(
            subject,
            msg_plain,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=msg_html,
        )

        if result:
            logger.info(f"Combined welcome+verification email sent to {user.email} for {company.name}")
        else:
            logger.warning(f"Failed to send combined welcome+verification email to {user.email}")

        return result

    except Exception as e:
        logger.error(f"Error sending combined welcome+verification email to {user.email}: {str(e)}")
        return False


def send_invitation_email(
    invitee_email, invitee_name, inviter, company, role, invitation_link, invitation_message=None
):
    """
    Send invitation email to user being invited to join a company
    """
    try:
        # Check if this is a company transfer (existing user)
        from django.contrib.auth import get_user_model

        from .models import WorksIn

        User = get_user_model()
        is_company_transfer = False

        existing_user = User.objects.filter(email=invitee_email).first()
        if existing_user:
            # Check if user has membership in another company
            other_membership = WorksIn.objects.filter(user=existing_user).exclude(company=company).exists()
            is_company_transfer = other_membership

        # Role display mapping
        role_display_map = {"CA": "Company Admin", "DS": "Domain Supervisor", "DW": "Domain Worker", "DE": "Dealer"}

        context = {
            "invitee_name": invitee_name,
            "inviter": inviter,
            "company": company,
            "role": role,
            "role_display": role_display_map.get(role, role),
            "invitation_link": invitation_link,
            "invitation_message": invitation_message,
            "BASE_URL": settings.BASE_URL,
        }

        # Choose appropriate template based on invitation type
        if is_company_transfer:
            template_name = "emails/company_transfer_invitation.html"
            subject = f"Company Transfer Invitation - Join {company.name} on Trazo"
        else:
            template_name = "emails/invitation.html"
            subject = f"You're Invited to Join {company.name} on Trazo"

        msg_plain = render_to_string("emails/invitation.txt", context)  # Keep same plain text template
        msg_html = render_to_string(template_name, context)  # Use appropriate HTML template
        print(f"Email settings debug for invitation to {invitee_email}:")
        print(f"  DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        print(f"  SERVER_EMAIL: {settings.SERVER_EMAIL}")
        print(f"  EMAIL_HOST: {settings.EMAIL_HOST}")
        print(f"  EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        print(f"  FROM_EMAIL_ADDRESS env var: {settings.DEFAULT_FROM_EMAIL}")

        # Debug logging for email configuration
        logger.info(f"Email settings debug for invitation to {invitee_email}:")
        logger.info(f"  DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        logger.info(f"  SERVER_EMAIL: {settings.SERVER_EMAIL}")
        logger.info(f"  EMAIL_HOST: {settings.EMAIL_HOST}")
        logger.info(f"  EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        logger.info(f"  FROM_EMAIL_ADDRESS env var: {settings.DEFAULT_FROM_EMAIL}")

        return send_mail(
            subject,
            msg_plain,
            "info@trazo.io",
            [invitee_email],
            html_message=msg_html,
        )
    except Exception as e:
        logger.error(f"Error sending invitation email to {invitee_email}: {str(e)}")
        return False


def send_invitation_to_user(email, link, username, email_address, user_type):
    """
    Send verification code link to the given email (Legacy function - kept for backward compatibility)
    """
    params = {
        "link": link,
        "username": username,
        "email": email_address,
        "user_type": user_type,
    }

    msg_plain = render_to_string("email_verification_code/message.txt", params)
    msg_html = render_to_string("email_verification_code/message.html", params)
    subject = "Welcome to trazo, just verify your account."

    return send_mail(
        subject,
        msg_plain,
        settings.DEFAULT_FROM_EMAIL,
        [email],
        html_message=msg_html,
    )


def generate_invitation_code():
    """
    Generate a secure invitation code for companies
    """
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
