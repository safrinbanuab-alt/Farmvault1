"""
scenario_engine.py

Runs "what-if" scenarios against the FarmVault digital twin: e.g. "what
happens if this batch of tomatoes is stored 5C warmer for the next 6 days
and there's a 15% demand spike at the mandi?"

The engine projects, day by day, how storage conditions affect produce
quality/spoilage and how market conditions affect the price the farmer would
realize, then reports revenue, loss-in-value, a recommended action, and lets
multiple scenarios be compared side by side (e.g. "sell now" vs "hold 3 days"
vs "cold-store and hold 7 days").

It is driven by SimulationClock so time advances deterministically and can
be replayed/fast-forwarded independent of wall-clock time.

Where possible the engine defers to the real twin/AI modules
(twin_core.produce_twin, twin_core.storage_twin, twin_core.market_twin,
ai_models.decay_model, ai_models.price_forecaster) so results reflect the
same models the rest of the platform uses. If those objects aren't supplied
or don't expose the expected methods, the engine falls back to built-in
agronomic/economic approximations so it still produces a usable scenario
projection.
"""

from __future__ import annotations

import copy
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .simulation_clock import ClockTickEvent, SimulationClock, TimeUnit

logger = logging.getLogger("farmvault.twin_core.scenario_engine")


# --------------------------------------------------------------------------
# Enums & data models
# --------------------------------------------------------------------------
class ScenarioStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScenarioParameters:
    """The levers a user can pull when building a what-if scenario."""

    storage_temperature_c: Optional[float] = None
    storage_humidity_pct: Optional[float] = None
    transport_delay_days: float = 0.0
    demand_shock_pct: float = 0.0
    supply_shock_pct: float = 0.0
    price_shock_pct: float = 0.0
    handling_quality_factor: float = 1.0

    def to_dict(self) -> dict:
        return {
            "storage_temperature_c": self.storage_temperature_c,
            "storage_humidity_pct": self.storage_humidity_pct,
            "transport_delay_days": self.transport_delay_days,
            "demand_shock_pct": self.demand_shock_pct,
            "supply_shock_pct": self.supply_shock_pct,
            "price_shock_pct": self.price_shock_pct,
            "handling_quality_factor": self.handling_quality_factor,
        }


@dataclass
class Scenario:
    name: str
    produce_id: str
    produce_name: str
    initial_quantity_kg: float
    base_price_per_kg: float
    optimal_storage_temp_c: float = 4.0
    optimal_storage_humidity_pct: float = 90.0
    initial_quality_pct: float = 100.0
    base_decay_rate_per_day: float = 0.015
    duration_days: int = 7
    tick_unit: TimeUnit = TimeUnit.DAY
    description: str = ""
    parameters: ScenarioParameters = field(default_factory=ScenarioParameters)
    scenario_id: str = field(default_factory=lambda: str(uuid4()))
    status: ScenarioStatus = ScenarioStatus.DRAFT
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "name": self.name,
            "description": self.description,
            "produce_id": self.produce_id,
            "produce_name": self.produce_name,
            "initial_quantity_kg": self.initial_quantity_kg,
            "base_price_per_kg": self.base_price_per_kg,
            "optimal_storage_temp_c": self.optimal_storage_temp_c,
            "optimal_storage_humidity_pct": self.optimal_storage_humidity_pct,
            "initial_quality_pct": self.initial_quality_pct,
            "base_decay_rate_per_day": self.base_decay_rate_per_day,
            "duration_days": self.duration_days,
            "tick_unit": self.tick_unit.value,
            "parameters": self.parameters.to_dict(),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ScenarioSnapshot:
    day: int
    timestamp: datetime
    storage_temp_c: float
    storage_humidity_pct: float
    quality_pct: float
    spoilage_pct: float
    sellable_quantity_kg: float
    market_price_per_kg: float
    effective_price_per_kg: float
    projected_revenue: float
    cumulative_loss_value: float
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "timestamp": self.timestamp.isoformat(),
            "storage_temp_c": round(self.storage_temp_c, 2),
            "storage_humidity_pct": round(self.storage_humidity_pct, 2),
            "quality_pct": round(self.quality_pct, 2),
            "spoilage_pct": round(self.spoilage_pct, 2),
            "sellable_quantity_kg": round(self.sellable_quantity_kg, 2),
            "market_price_per_kg": round(self.market_price_per_kg, 2),
            "effective_price_per_kg": round(self.effective_price_per_kg, 2),
            "projected_revenue": round(self.projected_revenue, 2),
            "cumulative_loss_value": round(self.cumulative_loss_value, 2),
            "notes": self.notes,
        }


