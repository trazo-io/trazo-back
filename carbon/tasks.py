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
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from celery import shared_task

from company.models import Company, Establishment

from .models import (
    CarbonAuditLog,
    CarbonBenchmark,
    CarbonEntry,
    CarbonReport,
    ProductionTemplate,
    SustainabilityBadge,
)

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


@shared_task
def generate_nightly_reports():
    """Generate carbon reports for all establishments and productions."""
    yesterday = timezone.now().date() - timedelta(days=1)

    # Generate establishment reports
    establishments = Establishment.objects.all()
    for establishment in establishments:
        entries = CarbonEntry.objects.filter(establishment=establishment, timestamp__date=yesterday)

        total_emissions = entries.filter(type="emission").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
        total_offsets = entries.filter(type="offset").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
        net_footprint = total_emissions - total_offsets

        # Calculate carbon score
        industry_average = (
            CarbonBenchmark.objects.filter(year=yesterday.year).aggregate(Avg("average_emissions"))[
                "average_emissions__avg"
            ]
            or 0
        )

        carbon_score = 100
        if industry_average > 0:
            ratio = net_footprint / industry_average
            carbon_score = max(1, min(100, int(100 * (1 - ratio))))

        # Create report
        CarbonReport.objects.create(
            establishment=establishment,
            period_start=yesterday,
            period_end=yesterday,
            total_emissions=total_emissions,
            total_offsets=total_offsets,
            net_footprint=net_footprint,
            carbon_score=carbon_score,
            generated_at=timezone.now(),
        )


@shared_task
def award_sustainability_badges():
    """Award sustainability badges based on carbon performance."""
    # Get all establishments with carbon entries
    establishments = Establishment.objects.filter(carbonentry__isnull=False).distinct()

    # Also get all productions with carbon entries
    productions = ProductionTemplate.objects.filter(carbonentry__isnull=False).distinct()

    # Get all automatic badges
    automatic_badges = SustainabilityBadge.objects.filter(is_automatic=True)

    # Process establishments
    for establishment in establishments:
        # Get latest year with entries
        latest_year = (
            CarbonEntry.objects.filter(establishment=establishment)
            .order_by("-year")
            .values_list("year", flat=True)
            .first()
        )

        if not latest_year:
            continue

        # Calculate carbon score for this establishment
        entries = CarbonEntry.objects.filter(establishment=establishment, year=latest_year)
        total_emissions = entries.filter(type="emission").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
        total_offsets = entries.filter(type="offset").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0

        # Get industry benchmark if available
        industry_benchmark = 0
        if hasattr(establishment, "industry"):
            benchmark = CarbonBenchmark.objects.filter(industry=establishment.industry, year=latest_year).first()
            if benchmark:
                industry_benchmark = benchmark.average_emissions

        # Calculate carbon score
        carbon_score = CarbonEntry.calculate_carbon_score(
            total_emissions=total_emissions, total_offsets=total_offsets, industry_benchmark=industry_benchmark
        )

        # Award badges based on score
        for badge in automatic_badges:
            if carbon_score >= badge.minimum_score:
                badge.establishments.add(establishment)

    # Process productions
    for production in productions:
        # Calculate carbon score for this production
        entries = CarbonEntry.objects.filter(production=production)
        total_emissions = entries.filter(type="emission").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0
        total_offsets = entries.filter(type="offset").aggregate(Sum("co2e_amount"))["co2e_amount__sum"] or 0

        # Get industry benchmark if available
        industry_benchmark = 0
        if hasattr(production.establishment, "industry"):
            benchmark = CarbonBenchmark.objects.filter(
                industry=production.establishment.industry, year=production.year
            ).first()
            if benchmark:
                industry_benchmark = benchmark.average_emissions

        # Calculate carbon score
        carbon_score = CarbonEntry.calculate_carbon_score(
            total_emissions=total_emissions, total_offsets=total_offsets, industry_benchmark=industry_benchmark
        )

        # Award badges based on score
        for badge in automatic_badges:
            if carbon_score >= badge.minimum_score:
                badge.productions.add(production)


@shared_task
def cleanup_old_audit_logs():
    """Clean up audit logs older than 1 year."""
    one_year_ago = timezone.now() - timedelta(days=365)
    CarbonAuditLog.objects.filter(timestamp__lt=one_year_ago).delete()


@shared_task
def update_industry_benchmarks():
    """Update industry benchmarks based on recent data."""
    current_year = timezone.now().year

    # Calculate average emissions by industry
    benchmarks = (
        CarbonEntry.objects.filter(year=current_year, type="emission")
        .values("establishment__industry")
        .annotate(average_emissions=Avg("co2e_amount"))
    )

    # Update or create benchmarks
    for benchmark in benchmarks:
        CarbonBenchmark.objects.update_or_create(
            year=current_year,
            industry=benchmark["establishment__industry"],
            defaults={"average_emissions": benchmark["average_emissions"], "updated_at": timezone.now()},
        )


# ---------------------------------------------------------------------------
# Blockchain tasks
# ---------------------------------------------------------------------------


