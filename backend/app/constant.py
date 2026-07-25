"""
Application-wide constants and enumerations.

Centralizing these values avoids magic strings/numbers scattered across
services, models, and the IoT simulator, and keeps domain vocabulary
consistent between the backend and frontend contracts.
"""

from enum import Enum


# =========================================================
# Produce domain
# =========================================================

class ProduceType(str, Enum):
    TOMATO = "tomato"
    ONION = "onion"
    POTATO = "potato"
    BANANA = "banana"
    MANGO = "mango"
    LEAFY_GREENS = "leafy_greens"
    GRAPES = "grapes"
    CITRUS = "citrus"


class ProduceStage(str, Enum):
    HARVESTED = "harvested"
    IN_TRANSIT = "in_transit"
    IN_STORAGE = "in_storage"
    AT_MARKET = "at_market"
    SOLD = "sold"
    SPOILED = "spoiled"


class QualityGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECTED = "rejected"


# =========================================================
# Storage domain
# =========================================================

class StorageType(str, Enum):
    AMBIENT = "ambient"
    COLD_STORAGE = "cold_storage"
    CONTROLLED_ATMOSPHERE = "controlled_atmosphere"
    WAREHOUSE = "warehouse"


# Ideal storage condition ranges per produce type: (temp_c_min, temp_c_max, humidity_pct_min, humidity_pct_max)
IDEAL_STORAGE_CONDITIONS: dict[str, tuple[float, float, float, float]] = {
    ProduceType.TOMATO.value: (10.0, 15.0, 85.0, 90.0),
    ProduceType.ONION.value: (0.0, 4.0, 65.0, 70.0),
    ProduceType.POTATO.value: (4.0, 10.0, 85.0, 95.0),
    ProduceType.BANANA.value: (13.0, 15.0, 85.0, 90.0),
    ProduceType.MANGO.value: (10.0, 13.0, 85.0, 90.0),
    ProduceType.LEAFY_GREENS.value: (0.0, 4.0, 90.0, 98.0),
    ProduceType.GRAPES.value: (0.0, 2.0, 90.0, 95.0),
    ProduceType.CITRUS.value: (3.0, 9.0, 85.0, 90.0),
}

# Sensor safety thresholds — breaches beyond these trigger anomaly alerts
TEMPERATURE_CRITICAL_DELTA_C: float = 5.0
HUMIDITY_CRITICAL_DELTA_PCT: float = 15.0
ETHYLENE_CRITICAL_PPM: float = 1.0


# =========================================================
# Alerts
# =========================================================

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    TEMPERATURE_BREACH = "temperature_breach"
    HUMIDITY_BREACH = "humidity_breach"
    ETHYLENE_SPIKE = "ethylene_spike"
    RAPID_DECAY = "rapid_decay"
    PRICE_DROP = "price_drop"
    PRICE_OPPORTUNITY = "price_opportunity"
    SENSOR_OFFLINE = "sensor_offline"


# =========================================================
# Market domain
# =========================================================

class MarketTrend(str, Enum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"
    VOLATILE = "volatile"


DEFAULT_CURRENCY: str = "INR"
PRICE_UNIT: str = "per_quintal"  # 1 quintal = 100 kg


# =========================================================
# Simulation
# =========================================================

class ScenarioAction(str, Enum):
    SELL_NOW = "sell_now"
    COLD_STORE = "cold_store"
    TRANSPORT_TO_MARKET = "transport_to_market"
    HOLD = "hold"


DEFAULT_SIMULATION_HORIZON_DAYS: int = 14
SIMULATION_TIME_STEP_HOURS: int = 6


# =========================================================
# WebSocket event types
# =========================================================

class WSEventType(str, Enum):
    SENSOR_UPDATE = "sensor_update"
    MARKET_UPDATE = "market_update"
    TWIN_UPDATE = "twin_update"
    ALERT = "alert"
    ANOMALY_INJECTED = "anomaly_injected"
    SIMULATION_RESULT = "simulation_result"
    HEARTBEAT = "heartbeat"


# =========================================================
# Pagination / API defaults
# =========================================================

DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100

# =========================================================
# Explainable AI
# =========================================================

CONFIDENCE_HIGH_THRESHOLD: float = 0.8
CONFIDENCE_MEDIUM_THRESHOLD: float = 0.5