"""
Django management command to sync Stripe billing data to local database.

This command fetches payment methods, invoices, and other billing data from Stripe
and creates corresponding records in the local database. This is especially useful
for local development environments where webhooks cannot be received.

Usage:
    python manage.py sync_stripe_data
    python manage.py sync_stripe_data --company-id 1
    python manage.py sync_stripe_data --dry-run
"""

import stripe
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.db import transaction
from company.models import Company
from subscriptions.models import Subscription, PaymentMethod, Invoice
from subscriptions.serializers import SubscriptionSerializer
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Stripe billing data (payment methods, invoices) to local database"

    def add_arguments(self, parser):
        parser.add_argument(
            '--company-id',
            type=int,
            help='Sync data for specific company ID only'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without making changes'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update existing records'
        )

    def handle(self, *args, **options):
        # Initialize Stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        if not stripe.api_key:
            raise CommandError("STRIPE_SECRET_KEY not configured in settings")

        self.dry_run = options.get('dry_run', False)
        self.force = options.get('force', False)
        company_id = options.get('company_id')

        if self.dry_run:
            self.stdout.write(
                self.style.WARNING("🔍 DRY RUN MODE - No changes will be made")
            )

        self.stdout.write("🔄 Starting Stripe data synchronization...")

        # Get companies to sync
        if company_id:
            try:
                companies = [Company.objects.get(id=company_id)]
            except Company.DoesNotExist:
                raise CommandError(f"Company with ID {company_id} not found")
        else:
            # Get companies that have a subscription
            companies = Company.objects.filter(subscription__isnull=False).distinct()

        if not companies:
            self.stdout.write(
                self.style.WARNING("⚠️  No companies with subscriptions found")
            )
            return

        total_synced = 0
        total_errors = 0

        for company in companies:
            self.stdout.write(f"\n📊 Processing company: {company.name} (ID: {company.id})")
            
            try:
                synced, errors = self.sync_company_data(company)
                total_synced += synced
                total_errors += errors
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"❌ Error processing {company.name}: {str(e)}")
                )
                total_errors += 1

        # Summary
        self.stdout.write(f"\n{'='*50}")
        if self.dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"📋 DRY RUN COMPLETE: Would sync {total_synced} records"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✅ SYNC COMPLETE: {total_synced} records synced, {total_errors} errors"
                )
            )

    def sync_company_data(self, company):
        """Sync all billing data for a specific company"""
        synced_count = 0
        error_count = 0

        try:
            # Get company's subscription
            subscription = company.subscription
            if not subscription:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠️  No subscription found for {company.name}"
                    )
                )
                return 0, 1

            # If we have a subscription ID but no customer ID, try to get customer from subscription
            customer_id = subscription.stripe_customer_id
            
            if not customer_id and subscription.stripe_subscription_id:
                self.stdout.write(
                    f"   🔍 No customer ID, attempting to retrieve from subscription: {subscription.stripe_subscription_id}"
                )
                try:
                    stripe_sub = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
                    customer_id = stripe_sub.customer
                    if customer_id:
                        # Update the local subscription with the customer ID
                        if not self.dry_run:
                            subscription.stripe_customer_id = customer_id
                            subscription.save()
                        self.stdout.write(
                            f"   ✅ Found customer ID from subscription: {customer_id}"
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"⚠️  No customer ID found in Stripe subscription {subscription.stripe_subscription_id}"
                            )
                        )
                        return 0, 1
                except stripe.error.StripeError as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"❌ Error retrieving Stripe subscription {subscription.stripe_subscription_id}: {str(e)}"
                        )
                    )
                    return 0, 1
            elif not customer_id:
                self.stdout.write(
                    self.style.WARNING(
                        f"⚠️  No Stripe customer ID or subscription ID for {company.name}"
                    )
                )
                return 0, 1

            self.stdout.write(f"   🔍 Stripe Customer ID: {customer_id}")

            # Sync payment methods
            pm_synced, pm_errors = self.sync_payment_methods(subscription, customer_id)
            synced_count += pm_synced
            error_count += pm_errors

            # Sync invoices
            inv_synced, inv_errors = self.sync_invoices(subscription, customer_id)
            synced_count += inv_synced
            error_count += inv_errors

            # Update subscription data from Stripe
            sub_synced, sub_errors = self.sync_subscription_data(subscription)
            synced_count += sub_synced
            error_count += sub_errors

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"   ❌ Error syncing {company.name}: {str(e)}")
            )
            error_count += 1

        return synced_count, error_count

    def sync_payment_methods(self, subscription, customer_id):
        """Sync payment methods from Stripe"""
        synced = 0
        errors = 0

        self.stdout.write("   💳 Syncing payment methods...")

        try:
            # Fetch payment methods from Stripe
            payment_methods = stripe.PaymentMethod.list(
                customer=customer_id,
                type='card'
            )

            for pm in payment_methods.data:
                try:
                    # Check if payment method already exists
                    existing_pm = PaymentMethod.objects.filter(
                        stripe_payment_method_id=pm.id
                    ).first()

                    if existing_pm and not self.force:
                        self.stdout.write(
                            f"     ⏭️  Payment method {pm.id} already exists"
                        )
                        continue

                    if self.dry_run:
                        self.stdout.write(
                            f"     📝 Would create/update: {pm.card.brand} ••••{pm.card.last4}"
                        )
                        synced += 1
                        continue

                    # Create or update payment method
                    payment_method_data = {
                        'subscription': subscription,
                        'stripe_payment_method_id': pm.id,
                        'card_brand': pm.card.brand,
                        'last_4': pm.card.last4,
                        'exp_month': pm.card.exp_month,
                        'exp_year': pm.card.exp_year,
                        'is_default': False  # We'll determine this separately
                    }

                    if existing_pm:
                        # Update existing
                        for key, value in payment_method_data.items():
                            if key != 'subscription':  # Don't update subscription
                                setattr(existing_pm, key, value)
                        existing_pm.save()
                        self.stdout.write(
                            f"     🔄 Updated: {pm.card.brand} ••••{pm.card.last4}"
                        )
                    else:
                        # Create new
                        PaymentMethod.objects.create(**payment_method_data)
                        self.stdout.write(
                            f"     ➕ Created: {pm.card.brand} ••••{pm.card.last4}"
                        )

                    synced += 1

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"     ❌ Error syncing payment method {pm.id}: {str(e)}"
                        )
                    )
                    errors += 1

            # Set default payment method
            if not self.dry_run:
                self.set_default_payment_method(subscription, customer_id)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"   ❌ Error fetching payment methods: {str(e)}")
            )
            errors += 1

        return synced, errors

    def sync_invoices(self, subscription, customer_id):
        """Sync invoices from Stripe"""
        synced = 0
        errors = 0

        self.stdout.write("   🧾 Syncing invoices...")

        try:
            # Fetch invoices from Stripe
            invoices = stripe.Invoice.list(
                customer=customer_id,
                limit=50  # Get recent invoices
            )

            for inv in invoices.data:
                try:
                    # Check if invoice already exists
                    existing_invoice = Invoice.objects.filter(
                        stripe_invoice_id=inv.id
                    ).first()

                    if existing_invoice and not self.force:
                        self.stdout.write(
                            f"     ⏭️  Invoice {inv.number or inv.id} already exists"
                        )
                        continue

                    if self.dry_run:
                        amount = inv.amount_paid / 100 if inv.amount_paid else inv.total / 100
                        self.stdout.write(
                            f"     📝 Would create/update: {inv.number or inv.id} (${amount:.2f})"
                        )
                        synced += 1
                        continue

                    # Create or update invoice
                    invoice_data = {
                        'subscription': subscription,
                        'stripe_invoice_id': inv.id,
                        'number': inv.number,
                        'amount': inv.total / 100,  # Convert from cents
                        'amount_paid': inv.amount_paid / 100 if inv.amount_paid else 0,
                        'status': inv.status,
                        'invoice_date': inv.created and inv.created.timestamp(),
                        'due_date': inv.due_date and inv.due_date.timestamp(),
                        'invoice_pdf': inv.invoice_pdf,
                    }

                    if existing_invoice:
                        # Update existing
                        for key, value in invoice_data.items():
                            if key != 'subscription':  # Don't update subscription
                                setattr(existing_invoice, key, value)
                        existing_invoice.save()
                        self.stdout.write(
                            f"     🔄 Updated: {inv.number or inv.id}"
                        )
                    else:
                        # Create new
                        Invoice.objects.create(**invoice_data)
                        self.stdout.write(
                            f"     ➕ Created: {inv.number or inv.id}"
                        )

                    synced += 1

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"     ❌ Error syncing invoice {inv.id}: {str(e)}"
                        )
                    )
                    errors += 1

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"   ❌ Error fetching invoices: {str(e)}")
            )
            errors += 1

        return synced, errors

    def sync_subscription_data(self, subscription):
        """Update subscription data from Stripe"""
        synced = 0
        errors = 0

        self.stdout.write("   📋 Syncing subscription data...")

        try:
            if not subscription.stripe_subscription_id:
                self.stdout.write("     ⚠️  No Stripe subscription ID")
                return 0, 0

            # Fetch subscription from Stripe
            stripe_sub = stripe.Subscription.retrieve(
                subscription.stripe_subscription_id
            )

            if self.dry_run:
                self.stdout.write(
                    f"     📝 Would update subscription status: {stripe_sub.status}"
                )
                return 1, 0

            # Update subscription fields
            updated_fields = []
            
            if subscription.status != stripe_sub.status:
                subscription.status = stripe_sub.status
                updated_fields.append('status')

            if subscription.current_period_start != stripe_sub.current_period_start:
                subscription.current_period_start = stripe_sub.current_period_start
                updated_fields.append('current_period_start')

            if subscription.current_period_end != stripe_sub.current_period_end:
                subscription.current_period_end = stripe_sub.current_period_end
                updated_fields.append('current_period_end')

            if subscription.cancel_at_period_end != stripe_sub.cancel_at_period_end:
                subscription.cancel_at_period_end = stripe_sub.cancel_at_period_end
                updated_fields.append('cancel_at_period_end')

            if updated_fields:
                subscription.save(update_fields=updated_fields)
                self.stdout.write(
                    f"     🔄 Updated subscription fields: {', '.join(updated_fields)}"
                )
                synced += 1
            else:
                self.stdout.write("     ✅ Subscription data already up to date")

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"   ❌ Error syncing subscription: {str(e)}")
            )
            errors += 1

        return synced, errors

    def set_default_payment_method(self, subscription, customer_id):
        """Set the default payment method based on Stripe customer data"""
        try:
            # Get customer from Stripe to find default payment method
            customer = stripe.Customer.retrieve(customer_id)
            
            if customer.invoice_settings and customer.invoice_settings.default_payment_method:
                default_pm_id = customer.invoice_settings.default_payment_method
                
                # Update all payment methods to not be default
                PaymentMethod.objects.filter(subscription=subscription).update(
                    is_default=False
                )
                
                # Set the correct default
                PaymentMethod.objects.filter(
                    subscription=subscription,
                    stripe_payment_method_id=default_pm_id
                ).update(is_default=True)
                
                self.stdout.write(
                    f"     ✅ Set default payment method: {default_pm_id}"
                )

        except Exception as e:
            self.stdout.write(
                self.style.WARNING(
                    f"     ⚠️  Could not set default payment method: {str(e)}"
                )
            )