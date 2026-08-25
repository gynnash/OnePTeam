"""FastAPI application for the local web console (no authentication)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from onep.domain import Problem
from onep.web import studio_runtime
from onep.web.api_v2 import router as v2_router

UI_DIST = Path(__file__).resolve().parent / "ui" / "dist"

FALLBACK_INDEX = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>OnePTeam Web Console</title></head>
<body style="font-family: sans-serif; max-width: 720px; margin: 3rem auto; padding: 0 1rem">
<h1>OnePTeam Web Console</h1>
<p>The web UI build was not found. The API is available:</p>
<ul>
  <li><a href="/api/v2/projects">GET /api/v2/projects</a> — Product Studio projects</li>
  <li><a href="/api/v2/knowledge/search">GET /api/v2/knowledge/search</a> — knowledge ledger</li>
</ul>
<p>Build the frontend with <code>cd onep/web/ui &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>
</body></html>"""


def create_app(application=None, studio_service=None) -> FastAPI:
    app = FastAPI(title="OnePTeam Product Studio")
    app.state.application = application
    app.state.studio_service = studio_service
    app.include_router(v2_router)

    @app.exception_handler(Problem)
    async def problem_handler(_request: Request, exc: Problem) -> JSONResponse:
        status = 404 if exc.code.endswith("_not_found") else 409
        if exc.code in {
            "requirement_required",
            "idea_required",
            "git_worktree_required",
            "git_branch_not_found",
            "git_branch_not_checked_out",
            "git_repository_required",
            "invalid_settings",
            "invalid_test_command",
            "local_repository_required",
            "source_required",
            "source_not_directory",
            "directory_not_found",
            "directory_picker_failed",
            "directory_picker_unavailable",
            "invalid_article_model",
            "invalid_execution_strategy",
            "invalid_release_scope",
            "invalid_discovery_decision",
            "invalid_assumption_status",
            "discovery_answers_required",
            "discovery_answer_required",
            "prd_feedback_required",
        }:
            status = 400
        return JSONResponse(status_code=status, content=exc.to_dict())

    if UI_DIST.exists():
        assets = UI_DIST / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API route not found")
            requested = (UI_DIST / path).resolve()
            root = UI_DIST.resolve()
            if requested.is_relative_to(root) and requested.is_file():
                return FileResponse(requested)
            return FileResponse(root / "index.html")
    else:

        @app.get("/", include_in_schema=False)
        def index() -> HTMLResponse:
            return HTMLResponse(FALLBACK_INDEX)

    return app


def run_server(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    # Resolved via the runtime module so tests can monkeypatch
    # Resolved at call time so tests can replace the local configuration reader.
    default_host, default_port = studio_runtime.web_config()
    resolved_host = host or default_host
    resolved_port = port or default_port
    print(f"OnePTeam web console: http://{resolved_host}:{resolved_port}")
    uvicorn.run(create_app(), host=resolved_host, port=resolved_port, log_level="info")
