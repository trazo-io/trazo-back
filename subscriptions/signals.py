# Usage tracking (productions, storage) is computed dynamically in
# SubscriptionSerializer._compute_used_productions() and _compute_used_storage_gb().
# No signals are needed — the model fields used_productions and used_storage_gb
# are stale counters that are not used for enforcement.
#
# Subscription lifecycle events ARE signal-driven (below). Subscription.plan and
# .status are written from ~8 call sites across views.py (self-serve upgrade,
# downgrade-at-period-end, Stripe webhooks for updated/deleted/payment_failed,
# admin actions). Emitting SubscriptionEvent at each call site would lose data the
# first time someone adds a ninth path — and the whole point of that table is that
# it cannot be reconstructed after the fact. Diffing in a signal covers every path,
# present and future.

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Subscription, SubscriptionEvent, mrr_for

logger = logging.getLogger(__name__)

# Attribute used to hand the pre_save snapshot to post_save on the same instance.
_PREV_ATTR = "_trazo_prev_state"


@receiver(pre_save, sender=Subscription, dispatch_uid="subscriptions.capture_prev_state")
def capture_prev_state(sender, instance, **kwargs):
    """
    Stash the pre-write DB state so post_save can diff against it.

    Costs one extra SELECT per subscription write. Subscription writes are rare (plan
    changes and webhook status updates), so this is not a hot path.
    """
    if not instance.pk:
        setattr(instance, _PREV_ATTR, None)
        return
    try:
        prev = sender.objects.select_related("plan").get(pk=instance.pk)
    except sender.DoesNotExist:
        setattr(instance, _PREV_ATTR, None)
        return
    setattr(
        instance,
        _PREV_ATTR,
        {
            "plan": prev.plan,
            "plan_slug": prev.plan.slug if prev.plan else "",
            "status": prev.status,
            # MRR is status-aware: a trialing or canceled subscription contributes zero
            # regardless of which plan is attached to it.
            "mrr": mrr_for(prev.plan, prev.status),
        },
    )


def _classify(prev, instance):
    """
    Map a (previous state -> new state) pair onto an event type.

    Returns None when nothing meaningful changed, so unrelated saves (usage counters,
    trial-email bookkeeping) do not pollute the log.
    """
    prev_status, new_status = prev["status"], instance.status
    prev_plan, new_plan = prev["plan"], instance.plan
    prev_mrr, new_mrr = prev["mrr"], mrr_for(new_plan, new_status)

    plan_changed = (prev_plan.pk if prev_plan else None) != (new_plan.pk if new_plan else None)
    status_changed = prev_status != new_status

    if not plan_changed and not status_changed:
        return None

    # Landing on a plan that bills NOTHING is churn, not a downgrade (2026-08-22).
    #
    # Since cancellation became a downgrade-to-Starter rather than a lockout, the terminal state
    # of a churned customer is `plan=starter, status=active` — which, read naively, is an ordinary
    # plan change with a negative MRR delta, i.e. "downgraded". That would have quietly hidden
    # every real cancellation inside the downgrade bucket and left `canceled` looking like zero.
    # Revenue going to zero is the definition of churn regardless of which row the customer ends
    # up sitting on, and this is derived from the MRR movement rather than from a flag a future
    # write path could forget to set.
    dropped_to_free = plan_changed and prev_mrr > 0 and new_mrr == 0

    # Status transitions are the stronger signal — a cancellation that also drops the
    # plan is a cancellation, not a downgrade. Terminal/non-billable statuses are checked
    # FIRST so that e.g. an abandoned checkout (incomplete) alongside a plan change is
    # never classified as "upgraded", which would book revenue that was never collected.
    if status_changed:
        if new_status == "canceled":
            return "canceled"
        if new_status == "past_due":
            return "past_due"
        if new_status == "unpaid":
            return "unpaid"
        if new_status == "incomplete":
            return "status_changed"
        # Checked ahead of `reactivated` and `trial_converted`: a lapsed subscription being
        # re-pointed at Starter arrives here as canceled/past_due/trialing -> active, and both
        # of those labels would book it as a WIN.
        if dropped_to_free:
            return "canceled"
        if new_status in ("active", "trialing") and prev_status in ("canceled", "unpaid"):
            return "reactivated"
        if prev_status == "trialing" and new_status == "active":
            return "trial_converted"
        if not plan_changed:
            return "status_changed"

    if plan_changed:
        if dropped_to_free:
            return "canceled"
        if new_mrr > prev_mrr:
            return "upgraded"
        if new_mrr < prev_mrr:
            return "downgraded"
        return "plan_changed"

    return "status_changed"


def _cancellation_metadata(instance, event_type):
    """Copy the churn reason onto the immutable event row.

    `Subscription` holds current state and is overwritten — a farm that cancels, comes back and
    cancels again for a different reason leaves only the second answer there. SubscriptionEvent
    is the append-only record, so the reason has to be snapshotted onto it at the transition or
    it is not really recorded. Only attached to cancellations: on any other event these fields
    are stale by definition.
    """
    if event_type != "canceled":
        return {}
    reason = getattr(instance, "cancellation_reason", "") or ""
    feedback = getattr(instance, "cancellation_feedback", "") or ""
    if not reason and not feedback:
        return {}
    return {"cancellation_reason": reason, "cancellation_feedback": feedback}


@receiver(post_save, sender=Subscription, dispatch_uid="subscriptions.log_subscription_event")
def log_subscription_event(sender, instance, created, **kwargs):
    """
    Append a SubscriptionEvent for every meaningful lifecycle transition.

    Failures are logged and swallowed: instrumentation must never break a customer's
    upgrade or a Stripe webhook. A missing row can be reconciled from Stripe later; a
    500 during checkout cannot be undone.
    """
    try:
        new_plan = instance.plan
        new_mrr = mrr_for(new_plan, instance.status)

        if created:
            event_type = "trial_started" if instance.status == "trialing" else "created"
            SubscriptionEvent.objects.create(
                company_id=instance.company_id,
                event_type=event_type,
                to_plan=new_plan,
                to_plan_slug=new_plan.slug if new_plan else "",
                to_status=instance.status,
                mrr_before=0,
                mrr_after=new_mrr,
                source="system",
            )
            return

        prev = getattr(instance, _PREV_ATTR, None)
        if prev is None:
            return

        event_type = _classify(prev, instance)
        if event_type is None:
            return

        SubscriptionEvent.objects.create(
            company_id=instance.company_id,
            event_type=event_type,
            from_plan=prev["plan"],
            to_plan=new_plan,
            from_plan_slug=prev["plan_slug"],
            to_plan_slug=new_plan.slug if new_plan else "",
            from_status=prev["status"],
            to_status=instance.status,
            mrr_before=prev["mrr"],
            mrr_after=new_mrr,
            source="system",
            metadata=_cancellation_metadata(instance, event_type),
        )
    except Exception:  # noqa: BLE001 — see docstring: instrumentation must not break writes
        logger.exception("Failed to log SubscriptionEvent for company_id=%s", instance.company_id)
