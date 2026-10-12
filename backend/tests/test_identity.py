from datetime import timedelta
from sqlalchemy import select

from app.db import utcnow
from app.identity import AuthSession


def test_authentication_and_logout(client, accounts):
    assert client.get("/api/v1/profile").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": accounts[0].email, "password": "wrong"}).status_code == 401
    response = client.post("/api/v1/auth/login", json={"email": accounts[0].email, "password": "test-password-123"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/v1/me").json()["email"] == accounts[0].email
    cookie = client.cookies.get("jobpilot_session")
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("jobpilot_session", cookie)
    assert client.get("/api/v1/me").status_code == 401


def test_profile_versions_and_isolation(signed_in, accounts):
    body = {"full_name": "One", "skills": ["Python", " python "], "expected_version": 1}
    assert signed_in.patch("/api/v1/profile", json=body).json()["skills"] == ["python"]
    assert signed_in.patch("/api/v1/profile", json=body).status_code == 409
    signed_in.post("/api/v1/auth/login", json={"email": accounts[1].email, "password": "test-password-123"})
    assert signed_in.get("/api/v1/profile").json()["full_name"] == ""


def test_csrf_and_expiration(signed_in, app):
    assert signed_in.post("/api/v1/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert signed_in.post("/api/v1/auth/logout", headers={"X-JobPilot": ""}).status_code == 403
    with app.state.sessions() as db:
        session = db.scalar(select(AuthSession))
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert signed_in.get("/api/v1/me").status_code == 401


def test_throttling(client, accounts):
    for _ in range(10):
        assert client.post("/api/v1/auth/login", json={"email": accounts[0].email, "password": "wrong"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": accounts[0].email, "password": "wrong"}).status_code == 429


def test_health(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
