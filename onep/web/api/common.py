"""Small compatibility helpers for unversioned read-only endpoints."""

from fastapi import HTTPException

from onep.application.defaults import resolve_project
from onep.domain import Problem


def project_by_name(reference: str):
    try:
        return resolve_project(reference)
    except Problem as exc:
        raise HTTPException(status_code=404, detail=exc.detail or exc.title) from exc