@shared_task(bind=True)
def batch_submit_monthly_summaries(self):
    """
    Monthly reconciliation sweep for blockchain submissions.
    Runs on 1st of each month at 2:00 AM UTC.

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
            # A production is "finalized" when finish_date is set.
            # A production is "not yet on blockchain" when extra_data has no
            # blockchain_tx_hash, or extra_data is null.
            productions = History.objects.filter(
                parcel__establishment__company=company,
                finish_date__isnull=False,
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


def _submit_single_production_to_blockchain(production, company, blockchain_service):
    """
    Submit a single finalized production to blockchain.

    Extracted from batch_submit_monthly_summaries so it can be called from:
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
        logger.info(f"Production {production.id} already on blockchain, skipping")
        return True

    # Get ALL carbon entries for this production (entire lifecycle)
    carbon_entries = CarbonEntry.objects.filter(production=production)

    if not carbon_entries.exists():
        logger.info(f"No carbon entries for production {production.id}, skipping")
        return False

    # Calculate total production summary
    summary_data = carbon_entries.aggregate(total_co2e=Sum("co2e_amount"), entry_count=Count("id"))
    total_co2e = summary_data["total_co2e"] or 0
    entry_count = summary_data["entry_count"] or 0

    # Include finalization hash — connects event integrity to
    # the on-chain record:
    # events -> finalization_hash -> production_hash -> blockchain
    finalization_hash = None
    finalization_event_count = 0
    if production.extra_data and isinstance(production.extra_data, dict):
        finalization_hash = production.extra_data.get("finalization_hash")
        finalization_event_count = production.extra_data.get("finalization_event_count", 0)

    # Build the complete production record for hashing
    raw_data = {
        "production_id": production.id,
        "company_id": company.id,
        "start_date": (production.start_date.isoformat() if production.start_date else None),
        "finish_date": (production.finish_date.isoformat() if production.finish_date else None),
        "total_co2e": float(total_co2e),
        "entry_count": entry_count,
        "entries": list(carbon_entries.values("id", "co2e_amount", "type", "timestamp")),
        "finalization_hash": finalization_hash,
        "finalization_event_count": finalization_event_count,
    }

    # Use keccak256 to match Solidity contract, fallback to SHA-256
    sorted_raw = json.dumps(raw_data, sort_keys=True, default=str)
    try:
        from web3 import Web3

        raw_hex = Web3.keccak(text=sorted_raw).hex()
        data_hash = raw_hex.removeprefix("0x")
    except ImportError:
        data_hash = hashlib.sha256(sorted_raw.encode()).hexdigest()

    # Submit to blockchain
    logger.info(
        f"Submitting production {production.id} to blockchain " f"({entry_count} entries, {total_co2e} kg CO2e)"
    )

    blockchain_result = blockchain_service.submit_monthly_summary(
        producer_id=company.id,
        production_id=production.id,
        total_co2e=total_co2e,
        data_hash=data_hash,
        raw_data=raw_data,
    )

    if blockchain_result and blockchain_result.get("success"):
        logger.info(f"Successfully submitted production {production.id}")
        logger.info(f"Transaction hash: {blockchain_result.get('transaction_hash')}")

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
        logger.error(f"Failed to submit production {production.id}: {blockchain_result}")
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
    try:
        from history.models import History

        production = History.objects.select_related("parcel__establishment__company").get(id=production_id)

        company = (
            production.parcel.establishment.company if production.parcel and production.parcel.establishment else None
        )
        if not company:
            logger.error(f"No company found for production {production_id}")
            return {"status": "error", "error": "No company found"}

        if not company.blockchain_subscription_status:
            logger.info(f"Company {company.id} has no blockchain subscription, skipping production {production_id}")
            return {"status": "skipped", "reason": "no_blockchain_subscription"}

        from .services.blockchain import BlockchainCarbonService

        blockchain_service = BlockchainCarbonService()
        success = _submit_single_production_to_blockchain(production, company, blockchain_service)

        if success:
            return {
                "status": "success",
                "production_id": production_id,
                "tx_hash": (production.extra_data or {}).get("blockchain_tx_hash"),
            }
        else:
            raise Exception(f"Blockchain submission failed for production {production_id}")

    except History.DoesNotExist:
        logger.error(f"Production {production_id} not found")
        return {"status": "error", "error": "Production not found"}
    except Exception as e:
        logger.error(f"Error submitting production {production_id} to blockchain: {e}")
        raise self.retry(countdown=30, exc=e)


@shared_task
def issue_carbon_credits(production_id, credits_amount):
    """
    Issue carbon credits for verified production on blockchain
    """
    try:
        from .services.blockchain import BlockchainCarbonService

        blockchain_service = BlockchainCarbonService()

        production = ProductionTemplate.objects.get(id=production_id)
        company = production.parcel.establishment.company

        # Only process if company has blockchain subscription
        if not company.blockchain_subscription_status:
            logger.info(f"Company {company.name} does not have blockchain subscription, skipping credit issuance")
            return {"status": "skipped", "reason": "no_blockchain_subscription"}

        # Issue credits on blockchain
        credits_result = blockchain_service.issue_credits(production_id, credits_amount)

        logger.info(f"Credits issued for production {production_id}: {credits_result}")

        return {
            "status": "completed",
            "production_id": production_id,
            "credits_amount": credits_amount,
            "credits_result": credits_result,
        }

    except ProductionTemplate.DoesNotExist:
        logger.error(f"Production {production_id} not found")
        return {"status": "error", "message": "Production not found"}
    except Exception as e:
        logger.error(f"Error issuing credits for production {production_id}: {str(e)}")
        return {"status": "error", "message": str(e)}
