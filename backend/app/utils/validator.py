"""
Validation utilities.

Provides a single `ValidationError` exception plus a set of reusable
validators for domain data (produce, storage conditions, sensor
readings) and generic input (pagination, dates, strings). Services and
API routes should catch `ValidationError` and translate it into an
appropriate HTTP response (e.g. 422) at the boundary.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.constants import (
    DEFAULT_PAGE_SIZE,
    ETHYLENE_CRITICAL_PPM,
    IDEAL_STORAGE_CONDITIONS,
    MAX_PAGE_SIZE,
    ProduceType,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Absolute physical bounds — anything outside these is treated as a
# malformed/sensor-fault reading rather than a mere "out of range" value.
ABSOLUTE_TEMP_MIN_C = -40.0
ABSOLUTE_TEMP_MAX_C = 60.0
ABSOLUTE_HUMIDITY_MIN_PCT = 0.0
ABSOLUTE_HUMIDITY_MAX_PCT = 100.0
ABSOLUTE_ETHYLENE_MAX_PPM = 50.0


class ValidationError(Exception):
    """Raised when input data fails validation. Carries the offending field."""

    def __init__(self, message: str, field: str | None = None):
        self.field = field
        self.message = message
        super().__init__(f"{field + ': ' if field else ''}{message}")


# =========================================================
# Generic validators
# =========================================================

def require(condition: bool, message: str, field: str | None = None) -> None:
    """Raise `ValidationError(message, field)` if `condition` is falsy."""
    if not condition:
        raise ValidationError(message, field)


def validate_non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("must be a non-empty string", field)
    return value.strip()


def validate_positive_number(value: Any, field: str, allow_zero: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError("must be a number", field) from None

    if allow_zero:
        require(number >= 0, "must be greater than or equal to 0", field)
    else:
        require(number > 0, "must be greater than 0", field)
    return number


def validate_range(
    value: Any, field: str, minimum: float, maximum: float
) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError("must be a number", field) from None

    require(
        minimum <= number <= maximum,
        f"must be between {minimum} and {maximum}",
        field,
    )
    return number


def validate_email(value: str, field: str = "email") -> str:
    value = validate_non_empty_string(value, field)
    require(bool(_EMAIL_RE.match(value)), "must be a valid email address", field)
    return value.lower()


def validate_enum_value(value: Any, enum_cls: type, field: str) -> str:
    valid_values = {member.value for member in enum_cls}
    require(
        value in valid_values,
        f"must be one of {sorted(valid_values)}",
        field,
    )
    return value


def validate_date_range(start: datetime, end: datetime, field: str = "date_range") -> None:
    require(isinstance(start, datetime) and isinstance(end, datetime), "must be valid datetimes", field)
    require(start <= end, "start date must be before or equal to end date", field)


def validate_pagination_params(
    page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
) -> tuple[int, int]:
    require(isinstance(page, int) and page >= 1, "must be an integer >= 1", "page")
    require(
        isinstance(page_size, int) and 1 <= page_size <= MAX_PAGE_SIZE,
        f"must be an integer between 1 and {MAX_PAGE_SIZE}",
        "page_size",
    )
    return page, page_size


def sanitize_string(value: str, max_length: int = 500) -> str:
    """Strip control characters and truncate to `max_length`."""
    if not isinstance(value, str):
        raise ValidationError("must be a string")
    cleaned = "".join(ch for ch in value if ch.isprintable() or ch in "\n\t").strip()
    return cleaned[:max_length]


# =========================================================
# Domain validators — produce & storage
# =========================================================

def validate_produce_type(value: str, field: str = "produce_type") -> str:
    return validate_enum_value(value, ProduceType, field)


def validate_quantity_kg(value: Any, field: str = "quantity_kg") -> float:
    return validate_positive_number(value, field, allow_zero=False)


def validate_temperature_reading(value: Any, field: str = "temperature_c") -> float:
    return validate_range(value, field, ABSOLUTE_TEMP_MIN_C, ABSOLUTE_TEMP_MAX_C)


def validate_humidity_reading(value: Any, field: str = "humidity_pct") -> float:
    return validate_range(value, field, ABSOLUTE_HUMIDITY_MIN_PCT, ABSOLUTE_HUMIDITY_MAX_PCT)


def validate_ethylene_reading(value: Any, field: str = "ethylene_ppm") -> float:
    return validate_range(value, field, 0.0, ABSOLUTE_ETHYLENE_MAX_PPM)


def is_within_ideal_storage_conditions(
    produce_type: str, temperature_c: float, humidity_pct: float
) -> bool:
    """
    Return True if `temperature_c`/`humidity_pct` fall within the ideal
    storage range for `produce_type`. Falls back to False for unknown
    produce types rather than raising, since this is a query helper.
    """
    ranges = IDEAL_STORAGE_CONDITIONS.get(produce_type)
    if ranges is None:
        return False

    temp_min, temp_max, humidity_min, humidity_max = ranges
    return (temp_min <= temperature_c <= temp_max) and (
        humidity_min <= humidity_pct <= humidity_max
    )


def is_ethylene_critical(ethylene_ppm: float) -> bool:
    """Return True if an ethylene reading exceeds the critical threshold."""
    return ethylene_ppm >= ETHYLENE_CRITICAL_PPM


def validate_batch_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Validate the core fields of a produce batch creation/update payload.
    Returns the cleaned payload (with normalized values) on success.
    """
    cleaned: dict[str, Any] = {}
    cleaned["produce_type"] = validate_produce_type(payload.get("produce_type"))
    cleaned["quantity_kg"] = validate_quantity_kg(payload.get("quantity_kg"))

    if "storage_type" in payload and payload["storage_type"] is not None:
        cleaned["storage_type"] = validate_non_empty_string(
            payload["storage_type"], "storage_type"
        )

    if "harvested_at" in payload and payload["harvested_at"] is not None:
        harvested_at = payload["harvested_at"]
        require(
            isinstance(harvested_at, datetime),
            "must be a valid datetime",
            "harvested_at",
        )
        cleaned["harvested_at"] = harvested_at

    return cleaned