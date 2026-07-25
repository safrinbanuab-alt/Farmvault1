"""
Produce twin.

The core, framework-agnostic "digital twin" for a single produce batch. This
module owns the decay simulation and health scoring logic that
produce_service.py and simulation_service.py build on. It operates purely on
in-memory model instances - it never touches the database itself; callers
are responsible for persisting any mutations it makes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.models.produce import Produce, ProduceStage, QualityGrade
from app.twin_core.storage_twin import StorageTwin

try:  # pragma: no cover - optional dependency, generated separately
    from app.ai_models.decay_model import predict_decay_rate as _ai_predict_decay_rate
except ImportError:  # pragma: no cover
    _ai_predict_decay_rate = None


# Baseline % decay per day under ideal storage conditions, by category.
# Perishables (fruit/veg/dairy) decay fast; grains/pulses/spices are slow.
BASE_DAILY_DECAY_RATE = {
    "fruit": 4.0,
    "vegetable": 3.5,
    "grain": 0.2,
    "pulse": 0.15,
    "spice": 0.1,
    "dairy": 6.0,
    "other": 3.0,
}

DEFAULT_SPOIL_THRESHOLD = 95.0


@dataclass
class DecayProjectionPoint:
    day: float
    decay_percent: float
    stage: ProduceStage
    quality_grade: QualityGrade


class ProduceTwin:
    """Wraps a Produce ORM instance with decay/health computation."""

    def __init__(self, produce: Produce, storage_twin: Optional[StorageTwin] = None):
        self.produce = produce
        self.storage_twin = storage_twin

    # ---------------------------------------------------------------
    # Construction
    # ---------------------------------------------------------------

    @classmethod
    def from_model(cls, produce: Produce, storage: Optional[object] = None) -> "ProduceTwin":
        """`storage` may be a StorageUnit model instance or an already-built
        StorageTwin; either is accepted for convenience."""

        storage_twin = None
        if isinstance(storage, StorageTwin):
            storage_twin = storage
        elif storage is not None:
            storage_twin = StorageTwin.from_model(storage)
        return cls(produce, storage_twin)

    # ---------------------------------------------------------------
    # Decay rate
    # ---------------------------------------------------------------

    def base_daily_decay_rate(self) -> float:
        category = getattr(self.produce.category, "value", self.produce.category)
        return BASE_DAILY_DECAY_RATE.get(category, BASE_DAILY_DECAY_RATE["other"])

    def daily_decay_rate(self) -> float:
        """Effective %/day decay rate given current storage conditions.
        Delegates to ai_models.decay_model when available, otherwise applies
        the storage twin's environmental stress factor to the category
        baseline."""

        if _ai_predict_decay_rate is not None:
            try:
                return float(
                    _ai_predict_decay_rate(
                        produce=self.produce,
                        storage=self.storage_twin.storage if self.storage_twin else None,
                    )
                )
            except Exception:
                pass  # fall through to heuristic

        rate = self.base_daily_decay_rate()
        if self.storage_twin is not None:
            rate *= self.storage_twin.environmental_stress_factor()
        return round(rate, 3)

    # ---------------------------------------------------------------
    # Simulation (mutating)
    # ---------------------------------------------------------------

    def simulate_tick(self, days: float = 1.0) -> DecayProjectionPoint:
        """Advance the twin's in-memory decay state by `days` and return the
        resulting projection point. This mutates the wrapped Produce object
        in place; the caller (a service) is responsible for committing it."""

        rate = self.daily_decay_rate()
        new_decay = min(100.0, (self.produce.decay_percent or 0.0) + rate * days)

        self.produce.decay_percent = round(new_decay, 2)
        self.produce.days_since_harvest = (self.produce.days_since_harvest or 0.0) + days
        self.produce.current_stage = self.stage_for_decay(new_decay)
        self.produce.quality_grade = self.grade_for_decay(new_decay)

        return DecayProjectionPoint(
            day=self.produce.days_since_harvest,
            decay_percent=self.produce.decay_percent,
            stage=self.produce.current_stage,
            quality_grade=self.produce.quality_grade,
        )

    # ---------------------------------------------------------------
    # Projection (non-mutating)
    # ---------------------------------------------------------------

    def project(self, days: float, step: float = 1.0) -> list[DecayProjectionPoint]:
        """Non-destructive projection: simulate forward without mutating the
        underlying Produce record. Used for scenario comparisons and
        dashboard "days until spoiled" style previews."""

        rate = self.daily_decay_rate()
        starting_decay = self.produce.decay_percent or 0.0
        starting_day = self.produce.days_since_harvest or 0.0

        points: list[DecayProjectionPoint] = []
        elapsed = 0.0
        while elapsed <= days:
            decay = min(100.0, starting_decay + rate * elapsed)
            points.append(
                DecayProjectionPoint(
                    day=round(starting_day + elapsed, 2),
                    decay_percent=round(decay, 2),
                    stage=self.stage_for_decay(decay),
                    quality_grade=self.grade_for_decay(decay),
                )
            )
            elapsed += step
        return points

    # ---------------------------------------------------------------
    # Health / value
    # ---------------------------------------------------------------

    def health_score(self) -> float:
        """0-100 composite health indicator: fresher and well-stored batches
        score higher."""

        decay = self.produce.decay_percent or 0.0
        score = 100.0 - decay

        if self.storage_twin is not None and self.storage_twin.has_environment_breach():
            score -= 15.0

        return round(max(0.0, min(100.0, score)), 1)

    def estimate_value(self, market_price_per_kg: Optional[float]) -> Optional[float]:
        """Current estimated value of the batch, discounted by decay."""

        if market_price_per_kg is None:
            return None
        decay = self.produce.decay_percent or 0.0
        quality_factor = max(0.0, 1 - (decay / 100.0))
        return round(market_price_per_kg * self.produce.quantity_kg * quality_factor, 2)

    def days_until_spoiled(self, spoil_threshold: float = DEFAULT_SPOIL_THRESHOLD) -> Optional[float]:
        rate = self.daily_decay_rate()
        if rate <= 0:
            return None
        remaining = max(0.0, spoil_threshold - (self.produce.decay_percent or 0.0))
        return round(remaining / rate, 1)

    # ---------------------------------------------------------------
    # Classification helpers (kept static so other modules, e.g.
    # simulation_service's heuristic fallback, can reuse the same mapping)
    # ---------------------------------------------------------------

    @staticmethod
    def stage_for_decay(decay_percent: float) -> ProduceStage:
        if decay_percent >= 95:
            return ProduceStage.SPOILED
        if decay_percent >= 70:
            return ProduceStage.DECAYING
        if decay_percent >= 40:
            return ProduceStage.PEAK
        if decay_percent >= 10:
            return ProduceStage.RIPENING
        return ProduceStage.FRESH

    @staticmethod
    def grade_for_decay(decay_percent: float) -> QualityGrade:
        if decay_percent < 20:
            return QualityGrade.A
        if decay_percent < 50:
            return QualityGrade.B
        if decay_percent < 80:
            return QualityGrade.C
        return QualityGrade.REJECTED

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "produce_id": self.produce.id,
            "name": self.produce.name,
            "decay_percent": self.produce.decay_percent,
            "current_stage": self.produce.current_stage.value,
            "quality_grade": self.produce.quality_grade.value,
            "health_score": self.health_score(),
            "daily_decay_rate": self.daily_decay_rate(),
            "days_until_spoiled": self.days_until_spoiled(),
            "as_of": datetime.now(timezone.utc).isoformat(),
        }