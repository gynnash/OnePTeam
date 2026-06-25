"""Code review loop using LangGraph. Flow: lint -> check -> fix or pass (max 3 iterations)."""
from __future__ import annotations

from typing import TypedDict, Literal
from pathlib import Path

from langgraph.graph import StateGraph, END


class CodeReviewState(TypedDict):
    workspace: str
    code_files: list[str]
    review_notes: str
    lint_output: str
    iteration: int
    passed: bool
    status: str


def lint_code(state: CodeReviewState) -> CodeReviewState:
    from onep.tools.lint import LintTool
    ws = Path(state["workspace"])
    tool = LintTool(workspace=ws)
    output = tool.check_python()
    state["lint_output"] = output
    state["passed"] = "No issues found" in output
    return state


def decide_next(state: CodeReviewState) -> Literal["fix_issues", "done"]:
    if state["passed"]:
        return "done"
    if state["iteration"] >= 3:
        return "done"
    return "fix_issues"


def fix_issues(state: CodeReviewState) -> CodeReviewState:
    state["iteration"] += 1
    state["status"] = "fixing"
    return state


def mark_done(state: CodeReviewState) -> CodeReviewState:
    state["status"] = "passed" if state["passed"] else "failed"
    return state


def build_code_review_graph() -> StateGraph:
    builder = StateGraph(CodeReviewState)
    builder.add_node("lint", lint_code)
    builder.add_node("fix", fix_issues)
    builder.add_node("mark_done", mark_done)
    builder.set_entry_point("lint")
    builder.add_conditional_edges(
        "lint", decide_next,
        {"fix_issues": "fix", "done": "mark_done"},
    )
    builder.add_edge("fix", "lint")
    builder.add_edge("mark_done", END)
    return builder.compile()


def run_code_review(workspace: Path) -> CodeReviewState:
    graph = build_code_review_graph()
    initial_state: CodeReviewState = {
        "workspace": str(workspace),
        "code_files": [],
        "review_notes": "",
        "lint_output": "",
        "iteration": 0,
        "passed": False,
        "status": "reviewing",
    }
    return graph.invoke(initial_state)
