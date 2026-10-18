from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SupervisorCreate(BaseModel):
    name: NonBlankString
    base_instruction: NonBlankString
    available_tools: list[NonBlankString] = Field(default_factory=list)
    default_wakeup_seconds: int | None = Field(default=None, gt=0)
    model: str | None = None
    wake_aggressiveness: str | None = None


class SupervisorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    base_instruction: str
    available_tools: list[str]
    default_wakeup_seconds: int | None
    model: str | None
    wake_aggressiveness: str | None
    created_at: datetime


class SupervisorList(BaseModel):
    items: list[SupervisorRead]


class RunCreate(BaseModel):
    supervisor_id: UUID
    order_id: NonBlankString
    order_context: dict[str, Any] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    supervisor_id: UUID
    order_id: str
    status: str
    sleep_until: datetime | None
    created_at: datetime
    updated_at: datetime


class TimelineEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    type: str
    payload: dict[str, Any]
    created_at: datetime


class RunFinalOutputRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    summary: str | None
    important_actions: list[dict[str, Any]]
    learnings: str | None
    feedback: str | None


class RunDetail(RunSummary):
    order_context: dict[str, Any]
    extra_instructions: list[str]
    timeline: list[TimelineEntryRead]
    memory_summary: str | None
    final_output: RunFinalOutputRead | None


class RunList(BaseModel):
    items: list[RunSummary]


class EventCreate(BaseModel):
    type: NonBlankString
    payload: dict[str, Any] = Field(default_factory=dict)
