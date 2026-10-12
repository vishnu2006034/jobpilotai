from fastapi.testclient import TestClient

from app.factory import create_app
from test_jobs import JOB


def test_fresh_api_instance_preserves_records(signed_in, app):
    job = signed_in.post("/api/v1/jobs", json=JOB).json()
    cookie = signed_in.cookies.get("jobpilot_session")
    restarted = create_app(app.state.settings)
    try:
        with TestClient(restarted, headers={"X-JobPilot": "1"}) as client:
            client.cookies.set("jobpilot_session", cookie)
            response = client.get(f"/api/v1/jobs/{job['id']}")
            assert response.status_code == 200
            assert response.json()["title"] == JOB["title"]
    finally:
        restarted.state.engine.dispose()
