"""
simulation_clock.py

Provides a controllable virtual clock that drives the FarmVault digital-twin
simulation. The clock decouples "wall-clock" time from "simulated" time so
the platform can fast-forward days or weeks of produce decay and market
movement in seconds (for scenario analysis), or advance one tick at a time
for deterministic, reproducible runs.

Two modes of operation:
  * Real-time driven -- a background thread advances simulated time on a
    wall-clock interval, scaled by `speed_factor` (e.g. speed_factor=3600
    means 1 real second == 1 simulated hour). Used to "live stream" a
    running simulation to the dashboard over the websocket manager.
  * Manual stepping -- `tick()` / `advance()` / `advance_days()` are called
    explicitly (e.g. by scenario_engine.py) so a scenario can be replayed
    deterministically without depending on wall-clock timing.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger("farmvault.twin_core.simulation_clock")


class ClockState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class TimeUnit(str, Enum):
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"


_TIME_UNIT_SECONDS: Dict[TimeUnit, int] = {
    TimeUnit.SECOND: 1,
    TimeUnit.MINUTE: 60,
    TimeUnit.HOUR: 3600,
    TimeUnit.DAY: 86400,
}


@dataclass
class ClockTickEvent:
    tick_id: int
    simulated_time: datetime
    elapsed_simulated_seconds: float
    delta_simulated_seconds: float
    speed_factor: float
    state: ClockState

    def to_dict(self) -> dict:
        return {
            "tick_id": self.tick_id,
            "simulated_time": self.simulated_time.isoformat(),
            "elapsed_simulated_seconds": self.elapsed_simulated_seconds,
            "delta_simulated_seconds": self.delta_simulated_seconds,
            "speed_factor": self.speed_factor,
            "state": self.state.value,
        }


@dataclass
class ScheduledEvent:
    """A one-shot or recurring callback scheduled against simulated time."""

    event_id: str
    run_at: datetime
    callback: Callable[[datetime], None]
    interval_seconds: Optional[float] = None
    recurring: bool = False
    label: str = ""


TickCallback = Callable[[ClockTickEvent], None]


class SimulationClock:
    """Drives simulated time forward for the digital twin engine."""

    def __init__(
        self,
        start_time: Optional[datetime] = None,
        tick_unit: TimeUnit = TimeUnit.HOUR,
        speed_factor: float = 1.0,
        real_tick_interval_seconds: float = 1.0,
    ) -> None:
        self._start_time: datetime = start_time or datetime.utcnow()
        self._current_time: datetime = self._start_time
        self._tick_unit = tick_unit
        self._tick_seconds = _TIME_UNIT_SECONDS[tick_unit]
        self._speed_factor = max(speed_factor, 0.0001)
        self._real_tick_interval_seconds = max(real_tick_interval_seconds, 0.01)

        self._state = ClockState.STOPPED
        self._tick_count = 0
        self._lock = threading.RLock()

        self._tick_callbacks: List[TickCallback] = []
        self._scheduled_events: Dict[str, ScheduledEvent] = {}

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ---------------------------------------------------------------- info
    @property
    def state(self) -> ClockState:
        return self._state

    @property
    def current_time(self) -> datetime:
        with self._lock:
            return self._current_time

    @property
    def start_time(self) -> datetime:
        return self._start_time

    @property
    def tick_count(self) -> int:
        return self._tick_count

    @property
    def tick_unit(self) -> TimeUnit:
        return self._tick_unit

    @property
    def speed_factor(self) -> float:
        return self._speed_factor

    @property
    def elapsed_simulated_seconds(self) -> float:
        with self._lock:
            return (self._current_time - self._start_time).total_seconds()

    def elapsed_days(self) -> float:
        return self.elapsed_simulated_seconds / 86400.0

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "start_time": self._start_time.isoformat(),
                "current_time": self._current_time.isoformat(),
                "tick_unit": self._tick_unit.value,
                "speed_factor": self._speed_factor,
                "tick_count": self._tick_count,
                "elapsed_days": round(self.elapsed_days(), 4),
            }

    # ------------------------------------------------------------ control
    def start(self, real_time_driven: bool = True) -> None:
        """Start the clock. If real_time_driven, spins up a background
        thread that advances simulated time automatically."""
        with self._lock:
            if self._state == ClockState.RUNNING:
                logger.debug("SimulationClock.start() called while already running")
                return
            self._state = ClockState.RUNNING
            self._stop_event.clear()

        if real_time_driven:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run_loop, name="SimulationClockThread", daemon=True
                )
                self._thread.start()
        logger.info(
            "SimulationClock started at %s (speed=%sx)", self._current_time, self._speed_factor
        )

    def pause(self) -> None:
        with self._lock:
            if self._state == ClockState.RUNNING:
                self._state = ClockState.PAUSED
                logger.info("SimulationClock paused at %s", self._current_time)

    def resume(self) -> None:
        with self._lock:
            if self._state == ClockState.PAUSED:
                self._state = ClockState.RUNNING
                logger.info("SimulationClock resumed at %s", self._current_time)

    def stop(self) -> None:
        with self._lock:
            self._state = ClockState.STOPPED
        self._stop_event.set()
        if (
            self._thread is not None
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=2.0)
        logger.info("SimulationClock stopped at %s", self._current_time)

    def reset(self, start_time: Optional[datetime] = None) -> None:
        self.stop()
        with self._lock:
            self._start_time = start_time or datetime.utcnow()
            self._current_time = self._start_time
            self._tick_count = 0
            self._scheduled_events.clear()
        logger.info("SimulationClock reset to %s", self._current_time)

    def set_speed(self, speed_factor: float) -> None:
        with self._lock:
            self._speed_factor = max(speed_factor, 0.0001)
        logger.debug("SimulationClock speed set to %sx", self._speed_factor)

    # -------------------------------------------------------- manual step
    def tick(self) -> ClockTickEvent:
        """Advance the clock by exactly one tick_unit. Safe to call manually
        even while the real-time thread is stopped (deterministic mode)."""
        return self.advance(seconds=self._tick_seconds)

    def advance(self, seconds: float) -> ClockTickEvent:
        """Advance simulated time by an arbitrary number of simulated
        seconds and fire all due callbacks/tick subscribers."""
        with self._lock:
            previous_time = self._current_time
            self._current_time = self._current_time + timedelta(seconds=seconds)
            self._tick_count += 1
            event = ClockTickEvent(
                tick_id=self._tick_count,
                simulated_time=self._current_time,
                elapsed_simulated_seconds=(self._current_time - self._start_time).total_seconds(),
                delta_simulated_seconds=seconds,
                speed_factor=self._speed_factor,
                state=self._state,
            )
            due_events = self._pop_due_events(previous_time, self._current_time)

        self._fire_tick_callbacks(event)
        for scheduled in due_events:
            self._fire_scheduled_event(scheduled)
        return event

    def advance_days(self, days: float) -> List[ClockTickEvent]:
        """Advance the clock day-by-day (stepping in units of tick_unit),
        returning every intermediate tick event. This is the primary entry
        point scenario_engine.py uses to fast-forward a simulation N days
        into the future."""
        total_seconds = days * 86400.0
        events: List[ClockTickEvent] = []
        remaining = total_seconds
        step = float(self._tick_seconds)
        while remaining > 1e-9:
            this_step = min(step, remaining)
            events.append(self.advance(seconds=this_step))
            remaining -= this_step
        return events

    def jump_to(self, target_time: datetime) -> ClockTickEvent:
        """Jump directly to a target simulated timestamp (used for scenario
        replays that don't need intermediate ticks)."""
        with self._lock:
            delta = (target_time - self._current_time).total_seconds()
        if delta < 0:
            raise ValueError("Cannot jump backwards in simulated time; use reset() instead")
        return self.advance(seconds=delta)

    # ------------------------------------------------------------- events
    def on_tick(self, callback: TickCallback) -> None:
        self._tick_callbacks.append(callback)

    def remove_tick_callback(self, callback: TickCallback) -> None:
        if callback in self._tick_callbacks:
            self._tick_callbacks.remove(callback)

    def schedule_at(
        self,
        run_at: datetime,
        callback: Callable[[datetime], None],
        label: str = "",
    ) -> str:
        event_id = str(uuid4())
        with self._lock:
            self._scheduled_events[event_id] = ScheduledEvent(
                event_id=event_id, run_at=run_at, callback=callback, label=label
            )
        return event_id

    def schedule_every(
        self,
        interval_seconds: float,
        callback: Callable[[datetime], None],
        label: str = "",
        first_run_at: Optional[datetime] = None,
    ) -> str:
        event_id = str(uuid4())
        with self._lock:
            run_at = first_run_at or (self._current_time + timedelta(seconds=interval_seconds))
            self._scheduled_events[event_id] = ScheduledEvent(
                event_id=event_id,
                run_at=run_at,
                callback=callback,
                interval_seconds=interval_seconds,
                recurring=True,
                label=label,
            )
        return event_id

    def cancel_scheduled(self, event_id: str) -> bool:
        with self._lock:
            return self._scheduled_events.pop(event_id, None) is not None

    # ---------------------------------------------------------- internals
    def _pop_due_events(self, previous_time: datetime, new_time: datetime) -> List[ScheduledEvent]:
        due: List[ScheduledEvent] = []
        for event_id, scheduled in list(self._scheduled_events.items()):
            if previous_time < scheduled.run_at <= new_time:
                due.append(scheduled)
                if scheduled.recurring and scheduled.interval_seconds:
                    scheduled.run_at = scheduled.run_at + timedelta(seconds=scheduled.interval_seconds)
                else:
                    self._scheduled_events.pop(event_id, None)
        return due

    def _fire_tick_callbacks(self, event: ClockTickEvent) -> None:
        for callback in list(self._tick_callbacks):
            try:
                callback(event)
            except Exception:
                logger.exception("SimulationClock tick callback raised an exception")

    def _fire_scheduled_event(self, scheduled: ScheduledEvent) -> None:
        try:
            scheduled.callback(scheduled.run_at)
        except Exception:
            logger.exception(
                "SimulationClock scheduled event '%s' raised an exception", scheduled.label
            )

    def _run_loop(self) -> None:
        logger.debug("SimulationClock real-time loop started")
        while not self._stop_event.is_set():
            with self._lock:
                current_state = self._state
                speed = self._speed_factor
            if current_state == ClockState.RUNNING:
                simulated_seconds = self._real_tick_interval_seconds * speed
                self.advance(seconds=simulated_seconds)
            time.sleep(self._real_tick_interval_seconds)
        logger.debug("SimulationClock real-time loop exiting")


def create_clock(
    start_time: Optional[datetime] = None,
    tick_unit: str = "hour",
    speed_factor: float = 1.0,
) -> SimulationClock:
    """Convenience factory used by services/dashboard_service.py and
    twin_core/scenario_engine.py to spin up a fresh clock instance."""
    return SimulationClock(
        start_time=start_time,
        tick_unit=TimeUnit(tick_unit),
        speed_factor=speed_factor,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    clock = create_clock(tick_unit="hour", speed_factor=1.0)

    def _print_tick(evt: ClockTickEvent) -> None:
        print(f"tick #{evt.tick_id} -> {evt.simulated_time.isoformat()}")

    clock.on_tick(_print_tick)
    clock.schedule_at(
        clock.current_time + timedelta(days=1),
        lambda ts: print(f"scheduled event fired at {ts.isoformat()}"),
        label="one-day-check",
    )
    events = clock.advance_days(1.5)
    print(f"advanced {len(events)} ticks, now at {clock.current_time.isoformat()}")
    print(clock.to_dict())