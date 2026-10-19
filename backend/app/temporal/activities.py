from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio import activity

from app.agent.llm import build_messages, request_decision
from app.agent.tools import execute_mock_tool
from app.db.models import Run, TimelineEntry
from app.db.session import get_engine


@activity.defn
async def ping(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    return f"pong:{name.strip()}"


@activity.defn
def mark_run_running(run_id: str) -> None:
    with Session(get_engine()) as session:
        run = session.get(Run, UUID(run_id))
        if run is None:
            raise ValueError(f"Run {run_id} does not exist")
        if run.status == "starting":
            run.status = "running"
            session.commit()


@activity.defn
def record_wake(
    run_id: str,
    cause: str,
    event_types: list[str],
    next_wakeup_at: datetime,
) -> None:
    with Session(get_engine()) as session:
        run = session.get(Run, UUID(run_id))
        if run is None:
            raise ValueError(f"Run {run_id} does not exist")
        if run.status in {"terminating", "terminated", "completed", "failed"}:
            return
        if run.status != "paused":
            run.status = "sleeping"
        run.sleep_until = next_wakeup_at
        session.add(
            TimelineEntry(
                run_id=run.id,
                kind="system",
                type="wake_trigger",
                payload={"cause": cause, "event_types": event_types},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


@activity.defn
async def run_agent(
    run_id: str,
    invocation_id: str,
    cause: str,
    events: list[dict[str, Any]],
    finalizing: bool,
) -> dict[str, Any]:
    from app.config import load_settings
    from app.db.models import RunFinalOutput, RunMemory, Supervisor

    settings = load_settings()
    with Session(get_engine()) as session:
        run = session.get(Run, UUID(run_id))
        if run is None:
            raise ValueError(f"Run {run_id} does not exist")
        last_agent_run = session.scalar(
            select(TimelineEntry)
            .where(
                TimelineEntry.run_id == run.id,
                TimelineEntry.type == "agent_run",
            )
            .order_by(TimelineEntry.created_at.desc(), TimelineEntry.id.desc())
            .limit(1)
        )
        if (
            last_agent_run is not None
            and last_agent_run.payload.get("invocation_id") == invocation_id
        ):
            return last_agent_run.payload["outcome"]
        supervisor = session.get(Supervisor, run.supervisor_id)
        if supervisor is None:
            raise ValueError(f"Supervisor for run {run_id} does not exist")
        memory = session.get(RunMemory, run.id)
        timeline = session.scalars(
            select(TimelineEntry)
            .where(TimelineEntry.run_id == run.id)
            .order_by(TimelineEntry.created_at.desc(), TimelineEntry.id.desc())
            .limit(30)
        ).all()
        messages = build_messages(
            base_instruction=supervisor.base_instruction,
            order_id=run.order_id,
            order_context=run.order_context,
            extra_instructions=run.extra_instructions,
            memory_summary=memory.summary if memory is not None else "",
            recent_timeline=[
                {
                    "kind": item.kind,
                    "type": item.type,
                    "payload": item.payload,
                    "created_at": item.created_at.isoformat(),
                }
                for item in reversed(timeline)
            ],
            events=events,
            cause=cause,
            finalizing=finalizing,
            available_tools=supervisor.available_tools,
        )
        base_instruction = supervisor.base_instruction
        available_tools = supervisor.available_tools
        order_id = run.order_id
        order_context = run.order_context
        extra_instructions = run.extra_instructions
        model = supervisor.model

    decision = await request_decision(
        messages=messages,
        api_key=settings.groq_api_key,
        model=model or settings.groq_model,
    )
    if finalizing and decision.final_output is None:
        raise ValueError("Final agent response must include final_output")
    if finalizing and decision.actions:
        raise ValueError("Final agent response must not include tool actions")

    now = datetime.now(timezone.utc)
    scheduled_seconds = decision.next_wakeup_seconds
    action_records: list[tuple[str, dict[str, Any]]] = []
    allowed_tools = set(available_tools)
    for action in decision.actions:
        try:
            if action.name not in allowed_tools:
                raise ValueError(f"Tool {action.name} is not enabled for this supervisor")
            result = execute_mock_tool(action.name, action.arguments)
            action_record = {"status": "succeeded", **result}
        except (ValueError, TypeError) as exc:
            action_record = {
                "status": "failed",
                "tool": action.name,
                "arguments": action.arguments,
                "error": str(exc),
            }
        action_records.append((action.name, action_record))

    outcome = {
        "next_wakeup_seconds": scheduled_seconds,
        "completed": finalizing,
    }
    with Session(get_engine()) as session:
        run = session.get(Run, UUID(run_id))
        if run is None:
            raise ValueError(f"Run {run_id} does not exist")
        memory = session.get(RunMemory, run.id)
        if memory is None:
            memory = RunMemory(run_id=run.id, summary=decision.memory_summary)
            session.add(memory)
        else:
            memory.summary = decision.memory_summary
        session.add(
            TimelineEntry(
                run_id=run.id,
                kind="system",
                type="agent_run",
                payload={
                    "invocation_id": invocation_id,
                    "cause": cause,
                    "summary": decision.summary,
                    "actions_count": len(decision.actions),
                    "outcome": outcome,
                },
                created_at=now,
            )
        )

        for tool_name, action_record in action_records:
            session.add(
                TimelineEntry(
                    run_id=run.id,
                    kind="action",
                    type=tool_name,
                    payload=action_record,
                    created_at=now,
                )
            )

        if finalizing:
            final_output = decision.final_output
            if final_output is None:
                raise ValueError("Final agent response must include final_output")
            session.merge(
                RunFinalOutput(
                    run_id=run.id,
                    summary=final_output.summary,
                    important_actions=final_output.important_actions,
                    learnings=final_output.learnings,
                    feedback=final_output.feedback,
                )
            )
            run.status = "completed"
            run.sleep_until = None
        session.commit()

    return outcome


@activity.defn
def record_agent_error(run_id: str, cause: str, error: str) -> None:
    with Session(get_engine()) as session:
        run = session.get(Run, UUID(run_id))
        if run is None:
            raise ValueError(f"Run {run_id} does not exist")
        session.add(
            TimelineEntry(
                run_id=run.id,
                kind="system",
                type="agent_error",
                payload={"cause": cause, "error": error[:2000]},
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


@activity.defn
def record_order_event(run_id: str, event: dict[str, Any]) -> None:
    with Session(get_engine()) as session:
        run = session.get(Run, UUID(run_id))
        if run is None:
            raise ValueError(f"Run {run_id} does not exist")
        session.add(
            TimelineEntry(
                run_id=run.id,
                kind="event",
                type=event["type"],
                payload=event.get("payload", {}),
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
