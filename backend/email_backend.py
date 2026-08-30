"""
Resend Web API email backend for Django.

Uses HTTPS (port 443) instead of SMTP, which is reliable on all
cloud platforms (DigitalOcean, Heroku, Railway, etc.) where SMTP
ports 25/465/587 are commonly blocked.

Requires: requests (already installed), RESEND_API_KEY in settings.

Note: the REST API is snake_case (`reply_to`); only Resend's Node/Python
SDKs use camelCase. The landing site's lib/email.ts posts the same shape.
"""

import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

import requests

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


class ResendAPIBackend(BaseEmailBackend):
    """Django email backend that sends via Resend's Web API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "RESEND_API_KEY", None)

    def send_messages(self, email_messages):
        if not self.api_key:
            logger.error("RESEND_API_KEY is not configured")
            if not self.fail_silently:
                raise ValueError("RESEND_API_KEY is not configured")
            return 0

        sent_count = 0
        for message in email_messages:
            try:
                if self._send(message):
                    sent_count += 1
            except Exception as e:
                logger.error(f"Resend API error sending to {message.to}: {e}")
                if not self.fail_silently:
                    raise
        return sent_count

    def _send(self, message):
        # Resend accepts "Name <email>" verbatim in `from`, so from_email needs
        # no parsing the way SendGrid's {"email": ..., "name": ...} dict did.
        payload = {
            "from": message.from_email,
            "to": list(message.to),
            "subject": message.subject,
        }

        if message.cc:
            payload["cc"] = list(message.cc)

        if message.bcc:
            payload["bcc"] = list(message.bcc)

        if message.reply_to:
            payload["reply_to"] = list(message.reply_to)

        if message.body:
            payload["text"] = message.body

        for content, mimetype in getattr(message, "alternatives", None) or []:
            if mimetype == "text/html":
                payload["html"] = content

        response = requests.post(
            RESEND_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if response.status_code in (200, 201, 202):
            logger.info(f"Email sent via Resend API to {message.to}")
            return True

        logger.error(
            f"Resend API failed: {response.status_code} {response.text} " f"| to={message.to} from={message.from_email}"
        )
        if not self.fail_silently:
            raise Exception(f"Resend API error: {response.status_code} {response.text}")
        return False
