"""
Django management command to create demo billing data for development.

This command creates fake payment methods and invoices for testing the billing interface
when you don't have real Stripe data. Useful for development and testing.

Usage:
    python manage.py create_demo_billing_data
    python manage.py create_demo_billing_data --company-id 8
    python manage.py create_demo_billing_data --clean
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from company.models import Company
from subscriptions.models import Subscription, PaymentMethod, Invoice
from decimal import Decimal
import uuid


class Command(BaseCommand):
    help = "Create demo billing data for development testing"

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            type=int,
            help='Create demo data for specific company ID only'
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Remove existing demo data before creating new'
        )

    def handle(self, *args, **options):
        company_id = options.get('company_id')
        clean = options.get('clean', False)

        self.stdout.write("🎭 Creating demo billing data for development...")

        # Get companies to create data for
        if company_id:
            try:
                companies = [Company.objects.get(id=company_id)]
            except Company.DoesNotExist:
                raise CommandError(f"Company with ID {company_id} not found")
        else:
            companies = Company.objects.filter(subscription__isnull=False).distinct()

        if not companies:
            self.stdout.write(
                self.style.WARNING("⚠️  No companies with subscriptions found")
            )
            return

        for company in companies:
            self.stdout.write(f"\n📊 Processing company: {company.name} (ID: {company.id})")
            
            if clean:
                self.clean_demo_data(company)
            
            self.create_demo_data(company)

        self.stdout.write(f"\n{'='*50}")
        self.stdout.write(
            self.style.SUCCESS("✅ Demo billing data created successfully!")
        )
        self.stdout.write(
            self.style.WARNING("⚠️  This is DEMO data for development only!")
        )

    def clean_demo_data(self, company):
        """Remove existing demo data for company"""
        self.stdout.write("   🧹 Cleaning existing demo data...")
        
        # Delete existing payment methods and invoices
        pm_deleted = PaymentMethod.objects.filter(company=company).delete()[0]
        inv_deleted = Invoice.objects.filter(company=company).delete()[0]
        
        self.stdout.write(f"   🗑️  Removed {pm_deleted} payment methods, {inv_deleted} invoices")

    def create_demo_data(self, company):
        """Create demo billing data for company"""
        try:
            subscription = company.subscription
            if not subscription:
                self.stdout.write(
                    self.style.WARNING(f"⚠️  No subscription for {company.name}")
                )
                return

            # Create demo payment methods
            self.create_demo_payment_methods(company)
            
            # Create demo invoices  
            self.create_demo_invoices(company, subscription)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"❌ Error creating demo data for {company.name}: {str(e)}")
            )

    def create_demo_payment_methods(self, company):
        """Create demo payment methods"""
        self.stdout.write("   💳 Creating demo payment methods...")

        payment_methods_data = [
            {
                'stripe_payment_method_id': f'pm_demo_{uuid.uuid4().hex[:8]}',
                'card_brand': 'visa',
                'last_4': '4242',
                'exp_month': 12,
                'exp_year': 2025,
                'is_default': True,
            },
            {
                'stripe_payment_method_id': f'pm_demo_{uuid.uuid4().hex[:8]}',
                'card_brand': 'mastercard', 
                'last_4': '5555',
                'exp_month': 8,
                'exp_year': 2026,
                'is_default': False,
            },
        ]

        for pm_data in payment_methods_data:
            payment_method = PaymentMethod.objects.create(
                company=company,
                **pm_data
            )
            default_text = " (Default)" if pm_data['is_default'] else ""
            self.stdout.write(
                f"     ➕ Created: {pm_data['card_brand'].title()} ••••{pm_data['last_4']}{default_text}"
            )

    def create_demo_invoices(self, company, subscription):
        """Create demo invoices"""
        self.stdout.write("   🧾 Creating demo invoices...")

        # Calculate dates for last 3 months
        now = timezone.now()
        
        invoices_data = [
            {
                'stripe_invoice_id': f'in_demo_{uuid.uuid4().hex[:8]}',
                'amount': Decimal('499.00'),
                'status': 'paid',
                'invoice_date': now.replace(day=1),
                'due_date': None,
                'invoice_pdf': f'https://pay.stripe.com/invoice/acct_demo/invst_demo_{uuid.uuid4().hex[:8]}/pdf',
            },
            {
                'stripe_invoice_id': f'in_demo_{uuid.uuid4().hex[:8]}',
                'amount': Decimal('499.00'),
                'status': 'paid',
                'invoice_date': now.replace(month=max(1, now.month-1), day=1),
                'due_date': None,
                'invoice_pdf': f'https://pay.stripe.com/invoice/acct_demo/invst_demo_{uuid.uuid4().hex[:8]}/pdf',
            },
            {
                'stripe_invoice_id': f'in_demo_{uuid.uuid4().hex[:8]}',
                'amount': Decimal('499.00'),
                'status': 'paid',
                'invoice_date': now.replace(month=max(1, now.month-2), day=1),
                'due_date': None,
                'invoice_pdf': f'https://pay.stripe.com/invoice/acct_demo/invst_demo_{uuid.uuid4().hex[:8]}/pdf',
            },
        ]

        for inv_data in invoices_data:
            invoice = Invoice.objects.create(
                company=company,
                subscription=subscription,
                **inv_data
            )
            invoice_id = inv_data['stripe_invoice_id']
            self.stdout.write(
                f"     ➕ Created: {invoice_id} (${inv_data['amount']})"
            )