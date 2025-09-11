#!/usr/bin/env python
"""
Script to create carbon entries specifically for Production ID 125
"""

import os
import sys

import django

# Setup Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings.dev")
django.setup()

from django.contrib.auth import get_user_model

from carbon.models import CarbonEntry, CarbonSource
from carbon.services.event_carbon_calculator import EventCarbonCalculator
from history.models import ChemicalEvent, GeneralEvent, History, ProductionEvent

User = get_user_model()


def create_carbon_entries_for_production_125():
    """Create carbon entries for Production ID 125"""

    try:
        # Get Production 125
        production = History.objects.get(id=125)
        print(f"Found production: {production.name}")

        # Get a user for the entries
        user = User.objects.first()  # Use any existing user
        print(f"Using user: {user.email}")

        # Initialize calculator
        calculator = EventCarbonCalculator()

        entries_created = 0

        # Process Chemical Events
        chemical_events = ChemicalEvent.objects.filter(history=production)
        print(f"Found {chemical_events.count()} chemical events")

        for event in chemical_events:
            try:
                # Calculate carbon impact
                calculation_result = calculator.calculate_chemical_event_impact(event)
                print(f"  Chemical Event {event.id}: {calculation_result.get('co2e', 0):.2f} kg CO2e")

                # Create carbon entry
                carbon_entry = create_carbon_entry_from_calculation(event, calculation_result, user)
                if carbon_entry:
                    entries_created += 1
                    print(f"    Created CarbonEntry {carbon_entry.id}")

            except Exception as e:
                print(f"    Error processing chemical event {event.id}: {e}")

        # Process Production Events
        production_events = ProductionEvent.objects.filter(history=production)
        print(f"Found {production_events.count()} production events")

        for event in production_events:
            try:
                # Calculate carbon impact
                calculation_result = calculator.calculate_production_event_impact(event)
                print(f"  Production Event {event.id}: {calculation_result.get('co2e', 0):.2f} kg CO2e")

                # Create carbon entry
                carbon_entry = create_carbon_entry_from_calculation(event, calculation_result, user)
                if carbon_entry:
                    entries_created += 1
                    print(f"    Created CarbonEntry {carbon_entry.id}")

            except Exception as e:
                print(f"    Error processing production event {event.id}: {e}")

        # Process General Events
        general_events = GeneralEvent.objects.filter(history=production)
        print(f"Found {general_events.count()} general events")

        for event in general_events:
            try:
                # Calculate carbon impact
                calculation_result = calculator.calculate_general_event_impact(event)
                print(f"  General Event {event.id} ({event.name}): {calculation_result.get('co2e', 0):.2f} kg CO2e")

                # Create carbon entry
                carbon_entry = create_carbon_entry_from_calculation(event, calculation_result, user)
                if carbon_entry:
                    entries_created += 1
                    print(f"    Created CarbonEntry {carbon_entry.id}")

            except Exception as e:
                print(f"    Error processing general event {event.id}: {e}")

        print(f"\n✅ SUMMARY:")
        print(f"Total Carbon Entries Created: {entries_created}")

        # Verify the results
        print("\n🔍 VERIFICATION:")
        carbon_entries = CarbonEntry.objects.filter(production_id=125)
        total_emissions = sum(entry.amount for entry in carbon_entries if entry.type == "emission")
        total_offsets = sum(entry.amount for entry in carbon_entries if entry.type == "offset")

        print(f"Total Carbon Entries in DB: {carbon_entries.count()}")
        print(f"Total Emissions: {total_emissions:.2f} kg CO2e")
        print(f"Total Offsets: {total_offsets:.2f} kg CO2e")
        print(f"Net Carbon: {total_emissions - total_offsets:.2f} kg CO2e")

        # Update confidence and transparency scores
        production.update_trust_metrics()
        print(
            f"Updated trust metrics - Confidence: {production.confidence_score}%, Transparency: {production.transparency_score}%"
        )

    except History.DoesNotExist:
        print("❌ Production ID 125 not found")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()


def create_carbon_entry_from_calculation(event, calculation_result, user):
    """Create a carbon entry from event calculation result"""
    try:
        # Get or create carbon source
        source_name = (
            f"{event.__class__.__name__} - {getattr(event, 'commercial_name', getattr(event, 'name', 'Unknown'))}"
        )
        carbon_source, created = CarbonSource.objects.get_or_create(
            name=source_name,
            defaults={
                "category": event.__class__.__name__,
                "unit": "kg CO2e",
                "default_emission_factor": calculation_result.get("co2e", 0),
                "usda_verified": calculation_result.get("usda_factors_based", False),
                "verification_status": calculation_result.get("verification_status", "estimated"),
                "data_source": calculation_result.get("data_source", "Event Calculation"),
            },
        )

        co2e = calculation_result.get("co2e", 0)
        if co2e == 0:
            return None  # Skip zero emissions

        # Create carbon entry
        carbon_entry = CarbonEntry.objects.create(
            establishment_id=event.history.parcel.establishment.id if event.history.parcel else None,
            production_id=event.history.id,
            type="emission" if co2e > 0 else "offset",
            source=carbon_source,
            amount=abs(co2e),
            co2e_amount=co2e,
            year=event.date.year,
            description=f"Auto-calculated from {event.__class__.__name__} event: {calculation_result.get('calculation_method', 'unknown')}",
            usda_factors_based=calculation_result.get("usda_factors_based", False),
            verification_status=calculation_result.get("verification_status", "estimated"),
            data_source=calculation_result.get("data_source", "Event Calculation"),
            created_by=user,
            timestamp=event.date,
        )

        return carbon_entry

    except Exception as e:
        print(f"Error creating carbon entry: {e}")
        return None


if __name__ == "__main__":
    create_carbon_entries_for_production_125()
