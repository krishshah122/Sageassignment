from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from app.temporal.activities import (
        mark_run_running,
        ping,
        record_agent_error,
        record_order_event,
        record_wake,
        run_agent,
    )
    from app.temporal.policy import should_wake_for_events


@dataclass
class OrderWorkflowInput:
    run_id: str
    base_instruction: str
    available_tools: list[str]
    order_id: str
    order_context: dict[str, Any]
    default_wakeup_seconds: int = 30


@workflow.defn
class NoopWorkflow:
    """Minimal workflow used to prove Temporal worker wiring for Milestone 1."""

    @workflow.run
    async def run(self, name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ApplicationError("name must be a non-empty string", non_retryable=True)
        return await workflow.execute_activity(
            ping,
            name,
            start_to_close_timeout=timedelta(seconds=10),
        )


@workflow.defn
class OrderSupervisorWorkflow:
    """Signal-driven order lifecycle that invokes the agent only on wake triggers."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._finalizing = False
        self._agent_call_count = 0
        self._paused = False
        self._interrupt_requested = False
        self._pending_finalization = False
        self._pending_events: list[dict[str, Any]] = []

    @workflow.signal
    async def order_event(self, event: dict[str, Any]) -> None:
        self._events.append(event)

    @workflow.signal
    async def pause(self) -> None:
        self._paused = True

    @workflow.signal
    async def resume(self) -> None:
        self._paused = False

    @workflow.signal
    async def interrupt(self) -> None:
        self._interrupt_requested = True

    @workflow.run
    async def run(self, input: OrderWorkflowInput) -> None:
        await workflow.execute_activity(
            mark_run_running,
            input.run_id,
            start_to_close_timeout=timedelta(seconds=10),
        )
        result = await self._run_agent(input, "start", [], finalizing=False)
        if result and result["completed"]:
            return
        next_wakeup_at = await self._schedule_next_wake(
            input,
            "start",
            [],
            result,
        )

        while True:
            if self._pending_finalization and not self._paused:
                self._pending_finalization = False
                events, self._pending_events = self._pending_events, []
                result = await self._run_agent(
                    input,
                    "finalization",
                    events,
                    finalizing=True,
                )
                if result and result["completed"]:
                    return
                next_wakeup_at = await self._schedule_next_wake(
                    input,
                    "finalization",
                    [event["type"] for event in events],
                    result,
                )
                continue

            if not self._paused and (
                self._interrupt_requested
                or should_wake_for_events(self._pending_events)
            ):
                cause = "interrupt" if self._interrupt_requested else "important_event"
                self._interrupt_requested = False
                events, self._pending_events = self._pending_events, []
                completed, next_wakeup_at = await self._execute_wake(
                    input,
                    cause,
                    events,
                )
                if completed:
                    return
                continue

            if self._paused:
                await workflow.wait_condition(
                    lambda: bool(self._events) or not self._paused,
                    timeout_summary="order-supervisor-paused",
                )
                if self._events:
                    events, self._events = self._events, []
                    for event in events:
                        await workflow.execute_activity(
                            record_order_event,
                            args=[input.run_id, event],
                            start_to_close_timeout=timedelta(seconds=10),
                        )
                    self._pending_events.extend(events)
                    if any(event["type"] == "delivered" for event in events):
                        self._finalizing = True
                        self._pending_finalization = True
                continue

            remaining = max(0.0, (next_wakeup_at - workflow.now()).total_seconds())
            try:
                await workflow.wait_condition(
                    lambda: bool(self._events)
                    or self._paused
                    or self._interrupt_requested,
                    timeout=remaining,
                    timeout_summary="order-supervisor-scheduled-wake",
                )
            except asyncio.TimeoutError:
                cause = "finalization_retry" if self._finalizing else "scheduled"
                events, self._pending_events = self._pending_events, []
                completed, next_wakeup_at = await self._execute_wake(
                    input,
                    cause,
                    events,
                )
                if completed:
                    return
                continue

            events, self._events = self._events, []
            for event in events:
                await workflow.execute_activity(
                    record_order_event,
                    args=[input.run_id, event],
                    start_to_close_timeout=timedelta(seconds=10),
                )
            self._pending_events.extend(events)
            if any(event["type"] == "delivered" for event in events):
                self._finalizing = True
                self._pending_finalization = True

    async def _execute_wake(
        self,
        input: OrderWorkflowInput,
        cause: str,
        events: list[dict[str, Any]],
    ) -> tuple[bool, datetime]:
        result = await self._run_agent(
            input,
            cause,
            events,
            finalizing=self._finalizing,
        )
        if result and result["completed"]:
            return True, workflow.now()
        next_wakeup_at = await self._schedule_next_wake(
            input,
            cause,
            [event["type"] for event in events],
            result,
        )
        return False, next_wakeup_at

    async def _run_agent(
        self,
        input: OrderWorkflowInput,
        cause: str,
        events: list[dict[str, Any]],
        *,
        finalizing: bool,
    ) -> dict[str, Any] | None:
        self._agent_call_count += 1
        try:
            return await workflow.execute_activity(
                run_agent,
                args=[
                    input.run_id,
                    f"{input.run_id}:agent:{self._agent_call_count}",
                    cause,
                    events,
                    finalizing,
                ],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=2),
                    maximum_attempts=2,
                ),
            )
        except ActivityError as exc:
            await workflow.execute_activity(
                record_agent_error,
                args=[input.run_id, cause, str(exc)],
                start_to_close_timeout=timedelta(seconds=10),
            )
            return None

    async def _schedule_next_wake(
        self,
        input: OrderWorkflowInput,
        cause: str,
        event_types: list[str],
        result: dict[str, Any] | None,
    ) -> datetime:
        seconds = (
            result["next_wakeup_seconds"]
            if result and result["next_wakeup_seconds"] is not None
            else input.default_wakeup_seconds
        )
        next_wakeup_at = workflow.now() + timedelta(seconds=seconds)
        await self._record_wake(input.run_id, cause, event_types, next_wakeup_at)
        return next_wakeup_at

    async def _record_wake(
        self,
        run_id: str,
        cause: str,
        event_types: list[str],
        next_wakeup_at: datetime,
    ) -> None:
        await workflow.execute_activity(
            record_wake,
            args=[run_id, cause, event_types, next_wakeup_at],
            start_to_close_timeout=timedelta(seconds=10),
        )
