from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def create_app() -> FastAPI:
    app = FastAPI(title="AR Aging Dashboard", version="0.1.0")

    # Stateless tool: no DB, no lifespan. Routes are pure functions of their input.
    from api import analysis, health

    app.include_router(health.router)
    app.include_router(analysis.router)

    # Serve the built Next.js static export at /app
    # Run `cd frontend && pnpm build` to generate frontend/out/ before starting.
    # Server starts fine without it (API-only mode when out/ doesn't exist).
    # __file__ = src/api/__init__.py → 3 parents up = repo root
    frontend_out = Path(__file__).resolve().parent.parent.parent / "frontend" / "out"
    if frontend_out.exists():
        app.mount("/app", StaticFiles(directory=str(frontend_out), html=True), name="frontend")

    return app


app = create_app()
