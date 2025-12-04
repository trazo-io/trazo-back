# Sprint 2 Epic 2.1.4: Data migration for Equipment events to Production events
# This migration converts existing EquipmentEvent records to ProductionEvent records
# with type='EM' (Equipment Maintenance) to consolidate event types

from django.db import migrations


def migrate_equipment_to_production(apps, schema_editor):
    """
    Sprint 2 Epic 2.1.4: Migrate existing EquipmentEvent records to ProductionEvent

    Field Mapping:
    - EquipmentEvent.type -> ProductionEvent.equipment_operation_type
    - EquipmentEvent.fuel_type -> ProductionEvent.fuel_type
    - EquipmentEvent.fuel_amount -> ProductionEvent.fuel_consumed
    - EquipmentEvent.hours_used -> ProductionEvent.equipment_hours
    - EquipmentEvent.area_covered -> ProductionEvent.area_covered (needs type conversion)
    - EquipmentEvent.equipment_name -> stored in description
    - ProductionEvent.type is set to 'EM' (Equipment Maintenance)
    """
    from decimal import Decimal, InvalidOperation

    EquipmentEvent = apps.get_model('history', 'EquipmentEvent')
    ProductionEvent = apps.get_model('history', 'ProductionEvent')

    # Counter for reporting
    migrated_count = 0

    for equipment_event in EquipmentEvent.objects.all():
        # Parse area_covered from CharField to Decimal
        area_value = None
        if equipment_event.area_covered:
            try:
                # Try to extract numeric value from area_covered string
                area_str = equipment_event.area_covered.replace(',', '.').strip()
                # Extract just the numeric part (e.g., "10.5 ha" -> "10.5")
                numeric_part = ''.join(c for c in area_str if c.isdigit() or c == '.')
                if numeric_part:
                    area_value = Decimal(numeric_part)
            except (InvalidOperation, ValueError):
                area_value = None

        # Create a new ProductionEvent with Equipment Maintenance type
        production_event = ProductionEvent(
            # Base CommonEvent fields (from CommonEvent base class)
            history=equipment_event.history,
            description=f"[Migrated from Equipment] {equipment_event.equipment_name or 'Equipment Event'}: {equipment_event.description or ''}",
            date=equipment_event.date,
            album=equipment_event.album,
            index=equipment_event.index,
            created_by=equipment_event.created_by,

            # Production event type - Equipment Maintenance
            type='EM',

            # Equipment-specific fields mapped to Production
            equipment_operation_type=equipment_event.type,  # MN, RE, CA, FC, BD, EI
            # Truncate fuel_type to 20 chars (EquipmentEvent allows 50, ProductionEvent allows 20)
            fuel_type=(equipment_event.fuel_type or '')[:20],
            fuel_consumed=equipment_event.fuel_amount,
            equipment_hours=equipment_event.hours_used,
            area_covered=area_value,

            # Extra data preserved (including original values that may be truncated)
            extra_data={
                'migrated_from': 'EquipmentEvent',
                'original_equipment_name': equipment_event.equipment_name,
                'original_maintenance_cost': str(equipment_event.maintenance_cost) if equipment_event.maintenance_cost else None,
                'original_area_covered_str': equipment_event.area_covered,  # Preserve original string
                'original_fuel_type': equipment_event.fuel_type,  # Preserve original if truncated
                'original_extra_data': equipment_event.extra_data,
            },
        )

        production_event.save()
        migrated_count += 1

    if migrated_count > 0:
        print(f"Sprint 2 Epic 2.1.4: Successfully migrated {migrated_count} EquipmentEvent records to ProductionEvent (type=EM)")


def reverse_migration(apps, schema_editor):
    """
    Reverse migration: Delete ProductionEvents that were created from EquipmentEvents
    Note: This only removes the migrated records, original EquipmentEvents are preserved
    """
    ProductionEvent = apps.get_model('history', 'ProductionEvent')

    # Find and delete ProductionEvents that were migrated from EquipmentEvents
    migrated_events = ProductionEvent.objects.filter(
        type='EM',
        extra_data__contains={'migrated_from': 'EquipmentEvent'}
    )

    deleted_count = migrated_events.count()
    migrated_events.delete()

    if deleted_count > 0:
        print(f"Sprint 2 Epic 2.1.4: Reversed migration - deleted {deleted_count} migrated ProductionEvent records")


class Migration(migrations.Migration):
    """
    Sprint 2 Epic 2.1.4: Data migration for Equipment events consolidation

    This migration:
    1. Converts existing EquipmentEvent records to ProductionEvent records
    2. Sets ProductionEvent.type to 'EM' (Equipment Maintenance)
    3. Maps equipment-specific fields to the new ProductionEvent fields
    4. Preserves original data in extra_data for traceability
    """

    dependencies = [
        ("history", "0116_sprint2_equipment_consolidation"),
    ]

    operations = [
        migrations.RunPython(
            migrate_equipment_to_production,
            reverse_code=reverse_migration,
        ),
    ]
