from django.core.management.base import BaseCommand

from carbon.models import CarbonOffsetAction


class Command(BaseCommand):
    help = "Seeds CarbonOffsetAction entries for the compensation dropdown"

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS("Creating offset actions..."))

        # Define offset actions (removed cost_per_unit field that doesn't exist in model)
        offset_actions = [
            {
                "name": "Reforestation",
                "description": "Plant trees to offset carbon emissions through natural sequestration",
                "unit": "trees planted",
                "verification_required": True,
                "verification_process": "Third-party verification of tree survival and growth rates",
                "usda_factors_used": True,
            },
            {
                "name": "Renewable Energy Credits",
                "description": "Investment in solar or wind energy projects",
                "unit": "kWh offset",
                "verification_required": True,
                "verification_process": "Renewable energy certificate tracking and verification",
                "usda_factors_used": True,
            },
            {
                "name": "Methane Capture",
                "description": "Capture methane from landfills or agricultural operations",
                "unit": "kg CH4 captured",
                "verification_required": True,
                "verification_process": "EPA-verified methane capture measurements",
                "usda_factors_used": True,
            },
            {
                "name": "Energy Efficiency",
                "description": "Energy efficiency improvement projects",
                "unit": "kWh saved",
                "verification_required": False,
                "verification_process": "Energy audit and measurement verification",
                "usda_factors_used": False,
            },
            {
                "name": "Composting",
                "description": "Organic waste composting programs",
                "unit": "kg organic waste composted",
                "verification_required": False,
                "verification_process": "Composting facility records and measurements",
                "usda_factors_used": False,
            },
            {
                "name": "Verified Carbon Credits",
                "description": "Purchase of verified carbon offset credits",
                "unit": "tCO₂e",
                "verification_required": True,
                "verification_process": "VCS or Gold Standard registry verification",
                "usda_factors_used": True,
            },
        ]

        # Create the offset actions
        actions_created = 0
        actions_updated = 0

        for action_data in offset_actions:
            action, created = CarbonOffsetAction.objects.update_or_create(
                name=action_data["name"], defaults=action_data
            )

            if created:
                actions_created += 1
                self.stdout.write(self.style.SUCCESS(f"Created: {action.name}"))
            else:
                actions_updated += 1
                self.stdout.write(self.style.SUCCESS(f"Updated: {action.name}"))

        self.stdout.write(self.style.SUCCESS(f"Created {actions_created} new offset actions"))
        self.stdout.write(self.style.SUCCESS(f"Updated {actions_updated} existing offset actions"))
