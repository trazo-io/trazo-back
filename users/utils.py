import boto3
import uuid
import json
import secrets
import string
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
from datetime import timedelta
from django.urls import reverse
from django.contrib.sites.models import Site
import logging

logger = logging.getLogger(__name__)


def send_welcome_email(user):
    """
    Send welcome email to new user after successful registration
    """
    try:
        from .constants import PRODUCER, CONSUMER
        user_type = 'producer' if user.user_type == PRODUCER else 'consumer'
        
        context = {
            'user': user,
            'user_type': user_type,
            'BASE_URL': settings.BASE_URL,
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
        from .constants import PRODUCER, CONSUMER
        user_type = 'producer' if user.user_type == PRODUCER else 'consumer'
        
        # Role display mapping
        role_display_map = {
            'CA': 'Company Admin',
            'FM': 'Farm Manager', 
            'DW': 'Domain Worker',
            'DE': 'Dealer'
        }
        
        context = {
            'user': user,
            'user_type': user_type,
            'company': company,
            'inviter': inviter,
            'role': role,
            'role_display': role_display_map.get(role, role),
            'BASE_URL': settings.BASE_URL,
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
        from .constants import PRODUCER, CONSUMER
        user_type = 'producer' if user.user_type == PRODUCER else 'consumer'
        
        context = {
            'user': user,
            'user_type': user_type,
            'verification_code': verification_code,
            'verification_link': verification_link,
            'BASE_URL': settings.BASE_URL,
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


def send_invitation_email(invitee_email, invitee_name, inviter, company, role, invitation_link, invitation_message=None):
    """
    Send invitation email to user being invited to join a company
    """
    try:
        # Role display mapping
        role_display_map = {
            'CA': 'Company Admin',
            'DS': 'Domain Supervisor', 
            'DW': 'Domain Worker',
            'DE': 'Dealer'
        }
        
        context = {
            'invitee_name': invitee_name,
            'inviter': inviter,
            'company': company,
            'role': role,
            'role_display': role_display_map.get(role, role),
            'invitation_link': invitation_link,
            'invitation_message': invitation_message,
            'BASE_URL': settings.BASE_URL,
        }
        
        msg_plain = render_to_string("emails/invitation.txt", context)
        msg_html = render_to_string("emails/invitation.html", context)
        subject = f"You're Invited to Join {company.name} on Trazo"
        
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
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
