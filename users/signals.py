import logging
import random
import string
from smtplib import SMTPException
from urllib.parse import quote

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .constants import CONSUMER, PRODUCER
from .models import User, VerificationCode
from .signup_alerts import alert_new_user
from .utils import send_verification_email, send_welcome_email

logger = logging.getLogger(__name__)


def generate_verification_code(length=6):
    letters_and_digits = string.ascii_letters + string.digits
    return "".join(random.choice(letters_and_digits) for i in range(length)).upper()


@receiver(post_save, sender=User)
def create_verification_code(sender, instance, created, **kwargs):
    if created:
        alert_new_user(instance)

        if instance.company_verified:
            # Company code users get combined email from serializer — skip here
            logger.info(
                f"User created via company code: {instance.email} - combined email handled by company join flow"
            )
            return

        # Always send welcome email for new users (regular, social auth, invited)
        try:
            send_welcome_email(instance)
            logger.info(f"Welcome email sent to new user: {instance.email}")
        except SMTPException as e:
            logger.error(f"Could not send welcome email to: {instance.email}, Error: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending welcome email to: {instance.email}, Error: {e}")

        # Only send verification email if user is NOT already verified
        # (social auth and invited users are already verified)
        if not instance.is_verified:
            code = generate_verification_code()
            VerificationCode.objects.create(user=instance, code=code)

            encoded_email = quote(instance.email)
            verification_link = ""
            user_type = int(instance.user_type)
            if user_type == PRODUCER:
                verification_link = f"{settings.BASE_APP_URL}auth/verifyemail?email={encoded_email}&code={code}"
            elif user_type == CONSUMER:
                verification_link = f"{settings.BASE_CONSUMER_URL}auth/verifyemail?email={encoded_email}&code={code}"

            try:
                send_verification_email(user=instance, verification_code=code, verification_link=verification_link)
                logger.info(f"Verification email sent to: {instance.email}")
            except SMTPException as e:
                logger.error(f"Could not send verification email to: {instance.email}, Error: {e}")
            except Exception as e:
                logger.error(f"Unexpected error sending verification email to: {instance.email}, Error: {e}")
