"""Re-run the drift detector over stored events, after its rules change.

Drift findings are STORED on each event (`drift_warning`), so a rule change reaches existing events
only when something re-evaluates them. Phase 5 slice 1 (2026-10-02) stopped partial-name matches from
clearing findings; run this once after that deploys.

    manage.py recompute_drift                 # every establishment with events
    manage.py recompute_drift --establishment 13
"""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Re-evaluate stored drift findings for chemical and soil events."

    def add_arguments(self, parser):
        parser.add_argument("--establishment", type=int, help="Only this establishment id.")

    def handle(self, *args, **options):
        from certifications.services.drift_detector import evaluate_chemical_event, evaluate_soil_event
        from history.models import ChemicalEvent, SoilManagementEvent

        chem = ChemicalEvent.objects.all()
        soil = SoilManagementEvent.objects.all()
        if options.get("establishment"):
            chem = chem.filter(history__parcel__establishment_id=options["establishment"])
            soil = soil.filter(history__parcel__establishment_id=options["establishment"])
        before = chem.filter(drift_warning__isnull=False).count() + soil.filter(drift_warning__isnull=False).count()
        n = 0
        for event in chem.iterator():
            evaluate_chemical_event(event)
            n += 1
        for event in soil.iterator():
            evaluate_soil_event(event)
            n += 1
        after = chem.filter(drift_warning__isnull=False).count() + soil.filter(drift_warning__isnull=False).count()
        self.stdout.write(f"Re-evaluated {n} events. Findings: {before} before, {after} after.")
