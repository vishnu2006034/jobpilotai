"""Immutable text resumes and extractive, user-reviewed job drafts."""
from datetime import datetime, timezone
import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint, select, func
from sqlalchemy.orm import Mapped, mapped_column, Session
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base, Identity, utcnow
from .identity import User, current_user, get_db
from .jobs import owned_job

router = APIRouter(prefix="/api/v1/resumes", tags=["Resume preparation"])


class Resume(Identity, Base):
    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("user_id", "id"), UniqueConstraint("user_id", "digest"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResumeDraft(Identity, Base):
    __tablename__ = "resume_drafts"
    __table_args__ = (
        ForeignKeyConstraint(["user_id", "resume_id"], ["resume_versions.user_id", "resume_versions.id"]),
        ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"]),
        UniqueConstraint("user_id", "digest"),
    )
    user_id: Mapped[uuid.UUID]
    resume_id: Mapped[uuid.UUID]
    job_id: Mapped[uuid.UUID]
    selected_blocks: Mapped[list] = mapped_column(JSONB)
    text: Mapped[str] = mapped_column(Text)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=50000)

    @field_validator("title", "text")
    @classmethod
    def plain_text(cls, value):
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not value or any(ord(c) < 32 and c not in "\n\t" for c in value):
            raise ValueError("Use non-empty plain text without control characters")
        if len(value.encode("utf-8")) > 200000:
            raise ValueError("Text is too large")
        return value


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class DraftInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_id: uuid.UUID
    job_id: uuid.UUID
    selected_blocks: list[int] = Field(min_length=1, max_length=500)


def blocks(text):
    # Paragraph boundaries preserve multi-line facts and bullets verbatim.
    return [part for part in text.split("\n\n") if part.strip()]


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def owned(db, model, user_id, item_id):
    row = db.scalar(select(model).where(model.id == item_id, model.user_id == user_id))
    if row is None:
        raise HTTPException(404, "Resume or draft not found")
    return row


def serialize(row):
    result = {"id": row.id, "text": row.text, "digest": row.digest,
              "created_at": row.created_at.astimezone(timezone.utc),
              "reviewed_at": row.reviewed_at.astimezone(timezone.utc) if row.reviewed_at else None}
    if isinstance(row, Resume):
        result.update(title=row.title, blocks=blocks(row.text))
    else:
        result.update(resume_id=row.resume_id, job_id=row.job_id, selected_blocks=row.selected_blocks)
    return result


def lock_owner(db, user):
    # Serialize quota checks, deduplication and reviews within an account.
    db.scalar(select(User).where(User.id == user.id).with_for_update())


@router.get("")
def list_resumes(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [serialize(row) for row in db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc()))]


@router.post("", status_code=201)
def import_resume(body: ResumeInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lock_owner(db, user)
    fingerprint = digest(body.text)
    row = db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.digest == fingerprint))
    if row:
        return serialize(row)
    if len(blocks(body.text)) > 500:
        raise HTTPException(422, "Use at most 500 paragraphs")
    if db.scalar(select(func.count()).select_from(Resume).where(Resume.user_id == user.id)) >= 100:
        raise HTTPException(409, "Resume version limit reached (100)")
    row = Resume(user_id=user.id, title=body.title, text=body.text, digest=fingerprint)
    db.add(row)
    db.commit()
    return serialize(row)


@router.post("/drafts", status_code=201)
def create_draft(body: DraftInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    lock_owner(db, user)
    resume = owned(db, Resume, user.id, body.resume_id)
    job = owned_job(db, user.id, body.job_id)
    if not resume.reviewed_at:
        raise HTTPException(409, "Review the source resume first")
    source = blocks(resume.text)
    indices = body.selected_blocks
    if len(set(indices)) != len(indices) or any(i < 0 or i >= len(source) for i in indices):
        raise HTTPException(422, "Choose distinct paragraphs from this resume")
    # Preserve source order: selection removes passages but does not rewrite claims.
    indices = sorted(indices)
    text = "\n\n".join(source[i] for i in indices)
    fingerprint = digest(f"{resume.id}:{job.id}:{resume.digest}:" + text)
    row = db.scalar(select(ResumeDraft).where(ResumeDraft.user_id == user.id, ResumeDraft.digest == fingerprint))
    if row:
        return serialize(row)
    if db.scalar(select(func.count()).select_from(ResumeDraft).where(ResumeDraft.user_id == user.id)) >= 500:
        raise HTTPException(409, "Draft limit reached (500)")
    row = ResumeDraft(user_id=user.id, resume_id=resume.id, job_id=job.id,
                      selected_blocks=indices, text=text, digest=fingerprint)
    db.add(row)
    db.commit()
    return serialize(row)


@router.get("/drafts")
def list_drafts(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [serialize(row) for row in db.scalars(select(ResumeDraft).where(ResumeDraft.user_id == user.id).order_by(ResumeDraft.created_at.desc()))]


@router.post("/{item_id}/review")
def review_resume(item_id: uuid.UUID, body: ReviewInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return review(db, Resume, user, item_id, body.digest)


@router.post("/drafts/{item_id}/review")
def review_draft(item_id: uuid.UUID, body: ReviewInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return review(db, ResumeDraft, user, item_id, body.digest)


def review(db, model, user, item_id, fingerprint):
    lock_owner(db, user)
    row = owned(db, model, user.id, item_id)
    if row.digest != fingerprint:
        raise HTTPException(409, "Content changed; reload before reviewing")
    if row.reviewed_at is None:
        row.reviewed_at = utcnow()
    db.commit()
    return serialize(row)


@router.get("/drafts/{item_id}/download")
def download_draft(item_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    row = owned(db, ResumeDraft, user.id, item_id)
    if not row.reviewed_at:
        raise HTTPException(409, "Review this draft before downloading")
    return Response(row.text, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="jobpilot-draft-{row.id}.txt"'})
