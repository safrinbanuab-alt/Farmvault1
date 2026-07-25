"""
decay_model.py

Predicts how fast a batch of produce loses quality (and eventually spoils)
given its storage conditions. Used by twin_core/scenario_engine.py and
twin_core/produce_twin.py, and exposed indirectly through
api/prediction_routes.py.

Model
-----
Decay is modeled as first-order exponential quality loss:

    quality(t) = quality(0) * exp(-rate * t)

`rate` (fraction of remaining quality lost per day) is derived from a
per-produce "decay curve profile" using a Q10-style temperature response --
the standard approximation used in postharvest physiology, where respiration
(and therefore spoilage) roughly multiplies by a constant factor (Q10, often
1.5-3x for fresh produce) for every 10C the storage temperature sits above
the produce's optimal storage temperature -- combined with a humidity
deviation penalty (both too-dry and too-humid storage accelerate spoilage
relative to the produce's ideal band).

Profiles are loaded from backend/app/data/decay_curves.csv when available
(columns: produce_id, produce_name, optimal_temp_c, optimal_humidity_pct,
base_decay_rate_per_day, q10_coefficient, humidity_sensitivity,
spoilage_quality_threshold_pct, max_shelf_life_days). If the file can't be
found, a built-in table of common produce profiles is used instead, so the
model is always usable standalone (e.g. in tests or notebooks).
"""

from __future__ import annotations

import csv
import logging
import math
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("farmvault.ai_models.decay_model")


# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------
@dataclass
class DecayCurveProfile:
    produce_id: str
    produce_name: str
    optimal_temp_c: float = 4.0
    optimal_humidity_pct: float = 90.0
    base_decay_rate_per_day: float = 0.02
    q10_coefficient: float = 2.0
    humidity_sensitivity: float = 0.01
    spoilage_quality_threshold_pct: float = 60.0
    max_shelf_life_days: float = 30.0

    def to_dict(self) -> dict:
        return {
            "produce_id": self.produce_id,
            "produce_name": self.produce_name,
            "optimal_temp_c": self.optimal_temp_c,
            "optimal_humidity_pct": self.optimal_humidity_pct,
            "base_decay_rate_per_day": self.base_decay_rate_per_day,
            "q10_coefficient": self.q10_coefficient,
            "humidity_sensitivity": self.humidity_sensitivity,
            "spoilage_quality_threshold_pct": self.spoilage_quality_threshold_pct,
            "max_shelf_life_days": self.max_shelf_life_days,
        }


class SpoilageRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --------------------------------------------------------------------------
# Built-in fallback profiles (used when decay_curves.csv is unavailable, or
# to fill in produce that isn't present in the CSV)
# --------------------------------------------------------------------------
DEFAULT_PROFILES: Dict[str, DecayCurveProfile] = {
    "tomato": DecayCurveProfile(
        produce_id="tomato", produce_name="Tomato",
        optimal_temp_c=12.0, optimal_humidity_pct=90.0,
        base_decay_rate_per_day=0.035, q10_coefficient=2.2,
        humidity_sensitivity=0.012, spoilage_quality_threshold_pct=60.0,
        max_shelf_life_days=14.0,
    ),
    "potato": DecayCurveProfile(
        produce_id="potato", produce_name="Potato",
        optimal_temp_c=7.0, optimal_humidity_pct=85.0,
        base_decay_rate_per_day=0.008, q10_coefficient=1.8,
        humidity_sensitivity=0.008, spoilage_quality_threshold_pct=55.0,
        max_shelf_life_days=120.0,
    ),
    "onion": DecayCurveProfile(
        produce_id="onion", produce_name="Onion",
        optimal_temp_c=4.0, optimal_humidity_pct=65.0,
        base_decay_rate_per_day=0.006, q10_coefficient=1.7,
        humidity_sensitivity=0.015, spoilage_quality_threshold_pct=55.0,
        max_shelf_life_days=150.0,
    ),
    "banana": DecayCurveProfile(
        produce_id="banana", produce_name="Banana",
        optimal_temp_c=13.5, optimal_humidity_pct=90.0,
        base_decay_rate_per_day=0.05, q10_coefficient=2.5,
        humidity_sensitivity=0.014, spoilage_quality_threshold_pct=65.0,
        max_shelf_life_days=10.0,
    ),
    "mango": DecayCurveProfile(
        produce_id="mango", produce_name="Mango",
        optimal_temp_c=13.0, optimal_humidity_pct=90.0,
        base_decay_rate_per_day=0.04, q10_coefficient=2.3,
        humidity_sensitivity=0.013, spoilage_quality_threshold_pct=60.0,
        max_shelf_life_days=18.0,
    ),
    "leafy_greens": DecayCurveProfile(
        produce_id="leafy_greens", produce_name="Leafy Greens",
        optimal_temp_c=1.0, optimal_humidity_pct=95.0,
        base_decay_rate_per_day=0.09, q10_coefficient=2.6,
        humidity_sensitivity=0.02, spoilage_quality_threshold_pct=70.0,
        max_shelf_life_days=7.0,
    ),
    "onion_bulb": DecayCurveProfile(
        produce_id="onion_bulb", produce_name="Onion Bulb",
        optimal_temp_c=4.0, optimal_humidity_pct=65.0,
        base_decay_rate_per_day=0.006, q10_coefficient=1.7,
        humidity_sensitivity=0.015, spoilage_quality_threshold_pct=55.0,
        max_shelf_life_days=150.0,
    ),
    "grapes": DecayCurveProfile(
        produce_id="grapes", produce_name="Grapes",
        optimal_temp_c=0.5, optimal_humidity_pct=92.0,
        base_decay_rate_per_day=0.02, q10_coefficient=2.1,
        humidity_sensitivity=0.011, spoilage_quality_threshold_pct=65.0,
        max_shelf_life_days=30.0,
    ),
    "generic": DecayCurveProfile(
        produce_id="generic", produce_name="Generic Produce",
        optimal_temp_c=4.0, optimal_humidity_pct=90.0,
        base_decay_rate_per_day=0.02, q10_coefficient=2.0,
        humidity_sensitivity=0.01, spoilage_quality_threshold_pct=60.0,
        max_shelf_life_days=21.0,
    ),
}

