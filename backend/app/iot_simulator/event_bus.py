"""
event_bus.py
------------
Lightweight in-process async publish/subscribe bus that decouples FarmVault's
IoT simulators (`sensor_generator.py`, `storage_sensor.py`, `market_feed.py`,
`anomaly_injector.py`) from their consumers (`websocket/manager.py`,
`services/dashboard_service.py`, `twin_core/*`).

Design goals:
- No external broker required (in-memory, single-process) -- fine for a
  simulation backend running inside one FastAPI process.
- Supports per-topic subscribers as well as a wildcard "*" subscriber
  (used by the websocket manager to fan every event out to connected
  clients without knowing every topic name in advance).
- Keeps a bounded rolling history per topic so late subscribers (e.g. a
  dashboard that just loaded) can request recent events instead of only
  future ones.
- Subscriber callbacks may be sync or async; both are supported.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, DefaultDict, Deque, Dict, List, Union

try:
    from app.utils.logger import get_logger  # type: ignore
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

Subscriber = Callable[[str, dict], Union[None, Awaitable[None]]]

WILDCARD_TOPIC = "*"
DEFAULT_HISTORY_SIZE = 200


@dataclass
class EventEnvelope:
    event_id: str
    topic: str
    payload: dict
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


class EventBus:
    """A minimal async pub/sub bus. One instance (`event_bus`, below) is
    shared across the whole backend process."""

    def __init__(self, history_size: int = DEFAULT_HISTORY_SIZE) -> None:
        self._subscribers: DefaultDict[str, List[Subscriber]] = defaultdict(list)
        self._history: DefaultDict[str, Deque[dict]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._lock = asyncio.Lock()
        self._event_count = 0

    # -- subscription management --
    def subscribe(self, topic: str, callback: Subscriber) -> Callable[[], None]:
        """Register `callback(topic, payload)` for a specific topic.
        Returns an `unsubscribe()` function."""
        self._subscribers[topic].append(callback)
        logger.debug(f"[event_bus] subscribed to '{topic}'")

        def unsubscribe() -> None:
            try:
                self._subscribers[topic].remove(callback)
            except ValueError:
                pass

        return unsubscribe

    def subscribe_all(self, callback: Subscriber) -> Callable[[], None]:
        """Register a callback that fires for every topic (e.g. websocket fan-out)."""
        return self.subscribe(WILDCARD_TOPIC, callback)

    # -- publishing --
    async def publish(self, topic: str, payload: dict) -> EventEnvelope:
        envelope = EventEnvelope(
            event_id=str(uuid.uuid4()),
            topic=topic,
            payload=payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        async with self._lock:
            self._history[topic].append(envelope.to_dict())
            self._event_count += 1

        callbacks = list(self._subscribers.get(topic, [])) + list(
            self._subscribers.get(WILDCARD_TOPIC, [])
        )
        for callback in callbacks:
            try:
                result = callback(topic, payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"[event_bus] subscriber raised on topic '{topic}': {e}")

        return envelope

    def publish_nowait(self, topic: str, payload: dict) -> None:
        """Fire-and-forget publish for sync call sites. Schedules the publish
        on the running loop if there is one, otherwise runs it synchronously."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(topic, payload))
        except RuntimeError:
            asyncio.run(self.publish(topic, payload))

    # -- introspection --
    def history(self, topic: str, limit: int = 50) -> List[dict]:
        return list(self._history.get(topic, []))[-limit:]

    def topics(self) -> List[str]:
        return [t for t in self._subscribers.keys() if t != WILDCARD_TOPIC]

    def stats(self) -> Dict[str, Any]:
        return {
            "event_count": self._event_count,
            "subscriber_counts": {t: len(subs) for t, subs in self._subscribers.items()},
            "tracked_topics": list(self._history.keys()),
        }
    async def start(self) -> None:
        """Initialize the event bus."""
        logger.info("[event_bus] started")

    async def stop(self) -> None:
        """Shutdown the event bus."""
        logger.info("[event_bus] stopped")


# Shared singleton imported by every simulator module and the websocket manager.
event_bus = EventBus()


if __name__ == "__main__":
    async def _demo():
        def on_event(topic: str, payload: dict) -> None:
            print(f"[sync subscriber] {topic} -> {payload}")

        async def on_event_async(topic: str, payload: dict) -> None:
            await asyncio.sleep(0)
            print(f"[async subscriber] {topic} -> {payload}")

        event_bus.subscribe("demo.topic", on_event)
        event_bus.subscribe("demo.topic", on_event_async)
        event_bus.subscribe_all(lambda t, p: print(f"[wildcard] {t}"))

        await event_bus.publish("demo.topic", {"hello": "world"})
        print("history:", event_bus.history("demo.topic"))
        print("stats:", event_bus.stats())

    asyncio.run(_demo())
    