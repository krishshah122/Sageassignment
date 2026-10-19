from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Supervisor(Base):
    __tablename__ = "supervisors"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    available_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    default_wakeup_seconds: Mapped[int | None] = mapped_column(nullable=True)
    model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wake_aggressiveness: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_status", "status"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    supervisor_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("supervisors.id"), nullable=False
    )
    order_id: Mapped[str] = mapped_column(String(200), nullable=False)
    order_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    extra_instructions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="starting")
    sleep_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temporal_workflow_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TimelineEntry(Base):
    __tablename__ = "timeline_entries"
    __table_args__ = (Index("ix_timeline_entries_run_created", "run_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("runs.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RunMemory(Base):
    __tablename__ = "run_memories"

    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id"), primary_key=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RunFinalOutput(Base):
    __tablename__ = "run_final_outputs"

    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("runs.id"), primary_key=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    important_actions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    learnings: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
