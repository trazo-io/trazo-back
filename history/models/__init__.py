"""The history app's models, one module per model or group of models (2026-11-17).

Until then this was the single file history/models.py. The modules below are imported in that
file's order, which is the order Django registers the models in: it decides content type ids
in a fresh database and the order `apps.get_models()` walks. Keep it. A new model goes in its
own module, imported here; history.tests.test_models_package fails on a module left out.
"""

# isort: skip_file
# Import order is model registration order; see above.
from .production import (
    logger,
    ORGANIC_LABEL_CATEGORY_CHOICES,
    TRAZO_GREEN,
    TRAZO_LEAF_LOGO,
    compute_retention_until,
    _FALSEY_PUBLISH_VALUES,
    _parse_publish_flag,
    Production,
    ProductionPostHarvestFacility,
)
from .activity import Activity
from .common_event import CommonEvent
from .weather_event import WeatherEvent
from .chemical_event import ChemicalEvent
from .production_event import ProductionEvent
from .general_event import GeneralEvent
from .history_scan import COUNTED_SCAN_BOT_SCORE_MAX, HistoryScanQuerySet, HistoryScan
from .equipment_event import EquipmentEvent
from .soil_management_event import SoilManagementEvent
from .pest_management_event import PestManagementEvent
from .business_event import BusinessEvent
from .sales import BuyerDocRequest, SalesRecordQuerySet, SalesRecord
from .label_image import LabelImage
from .event_amendment import EventAmendment
from .production_plan_item import ProductionPlanItem

__all__ = [
    "logger",
    "ORGANIC_LABEL_CATEGORY_CHOICES",
    "TRAZO_GREEN",
    "TRAZO_LEAF_LOGO",
    "compute_retention_until",
    "_FALSEY_PUBLISH_VALUES",
    "_parse_publish_flag",
    "Production",
    "ProductionPostHarvestFacility",
    "Activity",
    "CommonEvent",
    "WeatherEvent",
    "ChemicalEvent",
    "ProductionEvent",
    "GeneralEvent",
    "COUNTED_SCAN_BOT_SCORE_MAX",
    "HistoryScanQuerySet",
    "HistoryScan",
    "EquipmentEvent",
    "SoilManagementEvent",
    "PestManagementEvent",
    "BusinessEvent",
    "BuyerDocRequest",
    "SalesRecordQuerySet",
    "SalesRecord",
    "LabelImage",
    "EventAmendment",
    "ProductionPlanItem",
]
