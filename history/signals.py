import logging

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from carbon.services.event_carbon_calculator import EventCarbonCalculator

from .models import (
    BusinessEvent,
    ChemicalEvent,
    EquipmentEvent,
    GeneralEvent,
    PestManagementEvent,
    ProductionEvent,
    SoilManagementEvent,
    WeatherEvent,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sprint 3 — Auto-classify ChemicalEvent against the National List (7 CFR 205.601/602)
# on every save. Populates national_list_substance FK so the audit export can
# show "Allowed per §205.601(i)" rather than "Self-reported" even when the
# frontend hasn't been updated to let farmers set it manually.
# Never overwrites a farmer/admin-set value.
# ---------------------------------------------------------------------------
@receiver(pre_save, sender=ChemicalEvent)
def auto_classify_chemical_against_national_list(sender, instance, **kwargs):
    # Respect explicit set — only classify when not already set.
    if instance.national_list_substance_id is not None:
        return
    if not instance.commercial_name:
        return

    try:
        from certifications.models import NationalListSubstance
        from certifications.services.omri_verifier import OMRIProductVerifier, _normalize

        verifier = OMRIProductVerifier()
        if not verifier.health_check():
            return  # National List not seeded yet; skip silently
        result = verifier.verify(operation_name=instance.commercial_name)
        if not result.found:
            return

        normalized = _normalize(instance.commercial_name)
        nl = NationalListSubstance.objects.filter(substance_name_normalized=normalized).first()
        if nl is None:
            candidates = [
                n
                for n in NationalListSubstance.objects.values_list("substance_name_normalized", flat=True)
                if len(n) >= 5 and n in normalized
            ]
            if candidates:
                best = max(candidates, key=len)
                nl = NationalListSubstance.objects.filter(substance_name_normalized=best).first()
        if nl is not None:
            instance.national_list_substance = nl
    except Exception:  # noqa: BLE001 — classification is advisory; never block a save
        import logging

        logging.getLogger(__name__).exception(
            "Auto-classification failed for ChemicalEvent commercial_name=%r",
            instance.commercial_name,
        )


# Module-level singleton — EventCarbonCalculator is stateless, no need to
# re-instantiate (and re-load all USDA factors) on every signal fire.
_calculator = None


def _get_calculator():
    global _calculator
    if _calculator is None:
        _calculator = EventCarbonCalculator()
    return _calculator


# F09 (2026-06): the carbon-calc signal handlers below previously swallowed
# exceptions with a bare print(), so a crashed calculation looked identical to a
# true zero-emission event (no CarbonEntry, no trace). They now log at ERROR with
# exc_info so failures are visible in logs/monitoring (Sentry).
#
# NOTE: an earlier revision of this fix ALSO wrote a 0-amount CarbonEntry flagged
# verification_status="calculation_error" to make failures queryable in the DB.
# That was reverted — its description contained the "{cls}(ID={id})" substring
# that the consumer/event carbon lookup matches on
# (history/serializers.py:~244, description__icontains=event_id_pattern,
# order_by("-created_at").first()), so a failed event could surface co2e=0 and
# data_source="calculation_error" on the consumer event card. A DB error marker
# needs a description that avoids that pattern + success-path cleanup + a
# consumer-query exclusion; deferred as a reviewed change.


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

        calculator = _get_calculator()

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
        logger.error("Error calculating carbon for Chemical Event %s: %s", instance.id, e, exc_info=True)


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

        calculator = _get_calculator()

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

        # Create carbon entry as the authoritative source - single source of truth.
        # For facility-based subtypes (EM, PO, PH), create an entry even when co2e=0:
        # electric packing lines / pollination-by-bee-hive / equipment cleaning with
        # no fuel use legitimately produce 0 emissions, and the timeline should
        # display "0 kg CO₂e" (a transparency signal) rather than "No CO₂ data"
        # (which reads as missing data).
        co2e_value = calculation_result.get("co2e", 0)
        facility_subtypes = ("EM", "PO", "PH")
        if co2e_value > 0 or (co2e_value >= 0 and instance.type in facility_subtypes):
            carbon_entry = calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        print(
            f"✅ Carbon calculation {action} for Production Event {instance.id}: {calculation_result['co2e']} kg CO2e"
        )

    except Exception as e:
        logger.error("Error calculating carbon for Production Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=WeatherEvent)
def calculate_weather_event_carbon(sender, instance, created, **kwargs):
    """
    Calculate carbon impact for weather events.

    Some weather events generate real emissions (frost protection with heaters,
    drought irrigation, hailstorm cleanup, high-temp cooling). Others are purely
    transparency documentation (storms, winds, humidity).

    FIX (2026-03-10): Previously skipped CarbonEntry creation for ALL weather
    events, losing real emissions from frost/drought/hail/heat responses.
    """
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            event_id_pattern = f"WeatherEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-WeatherEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for WeatherEvent {instance.id} (update)")

        calculation_result = calculator.calculate_weather_event_impact(instance)
        co2e_value = calculation_result.get("co2e", 0)

        if abs(co2e_value) > 0:
            calculator.create_carbon_entry_from_event(instance, calculation_result)

        action = "created" if created else "updated"
        if abs(co2e_value) > 0:
            print(f"✅ Carbon calculation {action} for Weather Event {instance.id}: {co2e_value} kg CO2e")
        else:
            print(
                f"✅ Transparency documentation {action} for Weather Event {instance.id}:"
                " 0.0 kg CO2e (transparency value only)"
            )

    except Exception as e:
        logger.error("Error calculating carbon for Weather Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=GeneralEvent)
def calculate_general_event_carbon(sender, instance, created, **kwargs):
    """
    Automatically calculate minimal carbon impact for general events.

    PHASE 2 CONSOLIDATION (2025-12-12): CarbonEntry is now the single source of truth.

    FIX (2026-03-10): Now triggers on BOTH create AND update to ensure carbon values
    are recalculated when event fields are modified (was create-only).
    """
    try:
        from carbon.models import CarbonEntry

        calculator = _get_calculator()

        # For updates, delete the existing CarbonEntry first to avoid duplicates
        if not created:
            event_id_pattern = f"GeneralEvent(ID={instance.id})"
            existing_entries = CarbonEntry.objects.filter(
                production=instance.history,
                description__icontains=event_id_pattern,
            )
            deleted_count = existing_entries.count()

            if deleted_count == 0:
                existing_entries = CarbonEntry.objects.filter(
                    production=instance.history,
                    registry_verification_id=f"REG-GeneralEvent-{instance.id}",
                )
                deleted_count = existing_entries.count()

            if deleted_count > 0:
                existing_entries.delete()
                print(f"🔄 Deleted {deleted_count} existing carbon entries for GeneralEvent {instance.id} (update)")

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
            calculator.create_carbon_entry_from_event(instance, calculation_result)

            action = "created" if created else "updated"
            print(
                f"✅ Carbon calculation {action} for General Event {instance.id}: {calculation_result['co2e']} kg CO2e"
            )
        else:
            print(
                f"✅ General Event {instance.id} processed with minimal carbon impact: {calculation_result['co2e']} kg CO2e"
            )

    except Exception as e:
        logger.error("Error calculating carbon for General Event %s: %s", instance.id, e, exc_info=True)


@receiver(post_save, sender=BusinessEvent)
def calculate_business_event_carbon(sender, instance, created, **kwargs):
    """
    Business events (certifications, audits, compliance) have no direct operational
    emissions. Log for transparency tracking only — no CarbonEntry created.
    """
    action = "created" if created else "updated"
    print(f"✅ Transparency documentation {action} for Business Event {instance.id}: 0.0 kg CO2e (no direct emissions)")


@receiver(post_delete, sender=BusinessEvent)
@receiver(post_delete, sender=ChemicalEvent)
@receiver(post_delete, sender=ProductionEvent)
@receiver(post_delete, sender=WeatherEvent)
@receiver(post_delete, sender=GeneralEvent)
@receiver(post_delete, sender=EquipmentEvent)
@receiver(post_delete, sender=SoilManagementEvent)
@receiver(post_delete, sender=PestManagementEvent)
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

        calculator = _get_calculator()

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
        logger.error("Error calculating carbon for Equipment Event %s: %s", instance.id, e, exc_info=True)


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

        calculator = _get_calculator()

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
        logger.error("Error calculating carbon for Soil Management Event %s: %s", instance.id, e, exc_info=True)


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

        calculator = _get_calculator()

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
        logger.error("Error calculating carbon for Pest Management Event %s: %s", instance.id, e, exc_info=True)
