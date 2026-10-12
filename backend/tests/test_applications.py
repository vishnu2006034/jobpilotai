from concurrent.futures import ThreadPoolExecutor
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from test_jobs import JOB


def tracked(client):
    job = client.post("/api/v1/jobs", json=JOB).json()
    application = client.post("/api/v1/applications", json={"job_id": job["id"]}).json()
    return job, application


def command(state="APPLIED", version=1):
    return {"state": state, "expected_version": version, "command_id": str(uuid.uuid4()),
            "note": "Confirmed on company careers page", "confirmed": True}


def test_tracking_retry_and_events(signed_in):
    job, application = tracked(signed_in)
    path = f"/api/v1/applications/{application['id']}"
    assert signed_in.post("/api/v1/applications", json={"job_id": job["id"]}).json()["id"] == application["id"]
    payload = command()
    first = signed_in.post(path + "/status", json=payload)
    assert first.status_code == 200 and first.json()["state"] == "APPLIED"
    assert signed_in.post(path + "/status", json=payload).json()["replayed"]
    assert signed_in.post(path + "/status", json={**payload, "note": "changed"}).status_code == 409
    assert signed_in.post(path + "/status", json=command("INTERVIEW", 1)).status_code == 409
    assert signed_in.post(path + "/status", json=command("INTERVIEW", 2)).status_code == 200
    events = signed_in.get(path + "/events").json()["items"]
    assert [e["next_state"] for e in events] == ["INTERVIEW", "APPLIED", "SAVED"]
    assert signed_in.get("/api/v1/dashboard/summary").json()["by_state"] == {"INTERVIEW": 1}


def test_invalid_confirmation_and_ownership(signed_in, accounts):
    job, application = tracked(signed_in)
    path = f"/api/v1/applications/{application['id']}"
    assert signed_in.post(path + "/status", json=command("OFFER")).status_code == 422
    assert signed_in.post(path + "/status", json={**command(), "confirmed": False}).status_code == 422
    assert len(signed_in.get(path + "/events").json()["items"]) == 1
    signed_in.post("/api/v1/auth/login", json={"email": accounts[1].email, "password": "test-password-123"})
    assert signed_in.get(path).status_code == 404
    assert signed_in.get(path + "/events").status_code == 404
    assert signed_in.post(path + "/status", json=command()).status_code == 404
    assert signed_in.post("/api/v1/applications", json={"job_id": job["id"]}).status_code == 404
    assert signed_in.get("/api/v1/applications").json()["items"] == []


def test_concurrent_status_changes(signed_in, app):
    _, application = tracked(signed_in)
    cookie = signed_in.cookies.get("jobpilot_session")
    path = f"/api/v1/applications/{application['id']}/status"

    def update(state):
        with TestClient(app, headers={"X-JobPilot": "1"}) as client:
            client.cookies.set("jobpilot_session", cookie)
            return client.post(path, json=command(state)).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["APPLIED", "DRAFT"]))
    assert sorted(results) == [200, 409]
    assert len(signed_in.get(f"/api/v1/applications/{application['id']}/events").json()["items"]) == 2


def test_timeline_is_append_only(signed_in, app):
    tracked(signed_in)
    for statement in ("UPDATE application_events SET next_state='OFFER'", "DELETE FROM application_events"):
        with pytest.raises(DBAPIError, match="append-only"):
            with app.state.engine.begin() as connection:
                connection.execute(text(statement))
