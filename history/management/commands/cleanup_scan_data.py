"""
GDPR-Compliant Data Cleanup Management Command (2025 Standards)
Automatically anonymizes expired data and deletes non-consented data

Usage:
    python manage.py cleanup_scan_data
    python manage.py cleanup_scan_data --dry-run
    python manage.py cleanup_scan_data --force-cleanup
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
import logging

from history.models import HistoryScan
from history.services.privacy_service import GDPRComplianceService


class Command(BaseCommand):
    help = 'GDPR-compliant cleanup of scan data with anonymization and deletion'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be cleaned up without making changes',
        )
        parser.add_argument(
            '--force-cleanup',
            action='store_true',
            help='Force cleanup even if retention date is in the future',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=1000,
            help='Process records in batches of this size (default: 1000)',
        )
        parser.add_argument(
            '--max-age-days',
            type=int,
            default=None,
            help='Override default retention period (use with caution)',
        )
    
    def setup_logging(self):
        """Setup logging for the cleanup process"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def handle(self, *args, **options):
        self.setup_logging()
        
        dry_run = options['dry_run']
        force_cleanup = options['force_cleanup']
        batch_size = options['batch_size']
        max_age_days = options['max_age_days']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        self.logger.info(f"Starting GDPR scan data cleanup (dry_run={dry_run})")
        
        try:
            # Step 1: Anonymize expired consented data
            anonymized_count = self.anonymize_expired_data(
                dry_run=dry_run, 
                batch_size=batch_size,
                force_cleanup=force_cleanup,
                max_age_days=max_age_days
            )
            
            # Step 2: Delete non-consented data
            deleted_count = self.delete_non_consented_data(
                dry_run=dry_run, 
                batch_size=batch_size
            )
            
            # Step 3: Clean up duplicate scans
            duplicate_cleanup_count = self.cleanup_old_duplicates(
                dry_run=dry_run,
                batch_size=batch_size
            )
            
            # Step 4: Generate report
            self.generate_cleanup_report(anonymized_count, deleted_count, duplicate_cleanup_count)
            
            self.stdout.write(
                self.style.SUCCESS(f'Cleanup completed successfully')
            )
            
        except Exception as e:
            self.logger.error(f"Cleanup failed: {str(e)}")
            raise CommandError(f'Cleanup failed: {str(e)}')
    
    def anonymize_expired_data(self, dry_run=False, batch_size=1000, force_cleanup=False, max_age_days=None):
        """
        Anonymize expired consented data according to GDPR
        """
        self.stdout.write(self.style.HTTP_INFO('Step 1: Anonymizing expired consented data...'))
        
        # Get scans that need anonymization
        if max_age_days:
            # Use custom age override
            cutoff_date = timezone.now() - timedelta(days=max_age_days)
            expired_scans = HistoryScan.objects.filter(
                consent_given=True,
                date__lt=cutoff_date
            ).exclude(ip_hash__in=['ANONYMIZED', ''])
        elif force_cleanup:
            # Force cleanup of all consented data older than 30 days
            cutoff_date = timezone.now() - timedelta(days=30)
            expired_scans = HistoryScan.objects.filter(
                consent_given=True,
                date__lt=cutoff_date
            ).exclude(ip_hash__in=['ANONYMIZED', ''])
        else:
            # Normal operation - use retention_until date
            expired_scans = GDPRComplianceService.get_scans_for_cleanup()
        
        total_to_anonymize = expired_scans.count()
        
        if total_to_anonymize == 0:
            self.stdout.write(self.style.WARNING('No scans found for anonymization'))
            return 0
        
        self.stdout.write(f'Found {total_to_anonymize} scans to anonymize')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'Would anonymize {total_to_anonymize} scans'))
            return total_to_anonymize
        
        # Process in batches
        anonymized_count = 0
        processed_count = 0
        
        for batch_start in range(0, total_to_anonymize, batch_size):
            batch_end = min(batch_start + batch_size, total_to_anonymize)
            batch_scans = expired_scans[batch_start:batch_end]
            
            with transaction.atomic():
                for scan in batch_scans:
                    if GDPRComplianceService.anonymize_scan(scan):
                        anonymized_count += 1
                    processed_count += 1
                    
                    if processed_count % 100 == 0:
                        self.stdout.write(f'Processed {processed_count}/{total_to_anonymize} scans')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully anonymized {anonymized_count} scans')
        )
        
        return anonymized_count
    
    def delete_non_consented_data(self, dry_run=False, batch_size=1000):
        """
        Delete non-consented data older than 7 days
        """
        self.stdout.write(self.style.HTTP_INFO('Step 2: Deleting non-consented data...'))
        
        # Get non-consented scans for deletion
        scans_to_delete = GDPRComplianceService.get_non_consented_scans_for_deletion()
        total_to_delete = scans_to_delete.count()
        
        if total_to_delete == 0:
            self.stdout.write(self.style.WARNING('No non-consented scans found for deletion'))
            return 0
        
        self.stdout.write(f'Found {total_to_delete} non-consented scans to delete')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'Would delete {total_to_delete} non-consented scans'))
            return total_to_delete
        
        # Delete in batches to avoid memory issues
        deleted_count = 0
        
        while scans_to_delete.exists():
            batch = list(scans_to_delete[:batch_size])
            batch_ids = [scan.id for scan in batch]
            
            with transaction.atomic():
                deleted_in_batch, _ = HistoryScan.objects.filter(id__in=batch_ids).delete()
                deleted_count += deleted_in_batch
                
                self.stdout.write(f'Deleted batch: {deleted_in_batch} scans')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully deleted {deleted_count} non-consented scans')
        )
        
        return deleted_count
    
    def cleanup_old_duplicates(self, dry_run=False, batch_size=1000, days_old=90):
        """
        Clean up very old duplicate scans to save storage
        """
        self.stdout.write(self.style.HTTP_INFO('Step 3: Cleaning up old duplicate scans...'))
        
        cutoff_date = timezone.now() - timedelta(days=days_old)
        
        old_duplicates = HistoryScan.objects.filter(
            is_duplicate=True,
            date__lt=cutoff_date
        )
        
        total_duplicates = old_duplicates.count()
        
        if total_duplicates == 0:
            self.stdout.write(self.style.WARNING('No old duplicate scans found for cleanup'))
            return 0
        
        self.stdout.write(f'Found {total_duplicates} old duplicate scans to clean up')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(f'Would delete {total_duplicates} old duplicate scans'))
            return total_duplicates
        
        # Delete in batches
        deleted_count = 0
        
        while old_duplicates.exists():
            batch_ids = list(old_duplicates[:batch_size].values_list('id', flat=True))
            
            with transaction.atomic():
                deleted_in_batch, _ = HistoryScan.objects.filter(id__in=batch_ids).delete()
                deleted_count += deleted_in_batch
                
                self.stdout.write(f'Deleted duplicate batch: {deleted_in_batch} scans')
        
        self.stdout.write(
            self.style.SUCCESS(f'Successfully deleted {deleted_count} old duplicate scans')
        )
        
        return deleted_count
    
    def generate_cleanup_report(self, anonymized_count, deleted_count, duplicate_cleanup_count):
        """
        Generate a summary report of the cleanup operation
        """
        self.stdout.write(self.style.HTTP_INFO('\n=== CLEANUP REPORT ==='))
        
        # Current database state
        total_scans = HistoryScan.objects.count()
        consented_scans = HistoryScan.objects.filter(consent_given=True).count()
        anonymized_scans = HistoryScan.objects.filter(ip_hash='ANONYMIZED').count()
        duplicate_scans = HistoryScan.objects.filter(is_duplicate=True).count()
        
        self.stdout.write(f'Anonymized scans: {anonymized_count}')
        self.stdout.write(f'Deleted non-consented scans: {deleted_count}')
        self.stdout.write(f'Deleted old duplicates: {duplicate_cleanup_count}')
        self.stdout.write(f'')
        self.stdout.write(f'Current database state:')
        self.stdout.write(f'  Total scans: {total_scans}')
        self.stdout.write(f'  Consented scans: {consented_scans}')
        self.stdout.write(f'  Anonymized scans: {anonymized_scans}')
        self.stdout.write(f'  Duplicate scans: {duplicate_scans}')
        
        # Privacy compliance check
        privacy_compliant_scans = HistoryScan.objects.filter(
            ip_hash__isnull=False,
            consent_given=True
        ).exclude(ip_hash='').count()
        
        if total_scans > 0:
            compliance_rate = (privacy_compliant_scans / total_scans) * 100
            self.stdout.write(f'  Privacy compliance rate: {compliance_rate:.1f}%')
        
        self.stdout.write(self.style.HTTP_INFO('======================\n'))
    
    def get_retention_stats(self):
        """
        Get statistics about data retention and upcoming cleanups
        """
        now = timezone.now()
        
        # Scans expiring in the next 30 days
        upcoming_expiry = HistoryScan.objects.filter(
            data_retention_until__lte=now + timedelta(days=30),
            data_retention_until__gt=now,
            consent_given=True
        ).exclude(ip_hash='ANONYMIZED').count()
        
        # Non-consented scans older than 7 days
        overdue_deletion = GDPRComplianceService.get_non_consented_scans_for_deletion().count()
        
        return {
            'upcoming_expiry_30_days': upcoming_expiry,
            'overdue_deletion': overdue_deletion
        }