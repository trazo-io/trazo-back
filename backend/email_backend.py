"""
SendGrid Web API v3 email backend for Django.

Uses HTTPS (port 443) instead of SMTP, which is reliable on all
cloud platforms (DigitalOcean, Heroku, Railway, etc.) where SMTP
ports 25/465/587 are commonly blocked.

Requires: requests (already installed), SENDGRID_API_KEY in settings.
"""

import logging

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

SENDGRID_API_URL = "https://api.sendgrid.com/v3/mail/send"


class SendGridAPIBackend(BaseEmailBackend):
    """Django email backend that sends via SendGrid's Web API v3."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key = getattr(settings, "SENDGRID_API_KEY", None)

    def send_messages(self, email_messages):
        if not self.api_key:
            logger.error("SENDGRID_API_KEY is not configured")
            if not self.fail_silently:
                raise ValueError("SENDGRID_API_KEY is not configured")
            return 0

        sent_count = 0
        for message in email_messages:
            try:
                if self._send(message):
                    sent_count += 1
            except Exception as e:
                logger.error(f"SendGrid API error sending to {message.to}: {e}")
                if not self.fail_silently:
                    raise
        return sent_count

    def _send(self, message):
        payload = {
            "personalizations": [
                {
                    "to": [{"email": addr} for addr in message.to],
                }
            ],
            "from": self._parse_email(message.from_email),
            "subject": message.subject,
            "content": [],
        }

        # Add CC
        if message.cc:
            payload["personalizations"][0]["cc"] = [{"email": addr} for addr in message.cc]

        # Add BCC
        if message.bcc:
            payload["personalizations"][0]["bcc"] = [{"email": addr} for addr in message.bcc]

        # Add Reply-To
        if message.reply_to:
            payload["reply_to"] = {"email": message.reply_to[0]}

        # Add plain text content
        if message.body:
            payload["content"].append({"type": "text/plain", "value": message.body})

        # Add HTML content if available
        html_body = getattr(message, "alternatives", None)
        if html_body:
            for content, mimetype in html_body:
                if mimetype == "text/html":
                    payload["content"].append({"type": "text/html", "value": content})

        response = requests.post(
            SENDGRID_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )

        if response.status_code in (200, 201, 202):
            logger.info(f"Email sent via SendGrid API to {message.to}")
            return True
        else:
            logger.error(
                f"SendGrid API failed: {response.status_code} {response.text} "
                f"| to={message.to} from={message.from_email}"
            )
            if not self.fail_silently:
                raise Exception(f"SendGrid API error: {response.status_code} {response.text}")
            return False

    def _parse_email(self, email_str):
        """Parse 'Name <email>' format into SendGrid dict."""
        if "<" in email_str and ">" in email_str:
            name = email_str.split("<")[0].strip()
            email = email_str.split("<")[1].rstrip(">")
            return {"email": email, "name": name}
        return {"email": email_str}
