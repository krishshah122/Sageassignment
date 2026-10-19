from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from app.api.schemas import (
    EventCreate,
    InstructionCreate,
    RunCreate,
    RunDetail,
    RunFinalOutputRead,
    RunList,
    RunSummary,
    TimelineEntryRead,
)
from app.config import load_settings
from app.db.models import Run, RunFinalOutput, RunMemory, Supervisor, TimelineEntry
from app.db.session import get_db
from app.temporal.workflow import OrderSupervisorWorkflow, OrderWorkflowInput

router = APIRouter(prefix="/api/runs", tags=["runs"])

EVENT_TYPES = {
    "order_created",
    "payment_confirmed",
    "payment_failed",
    "shipment_created",
    "shipment_delayed",
    "delivered",
    "refund_requested",
    "customer_message_received",
    "no_update_for_n_hours",
}
TERMINAL_RUN_STATUSES = {"completed", "terminated", "failed", "terminating"}


async def _start_workflow(run: Run, supervisor: Supervisor) -> None:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    await client.start_workflow(
        OrderSupervisorWorkflow.run,
        OrderWorkflowInput(
            run_id=str(run.id),
            base_instruction=supervisor.base_instruction,
            available_tools=supervisor.available_tools,
            order_id=run.order_id,
            order_context=run.order_context,
            default_wakeup_seconds=(
                supervisor.default_wakeup_seconds
                if supervisor.default_wakeup_seconds is not None
                else settings.default_wakeup_seconds
            ),
        ),
        id=run.temporal_workflow_id,
        task_queue=settings.temporal_task_queue,
    )


async def _signal_event(run: Run, event: EventCreate) -> None:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    handle = client.get_workflow_handle(run.temporal_workflow_id)
    await handle.signal(
        OrderSupervisorWorkflow.order_event,
        event.model_dump(mode="json"),
    )


async def _signal_control(
    run: Run,
    control: Literal["pause", "resume", "interrupt"],
) -> None:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    handle = client.get_workflow_handle(run.temporal_workflow_id)
    signals = {
        "pause": OrderSupervisorWorkflow.pause,
        "resume": OrderSupervisorWorkflow.resume,
        "interrupt": OrderSupervisorWorkflow.interrupt,
    }
    await handle.signal(signals[control])


async def _terminate_workflow(run: Run) -> None:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    handle = client.get_workflow_handle(run.temporal_workflow_id)
    await handle.terminate("Terminated by operator")


def _require_active_run(run_id: UUID, session: Session) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run.status in TERMINAL_RUN_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot control a terminal run",
        )
    return run


def _record_control_event(run: Run, control: str, session: Session) -> None:
    session.add(
        TimelineEntry(
            run_id=run.id,
            kind="system",
            type=f"run_{control}",
            payload={},
        )
    )


@router.post("", response_model=RunSummary, status_code=status.HTTP_201_CREATED)
async def create_run(
    request: RunCreate, session: Session = Depends(get_db)
) -> Run:
    supervisor = session.get(Supervisor, request.supervisor_id)
    if supervisor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supervisor not found")

    run = Run(
        supervisor_id=supervisor.id,
        order_id=request.order_id,
        order_context=request.order_context,
        temporal_workflow_id="",
        status="starting",
    )
    session.add(run)
    session.flush()
    run.temporal_workflow_id = str(run.id)
    session.commit()
    session.refresh(run)

    try:
        await _start_workflow(run, supervisor)
    except (RPCError, WorkflowAlreadyStartedError) as exc:
        run.status = "failed"
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not start the Temporal workflow",
        ) from exc

    session.refresh(run)
    return run


@router.get("", response_model=RunList)
def list_runs(session: Session = Depends(get_db)) -> RunList:
    runs = session.scalars(select(Run).order_by(Run.created_at.desc())).all()
    return RunList(items=list(runs))


@router.get("/{run_id}", response_model=RunDetail)
def get_run(run_id: UUID, session: Session = Depends(get_db)) -> RunDetail:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")

    timeline = session.scalars(
        select(TimelineEntry)
        .where(TimelineEntry.run_id == run.id)
        .order_by(TimelineEntry.created_at.asc(), TimelineEntry.id.asc())
    ).all()
    memory = session.get(RunMemory, run.id)
    final_output = session.get(RunFinalOutput, run.id)
    return RunDetail(
        id=run.id,
        supervisor_id=run.supervisor_id,
        order_id=run.order_id,
        status=run.status,
        sleep_until=run.sleep_until,
        created_at=run.created_at,
        updated_at=run.updated_at,
        order_context=run.order_context,
        extra_instructions=run.extra_instructions,
        timeline=[TimelineEntryRead.model_validate(entry) for entry in timeline],
        memory_summary=memory.summary if memory is not None else None,
        final_output=(
            RunFinalOutputRead.model_validate(final_output)
            if final_output is not None
            else None
        ),
    )


@router.post("/{run_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def inject_event(
    run_id: UUID,
    request: EventCreate,
    session: Session = Depends(get_db),
) -> dict[str, str]:
    run = session.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if request.type not in EVENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown event type")
    if run.status not in {"starting", "running", "sleeping", "paused"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot add events to a terminal run",
        )

    try:
        await _signal_event(run, request)
    except RPCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not deliver event to the Temporal workflow",
        ) from exc

    return {"status": "accepted"}


@router.post("/{run_id}/instructions", response_model=RunSummary)
def add_instruction(
    run_id: UUID,
    request: InstructionCreate,
    session: Session = Depends(get_db),
) -> Run:
    run = _require_active_run(run_id, session)
    run.extra_instructions = [*run.extra_instructions, request.text]
    session.add(
        TimelineEntry(
            run_id=run.id,
            kind="system",
            type="instruction_added",
            payload={"text": request.text},
        )
    )
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/pause", response_model=RunSummary)
async def pause_run(
    run_id: UUID,
    session: Session = Depends(get_db),
) -> Run:
    run = _require_active_run(run_id, session)
    if run.status == "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is already paused",
        )
    try:
        await _signal_control(run, "pause")
    except RPCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not pause the Temporal workflow",
        ) from exc
    run.status = "paused"
    _record_control_event(run, "paused", session)
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/resume", response_model=RunSummary)
async def resume_run(
    run_id: UUID,
    session: Session = Depends(get_db),
) -> Run:
    run = _require_active_run(run_id, session)
    if run.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Run is not paused",
        )
    try:
        await _signal_control(run, "resume")
    except RPCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not resume the Temporal workflow",
        ) from exc
    run.status = "running"
    _record_control_event(run, "resumed", session)
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/interrupt", response_model=RunSummary)
async def interrupt_run(
    run_id: UUID,
    session: Session = Depends(get_db),
) -> Run:
    run = _require_active_run(run_id, session)
    try:
        await _signal_control(run, "interrupt")
    except RPCError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not interrupt the Temporal workflow",
        ) from exc
    _record_control_event(run, "interrupted", session)
    session.commit()
    session.refresh(run)
    return run


@router.post("/{run_id}/terminate", response_model=RunSummary)
async def terminate_run(
    run_id: UUID,
    session: Session = Depends(get_db),
) -> Run:
    run = _require_active_run(run_id, session)
    previous_status = run.status
    run.status = "terminating"
    session.commit()
    try:
        await _terminate_workflow(run)
    except RPCError as exc:
        session.refresh(run)
        if run.status == "terminating":
            run.status = previous_status
            session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not terminate the Temporal workflow",
        ) from exc
    run.status = "terminated"
    run.sleep_until = None
    _record_control_event(run, "terminated", session)
    session.commit()
    session.refresh(run)
    return run
