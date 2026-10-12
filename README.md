# JobPilot

Personal job discovery and application tracking project. Modules are developed and pushed incrementally. See [delivery status](docs/delivery-status.md) for verified progress and limitations.

- [Original architecture proposal](JobPilot_Architecture.md)
- [Architecture flaws, delivery estimates and acceptance plan](docs/architecture-review.md)

Planned stack: React/TypeScript, FastAPI and PostgreSQL in a modular monolith.

First delivery: private local profile, manual jobs, deterministic matching and manual application timeline. Gmail integration and automated submission are later milestones.

Implemented: account/session handling, profile editing, manual opportunities, explainable eligibility and fit scores, application timelines, and scheduled Greenhouse/Lever discovery with in-app alerts. No external applications are submitted.

Never commit credentials, real resumes, email exports or browser sessions.

## Backend setup (PowerShell)

Requires Python 3.13 and PostgreSQL 18. Run these from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt
python scripts/local_database.py start
python -m alembic -c backend/alembic.ini upgrade head
Set-Location backend
python -m app.manage create-user --email you@example.com
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The database helper creates a separate project-owned cluster on port 55439 and writes random credentials to ignored `.env`. It does not modify existing PostgreSQL services. Set `POSTGRES_BIN` if binaries are elsewhere. Alternatively copy `.env.example` to `.env` and supply an existing PostgreSQL database; do not run the cluster helper in that case. Migrations are explicit, never run on API startup. API documentation: `http://127.0.0.1:8000/docs`.

Create-user prompts for a password without placing it in command history. There is no public registration. API mutations require `X-JobPilot: 1`; browser requests must originate from `APP_ORIGIN`. Sessions use HttpOnly, SameSite=Strict cookies. Local HTTP uses `COOKIE_SECURE=false`; an HTTPS deployment must set it to true and use an exact HTTPS origin. This is a local application, not a production deployment recipe.

## Verification

```powershell
Set-Location backend
python -m pytest -q
```

Tests require `TEST_DATABASE_URL` with CREATEDB permission. They create and remove random `jobpilot_test_*` databases; they do not truncate the configured application database. CI uses PostgreSQL 18 as well.

## Frontend setup

With the API running on port 8000, open a second terminal from the repository root:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open `http://localhost:5173` and sign in with the account created above. Use this exact hostname to match the default `APP_ORIGIN`. Vite proxies `/api` to the local backend. Set `JOBPILOT_API_TARGET` to change the target. No default password or demo account is shipped. Begin with My profile, then Add opportunity, Check my fit, and Track this application.

```powershell
# From frontend: type checks and production assets
npm run build
# From the repository root, with Python dependencies and database running:
python scripts/browser_check.py
```

Browser checks create a separate temporary database and synthetic user, start temporary API/frontend servers on ports 8001/5183, and clean up afterward. Windows uses installed Google Chrome if available; otherwise run `npx playwright install chromium` from frontend first. Screenshots and temporary credentials remain under ignored `private-data`; credentials are removed when the run finishes. The screenshot data is explicitly synthetic.

The build outputs static assets; a public production deployment still needs HTTPS, a reverse proxy for `/api`, database backup/restore, managed secrets and an operational review. Google Fonts is optional visual styling; system fonts provide a fallback when offline.

## Company discovery

After upgrading migrations, run these in two additional terminals with the Python environment activated, each from `backend`:

```powershell
python -m app.worker worker
```

```powershell
python -m app.worker scheduler
```

In Discovery, choose **Add suggested companies** to follow ten supported company boards, or add a Greenhouse/Lever board name. This is a starter list, not coverage of every MNC. Sources check every 15 minutes by default while both processes and PostgreSQL run. The first successful check establishes a baseline; later new relevant postings generate persistent in-app alerts. The open app checks for alerts every 15 seconds. This is not instant company push or closed-browser notification delivery.

The shortlist targets SDE/data-analysis fresher or 2027 signals: Chennai on-site, India-compatible remote, and Bengaluru with an explicitly posted INR annual minimum of at least 800,000. Unknown pay, work location or eligibility stays in review. Text signals do not establish eligibility. See the [discovery contract](docs/discovery-contract.md) for supported sources and limitations.

Stop the API, worker and scheduler with Ctrl+C. From the repository root, stop only this project's database with `python scripts/local_database.py stop`.
