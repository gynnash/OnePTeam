"""FastAPI application for the local web console (no authentication)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from onep.domain import Problem
from onep.web import runtime
from onep.web.api.events import router as events_router
from onep.web.api.knowledge import router as knowledge_router
from onep.web.api_v1 import router as v1_router

UI_DIST = Path(__file__).resolve().parent / "ui" / "dist"

FALLBACK_INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>OnePTeam Web Console</title></head>
<body style="font-family: sans-serif; max-width: 720px; margin: 3rem auto; padding: 0 1rem">
<h1>OnePTeam Web Console</h1>
<p>The web UI build was not found. The API is available:</p>
<ul>
  <li><a href="/api/v1/projects">GET /api/v1/projects</a> — project list and run status</li>
  <li><a href="/api/knowledge/notes?vault=global">GET /api/knowledge/notes</a> — knowledge notes</li>
</ul>
<p>Build the frontend with <code>cd onep/web/ui &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>
</body></html>"""


def create_app(application=None) -> FastAPI:
    app = FastAPI(title="OnePTeam Web Console")
    # Initialize V2 state only when a V2 endpoint is used. This keeps the
    # read-only UI and legacy API usable in constrained environments.
    app.state.application = application
    app.include_router(v1_router)
    app.include_router(knowledge_router)
    app.include_router(events_router)

    @app.exception_handler(Problem)
    async def problem_handler(_request: Request, exc: Problem) -> JSONResponse:
        status = 404 if exc.code.endswith("_not_found") else 409
        if exc.code in {
            "requirement_required",
            "git_worktree_required",
            "invalid_settings",
            "invalid_test_command",
            "source_required",
        }:
            status = 400
        return JSONResponse(status_code=status, content=exc.to_dict())
    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")
    else:
        @app.get("/", include_in_schema=False)
        def index() -> HTMLResponse:
            return HTMLResponse(FALLBACK_INDEX)
    return app


def run_server(host: str | None = None, port: int | None = None) -> None:
    import uvicorn
    # Resolved via the runtime module so tests can monkeypatch
    # onep.web.runtime.web_config at call time.
    default_host, default_port = runtime.web_config()
    resolved_host = host or default_host
    resolved_port = port or default_port
    print(f"OnePTeam web console: http://{resolved_host}:{resolved_port}")
    uvicorn.run(create_app(), host=resolved_host, port=resolved_port, log_level="info")
