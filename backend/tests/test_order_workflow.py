from __future__ import annotations

import asyncio
import json
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.agent.tools import AgentDecision, FinalOutput, PlannedAction
from app.db.models import Base, Run, RunFinalOutput, RunMemory, Supervisor, TimelineEntry
from app.temporal import activities
from app.temporal.workflow import OrderSupervisorWorkflow, OrderWorkflowInput


async def wait_for_timeline(
    engine: Engine,
    run_id: UUID,
    *,
    event_types: Collection[str],
    wake_causes: Collection[str],
) -> list[TimelineEntry]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        with Session(engine) as session:
            entries = session.scalars(
                select(TimelineEntry).where(TimelineEntry.run_id == run_id)
            ).all()
        observed_events = {entry.type for entry in entries if entry.kind == "event"}
        observed_causes = {
            entry.payload["cause"]
            for entry in entries
            if entry.type == "wake_trigger"
        }
        if set(event_types) <= observed_events and set(wake_causes) <= observed_causes:
            return list(entries)
        await asyncio.sleep(0.01)
    pytest.fail(
        f"Timed out waiting for events {set(event_types)} and wake causes {set(wake_causes)}; "
        f"observed events {observed_events}, wake causes {observed_causes}"
    )


async def wait_for_agent_runs(engine: Engine, run_id: UUID, count: int) -> list[TimelineEntry]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5
    while loop.time() < deadline:
        with Session(engine) as session:
            entries = session.scalars(
                select(TimelineEntry)
                .where(
                    TimelineEntry.run_id == run_id,
                    TimelineEntry.type == "agent_run",
                )
                .order_by(TimelineEntry.created_at.asc(), TimelineEntry.id.asc())
            ).all()
        if len(entries) >= count:
            return list(entries)
        await asyncio.sleep(0.01)
    pytest.fail(f"Timed out waiting for {count} agent runs; observed {len(entries)}")


