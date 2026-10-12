from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import uuid

import pytest
from sqlalchemy import func, select

from app.db import utcnow
from app.operations import (Task, TaskAttempt, Schedule, TaskFailure, LostLease, enqueue, claim_next,
                            heartbeat, locked_claim, process_one, schedule_tick)


def add_task(app, user, key="one"):
    with app.state.sessions.begin() as db:
        return enqueue(db, user.id, "discovery.fetch", {"source_id": key}, key, key).id


def test_enqueue_replay_and_owned_read(app, signed_in, accounts):
    task_id = add_task(app, accounts[0])
    assert add_task(app, accounts[0]) == task_id
    with app.state.sessions.begin() as db:
        assert enqueue(db, accounts[0].id, "discovery.fetch", {"source_id": "one"}, "one", "another-key").id == task_id
    with pytest.raises(ValueError, match="different input"):
        with app.state.sessions.begin() as db:
            enqueue(db, accounts[0].id, "discovery.fetch", {"source_id": "two"}, "two", "one")
    assert signed_in.get(f"/api/v1/tasks/{task_id}").status_code == 200
    signed_in.post("/api/v1/auth/login", json={"email": accounts[1].email, "password": "test-password-123"})
    assert signed_in.get(f"/api/v1/tasks/{task_id}").status_code == 404


def test_workers_claim_once_and_expired_lease_is_fenced(app, accounts):
    task_id = add_task(app, accounts[0])
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_next(app.state.sessions), range(2)))
    claim = next(c for c in claims if c)
    assert len([c for c in claims if c]) == 1
    heartbeat(app.state.sessions, claim)
    with app.state.sessions.begin() as db:
        db.get(Task, task_id).lease_expires_at = utcnow() - timedelta(seconds=1)
    with pytest.raises(LostLease):
        heartbeat(app.state.sessions, claim)
    assert claim_next(app.state.sessions) is None  # recovery backs off instead of hot-looping
    with app.state.sessions.begin() as db:
        task = db.get(Task, task_id)
        assert task.status == "queued"
        task.run_after = utcnow() - timedelta(seconds=1)
    next_claim = claim_next(app.state.sessions)
    assert next_claim.attempt == 2 and next_claim.token != claim.token
    with pytest.raises(LostLease):
        with app.state.sessions.begin() as db:
            locked_claim(db, claim)


def test_handler_effects_and_completion_are_atomic(app, accounts):
    task_id = add_task(app, accounts[0])

    class Handler:
        def prepare(self, claim):
            # prepare can open another connection; it does not hold the queue transaction.
            with app.state.sessions() as db:
                assert db.get(Task, claim.id).status == "running"
            return {"count": 2}

        def apply(self, db, claim, prepared):
            db.add(Schedule(user_id=claim.user_id, task_type="discovery.fetch", payload={}, resource_key="effect",
                            interval_minutes=15, next_run_at=utcnow()))
            db.flush()
            raise TaskFailure("invalid_feed")

    assert process_one(app.state.sessions, {"discovery.fetch": Handler()})
    with app.state.sessions() as db:
        assert db.get(Task, task_id).status == "failed"
        assert db.scalar(select(func.count()).select_from(Schedule)) == 0
        assert db.get(TaskAttempt, (task_id, 1)).error_code == "invalid_feed"


def test_bounded_retry_and_success(app, accounts):
    task_id = add_task(app, accounts[0])

    class RetryHandler:
        def prepare(self, claim):
            raise TaskFailure("rate_limited", retryable=True, retry_after=300)

    for attempt in range(3):
        assert process_one(app.state.sessions, {"discovery.fetch": RetryHandler()})
        with app.state.sessions.begin() as db:
            task = db.get(Task, task_id)
            assert task.attempt == attempt + 1
            assert task.status == ("failed" if attempt == 2 else "queued")
            assert task.run_after >= utcnow() + timedelta(seconds=290)
            task.run_after = utcnow() - timedelta(seconds=1)
    assert not process_one(app.state.sessions, {})


def test_scheduler_coalesces_downtime_and_concurrent_ticks(app, accounts):
    with app.state.sessions.begin() as db:
        db.add(Schedule(user_id=accounts[0].id, task_type="discovery.fetch", payload={"source_id": "one"},
                        resource_key="one", interval_minutes=15, next_run_at=utcnow() - timedelta(days=2)))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: schedule_tick(app.state.sessions), range(2)))
    assert sum(results) == 1
    with app.state.sessions() as db:
        assert db.scalar(select(func.count()).select_from(Task)) == 1
        assert db.scalar(select(Schedule)).next_run_at > utcnow()


def test_successful_worker_restart_uses_persisted_task(app, accounts):
    from app.db import database
    task_id = add_task(app, accounts[0])

    class Handler:
        def prepare(self, claim):
            return 4

        def apply(self, db, claim, prepared):
            return {"imported": prepared}

    engine, fresh_sessions = database(app.state.settings.database_url)
    try:
        assert process_one(fresh_sessions, {"discovery.fetch": Handler()})
        with fresh_sessions() as db:
            task = db.get(Task, task_id)
            assert task.status == "succeeded" and task.result == {"imported": 4}
            assert db.get(TaskAttempt, (task_id, 1)).status == "succeeded"
    finally:
        engine.dispose()
