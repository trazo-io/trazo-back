"""
Celery tasks for carbon tracking and blockchain verification.

This module contains background tasks for:
- Carbon report generation (nightly)
- Sustainability badge awards (nightly)
- Audit log cleanup (nightly)
- Industry benchmark updates (nightly)
- Blockchain submission (on-demand + monthly reconciliation)
- Carbon credit issuance (on-demand)
"""

import hashlib
import json
import logging

from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.utils import timezone

from celery import shared_task

from company.models import Company

from .models import CarbonEntry, CarbonReport

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task
def generate_carbon_report(report_id):
    """
    Task to generate a carbon report in the background.
    """
    try:
        report = CarbonReport.objects.get(id=report_id)
        # Placeholder for report generation logic (e.g., PDF creation)
        print(f"Generating report {report_id} for {report.year}")
        # Update report status or save generated file path
        report.document = "path/to/generated/report.pdf"  # Placeholder
        report.save()
        return f"Report {report_id} generated"
    except CarbonReport.DoesNotExist:
        return f"Report {report_id} not found"


# NEVER: 2026-09-30 - `generate_nightly_reports`, `award_sustainability_badges` and
# `update_industry_benchmarks` were DELETED here, not merely unscheduled. Registered in
# `backend/scheduled_work.py` as the reason that file exists: all three write a self-assigned
# grade, and the first one wrote `CarbonReport.carbon_score` (0-100) for every establishment
# nightly, off `net_footprint`, which nets offsets out of emissions. The badge task's route was
# already cut in 2026-09-07; the report and benchmark routes are cut in this commit. Verified no
# caller other than the beat schedule before deleting. Do not restore any of the three: the
# score is retired as a CONCEPT, so there is nothing to re-enable.


# NEVER: 2026-09-30 - `cleanup_old_audit_logs` was DELETED. It deleted CarbonAuditLog rows older
# than 365 days, and the decision not to keep it is the answer to "what retention period should this
# have", not a dodge of it:
#
#   * The constant was arbitrary. Nothing in the repo specified 365 days, so scheduling it would have
#     enforced a policy nobody wrote.
#   * It is irreversible, unspecified, and free not to do. At current scale the table costs nothing,
#     so the only asymmetric risk is deleting something that turns out to be needed.
#   * The rows include the `gaming_detected` action. Deleting fraud signals on a timer is the wrong
#     default whatever the number is.
#   * An audit trail's retention belongs to the record it DESCRIBES, not to a global constant. These
#     rows track create/update/delete/verify on CarbonEntry, CarbonCertification and CarbonReport. If
#     the subject was deleted, the audit row is the only evidence the deletion happened, which is
#     exactly when it is most wanted. 7 CFR 205.103(b)(4) wants records for not less than five years.
#   * The one real argument FOR deletion is that the rows carry a `user` FK, so they are personal data
#     and unbounded retention is a minimisation liability. That argues for a written policy naming a
#     lawful basis and a period. Trazo has no such policy, so there is nothing to implement yet.
#
# Revisit when there is either a written retention policy or a storage cost. Until then the table
# grows, which is the cheap and reversible half of the choice.


# ---------------------------------------------------------------------------
# Blockchain tasks
# ---------------------------------------------------------------------------