@pytest.mark.asyncio
async def test_order_workflow_records_events_and_completes_on_delivery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}")
    Base.metadata.create_all(engine)
    run_id = uuid4()
    with Session(engine) as session:
        supervisor = Supervisor(
            name="Test",
            base_instruction="Watch the order.",
            available_tools=["create_internal_note"],
        )
        session.add(supervisor)
        session.flush()
        session.add(
            Run(
                id=run_id,
                supervisor_id=supervisor.id,
                order_id="ORD-2",
                order_context={},
                extra_instructions=[],
                status="starting",
                temporal_workflow_id=str(run_id),
            )
        )
        session.commit()
    monkeypatch.setattr(activities, "get_engine", lambda: engine)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")

    async def fake_request_decision(
        *,
        messages: list[dict[str, str]],
        api_key: str,
        model: str,
    ) -> AgentDecision:
        request = json.loads(messages[1]["content"])
        if request["finalizing"]:
            return AgentDecision(
                summary="Order delivered.",
                memory_summary="The order was delivered successfully.",
                actions=[],
                final_output=FinalOutput(
                    summary="Order delivered successfully.",
                    important_actions=[{"action": "order delivered"}],
                    learnings="The order completed.",
                    feedback="No further action is needed.",
                ),
            )
        actions = (
            [
                PlannedAction(
                    name="create_internal_note",
                    arguments={"note": "Shipment delay reviewed."},
                )
            ]
            if request["trigger"] == "important_event"
            else []
        )
        return AgentDecision(
            summary=f"Reviewed trigger {request['trigger']}.",
            memory_summary="The order is being monitored.",
            actions=actions,
        )

    monkeypatch.setattr(activities, "request_decision", fake_request_decision)

    workflow_input = OrderWorkflowInput(
        run_id=str(run_id),
        base_instruction="Watch the order.",
        available_tools=["create_internal_note"],
        order_id="ORD-2",
        order_context={},
        default_wakeup_seconds=3600,
    )
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with env.auto_time_skipping_disabled():
            with ThreadPoolExecutor(max_workers=2) as activity_executor:
                async with Worker(
                    env.client,
                    task_queue="test-order-supervisor",
                    workflows=[OrderSupervisorWorkflow],
                    activities=[
                        activities.mark_run_running,
                        activities.record_order_event,
                        activities.record_wake,
                        activities.run_agent,
                        activities.record_agent_error,
                    ],
                    activity_executor=activity_executor,
                ):
                    handle: WorkflowHandle = await env.client.start_workflow(
                        OrderSupervisorWorkflow.run,
                        workflow_input,
                        id=str(run_id),
                        task_queue="test-order-supervisor",
                    )
                    await handle.signal(
                        OrderSupervisorWorkflow.order_event,
                        {"type": "payment_confirmed", "payload": {}},
                    )
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"payment_confirmed"},
                        wake_causes={"start"},
                    )
                    with Session(engine) as session:
                        sleeping_run = session.get(Run, run_id)
                    assert sleeping_run is not None
                    assert sleeping_run.status == "sleeping"
                    assert sleeping_run.sleep_until is not None

                    await handle.signal(
                        OrderSupervisorWorkflow.order_event,
                        {"type": "shipment_delayed", "payload": {"reason": "weather"}},
                    )
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"payment_confirmed", "shipment_delayed"},
                        wake_causes={"start", "important_event"},
                    )
                    with Session(engine) as session:
                        wake_entries = session.scalars(
                            select(TimelineEntry).where(
                                TimelineEntry.run_id == run_id,
                                TimelineEntry.type == "wake_trigger",
                            )
                        ).all()
                    assert [entry.payload["cause"] for entry in wake_entries] == [
                        "start",
                        "important_event",
                    ]

                    await env.sleep(3600)
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"payment_confirmed", "shipment_delayed"},
                        wake_causes={"start", "important_event", "scheduled"},
                    )
                    with Session(engine) as session:
                        wake_entries = session.scalars(
                            select(TimelineEntry).where(
                                TimelineEntry.run_id == run_id,
                                TimelineEntry.type == "wake_trigger",
                            )
                        ).all()
                    assert [entry.payload["cause"] for entry in wake_entries] == [
                        "start",
                        "important_event",
                        "scheduled",
                    ]

                    await handle.signal(
                        OrderSupervisorWorkflow.order_event,
                        {"type": "delivered", "payload": {}},
                    )
                    await handle.result()

    with Session(engine) as session:
        run = session.get(Run, run_id)
        memory = session.get(RunMemory, run_id)
        final_output = session.get(RunFinalOutput, run_id)
        entries = session.scalars(
            select(TimelineEntry)
            .where(TimelineEntry.run_id == run_id)
            .order_by(TimelineEntry.created_at.asc(), TimelineEntry.id.asc())
        ).all()
    assert run is not None
    assert run.status == "completed"
    assert run.sleep_until is None
    assert memory is not None
    assert memory.summary == "The order was delivered successfully."
    assert final_output is not None
    assert final_output.summary == "Order delivered successfully."
    assert {
        entry.type for entry in entries if entry.kind == "event"
    } == {"payment_confirmed", "shipment_delayed", "delivered"}
    assert any(
        entry.kind == "action"
        and entry.type == "create_internal_note"
        and entry.payload["status"] == "succeeded"
        and entry.payload["result"]["created"] == "simulated"
        for entry in entries
    )
    engine.dispose()


