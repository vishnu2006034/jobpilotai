from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .config import Settings
from .db import database
from .identity import router
from .jobs import router as jobs_router


def create_app(settings: Settings):
    app = FastAPI(title="JobPilot", version="0.1.0")
    app.state.settings = settings
    app.state.engine, app.state.sessions = database(settings.database_url)

    @app.middleware("http")
    async def browser_boundary(request: Request, call_next):
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if request.headers.get("x-jobpilot") != "1" or (origin and origin != settings.app_origin):
                return JSONResponse(status_code=403, content={"detail": "Request origin or CSRF header rejected"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/v1/health")
    def health():
        with app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "version": "0.1.0"}

    app.include_router(router)
    app.include_router(jobs_router)
    return app