@dataclass
class ScenarioResult:
    scenario: Scenario
    timeline: List[ScenarioSnapshot]
    total_initial_value: float
    best_sell_day: int
    best_projected_revenue: float
    peak_spoilage_pct: float
    total_loss_value_at_best_day: float
    net_value_at_best_day: float
    breakeven_day: Optional[int]
    recommended_action: str
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario.to_dict(),
            "timeline": [s.to_dict() for s in self.timeline],
            "total_initial_value": round(self.total_initial_value, 2),
            "best_sell_day": self.best_sell_day,
            "best_projected_revenue": round(self.best_projected_revenue, 2),
            "peak_spoilage_pct": round(self.peak_spoilage_pct, 2),
            "total_loss_value_at_best_day": round(self.total_loss_value_at_best_day, 2),
            "net_value_at_best_day": round(self.net_value_at_best_day, 2),
            "breakeven_day": self.breakeven_day,
            "recommended_action": self.recommended_action,
            "generated_at": self.generated_at.isoformat(),
        }


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------
class ScenarioEngine:
    """
    Builds, runs, and compares digital-twin what-if scenarios.

    Usage:
        engine = ScenarioEngine()
        scenario = engine.create_scenario(
            name="Cold storage + 3 day hold",
            produce_id="tomato-batch-14",
            produce_name="Tomato",
            initial_quantity_kg=500,
            base_price_per_kg=18.5,
            duration_days=5,
            parameters=ScenarioParameters(storage_temperature_c=6, demand_shock_pct=10),
        )
        result = engine.run_scenario(scenario)
        print(result.recommended_action)
    """

    #: Loss threshold (fraction of initial batch value) used to flag the
    #: "breakeven" day in a scenario's summary -- i.e. the point beyond
    #: which holding the batch stops being worth the spoilage risk.
    BREAKEVEN_LOSS_FRACTION = 0.20

    def __init__(
        self,
        produce_twin: Optional[Any] = None,
        storage_twin: Optional[Any] = None,
        market_twin: Optional[Any] = None,
        decay_model: Optional[Any] = None,
        price_forecaster: Optional[Any] = None,
    ) -> None:
        self.produce_twin = produce_twin
        self.storage_twin = storage_twin
        self.market_twin = market_twin
        self.decay_model = decay_model
        self.price_forecaster = price_forecaster

        self._scenarios: Dict[str, Scenario] = {}
        self._results: Dict[str, ScenarioResult] = {}

    # ---------------------------------------------------------- authoring
    def create_scenario(
        self,
        name: str,
        produce_id: str,
        produce_name: str,
        initial_quantity_kg: float,
        base_price_per_kg: float,
        optimal_storage_temp_c: float = 4.0,
        optimal_storage_humidity_pct: float = 90.0,
        initial_quality_pct: float = 100.0,
        base_decay_rate_per_day: float = 0.015,
        duration_days: int = 7,
        description: str = "",
        parameters: Optional[ScenarioParameters] = None,
    ) -> Scenario:
        scenario = Scenario(
            name=name,
            produce_id=produce_id,
            produce_name=produce_name,
            initial_quantity_kg=initial_quantity_kg,
            base_price_per_kg=base_price_per_kg,
            optimal_storage_temp_c=optimal_storage_temp_c,
            optimal_storage_humidity_pct=optimal_storage_humidity_pct,
            initial_quality_pct=initial_quality_pct,
            base_decay_rate_per_day=base_decay_rate_per_day,
            duration_days=duration_days,
            description=description,
            parameters=parameters or ScenarioParameters(),
        )
        self._scenarios[scenario.scenario_id] = scenario
        logger.info("Created scenario '%s' (%s)", scenario.name, scenario.scenario_id)
        return scenario

    def clone_scenario(self, scenario: Scenario, **overrides: Any) -> Scenario:
        """Clone an existing scenario, applying field overrides. Useful for
        building a family of scenarios (e.g. sweeping storage temperature)
        without repeating all the boilerplate."""
        cloned = copy.deepcopy(scenario)
        cloned.scenario_id = str(uuid4())
        cloned.created_at = datetime.utcnow()
        cloned.status = ScenarioStatus.DRAFT
        for key, value in overrides.items():
            if key == "parameters" and isinstance(value, dict):
                for p_key, p_val in value.items():
                    setattr(cloned.parameters, p_key, p_val)
            elif hasattr(cloned, key):
                setattr(cloned, key, value)
        self._scenarios[cloned.scenario_id] = cloned
        return cloned

    def get_scenario(self, scenario_id: str) -> Optional[Scenario]:
        return self._scenarios.get(scenario_id)

    def get_result(self, scenario_id: str) -> Optional[ScenarioResult]:
        return self._results.get(scenario_id)

    def list_scenarios(self) -> List[Scenario]:
        return list(self._scenarios.values())

    # -------------------------------------------------------------- run
    def run_scenario(self, scenario: Scenario) -> ScenarioResult:
        """Step the scenario forward day by day using a dedicated
        SimulationClock, projecting quality/spoilage and market price, and
        return the full timeline plus a summary recommendation."""
        scenario.status = ScenarioStatus.RUNNING
        clock = SimulationClock(tick_unit=TimeUnit.DAY, speed_factor=1.0)

        params = scenario.parameters
        storage_temp = (
            params.storage_temperature_c
            if params.storage_temperature_c is not None
            else scenario.optimal_storage_temp_c
        )
        storage_humidity = (
            params.storage_humidity_pct
            if params.storage_humidity_pct is not None
            else scenario.optimal_storage_humidity_pct
        )

        timeline: List[ScenarioSnapshot] = []
        quality_pct = scenario.initial_quality_pct
        cumulative_loss_value = 0.0

        try:
            # Day 0 snapshot (before any decay/time has elapsed).
            timeline.append(
                self._build_snapshot(
                    scenario=scenario,
                    day=0,
                    timestamp=clock.current_time,
                    storage_temp=storage_temp,
                    storage_humidity=storage_humidity,
                    quality_pct=quality_pct,
                    cumulative_loss_value=cumulative_loss_value,
                )
            )

            for day in range(1, scenario.duration_days + 1):
                clock.tick()

                daily_rate = self._resolve_decay_rate(
                    scenario=scenario,
                    storage_temp=storage_temp,
                    storage_humidity=storage_humidity,
                )
                quality_pct = max(0.0, quality_pct * math.exp(-daily_rate))

                snapshot = self._build_snapshot(
                    scenario=scenario,
                    day=day,
                    timestamp=clock.current_time,
                    storage_temp=storage_temp,
                    storage_humidity=storage_humidity,
                    quality_pct=quality_pct,
                    cumulative_loss_value=None,  # computed inside _build_snapshot
                )
                cumulative_loss_value = snapshot.cumulative_loss_value
                timeline.append(snapshot)

            result = self._summarize(scenario, timeline)
            scenario.status = ScenarioStatus.COMPLETED
            self._results[scenario.scenario_id] = result
            logger.info(
                "Scenario '%s' completed: best_sell_day=%s net_value=%.2f",
                scenario.name,
                result.best_sell_day,
                result.net_value_at_best_day,
            )
            return result
        except Exception:
            scenario.status = ScenarioStatus.FAILED
            logger.exception("Scenario '%s' failed to run", scenario.name)
            raise
        finally:
            clock.stop()

    def run_batch(self, scenarios: List[Scenario]) -> List[ScenarioResult]:
        return [self.run_scenario(scenario) for scenario in scenarios]

    # --------------------------------------------------------- comparison
    def compare_scenarios(
        self, results: List[ScenarioResult], baseline_index: int = 0
    ) -> Dict[str, Any]:
        """Rank scenario results by net value at each scenario's own best
        sell day, and express every other scenario as a delta against the
        baseline (defaults to the first result in the list)."""
        if not results:
            return {"baseline": None, "ranked": [], "best_scenario_id": None}

        baseline = results[baseline_index]
        ranked = sorted(results, key=lambda r: r.net_value_at_best_day, reverse=True)

        comparison_rows = []
        for result in ranked:
            delta_vs_baseline = result.net_value_at_best_day - baseline.net_value_at_best_day
            comparison_rows.append(
                {
                    "scenario_id": result.scenario.scenario_id,
                    "scenario_name": result.scenario.name,
                    "best_sell_day": result.best_sell_day,
                    "net_value_at_best_day": round(result.net_value_at_best_day, 2),
                    "peak_spoilage_pct": round(result.peak_spoilage_pct, 2),
                    "delta_vs_baseline": round(delta_vs_baseline, 2),
                    "recommended_action": result.recommended_action,
                }
            )

        return {
            "baseline_scenario_id": baseline.scenario.scenario_id,
            "ranked": comparison_rows,
            "best_scenario_id": ranked[0].scenario.scenario_id if ranked else None,
        }

    # ---------------------------------------------------------- internals
    def _resolve_decay_rate(
        self, scenario: Scenario, storage_temp: float, storage_humidity: float
    ) -> float:
        """Prefer the real decay_model if one was supplied and exposes a
        compatible interface; otherwise fall back to a physically-plausible
        approximation: decay accelerates with temperature above the
        produce's optimal storage point and with humidity deviation, scaled
        by a handling-quality multiplier (rough handling/transport bruises
        produce and accelerates spoilage)."""
        if self.decay_model is not None:
            for method_name in ("predict_daily_rate", "predict", "compute_decay_rate"):
                method = getattr(self.decay_model, method_name, None)
                if callable(method):
                    try:
                        return float(
                            method(
                                produce_id=scenario.produce_id,
                                temperature_c=storage_temp,
                                humidity_pct=storage_humidity,
                            )
                        )
                    except TypeError:
                        try:
                            return float(method(storage_temp, storage_humidity))
                        except Exception:
                            logger.debug(
                                "decay_model.%s incompatible signature, using fallback",
                                method_name,
                            )
                    except Exception:
                        logger.exception(
                            "decay_model.%s raised an exception, using fallback", method_name
                        )

        return self._fallback_decay_rate(scenario, storage_temp, storage_humidity)

    def _fallback_decay_rate(
        self, scenario: Scenario, storage_temp: float, storage_humidity: float
    ) -> float:
        temp_excess = max(0.0, storage_temp - scenario.optimal_storage_temp_c)
        humidity_deviation = abs(storage_humidity - scenario.optimal_storage_humidity_pct)
        transport_penalty = 1.0 + (0.05 * scenario.parameters.transport_delay_days)

        rate = (
            scenario.base_decay_rate_per_day
            * (1.0 + 0.12 * temp_excess)
            * (1.0 + 0.01 * humidity_deviation)
            * scenario.parameters.handling_quality_factor
            * transport_penalty
        )
        return max(0.0, rate)

    def _resolve_market_price(self, scenario: Scenario, day: int) -> float:
        """Prefer the real price_forecaster if supplied; otherwise apply the
        scenario's demand/supply/price shocks as a simple linear model on
        top of the produce's base mandi price."""
        if self.price_forecaster is not None:
            for method_name in ("forecast_price", "forecast", "predict_price"):
                method = getattr(self.price_forecaster, method_name, None)
                if callable(method):
                    try:
                        return float(
                            method(produce_id=scenario.produce_id, day_offset=day)
                        )
                    except TypeError:
                        try:
                            return float(method(scenario.produce_id, day))
                        except Exception:
                            logger.debug(
                                "price_forecaster.%s incompatible signature, using fallback",
                                method_name,
                            )
                    except Exception:
                        logger.exception(
                            "price_forecaster.%s raised an exception, using fallback",
                            method_name,
                        )

        return self._fallback_market_price(scenario, day)

    def _fallback_market_price(self, scenario: Scenario, day: int) -> float:
        params = scenario.parameters
        net_demand_pct = params.demand_shock_pct - params.supply_shock_pct
        # Shocks are modeled as ramping in gradually over the first 3 days
        # rather than hitting all at once, which is more representative of
        # real mandi price discovery.
        ramp = min(1.0, day / 3.0) if day > 0 else 0.0
        price = scenario.base_price_per_kg * (
            1.0 + (params.price_shock_pct / 100.0) * ramp + (net_demand_pct / 100.0) * ramp
        )
        return max(0.0, price)

    def _build_snapshot(
        self,
        scenario: Scenario,
        day: int,
        timestamp: datetime,
        storage_temp: float,
        storage_humidity: float,
        quality_pct: float,
        cumulative_loss_value: Optional[float],
    ) -> ScenarioSnapshot:
        spoilage_pct = 100.0 - quality_pct
        sellable_quantity_kg = scenario.initial_quantity_kg * (quality_pct / 100.0)
        market_price = self._resolve_market_price(scenario, day)

        # Buyers discount visibly lower-quality produce faster than a 1:1
        # relationship -- a batch at 70% quality doesn't fetch 70% of the
        # price, it fetches noticeably less (sqrt discount curve).
        quality_discount = math.sqrt(max(0.0, quality_pct) / 100.0)
        effective_price = market_price * quality_discount

        projected_revenue = sellable_quantity_kg * effective_price

        spoiled_quantity_kg = scenario.initial_quantity_kg - sellable_quantity_kg
        loss_value = spoiled_quantity_kg * scenario.base_price_per_kg

        notes: List[str] = []
        if spoilage_pct >= 50:
            notes.append("Spoilage has crossed 50% -- batch is largely unsellable.")
        elif spoilage_pct >= 25:
            notes.append("Spoilage exceeding 25% -- consider selling soon.")
        if storage_temp > scenario.optimal_storage_temp_c + 5:
            notes.append("Storage temperature far above optimal -- accelerated decay.")

        return ScenarioSnapshot(
            day=day,
            timestamp=timestamp,
            storage_temp_c=storage_temp,
            storage_humidity_pct=storage_humidity,
            quality_pct=quality_pct,
            spoilage_pct=spoilage_pct,
            sellable_quantity_kg=sellable_quantity_kg,
            market_price_per_kg=market_price,
            effective_price_per_kg=effective_price,
            projected_revenue=projected_revenue,
            cumulative_loss_value=loss_value,
            notes=notes,
        )

    def _summarize(self, scenario: Scenario, timeline: List[ScenarioSnapshot]) -> ScenarioResult:
        total_initial_value = scenario.initial_quantity_kg * scenario.base_price_per_kg

        best_snapshot = max(timeline, key=lambda s: s.projected_revenue)
        peak_spoilage_pct = max(s.spoilage_pct for s in timeline)

        net_value_at_best_day = best_snapshot.projected_revenue - best_snapshot.cumulative_loss_value

        breakeven_day: Optional[int] = None
        loss_threshold_value = total_initial_value * self.BREAKEVEN_LOSS_FRACTION
        for snapshot in timeline:
            if snapshot.cumulative_loss_value >= loss_threshold_value:
                breakeven_day = snapshot.day
                break

        recommended_action = self._recommend_action(
            scenario=scenario,
            timeline=timeline,
            best_snapshot=best_snapshot,
            breakeven_day=breakeven_day,
        )

        return ScenarioResult(
            scenario=scenario,
            timeline=timeline,
            total_initial_value=total_initial_value,
            best_sell_day=best_snapshot.day,
            best_projected_revenue=best_snapshot.projected_revenue,
            peak_spoilage_pct=peak_spoilage_pct,
            total_loss_value_at_best_day=best_snapshot.cumulative_loss_value,
            net_value_at_best_day=net_value_at_best_day,
            breakeven_day=breakeven_day,
            recommended_action=recommended_action,
        )

    def _recommend_action(
        self,
        scenario: Scenario,
        timeline: List[ScenarioSnapshot],
        best_snapshot: ScenarioSnapshot,
        breakeven_day: Optional[int],
    ) -> str:
        day0_revenue = timeline[0].projected_revenue if timeline else 0.0

        if best_snapshot.day == 0:
            return (
                f"Sell immediately. Holding {scenario.produce_name} under the modeled "
                f"conditions loses value faster than any price/demand upside can offset."
            )

        if breakeven_day is not None and breakeven_day <= best_snapshot.day:
            return (
                f"Sell by day {breakeven_day}. Spoilage crosses the "
                f"{int(self.BREAKEVEN_LOSS_FRACTION * 100)}% value-loss threshold around then, "
                f"even though revenue could technically peak on day {best_snapshot.day}."
            )

        revenue_gain_pct = (
            ((best_snapshot.projected_revenue - day0_revenue) / day0_revenue) * 100.0
            if day0_revenue > 0
            else 0.0
        )
        return (
            f"Hold for {best_snapshot.day} day(s), then sell. Projected revenue peaks at "
            f"day {best_snapshot.day} (~{revenue_gain_pct:.1f}% above selling immediately) "
            f"before spoilage erodes further gains."
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    engine = ScenarioEngine()

    baseline = engine.create_scenario(
        name="Sell immediately (ambient storage)",
        produce_id="tomato-batch-14",
        produce_name="Tomato",
        initial_quantity_kg=500,
        base_price_per_kg=18.5,
        optimal_storage_temp_c=4.0,
        optimal_storage_humidity_pct=90.0,
        duration_days=6,
        parameters=ScenarioParameters(storage_temperature_c=28.0, storage_humidity_pct=55.0),
    )

    cold_hold = engine.clone_scenario(
        baseline,
        name="Cold-store + hold for demand spike",
        parameters={
            "storage_temperature_c": 5.0,
            "storage_humidity_pct": 90.0,
            "demand_shock_pct": 15.0,
            "handling_quality_factor": 1.0,
        },
    )

    results = engine.run_batch([baseline, cold_hold])
    for res in results:
        print(f"\n=== {res.scenario.name} ===")
        print(res.recommended_action)
        print(f"Best sell day: {res.best_sell_day}, net value: {res.net_value_at_best_day:.2f}")

    comparison = engine.compare_scenarios(results)
    print("\n=== Comparison ===")
    for row in comparison["ranked"]:
        print(row)