@pytest.mark.asyncio
async def test_pause_defers_wakes_and_interrupt_runs_after_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'controls.db'}")
    Base.metadata.create_all(engine)
    run_id = uuid4()
    with Session(engine) as session:
        supervisor = Supervisor(
            name="Test",
            base_instruction="Watch the order.",
            available_tools=["create_internal_note"],
        )
        session.add(supervisor)
        session.flush()
        session.add(
            Run(
                id=run_id,
                supervisor_id=supervisor.id,
                order_id="ORD-4",
                order_context={},
                extra_instructions=[],
                status="starting",
                temporal_workflow_id=str(run_id),
            )
        )
        session.commit()
    monkeypatch.setattr(activities, "get_engine", lambda: engine)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'controls.db'}")
    monkeypatch.setenv("TEMPORAL_ADDRESS", "localhost:7233")
    observed_instructions: list[list[str]] = []

    async def fake_request_decision(
        *,
        messages: list[dict[str, str]],
        api_key: str,
        model: str,
    ) -> AgentDecision:
        request = json.loads(messages[1]["content"])
        observed_instructions.append(request["run_instructions"])
        return AgentDecision(
            summary=f"Reviewed trigger {request['trigger']}.",
            memory_summary="The order is being monitored.",
            actions=[],
        )

    monkeypatch.setattr(activities, "request_decision", fake_request_decision)
    workflow_input = OrderWorkflowInput(
        run_id=str(run_id),
        base_instruction="Watch the order.",
        available_tools=[],
        order_id="ORD-4",
        order_context={},
        default_wakeup_seconds=3600,
    )
    async with await WorkflowEnvironment.start_time_skipping() as env:
        with env.auto_time_skipping_disabled():
            with ThreadPoolExecutor(max_workers=2) as activity_executor:
                async with Worker(
                    env.client,
                    task_queue="test-order-controls",
                    workflows=[OrderSupervisorWorkflow],
                    activities=[
                        activities.mark_run_running,
                        activities.record_order_event,
                        activities.record_wake,
                        activities.run_agent,
                        activities.record_agent_error,
                    ],
                    activity_executor=activity_executor,
                ):
                    handle: WorkflowHandle = await env.client.start_workflow(
                        OrderSupervisorWorkflow.run,
                        workflow_input,
                        id=str(run_id),
                        task_queue="test-order-controls",
                    )
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types=set(),
                        wake_causes={"start"},
                    )
                    await wait_for_agent_runs(engine, run_id, 1)

                    await handle.signal(OrderSupervisorWorkflow.pause)
                    await handle.signal(
                        OrderSupervisorWorkflow.order_event,
                        {"type": "shipment_delayed", "payload": {"reason": "weather"}},
                    )
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"shipment_delayed"},
                        wake_causes={"start"},
                    )
                    await asyncio.sleep(0.1)
                    assert len(await wait_for_agent_runs(engine, run_id, 1)) == 1

                    with Session(engine) as session:
                        run = session.get(Run, run_id)
                        assert run is not None
                        run.extra_instructions = ["Escalate delays immediately."]
                        session.commit()
                    await handle.signal(OrderSupervisorWorkflow.resume)
                    entries = await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"shipment_delayed"},
                        wake_causes={"start", "important_event"},
                    )
                    assert len(await wait_for_agent_runs(engine, run_id, 2)) == 2
                    assert observed_instructions[-1] == ["Escalate delays immediately."]
                    assert any(
                        entry.type == "wake_trigger"
                        and entry.payload["cause"] == "important_event"
                        for entry in entries
                    )

                    await handle.signal(OrderSupervisorWorkflow.pause)
                    await handle.signal(OrderSupervisorWorkflow.interrupt)
                    await handle.signal(
                        OrderSupervisorWorkflow.order_event,
                        {"type": "payment_confirmed", "payload": {}},
                    )
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"shipment_delayed", "payment_confirmed"},
                        wake_causes={"start", "important_event"},
                    )
                    await asyncio.sleep(0.1)
                    assert len(await wait_for_agent_runs(engine, run_id, 2)) == 2

                    await handle.signal(OrderSupervisorWorkflow.resume)
                    await wait_for_timeline(
                        engine,
                        run_id,
                        event_types={"shipment_delayed", "payment_confirmed"},
                        wake_causes={"start", "important_event", "interrupt"},
                    )
                    assert len(await wait_for_agent_runs(engine, run_id, 3)) == 3
                    await handle.terminate("Test cleanup")
    engine.dispose()
