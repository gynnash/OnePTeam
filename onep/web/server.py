"""FastAPI application for the local web console (no authentication)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from onep.web.api.events import router as events_router
from onep.web.api.knowledge import router as knowledge_router
from onep.web.api.projects import router as projects_router
from onep.web.runtime import web_config

UI_DIST = Path(__file__).resolve().parent / "ui" / "dist"

FALLBACK_INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>OnePTeam Web Console</title></head>
<body style="font-family: sans-serif; max-width: 720px; margin: 3rem auto; padding: 0 1rem">
<h1>OnePTeam Web Console</h1>
<p>The web UI build was not found. The API is available:</p>
<ul>
  <li><a href="/api/projects">GET /api/projects</a> — project list and run status</li>
  <li><a href="/api/knowledge/notes?vault=global">GET /api/knowledge/notes</a> — knowledge notes</li>
</ul>
<p>Build the frontend with <code>cd onep/web/ui &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>
</body></html>"""


def create_app() -> FastAPI:
    app = FastAPI(title="OnePTeam Web Console")
    app.include_router(projects_router)
    app.include_router(knowledge_router)
    app.include_router(events_router)
    if UI_DIST.exists():
        app.mount("/", StaticFiles(directory=str(UI_DIST), html=True), name="ui")
    else:
        @app.get("/", include_in_schema=False)
        def index() -> HTMLResponse:
            return HTMLResponse(FALLBACK_INDEX)
    return app


def run_server(host: str | None = None, port: int | None = None) -> None:
    import uvicorn
    default_host, default_port = web_config()
    resolved_host = host or default_host
    resolved_port = port or default_port
    print(f"OnePTeam web console: http://{resolved_host}:{resolved_port}")
    uvicorn.run(create_app(), host=resolved_host, port=resolved_port, log_level="info")