_CSV_FIELD_DEFAULTS = {
    "optimal_temp_c": 4.0,
    "optimal_humidity_pct": 90.0,
    "base_decay_rate_per_day": 0.02,
    "q10_coefficient": 2.0,
    "humidity_sensitivity": 0.01,
    "spoilage_quality_threshold_pct": 60.0,
    "max_shelf_life_days": 30.0,
}


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
class DecayModel:
    """Loads/holds per-produce decay curve profiles and predicts quality
    loss under given storage conditions."""

    def __init__(
        self,
        data_path: Optional[str] = None,
        default_profile_key: str = "generic",
        near_horizon_days: float = 3.0,
    ) -> None:
        self._profiles: Dict[str, DecayCurveProfile] = {}
        self._alias_index: Dict[str, str] = {}
        self._default_profile_key = default_profile_key
        # Shelf-life-remaining threshold (in days) used by
        # assess_spoilage_risk() to flag HIGH risk batches.
        self._near_horizon_days = near_horizon_days
        self._load_profiles(data_path)

    # ------------------------------------------------------------ loading
    def _candidate_paths(self) -> List[str]:
        here = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(here, "..", "app", "data", "decay_curves.csv"),
            os.path.join(here, "..", "data", "decay_curves.csv"),
            os.path.join(here, "data", "decay_curves.csv"),
        ]
        return [os.path.normpath(c) for c in candidates]

    def _load_profiles(self, data_path: Optional[str]) -> None:
        paths_to_try = ([data_path] if data_path else []) + self._candidate_paths()
        loaded_from = None
        for path in paths_to_try:
            if path and os.path.isfile(path):
                try:
                    self._load_csv(path)
                    loaded_from = path
                    break
                except Exception:
                    logger.exception("Failed to parse decay curve CSV at %s", path)

        if loaded_from is None:
            logger.info(
                "No decay_curves.csv found (checked %s) -- using built-in default decay profiles",
                ", ".join(paths_to_try) if paths_to_try else "(no candidate paths)",
            )

        # Seed/merge built-in defaults for any produce not already loaded
        # from CSV, so lookups never fail outright.
        for key, profile in DEFAULT_PROFILES.items():
            self._profiles.setdefault(key, profile)
            self._alias_index.setdefault(profile.produce_name.strip().lower(), key)

    def _load_csv(self, path: str) -> None:
        count = 0
        with open(path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                produce_id = (row.get("produce_id") or "").strip()
                if not produce_id:
                    continue
                produce_name = (row.get("produce_name") or produce_id).strip()

                def _num(field_name: str) -> float:
                    raw = row.get(field_name)
                    if raw is None or str(raw).strip() == "":
                        return _CSV_FIELD_DEFAULTS[field_name]
                    try:
                        return float(raw)
                    except ValueError:
                        return _CSV_FIELD_DEFAULTS[field_name]

                profile = DecayCurveProfile(
                    produce_id=produce_id,
                    produce_name=produce_name,
                    optimal_temp_c=_num("optimal_temp_c"),
                    optimal_humidity_pct=_num("optimal_humidity_pct"),
                    base_decay_rate_per_day=_num("base_decay_rate_per_day"),
                    q10_coefficient=_num("q10_coefficient"),
                    humidity_sensitivity=_num("humidity_sensitivity"),
                    spoilage_quality_threshold_pct=_num("spoilage_quality_threshold_pct"),
                    max_shelf_life_days=_num("max_shelf_life_days"),
                )
                self._profiles[profile.produce_id] = profile
                self._alias_index[profile.produce_name.strip().lower()] = profile.produce_id
                count += 1
        logger.info("Loaded %d decay curve profile(s) from %s", count, path)

    # -------------------------------------------------------------- CRUD
    def register_profile(self, profile: DecayCurveProfile) -> None:
        """Register or override a decay profile at runtime (e.g. from a
        produce record created through the API rather than the CSV seed)."""
        self._profiles[profile.produce_id] = profile
        self._alias_index[profile.produce_name.strip().lower()] = profile.produce_id

    def get_profile(self, produce_id: str) -> DecayCurveProfile:
        if produce_id in self._profiles:
            return self._profiles[produce_id]
        alias_key = self._alias_index.get(produce_id.strip().lower())
        if alias_key and alias_key in self._profiles:
            return self._profiles[alias_key]
        logger.debug(
            "No decay profile found for produce_id='%s' -- using default profile '%s'",
            produce_id, self._default_profile_key,
        )
        return self._profiles.get(self._default_profile_key, DEFAULT_PROFILES["generic"])

    def list_supported_produce(self) -> List[str]:
        return sorted(self._profiles.keys())

    # -------------------------------------------------------- prediction
    def predict_daily_rate(
        self,
        produce_id: str,
        temperature_c: float,
        humidity_pct: float,
        quality_pct: Optional[float] = None,
    ) -> float:
        """Fraction of remaining quality lost per day under the given
        storage conditions (Q10 temperature response x humidity deviation
        penalty). `quality_pct` is accepted for interface compatibility
        with callers that pass current batch quality, but the underlying
        exponential model doesn't need it (rate is quality-independent)."""
        profile = self.get_profile(produce_id)

        temp_delta = temperature_c - profile.optimal_temp_c
        temp_multiplier = profile.q10_coefficient ** (temp_delta / 10.0)

        humidity_deviation = abs(humidity_pct - profile.optimal_humidity_pct)
        humidity_multiplier = 1.0 + profile.humidity_sensitivity * humidity_deviation

        rate = profile.base_decay_rate_per_day * temp_multiplier * humidity_multiplier
        return max(0.0, rate)

    # Aliases kept for compatibility with different caller conventions
    # (twin_core/scenario_engine.py probes for any of these method names).
    def predict(
        self,
        produce_id: str,
        temperature_c: float,
        humidity_pct: float,
        quality_pct: Optional[float] = None,
    ) -> float:
        return self.predict_daily_rate(produce_id, temperature_c, humidity_pct, quality_pct)

    def compute_decay_rate(
        self,
        produce_id: str,
        temperature_c: float,
        humidity_pct: float,
        quality_pct: Optional[float] = None,
    ) -> float:
        return self.predict_daily_rate(produce_id, temperature_c, humidity_pct, quality_pct)

    def project_quality_curve(
        self,
        produce_id: str,
        days: int,
        temperature_c: float,
        humidity_pct: float,
        initial_quality_pct: float = 100.0,
    ) -> List[Tuple[int, float]]:
        """Day-by-day (day, quality_pct) points under constant storage
        conditions -- useful for charting (components/DecayChart.jsx)."""
        rate = self.predict_daily_rate(produce_id, temperature_c, humidity_pct)
        curve: List[Tuple[int, float]] = []
        quality = initial_quality_pct
        for day in range(days + 1):
            curve.append((day, round(quality, 4)))
            quality = max(0.0, quality * math.exp(-rate))
        return curve

    def estimate_shelf_life_days(
        self,
        produce_id: str,
        temperature_c: float,
        humidity_pct: float,
        initial_quality_pct: float = 100.0,
    ) -> float:
        """Days until quality decays to the produce's spoilage threshold,
        capped at the profile's max_shelf_life_days."""
        profile = self.get_profile(produce_id)
        rate = self.predict_daily_rate(produce_id, temperature_c, humidity_pct)
        threshold = profile.spoilage_quality_threshold_pct

        if initial_quality_pct <= threshold:
            return 0.0
        if rate <= 1e-9:
            return profile.max_shelf_life_days

        days = math.log(initial_quality_pct / threshold) / rate
        return round(min(days, profile.max_shelf_life_days), 2)

    def is_spoiled(self, produce_id: str, quality_pct: float) -> bool:
        profile = self.get_profile(produce_id)
        return quality_pct <= profile.spoilage_quality_threshold_pct

    def assess_spoilage_risk(
        self,
        produce_id: str,
        temperature_c: float,
        humidity_pct: float,
        current_quality_pct: float,
    ) -> SpoilageRisk:
        """Coarse risk banding used by services/dashboard_service.py to
        drive alert badges/colors without every caller re-deriving shelf
        life from scratch."""
        profile = self.get_profile(produce_id)
        if self.is_spoiled(produce_id, current_quality_pct):
            return SpoilageRisk.CRITICAL

        remaining_days = self.estimate_shelf_life_days(
            produce_id, temperature_c, humidity_pct, current_quality_pct
        )
        if remaining_days <= self._near_horizon_days:
            return SpoilageRisk.HIGH
        if remaining_days <= self._near_horizon_days * 2.5:
            return SpoilageRisk.MEDIUM

        temp_delta = temperature_c - profile.optimal_temp_c
        if temp_delta > 8:
            return SpoilageRisk.MEDIUM
        return SpoilageRisk.LOW

    def batch_predict(
        self, requests: List[Dict[str, float]]
    ) -> List[Dict[str, float]]:
        """Vectorized-style convenience wrapper: takes a list of dicts each
        with produce_id/temperature_c/humidity_pct[/quality_pct] and returns
        the same list annotated with predicted_daily_rate and
        estimated_shelf_life_days. Used by prediction_routes.py to serve a
        batch prediction endpoint in one call."""
        results = []
        for req in requests:
            produce_id = req["produce_id"]
            temperature_c = float(req["temperature_c"])
            humidity_pct = float(req["humidity_pct"])
            quality_pct = float(req.get("quality_pct", 100.0))

            rate = self.predict_daily_rate(produce_id, temperature_c, humidity_pct, quality_pct)
            shelf_life = self.estimate_shelf_life_days(
                produce_id, temperature_c, humidity_pct, quality_pct
            )
            results.append(
                {
                    **req,
                    "predicted_daily_rate": round(rate, 5),
                    "estimated_shelf_life_days": shelf_life,
                }
            )
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    model = DecayModel()
    print("Supported produce:", model.list_supported_produce())

    for produce in ("tomato", "potato", "banana"):
        rate_cold = model.predict_daily_rate(produce, temperature_c=4.0, humidity_pct=90.0)
        rate_hot = model.predict_daily_rate(produce, temperature_c=30.0, humidity_pct=50.0)
        shelf_cold = model.estimate_shelf_life_days(produce, 4.0, 90.0)
        shelf_hot = model.estimate_shelf_life_days(produce, 30.0, 50.0)
        print(
            f"{produce:12s} cold: rate={rate_cold:.4f}/day shelf_life={shelf_cold:.1f}d | "
            f"hot: rate={rate_hot:.4f}/day shelf_life={shelf_hot:.1f}d"
        )
        risk = model.assess_spoilage_risk(produce, 30.0, 50.0, current_quality_pct=95.0)
        print(f"  -> spoilage risk at hot storage: {risk.value}")

    curve = model.project_quality_curve("tomato", days=7, temperature_c=25.0, humidity_pct=60.0)
    print("Tomato 7-day quality curve @25C/60%RH:", curve)