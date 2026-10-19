from __future__ import annotations

from typing import Any


IMMEDIATE_WAKE_EVENTS = frozenset(
    {
        "payment_failed",
        "shipment_delayed",
        "refund_requested",
        "customer_message_received",
    }
)


def should_wake_for_events(events: list[dict[str, Any]]) -> bool:
    return any(event.get("type") in IMMEDIATE_WAKE_EVENTS for event in events)
