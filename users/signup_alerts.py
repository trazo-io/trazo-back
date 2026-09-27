"""Tell the owner about every new account and every new company, the day it happens.

Added 2026-09-27. The first sign-ups from outside were a competitor's staff evaluating the
product for an afternoon, and they were found two days later by scrolling the Django admin.
With a handful of accounts, each one is worth a look the same day.

Off unless `SIGNUP_ALERT_EMAILS` is set. Sent after the transaction commits, so the alert sees
the finished row (company-code joins write `WorksIn` after the user) and a rolled-back sign-up
never alerts. A failure is logged and swallowed: an alert must never break a sign-up.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

logger = logging.getLogger(__name__)


def _competitor_tag(email):
    domain = (email or "").rsplit("@", 1)[-1].lower()
    return "[COMPETITOR] " if domain in settings.COMPETITOR_EMAIL_DOMAINS else ""


def _send(subject, lines):
    recipients = settings.SIGNUP_ALERT_EMAILS
    if not recipients:
        return
    try:
        send_mail(subject, "\n".join(lines), settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
    except Exception:  # noqa: BLE001 - an alert must never break a sign-up
        logger.exception("Signup alert failed: %s", subject)


def _user_lines(user):
    companies = [f"{c.name} (id {c.id})" for c in user.companies.all()]
    return [
        f"Email: {user.email}",
        f"Name: {user.first_name} {user.last_name}".rstrip(),
        f"User id: {user.id}",
        f"Type: {user.get_user_type_display()}",
        f"Sign-up method: {user.social_auth_provider or 'email'}",
        f"Joined via company code: {'yes' if user.company_verified else 'no'}",
        f"Companies: {', '.join(companies) or 'none yet'}",
        f"Terms accepted: {user.terms_version or 'NOT RECORDED'}",
        f"Joined: {user.date_joined:%Y-%m-%d %H:%M} UTC",
    ]


def send_new_user_alert(user_id):
    from users.models import User

    user = User.objects.filter(pk=user_id).first()
    if user is None:
        return
    _send(f"{_competitor_tag(user.email)}New Trazo account: {user.email}", _user_lines(user))


def send_new_company_alert(company_id, creator_id):
    from company.models import Company
    from users.models import User

    company = Company.objects.filter(pk=company_id).first()
    creator = User.objects.filter(pk=creator_id).first()
    if company is None or creator is None:
        return
    _send(
        f"{_competitor_tag(creator.email)}New Trazo company: {company.name}",
        [f"Company: {company.name} (id {company.id})", "", "Created by:", *_user_lines(creator)],
    )


def alert_new_user(user):
    transaction.on_commit(lambda: send_new_user_alert(user.pk))


def alert_new_company(company, creator):
    transaction.on_commit(lambda: send_new_company_alert(company.pk, creator.pk))
