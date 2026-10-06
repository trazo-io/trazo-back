"""Re-check every certification Trazo marked "verified" against the confirmed-entry rule (run 8).

Until 2026-10-05 a fuzzy name match against the Organic Integrity Database was enough to store
`verified`, and an unrecognised database status defaulted to it. The verifier now requires a
confirmed entry (`USDAOrganicVerifier._confirmed`). Rows verified under the old rule keep their
status until this command re-checks them.

Dry run by default: it writes a JSON report of every row whose status would change and saves
nothing. `--apply` saves the changes and logs a `DataOperationLog` row; `--restore <report>`
puts the previous statuses back. See `common/services/data_operations.py`.

    manage.py reevaluate_certification_verification --report /tmp/r8-verification.json
    manage.py reevaluate_certification_verification --report /tmp/r8-verification.json --apply
    manage.py reevaluate_certification_verification --report /tmp/r8-verification-check.json   # expect 0 changes; never reuse the applied report's path
    manage.py reevaluate_certification_verification --restore /tmp/r8-verification.json

Only rows whose stored source is the Organic Integrity Database are re-checked. A `verified`
row with any other source already prints as self-reported everywhere (the source gate in
`Certification.consumer_display_status` and the dossier), and no verifier set it.

A row moved off `verified` may carry a certifier name, dates, scope or products that the old
rule copied from the unconfirmed entry. The report marks those rows for review; the command
does not guess which values the operator typed.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from common.services import data_operations as ops

OPERATION = "r8_certification_verification_reevaluation"
_COPIED = ("certifier_name", "effective_date", "expiry_date", "certification_scope", "certified_items")


def _new_status(result_status: str, *, facility: bool) -> str:
    """The status `VerificationManager` / `PostHarvestFacility.verify` would store today."""
    if result_status == "verified":
        return "verified"
    if facility:
        # A handler with no confirmed entry is self-reported (PostHarvestFacility.verify).
        return "self_reported"
    if result_status == "not_found":
        return "pending"
    return result_status


def plan():
    from certifications.models import Certification, PostHarvestFacility
    from certifications.services.usda_organic_verifier import USDAOrganicVerifier

    source = Certification.DATABASE_VERIFICATION_SOURCE
    verifier = USDAOrganicVerifier()
    # Review of back #119: with no OID data loaded, verify() answers self_reported for every
    # row, and --apply would downgrade every verified certification on a fresh or restored
    # database for a reason that has nothing to do with the rows. Refuse instead.
    if not verifier.health_check():
        raise CommandError(
            "The USDA Organic Integrity Database copy is not loaded (USDAOrganicOperation is empty). "
            "Run import_usda_organic_data first; re-checking against an empty copy would downgrade "
            "every verified row."
        )
    for cert in Certification.objects.filter(verification_status="verified", verification_source=source).select_related(
        "establishment"
    ):
        est = cert.establishment
        result = verifier.verify(
            operation_name=cert.usda_operation_name or est.name,
            state=est.state or "",
            certification_number=cert.certification_number,
            certifier_name=cert.certifier_name,
        )
        after = _new_status(result.status, facility=False)
        if after == cert.verification_status:
            continue
        filled = [f for f in _COPIED if getattr(cert, f)]
        yield ops.RowChange(
            model="certifications.Certification",
            pk=cert.pk,
            before={
                "verification_status": cert.verification_status,
                "verification_notes": cert.verification_notes,
                "_label": cert.verification_status,
            },
            after={
                "verification_status": after,
                "verification_notes": result.notes or "",
                "_label": after,
                "_review": (
                    f"check {', '.join(filled)}: may have been copied from the unconfirmed entry" if filled else ""
                ),
            },
            reason=result.notes or result.status,
        )
    for fac in PostHarvestFacility.objects.filter(verification_status="verified", verification_source=source):
        result = verifier.verify(fac.name, fac.state or "", fac.certification_number, certifier_name=fac.certifier_name)
        after = _new_status(result.status, facility=True)
        if after == fac.verification_status:
            continue
        yield ops.RowChange(
            model="certifications.PostHarvestFacility",
            pk=fac.pk,
            before={"verification_status": fac.verification_status, "_label": fac.verification_status},
            after={"verification_status": after, "_label": after},
            reason=result.notes or result.status,
        )


def write(model_label, pk, values):
    from django.apps import apps

    from certifications.models import CertificationVerificationLog

    model = apps.get_model(model_label)
    row = model.objects.get(pk=pk)
    before = row.verification_status
    model.objects.filter(pk=pk).update(**values)
    if model_label == "certifications.Certification":
        CertificationVerificationLog.objects.create(
            certification=row,
            status_before=before,
            status_after=values.get("verification_status", before),
            verification_source=OPERATION,
            success=True,
            raw_response={"operation": OPERATION, "values": values},
        )


class Command(BaseCommand):
    help = "Re-check certifications marked verified against the confirmed-entry rule. Dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--report", default="", help="Where to write the JSON report (dry run and --apply).")
        parser.add_argument("--apply", action="store_true", help="Save the changes and log the operation.")
        parser.add_argument("--restore", default="", help="Put back the 'before' values from this report.")
        parser.add_argument("--run-by", default="", help="Who ran it, recorded in the log.")

    def handle(self, *args, **options):
        if options["restore"]:
            report = ops.restore(report_path=options["restore"], write=write, run_by=options["run_by"])
            self.stdout.write(f"Restored {len(report.changes)} row(s) from {options['restore']}.")
            return
        if not options["report"]:
            raise CommandError("Give --report <path>: the report is the record of what changed and the rollback.")
        report = ops.run(
            operation=OPERATION,
            plan=plan,
            write=write,
            report_path=options["report"],
            apply=options["apply"],
            run_by=options["run_by"],
        )
        mode = "Applied" if options["apply"] else "Dry run, nothing saved"
        self.stdout.write(f"{mode}: {len(report.changes)} row(s) would change. Report: {options['report']}")
        for key, n in sorted(report.counts.items()):
            self.stdout.write(f"  {key}: {n}")
