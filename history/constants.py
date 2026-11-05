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
from .taxonomy import BY_SLUG

# The codes are defined once, in history/taxonomy.py. These names stay because ~40 modules import
# them; they are read from the taxonomy, never redeclared.
WEATHER_EVENT_TYPE = BY_SLUG["weather"].code
PRODUCTION_EVENT_TYPE = BY_SLUG["production"].code
CHEMICAL_EVENT_TYPE = BY_SLUG["chemical"].code
GENERAL_EVENT_TYPE = BY_SLUG["general"].code
EQUIPMENT_EVENT_TYPE = BY_SLUG["equipment"].code
SOIL_MANAGEMENT_EVENT_TYPE = BY_SLUG["soil"].code
PEST_MANAGEMENT_EVENT_TYPE = BY_SLUG["pest"].code
BUSINESS_EVENT_TYPE = BY_SLUG["business"].code

_MODELS = {
    model.__name__: model
    for model in (
        WeatherEvent,
        ChemicalEvent,
        ProductionEvent,
        GeneralEvent,
        EquipmentEvent,
        SoilManagementEvent,
        PestManagementEvent,
        BusinessEvent,
    )
}

#: code -> model, derived from the taxonomy. The insertion order (0, 2, 1, 3, ...) is the one this
#: dict always had; callers that iterate it keep their output order.
EVENT_TYPE_TO_MODEL = {
    BY_SLUG[slug].code: _MODELS[BY_SLUG[slug].model_name]
    for slug in ("weather", "chemical", "production", "general", "equipment", "soil", "pest", "business")
}

ALLOWED_PERIODS = ["week", "month", "year"]
