"""
Write one SubscriptionMonthlySnapshot row per company per month.

Cohort retention needs STATE at a point in time, not just transitions. With snapshots,
"of the companies that started in month M, how many were still active in M+n" is a
GROUP BY. Without them it is an event-replay exercise that gets harder every month.

Idempotent: re-running for a month overwrites that month's rows. Run monthly (first of
the month, covering the month just ended) and use --backfill once to seed history.

    poetry run python manage.py snapshot_subscriptions
    poetry run python manage.py snapshot_subscriptions --month 2026-06
    poetry run python manage.py snapshot_subscriptions --backfill
"""

from datetime import date, datetime

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from company.models import Company, Establishment
from history.models import History
from subscriptions.models import Subscription, SubscriptionEvent, SubscriptionMonthlySnapshot, mrr_for


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _next_month(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


class Command(BaseCommand):
    help = "Snapshot every company's subscription state for a given month (cohort retention source data)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--month",
            help="Month to snapshot as YYYY-MM. Defaults to the current month.",
        )
        parser.add_argument(
            "--backfill",
            action="store_true",
            help="Snapshot every month from the earliest subscription to now.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be written without writing.",
        )

    def handle(self, *args, **options):
        if options["backfill"] and options["month"]:
            raise CommandError("Use --month or --backfill, not both.")

        if options["backfill"]:
            earliest = Subscription.objects.order_by("created_at").values_list("created_at", flat=True).first()
            if earliest is None:
                self.stdout.write("No subscriptions exist yet — nothing to snapshot.")
                return
            months = []
            cursor = _month_start(earliest.date())
            end = _month_start(date.today())
            while cursor <= end:
                months.append(cursor)
                cursor = _next_month(cursor)
        elif options["month"]:
            try:
                year, month = options["month"].split("-")
                target = date(int(year), int(month), 1)
            except (ValueError, TypeError):
                raise CommandError("--month must look like 2026-06")
            # A future month has no state to observe; writing one would assert knowledge
            # of subscriptions that have not happened.
            if target > _month_start(date.today()):
                raise CommandError(f"--month {options['month']} is in the future; nothing to snapshot yet.")
            months = [target]
        else:
            months = [_month_start(date.today())]

        total = 0
        for month in months:
            written = self._snapshot_month(month, dry_run=options["dry_run"])
            total += written
            self.stdout.write(f"{month:%Y-%m}: {written} snapshot(s)")

        verb = "Would write" if options["dry_run"] else "Wrote"
        self.stdout.write(self.style.SUCCESS(f"{verb} {total} snapshot(s) across {len(months)} month(s)."))

    def _state_at(self, sub, month_end: date):
        """
        Derive state as of `month_end` -> dict(plan, plan_slug, status, mrr, is_reconstructed).

        For the current month the subscription row IS the truth. For any earlier month it
        is not — `plan` and `status` are overwritten in place, so today's values say
        nothing about what was true in March. Replay the event log instead.

        Historical MRR and plan identity come from the event's OWN snapshots
        (`mrr_after`, `to_plan_slug`), never from `Plan.price` / `Plan.slug`. Reading the
        live Plan would mean re-running this command after a price change silently
        rewrites past revenue — the exact failure SubscriptionEvent exists to prevent —
        and would lose the plan name entirely once a Plan row is deleted (to_plan is
        SET_NULL).

        When no events precede month_end (months predating this instrumentation), fall
        back to current state and flag the row as reconstructed rather than passing an
        approximation off as an observation.
        """
        current = {
            "plan": sub.plan,
            "plan_slug": sub.plan.slug if sub.plan else "",
            "status": sub.status,
            # Same status-aware definition the lifecycle signal uses — a trialing or
            # canceled subscription contributes zero MRR whatever plan is attached.
            "mrr": mrr_for(sub.plan, sub.status),
            "is_reconstructed": False,
        }

        # The month is still open: the live row is the best available statement of state.
        if month_end > date.today():
            return current

        last = (
            SubscriptionEvent.objects.filter(company_id=sub.company_id, occurred_at__date__lt=month_end)
            .select_related("to_plan")
            .order_by("-occurred_at", "-id")
            .first()
        )
        if last is None:
            return {**current, "is_reconstructed": True}

        return {
            "plan": last.to_plan,
            "plan_slug": last.to_plan_slug or (last.to_plan.slug if last.to_plan else ""),
            "status": last.to_status or sub.status,
            "mrr": last.mrr_after,
            "is_reconstructed": False,
        }

    def _snapshot_month(self, month: date, dry_run: bool = False) -> int:
        month_end = _next_month(month)

        subscriptions = Subscription.objects.select_related("plan", "company").all()
        written = 0

        for sub in subscriptions:
            # localtime(), not .date(): created_at is stored in UTC, so a signup late on
            # the last day of a month reads as the next month in UTC and would be dropped
            # from (or misfiled in) its own cohort.
            created_local = timezone.localtime(sub.created_at).date() if sub.created_at else None

            # A subscription created after this month had not started yet — recording a
            # row would invent a customer that did not exist, which quietly corrupts
            # every cohort that month feeds into.
            if created_local and created_local >= month_end:
                continue

            company = sub.company
            state = self._state_at(sub, month_end)

            establishments = Establishment.objects.filter(company=company)
            # History.start_date/finish_date are DateTimeFields — compare against aware
            # datetimes so the ORM does not coerce a naive date at the boundary.
            month_start_dt = timezone.make_aware(datetime(month.year, month.month, 1))
            month_end_dt = timezone.make_aware(datetime(month_end.year, month_end.month, 1))
            active_productions = (
                History.objects.filter(
                    parcel__establishment__company=company,
                    start_date__lt=month_end_dt,
                )
                .filter(Q(finish_date__gte=month_start_dt) | Q(finish_date__isnull=True))
                .count()
            )

            status = state["status"]
            defaults = {
                "plan": state["plan"],
                "plan_slug": state["plan_slug"],
                "status": status,
                "mrr": state["mrr"],
                "is_active": status in ("active", "trialing"),
                "is_trialing": status == "trialing",
                "cohort_month": _month_start(created_local) if created_local else None,
                "establishments_count": establishments.count(),
                "active_productions": active_productions,
                "is_reconstructed": state["is_reconstructed"],
            }

            if not dry_run:
                SubscriptionMonthlySnapshot.objects.update_or_create(company=company, month=month, defaults=defaults)
            written += 1

        return written