@shared_task(bind=True)
def batch_submit_monthly_summaries(self):
    """
    Monthly reconciliation sweep for blockchain submissions.

    NOT SCHEDULED, deliberately, since 2026-09-30. It selects companies with an ACTIVE BLOCKCHAIN
    SUBSCRIPTION, and `blockchain-verification` is is_active=False and withdrawn, so the query
    cannot match. Kept rather than deleted because it shares
    `_submit_single_production_to_blockchain` with the immediate path.

    Primary submission now happens immediately at finalization time via
    submit_production_to_blockchain(). This batch task is the safety net:
    it catches any productions whose immediate submission failed (network
    issues, gas spikes, Celery worker down, etc.).

    Logic: Find all finalized productions (finish_date is set) that belong to
    companies with active blockchain subscriptions and haven't been submitted
    to blockchain yet. Uses the same _submit_single_production_to_blockchain()
    function as the immediate task — no code duplication.
    """
    try:
        from .services.blockchain import BlockchainCarbonService

        blockchain_service = BlockchainCarbonService()

        from history.models import History

        # Get companies with active blockchain subscriptions
        companies_with_blockchain = Company.objects.filter(blockchain_subscription_status=True)

        total_summaries = 0
        successful_summaries = 0
        failed_summaries = 0

        for company in companies_with_blockchain:
            logger.info(f"Processing company: {company.name} (ID: {company.id})")

            # Find finalized productions not yet submitted to blockchain.
            # A production is "finalized" when finish_date is set and
            # finalization_hash exists (events have been hashed).
            # A production is "not yet on blockchain" when extra_data has no
            # blockchain_tx_hash, or extra_data is null.
            productions = History.objects.filter(
                parcel__establishment__company=company,
                finish_date__isnull=False,
                extra_data__finalization_hash__isnull=False,
            ).exclude(
                extra_data__blockchain_tx_hash__isnull=False,
            )

            for production in productions:
                try:
                    total_summaries += 1
                    success = _submit_single_production_to_blockchain(production, company, blockchain_service)
                    if success:
                        successful_summaries += 1
                    else:
                        failed_summaries += 1
                except Exception as e:
                    failed_summaries += 1
                    logger.error(f"Error processing production {production.id}: {str(e)}")
                    continue

        logger.info(f"Blockchain batch complete: {successful_summaries}/{total_summaries} successful")

        return {
            "status": "completed",
            "total_summaries": total_summaries,
            "successful_summaries": successful_summaries,
            "failed_summaries": failed_summaries,
        }

    except Exception as e:
        logger.error(f"Error in batch_submit_monthly_summaries: {str(e)}")
        raise self.retry(countdown=60, max_retries=3)


def build_blockchain_raw_data(production, company_id):
    """Build the raw_data dict for blockchain hashing.

    Single source of truth for the data structure that gets hashed and submitted
    on-chain. Used by:
    - _submit_single_production_to_blockchain() — at submission time
    - history/transparency_views.py _recompute_production_data_hash() — at verification time

    Returns (raw_data, data_hash) tuple.
    """
    extra = production.extra_data if isinstance(production.extra_data, dict) else {}
    finalization_hash = extra.get("finalization_hash")
    finalization_event_count = extra.get("finalization_event_count", 0)

    # Carbon data is supplementary — include if available, default to 0
    carbon_entries = CarbonEntry.objects.filter(production=production)
    summary_data = carbon_entries.aggregate(total_co2e=Sum("co2e_amount"), entry_count=Count("id"))
    total_co2e = float(summary_data["total_co2e"] or 0)
    carbon_entry_count = summary_data["entry_count"] or 0

    raw_data = {
        "production_id": production.id,
        "company_id": company_id,
        "start_date": (production.start_date.isoformat() if production.start_date else None),
        "finish_date": (production.finish_date.isoformat() if production.finish_date else None),
        "finalization_hash": finalization_hash,
        "finalization_event_count": finalization_event_count,
        "total_co2e": total_co2e,
        "carbon_entry_count": carbon_entry_count,
    }

    sorted_raw = json.dumps(raw_data, sort_keys=True, default=str)
    try:
        from web3 import Web3

        raw_hex = Web3.keccak(text=sorted_raw).hex()
        data_hash = raw_hex.removeprefix("0x")
    except ImportError:
        data_hash = hashlib.sha256(sorted_raw.encode()).hexdigest()

    return raw_data, data_hash, total_co2e, carbon_entry_count, finalization_event_count


