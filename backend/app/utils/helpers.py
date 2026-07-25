"""
Shared, framework-agnostic helper functions used across services,
the twin core, AI models, and the IoT simulator.
"""

from __future__ import annotations

import asyncio
import functools
import math
import random
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable, TypeVar

from app.utils.logger import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


# =========================================================
# Identifiers & timestamps
# =========================================================

def generate_id(prefix: str = "") -> str:
    """Generate a short, URL-safe unique identifier, optionally prefixed."""
    token = uuid.uuid4().hex[:12]
    return f"{prefix}_{token}" if prefix else token


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    """Serialize a datetime to an ISO-8601 string with 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def hours_between(start: datetime, end: datetime) -> float:
    """Return the number of hours (can be fractional) between two datetimes."""
    return (end - start).total_seconds() / 3600.0


# =========================================================
# Numeric helpers
# =========================================================

def clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp `value` to the inclusive range [minimum, maximum]."""
    return max(minimum, min(maximum, value))


def round_half_up(value: float, decimals: int = 2) -> float:
    """Round `value` to `decimals` places using standard half-up rounding."""
    factor = 10 ** decimals
    return math.floor(value * factor + 0.5) / factor


def percentage_change(old_value: float, new_value: float) -> float:
    """Return the percentage change from `old_value` to `new_value`."""
    if old_value == 0:
        return 0.0
    return round_half_up(((new_value - old_value) / old_value) * 100.0)


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide two numbers, returning `default` instead of raising on divide-by-zero."""
    return numerator / denominator if denominator else default


def jitter(base_value: float, spread: float) -> float:
    """Return `base_value` perturbed by uniform random noise in [-spread, spread]."""
    return base_value + random.uniform(-spread, spread)


def normalize(value: float, min_value: float, max_value: float) -> float:
    """Normalize `value` from [min_value, max_value] to [0, 1], clamped."""
    if max_value == min_value:
        return 0.0
    return clamp((value - min_value) / (max_value - min_value), 0.0, 1.0)


# =========================================================
# Collections
# =========================================================

def paginate(items: list[T], page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """Slice `items` into a page and return pagination metadata."""
    page = max(1, page)
    page_size = max(1, page_size)
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": math.ceil(total / page_size) if page_size else 0,
    }


def chunk(items: Iterable[T], size: int) -> Iterable[list[T]]:
    """Yield successive chunks of `size` from `items`."""
    bucket: list[T] = []
    for item in items:
        bucket.append(item)
        if len(bucket) == size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def moving_average(values: list[float], window: int) -> list[float]:
    """Compute a simple moving average over `values` with the given window size."""
    if window <= 0 or not values:
        return []
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        window_slice = values[start : i + 1]
        result.append(round_half_up(sum(window_slice) / len(window_slice)))
    return result


# =========================================================
# Async helpers
# =========================================================

def async_retry(
    max_attempts: int = 3,
    delay_seconds: float = 0.5,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    Decorator that retries an async function on failure with exponential backoff.

    Usage:
        @async_retry(max_attempts=3, exceptions=(httpx.HTTPError,))
        async def fetch_data(): ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 0
            current_delay = delay_seconds
            while True:
                attempt += 1
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {attempt} attempts: {exc}"
                        )
                        raise
                    logger.warning(
                        f"{func.__name__} attempt {attempt} failed ({exc}); "
                        f"retrying in {current_delay:.1f}s"
                    )
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

        return wrapper

    return decorator


# =========================================================
# Formatting
# =========================================================

def format_currency(amount: float, currency: str = "INR") -> str:
    """Format a numeric amount as a currency string (e.g. '₹1,234.50')."""
    symbols = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
    symbol = symbols.get(currency.upper(), f"{currency.upper()} ")
    return f"{symbol}{amount:,.2f}"


def slugify(value: str) -> str:
    """Convert a string into a lowercase, hyphen-separated slug."""
    cleaned = "".join(c if c.isalnum() else " " for c in value.lower())
    return "-".join(cleaned.split())


def truncate(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate `text` to `max_length` characters, appending `suffix` if cut."""
    if len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)].rstrip() + suffix