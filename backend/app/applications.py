from datetime import datetime
import hashlib
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKeyConstraint, UniqueConstraint, select, func
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column, Session

from .db import Base, Identity, utcnow
from .identity import User, current_user, get_db
from .jobs import Job, SavedJob, owned_job

router = APIRouter(prefix="/api/v1", tags=["Manual applications"])
TRANSITIONS = {
    "SAVED": {"DRAFT", "APPLIED", "WITHDRAWN", "EXPIRED"},
    "DRAFT": {"READY_FOR_REVIEW", "APPLIED", "WITHDRAWN", "EXPIRED"},
    "READY_FOR_REVIEW": {"DRAFT", "APPLIED", "WITHDRAWN", "EXPIRED"},
    "APPLIED": {"ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "NEEDS_REVIEW"},
    "ASSESSMENT": {"INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "NEEDS_REVIEW"},
    "INTERVIEW": {"OFFER", "REJECTED", "WITHDRAWN", "NEEDS_REVIEW"},
    "NEEDS_REVIEW": {"DRAFT", "APPLIED", "ASSESSMENT", "INTERVIEW", "OFFER", "REJECTED", "WITHDRAWN", "EXPIRED"},
    "OFFER": {"WITHDRAWN"}, "REJECTED": set(), "WITHDRAWN": set(), "EXPIRED": set(),
}


class Application(Identity, Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("user_id", "job_id"), UniqueConstraint("user_id", "id"),
                      ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"]))
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    job_id: Mapped[uuid.UUID]
    state: Mapped[str] = mapped_column(default="SAVED")
    version: Mapped[int] = mapped_column(default=1)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApplicationEvent(Identity, Base):
    __tablename__ = "application_events"
    __table_args__ = (UniqueConstraint("application_id", "command_id"), UniqueConstraint("application_id", "version"),
                      ForeignKeyConstraint(["user_id", "application_id"], ["applications.user_id", "applications.id"]))
    user_id: Mapped[uuid.UUID]
    application_id: Mapped[uuid.UUID]
    command_id: Mapped[uuid.UUID]
    request_hash: Mapped[str]
    version: Mapped[int]
    previous_state: Mapped[str | None]
    next_state: Mapped[str]
    evidence: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CreateApplication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: uuid.UUID


class ChangeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state: str = Field(max_length=30)
    expected_version: int = Field(ge=1)
    command_id: uuid.UUID
    note: str = Field(min_length=3, max_length=2000)
    confirmed: bool = False


def owned_application(db, user_id, application_id, lock=False):
    query = select(Application).where(Application.id == application_id, Application.user_id == user_id)
    if lock:
        query = query.with_for_update()
    application = db.scalar(query)
    if not application:
        raise HTTPException(404, "Application not found")
    return application


def serialize_application(db, application):
    job = db.get(Job, application.job_id)
    return {"id": application.id, "job_id": application.job_id, "company": job.data["company"], "title": job.data["title"],
            "state": application.state, "version": application.version, "applied_at": application.applied_at,
            "created_at": application.created_at, "updated_at": application.updated_at,
            "allowed_transitions": sorted(TRANSITIONS[application.state])}


@router.post("/applications", status_code=201)
def create_application(body: CreateApplication, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_job(db, user.id, body.job_id)
    created = db.scalar(insert(Application).values(id=uuid.uuid4(), user_id=user.id, job_id=body.job_id,
                         state="SAVED", version=1, created_at=utcnow(), updated_at=utcnow())
                         .on_conflict_do_nothing(index_elements=[Application.user_id, Application.job_id]).returning(Application.id))
    application = db.scalar(select(Application).where(Application.user_id == user.id, Application.job_id == body.job_id))
    if created:
        db.add(ApplicationEvent(user_id=user.id, application_id=application.id, command_id=uuid.uuid4(),
                                request_hash="creation", version=1, previous_state=None, next_state="SAVED",
                                evidence={"source": "user", "note": "Started tracking this application"}))
    db.commit()
    return serialize_application(db, application)


@router.get("/applications")
def list_applications(offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Application).where(Application.user_id == user.id)
                       .order_by(Application.updated_at.desc(), Application.id).offset(offset).limit(limit + 1)).all()
    return {"items": [serialize_application(db, row) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/applications/{application_id}")
def get_application(application_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize_application(db, owned_application(db, user.id, application_id))


@router.post("/applications/{application_id}/status")
def change_status(application_id: uuid.UUID, body: ChangeStatus, user: User = Depends(current_user), db: Session = Depends(get_db)):
    application = owned_application(db, user.id, application_id, lock=True)
    digest = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id,
                                                       ApplicationEvent.command_id == body.command_id))
    if previous:
        if previous.request_hash != digest:
            raise HTTPException(409, "This command ID was already used for different input")
        return {**serialize_application(db, application), "replayed": True}
    if application.version != body.expected_version:
        raise HTTPException(409, "Application changed. Reload the timeline before updating.")
    if body.state not in TRANSITIONS[application.state]:
        raise HTTPException(422, "This status transition is not allowed")
    if body.state in {"APPLIED", "REJECTED", "WITHDRAWN"} and not body.confirmed:
        raise HTTPException(422, "Confirm this status and provide supporting details")
    prior = application.state
    application.state, application.version = body.state, application.version + 1
    application.updated_at = utcnow()
    if body.state == "APPLIED" and not application.applied_at:
        application.applied_at = utcnow()
    db.add(ApplicationEvent(user_id=user.id, application_id=application.id, command_id=body.command_id,
                            request_hash=digest, version=application.version, previous_state=prior, next_state=body.state,
                            evidence={"source": "user", "note": body.note, "confirmed": body.confirmed}))
    db.commit()
    return {**serialize_application(db, application), "replayed": False}


@router.get("/applications/{application_id}/events")
def list_events(application_id: uuid.UUID, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_application(db, user.id, application_id)
    rows = db.scalars(select(ApplicationEvent).where(ApplicationEvent.application_id == application_id,
                      ApplicationEvent.user_id == user.id).order_by(ApplicationEvent.version.desc()).offset(offset).limit(limit + 1)).all()
    return {"items": [{"id": row.id, "previous_state": row.previous_state, "next_state": row.next_state,
                        "version": row.version, "evidence": row.evidence, "created_at": row.created_at} for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/dashboard/summary")
def summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Application.state, func.count()).where(Application.user_id == user.id)
                            .group_by(Application.state)).all())
    return {"jobs": db.scalar(select(func.count()).select_from(Job).where(Job.user_id == user.id)),
            "saved_jobs": db.scalar(select(func.count()).select_from(SavedJob).where(SavedJob.user_id == user.id)),
            "applications": sum(counts.values()), "by_state": counts}
