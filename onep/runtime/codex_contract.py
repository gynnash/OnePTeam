"""Shared OnePTeam contract used by every Codex transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from onep.runtime.engineering import ExecutionRequest


OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "contract_version",
        "baseline_fingerprint",
        "changed_files",
        "commands_attempted",
        "unresolved_blockers",
        "summary",
    ],
    "properties": {
        "schema_version": {"type": "integer", "const": 1},
        "contract_version": {"type": "integer"},
        "baseline_fingerprint": {"type": "string"},
        "changed_files": {"type": "array", "items": {"type": "string"}},
        "commands_attempted": {"type": "array", "items": {"type": "string"}},
        "unresolved_blockers": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
    },
}


def developer_instructions() -> str:
    return (
        "You are OnePTeam's write-capable engineering executor. Work only inside "
        "the supplied workspace and current delivery work item. Do not change the "
        "delivery contract, weaken tests, push commits, deploy externally, or claim "
        "that OnePTeam verification passed. OnePTeam independently checks the diff, "
        "tests, review findings, and final acceptance after this turn."
    )


def execution_prompt(request: ExecutionRequest, *, invoke_skill: bool = False) -> str:
    values = {
        "work_item_id": request.work_item_id,
        "attempt": request.attempt,
        "mode": request.mode,
        "objective": request.objective,
        "instructions": request.instructions,
        "contract_id": request.contract_id,
        "contract_version": request.contract_version,
        "baseline_fingerprint": request.baseline_fingerprint,
        "acceptance_rule_ids": list(request.acceptance_rule_ids),
        "expected_paths": list(request.expected_paths),
        "constraints": list(request.constraints),
        "feedback": request.feedback,
        "execution_strategy": request.strategy,
        "sanitized_prior_knowledge": request.sanitized_knowledge_context[:6000],
    }
    prefix = "$onep-delivery " if invoke_skill else ""
    return (
        prefix
        + "Implement or repair this bounded OnePTeam work item. Inspect only what is "
        "needed, edit the repository directly, and run focused tests when useful. "
        "Return the required structured summary; your summary is candidate evidence "
        "and does not determine completion.\n\n"
        + json.dumps(values, ensure_ascii=False, indent=2)
    )


def goal_objective(request: ExecutionRequest) -> str:
    values = {
        "objective": request.objective,
        "contract_id": request.contract_id,
        "contract_version": request.contract_version,
        "work_item_id": request.work_item_id,
        "acceptance_rule_ids": list(request.acceptance_rule_ids),
        "sanitized_prior_knowledge": request.sanitized_knowledge_context[:3000],
        "stop_condition": (
            "Stop after producing a candidate patch and structured summary. OnePTeam "
            "owns independent gates and the final completion decision."
        ),
    }
    return json.dumps(values, ensure_ascii=False, sort_keys=True)[:4000]


def parse_structured_response(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError as exc:
        raise ValueError("Codex returned invalid structured output") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Codex structured output must be an object")
    missing = set(OUTPUT_SCHEMA["required"]) - set(parsed)
    if missing:
        raise ValueError(f"Codex structured output is missing: {sorted(missing)}")
    if parsed.get("schema_version") != 1:
        raise ValueError("Codex returned an unsupported output schema")
    return parsed


def validate_structured_response(
    parsed: dict[str, Any], request: ExecutionRequest
) -> None:
    if parsed["contract_version"] != request.contract_version:
        raise ValueError("Codex returned a mismatched contract version")
    if parsed["baseline_fingerprint"] != request.baseline_fingerprint:
        raise ValueError("Codex returned a mismatched baseline fingerprint")


def delivery_skill_path() -> Path:
    return Path(__file__).with_name("onep_delivery_skill.md").resolve()
