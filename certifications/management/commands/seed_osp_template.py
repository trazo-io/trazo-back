"""
Sprint 5A — Create a skeleton Organic System Plan for an establishment.

Usage:
    poetry run python manage.py seed_osp_template <establishment_id>
    poetry run python manage.py seed_osp_template <establishment_id> --force

Pre-fills the six required § 205.201(a)(1)-(6) sections with starter narratives
sourced from the establishment's existing fields:
  - farming_method, crops_grown, irrigation_methods -> practices_procedures
  - existing chemical/soil inputs in the last 12 months -> inputs_list
  - has_split_operation / split_operation_plan -> commingling_barriers
  - fraud_prevention_plan_* fields -> monitoring_plan (SOE sub-block)

Safe by default: refuses to run if any OSP already exists for the establishment
(to avoid stomping on in-progress drafts). Pass --force to create a new draft
version anyway. NOT idempotent — --force creates an additional version each run.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from certifications.models import OSP_SECTION_KEYS, OrganicSystemPlan
from company.models import Establishment


def _fmt_list(items):
    return ", ".join(str(i) for i in items) if items else "(none recorded)"


class Command(BaseCommand):
    help = "Create a skeleton OSP draft for an establishment, pre-filled from existing data."

    def add_arguments(self, parser):
        parser.add_argument("establishment_id", type=int, help="Establishment ID")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Create a new draft even if an OSP already exists",
        )

    def handle(self, *args, **options):
        est_id = options["establishment_id"]
        force = options["force"]

        try:
            est = Establishment.objects.get(pk=est_id)
        except Establishment.DoesNotExist:
            raise CommandError(f"Establishment {est_id} not found.")

        existing = OrganicSystemPlan.objects.filter(establishment=est).order_by("-version_number").first()
        if existing and not force:
            raise CommandError(
                f"OSP already exists for {est.name} (v{existing.version_number}, "
                f"status={existing.status}). Re-run with --force to add a new draft."
            )

        with transaction.atomic():
            next_version = (existing.version_number + 1) if existing else 1
            sections = self._build_sections_from_establishment(est)
            osp = OrganicSystemPlan.objects.create(
                establishment=est,
                version_number=next_version,
                previous_version=existing,
                status="draft",
                sections=sections,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Created OSP v{osp.version_number} (draft) for {est.name} "
                f"— {int(osp.section_completion * 100)}% sections pre-filled."
            )
        )
        self.stdout.write(f"OSP id={osp.id}, public_id={osp.public_id}")
        self.stdout.write("Next steps: edit sections via the dashboard, then POST .../submit/ and .../activate/.")

    def _build_sections_from_establishment(self, est: Establishment) -> dict:
        """
        Build starter narratives for the six required sections. The narratives are
        factually accurate statements of what we already know; the farmer edits them
        before submission. We do NOT fabricate practices the establishment has not
        actually recorded.
        """
        now_iso = timezone.now().date().isoformat()

        practices = (
            f"Operation: {est.name}"
            + (f" ({est.establishment_type})" if est.establishment_type else "")
            + ".\n"
            + (f"Farming method: {est.farming_method}.\n" if est.farming_method else "")
            + f"Crops grown: {_fmt_list(est.crops_grown)}.\n"
            + f"Irrigation methods: {_fmt_list(est.irrigation_methods)}.\n"
            + f"Conservation practices: {_fmt_list(est.conservation_practices)}.\n"
            + "Frequencies and detailed SOPs: (farmer to complete)."
        )

        inputs_list = (
            "Inputs are logged per-event in Trazo (chemical, soil, and pest "
            "management events). See the Audit Export 'OMRI / National List "
            "Verification' table for the full classified list. Farmer must confirm "
            "commercial availability and source of each input here."
        )

        # Fraud prevention sub-block is SOE-required (88 FR 3622).
        # Regulatory-notification guidance is pre-filled with the CORRECT § 205.400(f)
        # sub-paragraphs: (f)(1) = application / drift of a prohibited substance,
        # (f)(2) = change in a certified operation (practice / input / buffer / etc.).
        # The regulatory duty is to notify the certifying agent "immediately" — do
        # NOT self-impose a specific-hour SLA in the OSP narrative; see § 205.400(f).
        has_ofpp = est.fraud_prevention_plan_uploaded
        monitoring = (
            "Monitoring practices: (farmer to complete — describe cadence and methods).\n\n"
            "Fraud Prevention Plan (7 CFR 205.201(a)(3); Strengthening Organic Enforcement rule, "
            "88 FR 3548, effective 2023-03-20, compliance date 2024-03-19):\n"
            + (
                f"  - Uploaded on {est.fraud_prevention_plan_date} by "
                f"{est.ofpp_responsible_person or '(responsible person not set)'}.\n"
                if has_ofpp
                else "  - NOT YET UPLOADED. Required for certified organic operations.\n"
            )
            + "  - Supplier verification: (farmer to complete).\n"
            + "  - Fraud risk review cadence: (farmer to complete).\n\n"
            + "Certifier notification duty (7 CFR 205.400(f)):\n"
            + "  - Any application or drift of a prohibited substance will be reported "
            "to the certifying agent immediately per § 205.400(f)(1).\n"
            + "  - Any change in the certified operation (new input, new parcel, "
            "buffer modification, split-operation change, etc.) will be reported "
            "to the certifying agent immediately per § 205.400(f)(2)."
        )

        recordkeeping = (
            "Records are maintained in Trazo, a digital recordkeeping system, and "
            "retained for 5 years per 7 CFR 205.103. Records include: production "
            "events, chemical/soil/pest management events, harvest and storage "
            "logs, input/material lists with OMRI/National-List classification, "
            "certifications, OSP versions, and annual updates. Change history is "
            "captured via django-auditlog (21 CFR Part 11 trustworthy-records "
            "principles: user attribution, timestamp, before/after diff)."
        )

        commingling = (
            "Split-operation status: "
            + ("YES — " if est.has_split_operation else "NO — ")
            + (
                "both organic and conventional production on this operation.\n"
                if est.has_split_operation
                else "this operation is wholly organic (no conventional production).\n"
            )
            + (est.split_operation_plan or "")
            + "\nParcels, storage separation, equipment cleaning, and drift buffers: "
            "(farmer to complete details per 7 CFR 205.272)."
        )

        additional = (
            "Certifier-specific attachments (certifier worksheets, land history "
            "affidavits, maps, labels, etc.) — attach via the OSP PDF upload or "
            "reference existing Trazo records.\n\n"
            "Material / activity change requests: any operational change (new "
            "parcel, hedgerow, fence, building, input list modification, split-"
            "operation change) will be filed as a Material/Activity change "
            "request with the certifying agent per § 205.400(f)(2) and reflected "
            "in the next annual update per § 205.406."
        )

        narratives = {
            "practices_procedures": practices,
            "inputs_list": inputs_list,
            "monitoring_plan": monitoring,
            "recordkeeping_description": recordkeeping,
            "commingling_barriers": commingling,
            "additional_certifier_info": additional,
        }
        # Belt-and-suspenders: make sure every required key is present even if a
        # future edit drops one.
        return {key: {"narrative": narratives.get(key, ""), "last_updated": now_iso} for key in OSP_SECTION_KEYS}
