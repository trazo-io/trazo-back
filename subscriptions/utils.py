"""Transactional email for the subscription lifecycle.

WHY THE PLAIN-TEXT BODY IS BUILT IN PYTHON AND NOT RENDERED FROM A `.txt` TEMPLATE
---------------------------------------------------------------------------------
Django autoescapes every template it renders, and it decides that from the ENGINE, not the
file extension. A `.txt` template therefore turns an apostrophe in a farm name into `&#x27;`
in a message that has no HTML to be escaped for — plain corruption, and invisible to anyone
who only ever opens the HTML alternative. That is a class this repo has already paid for
once. Only the HTML part is a template; the text part is assembled here.

WHY THESE FUNCTIONS DO NOT SWALLOW
----------------------------------
They raise. Every caller decides for itself whether a send failure is fatal, and the two
current callers both log at ERROR with a stack trace. Until 2026-08-22 this module rendered a
`subscription_emails/` namespace that has never existed anywhere in this repo, so
`render_to_string` raised `TemplateDoesNotExist` on the first line of every function — and the
one caller wrapped it in a bare `except` that logged at ERROR without a trace. The result: the
post-cancellation acknowledgement California's ARL requires was never sent to anybody, for
months, and nothing on any dashboard said so. Two dead trial helpers pointing at the same
phantom namespace were deleted at the same time; the live trial emails are in `tasks.py` and
render from `subscriptions/emails/`, which is the only email template directory this app has.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

# The billing page. `/account/billing` — the path this module used to send people to — has
# never been a route in the frontend; the real one is under /admin/dashboard.
BILLING_PATH = "/admin/dashboard/subscription"


def resolve_billing_recipient(company):
    """Return `(email, first_name)` for a company's billing contact, or `(None, "")`.

    THE ONLY correct way to reach a company's admin. `company.company_admins` — which the
    cancellation and payment webhooks both used to call — is not a relation that exists on
    `Company` and never has: `WorksIn` sets `related_name="company_workers"` and the reverse
    accessor for users is `company_users`. Every call raised `AttributeError`, and both call
    sites wrapped it in a bare `except`, so the failure was invisible. That was a SECOND
    independent reason no cancellation email ever went out, on top of the template namespace
    that did not exist either — two unrelated bugs on one line, each of which alone was enough.

    Priority matches `tasks._resolve_recipient`, which is the one path that worked:
    `company.contact_email` if the owner set one, else the first Company Admin's address.
    """
    from users.models import WorksIn

    admin = WorksIn.objects.filter(company=company, role=WorksIn.COMPANY_ADMIN).select_related("user").first()
    first_name = getattr(getattr(admin, "user", None), "first_name", "") or ""

    if company.contact_email:
        return company.contact_email, first_name
    if admin and admin.user.email:
        return admin.user.email, first_name
    return None, ""


def _base_context():
    frontend = getattr(settings, "FRONTEND_URL", "").rstrip("/")
    return {
        "app_url": frontend,
        "billing_url": f"{frontend}{BILLING_PATH}",
        "support_email": getattr(settings, "SUPPORT_EMAIL", "support@trazo.io"),
        "current_year": timezone.now().year,
        "BASE_URL": getattr(settings, "BASE_URL", "http://localhost:8000/"),
    }


def _send(subject, to_email, template_name, context, text_body):
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@trazo.io"),
        to=[to_email],
    )
    msg.attach_alternative(render_to_string(f"subscriptions/emails/{template_name}", context), "text/html")
    msg.send()


def send_cancellation_scheduled_email(email, username, company_name, plan_name, end_date):
    """Acknowledge a cancellation REQUEST, at the moment it is made.

    Required, not a courtesy: California's Automatic Renewal Law (AB 2863, in force since
    2025-07-01) requires an acknowledgement after cancellation that the consumer can retain.
    It has to state when access actually ends — which is the end of the period already paid
    for, not today — and how to undo it, because the subscription is still live until then.
    """
    context = dict(
        _base_context(),
        username=username or "there",
        company_name=company_name,
        plan_name=plan_name,
        end_date=end_date.strftime("%B %d, %Y") if end_date else "",
    )

    text_body = (
        f"Hi {context['username']},\n\n"
        f"We have cancelled the {plan_name} subscription for {company_name}. You will not be "
        f"charged again.\n\n"
        + (f"Your {plan_name} features stay on until {context['end_date']}.\n\n" if context["end_date"] else "")
        + "After that, the account moves to Starter, which is free forever:\n"
        "  - Every record you have ever logged stays in Trazo, complete and readable.\n"
        "  - You can keep logging activities, parcels and productions, with no limit.\n"
        "  - Your QR codes keep working, so cases already in the channel are unaffected.\n"
        "  - 10 GB of photo storage stays available.\n\n"
        "What stops are the certifier documents: the OSP renewal packet and workbooks, the "
        "audit exports, the California PUR export and the certifier review link.\n\n"
        f"Changed your mind? You can turn the subscription back on any time before "
        f"{context['end_date'] or 'it ends'}: {context['billing_url']}\n\n"
        f"If something we did pushed you to this, tell us — {context['support_email']}. We read "
        "every reply.\n"
    )

    _send(
        f"Your {plan_name} subscription for {company_name} has been cancelled",
        email,
        "subscription_cancel_scheduled.html",
        context,
        text_body,
    )


def send_subscription_canceled_email(email, username, company_name, previous_plan_name=""):
    """Confirm the subscription has now ENDED and the account is on Starter.

    Sent from `views.land_on_free_tier`, i.e. when Stripe reports the subscription gone. The
    job of this one is to say plainly that nothing was deleted — the previous behaviour locked
    the farm out of its own records, so "your data is fine" is the single most important
    sentence in the message and it is now also true.
    """
    context = dict(
        _base_context(),
        username=username or "there",
        company_name=company_name,
        previous_plan_name=previous_plan_name,
    )

    text_body = (
        f"Hi {context['username']},\n\n"
        f"The {previous_plan_name or 'paid'} subscription for {company_name} has ended. "
        f"{company_name} is now on Starter — free forever, no card, no clock.\n\n"
        "Nothing was deleted and nothing is locked:\n"
        "  - Every farm, parcel, production and activity you logged is still there.\n"
        "  - You can keep logging. Starter has no limit on parcels or productions.\n"
        "  - Your QR codes keep working.\n"
        "  - 10 GB of photo storage.\n\n"
        "Certifier documents — the OSP renewal packet and workbooks, the audit exports, the "
        "California PUR export and the certifier review link — need a Compliance plan. Your "
        "records keep building in the meantime, so whenever you come back the packet is ready "
        "from the history you already have.\n\n"
        f"Restart any time: {context['billing_url']}\n\n"
        f"Questions: {context['support_email']}\n"
    )

    _send(
        f"Your subscription for {company_name} has ended — you are on Starter now",
        email,
        "subscription_canceled.html",
        context,
        text_body,
    )


def send_payment_failed_email(email, username, company_name, plan_name, amount_due=None):
    """Tell the customer a charge failed — and that nothing has been switched off.

    The second half is the part that matters. Stripe's Smart Retries run for three to four
    weeks, and for that whole window Trazo deliberately keeps the plan live
    (`company.models.PAID_PLAN_STATUSES`). A dunning email that only says "your payment failed"
    invites the reader to assume the worst and stop logging mid-season, which is precisely the
    outcome the grace period exists to prevent. So this says what still works, first.
    """
    context = dict(
        _base_context(),
        username=username or "there",
        company_name=company_name,
        plan_name=plan_name,
        amount_due=amount_due,
    )

    # The HTML alternative printed the declined amount and the text part did not, so which
    # half a mail client rendered decided whether the reader learned how much was declined.
    amount_clause = f" for ${amount_due}" if amount_due else ""
    text_body = (
        f"Hi {context['username']},\n\n"
        f"We could not charge the card on file{amount_clause} for {company_name}'s "
        f"{plan_name} plan.\n\n"
        "NOTHING HAS BEEN SWITCHED OFF. Your farms, records, logging, exports and QR codes all "
        "keep working while we retry over the next few weeks. This is a card problem, not an "
        "account problem.\n\n"
        "Usually it is an expired card or a new number. Updating it takes a minute:\n"
        f"{context['billing_url']}\n\n"
        f"If you would rather stop paying, that is fine too — cancelling moves you to Starter, "
        f"which is free forever and keeps every record you have logged.\n\n"
        f"Stuck? {context['support_email']}\n"
    )

    _send(
        f"Card declined for {company_name} — nothing has been switched off",
        email,
        "payment_failed.html",
        context,
        text_body,
    )


def send_renewal_reminder_email(email, username, company_name, plan_name, amount, renewal_date):
    """Remind the customer that an annual subscription is about to auto-renew.

    Required by California's Automatic Renewal Law for any offer with a term of a year or
    longer: a clear and conspicuous reminder, in a form the consumer can retain, 15 to 45 days
    before the renewal date, stating the renewal, the amount and how to cancel. Compliance is
    $249/year and Operation is $1,200/year, so both are in scope; nothing here fires for a
    monthly plan or for Starter.

    Deliberately NOT driven off Stripe's `invoice.upcoming` webhook, which fires on whatever
    lead time the Stripe dashboard happens to be set to (3 days by default — outside the legal
    window). A statutory deadline should not depend on a setting in someone else's UI.
    """
    context = dict(
        _base_context(),
        username=username or "there",
        company_name=company_name,
        plan_name=plan_name,
        amount=amount,
        renewal_date=renewal_date.strftime("%B %d, %Y") if renewal_date else "",
    )

    text_body = (
        f"Hi {context['username']},\n\n"
        f"{company_name}'s Trazo {plan_name} plan renews automatically on "
        f"{context['renewal_date']}, and the card on file will be charged ${amount} for another "
        f"year.\n\n"
        "No action is needed if you want to continue.\n\n"
        f"To change plan, update your card, or cancel before you are charged: "
        f"{context['billing_url']}\n\n"
        "If you cancel, you move to Starter — free forever — and every record you have logged "
        "stays in Trazo.\n\n"
        f"Questions: {context['support_email']}\n"
    )

    _send(
        f"{company_name}'s Trazo {plan_name} plan renews on {context['renewal_date']}",
        email,
        "renewal_reminder.html",
        context,
        text_body,
    )
