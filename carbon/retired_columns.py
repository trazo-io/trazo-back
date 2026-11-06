"""CarbonEntry columns being retired (schema remodel plan, CarbonEntry slimming, 2026-11-06).

Each one has no reader. The writers were nine one-shot raw-SQL seeders and repair commands from
early 2026 (deleted with this list), the demo seeder `seed_comprehensive_demo_v2` (its raw INSERT
names every NOT NULL column, so it loses them in the change that drops them) and, for
`external_verification_id`, the event writer's "EXT-<Class>-<id>" copy of the registry id, which
nothing ever read back. Several held claims
compliance.md forbids, written as if they were facts: "USDA verified fuel consumption data" in
`verification_notes`, "https://usda.gov/verify/<id>" in `verification_report_url`, a
"USDA Carbon Registry" in `registry_name`, random coordinates in `gps_coordinates`.

The columns go in two deploys, because a migration that drops a column runs while the previous
containers still serve, and their INSERTs name every column:

1. This change: nothing writes the columns any more, and `clear_retired_carbon_columns` puts
   each one back to its default through `common.services.data_operations`. The applied report,
   stored on its `DataOperationLog` row, keeps every value it cleared and restores it.
2. The next change drops them. The census counts, per column, the rows still holding a value
   (`retiring_columns`), and its compare accepts a dropped column only when that count was 0 in
   the census taken before the drop.

`calculation_details` is NOT retired: `recompute_soil_carbon` writes its method marker there.
"""

#: Column -> the value it holds when nothing was written to it (the field's default).
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
