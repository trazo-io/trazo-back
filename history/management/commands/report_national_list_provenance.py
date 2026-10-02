"""Count what the National List basis migration will mark, before it runs. Writes nothing.

OSP alignment audit, Phase 5 slice 1 (2026-10-02). The migration keeps every stored classification and
marks it `legacy_unverified`: how it was made was never recorded. Run this against a database before the
migration deploys and put the counts in the PR, so the change is known before it lands.

The "today's exact/alias rules would reach" column is information only. It is not the original method,
and nothing uses it to label a row.
"""

from collections import Counter

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Count stored National List classifications by establishment. Read-only."

    def handle(self, *args, **options):
        from certifications.services.national_list_aliases import resolve_alias
        from certifications.services.omri_verifier import _normalize
        from history.models import ChemicalEvent

        # `.only()` the columns that exist before the migration: the command runs BEFORE it deploys, when
        # the new basis column is not in the table yet and a full select would fail.
        rows = (
            ChemicalEvent.objects.filter(national_list_substance__isnull=False)
            .select_related("national_list_substance", "history__parcel__establishment")
            .only(
                "id",
                "commercial_name",
                "extra_data",
                "national_list_substance__substance_name",
                "national_list_substance__substance_name_normalized",
                "history__id",
                "history__parcel__id",
                "history__parcel__establishment__id",
                "history__parcel__establishment__name",
            )
        )
        per_est = Counter()
        reachable = Counter()
        total = 0
        for event in rows.iterator():
            total += 1
            est = getattr(getattr(getattr(event, "history", None), "parcel", None), "establishment", None)
            key = f"{getattr(est, 'id', '-')} {getattr(est, 'name', '(no establishment)')}"
            per_est[key] += 1
            nl = event.national_list_substance
            extra = event.extra_data if isinstance(event.extra_data, dict) else {}
            names = [n for n in (extra.get("active_ingredient"), event.commercial_name) if n]
            for name in names:
                norm = _normalize(name)
                if norm == nl.substance_name_normalized or resolve_alias(norm) == nl.substance_name:
                    reachable[key] += 1
                    break

        self.stdout.write(f"Stored National List classifications: {total}")
        self.stdout.write("All will be marked legacy_unverified; values are kept. Per establishment:")
        for key, count in sorted(per_est.items()):
            self.stdout.write(f"  {key}: {count} (today's exact/alias rules would reach {reachable[key]})")
