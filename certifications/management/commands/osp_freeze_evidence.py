"""Show, reproducibly, that a filed annual-update revision does not move when the records around it do.

WHY THIS EXISTS (OSP alignment audit, run 3, R3-09)
---------------------------------------------------
The run-2 handoff carried `frozen/evidence.json`: before and after hashes, and the edits made, as
descriptive strings. The reviewer could check the file's own consistency and nothing else: no
canonical payload to recompute the signed hash from, no record ids, no before and after values, no
response body for the refused edit. This command writes all of them, so a reader can replay the
check against the same commit.

It never keeps an edit. Everything runs inside one transaction that is rolled back, and the command
re-reads the filing afterwards to show the rollback held. Safe against any database.

    manage.py osp_freeze_evidence --filing <id> --user-email <account with access> --out evidence.json
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

HASH_METHOD = (
    "SHA-256 of json.dumps(OSPAnnualUpdate.signed_content(), sort_keys=True, separators=(',', ':'), "
    "default=str), UTF-8. signed_content() is SIGNED_FIELDS, plus correction_note only when it is set."
)


SECTIONS_HASH_METHOD = (
    "SHA-256 of json.dumps(OrganicSystemPlan.sections, sort_keys=True, default=str), UTF-8. The same method "
    "for every plan-section digest in this file."
)


def _sections_canonical(plan) -> str:
    return json.dumps(plan.sections or {}, sort_keys=True, default=str)


class _Rollback(Exception):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — evidence still records that the commit was not readable
        return "unknown"


def _filed_copy_states(filing, signed_hash: str) -> bool:
    """Whether the frozen copy prints this signed-content hash: the signature as it was filed."""
    from pdfminer.high_level import extract_text

    if not signed_hash or not filing.filed_pdf:
        return False
    text = " ".join(extract_text(io.BytesIO(bytes(filing.filed_pdf))).split())
    return f"sha256 {signed_hash}" in text


def _state(filing) -> dict:
    filing.refresh_from_db()
    canonical = json.dumps(filing.signed_content(), sort_keys=True, separators=(",", ":"), default=str)
    data = bytes(filing.filed_pdf or b"")
    return {
        "filed_sha256_column": filing.filed_sha256,
        "filed_bytes_sha256": _sha(data),
        "filed_bytes_length": len(data),
        "signed_content_sha256_column": filing.signed_content_sha256,
        "canonical_payload": canonical,
        "canonical_payload_sha256": _sha(canonical.encode("utf-8")),
        "superseded_at": filing.superseded_at,
    }


def _shipped(filing) -> dict:
    """The bytes the plan's packet carries for this revision, rebuilt now."""
    from certifications.services.annual_update_filing import packet_revision_filename
    from certifications.services.osp_module_pdf import generate_osp_packet

    plan = filing.new_osp or filing.prior_osp
    name = packet_revision_filename(filing)
    packet = zipfile.ZipFile(io.BytesIO(generate_osp_packet(plan)))
    return {"plan_id": plan.pk, "plan_version": plan.version_number, "entry": name, "sha256": _sha(packet.read(name))}


