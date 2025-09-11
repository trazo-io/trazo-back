from django.core.management.base import BaseCommand
from django.db import transaction
import re

from history.models import ChemicalEvent, ProductionEvent, GeneralEvent


class Command(BaseCommand):
    help = "Update test content in existing events to professional consumer messaging"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update without confirmation",
        )

    def handle(self, *args, **options):
        """Update test content to professional messaging"""

        dry_run = options.get("dry_run", False)
        force_update = options.get("force", False)

        self.stdout.write(self.style.SUCCESS("🔄 UPDATING TEST CONTENT TO PROFESSIONAL MESSAGING"))
        self.stdout.write("=" * 70)

        # Count events to update
        test_events = self.count_test_events()
        total_updates = sum(test_events.values())

        if total_updates == 0:
            self.stdout.write(self.style.SUCCESS("✅ No test content found - all events already have professional messaging"))
            return

        self.stdout.write(f"📊 Found {total_updates} events with test content:")
        for event_type, count in test_events.items():
            if count > 0:
                self.stdout.write(f"   • {event_type}: {count} events")

        if dry_run:
            self.stdout.write(f"\n🔍 DRY RUN MODE - Showing what would be updated:")
            self.preview_updates()
            return

        if not force_update:
            confirm = input(f"\nUpdate {total_updates} events to professional messaging? (y/N): ")
            if confirm.lower() not in ['y', 'yes']:
                self.stdout.write("❌ Update cancelled")
                return

        # Perform updates
        with transaction.atomic():
            updated_count = self.update_all_events()
            
        self.stdout.write(f"\n🎉 SUCCESS: Updated {updated_count} events to professional messaging")
        self.stdout.write("\n📱 QR transparency pages now show professional consumer content!")

    def count_test_events(self):
        """Count events with test content"""
        return {
            "ChemicalEvent": ChemicalEvent.objects.filter(
                description__icontains="Test event for QR transparency"
            ).count(),
            "ProductionEvent": ProductionEvent.objects.filter(
                description__icontains="Test event for QR transparency"
            ).count(), 
            "GeneralEvent": GeneralEvent.objects.filter(
                description__icontains="Test event for QR transparency"
            ).count(),
        }

    def preview_updates(self):
        """Preview what would be updated"""
        
        self.stdout.write("\n🔍 Chemical Events to update:")
        chemical_events = ChemicalEvent.objects.filter(
            description__icontains="Test event for QR transparency"
        )[:3]
        for event in chemical_events:
            old_desc = event.description
            new_desc = self.create_professional_description(event.description)
            self.stdout.write(f"   OLD: {old_desc}")
            self.stdout.write(f"   NEW: {new_desc}")
            self.stdout.write("")

        self.stdout.write("🔍 Production Events to update:")
        production_events = ProductionEvent.objects.filter(
            description__icontains="Test event for QR transparency"
        )[:3]
        for event in production_events:
            old_desc = event.description
            new_desc = self.create_professional_description(event.description)
            self.stdout.write(f"   OLD: {old_desc}")
            self.stdout.write(f"   NEW: {new_desc}")
            self.stdout.write("")

    def update_all_events(self):
        """Update all events with test content"""
        
        updated_count = 0

        # Update Chemical Events
        chemical_events = ChemicalEvent.objects.filter(
            description__icontains="Test event for QR transparency"
        )
        for event in chemical_events:
            event.description = self.create_professional_description(event.description)
            # Only update description first, skip other fields for now
            event.save(update_fields=['description'])
            updated_count += 1

        # Update Production Events
        production_events = ProductionEvent.objects.filter(
            description__icontains="Test event for QR transparency"
        )
        for event in production_events:
            event.description = self.create_professional_description(event.description)
            # Only update description first, skip other fields for now
            event.save(update_fields=['description'])
            updated_count += 1

        # Update General Events
        general_events = GeneralEvent.objects.filter(
            description__icontains="Test event for QR transparency"
        )
        for event in general_events:
            event.description = self.create_professional_description(event.description)
            # Only update description first, skip other fields for now
            event.save(update_fields=['description'])
            updated_count += 1

        return updated_count

    def create_professional_description(self, old_description):
        """Convert test description to professional messaging"""
        
        # Extract event name from "Test event for QR transparency: EventName"
        match = re.search(r"Test event for QR transparency: (.+)", old_description)
        if match:
            event_name = match.group(1).lower()
            
            # Try full version first
            full_desc = f"Applied {event_name} for sustainable farming"
            if len(full_desc) <= 60:
                return full_desc
            
            # If too long, use abbreviated version
            # Truncate event name to fit within 60 chars
            max_name_length = 60 - len("Applied  for sustainable farming")  # 32 chars for the template
            if len(event_name) > max_name_length:
                event_name = event_name[:max_name_length-3] + "..."
            
            return f"Applied {event_name} for sustainable farming"
        
        # Fallback for other test patterns
        return old_description.replace("Test event for QR transparency", "Sustainable farming practice")

    def create_professional_observation(self, old_observation):
        """Convert test observation to professional messaging"""
        
        # Extract event name from "Test transparency event: EventName"  
        match = re.search(r"Test transparency event: (.+)", old_observation)
        if match:
            # Keep it shorter
            return "Sustainable practice for soil health optimization"
        
        # Fallback for other test patterns
        return old_observation.replace("Test transparency event", "Professional practice")