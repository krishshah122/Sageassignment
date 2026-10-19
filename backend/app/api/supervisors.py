from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import SupervisorCreate, SupervisorList, SupervisorRead
from app.db.models import Supervisor
from app.db.session import get_db

router = APIRouter(prefix="/api/supervisors", tags=["supervisors"])


@router.post("", response_model=SupervisorRead, status_code=status.HTTP_201_CREATED)
def create_supervisor(
    request: SupervisorCreate, session: Session = Depends(get_db)
) -> Supervisor:
    supervisor = Supervisor(**request.model_dump())
    session.add(supervisor)
    session.commit()
    session.refresh(supervisor)
    return supervisor


@router.get("", response_model=SupervisorList)
def list_supervisors(session: Session = Depends(get_db)) -> SupervisorList:
    supervisors = session.scalars(
        select(Supervisor).order_by(Supervisor.created_at.desc())
    ).all()
    return SupervisorList(items=list(supervisors))


@router.get("/{supervisor_id}", response_model=SupervisorRead)
def get_supervisor(
    supervisor_id: UUID, session: Session = Depends(get_db)
) -> Supervisor:
    supervisor = session.get(Supervisor, supervisor_id)
    if supervisor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Supervisor not found")
    return supervisor
