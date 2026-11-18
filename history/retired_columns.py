"""Event-table columns retired and being dropped (schema remodel, 2026-11-18).

`SoilManagementEvent.carbon_sequestration_potential` is a modelled kg CO2e figure. No form ever had
an input for it: only seeders and the old public QR payload touched it, and the producer modal only
showed a stored value. Soil-carbon stock change is excluded from Trazo's carbon
(.claude/rules/carbon-methodology.md, 2026-10-28), and back #412 already took it off the QR page
and made it read-only on the update API.

It leaves in three deploys, like the CarbonEntry columns (carbon/retired_columns.py), because
`migrate` runs while the previous containers still serve and their model names every column in
each INSERT and UPDATE:

1. Nothing reads or writes it: the serializers and the timeline no longer name it, and a
   correction cannot target it (`history.amendments.amendable_fields`).
   `clear_retired_soil_columns --apply` puts every value back to NULL through
   `common.services.data_operations`, and the applied report on its `DataOperationLog` row keeps
   every value it cleared (`--restore log:<id>` puts them back). The census counts, per column,
   the rows still holding a value (`retiring_columns`).
2. A migration refuses to run while a row holds a value, then takes the column out of the model
   state only.
3. A later migration drops the column from the table, once no container runs a model naming it.

The list stays as the record of what was retired.
"""

#: Column -> the value it holds when nothing was written to it.
RETIRED_SOIL_EVENT_COLUMNS = {
    "carbon_sequestration_potential": None,
}
