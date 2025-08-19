import logging
from smtplib import SMTPException
from urllib.parse import quote

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .constants import CONSUMER, PRODUCER
from .models import User, VerificationCode
from .utils import send_verification_email, send_welcome_email

logger = logging.getLogger(__name__)

import random
import string


def generate_verification_code(length=6):
    letters_and_digits = string.ascii_letters + string.digits
    return "".join(random.choice(letters_and_digits) for i in range(length)).upper()


@receiver(post_save, sender=User)
def create_verification_code(sender, instance, created, **kwargs):
    if created:
        # Check if user was created via invitation (already verified)
        if instance.is_verified:
            # For invited users: skip email sending here since the invitation flow
            # handles sending the specialized welcome email with company context
            logger.info(f"User created via invitation: {instance.email} - email handled by invitation flow")
        else:
            # For regular signups: send both welcome and verification emails
            code = generate_verification_code()
            VerificationCode.objects.create(user=instance, code=code)

            # Properly encode the email for URLs
            encoded_email = quote(instance.email)

            verification_link = ""
            user_type = int(instance.user_type)
            if user_type == PRODUCER:
                verification_link = f"{settings.BASE_APP_URL}auth/verifyemail?email={encoded_email}&code={code}"
            elif user_type == CONSUMER:
                verification_link = f"{settings.BASE_CONSUMER_URL}auth/verifyemail?email={encoded_email}&code={code}"

            # Send both welcome and verification emails for regular users
            try:
                # Send welcome email
                send_welcome_email(instance)

                # Send verification email with new template
                send_verification_email(user=instance, verification_code=code, verification_link=verification_link)

                logger.info(f"Welcome and verification emails sent to new user: {instance.email}")
            except SMTPException as e:
                logger.error(f"Could not send emails to user: {instance.email}, Error: {e}")
