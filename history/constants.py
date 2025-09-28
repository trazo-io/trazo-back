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

WEATHER_EVENT_TYPE = 0
PRODUCTION_EVENT_TYPE = 1
CHEMICAL_EVENT_TYPE = 2
GENERAL_EVENT_TYPE = 3
EQUIPMENT_EVENT_TYPE = 4
SOIL_MANAGEMENT_EVENT_TYPE = 5
PEST_MANAGEMENT_EVENT_TYPE = 6
BUSINESS_EVENT_TYPE = 7

EVENT_TYPE_TO_MODEL = {
    WEATHER_EVENT_TYPE: WeatherEvent,
    CHEMICAL_EVENT_TYPE: ChemicalEvent,
    PRODUCTION_EVENT_TYPE: ProductionEvent,
    GENERAL_EVENT_TYPE: GeneralEvent,
    EQUIPMENT_EVENT_TYPE: EquipmentEvent,
    SOIL_MANAGEMENT_EVENT_TYPE: SoilManagementEvent,
    PEST_MANAGEMENT_EVENT_TYPE: PestManagementEvent,
    BUSINESS_EVENT_TYPE: BusinessEvent,
}

ALLOWED_PERIODS = ["week", "month", "year"]
