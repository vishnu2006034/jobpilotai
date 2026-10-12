from datetime import datetime, timedelta
import hashlib
import json
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column, Session

from .ats import fetch_feed
from .db import Base, Identity, utcnow
from .identity import User, current_user, get_db
from .jobs import Job, JobInput, serialize_job
from .operations import Schedule, Task, TaskFailure, db_now, enqueue, task_view
from .targeting import POLICY_DESCRIPTION, POLICY_VERSION, target_posting

router = APIRouter(prefix="/api/v1", tags=["Discovery"])
CATALOG = [
    {"provider": "greenhouse", "board": "toast", "name": "Toast"},
    {"provider": "greenhouse", "board": "fourkites", "name": "FourKites"},
    {"provider": "greenhouse", "board": "zscaler", "name": "Zscaler"},
    {"provider": "greenhouse", "board": "rubrik", "name": "Rubrik"},
    {"provider": "greenhouse", "board": "databricks", "name": "Databricks"},
    {"provider": "greenhouse", "board": "mongodb", "name": "MongoDB"},
    {"provider": "greenhouse", "board": "cloudflare", "name": "Cloudflare"},
    {"provider": "greenhouse", "board": "stripe", "name": "Stripe"},
    {"provider": "lever", "board": "palantir", "name": "Palantir"},
    {"provider": "lever", "board": "spotify", "name": "Spotify"},
]


class Source(Identity, Base):
    __tablename__ = "discovery_sources"
    __table_args__ = (UniqueConstraint("user_id", "provider", "board"), UniqueConstraint("user_id", "id"),
                     ForeignKeyConstraint(["user_id", "schedule_id"], ["task_schedules.user_id", "task_schedules.id"]))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    schedule_id: Mapped[uuid.UUID]
    provider: Mapped[str] = mapped_column(String(30))
    board: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[int] = mapped_column(default=1)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Posting(Identity, Base):
    __tablename__ = "discovered_postings"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),
                     ForeignKeyConstraint(["user_id", "source_id"], ["discovery_sources.user_id", "discovery_sources.id"]))
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    source_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(String(150))
    url: Mapped[str] = mapped_column(String(2048))
    data: Mapped[dict] = mapped_column(JSONB)
    fingerprint: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(default=1)
    target: Mapped[dict] = mapped_column(JSONB)
    target_status: Mapped[str] = mapped_column(String(30), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoveryNotice(Identity, Base):
    __tablename__ = "discovery_notices"
    __table_args__ = (ForeignKeyConstraint(["user_id", "task_id"], ["background_tasks.user_id", "background_tasks.id"]),)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    source_name: Mapped[str] = mapped_column(String(160))
    potential_count: Mapped[int]
    review_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Literal["greenhouse", "lever", "lever_eu"]
    board: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=160)
    interval_minutes: int = Field(default=15, ge=15, le=10080)


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    enabled: bool
    interval_minutes: int = Field(ge=15, le=10080)


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: uuid.UUID
    command_id: uuid.UUID


def owned_source(db, user_id, source_id, lock=False):
    query = select(Source).where(Source.id == source_id, Source.user_id == user_id)
    source = db.scalar(query.with_for_update() if lock else query)
    if not source:
        raise HTTPException(404, "Source not found")
    return source


def source_view(db, source):
    schedule = db.get(Schedule, source.schedule_id)
    task = db.scalar(select(Task).where(Task.user_id == source.user_id, Task.resource_key == str(source.id))
                     .order_by(Task.created_at.desc()).limit(1))
    return {"id": source.id, "provider": source.provider, "board": source.board, "name": source.name,
            "version": source.version, "enabled": schedule.enabled, "interval_minutes": schedule.interval_minutes,
            "next_run_at": schedule.next_run_at, "last_success_at": source.last_success_at,
            "last_task": task_view(task) if task else None}


def add_source(db, user, body):
    # Serialize the small per-account source quota and duplicate creation.
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(select(Source).where(Source.user_id == user.id, Source.provider == body.provider, Source.board == body.board))
    if existing:
        return existing
    count = db.scalar(select(func.count()).select_from(Source).where(Source.user_id == user.id))
    if count >= 20:
        raise HTTPException(422, "This local version supports up to 20 sources per account")
    source_id, schedule_id = uuid.uuid4(), uuid.uuid4()
    db.add(Schedule(id=schedule_id, user_id=user.id, task_type="discovery.fetch", payload={"source_id": str(source_id)},
                    resource_key=str(source_id), interval_minutes=body.interval_minutes, enabled=True, next_run_at=db_now(db)))
    db.flush()
    source = Source(id=source_id, user_id=user.id, schedule_id=schedule_id, provider=body.provider, board=body.board, name=body.name)
    db.add(source)
    db.flush()
    return source