class Command(BaseCommand):
    help = "Write reproducible evidence that a filed annual-update revision is frozen. Changes nothing."

    def add_arguments(self, parser):
        parser.add_argument("--filing", type=int, required=True, help="OSPAnnualUpdate id of a filed revision.")
        parser.add_argument("--user-email", required=True, help="An account that can reach the filing's API.")
        parser.add_argument("--out", default="", help="Write the JSON here; stdout when omitted.")

    def handle(self, *args, **options):
        from rest_framework.test import APIClient

        from certifications.models import OSPAnnualUpdate, OSPChangeNotification
        from users.models import User

        filing = OSPAnnualUpdate.objects.select_related("prior_osp__establishment").filter(pk=options["filing"]).first()
        if filing is None or not filing.filed_pdf:
            raise CommandError("Give a revision that is filed and has a frozen copy.")
        user = User.objects.filter(email=options["user_email"]).first()
        if user is None:
            raise CommandError(f"No user with email {options['user_email']!r}.")

        evidence = {
            "commit": _commit(),
            "filing": {"id": filing.pk, "reporting_year": filing.reporting_year, "revision": filing.revision_number},
            "hash_method": HASH_METHOD,
            "sections_hash_method": SECTIONS_HASH_METHOD,
            # Run 4, R4-03: the plan's sections are read at three stages, each named, because building
            # a packet recompiles an editable plan's narratives (inside the transaction, so rolled back).
            "plan_sections_stages": {},
            "before": _state(filing),
            "edits": [],
        }
        plan = filing.new_osp or filing.prior_osp
        est = plan.establishment
        evidence["plan_sections_stages"]["1_before_the_command"] = _sha(_sections_canonical(plan).encode("utf-8"))
        kept_before = {
            "establishment_name": est.name,
            "plan_sections_sha256": _sha(_sections_canonical(plan).encode("utf-8")),
            "plan_updated_at": str(plan.updated_at),
        }
        notice_id = None

        try:
            with transaction.atomic():
                # Inside the transaction: building a packet refreshes an editable plan's narratives and
                # saves them, which would otherwise be a real write (review of back #93).
                evidence["before"]["packet"] = _shipped(filing)
                plan.refresh_from_db()
                est.refresh_from_db()
                evidence["plan_sections_stages"]["2_after_the_packet_build_recompiled_narratives"] = _sha(
                    _sections_canonical(plan).encode("utf-8")
                )
                client = APIClient()
                client.force_authenticate(user)
                url = f"/api/companies/{est.company_id}/establishments/{est.pk}/osp-annual-updates/{filing.pk}/"
                attempted = f"{filing.changes_summary} [edit attempted after filing]"
                res = client.patch(url, {"changes_summary": attempted}, format="json", HTTP_HOST="localhost")
                try:
                    body = res.json()
                except Exception:  # noqa: BLE001
                    body = res.content[:500].decode("utf-8", "replace")
                evidence["edits"].append(
                    {
                        "kind": "api_patch_on_the_filed_revision",
                        "request": {"method": "PATCH", "path": url, "data": {"changes_summary": attempted}},
                        "response": {"status": res.status_code, "body": body},
                    }
                )

                before_name = est.name
                est.name = f"{before_name} (renamed after filing)"
                est.save(update_fields=["name"])
                evidence["edits"].append(
                    {
                        "kind": "record_edit",
                        "model": "company.Establishment",
                        "id": est.pk,
                        "field": "name",
                        "before": before_name,
                        "after": est.name,
                    }
                )

                before_sections = _sections_canonical(plan)
                sections = dict(plan.sections or {})
                added = {"narrative": "Narrative added after the filing."}
                sections["edited_after_filing"] = added
                plan.sections = sections
                plan.save(update_fields=["sections"])
                after_sections = _sections_canonical(plan)
                evidence["edits"].append(
                    {
                        "kind": "record_edit",
                        "model": "certifications.OrganicSystemPlan",
                        "id": plan.pk,
                        "field": "sections",
                        "stage_of_before": "2_after_the_packet_build_recompiled_narratives",
                        "before_sha256": _sha(before_sections.encode("utf-8")),
                        "after_sha256": _sha(after_sections.encode("utf-8")),
                        "added_key": "edited_after_filing",
                        "added_value": added,
                        "before_canonical": before_sections,
                        "after_canonical": after_sections,
                    }
                )

                notice = OSPChangeNotification.objects.create(
                    osp=plan,
                    change_category="practice_input_procedure_change",
                    description="Change notified after the filing.",
                    date_notified=filing.submitted_at.date() if filing.submitted_at else None,
                    method="written",
                    created_by=user,
                )
                notice_id = notice.pk
                evidence["edits"].append(
                    {
                        "kind": "record_created",
                        "model": "certifications.OSPChangeNotification",
                        "id": notice.pk,
                        "values": {
                            "osp_id": plan.pk,
                            "change_category": notice.change_category,
                            "description": notice.description,
                            "date_notified": notice.date_notified,
                            "method": notice.method,
                        },
                    }
                )

                evidence["after_edits"] = _state(filing)
                evidence["after_edits"]["packet"] = _shipped(filing)
                raise _Rollback
        except _Rollback:
            pass

        evidence["after_rollback"] = _state(filing)
        # Re-read what the command itself touched, not only the filing (review of back #93): the
        # rollback is shown on the records edited, the notification created and the plan the packet
        # build may have saved.
        est.refresh_from_db()
        plan.refresh_from_db()
        evidence["plan_sections_stages"]["3_after_the_rollback"] = _sha(_sections_canonical(plan).encode("utf-8"))
        kept_after = {
            "establishment_name": est.name,
            "plan_sections_sha256": _sha(_sections_canonical(plan).encode("utf-8")),
            "plan_updated_at": str(plan.updated_at),
        }
        evidence["records_after_rollback"] = {
            **kept_after,
            "notification_created_exists": OSPChangeNotification.objects.filter(pk=notice_id).exists(),
        }
        evidence["records_before"] = kept_before
        before, after = evidence["before"], evidence["after_edits"]
        # The signed hash is checked against the frozen copy, which is the filing. A recompute from
        # this database is recorded beside it and never decides the result: the signed content holds
        # row ids (prior_osp_id, corrects_id), so a database rebuilt from a fixture re-hashes
        # differently while every signed field is unchanged (run 7c, R7-02; review of back #117).
        recomputes = before["canonical_payload_sha256"] == before["signed_content_sha256_column"]
        evidence["held_payload"] = {
            "recomputes_to_the_signed_hash": recomputes,
            "note": (
                "The payload held in this database hashes to the signed content hash."
                if recomputes
                else "The payload held in this database does not hash to the signed content hash. The signed "
                "hash is the one the frozen copy states; the held payload is not shown to be the signed content."
            ),
        }
        evidence["checks"] = {
            "signed_hash_stated_in_filed_copy": _filed_copy_states(filing, before["signed_content_sha256_column"]),
            "patch_refused": evidence["edits"][0]["response"]["status"] == 409,
            "filed_bytes_unchanged": before["filed_bytes_sha256"]
            == after["filed_bytes_sha256"]
            == before["filed_sha256_column"],
            "signed_content_unchanged": before["canonical_payload"] == after["canonical_payload"],
            "packet_ships_the_filed_bytes": before["packet"]["sha256"]
            == after["packet"]["sha256"]
            == before["filed_sha256_column"],
            "filing_rolled_back": evidence["after_rollback"]["canonical_payload"] == before["canonical_payload"],
            "edited_records_rolled_back": kept_after == kept_before
            and not evidence["records_after_rollback"]["notification_created_exists"],
        }
        evidence["unchanged"] = all(evidence["checks"].values())

        text = json.dumps(evidence, indent=2, default=str)
        if options["out"]:
            Path(options["out"]).write_text(text)
        else:
            self.stdout.write(text)
        if not evidence["unchanged"]:
            raise CommandError("A check failed: " + ", ".join(k for k, v in evidence["checks"].items() if not v))
