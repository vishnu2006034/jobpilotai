from datetime import datetime, timedelta
import hashlib
import re
import secrets
import uuid

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, String, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Mapped, mapped_column, Session

from .db import Base, Identity, utcnow

router = APIRouter(prefix="/api/v1")
password_hasher = PasswordHasher()
DUMMY_HASH = password_hasher.hash(secrets.token_urlsafe(32))
COOKIE = "jobpilot_session"


class User(Identity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(default=1)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class LoginGuard(Base):
    __tablename__ = "login_guards"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def get_db(request: Request):
    with request.app.state.sessions() as db:
        yield db


def current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE, "")
    session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if not session or session.expires_at <= utcnow():
        raise HTTPException(401, "Sign in to continue")
    user = db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Sign in to continue")
    return user


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email")
        return value


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(default="", max_length=120)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    degree: str = Field(default="", max_length=120)
    experience_years: float | None = Field(default=None, ge=0, le=60)
    location: str = Field(default="", max_length=120)
    skills: list[str] = Field(default_factory=list, max_length=100)
    authorized_countries: list[str] = Field(default_factory=list, max_length=50)
    preferred_roles: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("skills", "authorized_countries", "preferred_roles")
    @classmethod
    def clean_list(cls, values):
        result = sorted({v.strip().lower() for v in values if v.strip()})
        if any(len(v) > 100 for v in result):
            raise ValueError("List entries must be at most 100 characters")
        return result


class ProfileUpdate(ProfileInput):
    expected_version: int = Field(ge=1)


@router.post("/auth/login")
def login(body: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    # Database-backed account and IP windows also work across API processes.
    ip = request.client.host if request.client else "unknown"
    keys = sorted([(hashlib.sha256(("email:" + body.email).encode()).hexdigest(), 10),
                   (hashlib.sha256(("ip:" + ip).encode()).hexdigest(), 50)])
    for key, limit in keys:
        db.execute(insert(LoginGuard).values(key=key, attempts=0, window_start=utcnow()).on_conflict_do_nothing())
        guard = db.scalar(select(LoginGuard).where(LoginGuard.key == key).with_for_update())
        if guard.window_start < utcnow() - timedelta(minutes=15):
            guard.attempts, guard.window_start = 0, utcnow()
        if guard.attempts >= limit:
            db.commit()
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        guard.attempts += 1
    db.commit()
    user = db.scalar(select(User).where(User.email == body.email))
    try:
        password_hasher.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except VerificationError:
        raise HTTPException(401, "Email or password is incorrect")
    if not user:
        raise HTTPException(401, "Email or password is incorrect")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(body.password)
    token = secrets.token_urlsafe(32)
    hours = request.app.state.settings.session_hours
    db.add(AuthSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                       expires_at=utcnow() + timedelta(hours=hours)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, secure=request.app.state.settings.secure_cookie,
                        samesite="strict", max_age=hours * 3600, path="/")
    return {"id": user.id, "email": user.email}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE, "")
    session = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email}


@router.get("/profile")
def profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = db.get(Profile, user.id)
    return {**ProfileInput(**record.data).model_dump(), "version": record.version}


@router.patch("/profile")
def update_profile(body: ProfileUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = db.scalar(select(Profile).where(Profile.user_id == user.id).with_for_update())
    if record.version != body.expected_version:
        raise HTTPException(409, "Profile changed. Reload before saving.")
    record.data = body.model_dump(exclude={"expected_version"})
    record.version += 1
    db.commit()
    return {**record.data, "version": record.version}
