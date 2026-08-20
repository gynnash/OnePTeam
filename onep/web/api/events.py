"""SSE event stream endpoint (file-tail polling over harness state)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from onep.web import runtime
from onep.web.api.common import project_by_name

router = APIRouter(prefix="/api/projects", tags=["events"])


@router.get("/{name}/events")
def events_stream(name: str, poll: float | None = None):
    project = project_by_name(name)
    return StreamingResponse(
        runtime.event_stream(
            Path(project.workspace_path),
            poll=poll if poll is not None else runtime.POLL_INTERVAL,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
