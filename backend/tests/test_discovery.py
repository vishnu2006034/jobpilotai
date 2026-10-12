from datetime import timedelta
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app import ats
from app.ats import fetch_feed, normalize
from app.db import utcnow
from app.discovery import Source, Posting, DiscoveryNotice, DiscoveryHandler
from app.operations import Schedule, Task, enqueue, process_one, schedule_tick, TaskFailure
from app.targeting import target_posting


def lever_row(id="one", **changes):
    return {"id": id, "text": "Software Engineer — Graduate 2027", "hostedUrl": f"https://jobs.lever.co/example/{id}",
            "categories": {"location": "Chennai, India"}, "workplaceType": "on-site",
            "descriptionPlain": "Graduate opening for the 2027 batch", **changes}


def source(client):
    response = client.post("/api/v1/sources", json={"provider": "lever", "board": "example", "name": "Synthetic Company"})
    assert response.status_code == 201
    return response.json()


def queue(app, user, source_id):
    with app.state.sessions.begin() as db:
        return enqueue(db, user.id, "discovery.fetch", {"source_id": str(source_id)}, str(source_id), str(uuid.uuid4())).id


def process(app, rows):
    handler = DiscoveryHandler(app.state.sessions, lambda *args: [normalize("lever", "Synthetic Company", row) for row in rows])
    assert process_one(app.state.sessions, {"discovery.fetch": handler})


def test_greenhouse_and_lever_contracts_and_pagination(monkeypatch):
    raw = {"id": 7, "title": "Data Analyst", "location": {"name": "Chennai"},
           "absolute_url": "https://example.com/jobs/7", "content": "&lt;p&gt;Hello&lt;/p&gt;<script>ignore me</script>"}
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"jobs": [raw], "meta": {"total": 1}}))) as client:
        items = fetch_feed("greenhouse", "example", "Example", client)
    assert items[0].external_id == "7" and items[0].data["description"] == "Hello"
    monkeypatch.setattr(ats, "PAGE_SIZE", 1)
    calls = []

    def response(request):
        skip = int(request.url.params["skip"])
        calls.append(skip)
        return httpx.Response(200, json=[lever_row(str(skip))] if skip < 2 else [])

    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        assert len(fetch_feed("lever", "example", "Example", client)) == 2
    assert calls == [0, 1, 2]


@pytest.mark.parametrize("response,code", [
    (httpx.Response(429, headers={"Retry-After": "300"}), "rate_limited"),
    (httpx.Response(302, headers={"Location": "http://localhost/"}), "provider_rejected"),
    (httpx.Response(404), "board_not_found"),
    (httpx.Response(200, json={"jobs": [], "meta": {"total": 4}}), "incomplete_feed"),
    (httpx.Response(200, json={"unexpected": []}), "invalid_feed"),
])
def test_bad_feeds_do_not_look_like_empty_success(response, code):
    with httpx.Client(transport=httpx.MockTransport(lambda r: response)) as client:
        with pytest.raises(TaskFailure, match=code):
            fetch_feed("greenhouse", "example", "Example", client)


def test_bounded_feed_and_validation(monkeypatch):
    monkeypatch.setattr(ats, "MAX_BYTES", 10)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[lever_row()]))) as client:
        with pytest.raises(TaskFailure, match="feed_too_large"):
            fetch_feed("lever", "example", "Example", client)
    with pytest.raises(TaskFailure, match="invalid_source"):
        fetch_feed("lever", "../../private", "Example")
    with pytest.raises(TaskFailure, match="invalid_feed"):
        normalize("lever", "Example", lever_row(hostedUrl="javascript:alert(1)"))


def test_requested_location_and_salary_rules():
    base = normalize("lever", "Example", lever_row()).data
    assert target_posting(base)["status"] == "potential_match"
    bangalore = {**base, "location": "Bengaluru, India"}
    assert target_posting(bangalore)["status"] == "needs_review"
    assert target_posting({**bangalore, "salary": {"currency": "INR", "interval": "per-year", "min": 800000, "max": 1200000}})["status"] == "potential_match"
    assert target_posting({**bangalore, "salary": {"currency": "INR", "interval": "per-year", "min": 600000, "max": 700000}})["status"] == "excluded"
    assert target_posting({**bangalore, "salary": {"currency": "INR", "interval": "per-year", "min": 600000, "max": 900000}})["status"] == "needs_review"
    assert target_posting({**base, "workplace_type": "remote", "location": "Remote, India"})["status"] == "potential_match"
    assert target_posting({**base, "workplace_type": "remote", "location": "United States"})["status"] == "excluded"
    assert target_posting({**base, "workplace_type": "remote", "location": "Remote"})["status"] == "needs_review"
    assert target_posting({**base, "title": "Senior Software Engineer"})["status"] == "excluded"
    assert target_posting({**base, "title": "Software Engineer", "description": ""})["status"] == "needs_review"


