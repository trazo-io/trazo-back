"""
Management command to publish all finished productions for public transparency
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from history.models import History


class Command(BaseCommand):
    help = 'Publish all finished productions to make them accessible via QR code scanning'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🌾 Publishing finished productions...'))
        
        # Get all histories
        all_histories = History.objects.all()
        self.stdout.write(f'Total productions: {all_histories.count()}')
        
        # Count current published status
        published_before = History.objects.filter(published=True).count()
        unpublished_before = History.objects.filter(published=False).count()
        self.stdout.write(f'Currently published: {published_before}')
        self.stdout.write(f'Currently unpublished: {unpublished_before}')
        
        # Publish all unpublished productions that should be public
        updated_count = 0
        
        for history in all_histories.filter(published=False):
            should_publish = False
            reason = ""
            
            # Check if production is finished based on various criteria
            
            # 1. If it has a finish date that has passed
            if history.finish_date and history.finish_date <= timezone.now().date():
                should_publish = True
                reason = "has finish date in the past"
            
            # 2. If it's from a previous year based on start date
            elif history.start_date and history.start_date.year < timezone.now().year:
                should_publish = True
                reason = "from previous year"
            
            # 3. If it has a QR code (indicating it's ready for public viewing)
            elif history.qr_code:
                should_publish = True
                reason = "has QR code"
            
            # 4. If it has production amount (indicating harvest/completion)
            elif history.production_amount and history.production_amount > 0:
                should_publish = True
                reason = "has production amount"
            
            # 5. If it has multiple events (indicating active/completed production)
            elif history.events.count() >= 3:
                should_publish = True
                reason = f"has {history.events.count()} events"
            
            if should_publish:
                history.published = True
                history.save()
                updated_count += 1
                
                product_name = history.product.name if history.product else "Unknown Product"
                establishment = history.parcel.establishment.name if history.parcel and history.parcel.establishment else "Unknown"
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f'   ✅ Published: {product_name} at {establishment} (ID: {history.id}) - {reason}'
                    )
                )
        
        # Show summary
        published_after = History.objects.filter(published=True).count()
        
        self.stdout.write('\n📊 Publishing Summary:')
        self.stdout.write(f'   Published before: {published_before}')
        self.stdout.write(f'   Published after: {published_after}')
        self.stdout.write(f'   Newly published: {updated_count}')
        
        # Show all published productions with their public URLs
        self.stdout.write('\n🌐 All Published Productions:')
        published = History.objects.filter(published=True).select_related(
            'product', 'parcel__establishment'
        ).order_by('parcel__establishment', 'product__name')
        
        current_establishment = None
        for history in published:
            establishment = history.parcel.establishment if history.parcel else None
            establishment_name = establishment.name if establishment else 'Unknown'
            
            # Group by establishment
            if establishment_name != current_establishment:
                current_establishment = establishment_name
                self.stdout.write(f'\n🏢 {establishment_name}:')
            
            product_name = history.product.name if history.product else 'Unknown Product'
            
            # Show production info
            self.stdout.write(f'   📦 {product_name} (ID: {history.id})')
            
            # Show dates if available
            if history.start_date and history.finish_date:
                self.stdout.write(f'      Period: {history.start_date} to {history.finish_date}')
            elif history.start_date:
                self.stdout.write(f'      Started: {history.start_date}')
            
            # Show production amount if available
            if history.production_amount:
                self.stdout.write(f'      Production: {history.production_amount} units')
            
            # Show QR code info
            if history.qr_code:
                self.stdout.write(f'      QR Code: ✓ Available')
                self.stdout.write(f'      Public URL: http://app.localhost:3000/api/histories/{history.id}/public_history/')
            else:
                self.stdout.write(f'      QR Code: ✗ Not generated')
        
        # Final message
        self.stdout.write(
            self.style.SUCCESS(
                f'\n✅ All finished productions are now published and accessible via QR code scanning!'
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f'🔗 Consumers can now scan QR codes to view full production transparency data'
            )
        )