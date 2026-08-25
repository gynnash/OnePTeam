"""Application capabilities for the direct-cutover Product Studio."""

from __future__ import annotations

from pathlib import Path

from onep.application.capabilities import Capability, CapabilityRegistry
from onep.application.service import ApplicationService
from onep.application.studio_settings import runtime_connection_test
from onep.config import _config_dir
from onep.infrastructure import ControlStore


def control_store_path() -> Path:
    return _config_dir() / "control.db"


def build_application(path: str | Path | None = None) -> ApplicationService:
    store = ControlStore(path or control_store_path())
    return ApplicationService(build_registry(store), store)


def build_registry(store: ControlStore | None = None) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        Capability(
            "capability.list", "List Product Studio capabilities",
            lambda *_: {"capabilities": registry.describe()},
        )
    )
    registry.register(
        Capability(
            "studio.execute",
            "Execute an approved Release with Codex App Server",
            lambda payload, context: _execute_studio_project(
                payload, context, store
            ),
            mutating=True,
            background=True,
            input_schema={
                "type": "object", "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        )
    )
    registry.register(
        Capability(
            "settings.runtime.test", "Test required Codex App Server capabilities",
            runtime_connection_test,
        )
    )
    return registry


def _execute_studio_project(payload, context, control_store=None) -> dict:
    from onep.studio.execution import StudioExecutionService

    project_id = str(payload.get("project_id") or context.project_id or "").strip()
    cancel_checker = None
    if control_store is not None and context.job_id:
        cancel_checker = lambda: control_store.is_cancel_requested(context.job_id)
    return StudioExecutionService(cancel_checker=cancel_checker).execute_project(project_id)
