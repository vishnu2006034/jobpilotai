"""Durable, fenced task execution. External work happens outside transactions."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import random
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, String, UniqueConstraint, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column, Session

from .db import Base, Identity, utcnow
from .identity import User, current_user, get_db

router = APIRouter(prefix="/api/v1/tasks", tags=["Background tasks"])
LEASE_SECONDS = 45
TASK_POLICIES = {"discovery.fetch": True}


class Task(Identity, Base):
    __tablename__ = "background_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"), UniqueConstraint("user_id", "id"),
        Index("ix_task_due", "status", "run_after"), Index("ix_task_lease", "lease_expires_at"),
        Index("uq_task_active_resource", "user_id", "resource_key", unique=True,
              postgresql_where=text("status IN ('queued', 'running')")),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    task_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB)
    resource_key: Mapped[str] = mapped_column(String(160))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempt: Mapped[int] = mapped_column(default=0)
    max_attempts: Mapped[int] = mapped_column(default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_token: Mapped[uuid.UUID | None]
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(100))


class TaskAttempt(Base):
    __tablename__ = "task_attempts"
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("background_tasks.id"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    lease_token: Mapped[uuid.UUID]
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30))
    error_code: Mapped[str | None] = mapped_column(String(100))


class Schedule(Identity, Base):
    __tablename__ = "task_schedules"
    __table_args__ = (UniqueConstraint("user_id", "resource_key"), UniqueConstraint("user_id", "id"),)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    task_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB)
    resource_key: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(default=True)
    interval_minutes: Mapped[int] = mapped_column(default=15)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LostLease(Exception):
    pass


class TaskFailure(Exception):
    def __init__(self, code, retryable=False, retry_after=0):
        self.code, self.retryable, self.retry_after = code, retryable, retry_after
        super().__init__(code)


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    user_id: uuid.UUID
    task_type: str
    payload: dict
    token: uuid.UUID
    attempt: int


def db_now(db):
    return db.scalar(select(func.clock_timestamp()))


def enqueue(db, user_id, task_type, payload, resource_key, idempotency_key):
    if task_type not in TASK_POLICIES:
        raise ValueError("Unregistered task type")
    for _ in range(3):
        task_id = db.scalar(insert(Task).values(id=uuid.uuid4(), user_id=user_id, task_type=task_type,
                             payload=payload, resource_key=resource_key, idempotency_key=idempotency_key,
                             status="queued", attempt=0, max_attempts=3, run_after=db_now(db), created_at=db_now(db))
                             .on_conflict_do_nothing().returning(Task.id))
        if task_id:
            return db.get(Task, task_id)
        existing = db.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == idempotency_key))
        if existing:
            if existing.task_type != task_type or existing.payload != payload or existing.resource_key != resource_key:
                raise ValueError("Idempotency key reused for different input")
            return existing
        active = db.scalar(select(Task).where(Task.user_id == user_id, Task.resource_key == resource_key,
                                              Task.status.in_(["queued", "running"])))
        if active:
            return active
    raise RuntimeError("Concurrent enqueue contention")


def backoff(attempt):
    return min(900, 30 * 2 ** (attempt - 1)) + random.randint(0, 10)


def claim_next(sessions):
    with sessions.begin() as db:
        now = db_now(db)
        expired = db.scalars(select(Task).where(Task.status == "running", Task.lease_expires_at <= now)
                             .order_by(Task.lease_expires_at).limit(100).with_for_update(skip_locked=True)).all()
        for task in expired:
            record = db.get(TaskAttempt, (task.id, task.attempt))
            record.status, record.error_code, record.finished_at = "expired", "lease_expired", now
            retry_safe = TASK_POLICIES.get(task.task_type, False)
            task.status = "queued" if retry_safe and task.attempt < task.max_attempts else "failed" if retry_safe else "needs_review"
            task.error_code = "lease_expired"
            task.run_after = now + timedelta(seconds=backoff(task.attempt))
            task.finished_at = None if task.status == "queued" else now
            task.lease_token = task.lease_expires_at = None
        db.flush()
        task = db.scalar(select(Task).where(Task.status == "queued", Task.run_after <= now)
                         .order_by(Task.run_after, Task.id).limit(1).with_for_update(skip_locked=True))
        if not task:
            return None
        token = uuid.uuid4()
        task.status, task.lease_token = "running", token
        task.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        task.attempt += 1
        task.error_code = None
        db.add(TaskAttempt(task_id=task.id, number=task.attempt, lease_token=token, started_at=now, status="running"))
        return Claim(task.id, task.user_id, task.task_type, task.payload, token, task.attempt)


def locked_claim(db, claim):
    task = db.scalar(select(Task).where(Task.id == claim.id).with_for_update())
    if not task or task.status != "running" or task.lease_token != claim.token or task.lease_expires_at <= db_now(db):
        raise LostLease()
    return task


def heartbeat(sessions, claim):
    with sessions.begin() as db:
        task = locked_claim(db, claim)
        task.lease_expires_at = db_now(db) + timedelta(seconds=LEASE_SECONDS)


def fail(sessions, claim, failure):
    with sessions.begin() as db:
        task = locked_claim(db, claim)
        now = db_now(db)
        safe = TASK_POLICIES.get(task.task_type, False)
        retry = safe and failure.retryable and task.attempt < task.max_attempts
        task.status = "queued" if retry else "failed" if safe else "needs_review"
        task.error_code = failure.code
        task.run_after = now + timedelta(seconds=max(backoff(task.attempt), min(failure.retry_after, 86400)))
        task.finished_at = None if retry else now
        task.lease_token = task.lease_expires_at = None
        record = db.get(TaskAttempt, (task.id, task.attempt))
        record.status, record.error_code, record.finished_at = "failed", failure.code, now


def process_one(sessions, handlers):
    claim = claim_next(sessions)
    if claim is None:
        return False
    stop = threading.Event()

    def renew():
        while not stop.wait(10):
            try:
                heartbeat(sessions, claim)
            except Exception:
                # Failure to renew cannot grant ownership; finalization fences again.
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        handler = handlers.get(claim.task_type)
        if handler is None:
            raise TaskFailure("handler_unavailable")
        prepared = handler.prepare(claim)
        with sessions.begin() as db:
            task = locked_claim(db, claim)
            result = handler.apply(db, claim, prepared)
            # Check again after a potentially slow apply; rollback all effects if expired.
            locked_claim(db, claim)
            task.status, task.result, task.finished_at = "succeeded", result, db_now(db)
            task.lease_token = task.lease_expires_at = None
            record = db.get(TaskAttempt, (task.id, task.attempt))
            record.status, record.finished_at = "succeeded", task.finished_at
    except LostLease:
        pass
    except Exception as exc:
        failure = exc if isinstance(exc, TaskFailure) else TaskFailure("internal_error", retryable=True)
        try:
            fail(sessions, claim, failure)
        except LostLease:
            pass
    finally:
        stop.set()
        thread.join(timeout=1)
    return True


def schedule_tick(sessions):
    with sessions.begin() as db:
        if not db.scalar(select(func.pg_try_advisory_xact_lock(73498126))):
            return 0
        now = db_now(db)
        schedules = db.scalars(select(Schedule).where(Schedule.enabled.is_(True), Schedule.next_run_at <= now)
                               .order_by(Schedule.next_run_at).limit(100).with_for_update(skip_locked=True)).all()
        for schedule in schedules:
            enqueue(db, schedule.user_id, schedule.task_type, schedule.payload, schedule.resource_key,
                    f"schedule:{schedule.id}:{schedule.next_run_at.isoformat()}")
            # Coalesce missed intervals after downtime; never replay a fetch backlog.
            schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
        return len(schedules)


def task_view(task):
    return {"id": task.id, "status": task.status, "attempt": task.attempt, "max_attempts": task.max_attempts,
            "run_after": task.run_after, "created_at": task.created_at, "finished_at": task.finished_at,
            "error_code": task.error_code, "result": task.result}


@router.get("/{task_id}")
def get_task(task_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id))
    if not task:
        raise HTTPException(404, "Task not found")
    attempts = db.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task.id).order_by(TaskAttempt.number)).all()
    return {**task_view(task), "attempts": [{"number": a.number, "status": a.status, "error_code": a.error_code,
             "started_at": a.started_at, "finished_at": a.finished_at} for a in attempts]}