@router.get("/sources/catalog")
def catalog(user: User = Depends(current_user)):
    return {"items": CATALOG, "policy": POLICY_DESCRIPTION, "policy_version": POLICY_VERSION,
            "note": "Verified public feeds, not comprehensive MNC coverage. Company hiring and regional availability vary."}


@router.post("/sources/presets", status_code=201)
def presets(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sources = [add_source(db, user, SourceInput(**item)) for item in CATALOG]
    db.commit()
    return {"items": [source_view(db, source) for source in sources]}


@router.post("/sources", status_code=201)
def create_source(body: SourceInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = add_source(db, user, body)
    db.commit()
    return source_view(db, source)


@router.get("/sources")
def sources(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Source).where(Source.user_id == user.id).order_by(Source.created_at)).all()
    return {"items": [source_view(db, source) for source in rows]}


@router.patch("/sources/{source_id}")
def update_source(source_id: uuid.UUID, body: SourceUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = owned_source(db, user.id, source_id, lock=True)
    if source.version != body.expected_version:
        raise HTTPException(409, "Source changed. Refresh before saving.")
    schedule = db.scalar(select(Schedule).where(Schedule.id == source.schedule_id).with_for_update())
    schedule.enabled, schedule.interval_minutes = body.enabled, body.interval_minutes
    schedule.next_run_at = db_now(db) + timedelta(minutes=body.interval_minutes)
    source.version += 1
    db.commit()
    return source_view(db, source)


@router.post("/discovery-runs", status_code=202)
def run_discovery(body: RunInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = owned_source(db, user.id, body.source_id, lock=True)
    key = f"manual:{body.command_id}"
    replay = db.scalar(select(Task).where(Task.user_id == user.id, Task.idempotency_key == key))
    if replay:
        if replay.resource_key != str(source.id):
            raise HTTPException(409, "Command ID was used for another source")
        return task_view(replay)
    active = db.scalar(select(Task).where(Task.user_id == user.id, Task.resource_key == str(source.id), Task.status.in_(["queued", "running"])))
    if active:
        return task_view(active)
    now = db_now(db)
    if source.last_requested_at and source.last_requested_at > now - timedelta(minutes=5):
        raise HTTPException(429, "Wait five minutes between manual checks for this source")
    schedule = db.get(Schedule, source.schedule_id)
    if not schedule.enabled:
        raise HTTPException(409, "Resume this source before checking it")
    task = enqueue(db, user.id, "discovery.fetch", {"source_id": str(source.id)}, str(source.id), key)
    source.last_requested_at = now
    db.commit()
    return task_view(task)


@router.get("/discovery-runs/{task_id}")
def discovery_run(task_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user.id, Task.task_type == "discovery.fetch"))
    if not task:
        raise HTTPException(404, "Discovery run not found")
    return task_view(task)


def posting_view(posting):
    return {"id": posting.id, "source_id": posting.source_id, "external_id": posting.external_id, "source_url": posting.url,
            **posting.data, "revision": posting.revision, "target": posting.target, "first_seen_at": posting.first_seen_at,
            "last_seen_at": posting.last_seen_at, "missing_since": posting.missing_since, "closed_at": posting.closed_at}


@router.get("/discovered-postings")
def postings(status: Literal["potential_match", "needs_review", "all"] = "potential_match",
             source_id: uuid.UUID | None = None, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
             user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Posting).where(Posting.user_id == user.id, Posting.closed_at.is_(None))
    if status != "all":
        query = query.where(Posting.target_status == status)
    if source_id:
        owned_source(db, user.id, source_id)
        query = query.where(Posting.source_id == source_id)
    rows = db.scalars(query.order_by(Posting.first_seen_at.desc(), Posting.id).offset(offset).limit(limit + 1)).all()
    return {"items": [posting_view(row) for row in rows[:limit]], "next_offset": offset + limit if len(rows) > limit else None,
            "policy": POLICY_DESCRIPTION}


@router.post("/discovered-postings/{posting_id}/import", status_code=201)
def import_posting(posting_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    posting = db.scalar(select(Posting).where(Posting.id == posting_id, Posting.user_id == user.id))
    if not posting:
        raise HTTPException(404, "Posting not found")
    if posting.closed_at:
        raise HTTPException(409, "This posting is no longer listed by the source")
    source = db.get(Source, posting.source_id)
    body = JobInput(source_url=posting.url, **{k: v for k, v in posting.data.items() if k in JobInput.model_fields and k != "source_url"})
    provenance = {"kind": "ats_snapshot", "provider": source.provider, "board": source.board, "posting_id": str(posting.id),
                  "external_id": posting.external_id, "revision": posting.revision, "retrieved_at": posting.last_seen_at.isoformat()}
    created = db.scalar(insert(Job).values(id=uuid.uuid4(), user_id=user.id, source_url=posting.url,
                        data=body.model_dump(mode="json", exclude={"source_url"}), provenance=provenance, created_at=db_now(db))
                        .on_conflict_do_nothing(index_elements=[Job.user_id, Job.source_url]).returning(Job.id))
    job = db.scalar(select(Job).where(Job.user_id == user.id, Job.source_url == posting.url))
    db.commit()
    return {**serialize_job(db, job), "already_in_workspace": created is None}


@router.get("/discovery-notices")
def notices(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(DiscoveryNotice).where(DiscoveryNotice.user_id == user.id, DiscoveryNotice.read_at.is_(None))
                     .order_by(DiscoveryNotice.created_at.desc()).limit(50)).all()
    count = db.scalar(select(func.count()).select_from(DiscoveryNotice).where(DiscoveryNotice.user_id == user.id, DiscoveryNotice.read_at.is_(None)))
    return {"unread_count": count, "items": [{"id": row.id, "source_name": row.source_name, "potential_count": row.potential_count,
            "review_count": row.review_count, "created_at": row.created_at} for row in rows]}


@router.post("/discovery-notices/{notice_id}/read", status_code=204)
def read_notice(notice_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    notice = db.scalar(select(DiscoveryNotice).where(DiscoveryNotice.id == notice_id, DiscoveryNotice.user_id == user.id))
    if not notice:
        raise HTTPException(404, "Notification not found")
    notice.read_at = db_now(db)
    db.commit()


class DiscoveryHandler:
    def __init__(self, sessions, fetcher=fetch_feed):
        self.sessions, self.fetcher = sessions, fetcher

    def prepare(self, claim):
        with self.sessions() as db:
            source = db.scalar(select(Source).where(Source.id == uuid.UUID(claim.payload["source_id"]), Source.user_id == claim.user_id))
            if not source:
                raise TaskFailure("source_not_found")
            if not db.get(Schedule, source.schedule_id).enabled:
                return None
            provider, board, name = source.provider, source.board, source.name
        return self.fetcher(provider, board, name)

    def apply(self, db, claim, items):
        source = db.scalar(select(Source).where(Source.id == uuid.UUID(claim.payload["source_id"]), Source.user_id == claim.user_id))
        if not source:
            raise TaskFailure("source_not_found")
        if items is None or not db.get(Schedule, source.schedule_id).enabled:
            return {"skipped": "source_paused"}
        now = db_now(db)
        first_sync = source.last_success_at is None
        existing = {p.external_id: p for p in db.scalars(select(Posting).where(Posting.source_id == source.id)).all()}
        created, updated, potential, review = 0, 0, 0, 0
        for item in items:
            digest = hashlib.sha256(json.dumps({"url": item.url, "data": item.data}, sort_keys=True).encode()).hexdigest()
            target = target_posting(item.data)
            posting = existing.pop(item.external_id, None)
            if posting is None:
                posting = Posting(user_id=claim.user_id, source_id=source.id, external_id=item.external_id,
                                  url=item.url, data=item.data, fingerprint=digest, target=target, target_status=target["status"],
                                  first_seen_at=now, last_seen_at=now)
                db.add(posting)
                created += 1
                potential += target["status"] == "potential_match"
                review += target["status"] == "needs_review"
            else:
                if posting.fingerprint != digest:
                    posting.url, posting.data, posting.fingerprint = item.url, item.data, digest
                    posting.revision += 1
                    updated += 1
                posting.target, posting.target_status = target, target["status"]
                posting.last_seen_at, posting.missing_since, posting.closed_at = now, None, None
        for posting in existing.values():
            if posting.missing_since is None:
                posting.missing_since = now
            elif posting.missing_since <= now - timedelta(hours=24) and posting.closed_at is None:
                posting.closed_at = now
        if not first_sync and (potential or review):
            db.add(DiscoveryNotice(user_id=claim.user_id, task_id=claim.id, source_name=source.name,
                                    potential_count=potential, review_count=review, created_at=now))
        source.last_success_at = now
        return {"fetched": len(items), "created": created, "updated": updated, "potential": potential, "review": review,
                "baseline": first_sync}
