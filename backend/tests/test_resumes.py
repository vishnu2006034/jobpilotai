from concurrent.futures import ThreadPoolExecutor

from app.resumes import ResumeInput, import_resume


TEXT = "Synthetic Candidate\nChennai\n\nB.Tech, graduating 2027\n\nBuilt a Python project.\nUsed SQL."
JOB = {"company": "Synthetic", "title": "Python Engineer", "source_url": "https://example.test/resume-job"}


def source(client):
    response = client.post("/api/v1/resumes", json={"title": "Original", "text": TEXT})
    assert response.status_code == 201
    return response.json()


def test_review_snapshot_and_export(signed_in):
    c = signed_in
    r = source(c)
    job = c.post("/api/v1/jobs", json=JOB).json()
    payload = {"resume_id": r["id"], "job_id": job["id"], "selected_blocks": [2, 0]}
    assert c.post("/api/v1/resumes/drafts", json=payload).status_code == 409
    path = f"/api/v1/resumes/{r['id']}/review"
    assert c.post(path, json={"digest": "0" * 64}).status_code == 409
    reviewed = c.post(path, json={"digest": r["digest"]}).json()
    assert reviewed["reviewed_at"]
    assert c.post(path, json={"digest": r["digest"]}).json() == reviewed
    draft = c.post("/api/v1/resumes/drafts", json=payload).json()
    assert draft["selected_blocks"] == [0, 2]
    assert draft["text"] == "Synthetic Candidate\nChennai\n\nBuilt a Python project.\nUsed SQL."
    assert "B.Tech" not in draft["text"]
    assert c.post("/api/v1/resumes/drafts", json=payload).json()["id"] == draft["id"]
    download = f"/api/v1/resumes/drafts/{draft['id']}/download"
    assert c.get(download).status_code == 409
    assert c.post(f"/api/v1/resumes/drafts/{draft['id']}/review", json={"digest": draft["digest"]}).status_code == 200
    exported = c.get(download)
    assert exported.text == draft["text"]
    assert exported.headers["cache-control"] == "no-store"
    assert "attachment" in exported.headers["content-disposition"]
    # New source content creates a different unreviewed version, preserving the old draft.
    updated = c.post("/api/v1/resumes", json={"title": "Updated", "text": TEXT + "\n\nNew project"}).json()
    assert updated["id"] != r["id"] and updated["reviewed_at"] is None
    assert c.get(download).text == draft["text"]


def test_validation_and_no_injected_claims(signed_in):
    c = signed_in
    for text in (" ", "a\x00b", "a" * 50001):
        assert c.post("/api/v1/resumes", json={"title": "Bad", "text": text}).status_code == 422
    r = source(c)
    c.post(f"/api/v1/resumes/{r['id']}/review", json={"digest": r["digest"]})
    job = c.post("/api/v1/jobs", json=JOB).json()
    body = {"resume_id": r["id"], "job_id": job["id"], "selected_blocks": [0]}
    for selected in ([], [-1], [3], [0, 0]):
        assert c.post("/api/v1/resumes/drafts", json={**body, "selected_blocks": selected}).status_code == 422
    assert c.post("/api/v1/resumes/drafts", json={**body, "text": "Invented experience"}).status_code == 422
    assert c.patch(f"/api/v1/resumes/{r['id']}", json={"text": "Edit"}).status_code in (404, 405)


def test_private_resume_and_draft_ownership(signed_in, accounts):
    c = signed_in
    r = source(c)
    c.post(f"/api/v1/resumes/{r['id']}/review", json={"digest": r["digest"]})
    job = c.post("/api/v1/jobs", json=JOB).json()
    draft = c.post("/api/v1/resumes/drafts", json={"resume_id": r["id"], "job_id": job["id"], "selected_blocks": [0]}).json()
    c.post("/api/v1/auth/login", json={"email": accounts[1].email, "password": "test-password-123"})
    assert c.get("/api/v1/resumes").json() == []
    assert c.get("/api/v1/resumes/drafts").json() == []
    assert c.post(f"/api/v1/resumes/{r['id']}/review", json={"digest": r["digest"]}).status_code == 404
    assert c.get(f"/api/v1/resumes/drafts/{draft['id']}/download").status_code == 404
    assert c.post(f"/api/v1/resumes/drafts/{draft['id']}/review", json={"digest": draft["digest"]}).status_code == 404
    own = source(c)
    c.post(f"/api/v1/resumes/{own['id']}/review", json={"digest": own["digest"]})
    assert c.post("/api/v1/resumes/drafts", json={"resume_id": own["id"], "job_id": job["id"], "selected_blocks": [0]}).status_code == 404


def test_concurrent_import_deduplicates(app, accounts):
    def save(_):
        with app.state.sessions() as db:
            return import_resume(ResumeInput(title="Concurrent", text=TEXT), db, accounts[0])["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results[0] == results[1]
