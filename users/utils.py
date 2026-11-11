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
        # Recordkeeping review F-30: the tagline was the retired "transparency platform" framing.
        subject = "Welcome to Trazo - organic farm recordkeeping"

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


def send_code_join_notice(company_id, new_user_id):
    """Tell a company's admins that someone joined with the company code.

    A code join needs no approval and lands as Viewer on every farm, so the admins are the only
    people who can notice a code that travelled further than they meant it to. Added 2026-09-28,
    after a join by code went unseen for two days. Plain text only: the new member's name is
    typed by them.
    """
    from company.models import Company

    from .models import User, WorksIn

    company = Company.objects.filter(pk=company_id).first()
    new_user = User.objects.filter(pk=new_user_id).first()
    if company is None or new_user is None:
        return False
    admins = list(
        WorksIn.objects.filter(company=company, role=WorksIn.COMPANY_ADMIN)
        .exclude(user=new_user)
        .values_list("user__email", flat=True)
    )
    if not admins:
        return False
    settings_link = f"{settings.BASE_APP_URL}admin/dashboard/settings"
    body = "\n".join(
        [
            f"{new_user.get_full_name().strip() or new_user.email} ({new_user.email}) joined {company.name} "
            "on Trazo with your company code.",
            "",
            "They joined as a Viewer and can see every farm's records.",
            "",
            "If you don't know them, remove them from the team and generate a new code:",
            settings_link,
        ]
    )
    # Collapse whitespace: a newline in a company name makes send_mail raise BadHeaderError.
    company_name = " ".join(company.name.split())
    try:
        return send_mail(
            f"New member joined {company_name} with your company code",
            body,
            settings.DEFAULT_FROM_EMAIL,
            admins,
        )
    except Exception as e:
        logger.error(f"Error sending code-join notice for company {company.pk}: {str(e)}")
        return False


def send_invited_user_welcome_email(user, company, inviter, role):
    """
    Send welcome email to user who joined via company invitation
    """
    try:
        from .constants import PRODUCER

        user_type = "producer" if user.user_type == PRODUCER else "consumer"

        # Role display mapping
        role_display_map = {"CA": "Company Admin", "FM": "Farm Manager", "VW": "Viewer"}

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
        logger.error(
            f"Error sending password reset email to {user.email}: {type(e).__name__}: {str(e)} "
            f"| HOST={settings.EMAIL_HOST} PORT={settings.EMAIL_PORT} "
            f"TLS={settings.EMAIL_USE_TLS} SSL={getattr(settings, 'EMAIL_USE_SSL', False)} "
            f"FROM={settings.DEFAULT_FROM_EMAIL}"
        )
        return False


def send_company_join_welcome_email(user, company, role):
    """
    Send welcome email to user who joined a company via company code
    """
    try:
        # Role display mapping
        role_display_map = {"CA": "Company Admin", "FM": "Farm Manager", "VW": "Viewer"}

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
            settings.DEFAULT_FROM_EMAIL,
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
        role_display_map = {"CA": "Company Admin", "FM": "Farm Manager", "VW": "Viewer"}

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
        role_display_map = {"CA": "Company Admin", "FM": "Farm Manager", "VW": "Viewer"}

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

        msg_plain = render_to_string("emails/invitation.txt", context)
        msg_html = render_to_string(template_name, context)

        return send_mail(
            subject,
            msg_plain,
            settings.DEFAULT_FROM_EMAIL,
            [invitee_email],
            html_message=msg_html,
        )
    except Exception as e:
        logger.error(f"Error sending invitation email to {invitee_email}: {str(e)}")
        return False


def generate_invitation_code():
    """
    Generate a secure invitation code for companies
    """
    return "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))


def _display_name(user):
    return user.first_name if user.first_name else (user.email or "").split("@")[0]


def send_email_change_confirmation(user, new_email, link):
    """
    The single-use link that applies a change of login email, sent to the NEW address only
    (overall review 2026-11, OV-SEC-C03). Nothing changes until it is opened.
    """
    from .models import EmailChangeRequest

    context = {
        "user": user,
        "display_name": _display_name(user),
        "new_email": new_email,
        "link": link,
        "expiry_hours": EmailChangeRequest.LIFETIME_HOURS,
        "BASE_URL": settings.BASE_URL,
    }
    try:
        return send_mail(
            "Confirm your new Trazo email",
            render_to_string("emails/email_change_confirm.txt", context),
            settings.DEFAULT_FROM_EMAIL,
            [new_email],
            html_message=render_to_string("emails/email_change_confirm.html", context),
        )
    except Exception as e:
        logger.error(f"Failed to send email change confirmation for user {user.pk}: {e}")
        return False


def send_email_change_notice(user, new_email):
    """
    Tell the CURRENT address that a change to another address was requested, so the owner of a
    borrowed session learns of it before the link is opened (OV-SEC-C03).
    """
    context = {
        "user": user,
        "display_name": _display_name(user),
        "new_email": new_email,
        "BASE_URL": settings.BASE_URL,
    }
    try:
        return send_mail(
            "Your Trazo email is about to change",
            render_to_string("emails/email_change_notice.txt", context),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            html_message=render_to_string("emails/email_change_notice.html", context),
        )
    except Exception as e:
        logger.error(f"Failed to send email change notice for user {user.pk}: {e}")
        return False
