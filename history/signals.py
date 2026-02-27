from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from carbon.services.event_carbon_calculator import EventCarbonCalculator

from .models import (
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)


@receiver(post_save, sender=ChemicalEvent)
def calculate_chemical_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact when a chemical event is created or updated

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-24): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like volume_applied are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = EventCarbonCalculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            # Try both new format (with ID) and old format (without ID)
            event_id_pattern = f"ChemicalEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            # that match by source or other criteria for this specific event
            if deleted_count == 0:
                # For older entries without event ID in description, we need a different approach
                # Try matching by registry_verification_id which should have the event ID
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-ChemicalEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for ChemicalEvent {instance.id} (update)")

        calculation_result = calculator.calculate_chemical_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        co2e_value = calculation_result.get("co2e", 0)
        if abs(co2e_value) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(f"✅ Carbon calculation {action} for Chemical Event {instance.id}: {calculation_result['co2e']} kg CO2e")

    except Exception as e:
        print(f"❌ Error calculating carbon for Chemical Event {instance.id}: {e}")


@receiver(post_save, sender=ProductionEvent)
def calculate_production_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact when a production event is created or updated

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-24): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry

        calculator = EventCarbonCalculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Try both new format (with ID) and old format (using registry_verification_id)
            event_id_pattern = f"ProductionEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-ProductionEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for ProductionEvent {instance.id} (update)")

        calculation_result = calculator.calculate_production_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        if calculation_result.get("co2e", 0) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Production Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        print(f"❌ Error calculating carbon for Production Event {instance.id}: {e}")


@receiver(post_save, sender=WeatherEvent)
def calculate_weather_event_carbon(sender, instance, created, **kwargs):
    """
    Weather events are TRANSPARENCY DOCUMENTATION ONLY - they don't generate emissions.

    Weather events document environmental conditions (frost, drought, hailstorm) for
    agricultural transparency. They are NOT farmer responses that generate emissions.

    Per Trazo's transparency-first transformation: weather events provide transparency
    value without carbon emissions.

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.
    """
    if created or kwargs.get("update_fields"):
        try:
            # Weather events don't create carbon entries (no emissions)
            # But we log for transparency tracking
            print(
                f"✅ Transparency documentation recorded for Weather Event {instance.id}: 0.0 kg CO2e (transparency value only)"
            )

        except Exception as e:
            print(f"❌ Error recording transparency for Weather Event {instance.id}: {e}")


@receiver(post_save, sender=GeneralEvent)
def calculate_general_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate minimal carbon impact for general events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.
    """
    if created:  # Only for new general events
        try:
            from carbon.services.event_carbon_calculator import EventCarbonCalculator

            calculator = EventCarbonCalculator()

            # General events have minimal standard carbon impact
            calculation_result = {
                "co2e": 0.1,  # Minimal impact
                "efficiency_score": 50.0,
                "usda_factors_based": False,
                "verification_status": "estimated",
                "calculation_method": "general_event_standard",
                "data_source": "Industry Standards",
                "recommendations": [],
                "event_type": "general",
                "timestamp": instance.date.isoformat() if instance.date else None,
            }

            # Only create carbon entry if the event might have actual impact
            impact_keywords = ["fuel", "energy", "transport", "machinery", "equipment"]

            # Safe string concatenation - handle None values
            name_text = instance.name or ""
            observation_text = instance.observation or ""
            combined_text = (name_text + " " + observation_text).lower()

            if any(keyword in combined_text for keyword in impact_keywords):
                carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

                print(
                    f"✅ Carbon calculation completed for General Event {instance.id}: {calculation_result['co2e']} kg CO2e"
                )
            else:
                print(
                    f"✅ General Event {instance.id} processed with minimal carbon impact: {calculation_result['co2e']} kg CO2e"
                )

        except Exception as e:
            print(f"❌ Error calculating carbon for General Event {instance.id}: {e}")
            import traceback

            traceback.print_exc()


@receiver(post_delete, sender=ChemicalEvent)
@receiver(post_delete, sender=ProductionEvent)
@receiver(post_delete, sender=WeatherEvent)
@receiver(post_delete, sender=GeneralEvent)
def cleanup_carbon_entries_on_event_delete(sender, instance, **kwargs):
    """
    Clean up associated carbon entries when events are deleted
    """
    try:
        from carbon.models import CarbonEntry

        # Find and delete associated carbon entries
        # FIX: Match by event ID pattern to delete only the correct CarbonEntry
        event_class_name = instance.__class__.__name__
        event_id_pattern = f"{event_class_name}(ID={instance.id})"

        # First try to match with event ID (new format)
        carbon_entries = CarbonEntry.objects.filter(
            production=instance.history, description__icontains=event_id_pattern
        )

        deleted_count = carbon_entries.count()
        carbon_entries.delete()

        if deleted_count > 0:
            print(f"🗑️ Cleaned up {deleted_count} carbon entries for deleted {event_class_name} {instance.id}")

    except Exception as e:
        print(f"❌ Error cleaning up carbon entries for {instance.__class__.__name__} {instance.id}: {e}")


@receiver(post_save, sender=EquipmentEvent)
def calculate_equipment_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact for equipment events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-26): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like fuel_consumed are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            event_id_pattern = f"EquipmentEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-EquipmentEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for EquipmentEvent {instance.id} (update)")

        calculation_result = calculator.calculate_equipment_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        if calculation_result.get("co2e", 0) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(f"✅ Carbon calculation {action} for Equipment Event {instance.id}: {calculation_result['co2e']} kg CO2e")

    except Exception as e:
        print(f"❌ Error calculating carbon for Equipment Event {instance.id}: {e}")


@receiver(post_save, sender=SoilManagementEvent)
def calculate_soil_management_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact for soil management events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-26): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like fuel_consumed or amendment_amount are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            # Try both new format (with ID) and old format (without ID)
            event_id_pattern = f"SoilManagementEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            # that match by registry_verification_id which should have the event ID
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-SoilManagementEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(
                    f"🔄 Deleted {deleted_count} existing carbon entries for SoilManagementEvent {instance.id} (update)"
                )

        calculation_result = calculator.calculate_soil_management_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        if calculation_result.get("co2e", 0) > 0:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Soil Management Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        print(f"❌ Error calculating carbon for Soil Management Event {instance.id}: {e}")


@receiver(post_save, sender=PestManagementEvent)
def calculate_pest_management_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate carbon impact for pest management events

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.
    Removed dual-write to extra_data['carbon_calculation'] - using only CarbonEntry.

    FIX (2025-12-26): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields like pesticide_amount are modified.
    """
    # Always calculate carbon for both create AND update operations
    try:
        from carbon.models import CarbonEntry
        from carbon.services.event_carbon_calculator import EventCarbonCalculator

        calculator = EventCarbonCalculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            # Find and delete existing carbon entry for this event
            event_id_pattern = f"PestManagementEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            # If no entries found with new format, also look for old format entries
            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-PestManagementEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(
                    f"🔄 Deleted {deleted_count} existing carbon entries for PestManagementEvent {instance.id} (update)"
                )

        calculation_result = calculator.calculate_pest_management_event_impact(instance)

        # Create carbon entry as the authoritative source - single source of truth
        # Only create for significant impacts
        if abs(calculation_result.get("co2e", 0)) > 0.05:
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Pest Management Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        print(f"❌ Error calculating carbon for Pest Management Event {instance.id}: {e}")
