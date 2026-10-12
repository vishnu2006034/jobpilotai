from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str
    app_origin: str = "http://localhost:5173"
    secure_cookie: bool = False
    session_hours: int = 12

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        url = os.environ.get("DATABASE_URL", "")
        if not url.startswith("postgresql+psycopg://"):
            raise RuntimeError("Set DATABASE_URL to a PostgreSQL psycopg URL; see .env.example")
        return cls(url, os.getenv("APP_ORIGIN", "http://localhost:5173").rstrip("/"),
                   os.getenv("COOKIE_SECURE", "false").lower() == "true")
