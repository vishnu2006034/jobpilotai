from datetime import datetime
import uuid
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column, Session

from .db import Base, Identity, utcnow
from .identity import Profile, User, current_user, get_db

router = APIRouter(prefix="/api/v1/jobs", tags=["Jobs and matching"])
SCORING_VERSION = "deterministic-v1"


class Job(Identity, Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("user_id", "source_url"), UniqueConstraint("user_id", "id"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_url: Mapped[str] = mapped_column(String(2048))
    data: Mapped[dict] = mapped_column(JSONB)
    provenance: Mapped[dict] = mapped_column(JSONB, default=lambda: {"kind": "manual"})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SavedJob(Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"], ondelete="CASCADE"),)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Match(Base):
    __tablename__ = "user_job_matches"
    __table_args__ = (ForeignKeyConstraint(["user_id", "job_id"], ["jobs.user_id", "jobs.id"], ondelete="CASCADE"),)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    profile_version: Mapped[int]
    result: Mapped[dict] = mapped_column(JSONB)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl = Field(max_length=2048)
    location: str = Field(default="", max_length=1000)
    remote: bool = False
    description: str = Field(default="", max_length=30000)
    required_skills: list[str] = Field(default_factory=list, max_length=100)
    graduation_years: list[int] = Field(default_factory=list, max_length=50)
    accepted_degrees: list[str] = Field(default_factory=list, max_length=30)
    min_experience_years: float | None = Field(default=None, ge=0, le=60)
    work_country: str = Field(default="", max_length=100)
    deadline: AwareDatetime | None = None
    requirements_reviewed: bool = False

    @field_validator("source_url")
    @classmethod
    def safe_url(cls, value):
        if value.username or value.password:
            raise ValueError("URLs must not contain credentials")
        return value

    @field_validator("required_skills", "accepted_degrees")
    @classmethod
    def clean_list(cls, values):
        result = sorted({v.strip().lower() for v in values if v.strip()})
        if any(len(v) > 100 for v in result):
            raise ValueError("Entries must be at most 100 characters")
        return result

    @field_validator("graduation_years")
    @classmethod
    def years(cls, values):
        if any(v < 1950 or v > 2100 for v in values):
            raise ValueError("Graduation years must be between 1950 and 2100")
        return sorted(set(values))


def owned_job(db, user_id, job_id):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.user_id == user_id))
    if not job:
        raise HTTPException(404, "Job not found")
    return job


def serialize_job(db, job):
    return {"id": job.id, **job.data, "source_url": job.source_url, "created_at": job.created_at,
            "saved": db.get(SavedJob, (job.user_id, job.id)) is not None,
            "provenance": job.provenance.get("kind", "manual"), "source_details": job.provenance}


def calculate_match(profile, job, now=None):
    now = now or utcnow()
    reasons, failures, unknown = [], [], []

    def gate(label, required, actual, passes):
        if required:
            if actual is None or actual == "" or actual == []:
                unknown.append(f"{label}: profile information missing")
            elif not passes:
                failures.append(f"{label}: does not meet the stated requirement")
            else:
                reasons.append(f"{label}: meets the stated requirement")

    if not job.get("requirements_reviewed"):
        unknown.append("Job requirements have not been confirmed against the original posting")
    years = job.get("graduation_years", [])
    gate("Graduation year", years, profile.get("graduation_year"), profile.get("graduation_year") in years)
    degrees = job.get("accepted_degrees", [])
    gate("Degree", degrees, profile.get("degree"), profile.get("degree", "").strip().lower() in degrees)
    minimum = job.get("min_experience_years")
    experience = profile.get("experience_years")
    gate("Experience", minimum is not None, experience, experience is not None and experience >= (minimum or 0))
    country = job.get("work_country", "").strip().lower()
    gate("Work authorization", country, profile.get("authorized_countries"), country in profile.get("authorized_countries", []))
    if job.get("deadline") and datetime.fromisoformat(job["deadline"].replace("Z", "+00:00")) <= now:
        failures.append("Application deadline has passed")
    required = set(job.get("required_skills", []))
    skills = set(profile.get("skills", []))
    overlap = sorted(required & skills)
    gaps = sorted(required - skills)
    skill_points = round(70 * len(overlap) / len(required), 1) if required else None
    role_points = 20 if any(role in job["title"].lower() for role in profile.get("preferred_roles", [])) else 0
    location_points = 10 if job.get("remote") or (profile.get("location", "").strip() and
                         profile["location"].strip().lower() == job.get("location", "").strip().lower()) else 0
    return {"eligibility": "ineligible" if failures else "needs_review" if unknown else "eligible",
            "reasons": failures + unknown + reasons, "matched_skills": overlap, "skill_gaps": gaps,
            "score": round(skill_points + role_points + location_points, 1) if skill_points is not None else None,
            "components": {"skills_out_of_70": skill_points, "role_out_of_20": role_points, "location_out_of_10": location_points},
            "scoring_version": SCORING_VERSION}


@router.post("", status_code=201)
def create_job(body: JobInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = body.model_dump(mode="json", exclude={"source_url"})
    parsed = urlsplit(str(body.source_url))
    url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    db.execute(insert(Job).values(id=uuid.uuid4(), user_id=user.id, source_url=url, data=data, created_at=utcnow())
               .on_conflict_do_nothing(index_elements=[Job.user_id, Job.source_url]))
    job = db.scalar(select(Job).where(Job.user_id == user.id, Job.source_url == url))
    if job.data != data:
        raise HTTPException(409, "This URL already exists with different details")
    db.commit()
    return serialize_job(db, job)


@router.get("")
def list_jobs(saved: bool = False, offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100),
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(Job).where(Job.user_id == user.id)
    if saved:
        query = query.join(SavedJob, (SavedJob.job_id == Job.id) & (SavedJob.user_id == user.id))
    rows = db.scalars(query.order_by(Job.created_at.desc(), Job.id).offset(offset).limit(limit + 1)).all()
    return {"items": [serialize_job(db, job) for job in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return serialize_job(db, owned_job(db, user.id, job_id))


@router.post("/{job_id}/save")
def save_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_job(db, user.id, job_id)
    db.execute(insert(SavedJob).values(user_id=user.id, job_id=job_id, saved_at=utcnow()).on_conflict_do_nothing())
    db.commit()
    return {"saved": True}


@router.delete("/{job_id}/save", status_code=204)
def unsave_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    owned_job(db, user.id, job_id)
    saved = db.get(SavedJob, (user.id, job_id))
    if saved:
        db.delete(saved)
        db.commit()


@router.post("/{job_id}/match")
def score_job(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned_job(db, user.id, job_id)
    profile = db.get(Profile, user.id)
    values = dict(user_id=user.id, job_id=job_id, profile_version=profile.version,
                  result=calculate_match(profile.data, job.data), scored_at=utcnow())
    db.execute(insert(Match).values(**values).on_conflict_do_update(index_elements=[Match.user_id, Match.job_id], set_=values))
    db.commit()
    return get_match(job_id, user, db)


@router.get("/{job_id}/match")
def get_match(job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = owned_job(db, user.id, job_id)
    record = db.get(Match, (user.id, job_id))
    if not record:
        raise HTTPException(404, "Run matching for this job first")
    profile = db.get(Profile, user.id)
    deadline = job.data.get("deadline")
    crossed_deadline = deadline and record.scored_at < datetime.fromisoformat(deadline.replace("Z", "+00:00")) <= utcnow()
    return {**record.result, "job_id": job_id, "profile_version": record.profile_version,
            "scored_at": record.scored_at, "stale": bool(profile.version != record.profile_version or crossed_deadline)}
