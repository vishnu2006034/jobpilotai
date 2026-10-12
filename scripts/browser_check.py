"""Run real-browser checks against a disposable PostgreSQL database and API."""
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from app.db import database
from app.identity import Profile, User, password_hasher


def main():
    load_dotenv(ROOT / ".env")
    url = os.environ["TEST_DATABASE_URL"]
    name = "jobpilot_test_browser_" + uuid.uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    test_url = make_url(url).set(database=name).render_as_string(hide_password=False)
    engine, sessions = database(test_url)
    process = worker = None
    private = ROOT / "private-data"
    private.mkdir(exist_ok=True)
    log = (private / "browser-api.log").open("w", encoding="utf-8")
    try:
        config = Config(str(ROOT / "backend" / "alembic.ini"))
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        password = secrets.token_urlsafe(24)
        email = "browser-qa@example.test"
        with sessions() as db:
            user = User(email=email, password_hash=password_hasher.hash(password))
            db.add(user)
            db.flush()
            db.add(Profile(user_id=user.id, data={}))
            db.commit()
        (private / "browser-test.json").write_text(json.dumps({"email": email, "password": password}), encoding="utf-8")
        env = {**os.environ, "DATABASE_URL": test_url, "APP_ORIGIN": "http://127.0.0.1:5183"}
        if os.name == "nt" and Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe").exists():
            env.setdefault("PLAYWRIGHT_CHANNEL", "chrome")
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8001"],
                                   cwd=ROOT / "backend", env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Test API did not start; see private-data/browser-api.log")
            try:
                if httpx.get("http://127.0.0.1:8001/api/v1/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError("Timed out waiting for test API")
        worker = subprocess.Popen([sys.executable, str(ROOT / "scripts" / "browser_worker_fixture.py")],
                                  cwd=ROOT, env=env, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        result = subprocess.run([shutil.which("npm") or "npm", "run", "test:e2e"], cwd=ROOT / "frontend", env=env)
        return result.returncode
    finally:
        if worker:
            worker.terminate()
            worker.wait(timeout=15)
        if process:
            process.terminate()
            process.wait(timeout=15)
        log.close()
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()
        (private / "browser-test.json").unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
