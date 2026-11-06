"""CarbonEntry columns retired and dropped (schema remodel plan, CarbonEntry slimming, 2026-11-06).

Each one has no reader. The writers were nine one-shot raw-SQL seeders and repair commands from
early 2026 (deleted with this list), the demo seeder `seed_comprehensive_demo_v2` (its raw INSERT
named 12 of them, written EMPTY in step 1) and, for `external_verification_id`, the event
writer's "EXT-<Class>-<id>" copy of the registry id, which nothing ever read back. Several held
claims compliance.md forbids, written as if they were facts: "USDA verified fuel consumption data" in
`verification_notes`, "https://usda.gov/verify/<id>" in `verification_report_url`, a
"USDA Carbon Registry" in `registry_name`, random coordinates in `gps_coordinates`.

The columns went in three deploys, because `migrate` runs while the previous containers still
serve, and their model names every column in each CarbonEntry INSERT and UPDATE:

1. #318 stopped every writer, and `clear_retired_carbon_columns --apply` put each value back to
   its default through `common.services.data_operations`. The applied report, stored on its
   `DataOperationLog` row, keeps every value it cleared.
2. Migration 0048 refuses to run while a row holds a value, then takes the columns out of the
   model (the command went with them) and lets the table columns take NULL. The census counted,
   per column, the rows still holding a value (`retiring_columns`), and its compare accepts a
   column leaving only when that count was 0 in the census taken before.
3. Migration 0049 drops the columns from the table, once no container runs a model that names
   them, refusing to run while a row holds anything but NULL or the old default.

The list stays as the record of what was retired. The census still reads it and, with no listed
field left in the model, counts nothing; the compare across the change reads the counts stored in
the census taken before it.

`calculation_details` is NOT retired: `recompute_soil_carbon` writes its method marker there.
"""

#: Column -> the value it held when nothing was written to it (the field's default before the drop).
RETIRED_CARBON_ENTRY_COLUMNS = {
    "iot_device_id": "",
    "external_verification_id": "",
    "gps_coordinates": {},
    "verification_notes": "",
    "baseline_scenario": {},
    "detected_patterns": {},
    "financial_analysis": {},
    "methodology_id": "",
    "monitoring_plan": {},
    "registry_name": "",
    "registry_submission_id": "",
    "verification_report_url": "",
    "explanation_text": "",
    "confidence_level": "medium",
    "improvement_potential": 0.0,
    "benchmark_comparison": {},
}