def _submit_single_production_to_blockchain(production, company, blockchain_service):
    """
    Submit a single finalized production to blockchain.

    Transparency-first: The primary data anchored on-chain is the finalization
    hash (keccak256 of all production events). Carbon data is supplementary —
    included when available but NOT required for blockchain submission.

    Called from:
    1. The immediate submission task (at finalization time)
    2. The monthly batch reconciliation (safety net for failures)

    Returns True on success, False on failure.
    """
    # Skip if already submitted
    if (
        production.extra_data
        and isinstance(production.extra_data, dict)
        and production.extra_data.get("blockchain_tx_hash")
    ):
        logger.info("Production %s already on blockchain, skipping", production.id)
        return True

    # Extract finalization hash — the primary integrity anchor.
    extra = production.extra_data if isinstance(production.extra_data, dict) else {}
    if not extra.get("finalization_hash"):
        logger.warning("Production %s has no finalization hash — cannot submit to blockchain", production.id)
        return False

    # Build raw_data and hash using the shared function (single source of truth)
    raw_data, data_hash, total_co2e, carbon_entry_count, finalization_event_count = build_blockchain_raw_data(
        production, company.id
    )

    # Submit to blockchain
    logger.info(
        "Submitting production %s to blockchain (%d events documented, %d carbon entries, %.1f kg CO2e)",
        production.id,
        finalization_event_count,
        carbon_entry_count,
        total_co2e,
    )

    blockchain_result = blockchain_service.submit_monthly_summary(
        producer_id=company.id,
        production_id=production.id,
        total_co2e=total_co2e,
        data_hash=data_hash,
        raw_data=raw_data,
    )

    if blockchain_result and blockchain_result.get("success"):
        logger.info("Successfully submitted production %s", production.id)
        logger.info("Transaction hash: %s", blockchain_result.get("transaction_hash"))

        # Store blockchain result on this History record
        if production.extra_data is None:
            production.extra_data = {}
        production.extra_data["blockchain_tx_hash"] = blockchain_result.get("transaction_hash")
        production.extra_data["blockchain_block_number"] = blockchain_result.get("block_number")
        production.extra_data["blockchain_network"] = blockchain_result.get("network", "")
        production.extra_data["blockchain_submitted_at"] = timezone.now().isoformat()
        production.extra_data["blockchain_verified"] = not blockchain_result.get("mock", False)
        production.extra_data["blockchain_data_hash"] = data_hash
        production.save(update_fields=["extra_data"])
        return True
    else:
        logger.error("Failed to submit production %s: %s", production.id, blockchain_result)
        return False


@shared_task(bind=True, max_retries=3)
def submit_production_to_blockchain(self, production_id):
    """
    Immediately submit a single finalized production to blockchain.

    Triggered by finish_history() when the company has an active blockchain
    subscription. This eliminates the gap between production finalization
    and consumer-visible blockchain verification.

    The monthly batch task acts as a safety net for any failures here.
    """
    logger.info("BLOCKCHAIN TASK: Starting for production %s", production_id)
    try:
        from history.models import History

        production = History.objects.select_related("parcel__establishment__company").get(id=production_id)
        logger.info("BLOCKCHAIN TASK: Found production %s (finish_date=%s)", production_id, production.finish_date)

        company = (
            production.parcel.establishment.company if production.parcel and production.parcel.establishment else None
        )
        if not company:
            logger.error("BLOCKCHAIN TASK: No company found for production %s", production_id)
            return {"status": "error", "error": "No company found"}

        if not company.blockchain_subscription_status:
            logger.info("BLOCKCHAIN TASK: Company %s has no blockchain subscription, skipping", company.id)
            return {"status": "skipped", "reason": "no_blockchain_subscription"}

        logger.info("BLOCKCHAIN TASK: Initializing BlockchainCarbonService...")
        from .services.blockchain import BlockchainCarbonService

        blockchain_service = BlockchainCarbonService()
        logger.info(
            "BLOCKCHAIN TASK: Service initialized (blockchain_ready=%s, production_mode=%s, blockchain_required=%s)",
            blockchain_service._is_blockchain_ready(),
            blockchain_service.production_mode,
            blockchain_service.blockchain_required,
        )

        logger.info("BLOCKCHAIN TASK: Calling _submit_single_production_to_blockchain...")
        success = _submit_single_production_to_blockchain(production, company, blockchain_service)
        logger.info("BLOCKCHAIN TASK: Submission result for production %s: success=%s", production_id, success)

        if success:
            return {
                "status": "success",
                "production_id": production_id,
                "tx_hash": (production.extra_data or {}).get("blockchain_tx_hash"),
            }
        else:
            raise Exception(f"Blockchain submission failed for production {production_id}")

    except History.DoesNotExist:
        logger.error("BLOCKCHAIN TASK: Production %s not found", production_id)
        return {"status": "error", "error": "Production not found"}
    except Exception as e:
        logger.error("BLOCKCHAIN TASK: Error for production %s: %s", production_id, e, exc_info=True)
        raise self.retry(countdown=30, exc=e)
