"""What an off-farm facility does for the operation, in the words of WSDA's Additional Facilities and
Third-Parties form (AGR 2519, R 01/24, page 1, "Activity Information").

WSDA's crop OSP asks, in §J 13, §K 1 and §L 1, whether a third party transports the crop to a facility,
stores it or custom handles it, and a Yes is answered by attaching AGR 2519 for that facility. The form
asks which of these activities happen there, in four groups. The keys are Trazo's; the labels are the
form's, verbatim. The operator picks them per facility (`PostHarvestFacility.activities`): a facility's
type and role are a different, coarser fact, so no activity is ever inferred from them.
"""

from __future__ import annotations

#: (group, ((key, label as printed on the form), ...)), in the form's order.
ACTIVITY_GROUPS = (
    (
        "general",
        (
            ("equipment_storage", "Equipment storage"),
            ("input_material_storage", "Input material storage"),
            ("record_storage", "Record storage"),
            ("retail_sales", "Retail sales to public"),
        ),
    ),
    (
        "production",
        (
            ("livestock_housing", "Livestock barns or housing"),
            ("propagation_houses", "Propagation houses"),
        ),
    ),
    (
        "potentially_exempt",
        (
            ("brokering_packaged", "Brokering or marketing packaged products"),
            ("storage_packaged", "Storage, cross-docking packaged products"),
        ),
    ),
    (
        "requires_certification",
        (
            ("importing", "Importing organic products"),
            ("sourcing_trading", "Sourcing, trading wholesale ingredients, products"),
            ("presizing_sorting_hydrocooling", "Pre-sizing, sorting, hydrocooling crops"),
            ("transloading", "Transloading, combining, or splitting bulk shipments"),
            ("bulk_storage", "Storage of bulk, unpackaged organic products"),
            ("multi_ingredient_processing", "Multi-ingredient processing"),
            ("single_ingredient_processing", "Single ingredient processing"),
            ("packaging_labeling", "Packaging, labeling organic products"),
            ("slaughter", "Slaughter of livestock"),
        ),
    ),
)

ACTIVITY_LABELS = {key: label for _group, items in ACTIVITY_GROUPS for key, label in items}
ACTIVITY_KEYS = tuple(ACTIVITY_LABELS)
ACTIVITY_GROUP_OF = {key: group for group, items in ACTIVITY_GROUPS for key, _label in items}
