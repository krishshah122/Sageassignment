from __future__ import annotations

import pytest

from app.temporal.policy import should_wake_for_events


@pytest.mark.parametrize(
    "event_type",
    [
        "payment_failed",
        "shipment_delayed",
        "refund_requested",
        "customer_message_received",
    ],
)
def test_important_events_wake_agent_policy(event_type: str) -> None:
    assert should_wake_for_events([{"type": event_type}])


@pytest.mark.parametrize(
    "event_type",
    [
        "order_created",
        "payment_confirmed",
        "shipment_created",
        "delivered",
        "no_update_for_n_hours",
    ],
)
def test_routine_events_do_not_wake_agent_policy(event_type: str) -> None:
    assert not should_wake_for_events([{"type": event_type}])


def test_wake_policy_handles_empty_or_malformed_events() -> None:
    assert not should_wake_for_events([])
    assert not should_wake_for_events([{}])
