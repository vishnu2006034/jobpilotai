from app.jobs import calculate_match


JOB = {"company": "Example", "title": "Python Engineer", "source_url": "https://example.com/jobs/123",
       "required_skills": ["python", "sql"], "graduation_years": [2027], "requirements_reviewed": True, "remote": True}


def test_matching_fixtures():
    profile = {"skills": ["python"], "graduation_year": 2027, "preferred_roles": ["engineer"]}
    positive = calculate_match(profile, JOB)
    assert positive["eligibility"] == "eligible"
    assert positive["score"] == 65  # 70 * 1/2 + 20 for role + 10 for remote
    assert positive["skill_gaps"] == ["sql"]
    assert calculate_match({**profile, "graduation_year": 2026}, JOB)["eligibility"] == "ineligible"
    assert calculate_match({}, JOB)["eligibility"] == "needs_review"
    assert calculate_match(profile, {**JOB, "requirements_reviewed": False})["eligibility"] == "needs_review"
    assert calculate_match(profile, {**JOB, "required_skills": []})["score"] is None
    assert calculate_match(profile, {**JOB, "deadline": "2020-01-01T00:00:00+00:00"})["eligibility"] == "ineligible"


def test_job_dedup_save_and_stale_matching(signed_in):
    client = signed_in
    job = client.post("/api/v1/jobs", json=JOB).json()
    assert client.post("/api/v1/jobs", json=JOB).json()["id"] == job["id"]
    assert client.post("/api/v1/jobs", json={**JOB, "title": "Different"}).status_code == 409
    assert len(client.get("/api/v1/jobs").json()["items"]) == 1
    for _ in range(2):
        assert client.post(f"/api/v1/jobs/{job['id']}/save").status_code == 200
    assert len(client.get("/api/v1/jobs?saved=true").json()["items"]) == 1
    match = client.post(f"/api/v1/jobs/{job['id']}/match").json()
    assert match["eligibility"] == "needs_review" and not match["stale"]
    assert client.patch("/api/v1/profile", json={"expected_version": 1, "graduation_year": 2027}).status_code == 200
    assert client.get(f"/api/v1/jobs/{job['id']}/match").json()["stale"]
    assert client.delete(f"/api/v1/jobs/{job['id']}/save").status_code == 204
    assert client.get("/api/v1/jobs?saved=true").json()["items"] == []


def test_foreign_jobs_hidden(signed_in, accounts):
    job = signed_in.post("/api/v1/jobs", json=JOB).json()
    signed_in.post("/api/v1/auth/login", json={"email": accounts[1].email, "password": "test-password-123"})
    assert signed_in.get("/api/v1/jobs").json()["items"] == []
    for path in ("", "/match"):
        assert signed_in.get(f"/api/v1/jobs/{job['id']}{path}").status_code == 404
    for action in ("save", "match"):
        assert signed_in.post(f"/api/v1/jobs/{job['id']}/{action}").status_code == 404


def test_url_and_year_validation(signed_in):
    assert signed_in.post("/api/v1/jobs", json={**JOB, "source_url": "javascript:alert(1)"}).status_code == 422
    assert signed_in.post("/api/v1/jobs", json={**JOB, "graduation_years": [1]}).status_code == 422
