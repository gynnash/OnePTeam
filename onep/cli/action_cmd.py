"""Developer-facing access to the shared capability boundary."""

from __future__ import annotations

import json

import click

from onep.application import RequestContext
from onep.application.defaults import build_application
from onep.domain import Problem
from onep.execution import Worker


@click.command(name="capabilities")
def capabilities_cmd() -> None:
    """List actions available to both CLI and Web clients."""
    click.echo(json.dumps(
        {"capabilities": build_application().registry.describe()},
        ensure_ascii=False,
        indent=2,
    ))


@click.command(name="action")
@click.argument("capability_id")
@click.option("--payload", default="{}", help="JSON object passed to the action")
@click.option("--project", default="", help="Project name or ID")
@click.option("--run-id", default="", help="Run correlation ID")
@click.option("--action-id", default=None, help="Idempotency key")
@click.option("--wait/--no-wait", default=True, help="Run queued work before returning")
def action_cmd(
    capability_id: str,
    payload: str,
    project: str,
    run_id: str,
    action_id: str | None,
    wait: bool,
) -> None:
    """Execute a shared capability and print its structured result."""
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(body, dict):
        raise click.ClickException("--payload must contain a JSON object")
    application = build_application()
    try:
        result = application.execute(
            capability_id,
            body,
            context=RequestContext(project_id=project, run_id=run_id),
            action_id=action_id,
        )
        output = result.to_dict()
        if result.job_id and wait:
            worker = Worker(application.registry, application.store)
            job = application.store.get_job(result.job_id)
            while job and job.status.value == "queued":
                if worker.run_once() is None:
                    break
                job = application.store.get_job(result.job_id)
            if job:
                output["job"] = {
                    "id": job.id,
                    "status": job.status.value,
                    "result": job.result,
                    "error": job.error,
                }
    except Problem as exc:
        raise click.ClickException(
            json.dumps(exc.to_dict(), ensure_ascii=False)
        ) from exc
    click.echo(json.dumps(output, ensure_ascii=False, indent=2))


COMMANDS = [capabilities_cmd, action_cmd]