def test_snapshot_replay_alerts_import_and_source_changes(app, signed_in, accounts):
    src = source(signed_in)
    source_id = uuid.UUID(src["id"])
    assert schedule_tick(app.state.sessions) == 1
    process(app, [lever_row()])
    assert signed_in.get("/api/v1/discovery-notices").json()["unread_count"] == 0  # first sync is a baseline
    first = signed_in.get("/api/v1/discovered-postings").json()["items"][0]
    imported = signed_in.post(f"/api/v1/discovered-postings/{first['id']}/import").json()
    assert imported["provenance"] == "ats_snapshot"
    queue(app, accounts[0], source_id)
    process(app, [lever_row(descriptionPlain="Updated graduate 2027 details"), lever_row("two")])
    rows = signed_in.get("/api/v1/discovered-postings").json()["items"]
    assert len(rows) == 2 and next(r for r in rows if r["id"] == first["id"])["revision"] == 2
    # Imported snapshots are never overwritten by a later provider revision.
    assert signed_in.get(f"/api/v1/jobs/{imported['id']}").json()["description"] == "Graduate opening for the 2027 batch"
    assert signed_in.post(f"/api/v1/discovered-postings/{first['id']}/import").json()["already_in_workspace"]
    notices = signed_in.get("/api/v1/discovery-notices").json()
    assert notices["unread_count"] == 1 and notices["items"][0]["potential_count"] == 1
    queue(app, accounts[0], source_id)
    process(app, [lever_row(descriptionPlain="Updated graduate 2027 details"), lever_row("two")])
    assert signed_in.get("/api/v1/discovery-notices").json()["unread_count"] == 1


def test_failure_missing_grace_and_reappearance(app, signed_in, accounts):
    source_id = uuid.UUID(source(signed_in)["id"])
    queue(app, accounts[0], source_id)
    process(app, [lever_row()])
    task_id = queue(app, accounts[0], source_id)

    def broken(*args):
        raise TaskFailure("incomplete_feed")

    process_one(app.state.sessions, {"discovery.fetch": DiscoveryHandler(app.state.sessions, broken)})
    with app.state.sessions() as db:
        assert db.get(Task, task_id).status == "failed"
        assert db.scalar(select(Posting)).missing_since is None
    queue(app, accounts[0], source_id)
    process(app, [])
    with app.state.sessions.begin() as db:
        posting = db.scalar(select(Posting))
        assert posting.missing_since and posting.closed_at is None
        posting.missing_since = utcnow() - timedelta(hours=25)
    queue(app, accounts[0], source_id)
    process(app, [])
    assert signed_in.get("/api/v1/discovered-postings").json()["items"] == []
    queue(app, accounts[0], source_id)
    process(app, [lever_row()])
    assert len(signed_in.get("/api/v1/discovered-postings").json()["items"]) == 1


def test_source_ownership_pause_replay_and_rate_limit(app, signed_in, accounts):
    src = source(signed_in)
    body = {"source_id": src["id"], "command_id": str(uuid.uuid4())}
    run = signed_in.post("/api/v1/discovery-runs", json=body)
    assert run.status_code == 202
    assert signed_in.post("/api/v1/discovery-runs", json=body).json()["id"] == run.json()["id"]
    process(app, [])
    assert signed_in.post("/api/v1/discovery-runs", json={**body, "command_id": str(uuid.uuid4())}).status_code == 429
    assert signed_in.patch(f"/api/v1/sources/{src['id']}", json={"expected_version": 1, "enabled": False, "interval_minutes": 30}).status_code == 200
    assert signed_in.patch(f"/api/v1/sources/{src['id']}", json={"expected_version": 1, "enabled": True, "interval_minutes": 30}).status_code == 409
    signed_in.post("/api/v1/auth/login", json={"email": accounts[1].email, "password": "test-password-123"})
    assert signed_in.get("/api/v1/sources").json()["items"] == []
    assert signed_in.get("/api/v1/discovered-postings").json()["items"] == []
    assert signed_in.post("/api/v1/discovery-runs", json=body).status_code == 404
    assert signed_in.get(f"/api/v1/discovery-runs/{run.json()['id']}").status_code == 404


def test_source_url_injection_rejected(signed_in):
    assert signed_in.post("/api/v1/sources", json={"provider": "lever", "board": "../localhost", "name": "Bad"}).status_code == 422
    assert signed_in.post("/api/v1/sources", json={"provider": "custom", "board": "example", "name": "Bad"}).status_code == 422
