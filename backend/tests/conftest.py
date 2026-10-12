import os
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from dotenv import load_dotenv
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Settings
from app.db import Base
from app.factory import create_app
from app.identity import Profile, User, password_hasher

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


@pytest.fixture(scope="session")
def app():
    # Tests create and drop ONLY a random database bearing this test prefix.
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is required (PostgreSQL with CREATEDB permission)")
    name = "jobpilot_test_" + uuid.uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    test_url = make_url(url).set(database=name)
    application = create_app(Settings(test_url.render_as_string(hide_password=False)))
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        with application.state.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        yield application
    finally:
        application.state.engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(autouse=True)
def clean(app):
    with app.state.engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


@pytest.fixture
def client(app):
    with TestClient(app, headers={"X-JobPilot": "1"}) as client:
        yield client


@pytest.fixture
def accounts(app):
    with app.state.sessions() as db:
        users = [User(email=f"person{i}@example.test", password_hash=password_hasher.hash("test-password-123")) for i in range(2)]
        db.add_all(users)
        db.flush()
        for user in users:
            db.add(Profile(user_id=user.id, data={}))
        db.commit()
        return users


@pytest.fixture
def signed_in(client, accounts):
    assert client.post("/api/v1/auth/login", json={"email": accounts[0].email, "password": "test-password-123"}).status_code == 200
    return client
