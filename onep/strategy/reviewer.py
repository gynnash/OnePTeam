"""Independent, tool-free review of an Optimize Plan diff."""
from __future__ import annotations

import json
import re

from onep.strategy.optimize_models import ReviewResult


REVIEW_SYSTEM = """You are an independent code reviewer. You have no tools and
must review only the supplied Plan, diff, tests, and project context. Return
JSON only: {"passed": boolean, "blocking_issues": [{"file": string,
"line": integer|null, "message": string}], "summary": string}. A malformed or
uncertain response is blocking."""


class ReviewAgent:
    def __init__(self, llm):
        self.llm = llm

    def review(
        self, plan: str, diff: str, test_summary: str, project_context: str
    ) -> ReviewResult:
        prompt = (
            f"## Plan\n{plan}\n\n## Diff\n{diff}\n\n"
            f"## Test results\n{test_summary}\n\n## Project context\n"
            f"{project_context}"
        )
        try:
            output = self.llm.invoke(
                system_prompt=REVIEW_SYSTEM,
                user_prompt=prompt,
                stage_name="code_reviewer",
            )
            match = re.search(r"\{.*\}", output, re.DOTALL)
            data = json.loads(match.group(0) if match else output)
            if not isinstance(data.get("passed"), bool):
                raise ValueError("passed must be boolean")
            issues = data.get("blocking_issues") or []
            if not isinstance(issues, list):
                raise ValueError("blocking_issues must be a list")
            blocking_issues = []
            for issue in issues:
                if not isinstance(issue, dict) or not issue.get("message"):
                    raise ValueError("invalid blocking issue")
                blocking_issues.append({
                    "file": str(issue.get("file") or "?"),
                    "line": issue.get("line"),
                    "message": str(issue["message"]),
                })
            passed = data["passed"] and not blocking_issues
            return ReviewResult(
                passed=passed,
                summary=str(data.get("summary") or ""),
                blocking_issues=blocking_issues,
            )
        except (ValueError, TypeError, json.JSONDecodeError, AttributeError):
            return ReviewResult(
                passed=False,
                summary="invalid reviewer output",
                blocking_issues=[{
                    "file": "?",
                    "line": None,
                    "message": "Reviewer did not return valid structured JSON.",
                }],
            )
