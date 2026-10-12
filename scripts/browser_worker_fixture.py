"""Synthetic discovery worker ONLY for an explicitly named disposable browser database."""
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from sqlalchemy.engine import make_url
from app.ats import normalize
from app.config import Settings
from app.db import database
from app.discovery import DiscoveryHandler
from app.operations import process_one, schedule_tick


def main():
    settings = Settings.from_env()
    if not (make_url(settings.database_url).database or "").startswith("jobpilot_test_browser_"):
        raise SystemExit("Synthetic worker only accepts a disposable browser-test database")
    engine, sessions = database(settings.database_url)
    counts = {}

    def fixture(provider, board, company):
        if board != "qa-company":
            raise ValueError("Only the synthetic QA company is supported by this test worker")
        counts[board] = counts.get(board, 0) + 1
        rows = [
            {"id": "chennai", "text": "Software Engineer — Graduate 2027", "categories": {"location": "Chennai, India"},
             "workplaceType": "on-site", "hostedUrl": "https://example.com/fixture/chennai", "descriptionPlain": "Synthetic 2027 batch opening. Not a real vacancy."},
            {"id": "bangalore", "text": "Data Analyst — Fresher", "categories": {"location": "Bengaluru, India"},
             "workplaceType": "on-site", "hostedUrl": "https://example.com/fixture/bangalore", "descriptionPlain": "Synthetic fresher role with unknown salary."},
        ]
        if counts[board] > 1:
            rows.append({"id": "new", "text": "Data Analyst — Graduate 2027", "categories": {"location": "Remote, India"},
                         "workplaceType": "remote", "hostedUrl": "https://example.com/fixture/new", "descriptionPlain": "Synthetic new role after baseline."})
        return [normalize("lever", company, row) for row in rows]

    try:
        while True:
            schedule_tick(sessions)
            process_one(sessions, {"discovery.fetch": DiscoveryHandler(sessions, fixture)})
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
